"""PDF 源物化与独立对账的外部行为验收；损伤用例在 /tmp 副本上制造。"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf
        HAVE_PYMUPDF = True
    except ImportError:
        HAVE_PYMUPDF = False

if not HAVE_PYMUPDF:
    raise unittest.SkipTest("PyMuPDF 不可用，整组 PDF 源对账测试跳过")

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
PREPARE = SCRIPTS / 'prepare_pdf_source.py'
VERIFY = SCRIPTS / 'verify_pdf_source.py'


def run_cli(script, *args):
    return subprocess.run([sys.executable, str(script)]
                          + [str(a) for a in args],
                          capture_output=True, text=True)


class PdfSourceReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root

        doc = pymupdf.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), "1. Introduction")
        page.insert_text((40, 90), "First paragraph of the paper body "
                                   "with enough text to reconcile.")
        page.insert_text((40, 120), "def add(a, b):")
        page.insert_text((40, 134), "    return a + b")
        page.insert_text((40, 170), "Second paragraph follows the code "
                                    "listing region on the same page.")
        page.insert_text((40, 220), "Figure 1. A code listing figure.")
        doc.save(root / 'sample.pdf')
        doc.close()
        cls.pdf = root / 'sample.pdf'

        doc = pymupdf.open()
        doc.new_page(width=300, height=400)
        doc[0].insert_image(pymupdf.Rect(30, 40, 270, 360),
                            stream=pymupdf.Pixmap(
                                pymupdf.csRGB,
                                pymupdf.IRect(0, 0, 8, 8)).tobytes("png"))
        doc.save(root / 'scanned.pdf')
        doc.close()
        cls.scanned = root / 'scanned.pdf'

        # 勘察并逐项裁决清单
        cls.inspect_dir = root / 'inspect'
        result = run_cli(PREPARE, 'inspect', cls.pdf, '--pages', 'all',
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.checklist = cls.inspect_dir / 'adjudication_checklist.json'

        doc = pymupdf.open(str(cls.pdf))
        blocks_rects = {}
        prefixes = {
            'intro': '1. Introduction',
            'first': 'First paragraph of the paper body',
            'code': 'def add(a, b):',
            'second': 'Second paragraph follows the code',
            'caption': 'Figure 1. A code listing figure.',
        }
        for block in doc[0].get_text('blocks'):
            if block[6] != 0 or not block[4].strip():
                continue
            first = block[4].strip().splitlines()[0]
            for key, prefix in prefixes.items():
                if key not in blocks_rects and first.startswith(prefix):
                    blocks_rects[key] = [round(v, 2) for v in block[:4]]
        doc.close()
        cls.rects = blocks_rects
        payload = json.loads(cls.checklist.read_text(encoding='utf-8'))
        payload['blocks'] = [
            {'id': 'b001', 'order': 1, 'type': 'heading', 'page': 1,
             'rect': blocks_rects['intro'], 'level': 2,
             'text': '1. Introduction',
             'adjudication': {'status': 'accepted', 'basis': '编号+字号线索'}},
            {'id': 'b002', 'order': 2, 'type': 'paragraph', 'page': 1,
             'rect': blocks_rects['first'],
             'adjudication': {'status': 'accepted', 'basis': '正文块'}},
            {'id': 'b003', 'order': 3, 'type': 'code_region', 'page': 1,
             'rect': blocks_rects['code'], 'label': '图 1 代码区域',
             'adjudication': {'status': 'accepted', 'basis': '等宽文本区域'}},
            {'id': 'b004', 'order': 4, 'type': 'paragraph', 'page': 1,
             'rect': blocks_rects['second'],
             'adjudication': {'status': 'accepted', 'basis': '正文块'}},
            {'id': 'b005', 'order': 5, 'type': 'figure_caption', 'page': 1,
             'rect': blocks_rects['caption'],
             'text': 'Figure 1. A code listing figure.',
             'adjudication': {'status': 'accepted', 'basis': '图题候选'}},
        ]
        payload['reading_order'] = {
            'adjudicated': True,
            'basis': '单栏顺序即阅读顺序，对照原页确认',
        }
        cls.checklist.write_text(json.dumps(payload, ensure_ascii=False),
                                 encoding='utf-8')

        cls.md = root / 'source_draft.md'
        result = run_cli(PREPARE, 'materialize', cls.pdf,
                         '--checklist', cls.checklist, '--output', cls.md)
        assert result.returncode == 0, result.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verify(self, md):
        return run_cli(VERIFY, self.pdf, '--checklist', self.checklist,
                       '--source-md', md)

    def test_materialize_pass_and_pending_marker(self):
        text = self.md.read_text(encoding='utf-8')
        self.assertIn('[PENDING-CODE page=1', text)
        self.assertIn('图 1 代码区域', text)
        self.assertIn('## 1. Introduction', text)
        result = self.verify(self.md)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('机器硬检查通过', result.stdout)

    def _damaged(self, name):
        damaged = self.root / name
        shutil.copyfile(self.md, damaged)
        shutil.copyfile(str(self.md) + '.blocks.json',
                        str(damaged) + '.blocks.json')
        return damaged

    def test_swapped_blocks_fail_with_location(self):
        damaged = self._damaged('swapped.md')
        lines = damaged.read_text(encoding='utf-8').split('\n')
        first = next(i for i, ln in enumerate(lines)
                     if ln.startswith('First paragraph'))
        second = next(i for i, ln in enumerate(lines)
                      if ln.startswith('Second paragraph'))
        lines[first], lines[second] = lines[second], lines[first]
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        result = self.verify(damaged)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL', result.stderr)
        self.assertIn('page=1', result.stderr)

    def test_missing_region_fails(self):
        damaged = self._damaged('missing.md')
        lines = damaged.read_text(encoding='utf-8').split('\n')
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith('Second paragraph'))
        del lines[start:start + 1]
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        result = self.verify(damaged)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL', result.stderr)

    def test_extra_unclaimed_line_fails(self):
        damaged = self._damaged('extra.md')
        lines = damaged.read_text(encoding='utf-8').split('\n')
        lines.append('An unexplained inserted line.')
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        result = self.verify(damaged)
        self.assertEqual(result.returncode, 1)
        self.assertIn('不属于任何已裁决块区间', result.stderr)

    def test_dropped_pending_marker_fails(self):
        damaged = self._damaged('dropped.md')
        lines = [ln for ln in damaged.read_text(encoding='utf-8').split('\n')
                 if not ln.startswith('[PENDING-CODE')]
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        result = self.verify(damaged)
        self.assertEqual(result.returncode, 1)
        self.assertIn('待处理标记', result.stderr)

    def test_block_outside_declared_scope_fails(self):
        payload = json.loads(self.checklist.read_text(encoding='utf-8'))
        payload['scope'] = [2]
        bad = self.root / 'scope_checklist.json'
        bad.write_text(json.dumps(payload, ensure_ascii=False),
                       encoding='utf-8')
        result = run_cli(VERIFY, self.pdf, '--checklist', bad,
                         '--source-md', self.md)
        self.assertEqual(result.returncode, 1)
        self.assertIn('落在声明范围', result.stderr)

    def test_materialize_refuses_unadjudicated_order_and_scanned(self):
        payload = json.loads(self.checklist.read_text(encoding='utf-8'))
        payload['reading_order'] = {'adjudicated': False, 'basis': ''}
        bad = self.root / 'bad_checklist.json'
        bad.write_text(json.dumps(payload, ensure_ascii=False),
                       encoding='utf-8')
        result = run_cli(PREPARE, 'materialize', self.pdf,
                         '--checklist', bad, '--output', self.root / 'x.md')
        self.assertEqual(result.returncode, 2)
        self.assertIn('阅读顺序未记录裁决', result.stderr)

        out = self.root / 'scanned_inspect'
        result = run_cli(PREPARE, 'inspect', self.scanned, '--pages', 'all',
                         '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_cli(PREPARE, 'materialize', self.scanned,
                         '--checklist',
                         out / 'adjudication_checklist.json',
                         '--output', self.root / 'y.md')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不能宣称全文准备完成', result.stderr)


if __name__ == '__main__':
    unittest.main()
