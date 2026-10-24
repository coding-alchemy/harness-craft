"""Existing rule snapshots, exact task differences and local review qualification."""
import json,sys,tempfile,unittest
from pathlib import Path
import test_grid_work_packages as shared
sys.path.insert(0,str(shared.SCRIPTS))
import recover_work_packages as rwp
import verify_delivery as delivery

class RuleTaskRefresh(unittest.TestCase):
    run_tool=shared.GridPackageTests.run_tool
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rule-refresh-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'source.md'
        (self.root/'page.html').write_text('<article><h1>T</h1><h2>1. Alpha</h2><p>Use localized memory.</p><h2>2. Beta</h2><p>Keep the code.</p><pre>x();</pre></article>')
        self.run_tool('parse_api_html.py',self.root/'page.html',self.source)
        record={'version':1,'mode':'translation','delivery_root':str(self.root),'inputs':['final.md'],'outputs':[],'checks':[],'reviews':[],
                'sources':[{'family':'api','source_version':'fixture','parsed_markdown':'source.md','snapshots':[{'snapshot':'page.html'}],'covers':['final.md']}]}
        (self.root/'record.json').write_text(json.dumps(record))
        problems=[];entries=delivery.check_source_chains(self.root,record,problems,source_only=True)
        delivery.run_source_reconcile(self.root,record,entries,problems);self.assertEqual(problems,[])
        for file,body in {'instructions.md':'逐包回源，代码原样，链接保留。\n','rules-a.old.md':'locality domain 语境采用局部化，不采用语言本地化。\n',
                'rules-b.md':'保持代码字节及顺序。\n','contract.md':'保留原题和结构；返回四类信息。\n','example.md':'## Original（中文）\n',
                'terms.old.md':'| 英文原词 | 中文译法 | 处理方式 | 语境/备注 |\n| --- | --- | --- | --- |\n| localized | 局部化的 | 首现中英，后文中文 | locality domain |\n'}.items():
            (self.root/file).write_text(body)
        self.context={'project_root':str(self.root),'source_record':'record.json','source_scope':'all',
            'source_review':{'scope':'all','basis':'受控两小节原 HTML 与源 Markdown 全量核对。','binding':{k:entries[0][k] for k in ('parsed_sha256','source_version','snapshots')}},
            'instructions':['instructions.md'],'rules':[{'path':'rules-a.old.md','packages':['wp_001.md']},{'path':'rules-b.md','packages':['wp_002.md']}],
            'glossary':[{'path':'terms.old.md','packages':['wp_001.md']}],'output_contract':['contract.md'],
            'examples':[{'path':'example.md','differences':'只复用标题形态，正文与源不同。'}],
            'return_contract':'返回新术语、来源现象、检查及不确定项。','rule_conflicts':[],
            'python':sys.executable,'skill_dir':str(shared.SCRIPTS.parent),'check_args':[]}
        self.ctx=self.root/'context.json';self.save()
        self.run_tool('split_work_packages.py',self.source,self.root/'wps',self.root/'trans','h2','--project-context',self.ctx)
        for wp in (self.root/'wps').glob('*.md'):
            text=wp.read_text().replace('# T\n','# T（示例）\n').replace('## 1. Alpha\n','## 1. Alpha（甲）\n').replace('## 2. Beta\n','## 2. Beta（乙）\n').replace('Use localized memory.','使用局部化内存。').replace('Keep the code.','保留代码。')
            (self.root/'trans'/wp.name).write_text(text)
        self.common=['--source',self.source,'--strategy','h2','--source-packages',self.root/'wps','--project-context',self.ctx]
        for n in [1,2]:self.run_tool('build_work_package_tasks.py',*self.common,'--package',f'wp_{n:03}.md','--output',self.root/f'task-{n}.old.json')
    def save(self):self.ctx.write_text(json.dumps(self.context,ensure_ascii=False))
    def revise(self):
        (self.root/'rules-a.new.md').write_text('局部化内存首现写局部化内存（localized memory）；标签用加粗英文引导词，空格位保留，译注仅用于技术误导。\n')
        (self.root/'terms.new.md').write_text((self.root/'terms.old.md').read_text().replace('局部化的','局部化'))
        self.context['rules'][0]['path']='rules-a.new.md';self.context['glossary'][0]['path']='terms.new.md';self.save()
    def register(self,evidence,name,pending,note):
        item=pending[name];review={'package':name,'facts':{k:v for k,v in item.items() if k!='review'},'scope':'controlled two-package rule workflow','basis':'page.html and current project rule selections','note':note,'reviewed_at':'2026-10-24','items':['source meaning, first occurrence and current rules'],'unresolved':[]}
        path=self.root/(name+'.review.json');path.write_text(json.dumps(review,ensure_ascii=False))
        output=self.root/(name+'.'+str(len(list(self.root.glob('*.evidence.json'))))+'.evidence.json')
        self.run_tool('build_review_evidence.py','register-review',*self.common,'--review-evidence',evidence,'--package',name,'--review-record',path,'--output',output)
        return output
    def test_actual_rule_change_rechecks_only_affected_package(self):
        oldtask=(self.root/'task-1.old.json').read_bytes();oldrule=(self.root/'rules-a.old.md').read_bytes()
        self.run_tool('build_review_evidence.py','prepare',*self.common,'--output',self.root/'pending.json')
        pending=json.loads((self.root/'pending.json').read_text());evidence=self.root/'pending.json'
        for name in pending:evidence=self.register(evidence,name,pending,'核对原文 localized memory 指局部性域内的内存，旧规则表述为局部化；B 的代码原样。')
        oldevidence=evidence.read_bytes()
        self.revise()
        p=self.run_tool('recover_work_packages.py',self.source,self.root/'wps',self.root/'trans','h2','--project-context',self.ctx,'--review-evidence',evidence,ok=False)
        self.assertIn('可复用 (1)',p.stdout);self.assertIn('待复核 (1)',p.stdout)
        self.run_tool('build_work_package_tasks.py',*self.common,'--package','wp_001.md','--previous-task',self.root/'task-1.old.json','--output',self.root/'task-1.new.json')
        new=json.loads((self.root/'task-1.new.json').read_text())
        changed={row['location']:row for row in new['drift']['changes']}
        self.assertIn('rules 选区及内容',changed);self.assertIn('glossary 选区及内容',changed)
        self.assertIn('不采用语言本地化',changed['rules 选区及内容']['before'])
        self.assertIn('localized memory',changed['rules 选区及内容']['after'])
        # No agent owns these targets; the current process is the only writer.
        target=self.root/'trans/wp_001.md';target.write_text(target.read_text().replace('使用局部化内存。','使用局部化内存（localized memory）。'))
        self.run_tool('build_review_evidence.py','prepare',*self.common,'--output',self.root/'current.json')
        current=json.loads((self.root/'current.json').read_text())
        evidence2=self.register(evidence,'wp_001.md',current,'实际重读当前源和新增首现规则：内存局部化含义保持，首现英文已补；B 不涉及改变的规则/词表选区。')
        self.run_tool('recover_work_packages.py',self.source,self.root/'wps',self.root/'trans','h2','--project-context',self.ctx,'--review-evidence',evidence2)
        self.run_tool('merge_work_packages.py',self.root/'final.md',self.root/'trans','--source',self.source,'--strategy','h2','--source-packages',self.root/'wps','--project-context',self.ctx,'--review-evidence',evidence2)
        self.assertIn('局部化内存（localized memory）',(self.root/'final.md').read_text())
        self.assertEqual((self.root/'task-1.old.json').read_bytes(),oldtask);self.assertEqual((self.root/'rules-a.old.md').read_bytes(),oldrule);self.assertEqual(evidence.read_bytes(),oldevidence)
    def test_old_rule_reference_is_protected_after_replacing_current_reference(self):
        before=(self.root/'rules-a.old.md').read_bytes();self.revise()
        self.run_tool('build_work_package_tasks.py',*self.common,'--package','wp_001.md','--previous-task',self.root/'task-1.old.json','--output',self.root/'rules-a.old.md',ok=False)
        self.assertEqual((self.root/'rules-a.old.md').read_bytes(),before)
    def test_conflicts_and_missing_historical_text_refuse_dispatch(self):
        self.context['rule_conflicts']=['模板要求删题注链接，但源/检查要求保留，尚未解决。'];self.save()
        self.run_tool('build_work_package_tasks.py',*self.common,'--package','wp_001.md','--output',self.root/'blocked.json',ok=False)
        self.assertFalse((self.root/'blocked.json').exists())
        self.context['rule_conflicts']=[];self.save()
        task=json.loads((self.root/'task-1.old.json').read_text());task['context_refs']['rules'][0].pop('content')
        broken=self.root/'missing-text.json';broken.write_text(json.dumps(task))
        self.run_tool('build_work_package_tasks.py',*self.common,'--package','wp_001.md','--previous-task',broken,'--output',self.root/'blocked.json',ok=False)
        task=json.loads((self.root/'task-1.old.json').read_text());task['source']=str(self.root/'absent-old-package.md');broken.write_text(json.dumps(task))
        self.run_tool('build_work_package_tasks.py',*self.common,'--package','wp_001.md','--previous-task',broken,'--output',self.root/'blocked.json',ok=False)

if __name__=='__main__':unittest.main()
