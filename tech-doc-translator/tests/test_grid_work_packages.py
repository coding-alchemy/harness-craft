"""Single-snapshot conversion policy follows the existing package evidence chain."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_grid_tables import HTML, SCRIPTS
import recover_work_packages as rwp
import verify_delivery as delivery


class GridPackageTests(unittest.TestCase):
    def run_tool(self, tool, *args, ok=True):
        p=subprocess.run([sys.executable,str(SCRIPTS/tool),*map(str,args)],capture_output=True,text=True)
        if ok:
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        else:
            self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        return p

    def test_real_task_evidence_recovery_merge_and_local_mapping_change(self):
        with tempfile.TemporaryDirectory(prefix='grid-packages-') as tmp:
            root=Path(tmp).resolve(); source=root/'source.md'; mapping=root/'tables.json'
            (root/'page.html').write_text(HTML)
            self.run_tool('parse_api_html.py',root/'page.html',source,'--expand-tables','grid',
                          '--table-conversions-output',mapping)
            (root/'final.md').write_text('placeholder')
            record={'version':1,'mode':'translation','delivery_root':str(root), 'inputs':['final.md'],
                    'outputs':[],'checks':[],'reviews':[], 'sources':[{'family':'api','source_version':'fixture-v1',
                    'parsed_markdown':'source.md','snapshots':[{'snapshot':'page.html'}],
                    'table_conversions':'tables.json','covers':['final.md']}]}
            (root/'record.json').write_text(json.dumps(record))
            problems=[]
            entries=delivery.check_source_chains(root,record,problems,source_only=True)
            delivery.run_source_reconcile(root,record,entries,problems)
            self.assertEqual(problems,[])
            entry=entries[0]
            binding={k:entry[k] for k in ('parsed_sha256','source_version','snapshots')}
            binding['table_conversions']=delivery._source_identity(entry,lambda p:str(root/p))['table_conversions']
            for name in ('instructions','rules','contract','example'):
                (root/(name+'.md')).write_text('保留分组、空格和代码原点；中间包保留格代码标记，代码逐字一致。\n')
            context={'project_root':str(root),'source_record':'record.json','source_scope':'all',
                     'source_review':{'scope':'all','basis':'受控原 DOM 两表：逐格确认跨度、空格和两段代码原点。','binding':binding},
                     'skill_dir':str(SCRIPTS.parent),'python':sys.executable,
                     'instructions':['instructions.md'],'rules':['rules.md'],'glossary':[],
                     'output_contract':['contract.md'],'examples':[{'path':'example.md','differences':'只复用结构约定，不复制正文。'}],
                     'check_args':['--table-code-stage','intermediate'],'rule_conflicts':[],
                     'return_contract':'返回术语、来源问题、检查及不确定项。'}
            ctx=root/'context.json';ctx.write_text(json.dumps(context))
            self.run_tool('split_work_packages.py',source,root/'wps',root/'trans','h2','--project-context',ctx)
            for wp in sorted((root/'wps').glob('*.md')):
                text=wp.read_text().replace('# T\n','# T（示例）\n')
                for old,new in [('## 1. Grid','## 1. Grid（网格）'),('## 2. Other','## 2. Other（其他）'),
                                ('Feature','特征'),('Group','分组'),('Min','最小'),('Max','最大')]:
                    text=text.replace(old,new)
                (root/'trans'/wp.name).write_text(text)
            common=['--source',str(source),'--strategy','h2','--source-packages',str(root/'wps'),
                    '--project-context',str(ctx)]
            task=root/'task.json'
            self.run_tool('build_work_package_tasks.py',*common,'--package','wp_001.md','--output',task)
            current_task=json.loads(task.read_text())
            original_task=task.read_bytes()
            original_mapping=mapping.read_bytes()
            self.assertIn('--project-context',current_task['command'])
            self.assertEqual(len(current_task['table_conversions']['tables']),1)
            self.assertEqual(current_task['table_conversions']['version'],2)
            self.run_tool('build_review_evidence.py','prepare',*common,'--output',root/'pending.json')
            target = root / 'trans/wp_001.md'
            healthy = target.read_bytes()
            target.write_text(target.read_text().replace('**最小**', '最小'))
            output = self.run_tool('verify_translation.py', target, root/'wps/wp_001.md',
                '--fragment','--table-code-stage','intermediate','--project-context',ctx,ok=False)
            self.assertIn('表头角色', output.stdout + output.stderr)
            output = self.run_tool('build_review_evidence.py','prepare',*common,
                '--output',root/'damaged-pending.json',ok=False)
            self.assertIn('表头角色', output.stdout + output.stderr)
            target.write_bytes(healthy)
            pending=json.loads((root/'pending.json').read_text())
            evidence=root/'pending.json'
            before={name:entry['check_policy'].get('table_conversions') for name,entry in pending.items()}
            for name,item in pending.items():
                facts={k:v for k,v in item.items() if k!='review'}
                review={'package':name,'facts':facts,'scope':'controlled fixture package','basis':'page.html DOM',
                        'note':'测试受控裁决：格值、空格、头分组、代码原点及目标逐项对应。','reviewed_at':'2026-10-24',
                        'items':['all cells and code origins'],'unresolved':[]}
                review_path=root/(name+'.review.json');review_path.write_text(json.dumps(review))
                out=root/(name+'.evidence.json')
                self.run_tool('build_review_evidence.py','register-review',*common,'--review-evidence',evidence,
                              '--package',name,'--review-record',review_path,'--output',out)
                evidence=out
            p=self.run_tool('recover_work_packages.py',source,root/'wps',root/'trans','h2',
                            '--project-context',ctx,'--review-evidence',evidence)
            self.assertIn('可复用 (2)',p.stdout)
            self.assertIn('待复核 (0)',p.stdout)
            self.run_tool('merge_work_packages.py',root/'final.md',root/'trans',
                          '--source',source,'--strategy','h2','--source-packages',root/'wps',
                          '--project-context',ctx,'--review-evidence',evidence,'--finalize-table-code')
            self.assertNotIn('[TABLE-CODE', (root/'final.md').read_text())
            changed=json.loads(mapping.read_text())
            changed['tables'][1]['locate']={'table_id':'other'}
            revised=root/'tables.revised.json'
            revised.write_text(json.dumps(changed))
            record['sources'][0]['table_conversions']=revised.name
            (root/'record.json').write_text(json.dumps(record))
            self.run_tool('recover_work_packages.py',source,root/'wps',root/'trans','h2',
                          '--project-context',ctx,'--review-evidence',evidence,ok=False)
            context['source_review']['binding']['table_conversions']={'path':revised.name,'sha256':rwp.file_sha256(revised)}
            problems=[]
            current_entries=delivery.check_source_chains(root,record,problems,source_only=True)
            delivery.run_source_reconcile(root,record,current_entries,problems)
            self.assertEqual(problems,[])
            context['source_review']['binding']['snapshots']=current_entries[0]['snapshots']
            ctx.write_text(json.dumps(context))
            self.run_tool('build_review_evidence.py','prepare',*common,'--output',root/'after.json')
            after=json.loads((root/'after.json').read_text())
            self.assertEqual(before['wp_001.md'],after['wp_001.md']['check_policy']['table_conversions'])
            self.assertNotEqual(before['wp_002.md'],after['wp_002.md']['check_policy']['table_conversions'])
            p=self.run_tool('recover_work_packages.py',source,root/'wps',root/'trans','h2',
                            '--project-context',ctx,'--review-evidence',evidence,ok=False)
            self.assertIn('wp_002.md',p.stdout)
            self.assertIn('可复用 (1)',p.stdout)
            self.assertIn('待复核 (1)',p.stdout)
            facts={k:v for k,v in after['wp_002.md'].items() if k!='review'}
            review={'package':'wp_002.md','facts':facts,'scope':'second table revised mapping',
                    'basis':'page.html #other; tables.revised.json','note':'重新定位到同一原表并逐格核对，代码和空格无变化。',
                    'reviewed_at':'2026-10-24','items':['table2 all cells'],'unresolved':[]}
            review_path=root/'second.review.json';review_path.write_text(json.dumps(review))
            fresh=root/'revised.evidence.json'
            self.run_tool('build_review_evidence.py','register-review',*common,'--review-evidence',evidence,
                          '--package','wp_002.md','--review-record',review_path,'--output',fresh)
            self.run_tool('recover_work_packages.py',source,root/'wps',root/'trans','h2',
                          '--project-context',ctx,'--review-evidence',fresh)
            self.run_tool('merge_work_packages.py',root/'final.md',root/'trans','--source',source,'--strategy','h2',
                          '--source-packages',root/'wps','--project-context',ctx,'--review-evidence',fresh,'--finalize-table-code')
            self.assertEqual(task.read_bytes(),original_task)
            self.assertEqual(mapping.read_bytes(),original_mapping)
            self.assertEqual(sorted(p.name for p in (root/'wps').glob('*.md')), ['wp_001.md','wp_002.md'])


if __name__=='__main__':
    unittest.main()
