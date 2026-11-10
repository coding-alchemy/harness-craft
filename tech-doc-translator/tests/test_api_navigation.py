"""来源页身份、表外锚点及本章片段的真实 CLI 消费。"""
import json, subprocess,sys,tempfile,unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/tech-doc-translator/scripts'
sys.path.insert(0,str(SCRIPTS))
from _api_navigation import load_navigation,namespaced,verify_page,anchor_diffs

class ApiNavigationFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='api-navigation-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.raws={
            'a.html':'<article><section id="same"><h1>A</h1><p><a href="#t">table</a> <a href="b.html#same">B</a> <a href="c.html#same">C</a> <a href="b.html">page B</a></p><table id="t"><caption>Table 1. Values <a href="#t">#</a></caption><tr><th>Name</th><th>Value</th></tr><tr><td><a href="b.html#same">B</a></td><td>10</td></tr></table></section></article>',
            'b.html':'<article><section id="same"><h1>B</h1><p><a href="#same">B own</a> <a href="a.html#same">A</a></p></section></article>',
            'c.html':'<article><section id="same"><h1>C</h1><p><a href="#same">C own</a> <a href="a.html#t">A table</a></p></section></article>'}
        entries=[]
        for page,raw in self.raws.items():
            (self.root/page).write_text(raw)
            md=page.replace('.html','.md');self.run_tool('parse_api_html.py',self.root/page,self.root/md)
            (self.root/('trans_'+md)).write_text((self.root/md).read_text())
            entries.append({'family':'api','source_version':'test','parsed_markdown':md,'snapshots':[{'snapshot':page}], 'covers':['01_AB.md' if page!='c.html' else '02_C.md']})
        self.record={'version':1,'delivery_root':str(self.root),'mode':'translation','inputs':['01_AB.md','02_C.md'],'sources':entries}
        self.save_record()
        (self.root/'ab.txt').write_text('a.html\nb.html\n');(self.root/'c.txt').write_text('c.html\n')
    def save_record(self):
        (self.root/'record.json').write_text(json.dumps(self.record))
    def run_tool(self,script,*args,ok=True):
        p=subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
        if ok:self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        else:self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        return p
    def merge(self):
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json')
        self.run_tool('merge_api.py',self.root/'c.txt',self.root,self.root/'02_C.md','--navigation-record',self.root/'record.json')


