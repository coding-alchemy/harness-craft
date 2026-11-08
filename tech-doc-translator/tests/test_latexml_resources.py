"""二期 ticket 05：可核验资源与同版本 PDF 补图闭环。

覆盖验收 05-1～05-7 的底层定向用例：同名异资源无冲突目标、
resource_substitutions 合同逐项核对（版本/区域/裁剪/产物/依据）、
替换关系的对账与交付闭合、check_policy 资源投影。
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'latexml_content.html'

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>T05 Fixture</title></head>
<body><article id="paper" class="ltx_document">
<h1 class="ltx_title">T05 Fixture</h1>
<figure><img src="images/dup.png" alt="a"/></figure>
<figure><img src="assets/dup.png" alt="b"/></figure>
<figure><img src="images/gone.png" alt="c"/></figure>
</article></body></html>"""

IDENTITY = {
    'expected_title': 'T05 Fixture', 'actual_title': 'T05 Fixture',
    'paper_id': '2205.00005', 'version': 'v1',
    'final_url': 'https://example.org/abs/2205.00005v1',
    'retrieved_at': '2026-10-05T00:00:00Z',
    'confirmation': '对照已确认页面与快照 H1 逐字核对（测试样例）。',
}


def _sha_file(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


class _ResourceDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / 'images').mkdir()
        (base / 'assets').mkdir()
        (base / 'images' / 'dup.png').write_bytes(b'png-red')
        (base / 'assets' / 'dup.png').write_bytes(b'png-blue')
        # 同版本 PDF 与裁剪产物
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 50), 'Figure A (v1)', fontsize=12)
        doc.save(str(base / 'same_version.pdf'))
        doc.close()
        doc = fitz.open(str(base / 'same_version.pdf'))
        pix = doc[0].get_pixmap(clip=fitz.Rect(20, 30, 200, 120), dpi=100)
        pix.save(str(base / 'crop.png'))
        doc.close()
        self.base = base
        self.substitution = {
            'original_ref': 'images/gone.png',
            'missing_fact': '快照资源缺失（测试夹具）',
            'pdf': {'path': str(base / 'same_version.pdf'),
                    'sha256': _sha_file(base / 'same_version.pdf'),
                    'version': 'v1'},
            'page': 1, 'rect': [20, 30, 200, 120],
            'crop': {'basis': 'fitz clip dpi=100（测试）'},
            'product': {'path': str(base / 'crop.png'),
                        'sha256': _sha_file(base / 'crop.png')},
            'identity_basis': 'PDF 摘要与版本 v1 核对一致（测试）',
            'visual_basis': '裁剪含图内文字 Figure A (v1)（目检）',
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self, substitutions=()):
        raw = HTML
        (self.base / 'paper.html').write_text(raw, encoding='utf-8')
        md, corrs, unres, _f, _ad = latexml.adapt_latexml_snapshot(
            raw, None, [], str(self.base),
            resource_substitutions=list(substitutions))
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(self.base / 'paper.html'),
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY),
            'decisions': [],
            'correspondences': corrs,
            'unresolved': unres,
        }
        if substitutions:
            payload['resource_substitutions'] = list(substitutions)
        return raw, md, payload


