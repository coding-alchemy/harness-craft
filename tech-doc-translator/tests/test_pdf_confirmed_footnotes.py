"""确认PDF脚注通过正式准备、独立来源及实际译文消费。"""
import json
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pdf_test_support import (
    original, fact_digest, pdf_project_context, SCRIPTS, HAVE_PYMUPDF, pymupdf,
)


def render_confirmed(root, source, target):
    import export_pdf as exporter
    chapter=exporter.Chapter(1,target)
    exporter.apply_pdf_math_context([chapter],{'sources':[{'pdf_source':{
        'root':str(root),'pdf':'paper.pdf','checklist':'source/adjudication_checklist.json',
        'block_map':'source/source.md.blocks.json','source_markdown':str(source),'covers':[str(target)]}}]})
    exporter.parse_chapter(chapter)
    return chapter


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF不可用')
class ConfirmedPdfFootnoteTests(unittest.TestCase):
    def test_code_first_definition_keeps_empty_container_and_code_bytes(self):
        import os
        scripts=SCRIPTS
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);name='code-first';prose=False
            root=base/name;root.mkdir(exist_ok=True);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page()
                for y,t in [(60,'Code note trial'),(100,'Body1'),(200,'1 Note' if prose else '1'),(270,'Continued x=1'),(350,'Tail')]:p.insert_text((50,y),t)
                p.insert_text((60,225),'print(x)',fontname='cour',fontsize=10);d.save(pdf)
            def run(*args):
                q=subprocess.run([sys.executable,str(scripts/'prepare_pdf_source.py'),*map(str,args)],capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                return {'args':list(map(str,args)),'returncode':q.returncode,'stdout':q.stdout,'stderr':q.stderr}
            inspection=run('inspect',pdf,'--output',root/'source');cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                p=d[0];title=original(p,'Code note trial')
                blocks=[{'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},{'id':'body','type':'paragraph','page':1,'rect':[45,80,180,110],'order':2,'content':[{'type':'text','origin':original(p,'Body')},{'type':'footnote_ref','label':'1','origin':original(p,'1')}]},{'id':'note','type':'footnote_def','page':1,'rect':[45,180,300,310],'order':3,'footnote_label':'1','footnote_origin':original(p,'1',1),'content':[{'type':'text','origin':original(p,'Note')}] if prose else []},{'id':'code','type':'code_region','page':1,'rect':[55,208,280,240],'order':4,'footnote':'note','golden':'goldens/note.txt','lang':'python'},{'id':'tail','type':'paragraph','page':1,'rect':[45,330,180,360],'order':6,'content':[{'type':'text','origin':original(p,'Tail')}]}]
                math={'type':'math','id':'m','slot':1,'owner':{'block':'continued','role':'paragraph'},'kind':'inline','tex':'x=1','label':None,'origin':original(p,'x=1'),'conversion':{'source':'x=1','target':'x=1','basis':'native mathematical expression in continued note paragraph'}}
                math['confirmation']={'scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(math),'basis':'native continued mathematical paragraph and code-first definition'}
                blocks.insert(-1,{'id':'continued','type':'paragraph','page':1,'rect':[45,250,280,280],'order':5,'footnote':'note','content':[{'type':'text','origin':original(p,'Continued ')},math]})
                c.update(formula_contract='confirmed-tex-v1',formula_review={'scope':[1],'source_sha256':c['source']['sha256'],'basis':'selected original body/ref and whole code-only or paragraph-plus-code definition'},reading_order={'adjudicated':True,'basis':'native title body footnote then tail'},blocks=blocks)
            cp.write_text(json.dumps(c));extract=run('extract-code',pdf,'--checklist',cp,'--output',root/'source');materialize=run('materialize',pdf,'--checklist',cp,'--output',root/'source/source.md')
            self.assertEqual(0,extract["returncode"],extract)
            self.assertEqual(0,materialize["returncode"],materialize)
            self.assertEqual("print(x)\n",(root/"source/goldens/note.txt").read_text())
            source=root/'source/source.md';ctx=pdf_project_context(root);target=root/'translation.md'
            body=source.read_text().split('\n---\n',1)[1].replace('Body[^1]','正文[^1]').replace('Continued ','续段 ').replace('\nTail','\n尾段')
            same_line=body.replace('[^1]:\n\n    ```python','[^1]: ```python')
            for value in (body,same_line,body.replace('print(x)','print(y)'),body.replace('    ```','```').replace('    print(x)','print(x)')):
                target.write_text(value)
                for script,args in [('verify_pdf_source.py',[pdf,'--checklist',cp,'--source-md',source,'--translation',target]),('verify_translation.py',[target,source,'--project-context',ctx])]:
                    q=subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
                    if value in (body,same_line):self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                    else:self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'代码|golden|脚注|所属|叶子|宿主')
            target.write_text(body);chapter=render_confirmed(root,source,target)
            self.assertEqual('print(x)\n',chapter.soup.select_one('li.footnote-item pre').get_text())
            self.assertEqual(['x=1'],[item['latex'] for item in chapter.math])
            # The first child remains code in the real PDF, beside its note label.
            target.write_text(body.replace('# Code note trial','# Code note trial\n\n> **来源**：'+str(pdf),1))
            import verify_delivery as v
            record=json.loads((root/'record.json').read_text());record['checks'][0]['args']+=['--translation','translation.md']
            problems=[];entries=v.check_source_chains(str(root),record,problems);identity=v.compute_delivery_identity(str(root),record,entries);_,_,checks,pdfs=v.rerun_checks(str(root),record,problems)
            self.assertEqual([],problems)
            for kind in ('source-reconcile','semantic'):
                record['reviews'].append({'kind':kind,'target':'translation.md','status':'closed','sha256':v.sha256_file(str(target)),'binding':v.expected_review_binding(kind,'translation.md',str(root),record,entries,checks,pdfs,identity),'note':'native fixture has code first, then inline math paragraph','items':['code bytes','note ownership','inline equation'],'unresolved':[]})
            rp=root/'ready.json';rp.write_text(json.dumps(record))
            view=root/'view.json';view.write_text(json.dumps({'version':1,'inputs':[{'path':str(target),'sha256':v.sha256_file(str(target))}],'exclusions':[],'document_title':{'original':'Code note trial','chinese':'代码首块脚注试验','basis':'native fixture title translation'}}))
            for script,args in [('export_pdf.py',['--output',root/'result.pdf','--work-dir',root/'export','--translation-record',rp,'--view-declaration',view,target]),('verify_pdf.py',['--pdf',root/'result.pdf','--work-dir',root/'export','--view-declaration',view,target])]:
                q=subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
                self.assertEqual(0,q.returncode,q.stdout+q.stderr)

    def test_same_expression_in_two_definitions_keeps_identity_and_reference_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as doc:
                p=doc.new_page()
                for y,value in [(60,'Two notes'),(100,'Body21'),(200,'1 First x=1'),(300,'2 Second x=1')]:p.insert_text((50,y),value)
                doc.save(pdf)
            def run(script,*args):return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as doc:
                p=doc[0];title=original(p,'Two notes')
                blocks=[{'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                        {'id':'body','type':'paragraph','page':1,'rect':[45,80,180,110],'order':2,'content':[{'type':'text','origin':original(p,'Body')},{'type':'footnote_ref','label':'2','origin':original(p,'2')},{'type':'footnote_ref','label':'1','origin':original(p,'1')}]}]
                for index,word in enumerate(('First ','Second ')):
                    label=str(index+1);identity='note'+label
                    math={'type':'math','id':'math'+label,'slot':1,'owner':{'block':identity,'role':'footnote_def'},'kind':'inline','tex':'x=1','label':None,'origin':original(p,'x=1',index),'conversion':{'source':'x=1','target':'x=1','basis':'each distinct native footnote equation'}}
                    math['confirmation']={'scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(math),'basis':'original note separately located'}
                    blocks.append({'id':identity,'type':'footnote_def','page':1,'rect':[45,180+100*index,250,220+100*index],'order':3+index,'footnote_label':label,'footnote_origin':original(p,label,1),'content':[{'type':'text','origin':original(p,word)},math]})
            c.update(formula_contract='confirmed-tex-v1',formula_review={'scope':[1],'source_sha256':c['source']['sha256'],'basis':'both native references and complete definitions'},reading_order={'adjudicated':True,'basis':'native body then both notes'},blocks=blocks);cp.write_text(json.dumps(c))
            source=root/'source/source.md';q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            ctx=pdf_project_context(root);target=root/'translation.md';body='# Two notes\n\n正文[^2][^1]\n\n[^1]: 第一注$x=1$\n\n[^2]: 第二注$x=1$\n'
            for value in [body,body.replace('正文[^2][^1]','正文[^1][^2]'),body.replace('[^1]: 第一注$x=1$\n\n[^2]: 第二注$x=1$','[^2]: 第二注$x=1$\n\n[^1]: 第一注$x=1$'),body.replace('第一注','')]:
                target.write_text(value)
                for script,args in [('verify_pdf_source.py',[pdf,'--checklist',cp,'--source-md',source,'--translation',target]),('verify_translation.py',[target,source,'--project-context',ctx])]:
                    q=run(script,*args)
                    if value==body:self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                    else:self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'数学|脚注|所属|叶子')
            target.write_text(body);chapter=render_confirmed(root,source,target)
            notes=chapter.soup.select('li.footnote-item')
            self.assertEqual(2,len(notes));self.assertIn('第二注',notes[0].get_text());self.assertIn('第一注',notes[1].get_text())
            self.assertEqual(['x=1','x=1'],[item['latex'] for item in chapter.math])
            current=json.loads(Path(str(source)+'.blocks.json').read_text())
            for kind in ('id','range'):
                changed=copy.deepcopy(current);a=changed['blocks'][2]['math'][0];b=changed['blocks'][3]['math'][0]
                for key in (['id'] if kind=='id' else ['md_start','md_end']):a[key],b[key]=b[key],a[key]
                path=root/(kind+'.blocks.json');path.write_text(json.dumps(changed));q=run('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--block-map',path)
                self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'身份|区间|所属')

    def test_definition_subblocks_preserve_math_whitespace_cells_and_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as doc:
                p=doc.new_page()
                for x,y,value in [(50,60,'Structured footnote trial'),(50,100,'Body1'),(50,200,'1 First x=1+[^b]'),(100,215,'+y'),(50,260,'Second z=2'),(100,275,'w=3'),(50,320,'- Item k=3'),(140,370,'Group'),(50,410,'Count'),(230,410,'|n|=4'),(230,425,'n>0'),(290,410,'(7)'),(50,580,'Tail')]:p.insert_text((x,y),value)
                p.insert_text((50,470),'for x in xs:',fontname='cour',fontsize=10);p.insert_text((74,485),'use(x)',fontname='cour',fontsize=10)
                doc.save(pdf)
            def run(script,*args):return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as doc:
                p=doc[0];title=original(p,'Structured footnote trial')
                def math(identity,block,role,slot,native,tex,kind='inline',cell=None,label=None):
                    origin=original(p,native[0])
                    for value in native[1:]:
                        part=original(p,value);origin['text']+='\n'+part['text'];origin['fragments']+=part['fragments'];origin['rect']=[min(origin['rect'][0],part['rect'][0]),min(origin['rect'][1],part['rect'][1]),max(origin['rect'][2],part['rect'][2]),max(origin['rect'][3],part['rect'][3])]
                    owner={'block':block,'role':role}
                    if cell is not None:owner['cell']=cell
                    item={'type':'math','id':identity,'slot':slot,'owner':owner,'kind':kind,'tex':tex,'label':label,'origin':origin,'conversion':{'source':origin['text'],'target':tex,'basis':'native note mathematical lines; explicit representation whitespace stays inside math, not footnote syntax'}}
                    item['confirmation']={'basis':'native original note child and mathematical order','scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(item)}
                    return item
                first=math('first','note','footnote_def',1,['x=1+[^b]','+y'],' x=1+[^b]\n\n  +y ')
                second=math('second','continued','paragraph',1,['z=2','w=3'],r'\begin{aligned}z&=2\\'+'\n  '+r'w&=3\end{aligned}','block')
                listed=math('listed','item','list_item',1,['k=3'],'k=3')
                cells=[]
                for row,col,value in [(1,1,'Group'),(2,1,'Count'),(2,2,'n=4')]:
                    cell='r%dc%d'%(row,col);content=[math('cell','table','table_region',0,['|n|=4','n>0'],r'\begin{aligned}|n|&=4\\'+'\n '+r'n&>0\end{aligned}',kind='block',cell=cell,label={'text':'(7)','origin':original(p,'(7)')})] if value=='n=4' else [{'type':'text','origin':original(p,value)}]
                    cells.append({'id':cell,'row':row,'column':col,'rowspan':1,'colspan':2 if row==1 else 1,'header':row==1,'rect':[45+180*(col-1),350+40*(row-1),400 if row==1 else 220+180*(col-1),380 if row==1 else 440],'content':content})
                c.update(formula_contract='confirmed-tex-v1',formula_review={'scope':[1],'source_sha256':c['source']['sha256'],'basis':'entire structured note fixture'},reading_order={'adjudicated':True,'basis':'native body, complete note in order then tail'},blocks=[
                    {'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                    {'id':'body','type':'paragraph','page':1,'rect':[45,80,180,110],'order':2,'content':[{'type':'text','origin':original(p,'Body')},{'type':'footnote_ref','label':'1','origin':original(p,'1')}]},
                    {'id':'note','type':'footnote_def','page':1,'rect':[45,180,405,530],'order':3,'footnote_label':'1','footnote_origin':original(p,'1',1),'content':[{'type':'text','origin':original(p,'First ')},first]},
                    {'id':'continued','type':'paragraph','page':1,'rect':[45,240,250,280],'order':4,'footnote':'note','content':[{'type':'text','origin':original(p,'Second ')},second]},
                    {'id':'item','type':'list_item','page':1,'rect':[45,300,250,330],'order':5,'footnote':'note','content':[{'type':'text','origin':original(p,'- Item ')},listed]},
                    {'id':'table','type':'table_region','page':1,'rect':[45,350,405,445],'order':6,'footnote':'note','cells':cells,'table_conversion':{'basis':'native note two-column merged header explicitly expanded to both target header cells; data cells unchanged','rows':2,'columns':2,'cells':[{'source':'r1c1','row':1,'column':1},{'source':'r1c1','row':1,'column':2},{'source':'r2c1','row':2,'column':1},{'source':'r2c2','row':2,'column':2}]}},
                    {'id':'code','type':'code_region','page':1,'rect':[45,455,280,500],'order':7,'footnote':'note','golden':'goldens/note.txt','lang':'python'},
                    {'id':'tail','type':'paragraph','page':1,'rect':[45,560,180,590],'order':8,'content':[{'type':'text','origin':original(p,'Tail')}]}])
            cp.write_text(json.dumps(c));q=run('prepare_pdf_source.py','extract-code',pdf,'--checklist',cp,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            source=root/'source/source.md';q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            ctx=pdf_project_context(root);target=root/'translation.md';body=source.read_text().split('\n---\n',1)[1]
            body=body.replace('Body[^1]','正文[^1]').replace('First ','首段 ').replace('Second ','续段 ').replace('- Item ','- 条目 ').replace('Group','分组').replace('Count','数量').replace('\nTail','\n尾段')
            tabbed='\n'.join(('\t'+line[4:]) if line.startswith('    ') else line for line in body.split('\n'))
            for value in [body,tabbed,body.replace('  +y',' +y'),body.replace('    - 条目','- 条目'),body.replace('    use(x)','   use(x)'),body.replace('n&amp;&gt;0','n&amp;&gt;1'),body.replace('(7)','(8)'),body.replace('    续段','续段')]:
                target.write_text(value)
                for script,args in [('verify_pdf_source.py',[pdf,'--checklist',cp,'--source-md',source,'--translation',target]),('verify_translation.py',[target,source,'--project-context',ctx])]:
                    q=run(script,*args)
                    if value in (body,tabbed):
                        self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                        if script=='verify_translation.py':self.assertIn('公式逐项核对: 4 处',q.stdout)
                    else:self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'数学|脚注|所属|代码|golden')
            for value in (body,tabbed):
                target.write_text(value);chapter=render_confirmed(root,source,target)
                self.assertEqual([first['tex'],second['tex'],listed['tex'],cells[-1]['content'][0]['tex']+r'\tag*{\text{(7)}}'],[item['latex'] for item in chapter.math])
                self.assertEqual('for x in xs:\n    use(x)\n',chapter.soup.select_one('pre').get_text())
            q=run('split_work_packages.py',source,root/'wps',root/'trans','chars:60','--project-context',ctx)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            for variant in (tabbed,body.replace('[^1]:','   [^1]:')):
                for package in sorted((root/'wps').glob('wp_*.md')):
                    raw=package.read_text();head,part=raw.split('\n---\n',1)
                    # Only change actual definition syntax; preserve all code and math.
                    if '[^1]:' in part:
                        part=variant[variant.index('# Structured footnote trial'):variant.rfind('\n尾段')].rstrip()+'\n'
                    (root/'trans'/package.name).write_text(head+'\n---\n'+part)
                q=run('build_review_evidence.py','prepare','--source',source,'--source-packages',root/'wps','--strategy','chars:60','--project-context',ctx,'--output',root/'pending.json')
                self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            mapping=json.loads(Path(str(source)+'.blocks.json').read_text())
            next(b for b in mapping['blocks'] if b['id']=='code')['md_start']+=1
            badmap=root/'damaged.blocks.json';badmap.write_text(json.dumps(mapping))
            q=run('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--block-map',badmap)
            self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'精确区间|出现身份')

    def test_native_reference_definition_math_and_following_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page()
                for x,y,value in [(50,60,'Footnote trial'),(50,100,'Body1'),(50,200,'1 Note x=1'),(50,260,'Tail')]:
                    page.insert_text((x,y),value)
                doc.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as doc:
                p=doc[0];title=original(p,'Footnote trial')
                math={'type':'math','id':'note-math','slot':1,'owner':{'block':'note','role':'footnote_def'},
                      'kind':'inline','tex':'x=1','label':None,'origin':original(p,'x=1'),
                      'conversion':{'source':'x=1','target':'x=1','basis':'original note equation'}}
                math['confirmation']={'basis':'original note readback','scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(math)}
                c.update(formula_contract='confirmed-tex-v1',formula_review={'scope':[1],'source_sha256':c['source']['sha256'],'basis':'full selected page including reference and definition'},reading_order={'adjudicated':True,'basis':'native title, body, note then tail'},blocks=[
                    {'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                    {'id':'body','type':'paragraph','page':1,'rect':[45,80,180,110],'order':2,'content':[
                        {'type':'text','origin':original(p,'Body')},{'type':'footnote_ref','label':'1','origin':original(p,'1')}]},
                    {'id':'note','type':'footnote_def','page':1,'rect':[45,180,250,220],'order':3,'footnote_label':'1',
                     'footnote_origin':original(p,'1',1),'content':[{'type':'text','origin':original(p,'Note ')},math]},
                    {'id':'tail','type':'paragraph','page':1,'rect':[45,240,180,270],'order':4,'content':[{'type':'text','origin':original(p,'Tail')}]}])
            cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            ctx=pdf_project_context(root);target=root/'translation.md'
            body='# Footnote trial\n\n正文[^1]\n\n[^1]: 注释$x=1$\n\n尾段\n'
            for value in [body,body.replace('[^1]','[^2]'),body.replace('[^1]: 注释$x=1$','[^1]: 注释\n\n$x=1$'),body.replace('x=1','x=2')]:
                target.write_text(value)
                for script,args in [('verify_pdf_source.py',[pdf,'--checklist',cp,'--source-md',source,'--translation',target]),('verify_translation.py',[target,source,'--project-context',ctx])]:
                    q=run(script,*args)
                    if value==body:self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                    else:self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'数学|脚注|所属|引用')
            q=run('split_work_packages.py',source,root/'wps',root/'trans','chars:5000','--project-context',ctx);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            wp=root/'trans/wp_001.md';text=(root/'wps/wp_001.md').read_text().replace('Body[^1]','正文[^1]').replace('Note $x=1$','注释$x=1$').replace('Tail','尾段');wp.write_text(text)
            evidence=root/'pending.json';base=['--source',source,'--source-packages',root/'wps','--strategy','chars:5000','--project-context',ctx]
            q=run('build_review_evidence.py','prepare',*base,'--output',evidence);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            facts=json.loads(evidence.read_text())['wp_001.md'];facts.pop('review',None)
            record={'package':'wp_001.md','facts':facts,'scope':'original complete footnote fixture','basis':'independent native footnote fixture facts','note':'body/reference/definition/math and following text preserved','items':['reference target','definition mathematics','following body'],'reviewed_at':'2026-10-15','unresolved':[]}
            review=root/'human.json';review.write_text(json.dumps(record));q=run('build_review_evidence.py','register-review',*base,'--review-evidence',evidence,'--package','wp_001.md','--review-record',review,'--output',root/'qualified.json')
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
