"""正式PDF源CLI的确认数学合同；预期来自独立的原页文字及字面表达。"""
import hashlib
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pdf_test_support import (HAVE_PYMUPDF, pymupdf, draw_chart, CHART_A,
                              SCRIPTS, fact_digest, original)


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class ConfirmedPdfMathTests(unittest.TestCase):
    def test_group_publication_restores_old_members_and_removes_new_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page(width=500,height=400)
                draw_chart(p,['Batch A','Batch B','series one'])
                p.insert_text((50,250),'x+y=1 (1)')
                d.save(pdf)
            def run(*args):
                return subprocess.run([sys.executable,str(SCRIPTS/'prepare_pdf_source.py'),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('inspect',pdf,'--output',root).returncode)
            cp=root/'adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                item={'type':'math','id':'m','owner':{'block':'e','role':'formula'},'slot':0,
                      'origin':original(d[0],'x+y=1'),'kind':'block','tex':'x+y=1',
                      'label':{'text':'(1)','origin':original(d[0],'(1)')},
                      'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal original'}}
            item['confirmation']={'basis':'original formula','source_sha256':c['source']['sha256'],
                                  'scope':[1],'fact_sha256':fact_digest(item)}
            c.update(formula_contract='confirmed-tex-v1',
                     formula_review={'basis':'selected formula and independent graphic','source_sha256':c['source']['sha256'],'scope':[1]},
                     reading_order={'adjudicated':True,'basis':'formula then graphic'},
                     blocks=[{'id':'e','type':'formula','page':1,'rect':[45,235,250,260],'order':1,'content':[item]},
                             {'id':'figure','type':'figure_region','page':1,'rect':list(CHART_A),'order':2,
                              'image':'images/figure.png','adjudication':{'status':'accepted','basis':'fixture graphic'}}])
            cp.write_text(json.dumps(c))
            result=run('extract-figures',pdf,'--checklist',cp,'--output',root)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            source=root/'source.md';args=['materialize',str(pdf),'--checklist',str(cp),'--output',str(source)]
            result=run(*args);self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            members=[source,Path(str(source)+'.blocks.json'),Path(str(source)+'.images_display.json')]
            saved={p:p.read_bytes() for p in members}
            inputs={p:p.read_bytes() for p in [pdf,cp,root/'images/figure.png']}
            injection='''import os,sys
from pathlib import Path
import prepare_pdf_source
replace=os.replace
failed=Path(sys.argv[1]);injected=False
def fail_once(src,dst):
    global injected
    if Path(dst)==failed and not injected:
        injected=True
        raise OSError("injected actual member publication failure")
    return replace(src,dst)
os.replace=fail_once
prepare_pdf_source.main(sys.argv[2:])
'''
            for old in (True,False):
                for member in members:
                    with self.subTest(old=old,member=member.name):
                        for p in members:
                            if old:p.write_bytes(saved[p])
                            else:p.unlink(missing_ok=True)
                        result=subprocess.run([sys.executable,'-c',injection,str(member),*args],
                                              env={**os.environ,'PYTHONPATH':str(SCRIPTS)},capture_output=True,text=True)
                        self.assertNotEqual(0,result.returncode)
                        self.assertIn('整组发布失败',result.stdout+result.stderr)
                        for p in members:
                            if old:self.assertEqual(saved[p],p.read_bytes())
                            else:self.assertFalse(p.exists())
                        for p,data in inputs.items():self.assertEqual(data,p.read_bytes())

    def test_visible_label_braces_require_valid_representation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page()
                p.insert_text((50,70),'This explicit trial selects only the following numbered formula.')
                p.insert_text((50,110),'x+y=1 (1){a}')
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            path=root/'source/adjudication_checklist.json';c=json.loads(path.read_text())
            with pymupdf.open(pdf) as d:
                item={'type':'math','id':'brace-label','owner':{'block':'e','role':'formula'},
                      'slot':0,'origin':original(d[0],'x+y=1'),'kind':'block','tex':'x+y=1',
                      'label':{'text':'(1){a}','origin':original(d[0],'(1){a}')},
                      'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal formula readback'}}
            item['confirmation']={'basis':'fixture selected original formula','source_sha256':c['source']['sha256'],
                                  'scope':[1],'fact_sha256':fact_digest(item)}
            c.update(formula_contract='confirmed-tex-v1',
                     formula_review={'basis':'only selected numbered formula; other prose excluded',
                                     'source_sha256':c['source']['sha256'],'scope':[1]},
                     reading_order={'adjudicated':True,'basis':'single selected formula'},
                     blocks=[{'id':'e','type':'formula','page':1,'rect':[45,95,250,115],'order':1,'content':[item]}])
            path.write_text(json.dumps(c))
            source=root/'source/source.md'
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',path,'--output',source)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertIn(r'\{a\}',source.read_text())
            source.write_text(source.read_text().replace(r'\{a\}','{a}',1))
            # Update actual location to keep the negative about representation,
            # not a stale map or review binding.
            mp=Path(str(source)+'.blocks.json');mapping=json.loads(mp.read_text())
            mapping['blocks'][0]['md_end']-=2;mapping['blocks'][0]['math'][0]['md_end']-=2
            mp.write_text(json.dumps(mapping))
            result=run('verify_pdf_source.py',pdf,'--checklist',path,'--source-md',source)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('编号包装',result.stdout+result.stderr)

    def test_declared_pdf_math_cannot_split_without_explicit_source_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'source.md'
            source.write_text('---\npdf_formula_contract: confirmed-tex-v1\npdf_checklist: "checklist.json"\n---\n\n# Paper\n\n$x+y=1$\n')
            result=subprocess.run([sys.executable,str(SCRIPTS/'split_work_packages.py'),
                                   str(source),str(root/'wps'),str(root/'trans')],
                                  capture_output=True,text=True)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('project-context',result.stdout+result.stderr)
            self.assertFalse((root/'wps').exists())

    def test_single_line_confirmed_inline_and_numbered_display_reach_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root/'paper.pdf'
            with pymupdf.open() as d:
                p = d.new_page()
                p.insert_text((50, 70), 'Before &copy; x+y=1 after.')
                p.insert_text((50, 110), 'x+y=1 (1)')
                p.insert_text((50, 150), 'x_1 cost $1 code print(x_1)')
                p.insert_text((350, 110), 'x+y=1 (1)')
                d.save(pdf)
            def run(script, *args):
                return subprocess.run([sys.executable, str(SCRIPTS/script),
                                       *map(str,args)], capture_output=True, text=True)
            self.assertEqual(0, run('prepare_pdf_source.py','inspect',pdf,
                                   '--output',root/'source').returncode)
            path = root/'source/adjudication_checklist.json'
            c = json.loads(path.read_text())
            candidates=json.loads((root/'source/structure_candidates.json').read_text())['formulas']
            self.assertTrue(candidates)
            self.assertIn('fragments',candidates[0])
            self.assertEqual('rawdict',candidates[0]['extraction']['view'])
            self.assertFalse(c['blocks'])
            c['formula_contract'] = 'confirmed-tex-v1'
            c['formula_review'] = {'basis':'fixture original mathematical roles',
                                   'source_sha256':c['source']['sha256'], 'scope':[1]}
            c['reading_order'] = {'adjudicated':True,'basis':'fixture top to bottom'}
            with pymupdf.open(pdf) as d:
                p=d[0]
                def text(s):return {'type':'text','origin':original(p,s)}
                def math(block,kind,label=None):
                    item={'type':'math','id':'m-'+block,'owner':{'block':block,'role':'paragraph' if kind=='inline' else 'formula'},'slot':1 if kind=='inline' else 0,'origin':original(p,'x+y=1'),'kind':kind,'tex':'x+y=1','label':label,'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal original'}}
                    if kind=='block':
                        # Different physical occurrence with identical expression.
                        o=original(p,'x+y=1 (1)');o['text']='x+y=1';o['fragments'][0]['end']-=4;o['fragments'][0]['text']='x+y=1';item['origin']=o
                    item['confirmation']={'basis':'fixture original readback','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
                    return item
                c['blocks']=[{'id':'p','type':'paragraph','page':1,'rect':[45,55,250,75],'order':1,'content':[text('Before &copy; '),math('p','inline'),text(' after.')]}, {'id':'e','type':'formula','page':1,'rect':[45,95,250,115],'order':2,'content':[math('e','block',{'text':'(1)','origin':original(p,'(1)')})]}]
                right=copy.deepcopy(c['blocks'][1])
                right.update(id='right',order=3,rect=[345,95,550,115])
                item=right['content'][0]
                item.update(id='m-right',owner={'block':'right','role':'formula'})
                o=original(p,'x+y=1 (1)',1);o['text']='x+y=1';o['fragments'][0]['end']-=4;o['fragments'][0]['text']='x+y=1'
                item['origin']=o
                item['label']['origin']=original(p,'(1)',1)
                item['confirmation']['fact_sha256']=fact_digest(item)
                c['blocks'].append(right)
            path.write_text(json.dumps(c,ensure_ascii=False))
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',path,
                       '--output',root/'source/source.md')
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            source=(root/'source/source.md').read_text()
            self.assertIn(r'Before \&copy; $x+y=1$ after.',source)
            self.assertIn(r'\tag*{\text{(1)}}',source)
            self.assertNotIn('PENDING-FORMULA',source)
            result=run('verify_pdf_source.py',pdf,'--checklist',path,
                       '--source-md',root/'source/source.md')
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            record={'version':1,'mode':'translation','delivery_root':str(root),
                    'inputs':['translation.md'],'outputs':[],
                    'files':{'paper.pdf':'pdf','translation.md':'chapter'},
                    'sources':[{'family':'pdf-source','source_version':'fixture',
                                'pdf':'paper.pdf','checklist':'source/adjudication_checklist.json',
                                'source_markdown':'source/source.md',
                                'layout_snapshot':'source/snapshots_layout.txt',
                                'reading_snapshot':'source/snapshots_reading.txt',
                                'covers':['translation.md']}],
                    'checks':[{'tool':'verify_pdf_source','args':['paper.pdf',
                              '--checklist','source/adjudication_checklist.json',
                              '--source-md','source/source.md']}], 'reviews':[]}
            record_path=root/'record.json'
            record_path.write_text(json.dumps(record))
            # Public split must admit an image-free PDF source without requiring
            # an image mapping. Its source review binds the actual current files.
            sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            context={'project_root':str(root),'source_record':'record.json',
                     'source_scope':'all','source_review':{'scope':'all',
                     'basis':'fixture original readback','binding':{
                         'parsed_sha256':sha(root/'source/source.md'),
                         'source_version':'fixture','snapshots':[]}}
                     ,'instructions':[],'rules':[],'glossary':[],'output_contract':[],
                     'examples':[],'return_contract':'fixture return','rule_conflicts':[],
                     'skill_dir':str(SCRIPTS.parent),'python':sys.executable,'check_args':[]}
            context_path=root/'context.json'
            sys.path.insert(0,str(SCRIPTS))
            import verify_delivery as delivery
            admission_problems=[]
            admitted=delivery.check_source_chains(str(root),record,admission_problems,source_only=True)
            self.assertFalse(admission_problems)
            context['source_review']['binding']['pdf_source']=delivery._source_identity(admitted[0],lambda rel:str(root/rel))
            context_path.write_text(json.dumps(context))
            target=root/'translation.md'
            target.write_text(source)
            checks=[('verify_pdf_source.py',pdf,'--checklist',path,'--source-md',root/'source/source.md','--translation',target),
                    ('verify_translation.py',target,root/'source/source.md','--fragment','--project-context',context_path)]
            for args in checks:
                result=run(*args)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            target.write_text(source+'\n\n【译注：例如 $u=3$。】\n')
            approved=('--approved-extra-math','u=3')
            for args in checks:
                result=run(*args,*approved)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            result=run(*checks[1])
            self.assertNotEqual(0,result.returncode)
            # Approval is for this note occurrence; it cannot substitute source math.
            target.write_text(source.replace('$x+y=1$','',1)+'\n\n【译注：例如 $x+y=1$。】\n')
            result=run(*checks[1],'--approved-extra-math','x+y=1')
            self.assertNotEqual(0,result.returncode,result.stdout+result.stderr)
            for indent in range(1,4):
                target.write_text(source.replace('\n\n$$x+y=1','\n\n'+' '*indent+'$$x+y=1',1))
                for args in checks:
                    result=run(*args)
                    self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            damages=[source.replace('$x+y=1$', '\n\n$x+y=1$\n\n',1),
                     source.replace('\n\n$$x+y=1', '\n\nAdjacent prose $$x+y=1',1),
                     source.replace('}}$$\n\n', '}}$$ adjacent prose\n\n',1)]
            for damage in damages:
                target.write_text(damage)
                for args in checks:
                    result=run(*args)
                    self.assertNotEqual(0,result.returncode,result.stdout+result.stderr)
                    self.assertRegex(result.stdout+result.stderr,'角色|宿主|所属')
            target.write_text(source)
            result=run('split_work_packages.py',root/'source/source.md',root/'wps',
                       root/'trans','chars:200','--project-context',context_path)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            packages=list((root/'wps').glob('*.md'))
            self.assertTrue(packages)
            for package in packages:
                head,body=package.read_text().split('\n---\n',1)
                self.assertIn('pdf_formula_contract: confirmed-tex-v1',head)
                self.assertIn('project_context:',head)
                self.assertNotIn('pdf_checklist:',body)
                target=root/'trans'/package.name
                target.write_text(package.read_text())
                result=run('verify_translation.py',target,package,'--fragment')
                self.assertNotEqual(0,result.returncode)
                self.assertIn('project-context',result.stdout+result.stderr)
                result=run('verify_translation.py',target,package,'--fragment',
                           '--project-context',context_path)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                changed=copy.deepcopy(c)
                changed['formula_review']['basis']='Changed current original review; old context cannot certify this checklist'
                path.write_text(json.dumps(changed))
                result=run('verify_translation.py',target,package,'--fragment',
                           '--project-context',context_path)
                self.assertNotEqual(0,result.returncode)
                self.assertIn('来源裁决',result.stdout+result.stderr)
                path.write_text(json.dumps(c,ensure_ascii=False))
                mapping=json.loads((root/'source/source.md.blocks.json').read_text())
                location=mapping['blocks'][0]['math'][0]
                if '$x+y=1$' in body:
                    forged=root/'forged-source.md';forged_target=root/'forged-target.md'
                    meta_lines=head.splitlines()
                    meta_lines=[('source_char_start: '+str(location['md_start']) if line.startswith('source_char_start:') else
                                 'source_char_end: '+str(location['md_end']) if line.startswith('source_char_end:') else line) for line in meta_lines]
                    selected=source[location['md_start']:location['md_end']]
                    meta_lines=[('fragment_digest: '+hashlib.sha256(selected.encode()).hexdigest() if line.startswith('fragment_digest:') else line) for line in meta_lines]
                    forged.write_text('\n'.join(meta_lines)+'\n---\n'+selected)
                    forged_target.write_text(selected)
                    result=run('verify_translation.py',forged_target,forged,'--fragment','--project-context',context_path)
                    self.assertNotEqual(0,result.returncode)
                    self.assertIn('所属',result.stdout+result.stderr)
                for old,new in [('x+y=1','x+y=2'),('$x+y=1$','$$x+y=1$$'),('(1)','(2)')]:
                    if old not in target.read_text():
                        continue
                    target.write_text(package.read_text().replace(old,new,1))
                    result=run('verify_translation.py',target,package,'--fragment',
                               '--project-context',context_path)
                    self.assertNotEqual(0,result.returncode)
                    self.assertIn('数学',result.stdout+result.stderr)
                    target.write_text(package.read_text())
            saved_map=(root/'source/source.md.blocks.json').read_text()
            mapping=json.loads(saved_map)
            first=mapping['blocks'][0]['math'][0]
            second=mapping['blocks'][1]['math'][0]
            first['id'],second['id']=second['id'],first['id']
            (root/'source/source.md.blocks.json').write_text(json.dumps(mapping))
            result=run('verify_pdf_source.py',pdf,'--checklist',path,'--source-md',root/'source/source.md')
            self.assertNotEqual(0,result.returncode)
            self.assertIn('错绑',result.stdout+result.stderr)
            (root/'source/source.md.blocks.json').write_text(saved_map)
            wrong_label=copy.deepcopy(c)
            wrong_label['blocks'][2]['content'][0]['label']['origin']=copy.deepcopy(c['blocks'][1]['content'][0]['label']['origin'])
            wrong_label['blocks'][2]['content'][0]['confirmation']['fact_sha256']=fact_digest(wrong_label['blocks'][2]['content'][0])
            path.write_text(json.dumps(wrong_label))
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',path,'--output',root/'source/source.md')
            self.assertNotEqual(0,result.returncode)
            self.assertIn('式号',result.stdout+result.stderr)
            self.assertEqual(source,(root/'source/source.md').read_text())
            repeated=copy.deepcopy(c)
            repeated['blocks'][1]['content'][0]['origin']=copy.deepcopy(c['blocks'][0]['content'][1]['origin'])
            repeated['blocks'][1]['content'][0]['confirmation']['fact_sha256']=fact_digest(repeated['blocks'][1]['content'][0])
            path.write_text(json.dumps(repeated))
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',path,'--output',root/'source/source.md')
            self.assertNotEqual(0,result.returncode)
            self.assertIn('字形',result.stdout+result.stderr)
            self.assertEqual(source,(root/'source/source.md').read_text())
            path.write_text(json.dumps(c))
            translation=root/'translation.md'
            translation.write_text('已有人工译文不得覆盖\n')
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',path,'--output',translation)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('受保护',result.stdout+result.stderr)
            self.assertEqual('已有人工译文不得覆盖\n',translation.read_text())
