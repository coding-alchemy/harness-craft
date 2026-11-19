from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import pymupdf

from test_reading import fixture_pack
from reading import build_document
from review import apply_review, assess, content_digest


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pdf = self.root / 'review.pdf'
        self.raw = self.root / 'raw'
        with pymupdf.open() as doc:
            doc.new_page().insert_text((50, 80), '18    13')
            doc.save(self.pdf)
        box = [.1, .1, .8, .5]
        table = dict(type='table', index=0, bbox=box, content=[
            dict(type='table_body', index=0, bbox=box, content=
                 '<table><tr><td>A</td><td>B</td></tr><tr><td>18</td><td>18</td></tr></table>'),
        ])
        fixture_pack(self.pdf, self.raw, [[table]])
        self.input = build_document(self.pdf, self.raw)
        self.block_id = self.input['blocks'][0]['id']

    def record(self, items):
        return {key: self.input['source'][key] for key in ('pdf_sha256', 'zip_sha256')} | {'items': items}

    def correction(self):
        effective = deepcopy(self.input)
        effective['blocks'][0]['cells'][1][1] = '13'
        return dict(block_id=self.block_id, outcome='corrected', evidence='物理页 1 表格 B 列印为 13',
                    content_sha256=content_digest(effective, block_id=self.block_id),
                    row=2, column=2, old='18', new='13')

    def page_confirmed(self, doc=None, state=None):
        doc = doc or self.input
        item = dict(page=1, outcome='confirmed', evidence='目检物理页 1', content_sha256=content_digest(doc, page=1))
        if state:
            item['page_state'] = state
        return item

    def test_correct_one_cell_and_replay(self):
        record = self.record([self.correction()])
        corrected = apply_review(self.input, record)
        replayed = apply_review(build_document(self.pdf, self.raw), record)
        self.assertEqual(self.input['blocks'][0]['cells'][1], ['18', '18'])
        self.assertEqual(corrected['blocks'][0]['cells'][1], ['18', '13'])
        self.assertEqual(replayed, corrected)
        corrected['blocks'][0]['text'] = '不要改变原文'
        self.assertEqual(replayed['corrections'][0]['old'], '18')

    def test_formatted_cell_changes_preserve_other_runs_or_report_the_cell(self):
        item = self.correction() | dict(row=1, column=1, old='18 m2', new='13 m2')
        table = self.input['blocks'][0]
        del table['cells']
        cell = dict(column=1, tag='td', rowspan=1, colspan=1, text='18 m2', markup='18 m<sup>2</sup>')
        table['table'] = [[cell]]
        result = apply_review(self.input, self.record([item]))
        self.assertEqual(result['blocks'][0]['table'][0][0]['markup'], '13 m<sup>2</sup>')
        cell.update(text='18 m2, 05 g', markup='18 m<sup>2</sup>, 05 g')
        two_edits = item | dict(old=cell['text'], new='13 m2, 07 g')
        result = apply_review(self.input, self.record([two_edits]))
        self.assertEqual(result['blocks'][0]['table'][0][0]['markup'], '13 m<sup>2</sup>, 07 g')
        cell.update(text='11', markup='1<sup>1</sup>')
        with self.assertRaisesRegex(ValueError, self.block_id + ' 第 1 行第 1 列'):
            apply_review(self.input, self.record([item | dict(old='11', new='1')]))

    def test_cell_correction_does_not_resolve_table(self):
        self.input['blocks'][0]['issues'] = ['复杂表头待复核']
        fix = self.correction()
        table_review = dict(block_id=self.block_id, outcome='unresolved', evidence='另一个表头看不清',
                            content_sha256=fix['content_sha256'])
        for items in ([fix], [fix, table_review], [table_review, fix]):
            with self.subTest(items=items):
                result = apply_review(self.input, self.record(items))
                table = result['blocks'][0]
                self.assertEqual(table['cells'][1], ['18', '13'])
                self.assertIn('复杂表头待复核', table['issues'])
                if len(items) == 2:
                    self.assertIn('另一个表头看不清', ' '.join(table['issues']))
                self.assertEqual(assess(result, [])['status'], '降级')
        confirmed = dict(table_review, outcome='confirmed', evidence='逐项核对全表')
        result = apply_review(self.input, self.record([confirmed, fix]))
        self.assertEqual(result['blocks'][0]['issues'], [])
        with self.assertRaisesRegex(ValueError, '冲突'):
            apply_review(self.input, self.record([fix, confirmed, table_review]))

    def test_table_body_confirmation_covers_visible_cells_order_and_image(self):
        table = self.input['blocks'][0]
        body_id = table['children'][0]['id']
        table['assets'].append(dict(path='assets/table.jpg', sha256='a' * 64))
        checked = dict(block_id=body_id, outcome='confirmed', evidence='已核对表体',
                       content_sha256=content_digest(self.input, block_id=body_id))
        fix = self.correction()
        corrected = apply_review(self.input, self.record([checked, fix]))
        self.assertEqual(corrected['blocks'][0]['cells'][1], ['18', '13'])
        self.assertEqual(corrected['reviewed'][0]['outcome'], 'unresolved')
        self.assertIn('待复核', ' '.join(corrected['blocks'][0]['children'][0]['issues']))
        changed = deepcopy(self.input)
        changed['blocks'][0]['cells'].reverse()
        self.assertNotEqual(content_digest(changed, block_id=body_id), checked['content_sha256'])
        changed = deepcopy(self.input)
        changed['blocks'][0]['assets'][0]['sha256'] = 'b' * 64
        self.assertNotEqual(content_digest(changed, block_id=body_id), checked['content_sha256'])
        fresh = dict(checked, content_sha256=content_digest(corrected, block_id=body_id))
        replay = apply_review(self.input, self.record([fresh, fix]))
        self.assertEqual(replay['reviewed'][0]['outcome'], 'confirmed')
        self.assertEqual(replay['blocks'][0]['children'][0]['issues'], [])

    def test_invalid_or_conflicting_review(self):
        good = self.correction()
        for label, record in [
            ('pdf_sha256', self.record([good]) | {'pdf_sha256': 'f' * 64}),
            ('zip_sha256', self.record([good]) | {'zip_sha256': 'a' * 64}),
            ('old', self.record([good | {'old': '16'}])),
            ('冲突', self.record([good, good | {'new': '99'}])),
            ('block_id', self.record([good | {'block_id': 'bad'}])),
        ]:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, label):
                apply_review(self.input, record)
        stale = apply_review(self.input, self.record([good | {'content_sha256': '1' * 64}]))
        self.assertEqual(stale['blocks'][0]['cells'][1], ['18', '13'])
        self.assertEqual(stale['reviewed'][0]['outcome'], 'unresolved')
        self.assertIn('待复核', ' '.join(stale['blocks'][0]['issues']))

    def test_grade_and_empty_pages(self):
        self.assertEqual(assess(self.input, ['引用图片缺失'])['status'], '失败')
        self.assertEqual(assess(self.input, [])['status'], '降级')
        reviewed = apply_review(self.input, self.record([self.page_confirmed()]))
        self.assertEqual(assess(reviewed, [])['status'], '通过')
        issue = deepcopy(self.input)
        issue['blocks'][0]['issues'] = ['表格存疑']
        checked = apply_review(issue, self.record([self.page_confirmed(issue)]))
        self.assertEqual(assess(checked, [])['status'], '降级')
        for page_status in ('unknown', 'failed'):
            empty = deepcopy(self.input)
            empty['blocks'] = []
            empty['pages'][0].update(status=page_status, issues=['原页需核对'], block_ids=[])
            self.assertEqual(assess(empty, [])['status'], '失败')
            state = 'blank' if page_status == 'unknown' else 'has_content'
            checked = apply_review(empty, self.record([self.page_confirmed(empty, state)]))
            self.assertEqual(assess(checked, [])['status'], '通过' if state == 'blank' else '失败')
