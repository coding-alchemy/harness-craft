"""真实成品、完整绑定与显式视觉复用。"""
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject, TextStringObject

from translator_test_support import SCRIPTS, sha

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter
import verify_delivery as delivery
import verify_pdf as verifier


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def rewrite_pdf(path, mutate):
    writer = PdfWriter(clone_from=str(path))
    mutate(writer)
    output = io.BytesIO()
    writer.write(output)
    path.write_bytes(output.getvalue())


@pytest.fixture
def case(tmp_path):
    renderer = pytest.importorskip('pymupdf')
    root = tmp_path / 'delivery'
    old = tmp_path / 'history'
    reports = tmp_path / 'current-export'
    for folder in (root, old, reports):
        folder.mkdir()
    chapter = root / 'chapter.md'
    chapter.write_text('# 视觉样本\n\n> **来源**：https://example.org/paper\n\n'
                       '正文与[方法说明](https://example.org/method)。\n', encoding='utf-8')
    pdf = root / 'paper.pdf'
    report = reports / exporter.REPORT_NAME
    assert exporter.export([str(chapter)], pdf, reports) == 0
    record = {
        'version': 1, 'mode': 'pdf', 'delivery_root': str(root),
        'inputs': [chapter.name], 'outputs': [{'path': pdf.name, 'sha256': sha(pdf)}],
        'files': {chapter.name: 'chapter', pdf.name: 'pdf'},
        'checks': [{'tool': 'verify_pdf', 'args': [
            '--pdf', pdf.name, '--work-dir', str(reports), chapter.name]}],
        'reviews': [],
    }
    render = {'engine': 'pymupdf', 'version': renderer.VersionBind, 'dpi': 144,
              'colorspace': 'RGB', 'alpha': False, 'annots': True}
    history = delivery.prepare_reviews(str(root), record)
    for review in history['reviews']:
        review.update(status='closed', note='测试夹具中的已复核记录')
        if review['kind'] == 'visual':
            review['render'] = render
    historical_record = old / 'record.json'
    write_json(historical_record, history)
    old_pdf = old / pdf.name
    old_report = old / report.name
    shutil.copyfile(pdf, old_pdf)
    shutil.copyfile(report, old_report)
    rewrite_pdf(pdf, lambda writer: writer.add_metadata({'/Subject': '第二版元数据'}))
    assert sha(pdf) != sha(old_pdf)
    exported = json.loads(report.read_bytes())
    exported['pdf_sha256'] = sha(pdf)
    write_json(report, exported)
    record['outputs'][0]['sha256'] = sha(pdf)
    current = delivery.prepare_reviews(str(root), record)
    visual = next(review for review in current['reviews'] if review['kind'] == 'visual')
    assert visual['status'] == 'pending'
    visual.update(status='reused', note='显式申请复用原视觉记录', reuse={
        'original_review': {'record': '../history/record.json',
                            'sha256': sha(historical_record), 'target': pdf.name,
                            'kind': 'visual'},
        'old_pdf': {'path': '../history/paper.pdf', 'sha256': sha(old_pdf)},
        'old_report': {'path': '../history/export_report.json', 'sha256': sha(old_report)},
        'render': render,
    })
    for review in current['reviews']:
        if review['kind'] == 'link':
            assert review['status'] == 'pending'
            review.update(status='closed', note='当前链接目标另行核对')
    return root, current, visual, pdf, report, historical_record, old_pdf, old_report


