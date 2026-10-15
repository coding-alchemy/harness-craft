"""二期 ticket 23：包资格按局部事实复用。

覆盖验收 23-1～23-6：check_policy 投影将全篇别名归一为已核验局部出现
（角色前缀 + 包内出现序），保留角色、顺序、类型、父属与原内容，真实
标签/官方编号/资源身份不归一；从固定原 HTML 解析、对账、拆包并取得
真实有效复核证据后，只改后包专属公式、只在后包新增 MathML（触发全篇
重编号）、改前包公式、改脚注定义等场景走真实恢复链路：未变包保持
reusable（含算法题注与图片前后片段所在包），变包按现行合同失效；失效
后经实际重核（重建证据）恢复。旧证据不因别包编号漂移误撤，相关事实
变化仍失效。
"""
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
import recover_work_packages as rwp
import split_work_packages as swp
from _source_reconcile import reconcile_latexml_to_markdown

IDENTITY = {
    'expected_title': 'Package Identity', 'actual_title': 'Package Identity',
    'paper_id': '2210.00023', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00023v1',
    'retrieved_at': '2026-10-10T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}

# 1x1 真实 PNG（合并的最终目录语境检查按文件类型核验图片）
PNG_BYTES = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000d49444154789c63f8cfc0500f008501 8084a63084'
    '0000000049454e44ae426082'.replace(' ', ''))

GROUP_FIXTURE = Path(__file__).resolve().parent / 'fixtures' / (
    'latexml_tables_groups.html')

EXTRA_MATHML = (' <math xmlns="http://www.w3.org/1998/Math/MathML" '
                'alttext="u" display="inline" id="m3"><mi>u</mi></math>')


def make_raw(sec2_tail='Tail formula $z$ end.', sec1_math='$a$', extra='',
             note='Note text $q$ body.'):
    return (
        '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8">'
        '<title>Package Identity</title></head>\n<body>\n'
        '<article id="paper" class="ltx_document">\n'
        '<h1 class="ltx_title">Package Identity</h1>\n'
        '<h2 id="s1">Sec One</h2>\n'
        '<p class="ltx_p">Before image ' + sec1_math + ' here.</p>\n'
        '<figure class="ltx_figure" id="f1"><img src="images/a.png" alt="a"/>'
        '<figcaption class="ltx_caption">Figure 1: cap.</figcaption>'
        '</figure>\n'
        '<p class="ltx_p">After image <math xmlns="http://www.w3.org/1998/'
        'Math/MathML" alttext="b_1" display="inline" id="m1"><mi>b</mi>'
        '</math> tail.</p>\n'
        '<h2 id="s2">Sec Two</h2>\n'
        '<div class="ltx_algorithm" id="alg1">\n'
        '<div class="ltx_title_algorithm">Algorithm 1: cap '
        '<math xmlns="http://www.w3.org/1998/Math/MathML" alttext="t" '
        'display="inline" id="m2"><mi>t</mi></math></div>\n'
        '<div class="ltx_algorithm_body"><p class="ltx_p">Step $s_1$ done.'
        '</p></div>\n</div>\n'
        '<p class="ltx_p">Note ref<sup><a href="#fn:n1" class="ltx_note_ref">'
        'n1</a></sup> ' + sec2_tail + extra + '</p>\n'
        '<div class="ltx_notes">\n'
        '<div class="ltx_note" id="fn:n1"><span class="ltx_note_mark">n1'
        '</span>\n<div class="ltx_note_content"><p class="ltx_p">' + note +
        '</p></div>\n</div>\n</div>\n'
        '</article>\n</body>\n</html>\n')


def package_aliases(payload, md, marker='## Sec Two'):
    """marker 之前范围（前包）涉及的全局别名集合。"""
    end = md.index(marker)
    return sorted(c['node'] for c in payload['correspondences']
                  if isinstance(c.get('md_start'), int)
                  and c['md_start'] < end)


