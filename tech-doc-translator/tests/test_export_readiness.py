"""翻译验收身份约束导出（设计 §4.7 / R7 / A7）的固定验收。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import verify_delivery as delivery_verifier

from test_delivery_evidence import SCRIPTS, sha

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None


def run_export(root, extra=(), out_name=None):
    work = root / ('work-%s' % uuid.uuid4().hex[:6])
    out_name = out_name or ('book-%s.pdf' % uuid.uuid4().hex[:6])
    cmd = [sys.executable, str(SCRIPTS / 'export_pdf.py'),
           '--output', str(root / out_name),
           '--work-dir', str(work),
           '--images-display', 'export/images_display.json',
           '--translation-record', 'source/acceptance_record.json']
    cmd += list(extra)
    cmd.append('01_章.md')
    run = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    run.out_name = out_name
    return run


@unittest.skipIf(pymupdf is None, "PyMuPDF 不可用，导出就绪测试跳过")
class ExportReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='export-ready-'))
        cls.root = cls.base / 'project'
        cls.root.mkdir()
        root = cls.root

        doc = pymupdf.open()
        page = doc.new_page(width=500, height=400)
        page.insert_text((40, 50), "1 Intro", fontsize=14)
        page.insert_text((40, 80),
                         "The system runs in 44 ms with 9% gain and works.",
                         fontsize=10)
        y = 110
        for line in ("def run():", "    return 44"):
            page.insert_text((60, y), line, fontsize=10, fontname="courier")
            y += 14
        base = pymupdf.Point(60, 160)
        for i, label in enumerate(("Batch A", "Batch B")):
            rect = pymupdf.Rect(base.x + i * 45, base.y - 50 - i * 15,
                                base.x + i * 45 + 30, base.y)
            page.draw_rect(rect, fill=(0.7, 0.7, 0.9))
            page.insert_text((rect.x0 + 8, base.y + 12), label,
                             fontsize=8)
        page.draw_line(pymupdf.Point(50, base.y),
                       pymupdf.Point(200, base.y), color=(0,))
        page.insert_text((70, 50), "series one", fontsize=8)
        doc.save(root / 'paper.pdf')
        doc.close()

        inspect_dir = root / 'source'
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
             'inspect', str(root / 'paper.pdf'), '--pages', 'all',
             '--output', str(inspect_dir)],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        checklist_path = inspect_dir / 'adjudication_checklist.json'
        payload = json.loads(checklist_path.read_text(encoding='utf-8'))
        payload['blocks'] = [
            {'id': 'b001', 'order': 1, 'type': 'heading', 'page': 1,
             'rect': [38, 40, 200, 55], 'level': 1, 'text': '1 Intro',
             'adjudication': {'status': 'accepted', 'basis': '编号+字号'}},
            {'id': 'b002', 'order': 2, 'type': 'paragraph', 'page': 1,
             'rect': [38, 70, 460, 90],
             'adjudication': {'status': 'accepted', 'basis': '正文'}},
            {'id': 'b003', 'order': 3, 'type': 'code_region', 'page': 1,
             'rect': [50, 100, 400, 135], 'golden': 'golden/code.txt',
             'lang': 'python',
             'adjudication': {'status': 'accepted', 'basis': '代码区'}},
            {'id': 'b004', 'order': 4, 'type': 'figure_region', 'page': 1,
             'rect': [40, 40, 220, 190], 'image': '../images/chart.png',
             'label': '图 A',
             'adjudication': {'status': 'accepted', 'basis': '图 A'}},
        ]
        payload['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        payload['conventions']['strong_tokens'] = ["44 ms", "9%", "run"]
        checklist_path.write_text(json.dumps(payload, ensure_ascii=False),
                                  encoding='utf-8')
        cls.checklist = checklist_path
        for sub in ('extract-code', 'extract-figures'):
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
                 sub, str(root / 'paper.pdf'), '--checklist',
                 str(checklist_path), '--output', str(inspect_dir)],
                capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        cls.source_md = inspect_dir / 'source_draft.md'
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'prepare_pdf_source.py'),
             'materialize', str(root / 'paper.pdf'), '--checklist',
             str(checklist_path), '--output', str(cls.source_md)],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        draft = ("# 1 Intro（引言）\n\n"
                 "> **来源**：https://example.com/pv-export-ready\n"
                 "> **抓取日期**：2026-09-27\n\n"
                 "【译文】系统运行耗时 44 ms，增益 9%，工作正常。\n\n"
                 "⟦CODE⟧\n\n"
                 "![图 A](images/chart.png)\n")
        draft_path = cls.base / 'draft.md'
        draft_path.write_text(draft, encoding='utf-8')
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'splice_fences.py'),
             str(draft_path), str(cls.source_md), str(root / '01_章.md')],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        updated = json.loads(checklist_path.read_text(encoding='utf-8'))
        figure_block = next(b for b in updated['blocks']
                            if b.get('type') == 'figure_region')
        width_px = (figure_block.get('figure_extraction') or {}) \
            .get('display_width_px')
        (root / 'export').mkdir(exist_ok=True)
        (root / 'export' / 'images_display.json').write_text(json.dumps({
            'version': 1, 'markdown': '01_章.md',
            'entries': [{
                'markdown': '../01_章.md', 'occurrence': 1,
                'image': '../images/chart.png',
                'sha256': figure_block['image_sha256'],
                'width': {'value': width_px, 'unit': 'px',
                          'basis': 'physical-width', 'reference': None},
                'source': {
                    'pdf': updated['source']['realpath'],
                    'pdf_sha256': updated['source']['sha256'],
                    'page': figure_block['page'],
                    'rect': figure_block['rect'], 'dpi': 200,
                    'resource_sha256': figure_block['image_sha256'],
                },
            }],
            'undetermined': [],
        }, ensure_ascii=False), encoding='utf-8')
        cls.build_record()

    @classmethod
    def build_record(cls):
        root = cls.root
        record = {
            'version': 1, 'mode': 'translation',
            'delivery_root': str(root),
            'inputs': ['01_章.md'], 'outputs': [],
            'images_display': 'export/images_display.json',
            'files': {'01_章.md': 'chapter', 'paper.pdf': 'pdf'},
            'sources': [{
                'family': 'pdf-source', 'source_version': '1.0-test',
                'pdf': 'paper.pdf',
                'checklist': 'source/adjudication_checklist.json',
                'source_markdown': 'source/source_draft.md',
                'layout_snapshot': 'source/snapshots_layout.txt',
                'reading_snapshot': 'source/snapshots_reading.txt',
                'covers': ['01_章.md'],
            }],
            'checks': [{
                'tool': 'verify_pdf_source',
                'args': ['paper.pdf',
                         '--checklist', 'source/adjudication_checklist.json',
                         '--source-md', 'source/source_draft.md',
                         '--translation', '01_章.md']}],
        }
        problems = []
        entries = delivery_verifier.check_source_chains(root, record,
                                                        problems)
        assert not problems, problems
        identity = delivery_verifier.compute_delivery_identity(
            root, record, entries)
        candidates, _p, input_checks, pdf_checks = \
            delivery_verifier.rerun_checks(root, record, problems)
        assert not problems, problems
        reviews = []
        for kind in ('source-reconcile', 'semantic'):
            binding = delivery_verifier.expected_review_binding(
                kind, '01_章.md', str(root), record, entries,
                input_checks, pdf_checks, identity)
            assert binding is not None, kind
            reviews.append({
                'kind': kind, 'target': '01_章.md', 'status': 'closed',
                'sha256': identity['inputs']['01_章.md'],
                'binding': binding,
                'note': '%s 复核闭合' % kind})
        record['reviews'] = reviews
        (root / 'source' / 'acceptance_record.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding='utf-8')
        cls.record = record

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def test_ready_export_passes_and_records_identity(self):
        result = run_export(self.root)
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        self.assertTrue((self.root / result.out_name).is_file())
        report = self._report()
        readiness = report.get('translation_readiness')
        self.assertIsNotNone(readiness)
        self.assertTrue(readiness['ready'])
        self.assertTrue(readiness['reconfirmed_before_replace'])
        self.assertIn('inputs', readiness['identity'])
        # 交付级映射必须实际消费：条目路径相对映射文件（非交付根），
        # 恢复数按出现核对（映射数据错误会静默回退自然尺寸）
        self.assertTrue(report['images_display_maps'])
        coverage = report['image_coverage']
        chapter = next(iter(coverage.values()))
        self.assertEqual(chapter['restored'], 1)
        self.assertEqual(chapter['missing'], 0)

    def test_scope_mismatch_rejected_as_insufficient(self):
        record = json.loads((self.root / 'source' /
                             'acceptance_record.json')
                            .read_text(encoding='utf-8'))
        record['inputs'] = ['01_章.md', '02_章.md']
        (self.root / 'source' / 'acceptance_record.json').write_text(
            json.dumps(record, ensure_ascii=False), encoding='utf-8')
        try:
            result = run_export(self.root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('证据不足', result.stderr)
            self.assertFalse((self.root / result.out_name).exists())
        finally:
            self.build_record()

    def test_missing_reviews_rejected_as_insufficient(self):
        record = json.loads((self.root / 'source' /
                             'acceptance_record.json')
                            .read_text(encoding='utf-8'))
        record.pop('reviews')
        (self.root / 'source' / 'acceptance_record.json').write_text(
            json.dumps(record, ensure_ascii=False), encoding='utf-8')
        try:
            result = run_export(self.root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('证据不足', result.stderr)
        finally:
            self.build_record()

    def test_negation_drift_blocks_export_without_covering(self):
        # A7：改正文否定词且硬检查仍 PASS——机器硬检查不拦（语义域），
        # 验收身份漂移必须拦截，且旧成品不被覆盖
        first = run_export(self.root)
        self.assertEqual(first.returncode, 0, first.stderr[-400:])
        original_pdf = (self.root / first.out_name).read_bytes()
        target = self.root / '01_章.md'
        text = target.read_text(encoding='utf-8')
        target.write_text(text.replace('工作正常', '工作不正常'),
                          encoding='utf-8')
        try:
            # 硬检查仍然 PASS（结构不变量不承诺语义）
            hard = subprocess.run(
                [sys.executable, str(SCRIPTS / 'verify_pdf_source.py'),
                 'paper.pdf', '--checklist',
                 'source/adjudication_checklist.json',
                 '--source-md', 'source/source_draft.md',
                 '--translation', '01_章.md'],
                cwd=str(self.root), capture_output=True, text=True)
            self.assertEqual(hard.returncode, 0, hard.stderr)
            second = run_export(self.root, out_name=first.out_name)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('漂移', second.stderr)
            self.assertEqual((self.root / first.out_name).read_bytes(),
                             original_pdf)
        finally:
            target.write_text(text, encoding='utf-8')

    def test_h1_english_title_removal_rejected(self):
        record = json.loads((self.root / 'source' /
                             'acceptance_record.json')
                            .read_text(encoding='utf-8'))
        record['reviews'] = []
        (self.root / 'source' / 'acceptance_record.json').write_text(
            json.dumps(record, ensure_ascii=False), encoding='utf-8')
        target = self.root / '01_章.md'
        text = target.read_text(encoding='utf-8')
        target.write_text(text.replace(
            '# 1 Intro（引言）', '# 引言'), encoding='utf-8')
        try:
            result = run_export(self.root)
            self.assertNotEqual(result.returncode, 0)
        finally:
            target.write_text(text, encoding='utf-8')
            self.build_record()

    def test_reconfirm_before_replace_keeps_old_pdf(self):
        import export_pdf as exporter
        first = run_export(self.root)
        self.assertEqual(first.returncode, 0, first.stderr[-400:])
        target = self.root / first.out_name
        original_pdf = target.read_bytes()
        original = delivery_verifier.check_translation_readiness_cli
        calls = []

        def flaky(record_path, inputs):
            calls.append(1)
            if len(calls) > 1:
                return False, {"ready": False, "reasons": [
                    "【漂移】导出期间输入变化（模拟）"]}
            return original(record_path, inputs)

        delivery_verifier.check_translation_readiness_cli = flaky
        try:
            code = exporter.export(
                [str(self.root / '01_章.md')], target,
                self.root / ('work-%s' % uuid.uuid4().hex[:6]),
                images_display_paths=[
                    str(self.root / 'export' / 'images_display.json')],
                translation_record_path=str(
                    self.root / 'source' / 'acceptance_record.json'))
            self.assertNotEqual(code, 0)
            self.assertGreaterEqual(len(calls), 2)  # 生成前 + 替换前
            self.assertEqual(target.read_bytes(), original_pdf)
        finally:
            delivery_verifier.check_translation_readiness_cli = original

    def test_independent_export_without_record_unchanged(self):
        work = self.root / ('work-%s' % uuid.uuid4().hex[:6])
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'export_pdf.py'),
             '--output', str(self.root / 'solo.pdf'),
             '--work-dir', str(work),
             '--images-display', 'export/images_display.json',
             '01_章.md'],
            cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        report = json.loads((work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        self.assertNotIn('translation_readiness', report)

    def _report(self):
        reports = sorted(self.root.glob('work-*/export_report.json'),
                         key=os.path.getmtime)
        return json.loads(reports[-1].read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
