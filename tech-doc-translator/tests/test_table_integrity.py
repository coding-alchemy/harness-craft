"""简单表格位、确定性表示转换及拆包原子性。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _source_reconcile import markdown_table_facts, compare_translation_tables
from verify_translation import run_checks
from _verification import SourceMathContext
import split_work_packages as split


class TableIntegrityTest(unittest.TestCase):
    SOURCE = '[TABLE]\nName | Value\n--- | ---\nfirst | `a`\nsecond | $x := y$\n'
    DOC = '| 名称 | 数值 |\n| --- | --- |\n| 第一 | `a` |\n| 第二 | $x := y$ |\n'

    def test_valid_translation_and_damaged_grid(self):
        self.assertEqual(compare_translation_tables(self.SOURCE, self.DOC), [])
        for damaged in (
            self.DOC.replace('| 第一 | `a` |\n', ''),
            self.DOC.replace('| 第一', '<a id="fake"></a>\n| 第一'),
            self.DOC.replace('| 第一 | `a` |', '| `a` | 第一 |'),
            self.DOC.replace('x := y', 'x = y'),
        ):
            with self.subTest(damaged=damaged):
                count, lines = run_checks(damaged, self.SOURCE, fragment=True,
                    doc_dir='/private/tmp', doc_label='doc.md', src_label='source.md')
                self.assertGreater(count, 0, lines)
                self.assertTrue(any('表格核对:' in line for line in lines))

    def test_exact_conversion_rejects_equal_size_text_change(self):
        doc = self.DOC.replace('`a`', '甲').replace('$x := y$', '乙')
        self.assertEqual(compare_translation_tables(doc, doc, exact=True), [])
        for damaged in (doc.replace('甲', '丙'), doc.replace('甲','TEMP').replace('乙','甲').replace('TEMP','乙')):
            self.assertTrue(compare_translation_tables(doc, damaged, exact=True))

    def test_exact_conversion_rejects_caption_rebinding(self):
        src = '表 1：第一张表\n\n' + self.DOC + '\n表 2：第二张表\n\n' + self.DOC
        changed = src.replace('表 1', 'TMP').replace('表 2', '表 1').replace('TMP', '表 2')
        self.assertTrue(compare_translation_tables(src, changed, exact=True))
        src = '**表 41. 标注汇总（Table 41 Annotation Summary）** [#](#id24)\n\n' + self.DOC
        self.assertTrue(compare_translation_tables(
            src, src.replace('Annotation', 'Changed'), exact=True))

    def test_source_gfm_and_code_example_counts(self):
        text = self.SOURCE + '\n' + self.DOC + '\n```\n' + self.DOC + '\n```\n'
        self.assertEqual(len(markdown_table_facts(text)), 2)
        self.assertEqual(split._count_blocks(text.splitlines())['tables'], 2)
        bare = 'A | B\n--- | ---\n1 | 2\n'
        self.assertEqual(split._count_blocks(bare.splitlines())['tables'], 1)
        self.assertEqual(len(markdown_table_facts('| not a table\n')), 0)

    def test_table_forms_are_atomic_blocks(self):
        for table in (self.SOURCE, self.DOC, 'A | B\n--- | ---\n1 | 2\n'):
            blocks = split._parse_blocks(table.splitlines(), set())
            self.assertEqual([(b.kind,b.start,b.end) for b in blocks],
                             [('table',0,len(table.splitlines())-1)])

    def test_confirmed_multiline_math_representation(self):
        source = '[TABLE]\nName | Value\n--- | ---\n$x\n+y$ | Text\n'
        doc = '| Name | Value |\n|---|---|\n| $x&#10;+y$ | 正文 |\n'
        context = SourceMathContext([('x\n+y', None)])
        self.assertEqual(compare_translation_tables(
            source, doc, source_context=context), [])
        self.assertTrue(compare_translation_tables(
            source, doc.replace('+y', '+z'), source_context=context))

    def test_image_paths_follow_existing_identity_gate(self):
        source = '| H | Image |\n|---|---|\n| A | ![src](source/a.png) |\n'
        doc = source.replace('source/a.png', 'images/a.png')
        self.assertEqual(compare_translation_tables(source, doc), [])
        self.assertTrue(compare_translation_tables(
            source, doc.replace('![src](images/a.png)', '')))

    def test_grid_secondary_header_roles_survive_translation_and_exact_conversion(self):
        source = ('| Feature | Group | Group |\n|---|---|---|\n'
                  '| **Feature** | **Min** | **Max** |\n| value | 1 | 2 |\n')
        translated = source.replace('Feature', '特性').replace('Group', '分组').replace(
            'Min', '最小').replace('Max', '最大').replace('value', '数值')
        self.assertEqual(compare_translation_tables(source, translated), [])
        damaged = translated.replace('**最小**', '最小')
        from _source_reconcile import _SourceFacts, _mapped_table_headers
        raw = '<article><table><tr><th>Feature</th><th>Group</th><th>Group</th></tr>' \
              '<tr><th>Feature</th><th>Min</th><th>Max</th></tr><tr><td>value</td><td>1</td><td>2</td></tr></table></article>'
        mapping = {'version': 2, 'tables': [{'locate': {'table': 1}, 'cells': [
            {'row': r, 'col': c, 'targets': [{'table': 1, 'row': r, 'col': c}]}
            for r in (1, 2, 3) for c in (1, 2, 3)]}]}
        headers = _mapped_table_headers(_SourceFacts(raw, 'api', None), mapping)
        self.assertTrue(compare_translation_tables(source, damaged, header_cells=headers))
        self.assertTrue(compare_translation_tables(translated, damaged, exact=True, header_cells=headers))
        count, lines = run_checks(damaged, source, fragment=True,
            doc_dir='/private/tmp', doc_label='doc.md', src_label='source.md', header_cells=headers)
        self.assertGreater(count, 0, lines)
        self.assertTrue(any('表格核对:' in line for line in lines))

    def test_prose_and_partial_cell_emphasis_are_not_header_roles(self):
        source = '**Prose**\n\n| H | Text |\n|---|---|\n| x | Part **emphasis** here |\n'
        translated = '正文\n\n| 标题 | 文字 |\n|---|---|\n| x | 此处的局部强调 |\n'
        self.assertEqual(compare_translation_tables(source, translated), [])
        self.assertEqual(compare_translation_tables(source, source.replace('**', ''), exact=True), [])
        separate = source.replace('Part **emphasis** here', '**First** vs **Second**')
        self.assertEqual(compare_translation_tables(separate, separate.replace('**', ''), exact=True), [])


if __name__ == '__main__':
    unittest.main()
