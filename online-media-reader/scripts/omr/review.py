# -*- coding: utf-8 -*-
"""ASR 画面复核：提取证据帧、保存原始 cue、校验证据化纠正并重渲染。

复核只处理主入口生成的 review/input.json，不读取或局部改写 Markdown。
"""

import json
import shutil
from pathlib import Path

from . import media
from .model import ContentManifest, OMRError, ReviewState
from .render import render_markdown
from .workspace import write_json_atomic

REVIEW_INPUT_VERSION = 1

REVIEWED_PROCESSING_PATH = "语音转写（ASR）+ 画面字幕校对"
ZERO_CORRECTIONS_REASON = "画面无可用校对文字"


def frame_positions(start, end):
    """cue 的取帧时点：不超过 4 秒取中点；超过 4 秒取四分之一、中点和四分之三点。"""
    duration = end - start
    if duration <= 4:
        return [("p50", start + duration / 2)]
    return [
        ("p25", start + duration / 4),
        ("p50", start + duration / 2),
        ("p75", start + duration * 3 / 4),
    ]


def _numbered_non_empty_cues(track):
    """按稳定编号枚举第一主轨的非空 cue。"""
    cue_id = 0
    for cue in track.cues:
        if isinstance(cue.text, str) and cue.text.strip():
            cue_id += 1
            yield cue_id, cue


def _has_video_stream(source, frames_dir):
    """无 ffprobe 依赖的含视频探测：能否从该媒体提出一帧。"""
    probe = frames_dir / ".probe.jpg"
    try:
        media.extract_frame(source, 0.0, probe)
        return True
    except OMRError:
        return False
    finally:
        probe.unlink(missing_ok=True)


def _acquire_video_source(manifest, workdir, artifacts_dir, frames_dir):
    """优先复用已取得或保留的含视频媒体；只有音频时取得最小可用视频流。

    返回 (媒体路径, 是否为复核临时下载)；失败抛 OMRError 由调用方降级。
    """
    keep_copy = Path(artifacts_dir) / "source.mp4"
    if keep_copy.is_file():  # --keep-media 已验证的媒体直接复用
        return keep_copy, False
    transcription_media = Path(workdir) / "source.m4a"
    if transcription_media.is_file() and _has_video_stream(
        transcription_media, frames_dir
    ):
        # 转写下载回退到合成流时音频文件本身含视频，直接复用
        return transcription_media, False
    review_video = Path(workdir) / "review-source.mp4"
    sources = manifest.media_sources
    if sources.review_url:
        media.download_direct(sources.review_url, review_video, referer=sources.referer)
    else:
        media.download_media(
            manifest.canonical_url,
            review_video,
            mode="review",
            cookies=manifest.cookie_file,
        )
    return review_video, True


def prepare(manifest, run_dir, workdir, artifacts_dir):
    """为 ASR 主轨的全部非空 cue 生成证据帧和 review/input.json。

    成功后把 manifest 标记为待复核；证据不完整时清理复核目录并抛出
    OMRError，由调用方降级为复核不可用。
    """
    run_dir = Path(run_dir)
    review_dir = run_dir / "review"
    frames_dir = review_dir / "frames"
    source = None
    temporary = False
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        source, temporary = _acquire_video_source(
            manifest, workdir, artifacts_dir, frames_dir
        )
        cues_payload = []
        for cue_id, cue in _numbered_non_empty_cues(manifest.subtitle_tracks[0]):
            frames = []
            for label, timestamp in frame_positions(cue.start, cue.end):
                relative = f"review/frames/cue-{cue_id:04d}-{label}.jpg"
                media.extract_frame(source, timestamp, run_dir / relative)
                frames.append(relative)
            cues_payload.append(
                {
                    "id": cue_id,
                    "start": cue.start,
                    "end": cue.end,
                    "original_text": cue.text,
                    "frames": frames,
                }
            )
        write_json_atomic(
            review_dir / "input.json",
            {
                "version": REVIEW_INPUT_VERSION,
                "content": manifest.to_dict(),
                "cues": cues_payload,
            },
        )
    except BaseException:
        shutil.rmtree(review_dir, ignore_errors=True)
        raise
    finally:
        if temporary:
            source.unlink(missing_ok=True)
    manifest.review = ReviewState.pending(review_dir)
    return review_dir


# ---------------------------------------------------------------- 复核入口


def _load_input(run_dir):
    input_path = run_dir / "review" / "input.json"
    if not input_path.is_file():
        raise OMRError(
            "该运行目录没有画面复核输入（review/input.json 不存在）；"
            "只有 ASR 为主文字源且证据完整的运行才能复核。"
        )
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise OMRError("复核输入 review/input.json 不是有效 JSON。") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("cues"), list):
        raise OMRError("复核输入 review/input.json 结构不完整。")
    if payload.get("version") != REVIEW_INPUT_VERSION:
        raise OMRError(
            f"复核输入版本不兼容：期望 {REVIEW_INPUT_VERSION}，"
            f"收到 {payload.get('version')!r}。"
        )
    return payload


def _reject(message):
    raise OMRError(f"纠正项校验失败：{message}")


