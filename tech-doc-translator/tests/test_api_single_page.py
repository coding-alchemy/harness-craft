"""单页 API 仍通过完整家族门禁，列表覆盖率来自实际块读取。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
from _verification import markdown_list_count
from export_heading_list import export_heading_list
from verify_translation import run_checks


class SinglePageApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='api-single-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'page.html').write_text('<article><h1>API</h1><p>Text.</p></article>')
        (self.root / 'manifest.txt').write_text('page.html\n')
        (self.root / 'toc.txt').write_text('page.html\n')
        (self.root / 'source.md').write_text('# API\n\nText.\n')
        (self.root / 'doc.md').write_text('# API（接口）\n\n正文。\n')

    def check(self, *sources):
        return subprocess.run([sys.executable, str(SCRIPTS/'verify_api_translation.py'),
            str(self.root/'doc.md'), str(self.root/'manifest.txt'),
            str(self.root/'toc.txt'), str(self.root), *map(str, sources)],
            text=True, capture_output=True)

    def test_single_source_cli_and_zero_source_rejected(self):
        result = self.check(self.root/'source.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS: 1 pages', result.stdout)
        self.assertNotEqual(self.check().returncode, 0)

    def test_single_source_retains_toc_and_image_gate(self):
        (self.root/'toc.txt').write_text('page.html\nmissing.html\n')
        self.assertNotEqual(self.check(self.root/'source.md').returncode, 0)
        (self.root/'toc.txt').write_text('page.html\n')
        (self.root/'doc.md').write_text('# API\n\n![image](missing.png)\n')
        self.assertNotEqual(self.check(self.root/'source.md').returncode, 0)

    def test_list_counts_ignore_code_and_remain_information(self):
        src = '# API\n\n1. first\n   - nested\n2. second\n\n```\n- example\n```\n'
        doc = src.replace('1. first', '1. 第一').replace('   - nested\n', '')
        self.assertEqual(markdown_list_count(src), 3)
        self.assertEqual(markdown_list_count(doc), 2)
        failures, lines = run_checks(doc, src, doc_dir=str(self.root),
            doc_label='doc.md', src_label='source.md')
        self.assertEqual(failures, 0, lines)
        self.assertIn('覆盖率 列表项: 源 3 / 译 2（差值供人工判断）', lines)

    def test_heading_task_list_excludes_fences_and_indented_code(self):
        path = self.root/'source.md'
        path.write_text('# API\n\n````\n## fake\n```\n````\n\n~~~\n## fake2\n~~~\n\n'
                        '    ## fake3\n\n## Real\n')
        target = self.root/'headings.txt'
        self.assertEqual(export_heading_list(str(path),str(target)), ['API','Real'])
        self.assertEqual(target.read_text(), 'API\nReal\n')


if __name__ == '__main__':
    unittest.main()
