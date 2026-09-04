# -*- coding: utf-8 -*-
"""默认 .media 运行目录、结构化交付、失败诊断和输出原子性。"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_video_pipeline import ASR_FIXTURE, make_fakes, write_fixture

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_default(tmp_path, url, fixture, extra_args=None, fakes=False, env_changes=None):
    env = dict(os.environ)
    env["OMR_FIXTURE"] = str(fixture)
    if fakes:
        bindir = make_fakes(tmp_path)
        env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
        env["OMR_WHISPER_BIN"] = str(bindir / "fake-whisper")
        env["OMR_OCR_BIN"] = str(bindir / "fake-ocr")
        env["OMR_CALLLOG"] = str(tmp_path / "calls.log")
    if env_changes:
        env.update(env_changes)
    return subprocess.run(
        [sys.executable, str(ENTRY), url, *(extra_args or [])],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )


def test_default_run_delivers_content_and_manifest_under_media(tmp_path):
    result = run_default(
        tmp_path,
        "https://www.bilibili.com/video/BV1sample00",
        FIXTURES / "bilibili_subtitle.json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    assert payload["stage"] == "complete"
    assert payload["processing_path"] == "人工字幕"
    run_dir = Path(payload["run_dir"])
    result_path = Path(payload["result_path"])
    assert run_dir.parent == tmp_path / ".media"
    assert re.fullmatch(r"bilibili-BV1sample00-\d{8}T\d{6}[+-]\d{4}(?:-\d+)?", run_dir.name)
    assert result_path == run_dir / "content.md"
    assert result_path.is_file()
    assert "第一句固定样本字幕。" in result_path.read_text(encoding="utf-8")
    assert not (run_dir / "work").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "input_url": "https://www.bilibili.com/video/BV1sample00",
        "canonical_url": "https://www.bilibili.com/video/BV1sample00",
        "platform": "bilibili",
        "content_id": "BV1sample00",
        "status": "success",
        "stage": "complete",
        "processing_path": "人工字幕",
        "review_status": "not_required",
        "result_path": str(result_path),
        "artifact_paths": [],
    }


def test_explicit_output_remains_the_only_body_file(tmp_path):
    output = tmp_path / "chosen.md"
    result = run_default(
        tmp_path,
        "https://www.bilibili.com/video/BV1sample00",
        FIXTURES / "bilibili_subtitle.json",
        extra_args=["--output", str(output)],
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    assert Path(payload["result_path"]) == output
    assert output.is_file()
    assert not (run_dir / "content.md").exists()
    assert not list(run_dir.rglob("*.md"))


def test_failure_keeps_work_and_reports_stage_without_cookie(tmp_path):
    cookie = tmp_path / "fixture-cookies.txt"
    cookie.write_text("secret", encoding="utf-8")
    fixture_data = dict(ASR_FIXTURE, cookie_file=str(cookie))
    fixture = write_fixture(tmp_path, "failure.json", fixture_data)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    result = run_default(
        tmp_path,
        "https://www.bilibili.com/video/BV1noSubs0",
        fixture,
        env_changes={"PATH": str(empty_bin)},
    )

    assert result.returncode == 3
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["stage"] == "processing"
    assert "yt-dlp" in payload["error"]
    run_dir = Path(payload["run_dir"])
    assert run_dir.is_dir()
    assert (run_dir / "work").is_dir()
    assert not (run_dir / "content.md").exists()
    assert not list(run_dir.rglob("*.part"))
    assert not list(run_dir.rglob("*cookies*"))
    assert not cookie.exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "error"
    assert manifest["stage"] == "processing"
    assert manifest["error"] == payload["error"]


def test_keep_media_uses_fixed_artifact_name(tmp_path):
    result = run_default(
        tmp_path,
        "https://www.bilibili.com/video/BV1sample00",
        FIXTURES / "bilibili_subtitle.json",
        extra_args=["--keep-media"],
        fakes=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    media_path = run_dir / "artifacts" / "source.mp4"
    assert media_path.is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_paths"] == [str(media_path)]


def test_keep_media_muxes_to_typed_work_file_before_publish(monkeypatch, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest, MediaSources

    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="t",
        media_sources=MediaSources(
            video="https://cdn/video",
            audio="https://cdn/audio",
            referer="https://page",
        ),
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    monkeypatch.setattr(
        pipeline.media,
        "download_direct",
        lambda _url, dest, **_kwargs: dest.write_bytes(b"stream"),
    )

    def fake_mux(_video, _audio, dest):
        assert dest == workdir / "source.mp4"
        dest.write_bytes(b"muxed")

    monkeypatch.setattr(pipeline.media, "mux_av", fake_mux)

    pipeline._download_keep_copy(manifest, artifacts, workdir)

    assert (artifacts / "source.mp4").read_bytes() == b"muxed"
    assert not (workdir / "source.mp4").exists()


def test_keyboard_interrupt_reports_json_and_removes_cookie(monkeypatch, capsys, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    import read as read_entry

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OMR_FIXTURE", raising=False)

    def interrupt_fetch(_platform, _url, workdir, probe_only=False):
        assert probe_only is False
        (workdir / "cookies.txt").write_text("secret", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(read_entry, "fetch_manifest", interrupt_fetch)

    result = read_entry.main(["https://www.bilibili.com/video/BV1interrupt"])

    assert result == 130
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "error"
    assert payload["stage"] == "fetching"
    assert payload["error"] == "用户中断"
    run_dir = Path(payload["run_dir"])
    assert not list(run_dir.rglob("*cookies*"))
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))[
        "status"
    ] == "error"


def test_explicit_output_part_is_removed_when_replace_fails(monkeypatch, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr.workspace import RunWorkspace

    output = tmp_path / "chosen.md"
    workspace = RunWorkspace.create(
        tmp_path,
        "bilibili",
        "https://www.bilibili.com/video/BV1replace0",
        output=output,
    )
    part = output.with_name("chosen.md.part")
    original_replace = Path.replace

    def fail_output_replace(path, target):
        if path == part:
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_output_replace)

    with pytest.raises(OSError, match="replace failed"):
        workspace.deliver("body")

    assert not output.exists()
    assert not part.exists()


def test_final_manifest_failure_preserves_work_diagnostics(monkeypatch, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr.model import ContentManifest
    from omr.workspace import RunWorkspace

    workspace = RunWorkspace.create(
        tmp_path,
        "bilibili",
        "https://www.bilibili.com/video/BV1manifest0",
    )
    diagnostic = workspace.work_dir / "download.trace"
    diagnostic.write_text("diagnostic", encoding="utf-8")
    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="https://www.bilibili.com/video/BV1manifest0",
        content_type="video",
        title="t",
    )
    original_write = workspace.write_manifest

    def fail_success_write(item=None):
        if workspace.status == "success":
            raise OSError("final manifest failed")
        return original_write(item)

    monkeypatch.setattr(workspace, "write_manifest", fail_success_write)

    with pytest.raises(OSError, match="final manifest failed"):
        workspace.complete(manifest)

    assert diagnostic.read_text(encoding="utf-8") == "diagnostic"


def test_work_cleanup_failure_records_error_manifest(monkeypatch, tmp_path, capsys):
    import importlib.util

    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import workspace as workspace_module
    from omr.model import ContentManifest, WorkspaceFinalizationError
    from omr.workspace import RunWorkspace

    workspace = RunWorkspace.create(
        tmp_path,
        "bilibili",
        "https://www.bilibili.com/video/BV1cleanup0",
    )
    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="https://www.bilibili.com/video/BV1cleanup0",
        content_type="video",
        title="t",
    )

    def fail_cleanup(_path):
        raise OSError("cleanup failed")

    monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_cleanup)

    with pytest.raises(WorkspaceFinalizationError, match="cleanup failed") as failure:
        workspace.complete(manifest)

    state = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert state["status"] == "error"
    assert state["stage"] == "cleanup"
    assert state["error"] == "工作目录清理失败：cleanup failed"

    spec = importlib.util.spec_from_file_location("omr_read_entry_test", ENTRY)
    read_entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(read_entry)
    read_entry._print_failure(
        failure.value, "delivering", workspace=workspace, manifest=manifest
    )

    payload = json.loads(capsys.readouterr().err)
    assert payload["stage"] == "cleanup"
    assert payload["error"] == "工作目录清理失败：cleanup failed"
    recorded = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert recorded["stage"] == "cleanup"


@pytest.mark.parametrize("source", ["muxed", "downloader", "separate"])
def test_keep_media_failure_never_publishes_partial_artifact(
    monkeypatch, tmp_path, source
):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import pipeline
    from omr.model import ContentManifest, MediaSources, OMRError

    media_sources = MediaSources()
    if source == "muxed":
        media_sources = MediaSources(
            muxed="https://cdn/muxed", referer="https://page"
        )
    elif source == "separate":
        media_sources = MediaSources(
            video="https://cdn/video",
            audio="https://cdn/audio",
            referer="https://page",
        )
    manifest = ContentManifest(
        platform="bilibili",
        original_url="u",
        canonical_url="u",
        content_type="video",
        title="t",
        media_sources=media_sources,
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    def failing_download(_url, dest, **_kwargs):
        dest.write_bytes(b"partial")
        (dest.parent / "source.f137.mp4.part").write_bytes(b"yt-dlp partial")
        raise OMRError("download failed")

    if source == "downloader":
        monkeypatch.setattr(pipeline.media, "download_media", failing_download)
    elif source == "muxed":
        monkeypatch.setattr(pipeline.media, "download_direct", failing_download)
    else:
        monkeypatch.setattr(
            pipeline.media,
            "download_direct",
            lambda _url, dest, **_kwargs: dest.write_bytes(b"stream"),
        )

        def failing_mux(_video, _audio, dest):
            dest.write_bytes(b"partial")
            raise OMRError("mux failed")

        monkeypatch.setattr(pipeline.media, "mux_av", failing_mux)

    with pytest.raises(OMRError):
        pipeline._download_keep_copy(manifest, artifacts, workdir)

    assert not (artifacts / "source.mp4").exists()
    assert not list(tmp_path.rglob("*.part"))
    assert manifest.media_items == []


def test_media_downloader_removes_yt_dlp_part_on_failure(monkeypatch, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import media
    from omr.model import OMRError

    dest = tmp_path / "source.m4a"
    monkeypatch.setattr(media, "require_binary", lambda *_args: None)

    def fail(argv, **_kwargs):
        (dest.parent / "source.f137.mp4.part").write_bytes(b"partial")
        (dest.parent / "source.f140.m4a.part-Frag1").write_bytes(b"fragment")
        (dest.parent / "source.ytdl").write_bytes(b"state")
        return subprocess.CompletedProcess(argv, 1, "", "download failed")

    monkeypatch.setattr(media.subprocess, "run", fail)

    with pytest.raises(OMRError, match="yt-dlp 下载失败"):
        media.download_media("https://example.test/video", dest, mode="audio")

    assert not [
        path
        for path in tmp_path.iterdir()
        if ".part" in path.name or path.suffix == ".ytdl"
    ]


def test_review_download_does_not_force_an_audio_stream(monkeypatch, tmp_path):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr import media

    dest = tmp_path / "review-source.mp4"
    observed = {}
    monkeypatch.setattr(media, "require_binary", lambda *_args: None)

    def succeed(argv, **_kwargs):
        observed["argv"] = argv
        dest.write_bytes(b"video")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(media.subprocess, "run", succeed)

    media.download_media("https://example.test/video", dest, mode="review")

    selector = observed["argv"][observed["argv"].index("-f") + 1]
    assert selector == "bv[height<=480]/b[height<=480]/wv/w"
    assert "+ba" not in selector
