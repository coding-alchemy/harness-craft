"""二期 ticket 04：表格逐格保真与论文阅读口径。

覆盖验收 04-1～04-6 的底层定向用例：简单表既有表示、复杂表经
table_conversions 逐源格裁决映射（跨度/空值/代码/公式）、缺映射与
格位/格内损伤按目标原因拒绝、check_policy 表定位投影。
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_tables.html'

IDENTITY = {
    'expected_title': 'T04 Fixture', 'actual_title': 'T04 Fixture',
    'paper_id': '2204.00004', 'version': 'v1',
    'final_url': 'https://example.org/abs/2204.00004v1',
    'retrieved_at': '2026-10-04T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}


def _table_conversions(raw):
    return {
        'version': 1,
        'snapshot_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'tables': [{
            'locate': {'table': 2, 'table_id': 'tab2'},
            'cells': [
                {'row': 1, 'col': 1, 'rowspan': 2, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 1, 'col': 1}]},
                {'row': 1, 'col': 2, 'rowspan': 1, 'colspan': 2,
                 'targets': [{'table': 2, 'row': 1, 'col': 2}]},
                {'row': 2, 'col': 1, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 2, 'col': 2}]},
                {'row': 2, 'col': 2, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 2, 'col': 3}]},
                {'row': 3, 'col': 1, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 3, 'col': 1}]},
                {'row': 3, 'col': 2, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 3, 'col': 2}]},
                {'row': 3, 'col': 3, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 3, 'col': 3}]},
                {'row': 4, 'col': 1, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 4, 'col': 1}]},
                {'row': 4, 'col': 2, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 4, 'col': 2}]},
                {'row': 4, 'col': 3, 'rowspan': 1, 'colspan': 1,
                 'targets': [{'table': 2, 'row': 4, 'col': 3}]},
            ]}]}


def _adapt(table_conversions=True):
    raw = FIXTURE.read_text(encoding='utf-8')
    tc = _table_conversions(raw) if table_conversions else None
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(FIXTURE.parent), table_conversions=tc)
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': str(FIXTURE),
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
        'table_conversions': tc,
    }
    return raw, md, payload, adapter


class SimpleTableTest(unittest.TestCase):
    """04-1：简单表复用既有格位与代码表示。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_simple_table_rendered_with_cells(self):
        self.assertIn('[TABLE]\nName | Value\n--- | ---\nalpha | $a < b$\n'
                      'beta | `flag=1`', self.md)
        corr = next(c for c in self.payload['correspondences']
                    if c.get('content_type') == 'table'
                    and c['node'] == 'table[1]')
        self.assertEqual(corr['conversion']['style'], 'simple')

    def test_roundtrip_clean(self):
        self.assertEqual(reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload,
            table_conversions=self.payload['table_conversions']), [])

    def test_cell_text_tampered_rejected(self):
        damaged = self.md.replace('alpha | $a < b$',
                                  'alpha | $a > b$', 1)
        diffs = reconcile_latexml_to_markdown(
            self.raw, damaged, None, self.payload,
            table_conversions=self.payload['table_conversions'])
        self.assertTrue(any('第 2 行不一致' in d or '与声明源格不符' in d
                            or '正文流' in d for d in diffs))

    def test_flattened_table_rejected(self):
        damaged = self.md.replace(
            '[TABLE]\nName | Value\n--- | ---\nalpha | $a < b$\n'
            'beta | `flag=1`\n',
            'Name Value alpha a < b beta flag=1\n', 1)
        diffs = reconcile_latexml_to_markdown(
            self.raw, damaged, None, self.payload,
            table_conversions=self.payload['table_conversions'])
        self.assertTrue(any('切片与独立重建输出不符' in d or '正文流' in d
                            for d in diffs))

    def test_table_as_code_rejected(self):
        damaged = self.md.replace(
            '[TABLE]\nName | Value\n--- | ---\nalpha | $a < b$\n'
            'beta | `flag=1`\n',
            '```\nName Value\n```\n', 1)
        diffs = reconcile_latexml_to_markdown(
            self.raw, damaged, None, self.payload,
            table_conversions=self.payload['table_conversions'])
        self.assertTrue(diffs)


