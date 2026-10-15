"""确认PDF数学的标题/题注/算法实际角色，通过正式CLI核验。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pdf_test_support import (
    original, fact_digest, pdf_project_context, SCRIPTS, HAVE_PYMUPDF, pymupdf,
)


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF 不可用')
class ConfirmedPdfRoleTests(unittest.TestCase):
    def test_math_heading_preserves_original_title_level_and_exact_expression(self):
        for prefix in ('Math title ', ''):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);pdf=root/'paper.pdf'
                with pymupdf.open() as d:
                    p=d.new_page();p.insert_text((50,70),prefix+'x+y=1')
                    p.insert_text((50,110),'This fixture selects only the mathematical title above; this paragraph is outside the selection.')
                    d.save(pdf)
                def run(script,*args):
                    return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
                self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
                cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
                with pymupdf.open(pdf) as d:
                    item={'type':'math','id':'title-math','kind':'inline','tex':'x+y=1','label':None,
                          'owner':{'block':'title','role':'heading'},'slot':int(bool(prefix)),'origin':original(d[0],'x+y=1'),
                          'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal original mathematical title'}}
                    content=([{'type':'text','origin':original(d[0],prefix)}] if prefix else [])+[item]
                item['confirmation']={'basis':'fixture title original readback','source_sha256':c['source']['sha256'],
                                      'scope':[1],'fact_sha256':fact_digest(item)}
                c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'selected complete mathematical title',
                         'source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'one title'},
                         blocks=[{'id':'title','type':'heading','level':1,'text':prefix+'x+y=1','page':1,
                                  'rect':[45,55,250,75],'order':1,'content':content}])
                cp.write_text(json.dumps(c));source=root/'source/source.md'
                q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
                self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                self.assertIn('# '+prefix+'$x+y=1$',source.read_text())
                context=pdf_project_context(root);target=root/'translation.md'
                target.write_text('# '+prefix+'$x+y=1$（数学标题）\n')
                checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),
                        ('verify_translation.py',target,source,'--project-context',context)]
                for args in checks:
                    q=run(*args);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                for damaged in ['## '+prefix+'$x+y=1$（数学标题）\n',
                                '# Wrong title $x+y=1$（数学标题）\n',
                                '# '+prefix+'$x+y=2$（数学标题）\n',
                                prefix+'$x+y=1$（数学标题）\n']:
                    target.write_text(damaged)
                    for args in checks:
                        q=run(*args);self.assertNotEqual(0,q.returncode,q.stdout+q.stderr)
                        self.assertRegex(q.stdout+q.stderr,'标题|数学|角色')

    def test_caption_identity_and_mathematics_survive_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page();p.insert_text((50,70),'Caption mathematics trial')
                p.insert_text((50,110),'Figure 1: Measure x+y=1 with literal * and ` and &copy;.')
                p.insert_text((50,150),'Figure 2: Measure x+y=1 with literal * and ` and &copy;.')
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                title=original(d[0],'Caption mathematics trial')
                blocks=[{'id':'title','type':'heading','level':1,'text':title['text'],'page':1,'rect':title['rect'],'order':1}]
                for n,y in [(1,110),(2,150)]:
                    item={'type':'math','id':'caption-math-'+str(n),'kind':'inline','tex':'x+y=1','label':None,
                          'owner':{'block':'cap'+str(n),'role':'figure_caption'},'slot':1,
                          'origin':original(d[0],'x+y=1',n-1),
                          'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal original caption'}}
                    item['confirmation']={'basis':'fixture numbered caption readback','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
                    content=[{'type':'text','origin':original(d[0],'Figure '+str(n)+': Measure ')},item,
                             {'type':'text','origin':original(d[0],' with literal * and ` and &copy;.',n-1)}]
                    blocks.append({'id':'cap'+str(n),'type':'figure_caption','page':1,'rect':[45,y-15,400,y+5],'order':n+1,'content':content})
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'two selected numbered mathematical captions','source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'title then two independent captions'},blocks=blocks)
            cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            context=pdf_project_context(root);target=root/'translation.md'
            body=source.read_text().split('\n---\n',1)[1].replace('Measure','测量').replace('with literal','包含字面').replace(' and ',' 和 ')
            target.write_text(body)
            checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),
                    ('verify_translation.py',target,source,'--project-context',context)]
            for args in checks:
                q=run(*args);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            target.write_text(body.replace('Figure 1:','Figure 1：',1).replace('Figure 2:','Figure 2：',1))
            for args in checks:
                q=run(*args);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            for damage in [body.replace('Figure 1:','Figure 9：',1),body.replace('**Figure:', '**Table:',1),
                           body.replace('**Figure:','Figure:',1),body.replace('x+y=1','x+y=2',1)]:
                target.write_text(damage)
                for args in checks:
                    q=run(*args);self.assertNotEqual(0,q.returncode,q.stdout+q.stderr)
                    self.assertRegex(q.stdout+q.stderr,'数学|题注|角色|所属')

    def test_inline_code_and_pdf_link_keep_actual_leaves_around_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            sentence='Use a  `b` then x+y=1 and docs.'
            uri='https://example.org/math?literal=&copy;'
            with pymupdf.open() as d:
                p=d.new_page();p.insert_text((50,70),'Mathematics actual leaves')
                p.insert_text((50,110),sentence)
                p.insert_link({'kind':pymupdf.LINK_URI,'from':p.search_for('docs')[0],'uri':uri})
                p.insert_text((50,150),'Second link: docs2.')
                p.insert_link({'kind':pymupdf.LINK_URI,'from':p.search_for('docs2')[0],'uri':'https://example.org/second'})
                p.insert_text((50,200),'alone')
                p.insert_link({'kind':pymupdf.LINK_URI,'from':p.search_for('alone')[0],'uri':'https://example.org/bare'})
                p.set_rotation(90)
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                content=[]
                for typ,value in [('text','Use '),('code','a  `b`'),('text',' then '),
                                  ('math','x+y=1'),('text',' and '),('link','docs'),('text','.')]:
                    item={'type':typ,'origin':original(d[0],value)}
                    if typ=='link':item['target']=uri
                    if typ=='math':
                        item.update(id='m',kind='inline',tex=value,label=None,owner={'block':'p','role':'paragraph'},
                                    slot=len(content),conversion={'source':value,'target':value,'basis':'literal original formula'})
                        item['confirmation']={'basis':'original fixture readback','source_sha256':c['source']['sha256'],
                                              'scope':[1],'fact_sha256':fact_digest(item)}
                    content.append(item)
                title=original(d[0],'Mathematics actual leaves')
                linked=[{'type':'text','origin':original(d[0],'Second link: ')},
                        {'type':'link','origin':original(d[0],'docs2'),'target':'https://example.org/second'},
                        {'type':'text','origin':original(d[0],'.',1)}]
                bare=[{'type':'link','origin':original(d[0],'alone'),'target':'https://example.org/bare'}]
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'complete selected paragraph and leaves',
                     'source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'title then paragraph'},
                     blocks=[{'id':'title','type':'heading','level':1,'text':title['text'],'rect':title['rect'],'page':1,'order':1},
                             {'id':'p','type':'paragraph','rect':[45,95,400,115],'page':1,'order':2,'content':content},
                             {'id':'link-only','type':'paragraph','rect':[45,135,400,155],'page':1,'order':3,'content':linked},
                             {'id':'bare-link','type':'paragraph','rect':[45,185,400,205],'page':1,'order':4,'content':bare}])
            cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            context=pdf_project_context(root);target=root/'translation.md'
            body=source.read_text().split('\n---\n',1)[1].replace('Use ','使用 ').replace(' then ',' 随后 ').replace(' and ',' 和 ')
            body=body.replace('[alone]','[独立链接]')
            target.write_text(body)
            checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),
                    ('verify_translation.py',target,source,'--project-context',context)]
            for args in checks:
                q=run(*args);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            for damage in [body.replace('a  `b`','a `b`'),body.replace('example.org/second','other.org/second'),body.replace('example.org','other.org'),
                           body.replace('Second link: [docs2](<https://example.org/second>).','Second link: .\n\n[docs2](<https://example.org/second>)'),
                           body.replace('[docs]','[]'),body.replace('`` a  `b` ``','a  \\`b\\`')]:
                self.assertNotEqual(damage,body)
                target.write_text(damage)
                for args in checks:
                    q=run(*args);self.assertNotEqual(0,q.returncode,q.stdout+q.stderr)
                    self.assertRegex(q.stdout+q.stderr,'代码|链接|叶子|数学')

    def test_algorithm_parameter_math_and_golden_keep_child_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page();p.insert_text((50,70),'Algorithm mathematics trial')
                p.insert_text((50,110),'Algorithm 1: Pull workers')
                p.insert_text((50,140),'Input: workers\nx+y=1.')
                p.insert_text((50,190),'0) Explanation: x+y=1.')
                p.insert_text((50,240),'for i in range(2):\n    pull(i)',fontname='cour')
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                title=original(d[0],'Algorithm mathematics trial');algo=original(d[0],'Algorithm 1: Pull workers')
                item={'type':'math','id':'m','kind':'inline','tex':'x+y=1','label':None,
                      'owner':{'block':'input','role':'list_item'},'slot':1,'origin':original(d[0],'x+y=1'),
                      'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal mathematical parameter'}}
                content=[{'type':'text','origin':original(d[0],'Input: workers')},item,{'type':'text','origin':original(d[0],'.')}]
                explanation=dict(item,id='list-math',origin=original(d[0],'x+y=1',1),owner={'block':'explanation','role':'list_item'})
                explanation.pop('confirmation',None)
                explained=[{'type':'text','origin':original(d[0],'0) Explanation: ')},explanation,{'type':'text','origin':original(d[0],'.',1)}]
            item['confirmation']={'basis':'original parameter readback','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
            explanation['confirmation']={'basis':'original numbered explanation readback','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(explanation)}
            (root/'source/code.txt').write_text('for i in range(2):\n    pull(i)\n')
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'selected complete algorithm: parameter prose and separate pseudocode',
                     'source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'title algorithm input code'},
                     blocks=[{'id':'title','type':'heading','level':1,'text':title['text'],'rect':title['rect'],'page':1,'order':1},
                             {'id':'algo','type':'algorithm','page':1,'rect':[45,95,400,280],'order':2,'content':[{'type':'text','origin':algo}]},
                             {'id':'input','type':'list_item','algorithm':'algo','page':1,'rect':[45,125,400,165],'order':3,'content':content,
                              'list_marker':'-','list_conversion':{'source_role':'paragraph','target_role':'list_item','marker':'-',
                                                                  'basis':'whole original Input parameter prose to one bullet, unchanged order'}},
                             {'id':'explanation','type':'list_item','algorithm':'algo','page':1,'rect':[45,175,400,205],'order':4,'content':explained},
                             {'id':'code','type':'code_region','algorithm':'algo','page':1,'rect':[45,225,400,280],'order':5,'golden':'code.txt','lang':'python'}])
            cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            context=pdf_project_context(root);target=root/'translation.md'
            body=source.read_text().split('\n---\n',1)[1].replace('Input: workers','输入：工作进程').replace('Explanation:','说明：')
            self.assertIn('[ALGORITHM] Algorithm 1: Pull workers',body)
            self.assertIn('输入：工作进程 $x+y=1$.',body)
            target.write_text(body)
            checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),
                    ('verify_translation.py',target,source,'--project-context',context)]
            for args in checks:
                q=run(*args);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            code='```python\nfor i in range(2):\n    pull(i)\n```'
            parameter='- 输入：工作进程 $x+y=1$.'
            for damage in [body.replace('Algorithm 1:','Algorithm 2:'),body.replace('[ALGORITHM] ','',1),
                           body.replace(parameter+'\n\n0) 说明： $x+y=1$.\n\n'+code,code+'\n\n'+parameter+'\n\n0) 说明： $x+y=1$.'),
                           body.replace('0) 说明：','2) 说明：'),
                           body.replace('    pull(i)','  pull(i)')]:
                self.assertNotEqual(body,damage)
                target.write_text(damage)
                for args in checks:
                    q=run(*args);self.assertNotEqual(0,q.returncode,q.stdout+q.stderr)
                    self.assertRegex(q.stdout+q.stderr,'算法|角色|数学|代码|围栏')

    def test_package_truncation_uses_actual_lists_not_wrapped_citation_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page()
                for y,value in [(60,'Citation trial'),(100,'Recent work (Author,'),(115,'2018) allows models.'),(180,'- First item')]:
                    page.insert_text((50,y),value)
                doc.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as doc:
                title=original(doc[0],'Citation trial');wrapped=original(doc[0],'Recent work (Author,');continuation=original(doc[0],'2018) allows models.')
                wrapped['text']+='\n'+continuation['text'];wrapped['fragments']+=continuation['fragments'];wrapped['rect'][3]=continuation['rect'][3]
                listed=original(doc[0],'- First item')
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'entire native fixture contains no mathematics','source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'title, wrapped ordinary paragraph, real list'},blocks=[
                {'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                {'id':'body','type':'paragraph','page':1,'rect':wrapped['rect'],'content':[{'type':'text','origin':wrapped}],'order':2}])
            for real_list in (False,True):
                if real_list:c['blocks'].append({'id':'list','type':'list_item','page':1,'rect':listed['rect'],'content':[{'type':'text','origin':listed}],'order':3})
                cp.write_text(json.dumps(c));source=root/'source/source.md'
                q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                context=pdf_project_context(root)
                q=run('split_work_packages.py',source,root/'wps',root/'trans','chars:9999','--project-context',context);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                package=root/'wps/wp_001.md';header=package.read_text().split('\n---\n',1)[0]+'\n---\n';target=root/'trans/wp_001.md'
                body='# Citation trial\n\n先前工作（Author，2018）支持模型。\n'
                for keep_list in ((False,) if not real_list else (False,True)):
                    target.write_text(header+body+('\n- 第一项\n' if keep_list else ''))
                    q=run('build_review_evidence.py','prepare','--source',source,'--source-packages',root/'wps','--strategy','chars:9999','--project-context',context,'--output',root/'pending.json')
                    if real_list and not keep_list:
                        self.assertNotEqual(0,q.returncode);self.assertIn('列表项全部丢失',q.stdout+q.stderr)
                    else:self.assertEqual(0,q.returncode,q.stdout+q.stderr)
