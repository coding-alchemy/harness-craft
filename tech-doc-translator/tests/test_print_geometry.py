"""量测当前真实打印视图，并读取候选 PDF 的位置和导航。"""
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter


def check_link_failures(pdf_path, input_paths, view=None):
    import verify_pdf as verifier

    failures = []
    chapters = verifier.reparse_inputs(input_paths, failures, view_declaration_path=view)
    assert not failures, failures
    pdf = verifier.PdfFacts(pdf_path)
    heading_pages = {}
    verifier.check_headings(chapters, pdf, failures, heading_pages)
    bounds = verifier.chapter_bounds(chapters, pdf, heading_pages, failures)
    assert not failures, failures
    verifier.check_links(chapters, pdf, bounds, heading_pages, failures, [])
    return failures


@pytest.fixture(scope='module')
def printed_links(tmp_path_factory):
    directory = tmp_path_factory.mktemp('link-geometry')
    chapter = directory/'chapter.md'
    image = directory/'pixel.png'
    image.write_bytes((Path(__file__).parent/'fixtures/valid_1x1.png').read_bytes())
    long = '可换行的链接文字' * 32
    source = ('# 验证文档\n\n> **来源**：https://example.org/print\n\n'
              '[前往甲](#目标甲) 与 [前往乙](#目标乙)。\n\n'
              '[重复链接](https://example.org/)\n\n'
              '[重复链接](#目标甲)\n\n'
              '[重复链接](#目标乙)\n\n'
              f'[{long}](#目标甲)\n\n'
              '[![点击图片](pixel.png)](#目标乙)\n\n'
              '[段落](#para) [别名](#alias) [表格](#table) '
              '[图片](#image) [代码](#code) [页首](#entry) [行内](#inline)。\n\n'
              '<a id="entry"></a>\n\n## 目标甲\n\n甲的正文。\n\n'
              '## 目标乙\n\n乙的正文。\n\n'
              '<a id="para"></a>\n<a id="alias"></a>\n\n段落目标。\n\n'
              '<a id="table"></a>\n\n| 列一 | 列二 |\n| --- | --- |\n'
              + ''.join(f'| 甲{index:02d} | 乙 |\n' for index in range(46))
              + '\n<a id="image"></a>\n\n![目标图片](pixel.png)\n\n'
              '前缀 <a id="inline"></a>行内目的地。\n\n'
              '<a id="code"></a>\n\n```text\n'
              + ''.join(f'code line {index:02d}\n' for index in range(92))
              + '```\n\n脚注引用[^n]。\n\n[^n]: 脚注内容。\n')
    chapter.write_text(source)
    pdf = directory/'links.pdf'
    assert exporter.export([str(chapter)], pdf, directory/'work') == 0
    return directory, chapter, pdf


def _destination(writer, fragment):
    from urllib.parse import unquote

    return next(str(key) for key in writer.named_destinations
                if unquote(str(key)).endswith('-'+fragment))


def _annotations(writer, destination):
    return [(page, ref) for page in writer.pages for ref in page.get('/Annots', [])
            if str(ref.get_object().get('/Dest')) == destination]


def _damaged_copy(printed_links, name, mutate):
    from pypdf import PdfWriter

    directory, chapter, healthy = printed_links
    writer = PdfWriter(clone_from=healthy)
    mutate(writer)
    output = directory/(name+'.pdf')
    writer.write(output)
    return check_link_failures(output, [chapter])


def test_same_page_destination_swap_is_rejected(printed_links):
    from pypdf.generic import NameObject

    _, chapter, healthy = printed_links
    assert check_link_failures(healthy, [chapter]) == []

    def swap(writer):
        a, b = (_destination(writer, f) for f in ('目标甲', '目标乙'))
        _, first = _annotations(writer, a)[0]
        _, second = _annotations(writer, b)[0]
        first.get_object()[NameObject('/Dest')] = NameObject(b)
        second.get_object()[NameObject('/Dest')] = NameObject(a)

    assert any(x['code'] == 'internal-link-target'
               for x in _damaged_copy(printed_links, 'same-page', swap))


