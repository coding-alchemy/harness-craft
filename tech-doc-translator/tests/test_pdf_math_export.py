"""Ticket 02（一期 D2/R2 适用 PDF 消费）固定验收：合法公式进入真实 PDF。

最小真实样例同时含相邻行内公式（$x$$\\sim$）、数字邻接公式（2$\\times$3）、
合法数字开头公式（$5 + x$）与普通价格（costs $5 and $10、单个 $100）：
经真实 export_pdf CLI 导出实际 PDF，数学 DOM（combined.html 的 data-tex
节点序列）、导出证据的公式清单与实际成品（pymupdf 独立抽取）对照其类型、
顺序与内容，价格仍是普通文字。反例：删除公式或漏记公式必须使现有独立
PDF 核验因对应差异失败；未闭合定界必须拒绝导出并带原位置。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from test_delivery_evidence import SCRIPTS

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

SAMPLE = (
    "# 公式导出样例\n"
    "\n"
    "> **来源**：https://example.com/tdt-ticket02-sample\n"
    "\n"
    "相邻 $x$$\\sim$ 与数字邻接 2$\\times$3 及 $5 + x$ 合法，"
    "价格 costs $5 and $10 与单个 $100 保留。\n"
    "\n"
    "$$E=mc^2$$\n"
    "\n"
    "$$\n"
    "G(x)=1\n"
    "$$\n"
    "\n"
    "\\[H(y)=2\\]\n"
    "\n"
    "行中带尾随正文 $$Q=z$$ 尾部保留。\n"
    "\n"
    "历史包装 $\\(N\\)$ 与 $\\[D\\]$ 保持。\n"
)

EXPECTED_MATH = [
    ("inline", "dollar_inline", "x"),
    ("inline", "dollar_inline", "\\sim"),
    ("inline", "dollar_inline", "\\times"),
    ("inline", "dollar_inline", "5 + x"),
    ("display", "dollar_block", "E=mc^2"),
    ("display", "dollar_block", "G(x)=1"),
    ("display", "legacy_bracket", "H(y)=2"),
    ("display", "dollar_block", "Q=z"),
    ("inline", "legacy_paren", "N"),
    ("display", "legacy_bracket", "D"),
]


def run_cli(script, args, cwd):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)] + args,
        cwd=str(cwd), capture_output=True, text=True)


@unittest.skipIf(pymupdf is None, "PyMuPDF 不可用，PDF 数学导出测试跳过")
class PdfLiteralBracketLinkMathTest(unittest.TestCase):
    def test_adjacent_math_links_with_literal_brackets_export_and_verify(self):
        # 两组相邻行内公式不能跨标签被粗扫为 $$ 块；字面括号保留。
        with tempfile.TemporaryDirectory(prefix='pdf-literal-math-') as tmp:
            base = Path(tmp)
            sample = base / 'sample.md'
            sample.write_text(
                '# 公式链接\n\n> **来源**：https://example.com/probe\n\n'
                r'| 配对 | [\\\[$x$$y$\\\]](https://example.com/math)'
                r' | [\\\[$a*b*c$$y$\\\]](https://example.com/math) |'
                '\n| --- | --- | --- |\n', encoding='utf-8')
            pdf, work = base / 'sample.pdf', base / 'work'
            result = run_cli('export_pdf.py', [
                '--output', str(pdf), '--work-dir', str(work), str(sample)],
                base)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            result = run_cli('verify_pdf.py', [
                '--pdf', str(pdf), '--work-dir', str(work), str(sample)], base)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            with pymupdf.open(pdf) as doc:
                text = ''.join(page.get_text() for page in doc)
                self.assertEqual(text.count(r'\['), 2)
                self.assertEqual(text.count(r'\]'), 2)
                self.assertTrue(any(link.get('uri') ==
                                    'https://example.com/math'
                                    for page in doc for link in page.get_links()))
            damaged = base / 'damaged.md'
            damaged.write_text(sample.read_text().replace('$y$', '$z$', 1))
            result = run_cli('verify_pdf.py', [
                '--pdf', str(pdf), '--work-dir', str(work), str(damaged)], base)
            self.assertNotEqual(result.returncode, 0)
            failures = json.loads((work / 'verify_report.json').read_text())[
                'failures']
            self.assertTrue(any(f['code'] == 'math-record-mismatch'
                                for f in failures), failures)


@unittest.skipIf(pymupdf is None, "PyMuPDF 不可用，PDF 数学导出测试跳过")
class PdfMathExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-math-export-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(SAMPLE, encoding='utf-8')
        cls.out = cls.base / 'out'
        cls.out.mkdir()
        cls.pdf = cls.out / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]
        result = run_cli('verify_pdf.py', [
            '--pdf', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def _report(self):
        return json.loads((self.work / 'export_report.json')
                          .read_text(encoding='utf-8'))

    def test_export_and_verify_pass(self):
        report = self._report()
        self.assertEqual(report['status'], 'machine-pass-pending-visual')
        self.assertEqual(report['browser_checks']['katex'], [])

    def test_math_dom_matches_shared_scan(self):
        """数学 DOM（combined.html 的 data-tex 节点）与共享扫描的类型、
        顺序、内容一致。"""
        from bs4 import BeautifulSoup
        html = (self.work / 'combined.html').read_text(encoding='utf-8')
        nodes = BeautifulSoup(html, 'html.parser').select('[data-tex]')
        dom = [(n.get('data-mode'), n.get('data-tex')) for n in nodes]
        self.assertEqual(dom, [(mode, latex) for mode, _form, latex
                               in EXPECTED_MATH])

    def test_report_math_sequence_matches_shared_scan(self):
        report = self._report()
        math_list = [(m['mode'], m['original_form'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, EXPECTED_MATH)

    def test_pdf_product_renders_math_and_keeps_currency(self):
        """实际成品独立抽取：公式按顺序渲染为字形，价格仍是普通文字，
        原始定界不泄漏。"""
        doc = pymupdf.open(str(self.pdf))
        text = unicodedata.normalize(
            "NFKC", re.sub(r"\s+", "", "\n".join(p.get_text() for p in doc)))
        self.assertIn("costs$5and$10", text)
        self.assertIn("$100", text)
        for leak in ("$$", "$x$", "$\\sim$", "$\\times$", "$5+x$",
                     "\\[", "\\]"):
            self.assertNotIn(leak, text)
        pos = -1
        for glyph in ("x∼", "×", "5+x", "E=mc2", "G(x)=1", "H(y)=2",
                      "Q=z", "N", "D"):
            nxt = text.find(glyph, pos + 1)
            self.assertNotEqual(nxt, -1, "成品缺公式字形: %r" % glyph)
            pos = nxt

    def test_deleted_formula_fails_verify_with_attributed_diff(self):
        """删式反例：输入少一个公式，独立核验必须因对应差异（公式数量/
        证据记录）失败，不能通过。"""
        damaged = self.base / 'damaged.md'
        damaged.write_text(
            SAMPLE.replace("$x$$\\sim$", "$x$"), encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(damaged)], self.base)
        self.assertNotEqual(result.returncode, 0)
        codes = {f['code'] for f in json.loads(
            (self.work / 'verify_report.json').read_text(encoding='utf-8')
        )['failures']}
        self.assertIn('math-count-mismatch', codes)
        self.assertIn('math-record-mismatch', codes)

    def test_dropped_recorded_math_fails_verify(self):
        """漏渲染反例：导出证据少记一个公式（成品 DOM 事实缺失），
        核验必须因 math-record-mismatch 失败。"""
        report_path = self.work / 'export_report.json'
        report = self._report()
        report['chapters'][0]['math'] = [
            m for m in report['chapters'][0]['math'] if m['latex'] != "\\sim"]
        report_path.write_text(json.dumps(report, ensure_ascii=False),
                               encoding='utf-8')
        try:
            result = run_cli('verify_pdf.py', [
                '--pdf', str(self.pdf), '--work-dir', str(self.work),
                str(self.sample)], self.base)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('math-record-mismatch', result.stderr)
        finally:
            result = run_cli('export_pdf.py', [
                '--output', str(self.pdf), '--work-dir', str(self.work),
                str(self.sample)], self.base)
            assert result.returncode == 0, result.stderr[-400:]

    def test_unresolved_delimiter_blocks_export_with_location(self):
        """未闭合定界反例：导出就绪拒绝、带原位置、不覆盖既有成品。"""
        bad = self.base / 'unclosed.md'
        bad.write_text(
            "# 坏样例\n\n> **来源**：https://example.com/tdt-ticket02-bad\n\n"
            "正文 $x 未闭合。\n", encoding='utf-8')
        keep = self.out / 'keep.pdf'
        keep.write_bytes(b'PREEXISTING-OK-PDF')
        result = run_cli('export_pdf.py', [
            '--output', str(keep), '--work-dir', str(self.base / 'work_bad'),
            str(bad)], self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未解决数学定界', result.stderr)
        self.assertIn('unclosed.md', result.stderr)
        self.assertRegex(result.stderr, r'L\d+')
        self.assertEqual(keep.read_bytes(), b'PREEXISTING-OK-PDF')
        report = json.loads((self.base / 'work_bad' / 'export_report.json')
                            .read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'machine-fail')

    def test_unresolved_delimiter_fails_verify(self):
        """未闭合定界反例：核验入口同样带原位置拒绝。"""
        bad = self.base / 'unclosed_verify.md'
        bad.write_text(
            "# 坏样例\n\n> **来源**：https://example.com/tdt-ticket02-bad\n\n"
            "正文 $x 未闭合。\n", encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(bad)], self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('input-parse-blocked', result.stderr)
        self.assertIn('未解决数学定界', result.stderr)


LIST_SAMPLE = (
    "# 列表公式样例\n"
    "\n"
    "> **来源**：https://example.com/tdt-r7-list\n"
    "\n"
    "- 项内多行公式 $$E =\n"
    "  mc^2$$ 与后续 $x$ 行内公式。\n"
    "\n"
    "- 独立块级：\n"
    "  $$\n"
    "  G(y)=1\n"
    "  $$\n"
    "  后文 $\\alpha$ 结尾。\n"
    "\n"
    "正文引导\n"
    "$$\n"
    "Q=z\n"
    "$$\n"
    "后续 $w$ 结束。\n"
)

LIST_EXPECTED = [
    ("display", "dollar_block", "E =\n  mc^2"),
    ("inline", "dollar_inline", "x"),
    ("display", "dollar_block", "G(y)=1"),
    ("inline", "dollar_inline", "\\alpha"),
    ("display", "dollar_block", "Q=z"),
    ("inline", "dollar_inline", "w"),
]


@unittest.skipIf(pymupdf is None, "PyMuPDF 不可用，PDF 数学导出测试跳过")
class PdfMathListContainerTests(unittest.TestCase):
    """R7：列表等容器剥离缩进不得阻塞公式消费（有序游标 + raw 对齐）。

    列表项内一个多行公式（非独立块级走行内规则、独立块级走块级规则）
    与其后续公式都必须进入数学 DOM，类型/顺序/内容与共享扫描一致。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-math-list-'))
        cls.sample = cls.base / 'list.md'
        cls.sample.write_text(LIST_SAMPLE, encoding='utf-8')
        cls.pdf = cls.base / 'list.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def _report(self):
        return json.loads((self.work / 'export_report.json')
                          .read_text(encoding='utf-8'))

    def test_list_math_enters_dom_with_order_and_content(self):
        from bs4 import BeautifulSoup
        html = (self.work / 'combined.html').read_text(encoding='utf-8')
        nodes = BeautifulSoup(html, 'html.parser').select('[data-tex]')
        dom = [(n.get('data-mode'), n.get('data-tex')) for n in nodes]
        self.assertEqual(dom, [(mode, latex) for mode, _form, latex
                               in LIST_EXPECTED])

    def test_list_math_report_sequence_matches_shared_scan(self):
        report = self._report()
        math_list = [(m['mode'], m['original_form'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, LIST_EXPECTED)

    def test_list_export_verify_passes(self):
        """真实导出后独立核验全绿（含成品数学证据重读）。"""
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(self.sample)], self.base)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])


