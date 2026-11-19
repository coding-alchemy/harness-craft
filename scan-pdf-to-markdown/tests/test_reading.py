import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import pymupdf
from markdown_it import MarkdownIt

from test_capture import capture_raw
from reading import build_document, reading_files, write_reading
from review import apply_review


def text_block(text, index, bbox=None, kind='text', **fields):
    result = dict(type=kind, index=index, content=[dict(type='text', content=text)], **fields)
    if bbox is not None:
        result['bbox'] = bbox
    return result


def fixture_pack(pdf, raw, pages, assets=None, *, table_view=None):
    def structured(block):
        fields = {key: block[key] for key in ('type', 'bbox', 'level', 'sub_type') if key in block}
        content = block.get('content', '')
        if isinstance(content, list):
            if block['type'] in ('table', 'image', 'chart', 'code'):
                body, *other = content
                fields['image_source'] = body.get('image_path', '')
                fields['captions'] = [structured(item) for item in other if item['type'].endswith('_caption')]
                content = body.get('content', '')
                if block['type'] == 'table' and table_view is not None:
                    content = table_view
            elif block['type'] in ('list', 'index'):
                content = [structured(item) for item in content]
            else:
                content = ''.join(span['content'] for span in content)
        return dict(fields, content=content)

    with pymupdf.open(pdf) as doc:
        layout = [dict(page_idx=p.number, width_pt=p.rect.width, height_pt=p.rect.height) for p in doc]
    package = dict(
        metadata={'file_suffix': 'pdf', 'producer': {'name': 'mineru', 'version': '4.1.7'}},
        extensions={'mineru': {'tier': 'basic', 'parse_mode': 'ocr'},
                    'docvortex_layout': {'version': 1, 'pages': layout}},
        is_full_document=True,
        pages=[dict(page_idx=i, blocks=blocks) for i, blocks in enumerate(pages)],
    )

    def run(command, **kwargs):
        output = command[command.index('-o') + 1]
        with ZipFile(output, 'w') as archive:
            archive.writestr('middle_json.json', json.dumps(dict(
                package, schema='docvortex.middle', schema_version='2.0',
            )))
            view = [dict(page_idx=i, blocks=[structured(block) for block in blocks])
                    for i, blocks in enumerate(pages)]
            archive.writestr('structured_content.json', json.dumps(dict(package, pages=view)))
            for name, data in (assets or {}).items():
                archive.writestr(name, data)
        return subprocess.CompletedProcess(command, 0, '', '')

    with patch('capture.subprocess.run', side_effect=run):
        capture_raw(pdf, raw)


class ReadingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pdf = self.root / 'source.pdf'
        self.raw = self.root / 'raw'
        self.out = self.root / 'result'
        self.out.mkdir()
        with pymupdf.open() as doc:
            page = doc.new_page(width=400, height=600)
            page.insert_text((60, 75), 'Mixed page')
            page = doc.new_page(width=400, height=500)
            page.set_cropbox(pymupdf.Rect(25, 30, 375, 470))
            page.set_rotation(90)
            doc.new_page(width=400, height=600)
            doc.new_page().insert_text((30, 40), 'Visible but not recognized')
            doc.new_page().draw_rect(pymupdf.Rect(10, 20, 40, 50), fill=(0, 0, 0))
            doc.save(self.pdf)

    def build(self, pages, assets=None):
        fixture_pack(self.pdf, self.raw, pages, assets)
        return build_document(self.pdf, self.raw)

    def test_mixed_page_keeps_occurrences(self):
        texts = ['只在扫描区', '两个位置相同的句子', '只在原生区', '两个位置相同的句子']
        blocks = [text_block(text, i, [.1, .1 + i*.2, .9, .15 + i*.2]) for i, text in enumerate(texts)]
        document = self.build([blocks, [], [], [], []])
        self.assertEqual([block['text'] for block in document['blocks']], texts)
        self.assertEqual(len({block['id'] for block in document['blocks']}), 4)
        self.assertEqual(document['blocks'][3]['raw_refs'][0]['path'], '/pages/0/blocks/3')

    def test_table_view_is_gfm_and_original_body_is_html(self):
        box = [.1, .15, .8, .5]
        body = dict(type='table_body', index=0, bbox=box, content=(
            '<table><tr><td>Year</td><td>Sales</td><td>Orders</td></tr>'
            '<tr><td>2024</td><td>200</td><td>19</td></tr></table>'
        ))
        table = dict(type='table', index=0, bbox=box, content=[body])
        view = '| Year | Sales | Orders |\n| --- | --- | --- |\n| 2024 | 200 | 19 |'
        fixture_pack(self.pdf, self.raw, [[table], [], [], [], []], table_view=view)
        doc = build_document(self.pdf, self.raw)
        self.assertEqual(doc['pages'][0]['status'], 'readable')
        self.assertEqual(doc['blocks'][0]['cells'][1], ['2024', '200', '19'])
        self.assertIn(view, reading_files(doc)['document.md'])

    def test_table_preserves_equations_and_literal_cell_values(self):
        box = [.1, .15, .8, .5]
        formula_body = dict(type='table_body', index=0, bbox=box, content=(
            '<table><tr><td colspan="2">Geometric formulas</td></tr>'
            '<tr><td>Square</td><td><eq>A = x ^ { 2 }</eq></td></tr></table>'
        ))
        syntax_body = dict(type='table_body', index=1, bbox=box, content=(
            '<table><tr><td>Syntax</td></tr><tr><td>List&lt;T&gt;</td></tr>'
            '<tr><td>&lt;br&gt;<br>&lt;strong&gt;</td></tr><tr><td>&lt;ref&gt;</td></tr></table>'
        ))
        blocks = [dict(type='table', index=body['index'], bbox=box, content=[body])
                  for body in (formula_body, syntax_body)]
        doc = self.build([blocks, [], [], [], []])
        output = reading_files(doc)['document.md']
        self.assertIn('<td colspan="2">Geometric formulas</td>', output)
        self.assertIn('<td>Square</td><td> $A = x ^ { 2 }$ </td>', output)
        self.assertEqual(doc['blocks'][0]['table'][1][1]['text'], ' $A = x ^ { 2 }$ ')
        self.assertEqual(doc['blocks'][1]['cells'], [['Syntax'], ['List<T>'], ['<br>\n<strong>'], ['<ref>']])
        self.assertIn('| List&lt;T&gt; |', output)
        self.assertIn('| &lt;br&gt;<br>&lt;strong&gt; |', output)
        self.assertIn('| &lt;ref&gt; |', output)

    def test_visual_body_notices_and_nested_text_styles(self):
        box = [.1, .15, .8, .5]
        caption = text_block('10', 1, kind='image_caption')
        caption['content'] += [dict(type='text', content='2', styles=['superscript']),
                               dict(type='text', content=' m & height')]
        item = text_block('H', 0)
        item['content'] += [dict(type='text', content='2', styles=['subscript']), dict(type='text', content='O')]
        image = dict(type='image', index=0, bbox=box, content=[
            dict(type='image_body', index=0, bbox=box, content='', uncertain=True), caption,
        ])
        table = dict(type='table', index=2, bbox=box, content=[
            dict(type='table_body', index=2, bbox=box, content='<table><tr><td>A</td></tr></table>', uncertain=True),
        ])
        items = dict(type='list', index=3, bbox=box, content=[item])
        doc = self.build([[image, table, items], [], [], [], []])
        output = reading_files(doc)['document.md']
        self.assertIn('10<sup>2</sup> m &amp; height', output)
        self.assertIn('H<sub>2</sub>O', output)
        for parent in ('p0001-b0000', 'p0001-b0002'):
            self.assertIn(f'<!-- block:{parent}-c0 -->', output)
            self.assertIn(f'{parent}-c0）引擎标记为待核对', output)

    def test_list_reader_displays_literal_text_and_typed_spans(self):
        text = '![Figure](diagram.png) __init__'
        item = text_block(text, 0)
        item['content'].extend([dict(type='text', content='2', styles=['superscript']),
                                dict(type='equation_inline', content='x_1')])
        group = dict(type='list', index=0, content=[item])
        doc = self.build([[group], [], [], [], []])
        self.assertIn(text, doc['blocks'][0]['children'][0]['text'])
        output = MarkdownIt().render(reading_files(doc)['document.md'])
        self.assertIn(text + '<sup>2</sup>$x_1$', output)
        self.assertNotIn('<img', output)
        child = doc['blocks'][0]['children'][0]
        correction = dict(block_id=child['id'], outcome='corrected', content_sha256='0' * 64,
                          evidence='原图的标识符拼写不同', old=child['text'],
                          new=child['text'].replace('__init__', '__iter__'))
        binding = {k: doc['source'][k] for k in ('pdf_sha256', 'zip_sha256')}
        changed = apply_review(doc, dict(binding, items=[correction]))
        self.assertIn('__iter__<sup>2</sup>$x_1$', MarkdownIt().render(reading_files(changed)['document.md']))

    def test_continued_table_uses_preceding_page_table(self):
        box = [.1, .15, .8, .5]
        body = dict(type='table_body', index=0, bbox=box, content='<table><tr><td>A</td></tr></table>')
        table = dict(type='table', index=0, bbox=box, content=[body])
        continuation = dict(table, continues_prev=True)
        doc = self.build([[table, text_block('表后说明', 1, box)], [continuation], [], [continuation], []])
        self.assertEqual(doc['blocks'][2]['continues_from'], 'p0001-b0000')
        self.assertNotIn('continues_from', doc['blocks'][3])
        self.assertIn('无法确定续表来源', ' '.join(doc['pages'][3]['issues']))

    def test_text_continuation_skips_visual_block_but_stops_at_heading(self):
        box = [.1, .15, .8, .5]
        body = dict(type='table_body', index=1, bbox=box, content='<table><tr><td>A</td></tr></table>')
        table = dict(type='table', index=1, bbox=box, content=[body])
        continuation = text_block('the result.', 0, box, continues_prev=True)
        doc = self.build([[text_block('The figure shows', 0, box), table],
                          [continuation, text_block('Heading', 1, box, kind='paragraph_title')],
                          [continuation], [], [continuation]])
        self.assertEqual(doc['blocks'][2]['continues_from'], 'p0001-b0000')
        self.assertNotIn('continues_from', doc['blocks'][4])
        self.assertNotIn('continues_from', doc['blocks'][5])
        self.assertIn('无法确定续段来源', ' '.join(doc['pages'][4]['issues']))

    def test_rotated_crop_and_missing_child_box(self):
        container = {'type': 'list', 'index': 0, 'bbox': [.1, .2, .4, .5], 'sub_type': 'text',
                     'content': [text_block('子项无框', 0)]}
        document = self.build([[], [container], [], [], []])
        parent = document['blocks'][0]
        self.assertEqual(parent['bbox'], [95, 294, 200, 426])
        child = parent['children'][0]
        self.assertIsNone(child['bbox'])
        self.assertTrue(child['raw_refs'] and child['bbox_reason'])
        self.assertEqual(child['raw_refs'][0]['path'], '/pages/1/blocks/0/content/0')
        write_reading(document, self.out)
        self.assertIn(f'- <!-- block:{child["id"]} -->\n  \n  子项无框', (self.out / 'document.md').read_text())
        for bbox in ([.2, .5, .8, 2], [.2, .5, .2, .8], [.2, .6, .7, float('inf')]):
            with self.subTest(bbox=bbox):
                shutil.rmtree(self.raw)
                container['bbox'] = bbox
                with self.assertRaisesRegex(ValueError, 'bbox'):
                    self.build([[], [container], [], [], []])

    def test_reading_order_assets_and_uncertainty(self):
        asset = 'images/example.png'
        pixmap = pymupdf.Pixmap(pymupdf.csGRAY, 2, 2, b'\xf0\x80\xf0\x80', False)
        box = [.12, .12, .7, .7]
        image = dict(type='image', index=2, bbox=box, content=[
            dict(type='image_body', index=2, bbox=box, content='', image_path=asset),
            text_block('原图说明', 3, kind='image_caption'),
        ])
        table = dict(type='table', index=4, bbox=box, content=[
            dict(type='table_body', index=4, bbox=box, content=
                 '<table><tr><td>行名</td><td>产量</td></tr><tr><td>甲</td><td>18</td></tr></table>'),
        ])
        formula = dict(type='equation', index=5, bbox=box, content='')
        blocks = [text_block('章节', 0, box, 'paragraph_title', level=2), image, table, formula,
                  text_block('页脚', 7, box, 'footer')]
        doc = self.build([blocks, [], [], [], []], {asset: pixmap.tobytes('png')})
        write_reading(doc, self.out)
        text = (self.out / 'document.md').read_text()
        self.assertLess(text.index('## 章节'), text.index('原图说明'))
        self.assertLess(text.index('原图说明'), text.index('| 行名 | 产量 |'))
        self.assertIn('| 甲 | 18 |', text)
        self.assertIn('待核对', text)
        self.assertEqual(doc['pages'][2]['status'], 'blank')
        self.assertEqual(doc['pages'][3]['status'], 'failed')
        self.assertEqual(doc['pages'][4]['status'], 'unknown')
        source = json.loads((self.out / 'source-map.json').read_bytes())
        self.assertEqual(source['pages'][0]['excluded'][0]['text'], '页脚')
        moved = self.root / 'moved'
        self.out.rename(moved)
        ref = doc['blocks'][1]['assets'][0]['path']
        self.assertEqual((moved / ref).read_bytes(), pixmap.tobytes('png'))
        self.assertIn(ref, text)
