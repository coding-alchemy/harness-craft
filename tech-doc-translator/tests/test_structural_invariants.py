"""标题/脚注/强 token 核验的固定语义验收（任务 04）。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_headings,
    count_token,
    footnote_diffs,
    heading_entries,
    heading_title_matches,
    strong_token_checked_items,
    strong_token_report,
)
from _source_reconcile import reconcile_html_to_markdown


class HeadingTitleMatchTest(unittest.TestCase):

    def test_exact_and_chinese_suffix(self):
        self.assertTrue(heading_title_matches('1. Foo Bar', '1. Foo Bar'))
        self.assertTrue(heading_title_matches(
            '1. Foo Bar', '1. Foo Bar（中文标题）'))

    def test_curly_quotes_are_content_characters(self):
        self.assertFalse(heading_title_matches(
            '1. it’s here', "1. it's here"))

    def test_no_blind_truncation_at_first_paren(self):
        # 源原题本身含全角括号：后缀必须在其之后
        self.assertTrue(heading_title_matches(
            '1. Foo（Bar）', '1. Foo（Bar）（巴）'))
        # 后缀之后还有内容：不匹配
        self.assertFalse(heading_title_matches(
            '1. Foo', '1. Foo（中文）以及多余内容'))

    def test_suffix_must_be_nonempty(self):
        self.assertFalse(heading_title_matches('1. Foo', '1. Foo（）'))


class HeadingEntriesTest(unittest.TestCase):

    def test_ordered_entries_exclude_fence_lines(self):
        text = '# T\n```c\n## fake\n```\n## Real（真实）\n'
        entries = heading_entries(text)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'Real（真实）')])

    def test_quote_prefixed_headings_recognized(self):
        # R3 补充：引用前缀后的 ATX 标题（markdown-it 实测 > # x、> > # x
        # 均成为标题）；转义形态 \# 不误检
        text = '# T\n\n> # quoted\n\n> > # nested\n\n> \\# escaped\n'
        entries = heading_entries(text)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (1, 'quoted'), (1, 'nested')])

    def test_deep_h7_h8_headings_recognized(self):
        # 评审 P1-5：深层标题不截断到 H6；删除 H7/H8 必须被逐项对照检出
        text = '# T\n\n## A\n\n####### H7 七级\n\n######## H8 八级\n'
        entries = heading_entries(text)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'A'), (7, 'H7 七级'), (8, 'H8 八级')])
        doc = heading_entries('# T（T）\n\n## A（A）\n\n正文\n')
        diffs = compare_headings(entries, doc, 'src.md', 'doc.md')
        self.assertTrue(any('标题数不一致' in d for d in diffs))


class CompareHeadingsTest(unittest.TestCase):

    def test_level_change_reported(self):
        src = heading_entries('## A\n\ntext\n\n### A.1\n')
        doc = heading_entries('## A\n\ntext\n\n#### A.1\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('层级不一致' in d and 'H3' in d and 'H4' in d
                            for d in diffs))

    def test_title_change_reported(self):
        src = heading_entries('## A.1 Deep\n')
        doc = heading_entries('## A.1 Doeep（深）\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题 #1 不一致' in d and "'A.1 Deep'" in d
                            for d in diffs))

    def test_deleted_unnumbered_heading_reported(self):
        src = heading_entries('# T\n\n## 1. A\n\n### Intro\n\n## 2. B\n')
        doc = heading_entries('# T\n\n## 1. A\n\n## 2. B\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题数不一致' in d for d in diffs))

    def test_level_shift_and_header_skip_for_assembly(self):
        src = heading_entries('# 1. Foo\n\n## 1.1. Bar\n')
        doc = heading_entries('# 章节头\n\n## 1. Foo（福）\n\n### 1.1. Bar（巴）\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md',
                                 level_shift=1, doc_skip_head=1)
        self.assertEqual(diffs, [])

    def test_missing_heading_reported(self):
        src = heading_entries('# T\n\n## A\n\n## B\n')
        doc = heading_entries('# T\n\n## A\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题数不一致' in d and '多余' not in d for d in diffs))


class FootnoteDiffTest(unittest.TestCase):

    def test_pair_deletion_detected(self):
        src = '正文[^1]与[^2]。\n\n[^1]: 一\n[^2]: 二\n'
        doc = '正文[^1]。\n\n[^1]: 一\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('[^2]' in d for d in diffs))

    def test_ref_or_def_loss_detected(self):
        src = '正文[^1]。\n\n[^1]: 一\n'
        doc = '正文[^1]。\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('定义缺失' in d for d in diffs))

    def test_named_labels_supported(self):
        src = '正文[^note]。\n\n[^note]: 说明\n'
        doc = '正文[^note]。\n\n[^note]: 说明\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertEqual(diffs, [])

    def test_extra_note_footnote_is_warning(self):
        src = '正文[^1]。\n\n[^1]: 一\n'
        doc = '正文[^1]。译注[^n1]。\n\n[^1]: 一\n[^n1]: 译注说明\n'
        diffs, warns = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertEqual(diffs, [])
        self.assertTrue(any('[^n1]' in w for w in warns))


class StrongTokenTest(unittest.TestCase):

    def test_missing_token_fails(self):
        src = '调用 cublasSgemm 两次'
        doc = '调用 cublas'
        diffs, _ = strong_token_report(src, doc, ['cublasSgemm'], 'a', 'b')
        self.assertTrue(diffs and '1 处' in diffs[0])

    def test_word_boundary_no_false_positive(self):
        src = 'kernel 启动'
        doc = 'subkernel 内核'
        diffs, _ = strong_token_report(src, doc, ['kernel'], 'a', 'b')
        self.assertTrue(diffs)

    def test_unconfigured_reported_not_passed(self):
        diffs, warns = strong_token_report('a', 'b', [])
        self.assertIsNone(diffs)
        self.assertTrue(any('未配置' in w for w in warns))

    def test_increase_is_warning(self):
        diffs, warns = strong_token_report('a cublasSgemm', 'a cublasSgemm b cublasSgemm',
                                           ['cublasSgemm'], 'a', 'b')
        self.assertEqual(diffs, [])
        self.assertTrue(warns)


class CountTokenMorphologyTest(unittest.TestCase):
    """R3/D3：已配置 token 按形态选择有限边界，正文与代码同一口径。"""

    PTX = ('add.rn.f32 d, a, b;\n'
           'mov.u32 %r1, %tid.x;\n'
           'cvt.rn.satfinite.e4m3x2.f32 d, a;\n')

    def test_ptx_sample_counts(self):
        self.assertEqual(count_token(self.PTX, '.rn'), 2)
        self.assertEqual(count_token(self.PTX, '.f32'), 2)
        self.assertEqual(count_token(self.PTX, '.satfinite'), 1)
        self.assertEqual(count_token(self.PTX, '%r1'), 1)
        self.assertEqual(count_token(self.PTX, '%tid'), 1)

    def test_prose_and_code_same_rule(self):
        # 不屏蔽代码：正文叙述与围栏内代码按同一口径计数
        text = '正文叙述 .rn 修饰符与 %tid 寄存器\n```\nadd.rn.f32 d, a, b;\n```\n'
        self.assertEqual(count_token(text, '.rn'), 2)
        self.assertEqual(count_token(text, '%tid'), 1)

    def test_dot_chain_segments_each_counted(self):
        # 点分链允许指令名及其他修饰段紧邻，有效段分别保留
        self.assertEqual(count_token('add.rn.f32 d, a, b;', '.rn'), 1)
        self.assertEqual(count_token('add.rn.f32 d, a, b;', '.f32'), 1)
        self.assertEqual(count_token('cvt.rn.satfinite.e4m3x2.f32 d, a;', '.f32'), 1)

    def test_long_identifiers_and_incomplete_segments_do_not_match(self):
        self.assertEqual(count_token('add.rni.f32 x;', '.rn'), 0)
        self.assertEqual(count_token('add.rnx x;', '.rn'), 0)
        self.assertEqual(count_token('foo.rn. 残句', '.rn'), 0)

    def test_decimal_fraction_does_not_match(self):
        self.assertEqual(count_token('值 3.5 与 12.25', '.5'), 0)
        self.assertEqual(count_token('值 3.5 与 12.25', '.25'), 0)

    def test_register_boundaries(self):
        self.assertEqual(count_token('%tid.x 字段', '%tid'), 1)
        self.assertEqual(count_token('%tidy', '%tid'), 0)
        self.assertEqual(count_token('a%tid', '%tid'), 0)
        self.assertEqual(count_token('x%%tid', '%tid'), 0)

    def test_word_token_keeps_full_word_boundary(self):
        self.assertEqual(count_token('subkernel kernel kernel2', 'kernel'), 1)
        self.assertEqual(count_token('调用 cublasSgemm 两次', 'cublasSgemm'), 1)

    def test_symbol_token_literal_count(self):
        self.assertEqual(count_token('a <<< b <<<', '<<<'), 2)

    def test_case_and_literals_not_rewritten(self):
        self.assertEqual(count_token('ADD.RN.F32', '.rn'), 0)
        self.assertEqual(count_token('Kernel', 'kernel'), 0)


class StrongTokenAbsentReportTest(unittest.TestCase):
    """R3/D3：源中未出现的配置项逐项“未检查”，汇总不误称已检查。"""

    def test_absent_source_item_warned_even_when_doc_zero(self):
        diffs, warns = strong_token_report('正文无该项', '译文也没有',
                                           ['.rn'], 'a', 'b')
        self.assertEqual(diffs, [])
        self.assertTrue(any("'.rn'" in w and '未检查' in w for w in warns))

    def test_present_items_not_marked_unchecked(self):
        src = 'kernel 启动 .rn 修饰'
        doc = 'kernel 启动 .rn 修饰'
        diffs, warns = strong_token_report(src, doc, ['kernel', '.rn', '%tid'],
                                           'a', 'b')
        self.assertEqual(diffs, [])
        absent = [w for w in warns if '未检查' in w]
        self.assertTrue(any('%tid' in w for w in absent))
        self.assertFalse(any('kernel' in w for w in absent))
        self.assertFalse(any('.rn' in w for w in absent))
        self.assertEqual(strong_token_checked_items(src, ['kernel', '.rn', '%tid']),
                         ['kernel', '.rn'])

    def test_absent_item_with_doc_increase_stays_warning(self):
        # 缺席告警与增加告警并存，不升级为硬失败
        diffs, warns = strong_token_report('无', '%tid 出现', ['%tid'], 'a', 'b')
        self.assertEqual(diffs, [])
        self.assertTrue(any('未检查' in w for w in warns))
        self.assertTrue(any('增加' in w for w in warns))

    def test_missing_real_hit_still_fails(self):
        src = 'add.rn.f32 d, a, b;'
        doc = 'add.f32 d, a, b;'
        diffs, _ = strong_token_report(src, doc, ['.rn'], 'a', 'b')
        self.assertTrue(any("'.rn'" in d and '遗漏' in d for d in diffs))

    def test_empty_list_semantics_unchanged(self):
        diffs, warns = strong_token_report('a', 'b', [])
        self.assertIsNone(diffs)
        self.assertTrue(any('未配置' in w for w in warns))
        self.assertEqual(strong_token_checked_items('a', []), [])


class SourceReconcileTest(unittest.TestCase):
    """原 HTML → 解析 Markdown 独立对账（A27）：等数损伤必须定位。"""

    HTML = (
        '<html><body><article>'
        '<h1>1. Probe</h1>'
        '<p>intro <code>C#</code> text</p>'
        '<div class="highlight"><pre><span></span><code>alpha()</code></pre></div>'
        '<p>mid</p>'
        '<div class="highlight"><pre>beta(1)</pre></div>'
        '<img src="images/pic.png" alt="pic">'
        '<p><span class="math">x^2</span> formula</p>'
        '<table><tr><th>K</th><th>V</th></tr>'
        '<tr><td>a</td><td>b</td></tr></table>'
        '</article></body></html>'
    )

    @classmethod
    def setUpClass(cls):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(cls.HTML)
        out = []
        render(soup.find('article'), out, fidelity)
        cls.md = '\n'.join(out).strip() + '\n'
        cls.diffs_clean = reconcile_html_to_markdown(
            cls.HTML, cls.md, 'single')

    def test_faithful_parse_reconciles_clean(self):
        self.assertEqual(self.diffs_clean, [])

    def test_dropped_code_detected(self):
        damaged = self.md.replace('```\nalpha()\n```\n', '')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('数量不一致' in d for d in diffs))

    def test_equal_count_content_swap_detected(self):
        # 内容流含行内代码事实后，alpha() 位于节内第 2 项（第 1 项是 C#）
        damaged = self.md.replace('alpha()', 'alpha_changed()')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('第 2 项不一致' in d
                            and 'alpha_changed()' in d for d in diffs))

    def test_in_section_cross_category_order_detected(self):
        # P2-7：节内跨类别实际顺序参与对账——代码→图片换成图片→代码
        # （数量与内容各自不变）必须检出，不能靠拼接类别流蒙混。
        html = ('<html><body><article><h1>S</h1>'
                '<pre><code>alpha = 1;</code></pre>'
                '<img src="images/pic.png"></article></body></html>')
        md_ordered = ('# S\n\n```text\nalpha = 1;\n```\n\n'
                      '![pic](images/pic.png)\n')
        md_swapped = ('# S\n\n![pic](images/pic.png)\n\n'
                      '```text\nalpha = 1;\n```\n')
        self.assertEqual(
            reconcile_html_to_markdown(html, md_ordered, 'single'), [])
        diffs = reconcile_html_to_markdown(html, md_swapped, 'single')
        self.assertTrue(
            any('内容' in d and '第 1 项不一致' in d for d in diffs), diffs)

    def test_reordered_code_detected(self):
        damaged = (self.md.replace('alpha()', '@@T@@')
                   .replace('beta(1)', 'alpha()')
                   .replace('@@T@@', 'beta(1)'))
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('第 2 项不一致' in d and 'beta(1)' in d
                            for d in diffs))

    def test_duplicated_block_detected(self):
        damaged = self.md.replace(
            '```\nbeta(1)\n```', '```\nbeta(1)\n```\n\n```\nbeta(1)\n```')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('数量不一致' in d for d in diffs))

    def test_dropped_image_detected(self):
        damaged = self.md.replace('![pic](images/pic.png)\n', '')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('图片' in d or ('内容' in d and '数量不一致' in d) for d in diffs))

    def test_dropped_heading_detected(self):
        damaged = self.md.replace('# 1. Probe\n', '')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('标题' in d and '数量不一致' in d for d in diffs))

    def test_math_swap_detected(self):
        damaged = self.md.replace('$x^2$', '$y^2$')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        # 节内流按文档位置排序后比较：x^2/y^2 所在位置决定序号，
        # 内容流含行内代码事实后位于第 5 项。
        self.assertTrue(
            any('内容' in d and '第 5 项不一致' in d and 'y^2' in d
                for d in diffs), diffs[:3])

    def test_table_cell_swap_detected(self):
        damaged = self.md.replace('a | b', 'a | c')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('表格' in d for d in diffs))

    def test_colspan_table_blocked_by_parser(self):
        from _html_fidelity import TableStructureError, HtmlFidelity
        from parse_single_page_html import render
        fidelity = HtmlFidelity()
        soup = fidelity.parse(
            '<body><table><tr><td colspan="2">wide</td></tr></table></body>')
        out = []
        with self.assertRaises(TableStructureError):
            render(soup.find('body'), out, fidelity)


class InlineCodeSemanticsTest(unittest.TestCase):
    """行内代码语义保真（A25/A26）：反引号与 HTML 字面量保持代码语义。"""

    HTML = ('<html><body><article><h1>T</h1>'
            '<p>use <code>a`b</code> and <code>&lt;span&gt;</code> ok</p>'
            '<p>link <a href="u"><code>x=1</code></a></p>'
            '<p>literal `tick` in text</p>'
            '</article></body></html>')

    @classmethod
    def setUpClass(cls):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(cls.HTML)
        out = []
        render(soup.find('article'), out, fidelity)
        cls.md = '\n'.join(out).strip() + '\n'
        cls.diffs_clean = reconcile_html_to_markdown(cls.HTML, cls.md, 'single')

    def test_render_keeps_code_semantics(self):
        self.assertIn('``a`b``', self.md)
        self.assertIn('`<span>`', self.md)
        # 链接标签中的代码标签保留定界
        self.assertIn('[`x=1`](u)', self.md)

    def test_boundary_backticks_isolated_from_delimiter(self):
        # 内容首/尾反引号与定界符隔离（成对空格填充），markdown-it 实际
        # 渲染为代码跨度；闭合符必须是完整等长反引号串
        from markdown_it import MarkdownIt
        from _html_fidelity import markdown_inline_code, \
            parse_inline_code_spans
        for value in ('`foo', 'foo`', 'a`b'):
            span = markdown_inline_code(value)
            rendered = MarkdownIt().render(span)
            self.assertIn('<code>', rendered, value)
            contents = [c for c, _r in parse_inline_code_spans(span)]
            self.assertEqual(contents, [value], (value, span))
        # 一个反引号 + a + 两个反引号：闭合串不等长，是字面文本而非代码
        self.assertEqual(parse_inline_code_spans('`a``'), [])

    def test_mismatched_delimiters_detected(self):
        # 源 <code>a</code> 对应 “一个反引号 + a + 两个反引号” 必须拒绝
        html = '<html><body><article><h1>T</h1><p><code>a</code></p>' \
               '</article></body></html>'
        diffs = reconcile_html_to_markdown(html, '# T\n\n`a``\n', 'single')
        self.assertTrue(any('数量不一致' in d for d in diffs), diffs[:3])

    def test_faithful_parse_reconciles_clean(self):
        self.assertEqual(self.diffs_clean, [])

    def test_removed_delimiters_detected(self):
        # 整段代码跨度删除后，源侧事实仍在而输出侧缺失（节内首条差异
        # 为数量不一致）
        damaged = self.md.replace('``a`b`` ', '')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(
            any('内容' in d and '数量不一致' in d for d in diffs), diffs[:3])

    def test_changed_code_content_detected(self):
        damaged = self.md.replace('`x=1`', '`x=2`')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(
            any('inline-code' in d and 'x=1' in d for d in diffs), diffs[:3])

    def test_dropped_span_detected(self):
        damaged = self.md.replace('`<span>` ', '')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(
            any('内容' in d and '数量不一致' in d for d in diffs), diffs[:3])


class ContainerInlineCodeFidelityTest(unittest.TestCase):
    """03-S1：figcaption/脚注 aside/定义术语中的 <code> 保留代码语义。

    忠实保留代码定界的候选通过独立对账，拍平/去定界的被拒；普通段落
    与无代码容器对照不变。源事实不再由渲染策略决定有无。
    """

    CASES = [
        ('figure',
         '<figure><figcaption>Use <code>x()</code></figcaption></figure>',
         '**Figure: Use `x()`**'),
        ('footnote',
         '<aside role="doc-footnote" id="f1"><span class="label">[1]</span>'
         '<p>Use <code>x()</code></p></aside>',
         '[[1]] Use `x()`'),
        ('term',
         '<dl><dt><code>x()</code></dt><dd>Meaning</dd></dl>',
         '**`x()`**'),
        ('normal', '<p>Use <code>x()</code></p>', 'Use `x()`'),
    ]

    @staticmethod
    def html(body):
        return ('<html><body><article><h1>T</h1>%s</article></body></html>'
                % body)

    def parse_single(self, body):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(self.html(body))
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_container_code_preserved_and_flattening_rejected(self):
        for name, body, marker in self.CASES:
            with self.subTest(name=name):
                md = self.parse_single(body)
                self.assertIn(marker, md)
                self.assertEqual(
                    reconcile_html_to_markdown(self.html(body), md,
                                               'single'), [])
                flattened = md.replace('`x()`', 'x()')
                diffs = reconcile_html_to_markdown(self.html(body),
                                                   flattened, 'single')
                self.assertTrue(any('数量不一致' in d for d in diffs),
                                (name, diffs[:3]))

    def test_api_and_reference_caption_code_preserved(self):
        from _html_fidelity import HtmlFidelity
        import parse_api_html
        import parse_reference_html
        body = ('<figure><img src="c.png"/>'
                '<figcaption>Use <code>x()</code></figcaption></figure>')
        for name, module, marker in (
                ('api', parse_api_html, '[FIGCAPTION] Use `x()`'),
                ('reference', parse_reference_html, '[FIGURE] Use `x()`')):
            with self.subTest(name=name):
                fidelity = HtmlFidelity()
                soup = fidelity.parse(self.html(body))
                out = []
                module.render(soup.find('article'), out, fidelity)
                self.assertIn(marker, '\n'.join(out))

    def test_code_free_containers_unchanged(self):
        # 无代码容器对照：输出与对账行为不变
        for body in ('<figure><figcaption>plain cap</figcaption></figure>',
                     '<dl><dt>plain</dt><dd>Meaning</dd></dl>'):
            md = self.parse_single(body)
            self.assertNotIn('`', md)
            self.assertEqual(
                reconcile_html_to_markdown(self.html(body), md, 'single'),
                [])


class FootnoteBacklinkLabelTest(unittest.TestCase):
    """03-S4：带返回链接标签的 Sphinx 脚注正常解析。

    标签定位取 `.label` 元素纯文字（doc-backlink 锚点不得被行内序列化
    成 Markdown 链接使裸标签正则失配）；正文行内语义保真。无链接标签
    与无 `.label` 回退路径为正常对照。
    """

    @staticmethod
    def html(body):
        return ('<html><body><article><h1>T</h1>%s</article></body></html>'
                % body)

    def parse_single(self, body):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(self.html(body))
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_backlink_label_body_parsed(self):
        body = ('<aside class="footnote brackets" id="id2" role="doc-footnote">'
                '<span class="label">'
                '<a role="doc-backlink" href="#id1">[1]</a></span>'
                '<p>Footnote body text.</p></aside>')
        md = self.parse_single(body)
        self.assertIn('[[1]] Footnote body text.', md)
        self.assertEqual(
            reconcile_html_to_markdown(self.html(body), md, 'single'), [])

    def test_backlink_label_body_code_preserved(self):
        body = ('<aside class="footnote brackets" id="id2" role="doc-footnote">'
                '<span class="label">'
                '<a role="doc-backlink" href="#id1">[1]</a></span>'
                '<p>Use <code>x()</code> here.</p></aside>')
        md = self.parse_single(body)
        self.assertIn('[[1]] Use `x()` here.', md)
        self.assertEqual(
            reconcile_html_to_markdown(self.html(body), md, 'single'), [])
        flattened = md.replace('`x()`', 'x()')
        diffs = reconcile_html_to_markdown(self.html(body), flattened,
                                           'single')
        self.assertTrue(any('数量不一致' in d for d in diffs), diffs[:3])

    def test_plain_label_control_unchanged(self):
        body = ('<aside role="doc-footnote" id="f1">'
                '<span class="label">[1]</span>'
                '<p>Footnote body text.</p></aside>')
        md = self.parse_single(body)
        self.assertIn('[[1]] Footnote body text.', md)
        self.assertEqual(
            reconcile_html_to_markdown(self.html(body), md, 'single'), [])

    def test_bare_text_label_fallback_unchanged(self):
        # 无 .label 元素时维持渲染文本正则回退路径
        body = ('<aside role="doc-footnote" id="f2">'
                '<p>[2] bare label body</p></aside>')
        md = self.parse_single(body)
        self.assertIn('[[2]] bare label body', md)
        self.assertEqual(
            reconcile_html_to_markdown(self.html(body), md, 'single'), [])


class ImageSyntaxPositionTest(unittest.TestCase):
    """图片语法位置（A28 第三轮）：代码字面量与真实图片引用同路径共存
    时，真实图片按语法区间计入，不得因 URL 同名被代码排除误删。"""

    def test_inline_image_after_same_path_code_clean(self):
        # 段落内图片属解析器旧渲染限制，此处为手工明确转换候选，
        # 对账函数必须按真实引用位置核对
        html = ('<html><body><article><h1>H</h1>'
                '<p><code>images/pic.png</code> '
                '<img src="images/pic.png" alt="pic"></p>'
                '</article></body></html>')
        md = '# H\n\n`images/pic.png` ![pic](images/pic.png)\n'
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_reference_style_image_after_same_path_code_clean(self):
        html = ('<html><body><article><h1>H</h1>'
                '<p><code>images/pic.png</code> '
                '<img src="images/pic.png" alt="pic"></p>'
                '</article></body></html>')
        md = ('# H\n\n`images/pic.png` ![pic][p]\n\n'
              '[p]: images/pic.png\n')
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_table_cell_code_path_with_image_clean(self):
        html = ('<html><body><article><h1>H</h1>'
                '<table><tr><th>A</th><th>B</th></tr>'
                '<tr><td><code>images/pic.png</code></td>'
                '<td><img src="images/pic.png" alt="pic"></td></tr>'
                '</table></article></body></html>')
        md = ('# H\n\n[TABLE]\nA | B\n--- | ---\n'
              '`images/pic.png` | ![pic](images/pic.png)\n')
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_code_image_syntax_still_not_counted(self):
        # 控制样例：代码内容本身是图片语法，不是真实图片出现
        html = ('<html><body><article><h1>H</h1>'
                '<p><code>![a](images/pic.png)</code></p>'
                '</article></body></html>')
        md = '# H\n\n`![a](images/pic.png)`\n'
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_consecutive_spaces_kept_and_compression_detected(self):
        # S03：行内代码中的连续空格是字符串字面量内容，压缩即改义；
        # 两侧事实同用无损口径（行结束符转空格，不折叠），损伤可检出
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity, markdown_inline_code
        self.assertEqual(markdown_inline_code('print("a  b")'),
                         '`print("a  b")`')
        html = ('<html><body><article><h1>T</h1>'
                '<p>use <code>print("a  b")</code></p>'
                '</article></body></html>')
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        md = '\n'.join(out).strip() + '\n'
        self.assertIn('`print("a  b")`', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('a  b', 'a b')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('inline-code' in d for d in diffs), diffs[:3])

    def test_real_boundary_spaces_kept_and_deletion_detected(self):
        # S03/F7：真实边界空格是代码内容（语法填充由定界规则解码），
        # 删除边界空格必须检出，不得用两侧 strip 吸收
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        html = ('<html><body><article><h1>T</h1>'
                '<p>Use <code style="white-space:pre"> x </code>.</p>'
                '</article></body></html>')
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        md = '\n'.join(out).strip() + '\n'
        self.assertIn('`  x  `', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('`  x  `', '`x`')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('inline-code' in d and "' x '" in d
                            for d in diffs), diffs[:3])

    def test_image_syntax_inside_code_not_an_occurrence(self):
        # A28/F1c：代码跨度内的图片语法是代码内容，不是真实图片出现；
        # 段落与标题中的此类输入都必须正常解析
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        for body in ('<p>Use <code>![a](x.png)</code> here</p>',
                     '<h2>Use <code>![a](x.png)</code></h2>'):
            html = ('<html><body><article><h1>T</h1>%s'
                    '</article></body></html>' % body)
            fidelity = HtmlFidelity()
            soup = fidelity.parse(html)
            out = []
            render(soup.find('article'), out, fidelity)
            md = '\n'.join(out).strip() + '\n'
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [], body)
            # 改写代码内的图片字面量必须检出
            damaged = md.replace('![a](x.png)', '![b](z.png)')
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(diffs, (body, diffs[:3]))


class HighlightIndentationTest(unittest.TestCase):
    """高亮包装间的行首缩进保留（S01）：清理共用保白上下文，输出少缩进
    被独立对账拒绝。"""

    HTML = ('<html><body><article><h1>H</h1>'
            '<pre><span>if ok:</span>\n    <span>print(1)</span>\n</pre>'
            '<pre>if ok:\n    print(1)\n</pre>'
            '</article></body></html>')

    @classmethod
    def setUpClass(cls):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(cls.HTML)
        out = []
        render(soup.find('article'), out, fidelity)
        cls.md = '\n'.join(out).strip() + '\n'

    def test_highlight_indent_matches_plain_pre(self):
        # 高亮 span 间行首四空格与普通 pre 一致保留
        self.assertEqual(self.md.count('    print(1)'), 2, self.md)
        self.assertEqual(
            reconcile_html_to_markdown(self.HTML, self.md, 'single'), [])

    def test_indent_loss_rejected(self):
        damaged = self.md.replace('\n    print(1)', '\nprint(1)', 1)
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(diffs, diffs[:3])


class HeadingInlineSemanticsTest(unittest.TestCase):
    """标题行内语义（S02）：标题内代码保留代码跨度，拍平或改字被标题流
    检出；C# 与真实 headerlink 控制样例不受影响。"""

    HTML = ('<html><body><article><h1>H</h1>'
            '<h2>Use code(<code>a*b*</code>)</h2>'
            '<h2>C# and <a class="headerlink" href="#c">¶</a>plain</h2>'
            '</article></body></html>')

    @classmethod
    def setUpClass(cls):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(cls.HTML)
        out = []
        render(soup.find('article'), out, fidelity)
        cls.md = '\n'.join(out).strip() + '\n'

    def test_heading_code_kept_with_controls_clean(self):
        self.assertIn('## Use code(`a*b*`)', self.md)
        self.assertIn('## C# and plain', self.md)
        self.assertEqual(
            reconcile_html_to_markdown(self.HTML, self.md, 'single'), [])

    def test_flattened_heading_code_detected(self):
        # 拍平成裸 a*b*（Markdown 会渲染为强调）必须被标题流检出
        flattened = self.md.replace('`a*b*`', 'a*b*')
        diffs = reconcile_html_to_markdown(self.HTML, flattened, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs[:3])

    def test_changed_heading_code_detected(self):
        damaged = self.md.replace('`a*b*`', '`a*c*`')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs[:3])

    def test_heading_math_delimiters_kept_and_flatten_detected(self):
        # F1：标题公式保留 $ 定界参与标题比较，去定界（变普通文字）
        # 必须检出，不能被两侧同形去壳放行
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        html = ('<html><body><article><h1>H</h1>'
                '<h2>Use <span class="math">\\(x^2\\)</span></h2>'
                '</article></body></html>')
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        md = '\n'.join(out).strip() + '\n'
        self.assertIn('$x^2$', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        flattened = md.replace('$x^2$', 'x^2')
        diffs = reconcile_html_to_markdown(html, flattened, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs[:3])

    def test_heading_image_blocks_dispatch(self):
        # F1：图片是独立源事实；标题图片当前序列化无法表达，必须
        # 阻断分派，不得靠两侧排除静默丢失
        html = ('<html><body><article><h1>H</h1>'
                '<h2>See <img src="pic.png"/></h2>'
                '</article></body></html>')
        diffs = reconcile_html_to_markdown(html, '# H\n\n## See\n', 'single')
        self.assertTrue(any('内容' in d and '数量不一致' in d
                            for d in diffs), diffs[:3])


class PreDollarStringTest(unittest.TestCase):
    """代码内美元串不是正文公式（S08）：正确候选不被对账拒绝，正文公式
    照常核对。"""

    def _render_md(self, html):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_pre_dollar_and_plain_both_clean(self):
        for code in ('print("x")', 'print("$x$")'):
            html = ('<html><body><article><h1>H</h1><pre>%s</pre>'
                    '<p>value $y$.</p></article></body></html>' % code)
            md = self._render_md(html)
            self.assertIn(code, md)
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [], code)
            # 正文公式仍被提取核对：改符号必须拒绝
            damaged = md.replace('$y$', '$z$')
            self.assertTrue(
                reconcile_html_to_markdown(html, damaged, 'single'))