def test_named_destination_table_swap_is_rejected(printed_links):
    from pypdf.generic import NameObject

    def swap(writer):
        a, b = (_destination(writer, f) for f in ('目标甲', '目标乙'))
        tree = writer.root_object.get('/Dests').get_object()
        first, second = tree.raw_get(a), tree.raw_get(b)
        tree[NameObject(a)], tree[NameObject(b)] = second, first

    assert any(x['code'] == 'internal-link-target'
               for x in _damaged_copy(printed_links, 'name-swap', swap))


def test_equivalent_direct_array_destination_passes(printed_links):
    from pypdf.generic import NameObject

    def use_array(writer):
        target = _destination(writer, 'para')
        _, ref = _annotations(writer, target)[0]
        ref.get_object()[NameObject('/Dest')] = writer.named_destinations[target].dest_array

    assert _damaged_copy(printed_links, 'direct', use_array) == []


def test_duplicate_labels_keep_broken_instance_slot(printed_links):
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    _, chapter, _ = printed_links
    bad_line = chapter.read_text().splitlines().index('[重复链接](#目标甲)')+1

    def change_action(writer):
        target = _destination(writer, '目标甲')
        _, ref = _annotations(writer, target)[1]
        link = ref.get_object()
        del link['/Dest']
        link[NameObject('/A')] = DictionaryObject({
            NameObject('/S'): NameObject('/URI'),
            NameObject('/URI'): TextStringObject('file:///tmp/deleted.html'),
        })

    failures = _damaged_copy(printed_links, 'duplicate', change_action)
    assert any(x.get('line') == bad_line for x in failures), failures


@pytest.mark.parametrize('kind', ['wrap', 'image'])
def test_wrapped_and_image_links_require_own_annotations(printed_links, kind):
    def remove_annotation(writer):
        target = _destination(writer, '目标甲' if kind == 'wrap' else '目标乙')
        annotations = _annotations(writer, target)
        assert len(annotations) > 3 if kind == 'wrap' else len(annotations) >= 3
        page, ref = annotations[2]
        page['/Annots'].remove(ref)

    errors = _damaged_copy(printed_links, kind+'-missing', remove_annotation)
    assert any(x['code'] == 'internal-link-instance' for x in errors), errors


def test_aliases_and_cross_page_object_start_pass(printed_links):
    from pypdf import PdfReader
    from pypdf.generic import NameObject

    _, chapter, healthy = printed_links
    pdf = PdfReader(healthy)
    assert len(pdf.pages) > 3
    rows = [page.extract_text() for page in pdf.pages]
    first_page = next(i for i, text in enumerate(rows) if '甲00' in text)
    last_page = next(i for i, text in enumerate(rows) if '甲45' in text)
    assert first_page < last_page
    assert check_link_failures(healthy, [chapter]) == []

    def use_alias(writer):
        _, ref = _annotations(writer, _destination(writer, 'para'))[0]
        ref.get_object()[NameObject('/Dest')] = NameObject(_destination(writer, 'alias'))

    assert _damaged_copy(printed_links, 'equivalent-alias', use_alias) == []


