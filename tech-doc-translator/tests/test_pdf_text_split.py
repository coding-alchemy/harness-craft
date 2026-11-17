# coding: utf-8
"""R1：片段被数学字形或页缝分成两段时登记 relaxed，缺字、换字、乱序仍失败。"""
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import verify_pdf as verifier


class FakePdf:
    """只提供 check_blocks 与 split_match 用到的字段。"""

    def __init__(self, pages):
        self.pages = pages
        self.norm_text = ''.join(pages)
        self.page_offsets, position = [], 0
        for page in pages:
            self.page_offsets.append((position, position + len(page)))
            position += len(page)

    def find(self, needle, start):
        return self.norm_text.find(needle, start)

    def page_of_offset(self, offset):
        for index, (start, end) in enumerate(self.page_offsets):
            if start <= offset < end:
                return index
        return len(self.page_offsets) - 1


MATH = 'φhK̂hσ' * 160          # 800 字的字形串，超过 4×段长+60 的预算
SENTENCE = '由于注意力复杂度按序列长度平方增长'


def run(pages, segment=SENTENCE):
    chapter = SimpleNamespace(path='ch.md', blocks=[{'segments': [segment]}])
    pdf = FakePdf(pages)
    failures, relaxed = [], []
    verifier.check_blocks([chapter], pdf, [(chapter, 0, len(pages))],
                          failures, relaxed, 'text')
    return failures, relaxed


class SplitMatchTest(unittest.TestCase):
    def test_page_seam_with_trailing_math_is_relaxed(self):
        failures, relaxed = run(['前文' + '由' + MATH, '于注意力复杂度按序列长度平方增长后文'])
        self.assertEqual(failures, [])
        self.assertEqual(len(relaxed), 1)
        self.assertIn('第 1→2 页', relaxed[0]['reason'])

    def test_same_page_long_interleave_is_relaxed(self):
        failures, relaxed = run(['由于注意力' + MATH + '复杂度按序列长度平方增长'])
        self.assertEqual(failures, [])
        self.assertIn('第 1→1 页', relaxed[0]['reason'])

    def test_missing_char_fails(self):
        failures, _ = run(['由' + MATH, '于注意力复杂度按序列长度平方增'])
        self.assertEqual([f['code'] for f in failures], ['text-missing'])

    def test_swapped_halves_fail(self):
        failures, _ = run(['于注意力复杂度按序列长度平方增长' + MATH, '由'])
        self.assertEqual([f['code'] for f in failures], ['text-missing'])

    def test_tail_beyond_next_page_fails(self):
        failures, _ = run(['由' + MATH, MATH, '于注意力复杂度按序列长度平方增长'])
        self.assertEqual([f['code'] for f in failures], ['text-missing'])

    def test_short_needle_does_not_borrow_far_text(self):
        # 评审重点 1：两字片段，前后段分别只在相隔两页处出现
        failures, _ = run(['甲' + MATH, MATH, '乙'], segment='甲乙')
        self.assertEqual([f['code'] for f in failures], ['text-missing'])

    def test_split_rejects_missing_char_with_repeated_head(self):
        # 评审重点 2：前段“由于”在页内重复，真实缺“度”字
        failures, _ = run(['由于' + MATH + '由于注意力复杂按序列长度平方增长'])
        self.assertEqual([f['code'] for f in failures], ['text-missing'])


class StandaloneAnchorBeforeSuperscriptTest(unittest.TestCase):
    """E1 H.3：独立锚点段之后紧跟首行含上标数学的段落。"""

    def test_export_and_verify_pass(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='anchor-sup-') as temp:
            root = Path(temp)
            doc = root / 'chapter.md'
            doc.write_text(
                '# 锚点\n\n> **来源**：https://example.org/anchor-sup\n\n'
                '见[释文](#S3.p2)。\n\n<a id="S3.p2"></a>\n\n'
                '其中 $\\phi^{h}$ 与 $\\hat{K}^{h}$ 分别为第 $h$ 个头的投影与键矩阵，'
                '二者共同决定注意力权重。\n', encoding='utf-8')
            scripts = Path(verifier.__file__).parent
            for script, flag in (('export_pdf.py', '--output'), ('verify_pdf.py', '--pdf')):
                result = subprocess.run([sys.executable, str(scripts / script), flag,
                    str(root / 'chapter.pdf'), '--work-dir', str(root / 'work'), str(doc)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