class ReconcileMathKindAndIssueTest(unittest.TestCase):
    """R2/D2：源对账保留公式类型与原表达式，未解决定界阻断分派。"""

    @staticmethod
    def _render(html, family='single'):
        import parse_single_page_html
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        parse_single_page_html.render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_adjacent_inline_math_reconciles_clean(self):
        html = ('<html><body><article><h1>H</h1>'
                '<p>gain $x$$\\sim$ noise and $y$$\\le$ end</p>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('$x$$\\sim$', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_unresolved_literal_math_blocks_dispatch(self):
        html = ('<html><body><article><h1>H</h1>'
                '<p>前文 $x 后文</p></article></body></html>')
        md = self._render(html)
        diffs = reconcile_html_to_markdown(html, md, 'single')
        self.assertTrue(any('未解决数学定界' in d for d in diffs), diffs)

    def test_kind_change_inline_to_block_detected(self):
        # 类型不再拍平成单一 'math'：行内改块级必须被对账定位
        html = ('<html><body><article><h1>H</h1>'
                '<p>value $y$.</p></article></body></html>')
        md = self._render(html)
        damaged = md.replace('$y$.', '$$y$$.')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(diffs, diffs)

    def test_math_whitespace_flattening_not_blindly_removed(self):
        # 允许转换仅限家族序列化口径：块级首尾排版空白归一，
        # 表达式内部内容差异（等数换内容）必须检出
        html = ('<html><body><article><h1>H</h1>'
                '<p>a <span class="math">E = m c^2</span> b</p>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('E = m c^2', 'E = m c^3')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('math' in d or '内容' in d for d in diffs), diffs)


class RichContainerDirectInlineTest(unittest.TestCase):
    """富容器直接 code/a 子节点保留自身语义（S12）：与 p 包装版本输出
    等价，代码语义不丢、链接目标不丢。"""

    def _render(self, body):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        html = ('<html><body><article><h1>H</h1>%s</article></body></html>'
                % body)
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        return html, '\n'.join(out).strip() + '\n'

    def test_direct_code_equals_wrapped_and_flattening_detected(self):
        html_direct, md_direct = self._render(
            '<ul><li>Use <code>x()</code></li></ul>')
        html_wrapped, md_wrapped = self._render(
            '<ul><li><p>Use <code>x()</code></p></li></ul>')
        self.assertEqual(md_direct, md_wrapped)
        self.assertIn('`x()`', md_direct)
        self.assertEqual(
            reconcile_html_to_markdown(html_direct, md_direct, 'single'), [])
        # 拍平为裸 x()（旧行为）必须被对账拒绝
        damaged = md_direct.replace('`x()`', 'x()')
        self.assertTrue(
            reconcile_html_to_markdown(html_direct, damaged, 'single'))

    def test_direct_code_content_protected_from_punctuation_tightening(self):
        # F6：正文标点整理不得进入代码内容——直接子节点与 p 包装等价，
        # `print("a ; b")` 的标点前空格逐字节保持
        html_direct, md_direct = self._render(
            '<ul><li>Use <code>print("a ; b")</code></li></ul>')
        html_wrapped, md_wrapped = self._render(
            '<ul><li><p>Use <code>print("a ; b")</code></p></li></ul>')
        self.assertEqual(md_direct, md_wrapped)
        self.assertIn('`print("a ; b")`', md_direct)
        self.assertEqual(
            reconcile_html_to_markdown(html_direct, md_direct, 'single'), [])
        details_html, details_md = self._render(
            '<details><summary>More</summary>'
            'Use <code>print("a ; b")</code></details>')
        self.assertIn('`print("a ; b")`', details_md)
        self.assertEqual(
            reconcile_html_to_markdown(details_html, details_md, 'single'),
            [])

    def test_direct_code_in_details(self):
        html, md = self._render(
            '<details><summary>More</summary>Use <code>x()</code></details>')
        self.assertIn('`x()`', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_direct_link_target_preserved(self):
        html, md = self._render(
            '<ul><li>Use <a href="https://example.com">manual</a></li></ul>')
        self.assertIn('[manual](https://example.com)', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])


class TableOwnershipTest(unittest.TestCase):
    """表格归属（A25/A27）：末尾空格位保留、格内代码归属与未解释跨度。"""

    CODE_TABLE = ('<html><body><article><h1>T</h1>'
                  '<table><tr><th>A</th><th>B</th></tr>'
                  '<tr><td>a</td><td><pre>x = 1</pre></td></tr></table>'
                  '</article></body></html>')

    @staticmethod
    def _render(html):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_code_only_trailing_cell_reconciles_clean(self):
        # 仅含代码的末尾单元格保留列位：源 2 格 = 输出 2 格（末格为空文字）
        md = self._render(self.CODE_TABLE)
        self.assertIn('a | ', md)
        self.assertEqual(reconcile_html_to_markdown(self.CODE_TABLE, md,
                                                    'single'), [])

    def test_coordinate_tamper_detected(self):
        md = self._render(self.CODE_TABLE)
        for tamper in ('r=9 c=9', 'r=2 c=1'):
            damaged = md.replace('[TABLE-CODE r=2 c=2#1]',
                                 '[TABLE-CODE %s#1]' % tamper)
            diffs = reconcile_html_to_markdown(self.CODE_TABLE, damaged,
                                               'single')
            self.assertTrue(
                any('格内代码归属不一致' in d for d in diffs), (tamper, diffs))

    def test_code_body_change_detected(self):
        md = self._render(self.CODE_TABLE)
        damaged = md.replace('x = 1', 'y = 1')
        diffs = reconcile_html_to_markdown(self.CODE_TABLE, damaged, 'single')
        self.assertTrue(
            any('格内代码归属不一致' in d for d in diffs), diffs[:3])

    def test_unexplained_span_blocked(self):
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th colspan="2">wide</th></tr>'
                '<tr><td>a</td><td>b</td></tr></table>'
                '</article></body></html>')
        md = '# T\n\n[TABLE]\nwide | wide\n--- | ---\na | b\n'
        diffs = reconcile_html_to_markdown(html, md, 'single')
        self.assertTrue(any('未解释跨行/跨列' in d for d in diffs), diffs[:3])


class ListOwnershipTest(unittest.TestCase):
    """列表归属（A25/A27）：标签越过代码与跨父列表移动必须检出。"""

    HTML = ('<html><body><article><h1>T</h1><ul>'
            '<li>label1<pre><code>c1</code></pre></li>'
            '<li>label2<pre><code>c2</code></pre></li>'
            '</ul></article></body></html>')

    CROSS_HTML = ('<html><body><article><h1>T</h1><ul>'
                  '<li>l1<pre><code>c1</code></pre></li>'
                  '<li>l2<pre><code>c2</code></pre></li>'
                  '</ul><p>mid</p><ul>'
                  '<li>l3<pre><code>c3</code></pre></li>'
                  '</ul></article></body></html>')

    @staticmethod
    def _render(html):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_faithful_parse_reconciles_clean(self):
        self.assertEqual(reconcile_html_to_markdown(
            self.HTML, self._render(self.HTML), 'single'), [])
        self.assertEqual(reconcile_html_to_markdown(
            self.CROSS_HTML, self._render(self.CROSS_HTML), 'single'), [])

    def test_label_moved_after_code_detected(self):
        # 标签与代码的各自顺序未变，仅归属（标签越过代码）变化
        md = self._render(self.HTML)
        damaged = md.replace('  - label2\n', '  -\n') + '  - label2\n'
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single')
        self.assertTrue(any('列表项' in d for d in diffs), diffs[:3])

    def test_cross_parent_move_detected(self):
        # l3 项移入第一个列表：扁平顺序不变，仅父列表归属变化
        md = self._render(self.CROSS_HTML)
        lines = md.split('\n')
        mid = lines.index('mid')
        damaged = '\n'.join(lines[:mid] + lines[mid + 1:] + ['mid', ''])
        diffs = reconcile_html_to_markdown(self.CROSS_HTML, damaged, 'single')
        self.assertTrue(
            any('列表项第 3 项' in d and "(1, 1," in d for d in diffs),
            diffs[:3])


class ListItemContentTest(unittest.TestCase):
    """列表项内块级内容的归属（设计 §8.1）：三个合法场景不误拒。"""

    @staticmethod
    def _render(html):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        out = []
        render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def _wrap(self, body):
        return '<html><body><article><h1>T</h1>%s</article></body></html>' % body

    def test_parent_code_after_child_list(self):
        html = self._wrap('<ul><li><p>Parent</p><ul><li>Child</li></ul>'
                          '<pre>parent_code()</pre></li></ul>')
        md = self._render(html)
        # 缩进围栏属父项内代码，不被归给栈顶子项
        self.assertIn('  ```', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_two_child_lists_with_continuation(self):
        html = self._wrap('<ul><li><p>Parent</p><ul><li>One</li></ul>'
                          '<p>Between</p><ul><li>Two</li></ul></li></ul>')
        md = self._render(html)
        # 子列表边界可多次记录：第二个子列表不被首个边界吞并
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_wrapped_paragraph_in_item(self):
        html = self._wrap('<ul><li><p>Parent</p><div><p>Inner</p></div>'
                          '<p>After</p></li></ul>')
        md = self._render(html)
        # 项内经 div 包装的段落按项层级缩进，不落列 0
        self.assertIn('\n  Inner', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_nested_item_code_at_level_two(self):
        html = self._wrap('<ul><li><p>P</p><ul><li><p>C</p>'
                          '<pre>child_code()</pre></li></ul></li></ul>')
        md = self._render(html)
        # 二级项围栏 4 空格缩进：扫描器识别，代码事实与归属保持
        self.assertIn('    ```', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])


class TableConversionMapTest(unittest.TestCase):
    """逐表转换映射核验合同（设计 §4.10）：合法展开通过，漏格/错内容拒绝。"""

    # 两层表头（rowspan/colspan）；转换候选把表头展开为合并格
    HTML = ('<html><body><article><h1>T</h1>'
            '<p>intro</p>'
            '<table id="features">'
            '<tr><th rowspan="2">Feature</th><th colspan="2">Support</th>'
            '</tr>'
            '<tr><th>Min</th><th>Max</th></tr>'
            '<tr><td>SM count</td><td><code>1</code></td><td>132</td></tr>'
            '</table>'
            '<p>outro</p>'
            '<div class="highlight"><pre>side()</pre></div>'
            '</article></body></html>')

    CONVERTED_MD = (
        '# T\n\nintro\n\n[TABLE]\n'
        'Feature | Support / Min | Support / Max\n'
        '--- | --- | ---\n'
        'SM count | `1` | 132\n\noutro\n\n```\nside()\n```\n')

    MAP = {
        'version': 1,
        'tables': [{
            'locate': {'table': 1},
            'cells': [
                {'row': 1, 'col': 1, 'rowspan': 2,
                 'targets': [{'table': 1, 'row': 1, 'col': 1}]},
                {'row': 1, 'col': 2, 'colspan': 2,
                 'targets': [{'table': 1, 'row': 1, 'col': 2},
                             {'table': 1, 'row': 1, 'col': 3}]},
                {'row': 2, 'col': 1,
                 'targets': [{'table': 1, 'row': 1, 'col': 2}]},
                {'row': 2, 'col': 2,
                 'targets': [{'table': 1, 'row': 1, 'col': 3}]},
                {'row': 3, 'col': 1,
                 'targets': [{'table': 1, 'row': 2, 'col': 1}]},
                {'row': 3, 'col': 2,
                 'targets': [{'table': 1, 'row': 2, 'col': 2}]},
                {'row': 3, 'col': 3,
                 'targets': [{'table': 1, 'row': 2, 'col': 3}]},
            ],
        }],
    }

    def test_valid_conversion_reconciles_clean(self):
        self.assertEqual(reconcile_html_to_markdown(
            self.HTML, self.CONVERTED_MD, 'single',
            table_conversions=self.MAP), [])

    def test_missing_cell_declaration_rejected(self):
        mapping = {
            'version': 1,
            'tables': [{
                'locate': {'table': 1},
                'cells': [cell for cell in self.MAP['tables'][0]['cells']
                          if (cell['row'], cell['col']) != (3, 3)],
            }],
        }
        diffs = reconcile_html_to_markdown(self.HTML, self.CONVERTED_MD,
                                           'single', table_conversions=mapping)
        self.assertTrue(any('未声明的源格' in d for d in diffs), diffs[:3])

    def test_wrong_output_content_rejected(self):
        damaged = self.CONVERTED_MD.replace('SM count', 'Widget count')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single',
                                           table_conversions=self.MAP)
        self.assertTrue(any('与声明源格不符' in d for d in diffs), diffs[:3])

    def test_tampered_expansion_rejected(self):
        # 逐输出格核验：数值篡改与附加文字不能借子串/子集比较放行
        for old, new in (('132', '132000'),
                         ('SM count', 'SM count EVIL_EXTRA')):
            damaged = self.CONVERTED_MD.replace(old, new)
            diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single',
                                               table_conversions=self.MAP)
            self.assertTrue(any('与声明源格不符' in d for d in diffs),
                            (old, diffs[:3]))

    def test_fabricated_output_cell_rejected(self):
        damaged = self.CONVERTED_MD.replace(
            'SM count | `1` | 132', 'SM count | `1` | 132\nAdded row | a | b')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single',
                                           table_conversions=self.MAP)
        self.assertTrue(any('无源格依据' in d for d in diffs), diffs[:3])

    def test_mapped_cell_math_reconciles_clean(self):
        # R1：公式条目标签为 inline/block（非 'math'），映射表格格位分类
        # 必须覆盖两类，格内已声明的合法公式展开通过对账
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>Name</th><th>Formula</th></tr>'
                '<tr><td>energy</td>'
                '<td><span class="math">\\(E=mc^2\\)</span></td></tr>'
                '<tr><td>area</td><td><span class="math">\\(A=\\pi r^2\\)'
                '</span></td></tr>'
                '</table></article></body></html>')
        md = ('# T\n\n[TABLE]\nName | Formula\n--- | ---\n'
              'energy | $E=mc^2$\narea | $A=\\pi r^2$\n')
        mapping = {
            'version': 1,
            'tables': [{
                'locate': {'table': 1},
                'cells': [
                    {'row': 1, 'col': 1,
                     'targets': [{'table': 1, 'row': 1, 'col': 1}]},
                    {'row': 1, 'col': 2,
                     'targets': [{'table': 1, 'row': 1, 'col': 2}]},
                    {'row': 2, 'col': 1,
                     'targets': [{'table': 1, 'row': 2, 'col': 1}]},
                    {'row': 2, 'col': 2,
                     'targets': [{'table': 1, 'row': 2, 'col': 2}]},
                    {'row': 3, 'col': 1,
                     'targets': [{'table': 1, 'row': 3, 'col': 1}]},
                    {'row': 3, 'col': 2,
                     'targets': [{'table': 1, 'row': 3, 'col': 2}]},
                ],
            }],
        }
        self.assertEqual(reconcile_html_to_markdown(
            html, md, 'single', table_conversions=mapping), [])

    def test_mapped_cell_block_math_reconciles_clean(self):
        # R1（block 类型）：paginated 家族 div.math 为块级公式条目
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>Case</th><th>Equation</th></tr>'
                '<tr><td>quadratic</td>'
                '<td><div class="math">\\[x=\\frac{-b}{2a}\\]</div></td></tr>'
                '</table></article></body></html>')
        md = ('# T\n\n[TABLE]\nCase | Equation\n--- | ---\n'
              'quadratic | $$x=\\frac{-b}{2a}$$\n')
        mapping = {
            'version': 1,
            'tables': [{
                'locate': {'table': 1},
                'cells': [
                    {'row': 1, 'col': 1,
                     'targets': [{'table': 1, 'row': 1, 'col': 1}]},
                    {'row': 1, 'col': 2,
                     'targets': [{'table': 1, 'row': 1, 'col': 2}]},
                    {'row': 2, 'col': 1,
                     'targets': [{'table': 1, 'row': 2, 'col': 1}]},
                    {'row': 2, 'col': 2,
                     'targets': [{'table': 1, 'row': 2, 'col': 2}]},
                ],
            }],
        }
        self.assertEqual(reconcile_html_to_markdown(
            html, md, 'paginated', table_conversions=mapping), [])

    def test_mapped_cell_math_swap_rejected(self):
        # R1 不削弱既有合同：交换两格公式仍须按格位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>Name</th><th>Formula</th></tr>'
                '<tr><td>energy</td>'
                '<td><span class="math">\\(E=mc^2\\)</span></td></tr>'
                '<tr><td>area</td><td><span class="math">\\(A=\\pi r^2\\)'
                '</span></td></tr>'
                '</table></article></body></html>')
        swapped = ('# T\n\n[TABLE]\nName | Formula\n--- | ---\n'
                   'energy | $A=\\pi r^2$\narea | $E=mc^2$\n')
        mapping = {
            'version': 1,
            'tables': [{
                'locate': {'table': 1},
                'cells': [
                    {'row': r, 'col': c,
                     'targets': [{'table': 1, 'row': r, 'col': c}]}
                    for r in (1, 2, 3) for c in (1, 2)
                ],
            }],
        }
        diffs = reconcile_html_to_markdown(
            html, swapped, 'single', table_conversions=mapping)
        self.assertTrue(any('格内内容归属不一致' in d for d in diffs), diffs[:3])

    def test_snapshot_digest_mismatch_rejected(self):
        import hashlib
        mapping = dict(self.MAP)
        mapping['snapshot_sha256'] = '0' * 64
        diffs = reconcile_html_to_markdown(self.HTML, self.CONVERTED_MD,
                                           'single', table_conversions=mapping)
        self.assertTrue(any('快照摘要不符' in d for d in diffs), diffs[:3])
        mapping['snapshot_sha256'] = hashlib.sha256(
            self.HTML.encode('utf-8')).hexdigest()
        self.assertEqual(reconcile_html_to_markdown(
            self.HTML, self.CONVERTED_MD, 'single',
            table_conversions=mapping), [])

    def test_table_id_locate_and_outside_content_checked(self):
        mapping = {
            'version': 1,
            'tables': [dict(self.MAP['tables'][0],
                            locate={'table_id': 'features'})],
        }
        self.assertEqual(reconcile_html_to_markdown(
            self.HTML, self.CONVERTED_MD, 'single',
            table_conversions=mapping), [])
        # 表外内容照常全量检查：删除表外代码围栏即拒绝
        damaged = self.CONVERTED_MD.replace('\n\n```\nside()\n```\n', '\n')
        diffs = reconcile_html_to_markdown(self.HTML, damaged, 'single',
                                           table_conversions=mapping)
        self.assertTrue(any('数量不一致' in d for d in diffs), diffs[:3])

    def test_note_target_for_moved_out_cell(self):
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>A</th><th>B</th></tr>'
                '<tr><td>v1</td><td>v2</td></tr>'
                '<tr><td colspan="2">Shared note for all rows</td></tr>'
                '</table></article></body></html>')
        md = ('# T\n\n适用范围：Shared note for all rows\n\n'
              '[TABLE]\nA | B\n--- | ---\nv1 | v2\n')
        mapping = {
            'version': 1,
            'tables': [{
                'locate': {'table': 1},
                'cells': [
                    {'row': 1, 'col': 1,
                     'targets': [{'table': 1, 'row': 1, 'col': 1}]},
                    {'row': 1, 'col': 2,
                     'targets': [{'table': 1, 'row': 1, 'col': 2}]},
                    {'row': 2, 'col': 1,
                     'targets': [{'table': 1, 'row': 2, 'col': 1}]},
                    {'row': 2, 'col': 2,
                     'targets': [{'table': 1, 'row': 2, 'col': 2}]},
                    {'row': 3, 'col': 1, 'colspan': 2,
                     'targets': [{'note': [3, 3]}]},
                ],
            }],
        }
        self.assertEqual(reconcile_html_to_markdown(
            html, md, 'single', table_conversions=mapping), [])
        damaged = md.replace('Shared note for all rows', 'Wrong note')
        diffs = reconcile_html_to_markdown(html, damaged, 'single',
                                          table_conversions=mapping)
        self.assertTrue(any('内容未在声明说明区间找到' in d for d in diffs),
                        diffs[:3])

    # ---- S04/S11：格内内容与代码按声明格位归属，不能靠全局多重集放行 ----

    IMAGE_TABLE = ('<html><body><article><h1>T</h1>'
                   '<table><tr><th>Case</th><th>Safe</th><th>Unsafe</th></tr>'
                   '<tr><td>copy</td><td><img src="safe.png"/></td>'
                   '<td><img src="unsafe.png"/></td></tr></table>'
                   '</article></body></html>')

    def _image_map(self):
        return {'version': 1, 'tables': [{'locate': {'table': 1}, 'cells':
                [{'row': r, 'col': c,
                  'targets': [{'table': 1, 'row': r, 'col': c}]}
                 for r in (1, 2) for c in (1, 2, 3)]}]}

    def test_image_swap_between_declared_cells_rejected(self):
        md = ('# T\n\n[TABLE]\nCase | Safe | Unsafe\n--- | --- | ---\n'
              'copy | ![s](safe.png) | ![u](unsafe.png)\n')
        self.assertEqual(reconcile_html_to_markdown(
            self.IMAGE_TABLE, md, 'single',
            table_conversions=self._image_map()), [])
        # 映射、文字与总数不变而交换 Safe/Unsafe 两格图片必须拒绝
        swapped = md.replace('![s](safe.png) | ![u](unsafe.png)',
                             '![u](unsafe.png) | ![s](safe.png)')
        diffs = reconcile_html_to_markdown(
            self.IMAGE_TABLE, swapped, 'single',
            table_conversions=self._image_map())
        self.assertTrue(any('格内内容归属不一致' in d for d in diffs),
                        diffs[:3])

    def test_same_cell_image_order_detected(self):
        # F2：格内出现顺序参与对账（等数乱序失败），同一格两张图交换
        # 必须拒绝；不能以每格多重集再次丢序
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td><img src="safe.png"/> '
                '<img src="unsafe.png"/></td><td>x</td></tr></table>'
                '</article></body></html>')
        mapping = {'version': 1, 'tables': [{'locate': {'table': 1}, 'cells': [
            {'row': 1, 'col': 1,
             'targets': [{'table': 1, 'row': 1, 'col': 1}]},
            {'row': 1, 'col': 2,
             'targets': [{'table': 1, 'row': 1, 'col': 2}]},
        ]}]}
        ordered = ('# T\n\n[TABLE]\n![s](safe.png) ![u](unsafe.png) | x\n'
                   '--- | ---\n')
        self.assertEqual(reconcile_html_to_markdown(
            html, ordered, 'single', table_conversions=mapping), [])
        swapped = ('# T\n\n[TABLE]\n![u](unsafe.png) ![s](safe.png) | x\n'
                   '--- | ---\n')
        diffs = reconcile_html_to_markdown(
            html, swapped, 'single', table_conversions=mapping)
        self.assertTrue(any('格内内容归属不一致' in d for d in diffs),
                        diffs[:3])

    def test_one_to_many_image_expansion_passes_and_missing_copy_rejected(self):
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th colspan="2"><img src="pic.png"/></th></tr>'
                '<tr><td>a</td><td>b</td></tr></table>'
                '</article></body></html>')
        mapping = {'version': 1, 'tables': [{'locate': {'table': 1}, 'cells': [
            {'row': 1, 'col': 1, 'colspan': 2, 'targets': [
                {'table': 1, 'row': 1, 'col': 1},
                {'table': 1, 'row': 1, 'col': 2}]},
            {'row': 2, 'col': 1,
             'targets': [{'table': 1, 'row': 2, 'col': 1}]},
            {'row': 2, 'col': 2,
             'targets': [{'table': 1, 'row': 2, 'col': 2}]},
        ]}]}
        md = ('# T\n\n[TABLE]\n![p](pic.png) | ![p](pic.png)\n--- | ---\n'
              'a | b\n')
        self.assertEqual(reconcile_html_to_markdown(
            html, md, 'single', table_conversions=mapping), [])
        # 一对多展开缺一份（删掉第二个输出格的图片）必须拒绝
        missing = ('# T\n\n[TABLE]\n![p](pic.png) | \n--- | ---\na | b\n')
        diffs = reconcile_html_to_markdown(
            html, missing, 'single', table_conversions=mapping)
        self.assertTrue(any('格内内容归属不一致' in d for d in diffs),
                        diffs[:3])

    def test_code_only_cell_without_target_rejected(self):
        # S11：纯代码源格声明 targets=[]（守卫键形修复后必须真正生效）
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td colspan="2"><pre>x=1</pre></td></tr>'
                '</table></article></body></html>')
        mapping_ok = {'version': 1, 'tables': [{'locate': {'table': 1},
                                                'cells': [
            {'row': 1, 'col': 1, 'colspan': 2,
             'targets': [{'table': 1, 'row': 1, 'col': 1}]}]}]}
        md_ok = ('# T\n\n[TABLE]\n \n\n[TABLE-CODE r=1 c=1#1]\n'
                 '```\nx=1\n```\n')
        self.assertEqual(reconcile_html_to_markdown(
            html, md_ok, 'single', table_conversions=mapping_ok), [])
        mapping_drop = {'version': 1, 'tables': [{'locate': {'table': 1},
                                                  'cells': [
            {'row': 1, 'col': 1, 'colspan': 2, 'targets': []}]}]}
        diffs = reconcile_html_to_markdown(
            html, '# T\n', 'single', table_conversions=mapping_drop)
        self.assertTrue(
            any('含格内代码但未声明输出格位' in d for d in diffs), diffs[:3])

    def test_declared_code_target_dropped_from_output_rejected(self):
        # S11：声明了输出格位但输出删光整块代码，同样必须拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td colspan="2"><pre>x=1</pre></td></tr>'
                '</table></article></body></html>')
        mapping = {'version': 1, 'tables': [{'locate': {'table': 1},
                                             'cells': [
            {'row': 1, 'col': 1, 'colspan': 2,
             'targets': [{'table': 1, 'row': 1, 'col': 1}]}]}]}
        diffs = reconcile_html_to_markdown(
            html, '# T\n\n[TABLE]\n \n', 'single', table_conversions=mapping)
        self.assertTrue(diffs, diffs[:3])


