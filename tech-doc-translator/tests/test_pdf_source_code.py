"""代码 golden 提取、源围栏物化与逐字节核验的外部行为验收。

fixture 在测试时用 PyMuPDF 生成真实 PDF（courier 等宽字体），覆盖：
缩进/空行重建、区域外页眉排除、六种损伤（改字符、弯引号、缩进、
换块、行尾空格）各自 FAIL 并定位；golden ↔ 块显式对应。
"""
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
    raise unittest.SkipTest("PyMuPDF 不可用，整组 PDF 源代码 golden 测试跳过")

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
PREPARE = SCRIPTS / 'prepare_pdf_source.py'
VERIFY = SCRIPTS / 'verify_pdf_source.py'

CODE_ONE = ["import torch",
            "def f(x):",
            "    return x + 1  # 'quote'",
            "",
            "print(f(2))"]
CODE_TWO = ["class Model:",
            "    pass"]


def run_cli(script, *args):
    return subprocess.run([sys.executable, str(script)]
                          + [str(a) for a in args],
                          capture_output=True, text=True)


class PdfSourceCodeGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root

        doc = pymupdf.open()
        page = doc.new_page(width=400, height=500)
        # 区域外页眉：必须在 golden 之外
        page.insert_text((40, 35), "Running head must stay out",
                         fontsize=10)
        y = 70
        for line in CODE_ONE:
            if line:
                page.insert_text((60, y), line, fontsize=10,
                                 fontname="courier")
            y += 14
        y = 320
        for line in CODE_TWO:
            page.insert_text((60, y), line, fontsize=10, fontname="courier")
            y += 14
        doc.save(root / 'code.pdf')
        doc.close()
        cls.pdf = root / 'code.pdf'

        cls.inspect_dir = root / 'inspect'
        result = run_cli(PREPARE, 'inspect', cls.pdf, '--pages', 'all',
                         '--output', cls.inspect_dir)
        assert result.returncode == 0, result.stderr
        cls.checklist = cls.inspect_dir / 'adjudication_checklist.json'
        payload = json.loads(cls.checklist.read_text(encoding='utf-8'))
        payload['blocks'] = [
            {'id': 'b001', 'order': 1, 'type': 'code_region', 'page': 1,
             'rect': [40, 50, 390, 150], 'golden': 'golden/one.txt',
             'lang': 'python',
             'adjudication': {'status': 'accepted', 'basis': '代码区一'}},
            {'id': 'b002', 'order': 2, 'type': 'code_region', 'page': 1,
             'rect': [40, 300, 390, 350], 'golden': 'golden/two.txt',
             'lang': 'python',
             'adjudication': {'status': 'accepted', 'basis': '代码区二'}},
        ]
        payload['reading_order'] = {'adjudicated': True,
                                    'basis': '单栏顺序'}
        cls.checklist.write_text(json.dumps(payload, ensure_ascii=False),
                                 encoding='utf-8')

        result = run_cli(PREPARE, 'extract-code', cls.pdf,
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

    def test_golden_preserves_indent_blank_and_excludes_header(self):
        one = (self.inspect_dir / 'golden/one.txt').read_text(encoding='utf-8')
        two = (self.inspect_dir / 'golden/two.txt').read_text(encoding='utf-8')
        # 行首缩进按 char 偏移重建（4 空格）
        self.assertIn("    return x + 1  # 'quote'", one)
        self.assertIn("    pass", two)
        # 文本层不产出空行：按行距重建区域内空行
        self.assertIn("return x + 1  # 'quote'\n\nprint(f(2))", one)
        # 区域外页眉不进入基准
        self.assertNotIn("Running head", one + two)
        # 弯引号原样保留为字符内容
        self.assertIn("'quote'", one)
        # 清单回写 golden 摘要与提取取舍（块 id ↔ golden 显式对应）
        payload = json.loads(self.checklist.read_text(encoding='utf-8'))
        for block, name in ((payload['blocks'][0], 'one'),
                            (payload['blocks'][1], 'two')):
            self.assertEqual(block['golden'], 'golden/%s.txt' % name)
            self.assertEqual(len(block['golden_sha256']), 64)
            self.assertIn('char_width_pt', block['golden_extraction'])

    def test_materialize_fences_from_golden(self):
        text = self.md.read_text(encoding='utf-8')
        self.assertIn("```python\nimport torch\ndef f(x):", text)
        self.assertIn("class Model:", text)
        self.assertNotIn('[PENDING-CODE', text)

    def test_verify_passes_byte_exact(self):
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

    def _first_fence_line(self, lines, needle):
        return next(i for i, ln in enumerate(lines) if needle in ln)

    def test_changed_char_fails_with_location(self):
        result = self._damaged(
            'dmg_char.md',
            lambda ls: ls.__setitem__(
                self._first_fence_line(ls, 'return x + 1'),
                ls[self._first_fence_line(ls, 'return x + 1')].replace(
                    'x + 1', 'x + 2')))
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)
        self.assertIn('第 3 行', result.stderr)

    def test_curly_quote_fails(self):
        def curly(ls):
            i = self._first_fence_line(ls, "'quote'")
            ls[i] = ls[i].replace("'quote'", '’quote’')
        result = self._damaged('dmg_curly.md', curly)
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)

    def test_indent_change_fails(self):
        def dedent(ls):
            i = self._first_fence_line(ls, 'return x + 1')
            ls[i] = ls[i].replace('    return', '  return')
        result = self._damaged('dmg_indent.md', dedent)
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)

    def test_swapped_code_blocks_fail(self):
        def swap(ls):
            # 同位置互换两块围栏的首行（换块，行结构不变）
            a = self._first_fence_line(ls, 'import torch')
            b = self._first_fence_line(ls, 'class Model:')
            ls[a], ls[b] = ls[b], ls[a]
        result = self._damaged('dmg_swap.md', swap)
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)
        self.assertIn('b001', result.stderr)
        self.assertIn('b002', result.stderr)

    def test_trailing_space_fails(self):
        def trailing(ls):
            i = self._first_fence_line(ls, 'import torch')
            ls[i] = ls[i] + ' '
        result = self._damaged('dmg_trailing.md', trailing)
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)
        self.assertIn('import torch', result.stderr)


