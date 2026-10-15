"""二期 ticket 19：正文与图片拆段身份闭环。

覆盖验收 19-1～19-7：叶子出现身份与精确区间（重复表达式、MathML/字面
混合、图片拆段，独立手写来源顺序/范围预期）、字面识别基于完整内容单元
与 D2 边界、唯一临时标记传递无残留、同式身份交换拒绝、删正文/删式/
改表达式/改类型/移动公式/篡改范围/共同漏内容按目标原因拒绝且失败保旧、
现有拆包与检查投影消费入口贯通、块级公式落入不可拆宿主 fail-fast。
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown
from _verification import scan_math

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_occurrence.html'

IDENTITY = {
    'expected_title': 'T19 Fixture', 'actual_title': 'T19 Fixture',
    'paper_id': '2210.00019', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00019v1',
    'retrieved_at': '2026-10-10T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}

# 独立手写预期：来源出现顺序、类型与精确区间（不取自生成器）
EXPECTED_OCCURRENCES = [
    ('math[6]', 'inline', 'x', 21, 24),          # 段落字面公式
    ('math[1]', 'block', 'E=mc^2', 37, 49),      # 段中块级拆段
    ('math[2]', 'inline', 'y=1', 101, 106),      # 标题内
    ('math[3]', 'inline', 'p +\nq = r', 119, 130),  # 多行行内
    ('math[4]', 'inline', 'z', 144, 147),        # 重复表达式之一
    ('math[5]', 'inline', 'z', 152, 155),        # 重复表达式之二
]
EXPECTED_HOSTS = [
    ('h1[1]', 'heading', 0, 13, '# T19 Fixture'),
    ('p[1]', 'paragraph', 15, 30, 'Alpha $x$ beta.'),
    ('p[2]', 'paragraph', 32, 56, 'Pre\n\n$$\nE=mc^2\n$$\n\npost.'),
    ('p[3]', 'paragraph', 58, 91, 'Left\n\n[IMG: images/a.png]\n\nright.'),
    ('h2[1]', 'heading', 93, 111, '## Head $y=1$ done'),
    ('p[4]', 'paragraph', 113, 136, 'Multi $p +\nq = r$ tail.'),
    ('p[5]', 'paragraph', 138, 161, 'Twins $z$ and $z$ here.'),
    ('p[6]', 'paragraph', 163, 187, 'Costs $5 and $100 total.'),
]


def _adapt(raw=None, path=None):
    if raw is None:
        raw = FIXTURE.read_text(encoding='utf-8')
        path = str(FIXTURE)
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(FIXTURE.parent))
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': path, 'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
    }
    return raw, md, payload, adapter


def _math_corrs(payload):
    return [c for c in payload['correspondences']
            if c.get('content_type') == 'math']


class OccurrenceIdentityTest(unittest.TestCase):
    """19-1/19-3：叶子出现各自绑定精确区间；父范围不代替叶子；标记无残留。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_leaf_occurrence_order_and_exact_ranges(self):
        maths = _math_corrs(self.payload)
        self.assertEqual(
            [(c['node'], c['kind'], c['tex'], c['md_start'], c['md_end'])
             for c in maths],
            EXPECTED_OCCURRENCES)

    def test_leaf_slices_match_declared_ranges(self):
        for node, kind, tex, start, end in EXPECTED_OCCURRENCES:
            corr = next(c for c in _math_corrs(self.payload)
                        if c['node'] == node)
            self.assertEqual((corr['md_start'], corr['md_end']), (start, end))
            self.assertEqual(corr['kind'], kind)
            self.assertEqual(corr['tex'], tex)

    def test_host_covering_ranges_and_independent_leaves(self):
        by_node = {c['node']: c for c in self.payload['correspondences']}
        for node, ctype, start, end, text in EXPECTED_HOSTS:
            corr = by_node[node]
            self.assertEqual(corr['content_type'], ctype)
            self.assertEqual((corr['md_start'], corr['md_end']), (start, end))
            self.assertEqual(self.md[start:end], text)
        # 父段落范围覆盖拆段输出，叶子公式/图片各有独立精确区间
        p2, p3 = by_node['p[2]'], by_node['p[3]']
        m1, img = by_node['math[1]'], by_node['img[1]']
        self.assertTrue(p2['md_start'] < m1['md_start']
                        < m1['md_end'] < p2['md_end'])
        self.assertTrue(p3['md_start'] < img['md_start']
                        < img['md_end'] < p3['md_end'])
        self.assertEqual(self.md[img['md_start']:img['md_end']],
                         '[IMG: images/a.png]')

    def test_block_split_layout(self):
        self.assertIn('Pre\n\n$$\nE=mc^2\n$$\n\npost.', self.md)

    def test_no_marker_residual(self):
        self.assertNotIn('\x00', self.md)

    def test_roundtrip_clean(self):
        self.assertEqual(reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload), [])


