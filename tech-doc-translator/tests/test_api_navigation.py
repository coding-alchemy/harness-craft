"""来源页身份、表外锚点及本章片段的真实 CLI 消费。"""
import json, subprocess,sys,tempfile,unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/tech-doc-translator/scripts'
sys.path.insert(0,str(SCRIPTS))
from _api_navigation import load_navigation,namespaced,verify_page,anchor_diffs

class ApiNavigationTests(unittest.TestCase):
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
