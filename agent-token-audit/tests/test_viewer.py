"""Production browser validators/renderers and async callbacks at their DOM boundary."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_cli import ENTRY, END, PERF_T0, perf_database, perf_usage, pmeta, tctx, usage, pricing_cfg, pricing_rule

VIEWER = ENTRY.parents[1] / 'viewer'


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for viewer regressions')
class ViewerRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-viewer-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def node(self, code, *args):
        proc = subprocess.run(['node', '-', str(VIEWER), *map(str, args)], input=code,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def report(self, *args):
        import sys
        path = self.root / 'report.json'
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), 'report', *map(str, args),
                               '--to', END, '--export', 'json', '--output', str(path)],
                              capture_output=True, text=True)
        self.assertIn(proc.returncode, (0, 2), proc.stderr)
        return path

    def test_confirmed_zero_performance_renders_day_charts(self):
        db = perf_database(self.root / 'zero.sqlite',
                           [('zero', 'completed', PERF_T0, PERF_T0, PERF_T0 + 1000,
                             0, 0, 0, perf_usage(output=0))])
        saved = self.report('--harness', 'zcode', '--database', db, '--session', 's')
        self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const root = process.argv[2];
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.classList = {add(){},remove(){}}; }
  appendChild(node) { this.children.push(node); return node; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener() {}
}
const document = { createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag), createDocumentFragment: () => new Element('fragment'), createTextNode: text => Object.assign(new Element('text'), {textContent:text}) };
const context = vm.createContext({document, console});
vm.runInContext(fs.readFileSync(root + '/lossless-json.umd.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(root + '/shared.js', 'utf8'), context);
context.text = fs.readFileSync(process.argv[3], 'utf8');
const blocks = vm.runInContext(`const obj = LosslessJSON.parse(text, undefined, LosslessJSON.parseNumberAndBigInt);
validateReport(obj); ['ttft','throughput'].map(name => buildPerfMetricBlock(obj.analysis.performance, name));`, context);
function flatten(node) { return [node, ...node.children.flatMap(flatten)]; }
for (const block of blocks) {
  const nodes = flatten(block);
  assert(nodes.some(n => n.textContent && n.textContent.includes('0.00')));
  const bars = nodes.filter(n => n.attrs.class === 'bar-fill');
  assert.equal(bars.length, 1);
  assert.equal(bars[0].attrs.width, '2'); // Same visible zero marker as the tool chart.
}
""", saved)

    def test_browser_rejects_consistent_cost_partition_tampering(self):
        log = self.root / 'log.jsonl'
        log.write_text(''.join(json.dumps(row) + '\n' for row in
                              [pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)]))
        pricing = self.root / 'pricing.json'
        pricing.write_text(json.dumps(pricing_cfg([pricing_rule('rule-a1')])))
        saved = self.report('--source', log, '--session', 's', '--pricing', pricing)
        self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const context = vm.createContext({text: fs.readFileSync(process.argv[3], 'utf8'), assert});
