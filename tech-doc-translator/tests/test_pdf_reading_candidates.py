"""顺序诊断与两份原生快照逐块对应，不修改人工顺序。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_test_support import HAVE_PYMUPDF, pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class ReadingCandidateTests(unittest.TestCase):
    def test_snapshot_ranges_preserve_native_values_and_human_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pymupdf.open() as doc:
                page = doc.new_page(width=500, height=600)
                page.insert_text((280, 100), 'Right first in stream.\nRight next line.', fontsize=10)
                page.insert_text((40, 160), 'Left first to read.\nLeft next line.', fontsize=10)
                page.draw_rect((40, 250, 460, 350))
                page.insert_text((40, 375), 'Figure 1. Across both columns.', fontsize=10)
                doc.save(root / 'paper.pdf')
            command = [sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                       'inspect', str(root / 'paper.pdf'), '--output', str(root / 'source')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            path = root / 'source/adjudication_checklist.json'
            checklist = json.loads(path.read_text())
            order = checklist['candidates']['reading_orders'][0]
            layout = (root / 'source/snapshots_layout.txt').read_text().split('\n')
            reading = (root / 'source/snapshots_reading.txt').read_text().split('\n')
            for block in order['blocks']:
                for lines, key in ((layout, 'layout_page_lines'), (reading, 'reading_page_lines')):
                    start, end = block[key]
                    self.assertEqual(block['text'].rstrip('\n'), '\n'.join(lines[start-1:end]))
            self.assertNotEqual(order['extracted_sequence'], order['suggested_sequence'])
            self.assertTrue(any(g['crosses_midline'] for g in order['graphic_regions']))
            self.assertEqual([], checklist['blocks'])
            checklist['reading_order'] = {'adjudicated': True, 'basis': 'Human page decision.'}
            path.write_text(json.dumps(checklist))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(checklist['reading_order'], json.loads(path.read_text())['reading_order'])

    def test_empty_page_does_not_claim_reading_order(self):
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import page_content, structure_candidates
        with pymupdf.open() as doc:
            doc.new_page()
            candidates = structure_candidates(doc, [1], {1: page_content(doc[0])})
            self.assertEqual([], candidates['reading_orders'])