def test_same_path_reuse_and_changed_links(case):
    root, current, visual, pdf, report, historical_record, old_pdf, _ = case
    record_path = root.parent / 'current.json'
    evidence = Path.home() / '.cache' / ('tdt-visual-reuse-' + uuid.uuid4().hex)
    historical_bytes = historical_record.read_bytes()
    write_json(record_path, current)
    command = [sys.executable, str(SCRIPTS / 'verify_delivery.py'), '--record',
               str(record_path), '--evidence-dir', str(evidence)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        index = evidence / 'delivery_index.json'
        valid_index = index.read_bytes()
        assert any(r['status'] == 'reused' for r in json.loads(valid_index)['reviews'])
        equivalent = verifier.compare_pdf_pages(str(old_pdf), str(pdf), visual['reuse']['render'])
        assert equivalent == {'equal': True, 'page_count': 1, 'different_pages': []}

        def change_link(writer):
            action = writer.pages[0]['/Annots'][0].get_object()['/A']
            action[NameObject('/URI')] = TextStringObject('https://example.org/wrong')

        rewrite_pdf(pdf, change_link)
        current['outputs'][0]['sha256'] = sha(pdf)
        exported = json.loads(report.read_bytes())
        exported['pdf_sha256'] = sha(pdf)
        write_json(report, exported)
        write_json(record_path, current)
        assert verifier.compare_pdf_pages(str(old_pdf), str(pdf), visual['reuse']['render'])['equal']
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and 'verify_pdf（exit 1）' in result.stderr
        assert index.read_bytes() == valid_index
        assert historical_record.read_bytes() == historical_bytes
    finally:
        shutil.rmtree(evidence, ignore_errors=True)


def test_reuse_rejects_nonvisual_context_changes(case, monkeypatch):
    root, _, visual, pdf, report, _, old_pdf, _ = case
    binding = visual['binding']
    check = delivery.check_visual_reuse
    assert check(visual, binding, [], str(root)) == []
    for name in ('checks', 'environment'):
        current = deepcopy(binding)
        if name == 'checks':
            current[name][0]['script_sha256'] = 'different checker'
        else:
            current[name]['pypdf'] = 'different dependency'
        assert check(visual, current, [], str(root))

    original_report = report.read_bytes()
    exported = json.loads(original_report)
    exported['unrecognized_field'] = {'kept': True}
    write_json(report, exported)
    changed = deepcopy(binding)
    changed['checks'][0]['facts']['files']['export_report'][1] = sha(report)
    assert check(visual, changed, [], str(root))
    report.write_bytes(original_report)

    changed_pdf = pdf.parent.parent / 'changed-layout.pdf'
    shutil.copyfile(pdf, changed_pdf)
    rewrite_pdf(changed_pdf, lambda writer: writer.pages[0].rotate(90))
    with pytest.raises(ValueError):
        verifier.compare_pdf_pages(str(old_pdf), str(changed_pdf),
                                   {**visual['reuse']['render'], 'dpi': 0})
    diff = verifier.compare_pdf_pages(str(old_pdf), str(changed_pdf), visual['reuse']['render'])
    assert diff == {'equal': False, 'page_count': 1, 'different_pages': [1]}
    monkeypatch.setattr(verifier, '_load_aid_renderer', lambda: None)
    assert check(visual, binding, [], str(root))


def test_reuse_requires_original_closed_and_current_items(case):
    root, _, visual, _, _, historical_record, old_pdf, _ = case
    binding = visual['binding']
    check = delivery.check_visual_reuse
    assert check(visual, binding, ['uncovered'], str(root))
    history = json.loads(historical_record.read_bytes())
    previous = next(review for review in history['reviews'] if review['kind'] == 'visual')
    previous['items'] = ['twice', 'twice']
    visual['items'] = ['twice', 'twice']

    def update_history():
        write_json(historical_record, history)
        visual['reuse']['original_review']['sha256'] = sha(historical_record)

    update_history()
    assert check(visual, binding, ['twice', 'twice'], str(root)) == []
    assert check(visual, binding, ['twice', 'twice', 'twice'], str(root))
    for status in ('reused', 'pending'):
        previous['status'] = status
        update_history()
        assert check(visual, binding, [], str(root))
    previous['status'] = 'closed'
    old_render = previous.pop('render')
    update_history()
    assert check(visual, binding, [], str(root))
    previous['render'] = old_render
    update_history()
    old_pdf.unlink()
    assert check(visual, binding, [], str(root))
