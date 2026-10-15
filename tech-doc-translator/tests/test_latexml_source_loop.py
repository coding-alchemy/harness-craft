"""二期 ticket 01：LaTeXML 最小来源闭环（适配、独立对账、绑定与 check_policy）。

覆盖验收 01-1～01-8 的底层定向用例：原节点适配与实体保真、无 TeX 进
unresolved、独立对账损伤反例（删正文/漏公式/等数替换/改类型/错题名/
缺摘要/交叠/重复/额外输出）、消费端绑定与 precise 口径、check_policy
投影的无关包复用语义、CLI 兼容与漏参拒绝。
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown
from _verification import MathSpan, compare_math_spans, scan_math

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_paper.html'
SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'

IDENTITY = {
    'expected_title': 'Fixture LaTeXML Paper',
    'actual_title': 'Fixture LaTeXML Paper',
    'paper_id': '2101.00001',
    'version': 'v2',
    'final_url': 'https://example.org/abs/2101.00001v2',
    'retrieved_at': '2026-10-01T12:00:00Z',
    'confirmation': '对照已确认论文页面与快照 H1 逐字核对（测试样例）。',
}


def _adapt(decisions=()):
    raw = FIXTURE.read_text(encoding='utf-8')
    md, corrs, unres, _fidelity, _adapter = latexml.adapt_latexml_snapshot(
        raw, None, list(decisions), str(FIXTURE.parent))
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': str(FIXTURE),
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': list(decisions),
        'correspondences': corrs,
        'unresolved': unres,
    }
    return raw, md, payload


class AdaptRoundTripTest(unittest.TestCase):
    """01-1/01-3/01-4：适配候选经独立对账通过；实体与 TeX 逐字保持。"""

    def test_roundtrip_reconcile_clean(self):
        raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': '回源读取 MathML（测试）'}])
        self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload),
                         [])

    def test_entity_decoded_tex_preserved_verbatim(self):
        _raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])
        self.assertIn('$s < Q \\land x > y$', md)
        math = [c for c in payload['correspondences']
                if c.get('content_type') == 'math']
        self.assertEqual(math[0]['tex'], 's < Q \\land x > y')
        self.assertEqual(math[0]['kind'], 'inline')
        self.assertEqual(math[1]['kind'], 'block')
        # 块级定界转换含新增包装换行，表达式本体逐字
        self.assertEqual(math[1]['tex'], 'a+b = c')

    def test_markdown_ranges_match_slices(self):
        _raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])
        for corr in payload['correspondences']:
            if corr.get('content_type') != 'math':
                continue
            from _latexml_source import math_wrap
            self.assertEqual(
                md[corr['md_start']:corr['md_end']],
                math_wrap(corr['kind'], corr['tex']))

    def test_unresolved_no_alttext_located_and_preserved(self):
        raw, md, payload = _adapt()
        self.assertEqual([u['node'] for u in payload['unresolved']],
                         ['math[3]'])
        self.assertIn('<math display="inline" id="m3"', md)  # 序列化保留
        # 保留内容可被独立对账验证
        self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload),
                         [])
        # 改写保留内容（猜写/内部占位）即拒绝
        damaged = md.replace('<mi>t</mi>', '<mi>u</mi>', 1)
        diffs = reconcile_latexml_to_markdown(raw, damaged, None, payload)
        self.assertTrue(any('改写' in d or '正文流' in d for d in diffs))

    def test_empty_tex_wrapped_node_is_unresolved(self):
        raw = FIXTURE.read_text(encoding='utf-8')
        broken = raw.replace('alttext="a+b = c"', '')
        md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
            broken, None, [], str(FIXTURE.parent))
        # math[2] alttext 被删与 math[3] 本就无 alttext，均逐节点 unresolved
        self.assertEqual([u['node'] for u in unres], ['math[2]', 'math[3]'])
        self.assertIn('<math display="block" id="m2"', md)


class ReconcileDamageTest(unittest.TestCase):
    """01-3/01-8：独立对账按目标原因拒绝各类损伤。"""

    def setUp(self):
        self.raw, self.md, self.payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])

    def diffs(self, md=None, payload=None):
        return reconcile_latexml_to_markdown(
            self.raw, md or self.md, None, payload or self.payload)

    def test_baseline_clean(self):
        self.assertEqual(self.diffs(), [])

    def test_deleted_paragraph_rejected(self):
        diffs = self.diffs(self.md.replace('Author Name\n\n', ''))
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_missing_formula_rejected(self):
        diffs = self.diffs(self.md.replace('$$\na+b = c\n$$\n\n', '', 1))
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_equal_count_formula_swap_rejected(self):
        diffs = self.diffs(
            self.md.replace('$s < Q \\land x > y$', '$t >= 0$', 1))
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_type_change_rejected(self):
        diffs = self.diffs(self.md.replace('$$\na+b = c\n$$', '$a+b = c$', 1))
        self.assertTrue(any('定界转换不符' in d or '类型' in d for d in diffs))

    def test_wrong_title_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['paper_identity']['actual_title'] = 'Other Paper'
        self.assertTrue(any('身份错配' in d for d in self.diffs(payload=payload)))

    def test_missing_snapshot_digest_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['snapshot'] = {'path': payload['snapshot']['path']}
        self.assertTrue(any('sha256' in d for d in self.diffs(payload=payload)))

    def test_snapshot_drift_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['snapshot']['sha256'] = '0' * 64
        self.assertTrue(any('快照摘要不符' in d
                            for d in self.diffs(payload=payload)))

    def test_overlapping_ranges_rejected(self):
        payload = copy.deepcopy(self.payload)
        maths = [c for c in payload['correspondences']
                 if c.get('content_type') == 'math']
        for corr in payload['correspondences']:
            if corr.get('content_type') == 'math':
                corr['md_start'] = maths[0]['md_start']
                corr['md_end'] = maths[0]['md_end']
        self.assertTrue(any('交叠' in d for d in self.diffs(payload=payload)))

    def test_unexplained_duplicate_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['correspondences'].append(
            copy.deepcopy(payload['correspondences'][0]))
        self.assertTrue(any('重复' in d for d in self.diffs(payload=payload)))

    def test_extra_output_rejected(self):
        diffs = self.diffs(self.md + '\n$extra = 1$\n')
        self.assertTrue(any('额外输出' in d for d in diffs))

    def test_missing_node_in_adaptation_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['correspondences'] = [
            c for c in payload['correspondences']
            if c.get('node') != 'p[4]']  # Gap node 段落（含行内公式）
        self.assertTrue(any('漏节点' in d for d in self.diffs(payload=payload)))


class ConsumerBindingTest(unittest.TestCase):
    """01-5：消费端绑定与 precise 比较口径。"""

    def test_bound_math_spans_full_coverage(self):
        _raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])
        spans, problems = latexml.bound_math_spans(md, payload, full=True)
        self.assertEqual(problems, [])
        self.assertEqual([s[0] for s in spans],
                         ['inline', 'block', 'inline'])
        damaged = md.replace('$t >= 0$', '$t > 0$', 1)

        def _to_spans(bound):
            return [MathSpan(kind=k, expr=t, raw='', start=s, end=e,
                             start_line=1)
                    for k, t, s, e in bound]

        d_spans, d_problems = latexml.bound_math_spans(
            damaged, payload, full=True)
        # §7.11/24：宿主内公式出现均有各自的精确对应，宽宿主成功回退已
        # 删除——损伤公式在绑定阶段即按未绑定与数量不一致拒绝
        self.assertTrue(any('未绑定到来源依据' in p for p in d_problems),
                        d_problems)
        self.assertTrue(any('不一致' in p for p in d_problems), d_problems)
        # 译侧损伤仍由 precise 比较兜底发现
        diffs, _ignored = compare_math_spans(
            _to_spans(spans), _to_spans(d_spans), precise=True)
        self.assertTrue(diffs)

    def test_precise_compare_rejects_strip_tolerated_change(self):
        # 默认块级口径容忍首尾空白差异；precise（来源已确认）不容忍
        src = [MathSpan(kind='block', expr='a+b = c', raw='x',
                        start=0, end=0, start_line=1)]
        doc = [MathSpan(kind='block', expr='\n a+b = c \n', raw='y',
                        start=0, end=0, start_line=1)]
        default_diffs, _ = compare_math_spans(src, doc)
        precise_diffs, _ = compare_math_spans(src, doc, precise=True)
        self.assertEqual(default_diffs, [])
        self.assertTrue(precise_diffs)

    def test_precise_wrap_newline_stripped_once(self):
        src = [MathSpan(kind='block', expr='a+b = c', raw='x',
                        start=0, end=0, start_line=1)]
        doc = [MathSpan(kind='block', expr='\na+b = c\n', raw='y',
                        start=0, end=0, start_line=1)]
        diffs, _ = compare_math_spans(src, doc, precise=True)
        self.assertEqual(diffs, [])


class CheckPolicyTest(unittest.TestCase):
    """01-6/01-7：check_policy 只投影本包相关事实；无关变化不使本包失效。"""

    def test_projection_scopes_nodes(self):
        _raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            refs_start = md.index('## References')
            policy = latexml.check_policy_projection(payload, 0,
                                                     refs_start, path)
            nodes = {n['node'] for n in policy['nodes']}
            # §7.11.5/23：包资格按已核验局部出现命名，全篇别名不进入比较
            self.assertIn('math#1', nodes)
            self.assertTrue(all('[' not in n for n in nodes))
            tail = latexml.check_policy_projection(payload, refs_start,
                                                   len(md) + 1, path)
            self.assertEqual([(n['node'], n['content_type'])
                              for n in tail['nodes']],
                             [('h2#1', 'heading'), ('p#1', 'paragraph')])
        finally:
            os.unlink(path)

    def test_unrelated_fact_change_keeps_projection(self):
        raw, md, payload = _adapt(
            [{'node': 'math[3]', 'tex': 't >= 0', 'basis': 'b'}])
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            refs_start = md.index('## References')
            before = latexml.check_policy_projection(payload, refs_start,
                                                     len(md) + 1, path)
            # 仅改头部公式（该包范围外）的对应事实
            payload['correspondences'] = [
                dict(c, tex='CHANGED') if c.get('node') == 'math[1]'
                else c for c in payload['correspondences']]
            after = latexml.check_policy_projection(payload, refs_start,
                                                    len(md) + 1, path)
            self.assertEqual(before, after)
            # 本包相关对应/裁决变化则投影变化
            payload['correspondences'] = [
                dict(c, kind='changed') if c.get('node') == 'p[5]'
                else c for c in payload['correspondences']]
            changed = latexml.check_policy_projection(
                payload, refs_start, len(md) + 1, path)
            self.assertNotEqual(before, changed)
        finally:
            os.unlink(path)


class ParseCliTest(unittest.TestCase):
    """01-1/01-2：CLI 兼容、身份核对与候选/依据互不覆盖。"""

    def _write_input(self, directory, decisions=()):
        raw = FIXTURE.read_text(encoding='utf-8')
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(FIXTURE),
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY),
            'decisions': list(decisions),
        }
        path = os.path.join(directory, 'adaptation_input.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return path

    def _run(self, args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_reference_html.py')] + args,
            capture_output=True, text=True)

    def test_adapted_parse_and_reuse_of_old_positional_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = self._write_input(tmp, [{'node': 'math[3]', 'tex': 't >= 0',
                                           'basis': 'b'}])
            out = os.path.join(tmp, 'out.md')
            cand = os.path.join(tmp, 'candidate.json')
            result = self._run([str(FIXTURE), out,
                                '--source-adaptation', inp,
                                '--adaptation-output', cand])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.isfile(out))
            candidate = json.load(open(cand, encoding='utf-8'))
            self.assertEqual(candidate['version'], 1)
            self.assertEqual(candidate['format'], 'latexml')
            self.assertTrue(candidate['correspondences'])
            # 旧位置参数（带选区）调用不回归
            result = self._run([str(FIXTURE), 'paper',
                                os.path.join(tmp, 'plain.md')])
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_identity_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = self._write_input(tmp, [{'node': 'math[3]', 'tex': 't >= 0',
                                           'basis': 'b'}])
            payload = json.load(open(inp, encoding='utf-8'))
            payload['paper_identity']['actual_title'] = 'Wrong'
            with open(inp, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)
            result = self._run([str(FIXTURE), os.path.join(tmp, 'out.md'),
                                '--source-adaptation', inp,
                                '--adaptation-output',
                                os.path.join(tmp, 'cand.json')])
            self.assertEqual(result.returncode, 1)
            self.assertIn('身份错配', result.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, 'out.md')))

    def test_unresolved_blocks_dispatch_and_keeps_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = self._write_input(tmp)  # 无裁决：math[3] 无 alttext
            out = os.path.join(tmp, 'out.md')
            with open(out, 'w', encoding='utf-8') as handle:
                handle.write('旧源内容\n')
            result = self._run([str(FIXTURE), out,
                                '--source-adaptation', inp,
                                '--adaptation-output',
                                os.path.join(tmp, 'cand.json')])
            self.assertEqual(result.returncode, 1)
            self.assertIn('未解决项', result.stderr)
            with open(out, encoding='utf-8') as handle:
                self.assertEqual(handle.read(), '旧源内容\n')  # 失败保旧

    def test_adaptation_output_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = self._write_input(tmp, [{'node': 'math[3]', 'tex': 't >= 0',
                                           'basis': 'b'}])
            out = os.path.join(tmp, 'out.md')
            result = self._run([str(FIXTURE), out,
                                '--source-adaptation', inp,
                                '--adaptation-output', inp])
            self.assertEqual(result.returncode, 1)
            self.assertIn('就地覆盖', result.stderr)


class SplitRecoverParamTest(unittest.TestCase):
    """01-5/01-6：拆包绑定依据、frontmatter 引用与漏参拒绝。"""

    def _source_with_adaptation(self, tmp):
        inp = os.path.join(tmp, 'adaptation_input.json')
        raw = FIXTURE.read_text(encoding='utf-8')
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(FIXTURE),
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY),
            'decisions': [{'node': 'math[3]', 'tex': 't >= 0',
                           'basis': 'b'}],
        }
        with open(inp, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
        md = os.path.join(tmp, 'source.md')
        cand = os.path.join(tmp, 'source_adaptation.json')
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_reference_html.py'),
             str(FIXTURE), md, '--source-adaptation', inp,
             '--adaptation-output', cand],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return md, cand

    def test_split_binds_adaptation_in_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, cand = self._source_with_adaptation(tmp)
            wps = os.path.join(tmp, 'wps')
            trans = os.path.join(tmp, 'trans')
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / 'split_work_packages.py'),
                 md, wps, trans, 'h2', '--source-adaptation', cand],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            header = open(os.path.join(wps, 'wp_001.md'),
                          encoding='utf-8').read(2048)
            self.assertIn('source_adaptation: %s'
                          % os.path.realpath(cand), header)
            self.assertIn('source_char_start: 0', header)
            self.assertIn('fragment_digest:', header)

    def test_split_refuses_unresolved_adaptation(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = FIXTURE.read_text(encoding='utf-8')
            payload = {
                'version': 1, 'format': 'latexml',
                'snapshot': {'path': str(FIXTURE),
                             'sha256': latexml.sha256_text(raw)},
                'paper_identity': dict(IDENTITY),
                'decisions': [],
                'unresolved': [{'node': 'math[3]'}],
            }
            bad = os.path.join(tmp, 'bad.json')
            with open(bad, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)
            md = os.path.join(tmp, 'source.md')
            _md, cand = self._source_with_adaptation(tmp)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / 'split_work_packages.py'),
                 md, os.path.join(tmp, 'wps'), os.path.join(tmp, 'trans'),
                 'h2', '--source-adaptation', bad],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)

    def test_recover_refuses_missing_source_adaptation_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, cand = self._source_with_adaptation(tmp)
            wps = os.path.join(tmp, 'wps')
            trans = os.path.join(tmp, 'trans')
            subprocess.run(
                [sys.executable, str(SCRIPTS / 'split_work_packages.py'),
                 md, wps, trans, 'h2', '--source-adaptation', cand],
                capture_output=True, text=True)
            result = subprocess.run(
                [sys.executable,
                 str(SCRIPTS / 'recover_work_packages.py'),
                 md, wps, trans, 'h2'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('缺少 --source-adaptation', result.stderr)
            self.assertIn('不降级', result.stderr)


if __name__ == '__main__':
    unittest.main()
