"""CUDA 数学解析保真：原 DOM、真实渲染和损伤检查独立对照。"""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _html_fidelity import HtmlFidelity
from _source_reconcile import reconcile_html_to_markdown
from _verification import scan_math
from verify_translation import run_checks


class HtmlMathFidelityTest(unittest.TestCase):
    def render(self, body, family='api'):
        html = '<article><h1>Math</h1>' + body + '</article>'
        fidelity = HtmlFidelity()
        soup = fidelity.parse(html)
        out = []
        module = importlib.import_module('parse_' + {
            'api': 'api', 'single': 'single_page', 'reference': 'reference',
            'paginated': 'paginated'}[family] + '_html')
        module.render(soup.article, out, fidelity)
        return html, '\n'.join(out).strip() + '\n'

    def test_inline_spacing_punctuation_and_outer_pair(self):
        for family in ('api', 'single', 'reference', 'paginated'):
            with self.subTest(family=family):
                html, md = self.render(
                    r'<p>Value <span class="math">\(x  := y\)</span>.'
                    r' <span class="math">\(\[z := 2\]\)</span>'
                    r' and $a  := b$.</p>', family)
                self.assertIn('$x  := y$', md)
                self.assertIn(r'$\[z := 2\]$', md)
                self.assertIn('$a  := b$', md)
                self.assertEqual(reconcile_html_to_markdown(html, md, family), [])
                for damaged in (md.replace(':=', '=', 1),
                                md.replace('x  := y', 'x := z'),
                                md.replace('$x  := y$', '$$x  := y$$')):
                    self.assertTrue(reconcile_html_to_markdown(html, damaged, family))

    def test_direct_container_math_uses_same_protection(self):
        html, md = self.render(r'<ul><li>value <span class="math">x  := y</span>'
                               r' and $a  := b$</li></ul>')
        self.assertIn('$x  := y$', md)
        self.assertIn('$a  := b$', md)
        self.assertEqual(reconcile_html_to_markdown(html, md, 'api'), [])

    def test_family_block_contract_and_api_wrapper(self):
        for family in ('api', 'single', 'reference', 'paginated'):
            with self.subTest(family=family):
                html, md = self.render(r'<div class="math">\[x  := y\]</div>', family)
                spans = scan_math(md).spans
                expected = 'block' if family in ('reference', 'paginated') else 'inline'
                self.assertEqual(spans[0].kind, expected)
                self.assertIn('x  := y', spans[0].expr)
                self.assertEqual(reconcile_html_to_markdown(html, md, family), [])

    def test_code_currency_and_unresolved_delimiter(self):
        html, md = self.render(r'<p><code>$a := b$</code> costs $5 or $10.</p><p>'
                               r'Escaped \$4.</p><p><span class="math">x := y</span></p>')
        self.assertEqual([(s.kind, s.expr) for s in scan_math(md).spans],
                         [('inline', 'x := y')])
        self.assertEqual(reconcile_html_to_markdown(html, md, 'api'), [])
        html, md = self.render('<p>unresolved $x</p>')
        self.assertTrue(reconcile_html_to_markdown(html, md, 'api'))

    def test_translated_work_package_preserves_math(self):
        _, src = self.render(r'<p>Value <span class="math">\(x  := y\)</span>.</p>')
        doc = src.replace('Value', '数值')
        args = dict(doc_dir='/private/tmp', doc_label='wp.md', src_label='source.md', fragment=True)
        failures, lines = run_checks(doc, src, **args)
        self.assertEqual(failures, 0, lines)
        failures, _ = run_checks(doc.replace(':=', '='), src, **args)
        self.assertGreater(failures, 0)


if __name__ == '__main__':
    unittest.main()
