"""共享代码围栏扫描器的固定语义验收（任务 01：代码围栏保真）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_code_fences,
    heading_lines,
    scan_code_fences,
)


class ScanCodeFencesTest(unittest.TestCase):

    def test_offsets_and_body_byte_fidelity(self):
        text = 'intro\n\n```python\nprint("a")\n\n  indented  \n```\ntail\n'
        scan = scan_code_fences(text)
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.boundary_count, 2)
        fence = scan.blocks[0]
        self.assertEqual(fence.opener, '```python')
        self.assertEqual(fence.info, 'python')
        self.assertEqual(fence.body, 'print("a")\n\n  indented  ')
        self.assertEqual(fence.closer, '```')
        self.assertEqual(fence.fence_char, '`')
        self.assertEqual(fence.fence_length, 3)
        self.assertEqual(fence.start, text.index('```python'))
        self.assertEqual(text[fence.start:fence.end],
                         '```python\nprint("a")\n\n  indented  \n```')
        self.assertEqual(fence.start_line, 3)
        self.assertEqual(fence.end_line, 7)

    def test_tilde_fence(self):
        text = '~~~\ncode\n~~~\n'
        scan = scan_code_fences(text)
        self.assertTrue(scan.balanced)
        self.assertEqual(len(scan.blocks), 1)
        self.assertEqual(scan.blocks[0].fence_char, '~')
        self.assertEqual(scan.blocks[0].body, 'code')

    def test_long_backtick_fence_contains_short_fence_and_prose_marks(self):
        text = (
            '````md\n'
            '```c\n'
            'int x;\n'
            '```\n'
            '# not a heading\n'
            '---\n'
            '$x$\n'
            '![img](p.png)\n'
            '````\n'
        )
        scan = scan_code_fences(text)
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.boundary_count, 2)
        self.assertEqual(len(scan.blocks), 1)
        body = scan.blocks[0].body
        for fragment in ('```c', 'int x;', '```', '# not a heading',
                         '---', '$x$', '![img](p.png)'):
            self.assertIn(fragment, body)

    def test_close_requires_same_char_and_at_least_length(self):
        scan = scan_code_fences('````\ncode\n```\n')
        self.assertFalse(scan.balanced)
        self.assertEqual(scan.blocks, ())
        scan = scan_code_fences('~~~\ncode\n```\n')
        self.assertFalse(scan.balanced)
        scan = scan_code_fences('````\ncode\n````\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(len(scan.blocks), 1)

    def test_unterminated_fence_reports_unclosed_line(self):
        scan = scan_code_fences('a\n```c\nint x;\n')
        self.assertFalse(scan.balanced)
        self.assertEqual(scan.blocks, ())
        self.assertEqual(scan.unclosed_line, 2)

    def test_indent_rules(self):
        # 任意空格缩进的标记行均可开启/闭合围栏：列表项内围栏按项层级
        # 2×level 缩进（可达 4+ 空格），缩进代码块不是本管线受支持输出
        scan = scan_code_fences('   ```js\nvar x;\n   ```\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks[0].info, 'js')
        scan = scan_code_fences('    ```\nitem_code()\n    ```\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks[0].body, 'item_code()')
        # 深缩进标记行同样参与闭合（不再是代码正文）
        scan = scan_code_fences('```\ncode\n    ```\nafter\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks[0].body, 'code')

    def test_backtick_fence_info_may_not_contain_backtick(self):
        scan = scan_code_fences('``` a ` b \nx\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks, ())
        # 波浪围栏信息串可以含反引号
        scan = scan_code_fences('~~~ `code`\nx\n~~~\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks[0].info, '`code`')


class HeadingFenceExclusionTest(unittest.TestCase):

    def test_headings_inside_fences_excluded(self):
        text = ('# H1\n```c\n# comment\n```\n'
                '## H2\n~~~\n## in tilde\n~~~\n### H3\n')
        self.assertEqual(
            [t for _, t in heading_lines(text, ignore_fences=True)],
            ['H1', 'H2', 'H3'])

    def test_short_fence_inside_long_fence_does_not_confuse(self):
        text = '# T\n````\n```python\n# a\n```\n# b\n````\n## U\n'
        self.assertEqual(
            [t for _, t in heading_lines(text, ignore_fences=True)],
            ['T', 'U'])

    def test_unclosed_fence_hides_rest_of_document(self):
        text = '# T\n```\n# hidden\n'
        self.assertEqual(
            [t for _, t in heading_lines(text, ignore_fences=True)],
            ['T'])


class CompareCodeFencesTest(unittest.TestCase):

    def test_identical_fences_have_no_diffs(self):
        src = scan_code_fences('```c\nreturn 1;\n```\n').blocks
        self.assertEqual(compare_code_fences(src, src, 'a.md', 'b.md'), [])

    def test_body_change_reported_with_positions(self):
        src = scan_code_fences('```c\nreturn 1;\n```\n').blocks
        doc = scan_code_fences('```c\nreturn 2;\n```\n').blocks
        diffs = compare_code_fences(src, doc, 'src.md', 'doc.md')
        self.assertEqual(len(diffs), 1)
        self.assertIn('正文第 1 行不一致', diffs[0])
        self.assertIn("'return 1;'", diffs[0])
        self.assertIn("'return 2;'", diffs[0])
        self.assertIn('src.md', diffs[0])
        self.assertIn('doc.md', diffs[0])

    def test_opener_language_change_reported(self):
        src = scan_code_fences('```c\nx\n```\n').blocks
        doc = scan_code_fences('```python\nx\n```\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('开启行不一致' in d for d in diffs))

    def test_bare_source_fence_allows_language_tag_addition(self):
        src = scan_code_fences('```\nx\n```\n').blocks
        doc = scan_code_fences('```cuda\nx\n```\n').blocks
        self.assertEqual(compare_code_fences(src, doc, 'a.md', 'b.md'), [])

    def test_language_tag_removal_reported(self):
        src = scan_code_fences('```c\nx\n```\n').blocks
        doc = scan_code_fences('```\nx\n```\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('开启行不一致' in d for d in diffs))

    def test_fence_char_change_reported_even_from_bare(self):
        src = scan_code_fences('```\nx\n```\n').blocks
        doc = scan_code_fences('~~~\nx\n~~~\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('开启行不一致' in d for d in diffs))

    def test_whitespace_difference_reported(self):
        src = scan_code_fences('```c\nreturn 1;\n```\n').blocks
        doc = scan_code_fences('```c\nreturn 1;  \n```\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('正文第 1 行不一致' in d for d in diffs))
        self.assertTrue(any("'return 1;  '" in d for d in diffs))

    def test_block_count_mismatch_reported(self):
        src = scan_code_fences('```c\nx\n```\n\n```py\ny\n```\n').blocks
        doc = scan_code_fences('```c\nx\n```\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('代码块数不一致' in d for d in diffs))
        self.assertTrue(any('多余代码块' in d and '```py' in d for d in diffs))

    def test_closer_change_reported(self):
        src = scan_code_fences('```c\nx\n```\n').blocks
        doc = scan_code_fences('```c\nx\n````\n').blocks
        diffs = compare_code_fences(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('关闭行不一致' in d for d in diffs))

    def test_closer_indent_and_trailing_whitespace_tolerated(self):
        # 围栏标记行的缩进/首尾空白属容器痕迹，不参与比较；正文不受豁免
        src = scan_code_fences('```c\nx\n```\n').blocks
        doc = scan_code_fences('  ```c\nx\n  ```  \n').blocks
        self.assertEqual(compare_code_fences(src, doc, 'a.md', 'b.md'), [])


class DraftSpliceTest(unittest.TestCase):
    """草稿占位回填（A28）：复杂围栏逐字节回填，数量错误必须拒绝。"""

    def _write(self, tmp, name, text):
        path = tmp / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    def test_splice_mixed_fence_chars_roundtrip(self):
        import splice_fences
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            src = self._write(tmp, 'src.md',
                              '# T\n\n~~~~\ncode_tilde()\n~~~~\n\n'
                              '````python\ncode_quad()\n````\n\n尾\n')
            draft = self._write(tmp, 'draft.md',
                                '# T\n\n⟦CODE⟧\n\n⟦CODE⟧\n\n尾\n')
            out = tmp / 'cand.md'
            import contextlib
            import io
            argv = sys.argv
            sys.argv = ['splice_fences.py', str(draft), src, str(out)]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    splice_fences.main()
            finally:
                sys.argv = argv
            text = out.read_text(encoding='utf-8')
            bodies = [f.body for f in scan_code_fences(text).blocks]
            self.assertEqual(bodies, ['code_tilde()', 'code_quad()'])

    def test_splice_placeholder_count_mismatch_rejected(self):
        import splice_fences
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            src = self._write(tmp, 'src.md', '# T\n\n```a\nx\n```\n\n```b\ny\n```\n')
            draft = self._write(tmp, 'draft.md', '# T\n\n⟦CODE⟧\n\n尾\n')
            import contextlib
            import io
            argv = sys.argv
            sys.argv = ['splice_fences.py', draft, src, str(tmp / 'o.md')]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(AssertionError):
                        splice_fences.main()
            finally:
                sys.argv = argv


if __name__ == '__main__':
    unittest.main()
