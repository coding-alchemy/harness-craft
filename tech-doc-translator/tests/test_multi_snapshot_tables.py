"""Each snapshot owns its conversion map and local table numbering."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import test_grid_work_packages as grid_packages
from test_grid_tables import SCRIPTS
import recover_work_packages as rwp
import verify_delivery as delivery


class MultiSnapshotTables(unittest.TestCase):
    run_tool=grid_packages.GridPackageTests.run_tool

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='multi-table-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.parts=[]
        for name,heading,value in [('a','1. Alpha',10),('b','2. Beta',20)]:
            raw=('<article>'+('<h1>T</h1>' if name=='a' else '')+'<h2>'+heading+'</h2>'
                '<table id="shared"><tr><th>Name</th><th>Value</th></tr>'
                '<tr><td rowspan="2"><code>token_%s</code><pre>%s();</pre></td><td>%d</td></tr>'
                '<tr><td>%d</td></tr></table></article>' % (name,name,value,value+1))
            (self.root/(name+'.html')).write_text(raw)
            self.run_tool('parse_api_html.py',self.root/(name+'.html'),self.root/(name+'.md'),
                          '--expand-tables','grid','--table-conversions-output',self.root/(name+'.json'))
            self.parts.append((self.root/(name+'.md')).read_text())
        self.source=self.root/'source.md';self.source.write_text(''.join(self.parts))
        first=len(self.parts[0].split('\n'))-1;total=len(self.source.read_text().split('\n'))
        self.record={'version':1,'mode':'translation','delivery_root':str(self.root),'inputs':['final.md'],
            'outputs':[],'checks':[],'reviews':[], 'sources':[{'family':'api','source_version':'multi-fixture',
            'parsed_markdown':'source.md','snapshots':[{'snapshot':'a.html','range':[1,first],
                'table_conversions':'a.json'}, {'snapshot':'b.html','range':[first+1,total],
                'table_conversions':'b.json'}], 'covers':['final.md']}]}
        (self.root/'final.md').write_text('placeholder')

    def admission(self,record=None,full=True):
        record=record or self.record
        problems=[]
        entries=delivery.check_source_chains(self.root,record,problems,source_only=True)
        if full and not problems:
            delivery.run_source_reconcile(self.root,record,entries,problems)
        return entries,problems

    def context(self):
        entries,problems=self.admission();self.assertEqual(problems,[])
        for name in ('rules','instructions','contract','example'):
            (self.root/(name+'.md')).write_text('保留格内容与原点代码，中间阶段保留归属标记。\n')
        context={'project_root':str(self.root),'source_record':'record.json','source_scope':'all',
            'source_review':{'scope':'all','basis':'受控双快照，分别回源核对两张局部表1及不同代码。',
                'binding':{k:entries[0][k] for k in ('parsed_sha256','source_version','snapshots')}},
            'skill_dir':str(SCRIPTS.parent),'python':sys.executable,'check_args':['--table-code-stage','intermediate'],
            'instructions':['instructions.md'],'rules':['rules.md'],'glossary':[],
            'output_contract':['contract.md'],'examples':[{'path':'example.md','differences':'只复用结构合同。'}],
            'return_contract':'返回术语、来源现象、检查及不确定项。','rule_conflicts':[]}
        (self.root/'record.json').write_text(json.dumps(self.record))
        (self.root/'context.json').write_text(json.dumps(context))
        return context

    def test_two_local_table_one_maps_and_legacy_unique_assignment(self):
        entries,problems=self.admission();self.assertEqual(problems,[])
        view=rwp.source_table_view(entries[0],self.root,self.source)
        self.assertEqual([item['mapping']['locate']['table'] for item in view['tables']],[1,1])
        self.assertEqual(len(set(item['source']['snapshot'] for item in view['tables'])),2)
        legacy=copy.deepcopy(self.record)
        legacy['sources'][0]['snapshots'][0].pop('table_conversions')
        legacy['sources'][0]['table_conversions']='a.json'
        entries,problems=self.admission(legacy);self.assertEqual(problems,[])
        self.assertEqual(entries[0]['snapshots'][0]['table_conversions']['path'],'a.json')

    def test_reused_parser_starts_local_table_one_for_each_snapshot(self):
        from _html_fidelity import HtmlFidelity
        from parse_api_html import render
        fidelity=HtmlFidelity();fidelity.expand_tables=True
        for name in ('a','b'):
            soup=fidelity.parse((self.root/(name+'.html')).read_text())
            render(soup.article,[],fidelity)
            self.assertEqual(len(fidelity.table_conversions),1)
            self.assertEqual(fidelity.table_conversions[0]['locate'],{'table':1})

    def test_single_legacy_and_both_levels_same_map(self):
        record=copy.deepcopy(self.record)
        record['sources'][0].update(parsed_markdown='a.md',table_conversions='a.json')
        record['sources'][0]['snapshots']=[{'snapshot':'a.html','table_conversions':'a.json'}]
        self.assertEqual(self.admission(record)[1],[])
        record['sources'][0]['snapshots'][0].pop('table_conversions')
        self.assertEqual(self.admission(record)[1],[])
        record['sources'][0]['snapshots'][0]['table_conversions']='b.json'
        self.assertTrue(self.admission(record)[1])

    def test_wrong_snapshot_digest_ambiguous_duplicate_and_range_rejected(self):
        for mutate in [
            lambda e:e['snapshots'][1].update(table_conversions='a.json'),
            lambda e:(e.update(table_conversions='a.json'),e['snapshots'][1].update(snapshot='a.html'),
                      e['snapshots'][0].pop('table_conversions'),e['snapshots'][1].pop('table_conversions')),
            lambda e:(e['snapshots'][1].update(snapshot='a.html',table_conversions='a.json')),
            lambda e:(e['snapshots'][0]['range'].__setitem__(1,e['snapshots'][0]['range'][1]+1),
                      e['snapshots'][1]['range'].__setitem__(0,e['snapshots'][1]['range'][0]+1)),
            lambda e:e['snapshots'][1].pop('table_conversions')]:
            bad=copy.deepcopy(self.record);mutate(bad['sources'][0])
            self.assertTrue(self.admission(bad)[1])
        drift=json.loads((self.root/'a.json').read_text());drift['snapshot_sha256']='0'*64
        (self.root/'drift.json').write_text(json.dumps(drift))
        bad=copy.deepcopy(self.record);bad['sources'][0]['snapshots'][0]['table_conversions']='drift.json'
        self.assertTrue(any('摘要' in p for p in self.admission(bad)[1]))

    def test_v1_and_v2_keep_their_code_projection_contracts(self):
        legacy=json.loads((self.root/'a.json').read_text());legacy['version']=1
        for cell in legacy['tables'][0]['cells']:cell.pop('code_target',None)
        (self.root/'a.v1.json').write_text(json.dumps(legacy))
        a=self.parts[0]+'\n[TABLE-CODE r=3 c=1#1]\n\n```\na();\n```\n'
        (self.root/'mixed.md').write_text(a+self.parts[1])
        record=copy.deepcopy(self.record);entry=record['sources'][0]
        first=len(a.split('\n'))-1
        entry.update(parsed_markdown='mixed.md')
        entry['snapshots'][0].update(table_conversions='a.v1.json',range=[1,first])
        entry['snapshots'][1]['range']=[first+1,len((a+self.parts[1]).split('\n'))]
        entries,problems=self.admission(record);self.assertEqual(problems,[])
        view=rwp.source_table_view(entries[0],self.root,self.root/'mixed.md')
        policy=rwp.table_policy({'_table_view':view},{'char_start':0,'char_end':len(a+self.parts[1])})
        self.assertEqual(policy['version'],[1,2])
        self.assertEqual([t['version'] for t in policy['tables']],[1,2])

    def test_actual_task_recovery_and_merge_reuse_other_snapshot(self):
        context=self.context();ctx=self.root/'context.json'
        self.run_tool('split_work_packages.py',self.source,self.root/'wps',self.root/'trans','h2','--project-context',ctx)
        for wp in sorted((self.root/'wps').glob('*.md')):
            text=wp.read_text().replace('# T\n','# T（示例）\n').replace('## 1. Alpha','## 1. Alpha（阿尔法）').replace('## 2. Beta','## 2. Beta（贝塔）')
            text=text.replace('Name | Value','名称 | 数值')
            (self.root/'trans'/wp.name).write_text(text)
        common=['--source',self.source,'--strategy','h2','--source-packages',self.root/'wps','--project-context',ctx]
        self.run_tool('build_work_package_tasks.py',*common,'--package','wp_001.md','--output',self.root/'task.json')
        old_task=(self.root/'task.json').read_bytes();old_map=(self.root/'b.json').read_bytes()
        self.run_tool('build_review_evidence.py','prepare',*common,'--output',self.root/'pending.json')
        pending=json.loads((self.root/'pending.json').read_text());evidence=self.root/'pending.json'
        def register(name,facts,evidence,label):
            review={'package':name,'facts':facts,'scope':'controlled snapshot package','basis':'a.html / b.html and local map',
                'note':'受控测试复核记录：两份局部表1的不同 token、数值及代码原点逐项对应。','reviewed_at':'2026-10-24',
                'items':['all local cells and original code'],'unresolved':[]}
            path=self.root/(label+'.review.json');path.write_text(json.dumps(review))
            out=self.root/(label+'.evidence.json')
            self.run_tool('build_review_evidence.py','register-review',*common,'--review-evidence',evidence,
                          '--package',name,'--review-record',path,'--output',out)
            return out
        for name,item in pending.items():evidence=register(name,{k:v for k,v in item.items() if k!='review'},evidence,name)
        def recover(evidence,ok=True):
            return self.run_tool('recover_work_packages.py',self.source,self.root/'wps',self.root/'trans','h2',
                '--project-context',ctx,'--review-evidence',evidence,ok=ok)
        self.assertIn('可复用 (2)',recover(evidence).stdout)
        revised=json.loads(old_map);revised['tables'][0]['locate']={'table_id':'shared'}
        (self.root/'b.revised.json').write_text(json.dumps(revised))
        self.record['sources'][0]['snapshots'][1]['table_conversions']='b.revised.json'
        (self.root/'record.json').write_text(json.dumps(self.record))
        recover(evidence,ok=False)
        entries,problems=self.admission();self.assertEqual(problems,[])
        context['source_review']['binding']={k:entries[0][k] for k in ('parsed_sha256','source_version','snapshots')}
        ctx.write_text(json.dumps(context))
        self.run_tool('build_work_package_tasks.py',*common,'--package','wp_001.md',
            '--previous-task',self.root/'task.json','--output',self.root/'b.json',ok=False)
        self.assertEqual((self.root/'b.json').read_bytes(),old_map)
        p=recover(evidence,ok=False);self.assertIn('可复用 (1)',p.stdout);self.assertIn('待复核 (1)',p.stdout)
        self.run_tool('build_review_evidence.py','prepare',*common,'--review-evidence',evidence,'--output',self.root/'revised-pending.json')
        after=json.loads((self.root/'revised-pending.json').read_text())
        self.assertEqual(after['wp_001.md']['check_policy'],pending['wp_001.md']['check_policy'])
        self.assertNotEqual(after['wp_002.md']['check_policy'],pending['wp_002.md']['check_policy'])
        evidence=register('wp_002.md',{k:v for k,v in after['wp_002.md'].items() if k!='review'},evidence,'revised')
        self.assertIn('可复用 (2)',recover(evidence).stdout)
        self.run_tool('merge_work_packages.py',self.root/'final.md',self.root/'trans','--source',self.source,
            '--strategy','h2','--source-packages',self.root/'wps','--project-context',ctx,'--review-evidence',evidence,'--finalize-table-code')
        final=(self.root/'final.md').read_text()
        self.assertEqual(final.count('a();'),1);self.assertEqual(final.count('b();'),1)
        self.assertNotIn('[TABLE-CODE',final)
        self.assertEqual((self.root/'task.json').read_bytes(),old_task)
        self.assertEqual((self.root/'b.json').read_bytes(),old_map)


if __name__=='__main__':unittest.main()
