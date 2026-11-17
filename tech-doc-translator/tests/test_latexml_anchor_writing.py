# coding: utf-8
"""R3：解析稿按宿主写入链接目标锚点，源对账照常通过，删改锚点被核验拒绝。"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from latexml_test_support import current_candidate, latexml, reconcile_latexml_to_markdown
import verify_reference_translation as reference_verifier
from _api_navigation import compare_anchors

FIXTURE_PNG = Path(__file__).resolve().parent / 'fixtures/valid_1x1.png'
RAW = (
    '<article class="ltx_document"><h1 class="ltx_title">T</h1>'
    '<section class="ltx_section" id="S1"><h2 class="ltx_title">1 Intro</h2>'
    '<div class="ltx_para" id="S1.p1"><p class="ltx_p" id="S1.p1.1">See '
    '<a href="#S1.F1">Figure 1</a>, <a href="#S2">Section 2</a>, '
    '<a href="#S1.E1">(1)</a>, <a href="#bib.bib1">[1]</a> and '
    '<a href="#S1.p2.1">below</a>.</p></div>'
    '<div class="ltx_para" id="S1.p2"><p class="ltx_p" id="S1.p2.1">Second paragraph.</p></div>'
    '<table class="ltx_equation ltx_eqn_table"><tbody id="S1.E1">'
    '<tr class="ltx_equation ltx_eqn_row"><td class="ltx_eqn_cell">'
    '<math alttext="x=1" display="block"><mi>x</mi></math></td>'
    '<td class="ltx_eqn_cell ltx_eqn_eqno">(1)</td></tr></tbody></table>'
    '<figure class="ltx_figure" id="S1.F1"><img src="a.png" width="10" height="10"/>'
    '<figcaption class="ltx_caption">Figure 1: Cap.</figcaption></figure>'
    '</section>'
    '<section class="ltx_section" id="S2"><h2 class="ltx_title">2 Method</h2>'
    '<p class="ltx_p">Method text <code>&lt;a href="#fake"&gt;&lt;/a&gt;</code>.</p></section>'
    '<section class="ltx_bibliography"><h2 class="ltx_title">References</h2>'
    '<ul class="ltx_biblist"><li class="ltx_bibitem" id="bib.bib1">A (2020) Title.</li></ul>'
    '</section></article>')


class AnchorWritingTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='anchor-writing-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        shutil.copy(FIXTURE_PNG, self.base / 'a.png')
        self.md, self.payload = current_candidate(self.base, RAW)

    def test_anchor_forms(self):
        md = self.md
        self.assertIn('<a id="S1.p2.1"></a>Second paragraph.', md)
        self.assertIn('<a id="S1.E1"></a>(1)', md)
        self.assertIn('<a id="bib.bib1"></a>A (2020)', md)
        self.assertRegex(md, r'(?m)^<a id="S1\.F1"></a>\n\n')
        self.assertRegex(md, r'(?m)^<a id="S2"></a>\n\n## 2 Method')

    def test_reconcile_passes_with_anchors(self):
        diffs = reconcile_latexml_to_markdown(RAW, self.md, None, self.payload)
        self.assertEqual(diffs, [])

    def test_damage_still_rejected(self):
        damaged = self.md.replace('Second paragraph.', 'Second.')
        payload = dict(self.payload)
        diffs = reconcile_latexml_to_markdown(RAW, damaged, None, payload)
        self.assertTrue(diffs)

    def test_no_targets_no_anchors(self):
        raw = RAW.replace('href="#', 'href="https://example.org/#')
        md, _payload = current_candidate(self.base, raw)
        self.assertNotIn('<a id=', md)

    def test_footnote_own_id_not_written(self):
        # 评审重点 4：指向脚注的链接已转为 [^label]，脚注自身 id 不写锚点
        from latexml_test_support import note, raw_document
        md, payload = current_candidate(self.base, raw_document(note('Note text.')))
        self.assertNotIn('<a id="fn:a">', md)
        self.assertIn('[^', md)


SOURCE = ('<a id="S1"></a>\n\n## 1 Intro\n\n<a id="S1.p1.1"></a>Text.\n\n'
          '$$x=1$$\n\n<a id="S1.E1"></a>(1)\n\n<a id="bib.bib1"></a>A (2020) Title.\n')


class AnchorCompareTest(unittest.TestCase):
    def test_same_anchors_pass(self):
        translated = SOURCE.replace('Text.', '正文。').replace('1 Intro', '1 引言')
        self.assertEqual(compare_anchors(SOURCE, translated, inline=True), [])

    def test_missing_moved_or_reformed_anchor_fails(self):
        for broken in (SOURCE.replace('<a id="S1.p1.1"></a>', ''),
                       SOURCE.replace('<a id="S1.E1"></a>(1)', '(1)\n\n<a id="S1.E1"></a>'),
                       SOURCE.replace('<a id="S1.p1.1"></a>Text.', 'Text.<a id="S1.p1.1"></a>'),
                       SOURCE.replace('<a id="S1"></a>\n\n## 1 Intro\n\n<a id="S1.p1.1"></a>Text.',
                                      '<a id="S1.p1.1"></a>\n\n## 1 Intro\n\n<a id="S1"></a>Text.')):
            with self.subTest(broken=broken[:40]):
                problems = compare_anchors(SOURCE, broken, inline=True)
                self.assertTrue(problems)
                self.assertIn('来源锚点', problems[0])

    def test_default_mode_unchanged(self):
        # inline=False 只认独占一行的锚点：行内写法差异不报（API 家族行为不变）
        broken = SOURCE.replace('<a id="S1.p1.1"></a>', '')
        self.assertEqual(compare_anchors(SOURCE, broken), [])

    def test_anchor_text_in_code_is_ignored(self):
        # 评审重点 3
        source = 'Use `<a id="x"></a>` here.\n\n```\n<a id="y"></a>\n```\n'
        self.assertEqual(compare_anchors(source, 'Use `code` here.\n\n```\nz\n```\n', inline=True), [])

    def test_reference_verifier_reports_anchor_loss(self):
        translated = SOURCE.replace('<a id="bib.bib1"></a>', '')
        fails, _warns = reference_verifier.verify(translated, SOURCE, [])
        self.assertTrue(any('来源锚点' in item for item in fails), fails)

    def test_translation_restructuring_between_anchors_passes(self):
        # 译文重排非锚点块（文首加管理/作者块、段间加块、段内拆段）不改变
        # 判定：绝对块序号漂移（V3 实测 337 vs 291 块）不影响核对
        restructured = ('> 管理字段\n\n> 作者块\n\n'
                        + SOURCE.replace('Text.', 'Te\n\nxt 补充。')
                        .replace('$$x=1$$', '$$x=1$$\n\n补充说明段。'))
        self.assertEqual(compare_anchors(SOURCE, restructured, inline=True), [])

    def test_anchor_moved_into_other_anchor_block_fails(self):
        # 并入他块：与前一锚点的共块关系翻转即失败（绝对块号之外仍守恒）
        merged = SOURCE.replace(
            '<a id="S1.E1"></a>(1)\n\n<a id="bib.bib1"></a>A (2020) Title.',
            '<a id="S1.E1"></a>(1)\n<a id="bib.bib1"></a>A (2020) Title.')
        problems = compare_anchors(SOURCE, merged, inline=True)
        self.assertTrue(problems)
        self.assertIn('来源锚点', problems[0])


if __name__ == '__main__':
    unittest.main()