class ApiNavigationTests(ApiNavigationFixture, unittest.TestCase):
    def test_actual_merge_and_final_checker(self):
        self.assertFalse((self.root/'01_AB.md').exists());self.merge()
        self.run_tool('verify_api_translation.py',self.root/'01_AB.md',self.root/'ab.txt',self.root/'ab.txt',self.root,self.root/'a.md',self.root/'b.md','--navigation-record',self.root/'record.json')
        final=(self.root/'01_AB.md').read_text()
        self.assertIn('](02_C.md#'+namespaced('c.html','same')+')',final)
        self.assertIn('](#'+namespaced('b.html','same')+')',final)
        self.assertIn('](#'+namespaced('b.html','')+')',final)
        self.assertEqual(len(__import__('_source_reconcile').markdown_table_facts(final)[0]['rows']),2)
        damaged=final.replace('#'+namespaced('b.html','same'),'#'+namespaced('a.html','same'),1)
        (self.root/'01_AB.md').write_text(damaged)
        self.run_tool('verify_api_translation.py',self.root/'01_AB.md',self.root/'ab.txt',self.root/'ab.txt',self.root,self.root/'a.md',self.root/'b.md','--navigation-record',self.root/'record.json',ok=False)
    def object_source(self):
        return ('<article><h1 id="same">A</h1><p id="p">Paragraph.</p>'
                '<pre id="direct">one &lt; two</pre>'
                '<div class="literal-block-wrapper" id="listing">'
                '<div class="code-block-caption">Listing 1. Example.</div>'
                '<div class="highlight-c" id="alias"><pre>two &gt; one</pre></div></div>'
                '<p><a href="#p">paragraph</a> <a href="#direct">first</a> '
                '<a href="#listing">second</a> <a href="#alias">alias</a></p></article>')
    def test_code_listing_and_paragraph_ids_survive_parse_merge_verify(self):
        from _api_navigation import source_anchors
        raw = self.object_source()
        self.assertEqual(source_anchors(raw)['direct'], ('code', 1))
        self.assertEqual(source_anchors(raw)['p'], ('paragraph', 1))
        self.assertEqual(source_anchors(raw)['listing'], ('code', 2))
        self.assertEqual(source_anchors(raw)['alias'], ('code', 2))
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        text = (self.root/'a.md').read_text()
        self.assertEqual(anchor_diffs(raw, text), [])
        (self.root/'trans_a.md').write_text(text)
        output = self.root/'01_AB.md'
        self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                      '--navigation-record', self.root/'record.json')
        self.run_tool('verify_api_translation.py', output, self.root/'ab.txt',
                      self.root/'ab.txt', self.root, self.root/'a.md', self.root/'b.md',
                      '--navigation-record', self.root/'record.json')
        for name in ('p', 'direct', 'listing', 'alias'):
            self.assertIn('](#'+namespaced('a.html', name)+')', output.read_text())
        self.assertIn('\none < two\n', output.read_text())
        self.assertIn('\ntwo > one\n', output.read_text())
        from recover_work_packages import _frontmatter
        from _api_navigation import compare_anchors
        for strategy in ('h2', 'chars:25'):
            packages = self.root/strategy.replace(':', '_')
            self.run_tool('split_work_packages.py', self.root/'a.md', packages,
                          self.root/(packages.name+'_trans'), strategy)
            remaining = {'p': 'Paragraph.', 'direct': 'one < two', 'listing': 'two > one'}
            for package in packages.glob('wp_*.md'):
                _, body = _frontmatter(package)
                for name in tuple(remaining):
                    anchor = f'<a id="{name}"></a>'
                    if anchor in body:
                        self.assertIn(remaining.pop(name), body)
                        self.assertTrue(compare_anchors(body, body.replace(anchor, '')))
            self.assertEqual(remaining, {})
    def test_code_or_paragraph_anchor_wrong_object_is_rejected(self):
        raw = self.object_source()
        text = ('<a id="same"></a>\n\n# A\n\n<a id="p"></a>\n\nParagraph.\n\n<a id="direct"></a>\n\n'
                '```\none < two\n```\n\nListing 1. Example.\n\n<a id="listing"></a>\n'
                '<a id="alias"></a>\n\n```\ntwo > one\n```\n')
        self.assertEqual(anchor_diffs(raw, text), [])
        swapped = text.replace('"direct"', '"temp"').replace('"listing"', '"direct"')
        swapped = swapped.replace('"temp"', '"listing"')
        self.assertTrue(anchor_diffs(raw, swapped))
        misplaced = '<a id="p"></a>\n\n'+text.replace('<a id="p"></a>\n\n','')
        self.assertTrue(anchor_diffs(raw, misplaced))

    def test_admonition_anchor_follows_the_quote(self):
        from _api_navigation import _recovery_object_lines, source_anchors
        raw = ('<article><h1>A</h1><blockquote><p>Quote.</p></blockquote>'
               '<div class="admonition note" id="note"><p class="admonition-title">Note</p>'
               '<p>Text.</p></div><p><a href="#note">Read the note</a>.</p></article>')
        snapshot = self.root/'a.html'
        parsed = self.root/'a.md'
        snapshot.write_text(raw)
        self.run_tool('parse_api_html.py', snapshot, parsed)
        source = parsed.read_text()
        anchor = '<a id="note"></a>'
        self.assertIn(anchor, source)
        self.assertEqual(anchor_diffs(raw, source), [])
        self.assertTrue(anchor_diffs(raw, anchor+'\n\n'+source.replace(anchor, '')))
        current = source.replace(anchor, '').replace('ADMONITION [Note]', '注（Note）')
        facts = dict(source=source, raw=raw, section_id=None, anchors=source_anchors(raw))
        targets = _recovery_object_lines(current, 'a.html', facts, self.root/'01_AB.md')
        self.assertEqual(current.splitlines()[targets['note']-1], '> **注（Note）**')
        ambiguous = current+'\n> **另一个注（Note）**\n> Other text.\n'
        with self.assertRaisesRegex(ValueError, '无法唯一对应 admonition'):
            _recovery_object_lines(ambiguous, 'a.html', facts, self.root/'01_AB.md')

    def test_paragraph_recovery_uses_unique_adjacent_list_when_quote_layout_differs(self):
        from _api_navigation import _recovery_object_lines, source_anchors
        raw = ('<article><h1>A</h1><p id="flags">Options:</p><blockquote>'
               '<div><p>Compiler options.</p><ul><li>Pass <code>-O3</code>.</li></ul></div>'
               '</blockquote><p>End.</p></article>')
        snapshot = self.root/'a.html'
        parsed = self.root/'a.md'
        snapshot.write_text(raw)
        self.run_tool('parse_api_html.py', snapshot, parsed)
        facts = dict(source=parsed.read_text(), raw=raw, section_id=None, anchors=source_anchors(raw))
        current = '# A\n\n编译选项：\n\n选项说明。\n\n- 使用 `-O3`。\n\n结束。\n'
        targets = _recovery_object_lines(current, 'a.html', facts, self.root/'01_AB.md')
        self.assertEqual(current.splitlines()[targets['flags']-1], '编译选项：')
        with self.assertRaisesRegex(ValueError, '无法唯一对应 paragraph'):
            _recovery_object_lines(current.replace('-O3', '-O2'), 'a.html', facts, self.root/'01_AB.md')

    def test_recovery_retains_block_boundary_when_a_neighbouring_anchor_moves(self):
        from _api_navigation import _apply_edits, _recovery_anchor_edits
        text = ('# A\n\n<a id="table"></a>\n<a id="paragraph"></a>\n'
                '[TABLE-CAPTION] Table 1. Caption\n\n| A |\n| --- |\n\nText.\n')
        roles = {'table': ('table', 1), 'paragraph': ('paragraph', 1)}
        fixed = _apply_edits(text, _recovery_anchor_edits(
            text, 'a.html', {'table': 7, 'paragraph': 10}, roles))
        self.assertIn(f'<a id="{namespaced("a.html", "table")}"></a>\n\n[TABLE-CAPTION]', fixed)
        targets = {'table': fixed.splitlines().index('| A |')+1,
                   'paragraph': fixed.splitlines().index('Text.')+1}
        self.assertEqual(_recovery_anchor_edits(fixed, 'a.html', targets, roles), [])

    def test_navigation_record_required_from_source_even_when_translation_deletes_link(self):
        import _api_navigation
        raw = '<article><h1>A</h1><p><a href="b.html#same">B</a></p></article>'
        (self.root/'a.html').write_text(raw)
        (self.root/'trans_a.md').write_text('# A\n\nB\n')
        manifest = self.root/'a.txt'
        manifest.write_text('a.html\n')
        output = self.root/'01_AB.md'
        output.write_text('# A\n\nB\n')
        before = output.read_bytes()
        p = self.run_tool('merge_api.py', manifest, self.root, output, ok=False)
        self.assertIn('--navigation-record', p.stderr)
        self.assertIn('b.html#same', p.stderr)
        self.assertEqual(output.read_bytes(), before)
        (self.root/'a.md').write_bytes(before)
        p = self.run_tool('verify_api_translation.py', output, manifest, manifest,
                          self.root, self.root/'a.md', ok=False)
        self.assertIn('--navigation-record', p.stdout+p.stderr)
        self.assertTrue(_api_navigation.requires_navigation(raw, '# A\n\nB\n'))
    def test_non_navigation_api_and_outside_article_nav_need_no_record(self):
        import _api_navigation
        raw = ('<nav><a href="b.html#same">outside</a></nav><article><h1>A</h1>'
               '<p><a href="https://example.org">external</a> <a href="file.zip">asset</a></p>'
               '<pre><a href="b.html">literal</a></pre></article>')
        text = ('# A\n\n[external](https://example.org) [asset](file.zip)\n\n'
                '```\n[literal](b.html)\n```\n')
        (self.root/'a.html').write_text(raw)
        for name in ('a.md', 'trans_a.md'):
            (self.root/name).write_text(text)
        manifest = self.root/'a.txt'
        manifest.write_text('a.html\n')
        output = self.root/'01_AB.md'
        self.run_tool('merge_api.py', manifest, self.root, output)
        self.run_tool('verify_api_translation.py', output, manifest, manifest, self.root,
                      self.root/'a.md')
        self.assertTrue(hasattr(_api_navigation, 'requires_navigation'))
        self.assertFalse(_api_navigation.requires_navigation(raw, text))
        self.assertTrue(_api_navigation.requires_navigation(raw, text+'\n[added](b.html)\n'))
        with self.assertRaises(ValueError):
            _api_navigation.requires_navigation(raw, text, section_id='missing')
    def test_ownership_missing_target_conflict_and_range_refused(self):
        self.record['sources'][0]['covers']=['01_AB.md','02_C.md'];self.save_record()
        with self.assertRaisesRegex(ValueError,'不唯一'):load_navigation(self.root/'record.json',self.root)
        self.record['sources'][0]['covers']=['01_AB.md'];self.record['sources'][0]['snapshots']=[{'snapshot':'a.html','range':[1,2]}];self.save_record()
        with self.assertRaises(ValueError):load_navigation(self.root/'record.json',self.root)
        raw=self.raws['a.html'].replace('</article>','<h2 id="t">Duplicate</h2></article>')
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py',self.root/'a.html',self.root/'new.md',ok=False)
    def test_delivery_facts_bind_navigation_dependencies_and_failed_publish_keeps_old(self):
        self.merge()
        import verify_delivery as delivery
        args=[str(self.root/'01_AB.md'),str(self.root/'ab.txt'),str(self.root/'ab.txt'),str(self.root),str(self.root/'a.md'),str(self.root/'b.md'),'--navigation-record',str(self.root/'record.json')]
        facts,_=delivery._check_facts(str(self.root),'verify_api_translation',args,1)
        self.assertTrue(delivery._facts_complete(facts))
        paths=[Path(pair[0]).name for pair in facts['files']['navigation_sources']]
        self.assertIn('c.html',paths)
        import merge_api
        from unittest.mock import patch
        output=self.root/'01_AB.md';old=output.read_bytes()
        with patch.object(sys,'argv',['merge_api.py',str(self.root/'ab.txt'),str(self.root),str(output),'--navigation-record',str(self.root/'record.json')]),patch.object(merge_api.os,'replace',side_effect=OSError('controlled publish failure')):
            with self.assertRaises(OSError):merge_api.main()
        self.assertEqual(output.read_bytes(),old);self.assertEqual(list(self.root.glob('.api-merge-*')),[])
    def test_missing_inline_target_and_source_link_change_refused(self):
        text=(self.root/'trans_a.md').read_text().replace('](#t)','](#missing)',1)
        (self.root/'trans_a.md').write_text(text)
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json',ok=False)
        self.assertFalse((self.root/'01_AB.md').exists())
        (self.root/'a.html').write_text('<article><h1>A</h1><p><span id="inline">inline</span> <a href="#inline">link</a></p></article>')
        self.run_tool('parse_api_html.py',self.root/'a.html',self.root/'a.md')
        (self.root/'trans_a.md').write_text((self.root/'a.md').read_text())
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json',ok=False)
    def test_anchor_in_table_data_rejected(self):
        source=(self.root/'a.md').read_text();anchor='<a id="t"></a>'
        damaged=source.replace(anchor+'\n','').replace('--- | ---','--- | ---\n'+anchor)
        self.assertTrue(anchor_diffs(self.raws['a.html'],damaged))
        from _api_navigation import compare_anchors
        displaced=source.replace(anchor,anchor+'\n\nUnrelated paragraph.')
        self.assertTrue(compare_anchors(source,displaced))
        alphabetic=source.replace('[TABLE-CAPTION] Table 1. Values','[TABLE-CAPTION] Table A. Values')
        self.assertEqual(compare_anchors(alphabetic,alphabetic.replace('[TABLE-CAPTION] Table A. Values','**表 A. 数值**')),[])
    def test_figure_anchor_and_code_literals(self):
        raw='<article><h1>A</h1><figure id="fig"><img src="x.png"><figcaption>Figure 1. Item <a href="#fig">#</a></figcaption></figure><pre>[literal](#fig)</pre></article>'
        (self.root/'figure.html').write_text(raw)
        self.run_tool('parse_api_html.py',self.root/'figure.html',self.root/'figure.md')
        text=(self.root/'figure.md').read_text();self.assertEqual(anchor_diffs(raw,text),[])
        from _api_navigation import replace_links,links
        changed=replace_links(text,lambda href:'#new')
        self.assertEqual(links(changed),['#new']);self.assertIn('[literal](#fig)',changed)
    def test_explicit_section_alias_is_preserved_but_inline_id_is_unresolved(self):
        raw='<article><section id="s"><span id="alias"></span><h1 id="a&amp;b">T</h1><p><span id="inline">body</span></p></section></article>'
        (self.root/'alias.html').write_text(raw)
        self.run_tool('parse_api_html.py',self.root/'alias.html',self.root/'alias.md')
        from _api_navigation import source_anchors
        self.assertEqual(source_anchors(raw),{'s':('heading',1),'alias':('heading',1),'a&b':('heading',1)})
        self.assertEqual(anchor_diffs(raw,(self.root/'alias.md').read_text()),[])
    def test_link_to_selected_source_image_uses_same_verified_delivery_resource(self):
        import shutil
        shutil.copyfile(Path(__file__).parent/'fixtures/valid_1x1.png',self.root/'x.png')
        figure='<figure id="f"><a href="x.png"><img src="x.png" width="12"></a><figcaption><p>Figure 1 <a href="#f">#</a></p></figcaption></figure>'
        (self.root/'a.html').write_text(self.raws['a.html'].replace('</section>',figure+'</section>'))
        self.run_tool('parse_api_html.py',self.root/'a.html',self.root/'a.md')
        (self.root/'trans_a.md').write_text((self.root/'a.md').read_text())
        self.record['sources'][0]['snapshots'][0]['per_stem_map']='a.images_display.json';self.save_record()
        (self.root/'images').mkdir(exist_ok=True);shutil.copyfile(self.root/'x.png',self.root/'images/x.png')
        target=self.root/'trans_a.md';target.write_text(target.read_text().replace('![](x.png)','![](images/x.png)'))
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json','--display-src',self.root)
        mapping = self.root / 'export/images_display.json'
        self.assertEqual(json.loads(mapping.read_text())['markdown'], '../01_AB.md')
        self.run_tool('rebuild_images_display.py','--compose-map',mapping,
                      '--output',self.root/'combined/images_display.json')
        self.assertIn('](images/x.png)',(self.root/'01_AB.md').read_text())
        self.assertEqual((self.root/'images/x.png').read_bytes(),(self.root/'x.png').read_bytes())
        previous=(self.root/'01_AB.md').read_bytes()
        image=self.root/'images/x.png';image.write_bytes(image.read_bytes()+b'changed-resource')
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json','--display-src',self.root,ok=False)
        self.assertEqual((self.root/'01_AB.md').read_bytes(),previous)
    def test_anchor_follows_object_in_both_split_strategies(self):
        text='# T\n\n<a id="a"></a>\n\n## A\n\nAlpha.\n\n<a id="b"></a>\n\n## B\n\nBeta.\n'
        source=self.root/'split.md';source.write_text(text)
        from recover_work_packages import _frontmatter
        from _api_navigation import compare_anchors
        for strategy in ['h2','chars:25']:
            target=self.root/strategy.replace(':','_')
            self.run_tool('split_work_packages.py',source,target,self.root/(target.name+'_trans'),strategy)
            for package in target.glob('wp_*.md'):
                _,body=_frontmatter(package)
                if '<a id="b"' in body:self.assertIn('## B',body)
                if '<a id="a"' in body:self.assertIn('## A',body)
                self.assertEqual(compare_anchors(body,body),[])
    def test_bare_fragment_never_falls_back_to_another_chapter(self):
        from export_pdf import Chapter,resolve_links
        from bs4 import BeautifulSoup
        (self.root/'01_AB.md').write_text('[missing](#other)\n[explicit](02_C.md#other)')
        (self.root/'02_C.md').write_text('<a id="other"></a>')
        a=Chapter(1,self.root/'01_AB.md');b=Chapter(2,self.root/'02_C.md')
        a.soup=BeautifulSoup('<p><a href="#other">missing</a><a href="02_C.md#other">explicit</a></p>','html.parser')
        b.soup=BeautifulSoup('<a id="other"></a>','html.parser');a.targets={};b.targets={'other':{'kind':'anchor'}}
        a.source_text='[missing](#other)\n[explicit](02_C.md#other)';b.source_text=''
        diagnostics=[];resolve_links(a,[a,b],diagnostics)
        self.assertTrue(any(item.get('code')=='broken-internal-link' and item.get('line')==1 for item in diagnostics),diagnostics)
        self.assertEqual(a.soup.find_all('a')[1]['href'],'#'+b.prefix+'other')
    def test_chinese_chapter_paths_are_normalized_as_uris(self):
        self.record['sources'][2]['covers']=['02_补充结构.md'];self.save_record()
        self.run_tool('merge_api.py',self.root/'ab.txt',self.root,self.root/'01_AB.md','--navigation-record',self.root/'record.json')
        from urllib.parse import quote
        self.assertIn(quote('02_补充结构.md')+'#',(self.root/'01_AB.md').read_text())
        from _api_navigation import replace_links
        self.assertEqual(replace_links('[x](甲.html#id)',lambda href:'#fixed'),'[x](#fixed)')
    def test_footnote_roles_are_not_normal_reference_links(self):
        from _api_navigation import links,replace_links
        text='正文[^name] [ordinary](b.html#same)\n\n[^name]: 中文注文。\n    More [inside](a.html#same).\n    `[literal](c.html)`\n\n[after](c.html#same)\n'
        self.assertEqual(links(text),['b.html#same','a.html#same','c.html#same'])
        changed=replace_links(text,lambda href:'#new')
        self.assertEqual(links(changed),['#new','#new','#new']);self.assertIn('`[literal](c.html)`',changed)

