"""二期 ticket 21：表格与公式组逐项事实。

覆盖验收 21-1～21-6：简单表逐格（题注/表头/数据格/空格位/格内字面块级
公式）、映射复杂表重排格位、格内代码与公式组的成员/式号各有来源身份与
精确区间；重复表达式各自绑定自己的出现身份；错格位、身份交换、删格、
删成员、漏映射、改型/改式、乱序、式号文字与归属损伤均按目标原因拒绝；
未映射复杂表保持保留拒绝；表/组不再为成员授予宿主豁免（bound_math_spans
逐出现绑定）；拆包保护与 check_policy 投影等现有消费入口接入本票正例。
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / (
    'latexml_tables_groups.html')

IDENTITY = {
    'expected_title': 'T21 Fixture', 'actual_title': 'T21 Fixture',
    'paper_id': '2210.00021', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00021v1',
    'retrieved_at': '2026-10-10T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}

INLINE_IDENTITY = dict(
    IDENTITY, expected_title='T', actual_title='T')


def _payload(raw, corrs, unres, adapter, identity, snapshot_path,
             table_conversions=None):
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': str(snapshot_path),
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(identity),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
    }
    if adapter.groups:
        payload['groups'] = adapter.groups
    if table_conversions is not None:
        payload['table_conversions'] = table_conversions
    return payload


def _adapt():
    raw = FIXTURE.read_text(encoding='utf-8')
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(FIXTURE.parent))
    return raw, md, _payload(raw, corrs, unres, adapter, IDENTITY, FIXTURE)


def _adapt_inline(body, table_conversions=None):
    raw = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
           '<title>T</title></head><body><article class="ltx_document">'
           '<h1 class="ltx_title">T</h1>%s</article></body></html>' % body)
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(FIXTURE.parent),
        table_conversions=table_conversions)
    payload = _payload(raw, corrs, unres, adapter, INLINE_IDENTITY,
                       '<inline>', table_conversions=table_conversions)
    return raw, md, payload


def _corr(payload, node):
    return next(c for c in payload['correspondences']
                if c.get('node') == node)


def _reconcile(raw, md, payload, table_conversions=None):
    return reconcile_latexml_to_markdown(raw, md, None, payload,
                                         table_conversions=table_conversions)


class TableCellFactsTest(unittest.TestCase):
    """21-1/21-2：简单表逐格身份、空格位与格内字面块级公式。"""

    def setUp(self):
        self.raw, self.md, self.payload = _adapt()

    def test_roundtrip_clean(self):
        self.assertEqual(_reconcile(self.raw, self.md, self.payload), [])

    def test_table_simple_style_and_range(self):
        corr = _corr(self.payload, 'table[1]')
        self.assertEqual(corr['conversion']['style'], 'simple')
        self.assertEqual(
            self.md[corr['md_start']:corr['md_end']],
            '[TABLE-CAPTION] Tab $t$ cap. #\n\n[TABLE]\n'
            'H $h$ | H2\n--- | ---\nCell $x$ a | plain\n'
            'Lit $x$ b | \n$$y$$ | tail $x$')

    def test_caption_and_header_math_identity(self):
        cap = _corr(self.payload, 'math[1]')
        self.assertEqual((cap['kind'], cap['tex']), ('inline', 't'))
        self.assertEqual(self.md[cap['md_start']:cap['md_end']], '$t$')
        head = _corr(self.payload, 'math[2]')
        self.assertEqual((head['kind'], head['tex']), ('inline', 'h'))
        self.assertEqual(self.md[head['md_start']:head['md_end']], '$h$')
        table = _corr(self.payload, 'table[1]')
        self.assertTrue(table['md_start'] < cap['md_start']
                        < cap['md_end'] < table['md_end'])

    def test_cell_mathml_and_literal_distinct_identity(self):
        # 相同表达式 x 的三处出现：Cell 格 MathML、Lit 格字面、tail 格字面，
        # 各自绑定精确区间，互不相同
        m3 = _corr(self.payload, 'math[3]')
        m6 = _corr(self.payload, 'math[6]')
        m8 = _corr(self.payload, 'math[8]')
        self.assertEqual((m3['tex'], m6['tex'], m8['tex']), ('x', 'x', 'x'))
        ranges = {(m['md_start'], m['md_end']) for m in (m3, m6, m8)}
        self.assertEqual(len(ranges), 3)
        for m in (m3, m6, m8):
            self.assertEqual(m['kind'], 'inline')
            self.assertEqual(self.md[m['md_start']:m['md_end']], '$x$')
        # 文档序：Cell 格 < Lit 格 < tail 格
        self.assertTrue(m3['md_start'] < m6['md_start'] < m8['md_start'])

    def test_literal_block_math_stays_in_cell(self):
        # 字面块级公式逐字留在格内（既有格位表示），不因宿主位置改类型
        corr = _corr(self.payload, 'math[7]')
        self.assertEqual((corr['kind'], corr['tex']), ('block', 'y'))
        self.assertEqual(self.md[corr['md_start']:corr['md_end']], '$$y$$')

    def test_blank_cell_trailing_space_preserved(self):
        # 末列空格位的行尾空格是格位标记的一部分，原样保留
        self.assertIn('\nLit $x$ b | \n', self.md)


class GroupFactsTest(unittest.TestCase):
    """21-1/21-2：公式组成员序、式号文字/归属与重复式各自区间。"""

    def setUp(self):
        self.raw, self.md, self.payload = _adapt()

    def test_group_record_members_and_eqnos(self):
        groups = self.payload['groups']
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group['node'], 'group[1]')
        self.assertEqual(group['members'], ['math[4]', 'math[5]'])
        self.assertEqual(group['eqnos'], [
            {'member': 0, 'text': '(1)', 'target': '#e1'},
            {'member': 1, 'text': '(2)', 'target': '#e2'}])

    def test_duplicate_members_distinct_ranges(self):
        m4 = _corr(self.payload, 'math[4]')
        m5 = _corr(self.payload, 'math[5]')
        self.assertEqual((m4['kind'], m5['kind']), ('block', 'block'))
        self.assertEqual((m4['tex'], m5['tex']), ('u=v', 'u=v'))
        self.assertNotEqual((m4['md_start'], m4['md_end']),
                            (m5['md_start'], m5['md_end']))
        self.assertEqual(self.md[m4['md_start']:m4['md_end']], '$$\nu=v\n$$')
        self.assertEqual(self.md[m5['md_start']:m5['md_end']], '$$\nu=v\n$$')
        self.assertTrue(m4['md_end'] < m5['md_start'])

    def test_member_group_annotation(self):
        m4 = _corr(self.payload, 'math[4]')
        m5 = _corr(self.payload, 'math[5]')
        self.assertEqual((m4['group'], m4['group_index']), ('group[1]', 0))
        self.assertEqual((m5['group'], m5['group_index']), ('group[1]', 1))

    def test_group_host_range_covers_members(self):
        group = _corr(self.payload, 'group[1]')
        m4 = _corr(self.payload, 'math[4]')
        self.assertTrue(group['md_start'] <= m4['md_start']
                        < m4['md_end'] <= group['md_end'])


class DamageRejectionTest(unittest.TestCase):
    """21-4：错格位/身份交换/删格/删成员/改型/改式/乱序/式号与归属损伤。"""

    def setUp(self):
        self.raw, self.md, self.payload = _adapt()

    def test_wrong_cell_declared_range_rejected(self):
        payload = copy.deepcopy(self.payload)
        tail = _corr(payload, 'math[8]')
        _corr(payload, 'math[2]')['md_start'] = tail['md_start']
        _corr(payload, 'math[2]')['md_end'] = tail['md_end']
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('候选切片与实际写出内容不符' in d
                            or '出现身份传递区间' in d for d in diffs))

    def test_same_expression_cross_cell_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        a, b = _corr(payload, 'math[3]'), _corr(payload, 'math[6]')
        ra, rb = (a['md_start'], a['md_end']), (b['md_start'], b['md_end'])
        a['md_start'], a['md_end'] = rb
        b['md_start'], b['md_end'] = ra
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('出现身份传递区间' in d for d in diffs))

    def test_deleted_cell_content_rejected(self):
        damaged = self.md.replace(' | tail $x$', ' |')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('表格' in d for d in diffs))

    def test_table_row_reorder_rejected(self):
        damaged = self.md.replace('Lit $x$ b | \n$$y$$ | tail $x$',
                                  '$$y$$ | tail $x$\nLit $x$ b | ')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(diffs)
        self.assertTrue(any('表格' in d or '出现身份传递区间' in d
                            or '公式出现' in d for d in diffs))

    def test_cell_block_math_kind_tamper_rejected(self):
        payload = copy.deepcopy(self.payload)
        _corr(payload, 'math[7]')['kind'] = 'inline'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('类型冲突' in d for d in diffs))

    def test_group_member_tex_tamper_rejected(self):
        payload = copy.deepcopy(self.payload)
        _corr(payload, 'math[4]')['tex'] = 'v=u'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('表达式与原节点不符' in d for d in diffs))

    def test_group_member_order_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'][0]['members'] = ['math[5]', 'math[4]']
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('成员或顺序与独立重建不符' in d for d in diffs))

    def test_deleted_group_member_block_rejected(self):
        damaged = self.md.replace('$$\nu=v\n$$\n\n(2)\n', '(2)\n')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('数量不一致' in d for d in diffs))

    def test_eqno_text_tamper_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'][0]['eqnos'][0]['text'] = '(9)'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('式号与独立重建不符' in d for d in diffs))

    def test_eqno_member_misattribution_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'][0]['eqnos'][0]['member'] = 1
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('式号与独立重建不符' in d for d in diffs))

    def test_duplicate_member_range_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        a, b = _corr(payload, 'math[4]'), _corr(payload, 'math[5]')
        ra, rb = (a['md_start'], a['md_end']), (b['md_start'], b['md_end'])
        a['md_start'], a['md_end'] = rb
        b['md_start'], b['md_end'] = ra
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('出现身份传递区间' in d for d in diffs))


class UnmappedComplexTableTest(unittest.TestCase):
    """21-4/21-6：漏映射复杂表保持保留拒绝；保留文字中公式逐出现绑定，
    宿主范围不再授予免检资格。"""

    CPX = ('<table class="ltx_tabular"><tr><td rowspan="2">$m$</td>'
           '<td>n</td></tr><tr><td>o</td></tr></table>')

    def setUp(self):
        self.raw, self.md, self.payload = _adapt_inline(
            self.CPX + '<p>tail</p>')

    def test_unmapped_complex_table_unresolved(self):
        self.assertEqual(self.md, '# T\n\n[TABLE] $m$ n o\n\ntail\n')
        self.assertEqual(len(self.payload['unresolved']), 1)
        entry = self.payload['unresolved'][0]
        self.assertEqual(entry['content_type'], 'unresolved-container')
        self.assertEqual(entry['preserved'], '[TABLE] $m$ n o')
        self.assertIn('table_conversions', entry['reason'])

    def test_roundtrip_clean(self):
        self.assertEqual(_reconcile(self.raw, self.md, self.payload), [])

    def test_preserved_math_bound_individually(self):
        spans, problems = latexml.bound_math_spans(self.md, self.payload)
        self.assertEqual(problems, [])
        hits = [s for s in spans if s[1] == 'm']
        self.assertEqual(len(hits), 1)
        kind, _tex, start, end = hits[0]
        self.assertEqual(kind, 'inline')
        self.assertEqual(self.md[start:end], '$m$')


class MappedTableReorderTest(unittest.TestCase):
    """21-1/21-3：映射复杂表重排格位——出现身份绑定实际输出位置，
    输出序与 DOM 序相反时各自保持；文档末末列空格位由区间算术吸收。"""

    CPX = ('<table class="ltx_tabular" id="Tx">'
           '<tr><td rowspan="2">$A$</td><td>x</td></tr>'
           '<tr><td>$B$</td></tr></table>')

    def _convs(self, raw):
        return {
            'version': 1,
            'snapshot_sha256': latexml.sha256_text(raw),
            'tables': [{
                'locate': {'table': 1, 'table_id': 'Tx'},
                'cells': [
                    {'row': 1, 'col': 1, 'rowspan': 2, 'colspan': 1,
                     'targets': [{'table': 1, 'row': 2, 'col': 1}]},
                    {'row': 1, 'col': 2, 'rowspan': 1, 'colspan': 1,
                     'targets': [{'table': 1, 'row': 1, 'col': 2}]},
                    {'row': 2, 'col': 1, 'rowspan': 1, 'colspan': 1,
                     'targets': [{'table': 1, 'row': 1, 'col': 1}]},
                ],
            }],
        }

    def setUp(self):
        raw0, _md0, _p0 = _adapt_inline(self.CPX)
        self.raw, self.md, self.payload = _adapt_inline(
            self.CPX, table_conversions=self._convs(raw0))

    def test_reordered_output_identity(self):
        self.assertEqual(self.md, '# T\n\n[TABLE]\n$B$ | x\n$A$ |\n')
        a = _corr(self.payload, 'math[1]')
        b = _corr(self.payload, 'math[2]')
        self.assertEqual((a['tex'], b['tex']), ('A', 'B'))
        self.assertEqual(self.md[a['md_start']:a['md_end']], '$A$')
        self.assertEqual(self.md[b['md_start']:b['md_end']], '$B$')
        # 输出序与 DOM 序相反：身份绑定出现而非同文本
        self.assertTrue(b['md_start'] < a['md_start'])

    def test_roundtrip_clean(self):
        self.assertEqual(_reconcile(
            self.raw, self.md, self.payload,
            table_conversions=self.payload['table_conversions']), [])

    def test_reordered_identity_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        a = _corr(payload, 'math[1]')
        b = _corr(payload, 'math[2]')
        ra, rb = (a['md_start'], a['md_end']), (b['md_start'], b['md_end'])
        a['md_start'], a['md_end'] = rb
        b['md_start'], b['md_end'] = ra
        diffs = _reconcile(self.raw, self.md, payload,
                           table_conversions=payload['table_conversions'])
        self.assertTrue(any('候选切片与实际写出内容不符' in d
                            or '出现身份传递区间' in d for d in diffs))


class CellCodeTableTest(unittest.TestCase):
    """21-2：格内代码以 [TABLE-CODE] 围栏表示，格内公式保持身份。"""

    BODY = ('<table class="ltx_tabular">'
            '<tr><th>n</th><th>code</th></tr>'
            '<tr><td><math alttext="k" display="inline"><mi>k</mi></math></td>'
            '<td><pre>f(k)</pre></td></tr>'
            '</table>'
            '<p>after <math alttext="z" display="inline"><mi>z</mi></math></p>')

    def setUp(self):
        self.raw, self.md, self.payload = _adapt_inline(self.BODY)

    def test_roundtrip_clean(self):
        self.assertEqual(_reconcile(self.raw, self.md, self.payload), [])

    def test_cell_code_block_and_math(self):
        self.assertIn('[TABLE-CODE r=2 c=2#1]\n\n```\nf(k)\n```', self.md)
        k = _corr(self.payload, 'math[1]')
        z = _corr(self.payload, 'math[2]')
        self.assertEqual((k['kind'], k['tex']), ('inline', 'k'))
        self.assertEqual(self.md[k['md_start']:k['md_end']], '$k$')
        self.assertEqual((z['kind'], z['tex']), ('inline', 'z'))
        self.assertEqual(self.md[z['md_start']:z['md_end']], '$z$')
        # 格内代码文字不取得数学资格
        for c in self.payload['correspondences']:
            if c.get('content_type') == 'math':
                self.assertNotEqual(c['tex'], 'f(k)')


class ConsumptionPathTest(unittest.TestCase):
    """21-5：本票正例接入现有拆包保护与 check_policy 投影消费入口。"""

    def setUp(self):
        self.raw, self.md, self.payload = _adapt()

    def test_package_problems(self):
        contained = latexml.correspondence_package_problems(
            self.payload, [(0, len(self.md) + 1)])
        self.assertEqual(contained, [])
        corr = _corr(self.payload, 'math[4]')
        mid = (corr['md_start'] + corr['md_end']) // 2
        problems = latexml.correspondence_package_problems(
            self.payload, [(0, mid), (mid, len(self.md) + 1)])
        self.assertTrue(any('跨多个工作包' in p for p in problems))

    def test_policy_projection_group_facts(self):
        group = _corr(self.payload, 'group[1]')
        proj = latexml.check_policy_projection(
            self.payload, group['md_start'], group['md_end'], str(FIXTURE))
        self.assertEqual(len(proj['groups']), 1)
        # 23：投影按包内局部出现命名，全篇别名不进入资格比较
        self.assertEqual(proj['groups'][0]['members'],
                         ['math#1', 'math#2'])
        self.assertEqual(len(proj['groups'][0]['eqnos']), 2)
        nodes = {n['node']: n for n in proj['nodes']}
        self.assertIn('math#1', nodes)
        self.assertEqual(nodes['math#1'].get('group'), 'group#1')
        self.assertIn('tex_sha256', nodes['math#1'])

    def test_policy_projection_table_facts(self):
        table = _corr(self.payload, 'table[1]')
        proj = latexml.check_policy_projection(
            self.payload, table['md_start'], table['md_end'], str(FIXTURE))
        nodes = {n['node']: n for n in proj['nodes']}
        self.assertEqual(nodes['table#1']['table_style'], 'simple')
        self.assertIn('locate_sha256', nodes['table#1'])
        self.assertTrue(any(n['content_type'] == 'math'
                            for n in proj['nodes']))


if __name__ == '__main__':
    unittest.main()
