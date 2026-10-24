"""Explicit v2 API grid expansion and independent coverage checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
from _html_fidelity import HtmlFidelity, TableStructureError
from _source_reconcile import reconcile_html_to_markdown, markdown_table_facts
from _verification import file_sha256
from parse_api_html import render, _publish_new_group, main

HTML = r'''<article><h1>T</h1><h2>1. Grid</h2><table id="grid">
<tr><th rowspan="2">Feature</th><th colspan="2">Group</th></tr>
<tr><th>Min</th><th>Max</th></tr>
<tr><td rowspan="2"><code>x</code> <span class="math">\(\alpha | x\)</span>
<pre>  first();</pre><pre>second();</pre></td><td></td><td>1</td></tr>
<tr><td>2</td></tr>
<tr><td colspan="2">a|b <code>p|q</code> \path</td><td>3</td></tr></table>
<h2>2. Other</h2><table id="other"><tr><th>A</th></tr><tr><td>4</td></tr></table></article>'''


class GridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='grid-table-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html, self.md, self.mapping = [self.root/n for n in ('page.html','source.md','tables.json')]
        self.html.write_text(HTML)

    def parse(self, extra=()):
        p = subprocess.run([sys.executable, str(SCRIPTS/'parse_api_html.py'), str(self.html),
                            str(self.md), '--expand-tables', 'grid',
                            '--table-conversions-output', str(self.mapping), *extra],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        md = self.md.read_text()
        mapping = json.loads(self.mapping.read_text())
        self.assertEqual(reconcile_html_to_markdown(HTML, md, 'api', table_conversions=mapping), [])
        return md, mapping

    def test_real_grid_rows_empty_holes_math_code_and_v2_origin(self):
        md, mapping = self.parse()
        self.assertEqual(mapping['version'], 2)
        self.assertEqual(mapping['snapshot_sha256'], file_sha256(self.html))
        facts = markdown_table_facts(md)
        self.assertTrue(all(t['gfm'] for t in facts))
        self.assertEqual([len(row) for row in facts[0]['rows']], [3]*5)
        self.assertEqual(facts[0]['rows'][2][1], '')
        self.assertEqual(facts[0]['rows'][3][2], '')
        self.assertIn('**Feature**', md)
        self.assertIn('**Min**', md)
        self.assertEqual(md.count('first();'), 1)
        self.assertEqual(md.count('second();'), 1)
        code_cell = next(c for c in mapping['tables'][0]['cells'] if c['row']==3 and c['col']==1)
        self.assertEqual(len(code_cell['targets']), 2)
        self.assertEqual(code_cell['code_target'], {'table':1,'row':3,'col':1})

    def test_missing_empty_coverage_wrong_value_origin_role_and_digest_fail(self):
        md, mapping = self.parse()
        def missing(p):
            next(c for c in p['tables'][0]['cells'] if c['row']==3 and c['col']==2)['targets']=[]
        for change in [missing, lambda p: p.update(snapshot_sha256='0'*64),
                       lambda p: next(c for c in p['tables'][0]['cells'] if c['row']==3 and c['col']==1).update(
                           code_target={'table':1,'row':4,'col':1}),
                       lambda p: p['tables'][0]['cells'][0]['targets'].pop()]:
            bad = copy.deepcopy(mapping);change(bad)
            self.assertTrue(reconcile_html_to_markdown(HTML, md, 'api', table_conversions=bad))
        for damaged in [md.replace('**Min**','Min'), md.replace('| 2 |  |','| 2 | fabricated |'),
                        md.replace('first();','changed();'), md.replace('Group','Changed',1),
                        md.replace('[TABLE-CODE r=3 c=1#2]','[TABLE-CODE r=4 c=1#1]')]:
            self.assertTrue(reconcile_html_to_markdown(HTML, damaged, 'api', table_conversions=mapping))

    def test_secondary_header_translation_cli_rejects_role_loss(self):
        source, _mapping = self.parse()
        from test_table_header_roles import project_context
        context = project_context(self.root, self.md,
            [{'snapshot': self.html.name, 'table_conversions': self.mapping.name}])
        translated = self.root / 'translated.md'
        healthy = source.replace('**Min**', '**最小**')
        for text, expected in [(healthy, 0), (healthy.replace('**最小**', '最小'), 1)]:
            translated.write_text(text)
            result = subprocess.run([sys.executable, str(SCRIPTS / 'verify_translation.py'),
                str(translated), str(self.md), '--fragment', '--table-code-stage', 'intermediate',
                '--project-context', str(context)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            if expected:
                self.assertIn('表头角色', result.stdout + result.stderr)

    def test_default_refusal_pairing_and_existing_outputs_preserved(self):
        for options in [[], ['--expand-tables','grid'], ['--table-conversions-output',str(self.mapping)]]:
            p = subprocess.run([sys.executable,str(SCRIPTS/'parse_api_html.py'),str(self.html),str(self.md),*options],
                               capture_output=True,text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(self.md.exists())
        self.md.write_text('old')
        p=subprocess.run([sys.executable,str(SCRIPTS/'parse_api_html.py'),str(self.html),str(self.md),
                          '--expand-tables','grid','--table-conversions-output',str(self.mapping)],
                         capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertEqual(self.md.read_text(),'old')
        self.assertFalse(self.mapping.exists())

    def test_invalid_span_overlap_out_of_bounds_nested_refuse(self):
        samples = ['<table><tr><td rowspan="0">x</td></tr></table>',
                   '<table><tr><td rowspan="2">x</td></tr></table>',
                   '<table><tr><td>x</td><td rowspan="2">y</td></tr><tr><td colspan="2">z</td></tr></table>',
                   '<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>']
        for body in samples:
            f=HtmlFidelity();f.expand_tables=True;s=f.parse('<article>'+body+'</article>')
            with self.assertRaises(TableStructureError):
                render(s.article,[],f)
        f=HtmlFidelity();s=f.parse('<article>'+samples[-1]+'</article>')
        with self.assertRaisesRegex(TableStructureError,'嵌套表'):
            render(s.article,[],f)

    def test_group_failure_and_racing_target_preserve_old_files(self):
        for race in [False, True]:
            a,b=self.root/'a.json',self.root/'b.md'
            def validate(paths):
                self.assertEqual(Path(paths[str(a)]).read_text(),'new map')
                if race:
                    b.write_text('existing')
                else:
                    raise ValueError('candidate failed')
            with self.assertRaises((ValueError, FileExistsError)):
                _publish_new_group([(str(a),'new map'),(str(b),'new source')],validate)
            self.assertFalse(a.exists())
            if race:
                self.assertEqual(b.read_text(),'existing')
            self.assertEqual(list(self.root.glob('.api-grid-*')),[])

    def test_spanned_link_image_projects_display_occurrences_and_source_proof(self):
        from PIL import Image
        import verify_delivery as delivery
        Image.new('RGB',(20,10),'red').save(self.root/'plot.png')
        raw='<article><h1>T</h1><table><tr><th>A</th><th>B</th></tr><tr><td colspan="2">' \
            '<a href="https://example.org/image"><img src="plot.png" width="50"></a></td></tr></table></article>'
        self.html.write_text(raw)
        p=subprocess.run([sys.executable,str(SCRIPTS/'parse_api_html.py'),str(self.html),str(self.md),
            '--expand-tables','grid','--table-conversions-output',str(self.mapping)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        dims=json.loads(self.md.with_suffix('.images_display.json').read_text())
        self.assertEqual(len(dims['entries']),2)
        self.assertEqual([i['occurrence'] for i in dims['entries']],[1,2])
        source_map=json.loads(self.mapping.read_text())
        self.assertTrue(reconcile_html_to_markdown(raw,self.md.read_text().replace('example.org','wrong.org',1),
            'api',table_conversions=source_map))
        record={'sources':[{'family':'api','source_version':'fixture','parsed_markdown':self.md.name,
            'table_conversions':self.mapping.name,'per_stem_map':self.md.with_suffix('.images_display.json').name,
            'snapshots':[{'snapshot':self.html.name}],'covers':[]}], 'inputs':[]}
        problems=[]
        entries=delivery.check_source_chains(self.root,record,problems,source_only=True)
        delivery.run_source_reconcile(self.root,record,entries,problems)
        self.assertEqual(problems,[])

    def test_each_companion_write_failure_leaves_no_published_source(self):
        from PIL import Image
        Image.new('RGB',(20,10),'red').save(self.root/'plot.png')
        self.html.write_text(HTML.replace('<h1>T</h1>','<h1>T</h1><img src="plot.png" width="20">'))
        before=self.html.read_bytes()
        argv=['parse_api_html.py',str(self.html),str(self.md),'--expand-tables','grid',
              '--table-conversions-output',str(self.mapping)]
        for fail_at in (1,2,3):
            calls=[]
            def fail(fd):
                calls.append(fd)
                if len(calls)==fail_at:
                    raise OSError('staging write failed')
            with patch('sys.argv',argv),patch('parse_api_html.os.fsync',side_effect=fail):
                with self.assertRaisesRegex(OSError,'staging write failed'):
                    main()
            self.assertEqual(self.html.read_bytes(),before)
            for path in (self.md,self.mapping,self.md.with_suffix('.images_display.json')):
                self.assertFalse(path.exists())
            self.assertEqual(list(self.root.glob('.api-grid-*')),[])

    def test_gfm_math_and_code_preserve_original_backslash_pipes_and_ampersand(self):
        from _verification import scan_math, compare_math_spans
        raw=r'<article><h1>T</h1><table><tr><th>A</th></tr><tr><td><code>p\|q</code>' \
            r'<span class="math">\(\|x\|+\text{a&amp;b}\)</span></td></tr></table></article>'
        self.html.write_text(raw)
        p=subprocess.run([sys.executable,str(SCRIPTS/'parse_api_html.py'),str(self.html),str(self.md),
            '--expand-tables','grid','--table-conversions-output',str(self.mapping)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        text=self.md.read_text()
        diffs,warns=compare_math_spans(scan_math(text).spans,scan_math(text).spans,src_text=text,doc_text=text)
        self.assertEqual(diffs,[])


if __name__=='__main__':
    unittest.main()
