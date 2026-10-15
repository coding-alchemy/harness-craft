"""二期 ticket 02：原 TeX 保真、公式组与限定多行公式全链路。

覆盖验收 02-1～02-8 的底层定向用例：scan_math 来源上下文（D2，默认
行为不变）、多行行内逐字输出与跨行识别、公式组/式号独立重建与损伤
拒绝、\penalty/竖线/&/边界空白保真、包切点保护、跨包对应拒绝、
check_policy 组投影与导出受约束分类游标。
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from latexml_test_support import adapt_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown
from _verification import (MathSpan, SourceMathContext, compare_math_spans,
                           fenced_line_numbers, scan_math, scan_math_spans)

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_groups.html'

IDENTITY = {
    'expected_title': 'T02 Fixture', 'actual_title': 'T02 Fixture',
    'paper_id': '2202.00002', 'version': 'v1',
    'final_url': 'https://example.org/abs/2202.00002v1',
    'retrieved_at': '2026-10-02T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}

MULTI_TEX = 'p +\nq = r'


class ScanMathContextTest(unittest.TestCase):
    """02-3：限定来源上下文只授予已确认多行行内的跨行识别。"""

    TEXT = 'a $p +\nq = r$ b'

    def test_no_context_inline_cross_line_is_issue(self):
        scan = scan_math(self.TEXT)
        self.assertEqual(scan.spans, ())
        self.assertTrue(any('未闭合的行内公式' in i.reason
                            for i in scan.issues))

    def test_confirmed_context_enables_cross_line(self):
        ctx = SourceMathContext([(MULTI_TEX, 0)])
        scan = scan_math(self.TEXT, source_context=ctx)
        self.assertEqual(len(scan.spans), 1)
        self.assertEqual(scan.spans[0].kind, 'inline')
        self.assertEqual(scan.spans[0].expr, MULTI_TEX)
        self.assertEqual(scan.issues, ())

    def test_context_mismatch_still_issue(self):
        ctx = SourceMathContext([('other\nexpr', 0)])
        scan = scan_math(self.TEXT, source_context=ctx)
        self.assertEqual(scan.spans, ())
        self.assertTrue(any('不匹配' in i.reason for i in scan.issues))

    def test_single_line_entries_ignored_by_context(self):
        # 只含单行表达式的上下文不授予任何跨行资格
        ctx = SourceMathContext([('short', 0)])
        self.assertFalse(ctx)
        scan = scan_math(self.TEXT, source_context=ctx)
        self.assertEqual(scan.spans, ())

    def test_currency_code_escape_exclusions_unchanged(self):
        ctx = SourceMathContext([(MULTI_TEX, 0)])
        self.assertEqual(scan_math('`$x$` $y$').spans[0].expr, 'y')
        self.assertEqual(scan_math('$5 and $100').spans, ())
        masked = scan_math('\\$x$ $y$')
        self.assertEqual([s.expr for s in masked.spans], ['y'])

    def test_scan_math_spans_projection_same_implementation(self):
        ctx = SourceMathContext([(MULTI_TEX, 0)])
        spans = scan_math_spans(self.TEXT, source_context=ctx)
        self.assertEqual([(s.kind, s.expr) for s in spans],
                         [('inline', MULTI_TEX)])


class TexFidelityTest(unittest.TestCase):
    """02-1/02-2：原 TeX（命令/竖线/&/空白）逐字保持，包装与原式区分。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = adapt_fixture(FIXTURE, IDENTITY)

    def test_commands_pipes_entities_verbatim(self):
        self.assertIn('$a|b \\penalty 0<c & d$', self.md)
        corr = next(c for c in self.payload['correspondences']
                    if c.get('node') == 'math[1]')
        self.assertEqual(corr['tex'], 'a|b \\penalty 0<c & d')

    def test_multi_line_inline_verbatim(self):
        self.assertIn('$p +\nq = r$', self.md)
        corr = next(c for c in self.payload['correspondences']
                    if c.get('node') == 'math[2]')
        self.assertEqual(corr['tex'], MULTI_TEX)
        self.assertEqual(corr['kind'], 'inline')

    def test_display_boundary_whitespace_preserved(self):
        corr = next(c for c in self.payload['correspondences']
                    if c.get('node') == 'math[5]')
        self.assertEqual(corr['tex'], ' \\sum_{i} i \\ge 0 ')
        self.assertIn('$$\n \\sum_{i} i \\ge 0 \n$$', self.md)

    def test_roundtrip_clean(self):
        self.assertEqual(reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload), [])

    def test_folded_newline_rejected(self):
        damaged = self.md.replace('$p +\nq = r$', '$p + q = r$', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_enlarged_range_swallowing_prose_rejected(self):
        payload = copy.deepcopy(self.payload)
        corr = next(c for c in payload['correspondences']
                    if c.get('node') == 'math[2]')
        corr['md_end'] += 6  # 把正文 tail. 吞进公式范围
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('与实际写出内容不符' in d
                            or '出现身份传递区间' in d or '正文流' in d
                            for d in diffs))

    def test_forged_correspondence_rejected(self):
        # 伪造对应（把换行登记成已折叠的式子）不能由自报范围获得资格：
        # 独立 alttext 事实逐字不符即拒绝
        payload = copy.deepcopy(self.payload)
        corr = next(c for c in payload['correspondences']
                    if c.get('node') == 'math[2]')
        corr['tex'] = 'p + q = r'
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('等数替换' in d or '表达式与原节点不符' in d
                            for d in diffs))

    def test_precise_compare_multiline_verbatim(self):
        src = [MathSpan(kind='inline', expr=MULTI_TEX, raw='$%s$' % MULTI_TEX,
                        start=0, end=0, start_line=1)]
        ok = [MathSpan(kind='inline', expr=MULTI_TEX, raw='x',
                       start=0, end=0, start_line=1)]
        folded = [MathSpan(kind='inline', expr='p + q = r', raw='y',
                           start=0, end=0, start_line=1)]
        self.assertEqual(compare_math_spans(src, ok, precise=True)[0], [])
        self.assertTrue(compare_math_spans(src, folded, precise=True)[0])


