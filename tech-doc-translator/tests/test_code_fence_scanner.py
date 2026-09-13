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
        # 4 空格缩进的 ``` 只是代码正文，不参与围栏边界
        text = '```\ncode\n    ```\nstill code\n```\n'
        scan = scan_code_fences(text)
        self.assertTrue(scan.balanced)
        self.assertEqual(len(scan.blocks), 1)
        self.assertIn('still code', scan.blocks[0].body)
        # 0-3 空格缩进可以开启/闭合围栏
        scan = scan_code_fences('   ```js\nvar x;\n   ```\n')
        self.assertTrue(scan.balanced)
        self.assertEqual(scan.blocks[0].info, 'js')

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


if __name__ == '__main__':
    unittest.main()
