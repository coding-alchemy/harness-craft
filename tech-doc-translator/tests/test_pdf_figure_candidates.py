"""inspect 诊断候选与未旋转裁决区域的实际裁图合同。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_test_support import HAVE_PYMUPDF, pymupdf, draw_chart, draw_table

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class FigureCandidateTests(unittest.TestCase):
    def test_independent_occurrences_keep_labels_and_original_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = pymupdf.open()
            for _ in range(2):
                page = doc.new_page(width=500, height=400)
                draw_chart(page, ['Batch A', 'Batch B', 'series one'])
                draw_table(page)
                page.insert_text((50, 210), 'Figure 1. Same number', fontsize=9)
                page.insert_text((50, 250), 'Adjacent body remains independently located.', fontsize=10)
            doc.save(root / 'paper.pdf')
            doc.close()
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            checklist = json.loads((root / 'source/adjudication_checklist.json').read_text())
            candidates = checklist['candidates']
            self.assertEqual({1, 2}, {c['page'] for c in candidates['figure_captions']})
            charts = [c for c in candidates['figure_regions']
                      if any('series one' in o.get('text', '') for o in c['objects'])]
            self.assertEqual({1, 2}, {c['page'] for c in charts})
            for chart in charts:
                self.assertEqual(checklist['source']['sha256'], chart['source_sha256'])
                self.assertEqual([1, 2], chart['scope'])
                self.assertEqual('unrotated-page-pt', chart['coordinate_space'])
                self.assertTrue(chart['caption_alternatives'])
                self.assertTrue(chart['parameters'])
                self.assertTrue(chart['ambiguities'])
                self.assertNotIn('resolved', chart)
                self.assertFalse(any('Adjacent body' in o.get('text', '') for o in chart['objects']))
            self.assertEqual([], checklist['blocks'])
            self.assertFalse(checklist['reading_order']['adjudicated'])

    def test_rotated_region_renders_the_same_physical_content(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content, page_facts, render_figure
        for angle in (90, 180, 270):
            with self.subTest(rotation=angle), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                doc = pymupdf.open()
                page = doc.new_page(width=400, height=600)
                page.draw_rect((40, 80, 180, 150), fill=(0, 0, 0))
                page.insert_text((50, 130), 'TARGET LABEL', color=(1, 1, 1))
                page.set_rotation(angle)
                doc.save(root / 'paper.pdf')
                doc.close()
                with pymupdf.open(root / 'paper.pdf') as current:
                    page = current[0]
                    render_figure(page, [40, 80, 180, 150], 72, str(root / 'actual.png'))
                    expected = page.get_pixmap(dpi=72,
                        clip=pymupdf.Rect(40, 80, 180, 150) * page.rotation_matrix)
                    actual = pymupdf.Pixmap(str(root / 'actual.png'))
                    self.assertEqual((expected.width, expected.height, expected.samples),
                                     (actual.width, actual.height, actual.samples))
                    content = page_content(page)
                    facts = page_facts(page, content)
                    unrotated = page.rect * page.derotation_matrix
                    block = content['blocks'][0]
                    expected_ratio = round((block[2]-block[0])*(block[3]-block[1]) /
                                           (unrotated.width*unrotated.height), 3)
                    self.assertEqual(expected_ratio, facts['text_area_ratio'])

    def test_no_graphics_is_explicitly_undiscovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((50, 70), 'A text-only page with no detected drawing objects.')
            doc.save(root / 'paper.pdf')
            doc.close()
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            candidates = json.loads((root / 'source/structure_candidates.json').read_text())
            self.assertEqual([], candidates['figure_regions'])
            self.assertTrue(candidates['figure_regions_empty'])


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class CachedExtractionContractTests(unittest.TestCase):
    def make_page(self, doc):
        page = doc.new_page()
        page.insert_font(fontname='unicode', fontbuffer=pymupdf.Font('helv').buffer)
        page.insert_text((50, 50), 'Figure 1: workﬂows and ﬁdelity', fontname='unicode')
        page.draw_rect((50, 65, 100, 95))
        page.insert_image(pymupdf.Rect(120, 70, 160, 110),
                          filename=str(Path(__file__).parent / 'fixtures/valid_1x1.png'))
        page.insert_text((50, 180), 'Original text after an embedded image.', fontname='unicode')
        return page

    def test_cache_preserves_original_text_blocks_and_dict_views(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content
        with pymupdf.open() as doc:
            page = self.make_page(doc)
            self.assertIn('workﬂows', page.get_text('text'))
            content = page_content(page)
            self.assertEqual(page.get_text('text'), content['text'])
            # 原 blocks 不含图像且编号连续，dict 保留图像；不能互换这两个视图。
            self.assertEqual(page.get_text('blocks'), content['blocks'])
            self.assertEqual(page.get_text('dict'), content['dict'])
            self.assertIn('Figure 1: workﬂows and ﬁdelity', content['line_originals'])

    def test_inspect_preserves_ligature_codepoints_in_both_snapshots_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                self.make_page(doc)
                doc.save(root / 'paper.pdf')
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            for name in ('snapshots_layout.txt', 'snapshots_reading.txt'):
                text = (root / 'source' / name).read_text()
                self.assertIn('workﬂows and ﬁdelity', text)
                self.assertNotIn('workflows', text)
                self.assertNotIn('fidelity', text)
            candidates = json.loads((root / 'source/structure_candidates.json').read_text())
            self.assertEqual('Figure 1: workﬂows and ﬁdelity',
                             candidates['figure_captions'][0]['text'])
            associated = [caption['text'] for item in candidates['figure_regions']
                          for caption in item['caption_alternatives']]
            self.assertIn('Figure 1: workﬂows and ﬁdelity', associated)


    def test_intervening_image_keeps_native_same_line_grouping_and_snapshots(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_font(fontname='unicode', fontbuffer=pymupdf.Font('helv').buffer)
                page.insert_text((50, 80), 'Original workﬂows', fontname='unicode')
                # 内容流在两段同基线文字之间插图；图片实际在远处，不遮挡文字。
                page.insert_image(pymupdf.Rect(300, 300, 320, 320),
                    filename=str(Path(__file__).parent / 'fixtures/valid_1x1.png'))
                page.insert_text((142, 80), 'preserve ﬁdelity.', fontname='unicode')
                doc.save(root / 'paper.pdf')
            with pymupdf.open(root / 'paper.pdf') as doc:
                page = doc[0]
                native_text = page.get_text('text')
                native_blocks = page.get_text('blocks')
                native_dict = page.get_text('dict')
                self.assertEqual('Original workﬂows preserve ﬁdelity.\n', native_text)
                self.assertEqual(1, len(native_blocks))
                content = page_content(page)
                self.assertEqual(native_text, content['text'])
                self.assertEqual(native_blocks, content['blocks'])
                self.assertEqual(native_dict, content['dict'])
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            layout = (root / 'source/snapshots_layout.txt').read_text()
            reading = (root / 'source/snapshots_reading.txt').read_text()
            self.assertEqual(1, layout.count('[块]'))
            self.assertIn(native_text, layout)
            self.assertTrue(reading.endswith(native_text))
