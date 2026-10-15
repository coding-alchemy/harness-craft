"""矢量图裁剪、归属覆盖核对与来源身份绑定的外部行为验收。

fixture 在测试时用 PyMuPDF 生成真实 PDF：无大面积外框的矢量图 +
同页表格边框混排，覆盖裁剪、PNG 魔数、身份绑定与四种损伤
（同名换图、换序、漏图、删图中文字标签）各自 FAIL 并定位。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_test_support import pymupdf, CHART_A, draw_chart, draw_table

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
PREPARE = SCRIPTS / 'prepare_pdf_source.py'
VERIFY = SCRIPTS / 'verify_pdf_source.py'

CHART_B = (40, 40, 220, 190)


def build_pdf(path, with_legend=True):
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=400)
    labels = ["Batch A", "Batch B", "series one" if with_legend else "series"]
    draw_chart(page, labels)
    draw_table(page)
    page2 = doc.new_page(width=500, height=400)
    draw_chart(page2, ["Run X", "Run Y", "series two"])
    doc.save(path)
    doc.close()


def run_cli(script, *args):
    return subprocess.run([sys.executable, str(script)]
                          + [str(a) for a in args],
                          capture_output=True, text=True)


class PdfSourceFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root
        cls.pdf = root / 'charts.pdf'
        build_pdf(cls.pdf)
        cls.broken_pdf = root / 'charts_missing_label.pdf'
        build_pdf(cls.broken_pdf, with_legend=False)

        cls.inspect_dir = root / 'inspect'
        result = run_cli(PREPARE, 'inspect', cls.pdf, '--pages', 'all',
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.checklist = cls.inspect_dir / 'adjudication_checklist.json'
        payload = json.loads(cls.checklist.read_text(encoding='utf-8'))
        payload['blocks'] = [
            {'id': 'b001', 'order': 1, 'type': 'figure_region', 'page': 1,
             'rect': list(CHART_A), 'image': 'images/chart_a.png',
             'label': '图 A',
             'adjudication': {'status': 'accepted', 'basis': '图 A 区域'}},
            {'id': 'b002', 'order': 2, 'type': 'figure_region', 'page': 2,
             'rect': list(CHART_B), 'image': 'images/chart_b.png',
             'label': '图 B',
             'adjudication': {'status': 'accepted', 'basis': '图 B 区域'}},
        ]
        payload['reading_order'] = {'adjudicated': True, 'basis': '顺序'}
        cls.checklist.write_text(json.dumps(payload, ensure_ascii=False),
                                 encoding='utf-8')

        result = run_cli(PREPARE, 'extract-figures', cls.pdf,
                         '--checklist', cls.checklist,
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.md = root / 'source_draft.md'
        result = run_cli(PREPARE, 'materialize', cls.pdf,
                         '--checklist', cls.checklist, '--output', cls.md)
        assert result.returncode == 0, result.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_extract_records_identity_display_width_and_census(self):
        payload = json.loads(self.checklist.read_text(encoding='utf-8'))
        block = payload['blocks'][0]
        self.assertEqual(block['image'], 'images/chart_a.png')
        self.assertEqual(len(block['image_sha256']), 64)
        info = block['figure_extraction']
        self.assertEqual(info['dpi'], 200)
        self.assertEqual(info['width_pt'], round(CHART_A[2] - CHART_A[0], 2))
        # 显示宽度按物理宽度 pt→CSS px（1px=0.75pt），不以 dpi 冒充
        self.assertEqual(info['display_width_px'],
                         round((CHART_A[2] - CHART_A[0]) / 0.75, 1))
        census = info['census']
        # 图中文字标签（批名与图例）进入普查
        self.assertTrue(any('series one' in t for t in census['texts']))
        # 同页表格边框与单元格文字不属本图，不计入普查
        self.assertTrue(all('H0' not in t and 'H1' not in t
                            for t in census['texts']))
        # PNG 魔数有效
        with open(self.inspect_dir / 'images/chart_a.png', 'rb') as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")

    def test_materialize_and_verify_pass(self):
        text = self.md.read_text(encoding='utf-8')
        self.assertIn('![图 A](inspect/images/chart_a.png)', text)
        self.assertIn('![图 B](inspect/images/chart_b.png)', text)
        result = run_cli(VERIFY, self.pdf, '--checklist', self.checklist,
                         '--source-md', self.md)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _damaged(self, name, transform):
        damaged = self.root / name
        shutil.copyfile(self.md, damaged)
        shutil.copyfile(str(self.md) + '.blocks.json',
                        str(damaged) + '.blocks.json')
        lines = damaged.read_text(encoding='utf-8').split('\n')
        transform(lines)
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        return run_cli(VERIFY, self.pdf, '--checklist', self.checklist,
                       '--source-md', damaged)

    def test_same_name_image_swap_fails(self):
        target = self.inspect_dir / 'images/chart_a.png'
        original = target.read_bytes()
        try:
            shutil.copyfile(self.inspect_dir / 'images/chart_b.png', target)
            result = self._damaged('swap_content.md', lambda ls: None)
            self.assertEqual(result.returncode, 1)
            self.assertIn('同名换图', result.stderr)
        finally:
            target.write_bytes(original)

    def test_swapped_image_order_fails(self):
        def swap(ls):
            a = next(i for i, ln in enumerate(ls) if 'chart_a.png' in ln)
            b = next(i for i, ln in enumerate(ls) if 'chart_b.png' in ln)
            ls[a], ls[b] = ls[b], ls[a]
        result = self._damaged('swap_order.md', swap)
        self.assertEqual(result.returncode, 1)
        self.assertIn('同名换图', result.stderr)

    def test_missing_image_ref_fails(self):
        def drop(ls):
            index = next(i for i, ln in enumerate(ls)
                         if 'chart_b.png' in ln)
            del ls[index]
        result = self._damaged('missing.md', drop)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL', result.stderr)

    def test_deleted_infigure_label_census_fails(self):
        # 同版式但删掉图例文字标签的 PDF：归属覆盖核对必须定位差异
        result = run_cli(VERIFY, self.broken_pdf, '--checklist',
                         self.checklist, '--source-md', self.md)
        self.assertEqual(result.returncode, 1)
        self.assertIn('图中文字标签差异', result.stderr)


if __name__ == '__main__':
    unittest.main()
