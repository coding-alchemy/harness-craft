"""候选记录列出当前实际待办，正式发布仍按原复核门禁决定。"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_delivery_toc_roles import toc_project  # noqa: F401 — reuse pytest fixture
from translator_test_support import SCRIPTS

import build_toc
import verify_delivery as delivery


def make_numeric_record(toc_project):
    root, toc, manifest, record = toc_project
    chapter = root / "01_正文.md"
    snapshot = root / "source/page.html"
    parsed = root / "source/parsed.md"
    snapshot.write_text(snapshot.read_text().replace("Text.", "It takes 5ms."))
    parsed.write_text(parsed.read_text().replace("Text.", "It takes 5ms."))
    chapter.write_text(chapter.read_text().replace("正文。", "耗时 5s。"))
    generated, _, _, _ = build_toc.build(manifest, toc)
    toc.write_text(generated)
    record["checks"][0]["args"].append("--numeric-review")
    original = root / "source/record.json"
    original.write_text(json.dumps(record, ensure_ascii=False))
    return root, chapter, original, record


def run_cli(original, *arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_delivery.py"),
         "--record", str(original), *map(str, arguments)],
        text=True, capture_output=True, timeout=45)


def test_prepare_reviews_is_pending_and_nonpublishing(toc_project):
    root, _, original, record = make_numeric_record(toc_project)
    before = copy.deepcopy(record)
    candidate = delivery.prepare_reviews(root, record)
    assert record == before
    assert candidate["mode"] == "translation"
    assert [(review["kind"], review["target"], review["status"])
            for review in candidate["reviews"]] == [
        ("source-reconcile", "01_正文.md", "pending"),
        ("semantic", "01_正文.md", "pending")]
    items = candidate["reviews"][1]["items"]
    assert len(items) == 2 and all(item.startswith("NUM[") for item in items)
    assert all(review["binding"] for review in candidate["reviews"])

    output = original.with_name("candidate.json")
    result = run_cli(original, "--prepare-reviews", output)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == candidate
    assert "数字" in result.stderr
    assert json.loads(original.read_text()) == before
    with tempfile.TemporaryDirectory(prefix="tdt-candidate-",
                                     dir=Path.home() / ".cache") as evidence:
        index = Path(evidence) / "delivery_index.json"
        index.write_bytes(b"previous index")
        result = run_cli(output, "--evidence-dir", evidence)
        assert result.returncode != 0 and "复核未闭合" in result.stderr
        assert index.read_bytes() == b"previous index"


def test_prepare_reviews_rejects_alias_and_stale_items(toc_project):
    root, chapter, original, record = make_numeric_record(toc_project)
    before = original.read_bytes()
    alias = original.with_name("alias.json")
    alias.symlink_to(original)
    for target in (original, alias, chapter):
        result = run_cli(original, "--prepare-reviews", target)
        assert result.returncode != 0, result.stdout
        assert original.read_bytes() == before

    candidate = delivery.prepare_reviews(root, record)
    for review in candidate["reviews"]:
        review.update(status="closed", note="测试人工处置记录")
    assert delivery.prepare_reviews(root, candidate)["reviews"] == candidate["reviews"]

    chapter.write_text(chapter.read_text().replace("5s", "7s"))
    changed = delivery.prepare_reviews(root, candidate)
    semantic = next(review for review in changed["reviews"]
                    if review["kind"] == "semantic")
    assert semantic["status"] == "pending"
    assert any("7s" in item for item in semantic["items"])
    assert all("5s" not in item for item in semantic["items"])
    output = original.with_name("hard-failure.json")
    chapter.write_text(chapter.read_text().replace("## Second", "### Second"))
    result = run_cli(original, "--prepare-reviews", output)
    assert result.returncode != 0 and not output.exists()
