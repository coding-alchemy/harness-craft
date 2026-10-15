"""LaTeXML 测试候选准备及准入损伤断言；不从产物计算预期事实。"""
import copy
import json
import subprocess
import sys

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

IDENTITY = {
    'expected_title': 'T', 'actual_title': 'T', 'paper_id': '2210.00022',
    'version': 'v1', 'final_url': 'https://example.org/abs/2210.00022v1',
    'retrieved_at': '2026-10-11T00:00:00Z',
    'confirmation': '固定原始装置的题名与身份独立确认。',
}


def adapt_fixture(fixture, identity):
    raw = fixture.read_text(encoding='utf-8')
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(fixture.parent))
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': str(fixture),
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(identity),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
    }
    if adapter.groups:
        payload['groups'] = adapter.groups
    return raw, md, payload, adapter


def raw_document(content):
    return '<article class="ltx_document"><h1>T</h1>' + content + '</article>'


def note(content):
    return ('<p>Body <a class="ltx_note_ref" href="#fn:a">a</a>.</p>'
            '<div class="ltx_note" id="fn:a"><div class="ltx_note_content">'
            + content + '</div></div>')


def current_candidate(base, raw):
    snapshot = base / 'input.html'
    snapshot.write_text(raw)
    md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
        raw, None, [], str(base))
    payload = latexml.build_candidate_adaptation(
        {'paper_identity': IDENTITY, 'decisions': []}, raw, str(snapshot),
        corrs, unresolved, selection=None, md_text=md)
    return md, payload


def replace_current(md, payload, old, new):
    """更新合法摘要/坐标；反例必须到达独立回源检查，而非陈旧摘要预检。"""
    at = md.index(old)
    result = md[:at] + new + md[at + len(old):]
    payload = copy.deepcopy(payload)
    delta = len(new) - len(old)
    for entry in payload['correspondences']:
        for field in ('md_start', 'md_end'):
            if entry[field] > at:
                entry[field] += delta
    payload['markdown'] = latexml.markdown_range_facts(result)
    return result, payload


def assert_rejected_at_admission(self, base, raw, md, payload):
    diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
    self.assertTrue(any('正文流' in d for d in diffs), diffs)
    self.assertEqual(payload['markdown'], latexml.markdown_range_facts(md))
    (base / 'damaged.md').write_text(md)
    (base / 'damaged.json').write_text(json.dumps(payload))
    result = subprocess.run([
        sys.executable, str(SCRIPTS / 'split_work_packages.py'),
        str(base / 'damaged.md'), str(base / 'packs'), str(base / 'trans'),
        '--source-adaptation', str(base / 'damaged.json')],
        capture_output=True, text=True)
    self.assertNotEqual(result.returncode, 0, result.stdout)
    self.assertIn('拆分拒绝', result.stderr)
    self.assertNotIn('Markdown 摘要', result.stderr)
    self.assertFalse((base / 'packs').exists())
