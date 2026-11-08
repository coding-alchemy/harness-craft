"""量测当前真实打印视图，并读取候选 PDF 的位置和导航。"""
from hashlib import sha256
import json
import sys

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter


def _book(tmp_path):
    toc = tmp_path / '00_目录.md'
    chapter = tmp_path / '01_正文.md'
    toc.write_text('# 目录\n\n- [第一章](01_正文.md#第一章)\n')
    chapter.write_text('# 第一章\n\n> **来源**：https://example.org/paper\n\n正文。\n')
    view = tmp_path / 'view.json'
    view.write_text(json.dumps({
        'version': 1, 'exclusions': [],
        'inputs': [{'path': str(p), 'sha256': sha256(p.read_bytes()).hexdigest()}
                   for p in (toc, chapter)],
        'document_title': {'original': '第一章', 'chinese': '打印试验',
                           'basis': '试验书名'},
    }))
    return toc, chapter, view


def test_print_width_and_toc_second_pass(tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.set_content('<style>body{margin:0}</style><table id="wide" style="width:959px">'
                         '<tr><td>Print layout overflow</td></tr></table>')
        assert page.locator('#wide').bounding_box()['width'] < 1280
        checks = exporter.collect_print_checks(page, width_px=673)
        assert checks['viewport_width'] == 673
        assert [x['id'] for x in checks['overflow'] if x['id']] == ['wide']
        assert page.evaluate("matchMedia('print').matches")
        browser.close()

    toc, chapter, view = _book(tmp_path)
    old = {p: p.read_bytes() for p in (toc, chapter, view)}
    update = exporter.update_toc_nav
    observe = exporter.collect_print_checks
    measurements = []
    prints = []
    print_page = playwright.Page.pdf

    def widen_after_update(chapter, entries, pages):
        update(chapter, entries, pages)
        wide = chapter.soup.new_tag('table', id='second-pass', style='width:959px')
        row = chapter.soup.new_tag('tr')
        cell = chapter.soup.new_tag('td')
        cell.string = 'Wide second pass'
        row.append(cell)
        wide.append(row)
        chapter.soup.find('nav').append(wide)

    def measure(page, *, width_px):
        result = observe(page, width_px=width_px)
        measurements.append(result)
        return result

    def print_once(page, **kwargs):
        prints.append(kwargs['path'])
        return print_page(page, **kwargs)

    monkeypatch.setattr(exporter, 'update_toc_nav', widen_after_update)
    monkeypatch.setattr(exporter, 'collect_print_checks', measure)
    monkeypatch.setattr(playwright.Page, 'pdf', print_once)
    pdf, work = tmp_path / 'book.pdf', tmp_path / 'work'
    pdf.write_bytes(b'earlier result')
    assert exporter.export([str(toc), str(chapter)], pdf, work,
                           view_declaration_path=view) == 1
    assert len(measurements) == 2
    assert len(prints) == 1
    assert not measurements[0]['overflow']
    assert any(x['id'] == 'second-pass' for x in measurements[1]['overflow'])
    assert pdf.read_bytes() == b'earlier result'
    assert {p: p.read_bytes() for p in old} == old


def test_equation_label_and_numeric_cells(tmp_path):
    pymupdf = pytest.importorskip('pymupdf')
    playwright = pytest.importorskip('playwright.sync_api')
    from latexml_test_support import IDENTITY, adapt_fixture

    snapshot = tmp_path / 'native.html'
    snapshot.write_text(
        '<article class="ltx_document"><h1>T</h1><div class="ltx_subequations">'
        '<table class="ltx_equation"><tr><td>'
        '<math alttext="\\begin{aligned}a&amp;=11\\\\\nb&amp;=22\\end{aligned}" display="block">'
        '<mi>a</mi></math></td><td class="ltx_eqn_eqno">(14)</td></tr></table></div></article>')
    _, native, payload, _ = adapt_fixture(snapshot, IDENTITY)
    basis = tmp_path / 'adaptation.json'
    basis.write_text(json.dumps(payload))
    source = tmp_path / 'chapter.md'
    source.write_text(
        '# T（打印几何）\n\n> **来源**：https://example.org/print\n\n'
        + '占位段落用于接近页尾。\n\n' * 30
        + native.split('\n\n', 1)[1].rstrip() + '\n\n'
        + '| 分组 | 结果 | 时延 |\n| --- | --- | --- |\n'
        + '| 跨流排序分组长文本' + '可自然折行' * 38 + ' | -12.5% | 100 ms |\n')
    pdf, work = tmp_path / 'equation.pdf', tmp_path / 'work'
    assert exporter.export([str(source)], pdf, work, source_adaptation_path=basis) == 0
    with pymupdf.open(pdf) as doc:
        labels = [(p.number, box) for p in doc for box in p.search_for('(14)')]
        maths = [(p.number, box) for p in doc for box in p.search_for('22')]
        assert len(labels) == len(maths) == 1
        assert labels[0][0] == maths[0][0]
        assert maths[0][1].x1 < labels[0][1].x0
        assert sum(len(p.search_for('-12.5%')) for p in doc) == 1
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page()
        page.goto((work / exporter.HTML_NAME).as_uri())
        exporter.collect_print_checks(page, width_px=round(exporter.CONTENT_WIDTH_PX))
        assert page.locator('.equation-unit > .equation-label').inner_text() == '(14)'
        assert page.locator('td.table-number').all_text_contents() == ['-12.5%', '100 ms']
        browser.close()


def test_anchor_table_and_toc_navigation(tmp_path):
    pymupdf = pytest.importorskip('pymupdf')
    from pypdf import PdfWriter
    from pypdf.generic import NameObject
    import verify_pdf as verifier

    toc, chapter, view = _book(tmp_path)
    chapter.write_text(
        '# 第一章\n\n> **来源**：https://example.org/paper\n\n'
        '返回至[单元格](#cell)或[另格](#cell-other)。\n\n'
        '| 内容 | 值 |\n| --- | --- |\n'
        '| <a id="cell"></a>这里是锚点 | <a id="cell-other"></a>[书目](#ref) |\n\n'
        + '分页前的普通段落。\n\n' * 42
        + '## 参考文献\n\n<a id="ref"></a>书目正文和[回到表格](#cell)。\n')
    doc = json.loads(view.read_text())
    doc['inputs'][1]['sha256'] = sha256(chapter.read_bytes()).hexdigest()
    view.write_text(json.dumps(doc))
    before = {p: p.read_bytes() for p in (toc, chapter, view)}
    pdf, work = tmp_path / 'toc.pdf', tmp_path / 'work'
    assert exporter.export([str(toc), str(chapter)], pdf, work, view_declaration_path=view) == 0
    args = verifier.parse_args(['--pdf', str(pdf), '--work-dir', str(work),
                                '--view-declaration', str(view), str(toc), str(chapter)])
    ok, result = verifier.run_verification(args)
    assert ok, result
    with pymupdf.open(pdf) as out:
        targets = {text: next((page.number, page.search_for(text)[0]) for page in out
                              if page.search_for(text))
                   for text in ('这里是锚点', '书目正文')}
        for label, text, fragment in [('单元格', '这里是锚点', 'cell'),
                                      ('书目', '书目正文', 'ref'),
                                      ('回到表格', '这里是锚点', 'cell')]:
            target_page, target = targets[text]
            matches = [link for page in out for box in page.search_for(label)
                       for link in page.get_links() if link['from'].intersects(box)]
            link, = matches
            assert link['page'] == target_page
            assert link['nameddest'].endswith('-' + fragment)
            # Chromium 的命名目的地点用 PDF 坐标，滚动后上方保留页边距。
            point = out[target_page].rect.height - link['to'].y
            assert 0 <= target.y0 - point <= 60
        report = json.loads((work / exporter.REPORT_NAME).read_text())
        assert report['toc']['prints'] >= 2
        assert out[0].get_links()[0]['page'] == report['toc']['entries'][0]['page'] - 1
    writer = PdfWriter(clone_from=str(pdf))
    annot = next(ref.get_object() for ref in writer.pages[1]['/Annots']
                 if ref.get_object().get('/Dest') == '/ch02-cell')
    annot[NameObject('/Dest')] = NameObject('/ch02-cell-other')
    damaged = tmp_path / 'wrong-anchor.pdf'
    writer.write(damaged)
    report['pdf_sha256'] = sha256(damaged.read_bytes()).hexdigest()
    (work / exporter.REPORT_NAME).write_text(json.dumps(report))
    args.pdf = str(damaged)
    ok, result = verifier.run_verification(args)
    assert not ok
    assert any(f['code'] == 'internal-anchor-target' for f in result['failures']), result
    assert {p: p.read_bytes() for p in before} == before
