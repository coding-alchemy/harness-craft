# coding: utf-8
"""格代码的真实相邻归属、阶段、拆包与无损可读转换。"""
import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _html_fidelity import HtmlFidelity
from _source_reconcile import (markdown_table_facts, table_code_problems,
    finalize_table_code, reconcile_html_to_markdown, compare_translation_tables)
import parse_api_html
import split_work_packages as split
from verify_translation import run_checks
import recover_work_packages as recovery
import merge_work_packages as merge

HTML = ('<article><h1>T</h1><table><tr><th>H</th><th>V</th></tr>'
        '<tr><td>A</td><td><pre>one();</pre><pre>two();</pre></td></tr></table>'
        '<table><tr><th>H</th><th>V</th></tr><tr><td>B</td><td><pre>three();</pre>'
        '</td></tr></table></article>')
TABLE = '| H | V |\n|---|---|\n| A | |\n'
GROUP = '\n[TABLE-CODE r=2 c=2#1]\n```c\none();\n```\n\n[TABLE-CODE r=2 c=2#2]\n```c\ntwo();\n```\n'


class TableCodeLifecycleTest(unittest.TestCase):
    def test_multiple_codes_and_adjacent_tables_reconcile(self):
        fidelity = HtmlFidelity()
        out = []
        parse_api_html.render(fidelity.parse(HTML).article, out, fidelity)
        md = '\n'.join(out).strip() + '\n'
        self.assertEqual(reconcile_html_to_markdown(HTML, md, 'api'), [])
        facts = markdown_table_facts(md)
        self.assertEqual(list(facts[0]['codes']), [(2, 2, 1), (2, 2, 2)])
        self.assertEqual(list(facts[1]['codes']), [(2, 2, 1)])
        self.assertEqual(facts[1]['codes'][(2, 2, 1)], 'three();')
        self.assertEqual(table_code_problems(md, 'source'), [])

    def test_finalization_preserves_cells_fences_and_literal_examples(self):
        source = TABLE + GROUP + '\nLiteral `[TABLE-CODE r=2 c=2#1]`.\n'
        result = finalize_table_code(source)
        self.assertIn('本表第 2 行、第 2 列的代码 2：', result)
        self.assertIn('`[TABLE-CODE r=2 c=2#1]`', result)
        self.assertEqual(compare_translation_tables(source, result, exact=True), [])
        self.assertEqual(table_code_problems(result), [])
        self.assertTrue(table_code_problems(source))
        self.assertTrue(compare_translation_tables(source,
            result.replace('本表第 2 行、第 2 列的代码 2：', ''), exact=True))

    def test_group_boundaries_duplicates_and_orphans_rejected(self):
        good = TABLE + GROUP
        for broken in (good.replace('#2]', '#1]'),
                       good.replace('r=2 c=2#2', 'r=8 c=2#2'),
                       good.replace('[TABLE-CODE r=2 c=2#2]',
                                    'Other paragraph.\n\n[TABLE-CODE r=2 c=2#2]'),
                       good.replace('```c\ntwo();\n```', 'Other paragraph.\n\n```c\ntwo();\n```'),
                       good + '\n```\nextra();\n```\n',
                       GROUP):
            with self.subTest(broken=broken):
                self.assertTrue(table_code_problems(broken, 'intermediate'))
                with self.assertRaises(ValueError):
                    finalize_table_code(broken)

    def test_phase_entry_points_and_no_silent_marker_deletion(self):
        source = '# T\n\n' + TABLE + GROUP
        kwargs = dict(doc_dir='/private/tmp', doc_label='doc', src_label='src', fragment=True)
        self.assertGreater(run_checks(source, source, **kwargs)[0], 0)
        self.assertEqual(run_checks(source, source, table_code_stage='intermediate', **kwargs)[0], 0)
        self.assertEqual(run_checks(finalize_table_code(source), source, **kwargs)[0], 0)
        broken = source.replace('[TABLE-CODE r=2 c=2#1]\n', '')
        self.assertGreater(run_checks(broken, source, table_code_stage='intermediate', **kwargs)[0], 0)
        self.assertTrue(recovery._fragment_hard_checks(source, source, '/private/tmp/doc', [], [])[0])
        self.assertEqual(recovery._fragment_hard_checks(source, source,
            '/private/tmp/doc', [], [], table_code_stage='intermediate')[0], [])

    def test_table_code_group_is_atomic_and_counts_real_fences(self):
        text = TABLE + GROUP
        blocks = split._parse_blocks(text.splitlines(), set())
        self.assertEqual([(b.kind, b.start, b.end) for b in blocks],
                         [('table', 0, len(text.splitlines()) - 1)])
        self.assertEqual(split._count_blocks(text)['tables'], 1)
        self.assertEqual(split._count_blocks(text)['code_fences'], 2)

    def test_current_intermediate_evidence_merges_without_overwriting_packages(self):
        with tempfile.TemporaryDirectory(prefix='table-code-chain-') as temporary:
            root = Path(temporary)
            source = root / 'source.md'
            source.write_text('# T\n\n' + TABLE + GROUP)
            packages = root / 'packages'
            targets = root / 'targets'
            split.split(str(source), str(packages), str(targets), 'chars:1')
            expected = recovery.expected_packages(str(source), 'chars:1', str(targets))
            self.assertEqual(len(expected), 1)
            package = expected[0]
            target = Path(package['target_file'])
            target.write_text(Path(packages / package['name']).read_text())
            _, body = recovery._frontmatter(target)
            facts = recovery.package_facts(package, body, str(target), str(source),
                                           code_stage='intermediate')
            facts['review'] = {'semantic': 'done', 'unresolved': []}
            evidence = root / 'evidence.json'
            evidence.write_text(json.dumps({package['name']: facts}))
            result = recovery.recover(str(source), str(packages), str(targets),
                'chars:1', str(evidence), code_stage='intermediate')
            self.assertEqual(len(result[0]), 1)
            self.assertFalse(recovery.recover(str(source), str(packages), str(targets),
                'chars:1', str(evidence))[0])
            original = target.read_bytes()
            output = root / 'final.md'
            merge.merge(str(output), [str(target)], str(source), 'chars:1',
                str(packages), str(evidence), finalize_code=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertIn('本表第 2 行、第 2 列的代码 2：', output.read_text())
            self.assertEqual(table_code_problems(output.read_text()), [])

    def test_pdf_and_delivery_do_not_accept_intermediate_stage(self):
        import export_pdf
        import verify_delivery
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'doc.md'
            target.write_text('# T\n\n' + TABLE + GROUP)
            with self.assertRaisesRegex(export_pdf.ExportError, 'TABLE-CODE'):
                export_pdf.parse_chapter(export_pdf.Chapter(1, target))
        problems = []
        self.assertIsNone(verify_delivery._parse_tool_args('verify_translation',
            ['doc.md', 'src.md', '--fragment', '--table-code-stage', 'intermediate'],
            problems, 1))
        self.assertTrue(any('交付禁止' in problem for problem in problems))


if __name__ == '__main__':
    unittest.main()
