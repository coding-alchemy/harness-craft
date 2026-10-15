"""五项复评 P2 的原始输入回归；预期来自固定 DOM 内容与真实消费者。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from latexml_test_support import (raw_document, note, current_candidate,
                                  replace_current, assert_rejected_at_admission)

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))
import _latexml_source as latexml
import export_pdf as exporter
from _source_reconcile import reconcile_latexml_to_markdown

SCRIPTS = Path(latexml.__file__).parent


class ReadingRolesTest(unittest.TestCase):

    def test_code_role_and_exact_spaces_across_hosts(self):
        for host in ('p', 'h2', 'note'):
            body = 'Text <code>a  b</code>.'
            raw = raw_document(note('<p>' + body + '</p>') if host == 'note'
                               else '<%s>%s</%s>' % (host, body, host))
            for replacement in ('`a b`', 'a  b'):
                with self.subTest(host=host, replacement=replacement), \
                        tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    md, payload = current_candidate(base, raw)
                    self.assertIn('`a  b`', md)
                    self.assertEqual(reconcile_latexml_to_markdown(
                        raw, md, None, payload), [])
                    changed, current = replace_current(
                        md, payload, '`a  b`', replacement)
                    assert_rejected_at_admission(self,
                        base, raw, changed, current)

    def test_link_role_label_and_target_across_hosts(self):
        for host in ('p', 'h2', 'note'):
            body = 'Go <a href="https://example.org/a">Link</a>.'
            raw = raw_document(note('<p>' + body + '</p>') if host == 'note'
                               else '<%s>%s</%s>' % (host, body, host))
            for old, new in (('https://example.org/a', 'https://example.org/b'),
                             ('[Link](https://example.org/a)', 'Link'),
                             ('[Link]', '[Loss]')):
                with self.subTest(host=host, new=new), \
                        tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    md, payload = current_candidate(base, raw)
                    self.assertEqual(reconcile_latexml_to_markdown(
                        raw, md, None, payload), [])
                    changed, current = replace_current(md, payload, old, new)
                    assert_rejected_at_admission(self,
                        base, raw, changed, current)

    def test_footnote_math_first_and_continuation_paragraphs(self):
        for content in ('<p>Math $a*b*c$ tail.</p>',
                        '<p>First.</p><p>Math $a*b*c$ tail.</p>',
                        '<p>First.</p><p>Math <math display="inline" '
                        'alttext=" x\n+y "><mi>x</mi></math> tail.</p>'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                raw = raw_document(note(content))
                md, payload = current_candidate(Path(tmp), raw)
                self.assertEqual(reconcile_latexml_to_markdown(
                    raw, md, None, payload), [])

    def test_code_order_and_definition_owner_rejected(self):
        raw = raw_document(note('<p>Before.</p><pre>CODE</pre><p>After.</p>')
                           + '<div class="ltx_note" id="fn:b">'
                           '<div class="ltx_note_content"><p>Other.</p></div></div>')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md, payload = current_candidate(base, raw)
            fence = '    ```\n    CODE\n    ```'
            swapped, current = replace_current(
                md, payload, 'Before.\n    \n' + fence + '\n    \n    After.',
                'After.\n    \n' + fence + '\n    \n    Before.')
            assert_rejected_at_admission(self, base, raw, swapped, current)
            moved, current = replace_current(md, payload, fence, '')
            moved, current = replace_current(
                moved, current, 'Other.', 'Other.\n    \n' + fence)
            assert_rejected_at_admission(self, base, raw, moved, current)

    def test_mixed_footnote_real_consumption_and_damage(self):
        raw = raw_document(note(
            'DIRECT<p>Before $a*b*c$.</p><pre>CODE  KEEP</pre>'
            '<p>After $a*b*c$.</p><ol><li>One</li><li>Two</li></ol>'
            '<table><tr><td>Cell</td><td>Value</td></tr></table>'
            '<p>Last.</p>'))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md, payload = current_candidate(base, raw)
            self.assertEqual(reconcile_latexml_to_markdown(
                raw, md, None, payload), [])
            sink = []
            reader, _ = exporter.build_markdown(
                sink, 'ch01-', exporter.scan_math(md).spans, md)
            dom = BeautifulSoup(reader.render(md), 'html.parser')
            definition = dom.select_one('li.footnote-item')
            self.assertIsNotNone(definition.find('pre'))
            self.assertEqual(definition.find('pre').get_text().rstrip('\n'),
                             'CODE  KEEP')
            self.assertEqual([x['data-tex'] for x in
                              definition.select('[data-tex]')],
                             ['a*b*c', 'a*b*c'])
            self.assertEqual([x.get_text() for x in
                              definition.select('ol > li')], ['One', 'Two'])
            self.assertEqual([x.get_text() for x in
                              definition.select('th, td')], ['Cell', 'Value'])
            reading = definition.get_text()
            positions = [reading.index(x) for x in
                         ('DIRECT', 'Before', 'CODE', 'After', 'One', 'Cell', 'Last')]
            self.assertEqual(positions, sorted(positions))
            fence = '    ```\n    CODE  KEEP\n    ```'
            for old, new in (
                    (fence, '```\nCODE  KEEP\n```'),
                    ('Before $a*b*c$.', 'After $a*b*c$.'),
                    ('$a*b*c$', '$a*b*d$'), ('$a*b*c$', '')):
                changed, current = replace_current(md, payload, old, new)
                assert_rejected_at_admission(self, base, raw, changed, current)

    def test_recheck_leaf_and_child_structure(self):
        cases = (
            ('table', note('<table><tr><td><code>a|b</code></td><td>X</td></tr></table>')),
            ('math', note('<p>$x$$y$</p><p><a href="https://example.org/a">A[$x$$y$]</a></p>')),
            ('nested', note('<ul><li>One<ul><li>Inner</li></ul></li><li>Two</li></ul>')),
            ('list-code', note('<ul><li><p>Before.</p><pre>CODE KEEP</pre><p>After.</p></li></ul>')),
            ('wrapper-code', note('<div><p>Before.</p><pre>CODE KEEP</pre><p>After.</p></div>')),
            ('uri', '<p><a href="https://example.org/测试">Link</a></p>'),
            ('caption', '<figure><figcaption>Figure 1: <code>a  b</code>.</figcaption></figure>'),
            ('caption-math', '<figure><figcaption>Figure 1: <code>a  b</code> and $x$.</figcaption></figure>'),
        )
        for name, body in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                raw = raw_document(body)
                md, payload = current_candidate(base, raw)
                self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
                reader, _ = exporter.build_markdown([], 'ch01-', exporter.scan_math(md).spans, md)
                dom = BeautifulSoup(reader.render(md), 'html.parser')
                if name == 'nested':
                    self.assertEqual(len(dom.select('li.footnote-item ul')), 2)
                    self.assertEqual(dom.select_one('li.footnote-item ul ul li').get_text(), 'Inner')
                    old = '      - Inner'
                    self.assertIn(old, md)
                    new = '    - Inner'
                elif name in ('list-code', 'wrapper-code'):
                    definition = dom.select_one('li.footnote-item')
                    self.assertEqual(definition.find('pre').get_text().rstrip('\n'), 'CODE KEEP')
                    if name == 'list-code':
                        self.assertIsNotNone(definition.select_one('ul > li pre'))
                    reading = definition.get_text()
                    self.assertLess(reading.index('Before'), reading.index('CODE'))
                    self.assertLess(reading.index('CODE'), reading.index('After'))
                    old, new = 'CODE KEEP', 'CODE LOSS'
                elif name == 'math':
                    self.assertEqual([x['data-tex'] for x in dom.select('[data-tex]')], ['x', 'y', 'x', 'y'])
                    old, new = '$x$$y$', '$y$$x$'
                elif name == 'uri':
                    self.assertEqual(dom.find('a')['href'], 'https://example.org/%E6%B5%8B%E8%AF%95')
                    old, new = 'https://example.org/测试', 'https://example.org/损伤'
                else:
                    expected = 'a|b' if name == 'table' else 'a  b'
                    self.assertEqual(dom.find('code').get_text(), expected)
                    old, new = ('a\\|b', 'a\\|c') if name == 'table' else ('`a  b`', '`a b`')
                damaged, current = replace_current(md, payload, old, new)
                assert_rejected_at_admission(self, base, raw, damaged, current)

    def test_nested_footnote_code_owner_and_order_damage(self):
        raw = raw_document(note('<ul><li><p>Before.</p><pre>CODE KEEP</pre>'
                                '<p>After.</p></li><li>Other.</li></ul>'))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md, payload = current_candidate(base, raw)
            self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
            fence = '      ```\n      CODE KEEP\n      ```'
            moved, current = replace_current(md, payload, fence, '')
            moved, current = replace_current(moved, current, 'Other.',
                                               'Other.\n      \n' + fence)
            assert_rejected_at_admission(self, base, raw, moved, current)
            changed, current = replace_current(md, payload, 'Before.', 'After.')
            changed, current = replace_current(changed, current, '      After.', '      Before.')
            assert_rejected_at_admission(self, base, raw, changed, current)

    def test_mixed_footnote_real_pdf_and_independent_verification(self):
        import hashlib
        raw = raw_document(note(
            'DIRECT<p>Before $a*b*c$.</p><pre>CODE  KEEP</pre>'
            '<p>After $a*b*c$.</p><ol><li>One</li><li>Two</li></ol>'
            '<table><tr><td><code>a|b</code></td><td>Value</td></tr>'
            '<tr><td><math display="inline" alttext="|x|"><mi>x</mi></math></td>'
            '<td>Pipe</td></tr></table>'
            '<p>$x$$y$</p><ul><li>Outer<ul><li>Inner</li></ul>'
            '<pre>OWNED CODE</pre></li><li>Second</li></ul>'
            '<div><p>Wrapped before.</p><pre>WRAPPED CODE</pre>'
            '<p>Wrapped after.</p></div>'
            '<p>Last <math display="inline" alttext=" x\n+y ">'
            '<mi>x</mi></math>.</p>'))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md, payload = current_candidate(base, raw)
            self.assertEqual(reconcile_latexml_to_markdown(
                raw, md, None, payload), [])
            adaptation = base / 'adapt.json'
            adaptation.write_text(json.dumps(payload))
            doc = base / 'doc.md'
            doc.write_text(md.replace('# T\n',
                           '# T\n\n> **来源**：https://example.org/probe\n', 1))
            declaration = base / 'decl.json'
            declaration.write_text(json.dumps({
                'version': 1, 'inputs': [{'path': str(doc), 'sha256':
                    hashlib.sha256(doc.read_bytes()).hexdigest()}],
                'exclusions': [], 'document_title': {'original': 'T',
                    'chinese': '脚注混合结构', 'basis': '固定原始装置'}}))
            for script, option in (('export_pdf.py', '--output'),
                                   ('verify_pdf.py', '--pdf')):
                result = subprocess.run([
                    sys.executable, str(SCRIPTS / script), option,
                    str(base / 'doc.pdf'), '--work-dir', str(base / 'work'),
                    '--source-adaptation', str(adaptation),
                    '--view-declaration', str(declaration), str(doc)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
            report = json.loads((base / 'work/export_report.json').read_text())
            self.assertEqual([(x['mode'], x['latex'])
                              for x in report['chapters'][0]['math']],
                             [('inline', 'a*b*c'), ('inline', 'a*b*c'),
                              ('inline', '|x|'), ('inline', 'x'), ('inline', 'y'),
                              ('inline', ' x\n+y ')])
            dom = BeautifulSoup((base / 'work/combined.html').read_text(),
                                'html.parser')
            definition = dom.select_one('li.footnote-item')
            self.assertEqual(definition.select_one('th code').get_text(), 'a|b')
            self.assertEqual(len(definition.select('table td')), 2)
            self.assertEqual(definition.select_one('td [data-tex]')['data-tex'], '|x|')
            self.assertEqual(len(definition.find_all('ul')), 2)
            self.assertEqual(definition.select_one('ul > li pre').get_text().rstrip('\n'), 'OWNED CODE')
            self.assertIn('WRAPPED CODE', definition.get_text())


if __name__ == '__main__':
    unittest.main()
