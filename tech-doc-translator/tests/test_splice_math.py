"""数学装配保持原切片，确认来源走现有准入。"""
import json
import subprocess
import sys

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True)


def test_exact_splice_and_bad_placeholders():
    from splice_math import splice_math
    from _verification import scan_math

    source = 'Start $x_1$, then $$\ny = 2\n$$, then $x_1$.\n'
    draft = '首先⟦m1⟧，随后⟦m2⟧，最后⟦m3⟧。\n'
    result = splice_math(source, draft)
    assert result == '首先$x_1$，随后$$\ny = 2\n$$，最后$x_1$。\n'
    assert [(s.kind, s.raw) for s in scan_math(result).spans] == [
        (s.kind, s.raw) for s in scan_math(source).spans
    ]
    for bad in (draft.replace('⟦m2⟧', ''), draft.replace('⟦m2⟧', '⟦m1⟧'),
                '⟦m3⟧'+draft, draft.replace('⟦m3⟧', '⟦m4⟧'),
                draft+'$z=3$', draft.replace('⟦m3⟧', '⟦m3'),
                draft.replace('⟦m1⟧', '`⟦m1⟧`')+'$x_1$'):
        with pytest.raises(ValueError):
            splice_math(source, bad)


def test_confirmed_context_required(tmp_path):
    from pdf_test_support import original, fact_digest, pdf_project_context, pymupdf
    from test_pdf_confirmed_structure import joined_origin

    root = tmp_path
    pdf = root / 'paper.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 40), 'A confirmed multiline expression with an exact representation.')
        page.insert_text((50, 90), 'Before x+')
        page.insert_text((50, 108), 'y=1 after.')
        doc.save(pdf)
    source_dir = root / 'source'
    q = run('prepare_pdf_source.py', 'inspect', pdf, '--output', source_dir)
    assert q.returncode == 0, q.stderr
    checklist_path = source_dir / 'adjudication_checklist.json'
    checklist = json.loads(checklist_path.read_text())
    binding = {'basis': 'original source line pair', 'scope': [1],
               'source_sha256': checklist['source']['sha256']}
    tex = ' x+\r\ny=1 '
    with pymupdf.open(pdf) as doc:
        origin = joined_origin([original(doc[0], 'x+'), original(doc[0], 'y=1')])
        item = {'type': 'math', 'id': 'm', 'kind': 'inline', 'tex': tex,
                'label': None, 'owner': {'block': 'p', 'role': 'paragraph'},
                'slot': 1, 'origin': origin,
                'conversion': {'source': origin['text'], 'target': tex,
                               'basis': 'source line pair kept together'}}
        item['confirmation'] = {**binding, 'fact_sha256': fact_digest(item)}
        content = [{'type': 'text', 'origin': original(doc[0], 'Before ')},
                   item, {'type': 'text', 'origin': original(doc[0], ' after.')}]
    checklist.update(formula_contract='confirmed-tex-v1', formula_review=binding,
                     reading_order={'adjudicated': True, 'basis': 'selected two-line paragraph'},
                     blocks=[{'id': 'p', 'type': 'paragraph', 'page': 1,
                              'rect': [45, 75, 250, 120], 'order': 1, 'content': content}])
    checklist_path.write_text(json.dumps(checklist))
    source = source_dir / 'source.md'
    q = run('prepare_pdf_source.py', 'materialize', pdf, '--checklist', checklist_path,
            '--output', source)
    assert q.returncode == 0, q.stderr
    project = pdf_project_context(root)
    draft = root / 'draft.md'
    draft.write_text('前文 ⟦m1⟧ 后文。\n')
    output = root / 'assembled.md'
    args = ('--source', source, '--draft', draft, '--output', output)
    missing_context = run('splice_math.py', *args)
    assert missing_context.returncode != 0 and 'project-context' in missing_context.stderr
    assert not output.exists()
    q = run('splice_math.py', *args, '--project-context', project)
    assert q.returncode == 0, q.stdout + q.stderr
    assert ('$'+tex+'$').encode() in output.read_bytes()
    q = run('verify_pdf_source.py', pdf, '--checklist', checklist_path, '--source-md', source,
            '--translation', output)
    assert q.returncode == 0, q.stdout + q.stderr


def test_splice_failure_preserves_inputs(tmp_path):
    root = tmp_path
    source = root / 'source.md'
    draft = root / 'draft.md'
    existing = root / 'existing.md'
    output = root / 'candidate.md'
    alias = root / 'alias.md'
    source.write_bytes(b'Before $x_1$.\r\n')
    draft.write_text('译文 ⟦m2⟧。\n')
    existing.write_bytes(b'previous candidate\n')
    alias.symlink_to(source)
    before = {p: p.read_bytes() for p in (source, draft, existing, alias)}
    for path in (source, draft, existing, alias, output):
        q = run('splice_math.py', '--source', source, '--draft', draft, '--output', path)
        assert q.returncode != 0 and '拒绝' in q.stderr
        assert not output.exists()
        assert {p: p.read_bytes() for p in before} == before

    draft.write_text('译文 ⟦m1⟧。\n')
    q = run('splice_math.py', '--source', source, '--draft', draft, '--output', output)
    assert q.returncode == 0, q.stdout + q.stderr
    assert output.read_text() == '译文 $x_1$。\n'
    assert not list(root.glob('.splice-math-*'))
