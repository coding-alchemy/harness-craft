"""原DOM脚注表格分类及真实块阅读回归，不以数学掩蔽创造结构。"""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

from latexml_test_support import (
    IDENTITY, SCRIPTS, current_candidate, note, raw_document, replace_current,
    assert_rejected_at_admission,
)

sys.path.insert(0, str(SCRIPTS))
import _latexml_source as latexml
import export_pdf as exporter
from _source_reconcile import reconcile_latexml_to_markdown
from bs4 import BeautifulSoup

COMPLEX = ('<table><tr><td colspan="2">A</td><td>B</td></tr>'
           '<tr><td colspan="2">C</td><td>D</td></tr></table>')
MATH_TABLE = ('<table><tr><td><math display="inline" alttext="|x|">'
              '<mi>x</mi></math></td><td>X</td></tr></table>')


def mapping(raw):
    return {'version': 1, 'snapshot_sha256': latexml.sha256_text(raw),
            'tables': [{'locate': {'table': 1}, 'cells': [
                {'row': row, 'col': col, 'rowspan': 1,
                 'colspan': 2 if col == 1 else 1,
                 'targets': [{'table': 1, 'row': row, 'col': col}]}
                for row in (1, 2) for col in (1, 2)]}]}


class FootnoteTableBoundaryTest(unittest.TestCase):
    def assert_leaf_rejected(self, base, raw, md, payload):
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('正文流' in d or '与声明源格不符' in d for d in diffs), diffs)
        self.assertFalse(any('摘要' in d for d in diffs), diffs)
        self.assertEqual(payload['markdown'], latexml.markdown_range_facts(md))
        source, candidate = base / 'damaged.md', base / 'damaged.json'
        source.write_text(md)
        candidate.write_text(json.dumps(payload))
        result = subprocess.run([
            __import__('sys').executable, str(SCRIPTS / 'split_work_packages.py'),
            str(source), str(base / 'packs'), str(base / 'trans'),
            '--source-adaptation', str(candidate)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('Markdown 摘要', result.stderr)
        self.assertIn('拆分拒绝', result.stderr)
        self.assertFalse((base / 'packs').exists())

    def test_mapped_cell_leaf_roles_and_exact_content(self):
        for host in ('body', 'note'):
            for leaf in (
                '<code>a  b</code>',
                '<code>a b</code>',
                r'<code>a\|b  c</code>',
                '<a href="https://example.org/a">Link</a>',
                '<a href="https://example.org/测试"><code>a  b</code></a>',
            ):
                with self.subTest(host=host, leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    table = COMPLEX.replace('>A<', '>' + leaf + '<')
                    raw = raw_document(note(table) if host == 'note' else table)
                    (base / 'input.html').write_text(raw)
                    conversion = mapping(raw)
                    md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                        raw, None, [], tmp, table_conversions=conversion)
                    payload = latexml.build_candidate_adaptation(
                        {'paper_identity': IDENTITY, 'decisions': []}, raw,
                        str(base / 'input.html'), corrs, unresolved,
                        md_text=md, table_conversions=conversion)
                    self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
                    if host == 'note':
                        reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
                        dom = BeautifulSoup(reader.render(md), 'html.parser')
                        first = dom.select_one('li.footnote-item th')
                        if '<code>' in leaf:
                            self.assertEqual(first.code.get_text(), BeautifulSoup(leaf, 'html.parser').code.get_text())
                        if '<a ' in leaf:
                            self.assertEqual(first.a['href'], exporter.MarkdownIt().normalizeLink(
                                BeautifulSoup(leaf, 'html.parser').a['href']))
                    else:
                        # TABLE is the established source representation; read its cell once.
                        from _source_reconcile import _MarkdownFacts, _norm_reading, _direct_read
                        self.assertEqual(_MarkdownFacts(md, source_context=latexml.scan_context_from_payload(payload)).table_records()[0]['rows'][0][0],
                                         _norm_reading(_direct_read(BeautifulSoup(leaf, 'html.parser'))))
                    if '<code>' in leaf:
                        old = '`a b`' if leaf == '<code>a b</code>' else '`a  b`' if 'a  b' in leaf else r'`a\\|b  c`' if host == 'note' else r'`a\|b  c`'
                        for replacement in {old.replace('  ', ' '), old.strip('`'), old.replace('`', r'\`')} - {old}:
                            damaged, current = replace_current(md, payload, old, replacement)
                            self.assert_leaf_rejected(base, raw, damaged, current)
                    if '<a ' in leaf:
                        old = 'https://example.org/a' if '/a"' in leaf else 'https://example.org/测试'
                        damaged, current = replace_current(md, payload, old,
                            old[:-1] + ('b' if old.endswith('a') else '改'))
                        self.assert_leaf_rejected(base, raw, damaged, current)
                        label = '`a  b`' if '<code>' in leaf else 'Link'
                        damaged, current = replace_current(md, payload, '[' + label + '](' + old + ')', label)
                        self.assert_leaf_rejected(base, raw, damaged, current)
                        damaged, current = replace_current(md, payload, '[' + label + '](' + old + ')',
                            '&#91;' + label + '&#93;(' + old + ')')
                        self.assert_leaf_rejected(base, raw, damaged, current)

    def test_shared_mapped_leaf_fault_is_rejected_by_raw_dom(self):
        from unittest.mock import patch
        original = latexml.table_cell_facts
        for leaf, flat in (('<code>a  b</code>', 'a b'),
                           ('<a href="https://example.org/a">Link</a>', 'Link')):
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                raw = raw_document(note(COMPLEX.replace('>A<', '>' + leaf + '<')))
                (base / 'input.html').write_text(raw)
                conversion = mapping(raw)
                def faulty(*args, **kwargs):
                    cells, codes = original(*args, **kwargs)
                    cells[(1, 1)] = (flat, *cells[(1, 1)][1:])
                    return cells, codes
                with patch.object(latexml, 'table_cell_facts', side_effect=faulty):
                    md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                        raw, None, [], tmp, table_conversions=conversion)
                    payload = latexml.build_candidate_adaptation(
                        {'paper_identity': IDENTITY, 'decisions': []}, raw,
                        str(base / 'input.html'), corrs, unresolved,
                        md_text=md, table_conversions=conversion)
                    diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
                    self.assertTrue(any('与声明源格不符' in d for d in diffs), diffs)
                self.assert_leaf_rejected(base, raw, md, payload)

    def test_mapped_leaves_keep_existing_math_content(self):
        for host in ('body', 'note'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                math = ' x\n+y '
                table = COMPLEX.replace('>A<',
                    '>Literal $\\alpha$ <code>a  b</code> '
                    '<a href="https://example.org/a">Link</a> '
                    '<math alttext="' + math + '" display="inline"><mi>x</mi></math><')
                raw = raw_document(note(table) if host == 'note' else table)
                (base / 'input.html').write_text(raw)
                conversion = mapping(raw)
                md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                    raw, None, [], tmp, table_conversions=conversion)
                payload = latexml.build_candidate_adaptation(
                    {'paper_identity': IDENTITY, 'decisions': []}, raw,
                    str(base / 'input.html'), corrs, unresolved,
                    md_text=md, table_conversions=conversion)
                self.assertIn('$\\alpha$', md)
                self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])

    def test_multiline_mapped_cell_real_pdf_and_damage(self):
        import hashlib
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = raw_document(note(COMPLEX.replace('>A<',
                '><code>a  b</code> <a href="https://example.org/a">Link</a> '
                '<math alttext=" x\n+y " display="inline"><mi>x</mi></math> '
                '<math alttext="z" display="inline"><mi>z</mi></math><')))
            (base / 'input.html').write_text(raw)
            conversion = mapping(raw)
            md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                raw, None, [], tmp, table_conversions=conversion)
            payload = latexml.build_candidate_adaptation(
                {'paper_identity': IDENTITY, 'decisions': []}, raw,
                str(base / 'input.html'), corrs, unresolved,
                md_text=md, table_conversions=conversion)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            for replacement in ('', '$ x&#10;+z $', '$z$ $ x&#10;+y $'):
                old = '$ x&#10;+y $' if not replacement.startswith('$z$') else '$ x&#10;+y $ $z$'
                damaged, current = replace_current(md, payload, old, replacement)
                assert_rejected_at_admission(self, base, raw, damaged, current)
            adaptation = base / 'adapt.json'
            adaptation.write_text(json.dumps(payload))
            doc = base / 'doc.md'
            doc.write_text(md.replace('# T\n', '# T\n\n> **来源**：https://example.org/probe\n', 1))
            declaration = base / 'decl.json'
            declaration.write_text(json.dumps({'version': 1,
                'inputs': [{'path': str(doc), 'sha256': hashlib.sha256(doc.read_bytes()).hexdigest()}],
                'exclusions': [], 'document_title': {'original': 'T', 'chinese': '多行公式映射格', 'basis': '固定原HTML'}}))
            for script, option in (('export_pdf.py', '--output'), ('verify_pdf.py', '--pdf')):
                result = subprocess.run([sys.executable, str(SCRIPTS / script), option,
                    str(base / 'doc.pdf'), '--work-dir', str(base / 'work'),
                    '--source-adaptation', str(adaptation), '--view-declaration', str(declaration), str(doc)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
            dom = BeautifulSoup((base / 'work/combined.html').read_text(), 'html.parser')
            definition = dom.select_one('li.footnote-item')
            self.assertEqual(len(definition.select('th, td')), 4)
            self.assertEqual(definition.code.get_text(), 'a  b')
            self.assertEqual(definition.select_one('th a')['href'], 'https://example.org/a')
            self.assertEqual([m['data-tex'] for m in definition.select('[data-tex]')], [' x\n+y ', 'z'])
            report = json.loads((base / 'work/export_report.json').read_text())
            self.assertEqual([(m['mode'], m['latex']) for m in report['chapters'][0]['math']],
                             [('inline', ' x\n+y '), ('inline', 'z')])

    def test_complex_table_requires_mapping_and_failure_preserves_old(self):
        for body in (COMPLEX, note(COMPLEX)):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                raw = raw_document(body)
                (base / 'input.html').write_text(raw)
                (base / 'input.json').write_text(json.dumps({
                    'version': 1, 'format': 'latexml',
                    'snapshot': {'path': str(base / 'input.html'),
                                 'sha256': latexml.sha256_text(raw)},
                    'paper_identity': IDENTITY, 'decisions': []}))
                outputs = [base / 'source.md', base / 'candidate.json',
                           base / 'source.images_display.json']
                for path in outputs:
                    path.write_bytes(b'OLD')
                result = subprocess.run([
                    __import__('sys').executable, str(SCRIPTS / 'parse_reference_html.py'),
                    str(base / 'input.html'), str(outputs[0]),
                    '--source-adaptation', str(base / 'input.json'),
                    '--adaptation-output', str(outputs[1])], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('复杂表', result.stderr)
                self.assertIn('table_conversions', result.stderr)
                self.assertEqual([p.read_bytes() for p in outputs], [b'OLD'] * 3)

    def test_complex_mapping_uses_existing_cell_contract(self):
        raw = raw_document(note(COMPLEX))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'input.html').write_text(raw)
            conversion = mapping(raw)
            md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                raw, None, [], str(base), table_conversions=conversion)
            payload = latexml.build_candidate_adaptation(
                {'paper_identity': IDENTITY, 'decisions': []}, raw,
                str(base / 'input.html'), corrs, unresolved,
                md_text=md, table_conversions=conversion)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
            dom = BeautifulSoup(reader.render(md), 'html.parser')
            self.assertEqual([c.get_text() for c in dom.select('li.footnote-item th, li.footnote-item td')],
                             ['A', 'B', 'C', 'D'])
            for damage in ('missing-cell', 'span', 'target'):
                changed = copy.deepcopy(payload)
                cells = changed['table_conversions']['tables'][0]['cells']
                if damage == 'missing-cell':
                    cells.pop()
                elif damage == 'span':
                    cells[0]['colspan'] = 1
                else:
                    cells[0]['targets'][0]['col'] = 2
                self.assertTrue(reconcile_latexml_to_markdown(raw, md, None, changed), damage)

    def test_mapped_table_reuses_math_and_cell_code_consumption(self):
        raw = raw_document(note(COMPLEX.replace('>A<',
            '><pre>CODE  KEEP</pre><math display="inline" alttext="|x|"><mi>x</mi></math><')))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'input.html').write_text(raw)
            conversion = mapping(raw)
            md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                raw, None, [], tmp, table_conversions=conversion)
            payload = latexml.build_candidate_adaptation(
                {'paper_identity': IDENTITY, 'decisions': []}, raw,
                str(base / 'input.html'), corrs, unresolved,
                md_text=md, table_conversions=conversion)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
            definition = BeautifulSoup(reader.render(md), 'html.parser').select_one('li.footnote-item')
            self.assertEqual(definition.select_one('th [data-tex]')['data-tex'], '|x|')
            self.assertEqual(definition.find('pre').get_text().rstrip('\n'), 'CODE  KEEP')
            changed = copy.deepcopy(payload)
            changed.pop('table_conversions')
            self.assertTrue(reconcile_latexml_to_markdown(raw, md, None, changed))
            damaged, current = replace_current(md, payload, 'CODE  KEEP', 'CODE KEEP')
            assert_rejected_at_admission(self, base, raw, damaged, current)

    def test_mapping_note_target_does_not_receive_table_encoding(self):
        raw = raw_document(note(COMPLEX.replace('>A<',
            '><math display="inline" alttext="|x|"><mi>x</mi></math><')))
        conversion = mapping(raw)
        conversion['tables'][0]['cells'][0]['targets'] = [{'note': [9, 9]}]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'input.html').write_text(raw)
            md, corrs, unresolved, _, _ = latexml.adapt_latexml_snapshot(
                raw, None, [], tmp, table_conversions=conversion)
            payload = latexml.build_candidate_adaptation(
                {'paper_identity': IDENTITY, 'decisions': []}, raw,
                str(base / 'input.html'), corrs, unresolved,
                md_text=md, table_conversions=conversion)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            self.assertEqual(latexml.bound_math_spans(md, payload)[1], [])
            reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
            dom = BeautifulSoup(reader.render(md), 'html.parser')
            formula = dom.select_one('li.footnote-item [data-tex]')
            self.assertEqual(formula['data-tex'], '|x|')
            self.assertIsNone(formula.find_parent('table'))

    def test_table_encoding_keeps_original_tex(self):
        for tex in ('|x|', r'\|x\|', r'\\|x\\|', 'x\ny', ' x\r\n+y ', 'x&#10;y', 'x&amp;y'):
            with self.subTest(tex=tex), tempfile.TemporaryDirectory() as tmp:
                raw = raw_document(note(MATH_TABLE.replace('alttext="|x|"', 'alttext="%s"' % __import__('html').escape(tex, quote=True))))
                md, payload = current_candidate(Path(tmp), raw)
                self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
                self.assertEqual(latexml.bound_math_spans(md, payload)[1], [])
                context = latexml.scan_context_from_payload(payload)
                reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md, source_context=context).spans, md,
                                                   confirmed_math=[('inline', tex)])
                dom = BeautifulSoup(reader.render(md), 'html.parser')
                self.assertEqual(dom.select_one('li.footnote-item th [data-tex]')['data-tex'], tex)

    def test_math_pipe_keeps_real_table_and_lost_structure_is_rejected(self):
        raw = raw_document(note(MATH_TABLE))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md, payload = current_candidate(base, raw)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
            dom = BeautifulSoup(reader.render(md), 'html.parser')
            table = dom.select_one('li.footnote-item table')
            self.assertIsNotNone(table)
            self.assertEqual(len(table.find_all('th')), 2)
            self.assertEqual(table.select_one('[data-tex]')['data-tex'], '|x|')
            damaged, current = replace_current(md, payload, r'$\|x\|$', '$|x|$')
            assert_rejected_at_admission(self, base, raw, damaged, current)
