"""第 2 批 R17 D4：紧跟图片、以加粗图题或子图题开头的段落标为 image-caption。"""
import sys
import unittest

from bs4 import BeautifulSoup

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter


def marked(html):
    soup = BeautifulSoup(html, 'html.parser')
    exporter.mark_figure_captions(soup)
    return [p.get_text(' ', strip=True) for p in soup.find_all('p', class_='image-caption')]


class FigureCaptionMarkingTest(unittest.TestCase):
    def test_caption_after_image_and_linked_image(self):
        self.assertEqual(marked(
            '<p><img src="a.png"/></p><p><strong>图 1. 架构</strong></p>'
            '<p><a href="#x"><img src="b.png"/></a></p><p><strong>Figure 2. Layout</strong></p>'),
            ['图 1. 架构', 'Figure 2. Layout'])

    def test_inline_anchor_before_caption_is_skipped(self):
        self.assertEqual(marked(
            '<p><img src="a.png"/></p>'
            '<p><a id="id5"></a>\n<strong>图 27. 条件 IF 节点</strong> <a href="#id5">#</a></p>'),
            ['图 27. 条件 IF 节点 #'])

    def test_subfigure_captions_lead_to_the_main_caption(self):
        self.assertEqual(marked(
            '<p><img src="a.png"/></p><p><strong>(a) Criteo</strong></p>'
            '<p><img src="b.png"/></p><p><strong>（b）训练加速。</strong></p>'
            '<p><strong>图 4. 运行时间比较</strong></p><p><strong>图 5. 不紧跟图片</strong></p>'),
            ['(a) Criteo', '（b）训练加速。', '图 4. 运行时间比较'])

    def test_paragraphs_that_stay_unmarked(self):
        self.assertEqual(marked(
            '<p><img src="a.png"/></p><p class="anchor-only"><a id="S1.F1"></a></p>'
            '<p><strong>图 1. 隔着独立锚点段</strong></p>'
            '<p><img src="b.png"/></p>'
            '<p><strong>稠密向量表示（Dense vector representation）</strong> <a href="#d">#</a></p>'
            '<p><img src="c.png"/></p><p>且</p>'
            '<p><img src="d.png"/>\n<strong>图 9. 与图片同段</strong></p>'
            '<p>正文。</p><p><strong>图 2. 不紧跟图片</strong></p>'), [])


if __name__ == '__main__':
    unittest.main()
