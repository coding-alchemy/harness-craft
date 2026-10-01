"""标题/脚注/强 token 核验的固定语义验收（任务 04）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_headings,
    footnote_diffs,
    heading_entries,
    heading_title_matches,
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
