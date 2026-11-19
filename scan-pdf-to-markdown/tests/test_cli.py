import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import pymupdf

from test_capture import SCRIPTS
from test_reading import fixture_pack
from reading import build_document
from review import apply_review, content_digest


SCRIPT = SCRIPTS / 'scan_pdf.py'


def tree_digests(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / 'scan.pdf'
        self.input = self.root / 'input'
        self.input.mkdir()
        box = [.1, .1, .4, .35]
        with pymupdf.open() as source:
            source.new_page().insert_text((44, 70), '18 13')
            source.save(self.pdf)
        pixel = pymupdf.Pixmap(pymupdf.csGRAY, 3, 3, b'\x81' * 9, False).tobytes('png')
        body = dict(type='table_body', index=0, bbox=box, content=
                    '<table><tr><td>A</td><td>B</td></tr><tr><td>18</td><td>18</td></tr></table>')
        image = dict(type='image_body', index=1, bbox=box, image_path='images/figure.png', content='')
        blocks = [dict(type='table', index=0, bbox=box, content=[body]),
                  dict(type='image', index=1, bbox=box, content=[image])]
        fixture_pack(self.pdf, self.input / 'raw', [blocks], {'images/figure.png': pixel})

    def cli(self, *args, check=None, env=None, python=sys.executable):
        result = subprocess.run([python, '-B', str(SCRIPT), *map(str, args)], text=True,
                                capture_output=True, cwd=self.root, env=env)
        if check is not None:
            self.assertEqual(result.returncode, check, result.stdout + result.stderr)
        return result

    def render(self, target, *extra, check=0, pdf=None, start=None):
        return self.cli('render', start or self.input, '--source-pdf', pdf or self.pdf,
                        '--output', target, *extra, check=check)

    def verify(self, target, check, clue, pdf=None):
        result = self.cli('verify', target, '--source-pdf', pdf or self.pdf, check=check)
        self.assertIn(clue, result.stdout + result.stderr)

    def test_verify_reads_disk(self):
        target = self.root / 'result'
        self.render(target)
        self.verify(target, 0, '降级')
        report = target / 'qa-report.md'
        original_report = report.read_bytes()
        report.unlink()
        self.verify(target, 1, 'qa-report.md')
        report.write_bytes(original_report.replace('整体结论：降级'.encode(), '整体结论：失败'.encode()))
        self.verify(target, 1, 'qa-report.md')
        report.write_bytes(original_report)
        asset = target / 'assets/p0001-b0001.png'
        previous = asset.read_bytes()
        asset.unlink()
        self.verify(target, 1, 'assets/p0001-b0001.png')
        asset.write_bytes(pymupdf.Pixmap(pymupdf.csGRAY, 3, 3, b'\xaa' * 9, False).tobytes('png'))
        self.verify(target, 1, 'assets/p0001-b0001.png')
        asset.write_bytes(b'not an image')
        self.verify(target, 1, '图片无法解码')
        asset.write_bytes(previous)
        markdown = target / 'document.md'
        intact = markdown.read_text()
        markdown.write_text(intact.replace('| 18 | 18 |', '| 18 | 19 |'))
        self.verify(target, 1, 'p0001-b0000')
        markdown.write_text(intact)
        jsonl = target / 'blocks.jsonl'
        jsonl.write_text(jsonl.read_text().replace('"18", "18"', '"18", "19"'))
        snapshot = tree_digests(target)
        self.verify(target, 1, 'blocks.jsonl')
        self.assertEqual(snapshot, tree_digests(target))
        imposter = self.root / 'other' / self.pdf.name
        imposter.parent.mkdir()
        imposter.write_bytes(self.pdf.read_bytes() + b'\n% belongs to a different file')
        wrong = self.root / 'wrong'
        self.verify(target, 1, '源 PDF', pdf=imposter)
        self.assertIn('源 PDF', self.render(wrong, check=1, pdf=imposter).stdout)
        self.assertFalse(wrong.exists())

    def test_blank_candidate_resume(self):
        pdf = self.root / 'marked.pdf'
        raw = self.root / 'blank-raw'
        with pymupdf.open() as original:
            original.new_page().draw_rect(pymupdf.Rect(20, 20, 22, 22), color=(.8, .8, .8))
            original.save(pdf)
        fixture_pack(pdf, raw, [[]])
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        python = fake_bin / 'python'
        python.symlink_to(sys.executable)
        fake = fake_bin / 'mineru-kit'
        fake.write_text('#!' + str(sys.executable) + '\nimport os,shutil,sys\n'
                        'shutil.copyfile(os.environ["FAKE_ENGINE"],sys.argv[sys.argv.index("-o")+1])\n')
        fake.chmod(0o700)
        env = dict(os.environ, FAKE_ENGINE=str(raw / 'engine.zip'),
                   PYTHONPATH=os.pathsep.join(sys.path), PATH=str(fake_bin))
        target = self.root / 'blank'
        result = self.cli('parse', pdf, '--output', target, check=1, env=env, python=str(python))
        directory = re.search(r'^候选目录：(.+)$', result.stdout, flags=re.M)
        self.assertIsNotNone(directory, result.stdout)
        candidate = Path(directory.group(1))
        self.assertFalse(target.exists())
        self.assertTrue((candidate / 'raw/engine.zip').is_file())
        self.assertIn('失败', (candidate / 'qa-report.md').read_text())
        document = build_document(pdf, candidate / 'raw')
        record = {key: document['source'][key] for key in ('pdf_sha256', 'zip_sha256')}
        item = dict(page=1, outcome='confirmed', page_state='blank', evidence='核实淡痕为扫描噪点',
                    content_sha256=content_digest(document, page=1))
        review = self.root / 'blank-review.json'
        review.write_text(json.dumps(dict(record, items=[item])))
        recovered = self.render(target, '--review', review, pdf=pdf, start=candidate)
        self.assertIn('通过', recovered.stdout)
        self.assertIn('<!-- page:1 -->', (target / 'document.md').read_text())
        review.write_text(json.dumps(dict(record, items=[item | {'page_state': 'has_content'}])))
        self.render(self.root / 'unrecovered', '--review', review, pdf=pdf, start=candidate, check=1)
        self.assertFalse((self.root / 'unrecovered').exists())

    def test_no_replace_under_contention(self):
        target = self.root / 'result'
        command = [sys.executable, '-B', str(SCRIPT), 'render', str(self.input), '--source-pdf', str(self.pdf),
                   '--output', str(target)]
        competition = '''
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import scan_pdf
publish = scan_pdf.publish_new
ready, partner = map(Path, sys.argv[2:4])

def compete(candidate, target):
    ready.touch()
    deadline = time.monotonic() + 10
    while not partner.exists():
        if time.monotonic() > deadline:
            raise OSError('partner did not reach publication')
        time.sleep(0.01)
    publish(candidate, target)

scan_pdf.publish_new = compete
raise SystemExit(scan_pdf.main(sys.argv[4:]))
'''
        racers = [subprocess.Popen([sys.executable, '-B', '-c', competition, str(SCRIPTS), str(i), str(1-i),
                                    *command[3:]], cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                  for i in range(2)]
        for racer in racers:
            racer.communicate(timeout=30)
        self.assertEqual(sorted(racer.returncode for racer in racers), [0, 1])
        self.assertTrue((self.root / '0').is_file() and (self.root / '1').is_file())
        original = tree_digests(target)
        self.render(target, check=1)
        self.assertEqual(original, tree_digests(target))
        empty = self.root / 'empty'
        empty.mkdir()
        self.render(empty, check=1)
        self.assertTrue(empty.is_dir())
        self.assertEqual(list(empty.iterdir()), [])

        interrupted = self.root / 'interrupted'
        program = '''
import os, signal, sys
sys.path.insert(0, sys.argv[1])
import scan_pdf

def before_publish(candidate, target):
    target.mkdir()
    (target / 'old.txt').write_text('previous')
    os.kill(os.getpid(), signal.SIGTERM)

scan_pdf.publish_new = before_publish
raise SystemExit(scan_pdf.main(sys.argv[2:]))
'''
        cancelled = subprocess.run([sys.executable, '-B', '-c', program, str(SCRIPTS), *command[3:-1], str(interrupted)],
                                   cwd=self.root, capture_output=True)
        self.assertLess(cancelled.returncode, 0, cancelled.stderr.decode())
        self.assertEqual(tree_digests(interrupted), {'old.txt': hashlib.sha256(b'previous').hexdigest()})

    def test_verify_reports_actual_image_sources_and_ignores_code(self):
        target = self.root / 'references'
        self.render(target)
        with (target / 'document.md').open('a') as stream:
            stream.write('\n![Bad](missing-figure.png)\n\n<img src="missing-html.png">\n'
                         '\n`![Example](code.png)`\n')
        result = self.cli('verify', target, '--source-pdf', self.pdf, check=1)
        self.assertIn('missing-figure.png', result.stdout)
        self.assertIn('missing-html.png', result.stdout)
        self.assertNotIn('code.png', result.stdout)

    def test_full_page_illustration_requires_page_and_current_image_confirmation(self):
        pdf = self.root / 'plates.pdf'
        bundle = self.root / 'plates'
        bundle.mkdir()
        with pymupdf.open() as source:
            source.new_page().insert_text((40, 50), 'Plates')
            page = source.new_page()
            page.draw_rect(pymupdf.Rect(40, 50, 200, 180), fill=(.2, .4, .8))
            source.save(pdf)
        image = dict(type='image', index=0, bbox=[0, 0, 1, 1], content=[dict(type='image_body', content='')])
        fixture_pack(pdf, bundle / 'raw', [[dict(type='text', index=0, content='Plates')], [image]])
        base = build_document(pdf, bundle / 'raw')
        record = {key: base['source'][key] for key in ('pdf_sha256', 'zip_sha256')}
        def confirm(**target):
            return dict(**target, outcome='confirmed', evidence='对照原页及相应区域',
                        content_sha256=content_digest(base, **target))
        page1, page2, picture = confirm(page=1), confirm(page=2), confirm(block_id=base['blocks'][-1]['id'])
        only = page2 | dict(page_state='illustration_only')
        for name, second, figures, status in [
                ('only', only, [picture], '通过'),
                ('legacy', page2 | dict(page_state='has_content'), [picture], '降级'),
                ('missing', only, [], '降级'),
                ('stale', only, [picture | dict(content_sha256='0' * 64)], '降级')]:
            with self.subTest(name=name):
                path = self.root / (name + '.json')
                path.write_text(json.dumps(dict(record, items=[page1, second, *figures])))
                out = self.root / name
                result = self.render(out, '--review', path, start=bundle, pdf=pdf)
                self.assertIn('结论：' + status, result.stdout)
                self.verify(out, 0, status, pdf)

    def test_render_keeps_review_offline(self):
        original = build_document(self.pdf, self.input / 'raw')
        binding = {key: original['source'][key] for key in ('pdf_sha256', 'zip_sha256')}
        block = original['blocks'][0]['id']
        item = dict(block_id=block, outcome='corrected', row=2, column=2, old='18', new='13',
                    evidence='原页 B 列读数 13', content_sha256='0' * 64)
        preview = apply_review(original, dict(binding, items=[item]))
        item['content_sha256'] = content_digest(preview, block_id=block)
        page = dict(page=1, outcome='confirmed', evidence='对照物理页 1', content_sha256=content_digest(preview, page=1))
        review = self.root / 'review.json'
        review.write_text(json.dumps(dict(binding, items=[item, page])))
        corrected, replay, old = [self.root / name for name in ('corrected', 'replay', 'old')]
        self.assertIn('通过', self.render(corrected, '--review', review).stdout)
        self.assertIn('通过', self.render(replay, start=corrected).stdout)
        self.assertEqual(tree_digests(corrected), tree_digests(replay))
        self.assertIn('| 18 | 13 |', (replay / 'document.md').read_text())
        self.assertIn("'18' → '13'", (replay / 'qa-report.md').read_text())
        self.render(old)
        self.assertIn('| 18 | 18 |', (old / 'document.md').read_text())
        self.verify(replay, 0, '通过')
