"""PDF 解析的固定组合验收；所有输入均在工作区外构造。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter


class MarkdownStructureTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory(prefix='pdf-structure-') as temporary:
            path = Path(temporary) / 'chapter.md'
            path.write_text(text, encoding='utf-8')
            chapter = exporter.Chapter(1, path)
            exporter.parse_chapter(chapter)
            return chapter

    def test_heading_uses_chapter_reference_and_footnote_context(self):
        for level in (1, 6, 7, 8):
            with self.subTest(level=level):
                chapter = self.parse('#' * level + ' Use [docs][r] and `foo` $x^2$[^n]\n\n'
                                     '[r]: https://example.com/docs\n\n[^n]: Required note.\n')
                self.assertIsNotNone(chapter.soup.find('a', href='https://example.com/docs'))
                self.assertIn('Required note.', chapter.soup.get_text())
                self.assertEqual([m['latex'] for m in chapter.math], ['x^2'])
                self.assertEqual(chapter.soup.code.get_text(), 'foo')

    def test_explicit_anchor_inside_heading_and_code(self):
        for level in (1, 7, 8):
            with self.subTest(level=level):
                chapter = self.parse('#' * level + ' <a id="custom"></a>Title\n\n'
                                     '[go](#custom)\n\n`<a id="literal"></a>`\n')
                self.assertIsNotNone(chapter.soup.find(id='ch01-custom'))
                self.assertEqual(chapter.soup.code.get_text(), '<a id="literal"></a>')
                self.assertNotIn('PLACEHOLDER', chapter.soup.get_text())

    def test_code_boundaries_and_adjacent_headings(self):
        cases = [
            'Example: `begin\n####### literal\nend`',
            'Example: \\`ignored `begin\n####### literal\nend`',
            '````markdown\n```html\n<a id="sample"></a>\n####### literal\n```\n````',
        ]
        for case in cases:
            with self.subTest(case=case):
                chapter = self.parse('# A\n\n' + case + '\n\n####### B\n######## C\nTail\n')
                self.assertEqual([h['text'] for h in chapter.headings], ['A', 'B', 'C'])
                self.assertIn('####### literal', chapter.soup.get_text())
                self.assertIn('Tail', chapter.soup.get_text())

    def test_inline_title_spaces_and_code_blank_lines_survive(self):
        chapter = self.parse('# Use `foo` now\n\n[go](#use-foo-now)\n\n'
                             '```python\n\nprint(1)\n\n```\n')
        self.assertEqual(chapter.headings[0]['slug'], 'use-foo-now')
        self.assertEqual(chapter.soup.pre.get_text(), '\nprint(1)\n\n')

    def test_anchor_identity_does_not_depend_on_decimal_prefix(self):
        chapter = self.parse('# A\n\n' + '\n\n'.join(
            '<a id="a%d"></a> Text %d' % (i, i) for i in range(12)))
        self.assertEqual([a['id'] for a in chapter.soup.find_all('a')],
                         ['ch01-a%d' % i for i in range(12)])


if __name__ == '__main__':
    unittest.main()