@unittest.skipIf(pymupdf is None, "PyMuPDF 不可用，PDF 数学导出测试跳过")
class PdfMathProductMissingTests(unittest.TestCase):
    """R8：核验必须独立重读实际 PDF 成品。打印漏画公式（成品无公式）
    而导出证据未改时，必须因成品缺数学渲染证据失败，不以渲染器报告自证。"""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-math-r8-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(SAMPLE, encoding='utf-8')
        cls.pdf = cls.base / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def test_product_without_math_fails_verify(self):
        """用删去公式的输入打印无公式 PDF，保留原报告（仅修正 sha 绑定
        以隔离新核验）：重建清单与证据一致、浏览器计数一致，唯一差异是
        成品没有公式——必须按 pdf-math-missing 失败并定位到输入。"""
        no_math = self.base / 'no_math.md'
        no_math.write_text(
            "# 公式导出样例\n\n"
            "> **来源**：https://example.com/tdt-ticket02-sample\n\n"
            "相邻与数字邻接及价格文字保留，公式整段删去。\n",
            encoding='utf-8')
        bare_pdf = self.base / 'bare.pdf'
        bare_work = self.base / 'work_bare'
        result = run_cli('export_pdf.py', [
            '--output', str(bare_pdf), '--work-dir', str(bare_work),
            str(no_math)], self.base)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        self.assertTrue(report['chapters'][0]['math'])
        report['pdf_sha256'] = exporter_sha256(bare_pdf)
        tampered_work = self.base / 'work_tampered'
        tampered_work.mkdir()
        (tampered_work / 'export_report.json').write_text(
            json.dumps(report, ensure_ascii=False), encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(bare_pdf), '--work-dir', str(tampered_work),
            str(self.sample)], self.base)
        self.assertNotEqual(result.returncode, 0)
        failures = json.loads(
            (tampered_work / 'verify_report.json').read_text(
                encoding='utf-8'))['failures']
        codes = {f['code']: f for f in failures}
        self.assertIn('pdf-math-missing', codes)
        self.assertIn(str(self.sample), codes['pdf-math-missing'].get(
            'input', ''))


