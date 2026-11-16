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
        # 结构提示行不算段落（R5）：只把 [BLOCKQUOTE] 改成普通段落时段落数相等，按位置对应
        current = '# A\n\n编译选项：\n\n选项说明。\n\n- 使用 `-O3`。\n\n结束。\n'
        for text in (current, current.replace('-O3', '-O2')):
            targets = _recovery_object_lines(text, 'a.html', facts, self.root/'01_AB.md')
            self.assertEqual(text.splitlines()[targets['flags']-1], '编译选项：')
        # 段落数不等时，仍只凭冒号标签后相邻列表的唯一代码序列对应
        extra = current.replace('\n\n结束。', '\n\n附注。\n\n结束。')
        targets = _recovery_object_lines(extra, 'a.html', facts, self.root/'01_AB.md')
        self.assertEqual(extra.splitlines()[targets['flags']-1], '编译选项：')
        with self.assertRaisesRegex(ValueError, '无法唯一对应 paragraph'):
            _recovery_object_lines(extra.replace('-O3', '-O2'), 'a.html', facts, self.root/'01_AB.md')

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


class StructureHintParagraphTests(unittest.TestCase):
    """结构提示按约定写法改写后，段落锚点仍绑定原段落（R5）。"""

    AFTER = '<p id="after">After.</p><p>See <a href="#after">after</a>.</p>'

    def parse(self, body):
        import parse_api_html
        from _html_fidelity import HtmlFidelity
        raw = '<article><h1>A</h1>%s%s</article>' % (body, self.AFTER)
        fidelity = HtmlFidelity()
        out = []
        parse_api_html.render(fidelity.parse(raw).article, out, fidelity)
        source = '\n'.join(out).strip() + '\n'
        self.assertEqual(anchor_diffs(raw, source, source=source), [])
        return raw, source

    def assertBinds(self, raw, source, translated):
        self.assertEqual(anchor_diffs(raw, translated, source=source), [])

    def assertMisbinds(self, raw, source, translated):
        self.assertTrue(anchor_diffs(raw, translated, source=source))

    def test_blockquote_rewritten_as_quote(self):
        raw, source = self.parse('<blockquote><p>Quoted text.</p></blockquote>')
        self.assertIn('[BLOCKQUOTE]\n\nQuoted text.\n', source)
        quoted = source.replace('[BLOCKQUOTE]\n\nQuoted text.\n', '> 引用文字。\n')
        self.assertBinds(raw, source, quoted)
        moved = quoted.replace('<a id="after"></a>\n\n\n', '').replace(
            'See [after]', '<a id="after"></a>\n\nSee [after]')
        self.assertMisbinds(raw, source, moved)

    def test_definition_list_without_marker(self):
        raw, source = self.parse('<dl><dt>Left</dt><dd>One.</dd><dt>Right</dt><dd>Two.</dd></dl>')
        block = '[DEF-LIST]\n  **Left** One.\n  **Right** Two.\n'
        self.assertIn(block, source)
        self.assertBinds(raw, source, source.replace(block, '  **左** 一。\n  **右** 二。\n'))
        self.assertBinds(raw, source, source.replace(block, '  **左** 一。\\\n  **右** 二。\n'))
        self.assertMisbinds(raw, source, source.replace(
            block, '[DEF-LIST]\n  **左** 一。\n\n  **右** 二。\n'))

    def test_footnote_list_rewritten_as_definitions(self):
        ref = ('<a class="footnote-reference brackets" href="#fn1" id="r1" role="doc-noteref">'
               '<span class="fn-bracket">[</span>1<span class="fn-bracket">]</span></a>')
        note = ('<aside class="footnote-list brackets"><aside class="footnote brackets" id="fn1" '
                'role="doc-footnote"><span class="label"><span class="fn-bracket">[</span>'
                '<a role="doc-backlink" href="#r1">1</a><span class="fn-bracket">]</span></span>'
                '<p>See PTX.</p></aside></aside>')
        raw, source = self.parse('<p>Text%s.</p>%s' % (ref, note))
        block = '[FOOTNOTE-LIST]\n  [[1]] See PTX.\n'
        self.assertIn(block, source)
        for definition in ('[^1]: 见PTX。\n', '[^1]: 见 PTX 文档。\n'):
            with self.subTest(definition=definition):
                self.assertBinds(raw, source, source.replace(block, definition))

    def test_translated_admonition_label(self):
        raw, source = self.parse('<div class="admonition hint"><p class="admonition-title">Hint</p>'
                                 '<p>Hint text.</p></div>')
        translated = source.replace('> **ADMONITION [Hint]**\n> Hint text.',
                                    '> **提示（Hint）**\n> 提示文字。')
        self.assertBinds(raw, source, translated)

    def test_details_label_rewritten_as_bold_line(self):
        raw, source = self.parse('<details><summary>More</summary><p>Hidden text.</p></details>')
        self.assertBinds(raw, source, source.replace('[DETAILS] More', '**更多（Details）**'))

    def test_quote_with_code_or_table_rewritten_without_marker(self):
        """评审关注：引用里有代码或表格时同样去掉 [BLOCKQUOTE] 行，代码和表格留在列 0；
        片段核验不报 [BLOCKQUOTE] 残留；保留提示行的译文被片段核验拒绝。"""

        def blockquote_residual(doc, src):
            from verify_translation import run_checks
            with tempfile.TemporaryDirectory() as tmp:
                _fail, lines = run_checks(doc, src, doc_dir=tmp, doc_label='doc.md',
                                          src_label='src.md', fragment=True)
            return [line for line in lines if line.startswith('残留') and 'BLOCKQUOTE' in line]

        for body, label in (
                ('<blockquote><div><p>Run:</p><div class="highlight"><pre>make all</pre></div></div>'
                 '</blockquote>', 'Run:'),
                ('<blockquote><div><p>Values:</p><table><tr><th>K</th><th>V</th></tr>'
                 '<tr><td>a</td><td>1</td></tr></table></div></blockquote>', 'Values:')):
            with self.subTest(label=label):
                raw, source = self.parse(body)
                self.assertIn('[BLOCKQUOTE]\n\n' + label + '\n', source)
                # 约定写法：去掉提示行；引用里的段落加 >，代码围栏/表格不加、留在列 0
                rewritten = source.replace('[BLOCKQUOTE]\n\n', '').replace(label, '> 译文：')
                self.assertBinds(raw, source, rewritten)
                self.assertEqual(blockquote_residual(rewritten, source), [])
                moved = rewritten.replace('<a id="after"></a>\n\n\n', '').replace(
                    'See [after]', '<a id="after"></a>\n\nSee [after]')
                self.assertMisbinds(raw, source, moved)
                kept = source.replace(label, '> 译文：')  # 保留提示行：片段核验拒绝
                self.assertEqual(blockquote_residual(kept, source),
                                 ['残留块级占位符: [BLOCKQUOTE] FAIL'])


