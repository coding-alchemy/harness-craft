"""参考源准备清单只读，目标与表序可回查原 HTML。"""
import hashlib
import json
import subprocess
import sys

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import parse_reference_html as parser
import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown


def run_inspect(snapshot, output, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "parse_reference_html.py"), str(snapshot),
         "--inspect-output", str(output), *map(str, extra)],
        text=True, capture_output=True, timeout=30)


def test_inspect_unresolved_is_readonly(tmp_path):
    snapshot = tmp_path / "paper.html"
    raw = '<article class="ltx_document"><h1>T</h1><video>fallback</video><img src="gone.svg"></article>'
    snapshot.write_text(raw)
    output = tmp_path / "inspection.json"
    result = run_inspect(snapshot, output)
    assert result.returncode == 0, result.stderr
    candidate = json.loads(output.read_text())
    assert candidate["kind"] == "reference-inspection"
    assert candidate["snapshot"] == {
        "path": str(snapshot.resolve()), "sha256": hashlib.sha256(raw.encode()).hexdigest()}
    assert candidate["unresolved"]
    assert any(item["source_ref"] == "gone.svg" and item["problem"]
               for item in candidate["resources"])
    assert {path.name for path in tmp_path.iterdir()} == {"paper.html", "inspection.json"}
    assert snapshot.read_text() == raw


def test_inspect_anchor_ownership_and_table_order(tmp_path):
    snapshot = tmp_path / "paper.html"
    simple = "<table><tr><th>Simple</th></tr><tr><td>1</td></tr></table>"
    complex_a = (
        '<table id="a"><tr><th rowspan="2" id="cell"><code>x</code></th>'
        '<th>Value</th></tr><tr><td><math alttext="u"></math></td></tr></table>')
    complex_b = (
        '<table id="b"><tr><th colspan="2">Group</th></tr><tr>'
        '<td><a href="#p1">Back</a></td><td></td></tr></table>')
    equation = ('<table class="ltx_equation"><tr><td>'
                '<math display="block" alttext="q"></math></td></tr></table>')
    raw = ('<article class="ltx_document"><h1>T</h1>' + equation +
           '<p id="p1">Paragraph <a href="#cell">Cell</a> '
           '<a href="#a2024">2024a</a> <a href="#b2024">2024b</a>.</p>'
           + simple + complex_a + simple + complex_b +
           '<ul class="ltx_biblist"><li id="a2024">Author 2024a '
           '<a href="#p1">Cited by</a></li><li id="b2024">Author 2024b '
           '<a href="#p1">Cited by</a></li></ul></article>')
    snapshot.write_text(raw)
    candidate = parser.inspect_reference(str(snapshot))
    anchors = {item["id"]: item for item in candidate["anchors"]}
    assert set(anchors) == {"p1", "cell", "a2024", "b2024"}
    assert {key: item["role"] for key, item in anchors.items()} == {
        "p1": "paragraph", "cell": "table-cell", "a2024": "reference", "b2024": "reference"}
    assert anchors["p1"]["markdown"] == '<a id="p1"></a>'
    assert len({item["node"] for item in anchors.values()}) == 4
    tables = candidate["table_conversions"]["tables"]
    assert [table["locate"]["table"] for table in tables] == [2, 4]
    assert [{target["table"] for cell in table["cells"] for target in cell["targets"]}
            for table in tables] == [{2}, {4}]
    assert [(cell["row"], cell["col"]) for cell in tables[1]["cells"]] == [
        (1, 1), (2, 1), (2, 2)]
    mapping = candidate["table_conversions"]
    md, correspondences, unresolved, _, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(tmp_path), table_conversions=mapping)
    assert not unresolved
    assert md.count("[TABLE]") == 4
    assert md.count("(#p1)") == 3
    adaptation = latexml.build_candidate_adaptation(
        {"paper_identity": {
            "expected_title": "T", "actual_title": "T", "paper_id": "fixture",
            "version": "v1", "final_url": "https://example.org/paper",
            "retrieved_at": "2026-11-08", "confirmation": "测试原 DOM",
        }},
        raw, str(snapshot), correspondences, unresolved, groups=adapter.groups,
        table_conversions=mapping, md_text=md)
    assert not reconcile_latexml_to_markdown(raw, md, None, adaptation)


def test_inspect_output_conflicts(tmp_path):
    snapshot = tmp_path / "paper.html"
    snapshot.write_text('<article><h1>T</h1><p>Body.</p></article>')
    original = snapshot.read_bytes()
    existing = tmp_path / "candidate.json"
    existing.write_bytes(b"prior")
    alias = tmp_path / "alias.json"
    alias.symlink_to(snapshot)
    for output in (snapshot, existing, alias):
        result = run_inspect(snapshot, output)
        assert result.returncode != 0
        assert "新路径" in result.stderr
        assert snapshot.read_bytes() == original
        assert existing.read_bytes() == b"prior"
    result = run_inspect(snapshot, tmp_path / "new.json",
                         "--adaptation-output", tmp_path / "formal.json")
    assert result.returncode != 0
    assert not (tmp_path / "new.json").exists()
    assert not (tmp_path / "formal.json").exists()
