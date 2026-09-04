# -*- coding: utf-8 -*-
"""Ticket 02：ASR 画面证据与复核入口。

取帧时点、媒体复用与降级在模块边界测试；复核文件合同、非法纠正、
原子重渲染通过真实统一入口与复核入口（假外部命令）验证。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
REVIEW_ENTRY = MODULE_DIR / "scripts" / "review.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(MODULE_DIR / "scripts"))

from test_video_pipeline import ASR_FIXTURE, make_fakes, write_fixture  # noqa: E402


# ---------------------------------------------------------------- 取帧时点


def test_short_cue_gets_single_midpoint_frame():
    from omr.review import frame_positions

    assert frame_positions(0.0, 1.0) == [("p50", 0.5)]
    assert frame_positions(2.0, 6.0) == [("p50", 4.0)]


def test_four_second_boundary_is_midpoint_only():
    from omr.review import frame_positions

    assert frame_positions(1.0, 5.0) == [("p50", 3.0)]


def test_long_cue_gets_quarter_mid_and_three_quarter_frames():
    from omr.review import frame_positions

    assert frame_positions(0.0, 8.0) == [("p25", 2.0), ("p50", 4.0), ("p75", 6.0)]
    assert frame_positions(4.0, 9.0) == [("p25", 5.25), ("p50", 6.5), ("p75", 7.75)]


# ---------------------------------------------------------------- 证据准备


def asr_manifest(cues=None):
    from omr.model import ContentManifest, SubtitleCue, SubtitleTrack

    return ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="复核样本",
        duration=10,
        subtitle_tracks=[
            SubtitleTrack(
                language="asr",
                kind="asr",
                cues=cues
                or [
                    SubtitleCue(start=0.0, end=3.0, text="转写第一句。"),
                    SubtitleCue(start=4.0, end=9.0, text="转写第二句。"),
                ],
            )
        ],
        processing_path="语音转写（ASR）",
    )


def fake_frames(record):
    from omr.model import OMRError

    def extract(source, timestamp, dest):
        record.setdefault("sources", set()).add(str(source))
        record.setdefault("timestamps", []).append(round(timestamp, 3))
        dest.write_bytes(b"frame")

    return extract


def workspace_layout(tmp_path):
    run_dir = tmp_path / "run"
    workdir = run_dir / "work"
    workdir.mkdir(parents=True)
    artifacts = run_dir / "artifacts"
    return run_dir, workdir, artifacts


def test_media_sources_choose_one_review_url():
    from omr.model import MediaSources

    assert MediaSources(
        video="https://cdn/best",
        review_video="https://cdn/review",
        muxed="https://cdn/muxed",
    ).review_url == "https://cdn/review"
    assert MediaSources(muxed="https://cdn/muxed").review_url == "https://cdn/muxed"
    assert MediaSources(video="https://cdn/video").review_url == "https://cdn/video"


def test_prepare_writes_input_json_with_relative_frames(monkeypatch, tmp_path):
    from omr import review

    manifest = asr_manifest()
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda _url, dest, mode, cookies=None: dest.write_bytes(b"video"),
    )
    record = {}
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))

    review.prepare(manifest, run_dir, workdir, artifacts)

    payload = json.loads((run_dir / "review" / "input.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert [c["id"] for c in payload["cues"]] == [1, 2]
    assert payload["cues"][0]["original_text"] == "转写第一句。"
    assert payload["cues"][0]["frames"] == ["review/frames/cue-0001-p50.jpg"]
    assert payload["cues"][1]["frames"] == [
        "review/frames/cue-0002-p25.jpg",
        "review/frames/cue-0002-p50.jpg",
        "review/frames/cue-0002-p75.jpg",
    ]
    for cue in payload["cues"]:
        for frame in cue["frames"]:
            path = run_dir / frame
            assert path.is_file(), frame
            assert path.parent == run_dir / "review" / "frames"
    assert payload["content"]["title"] == "复核样本"
    assert payload["content"]["processing_path"] == "语音转写（ASR）"


def test_prepare_skips_empty_cues_in_stable_numbering(monkeypatch, tmp_path):
    from omr import review
    from omr.model import SubtitleCue

    manifest = asr_manifest(
        [
            SubtitleCue(start=0.0, end=1.0, text="有字。"),
            SubtitleCue(start=1.0, end=2.0, text="   "),
            SubtitleCue(start=2.0, end=3.0, text="也有字。"),
        ]
    )
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda _url, dest, mode, cookies=None: dest.write_bytes(b"video"),
    )
    monkeypatch.setattr(review.media, "extract_frame", fake_frames({}))

    review.prepare(manifest, run_dir, workdir, artifacts)

    payload = json.loads((run_dir / "review" / "input.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in payload["cues"]] == [1, 2]
    assert payload["cues"][1]["original_text"] == "也有字。"


def test_prepare_reuses_keep_media_artifact_without_new_download(monkeypatch, tmp_path):
    from omr import review

    manifest = asr_manifest()
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    keep = artifacts / "source.mp4"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"kept media")
    record = {}
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("应复用已保留媒体")),
    )
    monkeypatch.setattr(
        review.media,
        "download_direct",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("应复用已保留媒体")),
    )

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["sources"] == {str(keep)}
    assert keep.is_file()


def test_prepare_prefers_direct_muxed_stream(monkeypatch, tmp_path):
    from omr import review
    from omr.model import MediaSources

    manifest = asr_manifest()
    manifest.media_sources = MediaSources(
        muxed="https://cdn/muxed.mp4", referer="https://page"
    )
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    record = {}
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))
    monkeypatch.setattr(
        review.media,
        "download_direct",
        lambda url, dest, referer=None: (dest.write_bytes(b"muxed"), record.setdefault("urls", set()).add(url)),
    )
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("有直连合成流时不应使用下载器")),
    )

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["urls"] == {"https://cdn/muxed.mp4"}
    assert record["sources"] == {str(workdir / "review-source.mp4")}
    assert not (workdir / "review-source.mp4").exists(), "复核视频取帧后应删除"


@pytest.mark.parametrize(
    "video_urls,expected_url",
    [
        ({"video": "https://cdn/video.m4s"}, "https://cdn/video.m4s"),
        (
            {
                "video": "https://cdn/best-video.m4s",
                "review_video": "https://cdn/review-video.m4s",
            },
            "https://cdn/review-video.m4s",
        ),
    ],
    ids=["video-fallback", "review-video"],
)
def test_prepare_uses_resolved_direct_video_before_downloader(
    monkeypatch, tmp_path, video_urls, expected_url
):
    from omr import review
    from omr.model import MediaSources

    manifest = asr_manifest()
    manifest.media_sources = MediaSources(
        audio="https://cdn/audio.m4s",
        referer="https://www.bilibili.com/",
        **video_urls,
    )
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    record = {}

    def fake_direct(url, dest, referer=None):
        record["direct"] = (url, referer)
        dest.write_bytes(b"video")

    monkeypatch.setattr(review.media, "download_direct", fake_direct)
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("已有页面验证的直连视频时不应调用 yt-dlp")
        ),
    )

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["direct"] == (
        expected_url,
        "https://www.bilibili.com/",
    )
    assert record["sources"] == {str(workdir / "review-source.mp4")}
    assert not (workdir / "review-source.mp4").exists()


def test_prepare_downloads_minimal_video_when_only_audio(monkeypatch, tmp_path):
    from omr import review

    manifest = asr_manifest()
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    record = {}

    def fake_download(url, dest, mode, cookies=None):
        record["mode"] = mode
        dest.write_bytes(b"video")

    monkeypatch.setattr(review.media, "download_media", fake_download)
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["mode"] == "review"
    assert not (workdir / "review-source.mp4").exists(), "复核视频取帧后应删除"
    assert (run_dir / "review" / "frames" / "cue-0001-p50.jpg").is_file()


def test_prepare_reuses_transcription_media_when_it_contains_video(monkeypatch, tmp_path):
    from omr import review

    manifest = asr_manifest()
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    transcription_media = workdir / "source.m4a"
    transcription_media.write_bytes(b"muxed audio download")
    record = {}
    monkeypatch.setattr(review.media, "extract_frame", fake_frames(record))
    monkeypatch.setattr(
        review.media,
        "download_media",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("已有含视频媒体不应再下载")),
    )
    monkeypatch.setattr(
        review.media,
        "download_direct",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("已有含视频媒体不应再下载")),
    )

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["sources"] == {str(transcription_media)}
    assert transcription_media.is_file()
    assert not (workdir / "review" / "frames" / ".probe.jpg").exists()


def test_prepare_falls_back_to_review_download_for_audio_only_media(monkeypatch, tmp_path):
    from omr import review
    from omr.model import OMRError

    manifest = asr_manifest()
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    (workdir / "source.m4a").write_bytes(b"audio only")
    record = {}

    def extract_by_source(source, timestamp, dest):
        if Path(source).name == "source.m4a":
            dest.write_bytes(b"")
            raise OMRError("画面帧提取失败（0.0 秒）。")
        dest.write_bytes(b"frame")
        record.setdefault("sources", set()).add(str(source))

    def fake_download(url, dest, mode, cookies=None):
        record["mode"] = mode
        dest.write_bytes(b"video")

    monkeypatch.setattr(review.media, "download_media", fake_download)
    monkeypatch.setattr(review.media, "extract_frame", extract_by_source)

    review.prepare(manifest, run_dir, workdir, artifacts)

    assert record["mode"] == "review"
    assert record["sources"] == {str(workdir / "review-source.mp4")}
    assert (run_dir / "review" / "frames" / "cue-0001-p50.jpg").is_file()


def test_pipeline_marks_review_unavailable_when_evidence_incomplete(monkeypatch, tmp_path):
    from omr import pipeline
    from omr.model import OMRError

    manifest = asr_manifest()
    manifest.subtitle_tracks = []  # 无在线字幕，走真实 ASR 主路径
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    monkeypatch.setattr(
        pipeline.media,
        "download_media",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"video"),
    )
    monkeypatch.setattr(
        pipeline.media, "extract_audio", lambda _source, dest: dest.write_bytes(b"audio")
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda *_args, **_kwargs: [
            {"start": 0.0, "end": 3.0, "text": "转写第一句。"},
            {"start": 4.0, "end": 9.0, "text": "转写第二句。"},
        ],
    )

    def failing_frame(_source, _timestamp, dest):
        if "cue-0002" in str(dest):
            raise OMRError("画面帧提取失败（4.5s）。")
        dest.write_bytes(b"frame")

    monkeypatch.setattr(pipeline.media, "extract_frame", failing_frame)

    pipeline.process(manifest, workdir, artifacts)

    assert manifest.processing_path == "语音转写（ASR）"
    assert manifest.review.status == "unavailable"
    assert "画面帧提取失败" in manifest.review.reason
    assert not (run_dir / "review").exists(), "证据不完整时不得留下部分复核目录"


def test_pipeline_skips_review_when_first_track_is_not_asr(monkeypatch, tmp_path):
    from omr import pipeline

    manifest = asr_manifest()
    manifest.subtitle_tracks[0].kind = "manual"
    manifest.subtitle_tracks[0].language = "zh-CN"
    run_dir, workdir, artifacts = workspace_layout(tmp_path)
    monkeypatch.setattr(
        pipeline.media,
        "download_media",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"video"),
    )
    monkeypatch.setattr(
        pipeline.media, "extract_audio", lambda _source, dest: dest.write_bytes(b"audio")
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda *_args, **_kwargs: [{"start": 0.0, "end": 5.0, "text": "核验轨。"}],
    )
    monkeypatch.setattr(
        pipeline.media, "extract_frame", lambda *a: (_ for _ in ()).throw(AssertionError())
    )

    pipeline.process(manifest, workdir, artifacts, verify_audio=True)

    assert [track.kind for track in manifest.subtitle_tracks] == ["manual", "asr"]
    assert manifest.review.status == "not_required"
    assert not (run_dir / "review").exists()


# ---------------------------------------------------------------- 统一入口与复核入口


ASR_URL = "https://www.bilibili.com/video/BV1noSubs0"


def run_read(tmp_path, fixture, extra_args=None):
    """以假外部命令执行主读取入口，返回 (stdout payload, run_dir)。"""
    env = dict(os.environ)
    env["OMR_FIXTURE"] = str(fixture)
    bindir = make_fakes(tmp_path)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["OMR_WHISPER_BIN"] = str(bindir / "fake-whisper")
    env["OMR_OCR_BIN"] = str(bindir / "fake-ocr")
    env["OMR_CALLLOG"] = str(tmp_path / "calls.log")
    result = subprocess.run(
        [sys.executable, str(ENTRY), ASR_URL, *(extra_args or [])],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return payload, Path(payload["run_dir"])


def submit(run_dir, corrections, tmp_path):
    cpath = tmp_path / "submitted.json"
    cpath.write_text(json.dumps(corrections, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(REVIEW_ENTRY), str(run_dir), "--corrections", str(cpath)],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in ("OMR_FIXTURE", "OMR_WHISPER_BIN")},
        cwd=tmp_path,
    )


VALID_CORRECTIONS = {
    "reviewed_cue_ids": [1, 2],
    "corrections": [
        {
            "cue_id": 1,
            "text": "画面纠正第一句。",
            "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
        }
    ],
}


def prepared_review_submission(tmp_path, fixture_name):
    from omr.workspace import RunWorkspace

    fixture = write_fixture(tmp_path, fixture_name, ASR_FIXTURE)
    _, run_dir = run_read(tmp_path, fixture)
    cpath = tmp_path / "corr.json"
    cpath.write_text(json.dumps(VALID_CORRECTIONS, ensure_ascii=False), encoding="utf-8")
    return run_dir, RunWorkspace.load(run_dir), cpath


def test_cli_asr_run_generates_review_input_and_frames(tmp_path):
    payload, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_review.json", ASR_FIXTURE)
    )

    assert payload["review_required"] is True
    assert payload["review_path"] == str(run_dir / "review")
    assert payload["processing_path"] == "语音转写（ASR）"

    review_dir = run_dir / "review"
    input_payload = json.loads(
        (review_dir / "input.json").read_text(encoding="utf-8")
    )
    assert input_payload["version"] == 1
    assert [c["id"] for c in input_payload["cues"]] == [1, 2]
    assert input_payload["cues"][0]["frames"] == ["review/frames/cue-0001-p50.jpg"]
    assert input_payload["cues"][1]["frames"] == [
        "review/frames/cue-0002-p25.jpg",
        "review/frames/cue-0002-p50.jpg",
        "review/frames/cue-0002-p75.jpg",
    ]
    for cue in input_payload["cues"]:
        for frame in cue["frames"]:
            assert (run_dir / frame).is_file()
            assert (run_dir / frame).resolve().is_relative_to(review_dir.resolve())
    assert set(p.name for p in review_dir.iterdir()) == {"input.json", "frames"}
    assert not (run_dir / "work").exists(), "成功运行清理 work/，复核材料保留"

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_status"] == "pending"
    assert manifest["review_path"] == str(review_dir)

    text = (run_dir / "content.md").read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    assert "## 完整连续字幕" in text


def test_cli_reliable_subtitle_and_gallery_never_enter_review(tmp_path):
    subtitle_payload, subtitle_dir = run_read(
        tmp_path, FIXTURES / "bilibili_subtitle.json"
    )
    assert subtitle_payload["review_required"] is False
    assert "review_path" not in subtitle_payload
    assert not (subtitle_dir / "review").exists()
    assert not list(tmp_path.glob("*.mp4"))

    gallery_payload, gallery_dir = run_read(
        tmp_path, FIXTURES / "xiaohongshu_note.json"
    )
    assert gallery_payload["review_required"] is False
    assert not (gallery_dir / "review").exists()


def test_valid_correction_updates_both_transcripts_atomically(tmp_path):
    _, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_valid.json", ASR_FIXTURE)
    )
    before_input = (run_dir / "review" / "input.json").read_bytes()

    result = submit(run_dir, VALID_CORRECTIONS, tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    assert payload["review_status"] == "reviewed"
    assert payload["review_path"] == str(run_dir / "review")
    assert payload["processing_path"] == "语音转写（ASR）+ 画面字幕校对"
    assert payload["result_path"] == str(run_dir / "content.md")

    text = (run_dir / "content.md").read_text(encoding="utf-8")
    assert "## 完整连续字幕\n\n画面纠正第一句。转写第二句。\n\n" in text
    assert "- [00:00:00 → 00:00:03] 画面纠正第一句。" in text
    assert "转写第一句。" not in text

    assert (run_dir / "review" / "input.json").read_bytes() == before_input
    corrections = json.loads(
        (run_dir / "review" / "corrections.json").read_text(encoding="utf-8")
    )
    assert corrections == {
        "result": "reviewed",
        "reviewed_cue_ids": [1, 2],
        "corrections": VALID_CORRECTIONS["corrections"],
    }
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_status"] == "reviewed"
    assert manifest["processing_path"] == "语音转写（ASR）+ 画面字幕校对"
    assert not list(run_dir.rglob("*.part"))


def test_zero_corrections_records_no_usable_evidence_text(tmp_path):
    _, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_zero.json", ASR_FIXTURE)
    )
    before_content = (run_dir / "content.md").read_bytes()

    result = submit(
        run_dir,
        {"reviewed_cue_ids": [1, 2], "corrections": []},
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["review_status"] == "reviewed"
    assert payload["review_reason"] == "画面无可用校对文字"
    assert payload["processing_path"] == "语音转写（ASR）"
    assert (run_dir / "content.md").read_bytes() == before_content
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_status"] == "reviewed"
    assert manifest["review_reason"] == "画面无可用校对文字"


def test_unavailable_result_keeps_original_asr(tmp_path):
    _, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_unavail.json", ASR_FIXTURE)
    )
    before_content = (run_dir / "content.md").read_bytes()

    result = submit(
        run_dir,
        {"result": "unavailable", "reason": "当前环境无法查看本地图片"},
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["review_status"] == "unavailable"
    assert payload["review_path"] == str(run_dir / "review")
    assert payload["review_reason"] == "当前环境无法查看本地图片"
    assert (run_dir / "content.md").read_bytes() == before_content
    corrections = json.loads(
        (run_dir / "review" / "corrections.json").read_text(encoding="utf-8")
    )
    assert corrections == {
        "result": "unavailable",
        "reason": "当前环境无法查看本地图片",
    }
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_status"] == "unavailable"


def test_review_updates_explicit_output_as_only_body(tmp_path):
    output = tmp_path / "chosen.md"
    payload, run_dir = run_read(
        tmp_path,
        write_fixture(tmp_path, "asr_output.json", ASR_FIXTURE),
        extra_args=["--output", str(output)],
    )
    assert payload["result_path"] == str(output)

    result = submit(run_dir, VALID_CORRECTIONS, tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result_path"] == str(output)
    text = output.read_text(encoding="utf-8")
    assert "## 完整连续字幕\n\n画面纠正第一句。转写第二句。\n\n" in text
    assert not (run_dir / "content.md").exists()
    assert not list(tmp_path.glob("*.part"))


def test_second_submission_is_rejected(tmp_path):
    _, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_twice.json", ASR_FIXTURE)
    )
    assert submit(run_dir, VALID_CORRECTIONS, tmp_path).returncode == 0
    after_content = (run_dir / "content.md").read_bytes()
    after_corrections = (run_dir / "review" / "corrections.json").read_bytes()
    after_manifest = (run_dir / "manifest.json").read_bytes()

    result = submit(run_dir, VALID_CORRECTIONS, tmp_path)

    assert result.returncode != 0
    assert json.loads(result.stderr)["status"] == "error"
    assert (run_dir / "content.md").read_bytes() == after_content
    assert (run_dir / "review" / "corrections.json").read_bytes() == after_corrections
    assert (run_dir / "manifest.json").read_bytes() == after_manifest


def test_pending_review_reports_latest_failure(tmp_path):
    _, run_dir = run_read(
        tmp_path, write_fixture(tmp_path, "asr_latest_failure.json", ASR_FIXTURE)
    )

    first = submit(
        run_dir,
        {"reviewed_cue_ids": [1], "corrections": []},
        tmp_path,
    )
    second = submit(
        run_dir,
        {"result": "partial", "reviewed_cue_ids": [1, 2]},
        tmp_path,
    )

    first_payload = json.loads(first.stderr)
    second_payload = json.loads(second.stderr)
    assert first.returncode != 0
    assert second.returncode != 0
    assert "未知的复核结果" in second_payload["error"]
    assert second_payload["error"] != first_payload["error"]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_status"] == "pending"
    assert manifest["error"] == second_payload["error"]


def test_review_rejects_run_without_review_input(tmp_path):
    _, run_dir = run_read(
        tmp_path, FIXTURES / "bilibili_subtitle.json"
    )

    result = submit(run_dir, VALID_CORRECTIONS, tmp_path)

    assert result.returncode != 0
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert "复核" in payload["error"]
    assert not (run_dir / "review" / "corrections.json").exists()


def _rejection_case(name, corrections, mutate=None):
    return pytest.param(corrections, mutate, id=name)


def _bump_input_version(run_dir):
    path = run_dir / "review" / "input.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = payload["version"] + 1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    "corrections,mutate",
    [
        _rejection_case(
            "missing-cue", {"reviewed_cue_ids": [1], "corrections": []}
        ),
        _rejection_case(
            "unknown-cue", {"reviewed_cue_ids": [1, 2, 3], "corrections": []}
        ),
        _rejection_case(
            "duplicate-reviewed-cue", {"reviewed_cue_ids": [1, 1, 2], "corrections": []}
        ),
        _rejection_case(
            "unknown-correction-cue",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 3,
                        "text": "任意",
                        "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
                    }
                ],
            },
        ),
        _rejection_case(
            "duplicate-correction-cue",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "第一个",
                        "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
                    },
                    {
                        "cue_id": 1,
                        "text": "第二个",
                        "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
                    },
                ],
            },
        ),
        _rejection_case(
            "blank-replacement",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "   ",
                        "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
                    }
                ],
            },
        ),
        _rejection_case(
            "no-evidence-frame",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {"cue_id": 1, "text": "任意", "evidence_frames": []}
                ],
            },
        ),
        _rejection_case(
            "traversal-frame",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "任意",
                        "evidence_frames": ["review/frames/../../content.md"],
                    }
                ],
            },
        ),
        _rejection_case(
            "absolute-frame",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "任意",
                        "evidence_frames": ["/etc/passwd"],
                    }
                ],
            },
        ),
        _rejection_case(
            "cross-cue-evidence",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "任意",
                        "evidence_frames": ["review/frames/cue-0002-p25.jpg"],
                    }
                ],
            },
        ),
        _rejection_case(
            "missing-frame-file",
            {
                "reviewed_cue_ids": [1, 2],
                "corrections": [
                    {
                        "cue_id": 1,
                        "text": "任意",
                        "evidence_frames": ["review/frames/cue-0001-p50.jpg"],
                    }
                ],
            },
            lambda run_dir: (run_dir / "review" / "frames" / "cue-0001-p50.jpg").unlink(),
        ),
        _rejection_case(
            "unavailable-with-corrections",
            {
                "result": "unavailable",
                "reason": "无视觉",
                "corrections": VALID_CORRECTIONS["corrections"],
            },
        ),
        _rejection_case("unavailable-without-reason", {"result": "unavailable"}),
        _rejection_case(
            "unknown-result", {"result": "partial", "reviewed_cue_ids": [1, 2]}
        ),
        _rejection_case("not-an-object", ["corrections"]),
        _rejection_case(
            "incompatible-input-version",
            VALID_CORRECTIONS,
            lambda run_dir: _bump_input_version(run_dir),
        ),
    ],
)
def test_invalid_submissions_preserve_artifacts_and_report_failure(
    tmp_path, corrections, mutate
):
    fixture = write_fixture(tmp_path, "asr_reject.json", ASR_FIXTURE)
    _, run_dir = run_read(tmp_path, fixture)
    before_content = (run_dir / "content.md").read_bytes()
    if mutate is not None:
        mutate(run_dir)
    before_input = (run_dir / "review" / "input.json").read_bytes()

    result = submit(run_dir, corrections, tmp_path)

    assert result.returncode != 0, result.stdout
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["run_dir"] == str(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "error"
    assert manifest["stage"] == "reviewing"
    assert manifest["review_status"] == "pending"
    assert manifest["error"] == payload["error"]
    assert not (run_dir / "review" / "corrections.json").exists()
    assert (run_dir / "content.md").read_bytes() == before_content
    assert (run_dir / "review" / "input.json").read_bytes() == before_input
    assert not list(run_dir.rglob("*.part"))


def test_review_failure_keeps_body_and_leaves_no_part(monkeypatch, tmp_path):
    from omr import review as review_module
    from omr.workspace import RunWorkspace

    run_dir, workspace, cpath = prepared_review_submission(tmp_path, "asr_atomic.json")
    output = run_dir / "content.md"
    part = run_dir / "work" / "content.md.part"
    original_replace = Path.replace

    def fail_content_replace(path, target):
        if path.name == part.name:
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_content_replace)

    with pytest.raises(OSError, match="replace failed"):
        review_module.apply(workspace, cpath)

    assert "转写第一句。" in output.read_text(encoding="utf-8")
    assert not part.exists()
    assert (run_dir / "review" / "corrections.json").is_file()
    assert not list(run_dir.rglob("*.part"))

    monkeypatch.setattr(Path, "replace", original_replace)
    payload = review_module.apply(RunWorkspace.load(run_dir), cpath)

    assert payload["review_status"] == "reviewed"
    assert "画面纠正第一句。" in output.read_text(encoding="utf-8")


def test_corrections_write_failure_does_not_publish_reviewed_body(
    monkeypatch, tmp_path
):
    from omr import review as review_module
    from omr.workspace import RunWorkspace

    run_dir, workspace, cpath = prepared_review_submission(
        tmp_path, "asr_corrections_atomic.json"
    )
    before_content = (run_dir / "content.md").read_bytes()
    before_manifest = (run_dir / "manifest.json").read_bytes()
    original_write = review_module.write_json_atomic

    def fail_corrections(path, payload):
        if Path(path).name == "corrections.json":
            raise OSError("corrections write failed")
        return original_write(path, payload)

    monkeypatch.setattr(review_module, "write_json_atomic", fail_corrections)

    with pytest.raises(OSError, match="corrections write failed"):
        review_module.apply(workspace, cpath)

    assert (run_dir / "content.md").read_bytes() == before_content
    assert (run_dir / "manifest.json").read_bytes() == before_manifest
    assert not (run_dir / "review" / "corrections.json").exists()
    assert not list(run_dir.rglob("*.part"))


@pytest.mark.parametrize(
    "cleanup_error,expected_exit_code",
    [(OSError("cleanup failed"), 1), (KeyboardInterrupt(), 130)],
    ids=["io-error", "keyboard-interrupt"],
)
def test_review_cleanup_failure_remains_retryable(
    monkeypatch, tmp_path, capsys, cleanup_error, expected_exit_code
):
    import importlib.util

    from omr import review as review_module
    from omr import workspace as workspace_module
    from omr.workspace import RunWorkspace

    run_dir, workspace, cpath = prepared_review_submission(
        tmp_path, "asr_cleanup_retry.json"
    )
    original_rmtree = workspace_module.shutil.rmtree
    failed = False

    def fail_once(path):
        nonlocal failed
        if Path(path) == workspace.work_dir and not failed:
            failed = True
            raise cleanup_error
        return original_rmtree(path)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_once)

    spec = importlib.util.spec_from_file_location("omr_review_cleanup_test", REVIEW_ENTRY)
    review_entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review_entry)

    exit_code = review_entry.main([str(run_dir), "--corrections", str(cpath)])

    state = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(capsys.readouterr().err)
    assert exit_code == expected_exit_code
    assert state["status"] == "error"
    assert state["stage"] == "cleanup"
    assert state["review_status"] == "pending"
    assert payload["stage"] == "cleanup"
    assert payload["error"] == state["error"]

    completed = review_module.apply(RunWorkspace.load(run_dir), cpath)

    assert completed["review_status"] == "reviewed"
    assert not (run_dir / "work").exists()


def test_review_recovers_when_cleanup_state_cannot_be_persisted(
    monkeypatch, tmp_path, capsys
):
    import importlib.util

    from omr import workspace as workspace_module
    from omr.workspace import RunWorkspace

    run_dir, workspace, cpath = prepared_review_submission(
        tmp_path, "asr_cleanup_state_retry.json"
    )
    original_rmtree = workspace_module.shutil.rmtree
    cleanup_failed = False

    def interrupt_cleanup_once(path):
        nonlocal cleanup_failed
        if Path(path) == workspace.work_dir and not cleanup_failed:
            cleanup_failed = True
            raise KeyboardInterrupt
        return original_rmtree(path)

    original_write_manifest = RunWorkspace.write_manifest
    reject_cleanup_state = True

    def fail_cleanup_state_write(self, manifest=None):
        if reject_cleanup_state and self.stage == "cleanup":
            raise OSError("manifest unavailable")
        return original_write_manifest(self, manifest)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", interrupt_cleanup_once)
    monkeypatch.setattr(RunWorkspace, "write_manifest", fail_cleanup_state_write)

    spec = importlib.util.spec_from_file_location(
        "omr_review_cleanup_state_test", REVIEW_ENTRY
    )
    review_entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review_entry)

    first_exit = review_entry.main([str(run_dir), "--corrections", str(cpath)])
    first_payload = json.loads(capsys.readouterr().err)
    stale_state = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert first_exit == 130
    assert first_payload["stage"] == "cleanup"
    assert "工作目录清理失败：用户中断" in first_payload["error"]
    assert stale_state["status"] == "success"
    assert stale_state["review_status"] == "reviewed"

    reject_cleanup_state = False
    second_exit = review_entry.main([str(run_dir), "--corrections", str(cpath)])
    second_payload = json.loads(capsys.readouterr().out)

    assert second_exit == 0
    assert second_payload["review_status"] == "reviewed"
    assert not (run_dir / "work").exists()


def test_manifest_failure_can_retry_completed_review(monkeypatch, tmp_path, capsys):
    import importlib.util

    from omr import review as review_module
    from omr.model import OMRError
    from omr.workspace import RunWorkspace

    run_dir, workspace, cpath = prepared_review_submission(
        tmp_path, "asr_manifest_retry.json"
    )

    def fail_manifest(_manifest=None):
        raise OSError("final manifest failed")

    monkeypatch.setattr(workspace, "write_manifest", fail_manifest)

    with pytest.raises(OSError, match="final manifest failed") as failure:
        review_module.apply(workspace, cpath)

    pending = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert pending["review_status"] == "pending"
    assert (run_dir / "review" / "corrections.json").is_file()

    spec = importlib.util.spec_from_file_location("omr_review_entry_test", REVIEW_ENTRY)
    review_entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review_entry)
    review_entry._print_failure(failure.value, "reviewing", workspace=workspace)
    failure_payload = json.loads(capsys.readouterr().err)
    recorded = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert recorded["status"] == "error"
    assert recorded["stage"] == "reviewing"
    assert recorded["review_status"] == "pending"
    assert recorded["error"] == failure_payload["error"]

    unavailable_path = tmp_path / "unavailable.json"
    unavailable_path.write_text(
        json.dumps({"result": "unavailable", "reason": "改用未复核"}, ensure_ascii=False),
        encoding="utf-8",
    )
    before_retry = {
        "content": (run_dir / "content.md").read_bytes(),
        "corrections": (run_dir / "review" / "corrections.json").read_bytes(),
        "manifest": (run_dir / "manifest.json").read_bytes(),
    }

    with pytest.raises(OMRError, match="相同的纠正内容"):
        review_module.apply(RunWorkspace.load(run_dir), unavailable_path)

    assert (run_dir / "content.md").read_bytes() == before_retry["content"]
    assert (
        run_dir / "review" / "corrections.json"
    ).read_bytes() == before_retry["corrections"]
    assert (run_dir / "manifest.json").read_bytes() == before_retry["manifest"]

    payload = review_module.apply(RunWorkspace.load(run_dir), cpath)

    assert payload["review_status"] == "reviewed"
    assert payload["review_path"] == str(run_dir / "review")
    completed = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert completed["review_status"] == "reviewed"
    assert not list(run_dir.rglob("*.part"))
