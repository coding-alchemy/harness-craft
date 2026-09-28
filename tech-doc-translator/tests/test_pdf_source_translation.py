"""译文机器硬检查（权威标题/代码/图片身份/脚注覆盖/强 token/R5）验收。"""
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
    raise unittest.SkipTest("PyMuPDF 不可用，整组 PDF 源译文检查测试跳过")

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
PREPARE = SCRIPTS / 'prepare_pdf_source.py'
VERIFY = SCRIPTS / 'verify_pdf_source.py'
SPLICE = SCRIPTS / 'splice_fences.py'

CODE = ["def run():", "    return 44  # ms timer"]


def run_cli(script, *args):
    return subprocess.run([sys.executable, str(script)]
                          + [str(a) for a in args],
                          capture_output=True, text=True)


def draw_chart(page, labels):
    base = pymupdf.Point(60, 160)
    for i, label in enumerate(labels[:2]):
        rect = pymupdf.Rect(base.x + i * 45, base.y - 50 - i * 15,
                            base.x + i * 45 + 30, base.y)
        page.draw_rect(rect, fill=(0.7, 0.7, 0.9))
        page.insert_text((rect.x0 + 8, base.y + 12), label, fontsize=8)
    page.draw_line(pymupdf.Point(50, base.y), pymupdf.Point(200, base.y),
                   color=(0,))
    page.insert_text((70, 50), labels[2], fontsize=8)


class PdfSourceTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root

        doc = pymupdf.open()
        page = doc.new_page(width=500, height=400)
        page.insert_text((40, 50), "1 Intro", fontsize=14)
        page.insert_text(
            (40, 80),
            "The system runs in 44 ms and uses 9% memory overall.",
            fontsize=10)
        y = 110
        for line in CODE:
            page.insert_text((60, y), line, fontsize=10, fontname="courier")
            y += 14
        draw_chart(page, ["Batch A", "Batch B", "series one"])
        page.insert_text((40, 330), "1Details of the timer mechanism.",
                         fontsize=8)
        doc.new_page(width=500, height=400)
        draw_chart(doc[1], ["Run X", "Run Y", "series two"])
        doc.save(root / 'paper.pdf')
        doc.close()
        cls.pdf = root / 'paper.pdf'

        cls.inspect_dir = root / 'inspect'
        result = run_cli(PREPARE, 'inspect', cls.pdf, '--pages', 'all',
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.checklist = cls.inspect_dir / 'adjudication_checklist.json'
        payload = json.loads(cls.checklist.read_text(encoding='utf-8'))
        payload['blocks'] = [
            {'id': 'b001', 'order': 1, 'type': 'heading', 'page': 1,
             'rect': [38, 40, 200, 55], 'level': 2, 'text': '1 Intro',
             'adjudication': {'status': 'accepted', 'basis': '编号+字号'}},
            {'id': 'b002', 'order': 2, 'type': 'paragraph', 'page': 1,
             'rect': [38, 70, 460, 90],
             'adjudication': {'status': 'accepted', 'basis': '正文'}},
            {'id': 'b003', 'order': 3, 'type': 'code_region', 'page': 1,
             'rect': [50, 100, 400, 135], 'golden': 'golden/code.txt',
             'lang': 'python',
             'adjudication': {'status': 'accepted', 'basis': '代码区'}},
            {'id': 'b004', 'order': 4, 'type': 'figure_region', 'page': 1,
             'rect': [40, 40, 220, 190], 'image': 'images/chart_a.png',
             'label': '图 A',
             'adjudication': {'status': 'accepted', 'basis': '图 A'}},
            {'id': 'b005', 'order': 5, 'type': 'paragraph', 'page': 1,
             'rect': [38, 322, 400, 335], 'footnote_label': '1',
             'adjudication': {'status': 'accepted', 'basis': '脚注 1'}},
            {'id': 'b006', 'order': 6, 'type': 'figure_region', 'page': 2,
             'rect': [40, 40, 220, 190], 'image': 'images/chart_b.png',
             'label': '图 B',
             'adjudication': {'status': 'accepted', 'basis': '图 B'}},
        ]
        payload['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        payload['conventions']['strong_tokens'] = ["44 ms", "9%", "run"]
        payload['conventions']['defects'] = [{
            "kind": "url-text-layer",
            "extracted": "fxconvbnfuser.html",
            "evidence": "https://pytorch.org/tutorials/intermediate/"
                        "fx_conv_bn_fuser.html",
            "adjudicated": "https://pytorch.org/tutorials/intermediate/"
                           "fx_conv_bn_fuser.html",
            "note": "文本层丢失下划线，以 PDF 内嵌链接目标为权威回退，"
                    "译文须加译注"}]
        cls.checklist.write_text(json.dumps(payload, ensure_ascii=False),
                                 encoding='utf-8')
        result = run_cli(PREPARE, 'extract-code', cls.pdf,
                         '--checklist', cls.checklist,
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        result = run_cli(PREPARE, 'extract-figures', cls.pdf,
                         '--checklist', cls.checklist,
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.md = root / 'source_draft.md'
        result = run_cli(PREPARE, 'materialize', cls.pdf,
                         '--checklist', cls.checklist, '--output', cls.md)
        assert result.returncode == 0, result.stderr

        # 模拟译文：正文改写、围栏 ⟦CODE⟧ 占位后程序化回填
        draft = ("## 1 Intro（引言）\n"
                 "\n"
                 "【译文】系统运行耗时 44 ms，占用 9% 内存。\n"
                 "\n"
                 "⟦CODE⟧\n"
                 "\n"
                 "![图 A](inspect/images/chart_a.png)\n"
                 "\n"
                 "正文带脚注引用[^1]，并见教程 fx_conv_bn_fuser 链接："
                 "[教程](https://pytorch.org/tutorials/intermediate/"
                 "fx_conv_bn_fuser.html)。【译注：原文该 URL 文本层丢失"
                 "下划线，依 PDF 内嵌链接目标还原】\n"
                 "\n"
                 "![图 B](inspect/images/chart_b.png)\n"
                 "\n"
                 "[^1]: 计时器细节说明。（译注）\n")
        draft_path = root / 'draft_zh.md'
        draft_path.write_text(draft, encoding='utf-8')
        cls.translation = root / 'translation_zh.md'
        result = run_cli(SPLICE, draft_path, cls.md, cls.translation)
        assert result.returncode == 0, result.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verify(self, translation=None, checklist=None):
        return run_cli(VERIFY, self.pdf,
                       '--checklist', checklist or self.checklist,
                       '--source-md', self.md,
                       '--translation', translation or self.translation)

    def test_translation_passes_all_hard_checks(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('译文硬检查通过', result.stdout)
        self.assertIn('人工语义复核: 未登记', result.stdout)

    def _damaged(self, name, transform):
        damaged = self.root / name
        shutil.copyfile(self.translation, damaged)
        lines = damaged.read_text(encoding='utf-8').split('\n')
        transform(lines)
        damaged.write_text('\n'.join(lines), encoding='utf-8')
        return self.verify(translation=damaged)

    def test_deleted_heading_fails(self):
        result = self._damaged(
            'd_head.md',
            lambda ls: ls.__delitem__(next(i for i, ln in enumerate(ls)
                                          if ln.startswith('## '))))
        self.assertEqual(result.returncode, 1)
        self.assertIn('标题数不一致', result.stderr)

    def test_changed_heading_level_fails(self):
        result = self._damaged(
            'd_level.md',
            lambda ls: ls.__setitem__(
                next(i for i, ln in enumerate(ls) if ln.startswith('## ')),
                '### 1 Intro（引言）'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('层级不一致', result.stderr)

    def test_removed_english_title_fails(self):
        result = self._damaged(
            'd_en.md',
            lambda ls: ls.__setitem__(
                next(i for i, ln in enumerate(ls) if ln.startswith('## ')),
                '## 引言'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('标题 #1 不一致', result.stderr)

    def test_missing_image_fails(self):
        result = self._damaged(
            'd_img.md',
            lambda ls: ls.__delitem__(next(i for i, ln in enumerate(ls)
                                           if 'chart_a.png' in ln)))
        self.assertEqual(result.returncode, 1)
        self.assertIn('图片出现 1 次 vs 权威清单 2 次', result.stderr)

    def test_same_name_swap_and_order_fail(self):
        target = self.inspect_dir / 'images/chart_a.png'
        original = target.read_bytes()
        try:
            target.write_bytes((self.inspect_dir / 'images/chart_b.png')
                               .read_bytes())
            result = self._damaged('d_swap.md', lambda ls: None)
            self.assertEqual(result.returncode, 1)
            self.assertIn('同名换图', result.stderr)
        finally:
            target.write_bytes(original)

        def reorder(ls):
            a = next(i for i, ln in enumerate(ls) if 'chart_a.png' in ln)
            b = next(i for i, ln in enumerate(ls) if 'chart_b.png' in ln)
            ls[a], ls[b] = ls[b], ls[a]
        result = self._damaged('d_order.md', reorder)
        self.assertEqual(result.returncode, 1)
        self.assertIn('同名换图/乱序', result.stderr)

    def test_footnote_pair_deletion_fails(self):
        def drop_pair(ls):
            keep = [ln for ln in ls if '[^1]' not in ln]
            ls[:] = keep
        result = self._damaged('d_fn.md', drop_pair)
        self.assertEqual(result.returncode, 1)
        self.assertIn('脚注 [^1] 引用缺失', result.stderr)
        self.assertIn('脚注 [^1] 定义缺失', result.stderr)

    def test_footnote_def_missing_fails(self):
        def drop_def(ls):
            ls[:] = [ln for ln in ls if not ln.startswith('[^1]:')]
        result = self._damaged('d_fndef.md', drop_def)
        self.assertEqual(result.returncode, 1)
        self.assertIn('定义缺失', result.stderr)

    def test_strong_token_missing_fails(self):
        result = self._damaged(
            'd_tok.md',
            lambda ls: ls.__setitem__(
                next(i for i, ln in enumerate(ls) if '44 ms' in ln),
                ls[next(i for i, ln in enumerate(ls)
                        if '44 ms' in ln)].replace('44 ms', '45 ms')))
        self.assertEqual(result.returncode, 1)
        self.assertIn('强 token', result.stderr)

    def test_r5_adjudicated_value_missing_fails(self):
        result = self._damaged(
            'd_r5.md',
            lambda ls: ls.__setitem__(
                next(i for i, ln in enumerate(ls) if 'fx_conv_bn_fuser' in ln),
                '【译文】无链接段落。'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('R5 裁决值未落实', result.stderr)

    def test_unconfigured_strong_tokens_report_not_checked(self):
        payload = json.loads(self.checklist.read_text(encoding='utf-8'))
        payload['conventions']['strong_tokens'] = []
        checklist = self.inspect_dir / 'checklist_no_tokens.json'
        checklist.write_text(json.dumps(payload, ensure_ascii=False),
                             encoding='utf-8')
        result = self.verify(checklist=checklist)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('强 token: 未配置项目指定 token，此项未检查',
                      result.stderr + result.stdout)




if __name__ == '__main__':
    unittest.main()
