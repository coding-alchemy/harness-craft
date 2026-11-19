"""第 2 批 R8：图片适配声明只在导出时生效，不改任何图片文件。"""
from hashlib import sha256
import json
import shutil
import sys
from pathlib import Path

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter

PNG = Path(__file__).resolve().parent / 'fixtures/valid_1x1.png'
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" viewBox="0 0 360 180">'
       '<rect width="360" height="180" fill="#2266aa"/></svg>')


def declare(tmp_path, **item):
    item.setdefault('basis', '测试：用户批准的裁剪')
    path = tmp_path / 'image_adaptations.json'
    path.write_text(json.dumps({'version': 1, 'images': [item]}), encoding='utf-8')
    return path


def svg_file(tmp_path, text=SVG):
    path = tmp_path / 'figure.svg'
    path.write_text(text)
    return path, sha256(path.read_bytes()).hexdigest()


def test_valid_svg_crop_and_width_loaded(tmp_path):
    svg, digest = svg_file(tmp_path)
    loaded = exporter.load_image_adaptations(declare(
        tmp_path, image='figure.svg', sha256=digest, viewbox='0 20 360 160',
        display_width_px=200))
    item = loaded['images'][str(svg.resolve())]
    assert item['viewbox'] == (0.0, 20.0, 360.0, 160.0)
    assert item['display_width_px'] == 200.0
    assert loaded['path'] == str((tmp_path / 'image_adaptations.json').resolve())
    assert svg.read_text() == SVG


def test_svg_without_viewbox_uses_width_and_height(tmp_path):
    svg, digest = svg_file(tmp_path, SVG.replace(' viewBox="0 0 360 180"', ''))
    loaded = exporter.load_image_adaptations(declare(
        tmp_path, image='figure.svg', sha256=digest, viewbox='0 0 360 90'))
    assert loaded['images'][str(svg.resolve())]['viewbox'] == (0.0, 0.0, 360.0, 90.0)


@pytest.mark.parametrize('change, message', [
    ({'sha256': '0' * 64}, 'sha256'),
    ({'viewbox': '0 20 400 160'}, '超出原图范围'),
    ({'viewbox': '0 20 360'}, 'viewbox'),
    ({'viewbox': None, 'display_width_px': None}, '至少声明'),
    ({'display_width_px': 900}, 'display_width_px'),
    ({'basis': ' '}, 'basis'),
])
def test_invalid_declarations_rejected(tmp_path, change, message):
    _svg, digest = svg_file(tmp_path)
    item = {'image': 'figure.svg', 'sha256': digest, 'viewbox': '0 20 360 160',
            'display_width_px': 200}
    item.update(change)
    with pytest.raises(exporter.ExportError, match=message):
        exporter.load_image_adaptations(declare(tmp_path, **item))


def test_bitmap_crop_not_supported(tmp_path):
    shutil.copy(PNG, tmp_path / 'figure.png')
    digest = sha256((tmp_path / 'figure.png').read_bytes()).hexdigest()
    with pytest.raises(exporter.ExportError, match='位图裁剪不支持'):
        exporter.load_image_adaptations(declare(
            tmp_path, image='figure.png', sha256=digest, viewbox='0 0 1 1'))
    loaded = exporter.load_image_adaptations(declare(
        tmp_path, image='figure.png', sha256=digest, display_width_px=120))
    assert loaded['images'][str((tmp_path / 'figure.png').resolve())]['viewbox'] is None


def test_no_path_means_no_adaptations():
    assert exporter.load_image_adaptations(None) is None


from types import SimpleNamespace


def _chapter(path):
    return SimpleNamespace(path=Path(path))


def test_apply_updates_every_occurrence_and_reports_gaps(tmp_path):
    svg, digest = svg_file(tmp_path)
    adaptations = exporter.load_image_adaptations(declare(
        tmp_path, image='figure.svg', sha256=digest, viewbox='0 20 360 160',
        display_width_px=200))
    first, second = _chapter(tmp_path / 'a.md'), _chapter(tmp_path / 'b.md')
    enumerations = {first.path: [{'path': str(svg), 'line': 3}],
                    second.path: [{'path': str(svg), 'line': 5}, {'path': str(svg), 'line': 9}]}
    binding = lambda: {'px': 476.0, 'record': {'applied_px': 476.0, 'capped': False},
                       'map_path': tmp_path / 'm.json', 'source_resource': None}
    bindings = {first.path: {1: binding()}, second.path: {1: binding()}}
    diagnostics = []
    exporter.apply_image_adaptations([first, second], enumerations, bindings, adaptations,
                                     diagnostics)
    for held in (bindings[first.path][1], bindings[second.path][1]):
        assert held['px'] == 200.0
        assert held['record']['applied_px'] == 200.0
        assert held['viewbox'] == (0.0, 20.0, 360.0, 160.0)
        assert held['adaptation']['basis'] == '测试：用户批准的裁剪'
    assert [d['code'] for d in diagnostics] == ['image-adaptation-unbound']
    assert diagnostics[0]['line'] == 9

    unused = []
    exporter.apply_image_adaptations([first], {first.path: []}, {first.path: {}},
                                     adaptations, unused)
    assert [d['code'] for d in unused] == ['image-adaptation-unused']


