"""二期 ticket 05：可核验资源与同版本 PDF 补图闭环。

覆盖验收 05-1～05-7 的底层定向用例：同名异资源无冲突目标、
resource_substitutions 合同逐项核对（版本/区域/裁剪/产物/依据）、
替换关系的对账与交付闭合、check_policy 资源投影。
"""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