class RecoveryNavigationTests(ApiNavigationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.manifest = self.root/'ab.txt'
        self.toc = self.root/'official.txt'
        self.toc.write_text('a.html\nb.html\n')
        self.output = self.root/'01_AB.md'
        self.baseline = self.root/'current.md'
        self.candidate = self.root/'candidate.md'
        self.record_path = self.root/'record.json'
        source_image = self.root/'source.png'
        source_image.write_bytes((Path(__file__).parent/'fixtures/valid_1x1.png').read_bytes())
        raw = self.raws['a.html'].replace('</section>',
            '<figure id="figure"><img src="source.png"></figure></section>')
        self.raws['a.html'] = raw
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        self.record['sources'][0]['snapshots'][0]['per_stem_map'] = 'a.images_display.json'
        self.save_record()
        a = (self.root/'a.md').read_text()
        a = a.replace('<a id="t"></a>', '').replace('](source.png)', '](images/local.png)').replace(
            'Table 1. Values', 'Table 1. Values [one](https://example.com/blog) '
            '[two](https://example.com/blog)')
        a += ('\n合章后修订 [custom](#mine) [slug](#a) $x$\n\n'
              '<a id="mine"></a>\n\nCurrent text.\n')
        b = (self.root/'b.md').read_text()
        self.current = (a.rstrip()+'\n\n  ---  \n\n'+b).replace('\n', '\r\n').encode()
        self.baseline.write_bytes(self.current)
        (self.root/'trans_a.md').write_text('outdated translated page')
        self.image = self.root/'images/local.png'
        self.image.parent.mkdir()
        self.image.write_bytes(source_image.read_bytes())
        self.display = self.root/'images_display.json'
        self.display.write_text('{"independent":"existing display map"}\n')
        self.evidence = self.root/'previous-evidence.json'
        self.evidence.write_text('{"status":"PASS"}\n')

    def merge_args(self, baseline=None, output=None):
        return (self.manifest, self.root, output or self.output,
                '--recover-navigation-from', baseline or self.baseline,
                '--official-toc', self.toc, '--navigation-record', self.record_path)

    def verify_args(self):
        return (self.output, self.manifest, self.toc, self.root,
                '--navigation-only-from', self.baseline, '--navigation-record', self.record_path)

    def verify_candidate(self):
        from _api_navigation import verify_recovery
        args = (self.baseline, self.candidate, self.manifest, self.toc, self.root, self.record_path)
        return verify_recovery(*map(str,args), chapter_path=str(self.output))

    def test_recovery_uses_current_merged_and_preserves_duplicate_external_link(self):
        self.run_tool('merge_api.py', *self.merge_args())
        result = self.output.read_text()
        self.assertIn('合章后修订', result)
        self.assertEqual(result.count('https://example.com/blog'), 2)
        self.assertNotIn('outdated', result)
        self.assertIn('](#'+namespaced('a.html','t')+')', result)
        self.assertIn('](#'+namespaced('b.html',None)+')', result)
        self.assertIn('](02_C.md#'+namespaced('c.html','same')+')', result)
        self.candidate.write_bytes(self.output.read_bytes())
        self.assertEqual(self.verify_candidate(), [])
        p = self.run_tool('verify_api_translation.py', *self.verify_args())
        self.assertIn('仅导航', p.stdout)

    def test_recovery_preserves_bytes_links_resources_and_is_idempotent(self):
        old_image, old_map = self.image.read_bytes(), self.display.read_bytes()
        self.run_tool('merge_api.py', *self.merge_args())
        result = self.output.read_bytes()
        self.assertIn(b'\r\n\r\n  ---  \r\n\r\n', result)
        self.assertIn(b'[custom](#mine) [slug](#a) $x$', result)
        self.assertNotIn(b'\n', result.replace(b'\r\n', b''))
        self.candidate.write_bytes(result)
        self.run_tool('merge_api.py', *self.merge_args(baseline=self.candidate))
        self.assertEqual(self.output.read_bytes(), result)
        self.assertEqual(self.baseline.read_bytes(), self.current)
        self.assertEqual(self.image.read_bytes(), old_image)
        self.assertEqual(self.display.read_bytes(), old_map)

    def test_recovery_rejects_wrong_pages_and_ambiguous_objects(self):
        self.run_tool('merge_api.py', *self.merge_args())
        for text in (self.current.replace(b'  ---  ', b'---\r\n---'),
                     self.current.replace(b'# B', b'# Unexpected title')):
            with self.subTest(text=text[:80]):
                self.baseline.write_bytes(text)
                self.run_tool('merge_api.py', *self.merge_args(), ok=False)
        self.baseline.write_bytes(self.current)
        self.toc.write_text('b.html\na.html\n')
        self.run_tool('merge_api.py', *self.merge_args(), ok=False)
        self.toc.write_text('a.html\nb.html\n')
        raw = self.raws['a.html'].replace('</section>',
            '<pre id="first">same code</pre><pre id="second">same code</pre>'
            '</section>')
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        current = self.current.replace(b'  ---  ', b'```\r\nsame code\r\n```\r\n\r\n'
                                       b'```\r\nsame code\r\n```\r\n\r\n  ---  ')
        self.baseline.write_bytes(current)
        p = self.run_tool('merge_api.py', *self.merge_args(), ok=False)
        self.assertIn('唯一', p.stdout+p.stderr)

    def test_recovery_verifier_detects_candidate_and_dependency_mutation(self):
        self.run_tool('merge_api.py', *self.merge_args())
        healthy = self.output.read_bytes()
        self.candidate.write_bytes(healthy)
        self.assertEqual(self.verify_candidate(), [])
        target = namespaced('a.html', 't').encode()
        for change in (healthy.replace('合章后修订'.encode(), b'damaged'),
                       healthy.replace(b'](#'+target+b')', b'](#mine)', 1),
                       healthy.replace(b'id="'+target, b'id="wrong', 1),
                       healthy.replace(b'images/local.png', b'images/other.png')):
            with self.subTest(candidate=change[:70]):
                self.assertNotEqual(change, healthy)
                self.candidate.write_bytes(change)
                self.assertTrue(self.verify_candidate())
        self.candidate.write_bytes(healthy)
        self.baseline.write_bytes(self.current.replace('合章后修订'.encode(), b'drift'))
        self.assertTrue(self.verify_candidate())
        self.baseline.write_bytes(self.current)
        (self.root/'a.html').write_text(self.raws['a.html'].replace('id="t"', 'id="different"'))
        self.assertTrue(self.verify_candidate())

    def test_recovery_failure_keeps_baseline_output_and_evidence(self):
        from unittest.mock import patch
        import merge_api
        self.run_tool('merge_api.py', *self.merge_args())
        protected = (self.baseline, self.output, self.evidence)
        before = {p: p.read_bytes() for p in protected}
        self.run_tool('merge_api.py', *self.merge_args(output=self.baseline), ok=False)
        with patch.object(sys, 'argv', ['merge_api.py', *map(str,self.merge_args())]):
            with patch('_api_navigation.verify_recovery', return_value=['controlled failure']):
                with self.assertRaises((ValueError, SystemExit)):
                    merge_api.main()
            with patch.object(merge_api.os, 'replace', side_effect=OSError('controlled publish failure')):
                with self.assertRaises((OSError, SystemExit)):
                    merge_api.main()
        self.assertEqual({p: p.read_bytes() for p in protected}, before)
        self.assertEqual(list(self.root.glob('.api-merge-*')), [])

    def test_navigation_only_check_cannot_register_as_translation(self):
        from verify_delivery import _check_facts, rerun_checks
        self.run_tool('merge_api.py', *self.merge_args())
        self.run_tool('verify_api_translation.py', *self.verify_args())
        args = list(map(str,self.verify_args()))
        problems = []
        self.assertEqual(_check_facts(str(self.root), 'verify_api_translation', args, 1,
                                      problems), (None, None))
        self.assertIn('仅导航', '\n'.join(problems))
        problems.clear()
        delivery = {**self.record, 'checks': [{'tool': 'verify_api_translation', 'args': args}]}
        _, _, translation_checks, _ = rerun_checks(str(self.root), delivery, problems)
        self.assertEqual(translation_checks, {})
        self.assertIn('仅导航', '\n'.join(problems))
        normal = self.run_tool('verify_api_translation.py', self.output, self.manifest, self.toc,
                               self.root, self.root/'a.md', self.root/'b.md',
                               '--navigation-record', self.record_path, ok=False)
        self.assertIn('链接目标对象或出现顺序改变', normal.stdout)


class RawContainerLinkTests(unittest.TestCase):
    def test_outdented_code_literal_is_not_a_navigation_link(self):
        from _api_navigation import links, replace_links
        text = ('- Parent.\n\n  ```cpp\n'
                'const char* s = "[literal](#same)";\n  ```\n\n'
                '  [Real](#same)\n')
        self.assertEqual(links(text), ['#same'])
        self.assertEqual(replace_links(text, lambda href: '#new'),
                         text.replace('[Real](#same)', '[Real](#new)'))


if __name__=='__main__':unittest.main()
