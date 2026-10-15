"""格位诊断只保留原生线索，不成为人工结构裁决。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_test_support import HAVE_PYMUPDF, pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class TableCandidateTests(unittest.TestCase):
    def test_inspect_preserves_empty_cells_multiline_headers_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                page = doc.new_page()
                for x in (50, 150, 250):
                    page.draw_line((x, 80), (x, 220))
                for y in (80, 120, 170, 220):
                    page.draw_line((50, y), (250, y))
                page.insert_text((60, 95), 'Group\nName', fontsize=9)
                page.insert_text((160, 95), 'Original\nValue', fontsize=9)
                page.insert_text((60, 145), 'A', fontsize=9)
                page.insert_text((60, 195), 'B', fontsize=9)
                page.insert_text((160, 195), '12', fontsize=9)
                doc.save(root / 'paper.pdf')
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            checklist = json.loads((root / 'source/adjudication_checklist.json').read_text())
            candidates = checklist['candidates']
            table = next(t for t in candidates['table_cells'] if t['parameters']['strategy'] == 'lines')
            self.assertEqual((3, 2), (table['row_count'], table['column_count']))
            empty = next(c for c in table['cells'] if (c['row'], c['column']) == (2, 2))
            self.assertEqual('', empty['text'])
            self.assertTrue(empty['empty_text'])
            self.assertEqual('located', empty['boundary_status'])
            self.assertEqual(['Group\nName', 'Original\nValue'], table['header']['names'])
            self.assertTrue(table['figure_conflicts'])
            self.assertTrue(table['ambiguities'])
            self.assertEqual([], checklist['blocks'])
            self.assertFalse(checklist['reading_order']['adjudicated'])
            self.assertEqual({'lines', 'text'}, {c['parameters']['strategy'] for c in candidates['table_checks']})
            checklist['classification'] = {
                'type': 'text', 'adjudicated': True,
                'basis': 'Human checked all original cells and native text.',
                'evidence': ['Original human classification evidence.']}
            checklist['reading_order'] = {'adjudicated': True, 'basis': 'Original row order.'}
            path = root / 'source/adjudication_checklist.json'
            path.write_text(json.dumps(checklist))
            result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            refreshed = json.loads(path.read_text())
            self.assertEqual(checklist['classification'], refreshed['classification'])
            self.assertEqual(checklist['reading_order'], refreshed['reading_order'])

    def test_unavailable_api_is_a_local_gap_without_changing_native_views(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content, table_cell_candidates
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 80), 'Original text remains available.')
            content = page_content(page)

            class NoTables:
                def __getattr__(self, name):
                    if name == 'find_tables':
                        raise AttributeError('find_tables unavailable')
                    return getattr(page, name)

            tables, checks = table_cell_candidates(NoTables(), content, [], None, [1])
            self.assertEqual([], tables)
            self.assertTrue(all(c['status'] == 'unavailable' for c in checks))
            self.assertEqual(page.get_text('text'), content['text'])