class SameNameResourcesTest(_ResourceDirs):
    """05-2：同名异资源无冲突目标对应。"""

    def test_object_enumerate_pubnotes_roundtrip(self):
        (self.base / 'chart.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"/>')
        raw = (
            '<article class="ltx_document"><h1>T <span class="ltx_pubnotes">'
            '<span>出版注甲</span> <span>出版注乙</span></span></h1>'
            '<figure><object type="image/svg+xml" data="chart.svg" id="figure-object"'
            ' width="100" height="60"></object><figcaption>Chart</figcaption></figure>'
            '<ol class="ltx_enumerate" start="3"><li>Alpha'
            '<ol><li>Inner one</li><li>Inner two</li></ol></li>'
            '<li>Beta</li></ol></article>')
        snapshot = self.base / 'object.html'
        snapshot.write_text(raw)
        md, corrs, unresolved, fidelity, _ = latexml.adapt_latexml_snapshot(
            raw, None, [], str(self.base))
        self.assertEqual(unresolved, [])
        self.assertEqual(md.splitlines()[0], '# T')
        self.assertIn('出版注甲 出版注乙', md)
        self.assertIn('[IMG: images/chart.svg]', md)
        self.assertIn('3. Alpha', md)
        self.assertLess(md.index('1. Inner one'), md.index('2. Inner two'))
        self.assertLess(md.index('2. Inner two'), md.index('4. Beta'))
        image = next(c for c in corrs if c['content_type'] == 'image')
        self.assertEqual(image['conversion']['source_ref'], 'chart.svg')
        self.assertEqual(image['conversion']['source_id'], 'figure-object')
        self.assertEqual(fidelity.image_display[0]['value'], 100)
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(snapshot), 'sha256': latexml.sha256_text(raw)},
            'paper_identity': {**IDENTITY, 'actual_title': 'T', 'expected_title': 'T'},
            'decisions': [], 'correspondences': corrs, 'unresolved': unresolved,
        }
        self.assertEqual(reconcile_latexml_to_markdown(raw, md, None, payload), [])
        for damaged in (md.replace('2. Inner two', ''), md.replace('3. Alpha', '8. Alpha')):
            self.assertTrue(reconcile_latexml_to_markdown(raw, damaged, None, payload))

    def test_disambiguated_targets(self):
        _raw, md, payload, = self._payload()
        self.assertIn('[IMG: images/images--dup.png]', md)
        self.assertIn('[IMG: images/assets--dup.png]', md)
        images = {c['node']: c for c in payload['correspondences']
                  if c.get('content_type') == 'image'}
        self.assertEqual(images['img[1]']['conversion']['reference'],
                         'images/images--dup.png')
        self.assertEqual(images['img[2]']['conversion']['reference'],
                         'images/assets--dup.png')

    def _parse_ordered_list(self, raw):
        from translator_test_support import SCRIPTS

        snapshot = self.base / 'enumerate.html'
        snapshot.write_text(raw)
        basis = self.base / 'input.json'
        basis.write_text(json.dumps({
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': str(snapshot), 'sha256': latexml.sha256_text(raw)},
            'paper_identity': IDENTITY, 'decisions': [],
        }))
        output = self.base / 'source.md'
        adaptation = self.base / 'adaptation.json'
        run = subprocess.run([
            sys.executable, str(SCRIPTS / 'parse_reference_html.py'),
            str(snapshot), str(output), '--source-adaptation', str(basis),
            '--adaptation-output', str(adaptation),
        ], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return output.read_text(), json.loads(adaptation.read_text())

    def test_ordered_list_preserves_image_order_and_ownership(self):
        from latexml_test_support import replace_current

        (self.base / 'chart.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"/>')
        raw = (
            '<article class="ltx_document"><h1>T05 Fixture</h1>'
            '<ol class="ltx_enumerate" start="3"><li>Before'
            '<img src="images/dup.png"/>After'
            '<ol><li><object type="image/svg+xml" data="chart.svg" id="chart"'
            ' width="100" height="60"></object></li></ol>Tail</li>'
            '<li><img src="assets/dup.png"/>Next</li></ol></article>')
        md, payload = self._parse_ordered_list(raw)
        refs = ['images/images--dup.png', 'images/chart.svg', 'images/assets--dup.png']
        markers = ['[IMG: %s]' % ref for ref in refs]
        images = [c for c in payload['correspondences']
                  if c['content_type'] == 'image']
        self.assertEqual([c['conversion']['reference'] for c in images], refs)
        self.assertEqual(images[1]['conversion']['source_id'], 'chart')
        self.assertEqual(images[1]['conversion']['width'], '100')

        readable = md
        for marker, ref in zip(markers, refs):
            readable = readable.replace(marker, '![](%s)' % ref)
        dom = BeautifulSoup(MarkdownIt().render(readable), 'html.parser')
        outer = dom.ol
        self.assertEqual(outer['start'], '3')
        first, second = outer.find_all('li', recursive=False)
        self.assertEqual([part.get_text(strip=True) or part.name for part in first.children
                          if part.name], ['Before', 'p', 'After', 'ol', 'Tail'])
        self.assertEqual(first.ol.li.img['src'], refs[1])
        self.assertEqual(second.img['src'], refs[2])
        self.assertEqual(second.get_text(strip=True), 'Next')

        for original, replacement, problem in (
                ('   ' + markers[0] + '\n', '', '正文流'),
                ('      ' + markers[1], '   ' + markers[1], '图片 object[1] 的列表嵌套不符'),
                ('\n   ' + markers[2], '\n\n   ' + markers[2], '首块被空行移出列表')):
            with self.subTest(problem=problem):
                damaged, current = replace_current(md, payload, original, replacement)
                diffs = reconcile_latexml_to_markdown(raw, damaged, None, current)
                self.assertTrue(any(problem in diff for diff in diffs), diffs)

    def test_ordered_list_preserves_figure_caption_roles(self):
        from latexml_test_support import replace_current

        formula = '\\[\n  x+y\n\\]'
        raw = (
            '<article class="ltx_document"><h1>T05 Fixture</h1>'
            '<ol class="ltx_enumerate" start="3"><li>Before'
            '<figure id="F1"><img src="images/dup.png" width="20"/>'
            f'<div><figure id="F1a"><p>{formula}</p>'
            '<img src="assets/dup.png" width="30"/>'
            '<figcaption>Panel $x$.</figcaption></figure></div>'
            '<figcaption>Figure 1: Caption.</figcaption></figure>After</li>'
            '<li>Next</li></ol></article>')
        md, payload = self._parse_ordered_list(raw)
        self.assertIn('\n   ' + formula + '\n', md)
        self.assertIn('   [FIGURE] Panel $x$.\n\n   [FIGURE] Figure 1: Caption.\n\n   After', md)
        roles = [(c['content_type'], c['node'], c['figure'], c['subfigure'])
                 for c in payload['correspondences']
                 if c['content_type'] in ('image', 'figure-caption')]
        self.assertEqual(roles, [
            ('image', 'img[1]', 'figure[1]', None),
            ('image', 'img[2]', 'figure[1]', 1),
            ('figure-caption', 'figcaption[1]', 'figure[1]', 1),
            ('figure-caption', 'figcaption[2]', 'figure[1]', None),
        ])
        prefix = '   [FIGURE] Figure 1'
        damaged, current = replace_current(md, payload, prefix, prefix.lstrip())
        diffs = reconcile_latexml_to_markdown(raw, damaged, None, current)
        self.assertTrue(any('图题 figcaption[2] 的列表嵌套不符' in diff
                            for diff in diffs), diffs)
        wrong_owner = copy.deepcopy(payload)
        caption = next(c for c in wrong_owner['correspondences']
                       if c['node'] == 'figcaption[1]')
        caption['subfigure'] = None
        diffs = reconcile_latexml_to_markdown(raw, md, None, wrong_owner)
        self.assertTrue(any('图题 figcaption[1] subfigure 归属不符' in diff
                            for diff in diffs), diffs)

    def test_roundtrip_clean(self):
        raw, md, payload = self._payload()
        self.assertEqual(
            reconcile_latexml_to_markdown(raw, md, None, payload), [])

    def test_silent_override_rejected(self):
        raw, md, payload = self._payload()
        images = [c for c in payload['correspondences']
                  if c.get('content_type') == 'image']
        images[1]['conversion']['reference'] = \
            images[0]['conversion']['reference']
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('不得静默覆盖' in d for d in diffs))


