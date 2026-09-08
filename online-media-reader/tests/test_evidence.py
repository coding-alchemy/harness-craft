# -*- coding: utf-8 -*-
"""gallery-and-durable-evidence ticket 01：持久证据发布与输出位置门禁。

证据随运行目录持久保存（evidence/index.json 与快照/原图），成功清理 work/
后仍可回查；普通运行与显式输出拒绝系统临时根（含符号链接与真实临时目录）。
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
ENTRY = MODULE_DIR / "scripts" / "read.py"
REVIEW_ENTRY = MODULE_DIR / "scripts" / "review.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(MODULE_DIR / "tests"))

from test_video_pipeline import ASR_FIXTURE, make_fakes, run_entry, write_fixture  # noqa: E402
from test_xiaohongshu import gallery_fixture  # noqa: E402

RELIABLE_FIXTURE = FIXTURES / "bilibili_subtitle.json"

EMPTY_WHISPER = """#!/bin/sh
printf 'whisper %s\\n' "$*" >> "$OMR_CALLLOG"
printf '[]'
"""


def run_default(url, work_root, fixture=None, fake_whisper=None):
    """默认路径运行（不传 --output）；假命令桩齐全，可替换 whisper 输出。"""
    env = dict(os.environ)
    env.pop("OMR_FIXTURE", None)
    env.pop("OMR_WHISPER_BIN", None)
    env.pop("OMR_OCR_BIN", None)
    env.pop("OMR_CALLLOG", None)
    if fixture is not None:
        env["OMR_FIXTURE"] = fixture
    bindir = make_fakes(work_root)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["OMR_OCR_BIN"] = str(bindir / "fake-ocr")
    env["OMR_CALLLOG"] = str(work_root / "calls.log")
    if fake_whisper is not None:
        bindir_empty = work_root / "bin-empty"
        bindir_empty.mkdir(exist_ok=True)
        script = bindir_empty / "fake-whisper"
        script.write_text(textwrap.dedent(fake_whisper), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        env["OMR_WHISPER_BIN"] = str(script)
    else:
        env["OMR_WHISPER_BIN"] = str(bindir / "fake-whisper")
    return subprocess.run(
        [sys.executable, str(ENTRY), url],
        capture_output=True, text=True, env=env, cwd=work_root,
    )


def _payload(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _reliable_fixture(work_root):
    return write_fixture(work_root, "reliable.json", json.loads(
        RELIABLE_FIXTURE.read_text(encoding="utf-8")))


def test_video_run_publishes_cue_snapshot_and_index(work_root):
    result = run_default(
        "https://www.bilibili.com/video/BV1sample00",
        work_root, fixture=_reliable_fixture(work_root),
    )
    payload = _payload(result)
    run_dir = Path(payload["run_dir"])

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_path"] == "evidence/index.json"

    index = json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))
    assert index["version"] == 1
    assert index["result_path"] == "content.md"
    assert [e["kind"] for e in index["entries"]] == ["subtitle"]
    assert index["entries"][0]["path"] == "evidence/subtitle-cues.json"

    snapshot = json.loads(
        (run_dir / "evidence" / "subtitle-cues.json").read_text(encoding="utf-8")
    )
    assert set(snapshot) == {"track", "cues"}
    assert snapshot["track"]["language"] == "zh-CN"
    assert set(snapshot["cues"][0]) == {"start", "end", "text"}

    content = (run_dir / "content.md").read_text(encoding="utf-8")
    assert "- 证据索引：evidence/index.json" in content
    assert content.index("- 证据索引：") < content.index("## 原始字幕")

    assert not (run_dir / "work").exists()
    assert (run_dir / "evidence" / "index.json").is_file()


def test_gallery_run_publishes_original_images_and_ocr_snapshot(work_root):
    fixture = write_fixture(work_root, "gallery.json", gallery_fixture(work_root))
    result = run_default(
        "https://www.xiaohongshu.com/explore/65galler000000000000gal0",
        work_root, fixture=fixture,
    )
    payload = _payload(result)
    run_dir = Path(payload["run_dir"])

    index = json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))
    image_entries = [e for e in index["entries"] if e["kind"] == "ocr"]
    assert [e["image_index"] for e in image_entries] == [1, 2]
    images_dir = run_dir / "evidence" / "images"
    assert sorted(p.name for p in images_dir.iterdir()) == ["001.txt", "002.txt"]
    assert (images_dir / "001.txt").read_text(encoding="utf-8") == "第一张图片 中英文 OCR 文本"

    snapshot = json.loads(
        (run_dir / "evidence" / "ocr-snapshot.json").read_text(encoding="utf-8")
    )
    assert [img["index"] for img in snapshot["images"]] == [1, 2]
    assert snapshot["images"][0]["ocr_text"] == "第一张图片 中英文 OCR 文本"
    assert snapshot["images"][1]["ocr_text"] == ""
    assert set(snapshot["images"][0]) == {"index", "url", "ocr_text"}

    content = (run_dir / "content.md").read_text(encoding="utf-8")
    assert "- 证据索引：evidence/index.json" in content
    assert "未识别到文字" in content


def test_no_transcript_run_publishes_minimal_index(work_root):
    result = run_default(
        "https://www.bilibili.com/video/BV1noSubs0",
        work_root,
        fixture=write_fixture(work_root, "asr.json", ASR_FIXTURE),
        fake_whisper=EMPTY_WHISPER,
    )
    payload = _payload(result)
    assert payload["processing_path"] == "未获得文字（转写无结果）"
    run_dir = Path(payload["run_dir"])

    index = json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))
    assert index["result_path"] == "content.md"
    assert index["entries"] == []
    assert not (run_dir / "evidence" / "subtitle-cues.json").exists()
    content = (run_dir / "content.md").read_text(encoding="utf-8")
    assert content.count("- 证据索引：evidence/index.json") == 1


def test_asr_run_references_review_instead_of_duplicate_snapshot(work_root):
    result = run_default(
        "https://www.bilibili.com/video/BV1noSubs0",
        work_root,
        fixture=write_fixture(work_root, "asr.json", ASR_FIXTURE),
    )
    payload = _payload(result)
    assert payload["review_required"] is True
    run_dir = Path(payload["run_dir"])

    index = json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))
    kinds = {e["kind"] for e in index["entries"]}
    assert kinds == {"review"}
    assert index["entries"][0]["path"] == "review/input.json"
    assert not (run_dir / "evidence" / "subtitle-cues.json").exists()


def test_explicit_output_links_evidence_by_actual_location(work_root):
    out = work_root / "explicit" / "report.md"
    result = run_entry(
        "https://www.bilibili.com/video/BV1sample00",
        out,
        work_root,
        fixture=_reliable_fixture(work_root),
        fakes=False,
    )
    payload = _payload(result)
    run_dir = Path(payload["run_dir"])
    content = out.read_text(encoding="utf-8")
    line = next(l for l in content.splitlines() if l.startswith("- 证据索引："))
    link = line.split("：", 1)[1].strip()
    assert not os.path.isabs(link)
    assert (out.parent / link).resolve() == (run_dir / "evidence" / "index.json").resolve()
    assert not (run_dir / "content.md").exists()
    index = json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))
    assert index["result_path"] == str(out)


def test_review_rerender_keeps_evidence_entry(work_root):
    result = run_default(
        "https://www.bilibili.com/video/BV1noSubs0",
        work_root,
        fixture=write_fixture(work_root, "asr.json", ASR_FIXTURE),
    )
    payload = _payload(result)
    run_dir = Path(payload["run_dir"])

    corrections = work_root / "corrections.json"
    corrections.write_text(
        json.dumps({"reviewed_cue_ids": [1, 2], "corrections": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    review = subprocess.run(
        [sys.executable, str(REVIEW_ENTRY), str(run_dir), "--corrections", str(corrections)],
        capture_output=True, text=True,
    )
    assert review.returncode == 0, review.stderr

    content = (run_dir / "content.md").read_text(encoding="utf-8")
    assert content.count("- 证据索引：evidence/index.json") == 1
    assert json.loads((run_dir / "evidence" / "index.json").read_text(encoding="utf-8"))


def test_default_run_rejects_system_temp_root(work_root):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cwd = Path(tmp) / "run-here"
        tmp_cwd.mkdir()
        result = subprocess.run(
            [sys.executable, str(ENTRY), "https://www.bilibili.com/video/BV1sample00"],
            capture_output=True, text=True, cwd=tmp_cwd,
            env={**os.environ, "OMR_FIXTURE": _reliable_fixture(work_root)},
        )
    assert result.returncode != 0
    payload = json.loads(result.stderr)
    assert "临时" in payload["error"]
    assert not (tmp_cwd / ".media").exists()


def test_default_run_rejects_symlinked_temp_root(work_root):
    real = Path(tempfile.mkdtemp())
    try:
        link = work_root / "linked"
        link.symlink_to(real, target_is_directory=True)
        result = subprocess.run(
            [sys.executable, str(ENTRY), "https://www.bilibili.com/video/BV1sample00"],
            capture_output=True, text=True, cwd=link,
            env={**os.environ, "OMR_FIXTURE": _reliable_fixture(work_root)},
        )
        assert result.returncode != 0
        payload = json.loads(result.stderr)
        assert "临时" in payload["error"]
        assert not (real / ".media").exists()
    finally:
        for child in real.iterdir():
            child.unlink()
        real.rmdir()


def test_explicit_output_in_temp_root_is_rejected(work_root):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        result = run_entry(
            "https://www.bilibili.com/video/BV1sample00",
            out,
            work_root,
            fixture=_reliable_fixture(work_root),
            fakes=False,
        )
    assert result.returncode != 0
    payload = json.loads(result.stderr)
    assert "临时" in payload["error"]
    assert not out.exists()


def test_old_manifest_without_evidence_path_still_loads(work_root):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr.workspace import RunWorkspace  # noqa: E402

    run_dir = work_root / "bilibili-legacy-20260101T000000+0800"
    run_dir.mkdir(parents=True)
    (run_dir / "content.md").write_text("# 旧报告\n", encoding="utf-8")
    manifest = {
        "input_url": "https://www.bilibili.com/video/BVold0000",
        "canonical_url": "https://www.bilibili.com/video/BVold0000",
        "platform": "bilibili",
        "content_id": "BVold0000",
        "status": "success",
        "stage": "complete",
        "processing_path": "人工字幕",
        "result_path": str(run_dir / "content.md"),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    workspace = RunWorkspace.load(run_dir)
    assert workspace.evidence_path is None
    assert workspace.result_path == run_dir / "content.md"


def test_evidence_write_failure_is_a_structured_error(work_root):
    sys.path.insert(0, str(MODULE_DIR / "scripts"))
    from omr.model import OMRError  # noqa: E402
    from omr.workspace import RunWorkspace  # noqa: E402

    workspace = RunWorkspace.create(work_root, "bilibili",
                                    "https://www.bilibili.com/video/BV1sample00")
    workspace.evidence_dir.mkdir(parents=True, exist_ok=True)
    (workspace.evidence_dir / "index.json").write_text("占位", encoding="utf-8")
    try:
        try:
            workspace.write_evidence_atomic(
                "index.json", json.dumps({"version": 1}, ensure_ascii=False)
            )
        except OMRError as exc:
            assert "证据" in str(exc)
        else:
            raise AssertionError("写入到目录占位文件应失败")
    finally:
        (workspace.evidence_dir / "index.json").unlink()
