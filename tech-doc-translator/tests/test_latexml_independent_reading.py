"""二期复评修复回归：独立事实阅读、非公式节点区间对齐、脚注完整结构。

覆盖复评四项未闭合问题中代码侧的三项（第四项为真实交付验收证据）：

- S1（规范轴）：独立源事实不得调用生成侧出口。共享 paragraph_text 被注
  入删词故障时独立对账必须拒绝；字面 `*`/`_`/反斜线经生成端按阅读语义
  加写后真实阅读与原文字面一致，裸写（未加写）的候选必须被拒绝。
- F1（票 19/20）：非公式节点（标题/段落/图片）的声明范围须与独立对齐
  的实际字符区间精确一致——同级标题、同文段落、同资源图片的声明范围
  互换（Markdown 字节不变）必须被拒绝。
- F2（票 22）：脚注定义按文档序完整消费——直属文字、多个段落、列表
  条目与简单表内容不丢失，代码块保持在定义内；合法双段落与代码脚
  注不再被误拒。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _html_fidelity as fidelity_mod
import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown
from markdown_it import MarkdownIt

IDENTITY = {
    'expected_title': 'T', 'actual_title': 'T',
    'paper_id': '2210.00022', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00022v1',
    'retrieved_at': '2026-10-11T00:00:00Z',
    'confirmation': '独立检查固定测试原HTML题名与身份。',
}


def _adapt(raw):
    md, corrs, unres, _fidelity, _adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], '/tmp')
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
    }
    return md, payload


def _corr(payload, node):
    return next(c for c in payload['correspondences']
                if c.get('node') == node)


class IndependentFactsTest(unittest.TestCase):
    """S1：独立事实不消费生成侧自报文字；字面强调字符真实阅读保真。"""

    def test_shared_renderer_fault_detected(self):
        raw = ('<article class="ltx_document"><h1>T</h1>'
               '<p>Keep important word $x$.</p></article>')
        original = fidelity_mod.HtmlFidelity.paragraph_text

        def broken(self, node, escape_backslashes=False):
            return original(self, node,
                            escape_backslashes=escape_backslashes
                            ).replace('important ', '')

        with patch.object(fidelity_mod.HtmlFidelity,
                          'paragraph_text', broken):
            md, payload = _adapt(raw)
            diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(diffs, '共享出口删除重要文字必须被独立对账拒绝')
        # 无故障时同一输入通过对账
        md, payload = _adapt(raw)
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])

    def test_figure_caption_literal_asterisks_reading(self):
        raw = ('<article class="ltx_document"><h1>T</h1>'
               '<figure><figcaption>Figure 1: A*B*C.</figcaption>'
               '</figure></article>')
        md, payload = _adapt(raw)
        # 生成端按阅读语义加写：实际阅读与原文字面一致
        self.assertIn('A\\*B\\*C.', md)
        reading = MarkdownIt('commonmark').render(md)
        self.assertIn('A*B*C.', reading)
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])
        # 裸写（未加写）的候选真实阅读丢字符，必须被拒绝
        bare = md.replace('A\\*B\\*C.', 'A*B*C.')
        self.assertNotEqual(
            reconcile_latexml_to_markdown(raw, bare, None, payload), [])


class DeclaredRangeAlignmentTest(unittest.TestCase):
    """F1：非公式节点声明范围与独立对齐实际区间精确一致。"""

    def _swap_ranges(self, payload, node_a, node_b):
        a = _corr(payload, node_a)
        b = _corr(payload, node_b)
        a['md_start'], b['md_start'] = b['md_start'], a['md_start']
        a['md_end'], b['md_end'] = b['md_end'], a['md_end']

    def test_swapped_heading_ranges_rejected(self):
        raw = ('<article class="ltx_document"><h1>T</h1>'
               '<h2>A</h2><p>u</p><h2>B</h2><p>v</p></article>')
        md, payload = _adapt(raw)
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])
        self._swap_ranges(payload, 'h2[1]', 'h2[2]')
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('声明范围' in d and 'h2[1]' in d
                            for d in diffs), diffs)

    def test_swapped_identical_paragraph_ranges_rejected(self):
        raw = ('<article class="ltx_document"><h1>T</h1>'
               '<p>same</p><p>same</p></article>')
        md, payload = _adapt(raw)
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])
        self._swap_ranges(payload, 'p[1]', 'p[2]')
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('声明范围' in d and 'p[1]' in d
                            for d in diffs), diffs)

    def test_swapped_same_resource_image_ranges_rejected(self):
        raw = ('<article class="ltx_document"><h1>T</h1>'
               '<p><img src="a.png"/></p><p><img src="a.png"/></p>'
               '</article>')
        md, payload = _adapt(raw)
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])
        self._swap_ranges(payload, 'img[1]', 'img[2]')
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('声明范围' in d and 'img[1]' in d
                            for d in diffs), diffs)


class FootnoteStructureTest(unittest.TestCase):
    """F2：脚注定义完整结构——直属文字/列表/表/双段落/代码均保留且通过。"""

    def _footnote_case(self, content, expected_reading):
        from _source_reconcile import _md_inline_reading
        raw = ('<html><body><article class="ltx_document"><h1>T</h1>'
               '<p>Body <a class="ltx_note_ref" href="#fn:a">a</a>.</p>'
               '<div class="ltx_note" id="fn:a">'
               '<div class="ltx_note_content">' + content
               + '</div></div></article></body></html>')
        md, payload = _adapt(raw)
        self.assertEqual(payload['unresolved'], [])
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])
        # 脚注续行是本管线的缩进方言（非 CommonMark 代码块）；逐行按
        # 真实行内阅读核对原文字面保留
        reading = '\n'.join(_md_inline_reading(line)
                            for line in md.split('\n'))
        for text in expected_reading:
            self.assertIn(text, reading)
        return md

    def test_direct_text_preserved(self):
        self._footnote_case('DIRECT_KEEP<p>First.</p>',
                            ['DIRECT_KEEP', 'First.'])

    def test_table_preserved(self):
        self._footnote_case(
            '<p>First.</p><table class="ltx_tabular">'
            '<tr><td>TABLE_KEEP</td><td>V</td></tr></table>',
            ['TABLE_KEEP', 'V'])

    def test_list_preserved(self):
        self._footnote_case(
            '<p>First.</p><ul class="ltx_itemize"><li>LIST_KEEP</li></ul>',
            ['LIST_KEEP'])

    def test_two_paragraphs_accepted(self):
        md = self._footnote_case('<p>First.</p><p>Last.</p>',
                                 ['First.', 'Last.'])
        self.assertIn('[^fn:a]: First.\n', md)
        self.assertIn('Last.', md)

    def test_code_fence_accepted(self):
        md = self._footnote_case('<p>First.</p><pre>CODE_KEEP</pre>',
                                 ['First.'])
        self.assertIn('    ```\n    CODE_KEEP\n    ```', md)


if __name__ == '__main__':
    unittest.main()
