"""真实 SVG 子资源、导出负载和 PDF 像素回归。"""
from hashlib import sha256
from io import BytesIO
import json
import os
import sys

from PIL import Image
import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter
import verify_pdf as verifier
from _verification import resource_identity_digest


def _inputs(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    translated = tmp_path / 'translated'
    translated.mkdir()
    svg = source / 'diagram.svg'
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" viewBox="0 0 360 180">'
        '<style>@import "colors.css";</style>'
        '<rect class="fill" width="360" height="180"/>'
        '<image href="tile.png" x="30" y="20" width="60" height="60"/>'
        '</svg>')
    css = source / 'colors.css'
    css.write_text('.fill {fill: #2266aa;}')
    Image.new('RGB', (4, 4), '#aa5500').save(source / 'tile.png')
    chapter = translated / 'chapter.md'
    chapter.write_text('# SVG 几何\n\n> **来源**：https://example.org/figure\n\n'
                       '![图](../source/diagram.svg)\n\n原图题。\n')
    mapping = translated / 'images_display.json'
    mapping.write_text(json.dumps({'version': 1, 'entries': [{
        'markdown': chapter.name, 'occurrence': 1,
        'image': '../source/diagram.svg', 'sha256': sha256(svg.read_bytes()).hexdigest(),
        'source': {'resource_sha256': resource_identity_digest(str(svg))},
        'width': {'value': 240, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None},
    }]}))
    return chapter, mapping, svg, css


def _export(tmp_path, chapter, mapping):
    pdf, work = tmp_path / 'figure.pdf', tmp_path / 'work'
    assert exporter.export([str(chapter)], pdf, work, images_display_paths=[str(mapping)]) == 0
    return pdf, work


def _verify(pdf, work, chapter, mapping):
    args = verifier.parse_args(['--pdf', str(pdf), '--work-dir', str(work),
                                '--images-display', str(mapping), str(chapter)])
    return verifier.run_verification(args)


def test_svg_payload_identity_and_dimensions(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    chapter, mapping, svg, css = _inputs(tmp_path)
    original = svg.read_bytes()
    pdf, work = _export(tmp_path, chapter, mapping)
    report = json.loads((work / exporter.REPORT_NAME).read_text())
    record, = report['svg_renders']
    assert record['source'] == [str(svg), resource_identity_digest(str(svg))]
    assert set(record['dependencies']) == {str(css), str(svg.parent / 'tile.png')}
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert ok, facts
    current = verifier.PdfFacts(str(pdf))
    raster, = current.reader.pages[0].images
    drawn, = verifier.collect_drawn_images(current)[0]
    assert drawn[0] == pytest.approx(180, abs=verifier.IMAGE_WIDTH_TOLERANCE_PT)
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        payload, _ = exporter.render_svg_payload(
            str(svg), width_px=record['embedded']['width'], height_px=record['embedded']['height'],
            resource_registry={}, browser=browser)
        reference = Image.open(BytesIO(payload)).convert('RGB')
        browser.close()
    assert raster.image.convert('RGB').tobytes() == reference.tobytes()
    assert reference.getpixel((40, 35)) == (170, 85, 0)
    assert reference.getpixel((200, 120)) == (34, 102, 170)
    assert svg.read_bytes() == original


def test_svg_dependency_or_pixel_damage_rejected(tmp_path):
    from pypdf import PdfWriter

    chapter, mapping, svg, css = _inputs(tmp_path)
    original = svg.read_bytes()
    pdf, work = _export(tmp_path, chapter, mapping)
    saved_css = css.read_bytes()
    css.write_text('.fill {fill: red;}')
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert not ok and any('svg' in x['code'] for x in facts['failures'])
    css.write_bytes(saved_css)
    writer = PdfWriter(clone_from=str(pdf))
    raster, = writer.pages[0].images
    raster.replace(Image.new('RGB', raster.image.size, '#ffffff'))
    damaged = tmp_path / 'damaged.pdf'
    writer.write(damaged)
    report_path = work / exporter.REPORT_NAME
    report = json.loads(report_path.read_text())
    report['pdf_sha256'] = sha256(damaged.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report))
    ok, facts = _verify(damaged, work, chapter, mapping)
    assert not ok and any(x['code'] == 'svg-pdf-pixels' for x in facts['failures'])
    report['pdf_sha256'] = sha256(pdf.read_bytes()).hexdigest()
    del report['svg_renders'][0]['embedded']['width']
    report_path.write_text(json.dumps(report))
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert not ok and any(x['code'] == 'svg-render-drift' for x in facts['failures'])
    assert svg.read_bytes() == original


def test_resource_bases_do_not_guess_by_name(tmp_path, monkeypatch):
    chapter, mapping, svg, _ = _inputs(tmp_path)
    unrelated = chapter.parent / 'diagram.svg'
    unrelated.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
                         '<rect width="20" height="20" fill="green"/></svg>')
    monkeypatch.chdir(tmp_path)
    assert os.getcwd() != str(chapter.parent)
    pdf, work = _export(tmp_path, chapter, mapping)
    ok, facts = _verify(pdf, work, chapter, mapping)
    assert ok, facts
    report = json.loads((work / exporter.REPORT_NAME).read_text())
    assert report['svg_renders'][0]['source'][0] == str(svg)
    old = pdf.read_bytes()
    chapter.write_text(chapter.read_text().replace('../source/diagram.svg', 'diagram.svg'))
    assert exporter.export([str(chapter)], pdf, work, images_display_paths=[str(mapping)]) == 1
    assert pdf.read_bytes() == old
