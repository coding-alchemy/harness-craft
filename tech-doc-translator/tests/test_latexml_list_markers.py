# coding: utf-8
"""第 2 批 R7：LaTeXML 无序列表的默认标记不进入正文，自定义标签保留。"""
import copy
import tempfile
import unittest
from pathlib import Path

from latexml_test_support import current_candidate, raw_document, reconcile_latexml_to_markdown


def item(label, text):
    return ('<li class="ltx_item"><span class="ltx_tag ltx_tag_item">%s</span>'
            '<div class="ltx_para"><p class="ltx_p">%s</p></div></li>' % (label, text))


RAW = raw_document(
    '<ul class="ltx_itemize">' + item('•', 'First point') + item('•', 'Second point')
    + '<li class="ltx_item"><span class="ltx_tag ltx_tag_item">•</span>'
      '<div class="ltx_para"><p class="ltx_p">Outer</p>'
      '<ul class="ltx_itemize">' + item('–', 'Inner point') + '</ul></div></li>'
    + '</ul>'
    + '<ul class="ltx_itemize">' + item('(a)', 'Custom label') + '</ul>')

# 有序列表条目内嵌无序列表：嵌套块经 enumerate_items 的无序分支
# （默认标记剥除）由写出与独立读取两侧共同消费。
RAW_NESTED = raw_document(
    '<ol class="ltx_enumerate">' + item('1.', 'First step')
    + '<li class="ltx_item"><span class="ltx_tag ltx_tag_item">2.</span>'
      '<div class="ltx_para"><p class="ltx_p">Second step</p>'
      '<ul class="ltx_itemize">' + item('•', 'Nested point') + '</ul></div></li>'
    + item('3.', 'Third step')
    + '</ol>')

# 重新解析前（R7 之前）写出的旧解析稿保留默认标记：顶层条目写成
# `- • 条目`；嵌套于有序列表条目内的子列表是独立缩进行 `   - – 条目`；
# 嵌套于无序列表条目内的子列表拼进父条目同一行（`- • 外层 – 内层`）。
# 对账按现行读法不一致时，按 R7 之前的读法（保留默认标记）整篇重比。
RAW_SECOND_LEVEL = raw_document(
    '<ol class="ltx_enumerate">' + item('1.', 'First step')
    + '<li class="ltx_item"><span class="ltx_tag ltx_tag_item">2.</span>'
      '<div class="ltx_para"><p class="ltx_p">Second step</p>'
      '<ul class="ltx_itemize">' + item('–', 'Nested point') + '</ul></div></li>'
    + item('3.', 'Third step')
    + '</ol>')


class ItemizeMarkerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='itemize-markers-')
        self.addCleanup(temp.cleanup)
        self.md, self.payload = current_candidate(Path(temp.name), RAW)

    def test_default_markers_are_not_written(self):
        self.assertNotIn('•', self.md)
        self.assertNotIn('–', self.md)
        self.assertRegex(self.md, r'(?m)^- +First point$')
        self.assertIn('Inner point', self.md)

    def test_custom_label_is_kept(self):
        self.assertIn('(a)', self.md)

    def test_independent_reading_agrees(self):
        self.assertEqual(reconcile_latexml_to_markdown(RAW, self.md, None, self.payload), [])

    def test_nested_itemize_inside_enumerate_strips_markers(self):
        temp = tempfile.TemporaryDirectory(prefix='itemize-markers-nested-')
        self.addCleanup(temp.cleanup)
        md, payload = current_candidate(Path(temp.name), RAW_NESTED)
        self.assertNotIn('•', md)
        self.assertIn('Nested point', md)
        self.assertRegex(md, r'(?m)^1\. +First step$')
        self.assertRegex(md, r'(?m)^2\. +Second step$')
        self.assertRegex(md, r'(?m)^3\. +Third step$')
        self.assertEqual(reconcile_latexml_to_markdown(RAW_NESTED, md, None, payload), [])

    def test_old_style_default_marker_prefix_tolerated(self):
        # 旧解析稿（重新解析前写出）保留 `- • 条目` 前缀；对账按现行读法
        # 不一致时以保留默认标记的旧读法整篇重比，整篇旧写法即通过。
        # 自定义标签 `(a)` 与新式无标记条目均不受影响。
        old_md = (self.md
                  .replace('- First point', '- • First point')
                  .replace('- Second point', '- • Second point')
                  .replace('- Outer Inner point', '- • Outer – Inner point'))
        self.assertIn('- • First point', old_md)
        self.assertEqual(
            reconcile_latexml_to_markdown(RAW, old_md, None, self.payload), [])
        self.assertEqual(
            reconcile_latexml_to_markdown(RAW, self.md, None, self.payload), [])

    def test_old_style_second_level_marker_tolerated(self):
        # 旧解析稿的第二层默认标记 `–` 位于嵌套缩进行的条目文字开头，
        # 同样被容忍；且不会误伤枚举条目本身（`1. First step` 不动）。
        # 依据按旧稿文本模拟（V1.5 在旧稿上记录范围）：插入标记后，越
        # 过插入点的声明范围平移标记宽度。
        temp = tempfile.TemporaryDirectory(prefix='itemize-markers-l2-')
        self.addCleanup(temp.cleanup)
        md, payload = current_candidate(Path(temp.name), RAW_SECOND_LEVEL)
        at = md.index('- Nested point') + len('- ')
        old_md = md[:at] + '– ' + md[at:]
        width = len('– ')
        shifted = copy.deepcopy(payload)
        for entry in shifted['correspondences']:
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get('md_start'), int) and entry['md_start'] >= at:
                entry['md_start'] += width
            if isinstance(entry.get('md_end'), int) and entry['md_end'] > at:
                entry['md_end'] += width
        self.assertIn('   - – Nested point', old_md)
        self.assertEqual(
            reconcile_latexml_to_markdown(RAW_SECOND_LEVEL, old_md, None,
                                          shifted), [])

    def test_old_style_draft_damage_still_rejected(self):
        # 旧解析稿按旧读法整篇比对：改动一个条目的文字仍报差异，且只报这一处。
        old_md = (self.md
                  .replace('- First point', '- • First paint')
                  .replace('- Second point', '- • Second point')
                  .replace('- Outer Inner point', '- • Outer – Inner point'))
        diffs = reconcile_latexml_to_markdown(RAW, old_md, None, self.payload)
        self.assertEqual(len(diffs), 1, diffs)
        self.assertIn('First paint', diffs[0])

    def test_mixed_marker_forms_rejected(self):
        # 一份解析稿要么整篇是现行写法，要么整篇是旧写法；新稿单个条目多出默认标记被拒。
        mixed = self.md.replace('- First point', '- • First point')
        self.assertTrue(reconcile_latexml_to_markdown(RAW, mixed, None, self.payload))


if __name__ == '__main__':
    unittest.main()
