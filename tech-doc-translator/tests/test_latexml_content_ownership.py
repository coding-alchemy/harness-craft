"""二期 ticket 03：浮动体、算法与脚注的内容和归属保真。

覆盖验收 03-1～03-7 的底层定向用例：图/子图全部出现与父归属、算法与
代码清单、命名脚注配对（不抽数字合并）、渲染错误保留、装饰排除与
同源重复合并裁决的独立验证、check_policy 投影与失效。
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_content.html'

IDENTITY = {
    'expected_title': 'T03 Fixture', 'actual_title': 'T03 Fixture',
    'paper_id': '2203.00003', 'version': 'v1',
    'final_url': 'https://example.org/abs/2203.00003v1',
    'retrieved_at': '2026-10-03T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}

DECISIONS = [
    {'node': 'nav', 'action': 'exclude-decoration',
     'basis': '分页导航：仅页码链接，确认为装饰（人工回源核对）'},
    {'node': 'aside[2]', 'action': 'merge-duplicate', 'into': 'aside[1]',
     'basis': '同源重复表示：两处引文同字同序，人工核对内容一致'},
]


def _adapt(decisions=None):
    raw = FIXTURE.read_text(encoding='utf-8')
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, list(DECISIONS if decisions is None else decisions),
        str(FIXTURE.parent))
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': str(FIXTURE),
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': list(DECISIONS if decisions is None else decisions),
        'correspondences': corrs,
        'unresolved': unres,
    }
    if adapter.groups:
        payload['groups'] = adapter.groups
    if adapter.decision_results:
        payload['decision_results'] = adapter.decision_results
    return raw, md, payload, adapter


class FigureOwnershipTest(unittest.TestCase):
    """03-1/03-5：全部图出现与子图父归属，不只取首图。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_all_image_occurrences_emitted(self):
        images = [c for c in self.payload['correspondences']
                  if c.get('content_type') == 'image']
        self.assertEqual(len(images), 3)  # 主图 + 两个子图，不只首图
        self.assertEqual(self.md.count('[IMG:'), 3)

    def test_parent_and_subfigure_recorded(self):
        images = {c['node']: c for c in self.payload['correspondences']
                  if c.get('content_type') == 'image'}
        self.assertEqual(images['img[1]']['figure'], 'figure[1]')
        self.assertIsNone(images['img[1]']['subfigure'])
        self.assertEqual(images['img[2]']['figure'], 'figure[1]')
        self.assertEqual(images['img[2]']['subfigure'], 1)
        self.assertEqual(images['img[3]']['subfigure'], 2)
        captions = [c for c in self.payload['correspondences']
                    if c.get('content_type') == 'figure-caption']
        self.assertEqual(len(captions), 3)
        self.assertEqual(
            sorted((c.get('subfigure') for c in captions),
                   key=lambda v: (v is None, v)),
            [1, 2, None])

    def test_same_bytes_not_deduplicated(self):
        # 子图两图同 basename 资源但各自出现独立记录（同字节不去重）
        self.assertIn(self.md.count('[IMG: images/b.png]'), (2,))

    def test_missing_subfigure_rejected(self):
        damaged = self.md.replace(
            '\n[IMG: images/b.png]\n[FIGURE] (a) Sub one.\n', '\n', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d or '漏节点' in d for d in diffs))

    def test_wrong_parent_rejected(self):
        payload = copy.deepcopy(self.payload)
        corr = next(c for c in payload['correspondences']
                    if c.get('content_type') == 'image'
                    and c.get('subfigure') == 1)
        corr['subfigure'] = 2
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('错父节点' in d for d in diffs))

    def test_missing_image_correspondence_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['correspondences'] = [
            c for c in payload['correspondences']
            if not (c.get('content_type') == 'image'
                    and c.get('node') == 'img[2]')]
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('漏节点' in d for d in diffs))