class PseudoHeadingBoundaryTest(unittest.TestCase):
    """R4/D4：普通文字与真实标题分别保真。

    行首 # 的普通段落、表格首格经共享出口转义后不再是伪标题；围栏与
    行内代码逐字保持；含管道、与代码注释同名的真实标题保留层级与顺序；
    输出侧独立对账仅在普通文本角色解码该转义，损伤仍按具体差异拒绝。
    """

    @staticmethod
    def _render(html, family='single'):
        import parse_single_page_html
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        out = []
        parse_single_page_html.render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_escape_only_first_hash_at_line_start(self):
        from _html_fidelity import heading_trigger_escape
        self.assertEqual(heading_trigger_escape('# define data'),
                         '\\# define data')
        # 原文字面 \# 按 Markdown 阅读语义加写：行首 k 个反斜线逐倍加写
        # （\\ 阅读为一个反斜线），# 裸写——实际阅读与原文逐字一致
        self.assertEqual(heading_trigger_escape('\\# define data'),
                         '\\\\# define data')
        self.assertEqual(heading_trigger_escape('\\\\# define data'),
                         '\\\\\\\\# define data')
        # 行尾形态（整行只有 #）与行首 # 后无空白：编码侧一并转义，与
        # 解码「只删一个反斜线」严格互逆
        self.assertEqual(heading_trigger_escape('#'), '\\#')
        self.assertEqual(heading_trigger_escape('##nospace'), '##nospace')
        self.assertEqual(heading_trigger_escape('\\#'), '\\\\#')
        # 同行第二个 # 不转义；行首空白/bullet 后的 # 以 markdown-it 为准
        # （  - # item 实际会成为列表内标题，经复合容器循环转义）
        self.assertEqual(heading_trigger_escape('use # tag here'),
                         'use # tag here')
        self.assertEqual(heading_trigger_escape('  - # item'),
                         '  - \\# item')
        # 多行逐行检查：只有会成为标题的行首被转义
        self.assertEqual(heading_trigger_escape('# a\nkeep # b\n## c'),
                         '\\# a\nkeep # b\n\\## c')

    def test_literal_backslash_hash_round_trip(self):
        # R2：源原文本就含字面 \#（如配置注释）时，渲染端须再加一个
        # 反斜线、输出侧解码只删一个，解析→独立对账往返一致
        html = ('<html><body><article><h1>T</h1>'
                '<p>\\# config</p></article></body></html>')
        md = self._render(html)
        self.assertIn('\\\\# config', md)
        self.assertEqual(heading_entries(md), [(1, 1, 'T')])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        # 译文侧按渲染端同一转义手写普通文字同样一致（\# 阅读为 #）
        hand = '# T\n\n\\# config\n'
        html_hash = ('<html><body><article><h1>T</h1>'
                     '<p># config</p></article></body></html>')
        self.assertEqual(
            reconcile_html_to_markdown(html_hash, hand, 'single'), [])

    def test_paragraph_table_comment_reconcile_clean(self):
        html = ('<html><body><article><h1>T</h1>'
                '<p># define data first</p>'
                '<p>preprocessor flag with # inline mention</p>'
                '<table><tr><th>#</th><th>name</th></tr>'
                '<tr><td>1</td><td>alpha</td></tr></table>'
                '<pre><code># fenced comment\nx = 1  # inline comment\n'
                '</code></pre>'
                '<p>use <code># inline code</code> here</p>'
                '</article></body></html>')
        md = self._render(html)
        # 普通段落与表格首格只在行首第一个 # 前加反斜线；代码逐字保持
        self.assertIn('\\# define data first', md)
        self.assertIn('\\# | name', md)
        self.assertIn('# fenced comment\nx = 1  # inline comment', md)
        self.assertIn('`# inline code`', md)
        entries = heading_entries(md)
        self.assertEqual([(lvl, t) for _, lvl, t in entries], [(1, 'T')])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_unescaped_paragraph_becomes_pseudo_heading_rejected(self):
        html = ('<html><body><article><h1>T</h1>'
                '<p># define data</p></article></body></html>')
        md = self._render(html)
        damaged = md.replace('\\# define data', '# define data')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d and '数量不一致' in d for d in diffs),
                        diffs)

    def test_list_item_text_hash_escaped(self):
        # R3：列表项首段/项内后续段落行首 # 在真实 Markdown（markdown-it）
        # 中会成为列表内 ATX 标题，渲染端须在共享出口转义，且对账通过
        import markdown_it
        html = ('<html><body><article><h1>T</h1>'
                '<ul><li><p># define data</p></li>'
                '<li>intro<p># second paragraph</p></li></ul>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('- \\# define data', md)
        self.assertIn('  \\# second paragraph', md)
        tokens = markdown_it.MarkdownIt().parse(md)
        # 只允许文档真实标题 # T；列表行不得渲染为标题
        self.assertEqual([t.tag for t in tokens if t.type == 'heading_open'],
                         ['h1'], md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        # 既有「去转义产生伪标题」合同不削弱：手写 - # define data 被拒
        damaged = md.replace('- \\# define data', '- # define data')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_list_item_real_heading_damage_rejected(self):
        # R3 对账侧：heading_entries 原只认列 0 行首，译文手写列表内真实
        # 标题（源项文字恰为 # 开头时）会与源互相豁免；识别边界须覆盖
        # 项首 bullet 后的 ATX 标题，制造真实标题即拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<ul><li><p># Heading</p></li></ul>'
                '</article></body></html>')
        md = '# T\n\n- # Heading\n'
        diffs = reconcile_html_to_markdown(html, md, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)
        # 渲染端自身输出（转义后）仍通过对账
        self.assertEqual(
            reconcile_html_to_markdown(html, self._render(html), 'single'),
            [])

    def test_real_heading_inside_list_item_unaffected(self):
        # R3 不削弱真实标题路径：源 <li><h2> 仍走真实标题分支，不转义、
        # 原有输出形态保持不变
        html = ('<html><body><article><h1>T</h1>'
                '<ul><li><h2>Real Title</h2><p>body</p></li></ul>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('## Real Title', md)
        self.assertNotIn('\\## Real Title', md)
        entries = heading_entries(md)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'Real Title')])

    def test_admonition_text_hash_escaped(self):
        # R3 补充：提示框引用行行首 # 在真实 Markdown（markdown-it）中会
        # 成为引用内 ATX 标题，渲染端经共享出口转义，且对账通过
        import markdown_it
        html = ('<html><body><article><h1>T</h1>'
                '<div class="admonition note">'
                '<p class="admonition-title">Note</p>'
                '<p># note text</p></div>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('> \\# note text', md)
        tokens = markdown_it.MarkdownIt().parse(md)
        self.assertEqual([t.tag for t in tokens if t.type == 'heading_open'],
                         ['h1'], md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        # 既有合同不削弱：手写 > # note text 伪标题被拒
        damaged = md.replace('> \\# note text', '> # note text')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_admonition_real_heading_damage_rejected(self):
        # R3 补充对账侧：heading_entries 原不覆盖引用前缀，译文手写
        # 提示框内真实标题（源文字恰为 # 开头时）与源互相豁免；识别边界
        # 增补引用前缀形态后须拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<div class="admonition note">'
                '<p class="admonition-title">Note</p>'
                '<p># Note</p></div>'
                '</article></body></html>')
        md = '# T\n\n> **ADMONITION [Note]**\n> # Note\n'
        diffs = reconcile_html_to_markdown(html, md, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)
        # 渲染端自身输出（转义后）仍通过对账
        self.assertEqual(
            reconcile_html_to_markdown(html, self._render(html), 'single'),
            [])

    def test_real_heading_inside_admonition_unaffected(self):
        # R3 补充不削弱真实标题路径：提示框内直接子级 <h2> 的既有渲染
        # 形态保持不变（该形态源侧标题事实仍在，缺标题被对账阻断；对
        # 其结构的处置不在本次修复范围）
        html = ('<html><body><article><h1>T</h1>'
                '<div class="admonition note">'
                '<p class="admonition-title">Note</p>'
                '<h2>Real Title</h2><p>body</p></div>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(
            md, '# T\n\n> **ADMONITION [Note]**\n> body\n')
        diffs = reconcile_html_to_markdown(html, md, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)
        # 真实标题本身不转义：提示框之后的 <h2> 原样输出
        html2 = ('<html><body><article><h1>T</h1>'
                 '<div class="admonition note">'
                 '<p class="admonition-title">Note</p>'
                 '<p># note text</p></div>'
                 '<h2>Real Title</h2>'
                 '</article></body></html>')
        md2 = self._render(html2)
        self.assertIn('> \\# note text', md2)
        self.assertIn('\n## Real Title', md2)
        self.assertNotIn('\\## Real Title', md2)

    def test_real_pipe_and_comment_named_headings_kept(self):
        html = ('<html><body><article><h1>T</h1>'
                '<h2>Config | Range</h2><p>intro</p>'
                '<h2># config</h2><p>after</p>'
                '<pre><code># config\nx = 1\n</code></pre>'
                '</article></body></html>')
        md = self._render(html)
        # 真实标题（含管道、与代码注释同名）保留层级与顺序，均不转义
        self.assertLess(md.index('## Config | Range'),
                        md.index('## # config'))
        entries = heading_entries(md)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'Config | Range'), (2, '# config')])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        # 删除真实标题仍被具体差异拒绝
        diffs = reconcile_html_to_markdown(
            html, md.replace('## Config | Range\n', ''), 'single')
        self.assertTrue(any('标题' in d and '数量不一致' in d for d in diffs))
        # 改层级仍被拒绝（独立对账有序标题流定位到具体条目）
        diffs = reconcile_html_to_markdown(
            html, md.replace('## Config | Range', '### Config | Range'),
            'single')
        self.assertTrue(any('标题' in d and 'Config | Range' in d
                            for d in diffs), diffs)

    def test_heading_text_and_list_roles_round_trip(self):
        # 列表项行首 # 经共享出口转义（R3：bullet 后仍是 Markdown 行首）；
        # 提示框、定义术语中的行首 # 文字不转义；项内经容器包装的
        # 段落在输出侧解码后与源文字一致（对账不依赖删除内容）
        html = ('<html><body><article><h1>T</h1>'
                '<ul><li># list item text</li>'
                '<li><div><p># wrapped paragraph</p></div></li></ul>'
                '<div class="admonition note">'
                '<p class="admonition-title">Note</p><p># note text</p></div>'
                '<dl><dt># term</dt><dd>meaning</dd></dl>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('- \\# list item text', md)
        self.assertIn('> \\# note text', md)
        self.assertIn('**# term**', md)
        self.assertEqual(heading_entries(md), [(1, 1, 'T')])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_escape_does_not_touch_math_or_links(self):
        html = ('<html><body><article><h1>T</h1>'
                '<p># head <span class="math">x^2</span> and '
                '<a href="u">label</a></p></article></body></html>')
        md = self._render(html)
        self.assertIn('\\# head $x^2$ and [label](u)', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('$x^2$', '$y^2$')
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('math' in d or '内容' in d for d in diffs), diffs)

    def test_duplicate_h1_in_output_rejected(self):
        html = ('<html><body><article><h1>T</h1><p>body</p>'
                '</article></body></html>')
        md = self._render(html)
        damaged = md + '\n# T\n'
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d and '数量不一致' in d for d in diffs),
                        diffs)


