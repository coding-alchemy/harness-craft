import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/scan-pdf-to-markdown/scripts'
sys.path.insert(0, str(SCRIPTS))

from capture import _ocr_environment, capture_raw, read_raw


class CaptureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pdf = self.root / 'source.pdf'
        self.raw = self.root / 'raw'
        with pymupdf.open() as doc:
            doc.new_page()
            page = doc.new_page(width=400, height=500)
            page.set_cropbox(pymupdf.Rect(25, 30, 375, 470))
            page.set_rotation(90)
            doc.save(self.pdf)
        self.received = None

    def engine(self, command, **kwargs):
        self.assertEqual(kwargs['env']['MINERU_MODEL_SOURCE'], 'local')
        self.assertEqual(kwargs['env']['MINERU_LLM_AIDED_FEATURES_TITLE_LEVELING'], 'false')
        self.assertEqual(kwargs['env']['MINERU_LLM_AIDED_FEATURES_CROSS_PAGE_TABLE_CELL_MERGE'], 'false')
        snapshot = Path(command[2])
        self.received = snapshot.read_bytes()
        self.assertNotEqual(snapshot, self.pdf)
        self.assertEqual(snapshot.stat().st_mode & 0o222, 0)
        for option, value in [('--pages', 'all'), ('--tier', 'basic'),
                              ('--ocr-mode', 'ocr'), ('--format', 'zip')]:
            self.assertEqual(command[command.index(option) + 1], value)
        output = Path(command[command.index('-o') + 1])
        pages = [{'page_idx': 0, 'blocks': []}, {'page_idx': 1, 'blocks': []}]
        common = {
            'metadata': {'file_suffix': 'pdf', 'producer': {'name': 'mineru', 'version': '4.1.5'}},
            'extensions': {'mineru': {'tier': 'basic', 'parse_mode': 'ocr'}},
            'is_full_document': True,
            'pages': pages,
        }
        with ZipFile(output, 'w') as archive:
            archive.writestr('middle_json.json', json.dumps(dict(
                common, schema='docvortex.middle', schema_version='2.0',
            )))
            archive.writestr('structured_content.json', json.dumps(common))
        return subprocess.CompletedProcess(command, 0, '', '')

    def capture(self, run=None):
        with patch('capture.subprocess.run', side_effect=run or self.engine):
            capture_raw(self.pdf, self.raw)

    def test_new_session_defaults_respect_each_config_source(self):
        config = self.root / 'custom.yaml'
        backend, device = 'MINERU_MODEL_SMALL_BACKEND', 'MINERU_MODEL_ONNX_DEVICE'
        with patch.dict(os.environ, {'MINERU_HOME': str(self.root)}, clear=True):
            self.assertEqual([_ocr_environment()[k] for k in (backend, device)], ['onnx', 'cpu'])
            os.environ['MINERU_CONFIG'] = str(config)
            config.write_text('model:\n  small_backend: torch\n')
            self.assertNotIn(backend, _ocr_environment())
            self.assertEqual(_ocr_environment()[device], 'cpu')
            config.write_text('model:\n  small_backend: torch\n  onnx_device: gpu\n')
            os.environ[backend] = 'auto'
            self.assertEqual(_ocr_environment()[backend], 'auto')
            self.assertNotIn(device, _ocr_environment())

    def test_capture_binds_exact_input(self):
        self.capture()
        data = read_raw(self.pdf, self.raw)
        source = data['source']
        self.assertEqual(source['pdf_sha256'], hashlib.sha256(self.received).hexdigest())
        self.assertEqual(source['zip_sha256'], hashlib.sha256((self.raw / 'engine.zip').read_bytes()).hexdigest())
        self.assertEqual([page['page_idx'] for page in data['middle']['pages']], [0, 1])
        self.assertEqual(source['pages'][1], {
            'page': 2, 'cropbox': [25.0, 30.0, 375.0, 470.0], 'rotation': 90,
        })

        def drift(command, **kwargs):
            result = self.engine(command, **kwargs)
            self.pdf.write_bytes(b'new content at the original path')
            return result

        original_source = (self.raw / 'source.json').read_bytes()
        self.raw = self.root / 'new-raw'
        with self.assertRaisesRegex(ValueError, '源 PDF'):
            self.capture(drift)
        self.assertEqual(self.pdf.read_bytes(), b'new content at the original path')
        self.assertEqual((self.root / 'raw/source.json').read_bytes(), original_source)
        self.assertFalse((self.raw / 'source.json').exists())

    def test_wrong_pdf_or_incomplete_engine_pack(self):
        self.capture()
        original = self.pdf.read_bytes()
        self.pdf.write_bytes(original + b'\n% different')
        with self.assertRaisesRegex(ValueError, '源 PDF'):
            read_raw(self.pdf, self.raw)
        self.pdf.write_bytes(original)
        engine = self.raw / 'engine.zip'
        with ZipFile(engine) as archive:
            middle = json.loads(archive.read('middle_json.json'))
            structured = archive.read('structured_content.json')
        engine.write_bytes(engine.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'engine.zip'):
            read_raw(self.pdf, self.raw)
        for change in ('missing', 'duplicate', 'partial', 'misaligned'):
            with self.subTest(change=change):
                altered = json.loads(json.dumps(middle))
                if change == 'missing':
                    altered['pages'].pop()
                elif change == 'duplicate':
                    altered['pages'][1]['page_idx'] = 0
                elif change == 'partial':
                    altered['is_full_document'] = False
                else:
                    altered['pages'][0]['blocks'] = [{'type': 'text', 'index': 0}]
                with ZipFile(engine, 'w') as archive:
                    archive.writestr('middle_json.json', json.dumps(altered))
                    archive.writestr('structured_content.json', structured)
                source_file = self.raw / 'source.json'
                source = json.loads(source_file.read_bytes())
                source['zip_sha256'] = hashlib.sha256(engine.read_bytes()).hexdigest()
                source_file.write_text(json.dumps(source), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'middle_json|structured_content'):
                    read_raw(self.pdf, self.raw)

    def test_read_raw_without_mineru(self):
        self.capture()
        checkout = f'import sys; sys.path.insert(0, {str(SCRIPTS)!r})\n'
        program = checkout + '''
from pathlib import Path
from capture import read_raw
assert read_raw(Path(sys.argv[1]), Path(sys.argv[2]))['source']['page_count'] == 2
assert not any(name == 'mineru' or name.startswith('mineru.') for name in sys.modules)
'''
        result = subprocess.run(
            [sys.executable, '-B', '-c', program, str(self.pdf), str(self.raw)],
            cwd=self.root, env=dict(os.environ, PATH=''), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