def test_destination_coordinates_match_actual_object_geometry(tmp_path):
    import pymupdf
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    from verify_pdf import PdfFacts, _destination_origin

    physical_positions = []
    with sync_playwright() as runtime, runtime.chromium.launch() as browser:
        page = browser.new_page()
        for margin in (8, 30):
            source = tmp_path/f'page-{margin}.html'
            source.write_text(f'<style>@page{{size:A4;margin:{margin}mm 16mm}}'
                              'body{margin:0;font:16px/1.5 sans-serif}</style>'
                              '<p><a href="#one">jump</a></p>'
                              '<p id="one">TARGET ONE</p><p>TARGET TWO</p>')
            page.goto(source.as_uri())
            out = tmp_path/f'page-{margin}.pdf'
            page.pdf(path=out, tagged=True, prefer_css_page_size=True)
            raw = PdfReader(out)
            origin_x, top_margin = _destination_origin(raw.pages[0])
            assert top_margin == pytest.approx(margin * 72 / 25.4, abs=0.65)
            dest = raw.named_destinations['/one']
            facts = PdfFacts(out)
            run = next(event for event in facts.drawn_events[0]
                       if 'TARGET ONE' in event['text'])
            physical_y = dest.top - top_margin
            with pymupdf.open(out) as doc:
                first = doc[0].search_for('TARGET ONE')[0]
                second = doc[0].search_for('TARGET TWO')[0]
                page_top = doc[0].rect.height
                assert origin_x + dest.left == pytest.approx(first.x0, abs=0.8)
                assert run['baseline_y_pt'] <= physical_y <= run['baseline_y_pt'] + 18
                assert page_top - physical_y < first.y1 < second.y0
            physical_positions.append((dest.top, physical_y, run['baseline_y_pt']))
    first, second = physical_positions
    assert first[0] == second[0]
    assert first[1] - second[1] == pytest.approx(first[2] - second[2], abs=0.8)