class AlgorithmTest(unittest.TestCase):
    """03-2：算法题注归属本清单，代码走既有保护，不转代码绕过门禁。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_algorithm_title_and_code(self):
        self.assertIn('[ALGORITHM] Algorithm 1: Greedy select', self.md)
        self.assertIn('```\ndef pick(w):\n    return argmax(w)\n```',
                      self.md)
        algo = next((c for c in self.payload['correspondences']
                     if c.get('content_type') == 'algorithm'), None)
        self.assertIsNotNone(algo)
        self.assertEqual(algo['title'], 'Algorithm 1: Greedy select')

    def test_body_math_preserved(self):
        self.assertIn('$k = \\arg\\max_i w_i$', self.md)

    def test_removed_title_rejected(self):
        damaged = self.md.replace(
            '[ALGORITHM] Algorithm 1: Greedy select\n\n', '', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_removed_code_rejected(self):
        damaged = self.md.replace(
            '```\ndef pick(w):\n    return argmax(w)\n```\n\n', '', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))


class FootnoteTest(unittest.TestCase):
    """03-3：命名标签配对、定义内容完整、不抽数字合并。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_named_label_preserved(self):
        self.assertIn('[^fn:details]', self.md)
        self.assertIn('[^fn:details]: Details with code `flag=1` '
                      'and math $s=2$ inline.', self.md)

    def test_definition_correspondence(self):
        fndef = next((c for c in self.payload['correspondences']
                      if c.get('content_type') == 'footnote-def'), None)
        self.assertIsNotNone(fndef)
        self.assertEqual(fndef['label'], 'fn:details')

    def test_definition_deleted_rejected(self):
        damaged = self.md.replace(
            '[^fn:details]: Details with code `flag=1` and math $s=2$ '
            'inline.\n', '\n', 1)
        self.assertNotIn('fn:details]:', damaged)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_label_merge_rejected(self):
        payload = copy.deepcopy(self.payload)
        for c in payload['correspondences']:
            if c.get('content_type') == 'footnote-def':
                c['label'] = 'fn:other'
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('标签不符' in d for d in diffs))

    def test_roundtrip_clean(self):
        self.assertEqual(reconcile_latexml_to_markdown(
            self.raw, self.md, None, self.payload), [])


