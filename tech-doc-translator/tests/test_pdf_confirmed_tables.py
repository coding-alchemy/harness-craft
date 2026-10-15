"""确认PDF格位数学的正式源准备和独立消费者。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pdf_test_support import (
    original, fact_digest, pdf_project_context, SCRIPTS, HAVE_PYMUPDF, pymupdf,
)


@unittest.skipUnless(HAVE_PYMUPDF, 'PyMuPDF不可用')
class ConfirmedPdfTableTests(unittest.TestCase):
    def test_native_cells_and_empty_position_reach_actual_table_consumers(self):
        for merged in (False,True):
            with self.subTest(merged=merged), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);pdf=root/'paper.pdf'
                with pymupdf.open() as doc:
                    label='(3|a)' if merged else '(3)'
                    page=doc.new_page();page.insert_text((50,60),'Confirmed table trial');page.insert_text((50,80),'Table 1: Amount definitions' if merged else 'Table 1: Amount x+y=1')
                    header=[(140,100,'Group')] if merged else [(50,100,'Name'),(200,100,'Value')]
                    for x,y,t in header+[(50,140,'First'),(200,140,'x+y=1 '+label),(50,180,'Second')]:
                        page.insert_text((x,y),t)
                    doc.save(pdf)
                def run(script,*args):
                    return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
                q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text());cells=[]
                with pymupdf.open(pdf) as doc:
                    title=original(doc[0],'Confirmed table trial')
                    for row,values in enumerate([(['Group',''] if merged else ['Name','Value']),['First','x+y=1'],['Second','']],1):
                        for col,value in enumerate(values,1):
                            if merged and row==1 and col==2:continue
                            content=[];identity='r%dc%d'%(row,col)
                            if value:
                                item={'type':'math' if value=='x+y=1' else 'text','origin':original(doc[0],value,int(value=='x+y=1' and not merged))}
                                if item['type']=='math':
                                    item.update(id='cell-math',kind='inline',tex=value,label={'text':label,'origin':original(doc[0],label)},slot=0,
                                                owner={'block':'table','role':'table_region','cell':identity},
                                                conversion={'source':value,'target':value,'basis':'literal original cell mathematics'})
                                    item['confirmation']={'basis':'original cell readback','source_sha256':c['source']['sha256'],'scope':[1],'fact_sha256':fact_digest(item)}
                                content=[item]
                            cells.append({'id':identity,'row':row,'column':col,'rowspan':1,'colspan':2 if merged and row==1 else 1,'header':row==1,
                                          'rect':[45+150*(col-1),80+40*(row-1),(330 if merged and row==1 else 180+150*(col-1)),110+40*(row-1)],'content':content})
                with pymupdf.open(pdf) as doc:
                    if not merged:
                        caption_math={'type':'math','id':'caption-math','kind':'inline','tex':'x+y=1','label':None,'slot':1,
                                      'owner':{'block':'caption','role':'table_caption'},'origin':original(doc[0],'x+y=1'),
                                      'conversion':{'source':'x+y=1','target':'x+y=1','basis':'original table caption amount'}}
                        caption_math['confirmation']={'basis':'original table caption before actual table','scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(caption_math)}
                    caption={'id':'caption','type':'table_caption','page':1,'rect':[45,65,300,85],'order':2,'table':'table',
                             'content':([{'type':'text','origin':original(doc[0],'Table 1: Amount definitions')}] if merged else [{'type':'text','origin':original(doc[0],'Table 1: Amount ')},caption_math])}
                c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'selected full native table including empty lower right cell','source_sha256':c['source']['sha256'],'scope':[1]},
                         reading_order={'adjudicated':True,'basis':'title then table, row-major cells'},blocks=[
                             {'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                             caption,
                             {'id':'table','type':'table_region','page':1,'rect':[45,80,340,190],'order':3,
                              'cells':cells,'table_conversion':{'basis':'native rectangular grid, unchanged row/column ownership',
                              'rows':3,'columns':2,'cells':[{'source':('r1c1' if merged and row==1 else 'r%dc%d'%(row,col)),'row':row,'column':col} for row in range(1,4) for col in range(1,3)]}}])
                cp.write_text(json.dumps(c));source=root/'source/source.md'
                q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
                self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                md_label=label.replace('|',r'\|')
                self.assertIn('| First | $x+y=1$ '+md_label+' |',source.read_text());self.assertIn('| Second |  |',source.read_text())
                ctx=pdf_project_context(root);target=root/'translation.md'
                # 全源原字形已独立准入；全篇别名变化不改变本包实际格位事实。
                import _pdf_math, recover_work_packages
                view=recover_work_packages.load_project_context(ctx,source)['_pdf_view']
                before=_pdf_math.policy(view,0,len(view['text']));original_source=source.read_bytes()
                c['blocks'][1]['table']='renamed-table';c['blocks'][2]['id']='renamed-table'
                table=c['blocks'][2]
                for cell in table['cells']:
                    cell['id']='renamed-'+cell['id']
                    for item in cell['content']:
                        if item['type']=='math':
                            item['id']='renamed-'+item['id'];item['owner']['block']='renamed-table'
                            item['owner']['cell']=cell['id'];item['confirmation']['fact_sha256']=fact_digest(item)
                for cell in table['table_conversion']['cells']:cell['source']='renamed-'+cell['source']
                cp.write_text(json.dumps(c));q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source)
                self.assertEqual(0,q.returncode,q.stdout+q.stderr);self.assertEqual(original_source,source.read_bytes())
                ctx=pdf_project_context(root);view=recover_work_packages.load_project_context(ctx,source)['_pdf_view']
                self.assertEqual(before,_pdf_math.policy(view,0,len(view['text'])))
                body='# Confirmed table trial\n\n'+('**Table: Table 1: 金额定义**\n\n' if merged else '**Table: Table 1: 金额$x+y=1$**\n\n')+('| 分组 | 分组 |\n' if merged else '| 名称 | 值 |\n')+'| --- | --- |\n| 第一项 | $x+y=1$ '+md_label+' |\n| 第二项 |  |\n'
                checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),
                        ('verify_translation.py',target,source,'--project-context',ctx)]
                for value in [body,body.replace('| 第一项 | $x+y=1$ '+md_label+' |','| $x+y=1$ '+md_label+' | 第一项 |'),body.replace(md_label,'(4)'),
                              body.replace('| 第二项 |  |','| 第二项 | 额外 |'),body.replace('x+y=1','x+y=2'),body.replace('Table 1:','Table 9:'),body.replace('**\n\n|','**\n\n邻接正文。\n\n|')]:
                    target.write_text(value)
                    for args in checks:
                        q=run(*args)
                        if value==body:self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                        else:
                            self.assertNotEqual(0,q.returncode,q.stdout+q.stderr)
                            self.assertRegex(q.stdout+q.stderr,'数学|格位|表格|所属')

    def test_real_table_reading_preserves_math_pipe_label_and_code_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'paper.pdf';code=r'a  |b| &copy; \raw';uri='https://example.org/?literal=&copy;'
            with pymupdf.open() as doc:
                page=doc.new_page();page.insert_text((50,60),'Encoded table trial')
                for x,y,t in [(50,100,'Expression'),(230,100,'Details'),(50,140,'|x|=1 (3)'),(50,155,'y=2'),(230,140,code)]:page.insert_text((x,y),t)
                page.insert_text((230,165),'docs');page.insert_link({'kind':pymupdf.LINK_URI,'from':page.search_for('docs')[0],'uri':uri})
                doc.save(pdf)
            def run(script,*args):return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True)
            q=run('prepare_pdf_source.py','inspect',pdf,'--output',root/'source');self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            cp=root/'source/adjudication_checklist.json';c=json.loads(cp.read_text())
            with pymupdf.open(pdf) as doc:
                title=original(doc[0],'Encoded table trial');native=original(doc[0],'|x|=1');second=original(doc[0],'y=2');label=original(doc[0],'(3)')
                native['text']+='\n'+second['text'];native['fragments']+=second['fragments'];native['rect']=[min(native['rect'][0],second['rect'][0]),min(native['rect'][1],second['rect'][1]),max(native['rect'][2],second['rect'][2]),max(native['rect'][3],second['rect'][3])]
                tex=r'\begin{aligned}|x|&=1\\'+'\n'+r'y&=2\end{aligned}'
                math={'type':'math','id':'absolute','kind':'block','tex':tex,'label':{'text':'(3)','origin':label},'slot':0,
                      'owner':{'block':'table','role':'table_region','cell':'r2c1'},'origin':native,
                      'conversion':{'source':native['text'],'target':tex,'basis':'original two aligned equations, absolute-value operator, row order and independent visible label'}}
                math['confirmation']={'basis':'original single displayed expression in left cell','scope':[1],'source_sha256':c['source']['sha256'],'fact_sha256':fact_digest(math)}
                cells=[]
                for row,col,value,typ in [(1,1,'Expression','text'),(1,2,'Details','text'),(2,1,'|x|=1','math'),(2,2,code,'code')]:
                    content=[math] if typ=='math' else [{'type':typ,'origin':original(doc[0],value)}]
                    if typ=='code':content.append({'type':'link','origin':original(doc[0],'docs'),'target':uri})
                    cells.append({'id':'r%dc%d'%(row,col),'row':row,'column':col,'rowspan':1,'colspan':1,'header':row==1,
                                  'rect':[45+180*(col-1),80+40*(row-1),220+180*(col-1),(175 if row==2 else 110)],'content':content})
            c.update(formula_contract='confirmed-tex-v1',formula_review={'basis':'complete selected original rectangular table','scope':[1],'source_sha256':c['source']['sha256']},reading_order={'adjudicated':True,'basis':'title then table row-major'},blocks=[
                {'id':'title','type':'heading','level':1,'page':1,'rect':title['rect'],'text':title['text'],'order':1},
                {'id':'table','type':'table_region','page':1,'rect':[45,80,405,180],'order':2,'cells':cells,
                 'table_conversion':{'basis':'same original two rows/two columns with first-row headers','rows':2,'columns':2,'cells':[{'source':cell['id'],'row':cell['row'],'column':cell['column']} for cell in cells]}}])
            cp.write_text(json.dumps(c));source=root/'source/source.md'
            q=run('prepare_pdf_source.py','materialize',pdf,'--checklist',cp,'--output',source);self.assertEqual(0,q.returncode,q.stdout+q.stderr)
            ctx=pdf_project_context(root);target=root/'translation.md';body=source.read_text().split('\n---\n',1)[1].replace('Expression','表达式').replace('Details','详情')
            checks=[('verify_pdf_source.py',pdf,'--checklist',cp,'--source-md',source,'--translation',target),('verify_translation.py',target,source,'--project-context',ctx)]
            for damaged in [body,body.replace('[docs]','[文档]'),body.replace(r'\|x\|','|x|'),body.replace('a  ','a '),body.replace('(3)','(4)'),body.replace('&#10;',''),body.replace('example.org','example.net')]:
                target.write_text(damaged)
                for args in checks:
                    q=run(*args)
                    if damaged in (body,body.replace('[docs]','[文档]')):self.assertEqual(0,q.returncode,q.stdout+q.stderr)
                    else:self.assertNotEqual(0,q.returncode,q.stdout+q.stderr);self.assertRegex(q.stdout+q.stderr,'数学|表格|代码|格位|所属')