class BlockquoteObjectTests(ApiNavigationFixture, unittest.TestCase):
    """带 id 的引用块是来源对象：锚点随引用块，链接跳到对应引用块（R3）。"""

    RAW = ('<article><h1 id="same">A</h1><p>See <a href="#q1">(1)</a> and <a href="#q2">(2)</a>.</p>'
           '<blockquote id="q1"><div><ol class="arabic simple"><li><p>First note.</p></li></ol>'
           '</div></blockquote><blockquote id="q2"><div><ol class="arabic simple" start="2"><li>'
           '<p>Second note.</p></li></ol></div></blockquote></article>')

    @staticmethod
    def quoted(text):
        return (text.replace('[BLOCKQUOTE]\n  - First note.', '> - 第一条。')
                    .replace('[BLOCKQUOTE]\n  - Second note.', '> - 第二条。'))

    def parsed(self):
        (self.root/'a.html').write_text(self.RAW)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        return (self.root/'a.md').read_text()

    def test_blockquotes_with_ids_are_source_objects(self):
        from _api_navigation import source_anchors
        anchors = source_anchors(self.RAW)
        self.assertEqual((anchors['q1'], anchors['q2']), (('blockquote', 1), ('blockquote', 2)))
        source = self.parsed()
        self.assertIn('<a id="q1"></a>\n\n\n[BLOCKQUOTE]\n  - First note.', source)
        self.assertEqual(anchor_diffs(self.RAW, self.quoted(source), source=source), [])
        swapped = (self.quoted(source).replace('"q1"', '"tmp"').replace('"q2"', '"q1"')
                   .replace('"tmp"', '"q2"'))
        self.assertTrue(anchor_diffs(self.RAW, swapped, source=source))

    def test_recovery_maps_same_section_blockquotes_by_position(self):
        """评审 T5(b)：同一节两个带 id 的引用块，当前合章写成 > 引用块时按位置对应；
        写成普通缩进列表时报无法唯一对应 blockquote。"""
        from _api_navigation import _recovery_object_lines, source_anchors
        source = self.parsed()
        facts = dict(source=source, raw=self.RAW, section_id=None,
                     anchors=source_anchors(self.RAW))
        # 当前合章：去掉锚点行，两个 [BLOCKQUOTE] 按约定写成 > 引用块
        quoted = source
        for name in ('same', 'q1', 'q2'):
            quoted = quoted.replace('<a id="%s"></a>\n' % name, '')
        quoted = (quoted.replace('[BLOCKQUOTE]\n  - First note.', '> - First note.')
                        .replace('[BLOCKQUOTE]\n  - Second note.', '> - Second note.'))
        self.assertNotIn('[BLOCKQUOTE]', quoted)
        targets = _recovery_object_lines(quoted, 'a.html', facts, self.root/'01_AB.md')
        lines = quoted.splitlines()
        self.assertEqual(lines[targets['q1'] - 1], '> - First note.')
        self.assertEqual(lines[targets['q2'] - 1], '> - Second note.')
        damaged = quoted.replace('> - Second note.', '  - Second note.')
        with self.assertRaisesRegex(ValueError, '无法唯一对应 blockquote'):
            _recovery_object_lines(damaged, 'a.html', facts, self.root/'01_AB.md')

    def test_links_to_blockquotes_survive_merge_and_verify(self):
        (self.root/'trans_a.md').write_text(self.quoted(self.parsed()))
        output = self.root/'01_AB.md'
        self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                      '--navigation-record', self.root/'record.json')
        self.run_tool('verify_api_translation.py', output, self.root/'ab.txt', self.root/'ab.txt',
                      self.root, self.root/'a.md', self.root/'b.md',
                      '--navigation-record', self.root/'record.json')
        final = output.read_text()
        for name in ('q1', 'q2'):
            self.assertIn('](#'+namespaced('a.html', name)+')', final)
            self.assertIn('<a id="'+namespaced('a.html', name)+'"></a>', final)