class SubstitutionContractTest(_ResourceDirs):
    """05-3/05-4：resource_substitutions 逐项核对。"""

    def test_valid_substitution_passes(self):
        subs = [self.substitution]
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertEqual(problems, [])

    def test_roundtrip_with_substitution(self):
        subs = [self.substitution]
        raw, md, payload = self._payload(subs)
        self.assertIn('[IMG: images/crop.png]', md)
        self.assertEqual(reconcile_latexml_to_markdown(
            raw, md, None, payload), [])

    def test_wrong_pdf_version_rejected(self):
        subs = [copy.deepcopy(self.substitution)]
        subs[0]['pdf']['sha256'] = '0' * 64
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertTrue(any('摘要不符' in p for p in problems))

    def test_unknown_version_rejected(self):
        subs = [copy.deepcopy(self.substitution)]
        del subs[0]['pdf']['version']
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertTrue(any('版本不明' in p for p in problems))

    def test_version_mismatch_rejected(self):
        subs = [copy.deepcopy(self.substitution)]
        subs[0]['pdf']['version'] = 'v2'
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertTrue(any('不同版本不替换' in p for p in problems))

    def test_missing_fields_rejected(self):
        for key, expect in (('rect', '裁剪区域'), ('page', '页码'),
                            ('identity_basis', '身份依据'),
                            ('visual_basis', '视觉依据')):
            subs = [copy.deepcopy(self.substitution)]
            if key in ('identity_basis', 'visual_basis'):
                subs[0][key] = ''
            else:
                subs[0][key] = None
            problems = latexml.validate_resource_substitutions(
                {'resource_substitutions': subs}, str(self.base), 'v1')
            self.assertTrue(any(expect in p for p in problems), key)

    def test_product_digest_mismatch_rejected(self):
        subs = [copy.deepcopy(self.substitution)]
        subs[0]['product']['sha256'] = '0' * 64
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertTrue(any('产物摘要不符' in p for p in problems))

    def test_readable_original_rejected(self):
        subs = [copy.deepcopy(self.substitution)]
        subs[0]['original_ref'] = 'images/dup.png'
        problems = latexml.validate_resource_substitutions(
            {'resource_substitutions': subs}, str(self.base), 'v1')
        self.assertTrue(any('实际可读' in p for p in problems))

    def test_incomplete_basis_rejected_in_reconcile(self):
        subs = [copy.deepcopy(self.substitution)]
        raw, md, payload = self._payload(subs)
        payload['resource_substitutions'][0]['visual_basis'] = ''
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('视觉依据' in d for d in diffs))

    def test_declared_substitution_without_entry_rejected(self):
        subs = [self.substitution]
        raw, md, payload = self._payload(subs)
        payload['resource_substitutions'] = []
        diffs = reconcile_latexml_to_markdown(raw, md, None, payload)
        self.assertTrue(any('无对应原引用' in d or '缺失' in d or '身份' in d
                            for d in diffs))


class CheckPolicyResourceTest(_ResourceDirs):
    """05-6：资源目标与替换进 check_policy 投影。"""

    def test_image_projection_fields(self):
        subs = [self.substitution]
        _raw, md, payload = self._payload(subs)
        path = str(self.base / 'adaptation.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
        policy = latexml.check_policy_projection(payload, 0, len(md) + 1,
                                                 path)
        images = [n for n in policy['nodes']
                  if n['content_type'] == 'image']
        self.assertEqual(len(images), 3)
        self.assertIn('image_target', images[0])
        self.assertEqual(
            [i['image_target'] for i in images[:2]],
            ['images/images--dup.png', 'images/assets--dup.png'])
        before = copy.deepcopy(policy)
        for corr in payload['correspondences']:
            if corr.get('node') == 'img[2]':
                corr['conversion']['reference'] = 'images/hijack.png'
        changed = latexml.check_policy_projection(payload, 0, len(md) + 1,
                                                  path)
        self.assertNotEqual(before, changed)


if __name__ == '__main__':
    unittest.main()
