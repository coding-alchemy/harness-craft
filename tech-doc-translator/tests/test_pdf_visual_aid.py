"""无图像输入时的逐页辅助检查验收（PDF 源翻译 R8/A8，设计 §4.8）。

真实多页 PDF 在临时目录用 PyMuPDF 生成，逐页断言三类统计与疑似空白
定位；渲染失败与依赖缺失必须明确报告缺口；统计在任何文案中都不被
表述为无缺字/重叠/裁切的证明，也不构成视觉复核——verify_delivery 在
无真实视觉复核时仍拒绝完成。PyMuPDF 缺失时整组明确 skip；未启用
--visual-aid 的普通核验路径回归不受影响。
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))

try:
    import pymupdf as _pymupdf
except ImportError:
    try:
        import fitz as _pymupdf
    except ImportError:
        _pymupdf = None

import verify_pdf as verifier
import verify_delivery as delivery_verifier


@unittest.skipUnless(_pymupdf is not None, "辅助渲染依赖 PyMuPDF 不可用")
class VisualAidStatisticsTest(unittest.TestCase):
    """逐页统计单元验收：真实多页 PDF，临时目录生成。"""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='visual-aid-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.pdf = cls.root / 'multipage.pdf'
        cls.build_multipage_pdf(cls.pdf)

    @staticmethod
    def build_multipage_pdf(path):
        """三页样例：第 1 页正文；第 2 页空白（疑似空白定位对象）；
        第 3 页含一个图片对象与内部/外部链接注解。"""
        doc = _pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Chapter body text.", fontsize=12)
        doc.new_page()  # 空白页
        page3 = doc.new_page()
        rect = _pymupdf.Rect(72, 72, 140, 140)
        pixmap = _pymupdf.Pixmap(_pymupdf.csRGB, _pymupdf.IRect(0, 0, 8, 8))
        pixmap.clear_with(120)
        page3.insert_image(rect, pixmap=pixmap)
        page3.insert_link(
            {"kind": _pymupdf.LINK_GOTO, "from": rect, "page": 0})
        page3.insert_link(
            {"kind": _pymupdf.LINK_URI, "from": rect,
             "uri": "https://example.com/docs"})
        doc.save(str(path))
        doc.close()

    def test_three_statistics_per_page_and_blank_located(self):
        aid = verifier.collect_visual_aid(
            self.pdf, dpi=96, blank_threshold=0.0001)
        # 渲染参数与覆盖率定义写入报告。
        self.assertEqual(aid["dpi"], 96)
        self.assertEqual(aid["blank_threshold"], 0.0001)
        self.assertIn("像素占比", aid["ink_definition"])
        self.assertTrue(aid["renderer"].startswith("PyMuPDF"))
        self.assertNotIn("dependency_error", aid)
        self.assertEqual(len(aid["pages"]), 3)
        first, blank, rich = aid["pages"]
        # 第 1 页：渲染成功、有墨迹、无图片对象、无链接。
        self.assertTrue(first["render_ok"])
        self.assertGreater(first["ink_coverage"], 0.0001)
        self.assertEqual(first["image_objects"], 0)
        self.assertEqual(first["link_targets"], [])
        self.assertFalse(first["blank_suspect"])
        # 第 2 页：疑似空白页被定位。
        self.assertTrue(blank["render_ok"])
        self.assertLess(blank["ink_coverage"], 0.0001)
        self.assertTrue(blank["blank_suspect"])
        # 第 3 页：图片对象数与链接注解目标。
        self.assertEqual(rich["image_objects"], 1)
        targets = rich["link_targets"]
        self.assertIn({"type": "internal", "page": 1}, targets)
        self.assertIn({"type": "external",
                       "uri": "https://example.com/docs"}, targets)
        self.assertEqual(aid["summary"]["blank_suspects"], [2])
        self.assertEqual(aid["summary"]["render_failed"], [])

    def test_report_marks_statistics_as_aid_only(self):
        aid = verifier.collect_visual_aid(self.pdf)
        self.assertIn("仅定位线索", aid["purpose"])
        self.assertIn("仅作定位线索", aid["disclaimer"])
        self.assertIn("不构成", aid["disclaimer"])
        self.assertIn("视觉复核", aid["disclaimer"])
        # 报告不得出现任何视觉复核通过类结论。
        self.assertNotIn("视觉复核通过", json.dumps(aid, ensure_ascii=False))

    def test_render_failure_reports_gap_per_page(self):
        real = verifier._render_page_ink_coverage

        def flaky(page, renderer, dpi):
            if page.number == 1:
                raise RuntimeError("simulated render crash")
            return real(page, renderer, dpi)

        with unittest.mock.patch.object(
                verifier, "_render_page_ink_coverage", side_effect=flaky):
            aid = verifier.collect_visual_aid(self.pdf)
        blank = aid["pages"][1]
        self.assertFalse(blank["render_ok"])
        self.assertIn("渲染失败", blank["render_gap"])
        self.assertIsNone(blank["ink_coverage"])
        self.assertFalse(blank["blank_suspect"])  # 未渲染不得误判空白
        # 其余页照常统计。
        self.assertTrue(aid["pages"][0]["render_ok"])
        self.assertTrue(aid["pages"][2]["render_ok"])
        self.assertEqual(aid["summary"]["render_failed"], [2])

    def test_missing_dependency_reports_gap_without_install(self):
        with unittest.mock.patch.object(
                verifier, "_load_aid_renderer", return_value=None):
            aid = verifier.collect_visual_aid(self.pdf)
        self.assertIn("dependency_error", aid)
        self.assertIn("不自动安装", aid["dependency_error"])
        self.assertEqual(aid["pages"], [])
        # 缺口声明仍须保留辅助口径，不得退化为通过结论。
        self.assertIn("仅定位线索", aid["purpose"])


class VisualAidVerificationReportTest(unittest.TestCase):
    """真实导出 + 核验：辅助统计进入同次核验报告，机器结论不受影响，
    交付门禁不被辅助统计绕过。"""

    HEAD = '# 辅助章\n\n> **来源**：https://example.com/visual-aid\n\n正文段落。\n'

    @classmethod
    def setUpClass(cls):
        import export_pdf as exporter
        cls.exporter = exporter
        cls.temporary = tempfile.TemporaryDirectory(prefix='visual-aid-e2e-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.chapter = cls.root / 'chapter.md'
        cls.chapter.write_text(cls.HEAD, encoding='utf-8')
        cls.pdf = cls.root / 'book.pdf'
        cls.work = cls.root / 'work'
        with contextlib.redirect_stdout(io.StringIO()):
            result = exporter.export([str(cls.chapter)], cls.pdf, cls.work)
        if result:
            raise AssertionError(
                (cls.work / exporter.REPORT_NAME).read_text(encoding='utf-8'))

    def verify(self, extra=()):
        args = verifier.parse_args(
            ['--pdf', str(self.pdf), '--work-dir', str(self.work),
             *extra, str(self.chapter)])
        return verifier.run_verification(args)

    def test_aid_statistics_enter_verify_report(self):
        ok, report = self.verify(['--visual-aid'])
        self.assertTrue(ok, report['failures'])
        aid = report.get('visual_aid')
        self.assertIsNotNone(aid)
        self.assertEqual(aid['disclaimer'], verifier.VISUAL_AID_DISCLAIMER)
        self.assertEqual(aid['dpi'], verifier.VISUAL_AID_DEFAULT_DPI)
        self.assertEqual(aid['blank_threshold'],
                         verifier.VISUAL_AID_DEFAULT_BLANK_THRESHOLD)
        self.assertEqual(len(aid['pages']), report['pages'])
        for entry in aid['pages']:
            self.assertTrue(entry['render_ok'], entry)
            self.assertIsNotNone(entry['ink_coverage'], entry)
        # 统计正常时无辅助缺口项，且报告整体不出现视觉复核通过表述。
        self.assertFalse(
            [r for r in report['reviews']
             if r['code'].startswith('visual-aid')])
        self.assertNotIn("视觉复核通过",
                         json.dumps(report, ensure_ascii=False))

    def test_aid_does_not_change_machine_result(self):
        ok, report = self.verify(['--visual-aid'])
        ok_plain, report_plain = self.verify()
        self.assertTrue(ok_plain, report_plain['failures'])
        # 未启用辅助选项时核验报告不含辅助节（回归：普通路径原行为）。
        self.assertNotIn('visual_aid', report_plain)
        # 机器结论与失败集不受辅助统计影响。
        self.assertEqual(ok, ok_plain)
        self.assertEqual(report['failures'], report_plain['failures'])

    def test_render_failure_enters_reviews_as_gap(self):
        def crash(page, renderer, dpi):
            raise RuntimeError("simulated render crash")

        with unittest.mock.patch.object(
                verifier, "_render_page_ink_coverage", side_effect=crash):
            ok, report = self.verify(['--visual-aid'])
        self.assertTrue(ok, report['failures'])
        failed = [r for r in report['reviews']
                  if r['code'] == 'visual-aid-render-failed']
        self.assertEqual(len(failed), len(report['visual_aid']['pages']))
        self.assertIn("缺口交人工视觉复核", failed[0]['message'])

    def test_delivery_gate_rejects_completion_without_visual_review(self):
        # 即使辅助统计正常（见 test_aid_statistics_enter_verify_report），
        # 无绑定成品摘要的闭合视觉复核时，交付检查仍拒绝完成。
        problems = []
        record = {
            'mode': 'pdf',
            'inputs': [],
            'outputs': [{'path': 'book.pdf', 'sha256': '0' * 64}],
            'reviews': [],
        }
        delivery_verifier.check_reviews(
            record, problems, None, root=str(self.root))
        self.assertTrue(
            any("视觉复核" in problem for problem in problems),
            problems)


if __name__ == '__main__':
    unittest.main()