class LinkOrderFragmentTests(unittest.TestCase):
    """有来源锚点行的 API 片段，片段核验就查链接顺序（R6）。"""

    SOURCE = '<a id="intro"></a>\n\n## Intro\n\nSee [first](#a) and [second](#b).\n'

    def order_lines(self, doc, src):
        from verify_translation import run_checks
        with tempfile.TemporaryDirectory() as tmp:
            _fail, lines = run_checks(doc, src, doc_dir=tmp, doc_label='doc.md',
                                      src_label='src.md', fragment=True)
        return [line for line in lines if line.startswith('链接顺序')]

    def test_swapped_links_reported_with_position(self):
        healthy = self.SOURCE.replace('See [first](#a) and [second](#b).', '见[第一](#a)和[第二](#b)。')
        self.assertEqual(self.order_lines(healthy, self.SOURCE), [])
        swapped = self.SOURCE.replace('See [first](#a) and [second](#b).', '见[第二](#b)和[第一](#a)。')
        self.assertEqual(self.order_lines(swapped, self.SOURCE),
                         ['链接顺序: 第 1 个链接：源 #a（L5），译 #b（L5） FAIL'])

    def test_sources_without_anchor_lines_are_not_order_checked(self):
        source = self.SOURCE.replace('<a id="intro"></a>\n\n', '')
        swapped = source.replace('See [first](#a) and [second](#b).', '见[第二](#b)和[第一](#a)。')
        self.assertEqual(self.order_lines(swapped, source), [])

    def test_first_link_difference(self):
        from _api_navigation import first_link_difference
        self.assertIsNone(first_link_difference('[a](#a) [b](#b)\n', '[甲](#a) [乙](#b)\n'))
        self.assertEqual(first_link_difference('[a](#a)\n', '[a](#a)\n\n[b](#b)\n'),
                         '链接数不同：源 1，译 2，从第 2 个起')

    def test_reflowed_links_in_same_order_pass(self):
        """评审关注：译文调整断行、合并段落，链接换了行但先后不变，不报链接顺序。"""
        source = self.SOURCE.replace('See [first](#a) and [second](#b).',
                                     'See [first](#a).\n\nAlso [second](#b).')
        merged = source.replace('See [first](#a).\n\nAlso [second](#b).', '见[第一](#a)，另见[第二](#b)。')
        self.assertEqual(self.order_lines(merged, source), [])
        swapped = source.replace('See [first](#a).\n\nAlso [second](#b).', '见[第二](#b)，另见[第一](#a)。')
        self.assertEqual(self.order_lines(swapped, source),
                         ['链接顺序: 第 1 个链接：源 #a（L5），译 #b（L5） FAIL'])