class LiteralContextTest(unittest.TestCase):
    """19-2：字面识别基于排版整理前完整内容单元；标签/链接/代码语境与 D2。"""

    def _adapt_case(self, body):
        raw = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
               '<title>T</title></head><body><article class="ltx_document">'
               '<h1 class="ltx_title">T</h1>%s</article></body></html>' % body)
        md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
            raw, None, [], str(FIXTURE.parent))
        identity = dict(IDENTITY, expected_title='T', actual_title='T')
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': '<inline>',
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': identity,
            'decisions': [], 'correspondences': corrs, 'unresolved': unres,
        }
        return raw, md, payload

    def test_literal_across_inline_tags_single_unit(self):
        raw, md, payload = self._adapt_case('<p>See $<b>a</b>$ end.</p>')
        maths = _math_corrs(payload)
        self.assertEqual(len(maths), 1)
        self.assertEqual(maths[0]['tex'], 'a')
        self.assertEqual(md[maths[0]['md_start']:maths[0]['md_end']], '$a$')
        self.assertEqual(reconcile_latexml_to_markdown(raw, md, None,
                                                       payload), [])

    def test_literal_inside_link(self):
        raw, md, payload = self._adapt_case(
            '<p>Ref <a href="#x">$c$</a> done.</p>')
        maths = _math_corrs(payload)
        self.assertEqual(len(maths), 1)
        self.assertEqual(maths[0]['tex'], 'c')
        self.assertEqual(md[maths[0]['md_start']:maths[0]['md_end']], '$c$')
        self.assertEqual(reconcile_latexml_to_markdown(raw, md, None,
                                                       payload), [])

    def test_code_and_pre_contexts_not_math(self):
        for body in ('<p>Use <code>$x$</code> here.</p>',
                     '<pre>$raw$ code</pre>'):
            raw, md, payload = self._adapt_case(body)
            self.assertEqual(_math_corrs(payload), [])
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None,
                                                           payload), [])
        self.assertEqual(scan_math('`$x$` $y$').spans[0].expr, 'y')
        self.assertEqual(scan_math('$5 and $100').spans, ())

    def test_currency_string_not_math(self):
        _raw, md, payload, _a = _adapt()
        self.assertIn('Costs $5 and $100 total.', md)
        maths = _math_corrs(payload)
        self.assertNotIn('5 and $100 total', [c['tex'] for c in maths])
        self.assertEqual(reconcile_latexml_to_markdown(
            _raw, md, None, payload), [])

    def test_cross_line_literal_not_qualified_by_folding(self):
        body = '<p>A $p +\n<em>q = r</em>$ B.</p>'
        with self.assertRaises(ValueError) as ctx:
            self._adapt_case(body)
        self.assertIn('不折叠取得资格', str(ctx.exception))