def test_svg_dimensions_follow_the_declared_viewbox(tmp_path):
    svg, _digest = svg_file(tmp_path)
    facts = exporter._svg_resource_facts(str(svg))
    record = {'kind': 'SVG', 'path': str(svg), **facts}
    binding = {'px': 200.0, 'viewbox': (0.0, 20.0, 360.0, 160.0), 'source_resource': None,
               'map_path': tmp_path / 'm.json', 'record': {'width': None}}
    assert exporter.svg_print_dimensions(record, binding) == (360, 160, 200.0)
    plain = dict(binding)
    plain.pop('viewbox')
    assert exporter.svg_print_dimensions(record, plain) == (360, 180, 200.0)


def test_payload_is_cropped_in_the_browser(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from io import BytesIO
    from PIL import Image
    svg, _digest = svg_file(tmp_path, SVG.replace(
        '</svg>', '<rect width="360" height="20" fill="#ff0000"/></svg>'))
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        payload, evidence = exporter.render_svg_payload(
            str(svg), width_px=360, height_px=160, resource_registry={}, browser=browser,
            viewbox=(0.0, 20.0, 360.0, 160.0))
        plain, plain_evidence = exporter.render_svg_payload(
            str(svg), width_px=360, height_px=180, resource_registry={}, browser=browser)
        browser.close()
    assert Image.open(BytesIO(payload)).convert('RGB').getpixel((10, 2)) == (34, 102, 170)
    assert Image.open(BytesIO(plain)).convert('RGB').getpixel((10, 2)) == (255, 0, 0)
    assert evidence['render']['viewbox'] == [0.0, 20.0, 360.0, 160.0]
    assert 'viewbox' not in plain_evidence['render']


from test_svg_print_payload import _inputs, _verify
import verify_pdf as verifier


def _declare_for_inputs(tmp_path, svg, **extra):
    item = {'image': 'source/diagram.svg', 'sha256': sha256(svg.read_bytes()).hexdigest(),
            'viewbox': '0 20 360 160', 'display_width_px': 200,
            'basis': '测试：裁去顶部 20 单位'}
    item.update(extra)
    path = tmp_path / 'image_adaptations.json'
    path.write_text(json.dumps({'version': 1, 'images': [item]}), encoding='utf-8')
    return path


def _export_with(tmp_path, chapter, mapping, declaration):
    pdf, work = tmp_path / 'figure.pdf', tmp_path / 'work'
    assert exporter.export([str(chapter)], pdf, work, images_display_paths=[str(mapping)],
                           image_adaptations_path=str(declaration)) == 0
    return pdf, work


def test_export_applies_crop_and_width_without_touching_files(tmp_path):
    pytest.importorskip('playwright.sync_api')
    chapter, mapping, svg, _css = _inputs(tmp_path)
    original = svg.read_bytes()
    declaration = _declare_for_inputs(tmp_path, svg)
    pdf, work = _export_with(tmp_path, chapter, mapping, declaration)
    report = json.loads((work / exporter.REPORT_NAME).read_text())
    assert report['image_adaptations']['path'] == str(declaration.resolve())
    row, = report['svg_renders']
    assert row['render']['viewbox'] == [0, 20, 360, 160]
    # 裁剪后 360 宽、显示 200px：不足 2 倍，宽高同乘 2（R18）。
    assert (row['embedded']['width'], row['embedded']['height']) == (720, 320)
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert ok, facts
    drawn, = verifier.collect_drawn_images(verifier.PdfFacts(str(pdf)))[0]
    assert drawn[0] == pytest.approx(150, abs=verifier.IMAGE_WIDTH_TOLERANCE_PT)
    assert svg.read_bytes() == original


def test_declaration_changed_after_export_fails_verification(tmp_path):
    pytest.importorskip('playwright.sync_api')
    chapter, mapping, svg, _css = _inputs(tmp_path)
    declaration = _declare_for_inputs(tmp_path, svg)
    pdf, work = _export_with(tmp_path, chapter, mapping, declaration)
    _declare_for_inputs(tmp_path, svg, basis='导出后改了依据')
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert not ok
    assert 'image-adaptations-mismatch' in [f['code'] for f in facts['failures']]


def test_unused_declaration_blocks_export(tmp_path):
    chapter, mapping, svg, _css = _inputs(tmp_path)
    other = tmp_path / 'other.svg'
    other.write_text(SVG)
    declaration = tmp_path / 'image_adaptations.json'
    declaration.write_text(json.dumps({'version': 1, 'images': [{
        'image': 'other.svg', 'sha256': sha256(other.read_bytes()).hexdigest(),
        'display_width_px': 100, 'basis': '测试'}]}), encoding='utf-8')
    pdf, work = tmp_path / 'figure.pdf', tmp_path / 'work'
    assert exporter.export([str(chapter)], pdf, work, images_display_paths=[str(mapping)],
                           image_adaptations_path=str(declaration)) != 0
    assert not pdf.exists()
