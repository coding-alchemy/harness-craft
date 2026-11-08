"""复杂题名的声明兼容、源节点及成品核验。"""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from translator_test_support import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import export_pdf as exporter


def _declaration(path, source, version, **title):
    path.write_text(json.dumps({
        'version': version, 'exclusions': [],
        'inputs': [{'path': str(source), 'sha256': sha256(source.read_bytes()).hexdigest()}],
        'document_title': {'basis': '题名对照', **title},
    }))
    return path


def test_title_v2_preserves_math_and_links(tmp_path):
    pymupdf = pytest.importorskip('pymupdf')
    import verify_pdf as verifier

    original = 'Base model $x_1$ and [Guide](https://example.org/guide)'
    source = tmp_path / 'paper.md'
    source.write_text('# '+original+'\n\n> **来源**：https://example.org/paper\n\n中文正文。\n')
    declaration = _declaration(
        tmp_path/'view.json', source, 2, original=original,
        chinese_markdown='**基础模型** $x_1$ 与[指南](https://example.org/guide)')
    chapters = exporter.load_inputs([str(source)])
    view = exporter.load_view_declaration(declaration, chapters)
    exporter.parse_chapter(chapters[0])
    before = chapters[0].soup.h1
    original_math = [node['data-tex'] for node in before.find_all(attrs={'data-tex': True})]
    original_links = [node['href'] for node in before.find_all('a', href=True)]
    decision = exporter.decide_document_title(chapters, view)
    exporter.project_document_title(chapters, decision)
    title = chapters[0].soup.h1
    assert [node['data-tex'] for node in title.find_all(attrs={'data-tex': True})] == original_math
    assert [node['href'] for node in title.find_all('a', href=True)] == original_links
    assert title.strong.get_text() == '基础模型'

    pdf, work = tmp_path/'paper.pdf', tmp_path/'work'
    assert exporter.export([str(source)], pdf, work, view_declaration_path=declaration) == 0
    args = verifier.parse_args(['--pdf', str(pdf), '--work-dir', str(work),
                                '--view-declaration', str(declaration), str(source)])
    ok, report = verifier.run_verification(args)
    assert ok, report
    with pymupdf.open(pdf) as doc:
        assert doc.metadata['title'] == decision['title']
        assert '$' not in doc.metadata['title'] and '<' not in doc.metadata['title']
        page = doc[0]
        assert page.search_for('基础模型') and page.search_for('指南')
        assert {link['uri'] for link in page.get_links() if 'uri' in link} == set(original_links)
        assert any('KaTeX' in span['font'] for block in page.get_text('dict')['blocks']
                   for line in block.get('lines', ()) for span in line['spans'])

    for damaged in ('基础模型 $x_2$ 与[指南](https://example.org/guide)',
                    '基础模型 $x_1$ 与[指南](https://example.org/other)'):
        _declaration(declaration, source, 2, original=original, chinese_markdown=damaged)
        with pytest.raises(exporter.ExportError, match='公式|链接'):
            chapters = exporter.load_inputs([str(source)])
            view = exporter.load_view_declaration(declaration, chapters)
            exporter.parse_chapter(chapters[0])
            exporter.project_document_title(chapters, exporter.decide_document_title(chapters, view))


def test_title_v1_literal_and_old_reader_rejection(tmp_path):
    source = tmp_path/'paper.md'
    source.write_text('# Paper\n\n正文。\n')
    declaration = tmp_path/'view.json'
    literal = '字面 *星号* 与 $美元$'
    _declaration(declaration, source, 1, original='Paper', chinese=literal)
    chapters = exporter.load_inputs([str(source)])
    view = exporter.load_view_declaration(declaration, chapters)
    exporter.parse_chapter(chapters[0])
    decision = exporter.decide_document_title(chapters, view)
    exporter.project_document_title(chapters, decision)
    assert chapters[0].soup.h1.get_text() == literal
    assert not chapters[0].soup.h1.find('em')
    assert not chapters[0].soup.h1.find(attrs={'data-tex': True})

    _declaration(declaration, source, 2, original='Paper', chinese_markdown='**中文**')
    old = tmp_path/'baseline'
    old.mkdir()
    repo = Path(__file__).resolve().parents[2]
    archive = subprocess.run(
        ['git', 'archive', 'b10683bae717ede20b69dd98255ca33f979788eb',
         'tech-doc-translator/skills/tech-doc-translator'], cwd=repo,
        check=True, stdout=subprocess.PIPE)
    subprocess.run(['tar', '-xf', '-', '-C', str(old)], input=archive.stdout, check=True)
    reader = old/'tech-doc-translator/skills/tech-doc-translator/scripts/export_pdf.py'
    result = subprocess.run([sys.executable, str(reader), '--view-declaration', str(declaration),
                             '--output', str(tmp_path/'old.pdf'), '--work-dir', str(tmp_path/'old-work'),
                             str(source)], capture_output=True, text=True)
    assert result.returncode != 0
    assert '版本不受支持' in result.stderr and '2' in result.stderr


@pytest.mark.parametrize('version,fields', [
    (1, {'chinese_markdown': '复杂中文'}),
    (2, {'chinese': '普通中文', 'chinese_markdown': '复杂中文'}),
    (2, {'chinese_markdown': '中文 <b>HTML</b>'}),
    (2, {'chinese_markdown': '中文 ![图](asset.png)'}),
    (2, {'chinese_markdown': '中文\n\n第二段'}),
    (2, {'chinese_markdown': '# 中文块标题'}),
])
def test_title_v2_rejects_unsupported_nodes(tmp_path, version, fields):
    source = tmp_path/'paper.md'
    source.write_text('# Paper\n\n正文。\n')
    declaration = _declaration(tmp_path/'view.json', source, version, original='Paper', **fields)
    with pytest.raises(exporter.ExportError, match='视图声明|题名'):
        exporter.load_view_declaration(declaration, exporter.load_inputs([str(source)]))
