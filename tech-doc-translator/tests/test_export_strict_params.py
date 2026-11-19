"""第 2 批 R12：记录登记的 verify_pdf 严格参数与本次导出逐项比对。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter

ARGS = ['--pdf', 'book.pdf', '--work-dir', 'evidence/current-export',
        '--images-display', 'export/images_display.json', '--require-display-map',
        '--toc-sections', '--unlink-target', '术语表.md', '00_目录.md', '01_章.md']


class RecordParamTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='strict-params-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.record_path = self.root / 'docs/record.json'
        self.record_path.parent.mkdir()
        self.write([{'tool': 'verify_pdf', 'args': ARGS}])

    def write(self, checks):
        self.record_path.write_text(json.dumps({
            'version': 1, 'mode': 'translation+pdf', 'delivery_root': str(self.root),
            'inputs': ['00_目录.md', '01_章.md'], 'outputs': [], 'checks': checks,
            'reviews': []}, ensure_ascii=False))

    def mismatches(self, output='book.pdf', **changes):
        current = {'require_display_map': True, 'toc_sections': True,
                   'images_display': [str(self.root / 'export/images_display.json')],
                   'provenance': None, 'view_declaration': None,
                   'unlink_target': [str(self.root / '术语表.md')],
                   'navigation_record': [], 'site_root': []}
        current.update(changes)
        return exporter.record_pdf_param_mismatches(self.record_path, self.root / output, current)

    def test_same_params_pass(self):
        self.assertEqual(self.mismatches(), [])

    def test_missing_strict_flag_reported(self):
        self.assertEqual(self.mismatches(require_display_map=False),
                         ['--require-display-map：记录 启用 / 本次 未启用'])

    def test_path_params_compared_after_resolving(self):
        problems = self.mismatches(unlink_target=[],
                                   images_display=[str(self.root / 'other.json')])
        self.assertEqual([p.split('：')[0] for p in problems],
                         ['--images-display', '--unlink-target'])
        self.assertTrue(problems[1].endswith('/ 本次 无'))

    def test_other_output_or_no_pdf_check_not_compared(self):
        self.assertEqual(self.mismatches(output='other.pdf', require_display_map=False), [])
        self.write([])
        self.assertEqual(self.mismatches(require_display_map=False), [])


if __name__ == '__main__':
    unittest.main()
