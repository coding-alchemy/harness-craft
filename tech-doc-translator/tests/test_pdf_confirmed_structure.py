"""确认结构数学的正式CLI消费；合成反例不代替真实正文矩阵验收。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pdf_test_support import original, fact_digest, pdf_project_context, SCRIPTS, HAVE_PYMUPDF, pymupdf


def joined_origin(origins):
    return {'page':origins[0]['page'],
            'rect':[min(o['rect'][0] for o in origins),min(o['rect'][1] for o in origins),
                    max(o['rect'][2] for o in origins),max(o['rect'][3] for o in origins)],
            'text':'\n'.join(o['text'] for o in origins),
            'fragments':[f for o in origins for f in o['fragments']],
            'extraction':origins[0]['extraction']}


@unittest.skipUnless(HAVE_PYMUPDF,'PyMuPDF不可用')
class PdfConfirmedStructureTests(unittest.TestCase):
    def test_inline_visible_number_is_adjacent_independent_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page();p.insert_text((50,50),'This explicit trial contains a confirmed inline numbered expression.')
                p.insert_text((50,90),'Before x+y=1 (A_1) after.');d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                item={'type':'math','id':'inline-number','owner':{'block':'b','role':'paragraph'},'slot':1,
                      'origin':original(d[0],'x+y=1'),'kind':'inline','tex':'x+y=1',
                      'label':{'text':'(A_1)','origin':original(d[0],'(A_1)')},
                      'conversion':{'source':'x+y=1','target':'x+y=1','basis':'literal inline mathematical expression'}}
                content=[{'type':'text','origin':original(d[0],'Before ')},item,{'type':'text','origin':original(d[0],' after.')}]
            item['confirmation']={'basis':'visible adjacent inline number kept separate','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'selected inline original role and visible number','source_sha256':c['source']['sha256'],'scope':[1]},reading_order={'adjudicated':True,'basis':'before, expression, number, after'},blocks=[{'id':'b','type':'paragraph','page':1,'rect':[45,75,300,100],'order':1,'content':content}])
            cp.write_text(json.dumps(c,ensure_ascii=False));source=root/'source/source.md'
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertIn(r'$x+y=1$ (A\_1) after.',source.read_text())
            self.assertNotIn('tag*',source.read_text())
            result=run('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
    def test_confirmed_group_keeps_members_independent_and_unsplittable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page()
                p.insert_text((50,50),'This explicit trial selects two distinct members of one confirmed group.')
                p.insert_text((50,90),'x+y=1 (1)');p.insert_text((50,130),'x+y=1 (1)')
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(0,run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source').returncode)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text());blocks=[]
            with pymupdf.open(pdf) as d:
                for i in range(2):
                    item={'type':'math','id':'member-'+str(i),'group':'confirmed-group',
                          'owner':{'block':'b'+str(i),'role':'formula'},'slot':0,
                          'origin':original(d[0],'x+y=1',i),'kind':'block','tex':'x+y=1',
                          'label':{'text':'(1)','origin':original(d[0],'(1)',i)},
                          'conversion':{'source':'x+y=1','target':'x+y=1','basis':'independent original member'}}
                    item['confirmation']={'basis':'original member and its group relation',
                                          'source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
                    blocks.append({'id':'b'+str(i),'type':'formula','page':1,'rect':[45,75+i*40,250,100+i*40],
                                   'order':i+1,'content':[item]})
            c.update(formula_contract='confirmed-tex-v1',
                     formula_review={'basis':'two distinct original members, equal expression and label, one necessary group',
                                     'source_sha256':c['source']['sha256'],'scope':[1]},
                     reading_order={'adjudicated':True,'basis':'first member then second'},blocks=blocks)
            cp.write_text(json.dumps(c,ensure_ascii=False));source=root/'source/source.md'
            result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            context=pdf_project_context(root)
            result=run('split_work_packages.py',source,root/'wps',root/'trans','chars:1','--project-context',context)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            packages=list((root/'wps').glob('*.md'));self.assertEqual(1,len(packages),'necessary confirmed group was split')
            package=packages[0];target=root/'trans'/package.name;target.write_bytes(package.read_bytes())
            result=run('verify_translation.py',target,package,'--fragment','--project-context',context)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            head,body=package.read_bytes().decode().split('\n---\n',1)
            target.write_text(head+'\n---\n'+body.replace('\n\n','\n\nNew unrelated paragraph.\n\n',1))
            result=run('verify_translation.py',target,package,'--fragment','--project-context',context)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('公式组',result.stdout+result.stderr)
            mapping=json.loads(Path(str(source)+'.blocks.json').read_text())
            first=mapping['blocks'][0];selected=source.read_bytes().decode()[first['md_start']:first['md_end']]
            import hashlib
            meta=[('source_char_start: '+str(first['md_start']) if line.startswith('source_char_start:') else
                   'source_char_end: '+str(first['md_end']) if line.startswith('source_char_end:') else
                   'fragment_digest: '+hashlib.sha256(selected.encode()).hexdigest() if line.startswith('fragment_digest:') else line)
                  for line in head.splitlines()]
            forged=root/'forged-source.md';forged.write_text('\n'.join(meta)+'\n---\n'+selected)
            target.write_text(selected)
            result=run('verify_translation.py',target,forged,'--fragment','--project-context',context)
            self.assertNotEqual(0,result.returncode)
            self.assertIn('公式组',result.stdout+result.stderr)

    def test_matrix_internal_empty_line_and_multiline_inline_are_atomic(self):
        for kind,tex in [('block','\\begin{bmatrix}1&2\\\\\n\n3&4\\end{bmatrix}'),
                         ('inline',' x+\n\ny=1 '),('inline',' x+\r\ny=1 ')]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);pdf=root/'paper.pdf'
                with pymupdf.open() as d:
                    p=d.new_page()
                    p.insert_text((50,50),'This explicit structural trial contains a confirmed two-line expression.')
                    if kind=='block':
                        p.insert_text((60,90),'1 2');p.insert_text((60,110),'3 4')
                    else:
                        p.insert_text((50,90),'Before x+');p.insert_text((50,110),'y=1 after.')
                    d.save(pdf)
                def run(script,*args):
                    return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
                result=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source')
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
                role='formula' if kind=='block' else 'paragraph'
                with pymupdf.open(pdf) as d:
                    p=d[0]
                    orig=joined_origin([original(p,v) for v in (['1 2','3 4'] if kind=='block' else ['x+','y=1'])])
                    item={'type':'math','id':'structural','owner':{'block':'b','role':role},
                          'slot':0 if kind=='block' else 1,'origin':orig,'kind':kind,'tex':tex,'label':None,
                          'conversion':{'source':orig['text'],'target':tex,'basis':'literal confirmed rows and exact representation whitespace'}}
                    content=([item] if kind=='block' else [{'type':'text','origin':original(p,'Before ')},item,
                                                          {'type':'text','origin':original(p,' after.')}])
                item['confirmation']={'basis':'fixture original two rows','source_sha256':c['source']['sha256'],
                                      'scope':[1],'fact_sha256':fact_digest(item)}
                c.update(formula_contract='confirmed-tex-v1',
                         formula_review={'basis':'selected expression only','source_sha256':c['source']['sha256'],'scope':[1]},
                         reading_order={'adjudicated':True,'basis':'row one then row two'},
                         blocks=[{'id':'b','type':role,'page':1,'rect':[45,75,250,120],'order':1,'content':content}])
                cp.write_text(json.dumps(c,ensure_ascii=False));source=root/'source/source.md'
                result=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                self.assertIn(('$' if kind=='inline' else '$$')+tex+('$' if kind=='inline' else '$$'),source.read_bytes().decode())
                result=run('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                context=pdf_project_context(root)
                result=run('split_work_packages.py',source,root/'wps',root/'trans','chars:1','--project-context',context)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                packages=list((root/'wps').glob('*.md'));self.assertEqual(1,len(packages))
                target=root/'trans'/packages[0].name;target.write_bytes(packages[0].read_bytes())
                result=run('verify_translation.py',target,packages[0],'--fragment','--project-context',context)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
