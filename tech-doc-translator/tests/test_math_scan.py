"""共享公式扫描与逐项比较的固定语义验收（任务 02：公式内容与顺序）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_math_spans,
    extract_approved_extra_math,
    scan_math_spans,
)


def kinds(spans):
    return [(s.kind, s.expr) for s in spans]


class ScanMathSpansTest(unittest.TestCase):

    def test_inline_and_block_in_order_with_offsets(self):
        text = 'a $x+1$ b\n\n$$\ny = 2z\n$$\n\nc $w$ d\n'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans),
                         [('inline', 'x+1'), ('block', '\ny = 2z\n'),
                          ('inline', 'w')])
        self.assertEqual(text[spans[0].start:spans[0].end], '$x+1$')
        self.assertEqual(text[spans[1].start:spans[1].end], '$$\ny = 2z\n$$')
        self.assertEqual(spans[0].start_line, 1)
        self.assertEqual(spans[1].start_line, 3)
        self.assertEqual(spans[2].start_line, 7)

    def test_code_fence_inline_code_escape_and_currency_excluded(self):
        text = (
            '```c\nint d = $x$;\n```\n'
            '行内代码 `$not math$` 保持原样。\n'
            '转义 \\$5 不是公式，$a+b$ 是公式。\n'
            '价格为 $5 和 $10，不是公式。\n'
        )
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('inline', 'a+b')])

    def test_currency_heuristics(self):
        text = '共 $100，另收 $200。\n单价 $5 和 $10 均非公式。\n'
        self.assertEqual(scan_math_spans(text), [])
        # 无闭合美元也不是公式
        self.assertEqual(scan_math_spans('价格 $100\n'), [])

    def test_inline_math_cannot_span_lines_but_block_can(self):
        text = '$a\nb$ 不是行内公式\n\n$$\nc\nd\n$$\n'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('block', '\nc\nd\n')])

    def test_backslash_dollar_and_wrapped_inline(self):
        text = r'成本 \$3，历史包装 $\(N\)$ 保持。'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('inline', r'\(N\)')])

    def test_block_math_masked_before_inline_scan(self):
        text = '$$x$$ 正文'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('block', 'x')])


class CompareMathSpansTest(unittest.TestCase):

    def scan(self, text):
        return scan_math_spans(text)

    def test_identical_no_diffs(self):
        s = self.scan('$a+b$\n$$c$$\n')
        self.assertEqual(compare_math_spans(s, s, 'a.md', 'b.md'), ([], []))

    def test_operator_change_reported(self):
        s = self.scan('$a+b$ 后文\n')
        d = self.scan('$a-b$ 后文\n')
        diffs, _ = compare_math_spans(s, d, 'src.md', 'doc.md')
        self.assertTrue(any('表达式不一致' in x and "'a+b'" in x
                            and "'a-b'" in x and 'src.md' in x
                            for x in diffs))

    def test_swap_same_count_reported(self):
        s = self.scan('$x+1$ 中 $y+2$\n')
        d = self.scan('$y+2$ 中 $x+1$\n')
        diffs, _ = compare_math_spans(s, d, 'a.md', 'b.md')
        self.assertTrue(any('表达式不一致' in x for x in diffs))

    def test_kind_change_reported(self):
        s = self.scan('行内 $x+1$ 公式\n')
        d = self.scan('块级 $$x+1$$ 公式\n')
        diffs, _ = compare_math_spans(s, d, 'a.md', 'b.md')
        self.assertTrue(any('类型不一致' in x for x in diffs))

    def test_missing_formula_reported(self):
        s = self.scan('$a$ 与 $b$\n')
        d = self.scan('$a$ 与\n')
        diffs, _ = compare_math_spans(s, d, 'a.md', 'b.md')
        self.assertTrue(any('公式数不一致' in x for x in diffs))

    def test_extra_formula_fails_without_approval(self):
        s = self.scan('$a$ 正文\n')
        d = self.scan('$a$ 正文\n\n译注 $n^{2}$ 说明\n')
        diffs, _ = compare_math_spans(s, d, 'a.md', 'b.md')
        self.assertTrue(any('公式数不一致' in x or '多余' in x for x in diffs))

    def test_approved_extra_math_exempted_but_masks_nothing(self):
        s = self.scan('$a$ 与 $b$\n')
        # 译注公式获准：豁免后逐项一致
        d = self.scan('$a$ 与 $b$\n译注 $n^{2}$\n')
        diffs, warns = compare_math_spans(
            s, d, 'a.md', 'b.md', approved_extra_exprs=['n^{2}'])
        self.assertEqual(diffs, [])
        self.assertTrue(any('获准译注' in w for w in warns))
        # 获准译注不掩盖源公式遗漏：删掉 $b$ 后仍失败
        d2 = self.scan('$a$ 与\n译注 $n^{2}$\n')
        diffs, _ = compare_math_spans(
            s, d2, 'a.md', 'b.md', approved_extra_exprs=['n^{2}'])
        self.assertTrue(any('公式数不一致' in x for x in diffs))

    def test_wrapping_consistent_warns_new_wrapping_fails(self):
        s = self.scan(r'历史 $\(N\)$ 保持\n')
        d = self.scan(r'历史 $\(N\)$ 保持\n')
        diffs, warns = compare_math_spans(s, d, 'a.md', 'b.md')
        self.assertEqual(diffs, [])
        self.assertTrue(any('历史数学包装' in w for w in warns))
        # 译文新增包装（源为裸公式）→ 失败
        d2 = self.scan(r'历史 $\(M\)$ 新增\n')
        diffs, _ = compare_math_spans(s, d2, 'a.md', 'b.md')
        self.assertTrue(diffs)


class ExtractApprovedExtraMathTest(unittest.TestCase):

    def test_extract_repeated_flag(self):
        rest, exprs = extract_approved_extra_math(
            ['doc.md', 'src.md', '--approved-extra-math', 'n^{2}',
             '--approved-extra-math', 'x', '标题'])
        self.assertEqual(rest, ['doc.md', 'src.md', '标题'])
        self.assertEqual(exprs, ['n^{2}', 'x'])

    def test_no_flag(self):
        rest, exprs = extract_approved_extra_math(['a', 'b'])
        self.assertEqual((rest, exprs), (['a', 'b'], []))


if __name__ == '__main__':
    unittest.main()
