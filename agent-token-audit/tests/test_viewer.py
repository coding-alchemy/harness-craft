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

    def test_browser_v2_reference_integrity(self):
        # Ticket 08 S07 browser side: a whitelisted-but-unread source URL proves nothing;
        # rules and mappings must cite sources this very snapshot actually read.
        skill = VIEWER.parent
        pointer = json.loads((skill / 'pricing' / 'default.json').read_text(encoding='utf-8'))
        snapshot_path = skill / 'pricing' / 'snapshots' / (pointer['snapshot'] + '.json')
        self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const context = vm.createContext({assert, snapText: fs.readFileSync(process.argv[3], 'utf8')});
vm.runInContext(fs.readFileSync(process.argv[2] + '/lossless-json.umd.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(process.argv[2] + '/shared.js', 'utf8'), context);
vm.runInContext(`
const snap = LosslessJSON.parse(snapText, undefined, LosslessJSON.parseNumberAndBigInt);
checkPricingConfig(snap);  // the shipped default snapshot stays valid as-is
snap.sources = snap.sources.filter(s => !s.url.includes('openai'));
assert.throws(() => checkPricingConfig(snap), /不在本快照读取来源内/);
console.log('V2-REF-OK');`, context);
""", snapshot_path)

    def test_recompute_and_update_use_submitted_price_snapshot(self):
        self.node(r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[2] + '/web.js', 'utf8');
const start = source.indexOf('function pricingBasisNote(');
const end = source.indexOf('async function exportReport(', start);
(async () => {
  for (const id of ['recompute-run', 'update-run']) {
    for (const mode of ['custom-loaded', 'keep']) {
      const handlers = {}, nodes = new Map(); let submitted, footer, status;
      const loaded = mode === 'custom-loaded';
      const savedPricing = {text: loaded ? 'price-a' : null, name: loaded ? 'a.json' : null};
      let savedPricingMode = loaded ? 'custom' : 'keep';
      const context = vm.createContext({
        savedPricing, savedPricingMode, baseline: {text:'base',obj:{scope:{kind:'session',from:null}}},
        STATES:{partial:'partial'},
        applySavedPricingChoice: payload => {
          if (savedPricingMode === 'keep') return true;
          if (savedPricingMode === 'default') { payload.pricing_mode = 'default'; return true; }
          if (!savedPricing.text) return false;
          payload.pricing_mode = 'custom';
          payload.pricing_text = savedPricing.text;
          return true;
        },
        $: key => { if (!nodes.has(key)) nodes.set(key, {value:'keep',addEventListener:(event,cb)=>{handlers[key]=cb;}}); return nodes.get(key); },
        document:{querySelector:()=>({value:'keep'}),querySelectorAll:()=>[]},
        updateFormValues:()=>({from:null,to:'cutoff',turns:[]}), refreshUpdateDiff:()=>{},
        call: async (_, payload) => {
          submitted = payload;
          savedPricing.text = 'price-b'; savedPricing.name = 'b.json';
          return {ok:true,exit_code:2,report:{format_version:2,status:'partial',analysis:
            loaded ? {cost:{config:{revision:'rev-a'}}} : {performance:{}}}};
        },
        moveFreshTo:()=>{},selectTab:()=>{},failFresh:()=>{},
        showFreshResult:(_,text)=>{footer=text;},setStatus:text=>{status=text;}
      });
      vm.runInContext(source.slice(start,end), context);
      await handlers[id]();
      assert(footer && status, 'successful response must render');
      assert(!footer.includes('b.json') && !status.includes('b.json'));
      if (loaded) {
        assert.equal(submitted.pricing_mode,'custom');
        assert.equal(submitted.pricing_text,'price-a');
        assert(footer.includes('a.json') && status.includes('rev-a'));
      } else {
        assert(!Object.hasOwn(submitted,'pricing_text') && !Object.hasOwn(submitted,'pricing_mode'));
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


DOM_STUB = r'''
class Node { constructor(){ this.childNodes = []; } get textContent(){ return (this._text || '') + this.childNodes.map(c => c.textContent).join(''); } set textContent(v){ this.childNodes = []; this._text = String(v); } }
class ClassList { constructor(){ this.set = new Set(); } add(...cs){ cs.forEach(c => this.set.add(c)); } remove(...cs){ cs.forEach(c => this.set.delete(c)); } contains(c){ return this.set.has(c); } }
class Element extends Node {
  constructor(tag){ super(); this.tagName = tag.toUpperCase(); this.attributes = {}; this.classList = new ClassList(); this._listeners = {}; this.hidden = false; this.open = false; this.disabled = false; this.value = ''; this.checked = false; this.tabIndex = -1; this.title = ''; this.id = ''; this.className = ''; this.type = ''; this.name = ''; this._text = ''; }
  get firstChild(){ return this.childNodes[0] || null; }
  get firstElementChild(){ return this.childNodes.find(c => c instanceof Element) || null; }
  get lastChild(){ return this.childNodes[this.childNodes.length - 1] || null; }
  get parentElement(){ return this.parentNode instanceof Element ? this.parentNode : null; }
  appendChild(node){ if (node.__fragment) { for (const child of [...node.childNodes]) this.appendChild(child); node.childNodes = []; return node; } this.removeChild(node); node.parentNode = this; this.childNodes.push(node); return node; }
  insertBefore(node, ref){ node.parentNode = this; const i = this.childNodes.indexOf(ref); if (i < 0) this.childNodes.push(node); else this.childNodes.splice(i, 0, node); return node; }
  removeChild(node){ const i = this.childNodes.indexOf(node); if (i >= 0) this.childNodes.splice(i, 1); node.parentNode = null; return node; }
  remove(){ if (this.parentNode) this.parentNode.removeChild(this); }
  after(node){ const parent = this.parentNode; if (!parent) return; const i = parent.childNodes.indexOf(this); parent.childNodes.splice(i + 1, 0, node); node.parentNode = parent; }
  setAttribute(key, value){ this.attributes[key] = String(value); if (key === 'id') this.id = String(value); }
  getAttribute(key){ return Object.prototype.hasOwnProperty.call(this.attributes, key) ? this.attributes[key] : null; }
  addEventListener(kind, fn){ (this._listeners[kind] = this._listeners[kind] || []).push(fn); }
  removeEventListener(kind, fn){ this._listeners[kind] = (this._listeners[kind] || []).filter(f => f !== fn); }
  dispatchEvent(event){ event.target = event.target || this; for (const fn of (this._listeners[event.type] || [])) fn(event); return true; }
  click(){ this.dispatchEvent({ type: 'click', target: this }); }
  scrollIntoView(){}
  querySelector(sel){ return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel){ const out = []; const walk = node => { if (node instanceof Element && domMatches(node, sel)) out.push(node); node.childNodes.forEach(walk); }; this.childNodes.forEach(walk); return out; }
}
class Fragment extends Node { constructor(){ super(); this.__fragment = true; } appendChild(node){ node.parentNode = this; this.childNodes.push(node); return node; } }
function domMatches(el, sel){
  sel = String(sel);
  let m;
  if ((m = /^input\[name="([^"]+)"\]:checked$/.exec(sel))) return el.tagName === 'INPUT' && (el.getAttribute('name') === m[1] || el.name === m[1]) && el.checked;
  if ((m = /^input\[name="([^"]+)"\]$/.exec(sel))) return el.tagName === 'INPUT' && (el.getAttribute('name') === m[1] || el.name === m[1]);
  if ((m = /^#([\w-]+)$/.exec(sel))) return el.id === m[1];
  if ((m = /^\.([\w-]+)$/.exec(sel))) return el.classList.contains(m[1]) || el.className.split(/\s+/).includes(m[1]);
  if ((m = /^([a-zA-Z]+)$/.exec(sel))) return el.tagName === m[1].toUpperCase();
  return false;
}
const document = {
  _root: new Element('div'),
  createElement(tag){ return new Element(tag); },
  createElementNS(ns, tag){ return new Element(tag); },
  createTextNode(text){ const node = new Node(); node._text = String(text); return node; },
  createDocumentFragment(){ return new Fragment(); },
  getElementById(id){ return this._root.querySelectorAll('#' + id)[0] || null; },
  querySelector(sel){ return this.querySelectorAll(sel)[0] || null; },
  querySelectorAll(sel){ return this._root.querySelectorAll(sel); },
  addEventListener(){}, removeEventListener(){},
};
'''


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for viewer regressions')
class RenderSmoke(ViewerRegression):
    """Ticket 03: render paths (lazy sections, pagination) stay runnable and on-contract."""

    def test_overview_renders_lazy_and_paged(self):
        # A real overview with enough sessions to force pagination in the session ranking.
        log = self.root / 'many-sessions.jsonl'
        rows = [pmeta()]
        for i in range(28):
            rows.append({'timestamp': '2026-03-08T12:00:00.0%02dZ' % i, 'type': 'session_meta',
                         'payload': {'id': 's%d' % i, 'cwd': '/tmp', 'originator': 'x', 'cli_version': '1'}})
            rows.append(tctx(turn='t%d' % i, model='gpt-6.1-sol'))
            rows.append(usage(rid='r%d' % i, turn='t%d' % i, sid='s%d' % i, inp=100 * (i + 1), cache=0, output=10 * i))
        log.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        proc = subprocess.run(['python3', str(ENTRY), 'overview', '--source', str(log), '--to', END,
                               '--export', 'json', '--output', str(self.root / 'ov.json')],
                              capture_output=True, text=True)
        self.assertIn(proc.returncode, (0, 2), proc.stderr)
        proc = subprocess.run(['python3', str(ENTRY), 'report', '--source', str(log), '--session', 's0',
                               '--to', END, '--export', 'json', '--output', str(self.root / 'sess.json')],
                              capture_output=True, text=True)
        self.assertIn(proc.returncode, (0, 2), proc.stderr)
        self.node(r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
''' + DOM_STUB + r'''
const context = vm.createContext({console, assert, document, Node, setTimeout: fn => fn(),
  reportText: fs.readFileSync(process.argv[3], 'utf8')});
vm.runInContext(fs.readFileSync(process.argv[2] + '/lossless-json.umd.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(process.argv[2] + '/shared.js', 'utf8'), context);
vm.runInContext(`
const obj = LosslessJSON.parse(reportText, undefined, LosslessJSON.parseNumberAndBigInt);
validateReport(obj);
const host = document.createElement('section'); host.id = 'report';
const empty = document.createElement('div'); empty.id = 'empty';
empty.appendChild(document.createElement('p'));
document._root.appendChild(empty);
document._root.appendChild(host);
renderReport(obj, obj.format_version, 'footer');
assert(host.textContent.includes('费用估算'), 'session render missing cost section');
assert(host.textContent.includes('展开调用明细'), 'session render missing records toggle');
console.log('SESSION-RENDER-OK');
`, context);
''', self.root / 'sess.json')
        self.node(r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
''' + DOM_STUB + r'''
const context = vm.createContext({console, assert, document, Node, setTimeout: fn => fn(),
  reportText: fs.readFileSync(process.argv[3], 'utf8')});
vm.runInContext(fs.readFileSync(process.argv[2] + '/lossless-json.umd.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(process.argv[2] + '/shared.js', 'utf8'), context);
vm.runInContext(`
const obj = LosslessJSON.parse(reportText, undefined, LosslessJSON.parseNumberAndBigInt);
validateReport(obj);
const host = document.createElement('section'); host.id = 'overview-result';
document._root.appendChild(host);
renderOverviewReport(obj, 'footer', 'overview-result');
const text = host.textContent;
// First screen: scope band, metric cards and trend render eagerly.
assert(text.includes('结果范围与状态') && text.includes('日趋势'), 'first screen missing');
// Long sections render lazily: their summaries exist, bodies not yet generated.
const lazySummaries = host.querySelectorAll('summary').map ? null : null;
const summaries = document._root.querySelectorAll('summary').map(s => s.textContent);
const sessionIndex = summaries.find(s => s.includes('会话索引'));
assert(sessionIndex && sessionIndex.includes('个会话，其中 28 个有 usage'), 'session index summary: ' + sessionIndex);
const timelineCard = summaries.find(s => s.includes('轮次时间线'));
assert(timelineCard, 'timeline card missing');
// Session ranking is session content: folded by default with a count summary,
// paged body only when its entry is opened (model ranking stays eager).
assert(text.includes('会话排行：共 28 个会话'), 'ranking summary missing: ' + text.slice(text.indexOf('会话排行'), text.indexOf('会话排行') + 200));
const allDetails = document._root.querySelectorAll('details');
const rankCard = allDetails.find(d => d.querySelector('summary') && d.querySelector('summary').textContent.includes('展开会话排行'));
assert(rankCard, 'session ranking card missing');
rankCard.open = true; rankCard.dispatchEvent({type: 'toggle'});
assert(rankCard.textContent.includes('第 1 / 2 页'), 'ranking not paged after open');
// Opening the lazy session index builds the paged body exactly once.
const details = document._root.querySelectorAll('details').filter(d => (d.textContent || '').includes('会话索引') || (d.firstChild && d.firstChild.textContent && d.firstChild.textContent.includes('会话索引')));
const indexCard = details.find(d => d.querySelector('summary') && d.querySelector('summary').textContent.includes('会话索引'));
indexCard.open = true; indexCard.dispatchEvent({type: 'toggle'});
assert(indexCard.textContent.includes('第 1 / 2 页'), 'session index body not paged');
const afterFirst = indexCard.textContent.length;
indexCard.dispatchEvent({type: 'toggle'});
assert(indexCard.textContent.length === afterFirst, 'lazy body rebuilt on second open');
console.log('RENDER-SMOKE-OK');
`, context);
''', self.root / 'ov.json')