vm.runInContext(fs.readFileSync(process.argv[2] + '/lossless-json.umd.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(process.argv[2] + '/shared.js', 'utf8'), context);
vm.runInContext(`const obj = LosslessJSON.parse(text, undefined, LosslessJSON.parseNumberAndBigInt);
validateReport(obj);
const cost = obj.analysis.cost, c = cost.records[0].components[0];
c.tokens += 1000000n; c.amount = '16';
const bucket = cost.summary.currencies.TST;
bucket.amount = '18.8'; bucket.components.non_cache_read = {tokens:1600000n, amount:'16'};
assert.throws(() => validateReport(obj), /计价分区/);`, context);
""", saved)

    def test_recompute_and_update_use_submitted_price_snapshot(self):
        self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[2] + '/web.js', 'utf8');
const start = source.indexOf('function pricingBasisNote(');
const end = source.indexOf('async function exportReport(', start);
(async () => {
  for (const id of ['recompute-run', 'update-run']) {
    for (const initiallyPriced of [false, true]) {
      const handlers = {}, nodes = new Map(); let submitted, footer, status;
      const savedPricing = {text: initiallyPriced ? 'price-a' : null, name: initiallyPriced ? 'a.json' : null};
      const context = vm.createContext({
        savedPricing, baseline: {text:'base',obj:{scope:{kind:'session',from:null}}},
        STATES:{partial:'partial'},
        $: key => { if (!nodes.has(key)) nodes.set(key, {value:'keep',addEventListener:(event,cb)=>{handlers[key]=cb;}}); return nodes.get(key); },
        document:{querySelector:()=>({value:'keep'}),querySelectorAll:()=>[]},
        updateFormValues:()=>({from:null,to:'cutoff',turns:[]}), refreshUpdateDiff:()=>{},
        call: async (_, payload) => {
          submitted = payload;
          savedPricing.text = 'price-b'; savedPricing.name = 'b.json';
          return {ok:true,exit_code:2,report:{format_version:2,status:'partial',analysis:
            initiallyPriced ? {cost:{config:{revision:'rev-a'}}} : {performance:{}}}};
        },
        moveFreshTo:()=>{},selectTab:()=>{},failFresh:()=>{},
        showFreshResult:(_,text)=>{footer=text;},setStatus:text=>{status=text;}
      });
      vm.runInContext(source.slice(start,end), context);
      await handlers[id]();
      assert(footer && status, 'successful response must render');
      assert(!footer.includes('b.json') && !status.includes('b.json'));
      if (initiallyPriced) {
        assert.equal(submitted.pricing_text,'price-a');
        assert(footer.includes('a.json') && status.includes('rev-a'));
      } else {
        assert(!Object.hasOwn(submitted,'pricing_text'));
        assert(footer.includes('不含费用估算'));
      }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
""")

    def test_browser_validates_saved_rule_and_alias_identity(self):
        alias = {'id': 'alias-1', 'source': {'reference': '测试更名依据', 'version': '1'},
                 'from': {'provider': 'openai_http', 'model': 'legacy-name'},
                 'to': {'provider': 'openai_http', 'model': 'gpt-6.1-sol'}, 'basis': '明确更名'}
        other_alias = json.loads(json.dumps(alias))
        other_alias['from']['model'] = 'unused-name'
        for use_alias in (False, True):
            model = 'legacy-name' if use_alias else 'gpt-6.1-sol'
            log = self.root / 'identity.jsonl'
            log.write_text(''.join(json.dumps(row) + '\n' for row in [pmeta(), tctx(model=model), usage()]))
            pricing = self.root / 'pricing.json'
            pricing.write_text(json.dumps(pricing_cfg([pricing_rule('rule-a1')],
                                                     aliases=[alias, other_alias] if use_alias else [])))
            saved = self.report('--source', log, '--session', 's', '--pricing', pricing)
            self.node(r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const context=vm.createContext({text:fs.readFileSync(process.argv[3],'utf8'),assert});
vm.runInContext(fs.readFileSync(process.argv[2]+'/lossless-json.umd.js','utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[2]+'/shared.js','utf8'),context);
vm.runInContext(`const read=()=>LosslessJSON.parse(text,undefined,LosslessJSON.parseNumberAndBigInt);
validateReport(read());
const changes=[
  c=>{c.config.rules[0].provider='different-provider';},
  c=>{c.config.rules[0].model='different-model';},
  c=>{c.records[0].identity.provider='different-provider';}
];
if(read().analysis.cost.config.aliases.length) changes.push(
  c=>{c.config.aliases[0].from.model='different-model';},
  c=>{c.config.aliases[0].to.model='different-model';},
  c=>{c.records[0].matched.alias_id=null;}
);
for(const change of changes){const obj=read();change(obj.analysis.cost);assert.throws(()=>validateReport(obj),/身份/);}`,context);
""", saved)

    def test_browser_accepts_known_and_unknown_split_partitions(self):
        rule = pricing_rule('split',
            input_={'kind': 'split_cache_read_write', 'other_input_per_million': '10',
                    'cache_read_per_million': '2', 'cache_write_per_million': '30',
                    'basis': '测试来源：互斥输入分区'},
            output={'kind': 'split_reasoning', 'other_output_per_million': '20',
                    'reasoning_per_million': '20', 'basis': '测试来源：推理包含于输出'})
        pricing = self.root / 'split.json'
        pricing.write_text(json.dumps(pricing_cfg([rule])))
        for cache_write in (0, 100000):
            with self.subTest(cache_write=cache_write):
                row = usage(inp=1000000, cache=400000, output=100000)
                row['payload']['usage']['reasoning_output_tokens'] = 30000
                row['payload']['usage']['cache_write_input_tokens'] = cache_write
                log = self.root / 'split.jsonl'
                log.write_text(''.join(json.dumps(r) + '\n' for r in [pmeta(), tctx(), row]))
                saved = self.report('--source', log, '--session', 's', '--pricing', pricing)
                self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const context = vm.createContext({text:fs.readFileSync(process.argv[3],'utf8'), assert});
vm.runInContext(fs.readFileSync(process.argv[2]+'/lossless-json.umd.js','utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[2]+'/shared.js','utf8'),context);
vm.runInContext(`const obj=LosslessJSON.parse(text,undefined,LosslessJSON.parseNumberAndBigInt);
validateReport(obj);
const entry=obj.analysis.cost.records[0], components=new Map(entry.components.map(c=>[c.name,c.tokens]));
assert.equal(components.get('other_output'),70000n); assert.equal(components.get('reasoning'),30000n);
if(obj.records[0].metrics.cache_write.state==='unknown') {
  assert.equal(entry.status,'partially_priced'); assert(!components.has('other_input'));
} else { assert.equal(entry.status,'priced'); assert.equal(components.get('other_input'),500000n); }`,context);
""", saved)