def _is_cue_id(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_unavailable(submitted):
    if "reviewed_cue_ids" in submitted or "corrections" in submitted:
        _reject("unavailable 结果不能附带 reviewed_cue_ids 或纠正项。")
    reason = submitted.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        _reject("unavailable 结果必须说明原因。")
    return {"result": "unavailable", "reason": reason.strip()}


def _validate_reviewed(submitted, payload, run_dir):
    cues = payload["cues"]
    registered = {cue["id"]: cue for cue in cues if _is_cue_id(cue.get("id"))}
    if "reviewed_cue_ids" not in submitted or "corrections" not in submitted:
        _reject("正常复核必须同时包含 reviewed_cue_ids 和 corrections。")
    reviewed = submitted["reviewed_cue_ids"]
    if not isinstance(reviewed, list) or not all(_is_cue_id(i) for i in reviewed):
        _reject("reviewed_cue_ids 必须是 cue 编号列表。")
    if len(set(reviewed)) != len(reviewed):
        _reject("reviewed_cue_ids 存在重复编号。")
    if set(reviewed) != set(registered):
        _reject(
            "reviewed_cue_ids 必须覆盖且仅覆盖 input.json 的全部 cue "
            f"（期望 {sorted(registered)}，收到 {sorted(set(reviewed))}）。"
        )
    corrections = submitted["corrections"]
    if not isinstance(corrections, list):
        _reject("corrections 必须是列表。")
    corrected = {}
    for item in corrections:
        if not isinstance(item, dict):
            _reject("每条纠正必须是对象。")
        cue_id = item.get("cue_id")
        if not _is_cue_id(cue_id) or cue_id not in registered:
            _reject(f"纠正引用了未知 cue 编号：{cue_id!r}。")
        if cue_id in corrected:
            _reject(f"cue {cue_id} 存在重复纠正。")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            _reject(f"cue {cue_id} 的替换文本不能为空。")
        frames = item.get("evidence_frames")
        if not isinstance(frames, list) or not frames:
            _reject(f"cue {cue_id} 必须提供至少一个证据帧。")
        for frame in frames:
            if not isinstance(frame, str) or not frame:
                _reject(f"cue {cue_id} 的证据帧路径无效。")
            if frame.startswith(("/", "\\")) or "\\" in frame or ".." in Path(frame).parts:
                _reject(f"cue {cue_id} 的证据帧路径越界：{frame}")
            if frame not in registered[cue_id]["frames"]:
                _reject(f"cue {cue_id} 的证据帧不属于该 cue：{frame}")
            if not (run_dir / frame).is_file():
                _reject(f"cue {cue_id} 的证据帧文件缺失：{frame}")
        corrected[cue_id] = {"cue_id": cue_id, "text": text, "evidence_frames": frames}
    return {
        "result": "reviewed",
        "reviewed_cue_ids": sorted(registered),
        "corrections": [corrected[cue_id] for cue_id in sorted(corrected)],
    }


def _apply_to_track(manifest, corrections):
    """按稳定编号把完整替换应用到第一轨的非空 cue。"""
    replacements = {item["cue_id"]: item["text"] for item in corrections}
    for cue_id, cue in _numbered_non_empty_cues(manifest.subtitle_tracks[0]):
        if cue_id in replacements:
            cue.text = replacements[cue_id]


def apply(workspace, corrections_path):
    """校验并应用结构化纠正，原子更新唯一正文；返回成功 payload。

    input.json 一经生成不被改写；任何校验失败都不动正文、原始输入和
    正式纠正文件。已验证纠正先于正文交付原子保存；任一步失败时持久化
    状态仍为 pending，允许以相同纠正内容幂等重试完成交付。
    """
    run_dir = workspace.run_dir
    corrections_path = Path(corrections_path)
    corrections_file = run_dir / "review" / "corrections.json"
    persisted = None
    if corrections_file.is_file() and not workspace.review.required:
        raise OMRError("该运行的画面复核已完成，不接受重复提交。")
    if corrections_file.is_file():
        try:
            persisted = json.loads(corrections_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OMRError(f"无法读取待恢复的纠正文件：{exc}") from None
    payload = _load_input(run_dir)
    try:
        submitted = json.loads(corrections_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OMRError(f"无法读取纠正文件：{exc}") from None
    if not isinstance(submitted, dict):
        _reject("纠正文件必须是一个 JSON 对象。")
    if submitted.get("result") == "unavailable":
        normalized = _validate_unavailable(submitted)
    elif "result" in submitted:
        _reject(f"未知的复核结果：{submitted['result']!r}（只接受 reviewed 或 unavailable）。")
    else:
        normalized = _validate_reviewed(submitted, payload, run_dir)
    if persisted is not None and normalized != persisted:
        raise OMRError("上次复核未完成终态写入；请使用相同的纠正内容重试。")

    manifest = ContentManifest.from_dict(payload["content"])
    review_path = run_dir / "review"
    rendered = None
    if normalized["result"] == "unavailable":
        manifest.review = ReviewState.unavailable(normalized["reason"], review_path)
    else:
        _apply_to_track(manifest, normalized["corrections"])
        reason = None
        if normalized["corrections"]:
            manifest.processing_path = REVIEWED_PROCESSING_PATH
        else:
            reason = ZERO_CORRECTIONS_REASON
        manifest.review = ReviewState.reviewed(review_path, reason)
        rendered = render_markdown(manifest)
    write_json_atomic(corrections_file, normalized)
    if rendered is not None:
        workspace.deliver(rendered)
    workspace.complete(manifest)
    return workspace.success_payload()
