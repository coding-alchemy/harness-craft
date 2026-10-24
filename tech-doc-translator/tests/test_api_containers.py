"""API rich containers retain block order, ownership and selected images."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
from _html_fidelity import HtmlFidelity
from _source_reconcile import reconcile_html_to_markdown
from parse_api_html import render


def sd_tabs():
    return ('<div class="sd-tab-set"><input id="one"><label for="one" class="sd-tab-label">'
            'CPU <code>x()</code></label><div class="sd-tab-content"><p>First</p>'
            '<pre>  first();\n</pre></div><input id="two"><label for="two" class="sd-tab-label">GPU</label>'
            '<div class="sd-tab-content"><p>Second</p><pre>    second();\n</pre></div></div>')


class ApiContainerTests(unittest.TestCase):
    def parse(self, body):
        raw = '<article><h1>T</h1>%s</article>' % body
        fidelity = HtmlFidelity()
        soup = fidelity.parse(raw)
        out = []
        render(soup.article, out, fidelity)
        md = '\n'.join(out).strip() + '\n'
        self.assertEqual(reconcile_html_to_markdown(raw, md, 'api'), [], md)
        self.assertNotIn('__TECHDOC_', md)
        self.assertNotIn('\x00', md)
        return raw, md, fidelity

    def test_linked_images_text_and_dark_selection(self):
        raw, md, fidelity = self.parse('<p>Before <a href="full.html">'
            '<img class="only-light" src="light.png" width="40"> open '
            '<img class="only-dark" src="dark.png"></a> After</p>')
        self.assertIn('[![](light.png) open](full.html)', md)
        self.assertIn('Before', md)
        self.assertIn('After', md)
        self.assertNotIn('dark.png', md)
        self.assertEqual(len(fidelity.image_display), 1)
        self.assertEqual(fidelity.image_display[0]['value'], 40)
        self.assertTrue(reconcile_html_to_markdown(raw, md + '\n![](light.png)', 'api'))
        self.assertTrue(any('链接图片' in d for d in reconcile_html_to_markdown(
            raw, md.replace('](full.html)', '](wrong.html)'), 'api')))

    def test_rich_quote_and_details(self):
        raw, md, _ = self.parse('<blockquote><p>Quote</p><ul><li>A</li><li>B</li></ul>'
            '<pre>  code();</pre><img src="plot.png"><table><tr><th>X</th></tr>'
            '<tr><td>1</td></tr></table></blockquote><details><summary>More</summary>'
            '<p>Body</p><ul><li>C</li></ul></details>')
        self.assertIn('[BLOCKQUOTE]', md)
        self.assertIn('[DETAILS] More', md)
        self.assertIn('[TABLE]', md)
        self.assertIn('  code();', md)
        self.assertTrue(reconcile_html_to_markdown(raw, md.replace('  - B\n', ''), 'api'))

    def test_nested_sd_tabs_list_and_definition(self):
        for body in ['<ul><li><p>Parent</p>%s<p>After</p></li><li>Next</li></ul>',
                     '<dl><dt>Term</dt><dd><p>Definition</p>%s<p>After</p></dd></dl>']:
            raw, md, _ = self.parse(body % sd_tabs())
            self.assertIn('  **[Tab: CPU `x()`]**', md)
            self.assertIn('  first();', md)
            self.assertIn('    second();', md)
            self.assertEqual(md.count('**[Tab:'), 2)
            swapped = md.replace('Tab: CPU `x()`', 'Tab: TEMP').replace('Tab: GPU', 'Tab: CPU `x()`').replace('Tab: TEMP', 'Tab: GPU')
            self.assertTrue(reconcile_html_to_markdown(raw, swapped, 'api'))

    def test_sphinx_tabs_nested_and_wrong_parent(self):
        body = ('<ul><li><p>Parent</p><div class="sphinx-tabs"><div role="tablist">'
                '<button role="tab">One</button><button role="tab">Two</button></div>'
                '<div role="tabpanel"><pre>one()</pre></div>'
                '<div role="tabpanel"><pre>two()</pre></div></div></li><li>Next</li></ul>')
        raw, md, _ = self.parse(body)
        self.assertIn('  **[Tab: One]**', md)
        # Same code and global order, moved outside the parent item.
        damaged = md.replace('\n  ```\none()\n  ```', '\n```\none()\n```')
        self.assertTrue(any('列表项' in d for d in reconcile_html_to_markdown(raw, damaged, 'api')))

    def test_footnote_list_and_nested_definition_consumed_once(self):
        _, md, _ = self.parse('<div class="footnote-list"><aside role="doc-footnote">'
            '<span class="label">[1]</span><p>Note <code>f()</code></p></aside></div>'
            '<dl><dt>Outer</dt><dd><p>Definition</p><dl><dt>Inner</dt>'
            '<dd>Nested</dd></dl></dd></dl>')
        self.assertIn('[[1]] Note `f()`', md)
        self.assertEqual(md.count('**Inner**'), 1)

    def test_rich_numeric_footnotes_preserve_all_blocks_and_prose(self):
        body = ('<p>Note</p><ul><li>Item</li></ul><pre>  keep()</pre><p>End</p>'
                '<table><tr><th>A</th></tr><tr><td>1</td></tr></table><img src="f.png">')
        for wrap in ['<dl><dt>[1]</dt><dd>%s</dd></dl>',
                     '<aside role="doc-footnote"><span class="label">[1]</span>%s</aside>']:
            raw, md, _ = self.parse(wrap % body)
            self.assertIn('    - Item', md)
            self.assertIn('  keep()', md)
            self.assertIn('[TABLE]', md)
            self.assertTrue(any('脚注定义' in d for d in
                reconcile_html_to_markdown(raw, md.replace('  End', ''), 'api')))

    def test_unsupported_rich_container_and_bad_tab_pair_fail(self):
        for body in ['<custom-box id="missing"><p>Text</p><pre>x()</pre></custom-box>',
                     sd_tabs().replace('for="one"', 'for="missing"')]:
            fidelity = HtmlFidelity()
            soup = fidelity.parse('<article>%s</article>' % body)
            with self.assertRaisesRegex(ValueError, '富容器|标签'):
                render(soup.article, [], fidelity)

    def test_real_cli_and_translation_reader(self):
        with tempfile.TemporaryDirectory(prefix='api-container-') as tmp:
            root = Path(tmp)
            html = root / 'page.html'
            source = root / 'source.md'
            html.write_text('<article><h1>T</h1><blockquote><p>Body</p><ul><li>One</li>'
                            '<li>Two</li></ul><pre>  code()</pre></blockquote>%s</article>' % sd_tabs())
            p = subprocess.run([sys.executable, str(SCRIPTS/'parse_api_html.py'), str(html), str(source)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            translated = root / 'translated.md'
            text = source.read_text().replace('# T', '# T（示例）').replace('[BLOCKQUOTE]', '**引文**')
            for old, new in [('Body', '正文说明保持原有顺序和层级'), ('One', '第一项'),
                             ('Two', '第二项'), ('First', '第一面板'), ('Second', '第二面板')]:
                text = text.replace(old, new)
            translated.write_text(text)
            p = subprocess.run([sys.executable, str(SCRIPTS/'verify_translation.py'), '--fragment',
                                str(translated), str(source)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)


if __name__ == '__main__':
    unittest.main()
