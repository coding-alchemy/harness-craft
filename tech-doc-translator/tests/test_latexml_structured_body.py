"""二期 ticket 20：标题、题注、算法与条目正文。

覆盖验收 20-1～20-7：各角色（标题/图题/算法题注/算法直属 p/pre/table/
列表/参考文献/清单行）保留角色、所属与有序内容并独立对账；算法直属段落
误拒与条目内纯展示公式误拒反例通过；删内容、改类型/表达式、错题注或
条目归属、同内容身份交换、同条目内换序均按目标原因拒绝；代码中的美元
记法不取得数学资格。
"""
import copy
import sys
import unittest
from pathlib import Path

from latexml_test_support import adapt_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / (
    'latexml_structured.html')

IDENTITY = {
    'expected_title': 'T20 Fixture', 'actual_title': 'T20 Fixture',
    'paper_id': '2210.00020', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00020v1',
    'retrieved_at': '2026-10-10T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}


def _corr(payload, node):
    return next(c for c in payload['correspondences']
                if c.get('node') == node)


def _reconcile(raw, md, payload):
    return reconcile_latexml_to_markdown(raw, md, None, payload)


class RoleFactsTest(unittest.TestCase):
    """20-1/20-2：各角色身份、层级/编号、父属与精确区间。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = adapt_fixture(FIXTURE, IDENTITY)

    def test_roundtrip_clean(self):
        self.assertEqual(_reconcile(self.raw, self.md, self.payload), [])

    def test_heading_level_and_math(self):
        corr = _corr(self.payload, 'h2[1]')
        self.assertEqual(corr['level'], 2)
        self.assertEqual(
            self.md[corr['md_start']:corr['md_end']], '## Head $a$ here')
        math = _corr(self.payload, 'math[1]')
        self.assertTrue(corr['md_start'] < math['md_start']
                        < math['md_end'] < corr['md_end'])

    def test_figure_caption_parenting(self):
        c1 = _corr(self.payload, 'figcaption[1]')
        self.assertEqual((c1['figure'], c1['subfigure']), ('figure[1]', None))
        c2 = _corr(self.payload, 'figcaption[2]')
        self.assertEqual((c2['figure'], c2['subfigure']), ('figure[2]', 1))
        c3 = _corr(self.payload, 'figcaption[3]')
        self.assertEqual((c3['figure'], c3['subfigure']), ('figure[2]', None))
        img2 = _corr(self.payload, 'img[2]')
        self.assertEqual((img2['figure'], img2['subfigure']),
                         ('figure[2]', 1))

    def test_algorithm_title_separate_from_body(self):
        algo = _corr(self.payload, 'algorithm')
        self.assertEqual(algo['title'], 'Algorithm 1: mix $t$')
        self.assertEqual(self.md[algo['md_start']:algo['md_end']],
                         '[ALGORITHM] Algorithm 1: mix $t$')
        # 直属段落保留 p 节点身份与精确区间，不与题注合并
        p1 = _corr(self.payload, 'p[1]')
        self.assertEqual(self.md[p1['md_start']:p1['md_end']],
                         'Direct step $s_1$ here.')

    def test_algorithm_direct_pre_is_code_fence(self):
        self.assertIn('```\ncode $not math$ stays\n```', self.md)
        # 代码中的美元记法不取得数学资格
        for c in self.payload['correspondences']:
            if c.get('content_type') == 'math':
                self.assertNotEqual(c['tex'], 'not math')

    def test_algorithm_direct_table_dispatched(self):
        tbl = _corr(self.payload, 'table[1]')
        self.assertEqual(tbl['conversion']['style'], 'simple')
        self.assertEqual(self.md[tbl['md_start']:tbl['md_end']],
                         '[TABLE]\nak | av\n--- | ---')

    def test_listing_lines_with_math(self):
        corr = _corr(self.payload, 'listing[1]')
        self.assertEqual(self.md[corr['md_start']:corr['md_end']],
                         'line $m$ one\n\nplain $p$ two')

    def test_mixed_source_same_expression_distinct_identity(self):
        # MathML r（math[8]）与字面 r（math[11]）各有精确区间
        m8 = _corr(self.payload, 'math[8]')
        m11 = _corr(self.payload, 'math[11]')
        self.assertEqual((m8['tex'], m11['tex']), ('r', 'r'))
        self.assertNotEqual((m8['md_start'], m8['md_end']),
                            (m11['md_start'], m11['md_end']))
        self.assertEqual(self.md[m8['md_start']:m8['md_end']], '$r$')
        self.assertEqual(self.md[m11['md_start']:m11['md_end']], '$r$')


class ItemDisplayMathTest(unittest.TestCase):
    """20-4：条目内纯展示公式误拒反例通过；行内/展示类型保持。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = adapt_fixture(FIXTURE, IDENTITY)

    def test_display_math_in_item_split_layout(self):
        self.assertIn('- Display\n\n$$\nD=1\n$$\n\ntail.', self.md)
        corr = _corr(self.payload, 'math[7]')
        self.assertEqual(corr['kind'], 'block')
        self.assertEqual(self.md[corr['md_start']:corr['md_end']],
                         '$$\nD=1\n$$')

    def test_display_math_flanking_text_reconciled(self):
        # 展示公式两侧文字各自参与对账：删去尾部文字即定位失败
        damaged = self.md.replace('\n\ntail.\n', '\n')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_literal_and_mathml_items(self):
        q = _corr(self.payload, 'math[6]')
        u = _corr(self.payload, 'math[10]')
        self.assertEqual((q['kind'], u['kind']), ('inline', 'inline'))
        self.assertIn('- First $q$ item.', self.md)
        self.assertIn('- Pure literal $u$ item.', self.md)


class DamageRejectionTest(unittest.TestCase):
    """20-6：删内容/改类型/改表达式/错归属/身份交换/同条换序。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = adapt_fixture(FIXTURE, IDENTITY)

    def test_same_expression_identity_swap_rejected(self):
        payload = copy.deepcopy(self.payload)
        a, b = _corr(payload, 'math[8]'), _corr(payload, 'math[11]')
        ra, rb = (a['md_start'], a['md_end']), (b['md_start'], b['md_end'])
        a['md_start'], a['md_end'] = rb
        b['md_start'], b['md_end'] = ra
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('出现身份传递区间' in d for d in diffs))

    def test_wrong_caption_parent_rejected(self):
        payload = copy.deepcopy(self.payload)
        _corr(payload, 'figcaption[1]')['figure'] = 'figure[2]'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('归属不符' in d for d in diffs))

    def test_math_moved_across_items_rejected(self):
        damaged = self.md.replace(
            'First $q$ item.', 'First $q$ $u$ item.').replace(
            'Pure literal $u$ item.', 'Pure literal item.')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('出现身份传递区间' in d or '额外输出' in d
                            for d in diffs))

    def test_intra_item_reorder_rejected(self):
        damaged = self.md.replace('First $q$ item.', 'First item. $q$')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('出现身份传递区间' in d or '正文流' in d
                            for d in diffs))

    def test_changed_caption_number_rejected(self):
        damaged = self.md.replace('Figure 1: curve', 'Figure 2: curve', 1)
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('图题 figcaption[1]' in d or '正文流' in d
                            for d in diffs))

    def test_changed_heading_level_rejected(self):
        damaged = self.md.replace('## Head $a$ here', '### Head $a$ here')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any("'h', 2" in d and "'h', 3" in d
                            for d in diffs))

    def test_deleted_algorithm_paragraph_rejected(self):
        damaged = self.md.replace('Direct step $s_1$ here.\n\n', '')
        diffs = _reconcile(self.raw, damaged, self.payload)
        self.assertTrue(any('p[1]' in d for d in diffs))

    def test_changed_algorithm_caption_math_rejected(self):
        payload = copy.deepcopy(self.payload)
        _corr(payload, 'math[4]')['tex'] = 't2'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('表达式与原节点不符' in d for d in diffs))

    def test_changed_math_kind_rejected(self):
        payload = copy.deepcopy(self.payload)
        _corr(payload, 'math[7]')['kind'] = 'inline'
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('类型冲突' in d for d in diffs))

    def test_forged_math_in_code_fence_rejected(self):
        payload = copy.deepcopy(self.payload)
        at = self.md.index('$not math$')
        payload['correspondences'].append({
            'node': 'math[99]', 'content_type': 'math', 'section': 2,
            'md_start': at, 'md_end': at + 10,
            'conversion': {'delimiter': '$', 'wrap_newline': False},
            'kind': 'inline', 'tex': 'not math'})
        diffs = _reconcile(self.raw, self.md, payload)
        self.assertTrue(any('math[99]' in d and '不存在' in d
                            for d in diffs))


class WrappedContainerTest(unittest.TestCase):
    """20-3：透明包装后同型内容与直属节点同一语义。"""

    def test_wrapped_algorithm_paragraph_clean(self):
        raw = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
               '<title>T</title></head><body><article class="ltx_document">'
               '<h1 class="ltx_title">T</h1>'
               '<div class="ltx_algorithm"><div class="ltx_title">A</div>'
               '<div><p>Wrap <math alttext="w" display="inline">'
               '<mi>w</mi></math> ok.</p></div></div>'
               '</article></body></html>')
        md, corrs, unres, _f, adapter = latexml.adapt_latexml_snapshot(
            raw, None, [], str(FIXTURE.parent))
        identity = dict(IDENTITY, expected_title='T', actual_title='T')
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': '<inline>',
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': identity,
            'decisions': [], 'correspondences': corrs, 'unresolved': unres,
        }
        self.assertEqual(_reconcile(raw, md, payload), [])
        math = _corr(payload, 'math[1]')
        self.assertEqual(md[math['md_start']:math['md_end']], '$w$')


class ConsumptionPathTest(unittest.TestCase):
    """20-7：本票正例接入现有拆包保护消费入口。"""

    def test_package_problems(self):
        _raw, md, payload, _adapter = adapt_fixture(FIXTURE, IDENTITY)
        contained = latexml.correspondence_package_problems(
            payload, [(0, len(md) + 1)])
        self.assertEqual(contained, [])
        corr = _corr(payload, 'math[7]')
        mid = (corr['md_start'] + corr['md_end']) // 2
        problems = latexml.correspondence_package_problems(
            payload, [(0, mid), (mid, len(md) + 1)])
        self.assertTrue(any('跨多个工作包' in p for p in problems))


if __name__ == '__main__':
    unittest.main()
