"""工作区外隔离 venv 真正缺少依赖时，实际 CLI 在打印前失败并保旧。"""
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
import venv
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
FIXTURE = Path(__file__).resolve().parent / 'fixtures/valid_1x1.png'


class PdfDependencyPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pdf-dependency-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = self.root / 'chapter.md'
        self.doc.write_text('# 依赖预检\n\n> **来源**：https://example.org/dependencies\n\n正文保留。\n')
        self.pdf = self.root / 'old.pdf'
        self.pdf.write_bytes(b'old output must survive')
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}

    def isolated(self, missing):
        directory = self.root / ('venv-' + '-'.join(missing))
        venv.EnvBuilder(with_pip=False, symlinks=True).create(directory)
        source = Path(sysconfig.get_path('purelib'))
        destination = next((directory / 'lib').glob('python*/site-packages'))
        for child in source.iterdir():
            if child.name.endswith('.pth') or any(child.name == name or child.name.startswith(name + '-') for name in missing):
                continue
            (destination / child.name).symlink_to(child, target_is_directory=child.is_dir())
        return directory / 'bin/python'

    def export(self, python, work='work', env=None):
        return subprocess.run([str(python), str(SCRIPTS / 'export_pdf.py'), '--output', str(self.pdf),
            '--work-dir', str(self.root / work), str(self.doc)], env=env or self.env,
            text=True, capture_output=True)

    def assert_early_failure(self, result, python, component):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(component, result.stderr)
        self.assertIn(str(python), result.stderr)
        self.assertIn('requirements', result.stderr)
        self.assertIn('venv', result.stderr)
        self.assertFalse((self.root / 'work/candidate.pdf').exists())
        self.assertFalse((self.root / 'work/combined.html').exists())
        self.assertEqual(self.pdf.read_bytes(), b'old output must survive')

    def test_core_dependencies_missing_before_candidate_print(self):
        for module, label in [('uniseg', 'uniseg'), ('pypdf', 'pypdf'),
                              ('markdown_it', 'markdown_it'), ('pygments', 'pygments'),
                              ('bs4', 'bs4'), ('tinycss2', 'tinycss2'), ('playwright', 'playwright')]:
            with self.subTest(module=module):
                python = self.isolated([module])
                self.assert_early_failure(self.export(python), python, label)

    def test_pillow_missing_is_not_reported_as_unmeasurable_image(self):
        python = self.isolated(['PIL'])
        shutil.copyfile(FIXTURE, self.root / 'image.png')
        self.doc.write_text(self.doc.read_text() + '\n![图](image.png)\n')
        original = self.doc.read_bytes()
        result = self.export(python)
        self.assert_early_failure(result, python, 'PIL.Image')
        self.assertNotIn('图片内容无法量测', result.stderr)
        self.assertEqual(self.doc.read_bytes(), original)

    def test_missing_browser_and_footnote_plugin(self):
        result = self.export(sys.executable, env={**self.env,
            'PLAYWRIGHT_BROWSERS_PATH': str(self.root / 'empty-browsers')})
        self.assert_early_failure(result, sys.executable, 'Chromium')
        self.assertIn('playwright install chromium', result.stderr)
        python = self.isolated(['mdit_py_plugins'])
        self.doc.write_text(self.doc.read_text() + '\n引用[^n]。\n\n[^n]: 定义。\n')
        self.assert_early_failure(self.export(python), python, 'mdit_py_plugins')

    def test_optional_dependencies_follow_actual_mode(self):
        python = self.isolated(['PIL', 'pymupdf', 'fitz'])
        result = self.export(python)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        check = [str(python), str(SCRIPTS / 'verify_pdf.py'), '--pdf', str(self.pdf),
                 '--work-dir', str(self.root / 'work'), str(self.doc)]
        result = subprocess.run(check, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        original = self.pdf.read_bytes()
        result = subprocess.run([*check, '--visual-aid'], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PyMuPDF', result.stderr)
        self.assertIn(str(python), result.stderr)
        self.assertEqual(self.pdf.read_bytes(), original)

    def test_plain_translation_does_not_import_pdf_dependencies(self):
        python = self.isolated(['uniseg', 'pypdf', 'playwright', 'pymupdf', 'fitz'])
        source = self.root / 'source.md'
        source.write_text('# T\n\nSource.\n')
        self.doc.write_text('# T（示例）\n\n正文。\n')
        result = subprocess.run([str(python), str(SCRIPTS / 'verify_translation.py'),
            str(self.doc), str(source)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