class PackageEligibilityTest(unittest.TestCase):
    """23-2～23-5：真实恢复链路的无关变化复用与相关变化失效。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='package_eligibility_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        Path(self.tmp, 'images').mkdir()
        Path(self.tmp, 'images/a.png').write_bytes(PNG_BYTES)
        Path(self.tmp, 'trans/images').mkdir(parents=True)
        Path(self.tmp, 'trans/images/a.png').write_bytes(PNG_BYTES)
        self.adaptation = str(Path(self.tmp, 'adapt.json'))
        self.packs = str(Path(self.tmp, 'packs'))
        self.trans = str(Path(self.tmp, 'trans'))
        self.evidence = str(Path(self.tmp, 'evidence.json'))
        # 固定原 HTML v1：解析 → 对账 → 拆包 → 真实复核证据
        self.md1, self.payload1, self.src1 = self._build(make_raw(), 'v1')
        self.written = swp.split(self.src1, self.packs, self.trans, 'h2',
                                 self.adaptation)
        self.names = [os.path.basename(p) for p in self.written]
        assert len(self.names) == 2, self.names
        entries = {}
        for path in self.written:
            entries[Path(path).name] = self._evidence_entry(
                path, self.payload1, self.src1)
        Path(self.evidence).write_text(json.dumps(entries,
                                                  ensure_ascii=False),
                                       encoding='utf-8')

    def _build(self, raw, tag):
        """固定原 HTML → 适配 → 完整对账 → 依据落盘（恒定路径覆盖）。"""
        snap = Path(self.tmp, 'snapshot_%s.html' % tag)
        snap.write_text(raw, encoding='utf-8')
        md, corrs, unres, _f, _adapter = latexml.adapt_latexml_snapshot(
            raw, None, [], self.tmp)
        assert not unres, unres
        payload = latexml.build_candidate_adaptation(
            {'paper_identity': dict(IDENTITY), 'decisions': []},
            raw, str(snap), corrs, unres, selection=None, md_text=md)
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        assert diffs == [], diffs
        src = Path(self.tmp, 'source_%s.md' % tag)
        src.write_text(md, encoding='utf-8')
        Path(self.adaptation).write_text(json.dumps(payload,
                                                    ensure_ascii=False),
                                         encoding='utf-8')
        return md, payload, str(src)

    def _evidence_entry(self, pack_path, payload, src):
        meta, body = rwp._frontmatter(pack_path)
        target = Path(meta['target_file'])
        tbody = body.replace('[IMG: images/a.png]', '![a](images/a.png)')
        text = Path(pack_path).read_text(encoding='utf-8')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace(body, tbody), encoding='utf-8')
        return {
            'source_digest': meta['fragment_digest'],
            'target_digest': rwp._sha256(tbody),
            'resource_digests': rwp._resource_digests(
                tbody, os.path.dirname(os.path.abspath(str(target)))),
            'source_resource_digests': rwp._source_resource_digests(
                body, os.path.dirname(os.path.abspath(src))),
            'checker': rwp._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
            'check_policy': latexml.check_policy_projection(
                payload, int(meta['source_char_start']),
                int(meta['source_char_end']), self.adaptation),
        }

    def _recover(self, src):
        return rwp.recover(src, self.packs, self.trans, 'h2', self.evidence,
                           source_adaptation=self.adaptation)

    def test_baseline_all_reusable(self):
        reusable, _missing, invalidated, pending, _r = self._recover(
            self.src1)
        self.assertEqual([x['name'] for x in reusable], self.names)
        self.assertEqual(invalidated, [])
        self.assertEqual(pending, [])

    def test_evidence_uses_local_occurrence_names(self):
        # 23-1：证据中的 check_policy 不含全篇别名，保留角色/类型/父属/
        # 原内容；真实标签与资源身份不归一
        entries = json.loads(Path(self.evidence).read_text(
            encoding='utf-8'))
        first = entries[self.names[0]]['check_policy']
        nodes = first['nodes']
        self.assertTrue(nodes)
        self.assertTrue(all('[' not in n['node'] for n in nodes), nodes)
        math_nodes = [n for n in nodes if n['content_type'] == 'math']
        self.assertTrue(math_nodes)
        for node in math_nodes:
            self.assertEqual(node['wrap'], '$')
            self.assertTrue(node['tex_sha256'])
        image = next(n for n in nodes if n['content_type'] == 'image')
        self.assertEqual(image['image_target'], 'images/a.png')
        self.assertEqual(image['figure'], 'figure#1')
        second = entries[self.names[1]]['check_policy']
        fn = next(n for n in second['nodes']
                  if n['content_type'] == 'footnote-def')
        self.assertEqual(fn['label'], 'fn:n1')
        self.assertTrue(any(n['content_type'] == 'algorithm'
                            for n in second['nodes']))

    def test_merge_completes_mixed_chain(self):
        # 23-6/24-2：同一混合来源样例贯通恢复 + 合并（证据与来源约束
        # 真实入口），合并输出与逐包译文一致
        import merge_work_packages as mwp
        reusable, _m, invalidated, pending, _r = self._recover(self.src1)
        self.assertEqual([x['name'] for x in reusable], self.names)
        inputs = []
        for name in self.names:
            meta, _b = rwp._frontmatter(
                os.path.join(self.packs, name))
            inputs.append(meta['target_file'])
        out = str(Path(self.tmp, 'merged.md'))
        received = mwp.merge(out, inputs, self.src1, 'h2', self.packs,
                             evidence_path=self.evidence,
                             source_adaptation=self.adaptation)
        self.assertTrue(received)
        merged = Path(out).read_text(encoding='utf-8')
        self.assertIn('![a](images/a.png)', merged)
        self.assertIn('Tail formula $z$ end.', merged)
        self.assertIn('[^fn:n1]: Note text $q$ body.', merged)

    def test_unrelated_later_package_change_keeps_earlier(self):
        # 23-2：只改后包专属公式 → 前包（算法题注/图片前后片段之外的
        # 正文与图片事实）reusable，变包按现行合同失效
        _md, _p, src2 = self._build(
            make_raw(sec2_tail='Tail formula $z+1$ end.'), 'v2')
        reusable, _m, invalidated, pending, _r = self._recover(src2)
        self.assertEqual([x['name'] for x in reusable], [self.names[0]])
        self.assertEqual([x['name'] for x in invalidated], [self.names[1]])
        self.assertEqual(pending, [])

    def test_renumbering_from_later_mathml_keeps_earlier(self):
        # 23-3：只在后包新增 MathML，前包全局别名实际重编号（math[3]→
        # math[4]），但前包正文及相关事实不变 → 仍 reusable
        md3, _p, src3 = self._build(make_raw(extra=EXTRA_MATHML), 'v3')
        self.assertNotEqual(package_aliases(self.payload1, self.md1),
                            package_aliases(_p, md3))
        reusable, _m, invalidated, pending, _r = self._recover(src3)
        self.assertEqual([x['name'] for x in reusable], [self.names[0]])
        self.assertEqual([x['name'] for x in invalidated], [self.names[1]])
        self.assertEqual(pending, [])

    def test_related_earlier_change_invalidates_only_itself(self):
        # 23-4/23-5：前包自身公式变化 → 前包失效，后包（含算法题注与
        # 脚注定义）局部事实不变仍 reusable
        _md, _p, src4 = self._build(make_raw(sec1_math='$a_0$'), 'v4')
        reusable, _m, invalidated, pending, _r = self._recover(src4)
        self.assertEqual([x['name'] for x in reusable], [self.names[1]])
        self.assertEqual([x['name'] for x in invalidated], [self.names[0]])
        self.assertEqual(pending, [])

    def test_related_footnote_change_invalidates_owning_package(self):
        # 23-4：脚注定义变化使其所属包失效，引用无关包不牵连
        _md, _p, src5 = self._build(
            make_raw(note='Note text $q$ body!'), 'v5')
        reusable, _m, invalidated, pending, _r = self._recover(src5)
        self.assertEqual([x['name'] for x in reusable], [self.names[0]])
        self.assertEqual([x['name'] for x in invalidated], [self.names[1]])
        self.assertEqual(pending, [])

    def test_rereview_restores_eligibility(self):
        # 23-5：失效后重新实际复核（重建证据绑定）恢复资格；旧证据不能
        # 靠改名或补摘要追认
        _md, payload2, src2 = self._build(
            make_raw(sec2_tail='Tail formula $z+1$ end.'), 'v2')
        reusable, _m, invalidated, _p, _r = self._recover(src2)
        self.assertEqual([x['name'] for x in invalidated], [self.names[1]])
        # 失效包按真实流程重拆（替换 wps 中的旧包）、重译并重新登记证据
        entries = json.loads(Path(self.evidence).read_text(
            encoding='utf-8'))
        resplit = swp.split(src2, self.packs, self.trans, 'h2',
                            self.adaptation)
        for path in resplit:
            if Path(path).name == self.names[1]:
                entries[self.names[1]] = self._evidence_entry(
                    path, payload2, src2)
        Path(self.evidence).write_text(json.dumps(entries,
                                                  ensure_ascii=False),
                                       encoding='utf-8')
        reusable, _m, invalidated, pending, _r = self._recover(src2)
        self.assertEqual([x['name'] for x in reusable], self.names)
        self.assertEqual(invalidated, [])
        self.assertEqual(pending, [])


class GroupRelationProjectionTest(unittest.TestCase):
    """23-1/23-4：组关系引用随同一局部映射归一，式号官方编号不归一。"""

    def test_group_members_local_eqnos_preserved(self):
        raw = GROUP_FIXTURE.read_text(encoding='utf-8')
        md, corrs, unres, _f, adapter = latexml.adapt_latexml_snapshot(
            raw, None, [], str(GROUP_FIXTURE.parent))
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(GROUP_FIXTURE), 'sha256': ''},
            'paper_identity': {}, 'decisions': [],
            'correspondences': corrs, 'unresolved': unres,
            'groups': adapter.groups,
        }
        policy = latexml.check_policy_projection(payload, 0, len(md) + 1,
                                                 str(GROUP_FIXTURE))
        self.assertEqual(len(policy['groups']), 1)
        group = policy['groups'][0]
        self.assertEqual(group['node'], 'group#1')
        self.assertTrue(all('[' not in m for m in group['members']))
        # 成员局部名必须能在 nodes 中解析（一致局部映射，不是悬空引用）
        node_names = {n['node'] for n in policy['nodes']}
        self.assertTrue(all(m in node_names for m in group['members']))
        # 官方编号与真实锚点不作别名归一
        self.assertEqual(group['eqnos'],
                         [{'member': 0, 'text': '(1)', 'target': '#e1'},
                          {'member': 1, 'text': '(2)', 'target': '#e2'}])


if __name__ == '__main__':
    unittest.main()
