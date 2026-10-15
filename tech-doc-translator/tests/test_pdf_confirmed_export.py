"""PDF来源确认必须经当前就绪记录进入真实导出和独立核验。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import hashlib

from pdf_test_support import (
    original, fact_digest, pdf_project_context, SCRIPTS, HAVE_PYMUPDF, pymupdf,
)


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF不可用')
class ConfirmedPdfExportTests(unittest.TestCase):
    def test_current_pdf_confirmations_preserve_expression_whitespace_in_real_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf'
            with pymupdf.open() as d:
                p=d.new_page()
                for x,y,text in [(50,60,'Confirmed export trial'),(50,100,'Body x=1'),(50,160,'y=2 (9)')]:p.insert_text((x,y),text)
                d.save(pdf)
            def run(script,*args):
                return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as d:
                title=original(d[0],'Confirmed export trial');blocks=[{'id':'title','type':'heading','level':1,'text':title['text'],'page':1,'rect':title['rect'],'order':1}]
                for index,(identity,role,word,tex) in enumerate([('body','paragraph','x=1',' x=\r\n1 '),('equation','formula','y=2',' y=2 ')],2):
                    item={'type':'math','id':identity+'-math','slot':1 if role=='paragraph' else 0,'owner':{'block':identity,'role':role},'kind':'inline' if role=='paragraph' else 'block','tex':tex,'label':None if role=='paragraph' else {'text':'(9)','origin':original(d[0],'(9)')},'origin':original(d[0],word),'conversion':{'source':word,'target':tex,'basis':'literal native relationship and explicit retained boundary whitespace'}}
                    item['confirmation']={'basis':'native original equation and role','scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(item)}
                    content=([{'type':'text','origin':original(d[0],'Body ')}] if role=='paragraph' else [])+[item]
                    blocks.append({'id':identity,'type':role,'page':1,'rect':[45,80 if role=='paragraph' else 140,250,110 if role=='paragraph' else 170],'order':index,'content':content})
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'complete selected native page','scope':[1],'source_sha256':c['source']['sha256']},reading_order={'adjudicated':True,'basis':'heading, inline paragraph, independent numbered display'},blocks=blocks);cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            target=root/'translation.md';target.write_text('# Confirmed export trial\n\n> **来源**：'+str(pdf)+'\n\n正文 $ x=\r\n1 $\n\n$$ y=2 '+r'\tag*{\text{(9)}}'+'$$\n')
            target.write_bytes(target.read_bytes()+'\n【译注：例如 $u=3$。】\n'.encode())
            pdf_project_context(root)
            import verify_delivery as v
            record=json.loads((root/'record.json').read_text());record['checks'][0]['args']+=['--translation','translation.md','--approved-extra-math','u=3'];problems=[];entries=v.check_source_chains(str(root),record,problems);identity=v.compute_delivery_identity(str(root),record,entries);_,_,inputs,pdfs=v.rerun_checks(str(root),record,problems);self.assertEqual([],problems)
            for kind in ('source-reconcile','semantic'):
                record['reviews'].append({'kind':kind,'target':'translation.md','status':'closed','sha256':v.sha256_file(str(target)),'binding':v.expected_review_binding(kind,'translation.md',str(root),record,entries,inputs,pdfs,identity),'note':'literal native fixture and independently written Chinese body, role and boundary whitespace','items':['inline','numbered display'],'unresolved':[]})
            rp=root/'ready.json';rp.write_text(json.dumps(record));view=root/'view.json';view.write_text(json.dumps({'version':1,'inputs':[{'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}],'exclusions':[],'document_title':{'original':'Confirmed export trial','chinese':'确认数学导出试点','basis':'native fixture title translation'}}));work=root/'export';output=root/'result.pdf'
            q=run('export_pdf.py','--output',output,'--work-dir',work,'--translation-record',rp,'--view-declaration',view,target);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            report=json.loads((work/'export_report.json').read_text());math=report['chapters'][0]['math']
            self.assertEqual([' x=\r\n1 ',' y=2 '+r'\tag*{\text{(9)}}'],[m['latex'] for m in math])
            self.assertEqual(['source_constrained']*2,[m['original_form'] for m in math])
            self.assertEqual(['【译注：例如 $u=3$。】'],[note['fragment'] for note in report['translator_note_exclusions']])
            q=run('verify_pdf.py','--pdf',output,'--work-dir',work,'--view-declaration',view,target);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            # The same approved occurrence must survive the actual package merge,
            # including its fragment admission and final candidate check.
            context=root/'context.json';data=json.loads(context.read_text())
            data['check_args']=['--approved-extra-math','u=3'];context.write_text(json.dumps(data))
            q=run('split_work_packages.py',source,root/'wps',root/'trans','chars:9999','--project-context',context)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            package=root/'wps/wp_001.md';translated=root/'trans/wp_001.md'
            header=package.read_bytes().split(b'\n---\n',1)[0]+b'\n---\n'
            translated.write_bytes(header+target.read_bytes())
            base=['--source',source,'--strategy','chars:9999','--source-packages',root/'wps','--project-context',context]
            pending=root/'pending.json';q=run('build_review_evidence.py','prepare',*base,'--output',pending)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            facts=json.loads(pending.read_text())['wp_001.md'];facts.pop('review',None)
            human=root/'human.json';human.write_text(json.dumps({'package':'wp_001.md','facts':facts,'scope':'complete native fixture','basis':'literal original inline and numbered display plus specifically approved u=3 note','note':'source mathematics and roles retained','items':['native inline/display','exact CRLF expression','specific extra note'],'reviewed_at':'2026-10-15','unresolved':[]}))
            qualified=root/'qualified.json';q=run('build_review_evidence.py','register-review',*base,'--review-evidence',pending,'--package','wp_001.md','--review-record',human,'--output',qualified)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            q=run('recover_work_packages.py',source,root/'wps',root/'trans','chars:9999','--project-context',context,'--review-evidence',qualified)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            merged=root/'merged.md';q=run('merge_work_packages.py',merged,translated,*base,'--review-evidence',qualified)
            self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            stable=merged.read_bytes()
            data['check_args']=[];context.write_text(json.dumps(data))
            q=run('merge_work_packages.py',merged,translated,*base,'--review-evidence',qualified)
            self.assertNotEqual(0,q.returncode);self.assertIn('数学',q.stdout+q.stderr)
            self.assertEqual(stable,merged.read_bytes())
            data['check_args']=['--approved-extra-math','u=3'];context.write_text(json.dumps(data))
            for damaged in (target.read_bytes()+b'\n'+ '【译注：再举 $u=3$。】\n'.encode(),
                            target.read_bytes().replace(b'$ x=\r\n1 $',b'')+'\n【译注：来源 $ x=\r\n1 $。】\n'.encode()):
                translated.write_bytes(header+damaged)
                q=run('merge_work_packages.py',merged,translated,*base,'--review-evidence',qualified)
                self.assertNotEqual(0,q.returncode);self.assertIn('数学',q.stdout+q.stderr)
                self.assertEqual(stable,merged.read_bytes())
