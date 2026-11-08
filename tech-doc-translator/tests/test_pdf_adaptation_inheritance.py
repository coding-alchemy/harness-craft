"""依据顺序与实际核验/交付事实共用，覆盖成品和漂移。"""
from hashlib import sha256
import json
import sys

from latexml_test_support import IDENTITY, adapt_fixture
from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter
import verify_delivery as delivery
import verify_pdf as verifier


def _export(tmp_path, size):
    inputs = []
    bases = []
    originals = []
    for index, tex in enumerate(('a+\nb', 'x+\ny')[:size]):
        snapshot = tmp_path / f'original-{index}.html'
        snapshot.write_text(
            '<article class="ltx_document"><h1>T</h1>'
            f'<p>With <math alttext="{tex}" display="inline"><mi>x</mi></math>.</p></article>')
        _, md, payload, _ = adapt_fixture(snapshot, IDENTITY)
        basis = tmp_path / f'basis-{index}.json'
        basis.write_text(json.dumps(payload))
        chapter = tmp_path / f'chapter-{index}.md'
        _, body = md.split('\n\n', 1)
        chapter.write_text(f'# T（第{index + 1}章）\n\n> **来源**：https://example.org/paper\n\n'
                           + body.replace('With ', '其中 '))
        inputs.append(chapter)
        bases.append(basis)
        originals.append(snapshot)
    view = tmp_path / 'view.json'
    view.write_text(json.dumps({
        'version': 1, 'exclusions': [],
        'inputs': [{'path': str(p), 'sha256': sha256(p.read_bytes()).hexdigest()} for p in inputs],
        'document_title': {'original': 'T（第1章）', 'chinese': '试验论文', 'basis': '来源对照'},
    }))
    pdf, work = tmp_path/'paper.pdf', tmp_path/'work'
    assert exporter.export([str(p) for p in inputs], pdf, work,
                           view_declaration_path=view,
                           source_adaptation_path=[str(p) for p in bases]) == 0
    args = ['--pdf', pdf.name, '--work-dir', work.name, '--view-declaration', view.name,
            *(p.name for p in inputs)]
    return work / exporter.REPORT_NAME, args, bases, originals


def _verify(tmp_path, args, extra=()):
    effective = [str(tmp_path / value) if value in {'paper.pdf', 'work', 'view.json'}
                 or value.startswith(('chapter-', 'basis-')) else value
                 for value in (*args, *extra)]
    return verifier.run_verification(verifier.parse_args(effective))


def test_single_and_multiple_adaptations_inherit(tmp_path):
    for size in (1, 2):
        root = tmp_path / str(size)
        root.mkdir()
        report_path, args, bases, _ = _export(root, size)
        report = json.loads(report_path.read_text())
        paths = [str(p.resolve()) for p in bases]
        assert verifier.resolve_source_adaptations(
            verifier.parse_args(args), report, root=str(root)) == paths
        ok, result = _verify(root, args)
        assert ok, result
        explicit = [arg for p in bases for arg in ('--source-adaptation', p.name)]
        ok, result = _verify(root, args, explicit)
        assert ok, result
        inherited, _ = delivery._check_facts(str(root), 'verify_pdf', args, 1)
        declared, _ = delivery._check_facts(str(root), 'verify_pdf', [*args, *explicit], 1)
        assert inherited == declared
        facts = [[str(p.resolve()), sha256(p.read_bytes()).hexdigest()] for p in bases]
        assert inherited['files']['source_adaptation'] == (facts[0] if size == 1 else facts)
        if size == 1:
            report.pop('source_adaptation')
            report_path.write_text(json.dumps(report))
            ok, result = _verify(root, args, explicit)
            assert ok, result


def test_explicit_conflict_and_dependency_drift(tmp_path):
    _, args, bases, originals = _export(tmp_path, 2)
    swapped = ['--source-adaptation', bases[1].name, '--source-adaptation', bases[0].name]
    for extra in (swapped, swapped[:2]):
        ok, result = _verify(tmp_path, args, extra)
        assert not ok and any(f['code'] == 'source-adaptation-mismatch' for f in result['failures'])

    path = bases[1]
    original = path.read_bytes()
    path.unlink()
    ok, result = _verify(tmp_path, args)
    assert not ok and any('依据' in f['message'] and path.name in f['message']
                          for f in result['failures'])
    path.write_bytes(original + b'\n')
    ok, result = _verify(tmp_path, args)
    assert not ok and any('摘要' in f['message'] and path.name in f['message']
                          for f in result['failures'])
    path.write_bytes(original)
    originals[1].write_text(originals[1].read_text()+'\n<p>Drift</p>')
    ok, result = _verify(tmp_path, args)
    assert not ok and any('快照' in f['message'] for f in result['failures'])
