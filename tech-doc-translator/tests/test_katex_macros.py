# coding: utf-8
"""R5：宏表经 JSON 注入 KaTeX，data-tex 不变；只渲染公式一次列全失败。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter

SCRIPTS = Path(exporter.__file__).parent
DOC = ('# 宏表\n\n> **来源**：https://example.org/katex-macros\n\n'
       '权重为 $p_{u}\\leftarrow\\textsc{SLWeight}(n_{u};\\alpha)$，'
       '另有 $\\text{Att}_{\\textsc{Composite}}$ 与 $x^{2}$。\n')


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'), *args],
                          capture_output=True, text=True)


class KatexMacrosTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='katex-macros-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.doc = self.root / 'chapter.md'
        self.doc.write_text(DOC, encoding='utf-8')
        self.macros = self.root / 'macros.json'
        self.macros.write_text(json.dumps({'\\textsc': '\\text'}), encoding='utf-8')

    def test_without_macros_export_fails_with_hint(self):
        result = run('--output', str(self.root / 'a.pdf'), '--work-dir',
                     str(self.root / 'w1'), str(self.doc))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Undefined control sequence', result.stderr)
        self.assertIn('--katex-macros', result.stderr)

    def test_with_macros_export_passes_and_records(self):
        result = run('--output', str(self.root / 'b.pdf'), '--work-dir', str(self.root / 'w2'),
                     '--katex-macros', str(self.macros), str(self.doc))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.root / 'w2/export_report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['katex_macros']['macros'], {'\\textsc': '\\text'})
        verify = subprocess.run([sys.executable, str(SCRIPTS / 'verify_pdf.py'), '--pdf',
                                 str(self.root / 'b.pdf'), '--work-dir', str(self.root / 'w2'),
                                 str(self.doc)], capture_output=True, text=True)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_check_math_lists_all_failures(self):
        result = run('--check-math', str(self.doc))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.count('[katex-error]'), 2, result.stdout)
        for line in result.stdout.splitlines():
            if line.startswith('[katex-error]'):
                self.assertRegex(line, r'\[katex-error\] \S+:\d+ ')
        self.assertIn('公式 3 个，渲染失败 2 个', result.stdout)
        ok = run('--check-math', '--katex-macros', str(self.macros), str(self.doc))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_bad_macros_file_rejected(self):
        bad = self.root / 'bad.json'
        bad.write_text('["\\\\textsc"]', encoding='utf-8')
        result = run('--check-math', '--katex-macros', str(bad), str(self.doc))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('宏表格式无效', result.stderr)

    def test_macros_json_cannot_close_script(self):
        # 评审重点 5
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        html = exporter.build_document([chapter], 'T',
                                       katex_macros={'\\evil': '</script><b>x'})
        self.assertNotIn('</script><b>', html)
        self.assertIn('<\\/script>', html)

    def test_check_math_uses_source_adaptation(self):
        # 设计 §7.2：带来源依据时公式按来源类型渲染，行内 split 须报错
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from latexml_test_support import current_candidate
        raw = ('<article class="ltx_document"><h1 class="ltx_title">T</h1>'
               '<p class="ltx_p">Loss is '
               '<math alttext="\\begin{split}a&amp;=b\\\\&amp;=c\\end{split}" display="inline">'
               '<mi>a</mi></math> here.</p></article>')
        md, payload = current_candidate(self.root, raw)
        doc = self.root / 'split.md'
        doc.write_text(md, encoding='utf-8')
        adaptation = self.root / 'split-adaptation.json'
        adaptation.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        plain = run('--check-math', str(doc))
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        confirmed = run('--check-math', '--source-adaptation', str(adaptation), str(doc))
        self.assertEqual(confirmed.returncode, 1, confirmed.stdout + confirmed.stderr)
        self.assertIn('can be used only in display mode', confirmed.stdout)
        self.assertIn('公式 1 个，渲染失败 1 个', confirmed.stdout)


if __name__ == '__main__':
    unittest.main()