def exporter_sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


FOOTNOTE_SAMPLE = (
    "# 脚注公式\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "正文引用脚注[^a]。\n"
    "\n"
    "[^a]: 脚注内公式 $x$。\n"
    "\n"
    "后续正文公式 $y$。\n"
)

FOOTNOTE_ORDER_SWAP = (
    "# 变体\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "先引用[^b]再引用[^a]。\n"
    "\n"
    "[^a]: 注 A 公式 $p$。\n"
    "\n"
    "[^b]: 注 B 公式 $r$。\n"
    "\n"
    "正文末尾 $z$。\n"
)

FOOTNOTE_MULTI = (
    "# 多公式脚注\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "引用[^m]。\n"
    "\n"
    "[^m]: 第一式 $a$。\n"
    "\n"
    "    续段第二式 $b$。\n"
    "\n"
    "正文 $c$。\n"
)

FORMULA_FAKE_REF = (
    "# 公式脚注\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "Formula $[^b]$ then actual [^a] and [^b].\n"
    "\n"
    "Body $y$.\n"
    "\n"
    "[^a]: note $x$.\n"
    "\n"
    "[^b]: note $z$.\n"
)

FOOTNOTE_BLOCK_BLANK = (
    "# 公式脚注\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "Body $y$ ref [^a].\n"
    "\n"
    "[^a]: note\n"
    "\n"
    "    $$\n"
    "    x\n"
    "\n"
    "    +z\n"
    "    $$\n"
    "\n"
    "    tail $r$.\n"
    "\n"
    "Body $w$.\n"
)


