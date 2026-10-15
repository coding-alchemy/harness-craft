"""二期 ticket 22：脚注与多章 PDF 消费闭环。

覆盖验收 22-1～22-6：脚注定义与引用按来源身份逐项成事实（命名标签、
引用序≠定义序、注内 MathML/字面/跨行公式各有个体对应与精确区间）；
脚注内删式/改式、删引用、错目标、删定义、同表达式跨定义区间交换均按
目标原因拒绝；footnote-def 不再授予宿主豁免（bound_math_spans 逐出现
绑定，旧第二套投影 drop_host_math_spans 已删除）；多章消费按章分配，
缺章/额外公式章/空绑定章渲染非空均拒绝；受来源约束的真实 PDF 导出与
独立核验走合法脚注渲染投影序，消费表达式漂移按 source-math-mismatch
拒绝。
"""
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
import export_pdf as exporter
import verify_pdf as verifier
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / (
    'latexml_footnotes.html')
SCRIPTS = Path(__file__).resolve().parents[1] / (
    'skills/tech-doc-translator/scripts')

IDENTITY = {
    'expected_title': 'Footnote Facts', 'actual_title': 'Footnote Facts',
    'paper_id': '2210.00022', 'version': 'v1',
    'final_url': 'https://example.org/abs/2210.00022v1',
    'retrieved_at': '2026-10-10T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}


def _adapt(snapshot_path=None):
    raw = FIXTURE.read_text(encoding='utf-8')
    md, corrs, unres, _fidelity, _adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], str(FIXTURE.parent))
    payload = latexml.build_candidate_adaptation(
        {'paper_identity': dict(IDENTITY), 'decisions': []},
        raw, str(snapshot_path or FIXTURE), corrs, unres,
        selection=None, md_text=md)
    return raw, md, payload


def _corr(payload, node):
    return next(c for c in payload['correspondences']
                if c.get('node') == node)


def _math_corrs(payload):
    return [c for c in payload['correspondences']
            if c.get('content_type') == 'math']


class FootnoteSourceFactsTest(unittest.TestCase):
    """22-1：脚注定义/引用与注内公式逐项成来源事实，roundtrip 干净。"""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.md, cls.payload = _adapt()

    def test_roundtrip_clean(self):
        self.assertEqual(
            reconcile_latexml_to_markdown(self.raw, self.md, None,
                                          self.payload), [])

    def test_reference_order_differs_from_definition_order(self):
        # 正文先引 fn:beta 后引 fn:alpha；定义序 alpha 先 beta 后
        self.assertLess(self.md.find('[^fn:beta]'),
                        self.md.find('[^fn:alpha]'))
        self.assertLess(self.md.find('[^fn:alpha]:'),
                        self.md.find('[^fn:beta]:'))

    def test_definition_facts_carry_label_and_exact_range(self):
        fn1 = _corr(self.payload, 'fn[1]')
        fn2 = _corr(self.payload, 'fn[2]')
        self.assertEqual((fn1['content_type'], fn1['label']),
                         ('footnote-def', 'fn:alpha'))
        self.assertEqual((fn2['content_type'], fn2['label']),
                         ('footnote-def', 'fn:beta'))
        self.assertEqual(
            self.md[fn1['md_start']:fn1['md_end']],
            '[^fn:alpha]: Alpha note $x$ and lit $q$ here.')
        self.assertEqual(
            self.md[fn2['md_start']:fn2['md_end']],
            '[^fn:beta]: Beta note same $q$ lit and $w\n+1$ multi.')

    def test_footnote_math_has_individual_identity_and_range(self):
        corrs = _math_corrs(self.payload)
        # 正文 $m$ + 注内 MathML $x$、跨行字面 $w\n+1$、两处同表达式 $q$
        self.assertEqual(sorted(c['tex'] for c in corrs),
                         sorted(['m', 'x', 'q', 'q', 'w\n+1']))
        for corr in corrs:
            self.assertEqual(corr['kind'], 'inline')
            self.assertEqual(
                self.md[corr['md_start']:corr['md_end']],
                '$%s$' % corr['tex'])
        # 同表达式 q 各自绑定自己的出现身份，区间互不相同且落在所属定义内
        q_corrs = sorted((c for c in corrs if c['tex'] == 'q'),
                         key=lambda c: c['md_start'])
        self.assertEqual(len(q_corrs), 2)
        self.assertNotEqual((q_corrs[0]['md_start'], q_corrs[0]['md_end']),
                            (q_corrs[1]['md_start'], q_corrs[1]['md_end']))
        fn1, fn2 = _corr(self.payload, 'fn[1]'), _corr(self.payload, 'fn[2]')
        self.assertTrue(fn1['md_start'] <= q_corrs[0]['md_start']
                        < q_corrs[0]['md_end'] <= fn1['md_end'])
        self.assertTrue(fn2['md_start'] <= q_corrs[1]['md_start']
                        < q_corrs[1]['md_end'] <= fn2['md_end'])


