"""标题/脚注/强 token 核验的固定语义验收（任务 04）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    compare_headings,
    footnote_diffs,
    heading_entries,
    heading_title_matches,
    strong_token_report,
)


class HeadingTitleMatchTest(unittest.TestCase):

    def test_exact_and_chinese_suffix(self):
        self.assertTrue(heading_title_matches('1. Foo Bar', '1. Foo Bar'))
        self.assertTrue(heading_title_matches(
            '1. Foo Bar', '1. Foo Bar（中文标题）'))

    def test_curly_quotes_are_content_characters(self):
        self.assertFalse(heading_title_matches(
            '1. it’s here', "1. it's here"))

    def test_no_blind_truncation_at_first_paren(self):
        # 源原题本身含全角括号：后缀必须在其之后
        self.assertTrue(heading_title_matches(
            '1. Foo（Bar）', '1. Foo（Bar）（巴）'))
        # 后缀之后还有内容：不匹配
        self.assertFalse(heading_title_matches(
            '1. Foo', '1. Foo（中文）以及多余内容'))

    def test_suffix_must_be_nonempty(self):
        self.assertFalse(heading_title_matches('1. Foo', '1. Foo（）'))


class HeadingEntriesTest(unittest.TestCase):

    def test_ordered_entries_exclude_fence_lines(self):
        text = '# T\n```c\n## fake\n```\n## Real（真实）\n'
        entries = heading_entries(text)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'Real（真实）')])

    def test_deep_h7_h8_headings_recognized(self):
        # 评审 P1-5：深层标题不截断到 H6；删除 H7/H8 必须被逐项对照检出
        text = '# T\n\n## A\n\n####### H7 七级\n\n######## H8 八级\n'
        entries = heading_entries(text)
        self.assertEqual([(lvl, t) for _, lvl, t in entries],
                         [(1, 'T'), (2, 'A'), (7, 'H7 七级'), (8, 'H8 八级')])
        doc = heading_entries('# T（T）\n\n## A（A）\n\n正文\n')
        diffs = compare_headings(entries, doc, 'src.md', 'doc.md')
        self.assertTrue(any('标题数不一致' in d for d in diffs))


class CompareHeadingsTest(unittest.TestCase):

    def test_level_change_reported(self):
        src = heading_entries('## A\n\ntext\n\n### A.1\n')
        doc = heading_entries('## A\n\ntext\n\n#### A.1\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('层级不一致' in d and 'H3' in d and 'H4' in d
                            for d in diffs))

    def test_title_change_reported(self):
        src = heading_entries('## A.1 Deep\n')
        doc = heading_entries('## A.1 Doeep（深）\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题 #1 不一致' in d and "'A.1 Deep'" in d
                            for d in diffs))

    def test_deleted_unnumbered_heading_reported(self):
        src = heading_entries('# T\n\n## 1. A\n\n### Intro\n\n## 2. B\n')
        doc = heading_entries('# T\n\n## 1. A\n\n## 2. B\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题数不一致' in d for d in diffs))

    def test_level_shift_and_header_skip_for_assembly(self):
        src = heading_entries('# 1. Foo\n\n## 1.1. Bar\n')
        doc = heading_entries('# 章节头\n\n## 1. Foo（福）\n\n### 1.1. Bar（巴）\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md',
                                 level_shift=1, doc_skip_head=1)
        self.assertEqual(diffs, [])

    def test_missing_heading_reported(self):
        src = heading_entries('# T\n\n## A\n\n## B\n')
        doc = heading_entries('# T\n\n## A\n')
        diffs = compare_headings(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('标题数不一致' in d and '多余' not in d for d in diffs))


class FootnoteDiffTest(unittest.TestCase):

    def test_pair_deletion_detected(self):
        src = '正文[^1]与[^2]。\n\n[^1]: 一\n[^2]: 二\n'
        doc = '正文[^1]。\n\n[^1]: 一\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('[^2]' in d for d in diffs))

    def test_ref_or_def_loss_detected(self):
        src = '正文[^1]。\n\n[^1]: 一\n'
        doc = '正文[^1]。\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertTrue(any('定义缺失' in d for d in diffs))

    def test_named_labels_supported(self):
        src = '正文[^note]。\n\n[^note]: 说明\n'
        doc = '正文[^note]。\n\n[^note]: 说明\n'
        diffs, _ = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertEqual(diffs, [])

    def test_extra_note_footnote_is_warning(self):
        src = '正文[^1]。\n\n[^1]: 一\n'
        doc = '正文[^1]。译注[^n1]。\n\n[^1]: 一\n[^n1]: 译注说明\n'
        diffs, warns = footnote_diffs(src, doc, 'a.md', 'b.md')
        self.assertEqual(diffs, [])
        self.assertTrue(any('[^n1]' in w for w in warns))


class StrongTokenTest(unittest.TestCase):

    def test_missing_token_fails(self):
        src = '调用 cublasSgemm 两次'
        doc = '调用 cublas'
        diffs, _ = strong_token_report(src, doc, ['cublasSgemm'], 'a', 'b')
        self.assertTrue(diffs and '1 处' in diffs[0])

    def test_word_boundary_no_false_positive(self):
        src = 'kernel 启动'
        doc = 'subkernel 内核'
        diffs, _ = strong_token_report(src, doc, ['kernel'], 'a', 'b')
        self.assertTrue(diffs)

    def test_unconfigured_reported_not_passed(self):
        diffs, warns = strong_token_report('a', 'b', [])
        self.assertIsNone(diffs)
        self.assertTrue(any('未配置' in w for w in warns))

    def test_increase_is_warning(self):
        diffs, warns = strong_token_report('a cublasSgemm', 'a cublasSgemm b cublasSgemm',
                                           ['cublasSgemm'], 'a', 'b')
        self.assertEqual(diffs, [])
        self.assertTrue(warns)


if __name__ == '__main__':
    unittest.main()
