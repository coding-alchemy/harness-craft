"""真实 PDF 固定验收：章节隔离、无标题章节、组合语法及损坏检测。"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject


def make_png(path, w, h, color=b'\x01\x02\x03'):
    import struct
    import zlib
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + color * w for _ in range(h))
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter
import verify_pdf as verifier


class PdfStyleGeometryContractTest(unittest.TestCase):
    def test_verifier_geometry_matches_pdf_stylesheet(self):
        """页界证据必须绑定真实 CSS，不能靠已漂移的裸常量。"""
        style = (Path(__file__).resolve().parents[1]
                 / 'skills/tech-doc-translator/assets/pdf/style.css').read_text()
        page = re.search(r'@page\s*\{([^}]*)\}', style, re.DOTALL).group(1)
        pre = re.search(r'(?m)^pre\s*\{([^}]*)\}', style, re.DOTALL).group(1)
        margin = re.search(r'margin:\s*([0-9.]+)mm\s+([0-9.]+)mm', page)
        padding = re.search(r'padding:\s*([0-9.]+)pt\s+([0-9.]+)pt', pre)
        line_height = re.search(r'line-height:\s*([0-9.]+)', pre)
        self.assertIsNotNone(margin)
        self.assertIsNotNone(padding)
        self.assertIsNotNone(line_height)
        self.assertAlmostEqual(
            verifier.PDF_PAGE_MARGIN_VERTICAL_PT,
            float(margin.group(1)) * verifier.MM_TO_PT)
        self.assertAlmostEqual(
            verifier.PDF_PAGE_MARGIN_HORIZONTAL_PT,
            float(margin.group(2)) * verifier.MM_TO_PT)
        self.assertEqual(verifier.PDF_PRE_PADDING_VERTICAL_PT,
                         float(padding.group(1)))
        self.assertEqual(verifier.PDF_PRE_PADDING_HORIZONTAL_PT,
                         float(padding.group(2)))
        self.assertEqual(verifier.PDF_PRE_LINE_HEIGHT,
                         float(line_height.group(1)))
        # 短块超页预检的打印版心宽度同样绑定 @page（A4 宽 210mm）。
        self.assertEqual(
            exporter.PRINT_CONTENT_WIDTH_PX,
            round((210 - float(margin.group(2)) * 2) / 25.4 * 96))


class PdfIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='pdf-integrity-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.work = cls.root / 'work'
        cls.pdf = cls.root / 'book.pdf'
        image = Path(__file__).parent / 'fixtures/valid_1x1.png'
        # 默认出处门禁（R6/D6）要求每章可定位具体原文：样例章补足
        # 可定位来源，不改变被检验的正文/资源语义。
        head = ('> **来源**：https://example.com/source?page=%d\n'
                '> **抓取日期**：2026-09-15\n\n')
        sources = [
            '# A\n\n' + head % 1 + 'Intro.\n\n```text\nSame paragraph.\n```\n',
            head % 2 + 'Same paragraph.\n',
            head % 3 + '```text\nSame paragraph.\n```\n',
            head % 4 + '$$x^2 + y^2 = 1$$\n',
            head % 5 + '![Diagram](%s)\n' % image,
            head % 6 + '####### <a id="custom"></a>Use [docs][r] and `foo` $x^2$[^n]\n\n'
            '[go](#custom)\n\n[r]: https://example.com/docs\n\n[^n]: Required note.\n',
        ]
        cls.inputs = []
        for index, source in enumerate(sources):
            path = cls.root / ('chapter%d.md' % index)
            path.write_text(source)
            cls.inputs.append(str(path))
        with contextlib.redirect_stdout(io.StringIO()):
            result = exporter.export(cls.inputs, cls.pdf, cls.work)
        if result:
            raise AssertionError((cls.work / exporter.REPORT_NAME).read_text())
        cls.evidence = (cls.work / exporter.REPORT_NAME).read_text()

    def verify(self, path, inputs=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = verifier.main(['--pdf', str(path), '--work-dir', str(self.work),
                                    *(inputs if inputs is not None else self.inputs)])
        report = json.loads((self.work / verifier.VERIFY_NAME).read_text())
        return result, {item['code'] for item in report['failures']}

    def setUp(self):
        (self.work / exporter.REPORT_NAME).write_text(self.evidence)

    def test_complete_book_and_exact_chapter_boundaries(self):
        result, codes = self.verify(self.pdf)
        self.assertEqual((result, codes), (0, set()))
        failures = []
        chapters = verifier.reparse_inputs(self.inputs, failures)
        bounds = verifier.chapter_bounds(chapters, verifier.PdfFacts(self.pdf), {}, failures)
        self.assertEqual(failures, [])
        self.assertEqual([(start, end) for _, start, end in bounds],
                         [(i, i + 1) for i in range(6)])

    def test_blank_chapter_cannot_borrow_previous_code_even_with_matching_digest(self):
        writer = PdfWriter(clone_from=self.pdf)
        stream = DecodedStreamObject()
        stream.set_data(b'')
        writer.pages[1][NameObject('/Contents')] = writer._add_object(stream)
        path = self.root / 'blank.pdf'
        writer.write(path)
        # 更新摘要以单独检验内容隔离，防止测试只依赖摘要拒绝损坏文件。
        report = json.loads(self.evidence)
        report['pdf_sha256'] = exporter.sha256_file(path)
        (self.work / exporter.REPORT_NAME).write_text(json.dumps(report))
        result, codes = self.verify(path)
        self.assertEqual(result, 1)
        self.assertIn('text-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_damage_and_old_render_evidence_rejected(self):
        for page_index in (2, 3, 4):
            with self.subTest(page=page_index):
                writer = PdfWriter(clone_from=self.pdf)
                stream = DecodedStreamObject()
                stream.set_data(b'')
                writer.pages[page_index][NameObject('/Contents')] = writer._add_object(stream)
                path = self.root / ('blank%d.pdf' % page_index)
                writer.write(path)
                result, codes = self.verify(path)
                self.assertEqual(result, 1)
                self.assertIn('pdf-evidence-mismatch', codes)

    def test_deleted_reordered_and_duplicated_pages_rejected(self):
        for order in ([0, 2, 3, 4, 5], [1, 0, 2, 3, 4, 5], [0, 0, 2, 3, 4, 5]):
            with self.subTest(order=order):
                writer = PdfWriter()
                reader = verifier.PdfFacts(self.pdf).reader
                for index in order:
                    writer.add_page(reader.pages[index])
                path = self.root / 'reordered.pdf'
                writer.write(path)
                result, codes = self.verify(path)
                self.assertEqual(result, 1)
                self.assertIn('chapter-structure', codes)

    def test_input_order_bound_to_evidence(self):
        result, codes = self.verify(self.pdf, list(reversed(self.inputs)))
        self.assertEqual(result, 1)
        self.assertIn('input-order-mismatch', codes)

    def test_subheading_same_as_next_chapter_title(self):
        paths = []
        head = '> **来源**：https://example.com/source?page=%s\n\n'
        for name, source in [
            ('a', '# A\n\n' + head % 'a' + '## B\n\nFirst.'),
            ('b', '# B\n\n' + head % 'b' + 'Second.'),
        ]:
            path = self.root / (name + '.md')
            path.write_text(source)
            paths.append(str(path))
        work = self.root / 'outline-work'
        output = self.root / 'outline.pdf'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.export(paths, output, work), 0)
            self.assertEqual(verifier.main(['--pdf', str(output), '--work-dir', str(work),
                                            *paths]), 0)

    def test_titleless_book_needs_no_outline(self):
        work = self.root / 'titleless-work'
        output = self.root / 'titleless.pdf'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.export(self.inputs[1:3], output, work), 0)
            self.assertEqual(verifier.main(['--pdf', str(output), '--work-dir', str(work),
                                            *self.inputs[1:3]]), 0)


class CodeStructuralVerificationTest(unittest.TestCase):
    """结构树归属代码核验（R8/4.9，P1-1/P1-2 复现修复）的真实导出验收。

    负例用“渲染差异 + 证据对齐原输入”构造（与 run_pdf_export.sh 的
    N01/N04 同手法）：导出受损渲染，把导出证据中的输入路径/摘要改写为
    原输入并重签 PDF 摘要，迫使核验只能靠代码内容检查检出目标损伤，
    而不是靠摘要或证据一致性拒绝。
    """

    HEAD = '# 章\n\n> **来源**：https://example.com/structural\n\n'

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='code-structural-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)

    def export_one(self, name, code, language='c'):
        md = self.root / (name + '.md')
        md.write_text(self.HEAD + '```%s\n%s\n```\n' % (language, code),
                      encoding='utf-8')
        pdf = self.root / (name + '.pdf')
        work = self.root / ('work_' + name)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(md)], pdf, work)
        self.assertEqual(rc, 0, name)
        return md, pdf, work

    def resign_as_original(self, work, pdf, orig_md):
        """证据对齐原输入：输入路径/摘要换成原文件，重签 PDF 摘要。"""
        report = json.loads((work / exporter.REPORT_NAME).read_text(
            encoding='utf-8'))
        digest = exporter.sha256_file(orig_md)
        for item in report.get('inputs', []):
            item['path'] = str(orig_md.resolve())
            item['sha256'] = digest
        for item in report.get('chapters', []):
            item['path'] = str(orig_md.resolve())
            if 'sha256' in item:
                item['sha256'] = digest
        report['pdf_sha256'] = exporter.sha256_file(pdf)
        (work / exporter.REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def verify(self, pdf, work, md):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = verifier.main(['--pdf', str(pdf), '--work-dir', str(work),
                                str(Path(md).resolve())])
        report = json.loads((work / verifier.VERIFY_NAME).read_text())
        return rc, {f['code'] for f in report['failures']}

    def test_whitespace_deletion_inside_string_rejected(self):
        # P1-1：行内空白被删除（printf("a b") → printf("ab")）必拒；
        # 证据已对齐原输入，失败只能来自代码内容检查本身。
        orig_md, _, _ = self.export_one('ws_orig', 'printf("a b");')
        tam_md, tam_pdf, tam_work = self.export_one('ws_tam', 'printf("ab");')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_intact_code_with_spaces_and_cjk_comment_passes(self):
        # 正例：行内空白、混合中英文字体、缩进均保留时通过。
        code = 'int main() {\n    printf("a b");  // 中文注释：x\n    return 0;\n}'
        md, pdf, work = self.export_one('ws_ok', code)
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_cjk_line_inserted_at_block_head_rejected(self):
        # P1-2（块首）：非等宽回退字体的插入行在代码块容器内，必拒。
        orig_md, _, _ = self.export_one('head_orig', 'alpha = 1;\nbeta = 2;')
        tam_md, tam_pdf, tam_work = self.export_one(
            'head_tam', '恶意操作\nalpha = 1;\nbeta = 2;')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_cjk_line_inserted_at_block_tail_rejected(self):
        # P1-2（块尾）：插入行落在块内容器未消费部分，必拒。
        orig_md, _, _ = self.export_one('tail_orig', 'alpha = 1;\nbeta = 2;')
        tam_md, tam_pdf, tam_work = self.export_one(
            'tail_tam', 'alpha = 1;\nbeta = 2;\n恶意操作')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_line_inserted_inside_block_rejected(self):
        # 邻近情况：块中间插入整行同样必拒。
        orig_md, _, _ = self.export_one('mid_orig', 'a = 1;\nb = 2;\nc = 3;')
        tam_md, tam_pdf, tam_work = self.export_one(
            'mid_tam', 'a = 1;\nEVIL();\nb = 2;\nc = 3;')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_cross_page_long_block_and_repeated_blocks_pass(self):
        # 正例邻近情况：跨页长块 + 重复块各消费一份 + 空行/制表符保真。
        lines = '\n'.join('def f%d(): return %d' % (i, i) for i in range(1, 26))
        code = lines + '\n\n\ndef f1(): return 1\n' + lines
        md, pdf, work = self.export_one('cross_ok', code, language='python')
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_fence_inserted_between_blocks_rejected(self):
        # 邻近情况：两块之间插入一个独立围栏块（快路径会跳过它），必须
        # 被“未归属等宽容器”清扫检出。
        body_orig = '```python\nalpha = 1;\n```\n\n```text\nbeta = 2;\n```\n'
        body_tam = ('```python\nalpha = 1;\n```\n\n```text\nEVIL_INSERT();\n```'
                    '\n\n```text\nbeta = 2;\n```\n')
        orig_md = self.root / 'ib_orig.md'
        orig_md.write_text(self.HEAD + body_orig, encoding='utf-8')
        tam_md = self.root / 'ib_tam.md'
        tam_md.write_text(self.HEAD + body_tam, encoding='utf-8')
        tam_pdf, tam_work = self.root / 'ib_tam.pdf', self.root / 'ib_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(tam_md)], tam_pdf, tam_work)
        self.assertEqual(rc, 0)
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_mixed_font_fence_between_blocks_goes_to_review(self):
        # 复审修复：块间插入混合字体围栏（如 // 恶意注释）既非全等宽、
        # 也无法在原文逐行解释，必须记入待复核，不得静默通过。
        body_orig = '```python\nalpha = 1;\n```\n\n```text\nbeta = 2;\n```\n'
        body_tam = ('```python\nalpha = 1;\n```\n\n```python\nevil();  '
                    '// 恶意注释\n```\n\n```text\nbeta = 2;\n```\n')
        orig_md = self.root / 'mb_orig.md'
        orig_md.write_text(self.HEAD + body_orig, encoding='utf-8')
        tam_md = self.root / 'mb_tam.md'
        tam_md.write_text(self.HEAD + body_tam, encoding='utf-8')
        tam_pdf, tam_work = self.root / 'mb_tam.pdf', self.root / 'mb_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(tam_md)], tam_pdf, tam_work)
        self.assertEqual(rc, 0)
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, _ = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 0)
        report = json.loads(
            (tam_work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        self.assertTrue(
            any('未归属容器' in item['segment']
                for item in report['relaxed_matches']),
            report['relaxed_matches'])

    def test_empty_fence_block_passes(self):
        # 复审修复：源块仅含空行/空白（无可绘制 token）不得误拒。
        code = 'x = 1;\n\n```\n\n\n```\n\ny = 2;'
        md, pdf, work = self.export_one('empty_fence', code, language='text')
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_trailing_empty_fence_block_passes(self):
        # 评审 S1：章末空代码块零消费后不访问已耗尽的容器（此前
        # IndexError 使合法文档无法导出）。
        md = self.root / 'empty_tail.md'
        md.write_text(self.HEAD + '```text\nhello\n```\n\n```\n\n```\n',
                      encoding='utf-8')
        pdf, work = self.root / 'empty_tail.pdf', self.root / 'empty_tail_work'
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = exporter.export([str(md)], pdf, work)
        self.assertEqual(rc, 0)
        self.assertEqual(self.verify(pdf, work, md), (0, set()))

    def test_mixed_tab_space_indent_same_column_passes(self):
        # 评审 S2：`\t` 与空格+`\t` 都按制表位对齐第 8 列，是同一缩进；
        # 核验须按制表位换算列宽，不得按固定 8 空格折算后误报
        # code-indent-mismatch。
        md, pdf, work = self.export_one(
            'mixed_indent_ok', '\talpha();\n \tbeta();', language='c')
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_admonition_between_blocks_passes_silently(self):
        # 复审保护项：提示框（/Div 但属预期正文）不得被未归属清扫误伤。
        md_text = (self.HEAD + '```python\nalpha = 1;\n```\n\n'
                   '> **注（Note）**：提示框正文。\n\n'
                   '```text\nbeta = 2;\n```\n')
        md = self.root / 'adm.md'
        md.write_text(md_text, encoding='utf-8')
        pdf, work = self.root / 'adm.pdf', self.root / 'adm_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(md)], pdf, work)
        self.assertEqual(rc, 0)
        vrc, codes = self.verify(pdf, work, md)
        self.assertEqual((vrc, codes), (0, set()))
        report = json.loads(
            (work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        self.assertFalse(
            any('未归属容器' in item['segment']
                for item in report['relaxed_matches']),
            report['relaxed_matches'])

    def test_duplicate_whole_block_inserted_rejected(self):
        # 复审修复（发现1）：PDF 多出与源相同的整块代码（重复容器）必须
        # 拒绝——“内容能在原文找到”不排除出现次数，逐块独占一一消费。
        body_orig = '```python\nalpha = 1;\nbeta = 2;\n```\n'
        orig_md = self.root / 'dup_orig.md'
        orig_md.write_text(self.HEAD + body_orig, encoding='utf-8')
        tam_md = self.root / 'dup_tam.md'
        tam_md.write_text(self.HEAD + body_orig + '\n' + body_orig,
                          encoding='utf-8')
        tam_pdf, tam_work = self.root / 'dup_tam.pdf', self.root / 'dup_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(tam_md)], tam_pdf, tam_work)
        self.assertEqual(rc, 0)
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_whitespace_run_count_deletion_rejected(self):
        # 复审修复（发现2）：源空白 run 个数被删短（"a  b"→"a b"）必拒，
        # 不做删空白后的比较口径。
        orig_md, _, _ = self.export_one('wsc_orig', 'char *s = "a  b";')
        tam_md, tam_pdf, tam_work = self.export_one('wsc_tam', 'char *s = "a b";')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_fake_short_wrap_with_whitespace_deletion_rejected(self):
        # 三轮复审 P1-4：真实 Chromium 成品把一条很短的源行
        # 拆成三行，同时把字符串中的双空格删为单空格。重签名
        # 后摘要与输入均正确，必须由代码几何/内容核验本身拒绝。
        orig_md, _, _ = self.export_one('fake_wrap_orig', 'printf("a  b");')
        _tam_md, tam_pdf, tam_work = self.export_one(
            'fake_wrap_tam', 'printf(\n"a \nb");')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_real_long_line_visual_wrap_passes(self):
        # 配对正例：一条足以到达版心右界的源代码行由 Chromium
        # 正常视觉折行，内容未变时应继续通过。
        code = 'printf("%s", "' + ('alpha beta ' * 90) + '");'
        md, pdf, work = self.export_one('real_wrap_ok', code)
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_hyphen_boundary_visual_wrap_passes(self):
        # 六轮复审 P2：Chromium 可以在 ASCII 连字符后使用正常
        # 软断点。断点前的字形右缘可能远离版心右界，但只有
        # 当后续 token 确实放不下时才能解释为合法排版折行。
        code = 'short-' + ('A' * 90)
        md, pdf, work = self.export_one('hyphen_wrap_ok', code)
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_long_token_early_manual_break_rejected(self):
        # 五轮复审 P1：连续 200 个 A 的正常自然折行应通过；人为在
        # 第 5 个字符后插入逻辑换行时，首行距右界很远。重签摘要后
        # 必须由实际绘制几何拒绝，不能以“剩余 token 放不下”放行。
        code = 'A' * 200
        orig_md, orig_pdf, orig_work = self.export_one(
            'long_token_orig', code)
        rc, codes = self.verify(orig_pdf, orig_work, orig_md)
        self.assertEqual((rc, codes), (0, set()))

        _tam_md, tam_pdf, tam_work = self.export_one(
            'long_token_early_break', code[:5] + '\n' + code[5:])
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_mid_fragment_break_with_fitting_tail_rejected(self):
        # 七轮复审：断点已过片段半程（绘制多数守卫不适用）、整段
        # 宽度超剩余空间，但未绘制尾部本放得下——整段宽度把已绘制
        # 前缀重复计数，不构成折行依据；只有未绘制部分放不下才行。
        # 60 个 A 单行正常通过；拆成 40+20（首行剩约 281pt、尾部
        # 仅约 102pt）重签后必须由代码检查拒绝。
        code = 'A' * 60
        orig_md, orig_pdf, orig_work = self.export_one(
            'mid_frag_orig', code)
        rc, codes = self.verify(orig_pdf, orig_work, orig_md)
        self.assertEqual((rc, codes), (0, set()))

        _tam_md, tam_pdf, tam_work = self.export_one(
            'mid_frag_early', code[:40] + '\n' + code[40:])
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_unicode_punctuation_visual_wrap_passes(self):
        # 原样交给 Chromium 排版，核验不能把 Unicode 合法软断点
        # 当成新增逻辑换行；覆盖连字符白名单之外的破折号。
        for label, separator in [('em_dash', '\u2014'),
                                 ('en_dash', '\u2013'),
                                 ('unicode_hyphen', '\u2010')]:
            with self.subTest(separator=label):
                md, pdf, work = self.export_one(
                    label + '_wrap', 'short' + separator + 'A' * 90)
                self.assertEqual(self.verify(pdf, work, md), (0, set()))

    def test_soft_boundary_still_requires_insufficient_space(self):
        # 有合法软断点也不等于可以任意移行：紧随破折号的 tiny-
        # 仍能放进当前行，不能因更远处的长串放不下而提前换行。
        code = 'short\u2014tiny-' + 'A' * 90
        md, pdf, work = self.export_one('soft_boundary_orig', code)
        self.assertEqual(self.verify(pdf, work, md), (0, set()))
        _, damaged, damaged_work = self.export_one(
            'soft_boundary_early', code.replace('\u2014', '\u2014\n'))
        self.resign_as_original(damaged_work, damaged, md)
        rc, codes = self.verify(damaged, damaged_work, md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_nonbreaking_hyphen_early_break_rejected(self):
        code = 'short\u2011' + 'A' * 90
        md, pdf, work = self.export_one('nonbreaking_orig', code)
        self.assertEqual(self.verify(pdf, work, md), (0, set()))
        _, damaged, damaged_work = self.export_one(
            'nonbreaking_early', code.replace('\u2011', '\u2011\n'))
        self.resign_as_original(damaged_work, damaged, md)
        rc, codes = self.verify(damaged, damaged_work, md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_uniform_leading_indent_deletion_rejected(self):
        # 四轮复审：单行/全块同缩进不能因没有相对 x 参照行而被
        # lstrip 静默掉。重签证据后必须仍由实际绘制内容拒绝。
        orig_md, _, _ = self.export_one(
            'indent_orig', '    printf("kept indent");')
        _tam_md, tam_pdf, tam_work = self.export_one(
            'indent_tam', 'printf("kept indent");')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_literal_tab_indent_passes(self):
        # 配对正例：真实 tab 的视觉展开宽度可由排版决定，但前导
        # 缩进不得丢失；完好产物应通过并保留待视觉复核记录。
        md, pdf, work = self.export_one(
            'tab_indent_ok', '\tprintf("tab indent");')
        rc, codes = self.verify(pdf, work, md)
        self.assertEqual((rc, codes), (0, set()))

    def test_codepoint_replacement_rejected(self):
        # 复审修复（发现3）：全角Ａ被渲染为半角 A 属码位替换，必拒——
        # 代码对账不做 NFKC 归一。
        orig_md, _, _ = self.export_one('nfkc_orig', 'printf("Ａ");')
        tam_md, tam_pdf, tam_work = self.export_one('nfkc_tam', 'printf("A");')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_structure_insufficient_goes_to_per_block_review(self):
        # 设计 §2 差异③：结构树不可用时不再运行旧几何匹配器。每个源块
        # 记录源位置、候选页/区域与未证实的内容/分页项，进入待复核；
        # 机器不假判通过，也不在无归属证据时猜测硬失败——复核闭合前
        # verify_delivery 必拒（03 阶段验收）。
        import unittest.mock as mock
        orig_md, _, _ = self.export_one('si_orig', 'char *s = "a b";')
        tam_md, tam_pdf, tam_work = self.export_one('si_tam', 'char *s = "ab";')
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        with mock.patch.object(verifier, '_walk_content_stream_positions',
                               return_value=None):
            rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 0)
        self.assertEqual(codes, set())  # 无结构归属证据：机器不猜测定损伤
        report = json.loads(
            (tam_work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        segments = [item['segment'] for item in report['relaxed_matches']]
        self.assertTrue(any('结构不足' in s for s in segments), segments)
        per_block = [s for s in segments if '代码块 #1' in s and '待复核' in s]
        self.assertTrue(per_block, segments)
        # 源位置（首行内容）与候选页区域都必须可定位
        self.assertIn('char *s', per_block[0])
        self.assertRegex(per_block[0], r'第 \d+–\d+ 页')

    def test_structure_insufficient_covers_every_block(self):
        # 逐块合同：结构不足时每个源块各有一条待复核记录（含空块），
        # 不能只留一条章级记录蒙混。
        import unittest.mock as mock
        md = self.root / 'si_multi.md'
        md.write_text(self.HEAD
                      + '```text\na = 1;\n```\n\n```\n\n\n```\n\n'
                      + '```text\nb = 2;\n```\n', encoding='utf-8')
        pdf, work = self.root / 'si_multi.pdf', self.root / 'si_multi_work'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.export([str(md)], pdf, work), 0)
        with mock.patch.object(verifier, '_walk_content_stream_positions',
                               return_value=None):
            rc, codes = self.verify(pdf, work, md)
        self.assertEqual(rc, 0)
        report = json.loads(
            (work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        segments = [item['segment'] for item in report['relaxed_matches']]
        for block_no in ('#1', '#2', '#3'):
            self.assertTrue(
                any(('代码块 ' + block_no) in s and '待复核' in s
                    for s in segments),
                (block_no, segments))

    def test_mixed_font_duplicate_block_rejected(self):
        # 二轮复审（发现1重开）：逐字重复的代码块含混合字体行（CJK 注释）
        # 时，不能只因子串在原文出现就静默放行——与源代码块严格对账一致
        # 且有等宽行，按重复块必拒。
        body = '```python\nalpha = 1;  // 初始化\nbeta = 2;\n```\n'
        orig_md = self.root / 'mdup_orig.md'
        orig_md.write_text(self.HEAD + body, encoding='utf-8')
        tam_md = self.root / 'mdup_tam.md'
        tam_md.write_text(self.HEAD + body + '\n' + body, encoding='utf-8')
        tam_pdf, tam_work = self.root / 'mdup_tam.pdf', self.root / 'mdup_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(tam_md)], tam_pdf, tam_work)
        self.assertEqual(rc, 0)
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, codes = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)

    def test_pure_fallback_duplicate_block_goes_to_review(self):
        # 纯回退字体渲染（无等宽行）的重复块无法按字体机器定性：必须记
        # 待复核，不得静默通过。
        body = '```text\n仅中文注释行\n```\n'
        orig_md = self.root / 'pdup_orig.md'
        orig_md.write_text(self.HEAD + body, encoding='utf-8')
        tam_md = self.root / 'pdup_tam.md'
        tam_md.write_text(self.HEAD + body + '\n' + body, encoding='utf-8')
        tam_pdf, tam_work = self.root / 'pdup_tam.pdf', self.root / 'pdup_work'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = exporter.export([str(tam_md)], tam_pdf, tam_work)
        self.assertEqual(rc, 0)
        self.resign_as_original(tam_work, tam_pdf, orig_md)
        rc, _ = self.verify(tam_pdf, tam_work, orig_md)
        self.assertEqual(rc, 0)
        report = json.loads(
            (tam_work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        self.assertTrue(
            any('与源代码块一致' in item['segment']
                for item in report['relaxed_matches']),
            report['relaxed_matches'])

    def test_missing_duplicate_block_rejected(self):
        # 邻近情况：重复块缺一份（源只剩一块，PDF 有两块）必拒。
        block = 'same();\nsame();'
        two_md, two_pdf, two_work = self.export_one(
            'dup_two', block, language='text')
        one_md, one_pdf, one_work = self.export_one(
            'dup_one', 'same();', language='text')
        self.resign_as_original(two_work, two_pdf, one_md)
        rc, codes = self.verify(two_pdf, two_work, one_md)
        self.assertEqual(rc, 1)
        self.assertIn('code-line-missing', codes)


class BlockTokenReconciliationTest(unittest.TestCase):
    """块对账核心（_consume_block_tokens）合同：插入/换序/借字必拒（R8/A23）。

    结构归属把容器行交给该核心逐块对账；几何回退匹配器已按精简 02
    撤除（结构不足走逐块待复核），这里直接固定唯一对账核心的行为。
    """

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
        import verify_pdf
        self.vp = verify_pdf

    @staticmethod
    def rows(*texts):
        return [{"text": text} for text in texts]

    def consume(self, texts, code):
        return self.vp._consume_block_tokens(
            self.rows(*texts), self.vp.logical_lines_of(code))

    def test_intact_block_with_blank_lines_consumes(self):
        self.assertIsNotNone(
            self.consume(['a = 1', '', 'b = 2'], 'a = 1\n\nb = 2\n'))

    def test_mixed_script_line_matches_logical_order(self):
        text = '# 中文注释：code with $dollars$ stays'
        self.assertIsNotNone(self.consume([text], text + '\n'))

    def test_inserted_line_between_lines_fails(self):
        self.assertIsNone(
            self.consume(['a = 1', 'EVIL_EXTRA();', 'b = 2'], 'a = 1\nb = 2\n'))

    def test_order_swap_within_line_fails(self):
        self.assertIsNone(self.consume(['return b-a;'], 'return a-b;\n'))

    def test_trailing_inserted_line_fails(self):
        self.assertIsNone(
            self.consume(['a = 1', 'b = 2', 'EVIL_EXTRA();'],
                         'a = 1\nb = 2\n'))

    def test_leading_inserted_line_fails(self):
        self.assertIsNone(self.consume(['EVIL_EXTRA();', 'a = 1'], 'a = 1\n'))

    def test_adjacent_body_text_between_lines_fails(self):
        # 邻文不能补齐缺字：正文行插在代码行之间必须拒绝
        self.assertIsNone(
            self.consume(['a = 1', '正文插入', 'b = 2'], 'a = 1\nb = 2\n'))

    def test_cross_page_wrap_requires_bottom_and_top_geometry(self):
        # 四轮复审：“页码不同”本身不是页界证据。两条短行都远离
        # 页底/页首时，不能用假跨页放行源双空格被删一个。
        rows = [
            {"text": 'printf("a ', "bucket": {
                "page": 0, "baseline_y_pt": 400.0,
                "page_bottom_pt": 0.0, "page_top_pt": 842.0,
                "line_height_pt": 10.0, "wrap_at_right": False}},
            {"text": 'b");', "bucket": {
                "page": 1, "baseline_y_pt": 400.0,
                "page_bottom_pt": 0.0, "page_top_pt": 842.0,
                "line_height_pt": 10.0, "wrap_at_right": False}},
        ]
        self.assertIsNone(
            self.vp._consume_block_tokens(rows, ['printf("a  b");']))

    def test_real_page_boundary_allows_intact_continuation(self):
        # 配对正例：前行基线已到实际页底、后行从下页版心顶部续排
        # 时，完整 token 可以跨页拼接。
        rows = [
            {"text": 'printf("alpha ', "bucket": {
                "page": 0, "baseline_y_pt": 66.0,
                "page_bottom_pt": 0.0, "page_top_pt": 842.0,
                "line_height_pt": 10.0, "wrap_at_right": False}},
            {"text": 'beta");', "bucket": {
                "page": 1, "baseline_y_pt": 776.0,
                "page_bottom_pt": 0.0, "page_top_pt": 842.0,
                "line_height_pt": 10.0, "wrap_at_right": False}},
        ]
        self.assertIsNotNone(
            self.vp._consume_block_tokens(
                rows, ['printf("alpha beta");']))


class CodePaginationGapTest(unittest.TestCase):
    """A21 + 设计 §4.9：长块被强制整块移页时，候选代码门禁阻止替换成品。

    用真实 Chromium 输出构造：把打印样式中的长块跨页规则临时改为
    break-inside: avoid（模拟旧缺陷），长块整块移到下一页、前页仅剩
    几行导语。导出器在复制候选到最终目标前调用与核验器同一实现的
    代码检查：必须以 code-page-gap 拒绝导出（非零退出），已有成品
    字节保持不变，不能仅靠独立核验事后发现。
    """

    def _patched_assets(self, root):
        import shutil
        skill_dir = (Path(__file__).resolve().parents[1]
                     / 'skills/tech-doc-translator')
        assets = root / 'pdf'
        shutil.copytree(skill_dir / 'assets/pdf', assets)
        css_path = assets / 'style.css'
        css = css_path.read_text(encoding='utf-8')
        broken = css.replace(
            '.code-block.code-long, .code-block.code-long pre {\n'
            '  break-inside: auto;',
            '.code-block.code-long, .code-block.code-long pre {\n'
            '  break-inside: avoid;')
        self.assertNotEqual(broken, css)  # 样式补丁必须命中
        css_path.write_text(broken, encoding='utf-8')
        return assets

    @staticmethod
    def _long_block_markdown(pad_paragraphs):
        lines = '\n'.join('value%d = %d;' % (i, i) for i in range(1, 64))
        if pad_paragraphs:
            pad = '\n\n'.join('段落 %d：占据版面高度的普通正文内容。' % i
                              for i in range(1, pad_paragraphs + 1))
            return ('# 章\n\n> **来源**：https://example.com/page-gap\n\n'
                    + pad + '\n\n## 小节标题\n\n```python\n' + lines
                    + '\n```\n')
        return ('# 章\n\n> **来源**：https://example.com/page-gap\n\n'
                '导语一行，其后长块应从当前页续排：\n\n```python\n' + lines
                + '\n```\n')

    def _export(self, md_text, patched):
        root = Path(tempfile.mkdtemp(prefix='page-gap-'))
        self.addCleanup(__import__('shutil').rmtree, root, True)
        assets = self._patched_assets(root) if patched else None
        md = root / 'gap.md'
        md.write_text(md_text, encoding='utf-8')
        pdf, work = root / 'gap.pdf', root / 'gap_work'
        pdf.write_bytes(b'OLD-PDF-BYTES')
        saved_assets = exporter.ASSETS_DIR
        if assets is not None:
            exporter.ASSETS_DIR = assets
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                rc = exporter.export([str(md)], pdf, work)
        finally:
            exporter.ASSETS_DIR = saved_assets
        return rc, stderr.getvalue(), pdf, work

    def test_forced_long_block_move_blocked_before_replacing_output(self):
        # 无标题变体：63 行长块整块移页、前页仅几行导语
        rc, stderr, pdf, work = self._export(self._long_block_markdown(0),
                                             patched=True)
        self.assertEqual(rc, 1)
        self.assertIn('code-page-gap', stderr)
        self.assertEqual(pdf.read_bytes(), b'OLD-PDF-BYTES')  # 旧成品不变
        report = json.loads(
            (work / exporter.REPORT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'machine-fail')
        gate_codes = {item['code'] for item in report['code_gate_failures']}
        self.assertIn('code-page-gap', gate_codes)

    def test_forced_move_with_leading_h2_still_blocked(self):
        # H2 变体：小节标题随块移到下页（标题在块前、前页大段留白）。
        # 前导内容不构成豁免：前页放得下标题与至少一完整代码行即拒绝。
        rc, stderr, pdf, work = self._export(self._long_block_markdown(20),
                                             patched=True)
        self.assertEqual(rc, 1)
        self.assertIn('code-page-gap', stderr)
        self.assertEqual(pdf.read_bytes(), b'OLD-PDF-BYTES')  # 旧成品不变
        report = json.loads(
            (work / exporter.REPORT_NAME).read_text(encoding='utf-8'))
        gate_codes = {item['code'] for item in report['code_gate_failures']}
        self.assertIn('code-page-gap', gate_codes)

    def test_same_content_without_patch_uses_page_tail(self):
        # 配对正例：去掉强制整块约束后，长块从当前页尾续排并跨页，
        # 导出与独立核验均通过
        rc, _stderr, pdf, work = self._export(self._long_block_markdown(20),
                                              patched=False)
        self.assertEqual(rc, 0)
        from pypdf import PdfReader
        reader = PdfReader(str(pdf))
        page1 = reader.pages[0].extract_text() or ''
        page2 = reader.pages[1].extract_text() or ''
        self.assertIn('value1 = 1;', page1)   # 块从当前页尾开始
        self.assertIn('value63 = 63;', page2)  # 后续行续到下一页
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            vrc = verifier.main(['--pdf', str(pdf), '--work-dir', str(work),
                                 str(pdf.parent / 'gap.md')])
        self.assertEqual(vrc, 0)
        report = json.loads(
            (work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        self.assertEqual(report['failures'], [])


class LineBucketPhysicalInvarianceTest(unittest.TestCase):
    """行聚合/排序统一物理基线：同一物理布局以不同文本矩阵表达时，
    聚类、顺序与行首几何结论一致；原始 tm 仅作提取层联接键。"""

    @staticmethod
    def _events(variant):
        # 同一物理布局的两行（基线 700/500，起点 60/80），两种 tm 表达：
        # variant 0 的原始 tm.y 与物理同序、variant 1 加了整体偏移并
        # 交叉——聚类与顺序必须只看 baseline_y_pt
        offsets = [(100.0, 300.0), (250.0, 450.0)][variant]
        def run(text, baseline, start, raw_y, raw_x):
            return {"y": raw_y, "x": raw_x, "font": "Menlo", "text": text,
                    "start_pt": start, "right_pt": start + 100.0,
                    "code_left_pt": 50.0, "code_right_pt": 520.0,
                    "advance_pt": 5.1, "baseline_y_pt": baseline,
                    "font_size_pt": 8.5, "page_left_pt": 0.0,
                    "page_bottom_pt": 0.0, "page_right_pt": 595.0,
                    "page_top_pt": 842.0}
        return [[
            run("top_line();", 700.0, 60.0, offsets[0], 3.0),
            run("bottom_line();", 500.0, 80.0, offsets[1], 9.0),
        ]]

    def test_clustering_order_and_geometry_invariant(self):
        first = verifier.build_line_buckets(self._events(0))
        second = verifier.build_line_buckets(self._events(1))
        shape = lambda buckets: [  # noqa: E731
            (b["text"], round(b["start_pt"], 1), round(b["baseline_y_pt"], 1))
            for b in buckets]
        self.assertEqual(shape(first), shape(second))
        # 物理基线降序 = 视觉自上而下
        self.assertEqual([b["text"] for b in first],
                         ["top_line();", "bottom_line();"])
        # 不同缩进（60 vs 80）在两种表达下都参与缩进几何
        failures = []
        verifier._check_code_indent_geometry(
            [(0, first[0]["start_pt"]), (4, first[1]["start_pt"])],
            type('C', (), {'path': 'x.md'})(), 1, failures)
        self.assertEqual(failures, [])


class ImageBottomPaginationTest(unittest.TestCase):
    """图片页底 + 跨页长代码的正例：不误报整块移页（A22 正常成品）。

    图片未挤进前页剩余空间而移到下一页顶部、长块跟随图片排布时，
    块不能回填前页；剩余空间计算须计入绘制图片底边，且非页顶起块的
    长块不构成整块移页。导出（含候选代码门禁）与独立核验均须通过。
    """

    def test_image_then_cross_page_code_layout_passes(self):
        import shutil
        skill_dir = (Path(__file__).resolve().parents[1]
                     / 'skills/tech-doc-translator')
        root = Path(tempfile.mkdtemp(prefix='img-code-'))
        self.addCleanup(shutil.rmtree, root, True)
        make_png(root / 'images/pic.png', 600, 300)
        lines11 = '\n'.join('value%d = %d;' % (i, i) for i in range(1, 12))
        # 18 段导语把图片推到页界：图片移到下页顶部、代码随后跨页
        pad = '\n\n'.join('段落 %d：占据版面高度的普通正文内容。' % i
                          for i in range(1, 19))
        md = root / 'a.md'
        md.write_text(
            '# 章\n\n> **来源**：https://example.com/img-code\n\n' + pad
            + '\n\n![图](images/pic.png)\n\n```python\n' + lines11
            + '\n```\n', encoding='utf-8')
        pdf, work = root / 'a.pdf', root / 'work'
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = exporter.export([str(md)], pdf, work)
        self.assertEqual(rc, 0)
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            vrc = verifier.main(['--pdf', str(pdf), '--work-dir', str(work),
                                 str(md)])
        self.assertEqual(vrc, 0)
        report = json.loads(
            (work / verifier.VERIFY_NAME).read_text(encoding='utf-8'))
        self.assertEqual(report['failures'], [])
        # 移页有依据时记录空间证据（前导图片范围与前页剩余），非待复核项
        justified = [item for item in report['relaxed_matches']
                     if '有空间依据' in item.get('segment', '')]
        self.assertTrue(justified, report['relaxed_matches'][:3])
        self.assertTrue(all(item.get('review') is False for item in justified))


class IndentColumnTest(unittest.TestCase):
    """前导空白列宽统一按 8 列制表位换算（评审 S2 的纯规则口径）。"""

    def test_tab_stop_alignment(self):
        self.assertEqual(verifier._indent_columns(''), 0)
        self.assertEqual(verifier._indent_columns('    '), 4)
        self.assertEqual(verifier._indent_columns('\t'), 8)
        self.assertEqual(verifier._indent_columns(' \t'), 8)
        self.assertEqual(verifier._indent_columns('       \t'), 8)
        self.assertEqual(verifier._indent_columns('        \t'), 16)
        self.assertEqual(verifier._indent_columns('\t\t'), 16)


class EmbedResampleTest(unittest.TestCase):
    """内联重采样的显示语义保持（评审 S3/S4）：只变嵌入负载，显示不变。"""

    HEAD = '# 章\n\n> **来源**：https://example.com/resample\n\n'

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='embed-resample-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        (cls.root / 'images').mkdir()

    def _export_one(self, name, md_text):
        md = self.root / (name + '.md')
        md.write_text(md_text, encoding='utf-8')
        pdf, work = self.root / (name + '.pdf'), self.root / (name + '_work')
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = exporter.export([str(md)], pdf, work)
        self.assertEqual(rc, 0, name)
        return pdf, work

    @staticmethod
    def _drawn_images(pdf):
        facts = verifier.PdfFacts(str(pdf))
        return [img for page in verifier.collect_drawn_images(facts)
                for img in page]

    def test_pure_below_threshold_passes_through(self):
        small = self.root / 'images/small.png'
        make_png(str(small), 100, 100)
        record = {"pixel_known": True, "kind": "PNG", "frames": 1,
                  "pixel_size": (100, 100)}
        self.assertEqual(exporter._resampled_embed(str(small), record),
                         (None, None))

    def test_pure_resample_records_display_width(self):
        tall = self.root / 'images/tall.png'
        make_png(str(tall), 300, 3000)
        record = {"pixel_known": True, "kind": "PNG", "frames": 1,
                  "pixel_size": (300, 3000)}
        payload, rec = exporter._resampled_embed(str(tall), record)
        self.assertIsNotNone(payload)
        self.assertEqual(rec["original"], [300, 3000])
        self.assertEqual(rec["embedded"], [260, 2600])
        self.assertEqual(rec["display_width"], 300)

    def test_pure_jpeg_exif_orientation_baked_in(self):
        from io import BytesIO

        from PIL import Image
        src = self.root / 'images/rotated.jpg'
        image = Image.new('RGB', (3000, 1000), (200, 30, 30))
        exif = Image.Exif()
        exif[0x0112] = 6  # 显示方向旋转 90°：浏览器自然尺寸为竖图 1000×3000
        image.save(str(src), quality=90, exif=exif)
        record = {"pixel_known": True, "kind": "JPEG", "frames": 1,
                  "pixel_size": (3000, 1000)}
        payload, rec = exporter._resampled_embed(str(src), record)
        self.assertIsNotNone(payload)
        self.assertEqual(rec["display_width"], 1000)
        self.assertEqual(rec["embedded"], [867, 2600])  # 竖图保持竖向
        decoded = Image.open(BytesIO(payload))
        self.assertEqual(list(decoded.size), [867, 2600])
        # 负载不再依赖方向标记（像素已是显示方向）
        self.assertIsNone(decoded.getexif().get(0x0112))

    def test_unmapped_resampled_image_keeps_display_width(self):
        # 评审 S3：300×3000 无映射图片重采样后，PDF 绘制宽度必须保持
        # 原自然尺寸 300px=225pt，不随负载（260px）缩为 195pt。
        make_png(str(self.root / 'images/tall.png'), 300, 3000)
        pdf, work = self._export_one(
            'tall', self.HEAD + '![长图](images/tall.png)\n')
        report = json.loads(
            (work / exporter.REPORT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(report['embed_resampled'][0]['original'],
                         [300, 3000])
        drawn = self._drawn_images(pdf)
        self.assertTrue(drawn)
        self.assertAlmostEqual(max(w for w, _b, _t in drawn), 225.0,
                               delta=2.0)

    def test_resampled_jpeg_keeps_portrait_orientation(self):
        # 评审 S4：EXIF orientation=6 的 3000×1000 JPEG 原显示为竖图
        # 1000×3000；重采样后必须仍为竖图（版心限宽下高约为宽 3 倍）。
        from PIL import Image
        src = self.root / 'images/rotated.jpg'
        image = Image.new('RGB', (3000, 1000), (30, 30, 200))
        exif = Image.Exif()
        exif[0x0112] = 6
        image.save(str(src), quality=90, exif=exif)
        pdf, _work = self._export_one(
            'rotated', self.HEAD + '![竖图](images/rotated.jpg)\n')
        drawn = self._drawn_images(pdf)
        self.assertTrue(drawn)
        width = max(w for w, _b, _t in drawn)
        # 跨页图片在每页记录整幅范围：取单条目的高宽比，不跨页累加。
        height = max(t - b for _w, b, t in drawn)
        self.assertAlmostEqual(width, 504.6, delta=3.0)  # 版心上限
        self.assertAlmostEqual(height / width, 3.0, delta=0.1)


class CodeShortTooTallTest(unittest.TestCase):
    """短块超页预检（评审 S5）：按打印版心宽度量测并覆盖高亮路线。

    默认 1280px 窗口下高度不足一页的短块，在 A4 打印版心宽度下可能
    超过一页；预检必须按打印宽度量测，选择器须同时覆盖回退 <pre>
    与 Pygments 的 .highlight 包装节点。超页短块必拒且不替换已有
    成品；候选门禁保持独立。
    """

    HEAD = '# 章\n\n> **来源**：https://example.com/too-tall\n\n'

    def _export(self, name, language):
        import shutil
        root = Path(tempfile.mkdtemp(prefix='too-tall-'))
        self.addCleanup(shutil.rmtree, root, True)
        line = 'value = "%s";' % ('A' * 4000)
        md = root / (name + '.md')
        md.write_text(self.HEAD + '```%s\n%s\n%s\n```\n'
                      % (language, line, line), encoding='utf-8')
        pdf, work = root / (name + '.pdf'), root / (name + '_work')
        pdf.write_bytes(b'OLD-PDF-BYTES')
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            rc = exporter.export([str(md)], pdf, work)
        return rc, stderr.getvalue(), pdf, work

    def test_unknown_language_short_block_too_tall_rejected(self):
        # 打印宽度下超过一页（默认 1280px 窗口量测则漏诊）。
        rc, stderr, pdf, work = self._export('plain', 'unknownlang')
        self.assertEqual(rc, 1)
        self.assertIn('code-short-too-tall', stderr)
        self.assertEqual(pdf.read_bytes(), b'OLD-PDF-BYTES')  # 旧成品不变
        report = json.loads(
            (work / exporter.REPORT_NAME).read_text(encoding='utf-8'))
        self.assertTrue(report['browser_checks']['codeShortTooTall'])

    def test_highlighted_short_block_too_tall_rejected(self):
        # Pygments 高亮路线（.code-block > .highlight > pre）同样覆盖。
        rc, stderr, pdf, work = self._export('highlight', 'c')
        self.assertEqual(rc, 1)
        self.assertIn('code-short-too-tall', stderr)
        self.assertEqual(pdf.read_bytes(), b'OLD-PDF-BYTES')  # 旧成品不变


if __name__ == "__main__":
    unittest.main()