if __name__ == '__main__':
    unittest.main()


class CodeGoldenLineEndingTests(unittest.TestCase):
    """R3/A3 逐字节口径：golden LF vs 围栏正文 CRLF 必须 FAIL 定位。"""

    def setUp(self):
        PdfSourceCodeGoldenTests.setUpClass()
        self.root = PdfSourceCodeGoldenTests.root
        self.pdf = PdfSourceCodeGoldenTests.pdf
        self.checklist = PdfSourceCodeGoldenTests.checklist
        self.md = PdfSourceCodeGoldenTests.md

    def test_crlf_fence_body_fails_against_lf_golden(self):
        damaged = self.root / 'crlf.md'
        shutil.copyfile(self.md, damaged)
        shutil.copyfile(str(self.md) + '.blocks.json',
                        str(damaged) + '.blocks.json')
        text = damaged.read_bytes()
        # 仅把第一个围栏正文（golden/one.txt 内容）换成 CRLF 行尾
        lines = text.split(b'\n')
        out = []
        in_target = False
        for ln in lines:
            if ln == b'import torch':
                in_target = True
            if in_target and ln.strip():
                out.append(ln + b'\r')
                if ln.startswith(b'print(f(2))'):
                    in_target = False
                continue
            out.append(ln)
        damaged.write_bytes(b'\n'.join(out))
        result = run_cli(VERIFY, self.pdf, '--checklist', self.checklist,
                         '--source-md', damaged)
        self.assertEqual(result.returncode, 1)
        self.assertIn('逐字节不一致', result.stderr)
