"""目录角色必须由官方条目、实际标题和目录目标共同证明。"""
import json
import sys
from pathlib import Path

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import build_toc
import verify_delivery as delivery


@pytest.fixture
def toc_project(tmp_path):
    root = tmp_path
    chapter = "01_正文.md"
    toc = "00_目录.md"
    (root / "source").mkdir()
    (root / "source/official.txt").write_text("First\nSecond\n")
    (root / "source/page.html").write_text(
        "<article><h1>First</h1><p>Text.</p><h2>Second</h2><p>More.</p></article>")
    (root / "source/parsed.md").write_text("# First\n\nText.\n\n## Second\n\nMore.\n")
    (root / chapter).write_text("# First（第一节）\n\n正文。\n\n## Second（第二节）\n\n续文。\n")
    manifest = {
        "project_root": str(root), "scope": "两节",
        "official_basis": {"path": "source/official.txt", "confirmation": "原题"},
        "official_lines": [1, 2],
        "entries": [
            {"official_line": number, "original_title": title, "level": number,
             "translation": chapter, "occurrence": 1}
            for number, title in enumerate(("First", "Second"), 1)
        ],
    }
    manifest_path = root / "source/toc.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))
    record = {
        "version": 1, "mode": "translation", "delivery_root": str(root),
        "inputs": [toc, chapter], "outputs": [],
        "files": {toc: "toc", chapter: "chapter"},
        "toc_manifests": {toc: "source/toc.json"},
        "sources": [{
            "family": "single", "source_version": "fixture",
            "parsed_markdown": "source/parsed.md",
            "snapshots": [{"snapshot": "source/page.html", "section_id": None}],
            "covers": [chapter],
        }],
        "checks": [{"tool": "verify_translation", "args": [chapter, "source/parsed.md"]}],
        "reviews": [],
    }
    return root, root / toc, manifest_path, record


def test_toc_pairing_and_unmarked_content(toc_project):
    root, toc, manifest, _ = toc_project
    links = [
        "[First（第一节）](01_正文.md#first第一节)",
        "[Second（第二节）](01_正文.md#second第二节)",
    ]
    content = "# 目录\n\n范围：两节\n\n- " + links[0] + "\n  - " + links[1] + "\n"
    marked = build_toc.START + "\n\n" + content + "\n" + build_toc.END + "\n"
    for actual in (marked, content):
        toc.write_text(actual)
        result = build_toc.verify_toc(str(manifest), str(toc))
        assert [(item["label"], item["fragment"]) for item in result["entries"]] == [
            ("First（第一节）", "first第一节"), ("Second（第二节）", "second第二节")]
        assert set(result["dependencies"]) == {str(path.resolve()) for path in (
            toc, manifest, root / "source/official.txt", root / "01_正文.md")}
        assert all(result["dependencies"].values())
        assert toc.read_text() == actual

    legacy_table = (
        "# 目录\n\n译自：https://example.org/paper。\n\n交付范围：两节\n\n"
        "| 官方原题 | 译文标题 | 位置 |\n|---|---|---|\n"
        "| First | 第一节 | [01_正文.md](01_正文.md) |\n"
        "| Second | 第二节 | [Second](01_正文.md#second第二节) |\n")
    toc.write_text(legacy_table)
    assert len(build_toc.verify_toc(str(manifest), str(toc))["entries"]) == 2

    swapped = (content.replace("first第一节", "SWAP")
               .replace("second第二节", "first第一节").replace("SWAP", "second第二节"))
    for invalid in (swapped, marked + "\n未经核验的正文。\n",
                    content + "\n未经核验的正文。\n",
                    content.replace("范围：两节", "范围：三节"),
                    legacy_table.replace("第一节 |", "另一节 |")):
        toc.write_text(invalid)
        with pytest.raises(ValueError):
            build_toc.verify_toc(str(manifest), str(toc))


def test_toc_identity_and_body_coverage(toc_project):
    root, toc, manifest, record = toc_project
    generated, _, _, _ = build_toc.build(manifest, toc)
    toc.write_text(generated)
    assert delivery.resolve_input_roles(str(root), record) == {
        "00_目录.md": "toc", "01_正文.md": "chapter"}
    problems = []
    entries = delivery.check_source_chains(root, record, problems)
    assert not problems, problems
    identity = delivery.compute_delivery_identity(root, record, entries)
    _, _, inputs, pdfs = delivery.rerun_checks(root, record, problems)
    assert not problems, problems
    chapter = "01_正文.md"
    for kind in ("source-reconcile", "semantic"):
        binding = delivery.expected_review_binding(
            kind, chapter, root, record, entries, inputs, pdfs, identity)
        record["reviews"].append({
            "kind": kind, "target": chapter, "status": "closed", "note": "核对",
            "sha256": identity["inputs"][chapter], "binding": binding})
    target_inputs = [root / path for path in record["inputs"]]
    ready, before = delivery.check_translation_readiness(root, record, target_inputs)
    assert ready, before

    for path in (root / "source/official.txt", manifest):
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        current = delivery.compute_delivery_identity(root, record, entries)
        assert current != identity
        ready, after = delivery.check_translation_readiness(root, record, target_inputs)
        assert ready, after
        assert after["identity"] != before["identity"]
        path.write_bytes(original)
    checks = record["checks"]
    record["checks"] = []
    ready, after = delivery.check_translation_readiness(root, record, target_inputs)
    assert not ready and "没有可复跑的核验记录" in " ".join(after["reasons"])
    record["checks"] = checks
    record["toc_manifests"] = {}
    with pytest.raises(delivery.DeliveryError, match="目录.*依据"):
        delivery.resolve_input_roles(str(root), record)
