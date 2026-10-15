"""字符建议保持证据层级，不能自动改写原提取视图。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_test_support import HAVE_PYMUPDF, pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class CharacterCandidateTests(unittest.TestCase):
    def test_saved_rotations_keep_link_text_and_target_at_same_occurrence(self):
        source = 'https://one.test/fx fuser.html'
        target = 'https://one.test/fx_fuser.html'
        other = 'https://unlinked.test/item'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                page = doc.new_page(width=400, height=600)
                page.insert_text((40, 100), source, fontsize=10)
                original_rect = page.search_for(source)[0]
                page.insert_link({'kind': pymupdf.LINK_URI, 'from': original_rect,
                                  'uri': target})
                mirror = original_rect * pymupdf.Matrix(-1, 0, 0, -1, 400, 600)
                page.insert_text((mirror.x0, mirror.y1 - 3), other, fontsize=10)
                for rotation in (0, 90, 180, 270):
                    page.set_rotation(rotation)
                    doc.save(root / ('paper-%d.pdf' % rotation))
            for rotation in (0, 90, 180, 270):
                with self.subTest(rotation=rotation):
                    pdf = root / ('paper-%d.pdf' % rotation)
                    output = root / ('source-%d' % rotation)
                    result = subprocess.run([sys.executable,
                        str(SCRIPTS / 'prepare_pdf_source.py'), 'inspect',
                        str(pdf), '--output', str(output)],
                        capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    checklist = json.loads((output / 'adjudication_checklist.json').read_text())
                    urls = [d for d in checklist['candidates']['character_defects']
                            if d['kind'] == 'url-target-difference']
                    self.assertEqual([source], [d['text'] for d in urls])
                    item = urls[0]
                    self.assertEqual(target, item['suggestion'])
                    self.assertEqual(target, item['suggestion_evidence']['uri'])
                    self.assertEqual('unrotated-page-pt', item['coordinate_space'])
                    self.assertEqual(rotation, item['rotation'])
                    with pymupdf.open(pdf) as reopened:
                        display_rect = original_rect * reopened[0].rotation_matrix
                        link = reopened[0].get_links()[0]
                        self.assertEqual(link['xref'], item['object_locator']['xref'])
                        for expected, actual in zip(display_rect, link['from']):
                            self.assertAlmostEqual(expected, actual, places=3)
                    for expected, actual in zip(original_rect, item['rect']):
                        self.assertAlmostEqual(expected, actual, places=2)
                    for expected, actual in zip(display_rect, item['display_rect']):
                        self.assertAlmostEqual(expected, actual, places=2)
                    self.assertEqual([], checklist['blocks'])
                    self.assertNotIn('defects', checklist['conventions'])

    def test_suggestions_require_evidence_and_leave_native_text_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_font(fontname='unicode', fontbuffer=pymupdf.Font('helv').buffer)
                page.insert_text((50, 60), 'Original workﬂows.', fontname='unicode')
                page.insert_text((50, 110), 'https://example.test/fx fuser.html', fontsize=10)
                rect = page.search_for('https://example.test/fx fuser.html')[0]
                page.insert_link({'kind': pymupdf.LINK_URI, 'from': rect,
                                  'uri': 'https://example.test/fx_fuser.html'})
                doc.save(root / 'paper.pdf')
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            checklist = json.loads((root / 'source/adjudication_checklist.json').read_text())
            defects = checklist['candidates']['character_defects']
            ligature = next(d for d in defects if d['kind'] == 'ligature')
            self.assertEqual('ﬂ', ligature['text'])
            self.assertEqual(['U+FB02'], ligature['codepoints'])
            self.assertIsNone(ligature['suggestion'])
            self.assertTrue(ligature['rect'])
            url = next(d for d in defects if d['kind'] == 'url-target-difference')
            self.assertEqual('https://example.test/fx_fuser.html', url['suggestion'])
            self.assertEqual(url['suggestion'], url['suggestion_evidence']['uri'])
            self.assertTrue(url['ambiguities'])
            self.assertEqual([], checklist['blocks'])
            self.assertNotIn('defects', checklist['conventions'])
            reading = (root / 'source/snapshots_reading.txt').read_text()
            self.assertIn('workﬂows', reading)
            self.assertIn('fx fuser', reading)
            self.assertNotIn('fx_fuser', reading)

    def test_common_facts_read_each_native_view_and_links_once(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content, page_facts, character_defect_candidates
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 60), 'Ordinary original text.')
            calls = {}

            class ObservedPage:
                def get_text(self, mode):
                    calls[mode] = calls.get(mode, 0) + 1
                    return page.get_text(mode)

                def get_links(self):
                    calls['links'] = calls.get('links', 0) + 1
                    return page.get_links()

                def __getattr__(self, name):
                    return getattr(page, name)

            observed = ObservedPage()
            content = page_content(observed)
            page_facts(observed, content)
            self.assertEqual([], character_defect_candidates(observed, content, None, [1]))
            self.assertEqual({key: 1 for key in ('text', 'blocks', 'dict', 'rawdict', 'links')}, calls)
