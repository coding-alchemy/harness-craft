"""PDF 解析的固定组合验收；所有输入均在工作区外构造。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter
import verify_pdf as verifier


REAL_CHAPTER_HEAD = (
    '# CUDA Programming Guide 中文翻译 —— 第 1 章 Introduction to CUDA\n'
    '\n'
    '> **原文**：CUDA Programming Guide，版本 v13.3\n'
    '> **来源**：https://docs.nvidia.com/cuda/cuda-programming-guide/ \n'
    '>\n'
    '> **译例说明**：\n'
    '> - 本文档为第 1 章 *Introduction to CUDA* 的中文翻译；\n'
    '> - 术语译法遵循本项目 术语表.md；细节见 [术语表](术语表.md)；\n'
    '\n'
    '---\n'
    '\n'
    '# 1. Introduction to CUDA（CUDA 导论）\n'
    '\n'
    '正文提到 原文 与 译例说明 词汇，以及 `代码中的 译例说明`，必须保留。\n'
)

QUOTED_FENCE_HEAD = (
    '# 第 1 章 样例\n'
    '\n'
    '> **来源**：https://example.com\n'
    '>\n'
    '> **原文**：official text\n'
    '> 续行一\n'
    '>\n'
    '> ```python\n'
    '> **原文**：代码内的字面量\n'
    '> ```\n'
    '>\n'
    '> **译例说明**：example note\n'
    '>\n'
    '\n'
    '正文从这里开始。\n'
)

NESTED_FENCE_HEAD = (
    '# 第 1 章 样例\n'
    '\n'
    '> **来源**：https://example.com\n'
    '>\n'
    '> **原文**：official text\n'
    '>\n'
    '> ````md 示例\n'
    '> ```python\n'
    '> **原文**：嵌套示例里的字面量\n'
    '> ```\n'
    '> ````\n'
    '>\n'
    '> **译例说明**：example note\n'
    '>\n'
    '\n'
    '正文开始。\n'
)

# 收尾计划 H01–H12 固定用例：KEEP=必须保留，REMOVE=授权排除。
# 每项直接对照原 Markdown 语义；无目标字段的正向例要求投影后与输入
# 完全一致（identity），不以其余扫描器一致为成功。
HEAD_FIXED_CASES = [
    # (ID, 正文行, 期望: identity 或 [(label, start, end_inclusive)])
    ('H01', [
        '> ```',
        '> **原文**：KEEP',
        '> ```',
    ], 'identity'),
    ('H02', [
        '> **来源**：x',
        '>',
        '> ````md',
        '> ```python',
        '> **原文**：KEEP',
        '> ```',
        '> ````',
    ], 'identity'),
    ('H03', [
        '> **来源**：x',
        '>',
        '> ```',
        '> ~~~',
        '> **原文**：KEEP',
        '> ```',
    ], 'identity'),
    ('H04', [
        '> **来源**：x',
        '>',
        '> ```python',
        '> ``` trailing',
        '> **原文**：KEEP',
        '> ```',
    ], 'identity'),
    ('H05', [
        '> **来源**：x',
        '>',
        '> ~~~python',
        '> ~~~ trailing',
        '> **原文**：KEEP',
        '> ~~~',
    ], 'identity'),
    ('H06', [
        '    code line',
        '    > **原文**：KEEP',
    ], 'identity'),
    ('H07', [
        '> **来源**：x',
        '>',
        '>     code',
        '>     **原文**：KEEP',
    ], 'identity'),
    ('H08', [
        '> **来源**：x',
        '>',
        '> > ```',
        '> > **原文**：KEEP',
        '> > ```',
    ], 'identity'),
    ('H09', [
        '正文段落。',
        '',
        '> **原文**：技术引用块',
    ], 'identity'),
    ('H10', [
        '> **注（Note）**：这是一个技术提示。',
        '',
        '> **原文**：技术引用块',
    ], 'identity'),
    ('H11', [
        '> **原文**：official',
        'lazy continuation line',
        '',
        '正文。',
    ], [('原文', 3, 4)]),
    ('H12', [
        '> **原文**：CUDA v1',
        '> **来源**：https://example.com',
        '>',
        '> **译例说明**：',
        '> - 第一条说明',
        '> - 第二条说明',
        '',
        '正文开始。',
    ], [('原文', 3, 3), ('译例说明', 6, 8)]),
]


def head_case_text(lines):
    return '# T\n\n' + '\n'.join(lines) + '\n'


class ManagementFieldProjectionTests(unittest.TestCase):
    def test_real_head_mixed_quote_projection(self):
        projected, spans = exporter.project_management_fields(REAL_CHAPTER_HEAD)
        self.assertEqual(
            [(s['label'], s['start_line'], s['end_line']) for s in spans],
            [('原文', 3, 3), ('译例说明', 6, 8)],
        )
        self.assertIn('> **来源**', projected)
        self.assertNotIn('> **原文**', projected)
        self.assertNotIn('术语译法遵循本项目', projected)
        self.assertNotIn('[术语表](术语表.md)', projected)
        # 正文与代码中的同名文字不受影响。
        self.assertIn('正文提到 原文 与 译例说明 词汇', projected)
        self.assertIn('代码中的 译例说明', projected)

    def test_independent_scan_agrees_with_exporter(self):
        nested_quote = '\n'.join(
            ('> >' + line[1:]) if line.startswith('>') else line
            for line in NESTED_FENCE_HEAD.split('\n'))
        for text in (REAL_CHAPTER_HEAD, '# 标题\n\n正文。\n',
                     '# T\n\n```text\n> **原文**：围栏内\n```\n',
                     '# T\n\n正文。\n\n> **原文**：正文引用块保留\n',
                     QUOTED_FENCE_HEAD, NESTED_FENCE_HEAD, nested_quote):
            with self.subTest(text=text[:20]):
                projected, spans = exporter.project_management_fields(text)
                authorized = verifier.authorized_head_exclusions(text)
                records = [{'label': label, 'start_line': start + 1,
                            'end_line': end, 'reason': exporter.EXCLUSION_REASON}
                           for start, end, label in authorized]
                self.assertEqual(records, spans, text)
                self.assertEqual(
                    verifier.apply_authorized_spans(text, authorized), projected, text)

    def test_nested_quoted_fence_survives_head_projection(self):
        # H08 形态：管理字段之后的嵌套引用内含围栏与字段字面量。
        lines = NESTED_FENCE_HEAD.split('\n')
        nested = lines[:6] + ['> >' + line[1:] for line in lines[6:11]] + lines[11:]
        nested_quote = '\n'.join(nested)
        for text in (NESTED_FENCE_HEAD, nested_quote):
            with self.subTest(text=text.splitlines()[4][:12]):
                projected, spans = exporter.project_management_fields(text)
                # 外层四反引号中的三反引号示例是代码内容：内部字段字面量
                # 与全部围栏行都不删。
                fences = [line for line in projected.split('\n')
                          if '```' in line]
                self.assertEqual(len(fences), 4, fences)
                self.assertIn('嵌套示例里的字面量', projected)
                self.assertNotIn('official text', projected)
                self.assertNotIn('example note', projected)
                self.assertEqual(
                    [(s['label'], s['start_line'], s['end_line']) for s in spans],
                    [('原文', 5, 5), ('译例说明', 13, 13)],
                )

    def test_quoted_code_fence_survives_head_projection(self):
        projected, spans = exporter.project_management_fields(QUOTED_FENCE_HEAD)
        # 引用块内的代码围栏是技术内容：围栏内的字段字面量与闭合围栏都不删。
        self.assertEqual(projected.count('```'), 2, projected)
        self.assertIn('**原文**：代码内的字面量', projected)
        # 围栏之外的管理字段仍按规则排除。
        self.assertNotIn('official text', projected)
        self.assertNotIn('example note', projected)
        self.assertEqual(
            [(s['label'], s['start_line'], s['end_line']) for s in spans],
            [('原文', 5, 6), ('译例说明', 12, 12)],
        )

    def test_fields_after_first_body_paragraph_survive(self):
        text = '# 标题\n\n正文首段。\n\n> **原文**：正文引用块\n> **译例说明**：保留\n'
        self.assertEqual(exporter.project_management_fields(text), (text, []))

    def test_fixed_head_cases(self):
        for case_id, lines, expected in HEAD_FIXED_CASES:
            with self.subTest(case=case_id):
                text = head_case_text(lines)
                projected, spans = exporter.project_management_fields(text)
                authorized = verifier.authorized_head_exclusions(text)
                records = [{'label': label, 'start_line': start + 1,
                            'end_line': end, 'reason': exporter.EXCLUSION_REASON}
                           for start, end, label in authorized]
                # 两侧独立实现必须一致，且与人工标定预期一致。
                self.assertEqual(
                    records, spans, '%s 两侧扫描不一致\n%s' % (case_id, text))
                if expected == 'identity':
                    self.assertEqual(
                        (projected, spans), (text, []),
                        '%s 应保持原样\n投影结果：%r' % (case_id, projected))
                    if 'KEEP' in text:
                        self.assertIn('KEEP', projected, case_id)
                else:
                    self.assertEqual(
                        [(s['label'], s['start_line'], s['end_line'])
                         for s in spans],
                        expected, '%s 排除区间不符\n%s' % (case_id, text))
                    self.assertEqual(
                        verifier.apply_authorized_spans(text, authorized),
                        projected, case_id)

    def test_no_target_field_keeps_original_path(self):
        text = '# 标题\n\n> **来源**：https://example.com\n\n正文。\n'
        self.assertEqual(exporter.project_management_fields(text), (text, []))


A_CHAPTER = (
    '# 1. 简介\n'
    '\n'
    'A 章正文。\n'
    '\n'
    '<a id="basic"></a>\n'
    '\n'
    '## 1.1. 基础\n'
    '\n'
    '基础正文。\n'
    '\n'
    '### 1.1.1. 深层\n'
    '\n'
    '深层正文。\n'
)

B_CHAPTER = '# 2. 进阶\n\nB 章正文。\n'


class TocNavigationTests(unittest.TestCase):
    """收尾计划 T01–T16 固定目录用例（逻辑层；PDF 级验证见阶段 02）。"""

    def build(self, toc_body, include_b=True, order=('a.md', 'b.md')):
        temporary = tempfile.mkdtemp(prefix='pdf-toc-fixed-')
        self.addCleanup(lambda: __import__('shutil').rmtree(temporary, True))
        base = Path(temporary)
        (base / 'a.md').write_text(A_CHAPTER, encoding='utf-8')
        if include_b:
            (base / 'b.md').write_text(B_CHAPTER, encoding='utf-8')
        (base / '00_目录.md').write_text(toc_body, encoding='utf-8')
        names = ['00_目录.md'] + list(order)
        chapters = [exporter.Chapter(number, (base / name).resolve())
                    for number, name in enumerate(names, start=1)]
        for chapter in chapters:
            exporter.parse_chapter(chapter)
        return chapters

    def entries(self, chapters, sections=False):
        diagnostics = []
        entries, _out = exporter.build_print_toc(
            chapters[0], chapters, diagnostics, sections)
        return entries, diagnostics

    def soup_text(self, chapters):
        return chapters[0].soup.get_text(' ', strip=True)

    def test_T01_plain_chapter_link_collapses_section_link(self):
        chapters = self.build('- [a 章](a.md)\n  - [基础](a.md#11-基础)\n')
        entries, diagnostics = self.entries(chapters)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介')])
        self.assertEqual([d['severity'] for d in diagnostics], [])

    def test_T02_sections_adds_h2_once(self):
        chapters = self.build('- [a 章](a.md)\n  - [基础](a.md#11-基础)\n')
        entries, diagnostics = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])

    def test_T03_h1_fragment_does_not_duplicate_chapter(self):
        chapters = self.build(
            '- [a 章](a.md#1-简介)\n  - [基础](a.md#11-基础)\n')
        entries, _ = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])

    def test_T04_h3_fragment_stays_out_of_sections(self):
        chapters = self.build(
            '- [a 章](a.md)\n'
            '  - [基础](a.md#11-基础)\n'
            '  - [深层](a.md#111-深层)\n')
        entries, _ = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])

    def test_T05_percent_encoded_fragment_resolves(self):
        chapters = self.build('- [基础](a.md#11-%E5%9F%BA%E7%A1%80)\n')
        entries, _ = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])
        self.assertTrue(
            all(e['target'].startswith('ch02-') for e in entries))

    def test_T06_unresolvable_anchor_fragment_blocks(self):
        chapters = self.build('- [基础](a.md#basic)\n')
        diagnostics = []
        try:
            exporter.build_print_toc(chapters[0], chapters, diagnostics, True)
        except exporter.TocError:
            self.fail('T06 应以诊断阻断，不应静默失败')
        codes = [(d['severity'], d['code']) for d in diagnostics]
        self.assertIn(('fail', 'toc-anchor-unassociated'), codes, codes)
        # 默认章级模式目标可解析，按章折叠不阻断。
        diagnostics_default = []
        entries, _ = exporter.build_print_toc(
            chapters[0], chapters, diagnostics_default, False)
        self.assertEqual([e['level'] for e in entries], [1])
        self.assertEqual(diagnostics_default, [])

    def test_T07_reference_links_match_inline(self):
        chapters = self.build(
            '- [简介][chapter]\n  - [基础][section]\n\n'
            '[chapter]: a.md\n[section]: a.md#11-基础\n')
        entries, _ = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])

    def test_T09_mixed_notes_list_keeps_note(self):
        chapters = self.build(
            '- [a 章](a.md)\n\n补充说明：\n\n- 简介\n- 此章的示例需要 Python 3.11\n')
        entries, _ = self.entries(chapters)
        self.assertEqual([e['level'] for e in entries], [1])
        text = self.soup_text(chapters)
        self.assertIn('此章的示例需要 Python 3.11', text)

    def test_T10_note_inside_nav_li_survives(self):
        chapters = self.build(
            '- [简介](a.md)\n\n  此章的示例需要 Python 3.11\n')
        entries, _ = self.entries(chapters)
        self.assertEqual([e['level'] for e in entries], [1])
        text = self.soup_text(chapters)
        self.assertIn('此章的示例需要 Python 3.11', text)
        self.assertIsNone(chapters[0].soup.find('a', href='a.md'))

    def test_T11_note_cell_in_nav_row_survives(self):
        chapters = self.build(
            '| 章 | 链接 | 说明 |\n|---|---|---|\n'
            '| 1 | [简介](a.md) | 此章的示例需要 Python 3.11 |\n')
        entries, _ = self.entries(chapters)
        self.assertEqual([e['level'] for e in entries], [1])
        text = self.soup_text(chapters)
        self.assertIn('此章的示例需要 Python 3.11', text)
        self.assertIsNone(chapters[0].soup.find('a', href='a.md'))

    def test_T12_missing_fragment_blocks_default(self):
        chapters = self.build('- [a 章](a.md)\n  - [丢失](a.md#missing)\n')
        diagnostics = []
        exporter.build_print_toc(chapters[0], chapters, diagnostics, False)
        codes = [(d['severity'], d['code']) for d in diagnostics]
        self.assertIn(('fail', 'toc-fragment-unresolved'), codes, codes)

    def test_T13_missing_fragment_blocks_sections(self):
        chapters = self.build('- [a 章](a.md)\n  - [丢失](a.md#missing)\n')
        diagnostics = []
        exporter.build_print_toc(chapters[0], chapters, diagnostics, True)
        codes = [(d['severity'], d['code']) for d in diagnostics]
        self.assertIn(('fail', 'toc-fragment-unresolved'), codes, codes)

    def test_T14_duplicate_targets_appear_once(self):
        chapters = self.build(
            '- [a 章](a.md)\n- [再链 a](a.md)\n'
            '- [基础](a.md#11-基础)\n- [再链基础](a.md#11-基础)\n')
        entries, _ = self.entries(chapters, sections=True)
        self.assertEqual([(e['level'], e['title']) for e in entries],
                         [(1, '1. 简介'), (2, '1.1. 基础')])

    def test_T15_document_order_overrides_filename(self):
        chapters = self.build('- [b 章](b.md)\n- [a 章](a.md)\n',
                              order=('b.md', 'a.md'))
        entries, _ = self.entries(chapters)
        self.assertEqual([e['title'] for e in entries], ['2. 进阶', '1. 简介'])

    def test_T16_partial_export_keeps_only_volume(self):
        chapters = self.build('- [a 章](a.md)\n- [b 章](b.md)\n',
                              include_b=False, order=('a.md',))
        entries, out_links = exporter.build_print_toc(
            chapters[0], chapters, [], False)
        self.assertEqual([e['title'] for e in entries], ['1. 简介'])
        self.assertTrue(any('b.md' in item['href'] for item in out_links),
                        out_links)
        # 分篇：范围外章的纯导航行随消费移除，不残留在印刷目录正文里。
        text = self.soup_text(chapters)
        self.assertNotIn('b 章', text)
        # 核验器独立消费作出同一判定：范围外行进入目录页断言的清单。
        mirror = self.build('- [a 章](a.md)\n- [b 章](b.md)\n',
                            include_b=False, order=('a.md',))
        mirror_failures = []
        self.assertTrue(verifier.consume_toc_navigation(
            mirror[0], mirror, mirror_failures, False))
        excluded = mirror[0].excluded_nav_texts
        self.assertTrue(any('b 章' in item for item in excluded), excluded)

    def test_verifier_derive_matches_exporter_entries(self):
        """核验器独立预期与导出条目、固定预期三方一致；坏目标独立阻断。"""
        cases = (
            ('T01', '- [a 章](a.md)\n  - [基础](a.md#11-基础)\n', False,
             [(1, '1. 简介')]),
            ('T02', '- [a 章](a.md)\n  - [基础](a.md#11-基础)\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
            ('T03', '- [a 章](a.md#1-简介)\n  - [基础](a.md#11-基础)\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
            ('T04', '- [a 章](a.md)\n  - [基础](a.md#11-基础)\n'
             '  - [深层](a.md#111-深层)\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
            ('T05', '- [基础](a.md#11-%E5%9F%BA%E7%A1%80)\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
            ('T07', '- [简介][chapter]\n  - [基础][section]\n\n'
             '[chapter]: a.md\n[section]: a.md#11-基础\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
            ('T14', '- [a 章](a.md)\n- [再链 a](a.md)\n'
             '- [基础](a.md#11-基础)\n- [再链基础](a.md#11-基础)\n', True,
             [(1, '1. 简介'), (2, '1.1. 基础')]),
        )
        for case_id, body, sections, expected in cases:
            with self.subTest(case=case_id):
                chapters = self.build(body)
                produced, _diagnostics = self.entries(chapters, sections)
                failures = []
                derived = verifier.derive_toc_expectations(
                    chapters, sections, failures)
                self.assertEqual(
                    [(e['level'], e['title']) for e in produced], expected)
                self.assertEqual(
                    [(e['level'], e['title']) for e in derived], expected)
                self.assertEqual(failures, [])
        chapters = self.build('- [a 章](a.md)\n  - [丢失](a.md#missing)\n')
        failures = []
        verifier.derive_toc_expectations(chapters, False, failures)
        self.assertTrue(
            any(f['code'] == 'toc-fragment-unresolved' for f in failures),
            failures)
        failures = []
        chapters = self.build('- [基础](a.md#basic)\n')
        verifier.derive_toc_expectations(chapters, True, failures)
        self.assertTrue(
            any(f['code'] == 'toc-anchor-unassociated' for f in failures),
            failures)


class MarkdownStructureTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory(prefix='pdf-structure-') as temporary:
            path = Path(temporary) / 'chapter.md'
            path.write_text(text, encoding='utf-8')
            chapter = exporter.Chapter(1, path)
            exporter.parse_chapter(chapter)
            return chapter

    def test_heading_uses_chapter_reference_and_footnote_context(self):
        for level in (1, 6, 7, 8):
            with self.subTest(level=level):
                chapter = self.parse('#' * level + ' Use [docs][r] and `foo` $x^2$[^n]\n\n'
                                     '[r]: https://example.com/docs\n\n[^n]: Required note.\n')
                self.assertIsNotNone(chapter.soup.find('a', href='https://example.com/docs'))
                self.assertIn('Required note.', chapter.soup.get_text())
                self.assertEqual([m['latex'] for m in chapter.math], ['x^2'])
                self.assertEqual(chapter.soup.code.get_text(), 'foo')

    def test_explicit_anchor_inside_heading_and_code(self):
        for level in (1, 7, 8):
            with self.subTest(level=level):
                chapter = self.parse('#' * level + ' <a id="custom"></a>Title\n\n'
                                     '[go](#custom)\n\n`<a id="literal"></a>`\n')
                self.assertIsNotNone(chapter.soup.find(id='ch01-custom'))
                self.assertEqual(chapter.soup.code.get_text(), '<a id="literal"></a>')
                self.assertNotIn('PLACEHOLDER', chapter.soup.get_text())

    def test_code_boundaries_and_adjacent_headings(self):
        cases = [
            'Example: `begin\n####### literal\nend`',
            'Example: \\`ignored `begin\n####### literal\nend`',
            '````markdown\n```html\n<a id="sample"></a>\n####### literal\n```\n````',
        ]
        for case in cases:
            with self.subTest(case=case):
                chapter = self.parse('# A\n\n' + case + '\n\n####### B\n######## C\nTail\n')
                self.assertEqual([h['text'] for h in chapter.headings], ['A', 'B', 'C'])
                self.assertIn('####### literal', chapter.soup.get_text())
                self.assertIn('Tail', chapter.soup.get_text())

    def test_inline_title_spaces_and_code_blank_lines_survive(self):
        chapter = self.parse('# Use `foo` now\n\n[go](#use-foo-now)\n\n'
                             '```python\n\nprint(1)\n\n```\n')
        self.assertEqual(chapter.headings[0]['slug'], 'use-foo-now')
        self.assertEqual(chapter.soup.pre.get_text(), '\nprint(1)\n\n')

    def test_anchor_identity_does_not_depend_on_decimal_prefix(self):
        chapter = self.parse('# A\n\n' + '\n\n'.join(
            '<a id="a%d"></a> Text %d' % (i, i) for i in range(12)))
        self.assertEqual([a['id'] for a in chapter.soup.find_all('a')],
                         ['ch01-a%d' % i for i in range(12)])


if __name__ == '__main__':
    unittest.main()
