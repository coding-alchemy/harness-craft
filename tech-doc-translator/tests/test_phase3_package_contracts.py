"""最小持久回归：版本不能沿用旧资格，venv 入口不能被 realpath 破坏。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      'skills/tech-doc-translator/scripts'))
import build_work_package_tasks as tasks
import recover_work_packages as recovery
import review_delivery_batch as batch
import verify_delivery as delivery


class PackageContractTests(unittest.TestCase):
    def test_partial_review_protects_other_target_and_resource_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = root / 'wps'
            packages.mkdir()
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                      'inputs': [], 'outputs': [], 'checks': [], 'reviews': []}
            (root / 'record.json').write_text(json.dumps(record), encoding='utf-8')
            first, other = root / 'first.md', root / 'other.md'
            first.write_text('## First\n\n正文。\n', encoding='utf-8')
            other.write_text('## Other\n\n![图](figure.svg)\n', encoding='utf-8')
            (root / 'figure.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<style>@import url(style.css);</style><rect/></svg>', encoding='utf-8')
            css = root / 'style.css'
            css.write_text('rect {fill: green;}', encoding='utf-8')
            for name, target in [('wp_001.md', first), ('wp_002.md', other)]:
                (packages / name).write_text(
                    '---\ntarget_file: ' + str(target) + '\n---\n正文。\n', encoding='utf-8')
            context = {'_root': directory, '_path': str(root / 'context.json'),
                       'source_record': 'record.json'}
            protected = recovery.protected_inputs(context,
                [{'path': str(packages / 'wp_001.md')}], first)
            self.assertIn(other.resolve(), protected)
            self.assertIn(css.resolve(), protected)

    def test_unreadable_project_record_keeps_other_project_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bad.json').write_text('{', encoding='utf-8')
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                      'inputs': ['missing.md'], 'outputs': [], 'checks': [],
                      'reviews': [], 'sources': []}
            (root / 'valid.json').write_text(json.dumps(record), encoding='utf-8')
            projects = [{'project': name, 'record': name + '.json', 'mode': 'pdf',
                         'scope': ['missing.md'], 'evidence_dir': name + '-evidence'}
                        for name in ('valid', 'bad')]
            manifest, report = root / 'manifest.json', root / 'report.json'
            manifest.write_text(json.dumps({'projects': projects}), encoding='utf-8')
            self.assertFalse(batch.review(manifest, report))
            results = json.loads(report.read_text())['projects']
            self.assertIsNotNone(results[0]['exit_code'])
            self.assertEqual('record-gap', results[1]['category'])

    def test_bad_utf8_body_does_not_cancel_other_cli_or_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'bad.md').write_bytes(b'\xff')
            (root/'good.md').write_text('# Guide\n\nCurrent content.\n')
            projects = []
            for name in ('bad', 'good'):
                record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                          'inputs': [name+'.md'], 'outputs': [], 'checks': [],
                          'reviews': [], 'sources': []}
                (root/(name+'.json')).write_text(json.dumps(record))
                projects.append({'project': name, 'record': name+'.json',
                    'mode': 'pdf', 'scope': record['inputs'],
                    'evidence_dir': name+'-evidence'})
            manifest, report = root/'manifest.json', root/'report.json'
            manifest.write_text(json.dumps({'projects': projects}))
            self.assertFalse(batch.review(manifest, report))
            results = json.loads(report.read_text())['projects']
            self.assertEqual(['bad', 'good'], [r['project'] for r in results])
            self.assertTrue(all(r['call'] and r['exit_code'] is not None for r in results))
            self.assertTrue(any('不可读' in d for d in results[0]['diagnostics']))
            before = (root/'good.md').read_bytes()
            with self.assertRaisesRegex(ValueError, '受保护'):
                batch.review(manifest, root/'good.md')
            self.assertEqual(before, (root/'good.md').read_bytes())

    def test_source_preload_uses_existing_empty_and_invalid_entry_semantics(self):
        for sources in (None, [None], [None, {'parsed_markdown': 'source.md',
                'snapshots': [None, {'snapshot': 'snapshot.html'}]}]):
            with self.subTest(sources=sources), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'chapter.md').write_text('# Guide\n\nContent.\n')
                (root/'source.md').write_text('# Source\n')
                (root/'snapshot.html').write_text('<h1>Source</h1>')
                projects = []
                for name, declarations in [('affected', sources), ('companion', [])]:
                    record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                        'inputs': ['chapter.md'], 'outputs': [], 'checks': [],
                        'reviews': [], 'sources': declarations}
                    (root/(name+'.json')).write_text(json.dumps(record))
                    projects.append({'project': name, 'record': name+'.json',
                        'mode': 'pdf', 'scope': ['chapter.md'],
                        'evidence_dir': name+'-evidence'})
                manifest, report = root/'manifest.json', root/'report.json'
                manifest.write_text(json.dumps({'projects': projects}))
                self.assertFalse(batch.review(manifest, report))
                results = json.loads(report.read_text())['projects']
                self.assertEqual(['affected', 'companion'], [x['project'] for x in results])
                self.assertTrue(all(x['call'] and x['exit_code'] is not None for x in results))
                problems = []
                protected = delivery.source_dependency_paths(root, record | {'sources': sources}, problems)
                if sources is None:
                    self.assertEqual([], problems)
                else:
                    self.assertIn('源链 #1 必须是对象', problems)
                if sources and len(sources) > 1:
                    for path in (root/'source.md', root/'snapshot.html'):
                        self.assertIn(path.resolve(), protected)
                        before = path.read_bytes()
                        with self.assertRaisesRegex(ValueError, '受保护'):
                            batch.review(manifest, path)
                        self.assertEqual(before, path.read_bytes())

    def test_source_collection_and_mixed_snapshot_failures_remain_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'source.md').write_text('# Guide\n\nContent.\n')
            (root/'snapshot.html').write_text('<h1 id="selected">Guide</h1><p>Content.</p>')
            source = {'parsed_markdown': 'source.md', 'family': 'reference',
                'source_version': 'v1', 'snapshots': [
                    {'snapshot': 'snapshot.html', 'section_id': 'selected'}]}
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                'inputs': ['source.md'], 'outputs': [], 'files': {},
                'checks': [], 'reviews': [], 'sources': [source]}
            cases = [([source], None), (1, 'sources 必须是列表'),
                (False, 'sources 必须是列表'),
                ([source | {'snapshots': 1}], 'snapshots 必须是列表'),
                ([source | {'snapshots': [None, *source['snapshots']]}],
                    'snapshots 项需要 snapshot 路径')]
            for sources, diagnostic in cases:
                with self.subTest(sources=sources):
                    affected = record | {'sources': sources}
                    problems = []
                    entries = delivery.check_source_chains(directory, affected, problems,
                        source_only=True)
                    if diagnostic:
                        self.assertTrue(any(diagnostic in x for x in problems), problems)
                    else:
                        self.assertEqual([], problems)
                    if sources == [source] or (isinstance(sources, list)
                            and sources[0]['snapshots'] == [None, *source['snapshots']]):
                        self.assertEqual(1, len(entries))
                        self.assertEqual('selected', entries[0]['snapshots'][0]['section_id'])
                    (root/'affected.json').write_text(json.dumps(affected))
                    (root/'companion.json').write_text(json.dumps(record | {'sources': []}))
                    manifest, report = root/'manifest.json', root/'report.json'
                    manifest.write_text(json.dumps({'projects': [
                        {'project': name, 'record': name+'.json', 'mode': 'pdf',
                            'scope': ['source.md'], 'evidence_dir': name+'-evidence'}
                        for name in ('affected', 'companion')]}))
                    self.assertFalse(batch.review(manifest, report))
                    results = json.loads(report.read_text())['projects']
                    self.assertTrue(all(x['call'] and x['exit_code'] is not None for x in results))
                    if diagnostic:
                        self.assertTrue(any(diagnostic in x for x in results[0]['diagnostics']))
                    if entries and entries[0]['snapshots']:
                        before = (root/'snapshot.html').read_bytes()
                        with self.assertRaisesRegex(ValueError, '受保护'):
                            batch.review(manifest, root/'snapshot.html')
                        self.assertEqual(before, (root/'snapshot.html').read_bytes())

    def test_toc_cli_preserves_literal_title_in_actual_reading(self):
        from markdown_it import MarkdownIt
        from bs4 import BeautifulSoup
        import build_toc
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'chapter.md').write_text('# A\\*B\\*C.\n')
            (root/'official.txt').write_text('A*B*C.\n')
            manifest = {'project_root': directory, 'scope': 'all',
                'official_basis': {'path': 'official.txt', 'confirmation': '独立原题'},
                'official_lines': [1], 'entries': [{'official_line': 1,
                    'original_title': 'A*B*C.', 'translation': 'chapter.md',
                    'occurrence': 1, 'level': 1}]}
            path, output = root/'manifest.json', root/'00_目录.md'
            path.write_text(json.dumps(manifest))
            result = subprocess.run([sys.executable, build_toc.__file__,
                '--manifest', str(path), '--output', str(output)],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            html = MarkdownIt('commonmark', {'html': False}).render(output.read_text())
            link = BeautifulSoup(html, 'html.parser').find('a', href=True)
            self.assertEqual('A*B*C.', link.get_text())
            self.assertEqual('chapter.md#abc', link['href'])
            # 编号判断基于可见标题；序列化后的句点转义不能触发重复编号。
            (root/'chapter.md').write_text('# 1. A\\*B\\*C.\n')
            (root/'official.txt').write_text('1. A*B*C.\n')
            manifest['entries'][0].update(original_title='1. A*B*C.', number='1.')
            path.write_text(json.dumps(manifest))
            result = subprocess.run([sys.executable, build_toc.__file__,
                '--manifest', str(path), '--output', str(output)],
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            html = MarkdownIt('commonmark', {'html': False}).render(output.read_text())
            link = BeautifulSoup(html, 'html.parser').find('a', href=True)
            self.assertEqual('1. A*B*C.', link.get_text())
            self.assertEqual('chapter.md#1-abc', link['href'])

    def test_batch_compares_persisted_resource_identity_and_detects_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'chapter.md').write_text('# 章\n\n![图](figure.svg)\n',
                                             encoding='utf-8')
            resource = root / 'figure.svg'
            resource.write_text('<svg xmlns="http://www.w3.org/2000/svg">'
                                '<rect fill="green"/></svg>', encoding='utf-8')
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                      'inputs': ['chapter.md'], 'outputs': [], 'checks': [],
                      'reviews': [], 'sources': []}
            record_path = root / 'record.json'
            record_path.write_text(json.dumps(record), encoding='utf-8')
            index_path = root / 'index.json'
            index_path.write_text(json.dumps({'identity':
                delivery.compute_delivery_identity(directory, record, [])}),
                encoding='utf-8')
            persisted = json.loads(index_path.read_text())['identity']
            self.assertEqual(persisted, batch.current_identity(record_path))
            resource.write_text(resource.read_text().replace('green', 'red'),
                                encoding='utf-8')
            self.assertNotEqual(persisted, batch.current_identity(record_path))

    def test_source_version_changes_existing_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rule = root / 'rules.md'
            rule.write_text('保持原文含义。\n', encoding='utf-8')
            context = {'_root': directory, '_source_version': 'v1',
                       'instructions': ['rules.md'], 'rules': ['rules.md'],
                       'glossary': [], 'output_contract': ['rules.md']}
            source = root / 'source.md'
            source.write_text('## Section\n\nKeep the condition.\n', encoding='utf-8')
            body = '## Section（节）\n\n保留该条件。\n'
            exp = {'name': 'wp_001.md', 'body': source.read_text(),
                   'digest': recovery._sha256(source.read_text())}
            target = root / 'wp_001.md'
            target.write_text(body, encoding='utf-8')
            facts = recovery.package_facts(exp, body, str(target), str(source),
                                            context=context)
            entry = dict(facts, review={'semantic': 'done', 'unresolved': []})
            self.assertEqual([], recovery.package_binding_problems(entry, facts, body))
            context['_source_version'] = 'v2'
            current = recovery.package_facts(exp, body, str(target), str(source),
                                              context=context)
            self.assertTrue(recovery.package_binding_problems(entry, current, body))

    def test_task_executes_with_configured_virtualenv_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, output = (root / n for n in ('source.md', 'target.md', 'task.json'))
            source.write_text('## Section\n\nKeep the condition.\n', encoding='utf-8')
            target.write_text('## Section（节）\n\n保留该条件。\n', encoding='utf-8')
            rule = root / 'rules.md'
            rule.write_text('保留标题，准确翻译。\n', encoding='utf-8')
            skill = Path(tasks.__file__).resolve().parent.parent
            context = {'_root': directory, 'python': sys.executable,
                       'skill_dir': str(skill), 'instructions': ['rules.md'],
                       'rules': ['rules.md'], 'glossary': [],
                       'output_contract': ['rules.md'],
                       'examples': [{'path': 'rules.md', 'differences': '无代码示例，不添加正文。'}],
                       'return_contract': '返回术语、原文现象、检查、不确定项。'}
            exp = {'name': 'wp_001.md', 'path': str(source), 'target': str(target),
                   'body': source.read_text(), 'meta': {'headings': '1'}}
            result = tasks.task(context, exp, source, output)
            output.write_text(json.dumps(result), encoding='utf-8')
            self.assertEqual(str(Path(sys.executable).absolute()), result['command'][0])
            checked = subprocess.run(result['command'], capture_output=True, text=True)
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_batch_report_cannot_replace_svg_css_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'chapter.md').write_text('# 章\n\n![图](figure.svg)\n',
                                             encoding='utf-8')
            (root / 'figure.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<style>@import url(style.css);</style><rect/></svg>',
                encoding='utf-8')
            css = root / 'style.css'
            css.write_text('rect {fill: green;}', encoding='utf-8')
            original = css.read_bytes()
            record = {'version': 1, 'mode': 'pdf', 'delivery_root': directory,
                      'inputs': ['chapter.md'], 'outputs': [], 'checks': [],
                      'reviews': [], 'sources': []}
            (root / 'record.json').write_text(json.dumps(record), encoding='utf-8')
            manifest = root / 'batch.json'
            manifest.write_text(json.dumps({'projects': [{
                'project': 'explicit', 'record': 'record.json', 'mode': 'pdf',
                'scope': ['chapter.md'], 'evidence_dir': 'evidence'}]}),
                encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '受保护'):
                batch.review(manifest, css)
            self.assertEqual(original, css.read_bytes())


if __name__ == '__main__':
    unittest.main()