class SourceBrokenLinkTests(ApiNavigationFixture, unittest.TestCase):
    """原站本来就坏的链接：未登记时合章阻断；回源登记后去掉链接、保留文字（R4）。"""

    RAW = ('<article><h1 id="same">A</h1><p>See <a href="#missing-object">the section</a> '
           'and <a href="#t">table</a>.</p><table id="t"><tr><th>Name</th><th>Value</th></tr>'
           '<tr><td><a href="#missing-object">cell link</a></td><td>1</td></tr></table></article>')

    def setUp(self):
        super().setUp()
        (self.root/'a.html').write_text(self.RAW)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        (self.root/'trans_a.md').write_text((self.root/'a.md').read_text())

    def register(self, *hrefs):
        self.record['sources'][0]['snapshots'][0]['source_broken_links'] = [
            {'href': href, 'basis': '回源确认：原快照没有这个 id'} for href in hrefs]
        self.save_record()

    def merge_ab(self, ok=True):
        return self.run_tool('merge_api.py', self.root/'ab.txt', self.root, self.root/'01_AB.md',
                             '--navigation-record', self.root/'record.json', ok=ok)

    def test_unregistered_broken_link_blocks_merge(self):
        result = self.merge_ab(ok=False)
        self.assertIn('源文坏链接未登记', result.stderr)
        self.assertIn('#missing-object', result.stderr)
        self.assertFalse((self.root/'01_AB.md').exists())

    def test_registered_broken_link_becomes_text(self):
        self.register('#missing-object')
        self.merge_ab()
        final = (self.root/'01_AB.md').read_text()
        self.assertIn('See the section and [table](', final)
        self.assertIn('cell link | 1', final)
        self.assertNotIn('missing-object', final)
        self.run_tool('verify_api_translation.py', self.root/'01_AB.md', self.root/'ab.txt',
                      self.root/'ab.txt', self.root, self.root/'a.md', self.root/'b.md',
                      '--navigation-record', self.root/'record.json')

    def test_registration_must_name_a_present_link_whose_id_is_absent(self):
        self.register('#missing-object', '#t')
        self.assertIn('目标页快照里有这个 id', self.merge_ab(ok=False).stderr)
        self.register('#not-in-the-page-text')
        self.assertIn('解析稿里没有这个链接', self.merge_ab(ok=False).stderr)

    def test_translation_cannot_point_a_valid_link_to_a_missing_id(self):
        self.register('#missing-object')
        trans = self.root/'trans_a.md'
        trans.write_text(trans.read_text().replace('[table](#t)', '[table](#nowhere)'))
        self.assertIn('翻译页改变原链接目标', self.merge_ab(ok=False).stderr)

    def test_malformed_registration_is_rejected(self):
        self.record['sources'][0]['snapshots'][0]['source_broken_links'] = [{'href': '#missing-object'}]
        self.save_record()
        self.assertIn('source_broken_links 无效', self.merge_ab(ok=False).stderr)

    def test_present_id_that_is_not_an_object_stays_a_parse_gap(self):
        """快照里有、但不是来源对象的 id（如段落里的 span）仍按解析缺口失败，也不能登记成坏链接。"""
        raw = ('<article><h1 id="same">A</h1><p>See <a href="#inline">x</a>.</p>'
               '<p>Text <span id="inline">here</span>.</p></article>')
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        (self.root/'trans_a.md').write_text((self.root/'a.md').read_text())
        result = self.merge_ab(ok=False)
        self.assertIn('来源目标缺失或无法定位: a.html → #inline', result.stderr)
        self.assertNotIn('源文坏链接未登记', result.stderr)
        self.register('#inline')
        self.assertIn('目标页快照里有这个 id', self.merge_ab(ok=False).stderr)

    def test_removing_a_link_keeps_its_label(self):
        from _api_navigation import replace_links
        text = 'A [a \\[b\\] c](#bad), [see [1]](#bad), [![x](i.png)](#bad) and [ok](#good).\n'
        self.assertEqual(replace_links(text, lambda href: None if href == '#bad' else href),
                         'A a \\[b\\] c, see [1], ![x](i.png) and [ok](#good).\n')

    def test_cross_page_broken_link(self):
        """评审关注：指向另一页的坏链接按目标页快照判断；登记后去掉链接，目标页有该 id 时登记被拒。"""
        raw = ('<article><h1 id="same">A</h1><p>See <a href="b.html#gone">B gone</a> '
               'and <a href="b.html#same">B</a>.</p></article>')
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        (self.root/'trans_a.md').write_text((self.root/'a.md').read_text())
        self.assertIn('源文坏链接未登记: a.html → b.html#gone', self.merge_ab(ok=False).stderr)
        self.register('b.html#same')
        self.assertIn('目标页快照里有这个 id', self.merge_ab(ok=False).stderr)
        self.register('b.html#gone')
        self.merge_ab()
        self.assertIn('See B gone and [B](#' + namespaced('b.html', 'same') + ')',
                      (self.root/'01_AB.md').read_text())


