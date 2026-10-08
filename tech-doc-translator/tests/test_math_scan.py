"""共享公式扫描与逐项比较的固定语义验收（任务 02：公式内容与顺序）。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_math_spans,
    extract_approved_extra_math,
    markdown_table_row_lines,
    scan_math,
    scan_math_spans,
)


def kinds(spans):
    return [(s.kind, s.expr) for s in spans]


class BaseDependencyDeclarationTest(unittest.TestCase):
    """基础依赖声明与核验模块导入面一致（普通翻译不安装 PDF 依赖）。"""

    def test_markdown_it_declared_in_base_requirements(self):
        # S1：_verification（翻译核验共用模块）顶层导入 markdown_it，
        # markdown-it-py 必须声明在基础 requirements.txt 中，不能只
        # 留在 PDF 可选依赖里
        skill_dir = (Path(__file__).resolve().parents[1]
                     / 'skills/tech-doc-translator')
        text = (skill_dir / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('markdown-it-py', text)


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
        scan = scan_math(text)
        self.assertEqual(scan.spans, ())
        self.assertEqual(scan.issues, ())
        # 无闭合美元也不是公式
        self.assertEqual(scan_math_spans('价格 $100\n'), [])
        self.assertEqual(scan_math('价格 $100\n').issues, ())

    def test_inline_math_cannot_span_lines_but_block_can(self):
        text = '$a\nb$ 不是行内公式\n\n$$\nc\nd\n$$\n'
        scan = scan_math(text)
        self.assertEqual(kinds(scan.spans), [('block', '\nc\nd\n')])
        # 行内不跨行吞入正文：$a 是无法闭合的非货币候选，定位 issue
        self.assertEqual(len(scan.issues), 1)
        self.assertEqual(scan.issues[0].raw, '$')
        self.assertEqual(scan.issues[0].start_line, 1)

    def test_backslash_dollar_and_wrapped_inline(self):
        text = r'成本 \$3，历史包装 $\(N\)$ 保持。'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('inline', r'\(N\)')])

    def test_block_math_masked_before_inline_scan(self):
        text = '$$x$$ 正文'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans), [('block', 'x')])


class ScanMathAdjacentInlineTest(unittest.TestCase):
    """R2/D2：相邻行内公式与数字邻接公式按上下文逐一定界（一期需求 §3.1
    直接验收样例）；预期值由原输入含义手工写出。"""

    def test_adjacent_sample_four_inlines(self):
        text = ('gain $x$$\\sim$ noise and more prose here $y$$\\le$ '
                'bound end')
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans),
                         [('inline', 'x'), ('inline', '\\sim'),
                          ('inline', 'y'), ('inline', '\\le')])
        # 原切片、顺序、行号与偏移可回查；相邻正文不被吞入表达式
        self.assertEqual(text[spans[0].start:spans[0].end], '$x$')
        self.assertEqual(text[spans[1].start:spans[1].end], '$\\sim$')
        self.assertEqual(text[spans[2].start:spans[2].end], '$y$')
        self.assertEqual(text[spans[3].start:spans[3].end], '$\\le$')
        self.assertEqual([s.start_line for s in spans], [1, 1, 1, 1])
        self.assertEqual(text[spans[0].end:spans[1].start], '')
        self.assertEqual(text[spans[2].end:spans[3].start], '')

    def test_adjacent_sample_digit_neighbors(self):
        text = 'speedup of 2$\\times$$\\sim$3 over baseline and $a$ ok'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans),
                         [('inline', '\\times'), ('inline', '\\sim'),
                          ('inline', 'a')])

    def test_digit_adjacent_sample_two_inlines(self):
        # 数字邻接样例：删除或修改任一个必须可定位（比较器反例见下）
        text = '2$\\times$3 and $\\sim$10'
        spans = scan_math_spans(text)
        self.assertEqual(kinds(spans),
                         [('inline', '\\times'), ('inline', '\\sim')])
        self.assertEqual(text[spans[0].start:spans[0].end], '$\\times$')
        self.assertEqual(text[spans[1].start:spans[1].end], '$\\sim$')

    def test_digit_adjacent_damage_counterexamples(self):
        src = scan_math_spans('2$\\times$3 and $\\sim$10\n')
        for damaged, why in (
                ('2$\\times$3 and 10\n', '删除第二个公式'),
                ('2 3 and $\\sim$10\n', '删除第一个公式'),
                ('2$\\div$3 and $\\sim$10\n', '等数换内容'),
                ('$\\sim$10 and 2$\\times$3\n', '换序'),
                ('2$$\\times$$3 and $\\sim$10\n', '改类型')):
            doc = scan_math_spans(damaged)
            diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md')
            self.assertTrue(diffs, '%s 未被检出' % why)

    def test_closing_dollar_followed_by_digit_kept(self):
        # 闭合 $ 后的数字不再否定公式；也不再需要货币式排除误伤
        spans = scan_math_spans('$x$5 and $y$')
        self.assertEqual(kinds(spans), [('inline', 'x'), ('inline', 'y')])

    def test_currency_priority_and_exclusion(self):
        # 数字开头完整公式优先识别；金额片段不构成公式也不制造 issue
        text = '成本 $5 + x$ 与 $5$ 是公式；costs $5 and $10 不是。\n'
        scan = scan_math(text)
        self.assertEqual(kinds(scan.spans),
                         [('inline', '5 + x'), ('inline', '5')])
        self.assertEqual(scan.issues, ())
        self.assertEqual(scan_math_spans('价格 $100\n'), [])
        self.assertEqual(scan_math('价格 $100\n').issues, ())

    def test_unresolved_inline_delimiter_located(self):
        scan = scan_math('前文 $x 后文\n下一行 $ok$\n')
        self.assertEqual(kinds(scan.spans), [('inline', 'ok')])
        self.assertEqual(len(scan.issues), 1)
        issue = scan.issues[0]
        self.assertEqual(issue.start_line, 1)
        self.assertEqual(issue.raw, '$')

    def test_unresolved_block_delimiter_located(self):
        scan = scan_math('$$\n未闭合块级\n')
        self.assertEqual(scan.spans, ())
        self.assertEqual(len(scan.issues), 1)
        self.assertEqual(scan.issues[0].start_line, 1)
        self.assertEqual(scan.issues[0].raw, '$$')

    def test_unresolved_bracket_block_located(self):
        scan = scan_math('\\[ 未闭合\n')
        self.assertEqual(len(scan.issues), 1)
        self.assertEqual(scan.issues[0].raw, '\\[')

    def test_stray_dollar_not_an_issue(self):
        # 行尾/空白后的孤立美元（如 shell 提示符）不是数学候选
        scan = scan_math('$ \n$\nls $ 列目录\n')
        self.assertEqual(scan.spans, ())
        self.assertEqual(scan.issues, ())

    def test_projection_matches_full_scan(self):
        text = 'a $x$ b $$\ny\n$$ c $z\n'
        scan = scan_math(text)
        self.assertEqual(scan_math_spans(text), list(scan.spans))


class ScanMathDigitLeadingUnclosedTest(unittest.TestCase):
    """R6/一期设计 D2：数字开头未闭合候选只有能判定为纯金额片段（数字/
    千分位/小数到空白或行尾）才静默排除；同一行剩余含运算符/孤立单字母
    等数学特征且无法闭合的，定位 issue（原偏移、行号、定界原文）。预期值
    由样例含义手工写出。"""

    def test_unclosed_digit_leading_with_operator_located(self):
        text = '前文 $5 + x 后文\n'
        scan = scan_math(text)
        self.assertEqual(scan.spans, ())
        self.assertEqual(len(scan.issues), 1)
        issue = scan.issues[0]
        self.assertEqual(issue.raw, '$')
        self.assertEqual(issue.start_line, 1)
        self.assertEqual(text[issue.start:issue.end], '$')

    def test_unclosed_double_dollar_digit_leading_located(self):
        text = '前文 $$5 + x 后文\n'
        scan = scan_math(text)
        self.assertEqual(scan.spans, ())
        self.assertEqual(len(scan.issues), 1)
        issue = scan.issues[0]
        self.assertEqual(issue.raw, '$$')
        self.assertEqual(issue.start_line, 1)

    def test_pure_currency_fragments_still_excluded(self):
        for text in ('单个 $100。\n',
                     '共 $1,000.50，另收 $200\n',
                     'costs $5 and $10\n',
                     '价格 $5 元\n',
                     '价格 $$100\n'):
            scan = scan_math(text)
            self.assertEqual(scan.spans, (), text)
            self.assertEqual(scan.issues, (), text)

    def test_digit_leading_complete_spans_unchanged(self):
        scan = scan_math('$5 + x$ 与 $5$ 合法\n')
        self.assertEqual(kinds(scan.spans),
                         [('inline', '5 + x'), ('inline', '5')])
        self.assertEqual(scan.issues, ())


class VerifyTranslationUnclosedDigitCliTest(unittest.TestCase):
    """R6 复现链路：源含 `$5 + x` 未闭合片段、译文整段删除时，
    verify_translation.py 必须 FAIL 并定位到该 issue（静默漏检反例）。"""

    def test_deleted_unclosed_fragment_fails_with_location(self):
        base = Path(tempfile.mkdtemp(prefix='tdt-r6-'))
        try:
            src = base / 'src.md'
            doc = base / 'doc.md'
            src.write_text('# 示例\n\n前文 $5 + x 后文。\n', encoding='utf-8')
            doc.write_text('# 示例\n\n前文 后文。\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable,
                 str(Path(__file__).resolve().parents[1]
                     / 'skills/tech-doc-translator/scripts'
                     / 'verify_translation.py'),
                 str(doc), str(src)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('未解决数学定界', result.stdout)
            self.assertIn('L3', result.stdout)
            self.assertIn('$5 + x', src.read_text(encoding='utf-8'))
        finally:
            shutil.rmtree(base, True)


class ScanMathMaskExclusionTest(unittest.TestCase):
    """掩蔽保持：长反引号/波浪线围栏、行内代码、转义美元继续排除。"""

    def test_long_backtick_and_tilde_fences_excluded(self):
        text = ('````\n$$\n````\n\n~~~~\n$\\sim$\n~~~~\n\n`$x$`\n')
        scan = scan_math(text)
        self.assertEqual(scan.spans, ())
        self.assertEqual(scan.issues, ())

    def test_escaped_dollar_not_delimiter(self):
        scan = scan_math('转义 \\$5 与 \\$x$ 不是公式开头\n')
        # 第二个 \$ 被掩蔽，其后的 x$ 不构成定界对
        self.assertEqual(scan.spans, ())
        self.assertEqual(scan.issues, ())


class ScanMathIssueContractTest(unittest.TestCase):
    """issue 只保存原偏移、行号、定界原文与原因；偏移可回查原输入。"""

    def test_issue_offsets_reference_original_text(self):
        text = 'aaa $x bbb\n'
        scan = scan_math(text)
        issue = scan.issues[0]
        self.assertEqual(text[issue.start:issue.end], '$')
        self.assertEqual(issue.start, 4)
        self.assertEqual(issue.start_line, 1)

    def test_inline_candidate_with_trailing_space_content(self):
        # '$a $b$'：$a 无法构成完整公式（内容首尾须非空白）→ issue；
        # $b$ 仍是合法行内公式
        scan = scan_math('$a $b$\n')
        self.assertEqual(kinds(scan.spans), [('inline', 'b')])
        self.assertEqual(len(scan.issues), 1)
        self.assertEqual(scan.issues[0].start, 0)


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


class LinkLabelMathScanTest(unittest.TestCase):
    """链接标签中的公式参与扫描（S09）：标签内改符号必须可检出；标签内
    转义括号仍不构成公式定界（既有排除目的保持）。"""

    def test_label_math_scanned_and_damage_detected(self):
        src = scan_math_spans('见 [Equation $x$](https://example.com) 说明\n')
        self.assertEqual(kinds(src), [('inline', 'x')])
        doc = scan_math_spans('见 [Equation $y$](https://example.com) 说明\n')
        diffs, _ = compare_math_spans(src, doc, 'a.md', 'b.md')
        self.assertTrue(any("'x'" in d and "'y'" in d for d in diffs))
        # 未变公式正例通过
        same = scan_math_spans('见 [Equation $x$](https://example.com) 说明\n')
        self.assertEqual(compare_math_spans(src, same, 'a.md', 'b.md'),
                         ([], []))

    def test_escaped_brackets_in_label_not_block_math(self):
        text = r'常量 [Python Constant\[T\]](https://example.com) 说明'
        self.assertEqual(scan_math_spans(text), [])


class TablePipeNormalizationTest(unittest.TestCase):
    """译文表格行管道转义归一（§8.5）：仅真实表格行归一，普通正文含管道
    不归一（S10）。"""

    def test_markdown_table_row_lines_detection(self):
        # GFM 语义：表格块由表头 + 分隔行识别，其后连续含管道行为数据行；
        # 空行结束表格；单行含管道正文（其后无分隔行）不是表格
        text = ('| A | B |\n| --- | --- |\n| a | b |\n'
                '\n'
                '正文 | 管道\n'
                '| 只有表头 |\n不是表格\n'
                '```text\n| 代码 | 块 |\n| --- | --- |\n```\n')
        self.assertEqual(markdown_table_row_lines(text), {1, 2, 3})

    def test_table_block_ends_at_other_blocks_and_bad_column_count(self):
        # F5：表格后的列表/引用块开启新块，不再算作表格行（表外公式
        # 损伤必须可检）；表头列数与分隔行不符不构成表格
        after_list = ('| A | B |\n| --- | --- |\n| a | b |\n'
                      '- item | with pipe\n')
        self.assertEqual(markdown_table_row_lines(after_list), {1, 2, 3})
        after_quote = ('| A | B |\n| --- | --- |\n| a | b |\n'
                       '> quote | with pipe\n')
        self.assertEqual(markdown_table_row_lines(after_quote), {1, 2, 3})
        bad_columns = '| A | B | C |\n| --- | --- |\n| a | $x$ |\n'
        self.assertEqual(markdown_table_row_lines(bad_columns), set())

    def test_table_then_list_pipe_escape_damage_detected(self):
        # F5：表格紧接列表（无空行）时，列表行的公式不是表格行，
        # 绝对值改范数必须拒绝
        src = scan_math_spans('[TABLE]\nKind | Formula\n--- | ---\n'
                              'Abs | $|x|$\n- Formula $|x|$\n')
        doc_text = ('| Kind | Formula |\n| --- | --- |\n| Abs | $\\|x\\|$ |\n'
                    '- Formula $\\|x\\|$\n')
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertTrue(any("L4" in d or 'L5' in d for d in diffs), diffs)
        # 列表行未改公式的正例通过
        doc_same = scan_math_spans(
            '| Kind | Formula |\n| --- | --- |\n| Abs | $\\|x\\|$ |\n'
            '- Formula $|x|$\n')
        diffs, _ = compare_math_spans(
            src, doc_same, 'src.md', 'doc.md',
            doc_text='| Kind | Formula |\n| --- | --- |\n'
                     '| Abs | $\\|x\\|$ |\n- Formula $|x|$\n')
        self.assertEqual(diffs, [])

    def test_table_inside_blockquote_recognized(self):
        # F5：引用块内的真实表格按去 ``> `` 后内容判定，合法转义归一
        quote = ('> | Kind | Formula |\n> | --- | --- |\n'
                 '> | Abs | $\\|x\\|$ |\n')
        self.assertEqual(markdown_table_row_lines(quote), {1, 2, 3})
        src = scan_math_spans('[TABLE]\nKind | Formula\n--- | ---\n'
                              'Abs | $|x|$\n')
        doc = scan_math_spans(quote)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=quote)
        self.assertEqual(diffs, [])
        # 引用表格内的其余公式损伤仍拒绝
        bad = scan_math_spans(quote.replace('$\\|x\\|$', '$\\|x*y\\|$'))
        diffs, _ = compare_math_spans(src, bad, 'src.md', 'doc.md',
                                      doc_text=quote)
        self.assertTrue(diffs)

    def test_nested_quote_after_quoted_table_not_table_row(self):
        # F5 第三轮：引用表格后的嵌套引用行开启新块，不算表格行；
        # 表外公式把 | 转义成 \| 的损伤不得被表格行归一掩盖
        doc_text = ('> | Kind | Formula |\n> | --- | --- |\n'
                    '> | Abs | $\\|x\\|$ |\n>> note $\\|x\\|$\n')
        self.assertEqual(markdown_table_row_lines(doc_text), {1, 2, 3})
        src = scan_math_spans('[TABLE]\nKind | Formula\n--- | ---\n'
                              'Abs | $|x|$\nnote $|x|$\n')
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertTrue(any('L4' in d for d in diffs), diffs)
        # 嵌套引用行未改公式的正例通过
        doc_same = scan_math_spans(doc_text.replace('note $\\|x\\|$',
                                                    'note $|x|$'))
        diffs, _ = compare_math_spans(src, doc_same, 'src.md', 'doc.md',
                                      doc_text=doc_text.replace(
                                          'note $\\|x\\|$', 'note $|x|$'))
        self.assertEqual(diffs, [])

    def test_escaped_pipe_in_header_keeps_real_table(self):
        # F5 第三轮：表头单元格内的 \| 是转义管道，实际列数不变；
        # 表仍被识别，表内公式的合法 \| 转义照常归一
        doc_text = '| A\\|X | B |\n| --- | --- |\n| a | $\\|x\\|$ |\n'
        self.assertEqual(markdown_table_row_lines(doc_text), {1, 2, 3})
        src = scan_math_spans('[TABLE]\nA | B\n--- | ---\na | $|x|$\n')
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertEqual(diffs, [])
        # 表内其余公式损伤仍拒绝
        bad = scan_math_spans(doc_text.replace('$\\|x\\|$', '$\\|x*y\\|$'))
        diffs, _ = compare_math_spans(src, bad, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertTrue(diffs)

    def test_literal_html_line_before_table_matches_export(self):
        # F5 第四轮：核验解析配置与实际导出一致（html=False）——字面
        # <div> 行只是普通文字，其后紧邻的合法表格照常识别，表内合法
        # \| 转义归一通过（html=True 会把整片吞成 HTML 块而误拒）
        doc_text = '# H\n\n<div>\n| A | B |\n| --- | --- |\n| a | $\\|x\\|$ |\n'
        self.assertEqual(markdown_table_row_lines(doc_text), {4, 5, 6})
        src = scan_math_spans('[TABLE]\nA | B\n--- | ---\na | $|x|$\n')
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertEqual(diffs, [])

    def test_real_table_row_normalized_and_damage_detected(self):
        src = scan_math_spans('[TABLE]\nKind | Formula\n--- | ---\n'
                              'Abs | $|x|$\n')
        doc_text = '| Kind | Formula |\n| --- | --- |\n| Abs | $\\|x\\|$ |\n'
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertEqual(diffs, [])
        # 表格行内的其余公式损伤仍拒绝
        doc_bad = scan_math_spans(doc_text.replace('$\\|x\\|$', '$\\|x*y\\|$'))
        diffs, _ = compare_math_spans(src, doc_bad, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertTrue(diffs)

    def test_pipe_in_plain_prose_not_normalized(self):
        src = scan_math_spans('A | B value $|x|$\n')
        doc_text = 'A | B value $\\|x\\|$\n'
        doc = scan_math_spans(doc_text)
        diffs, _ = compare_math_spans(src, doc, 'src.md', 'doc.md',
                                      doc_text=doc_text)
        self.assertTrue(any("'|x|'" in d for d in diffs), diffs)
        # 未改公式的正文管道正例照常通过
        doc_same = scan_math_spans('A | B value $|x|$\n')
        diffs, _ = compare_math_spans(src, doc_same, 'src.md', 'doc.md',
                                      doc_text='A | B value $|x|$\n')
        self.assertEqual(diffs, [])


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