class MathGroupTest(unittest.TestCase):
    """02-4：组/成员序/式号可回查；换序/改式号/漏组按目标原因拒绝。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = adapt_fixture(FIXTURE, IDENTITY)

    def test_group_record_and_emission(self):
        groups = self.payload['groups']
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group['members'], ['math[3]', 'math[4]'])
        self.assertEqual([e['text'] for e in group['eqnos']], ['(1a)', '(1b)'])
        self.assertEqual(group['eqnos'][0]['target'], '#e1')
        self.assertIn('(1a)', self.md)
        self.assertNotIn('\\tag', self.md)

    def test_member_correspondence_annotated(self):
        corr = next(c for c in self.payload['correspondences']
                    if c.get('node') == 'math[4]')
        self.assertEqual(corr['group'], 'group[1]')
        self.assertEqual(corr['group_index'], 1)

    def test_swap_members_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'][0]['members'] = ['math[4]', 'math[3]']
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('成员或顺序' in d for d in diffs))

    def test_changed_eqno_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'][0]['eqnos'][0]['text'] = '(2a)'
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('式号' in d for d in diffs))

    def test_missing_group_declaration_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['groups'] = []
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('漏组' in d for d in diffs))

    def test_swapped_member_output_rejected(self):
        a = '$$\nx+y=z\n$$\n\n(1a)'
        b = '$$\nu=v\n$$\n\n(1b)'
        damaged = self.md.replace(a + '\n\n' + b, b + '\n\n' + a, 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))


class PackageProtectionTest(unittest.TestCase):
    """02-5：多行行内覆盖行受保护；对应跨包拒绝。"""

    def test_protected_lines_cover_multi_line_inline(self):
        import split_work_packages as swp
        text = 'head\n\npara $p +\nq = r$ tail\n\nafter\n'
        # 覆盖行集合含公式全部行，_parse_blocks 吸收为单个原子 math_block，
        # 候选切点只落块间（真实拆分保护见验收日志 03_split）
        scan = scan_math(text, source_context=SourceMathContext(
            [(MULTI_TEX, 0)]))
        protected = set()
        for span in scan.spans:
            end_line = text.count('\n', 0, span.end - 1) + 1
            if end_line > span.start_line:
                protected.update(range(span.start_line, end_line + 1))
        self.assertIn(4, protected)  # 'q = r$ tail' 行受保护
        blocks = swp._parse_blocks(text.split('\n'),
                                   fenced_line_numbers(text), protected)
        math_blocks = [b for b in blocks if b.kind == 'math_block']
        self.assertEqual(len(math_blocks), 1)
        self.assertEqual((math_blocks[0].start, math_blocks[0].end),
                         (2, 4))  # 原子块覆盖公式全部行，切点只落块间

    def test_cross_package_correspondence_rejected(self):
        _raw, md, payload, _ad = adapt_fixture(FIXTURE, IDENTITY)
        payload = json.loads(json.dumps(payload))
        corr = next(c for c in payload['correspondences']
                    if c.get('node') == 'math[2]')
        mid = (corr['md_start'] + corr['md_end']) // 2
        problems = latexml.correspondence_package_problems(
            payload, [(0, mid), (mid, len(md) + 1)])
        self.assertTrue(any('跨多个工作包' in p for p in problems))
        contained = latexml.correspondence_package_problems(
            payload, [(0, len(md) + 1)])
        self.assertEqual(contained, [])


class CheckPolicyGroupTest(unittest.TestCase):
    """02-8：check_policy 投影公式组；组事实变化使相关包失效。"""

    def test_projection_includes_groups(self):
        _raw, md, payload, _ad = adapt_fixture(FIXTURE, IDENTITY)
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            start = md.index('(1a)') - 10
            policy = latexml.check_policy_projection(payload, start,
                                                     len(md) + 1, path)
            self.assertEqual(len(policy['groups']), 1)
            before = copy.deepcopy(policy)
            payload['groups'][0]['eqnos'][0]['text'] = '(2a)'
            changed = latexml.check_policy_projection(payload, start,
                                                      len(md) + 1, path)
            self.assertNotEqual(before, changed)
        finally:
            os.unlink(path)


class ExportCursorTest(unittest.TestCase):
    """02-6：受约束分类严格优先、定位回退，输出永远逐字。"""

    def test_strict_and_locate(self):
        from export_pdf import ConfirmedMathCursor
        entries = [('inline', MULTI_TEX),
                   ('block', ' \\sum_{i} i \\ge 0 ')]
        cursor = ConfirmedMathCursor(entries)
        self.assertEqual(
            cursor.resolve('p +\nq = r', False),
            (MULTI_TEX, 'inline', 'source_constrained'))
        # 插件裁掉块级边界空白：定位回退，输出仍为确认原表达式
        self.assertEqual(
            cursor.resolve('\\sum_{i} i \\ge 0', True),
            (' \\sum_{i} i \\ge 0 ', 'display', 'source_constrained'))
        self.assertEqual(cursor.remaining(), 0)

    def test_type_mismatch_falls_back(self):
        from export_pdf import ConfirmedMathCursor
        cursor = ConfirmedMathCursor([('block', 'x')])
        self.assertIsNone(cursor.resolve('x', False))
        self.assertEqual(cursor.remaining(), 1)


if __name__ == '__main__':
    unittest.main()
