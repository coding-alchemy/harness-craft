"""PDF 源勘察入口的外部行为验收；fixture 在测试时用 PyMuPDF 生成真实 PDF。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf  # noqa: F401
    HAVE_PYMUPDF = True
except ImportError:
    try:
        import fitz  # noqa: F401
        HAVE_PYMUPDF = True
    except ImportError:
        HAVE_PYMUPDF = False

if not HAVE_PYMUPDF:
    raise unittest.SkipTest("PyMuPDF 不可用，整组 PDF 源勘察测试跳过")

import pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
PREPARE = SCRIPTS / 'prepare_pdf_source.py'


def run_cli(*args):
    return subprocess.run([sys.executable, str(PREPARE)] + [str(a) for a in args],
                          capture_output=True, text=True)


def make_bitmap_bytes():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
    return pix.tobytes("png")


class PdfSourceInspectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)

        def new_doc(name):
            doc = pymupdf.open()
            doc.new_page(width=300, height=400)
            return doc, root / name

        # 含位图插图的纯文字版：正文可靠 + 一张嵌入位图
        doc, path = new_doc('text_bitmap.pdf')
        page = doc[0]
        page.insert_text((40, 60), "Reliable text layer with an embedded "
                                   "bitmap figure inside the body.")
        page.insert_text((40, 90), "Second paragraph stays fully readable.")
        page.insert_image(pymupdf.Rect(40, 120, 120, 200),
                          stream=make_bitmap_bytes())
        doc.save(path)
        doc.close()
        cls.text_bitmap = path

        # 混合版：第 1 页正文可靠，第 2 页正文只有位图（需 OCR）
        doc, path = new_doc('mixed.pdf')
        doc[0].insert_text((40, 60), "Page one has a reliable text layer "
                                     "with enough body characters.")
        page2 = doc.new_page(width=300, height=400)
        page2.insert_image(pymupdf.Rect(30, 40, 270, 360),
                           stream=make_bitmap_bytes())
        doc.save(path)
        doc.close()
        cls.mixed = path

        # 扫描版：两页均无文本层、只有位图
        doc, path = new_doc('scanned.pdf')
        for page in doc:
            pass
        doc[0].insert_image(pymupdf.Rect(30, 40, 270, 360),
                            stream=make_bitmap_bytes())
        doc.new_page(width=300, height=400)
        doc[1].insert_image(pymupdf.Rect(30, 40, 270, 360),
                            stream=make_bitmap_bytes())
        doc.save(path)
        doc.close()
        cls.scanned = path

        # 双栏文字版
        doc, path = new_doc('twocol.pdf')
        page = doc[0]
        left = "Left column body text with sufficient characters to read."
        right = "Right column body text with sufficient characters."
        for i in range(6):
            page.insert_text((40, 60 + i * 14), left)
            page.insert_text((170, 60 + i * 14), right)
        doc.save(path)
        doc.close()
        cls.twocol = path

        cls.out = root / 'out'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def inspect(self, pdf, name):
        out = self.out / name
        result = run_cli('inspect', pdf, '--pages', 'all', '--output', out)
        self.assertEqual(result.returncode, 0,
                         result.stderr)
        report = json.loads((out / 'inspection_report.json').read_text(
            encoding='utf-8'))
        return out, report

    def test_text_with_bitmap_classified_text_and_bitmap_listed(self):
        out, report = self.inspect(self.text_bitmap, 'text_bitmap')
        self.assertEqual(report['classification']['type'], 'text')
        self.assertTrue(any('嵌入位图 1' in item
                            for item in report['classification']['evidence']))
        candidates = report['candidates']
        self.assertEqual(len(candidates['bitmaps']), 1)
        self.assertEqual(candidates['bitmaps'][0]['page'], 1)
        self.assertFalse(candidates['bitmaps_empty'])
        # 双快照与清单草稿落盘
        for name in ('snapshots_layout.txt', 'snapshots_reading.txt',
                     'structure_candidates.json',
                     'adjudication_checklist.json'):
            self.assertTrue((out / name).is_file(), name)
        layout = (out / 'snapshots_layout.txt').read_text(encoding='utf-8')
        self.assertIn('Reliable text layer', layout)
        reading = (out / 'snapshots_reading.txt').read_text(encoding='utf-8')
        self.assertIn('Second paragraph', reading)

    def test_mixed_locates_ocr_region_without_auto_ocr(self):
        _out, report = self.inspect(self.mixed, 'mixed')
        self.assertEqual(report['classification']['type'], 'mixed')
        evidence = '\n'.join(report['classification']['evidence'])
        self.assertIn('P2', evidence)
        self.assertIn('OCR', evidence)
        # 第 2 页被逐页事实定位为无文本层
        page2 = report['pages'][1]
        self.assertEqual(page2['chars'], 0)
        self.assertGreaterEqual(page2['embedded_bitmaps'], 1)
        # 需 OCR 区域逐项定位进清单待处理项，不自动执行 OCR
        checklist = json.loads((self.out / 'mixed' /
                                'adjudication_checklist.json').read_text(
            encoding='utf-8'))
        ocr = [p for p in checklist['pending'] if p.get('kind') == 'ocr_region']
        self.assertEqual([p['page'] for p in ocr], [2])
        # 不自动 OCR：输出目录不产生任何 OCR 文本产物之外的行为，
        # 正文类型仍是 mixed（第 2 页未被当作可靠文本）
        self.assertEqual(report['pages'][1]['text_blocks'], 0)

    def test_scanned_and_empty_candidates_marked(self):
        _out, report = self.inspect(self.scanned, 'scanned')
        self.assertEqual(report['classification']['type'], 'scanned')
        candidates = report['candidates']
        # 该 fixture 无标题/图题/表格/脚注/公式：空类别显式标记为空
        for key in ('headings', 'figure_captions', 'table_captions',
                    'footnotes', 'formulas'):
            self.assertEqual(candidates[key], [])
            self.assertTrue(candidates[key + '_empty'], key)

    def test_two_column_snapshots_cover_both_columns(self):
        out, report = self.inspect(self.twocol, 'twocol')
        self.assertEqual(report['classification']['type'], 'text')
        layout = (out / 'snapshots_layout.txt').read_text(encoding='utf-8')
        reading = (out / 'snapshots_reading.txt').read_text(encoding='utf-8')
        self.assertIn('Left column body text', layout)
        self.assertIn('Right column body text', layout)
        self.assertIn('Left column body text', reading)
        self.assertIn('Right column body text', reading)
        # 坐标口径留档
        coord = report['source']['coordinate_system']
        self.assertEqual(coord['unit'], 'pt')
        self.assertIn('top-left', coord['origin'])

    def test_inspect_preserves_existing_adjudication(self):
        out, _report = self.inspect(self.twocol, 'preserve')
        checklist_path = out / 'adjudication_checklist.json'
        checklist = json.loads(checklist_path.read_text(encoding='utf-8'))
        checklist['blocks'] = [{'id': 'b001', 'type': 'paragraph', 'page': 1,
                                'rect': [40, 50, 260, 70],
                                'adjudication': {'status': 'accepted',
                                                 'basis': '人工裁决留档'}}]
        checklist['reading_order'] = {'adjudicated': True,
                                      'basis': '双栏左→右'}
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        result = run_cli('inspect', self.twocol, '--pages', 'all',
                         '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(checklist_path.read_text(encoding='utf-8'))
        self.assertEqual(merged['blocks'], checklist['blocks'])
        self.assertEqual(merged['reading_order'],
                         checklist['reading_order'])

    def test_environment_probes_page_api(self):
        _out, report = self.inspect(self.twocol, 'env_probe')
        api = report['environment']['api']
        # Page API 为实际属性探测结果（D5：记录实际兼容性，不写死）
        self.assertIs(api['open'], True)
        for name in ('Page.get_text', 'Page.get_drawings',
                     'Page.get_image_info', 'Page.annots',
                     'Page.get_links'):
            self.assertIsInstance(api[name], bool)
            self.assertIn(name, api)
        self.assertTrue(report['environment']['compatible'])

    def test_inspect_warns_when_scope_changes(self):
        out = self.out / 'scope_warn'
        result = run_cli('inspect', self.mixed, '--pages', 'all',
                         '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        checklist_path = out / 'adjudication_checklist.json'
        checklist = json.loads(checklist_path.read_text(encoding='utf-8'))
        checklist['blocks'] = [{'id': 'b001', 'type': 'paragraph', 'page': 1,
                                'rect': [40, 50, 360, 70],
                                'adjudication': {'status': 'accepted',
                                                 'basis': '人工裁决留档'}}]
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        result = run_cli('inspect', self.mixed, '--pages', '1',
                         '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        # 范围变化：保留旧裁决但必须在 stderr 警告须重新核对
        self.assertIn('源/范围已变化', result.stderr)
        self.assertIn('stale', result.stderr)
        merged = json.loads(checklist_path.read_text(encoding='utf-8'))
        self.assertEqual(merged['blocks'], checklist['blocks'])
        self.assertEqual(merged['scope'], [1])
        # 源/范围变化：保留的裁决被标记 stale，物化与对账拒绝
        self.assertIn('stale', merged)
        # P1-2：对同一新源/范围二次勘察，stale 必须继承保留
        again = run_cli('inspect', self.mixed, '--pages', '1', '--output', out)
        self.assertEqual(again.returncode, 0, again.stderr)
        remerged = json.loads(checklist_path.read_text(encoding='utf-8'))
        self.assertIn('stale', remerged)
        blocked2 = run_cli(
            'materialize', self.mixed,
            '--checklist', checklist_path,
            '--output', out / 'draft2.md')
        self.assertNotEqual(blocked2.returncode, 0)
        self.assertIn('stale', blocked2.stderr)
        self.assertIn('blocks', merged['stale']['fields'])
        self.assertIn('源/范围已变化', merged['stale']['reason'])
        blocked = run_cli(
            'materialize', self.mixed,
            '--checklist', checklist_path,
            '--output', out / 'draft.md')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('stale', blocked.stderr)
        # 主 Agent 逐项重新核对后清除 stale（记录依据），物化通过
        merged.pop('stale')
        merged['reading_order'] = {'adjudicated': True,
                                   'basis': '重新核对后确认'}
        bound = merged['adjudicated_against']
        current = {'sha256': merged['source']['sha256'],
                   'scope': merged['scope']}
        merged['revalidate'] = {
            'from': {'sha256': bound['sha256'], 'scope': bound['scope']},
            'to': current,
            'basis': '源/范围变化后逐项重新核对照旧裁决，全部仍然成立',
        }
        merged['adjudicated_against'] = current
        # 重核结论：新范围 [1] 不含第 2 页，旧页级 ocr_region 项随范围
        # 收窄移除（依据留痕），避免残留未处置 ocr_region 与类型冲突
        merged['pending'] = [p for p in merged['pending']
                             if p.get('page') != 2]
        merged.setdefault('rejected', []).append({
            'candidate': 'P2 整页 ocr_region（旧范围 [1,2] 定位）',
            'reason': '范围收窄至 [1] 后不再覆盖第 2 页，重核移除'})
        checklist_path.write_text(json.dumps(merged, ensure_ascii=False),
                                  encoding='utf-8')
        ok = run_cli(
            'materialize', self.mixed,
            '--checklist', checklist_path,
            '--output', out / 'draft.md')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        # 同范围重勘察不警告、不产生 stale
        result = run_cli('inspect', self.mixed, '--pages', '1',
                         '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('源/范围已变化', result.stderr)
        self.assertNotIn('stale', json.loads(
            checklist_path.read_text(encoding='utf-8')))

    def test_pages_range_validation(self):
        result = run_cli('inspect', self.twocol, '--pages', '1-9',
                         '--output', self.out / 'bad_range')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('超出实际页数', result.stderr)


if __name__ == '__main__':
    unittest.main()


class RegionLevelClassificationTests(unittest.TestCase):
    """R1/A10 复审口径：位图区域只提供待裁决线索，不参与类型判定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, name, image_rect):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=500)
        for i in range(4):
            page.insert_text((40, 50 + i * 14),
                             "Reliable body text line %d of the page." % i,
                             fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32))
        page.insert_image(pymupdf.Rect(image_rect),
                          stream=pix.tobytes("png"))
        path = self.root / name
        doc.save(path)
        doc.close()
        return path

    def _inspect(self, path):
        result = run_cli('inspect', path, '--pages', 'all',
                         '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / 'inspection_report.json').read_text(
            encoding='utf-8'))
        checklist = json.loads((self.out / 'adjudication_checklist.json')
                               .read_text(encoding='utf-8'))
        return report, checklist

    def test_large_independent_illustration_not_mixed(self):
        # 复审反例：可靠正文 + 占页 40% 的独立插图 → 仍判 text，
        # 区域以待裁决 pending 单列（不由面积规则判 mixed）
        path = self._build('illus40.pdf', (30, 250, 370, 480))
        report, checklist = self._inspect(path)
        self.assertEqual(report['classification']['type'], 'text')
        regions = [p for p in checklist['pending']
                   if p.get('kind') == 'bitmap_region']
        self.assertEqual(len(regions), 1)
        self.assertGreater(regions[0]['area_ratio'], 0.35)
        self.assertIn('待裁决', regions[0]['status'])

    def test_small_untexted_bitmap_region_located_pending(self):
        # 小面积（<25%）无文本覆盖位图区域也被定位记录，不静默放行
        path = self._build('small.pdf', (30, 330, 170, 470))  # ~12.6%
        report, checklist = self._inspect(path)
        self.assertEqual(report['classification']['type'], 'text')
        regions = [p for p in checklist['pending']
                   if p.get('kind') == 'bitmap_region']
        self.assertEqual(len(regions), 1)
        self.assertLess(regions[0]['area_ratio'], 0.25)
        self.assertIn('待裁决', regions[0]['status'])


    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'

    def tearDown(self):
        self.tmp.cleanup()


