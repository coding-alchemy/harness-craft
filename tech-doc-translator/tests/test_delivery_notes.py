"""第 2 批 R12：交付文书统计段渲染；含〔待补的备注与用户说明不能交付。"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
import render_delivery_notes as notes
import verify_delivery as delivery
from test_delivery_toc_roles import toc_project  # noqa: F401 — 复用 pytest 夹具

NOTE = 'PDF导出交付说明.md'


class PlaceholderTest(unittest.TestCase):
    """复核备注或登记的用户说明含〔待补时，交付校验报错（路线图 §3 审查重点 5）。"""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='notes-placeholder-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def record(self, note):
        return {'version': 1, 'mode': 'translation', 'delivery_root': str(self.root),
                'inputs': [], 'outputs': [], 'checks': [], 'files': {NOTE: 'user-note'},
                'reviews': [{'kind': 'semantic', 'target': '01_章.md',
                             'status': 'closed', 'note': note}]}

    def problems(self, record, **kwargs):
        problems = []
        delivery.check_reviews(record, problems, root=str(self.root), **kwargs)
        return problems

    def test_review_note_with_placeholder_rejected(self):
        (self.root / NOTE).write_text('结论已写。\n', encoding='utf-8')
        problems = self.problems(self.record('统计……\n- 例外：〔待补：例外与未解决项〕'))
        self.assertIn("复核 '01_章.md' 的备注仍有待补项（含“〔待补”）", problems)
        self.assertFalse(any('交付说明' in p for p in problems))

    def test_user_note_with_placeholder_rejected(self):
        (self.root / NOTE).write_text('- 视觉检查结论：〔待补：视觉检查结论〕\n', encoding='utf-8')
        problems = self.problems(self.record('已逐项核对。'))
        self.assertIn('交付说明 %s 仍有待补项（含“〔待补”）' % NOTE, problems)
        self.assertFalse(any('备注仍有待补项' in p for p in problems))

    def test_translation_readiness_ignores_user_note(self):
        (self.root / NOTE).write_text('〔待补：视觉检查结论〕\n', encoding='utf-8')
        problems = self.problems(self.record('已逐项核对。'), purpose='translation')
        self.assertFalse(any('交付说明' in p for p in problems))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RenderFixture:
    """交付根 + verify_pdf 检查 + work-dir 报告（合成），不启动 Chromium。"""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='render-notes-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        work = self.root / 'evidence/current-export'
        work.mkdir(parents=True)
        (self.root / 'book.pdf').write_bytes(b'%PDF-1.7 fixture')
        (self.root / '01_章.md').write_text('# 章\n', encoding='utf-8')
        self.export = {
            'status': 'machine-pass-pending-visual', 'pdf_sha256': sha256(self.root / 'book.pdf'),
            'image_coverage': {'01_章.md': {'total': 5, 'restored': 3, 'missing': 1,
                                            'no-source-constraint': 1, 'unresolved-size': 0}},
            'katex_macros': {'path': 'm.json', 'sha256': 'x', 'macros': {'\\textsc': '\\text'}},
            'image_adaptations': {'path': 'a.json', 'sha256': 'y', 'images': [{
                'image': str(self.root / 'images/f.svg'), 'sha256': 'z',
                'viewbox': [0, 40, 960, 520], 'display_width_px': 300, 'basis': 'b'}]},
            'range_out_links': [{'href': '02_章.md', 'exists': True}],
            'toc': {'out_links': []},
        }
        self.verify = {
            'status': 'machine-pass-pending-visual', 'pages': 12,
            'relaxed_matches': [{'segment': 'a', 'reason': '标题与长代码块一起移页'},
                                {'segment': 'b', 'reason': '标题与长代码块一起移页'},
                                {'segment': 'c', 'reason': '页文本回退'}],
            'reviews': [{'code': 'code-review', 'message': 'm'}],
            'internal_link_annots': 30, 'external_uri_annots': ['https://a', 'https://b'],
            'unlinked_links': [{'input': '01_章.md', 'links': [{'href': '术语表.md'}]}],
        }
        (work / 'export_report.json').write_text(json.dumps(self.export, ensure_ascii=False))
        (work / 'verify_report.json').write_text(json.dumps(self.verify, ensure_ascii=False))
        self.record = {
            'version': 1, 'mode': 'translation+pdf', 'delivery_root': str(self.root),
            'inputs': ['01_章.md'], 'outputs': [{'path': 'book.pdf', 'sha256': sha256(self.root / 'book.pdf')}],
            'files': {'01_章.md': 'chapter', 'book.pdf': 'pdf'},
            'checks': [{'tool': 'verify_pdf', 'args': [
                '--pdf', 'book.pdf', '--work-dir', 'evidence/current-export', '01_章.md']}],
            'reviews': []}
        self.out = Path(tempfile.mkdtemp(prefix='render-out-'))

    def write_record(self):
        path = self.root / 'docs/record.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.record, ensure_ascii=False))
        return path

    def render(self, kind, output=None, **kwargs):
        output = output or self.out / ('%s.md' % kind)
        return notes.render(self.write_record(), kind, str(output), **kwargs)


class RenderVisualLinkTest(RenderFixture, unittest.TestCase):
    def test_visual_numbers_match_reports(self):
        lines = self.render('visual').splitlines()
        self.assertIn('- 放宽项：3 项（标题与长代码块一起移页 2、页文本回退 1）', lines)
        self.assertIn('- 待复核项：1 项（code-review 1）', lines)
        self.assertIn('- 图片：5 次出现，已恢复 3，未恢复 2（缺映射 1、源无约束 1、尺寸未定 0）', lines)
        self.assertIn('- KaTeX 宏表：\\textsc → \\text', lines)
        self.assertIn('- 图片适配声明：images/f.svg（viewBox 0 40 960 520，显示宽度 300px）', lines)
        self.assertTrue(lines[0].startswith('- 成品：book.pdf（sha256 '))
        self.assertTrue(lines[0].endswith('12 页）；依据：evidence/current-export'))
        self.assertIn('- 视觉检查结论：〔待补：视觉检查结论〕', lines)

    def test_link_numbers_match_reports(self):
        lines = self.render('link').splitlines()
        self.assertIn('- 内部链接注解：30 个', lines)
        self.assertIn('- 外部链接：2 个（去重 URI）', lines)
        self.assertIn('- 目标默认排除、转为纯文本的链接：1 处（术语表.md 1）', lines)
        self.assertIn('- 范围外本地链接：1 处（目标存在 1）', lines)
        self.assertIn('- 范围外链接的处置：〔待补：经用户确认的处置方式〕', lines)

    def test_stale_export_report_refused(self):
        (self.root / 'book.pdf').write_bytes(b'%PDF-1.7 changed')
        with self.assertRaisesRegex(delivery.DeliveryError, '导出报告与当前 PDF 不一致'):
            self.render('visual')

    def test_verify_report_not_machine_pass_refused(self):
        self.verify['status'] = 'machine-fail'
        (self.root / 'evidence/current-export/verify_report.json').write_text(
            json.dumps(self.verify, ensure_ascii=False))
        with self.assertRaisesRegex(delivery.DeliveryError, '核验报告不是机器通过'):
            self.render('visual')

    def test_record_without_verify_pdf_check_refused(self):
        self.record['checks'] = []
        with self.assertRaisesRegex(delivery.DeliveryError, '记录里没有 verify_pdf 检查'):
            self.render('link')

    def test_visual_aid_dependency_error_refused(self):
        # R13：辅助渲染不可用时不能写程序化目检备注
        self.verify['visual_aid'] = {'dependency_error': '缺少 pymupdf'}
        (self.root / 'evidence/current-export/verify_report.json').write_text(
            json.dumps(self.verify, ensure_ascii=False))
        with self.assertRaisesRegex(delivery.DeliveryError, '辅助渲染不可用，不能做程序化目检：缺少 pymupdf'):
            self.render('visual')

    def test_output_rules(self):
        with self.assertRaisesRegex(delivery.DeliveryError, '交付根一级只能写用户说明'):
            self.render('visual', output=self.root / '统计.md')
        with self.assertRaisesRegex(delivery.DeliveryError, '"PDF导出交付说明.md": "user-note"'):
            self.render('visual', output=self.root / NOTE)
        self.assertFalse((self.root / NOTE).exists())
        self.record['files'][NOTE] = 'user-note'
        self.render('visual', output=self.root / NOTE)
        self.assertIn('〔待补：视觉检查结论〕', (self.root / NOTE).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(delivery.DeliveryError, '须是新路径'):
            self.render('visual', output=self.root / NOTE)

    def test_record_is_not_modified(self):
        path = self.write_record()
        before = path.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPTS / 'render_delivery_notes.py'),
                                 '--record', str(path), '--kind', 'link',
                                 '--output', str(self.out / 'cli.md')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), before)


class RenderDeliveryTest(RenderFixture, unittest.TestCase):
    def test_delivery_numbers_match_index(self):
        evidence = self.out / 'evidence'
        evidence.mkdir()
        (evidence / 'delivery_index.json').write_text(json.dumps({
            'mode': 'translation+pdf', 'batch': 'batch-1', 'inputs': self.record['inputs'],
            'outputs': self.record['outputs'],
            'identity': {'inputs': {'01_章.md': 'ab' * 32},
                         'environment': {'python': '3.12.7', 'pypdf': '6.21.4'}},
            'checks': [{'tool': 'verify_reference_translation', 'exit_code': 0},
                       {'tool': 'verify_pdf', 'exit_code': 0}],
            'reviews': [{'kind': 'visual', 'target': 'book.pdf', 'status': 'closed',
                         'items': ['a', 'b']}],
        }, ensure_ascii=False))
        lines = self.render('delivery', evidence_dir=str(evidence)).splitlines()
        self.assertIn('- 输入顺序：1. 01_章.md（sha256 %s…）' % ('ab' * 6), lines)
        self.assertIn('- 检查：1. verify_reference_translation 退出码 0；2. verify_pdf 退出码 0', lines)
        self.assertIn('- 复核：visual book.pdf closed（2 项）', lines)
        self.assertIn('- 依赖版本：pypdf 6.21.4、python 3.12.7', lines)

    def test_index_out_of_date_refused(self):
        evidence = self.out / 'evidence'
        evidence.mkdir()
        (evidence / 'delivery_index.json').write_text(json.dumps({
            'inputs': ['00_目录.md'], 'outputs': self.record['outputs']}))
        with self.assertRaisesRegex(delivery.DeliveryError, '证据索引的输入或输出与交付记录不一致'):
            self.render('delivery', evidence_dir=str(evidence))


def test_files_lists_snapshots_and_outputs(toc_project, tmp_path_factory):
    root, _toc, _manifest, record = toc_project
    (root / 'book.pdf').write_bytes(b'%PDF-1.7 fixture')
    record['outputs'] = [{'path': 'book.pdf', 'sha256': sha256(root / 'book.pdf')}]
    record_path = root / 'source/record.json'
    record_path.write_text(json.dumps(record, ensure_ascii=False))
    output = tmp_path_factory.mktemp('files') / 'files.json'
    payload = json.loads(notes.render(record_path, 'files', str(output)))
    assert payload['sources'] == [{'path': 'source/page.html', 'sha256': sha256(root / 'source/page.html'),
                                   'bytes': (root / 'source/page.html').stat().st_size}]
    assert payload['outputs'] == [{'path': 'book.pdf', 'sha256': sha256(root / 'book.pdf'),
                                   'bytes': len(b'%PDF-1.7 fixture')}]


def test_files_missing_output_refused(toc_project, tmp_path_factory):
    root, _toc, _manifest, record = toc_project
    record['outputs'] = [{'path': 'book.pdf', 'sha256': '0' * 64}]   # 成品不在交付根
    record_path = root / 'source/record.json'
    record_path.write_text(json.dumps(record, ensure_ascii=False))
    output = tmp_path_factory.mktemp('files') / 'files.json'
    with pytest.raises(delivery.DeliveryError, match='清单文件不存在'):
        notes.render(record_path, 'files', str(output))
    assert not output.exists()


if __name__ == '__main__':
    unittest.main()