def test_cross_chapter_target_is_bound_to_own_link(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject

    a, b = tmp_path/'a.md', tmp_path/'b.md'
    a.write_text('# 章一\n\n> **来源**：https://example.org/a\n\n'
                 '[同章](#同名) [跨章](b.md#同名) [另一条](b.md#同名)。\n\n## 同名\n\n甲。\n')
    b.write_text('# 章二\n\n> **来源**：https://example.org/b\n\n## 同名\n\n乙。\n')
    view = tmp_path/'view.json'
    view.write_text(json.dumps({'version': 1, 'exclusions': [], 'inputs': [
        {'path': str(p), 'sha256': sha256(p.read_bytes()).hexdigest()} for p in (a,b)],
        'document_title': {'original': 'Link geometry', 'chinese': '跨章导航', 'basis': '测试'}}))
    pdf = tmp_path/'book.pdf'
    assert exporter.export([str(a), str(b)], pdf, tmp_path/'work', view_declaration_path=view) == 0
    assert check_link_failures(pdf, [a,b], view) == []
    writer = PdfWriter(clone_from=pdf)
    a_dest, b_dest = sorted(str(key) for key in writer.named_destinations if
                            str(key).startswith(('/ch01-', '/ch02-'))
                            and _annotations(writer, str(key)))
    _, ref = _annotations(writer, b_dest)[0]
    ref.get_object()[NameObject('/Dest')] = NameObject(a_dest)
    bad = tmp_path/'cross.pdf'
    writer.write(bad)
    errors = check_link_failures(bad, [a,b], view)
    assert any(x['code'] == 'internal-link-target' and x.get('line') == 5 for x in errors), errors


def test_link_to_quote_and_footnote_starting_with_code(tmp_path):
    chapter = tmp_path/'chapter.md'
    chapter.write_text('# 注释和脚注\n\n> **来源**：https://example.org/print\n\n'
                       '[跳到注释](#note) 并查看脚注[^code]、再次查看[^code]。\n\n'
                       '<a id="note"></a>\n\n> **注（Note）**\n> 这是注释。\n\n'
                       '[^code]: `this_cluster()` 脚注以行内代码开头。\n')
    pdf = tmp_path/'book.pdf'
    assert exporter.export([str(chapter)], pdf, tmp_path/'work') == 0
    assert check_link_failures(pdf, [chapter]) == []


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


def _candidate_case(tmp_path):
    chapter = tmp_path/'chapter.md'
    chapter.write_text('# 检查样例\n\n> **来源**：https://example.org/candidate\n\n'
                       '[甲链接](#甲目标) [乙链接](#乙目标)。\n\n'
                       '## 甲目标\n\n甲正文。\n\n## 乙目标\n\n乙正文。\n')
    return chapter, tmp_path/'book.pdf', tmp_path/'work'


def _damage_candidate(path, out):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject

    writer = PdfWriter(clone_from=path)
    target = _destination(writer, '甲目标')
    _, annot = _annotations(writer, target)[0]
    annot.get_object()[NameObject('/Dest')] = NameObject(_destination(writer, '乙目标'))
    writer.write(out)


def test_candidate_link_damage_keeps_previous_pdf(tmp_path, monkeypatch, capsys):
    from playwright.sync_api import Page

    chapter, pdf, work = _candidate_case(tmp_path)
    assert exporter.export([chapter], pdf, work) == 0
    report_path = work/exporter.REPORT_NAME
    prior = json.loads(report_path.read_text())
    protected = [pdf, report_path, Path(prior['candidate'])]
    before = {p: p.read_bytes() for p in protected}
    original = Page.pdf

    def print_damaged(self, **kwargs):
        data = original(self, **kwargs)
        candidate = Path(kwargs['path'])
        damaged = candidate.with_name('damage.pdf')
        _damage_candidate(candidate, damaged)
        damaged.replace(candidate)
        return data

    monkeypatch.setattr(Page, 'pdf', print_damaged)
    assert exporter.export([chapter], pdf, work) != 0
    error = capsys.readouterr().err
    assert 'internal-link-target' in error and '甲链接' in error
    assert {p: p.read_bytes() for p in protected} == before


def test_candidate_gate_does_not_run_full_verification(tmp_path, monkeypatch):
    import verify_pdf as verifier

    def unexpected(*args, **kwargs):
        raise AssertionError('candidate called full verifier')

    monkeypatch.setattr(verifier, 'run_verification', unexpected)
    chapter, pdf, work = _candidate_case(tmp_path)
    assert exporter.export([chapter], pdf, work) == 0
    assert pdf.is_file()


def test_independent_link_failure_keeps_previous_evidence(tmp_path, capsys):
    import verify_pdf as verifier

    chapter, pdf, work = _candidate_case(tmp_path)
    assert exporter.export([chapter], pdf, work) == 0
    assert verifier.main(['--pdf', str(pdf), '--work-dir', str(work), str(chapter)]) == 0
    damaged = tmp_path/'damaged.pdf'
    _damage_candidate(pdf, damaged)
    isolated = tmp_path/'verify-damage'
    isolated.mkdir()
    report = json.loads((work/exporter.REPORT_NAME).read_text())
    report['pdf_sha256'] = sha256(damaged.read_bytes()).hexdigest()
    (isolated/exporter.REPORT_NAME).write_text(json.dumps(report))
    previous = isolated/verifier.VERIFY_NAME
    previous.write_bytes((work/verifier.VERIFY_NAME).read_bytes())
    protected = [pdf, damaged, previous, work/exporter.REPORT_NAME, work/verifier.VERIFY_NAME]
    before = {p: p.read_bytes() for p in protected}
    assert verifier.main(['--pdf', str(damaged), '--work-dir', str(isolated), str(chapter)]) != 0
    error = capsys.readouterr().err
    assert 'internal-link-target' in error and '甲链接' in error
    assert {p: p.read_bytes() for p in protected} == before


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
            from pypdf import PdfReader
            raw = PdfReader(pdf)
            destination = raw.named_destinations['/'+link['nameddest']]
            operations = raw.pages[target_page].get_contents().operations
            clip_y = float(operations[2][0][1])
            top_margin = -clip_y * float(operations[0][0][3])
            point = out[target_page].rect.height - (destination.top - top_margin)
            assert target.y0 - target.height <= point <= target.y1
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
    assert any(f['code'] == 'internal-link-target' for f in result['failures']), result
    assert {p: p.read_bytes() for p in before} == before