class RegionEnumerationAndBindingTests(unittest.TestCase):
    """§7.3：枚举无消失性过滤、ocr_region⇒mixed 强制迁移、裁决身份绑定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, name, image_rect, header=None, page_size=(400, 500)):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=page_size[0], height=page_size[1])
        for i in range(4):
            page.insert_text((40, 60 + i * 14),
                             "Reliable body text line %d of the page." % i,
                             fontsize=10)
        if header:
            page.insert_text((40, 30), header, fontsize=9)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
        page.insert_image(pymupdf.Rect(image_rect),
                          stream=pix.tobytes("png"))
        path = self.root / name
        doc.save(path)
        doc.close()
        return path

    def _inspect(self, path, out=None):
        out = out or self.out
        result = run_cli('inspect', path, '--pages', 'all', '--output', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        checklist = json.loads(
            (out / 'adjudication_checklist.json').read_text(encoding='utf-8'))
        return checklist

    def test_tiny_bitmap_region_not_disappeared(self):
        # <0.5% 的小扫描正文区域也在 pending 中，不消失
        path = self._build('tiny.pdf', (30, 450, 66, 486))  # ~0.65%... 缩小
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=500)
        for i in range(4):
            page.insert_text((40, 60 + i * 14),
                             "Reliable body text line %d of the page." % i,
                             fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4))
        page.insert_image(pymupdf.Rect(30, 460, 58, 488),  # ~0.39%
                          stream=pix.tobytes("png"))
        path = self.root / 'tiny.pdf'
        doc.save(path)
        doc.close()
        checklist = self._inspect(path)
        self.assertEqual(checklist['classification']['type'], 'text')
        regions = [p for p in checklist['pending']
                   if p.get('kind') == 'bitmap_region']
        self.assertEqual(len(regions), 1)
        self.assertLess(regions[0]['area_ratio'], 0.005)

    def test_edge_overlapping_region_kept_with_clue(self):
        # 与页眉文本块边缘相交的位图区域仍在 pending，basis 记录相交线索
        path = self._build('edge.pdf', (30, 24, 370, 60),
                           header="Running header line of the page")
        checklist = self._inspect(path)
        regions = [p for p in checklist['pending']
                   if p.get('kind') == 'bitmap_region']
        self.assertEqual(len(regions), 1)
        self.assertIn('相交', regions[0]['basis'])

    def test_ocr_region_requires_mixed_migration(self):
        path = self._build('migrate.pdf', (30, 250, 370, 480))
        checklist_path = self.out / 'adjudication_checklist.json'
        checklist = self._inspect(path)
        # 主 Agent 裁决为需 OCR 正文：转 ocr_region 但忘记改类型 → 双入口拒绝
        for item in checklist['pending']:
            item['kind'] = 'ocr_region'
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        verify = subprocess.run(
            [sys.executable,
             str(SCRIPTS / 'verify_pdf_source.py'), str(path),
             '--checklist', str(checklist_path),
             '--source-md', str(self.out / 'source_draft.md')],
            capture_output=True, text=True)
        # 源 Markdown 不存在会先失败，仅断言类型迁移诊断出现需先物化——
        # 直接验证 materialize 拒绝即可；verify 侧用核心函数断言
        sys.path.insert(0, str(SCRIPTS))
        from _pdf_source import check_type_migration
        self.assertIn('mixed', check_type_migration(checklist))
        mat = run_cli('materialize', path, '--checklist', checklist_path,
                      '--output', self.out / 'draft.md')
        self.assertNotEqual(mat.returncode, 0)
        self.assertIn('mixed', mat.stderr)
        # 类型改 mixed 但未处置 → 物化仍拒绝（既有 _check_dispatchable）
        checklist['classification']['type'] = 'mixed'
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        mat2 = run_cli('materialize', path, '--checklist', checklist_path,
                       '--output', self.out / 'draft.md')
        self.assertNotEqual(mat2.returncode, 0)
        self.assertIn('OCR', mat2.stderr)
        # 用户明确处置并记录 → 放行
        for item in checklist['pending']:
            item['adjudication'] = 'user-resolved'
            item['status'] = '用户已明确宿主 OCR 处置并记录'
        checklist['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        checklist['blocks'] = [{'id': 'b001', 'order': 1, 'type': 'paragraph',
                                'page': 1, 'rect': [38, 48, 380, 120]}]
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        mat3 = run_cli('materialize', path, '--checklist', checklist_path,
                       '--output', self.out / 'draft.md')
        self.assertEqual(mat3.returncode, 0, mat3.stderr)

    def test_stale_deletion_still_blocked_by_binding(self):
        # 二次勘察扩大范围 → stale；仅删 stale 字段 → 绑定校验仍拒绝
        import pymupdf
        doc = pymupdf.open()
        for pno in range(2):
            page = doc.new_page(width=400, height=500)
            for i in range(4):
                page.insert_text((40, 60 + i * 14),
                                 "Reliable body text %d page %d." % (i, pno),
                                 fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
        doc[0].insert_image(pymupdf.Rect(30, 250, 370, 480),
                            stream=pix.tobytes("png"))
        path = self.root / 'bind.pdf'
        doc.save(path)
        doc.close()
        # 首轮只勘察第 1 页并作出裁决
        result = run_cli('inspect', path, '--pages', '1', '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        checklist_path = self.out / 'adjudication_checklist.json'
        checklist = json.loads(checklist_path.read_text(encoding='utf-8'))
        checklist['blocks'] = [{'id': 'b001', 'order': 1, 'type': 'paragraph',
                                'page': 1, 'rect': [38, 48, 380, 120]}]
        checklist['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        result = run_cli('inspect', path, '--pages', '1,2', '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(checklist_path.read_text(encoding='utf-8'))
        self.assertIn('stale', merged)
        self.assertIn('adjudicated_against', merged)
        self.assertEqual(merged['adjudicated_against']['scope'], [1])
        # 仅删 stale（模拟绕过），adjudicated_against 与当前范围不符
        del merged['stale']
        checklist_path.write_text(json.dumps(merged, ensure_ascii=False),
                                  encoding='utf-8')
        mat = run_cli('materialize', path, '--checklist', checklist_path,
                      '--output', self.out / 'draft.md')
        self.assertNotEqual(mat.returncode, 0)
        self.assertIn('revalidate', mat.stderr)
        verify = subprocess.run(
            [sys.executable,
             str(SCRIPTS / 'verify_pdf_source.py'), str(path),
             '--checklist', str(checklist_path),
             '--source-md', str(self.out / 'source_draft.md')],
            capture_output=True, text=True)
        self.assertEqual(verify.returncode, 2)  # 源稿缺失前先经门禁
        # 有效 revalidate + 绑定更新 → 放行
        merged['revalidate'] = {
            'from': dict(merged['adjudicated_against']),
            'to': {'sha256': merged['source']['sha256'],
                   'scope': merged['scope']},
            'basis': '逐项重核后确认旧裁决成立',
        }
        merged['adjudicated_against'] = merged['revalidate']['to']
        checklist_path.write_text(json.dumps(merged, ensure_ascii=False),
                                  encoding='utf-8')
        mat2 = run_cli('materialize', path, '--checklist', checklist_path,
                       '--output', self.out / 'draft.md')
        self.assertEqual(mat2.returncode, 0, mat2.stderr)

    def test_pending_merge_preserves_state_and_appends(self):
        # 范围扩大：旧已裁决 pending 保留状态，新页位图区域追加
        doc_pages = []
        import pymupdf
        doc = pymupdf.open()
        for pno in range(2):
            page = doc.new_page(width=400, height=500)
            for i in range(4):
                page.insert_text((40, 60 + i * 14),
                                 "Reliable body text %d page %d." % (i, pno),
                                 fontsize=10)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
            page.insert_image(pymupdf.Rect(30, 250, 370, 480),
                              stream=pix.tobytes("png"))
        path = self.root / 'merge.pdf'
        doc.save(path)
        doc.close()
        checklist = self._inspect(path)
        self.assertEqual(len([p for p in checklist['pending']
                              if p.get('kind') == 'bitmap_region']), 2)
        # 裁决第 1 页为素材（resolved），随后扩大范围重勘察
        for item in checklist['pending']:
            if item['page'] == 1:
                item['resolved'] = True
                item['resolution_basis'] = '对照原页确认为插图素材'
        checklist['blocks'] = [{'id': 'b001', 'order': 1, 'type': 'paragraph',
                                'page': 1, 'rect': [38, 48, 380, 120]}]
        checklist['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        checklist_path = self.out / 'adjudication_checklist.json'
        checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                  encoding='utf-8')
        result = run_cli('inspect', path, '--pages', '1,2', '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(checklist_path.read_text(encoding='utf-8'))
        page1 = [p for p in merged['pending'] if p.get('page') == 1
                 and p.get('kind') == 'bitmap_region']
        page2 = [p for p in merged['pending'] if p.get('page') == 2
                 and p.get('kind') == 'bitmap_region']
        self.assertEqual(len(page1), 1)
        self.assertTrue(page1[0].get('resolved'))  # 旧裁决状态保留
        self.assertEqual(len(page2), 1)            # 新发现追加


class LifecycleContinuityTests(unittest.TestCase):
    """§7.3 追加重审：稳定区域身份合并 + 已裁决类型继承的连续生命周期。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'
        import pymupdf
        doc = pymupdf.open()
        for pno in range(2):
            page = doc.new_page(width=400, height=500)
            for i in range(4):
                page.insert_text((40, 60 + i * 14),
                                 "Reliable body text %d page %d." % (i, pno),
                                 fontsize=10)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
        doc[0].insert_image(pymupdf.Rect(30, 250, 200, 420),
                            stream=pix.tobytes("png"))
        doc[1].insert_image(pymupdf.Rect(30, 250, 200, 420),
                            stream=pix.tobytes("png"))
        self.pdf = self.root / 'life.pdf'
        doc.save(self.pdf)
        doc.close()
        self.checklist_path = self.out / 'adjudication_checklist.json'

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        return run_cli(*args)

    def test_lifecycle_adjudication_reinspect_scope_widen(self):
        # 1) 勘察第 1 页：pending 有 bitmap_region
        result = self._run('inspect', self.pdf, '--pages', '1',
                           '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        checklist = json.loads(self.checklist_path.read_text(encoding='utf-8'))
        regions = [p for p in checklist['pending']
                   if p.get('kind') == 'bitmap_region']
        self.assertEqual(len(regions), 1)
        region = regions[0]

        # 2) 主 Agent 回源裁决：该物理区域为需 OCR 正文
        region['kind'] = 'ocr_region'
        region['adjudication'] = 'user-resolved'
        region['status'] = '用户明确要求并授权宿主 OCR，处置记录见项目说明'
        region['resolution_basis'] = '渲染原页目检：该区域为扫描正文表格'
        checklist['classification']['type'] = 'mixed'
        checklist['classification']['adjudicated'] = {
            'status': 'accepted',
            'basis': 'P1 下半为扫描正文区域（人工回源目检）'}
        checklist['blocks'] = [{'id': 'b001', 'order': 1, 'type': 'paragraph',
                                'page': 1, 'rect': [38, 48, 380, 130]}]
        checklist['reading_order'] = {'adjudicated': True, 'basis': '单栏'}
        self.checklist_path.write_text(json.dumps(checklist, ensure_ascii=False),
                                       encoding='utf-8')

        # 3) 同源同范围再次 inspect：候选被已裁决项抑制，类型不被机器覆盖
        result = self._run('inspect', self.pdf, '--pages', '1',
                           '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(self.checklist_path.read_text(encoding='utf-8'))
        items = [p for p in merged['pending'] if p.get('page') == 1]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['kind'], 'ocr_region')  # 无新 bitmap_region
        self.assertEqual(items[0].get('adjudication'), 'user-resolved')
        self.assertIn('扫描正文表格', items[0]['resolution_basis'])
        self.assertEqual(merged['classification']['type'], 'mixed')
        self.assertIn('accepted', json.dumps(
            merged['classification']['adjudicated'], ensure_ascii=False))
        report = json.loads((self.out / 'inspection_report.json').read_text(
            encoding='utf-8'))
        self.assertEqual(report['classification']['type'], 'text')
        self.assertTrue(any('待裁决' in e or '位图' in e
                            for e in report['classification']['evidence']))

        # 4) 按当前处置物化通过；verify 子进程与处置状态一致
        mat = self._run('materialize', self.pdf,
                        '--checklist', self.checklist_path,
                        '--output', self.out / 'draft.md')
        self.assertEqual(mat.returncode, 0, mat.stderr)
        verify = subprocess.run(
            [sys.executable, str(SCRIPTS / 'verify_pdf_source.py'),
             str(self.pdf), '--checklist', str(self.checklist_path),
             '--source-md', str(self.out / 'draft.md')],
            capture_output=True, text=True)
        self.assertEqual(verify.returncode, 0, verify.stderr)

        # 5) 扩大范围：stale + 旧项保留 + 第 2 页新候选追加；门禁拒绝
        result = self._run('inspect', self.pdf, '--pages', '1,2',
                           '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        widened = json.loads(self.checklist_path.read_text(encoding='utf-8'))
        self.assertIn('stale', widened)
        self.assertEqual(widened['classification']['type'], 'mixed')
        page1 = [p for p in widened['pending'] if p.get('page') == 1]
        page2 = [p for p in widened['pending'] if p.get('page') == 2]
        self.assertEqual(len(page1), 1)
        self.assertEqual(page1[0]['kind'], 'ocr_region')
        self.assertEqual(page1[0].get('adjudication'), 'user-resolved')
        self.assertEqual(len(page2), 1)
        self.assertEqual(page2[0]['kind'], 'bitmap_region')
        mat2 = self._run('materialize', self.pdf,
                         '--checklist', self.checklist_path,
                         '--output', self.out / 'draft2.md')
        self.assertNotEqual(mat2.returncode, 0)
        self.assertIn('stale', mat2.stderr)
        verify2 = subprocess.run(
            [sys.executable, str(SCRIPTS / 'verify_pdf_source.py'),
             str(self.pdf), '--checklist', str(self.checklist_path),
             '--source-md', str(self.out / 'draft.md')],
            capture_output=True, text=True)
        self.assertEqual(verify2.returncode, 1)
        self.assertIn('stale', verify2.stderr)

        # 6) 重核：有效 revalidate + 绑定更新 + 除 stale → 放行
        bound = widened['adjudicated_against']
        current = {'sha256': widened['source']['sha256'],
                   'scope': widened['scope']}
        widened['revalidate'] = {'from': bound, 'to': current,
                                 'basis': '逐项重核：P1 扫描正文裁决不变，'
                                          'P2 新位图对照原页确认为插图素材'}
        widened['adjudicated_against'] = current
        widened['blocks'].append({'id': 'b002', 'order': 2,
                                  'type': 'paragraph', 'page': 2,
                                  'rect': [38, 48, 380, 130]})
        for item in widened['pending']:
            if item.get('page') == 2:
                item['resolved'] = True
                item['resolution_basis'] = '对照原页确认为插图素材'
        del widened['stale']
        self.checklist_path.write_text(json.dumps(widened, ensure_ascii=False),
                                       encoding='utf-8')
        mat3 = self._run('materialize', self.pdf,
                         '--checklist', self.checklist_path,
                         '--output', self.out / 'draft3.md')
        self.assertEqual(mat3.returncode, 0, mat3.stderr)