class MergeReportsAllProblemsTests(ApiNavigationFixture, unittest.TestCase):
    """一次合章报出所有页、所有类别的问题；失败时旧成品不变（R7）。"""

    RAW = ('<article><h1 id="same">A</h1><p>See <a href="#p1">one</a> and <a href="#t">two</a>.</p>'
           '<p id="p1">Para.</p><table id="t"><tr><th>Name</th><th>Value</th></tr>'
           '<tr><td>x</td><td>1</td></tr></table></article>')

    def test_transform_page_reports_anchor_link_and_table_together(self):
        from _api_navigation import source_anchors, transform_page
        (self.root/'a.html').write_text(self.RAW)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        source = (self.root/'a.md').read_text()
        chapter = (self.root/'01_AB.md').resolve()
        pages = {'a.html': {'chapter': chapter, 'anchors': source_anchors(self.RAW), 'raw': self.RAW,
                            'section_id': None, 'source': source, 'resources': {},
                            'header_cells': {(1, 2, 1)}, 'broken_links': set()}}
        healthy = source.replace('x | 1', '**x** | 1')
        transform_page(healthy, 'a.html', pages, chapter)
        damaged = (healthy.replace('See [one](#p1) and [two](#t).', 'See [two](#t) and [one](#p1).')
                          .replace('<a id="p1"></a>\n\n\nPara.', 'Para.')
                          .replace('<a id="t"></a>', '<a id="p1"></a>\n\n<a id="t"></a>')
                          .replace('**x** | 1', 'x | 1'))
        with self.assertRaises(ValueError) as caught:
            transform_page(damaged, 'a.html', pages, chapter)
        message = str(caught.exception)
        for expected in ('翻译页锚点无来源证明', '锚点目标错绑: p1；期望 paragraph #', '实际紧随 table #1',
                         '翻译页改变原链接目标', '第 1 个链接：源 #p1', '表头角色丢失'):
            self.assertIn(expected, message)

    def test_merge_lists_every_failing_page_and_keeps_old_output(self):
        output = self.root/'01_AB.md'
        output.write_text('旧成品\n')
        a, b = self.root/'trans_a.md', self.root/'trans_b.md'
        a.write_text(a.read_text().replace('[table](#t) [B](b.html#same)', '[B](b.html#same) [table](#t)')
                                  .replace('<a id="t"></a>\n', ''))
        b.write_text(b.read_text().replace('[B own](#same) [A](a.html#same)', '[A](a.html#same) [B own](#same)'))
        result = self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                               '--navigation-record', self.root/'record.json', ok=False)
        self.assertIn('合章失败，2 页有问题，未写出成品', result.stderr)
        self.assertIn('缺来源对象锚点 t', result.stderr)
        self.assertEqual(result.stderr.count('翻译页改变原链接目标'), 2)
        self.assertEqual(output.read_text(), '旧成品\n')

    def test_conversion_failure_does_not_hide_anchor_problems(self):
        """评审关注：某页链接转换失败（未登记的源文坏链接）时，同页的锚点和表格问题照样一起报出。"""
        from _api_navigation import link_occurrences, source_anchors, transform_page
        raw = ('<article><h1 id="same">A</h1><p>See <a href="#gone">gone</a>.</p>'
               '<p id="p1">Para.</p><table id="t"><tr><th>x</th><th>1</th></tr></table></article>')
        (self.root/'a.html').write_text(raw)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        source = (self.root/'a.md').read_text()
        chapter = (self.root/'01_AB.md').resolve()
        pages = {'a.html': {'chapter': chapter, 'anchors': source_anchors(raw), 'raw': raw,
                            'section_id': None, 'source': source, 'resources': {},
                            'header_cells': {(1, 1, 1)}, 'broken_links': set()}}
        damaged = source.replace('<a id="p1"></a>\n', '')
        with self.assertRaises(ValueError) as caught:
            transform_page(damaged, 'a.html', pages, chapter)
        message = str(caught.exception)
        self.assertIn('缺来源对象锚点 p1', message)
        self.assertIn('链接转换失败: 源文坏链接未登记: a.html → #gone', message)
        line = next(number for number, href in link_occurrences(damaged) if href == '#gone')
        self.assertIn('（译文 L%d）' % line, message)
        self.assertIn('导航转换损伤表格: a.html', message)
        self.assertIn('表头角色丢失', message)


