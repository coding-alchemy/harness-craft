# -*- coding: utf-8 -*-
"""把内容清单渲染为标明来源的 Markdown。"""

import re


def _ts(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _default_processing_path(manifest):
    if manifest.processing_path:
        return manifest.processing_path
    if manifest.content_type == "image_gallery":
        return "图片 OCR"
    if manifest.subtitle_tracks:
        return manifest.subtitle_tracks[0].label()
    return "未获得文字（无字幕，未执行转写）"


def _display_title(title):
    candidate = title.strip()
    if len(candidate) % 2 == 0:
        half = len(candidate) // 2
        if half >= 4 and candidate[:half] == candidate[half:]:
            return candidate[:half].strip()
    separated = re.fullmatch(r"(.{4,}?)\s+\1", candidate, re.S)
    if separated:
        return separated.group(1).strip()
    return title


_ASCII_ALNUM = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _join_transcript_pieces(pieces):
    """按cue边界与内部换行共用的规则拼接：仅两侧均为 ASCII 字母或数字时插入空格。"""
    joined = ""
    for piece in pieces:
        if joined and joined[-1] in _ASCII_ALNUM and piece[0] in _ASCII_ALNUM:
            joined += " "
        joined += piece
    return joined


def _continuous_transcript(track):
    """主轨非空 cue 规范为单个段落；返回空串表示无可渲染文本。"""
    cue_texts = []
    for cue_text in (cue.text for cue in track.cues):
        if not isinstance(cue_text, str):
            continue
        pieces = [piece.strip() for piece in cue_text.splitlines()]
        text = _join_transcript_pieces([piece for piece in pieces if piece])
        if text:
            cue_texts.append(text)
    return _join_transcript_pieces(cue_texts)


def render_markdown(manifest):
    lines = [f"# {_display_title(manifest.title)}", ""]
    lines += [
        f"- 平台：{manifest.platform}",
        f"- 内容类型：{manifest.content_type}",
        f"- 原始 URL：{manifest.original_url}",
        f"- 规范 URL：{manifest.canonical_url}",
    ]
    if manifest.author:
        lines.append(f"- 作者：{manifest.author}")
    if manifest.published_at:
        lines.append(f"- 发布时间：{manifest.published_at}")
    if manifest.duration:
        lines.append(f"- 时长：{int(manifest.duration)} 秒")
    lines.append(f"- 处理路径：{_default_processing_path(manifest)}")
    lines.append("")

    probe_labels = {"inaccessible": "不可访问", "invalid": "无效"}
    probe_label = probe_labels.get(manifest.subtitle_probe.status)
    if probe_label and manifest.subtitle_probe.reason:
        lines.append(
            f"> 在线字幕探测{probe_label}：{manifest.subtitle_probe.reason}"
        )
        lines.append("")

    tracks = manifest.subtitle_tracks
    if manifest.content_type == "video" and tracks:
        paragraph = _continuous_transcript(tracks[0])
        if paragraph:
            lines.append("## 完整连续字幕")
            lines.append("")
            lines.append(paragraph)
            lines.append("")
    for i, track in enumerate(tracks):
        heading = track.label()
        if tracks and tracks[0].kind == "asr" and i > 0:
            heading = f"原在线{track.label()}（可能不完整）"
        lines.append(f"## {heading}（{track.language}）")
        lines.append("")
        for cue in track.cues:
            if not isinstance(cue.text, str) or not cue.text.strip():
                continue
            lines.append(f"- [{_ts(cue.start)} → {_ts(cue.end)}] {cue.text}")
        lines.append("")

    if len(tracks) > 1 and any(t.kind == "asr" for t in tracks):
        lines.append("> 在线字幕与转写结果可能存在实质差异，请人工核对。")
        lines.append("")

    if manifest.image_items:
        lines.append("## 图片 OCR（按页面顺序）")
        lines.append("")
        for image in manifest.image_items:
            text = image.ocr_text if image.ocr_text else "未识别到文字"
            lines.append(f"### 第 {image.index} 张")
            lines.append("")
            lines.append(text)
            lines.append("")

    if manifest.summary:
        lines.append("## 平台摘要（补充信息，非正文）")
        lines.append("")
        lines.append(manifest.summary)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