def _unmasked_footnote_extents(text):
    """独立期望：不做公式掩蔽的 footnote 插件结构重读（ tail 段 map →
    原定义区间，段顺序即首次引用序）。用于验证核验侧保护处理本身不改变
    脚注结构，而不是复制被测函数的实现。"""
    from markdown_it import MarkdownIt
    from mdit_py_plugins.footnote import footnote_plugin
    markdown = MarkdownIt("commonmark", {"html": False})
    markdown.enable("table")
    markdown.use(footnote_plugin)
    tokens = markdown.parse(text, {})
    line_starts = [0]
    for match in re.finditer("\n", text):
        line_starts.append(match.end())
    extents = []
    current = None
    for token in tokens:
        if token.type == "footnote_open":
            current = []
            extents.append(current)
        elif token.type == "footnote_close":
            current = None
        elif current is not None and token.map:
            current.append(tuple(token.map))
    result = []
    for maps in extents:
        if not maps:
            continue
        start = line_starts[min(m[0] for m in maps)]
        end_line = max(m[1] for m in maps)
        end = (line_starts[end_line] if end_line < len(line_starts)
               else len(text))
        result.append((start, end))
    return result


class PdfFootnoteMathTests(unittest.TestCase):
    """Ticket 03（提交前评审 R2）：脚注定义移到章末是合法交付投影。

    脚注定义 $x$ 写在后续正文 $y$ 前：既有插件按首次引用序把定义移到
    章末，合法渲染序 y/x 与源序 x/y 不同，真实导出与独立核验均须成功。
    逐式类型、原表达式、出现次数与所属序列内顺序核验保持：正文或同一
    脚注内删式、改式、换序仍按目标原因拒绝。核验只依赖声明的 PDF 导出
    依赖（本类不需要 pymupdf）。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-footnote-math-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(FOOTNOTE_SAMPLE, encoding='utf-8')
        cls.pdf = cls.base / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]
        result = run_cli('verify_pdf.py', [
            '--pdf', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def _export_verify(self, name, text):
        doc = self.base / name
        doc.write_text(text, encoding='utf-8')
        pdf = self.base / ('%s.pdf' % name)
        work = self.base / ('work-%s' % name)
        result = run_cli('export_pdf.py', [
            '--output', str(pdf), '--work-dir', str(work), str(doc)],
            self.base)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        result = run_cli('verify_pdf.py', [
            '--pdf', str(pdf), '--work-dir', str(work), str(doc)],
            self.base)
        return doc, pdf, work, result

    def test_render_order_is_legal_projection(self):
        """渲染序 y/x（定义移章末），两式均实际渲染，核验通过。"""
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [(m['mode'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, [('inline', 'y'), ('inline', 'x')])
        self.assertEqual(
            report['browser_checks'].get('mathTotal'), 2)

    def test_definition_reference_order_swap_variant(self):
        """定义顺序与引用顺序不同：按首次引用序投影（z, r, p）。"""
        doc, _pdf, work, result = self._export_verify(
            'order-swap.md', FOOTNOTE_ORDER_SWAP)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        report = json.loads((work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [m['latex'] for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, ['z', 'r', 'p'])

    def test_multi_math_footnote_variant(self):
        """多公式脚注（含缩进续段）：定义内源序保持（c, a, b）。"""
        doc, _pdf, work, result = self._export_verify(
            'multi.md', FOOTNOTE_MULTI)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        report = json.loads((work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [m['latex'] for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, ['c', 'a', 'b'])

    def test_deleted_body_or_footnote_math_fails(self):
        """正文删式与脚注内删式：数量/证据记录差异拒绝。"""
        for name, damaged_text in (
                ('del-body.md',
                 FOOTNOTE_SAMPLE.replace('后续正文公式 $y$。', '后续正文公式。')),
                ('del-footnote.md',
                 FOOTNOTE_SAMPLE.replace('脚注内公式 $x$。', '脚注内公式。'))):
            damaged = self.base / name
            damaged.write_text(damaged_text, encoding='utf-8')
            result = run_cli('verify_pdf.py', [
                '--pdf', str(self.pdf), '--work-dir', str(self.work),
                str(damaged)], self.base)
            self.assertNotEqual(result.returncode, 0, name)
            codes = {f['code'] for f in json.loads(
                (self.work / 'verify_report.json').read_text(
                    encoding='utf-8'))['failures']}
            self.assertIn('math-record-mismatch', codes, name)

    def test_changed_or_swapped_footnote_math_fails(self):
        """脚注内改式（x→w）与同一脚注内换序（a/b 互换）拒绝。"""
        changed = self.base / 'changed.md'
        changed.write_text(FOOTNOTE_SAMPLE.replace('$x$', '$w$'),
                           encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(changed)], self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('math-record-mismatch', result.stderr)
        # 同一脚注内换序：先按未损伤多公式脚注导出，再核验换序输入。
        doc, _pdf, work, result = self._export_verify(
            'multi-swap-base.md', FOOTNOTE_MULTI)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        swapped = self.base / 'swapped.md'
        swapped.write_text(
            FOOTNOTE_MULTI.replace('第一式 $a$。', '第一式 $b$。')
            .replace('续段第二式 $b$。', '续段第二式 $a$。'),
            encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(_pdf), '--work-dir', str(work),
            str(swapped)], self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('math-record-mismatch', result.stderr)


class PdfFormulaFootnoteNotationTests(unittest.TestCase):
    """Ticket 03（复评 P2-1）：公式内部记法不是真实脚注引用。

    合法公式 $[^b]$ 内的记法不得被脚注结构重读当成脚注 b 的首次引用；
    正确公式序列为 [^b]、y、x、z（真实引用序 a→b）。保护处理复用共享
    扫描的公式跨度等长掩蔽，本身不改变脚注结构。核验只依赖声明的 PDF
    导出依赖（本类不需要 pymupdf）。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-formula-ref-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(FORMULA_FAKE_REF, encoding='utf-8')
        cls.pdf = cls.base / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]
        result = run_cli('verify_pdf.py', [
            '--pdf', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def test_formula_sequence_and_render_count(self):
        """期望公式序列 [^b]、y、x、z 逐项一致，四式实际渲染。"""
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [(m['mode'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, [('inline', '[^b]'), ('inline', 'y'),
                                     ('inline', 'x'), ('inline', 'z')])
        self.assertEqual(report['browser_checks'].get('mathTotal'), 4)

    def test_masking_preserves_footnote_structure(self):
        """保护处理本身不改变脚注结构：不含脚注记法的既有脚注输入，
        掩蔽后重读的定义区间/引用序与独立未掩蔽插件解析一致。"""
        import verify_pdf
        for text in (FOOTNOTE_SAMPLE, FOOTNOTE_ORDER_SWAP, FOOTNOTE_MULTI,
                     FORMULA_FAKE_REF.replace('$[^b]$', '$q$')):
            self.assertEqual(verify_pdf._footnote_render_extents(text),
                             _unmasked_footnote_extents(text))

    def test_damaged_formula_rejected(self):
        """删去含记法公式：核验仍按目标差异（证据记录/数量）拒绝。"""
        damaged = self.base / 'damaged.md'
        damaged.write_text(FORMULA_FAKE_REF.replace(
            'Formula $[^b]$ then', 'Formula then'), encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(damaged)], self.base)
        self.assertNotEqual(result.returncode, 0)
        codes = {f['code'] for f in json.loads(
            (self.work / 'verify_report.json').read_text(
                encoding='utf-8'))['failures']}
        self.assertIn('math-record-mismatch', codes)


class PdfFootnoteBlockBlankTests(unittest.TestCase):
    """Ticket 03（P2-1 回归，2026-10-07 最新评审）：公式内的空白行与
    缩进续段是结构事实。

    脚注定义内含带空白行的多行 $$ 公式，其后缩进续段与定义末段
    tail $r$. 同属该定义；掩蔽若把公式内缩进擦除，定义区间被提前
    截断，tail $r$ 被误当正文。合法交付顺序为正文 inline y、inline w
    + 脚注 display x+z、inline r（表达式沿用原合同，不归一内部空白）。
    核验只依赖声明的 PDF 导出依赖（本类不需要 pymupdf）。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-footnote-blank-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(FOOTNOTE_BLOCK_BLANK, encoding='utf-8')
        cls.pdf = cls.base / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]
        result = run_cli('verify_pdf.py', [
            '--pdf', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def test_delivery_sequence_and_render_count(self):
        """交付序为正文 y、w + 脚注 display x+z、inline r，四式渲染。"""
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [(m['mode'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, [('inline', 'y'), ('inline', 'w'),
                                     ('display', 'x\n\n    +z'),
                                     ('inline', 'r')])
        self.assertEqual(report['browser_checks'].get('mathTotal'), 4)

    def test_masking_preserves_definition_extent(self):
        """结构保持以独立未掩蔽插件解析为期望：唯一定义区间覆盖
        display 公式与 tail $r$.，正文 y/w 在区间外。"""
        import verify_pdf
        from _verification import scan_math
        extents = verify_pdf._footnote_render_extents(FOOTNOTE_BLOCK_BLANK)
        self.assertEqual(extents,
                         _unmasked_footnote_extents(FOOTNOTE_BLOCK_BLANK))
        (start, end), = extents
        spans = scan_math(FOOTNOTE_BLOCK_BLANK).spans
        inside = [s.kind for s in spans if start <= s.start < end]
        outside = [s.expr for s in spans if not start <= s.start < end]
        self.assertEqual(inside, ['block', 'inline'])
        self.assertEqual(outside, ['y', 'w'])

    def test_damaged_variants_rejected(self):
        """正文及同一脚注内删式、改式、换序仍按目标原因拒绝。"""
        swapped = FOOTNOTE_BLOCK_BLANK.replace(
            "    $$\n    x\n\n    +z\n    $$\n\n    tail $r$.\n",
            "    tail $r$.\n\n    $$\n    x\n\n    +z\n    $$\n")
        assert swapped != FOOTNOTE_BLOCK_BLANK
        for name, damaged_text in (
                ('del-body.md',
                 FOOTNOTE_BLOCK_BLANK.replace('Body $w$.', 'Body.')),
                ('del-tail.md',
                 FOOTNOTE_BLOCK_BLANK.replace('    tail $r$.\n', '')),
                ('change-tail.md',
                 FOOTNOTE_BLOCK_BLANK.replace('$r$', '$q$')),
                ('swap-in-footnote.md', swapped)):
            damaged = self.base / name
            damaged.write_text(damaged_text, encoding='utf-8')
            result = run_cli('verify_pdf.py', [
                '--pdf', str(self.pdf), '--work-dir', str(self.work),
                str(damaged)], self.base)
            self.assertNotEqual(result.returncode, 0, name)
            codes = {f['code'] for f in json.loads(
                (self.work / 'verify_report.json').read_text(
                    encoding='utf-8'))['failures']}
            self.assertIn('math-record-mismatch', codes, name)


GLYPH_SAMPLE = (
    "# 字形证据样例\n"
    "\n"
    "> **来源**：https://example.com/probe\n"
    "\n"
    "正文公式 $x$ 与 $y$ 结尾。\n"
)


class PdfMathGlyphsStrippedTests(unittest.TestCase):
    """Ticket 03（复评 P2-2）：字体资源与布局不能单独证明公式存在。

    从真实成品删除全部 KaTeX 绘字运算、保留字体资源与布局（pypdf 会
    为布局合成携带 KaTeX 字体的换行段），仅更新报告 PDF 摘要以隔离
    摘要绑定检查，源输入、公式记录与浏览器记录不变：核验必须按
    pdf-math-missing 定位拒绝，不能借其他失败代替目标检查。只使用
    已声明的 PDF 导出依赖（pypdf），不引入 pymupdf。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='pdf-glyphs-stripped-'))
        cls.sample = cls.base / 'sample.md'
        cls.sample.write_text(GLYPH_SAMPLE, encoding='utf-8')
        cls.pdf = cls.base / 'sample.pdf'
        cls.work = cls.base / 'work'
        result = run_cli('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            str(cls.sample)], cls.base)
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def test_legal_product_passes(self):
        """正常对照：合法真实成品仍通过。"""
        result = run_cli('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            str(self.sample)], self.base)
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)

    def test_stripped_glyphs_fail_with_pdf_math_missing(self):
        import pypdf
        from pypdf.generic import ContentStream
        writer = pypdf.PdfWriter(clone_from=str(self.pdf))
        removed = 0
        kept_fonts = 0
        for page in writer.pages:
            fonts = page['/Resources'].get('/Font', {})
            katex = {name for name, ref in fonts.items()
                     if 'KaTeX' in str(ref.get_object().get('/BaseFont', ''))}
            kept_fonts += len(katex)
            content = ContentStream(page.get_contents(), writer)
            font = None
            ops = []
            for operands, operator in content.operations:
                if operator == b'Tf':
                    font = operands[0]
                if font in katex and operator in (b'Tj', b'TJ', b"'", b'"'):
                    removed += 1
                    continue
                ops.append((operands, operator))
            content.operations = ops
            page.replace_contents(content)
            # 构造保证：移除后本页不再有 KaTeX 字体绘字运算
            font = None
            for operands, operator in ContentStream(
                    page.get_contents(), writer).operations:
                if operator == b'Tf':
                    font = operands[0]
                elif font in katex and operator in (b'Tj', b'TJ', b"'", b'"'):
                    self.fail('移除后仍残留 KaTeX 绘字运算')
        # 样例含两条公式，确有绘字被移除；字体资源与布局保留
        self.assertGreater(removed, 0)
        self.assertGreater(kept_fonts, 0)
        stripped = self.base / 'stripped.pdf'
        with stripped.open('wb') as f:
            writer.write(f)
        # 仅更新报告 PDF 摘要以隔离摘要绑定检查；源输入、公式记录与
        # 浏览器记录不变
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        original = dict(report)
        self.assertTrue(report['chapters'][0]['math'])
        report['pdf_sha256'] = exporter_sha256(stripped)
        self.assertEqual([k for k in report if report[k] != original[k]],
                         ['pdf_sha256'])
        tampered_work = self.base / 'work_stripped'
        tampered_work.mkdir()
        (tampered_work / 'export_report.json').write_text(
            json.dumps(report, ensure_ascii=False), encoding='utf-8')
        result = run_cli('verify_pdf.py', [
            '--pdf', str(stripped), '--work-dir', str(tampered_work),
            str(self.sample)], self.base)
        self.assertNotEqual(result.returncode, 0)
        codes = {f['code'] for f in json.loads(
            (tampered_work / 'verify_report.json').read_text(
                encoding='utf-8'))['failures']}
        self.assertIn('pdf-math-missing', codes)
        # 不借其他失败代替目标检查：记录与计数口径均未变
        self.assertNotIn('math-record-mismatch', codes)
        self.assertNotIn('math-count-mismatch', codes)


if __name__ == '__main__':
    unittest.main()