class FigureAliasTests(ApiNavigationFixture, unittest.TestCase):
    """figure 开头的别名 id 是其中的图片对象：锚点随图片，链接跳到对应图片（R9）。"""

    RAW = ('<article><h1 id="same">A</h1><p>See <a href="#figure-one">Figure 51</a> '
           'and <a href="#figure-two">Figure 52</a>.</p>'
           '<figure id="id1"><span id="figure-one"></span>'
           '<a class="reference internal image-reference" href="images/one.png">'
           '<img alt="First" src="images/one.png"/></a></figure>'
           '<figure id="id2"><span id="figure-two"></span>'
           '<a class="reference internal image-reference" href="images/two.png">'
           '<img alt="Second" src="images/two.png"/></a></figure></article>')

    def parsed(self):
        (self.root/'a.html').write_text(self.RAW)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        return (self.root/'a.md').read_text()

    def test_figure_aliases_are_the_image_objects(self):
        from _api_navigation import source_anchors
        anchors = source_anchors(self.RAW)
        self.assertEqual((anchors['id1'], anchors['id2']), (('image', 1), ('image', 2)))
        self.assertEqual(anchors['figure-one'], anchors['id1'])
        self.assertEqual(anchors['figure-two'], anchors['id2'])
        source = self.parsed()
        for own, alias in (('id1', 'figure-one'), ('id2', 'figure-two')):
            self.assertLess(source.index('<a id="%s"></a>' % own),
                            source.index('<a id="%s"></a>' % alias))
        swapped = (source.replace('<a id="figure-one"></a>', '@@')
                   .replace('<a id="figure-two"></a>', '<a id="figure-one"></a>')
                   .replace('@@', '<a id="figure-two"></a>'))
        self.assertTrue(anchor_diffs(self.RAW, swapped, source=source))
        deleted = source.replace('<a id="figure-two"></a>\n', '', 1)
        self.assertTrue(anchor_diffs(self.RAW, deleted, source=source))

    def test_links_to_figure_aliases_survive_merge_and_verify(self):
        # 本文件首个含 <img> 的 fixture：合章的来源准入要求图片文件存在、
        # 记录条目带 per_stem_map（map 由 parse 自动生成）
        (self.root/'images').mkdir()
        fixture = Path(__file__).resolve().parents[1]/'tests'/'fixtures'/'valid_1x1.png'
        for name in ('one.png', 'two.png'):
            (self.root/'images'/name).write_bytes(fixture.read_bytes())
        source = self.parsed()
        self.record['sources'][0]['snapshots'][0]['per_stem_map'] = 'a.images_display.json'
        self.save_record()
        (self.root/'trans_a.md').write_text(source)
        output = self.root/'01_AB.md'
        self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                      '--navigation-record', self.root/'record.json')
        self.run_tool('verify_api_translation.py', output, self.root/'ab.txt', self.root/'ab.txt',
                      self.root, self.root/'a.md', self.root/'b.md',
                      '--navigation-record', self.root/'record.json')
        final = output.read_text()
        for alias in ('figure-one', 'figure-two'):
            self.assertIn('](#'+namespaced('a.html', alias)+')', final)
            self.assertIn('<a id="'+namespaced('a.html', alias)+'"></a>', final)


