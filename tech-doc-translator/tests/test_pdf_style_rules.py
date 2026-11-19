"""第 2 批 R6：链接按词边界断行；带链接的图片与图注同页。"""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1]
       / 'skills/tech-doc-translator/assets/pdf/style.css').read_text(encoding='utf-8')


class PdfStyleRulesTest(unittest.TestCase):
    def test_links_wrap_at_word_boundaries(self):
        rule = re.search(r'^a \{[^}]*\}', CSS, re.M).group(0)
        self.assertNotIn('break-all', rule)
        self.assertIn('overflow-wrap: anywhere', rule)
        self.assertIn('.table-number a { overflow-wrap: normal; }', CSS)
        self.assertNotIn('word-break: break-all', CSS)

    def test_linked_images_follow_the_same_page_rules(self):
        for rule in (
                'p:has(> img), p:has(> a > img) { break-after: avoid-page; }',
                'p:has(> img) + p, p:has(> a > img) + p { break-inside: avoid; }',
                'p:has(> img) + .anchor-only + p, p:has(> a > img) + .anchor-only + p'
                ' { break-inside: avoid; }'):
            self.assertIn(rule, CSS)

    def test_standalone_images_are_centered(self):
        self.assertIn('p:has(> img), p:has(> a > img) { text-align: center; }', CSS)

    def test_image_captions_shrink_to_one_line_and_center(self):
        self.assertIn('p.image-caption { width: fit-content; margin-inline: auto; }', CSS)


if __name__ == '__main__':
    unittest.main()