class MarkdownContextConvergenceTest(unittest.TestCase):
    """A2/A3 收敛：编码/解码/标题事实统一以 markdown-it 实际解析为准。

    A2：表格第二格字面 \\# 合法输入须通过对账；首格多反斜线以 markdown-it
    实际阅读文字为验收（不再以「加一/删一」字符串互逆为证）。
    A3：标题事实由 markdown-it 块解析给出（列表续行、引用、复合容器天然
    覆盖）；删转义产生真实标题的损伤必须拒绝。
    """

    @staticmethod
    def _render(html, family='single'):
        import parse_single_page_html
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        out = []
        parse_single_page_html.render(soup.find('article'), out, fidelity)
        return '\n'.join(out).strip() + '\n'

    @staticmethod
    def _cell_readings(md_text):
        from bs4 import BeautifulSoup
        from markdown_it import MarkdownIt
        md = MarkdownIt('commonmark', {'html': False}).enable('table')
        soup = BeautifulSoup(md.render(md_text), 'html.parser')
        return [cell.get_text() for cell in soup.find_all(['td', 'th'])]

    @staticmethod
    def _atx_headings(md_text):
        from markdown_it import MarkdownIt
        md = MarkdownIt('commonmark', {'html': False}).enable('table')
        return [(tok.tag, tok.map[0] + 1)
                for tok in md.parse(md_text)
                if tok.type == 'heading_open' and tok.markup.startswith('#')]

    def test_table_second_cell_literal_backslash_reconciles(self):
        # F1/A2：GFM 格位是行内语境，\+ASCII 标点的阅读会丢反斜线——
        # 序列化按阅读语义加写（\\ 阅读为一个反斜线），对账逐格比较源
        # 字面文字与实际 Markdown 阅读
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>Key</th><th>Value</th></tr>'
                '<tr><td>config</td><td>\\# config</td></tr>'
                '<tr><td>escape</td><td>a\\_b\\*c</td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._atx_headings(md), [('h1', 1)])
        # 直接验收：逐格实际阅读与源字面文字一致
        self.assertEqual(self._cell_readings(md),
                         ['Key', 'Value', 'config', '\\# config',
                          'escape', 'a\\_b\\*c'])

    def test_heading_trailing_content_hash_preserved(self):
        # F2：内容性尾部 # 是标题内容（非 ATX 关闭标记）——序列化保留
        # 内容符号（\# 阅读为 #），标题事实与独立 DOM 严格对照
        for tail in ('#', '###'):
            html = ('<html><body><article><h1>T</h1>'
                    '<h2>Title %s</h2><p>body</p></article></body></html>'
                    % tail)
            md = self._render(html)
            # 实际阅读保留尾部 #
            from bs4 import BeautifulSoup
            from markdown_it import MarkdownIt
            rendered = MarkdownIt(
                'commonmark', {'html': False}).render(md)
            heads = [h.get_text() for h in BeautifulSoup(
                rendered, 'html.parser').find_all('h2')]
            self.assertEqual(heads, ['Title %s' % tail], md)
            # 合法输入可处理
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [])
            # 删除内容符号被拒绝
            escaped_tail = ''.join('\\#' for _ in tail)
            damaged = md.replace(' ' + escaped_tail, '')
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(any('标题' in d for d in diffs),
                            (tail, diffs))

    def test_heading_trailing_literal_backslash_hash(self):
        # F2 同族：标题原文含字面 \#（反斜线+# 都是内容字符）
        html = ('<html><body><article><h1>T</h1>'
                '<h2>Title \\#</h2><p>body</p></article></body></html>')
        md = self._render(html)
        from bs4 import BeautifulSoup
        from markdown_it import MarkdownIt
        rendered = MarkdownIt('commonmark', {'html': False}).render(md)
        heads = [h.get_text() for h in BeautifulSoup(
            rendered, 'html.parser').find_all('h2')]
        self.assertEqual(heads, ['Title \\#'], md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_table_first_cell_multi_backslash_reading_exact(self):
        # A2：首格两个字面反斜线——实际阅读文字须与原文逐字一致
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><th>Value</th><th>Key</th></tr>'
                '<tr><td>\\\\# config</td><td>x</td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        readings = self._cell_readings(md)
        self.assertIn('\\\\# config', readings)
        self.assertEqual(self._atx_headings(md), [('h1', 1)])

    def test_paragraph_multi_backslash_reading_exact(self):
        # A2：普通段落同样以实际阅读文字为验收（多反斜线不丢字）
        html = ('<html><body><article><h1>T</h1>'
                '<p>\\\\# config</p></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        from bs4 import BeautifulSoup
        from markdown_it import MarkdownIt
        rendered = MarkdownIt('commonmark', {'html': False}).render(md)
        text = BeautifulSoup(rendered, 'html.parser').get_text()
        self.assertIn('\\\\# config', text)
        self.assertEqual(self._atx_headings(md), [('h1', 1)])

    def test_list_continuation_unescape_damage_rejected(self):
        # A3：项内续行行首 # 删转义后在真实 Markdown 中成为标题，标题
        # 事实（markdown-it 解析）必须检出，源对账不再互相豁免
        html = ('<html><body><article><h1>T</h1>'
                '<ul><li><p>intro</p><p># inner</p></li></ul>'
                '</article></body></html>')
        md = self._render(html)
        self.assertIn('\\# inner', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('\\# inner', '# inner')
        self.assertEqual(self._atx_headings(damaged),
                         [('h1', 1), ('h1', 4)])
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_compound_quote_list_paragraph_escaped(self):
        # A3：普通段落文字「> - # text」由解析 CLI 正常生成，编码侧按
        # markdown-it 实际解析转义（复合容器形态），产物无标题、对账通过；
        # 删转义的真实标题损伤被拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<p>&gt; - # text</p></article></body></html>')
        md = self._render(html)
        self.assertEqual(self._atx_headings(md), [('h1', 1)])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        damaged = md.replace('\\# text', '# text')
        self.assertEqual(self._atx_headings(damaged),
                         [('h1', 1), ('h1', 3)])
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)


class SerializationReadingConvergenceTest(unittest.TestCase):
    """R1–R3 收敛：源字面反斜线与生成语法转义在节点出口区分，保护区
    复用代码感知的公式事实，标题序列化与事实读取同一阅读语义。

    R1：代码与伪数学保护区不得重叠，编码/解码不重复拼接保护区。
    R2：链接标签的生成 \\[ \\] 不被再次加写；字面反斜线标签保真；
    双重加写的阅读损伤必须被独立对账拒绝。
    R3：真实标题任意数量字面反斜线按阅读语义保真，合法输入不误拒。
    """

    _render = staticmethod(MarkdownContextConvergenceTest._render)
    _cell_readings = staticmethod(
        MarkdownContextConvergenceTest._cell_readings)

    @staticmethod
    def _heading_readings(md_text, tag='h2'):
        from bs4 import BeautifulSoup
        from markdown_it import MarkdownIt
        rendered = MarkdownIt('commonmark', {'html': False}).render(md_text)
        return [h.get_text() for h in BeautifulSoup(
            rendered, 'html.parser').find_all(tag)]

    def test_heading_inline_code_dollar_not_duplicated(self):
        # R1：标题行内代码内的 $…$ 不再被识别为独立公式区间
        html = ('<html><body><article><h1>T</h1>'
                '<h2>Literal <code>$a\\b$</code></h2>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._heading_readings(md), ['Literal $a\\b$'])
        self.assertEqual(md.count('$a\\b$'), 1, md)

    def test_table_code_currency_not_duplicated(self):
        # R1：格内代码的金额文本不产生重复正文与多余定界符
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td>'
                '<td><code>\\# costs $5 and $10</code></td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._cell_readings(md),
                         ['name', '\\# costs $5 and $10'])
        self.assertEqual(md.count('$5 and $10'), 1, md)

    def test_table_link_bracket_reading_preserved(self):
        # R2：链接标签的生成语法转义不被再次加写，阅读与链接目标保持
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td>'
                '<td><a href="https://example.com">A[B]</a></td>'
                '</tr></table></article></body></html>')
        md = self._render(html)
        self.assertIn('[A\\[B\\]](https://example.com)', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._cell_readings(md), ['name', 'A[B]'])

    def test_table_link_literal_backslash_label_preserved(self):
        # R2：原文字面含反斜线的链接标签保真，不整体豁免链接
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td>'
                '<td><a href="https://example.com">A\\[B\\]</a></td>'
                '</tr></table></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._cell_readings(md), ['name', 'A\\[B\\]'])
        # 阅读丢反斜线的损伤（标签退化为单层转义）被拒绝
        damaged = md.replace('[A' + '\\' * 3 + '[B' + '\\' * 3 + ']'
                             '](https://example.com)',
                             '[A\\[B\\]](https://example.com)')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('表格' in d for d in diffs), diffs)

    def test_table_link_double_escape_damage_rejected(self):
        # R2：双重加写（阅读多出原文没有的反斜线）不得漏过对账
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td>'
                '<td><a href="https://example.com">A[B]</a></td>'
                '</tr></table></article></body></html>')
        md = self._render(html)
        damaged = md.replace('[A\\[B\\]](https://example.com)',
                             '[A\\\\[B\\\\]](https://example.com)')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('表格' in d for d in diffs), diffs)

    def test_heading_literal_backslashes_preserved(self):
        # R3：两个/一个字面反斜线的真实标题按阅读语义保真；丢一个被拒
        cases = [
            # (源标题字面, 产物行, 损伤行)
            ('Title \\\\#',
             '## Title ' + '\\' * 5 + '#',
             '## Title ' + '\\' * 3 + '#'),
            ('Title \\_tail',
             '## Title ' + '\\' * 3 + '_tail',
             '## Title \\_tail'),
        ]
        for source, line, damaged_line in cases:
            html = ('<html><body><article><h1>T</h1>'
                    '<h2>%s</h2></article></body></html>' % source)
            md = self._render(html)
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [])
            self.assertEqual(self._heading_readings(md), [source], md)
            damaged = md.replace(line, damaged_line)
            self.assertNotEqual(damaged, md)
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_h7_h8_fact_decodes_reading_escapes(self):
        # R3 同族：H7/H8 扩展路径与 ATX 同一阅读语义解码
        entries = heading_entries('####### Title \\\\_tail\n')
        self.assertEqual(entries, [(1, 7, 'Title \\_tail')])

    def test_heading_link_literal_backslash_label_preserved(self):
        # F1：标题链接标签的字面反斜线是阅读内容，不再被二次解释；
        # 合法输入不误拒，链接目标与内容性尾部 # 保持
        html = ('<html><body><article><h1>T</h1>'
                '<h2><a href="https://example.com">A\\[B\\]</a> #</h2>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._heading_readings(md), ['A\\[B\\] #'])
        line = next(l for l in md.split('\n') if l.startswith('## '))
        self.assertIn('(https://example.com)', line)

    def test_heading_link_literal_backslash_damage_rejected(self):
        # F1：删除标题标签的字面反斜线（阅读退化为 A[B]）被标题对账拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<h2><a href="https://example.com">A\\[B\\]</a> #</h2>'
                '</article></body></html>')
        md = self._render(html)
        damaged = re.sub(r'\[((?:\\.|[^\[\]])*)\]\(https://example\.com\)',
                         '[A[B\\]](https://example.com)', md)
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_table_link_literal_stars_reading_preserved(self):
        # F2：源标签的字面反斜线与星号逐字保持（单/双星号同一职责，
        # 不设数量例外），链接目标保持
        for label, expected in [('A\\*B\\*', 'A\\*B\\*'),
                                ('A\\**B\\**', 'A\\**B\\**')]:
            html = ('<html><body><article><h1>T</h1>'
                    '<table><tr><td>name</td>'
                    '<td><a href="https://example.com">%s</a></td>'
                    '</tr></table></article></body></html>' % label)
            md = self._render(html)
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [])
            self.assertEqual(self._cell_readings(md), ['name', expected],
                             (label, md))
            self.assertIn('(https://example.com)', md)

    def test_table_link_star_deletion_damage_rejected(self):
        # F2：删除产物标签中的星号（单/双同职责），独立对账定位拒绝
        for label in ('A\\*B\\*', 'A\\**B\\**'):
            html = ('<html><body><article><h1>T</h1>'
                    '<table><tr><td>name</td>'
                    '<td><a href="https://example.com">%s</a></td>'
                    '</tr></table></article></body></html>' % label)
            md = self._render(html)
            link = re.search(r'\[(?:\\.|[^\[\]])*\]\(https://example\.com\)',
                             md)
            self.assertIsNotNone(link, md)
            damaged = md.replace(link.group(0),
                                 link.group(0).replace('*', ''))
            self.assertNotEqual(damaged, md)
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(any('表格' in d for d in diffs), (label, diffs))

    def test_table_link_math_star_expression_preserved(self):
        # P2-1：链接内公式免于普通 Markdown 阅读解释，合法输入不误拒，
        # 表达式与链接目标按共享公式事实保持
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td><a href="https://example.com">'
                '<span class="math">a*b*c</span></a></td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        self.assertIn('[$a*b*c$](https://example.com)', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])

    def test_table_link_math_expression_damage_rejected(self):
        # P2-1：修改公式表达式的损伤被定位拒绝，失败原因含目标表达式
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td><a href="https://example.com">'
                '<span class="math">a*b*c</span></a></td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        damaged = md.replace('$a*b*c$', '$a*b*d$')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('a*b' in d for d in diffs), diffs)

    def test_table_link_bracketed_math_expression_preserved(self):
        # P2-1 组合：方括号/小括号包公式的链接标签，生成括号转义不遮住
        # 内部美元公式，合法输入不误拒，表达式与链接目标保持
        cases = [
            ('A[<span class="math">a*b*c</span>]', '[A\\[$a*b*c$ \\]]'),
            ('[<span class="math">a*b*c</span>]', '[\\[$a*b*c$ \\]]'),
            ('[<span class="math">x</span>]', '[\\[$x$ \\]]'),
            ('(<span class="math">a*b*c</span>)', '[($a*b*c$)]'),
        ]
        for label, fragment in cases:
            html = ('<html><body><article><h1>T</h1>'
                    '<table><tr><td>name</td>'
                    '<td><a href="https://example.com">%s</a></td>'
                    '</tr></table></article></body></html>' % label)
            md = self._render(html)
            self.assertIn('%s(https://example.com)' % fragment,
                          md, (label, md))
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [],
                (label, md))

    def test_table_link_bracketed_math_damage_rejected(self):
        # P2-1 组合：修改表达式、删除公式、删除内容性方括号分别被定位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td>'
                '<td><a href="https://example.com">'
                'A[<span class="math">a*b*c</span>]</a></td>'
                '</tr></table></article></body></html>')
        md = self._render(html)
        base = '[A\\[$a*b*c$ \\]](https://example.com)'
        self.assertIn(base, md)
        cases = [
            ('[A\\[$a*b*d$ \\]](https://example.com)', 'a*b'),
            ('[A\\[ \\]](https://example.com)', '表格'),
            ('[A$a*b*c$ ](https://example.com)', '表格'),
        ]
        for damaged_link, key in cases:
            damaged = md.replace(base, damaged_link)
            self.assertNotEqual(damaged, md)
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(any(key in d for d in diffs),
                            (damaged_link, diffs))

    def test_table_link_adjacent_math_dollars_preserved(self):
        # P2 复审：源标签公式归一复用共享 scan_math 边界，相邻美元公式
        # 的闭合/开启美元不被吞并，合法输入不误拒，按序表达式与链接
        # 目标保持
        cases = [
            ('[$x$$y$]', '[\\[$x$$y$\\]]'),
            ('$x$$y$', '[$x$$y$]'),
            ('($x$$y$)', '[($x$$y$)]'),
            ('$x$ $y$', '[$x$ $y$]'),
        ]
        for label, fragment in cases:
            html = ('<html><body><article><h1>T</h1>'
                    '<table><tr><td><a href="https://example.com">%s</a>'
                    '</td></tr></table></article></body></html>' % label)
            md = self._render(html)
            self.assertIn('%s(https://example.com)' % fragment,
                          md, (label, md))
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [],
                (label, md))

    def test_table_link_source_literal_brackets_math_preserved(self):
        # 源字面 \[ \] 不作块级定界；相邻美元公式与字面文字各自保留。
        from bs4 import BeautifulSoup
        from export_pdf import build_markdown
        from _verification import scan_math

        for label, reading in [(r'\[$x$$y$\]', r'\[xy\]'),
                               (r'A\[$x$$y$\]', r'A\[xy\]'),
                               (r'\[$x$ $y$\]', r'\[x y\]')]:
            html = ('<html><body><article><h1>T</h1>'
                    '<table><tr><td><a href="https://example.com">%s</a>'
                    '</td></tr></table></article></body></html>' % label)
            md = self._render(html)
            self.assertEqual(
                reconcile_html_to_markdown(html, md, 'single'), [], label)
            sink = []
            consumer, _ = build_markdown(sink, 'probe-',
                                         scan_math(md).spans, md)
            rendered = BeautifulSoup(consumer.render(md), 'html.parser')
            maths = rendered.find_all(attrs={'data-tex': True})
            self.assertEqual([m['data-tex'] for m in maths], ['x', 'y'])
            for math in maths:
                math.replace_with(math['data-tex'])
            link = rendered.find('a')
            self.assertEqual(link['href'], 'https://example.com')
            self.assertEqual(link.get_text(), reading)

    def test_table_link_source_literal_brackets_math_stars_preserved(self):
        # 相同源角色也用于序列化：美元公式内的星号不作正文强调加写。
        from bs4 import BeautifulSoup
        from export_pdf import build_markdown
        from _verification import scan_math

        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td><a href="https://example.com">'
                r'\[$a*b*c$$y$\]</a></td></tr></table>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        sink = []
        consumer, _ = build_markdown(sink, 'probe-', scan_math(md).spans, md)
        rendered = BeautifulSoup(consumer.render(md), 'html.parser')
        self.assertEqual([m['data-tex'] for m in
                          rendered.find_all(attrs={'data-tex': True})],
                         ['a*b*c', 'y'])
        damaged = md.replace('$a*b*c$', '$a*b*d$')
        self.assertNotEqual(md, damaged)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('a*b*d' in d for d in diffs), diffs)

    def test_table_link_adjacent_math_dollars_damage_rejected(self):
        # P2 复审：删除任一公式、修改表达式、交换顺序、删除内容性方括号
        # 分别被适用检查按目标损伤定位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td><a href="https://example.com">'
                '[$x$$y$]</a></td></tr></table></article></body></html>')
        md = self._render(html)
        base = '[\\[$x$$y$\\]](https://example.com)'
        self.assertIn(base, md)
        cases = [
            ('[\\[$x$\\]](https://example.com)', '表格'),
            ('[\\[$x$$z$\\]](https://example.com)', "'z'"),
            ('[\\[$y$$x$\\]](https://example.com)', "('inline', 'y')"),
            ('[$x$$y$](https://example.com)', '表格'),
        ]
        for damaged_link, key in cases:
            damaged = md.replace(base, damaged_link)
            self.assertNotEqual(damaged, md)
            diffs = reconcile_html_to_markdown(html, damaged, 'single')
            self.assertTrue(any(key in d for d in diffs),
                            (damaged_link, diffs))

    def test_heading_literal_bold_stars_preserved(self):
        # P2-2：真实标题的内容性星号是阅读文字，逐字保留；
        # 删除四个星号及其转义被标题对账定位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<h2>A**B**</h2></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._heading_readings(md), ['A**B**'])
        damaged = md.replace('A\\*\\*B\\*\\*', 'AB')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_heading_link_literal_bold_stars_preserved(self):
        # P2-2 同根因：标题链接标签的内容性星号逐字保留，链接目标保持；
        # 删除星号被标题对账定位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<h2><a href="https://example.com">A**B**</a></h2>'
                '</article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._heading_readings(md), ['A**B**'])
        line = next(l for l in md.split('\n') if l.startswith('## '))
        self.assertIn('(https://example.com)', line)
        damaged = md.replace('A\\*\\*B\\*\\*', 'AB')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('标题' in d for d in diffs), diffs)

    def test_cell_literal_bold_stars_preserved(self):
        # P2-2 同根因：非链接格位的内容性星号逐字保留；
        # 删除星号被表格对账定位拒绝
        html = ('<html><body><article><h1>T</h1>'
                '<table><tr><td>name</td><td>A**B**</td></tr>'
                '</table></article></body></html>')
        md = self._render(html)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'single'), [])
        self.assertEqual(self._cell_readings(md), ['name', 'A**B**'])
        damaged = md.replace('A\\*\\*B\\*\\*', 'AB')
        self.assertNotEqual(damaged, md)
        diffs = reconcile_html_to_markdown(html, damaged, 'single')
        self.assertTrue(any('表格' in d for d in diffs), diffs)