class MultiBacklinkFootnoteMergeTests(ApiNavigationFixture, unittest.TestCase):
    """含多回链脚注的页按导航合章：回链是纯文字；译文写回链接被拒绝（R10）。"""

    RAW = ('<article><h1 id="same">A</h1><p>Counts <a class="footnote-reference brackets" '
           'href="#family2" id="id2" role="doc-noteref"><span class="fn-bracket">[</span>1'
           '<span class="fn-bracket">]</span></a> and limits <a class="footnote-reference brackets" '
           'href="#family2" id="id3" role="doc-noteref"><span class="fn-bracket">[</span>1'
           '<span class="fn-bracket">]</span></a> differ.</p>'
           '<aside class="footnote brackets" id="family2" role="doc-footnote">'
           '<span class="label"><span class="fn-bracket">[</span>1<span class="fn-bracket">]</span></span>'
           '<span class="backrefs">(<a href="#id2" role="doc-backlink">1</a>,'
           '<a href="#id3" role="doc-backlink">2</a>)</span>'
           '<p>Some families only contain a single member.</p></aside></article>')

    def test_multibacklink_page_merges_and_verifies(self):
        (self.root/'a.html').write_text(self.RAW)
        self.run_tool('parse_api_html.py', self.root/'a.html', self.root/'a.md')
        source = (self.root/'a.md').read_text()
        self.assertIn('(1, 2)', source)
        (self.root/'trans_a.md').write_text(source)
        output = self.root/'01_AB.md'
        self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                      '--navigation-record', self.root/'record.json')
        self.run_tool('verify_api_translation.py', output, self.root/'ab.txt', self.root/'ab.txt',
                      self.root, self.root/'a.md', self.root/'b.md',
                      '--navigation-record', self.root/'record.json')
        self.assertIn('(1, 2)', output.read_text())
        damaged = source.replace('(1, 2)', '([1](#id2), [2](#id3))', 1)
        (self.root/'trans_a.md').write_text(damaged)
        self.run_tool('merge_api.py', self.root/'ab.txt', self.root, output,
                      '--navigation-record', self.root/'record.json', ok=False)


if __name__=='__main__':unittest.main()