class ComplexTableTest(unittest.TestCase):
    """04-1/04-2：复杂表按逐源格裁决映射物化并独立核对。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_mapped_table_rendered(self):
        self.assertIn('Config | Metric | ', self.md)
        self.assertIn(' | Speed | Acc', self.md)
        self.assertIn('base | 1.2 | $\\frac{9}{10}$', self.md)
        self.assertIn('[TABLE-CODE r=4 c=2#1]\n```\ncode_big()\n```',
                      self.md)
        corr = next(c for c in self.payload['correspondences']
                    if c.get('node') == 'table[2]')
        self.assertEqual(corr['conversion']['style'], 'mapped')
        self.assertEqual(corr['conversion']['locate'],
                         {'table': 2, 'table_id': 'tab2'})

    def test_missing_mapping_rejected(self):
        raw, md, payload, _ad = _adapt(table_conversions=False)
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload,
                                              table_conversions=None)
        self.assertTrue(any('未解释跨行/跨列' in d or '表格数量不一致' in d
                            or '未在依据中登记' in d for d in diffs))

    def test_undeclared_source_cell_rejected(self):
        tc = copy.deepcopy(self.payload['table_conversions'])
        tc['tables'][0]['cells'] = [
            c for c in tc['tables'][0]['cells']
            if not (c['row'] == 2 and c['col'] == 1)]
        diffs = reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload, table_conversions=tc)
        self.assertTrue(any('未声明的源格' in d for d in diffs))

    def test_wrong_target_rejected(self):
        tc = copy.deepcopy(self.payload['table_conversions'])
        for c in tc['tables'][0]['cells']:
            if c['row'] == 2 and c['col'] == 1:
                c['targets'] = [{'table': 2, 'row': 2, 'col': 3}]
        diffs = reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload, table_conversions=tc)
        self.assertTrue(any('与声明源格不符' in d for d in diffs))

    def test_undeclared_span_rejected(self):
        tc = copy.deepcopy(self.payload['table_conversions'])
        tc['tables'][0]['cells'][0]['rowspan'] = 3
        diffs = reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload, table_conversions=tc)
        self.assertTrue(any('跨度不符' in d for d in diffs))

    def test_cell_code_tampered_rejected(self):
        damaged = self.md.replace('code_big()', 'code_small()', 1)
        diffs = reconcile_latexml_to_markdown(
            self.raw, damaged, None, self.payload,
            table_conversions=self.payload['table_conversions'])
        self.assertTrue(any('格内代码归属不一致' in d for d in diffs))

    def test_cell_formula_tampered_rejected(self):
        damaged = self.md.replace('\\frac{9}{10}', '\\frac{8}{10}', 1)
        diffs = reconcile_latexml_to_markdown(
            self.raw, damaged, None, self.payload,
            table_conversions=self.payload['table_conversions'])
        self.assertTrue(any('与声明源格不符' in d for d in diffs))

    def test_empty_cell_without_target_rejected(self):
        tc = copy.deepcopy(self.payload['table_conversions'])
        for c in tc['tables'][0]['cells']:
            if c['row'] == 3 and c['col'] == 2:
                c['targets'] = []
        diffs = reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload, table_conversions=tc)
        self.assertTrue(any('未声明任何对应位置' in d for d in diffs))


class CheckPolicyTableTest(unittest.TestCase):
    """04-6：表定位进 check_policy 投影，相关变化使包失效。"""

    def test_locate_projection(self):
        _raw, md, payload, _ad = _adapt()
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            import os
            policy = latexml.check_policy_projection(payload, 0,
                                                     len(md) + 1, path)
            tables = [n for n in policy['nodes']
                      if n['content_type'] == 'table']
            self.assertEqual(len(tables), 2)
            self.assertIn('locate_sha256', tables[1])
            before = copy.deepcopy(policy)
            for c in payload['correspondences']:
                if c.get('node') == 'table[2]':
                    c['conversion']['locate'] = {'table': 9}
            changed = latexml.check_policy_projection(
                payload, 0, len(md) + 1, path)
            self.assertNotEqual(before, changed)
            os.unlink(path)
        except OSError:
            pass


if __name__ == '__main__':
    unittest.main()