class SectionAttributionTest(unittest.TestCase):
    """章节归属对账：跨节移动与脚注正文替换必须检出（R9/S9-S10）。"""

    HTML = (
        '<html><body><article>'
        '<h1>1. Probe</h1>'
        '<h2>1.1. A</h2>'
        '<div class="highlight"><pre>alpha()</pre></div>'
        '<h2>1.2. B</h2>'
        '<div class="highlight"><pre>beta()</pre></div>'
        '</article></body></html>'
    )

    ASIDE_HTML = (
        '<html><body><article><h1>T</h1>'
        '<p>ref<span class="footnote-reference brackets">'
        '<a href="#fn1">[1]</a></span>.</p>'
        '<aside class="footnote brackets" role="doc-footnote" id="fn1">'
        '<span class="brackets">[1]</span> 现代脚注正文内容。</aside>'
        '</article></body></html>'
    )

    @staticmethod
    def _render(html):
        from parse_single_page_html import render
        from _html_fidelity import HtmlFidelity
        fidelity = HtmlFidelity(snapshot_dir='/nonexistent')
        soup = fidelity.parse(html)
        root = soup.find('article') or soup.find('body')
        out = []
        render(root, out, fidelity)
        return '\n'.join(out).strip() + '\n'

    def test_faithful_parse_reconciles_clean(self):
        self.assertEqual(reconcile_html_to_markdown(
            self.HTML, self._render(self.HTML), 'single'), [])

    def test_code_moved_between_sections_detected(self):
        md = self._render(self.HTML)
        moved = md.replace('## 1.1. A\n\n```\nalpha()\n```',
                           '## 1.1. A\n\n```\nbeta()\n```')
        moved = moved.replace('## 1.2. B\n\n```\nbeta()\n```',
                              '## 1.2. B\n\n```\nalpha()\n```')
        diffs = reconcile_html_to_markdown(self.HTML, moved, 'single')
        self.assertTrue(
            any('第 1 项不一致' in d and "'alpha()'" in d for d in diffs)
            and any("'beta()'" in d for d in diffs), diffs[:3])

    def test_aside_footnote_parsed_and_checked(self):
        md = self._render(self.ASIDE_HTML)
        self.assertIn('[FOOTNOTE-LIST]', md)
        self.assertIn('[[1]] 现代脚注正文内容', md)
        self.assertEqual(reconcile_html_to_markdown(
            self.ASIDE_HTML, md, 'single'), [])
        tampered = md.replace('现代脚注正文内容', '被替换的脚注正文')
        diffs = reconcile_html_to_markdown(self.ASIDE_HTML, tampered, 'single')
        self.assertTrue(any('脚注定义' in d for d in diffs))


if __name__ == '__main__':
    unittest.main()
