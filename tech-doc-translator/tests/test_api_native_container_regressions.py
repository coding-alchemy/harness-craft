"""Full CUDA range patterns: grouped footnotes, rich legends and list separators."""
import subprocess,sys,tempfile,unittest,shutil,json
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/tech-doc-translator/scripts'
class NativeContainerPatterns(unittest.TestCase):
    def parse(self,body,grid=False):
        with tempfile.TemporaryDirectory(prefix='native-container-') as tmp:
            root=Path(tmp);source=root/'page.html';source.write_text('<article><h1>T</h1>'+body+'</article>')
            shutil.copyfile(Path(__file__).parent/'fixtures/valid_1x1.png',root/'x.png')
            args=[sys.executable,str(SCRIPTS/'parse_api_html.py'),str(source),str(root/'source.md')]
            if grid:args+=['--expand-tables','grid','--table-conversions-output',str(root/'tables.json')]
            p=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            text=(root/'source.md').read_text()
            return (text,json.loads((root/'tables.json').read_text())) if grid else text
    def test_grouped_sphinx_asides_retain_both_definitions_and_lists(self):
        result=self.parse('<p>Text<a class="footnote-reference" href="#fn1">[1]</a><a class="footnote-reference" href="#fn2">[2]</a></p><aside class="footnote-list brackets"><aside class="footnote" role="doc-footnote" id="fn1"><span class="label">[1]</span><p>First.</p></aside><aside class="footnote" role="doc-footnote" id="fn2"><span class="label">[2]</span><p>Second.</p><ul><li>Nested.</li></ul></aside></aside>')
        self.assertIn('[[1]] First.',result);self.assertIn('[[2]] Second.',result);self.assertIn('    - Nested.',result)
    def test_figure_legend_keeps_definition_list_and_quote_blocks(self):
        result=self.parse('<figure id="f"><img src="x.png"><figcaption><p>Figure 1 <a href="#f">#</a></p><div class="legend"><blockquote><p>Explanation.</p></blockquote><dl><dt>Left</dt><dd><p>First view.</p></dd><dt>Right</dt><dd><p>Second view.</p></dd></dl></div></figcaption></figure>')
        self.assertIn('[DEF-LIST]',result);self.assertIn('[BLOCKQUOTE]',result);self.assertEqual(result.count('First view.'),1)
    def test_visible_blockquote_separates_top_level_list_numbering(self):
        result=self.parse('<ol><li>A</li></ol><blockquote><ul><li>B</li><li>C</li></ul></blockquote><ol><li>D</li></ol>')
        self.assertEqual(result.count('[BLOCKQUOTE]'),1);self.assertIn('  - D',result)
    def test_grid_code_table_inside_list_tab_keeps_raw_indent_and_ownership(self):
        code='if (x) {\n    work();\n}'
        body='<ul><li><p>Parent.</p><div class="sd-tab-set"><input id="tab"><label class="sd-tab-label" for="tab">Code</label><div class="sd-tab-content"><table id="t"><tr><td><pre>'+code+'</pre></td></tr></table></div></div><p>After.</p></li></ul>'
        text,mapping=self.parse(body,grid=True)
        sys.path.insert(0,str(SCRIPTS))
        from _source_reconcile import markdown_table_facts,reconcile_html_to_markdown
        self.assertEqual(markdown_table_facts(text)[0]['codes'][(1,1,1)],code)
        damaged=text.replace('    work();','  work();')
        self.assertTrue(reconcile_html_to_markdown('<article><h1>T</h1>'+body+'</article>',damaged,'api',table_conversions=mapping))
    def test_list_after_footnote_does_not_become_note_continuation(self):
        result=self.parse('<aside class="footnote-list"><aside role="doc-footnote"><span class="label">[1]</span><p>Note.</p><ul><li>Inside.</li></ul></aside></aside><ul><li><p>Next parent.</p><div class="sphinx-tabs"><div role="tablist"><button role="tab">One</button></div><div role="tabpanel"><pre>x();</pre></div></div><p>After panel.</p></li></ul>')
        self.assertIn('After panel.',result)
    def test_final_api_image_count_uses_inline_dark_selection_too(self):
        sys.path.insert(0,str(SCRIPTS))
        from verify_api_translation import _visible_html_images
        with tempfile.TemporaryDirectory(prefix='inline-light-') as tmp:
            root=Path(tmp);(root/'page.html').write_text('<article><p><a href="x.png"><img class="only-light" src="x.png"><img class="only-dark" src="dark.png"></a></p></article>')
            self.assertEqual(_visible_html_images(str(root),'page.html'),[str(root/'x.png')])
if __name__=='__main__':unittest.main()
