"""第 2 批 R4：标题与长代码块一起移页记放宽项，无标题粘连仍判 code-page-gap。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
import verify_pdf as verifier

CODE = '\n'.join('line %d' % n for n in range(1, 16))


def chapter_with(before_code):
    html = ('<div class="chapter"><p>前文。</p>%s'
            '<div class="code-block code-long"><pre>%s</pre></div></div>' % (before_code, CODE))
    return SimpleNamespace(path=Path('/tmp/r4-chapter.md'), code_blocks=[CODE],
                           soup=BeautifulSoup(html, 'html.parser'))


def run_pagination(chapter):
    # 第 1 页只用到 y=200 处：尾部剩约 142pt，放得下标题与两行代码。
    # 第 2 页：y=780 是块上方的标题行，块首行基线 y=760，行高 12pt。
    pdf = SimpleNamespace(line_buckets=[
        {'page': 0, 'text': '前文。', 'baseline_y_pt': 200.0},
        {'page': 1, 'text': 'Title', 'baseline_y_pt': 780.0},
        {'page': 1, 'text': 'line 1', 'baseline_y_pt': 760.0},
    ])
    infos = {str(chapter.path): [{'long': True, 'first_page': 1, 'last_page': 1,
                                  'first_baseline_pt': 760.0, 'line_height_pt': 12.0}]}
    failures, reviews, relaxed = [], [], []
    with patch.object(verifier, 'collect_drawn_images', return_value=[[], []]):
        verifier.check_code_pagination([chapter], pdf, [(chapter, 0, 2)],
                                       failures, reviews, infos, relaxed)
    return failures, reviews, relaxed


class HeadingGluedCodeBlockTest(unittest.TestCase):
    def test_heading_moved_with_long_block_is_relaxed_for_review(self):
        failures, _, relaxed = run_pagination(chapter_with('<h2 id="s">Title</h2>'))
        self.assertEqual([f['code'] for f in failures], [])
        self.assertEqual(len(relaxed), 1)
        self.assertTrue(relaxed[0]['review'])
        self.assertEqual(relaxed[0]['page'], 2)
        self.assertIn('标题', relaxed[0]['segment'])

    def test_anchor_only_paragraph_between_heading_and_block_is_skipped(self):
        failures, _, relaxed = run_pagination(chapter_with(
            '<h3 id="s">Title</h3><p class="anchor-only"><a id="x"></a></p>'))
        self.assertEqual(failures, [])
        self.assertEqual(len(relaxed), 1)

    def test_paragraph_before_block_still_fails(self):
        failures, _, relaxed = run_pagination(chapter_with('<p>Title</p>'))
        self.assertEqual([f['code'] for f in failures], ['code-page-gap'])
        self.assertEqual(relaxed, [])

    def test_follows_heading_reads_code_blocks_in_order(self):
        soup = BeautifulSoup(
            '<h2>A</h2><div class="code-block"><pre>a</pre></div>'
            '<p>x</p><div class="code-block"><pre>b</pre></div>', 'html.parser')
        chapter = SimpleNamespace(path=Path('/tmp/x.md'), code_blocks=['a', 'b'], soup=soup)
        self.assertTrue(verifier._code_follows_heading(chapter, 0))
        self.assertFalse(verifier._code_follows_heading(chapter, 1))


if __name__ == '__main__':
    unittest.main()