class LiteralMathCorrTest(unittest.TestCase):
    """08：字面数学快照的 math[k] 扫描对应被独立对账承认（宿主覆盖/
    重建流匹配 + 切片逐字），损伤仍按目标原因拒绝。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()
        self.payload = copy.deepcopy(self.payload)
        start = self.md.find('$s=2$')
        self.assertGreaterEqual(start, 0)
        # 三轮 F3：字面公式对应由适配器本次重建自动生成（不再手工追加）；
        # 本组测试消费该自动生成条目验证对账端承认/拒绝口径
        corr = [c for c in self.payload['correspondences']
                if c.get('content_type') == 'math'
                and c.get('md_start') == start
                and c.get('md_end') == start + len('$s=2$')]
        self.assertEqual(len(corr), 1,
                         '适配器应自动生成该字面公式对应（三轮 F3）')
        self.assertEqual(corr[0].get('tex'), 's=2')
        self.corr = corr[0]
        self.corr_node = self.corr['node']

    def diffs(self):
        return reconcile_latexml_to_markdown(self.raw, self.md, None,
                                             self.payload)

    def test_host_covered_corr_accepted(self):
        self.assertEqual(self.diffs(), [])

    def test_damaged_tex_rejected(self):
        for c in self.payload['correspondences']:
            if c.get('node') == self.corr_node:
                c['tex'] = 's=3'
        self.assertTrue(any('表达式与原节点不符' in d for d in self.diffs()))

    def test_damaged_range_rejected(self):
        for c in self.payload['correspondences']:
            if c.get('node') == self.corr_node:
                c['md_end'] += 3
        diffs = self.diffs()
        self.assertTrue(any('与实际写出内容不符' in d
                            or '出现身份传递区间' in d for d in diffs))

    def test_math_math_overlap_rejected(self):
        twin = dict(self.corr, node='math[twin]',
                    md_start=self.corr['md_start'] + 1)
        self.payload['correspondences'].append(twin)
        self.assertTrue(any('范围交叠' in d for d in self.diffs()))

    def test_unmatched_and_unhosted_rejected(self):
        # 宿主被移除且表达式不在重建流：不得凭扫描对应放行
        self.payload['correspondences'] = [
            c for c in self.payload['correspondences']
            if c.get('content_type') != 'footnote-def']
        for c in self.payload['correspondences']:
            if c.get('node') == self.corr_node:
                c['tex'] = 'unmatched'
                c['md_end'] = c['md_start'] + len('$unmatched$')
        diffs = self.diffs()
        self.assertTrue(any('漏节点' in d or '切片' in d or '不符' in d
                            for d in diffs))


class RenderingErrorTest(unittest.TestCase):
    """03-4：渲染错误内容保留；装饰排除与重复合并按裁决验证。"""

    def setUp(self):
        self.raw, self.md, self.payload, self.adapter = _adapt()

    def test_error_content_preserved(self):
        self.assertIn('Broken fallback text.', self.md)

    def test_error_content_deleted_rejected(self):
        damaged = self.md.replace('Broken fallback text.\n\n', '', 1)
        diffs = reconcile_latexml_to_markdown(self.raw, damaged, None,
                                              self.payload)
        self.assertTrue(any('正文流' in d for d in diffs))

    def test_nav_excluded_by_decision(self):
        self.assertNotIn('[NAV]', self.md)
        self.assertNotIn('Page 2 of 5', self.md)
        results = {r['node']: r['result']
                   for r in self.payload['decision_results']}
        self.assertEqual(results['nav'], 'excluded')

    def test_duplicate_merged_by_decision(self):
        self.assertEqual(self.md.count('Duplicate stage summary.'), 1)
        results = {r['node']: r['result']
                   for r in self.payload['decision_results']}
        self.assertEqual(results['aside[2]'], 'merged')

    def test_forged_merge_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['decision_results'] = list(payload['decision_results']) + [
            {'node': 'figure[1]', 'action': 'merge-duplicate',
             'into': 'aside[1]', 'basis': '伪造', 'result': 'merged'}]
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('重复合并裁决' in d for d in diffs))

    def test_exclusion_not_decorative_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload['decision_results'] = list(payload['decision_results']) + [
            {'node': 'figure[1]', 'action': 'exclude-decoration',
             'basis': '伪造', 'result': 'excluded'}]
        diffs = reconcile_latexml_to_markdown(self.raw, self.md, None,
                                              payload)
        self.assertTrue(any('装饰排除裁决' in d for d in diffs))

    def test_unmergeable_decision_keeps_content(self):
        _raw, md, payload, _ad = _adapt(decisions=[
            {'node': 'aside[2]', 'action': 'merge-duplicate',
             'into': 'figure[1]', 'basis': '内容不同的合并请求'}])
        results = {r['node']: r.get('result')
                   for r in payload['decision_results']}
        self.assertEqual(results['aside[2]'], 'unresolved')
        self.assertIn('Duplicate stage summary.', md)


class CheckPolicyContentTest(unittest.TestCase):
    """03-7：内容/归属/裁决进 check_policy 投影；相关变化使包失效。"""

    def test_projection_contains_ownership_and_decisions(self):
        _raw, md, payload, _ad = _adapt()
        with tempfile.NamedTemporaryFile('w', suffix='.json',
                                         delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            path = handle.name
        try:
            policy = latexml.check_policy_projection(payload, 0,
                                                     len(md) + 1, path)
            kinds = {n['content_type'] for n in policy['nodes']}
            self.assertIn('image', kinds)
            self.assertIn('figure-caption', kinds)
            self.assertIn('footnote-def', kinds)
            self.assertIn('algorithm', kinds)
            self.assertTrue(any(
                d.get('action') == 'merge-duplicate'
                for d in policy['decisions']))
            before = copy.deepcopy(policy)
            for c in payload['correspondences']:
                if c.get('content_type') == 'image' and c.get('subfigure'):
                    c['subfigure'] = 9
            changed = latexml.check_policy_projection(
                payload, 0, len(md) + 1, path)
            self.assertNotEqual(before, changed)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
