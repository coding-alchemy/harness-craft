"""第 2 批 R13：无读图能力时的程序化目检——页脚页码、关键页、备注格式与交付核对。"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))

try:
    import pymupdf as _pymupdf
except ImportError:
    try:
        import fitz as _pymupdf
    except ImportError:
        _pymupdf = None

import verify_delivery as delivery
import verify_pdf as verifier
from test_delivery_notes import RenderFixture


def aid_pages(total, **flags):
    """合成 visual_aid.pages：flags 形如 blank=[3], footer_bad=[4], failed=[5]。"""
    return [{'page': n, 'render_ok': n not in flags.get('failed', []),
             'blank_suspect': n in flags.get('blank', []),
             'footer_ok': n not in flags.get('footer_bad', [])} for n in range(1, total + 1)]


def chapter(name):
    return SimpleNamespace(path=Path('/tmp/book') / name)


@unittest.skipUnless(_pymupdf is not None, '辅助渲染依赖 PyMuPDF 不可用')
class FooterAidTest(unittest.TestCase):
    def build(self, footers):
        temp = tempfile.TemporaryDirectory(prefix='aid-footer-')
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'footer.pdf'
        doc = _pymupdf.open()
        for text in footers:
            page = doc.new_page()
            page.insert_text((72, 72), 'Body text.', fontsize=12)
            page.insert_text((page.rect.width / 2 - 10, page.rect.height - 20), text, fontsize=8)
        doc.save(str(path))
        doc.close()
        return verifier.collect_visual_aid(path)

    def test_footer_numbers_checked_per_page(self):
        aid = self.build(['1 / 3', '2 / 3', '3 / 3'])
        self.assertEqual([entry['footer_ok'] for entry in aid['pages']], [True, True, True])
        self.assertEqual(aid['summary']['footer_anomalies'], [])

    def test_wrong_or_missing_footer_is_anomaly(self):
        aid = self.build(['1 / 3', '2 / 4', ''])
        self.assertEqual(aid['summary']['footer_anomalies'], [2, 3])
        self.assertEqual(aid['pages'][1]['footer_text'], '2 / 4')


class KeyPagesTest(unittest.TestCase):
    """路线图 §3 审查重点 4：没有目录的单篇论文；几百页的书合并成区间。"""

    def test_single_paper_without_toc(self):
        aid = {'pages': aid_pages(9, blank=[4], footer_bad=[6], failed=[7])}
        relaxed = [{'segment': 'a', 'reason': 'r', 'page': 3}, {'segment': 'b', 'reason': 'r'}]
        reviews = [{'code': 'code-page-gap-review', 'page': 3}]
        pages = verifier.visual_key_pages(aid, [(chapter('paper.md'), 0, 9)], relaxed, reviews)
        self.assertEqual(pages, [
            {'first': 1, 'last': 1, 'reasons': ['首页', '章首（paper.md）']},
            {'first': 3, 'last': 3, 'reasons': ['relaxed_matches#1', 'reviews#1']},
            {'first': 4, 'last': 4, 'reasons': ['疑似空白页']},
            {'first': 6, 'last': 6, 'reasons': ['页脚异常']},
            {'first': 7, 'last': 7, 'reasons': ['渲染失败']},
            {'first': 9, 'last': 9, 'reasons': ['末页']},
        ])
        self.assertFalse(any('目录' in reason for item in pages for reason in item['reasons']))

    def test_long_book_merges_toc_pages(self):
        aid = {'pages': aid_pages(400)}
        bounds = [(chapter('00_目录.md'), 1, 6)] + [
            (chapter('%02d_章.md' % n), 6 + (n - 1) * 39, 6 + n * 39) for n in range(1, 11)]
        pages = verifier.visual_key_pages(aid, bounds, [], [])
        self.assertEqual(pages[1], {'first': 2, 'last': 6, 'reasons': ['目录']})
        self.assertEqual(len(pages), 1 + 1 + 10 + 1)
        self.assertEqual(pages[-1], {'first': 400, 'last': 400, 'reasons': ['末页']})


class PageFieldTest(unittest.TestCase):
    def test_code_gap_review_without_line_height_records_page(self):
        from bs4 import BeautifulSoup
        code = '\n'.join('line %d' % n for n in range(1, 16))
        html = '<div><p>Title</p><div class="code-block"><pre>%s</pre></div></div>' % code
        ch = SimpleNamespace(path=Path('/tmp/gap.md'), code_blocks=[code],
                             soup=BeautifulSoup(html, 'html.parser'))
        pdf = SimpleNamespace(line_buckets=[
            {'page': 0, 'text': '前文。', 'baseline_y_pt': 200.0},
            {'page': 1, 'text': 'line 1', 'baseline_y_pt': 760.0}])
        infos = {str(ch.path): [{'long': True, 'first_page': 1, 'last_page': 1,
                                 'first_baseline_pt': 760.0, 'line_height_pt': None}]}
        failures, reviews, relaxed = [], [], []
        with patch.object(verifier, 'collect_drawn_images', return_value=[[], []]):
            verifier.check_code_pagination([ch], pdf, [(ch, 0, 2)], failures, reviews, infos, relaxed)
        self.assertEqual([(r['code'], r['page']) for r in reviews], [('code-page-gap-review', 2)])


@unittest.skipUnless(_pymupdf is not None, '辅助渲染依赖 PyMuPDF 不可用')
class RealExportKeyPagesTest(unittest.TestCase):
    """真实导出 + 核验：关键页与页脚核对进入同次核验报告。"""

    def test_single_page_export(self):
        import export_pdf as exporter
        with tempfile.TemporaryDirectory(prefix='key-pages-e2e-') as temp:
            root = Path(temp)
            doc = root / 'chapter.md'
            doc.write_text('# 关键页\n\n> **来源**：https://example.com/key-pages\n\n正文段落。\n',
                           encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(exporter.export([str(doc)], root / 'book.pdf', root / 'work'), 0)
            ok, report = verifier.run_verification(verifier.parse_args(
                ['--pdf', str(root / 'book.pdf'), '--work-dir', str(root / 'work'),
                 '--visual-aid', str(doc)]))
        self.assertTrue(ok, report['failures'])
        aid = report['visual_aid']
        self.assertEqual(aid['summary']['footer_anomalies'], [])
        self.assertEqual(aid['key_pages'], [
            {'first': 1, 'last': 1, 'reasons': ['首页', '章首（chapter.md）', '末页']}])


class CheckFactsVisualAidTest(unittest.TestCase):
    def test_visual_aid_param_only_when_enabled(self):
        with tempfile.TemporaryDirectory(prefix='facts-aid-') as temp:
            args = ['--pdf', 'book.pdf', '--work-dir', 'work', '01_章.md']
            plain, _ = delivery._check_facts(temp, 'verify_pdf', args, 1, [])
            aided, _ = delivery._check_facts(
                temp, 'verify_pdf', args[:4] + ['--visual-aid'] + args[4:], 1, [])
        self.assertNotIn('visual_aid', plain['params'])
        self.assertEqual(aided['params'], dict(plain['params'], visual_aid=True))


class ProgrammaticReviewCheckTest(unittest.TestCase):
    NOTE = ('【程序化目检】会话与子代理均无读图能力，未做逐页人眼目检。\n'
            '最少检查：3 页渲染成功；疑似空白页 无；页脚页码 1/3 至 3/3 连续；导出与 PDF 机器核验通过。\n'
            '关键页：p1（首页、章首（01_章.md））、p3（末页）\n'
            '用户抽查：%s')

    def problems(self, note, visual_aid=True):
        with tempfile.TemporaryDirectory(prefix='prog-review-') as temp:
            root = Path(temp)
            pdf = str((root / 'book.pdf').resolve())
            params = {'toc_sections': False, 'require_display_map': False}
            if visual_aid:
                params['visual_aid'] = True
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': temp, 'inputs': [],
                      'outputs': [{'path': 'book.pdf', 'sha256': 'x'}], 'checks': [],
                      'reviews': [{'kind': 'visual', 'target': 'book.pdf', 'status': 'closed',
                                   'sha256': 'x', 'note': note}]}
            problems = []
            delivery.check_reviews(record, problems, root=temp,
                                   pdf_checks={pdf: [{'order': 1, 'facts': {'params': params}}]})
        return [p for p in problems if '程序化目检' in p or '待补' in p]

    def test_user_conclusion_written_passes_these_checks(self):
        self.assertEqual(self.problems(self.NOTE % '2026-11-18 用户抽查 p1、p3，版面正常'), [])

    def test_placeholder_or_empty_user_line_rejected(self):
        self.assertIn("复核 'book.pdf' 的备注仍有待补项（含“〔待补”）",
                      self.problems(self.NOTE % '〔待补：用户抽查的页码、日期与结论〕'))
        self.assertIn("复核 'book.pdf' 标为【程序化目检】，缺少写明用户抽查结论的“用户抽查：”行",
                      self.problems(self.NOTE % ''))

    def test_check_without_visual_aid_rejected(self):
        self.assertEqual(
            self.problems(self.NOTE % '2026-11-18 用户抽查 p1，正常', visual_aid=False),
            ["复核 'book.pdf' 标为【程序化目检】，但覆盖该成品的 verify_pdf 检查没有启用 --visual-aid"])


class RenderProgrammaticTest(RenderFixture, unittest.TestCase):
    def test_visual_note_starts_with_programmatic_block(self):
        self.verify['visual_aid'] = {
            'pages': aid_pages(12, blank=[7]),
            'summary': {'pages': 12, 'render_failed': [], 'blank_suspects': [7],
                        'footer_anomalies': []},
            'key_pages': [{'first': 1, 'last': 1, 'reasons': ['首页', '章首（01_章.md）']},
                          {'first': 7, 'last': 7, 'reasons': ['疑似空白页']},
                          {'first': 12, 'last': 12, 'reasons': ['末页']}]}
        (self.root / 'evidence/current-export/verify_report.json').write_text(
            json.dumps(self.verify, ensure_ascii=False))
        lines = self.render('visual').splitlines()
        self.assertEqual(lines[:4], [
            '【程序化目检】会话与子代理均无读图能力，未做逐页人眼目检。',
            '最少检查：12 页渲染成功；疑似空白页 p7；页脚页码 1/12 至 12/12 连续；导出与 PDF 机器核验通过。',
            '关键页：p1（首页、章首（01_章.md））、p7（疑似空白页）、p12（末页）',
            '用户抽查：〔待补：用户抽查的页码、日期与结论〕'])
        self.assertIn('- 放宽项：3 项（标题与长代码块一起移页 2、页文本回退 1）', lines)

    def test_visual_note_without_aid_has_no_block(self):
        self.assertFalse(self.render('visual').startswith('【程序化目检】'))


if __name__ == '__main__':
    unittest.main()