class FootnoteDamageRejectionTest(unittest.TestCase):
    """22-3：脚注相关损伤按目标原因拒绝。"""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.md, cls.payload = _adapt()

    def _diffs(self, md=None, payload=None):
        return reconcile_latexml_to_markdown(
            self.raw, md if md is not None else self.md, None,
            payload if payload is not None else self.payload)

    def test_reference_deleted_rejected(self):
        damaged = self.md.replace(' then alpha [^fn:alpha] end.',
                                  ' then alpha end.')
        diffs = self._diffs(md=damaged)
        self.assertTrue(any('候选内容被改写/删除' in d for d in diffs), diffs)

    def test_reference_wrong_target_rejected(self):
        damaged = self.md.replace('[^fn:beta] mid', '[^fn:alpha] mid', 1)
        diffs = self._diffs(md=damaged)
        self.assertTrue(any('正文流' in d for d in diffs), diffs)

    def test_definition_deleted_rejected(self):
        damaged = self.md.replace(
            '\n[^fn:beta]: Beta note same $q$ lit and $w\n+1$ multi.\n',
            '\n')
        diffs = self._diffs(md=damaged)
        self.assertTrue(any('公式出现数量不一致' in d for d in diffs), diffs)
        self.assertTrue(any('漏节点' in d for d in diffs), diffs)

    def test_math_deleted_inside_definition_rejected(self):
        damaged = self.md.replace('Alpha note $x$ and lit $q$ here.',
                                  'Alpha note and lit $q$ here.')
        diffs = self._diffs(md=damaged)
        self.assertTrue(any('正文流' in d
                            for d in diffs), diffs)
        self.assertTrue(any('公式出现数量不一致' in d for d in diffs), diffs)

    def test_math_changed_inside_definition_rejected(self):
        damaged = self.md.replace('Beta note same $q$ lit',
                                  'Beta note same $r$ lit')
        diffs = self._diffs(md=damaged)
        self.assertTrue(any('候选跨度不符' in d for d in diffs), diffs)
        self.assertTrue(any('正文流' in d
                            for d in diffs), diffs)

    def test_same_expression_cross_definition_interval_swap_rejected(self):
        # 两处同表达式 $q$ 交换候选区间：身份传递区间不符，同文本不能顶替
        payload = copy.deepcopy(self.payload)
        q_corrs = sorted((c for c in payload['correspondences']
                          if c.get('content_type') == 'math'
                          and c.get('tex') == 'q'),
                         key=lambda c: c['md_start'])
        self.assertEqual(len(q_corrs), 2)
        first, second = q_corrs
        (first['md_start'], first['md_end'],
         second['md_start'], second['md_end']) = (
            second['md_start'], second['md_end'],
            first['md_start'], first['md_end'])
        diffs = self._diffs(payload=payload)
        swaps = [d for d in diffs if '出现身份传递区间' in d]
        self.assertEqual(len(swaps), 2, diffs)


class HostExemptionRemovedTest(unittest.TestCase):
    """22-2/22-6：footnote-def 不再授予宿主豁免；第二套投影已删除。"""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.md, cls.payload = _adapt()

    def test_footnote_math_bound_per_occurrence(self):
        spans, problems = latexml.bound_math_spans(self.md, self.payload,
                                                   full=True)
        self.assertEqual(problems, [])
        self.assertEqual([(kind, tex) for kind, tex, _s, _e in spans],
                         [('inline', 'm'), ('inline', 'x'), ('inline', 'q'),
                          ('inline', 'q'), ('inline', 'w\n+1')])
        for kind, tex, start, end in spans:
            self.assertEqual(self.md[start:end], '$%s$' % tex)

    def test_deleted_footnote_math_correspondence_rejected(self):
        # 删掉注内 MathML $x$ 的对应：宿主豁免不再救场，跨度未绑定即拒绝
        payload = copy.deepcopy(self.payload)
        payload['correspondences'] = [
            c for c in payload['correspondences']
            if not (c.get('content_type') == 'math' and c.get('tex') == 'x')]
        _spans, problems = latexml.bound_math_spans(self.md, payload,
                                                    full=True)
        self.assertTrue(any('未绑定到来源依据' in p for p in problems),
                        problems)

    def test_second_projection_helper_removed(self):
        self.assertFalse(hasattr(latexml, 'drop_host_math_spans'))