class DuplicateIdentitySwapTest(unittest.TestCase):
    """19-4：相同表达式的两次出现各自绑定；只换身份不改产物字节即拒绝。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_duplicates_have_distinct_ranges(self):
        zcorrs = [c for c in _math_corrs(self.payload)
                  if c['node'] in ('math[4]', 'math[5]')]
        self.assertEqual(len(zcorrs), 2)
        self.assertNotEqual(
            (zcorrs[0]['md_start'], zcorrs[0]['md_end']),
            (zcorrs[1]['md_start'], zcorrs[1]['md_end']))

    def test_identity_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        zcorrs = [c for c in payload['correspondences']
                  if c.get('node') in ('math[4]', 'math[5]')]
        a, b = zcorrs
        ra = (a['md_start'], a['md_end'])
        rb = (b['md_start'], b['md_end'])
        a['md_start'], a['md_end'] = rb
        b['md_start'], b['md_end'] = ra
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('出现身份传递区间' in d for d in diffs))


class DamageRejectionTest(unittest.TestCase):
    """19-5：删正文/删式/改表达式/改类型/移动公式/篡改范围/共同漏内容。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_deleted_paragraph_rejected(self):
        damaged = self.md.replace('Costs $5 and $100 total.\n', '')
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d or '缺少来源依据对应' in d
                            for d in diffs))

    def test_deleted_math_rejected(self):
        damaged = self.md.replace('$x$', 'x', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('公式出现数量不一致' in d
                            or '与候选跨度不符' in d for d in diffs))

    def test_changed_tex_rejected(self):
        payload = copy.deepcopy(self.payload)
        next(c for c in payload['correspondences']
             if c.get('node') == 'math[2]')['tex'] = 'y=2'
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('表达式与原节点不符' in d for d in diffs))

    def test_changed_kind_rejected(self):
        payload = copy.deepcopy(self.payload)
        next(c for c in payload['correspondences']
             if c.get('node') == 'math[1]')['kind'] = 'inline'
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('类型冲突' in d for d in diffs))

    def test_tampered_range_rejected(self):
        payload = copy.deepcopy(self.payload)
        next(c for c in payload['correspondences']
             if c.get('node') == 'math[2]')['md_end'] += 5
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('与实际写出内容不符' in d
                            or '出现身份传递区间' in d for d in diffs))

    def test_moved_formula_rejected(self):
        damaged = self.md.replace('Alpha $x$ beta.', 'Alpha beta. $x$', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('出现身份传递区间' in d or '正文流' in d
                            or '候选内容被改写' in d for d in diffs))

    def test_joint_omission_still_rejected_by_source_snapshot(self):
        payload = copy.deepcopy(self.payload)
        payload['correspondences'] = [
            c for c in payload['correspondences']
            if c.get('node') != 'math[6]']
        damaged = self.md.replace('$x$', '', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              payload)
        self.assertTrue(any('公式出现数量不一致' in d
                            or '与候选跨度不符' in d for d in diffs))

    def test_failure_keeps_inputs_unchanged(self):
        md_before = self.md
        payload_before = copy.deepcopy(self.payload)
        damaged = self.md.replace('Alpha $x$ beta.', 'Alpha beta. $x$', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(diffs)
        self.assertEqual(self.md, md_before)
        self.assertEqual(self.payload, payload_before)


class ConsumptionPathTest(unittest.TestCase):
    """19-6：本票正例接入现有拆包保护/检查投影消费入口。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_package_problems_contained_and_split(self):
        contained = latexml.correspondence_package_problems(
            self.payload, [(0, len(self.md) + 1)])
        self.assertEqual(contained, [])
        zcorr = next(c for c in _math_corrs(self.payload)
                     if c['node'] == 'math[4]')
        mid = (zcorr['md_start'] + zcorr['md_end']) // 2
        problems = latexml.correspondence_package_problems(
            self.payload, [(0, mid), (mid, len(self.md) + 1)])
        self.assertTrue(any('跨多个工作包' in p for p in problems))

    def test_check_policy_projection(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(self.payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            policy = latexml.check_policy_projection(
                self.payload, 0, len(self.md) + 1, path)
            self.assertIn('nodes', policy)
            before = copy.deepcopy(policy)
            next(c for c in self.payload['correspondences']
                 if c.get('node') == 'math[2]')['tex'] = 'y=2'
            changed = latexml.check_policy_projection(
                self.payload, 0, len(self.md) + 1, path)
            self.assertNotEqual(before, changed)
        finally:
            os.unlink(path)


GROUP_RAW = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>T19 Grp</title></head>
<body>
<article id="paper" class="ltx_document">
<h1 class="ltx_title">T19 Grp</h1>
<p class="ltx_p">Before.</p>
<table class="ltx_equationgroup ltx_eqn_table" id="S2.Ex3">
<tbody>
<tr class="ltx_equation ltx_eqn_row">
<td class="ltx_td ltx_eqn_cell">$dx$</td>
<td class="ltx_td ltx_eqn_cell">$\\leftarrow f$</td>
<td class="ltx_eqn_cell ltx_eqn_eqno">($B$)</td>
</tr>
<tr class="ltx_equation ltx_eqn_row">
<td class="ltx_td ltx_eqn_cell">$g$</td>
<td class="ltx_td ltx_eqn_cell">$\\leftarrow h$</td>
</tr>
</tbody>
</table>
<p class="ltx_p">After.</p>
</article>
</body>
</html>
"""


class MathGroupEqnoOrderTest(unittest.TestCase):
    """公式组表式号格内的公式出现：DOM 序先于后续内容行，但输出序为
    “内容格先行、式号随后”，出现流按输出序配对（torchgpipe S2.Ex3
    真实形态回归）。"""

    def _adapt_group(self):
        md, corrs, unres, _f, adapter = latexml.adapt_latexml_snapshot(
            GROUP_RAW, None, [], str(FIXTURE.parent))
        identity = dict(IDENTITY, expected_title='T19 Grp',
                        actual_title='T19 Grp')
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': '<inline>',
                         'sha256': latexml.sha256_text(GROUP_RAW)},
            'paper_identity': identity,
            'decisions': [], 'correspondences': corrs, 'unresolved': unres,
            'groups': adapter.groups,
        }
        return md, payload

    def test_eqno_math_output_order_roundtrip_clean(self):
        md, payload = self._adapt_group()
        by_tex = {c['tex']: c for c in _math_corrs(payload)}
        # 式号格公式 B 在 DOM 中先于内容行 g，输出区间却在 g 之后
        self.assertGreater(by_tex['B']['md_start'], by_tex['g']['md_start'])
        self.assertEqual(md[by_tex['B']['md_start']:by_tex['B']['md_end']],
                         '$B$')
        self.assertEqual(reconcile_latexml_to_markdown(
            GROUP_RAW, md, None, payload), [])

    def test_eqno_content_swap_rejected(self):
        md, payload = self._adapt_group()
        payload = copy.deepcopy(payload)
        bcorr = next(c for c in payload['correspondences']
                     if c.get('tex') == 'B')
        gcorr = next(c for c in payload['correspondences']
                     if c.get('tex') == 'g')
        rb = (bcorr['md_start'], bcorr['md_end'])
        rg = (gcorr['md_start'], gcorr['md_end'])
        bcorr['md_start'], bcorr['md_end'] = rg
        gcorr['md_start'], gcorr['md_end'] = rb
        diffs = reconcile_latexml_to_markdown(GROUP_RAW, md, None, payload)
        self.assertTrue(any('出现身份传递区间' in d for d in diffs))


class NonSplittableHostTest(unittest.TestCase):
    """块级公式落入不可拆宿主（简单表单元格）fail-fast，不静默产出。"""

    def test_simple_table_block_mathml_rejected(self):
        raw = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
               '<title>T19 Tbl</title></head><body>'
               '<article class="ltx_document">'
               '<h1 class="ltx_title">T19 Tbl</h1>'
               '<table><tr><td>Cell <math alttext="a+b" display="block">'
               '<mi>a</mi></math></td></tr></table>'
               '</article></body></html>')
        with self.assertRaises(ValueError) as ctx:
            latexml.adapt_latexml_snapshot(raw, None, [],
                                           str(FIXTURE.parent))
        self.assertIn('不可拆宿主', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
