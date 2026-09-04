# -*- coding: utf-8 -*-
"""Ticket 02：通过统一入口验证字幕优先、按需下载转写、--keep-media 与依赖检查。

外部命令边界用假可执行文件替换（临时 PATH），调用记录写入临时日志；
测试不访问真实网络，不产生仓库内残留。
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
import types
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

FAKE_YTDLP = """#!/bin/sh
printf 'yt-dlp %s\\n' "$*" >> "$OMR_CALLLOG"
printf 'media' > "$4"
"""

FAKE_FFMPEG = """#!/bin/sh
printf 'ffmpeg %s\\n' "$*" >> "$OMR_CALLLOG"
for _last in "$@"; do :; done
printf 'media' > "$_last"
"""

FAKE_OCR = """#!/bin/sh
printf 'ocr %s\\n' "$*" >> "$OMR_CALLLOG"
text=$(cat "$1")
printf '{"text": "%s"}' "$text"
"""

FAKE_WHISPER = """#!/bin/sh
printf 'whisper %s\\n' "$*" >> "$OMR_CALLLOG"
cat <<'JSON'
[{"start": 0.0, "end": 3.0, "text": "转写第一句。"},
 {"start": 4.0, "end": 9.0, "text": "转写第二句。"}]
JSON
"""

ASR_FIXTURE = {
    "platform": "bilibili",
    "original_url": "https://www.bilibili.com/video/BV1noSubs0",
    "canonical_url": "https://www.bilibili.com/video/BV1noSubs0",
    "content_type": "video",
    "title": "固定样本：无字幕视频",
    "author": "示例UP主",
    "published_at": "2026-08-05",
    "duration": 10,
    "subtitle_tracks": [],
    "media_items": [],
    "image_items": [],
    "summary": None,
}

INCOMPLETE_FIXTURE = {
    "platform": "bilibili",
    "original_url": "https://www.bilibili.com/video/BV1partial0",
    "canonical_url": "https://www.bilibili.com/video/BV1partial0",
    "content_type": "video",
    "title": "固定样本：不完整字幕视频",
    "author": "示例UP主",
    "published_at": "2026-08-06",
    "duration": 60,
    "subtitle_tracks": [
        {
            "language": "zh-CN",
            "kind": "auto",
            "cues": [{"start": 0.0, "end": 6.0, "text": "仅有的少量自动字幕。"}],
        }
    ],
    "media_items": [],
    "image_items": [],
    "summary": None,
}


def write_fixture(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def make_fakes(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in [
        ("yt-dlp", FAKE_YTDLP),
        ("ffmpeg", FAKE_FFMPEG),
        ("fake-whisper", FAKE_WHISPER),
        ("fake-ocr", FAKE_OCR),
    ]:
        script = bindir / name
        script.write_text(textwrap.dedent(body), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bindir


def run_entry(url, output, tmp_path, fixture=None, extra_args=None, fakes=True, calllog=None):
    env = dict(os.environ)
    env.pop("OMR_FIXTURE", None)
    env.pop("OMR_WHISPER_BIN", None)
    env.pop("OMR_OCR_BIN", None)
    if fixture is not None:
        env["OMR_FIXTURE"] = fixture
    if fakes:
        bindir = make_fakes(tmp_path)
        env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
        env["OMR_WHISPER_BIN"] = str(bindir / "fake-whisper")
        env["OMR_OCR_BIN"] = str(bindir / "fake-ocr")
        log = calllog or (tmp_path / "calls.log")
        env["OMR_CALLLOG"] = str(log)
    return subprocess.run(
        [sys.executable, str(ENTRY), url, "--output", str(output)] + (extra_args or []),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )


def calls(tmp_path):
    log = tmp_path / "calls.log"
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def test_reliable_subtitle_used_without_download(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        tmp_path,
        fixture=str(FIXTURES / "bilibili_subtitle.json"),
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "人工字幕" in text
    assert "处理路径：人工字幕" in text
    assert calls(tmp_path) == []
    assert list(tmp_path.glob("*.mp4")) == list(tmp_path.glob("*.m4a")) == []


def test_missing_subtitle_triggers_asr(tmp_path):
    fixture = write_fixture(tmp_path, "no_subs.json", ASR_FIXTURE)
    out = tmp_path / "out.md"
    result = run_entry("https://www.bilibili.com/video/BV1noSubs0", out, tmp_path, fixture=fixture)
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "语音转写（ASR）" in text
    assert "处理路径：语音转写（ASR）" in text
    assert "转写第一句。" in text
    assert "00:00:04" in text
    invoked = calls(tmp_path)
    assert any(c.startswith("yt-dlp") for c in invoked)
    assert any(c.startswith("whisper") for c in invoked)
    # 无 --keep-media：不残留媒体
    assert list(tmp_path.glob("*.mp4")) == []


def test_asr_renders_continuous_and_timed_transcripts(tmp_path):
    fixture = write_fixture(tmp_path, "no_subs_cont.json", ASR_FIXTURE)
    out = tmp_path / "out.md"
    result = run_entry("https://www.bilibili.com/video/BV1noSubs0", out, tmp_path, fixture=fixture)
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "## 完整连续字幕\n\n转写第一句。转写第二句。\n\n" in text
    assert "- [00:00:04 → 00:00:09] 转写第二句。" in text


def test_verify_audio_renders_single_continuous_transcript_from_first_track(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        tmp_path,
        fixture=str(FIXTURES / "bilibili_subtitle.json"),
        extra_args=["--verify-audio"],
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert text.count("## 完整连续字幕") == 1
    assert "## 完整连续字幕\n\n第一句固定样本字幕。第二句固定样本字幕。\n\n" in text


def test_incomplete_subtitle_lists_original_and_warns(tmp_path):
    fixture = write_fixture(tmp_path, "partial.json", INCOMPLETE_FIXTURE)
    out = tmp_path / "out.md"
    result = run_entry("https://www.bilibili.com/video/BV1partial0", out, tmp_path, fixture=fixture)
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    assert "自动字幕" in text
    assert "仅有的少量自动字幕。" in text
    assert "人工核对" in text
    # ASR 为主要正文（在前），原字幕单列在后
    assert text.index("转写第一句。") < text.index("仅有的少量自动字幕。")


def test_keep_media_downloads_without_asr(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        tmp_path,
        fixture=str(FIXTURES / "bilibili_subtitle.json"),
        extra_args=["--keep-media"],
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：人工字幕" in text
    assert "ASR" not in text
    invoked = calls(tmp_path)
    assert any(c.startswith("yt-dlp") for c in invoked)
    assert not any(c.startswith("whisper") for c in invoked)
    run_dir = Path(json.loads(result.stdout)["run_dir"])
    assert (run_dir / "artifacts" / "source.mp4").is_file()


def test_verify_audio_transcribes_reliable_subtitle_without_keeping_media(tmp_path):
    out = tmp_path / "out.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        tmp_path,
        fixture=str(FIXTURES / "bilibili_subtitle.json"),
        extra_args=["--verify-audio"],
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：人工字幕 + 原音核验（ASR）" in text
    assert text.index("第一句固定样本字幕。") < text.index("转写第一句。")
    assert "在线字幕与转写结果可能存在实质差异" in text
    invoked = calls(tmp_path)
    assert any(c.startswith("yt-dlp") for c in invoked)
    assert any(c.startswith("whisper") for c in invoked)
    assert not [p for p in tmp_path.iterdir() if p.suffix in (".mp4", ".m4a", ".wav")]


def test_verify_audio_keeps_reliable_subtitle_when_asr_is_empty(monkeypatch, tmp_path):
    import sys as _sys

    _sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest, SubtitleCue, SubtitleTrack

    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="t",
        duration=10,
        subtitle_tracks=[
            SubtitleTrack(
                language="zh-CN",
                kind="manual",
                cues=[SubtitleCue(start=0, end=10, text="可靠字幕")],
            )
        ],
    )
    monkeypatch.setattr(
        pipeline.media, "download_media", lambda u, d, mode, cookies=None: d.write_bytes(b"x")
    )
    monkeypatch.setattr(pipeline.media, "extract_audio", lambda a, b: b.write_bytes(b"x"))
    monkeypatch.setattr(pipeline.media, "transcribe_audio", lambda a, m, **kwargs: [])

    pipeline.process(manifest, tmp_path, tmp_path / "artifacts", verify_audio=True)

    assert [track.kind for track in manifest.subtitle_tracks] == ["manual"]
    assert manifest.processing_path == "人工字幕（原音核验无结果）"


def test_keep_media_saves_media_even_with_unreliable_subtitle(tmp_path):
    fixture = write_fixture(tmp_path, "partial_keep.json", dict(INCOMPLETE_FIXTURE, cookie_file=None))
    out = tmp_path / "keep.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1partial0",
        out,
        tmp_path,
        fixture=fixture,
        extra_args=["--keep-media"],
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "处理路径：语音转写（ASR）" in text
    run_dir = Path(json.loads(result.stdout)["run_dir"])
    assert (run_dir / "artifacts" / "source.mp4").is_file()


def test_cookie_file_deleted_after_media_located(monkeypatch, tmp_path):
    import sys as _sys

    _sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    manifest = ContentManifest(
        platform="douyin",
        original_url="u", canonical_url="u", content_type="video",
        title="t", duration=60, cookie_file=str(cookie),
    )
    saved = {}

    def fake_download(url, dest, mode, cookies=None):
        saved["cookies"] = cookies
        dest.write_bytes(b"x")

    monkeypatch.setattr(pipeline.media, "download_media", fake_download)
    monkeypatch.setattr(
        pipeline.media, "extract_audio", lambda a, b: b.write_bytes(b"x")
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda a, m, **kwargs: [{"start": 0.0, "end": 5.0, "text": "转写句。"}],
    )
    monkeypatch.setattr(
        pipeline.media, "extract_frame", lambda *_args: _args[2].write_bytes(b"frame")
    )
    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")
    assert saved["cookies"] == str(cookie), "yt-dlp 应收到匿名 Cookie"
    assert not cookie.exists(), "媒体定位完成后 Cookie 应尽早删除"
    assert manifest.cookie_file is None


def test_douyin_media_branch_creates_cookie_on_demand(monkeypatch, tmp_path):
    import sys as _sys

    _sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest

    cookie = tmp_path / "cookies.txt"
    manifest = ContentManifest(
        platform="douyin",
        original_url="u",
        canonical_url="https://www.douyin.com/video/1",
        content_type="video",
        title="t",
        duration=10,
    )
    used = {}

    def fake_cookie_jar(url, workdir):
        used["cookie_url"] = url
        cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        return cookie

    def fake_download(url, dest, mode, cookies=None):
        used["download_cookie"] = cookies
        dest.write_bytes(b"x")

    monkeypatch.setattr(pipeline.browser_session, "anonymous_cookie_jar", fake_cookie_jar)
    monkeypatch.setattr(pipeline.media, "download_media", fake_download)
    monkeypatch.setattr(pipeline.media, "extract_audio", lambda a, b: b.write_bytes(b"x"))
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda a, m, **kwargs: [{"start": 0.0, "end": 5.0, "text": "转写句。"}],
    )

    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")

    assert used == {
        "cookie_url": manifest.canonical_url,
        "download_cookie": str(cookie),
    }
    assert not cookie.exists()


def test_douyin_direct_media_does_not_require_browser(monkeypatch, tmp_path):
    import sys as _sys

    _sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest, MediaSources

    manifest = ContentManifest(
        platform="douyin",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="直连媒体",
        media_sources=MediaSources(
            audio="https://cdn/audio.mp4",
            muxed="https://cdn/video.mp4",
            referer="https://www.douyin.com/",
        ),
    )
    monkeypatch.setattr(
        pipeline.browser_session,
        "anonymous_cookie_jar",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("已有直连媒体时不应启动浏览器")
        ),
    )
    monkeypatch.setattr(
        pipeline.media,
        "download_direct",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"media"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "extract_audio",
        lambda _source, dest: dest.write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda *_args, **_kwargs: [{"start": 0, "end": 1, "text": "正文"}],
    )

    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")

    assert manifest.processing_path == "语音转写（ASR）"


def test_blank_asr_segments_are_treated_as_no_result(monkeypatch, tmp_path):
    import sys as _sys

    _sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest

    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="空白转写",
    )
    monkeypatch.setattr(
        pipeline.media,
        "download_media",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"media"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "extract_audio",
        lambda _source, dest: dest.write_bytes(b"audio"),
    )
    monkeypatch.setattr(
        pipeline.media,
        "transcribe_audio",
        lambda *_args, **_kwargs: [{"start": 0, "end": 1, "text": "   "}],
    )

    pipeline.process(manifest, tmp_path, tmp_path / "artifacts")

    assert manifest.subtitle_tracks == []
    assert manifest.processing_path == "未获得文字（转写无结果）"
    assert manifest.cookie_file is None


def test_missing_dependency_fails_only_when_needed(tmp_path):
    out = tmp_path / "out.md"
    # 字幕可靠：无下载依赖也应成功
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        tmp_path,
        fixture=str(FIXTURES / "bilibili_subtitle.json"),
        fakes=False,
    )
    assert result.returncode == 0, result.stderr
    # 需要下载但 PATH 中没有 yt-dlp：明确失败并指出缺失能力
    fixture = write_fixture(tmp_path, "no_subs2.json", ASR_FIXTURE)
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    out2 = tmp_path / "out2.md"
    env_clean = dict(os.environ)
    env_clean["PATH"] = str(empty_bin)
    env_clean["OMR_FIXTURE"] = fixture
    env_clean.pop("OMR_WHISPER_BIN", None)
    result = subprocess.run(
        [sys.executable, str(ENTRY), "https://www.bilibili.com/video/BV1noSubs0",
         "--output", str(out2)],
        capture_output=True, text=True, env=env_clean, cwd=tmp_path,
    )
    assert result.returncode == 3
    assert "yt-dlp" in result.stderr
    assert not out2.exists()


def test_chinese_asr_receives_language_and_page_context(tmp_path):
    fixture = write_fixture(tmp_path, "zh-context.json", ASR_FIXTURE)
    out = tmp_path / "out.md"

    result = run_entry(
        "https://www.bilibili.com/video/BV1noSubs0",
        out,
        tmp_path,
        fixture=fixture,
    )

    assert result.returncode == 0, result.stderr
    whisper = next(c for c in calls(tmp_path) if c.startswith("whisper"))
    assert "--language zh" in whisper
    assert "--initial-prompt" in whisper
    assert "固定样本：无字幕视频" in whisper
    assert "示例UP主" in whisper
    assert "--download-root" in whisper
    assert str(tmp_path / ".media" / "tools" / "faster-whisper") in whisper


def test_whisper_dependency_check_does_not_require_downloader(monkeypatch):
    from omr import media

    monkeypatch.setattr(media.shutil, "which", lambda _name: None)
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace())
    media.require_transcribe_deps()


def test_whisper_runner_forwards_language_and_prompt(monkeypatch, capsys, tmp_path):
    from omr import whisper_runner

    received = {}

    class Segment:
        start = 0
        end = 1
        text = "舆情"

    class FakeModel:
        def __init__(self, model_name, download_root=None):
            received["model"] = model_name
            received["download_root"] = download_root

        def transcribe(self, audio_path, **kwargs):
            received["audio"] = audio_path
            received.update(kwargs)
            return [Segment()], None

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeModel),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "whisper-runner",
            "audio.wav",
            "small",
            "--download-root",
            str(tmp_path / ".media" / "tools" / "faster-whisper"),
            "--language",
            "zh",
            "--initial-prompt",
            "标题：舆情监测；作者：书醒时刻",
        ],
    )

    whisper_runner.main()

    assert received == {
        "model": "small",
        "download_root": str(tmp_path / ".media" / "tools" / "faster-whisper"),
        "audio": "audio.wav",
        "language": "zh",
        "initial_prompt": "标题：舆情监测；作者：书醒时刻",
    }
    assert json.loads(capsys.readouterr().out)[0]["text"] == "舆情"