class MultiChapterConsumptionTest(unittest.TestCase):
    """22-4：多章按实际范围分配已确认公式；缺章/额外公式章/空绑定章拒绝。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='footnote_pdf_facts_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        raw, self.md_a, payload_a = _adapt(
            snapshot_path=Path(self.tmp) / 'snapshot_a.html')
        Path(self.tmp, 'snapshot_a.html').write_text(raw, encoding='utf-8')
        raw_b = (
            '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8">'
            '<title>Footnote Facts</title></head>\n<body>\n'
            '<article id="paper" class="ltx_document">\n'
            '<h1 class="ltx_title">Footnote Facts</h1>\n'
            '<p class="ltx_p">Second part has no math at all.</p>\n'
            '</article>\n</body>\n</html>\n')
        Path(self.tmp, 'snapshot_b.html').write_text(raw_b, encoding='utf-8')
        md_b, corrs_b, unres_b, _f, _a = latexml.adapt_latexml_snapshot(
            raw_b, None, [], self.tmp)
        self.md_b = md_b
        self.payload_b = latexml.build_candidate_adaptation(
            {'paper_identity': dict(IDENTITY), 'decisions': []},
            raw_b, str(Path(self.tmp) / 'snapshot_b.html'), corrs_b,
            unres_b, selection=None, md_text=md_b)
        self.paths = []
        for name, payload in (('a.adaptation.json', payload_a),
                              ('b.adaptation.json', self.payload_b)):
            path = Path(self.tmp) / name
            path.write_text(json.dumps(payload, ensure_ascii=False),
                            encoding='utf-8')
            self.paths.append(str(path))
        Path(self.tmp, 'c1.md').write_text(self.md_a, encoding='utf-8')
        self.chapter_a = exporter.Chapter(1, Path(self.tmp, 'c1.md'))
        Path(self.tmp, 'c2.md').write_text(self.md_b, encoding='utf-8')
        self.chapter_b = exporter.Chapter(2, Path(self.tmp, 'c2.md'))

    def test_single_source_toc_does_not_consume_body_formulas(self):
        toc_path = Path(self.tmp, '00_目录.md')
        toc_path.write_text('# 目录\n\n[正文](c1.md)\n', encoding='utf-8')
        toc = exporter.Chapter(1, toc_path)
        exporter.apply_source_math_context(
            [toc, self.chapter_a], {'_path': self.paths[0]})
        exporter.parse_chapter(toc)
        exporter.parse_chapter(self.chapter_a)
        self.assertEqual(toc.math, [])
        self.assertEqual(len(self.chapter_a.math), 5)
        damaged = Path(self.tmp, 'damaged.md')
        damaged.write_text('# 正文\n\n无公式。\n', encoding='utf-8')
        missing = exporter.Chapter(2, damaged)
        exporter.apply_source_math_context(
            [toc, missing], {'_path': self.paths[0]})
        with self.assertRaises(exporter.ExportError):
            exporter.parse_chapter(missing)

    def test_per_chapter_assignment_with_footnote_math(self):
        chapters = [self.chapter_a, self.chapter_b]
        info = exporter.apply_source_math_context(
            chapters, {'_paths': list(self.paths)})
        self.assertEqual([t for _k, t in chapters[0].math_confirmed],
                         ['m', 'x', 'q', 'q', 'w\n+1'])
        self.assertEqual(chapters[1].math_confirmed, [])
        self.assertEqual(info['paths'],
                         [str(Path(p).resolve()) for p in self.paths])

    def test_missing_chapter_rejected(self):
        with self.assertRaises(exporter.ExportError) as ctx:
            exporter.apply_source_math_context(
                [self.chapter_b], {'_paths': list(self.paths)})
        self.assertIn('未落入任何章节', str(ctx.exception))

    def test_extra_math_chapter_rejected(self):
        # 无公式的 B 章被加入额外公式：确认序列耗尽后仍有跨度即拒绝
        Path(self.tmp, 'c2x.md').write_text(
            self.md_b + '\n额外公式 $z$。\n', encoding='utf-8')
        chapter_bx = exporter.Chapter(2, Path(self.tmp, 'c2x.md'))
        with self.assertRaises(exporter.ExportError) as ctx:
            exporter.apply_source_math_context(
                [self.chapter_a, chapter_bx], {'_paths': list(self.paths)})
        self.assertIn('已确认序列之外', str(ctx.exception))

    def test_empty_bound_chapter_rendered_nonempty_rejected(self):
        # 空列表不是免检依据：绑定为空的章渲染出公式即 source-math-mismatch
        chapters = [self.chapter_a, self.chapter_b]
        exporter.apply_source_math_context(chapters,
                                           {'_paths': list(self.paths)})
        self.chapter_b.math = [{'mode': 'inline',
                                'original_form': 'dollar_inline',
                                'latex': 'z'}]
        report = {'browser_checks': {},
                  'chapters': [{}, {'math': list(self.chapter_b.math)}]}
        failures = []
        verifier.check_math(chapters, report,
                            Path(self.tmp) / 'nonexistent.pdf', [],
                            failures)
        codes = [f['code'] for f in failures]
        self.assertIn('source-math-mismatch', codes, failures)


class SourceConstrainedPdfExportTest(unittest.TestCase):
    """22-5：受来源约束的真实 PDF 导出 + 脚注渲染投影序 + 独立核验。

    脚注定义按首次引用序移到章末（beta 先于 alpha），渲染序
    m/q/w+1/x/q 与源序 m/x/q/q/w+1 不同但合法；消费表达式漂移按
    source-math-mismatch 拒绝。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='footnote-pdf-facts-'))
        raw, md, payload = _adapt(
            snapshot_path=cls.base / 'snapshot.html')
        (cls.base / 'snapshot.html').write_text(raw, encoding='utf-8')
        cls.adaptation = cls.base / 'source.adaptation.json'
        cls.adaptation.write_text(json.dumps(payload, ensure_ascii=False),
                                  encoding='utf-8')
        # 导出视图带出处行（真实交付形态），公式序列与来源一致
        lines = md.split('\n')
        cls.doc_text = (lines[0]
                        + '\n\n> **来源**：https://example.com/probe\n'
                        + '\n'.join(lines[1:]))
        cls.doc = cls.base / 'doc.md'
        cls.doc.write_text(cls.doc_text, encoding='utf-8')
        cls.declaration = cls.base / 'decl.json'
        cls.declaration.write_text(json.dumps({
            'version': 1,
            'inputs': [{'path': str(cls.doc.resolve()),
                        'sha256': hashlib.sha256(
                            cls.doc.read_bytes()).hexdigest()}],
            'exclusions': [],
            'document_title': {'original': 'Footnote Facts',
                               'chinese': '脚注事实样例',
                               'basis': '测试夹具题名'},
        }, ensure_ascii=False), encoding='utf-8')
        cls.pdf = cls.base / 'doc.pdf'
        cls.work = cls.base / 'work'
        result = cls._run('export_pdf.py', [
            '--output', str(cls.pdf), '--work-dir', str(cls.work),
            '--source-adaptation', str(cls.adaptation),
            '--view-declaration', str(cls.declaration), str(cls.doc)])
        assert result.returncode == 0, result.stderr[-800:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    @staticmethod
    def _run(script, args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script)] + args,
            capture_output=True, text=True)

    def _verify(self, doc):
        return self._run('verify_pdf.py', [
            '--pdf', str(self.pdf), '--work-dir', str(self.work),
            '--source-adaptation', str(self.adaptation),
            '--view-declaration', str(self.declaration), str(doc)])

    def test_source_constrained_export_render_projection(self):
        report = json.loads((self.work / 'export_report.json')
                            .read_text(encoding='utf-8'))
        math_list = [(m['mode'], m['latex'])
                     for m in report['chapters'][0]['math']]
        self.assertEqual(math_list, [('inline', 'm'), ('inline', 'q'),
                                     ('inline', 'w\n+1'), ('inline', 'x'),
                                     ('inline', 'q')])
        self.assertEqual(report['browser_checks'].get('mathTotal'), 5)

    def test_source_constrained_verify_passes(self):
        result = self._verify(self.doc)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])

    def test_consumed_expression_drift_rejected(self):
        damaged = self.base / 'doc_damaged.md'
        damaged.write_text(self.doc_text.replace(
            'Beta note same $q$ lit', 'Beta note same $r$ lit'),
            encoding='utf-8')
        result = self._verify(damaged)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads((self.work / 'verify_report.json')
                            .read_text(encoding='utf-8'))
        codes = [f['code'] for f in report.get('failures', [])]
        self.assertIn('source-math-mismatch', codes, codes)


if __name__ == '__main__':
    unittest.main()
