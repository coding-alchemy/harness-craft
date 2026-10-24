"""Source-proven v2 th roles; v1 and td emphasis remain ordinary formatting."""
import hashlib
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
import recover_work_packages as rwp
import verify_delivery as delivery
from _source_reconcile import compare_translation_tables


def project_context(root, source, snapshots):
    record = {'version': 1, 'mode': 'translation', 'delivery_root': str(root),
        'inputs': ['final.md'], 'outputs': [], 'checks': [], 'reviews': [],
        'sources': [{'family': 'api', 'source_version': 'fixture',
        'parsed_markdown': str(source.relative_to(root)), 'snapshots': snapshots, 'covers': ['final.md']}]}
    (root / 'record.json').write_text(json.dumps(record))
    problems = []
    entries = delivery.check_source_chains(root, record, problems, source_only=True)
    delivery.run_source_reconcile(root, record, entries, problems)
    if problems:
        raise AssertionError(problems)
    entry = entries[0]
    context = {'project_root': str(root), 'source_record': 'record.json', 'source_scope': 'all',
        'skill_dir': str(SCRIPTS.parent), 'python': sys.executable,
        'source_review': {'scope': 'all', 'basis': 'Controlled original DOM and declared mapping.',
                         'binding': {k: entry[k] for k in ('parsed_sha256', 'source_version', 'snapshots')}}}
    path = root / 'context.json'
    path.write_text(json.dumps(context))
    return path


class HeaderRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='table-header-origin-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_tool(self, tool, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / tool), *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def grid(self, name='page'):
        snapshot = self.root / (name + '.html')
        snapshot.write_text('<article><h1>T</h1><table><tr><th rowspan="2">Name</th>'
            '<th>Description</th></tr><tr><td><strong>Important</strong></td></tr>'
            '<tr><td>x</td><td>value</td></tr></table></article>')
        source = self.root / (name + '.md')
        mapping = self.root / (name + '.json')
        self.run_tool('parse_api_html.py', snapshot, source, '--expand-tables', 'grid',
                      '--table-conversions-output', mapping)
        source.write_text(source.read_text().replace('| Important |', '| **Important** |'))
        return source, {'snapshot': snapshot.name, 'table_conversions': mapping.name}

    def test_v1_td_strong_allows_plain_translation_with_and_without_context(self):
        raw = '<article><h1>T</h1><table><tr><th>Name</th><th>Description</th></tr>' \
              '<tr><td>x</td><td><strong>Important</strong></td></tr></table></article>'
        (self.root / 'page.html').write_text(raw)
        source = self.root / 'source.md'
        source.write_text('# T\n\n| Name | Description |\n|---|---|\n| x | **Important** |\n')
        mapping = {'version': 1, 'snapshot_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'tables': [{'locate': {'table': 1}, 'cells': [
                {'row': r, 'col': c, 'targets': [{'table': 1, 'row': r, 'col': c}]}
                for r in (1, 2) for c in (1, 2)]}]}
        (self.root / 'tables.json').write_text(json.dumps(mapping))
        ctx = project_context(self.root, source, [{'snapshot': 'page.html', 'table_conversions': 'tables.json'}])
        healthy = source.read_text().replace('**Important**', '重要')
        translated = self.root / 'translated.md'; translated.write_text(healthy)
        self.assertEqual(compare_translation_tables(source.read_text(), healthy), [])
        self.assertEqual(compare_translation_tables(source.read_text(), source.read_text().replace('**', ''), exact=True), [])
        for options in [[], ['--project-context', ctx]]:
            self.run_tool('verify_translation.py', translated, source, '--fragment', *options)
        record = json.loads((self.root / 'record.json').read_text())
        (self.root / 'final.md').write_text(healthy)
        record['checks'] = [{'tool': 'verify_translation', 'args': ['final.md', source.name]}]
        self.assertEqual(self.delivery_chain(record), [])

    def test_v2_td_is_not_th_and_th_loss_is_rejected_with_source_proof(self):
        source, snapshot = self.grid()
        ctx = project_context(self.root, source, [snapshot])
        current = rwp.load_project_context(ctx, source)
        headers = rwp.table_headers(current)
        self.assertEqual(headers, {(1, 2, 1)})
        healthy = source.read_text().replace('**Important**', '重要')
        translated = self.root / 'translated.md'; translated.write_text(healthy)
        self.assertEqual(compare_translation_tables(source.read_text(), healthy, header_cells=headers), [])
        self.run_tool('verify_translation.py', translated, source, '--fragment', '--project-context', ctx)
        damaged = healthy.replace('**Name**', 'Name')
        self.assertTrue(compare_translation_tables(source.read_text(), damaged, header_cells=headers))
        self.assertTrue(compare_translation_tables(healthy, damaged, exact=True, header_cells=headers))
        translated.write_text(damaged)
        self.assertIn('表头角色', self.run_tool('verify_translation.py', translated, source,
            '--fragment', '--project-context', ctx, ok=False))
        # A pure Markdown caller has no provenance from which to infer th.
        self.assertEqual(compare_translation_tables(healthy, damaged), [])

    def test_api_candidate_and_final_check_keep_source_proven_roles(self):
        source, snapshot = self.grid()
        project_context(self.root, source, [snapshot])
        for name in ['manifest.txt', 'official.txt']:
            (self.root / name).write_text('page.html\n')
        translated = self.root / 'trans_page.md'
        translated.write_text(source.read_text().replace('**Important**', '重要'))
        final = self.root / 'final.md'
        self.run_tool('merge_api.py', self.root / 'manifest.txt', self.root, final,
                      '--navigation-record', self.root / 'record.json')
        before = final.read_bytes()
        args = [final, self.root / 'manifest.txt', self.root / 'official.txt', self.root, source,
                '--navigation-record', self.root / 'record.json']
        self.run_tool('verify_api_translation.py', *args)
        translated.write_text(translated.read_text().replace('**Name**', 'Name'))
        self.assertIn('表头角色', self.run_tool('merge_api.py', self.root / 'manifest.txt', self.root,
            final, '--navigation-record', self.root / 'record.json', ok=False))
        self.assertEqual(final.read_bytes(), before)
        final.write_text(final.read_text().replace('**Name**', 'Name'))
        self.assertIn('表头角色', self.run_tool('verify_api_translation.py', *args, ok=False))

    def delivery_chain(self, record):
        problems = []
        entries = delivery.check_source_chains(self.root, record, problems, source_only=True)
        delivery.run_source_reconcile(self.root, record, entries, problems)
        _, _, checks, _ = delivery.rerun_checks(self.root, record, problems)
        delivery.align_sources_with_checks(entries, checks, problems, mode='translation', root=str(self.root))
        return problems

    def test_formal_v2_delivery_requires_consumed_matching_context(self):
        source, snapshot = self.grid()
        ctx = project_context(self.root, source, [snapshot])
        record = json.loads((self.root / 'record.json').read_text())
        healthy = source.read_text().replace('**Important**', '重要')
        final = self.root / 'final.md'; final.write_text(healthy)
        record['checks'] = [{'tool': 'verify_translation', 'args': ['final.md', source.name]}]
        self.assertIn('角色依据', str(self.delivery_chain(record)))
        record['checks'][0]['args'] += ['--project-context', str(ctx)]
        self.assertEqual(self.delivery_chain(record), [])
        final.write_text(healthy.replace('**Name**', 'Name'))
        self.assertIn('复验失败', str(self.delivery_chain(record)))
        final.write_text(healthy)
        # Another valid source admission for the same Markdown, with v1 manual
        # mapping: its path/role semantics cannot authorize a declared v2 chain.
        alternate = copy.deepcopy(record)
        mapping = json.loads((self.root / snapshot['table_conversions']).read_text())
        mapping['version'] = 1
        (self.root / 'manual.json').write_text(json.dumps(mapping))
        alternate['sources'][0]['snapshots'][0]['table_conversions'] = 'manual.json'
        (self.root / 'alternate.json').write_text(json.dumps(alternate))
        problems = []
        entry = delivery.check_source_chains(self.root, alternate, problems, source_only=True)[0]
        delivery.run_source_reconcile(self.root, alternate, [entry], problems)
        self.assertEqual(problems, [])
        context = json.loads(ctx.read_text()); context['source_record'] = 'alternate.json'
        context['source_review']['binding'] = {k: entry[k] for k in ('parsed_sha256', 'source_version', 'snapshots')}
        wrong = self.root / 'wrong-context.json'; wrong.write_text(json.dumps(context))
        record['checks'][0]['args'][-1] = str(wrong)
        self.assertIn('角色依据', str(self.delivery_chain(record)))

    def test_formal_api_v2_delivery_requires_matching_navigation_consumption(self):
        source, snapshot = self.grid()
        project_context(self.root, source, [snapshot])
        record = json.loads((self.root / 'record.json').read_text())
        for name in ['manifest.txt', 'official.txt']:
            (self.root / name).write_text('page.html\n')
        (self.root / 'trans_page.md').write_text(source.read_text().replace('**Important**', '重要'))
        self.run_tool('merge_api.py', self.root / 'manifest.txt', self.root, self.root / 'final.md',
                      '--navigation-record', self.root / 'record.json')
        args = ['final.md', 'manifest.txt', 'official.txt', str(self.root), source.name]
        record['checks'] = [{'tool': 'verify_api_translation', 'args': args}]
        self.assertIn('角色依据', str(self.delivery_chain(record)))
        args += ['--navigation-record', str(self.root / 'record.json')]
        self.assertEqual(self.delivery_chain(record), [])
        # Healthy bytes alone are not proof that the same map was consumed.
        wrong = copy.deepcopy(record)
        mapping = json.loads((self.root / snapshot['table_conversions']).read_text())
        mapping['version'] = 1
        (self.root / 'manual.json').write_text(json.dumps(mapping))
        wrong['sources'][0]['snapshots'][0]['table_conversions'] = 'manual.json'
        (self.root / 'wrong-navigation.json').write_text(json.dumps(wrong))
        args[-1] = str(self.root / 'wrong-navigation.json')
        self.assertIn('角色依据', str(self.delivery_chain(record)))
        args[-1] = str(self.root / 'record.json')
        final = self.root / 'final.md'; final.write_text(final.read_text().replace('**Name**', 'Name'))
        self.assertIn('复验失败', str(self.delivery_chain(record)))

    def test_multi_snapshot_local_table_numbers_project_to_selected_range(self):
        first, a = self.grid('a'); second, b = self.grid('b')
        left, right = first.read_text().rstrip('\n'), second.read_text().rstrip('\n')
        text = left + '\n\n' + right + '\n'; source = self.root / 'combined.md'; source.write_text(text)
        boundary = len(left.splitlines()) + 1
        a['range'] = [1, boundary]; b['range'] = [boundary + 1, len(text.split('\n'))]
        ctx = project_context(self.root, source, [a, b])
        current = rwp.load_project_context(ctx, source)
        self.assertEqual(rwp.table_headers(current), {(1, 2, 1), (2, 2, 1)})
        self.assertEqual(rwp.table_headers(current, [(len(left) + 2, len(text))]), {(1, 2, 1)})
        record = json.loads((self.root / 'record.json').read_text())
        record['checks'] = [{'tool': 'verify_translation',
            'args': ['final.md', source.name, '--fragment', '--project-context', str(ctx)]}]
        final = self.root / 'final.md'; final.write_text(text)
        self.assertEqual(self.delivery_chain(record), [])
        # Only the second snapshot loses its real th: local table 1 must still
        # be checked as table 2 in this full-source delivery.
        final.write_text(left + '\n\n' + right.replace('**Name**', 'Name') + '\n')
        self.assertIn('复验失败', str(self.delivery_chain(record)))


if __name__ == '__main__':
    unittest.main()
