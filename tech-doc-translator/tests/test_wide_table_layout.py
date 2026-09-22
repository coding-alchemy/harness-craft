"""宽表整本缩印的几何验收（迁移 B：表格单元格 overflow-wrap: anywhere）。

含长标识符的多列表格在 `overflow-wrap: break-word` 下不参与 min-content
计算：表格塞进屏幕视口（导出器溢出检查通过）却超出打印版心，Chromium
打印把整文档统一缩印。缩印对所有机器内容检查静默（正文仍在、核验通
过），只能用几何观测：已知自然尺寸的探针图其实际绘制宽度即整文档缩
放因子。
"""
import contextlib
import io
import json
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter   # noqa: E402
import verify_pdf as verifier   # noqa: E402

# A4 版心右缘：210mm − 16mm 边距（1pt = 1/72 inch）。
CONTENT_RIGHT_PT = (210 - 16) / 25.4 * 72
# 探针图自然尺寸 200×100 CSS px = 150×75 pt。
PROBE_PNG_PX = (200, 100)
PROBE_WIDTH_PT = PROBE_PNG_PX[0] * exporter.PT_PER_CSS_PX
# 长标识符（55 字符）×3 列：min-content 落在打印版心与屏幕视口之间，
# 复现"屏幕检查通过、打印整本缩印"的真实缺陷场景。
LONG_ID = 'cudaDeviceSetLimitAsyncConfig__heap_padding_alignment'


def probe_png(path):
    """生成固定纯色 PNG 探针，不依赖图像库。"""
    def chunk(tag, data):
        body = struct.pack('>I', len(data)) + tag + data
        return body + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    width, height = PROBE_PNG_PX
    raw = b''.join(b'\x00' + bytes((40, 90, 200) * width) for _ in range(height))
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class WideTableLayoutTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='wide-table-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        probe_png(cls.root / 'probe.png')
        doc = '\n'.join([
            '# 宽表缩印回归',
            '',
            '> **来源**：https://example.invalid/wide-table（合成测试）',
            '',
            '这是用于测量整本文档缩放因子的普通段落，包含足够长的中文文字'
            '用来观察正文排版宽度是否被打印缩放压缩，这一行文字应当延伸到'
            '接近版心右缘的位置才会自然换行。',
            '',
            '| 普通列 A | 普通列 B |',
            '|---|---|',
            '| 短文本 1 | 短文本 2 |',
            '',
            '| 宽表列 1 | 宽表列 2 | 宽表列 3 |',
            '|---|---|---|',
            '| %s_a | %s_b | %s_c |' % (LONG_ID, LONG_ID, LONG_ID),
            '',
            '![探针图](probe.png)',
            '',
            '结尾段落。',
        ])
        (cls.root / 'doc.md').write_text(doc, encoding='utf-8')
        cls.work = cls.root / 'work'
        with contextlib.redirect_stdout(io.StringIO()):
            result = exporter.export([str(cls.root / 'doc.md')],
                                     cls.root / 'book.pdf', cls.work)
        if result:
            raise AssertionError((cls.work / exporter.REPORT_NAME).read_text(
                encoding='utf-8'))
        report = json.loads(
            (cls.work / exporter.REPORT_NAME).read_text(encoding='utf-8'))
        cls.report = report

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return verifier.main(
                ['--pdf', str(self.root / 'book.pdf'),
                 '--work-dir', str(self.work), str(self.root / 'doc.md')])

    def test_probe_image_keeps_natural_width_no_document_shrink(self):
        # 整文档缩印的直接几何观测：探针图按自然尺寸绘制说明打印缩放
        # 因子为 1；break-word 下同一文档实测被压到约 0.77×（114.7pt）。
        widths = verifier.collect_drawn_images(
            verifier.PdfFacts(str(self.root / 'book.pdf')))
        self.assertEqual(len(widths), 1, widths)
        self.assertAlmostEqual(widths[0][0], PROBE_WIDTH_PT, delta=1.0,
                               msg='探针图被缩放，整文档处于缩印状态：%r' % widths)

    def test_no_text_beyond_content_box(self):
        import pypdf
        reader = pypdf.PdfReader(str(self.root / 'book.pdf'))
        worst = 0.0
        for page in reader.pages:
            origins = []

            def visit(text, cm, tm, font_dict, font_size, origins=origins):
                if text.strip():
                    origins.append(cm[0] * tm[4] + cm[2] * tm[5] + cm[4])

            page.extract_text(visitor_text=visit)
            if origins:
                worst = max(worst, max(origins))
        self.assertLessEqual(
            worst, CONTENT_RIGHT_PT + 2.0,
            '文本绘制原点超出版心右缘 %.1f：%.1f' % (CONTENT_RIGHT_PT, worst))

    def test_export_checks_and_independent_verify_pass(self):
        self.assertEqual(self.report['browser_checks']['overflow'], [])
        self.assertEqual(self.report['browser_checks']['katex'], [])
        self.assertEqual(self.verify(), 0)

    def test_normal_and_wide_table_content_intact(self):
        import unicodedata
        import pypdf
        reader = pypdf.PdfReader(str(self.root / 'book.pdf'))
        text = re.sub(r'\s+', '', ''.join(
            p.extract_text() or '' for p in reader.pages))
        # NFKC 归一化 fi 连字等，再做内容断言
        text = unicodedata.normalize('NFKC', text)
        # 普通表格不触发词中断行，单元格文字完整；宽表长标识符按
        # anywhere 折行后仍逐字连续可提取。
        self.assertIn('短文本1', text)
        self.assertIn('短文本2', text)
        self.assertIn('宽表列1', text)
        self.assertIn(LONG_ID + '_a', text)
        self.assertIn(LONG_ID + '_c', text)


if __name__ == '__main__':
    unittest.main()
