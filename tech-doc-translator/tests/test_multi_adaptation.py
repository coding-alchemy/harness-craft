"""§7.5 F2/F7：依据范围事实、选区准入与多快照消费者贯通。

覆盖：依据新键（selection / markdown.sha256+lines）记录与旧格式兼容、
按 selected 选区解析后的同源拆包准入（选区外篡改仍按完整对账拒绝）、
多快照 merged.md 的双依据拆包/恢复/合并/片段核验/翻译就绪/导出上下文
正例，以及单依据覆盖不完整、切片 sha 漂移、缺新键、反序等反例的如实
诊断（不得以"未闭合数学定界"等错误原因失败）。
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
import merge_work_packages as mwp
import recover_work_packages as rwp
import split_work_packages as swp
import verify_delivery as vd
import verify_translation as vt
from _source_reconcile import reconcile_latexml_to_markdown

IDENTITY = {
    'expected_title': 'Multi Snapshot Paper',
    'actual_title': 'Multi Snapshot Paper',
    'paper_id': '2101.00002', 'version': 'v1',
    'final_url': 'https://example.org/abs/2101.00002v1',
    'retrieved_at': '2026-10-09T00:00:00Z',
    'confirmation': 'Independent synthetic fixture（多快照贯通测试）。',
}

SNAPSHOT_A = (
    '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8">'
    '<title>Multi Snapshot Paper</title></head>\n<body>\n'
    '<article id="paper" class="ltx_document">\n'
    '<h1 class="ltx_title">Multi Snapshot Paper</h1>\n'
    '<p class="ltx_p">First part studies <math xmlns="http://www.w3.org/1998/'
    'Math/MathML" alttext="x\n+y" display="inline" id="m1">'
    '<mrow><mi>x</mi></mrow></math> inline.</p>\n'
    '</article>\n</body>\n</html>\n')
SNAPSHOT_B = SNAPSHOT_A.replace(
    'First part studies', 'Second part shows').replace('id="m1"', 'id="m2"')


def build_adaptation(raw, snapshot_path, selection=None, identity=None):
    md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
        raw, selection, [], str(Path(snapshot_path).parent))
    payload = latexml.build_candidate_adaptation(
        {'paper_identity': dict(identity or IDENTITY), 'decisions': []},
        raw, str(snapshot_path), corrs, unres, selection=selection,
        md_text=md)
    return md, payload


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='multi_adaptation_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def write(self, name, text):
        path = self.path(name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path


class AdaptationRangeFactsTest(TempDirTest):
    """F7-1：依据记录选区与本快照 Markdown 范围事实；旧格式行为不变。"""

    def test_records_selection_and_markdown_facts(self):
        snap = self.write('paper.html', SNAPSHOT_A)
        raw = open(snap, encoding='utf-8').read()
        md, payload = build_adaptation(raw, snap, selection='paper')
        self.assertEqual(payload['selection'], 'paper')
        sliced = latexml.markdown_slice_form(md)
        self.assertEqual(payload['markdown']['sha256'],
                         latexml.sha256_text(sliced))
        self.assertEqual(payload['markdown']['lines'],
                         len(sliced.split('\n')))
        # 无选区解析记录 null 选区
        _md2, payload2 = build_adaptation(raw, snap)
        self.assertIsNone(payload2['selection'])
        self.assertIn('markdown', payload2)

    def test_old_format_admission_unchanged(self):
        """旧格式依据（无 selection/markdown 键）整文准入行为不变。"""
        snap = self.write('paper.html', SNAPSHOT_A)
        raw = open(snap, encoding='utf-8').read()
        md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
            raw, None, [], self.tmp)
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': snap, 'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY), 'decisions': [],
            'correspondences': corrs, 'unresolved': unres,
        }
        self.assertNotIn('selection', payload)
        self.assertNotIn('markdown', payload)
        # 旧格式单依据：范围事实核对直接通过（无新键不拒绝）
        self.assertEqual(latexml.recorded_markdown_problems(md, payload), [])
        self.assertEqual(
            swp.full_source_reconcile_admission(payload, md), [])
        src = self.write('source.md', md)
        packs = self.path('packs')
        trans = self.path('trans')
        written = swp.split(src, packs, trans, 'h2', self.write(
            'old.adaptation.json', json.dumps(payload, ensure_ascii=False)))
        self.assertTrue(written)

    def test_recorded_markdown_problems_detects_drift(self):
        snap = self.write('paper.html', SNAPSHOT_A)
        raw = open(snap, encoding='utf-8').read()
        md, payload = build_adaptation(raw, snap)
        problems = latexml.recorded_markdown_problems(
            md + 'extra line\n', payload)
        self.assertTrue(any('覆盖不完整' in p or '漂移' in p for p in problems))
        problems = latexml.recorded_markdown_problems(
            md.replace('First part', 'Altered part', 1), payload)
        self.assertTrue(any('漂移' in p for p in problems))
        self.assertEqual(latexml.recorded_markdown_problems(md, payload), [])


class SelectionAdmissionTest(TempDirTest):
    """F2：按 selected 选区解析后的同源拆包准入。"""

    def _selection_fixture(self):
        raw = ('<html><body><article><h1>Scope Fixture</h1>'
               '<section id="selected"><h2>Chosen section</h2>'
               '<p>Chosen body.</p></section>'
               '<section id="other"><h2>Other section</h2>'
               '<p>Outside selected scope.</p></section>'
               '</article></body></html>')
        snap = self.write('scope.html', raw)
        identity = dict(IDENTITY, expected_title='Scope Fixture',
                        actual_title='Scope Fixture')
        md, payload = build_adaptation(raw, snap, selection='selected',
                                       identity=identity)
        self.assertEqual(payload['selection'], 'selected')
        adapt = self.write('adaptation.json',
                           json.dumps(payload, ensure_ascii=False))
        src = self.write('source.md', md)
        return raw, snap, md, adapt, src

    def test_selected_scope_split_passes(self):
        _raw, _snap, md, adapt, src = self._selection_fixture()
        packs = self.path('packs')
        trans = self.path('trans')
        written = swp.split(src, packs, trans, 'h2', adapt)
        self.assertTrue(written)
        body = open(written[0], encoding='utf-8').read()
        self.assertIn('Chosen body.', body)
        self.assertNotIn('Outside selected scope', body)
        # 选区 Markdown 只含选区内容（无选区外节点）
        self.assertNotIn('Other section', md)

    def test_out_of_scope_tamper_still_rejected(self):
        """选区外追加篡改：范围事实/完整对账按目标原因拒绝（不降级）。"""
        _raw, _snap, md, adapt, src = self._selection_fixture()
        with open(src, 'w', encoding='utf-8') as handle:
            handle.write(md + '\nTampered outside content.\n')
        packs = self.path('packs')
        trans = self.path('trans')
        with self.assertRaises(SystemExit) as ctx:
            swp.split(src, packs, trans, 'h2', adapt)
        message = str(ctx.exception)
        self.assertTrue('覆盖不完整' in message or '完整对账失败' in message,
                        message)


class MultiSnapshotFixture(TempDirTest):
    """两快照（各含一个多行行内公式）拼接成 merged.md 的共用基座。"""

    def setUp(self):
        super().setUp()
        self.snap_a = self.write('a.html', SNAPSHOT_A)
        self.snap_b = self.write('b.html', SNAPSHOT_B)
        raw_a = open(self.snap_a, encoding='utf-8').read()
        raw_b = open(self.snap_b, encoding='utf-8').read()
        self.md_a, self.payload_a = build_adaptation(raw_a, self.snap_a)
        self.md_b, self.payload_b = build_adaptation(raw_b, self.snap_b)
        self.adapt_a = self.write(
            'a.adaptation.json',
            json.dumps(self.payload_a, ensure_ascii=False))
        self.adapt_b = self.write(
            'b.adaptation.json',
            json.dumps(self.payload_b, ensure_ascii=False))
        self.merged = self.md_a + self.md_b
        self.source = self.write('merged.md', self.merged)
        self.adapts = [self.adapt_a, self.adapt_b]
        payloads = [self.payload_a, self.payload_b]
        self.pieces, self.view_payload = latexml.multi_admission_view(
            self.merged, payloads, list(self.adapts))
        self.assertEqual(self.pieces[0], latexml.markdown_slice_form(self.md_a))

    def split_packs(self, adapts=None):
        packs = self.path('packs')
        trans = self.path('trans')
        written = swp.split(self.source, packs, trans, 'h2',
                            adapts or self.adapts)
        return written, packs, trans


class MultiAdaptationAdmissionTest(MultiSnapshotFixture):
    """F7：多依据切片校验与整文视图。"""

    def test_slice_partition_is_seamless(self):
        self.assertEqual(
            '\n'.join(latexml.markdown_slice_form(p) for p in self.pieces),
            latexml.markdown_slice_form(self.merged))
        corrs = self.view_payload['correspondences']
        math = [c for c in corrs if c.get('content_type') == 'math']
        self.assertEqual(len(math), 2)
        # 第二片的公式区间已按累计偏移平移到整文坐标
        second = [c for c in math if c['tex'] == 'x\n+y'][1]
        self.assertEqual(self.merged[second['md_start']:second['md_end']],
                         latexml.math_wrap(second['kind'], second['tex']))

    def test_double_adaptation_split_passes(self):
        written, _packs, _trans = self.split_packs()
        self.assertTrue(written)
        bodies = [open(p, encoding='utf-8').read().split('---\n', 2)[-1]
                  for p in written]
        self.assertEqual('\n'.join(bodies), self.merged)

    def test_single_adaptation_coverage_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.split_packs([self.adapt_a])
        message = str(ctx.exception)
        self.assertIn('覆盖不完整', message)
        self.assertNotIn('未闭合', message)

    def test_slice_sha_drift_rejected(self):
        drifted = self.merged.replace('Second part shows',
                                      'SeconX part shows', 1)
        src = self.write('drifted.md', drifted)
        with self.assertRaises(SystemExit) as ctx:
            swp.split(src, self.path('packs'), self.path('trans'), 'h2',
                      self.adapts)
        self.assertIn('漂移', str(ctx.exception))

    def test_missing_range_facts_rejected(self):
        old = dict(self.payload_a)
        old.pop('markdown', None)
        old.pop('selection', None)
        old_adapt = self.write('a.old.json',
                               json.dumps(old, ensure_ascii=False))
        with self.assertRaises(SystemExit) as ctx:
            self.split_packs([old_adapt, self.adapt_b])
        self.assertIn('范围事实', str(ctx.exception))

    def test_swapped_order_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.split_packs([self.adapt_b, self.adapt_a])
        message = str(ctx.exception)
        self.assertTrue('漂移' in message or '顺序错误' in message)

    def test_view_payload_reconcile_matches_merged(self):
        """整文视图的公式事实与 merged.md 完全绑定（full 口径）。"""
        spans, problems = latexml.bound_math_spans(
            self.merged, self.view_payload, full=True, label='当前源')
        self.assertEqual(problems, [])
        self.assertEqual(len(spans), 2)


class MultiAdaptationConsumersTest(MultiSnapshotFixture):
    """F7：恢复/合并/片段核验/翻译就绪/导出上下文正例。"""

    def _translate_and_evidence(self):
        written, packs, trans = self.split_packs()
        entries = {}
        for path in written:
            meta, body = rwp._frontmatter(path)
            target = Path(meta['target_file'])
            # 译文目标保留完整包（frontmatter + 译文正文），与真实流程一致
            target.write_text(open(path, encoding='utf-8').read())
            entries[Path(path).name] = {
                'source_digest': meta['fragment_digest'],
                'target_digest': rwp._sha256(body),
                'resource_digests': [],
                'source_resource_digests': [],
                'checker': rwp._script_identity(),
                'strong_tokens': [],
                'review': {'semantic': 'done', 'unresolved': []},
                'check_policy': latexml.check_policy_projection(
                    self.view_payload, int(meta['source_char_start']),
                    int(meta['source_char_end']), self.adapt_a),
            }
        evidence = self.write('evidence.json',
                              json.dumps(entries, ensure_ascii=False))
        return written, packs, trans, evidence

    def test_recover_reuses_all_packages(self):
        _written, packs, trans, evidence = self._translate_and_evidence()
        reusable, missing, invalidated, pending, _reports = rwp.recover(
            self.source, packs, trans, 'h2', evidence,
            source_adaptation=self.adapts)
        self.assertEqual(missing + invalidated + pending, [])
        pack_count = len([n for n in os.listdir(packs) if n.endswith('.md')])
        self.assertEqual(len(reusable), pack_count)

    def test_merge_assembles_merged_translation(self):
        _written, packs, trans, evidence = self._translate_and_evidence()
        # 译文目标即权威 target_file，收集实存译文
        inputs = []
        for name in sorted(os.listdir(packs)):
            if not name.endswith('.md'):
                continue
            meta, _body = rwp._frontmatter(os.path.join(packs, name))
            inputs.append(meta['target_file'])
        out = self.path('out.md')
        received = mwp.merge(out, inputs, self.source, 'h2', packs,
                             evidence_path=evidence,
                             source_adaptation=self.adapts)
        self.assertTrue(received)
        merged_out = open(out, encoding='utf-8').read()
        self.assertEqual(merged_out.strip('\n'),
                         self.merged.strip('\n'))

    def test_fragment_hard_checks_pass(self):
        _written, packs, trans, _evidence = self._translate_and_evidence()
        for name in sorted(os.listdir(packs)):
            meta, body = rwp._frontmatter(os.path.join(packs, name))
            target = Path(meta['target_file'])
            fails, _warns = rwp._fragment_hard_checks(
                body, target.read_text(), str(target), (), (),
                self.adapts, adaptation_payload=self.view_payload)
            self.assertEqual(fails, [])

    def test_verify_translation_full_document_passes(self):
        target = self.write('01_章.md', self.merged)
        fail, lines = vt.run_checks(
            self.merged, self.merged, (),
            doc_dir=self.tmp, doc_label=target, src_label=self.source,
            fragment=True, source_adaptations=self.adapts)
        self.assertEqual(fail, 0, '\n'.join(lines))

    def test_verify_translation_single_adaptation_diagnoses_coverage(self):
        # 完整文档模式：单依据对多快照合并文本仍诊断覆盖不完整
        # （整源准入保留，三轮 F4 不改变完整文档核对）
        fail, lines = vt.run_checks(
            self.merged, self.merged, (),
            doc_dir=self.tmp, doc_label='译文', src_label=self.source,
            fragment=False, source_adaptations=[self.adapt_a])
        self.assertGreater(fail, 0)
        joined = '\n'.join(lines)
        self.assertIn('覆盖不完整', joined)
        self.assertNotIn('未闭合', joined)
        # 片段模式（三轮 F4）：按包范围口径装载，不做全篇范围事实核对；
        # 覆盖完整性由拆包/恢复/合并的整源准入承担
        fail, lines = vt.run_checks(
            self.merged, self.merged, (),
            doc_dir=self.tmp, doc_label='译文', src_label=self.source,
            fragment=True, source_adaptations=[self.adapt_a])
        self.assertEqual(fail, 0, '\n'.join(lines))

    def test_export_math_context_union(self):
        import export_pdf as ep

        # 多依据按章分配（三轮 F5）：每章绑定本章实际范围内的已确认公式
        chapters = [ep.Chapter(1, Path(self.write('c1.md', self.md_a))),
                    ep.Chapter(2, Path(self.write('c2.md', self.md_b)))]
        info = ep.apply_source_math_context(chapters,
                                            {'_paths': list(self.adapts)})
        self.assertEqual(info['paths'],
                         [os.path.realpath(p) for p in self.adapts])
        self.assertEqual([[t for _k, t in c.math_confirmed]
                          for c in chapters], [['x\n+y'], ['x\n+y']])
        # 缺章（已确认公式未落入任何章）拒绝：最终完整性核验保留
        try:
            ep.apply_source_math_context(
                [ep.Chapter(1, Path(self.write('only.md', self.md_a)))],
                {'_paths': list(self.adapts)})
            self.fail('缺章未拒绝')
        except ep.ExportError as exc:
            self.assertIn('未落入任何章节', str(exc))
        # 单依据路径行为不变：整列表绑定 + 单 path/sha256 键
        chapters = [ep.Chapter(1, Path(self.write('full.md', self.merged)))]
        info = ep.apply_source_math_context(chapters,
                                            {'_path': self.adapt_a})
        self.assertEqual([t for _k, t in chapters[0].math_confirmed],
                         ['x\n+y'])
        self.assertEqual(set(info), {'path', 'sha256'})
        self.assertEqual(info['path'], os.path.realpath(self.adapt_a))


class MultiAdaptationReadinessTest(MultiSnapshotFixture):
    """F7：交付预检多快照就绪（记录投影 source_adaptations 列表）。"""

    def test_translation_readiness_ready(self):
        root = self.tmp
        target = self.write('01_章.md', self.merged)
        record = {
            'version': 1, 'mode': 'translation', 'delivery_root': root,
            'inputs': ['01_章.md'], 'outputs': [],
            'files': {'01_章.md': 'chapter'},
            'sources': [{
                'order': 1, 'family': 'reference', 'source_version': 'v1',
                'parsed_markdown': 'merged.md',
                'snapshots': [
                    {'snapshot': 'a.html',
                     'source_adaptation': 'a.adaptation.json',
                     'range': [1, len(self.md_a.split('\n')) - 1]},
                    {'snapshot': 'b.html',
                     'source_adaptation': 'b.adaptation.json',
                     'range': [len(self.md_a.split('\n')),
                               len(self.merged.split('\n'))]}],
                'covers': ['01_章.md'], 'table_conversions': None}],
            'checks': [{
                'tool': 'verify_translation',
                'args': ['01_章.md', 'merged.md', '--fragment',
                         '--source-adaptation', 'a.adaptation.json',
                         '--source-adaptation', 'b.adaptation.json']}]}
        problems = []
        entries = vd.check_source_chains(root, record, problems)
        self.assertEqual(problems, [])
        identity = vd.compute_delivery_identity(root, record, entries)
        _c, _p, input_checks, pdf_checks = vd.rerun_checks(
            root, record, problems)
        self.assertEqual(problems, [])
        record['reviews'] = []
        for kind in ('source-reconcile', 'semantic'):
            binding = vd.expected_review_binding(
                kind, '01_章.md', root, record, entries, input_checks,
                pdf_checks, identity)
            self.assertIsNotNone(binding)
            record['reviews'].append({
                'kind': kind, 'target': '01_章.md', 'status': 'closed',
                'sha256': hashlib.sha256(
                    open(target, 'rb').read()).hexdigest(),
                'binding': binding, 'note': 'F7 多快照就绪测试'})
        ready, result = vd.check_translation_readiness(
            root, record, [os.path.realpath(target)])
        self.assertTrue(ready, result.get('reasons'))
        sources = result['identity']['sources']
        self.assertEqual(len(sources), 1)
        projected = sources[0]['source_adaptations']
        self.assertEqual(projected,
                         [os.path.realpath(p) for p in self.adapts])
        self.assertIsNone(sources[0]['source_adaptation'])

    def test_section_id_selection_mismatch_rejected(self):
        """记录声明 section_id 与依据 selection 不一致即拒绝；未声明回落。"""
        snap = self.write('scope.html',
                          '<html><body><article><h1>Scope Fixture</h1>'
                          '<section id="selected"><h2>Chosen</h2>'
                          '<p>Body.</p></section></article></body></html>')
        raw = open(snap, encoding='utf-8').read()
        identity = dict(IDENTITY, expected_title='Scope Fixture',
                        actual_title='Scope Fixture')
        md, payload = build_adaptation(raw, snap, selection='selected',
                                       identity=identity)
        adapt = self.write('scope.adaptation.json',
                           json.dumps(payload, ensure_ascii=False))
        self.write('scope.md', md)
        record = {
            'version': 1, 'mode': 'translation', 'delivery_root': self.tmp,
            'inputs': [], 'outputs': [], 'files': {},
            'sources': [{
                'order': 1, 'family': 'reference', 'source_version': 'v1',
                'parsed_markdown': 'scope.md',
                'source_adaptation': 'scope.adaptation.json',
                'snapshots': [{'snapshot': 'scope.html',
                               'section_id': 'wrong_section'}],
                'covers': [], 'table_conversions': None}],
            'checks': []}
        problems = []
        vd.check_source_chains(self.tmp, record, problems)
        self.assertTrue(any('section_id' in p and '不一致' in p
                            for p in problems), problems)
        # 未声明 section_id：回落依据 selection，无不一致问题
        record['sources'][0]['snapshots'][0].pop('section_id')
        problems = []
        entries = vd.check_source_chains(self.tmp, record, problems)
        self.assertEqual(problems, [])
        self.assertEqual(entries[0]['snapshots'][0]['section_id'],
                         'selected')


class SingleAdaptationCliCompatTest(TempDirTest):
    """二轮真实链修复：单个 --source-adaptation 经 append 解析为单元素
    列表时，恢复/合并预检与交付对齐行为与标量旧用法完全一致。"""

    def test_recover_load_single_old_format_via_list(self):
        snap = self.write('paper.html', SNAPSHOT_A)
        raw = open(snap, encoding='utf-8').read()
        md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
            raw, None, [], self.tmp)
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': snap, 'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY), 'decisions': [],
            'correspondences': corrs, 'unresolved': unres,
        }
        adapt = self.write('old.adaptation.json',
                           json.dumps(payload, ensure_ascii=False))
        # 单元素列表（CLI append 形态）与标量同义：旧格式依据不拒绝
        loaded, adaptation_abs, _project = rwp._load_source_adaptation(
            [adapt], md)
        self.assertIsInstance(adaptation_abs, str)
        self.assertEqual(loaded['snapshot']['sha256'],
                         payload['snapshot']['sha256'])

    def test_align_scalar_dep_pair_not_misparsed(self):
        # dep 标量对 [路径, 摘要] 首元素是字符串；不得按多依据 dep 对
        # 列表逐元素取首字符（二轮真实链 verify_delivery 误拒的回归）
        snap = self.write('paper.html', SNAPSHOT_A)
        raw = open(snap, encoding='utf-8').read()
        md, payload = build_adaptation(raw, snap)
        adapt = self.write('a.adaptation.json',
                           json.dumps(payload, ensure_ascii=False))
        src = self.write('paper.md', md)
        real_src = os.path.realpath(src)
        real_adapt = os.path.realpath(adapt)
        entry = {'order': 1, 'parsed_markdown': 'paper.md',
                 '_parsed_abs': real_src,
                 '_source_adaptations': [(payload, 'a.adaptation.json')]}
        check = {'tool': 'verify_reference_translation',
                 'facts': {'files': {
                     'sources': [[real_src, None]],
                     'source_adaptation': [real_adapt, None]}}}
        problems = []
        vd.align_sources_with_checks([entry], {'out.md': [check]}, problems,
                                     mode='translation', root=self.tmp)
        self.assertEqual(problems, [])
        # 缺参数仍按原合同拒绝
        check['facts']['files'].pop('source_adaptation')
        problems = []
        vd.align_sources_with_checks([entry], {'out.md': [check]}, problems,
                                     mode='translation', root=self.tmp)
        self.assertTrue(any('未提供相符的 --source-adaptation' in p
                            for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
