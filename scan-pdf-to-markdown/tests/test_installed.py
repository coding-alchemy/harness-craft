import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pymupdf

from test_capture import SCRIPTS
from test_cli import tree_digests
from test_reading import fixture_pack, text_block


class InstalledSkillTests(unittest.TestCase):
    def test_copied_skill_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / 'skills' / 'scan-pdf-to-markdown'
            shutil.copytree(SCRIPTS.parent, installed)
            entry = (installed / 'SKILL.md').read_text()
            self.assertIn('name: scan-pdf-to-markdown', entry)
            self.assertIn('references/review.md', entry)
            self.assertTrue((installed / 'references/review.md').is_file())
            script = installed / 'scripts' / 'scan_pdf.py'
            self.assertTrue(script.is_relative_to(installed))
            work = root / 'work'
            work.mkdir()
            pdf = work / 'source.pdf'
            incoming = work / 'incoming'
            incoming.mkdir()
            with pymupdf.open() as source:
                source.new_page().insert_text((55, 78), 'Known text')
                source.save(pdf)
            fixture_pack(pdf, incoming / 'raw', [[text_block('Known text', 0, [.08, .085, .2, .1])]])
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            args = ('render', str(incoming), '--source-pdf', str(pdf), '--output')
            results = []
            for executable, destination in ((SCRIPTS / 'scan_pdf.py', 'direct'), (script, 'rebuilt')):
                run = subprocess.run([sys.executable, str(executable), *args, destination],
                                     cwd=work, env=env, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                results.append(run.stdout.splitlines()[0])
            checked = subprocess.run([sys.executable, str(script), 'verify', 'rebuilt', '--source-pdf', str(pdf)],
                                     cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertEqual(results, ['结论：降级', '结论：降级'])
            self.assertEqual(checked.stdout.splitlines()[0], results[0])
            self.assertIn('Known text', (work / 'rebuilt/document.md').read_text())
            self.assertEqual(tree_digests(work / 'direct'), tree_digests(work / 'rebuilt'))
