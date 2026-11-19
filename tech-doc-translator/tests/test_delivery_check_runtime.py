"""第 2 批 R15：对账只解析一次输出表格；取检查事实不做全站准入；进度阶段。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
import _source_reconcile as sr
from test_grid_tables import HTML


class TableRecordsOnceTest(unittest.TestCase):
    """v2 网格映射：逐格核对时不再每格重新解析整份 Markdown 的表格。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='table-records-once-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        html, md, mapping = root / 'page.html', root / 'source.md', root / 'tables.json'
        html.write_text(HTML)
        run = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_api_html.py'), str(html), str(md),
             '--expand-tables', 'grid', '--table-conversions-output', str(mapping)],
            capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.md = md.read_text()
        self.mapping = json.loads(mapping.read_text())

    def test_conversion_map_diffs_parses_output_tables_once(self):
        original_records = sr._MarkdownFacts.table_records
        original_diffs = sr._conversion_map_diffs
        inside, counts = [False], []

        def counting_records(facts):
            if inside[0]:
                counts[-1] += 1
            return original_records(facts)

        def tracking_diffs(*args, **kwargs):
            inside[0] = True
            counts.append(0)
            try:
                return original_diffs(*args, **kwargs)
            finally:
                inside[0] = False

        with patch.object(sr._MarkdownFacts, 'table_records', counting_records), \
                patch.object(sr, '_conversion_map_diffs', tracking_diffs):
            diffs = sr.reconcile_html_to_markdown(
                HTML, self.md, 'api', table_conversions=self.mapping)
        self.assertEqual(diffs, [])
        self.assertTrue(counts)
        self.assertEqual(counts, [1] * len(counts))

    def test_damaged_grid_header_still_rejected(self):
        damaged = self.md.replace('**Max**', '**Mix**', 1)
        self.assertNotEqual(damaged, self.md)
        self.assertNotEqual(
            sr.reconcile_html_to_markdown(HTML, damaged, 'api', table_conversions=self.mapping), [])


from test_api_navigation import ApiNavigationFixture
import _api_navigation as nav
import verify_delivery as delivery


class NavigationFactsTest(ApiNavigationFixture, unittest.TestCase):
    def test_facts_match_admission_without_site_reconcile(self):
        record = self.root / 'record.json'
        expected_pages = nav.load_navigation(record, self.root)
        expected_deps = nav.navigation_dependencies(record)
        with patch.object(delivery, 'run_source_reconcile',
                          side_effect=AssertionError('取事实时不应做全站对账')):
            facts = nav.navigation_facts(record, self.root)
        self.assertEqual(facts['record'], str(record.resolve()))
        self.assertEqual(facts['site_root'], str(self.root.resolve()))
        self.assertEqual(facts['dependencies'], expected_deps)
        self.assertEqual(set(facts['pages']), set(expected_pages))
        for page, info in facts['pages'].items():
            self.assertEqual(info['chapter'], expected_pages[page]['chapter'])
            self.assertEqual(info['role_source'], expected_pages[page]['role_source'])

    def test_snapshot_outside_site_root_rejected(self):
        with self.assertRaisesRegex(ValueError, 'site_root'):
            nav.navigation_facts(self.root / 'record.json', self.root / 'elsewhere')


class CheckFactsNavigationTest(ApiNavigationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.merge()
        self.args = [str(self.root / '01_AB.md'), str(self.root / 'ab.txt'),
                     str(self.root / 'ab.txt'), str(self.root),
                     str(self.root / 'a.md'), str(self.root / 'b.md'),
                     '--navigation-record', str(self.root / 'record.json')]

    def test_check_facts_skip_site_reconcile_and_keep_binding_facts(self):
        record = self.root / 'record.json'
        pages = nav.load_navigation(record, self.root)
        deps = nav.navigation_dependencies(record)
        record_path = str(record.resolve())
        with patch.object(delivery, 'run_source_reconcile',
                          side_effect=AssertionError('取事实时不应做全站对账')):
            facts, _ = delivery._check_facts(
                str(self.root), 'verify_api_translation', self.args, 1)
        self.assertTrue(delivery._facts_complete(facts))
        self.assertEqual(facts['files']['navigation_record'],
                         next(item for item in deps if item[0] == record_path))
        self.assertEqual(facts['files']['navigation_sources'],
                         [item for item in deps if item[0] != record_path])
        self.assertEqual(facts['params']['table_role_sources'],
                         [pages[page]['role_source'] for page in ('a.html', 'b.html')])

    def test_one_navigation_computation_per_identity_call(self):
        self.record['checks'] = [{'tool': 'verify_api_translation', 'args': self.args},
                                 {'tool': 'verify_api_translation', 'args': list(self.args)}]
        with patch.object(nav, 'navigation_facts', wraps=nav.navigation_facts) as call:
            delivery.compute_delivery_identity(str(self.root), self.record, [])
        self.assertEqual(call.call_count, 1)

    def test_distinct_navigation_records_are_not_shared(self):
        second = self.root / 'record2.json'
        second.write_bytes((self.root / 'record.json').read_bytes())
        other = list(self.args)
        other[-1] = str(second)
        self.record['checks'] = [{'tool': 'verify_api_translation', 'args': self.args},
                                 {'tool': 'verify_api_translation', 'args': other}]
        with patch.object(nav, 'navigation_facts', wraps=nav.navigation_facts) as call:
            identity = delivery.compute_delivery_identity(str(self.root), self.record, [])
        self.assertEqual(call.call_count, 2)
        first, later = (check['facts'] for check in identity['checks'])
        self.assertEqual(first['files']['navigation_record'][0],
                         str((self.root / 'record.json').resolve()))
        self.assertEqual(later['files']['navigation_record'][0],
                         str(second.resolve()))


class ProgressStageTest(ApiNavigationFixture, unittest.TestCase):
    def test_identity_and_check_facts_stages_are_reported(self):
        self.merge()
        args = [str(self.root / '01_AB.md'), str(self.root / 'ab.txt'),
                str(self.root / 'ab.txt'), str(self.root),
                str(self.root / 'a.md'), str(self.root / 'b.md'),
                '--navigation-record', str(self.root / 'record.json')]
        self.record['checks'] = [{'tool': 'verify_api_translation', 'args': args}]
        events = []
        context = delivery.new_run_context(events.append)
        delivery.check_translation_readiness(
            str(self.root), self.record,
            [str(self.root / '01_AB.md'), str(self.root / '02_C.md')], run_context=context)
        seen = {(event['stage'], event['event']) for event in events}
        self.assertIn(('identity', 'start'), seen)
        self.assertIn(('identity', 'end'), seen)
        self.assertIn(('check-facts', 'start'), seen)


if __name__ == '__main__':
    unittest.main()
