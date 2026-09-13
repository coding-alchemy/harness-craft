"""依据当前源与复核证据恢复的固定语义验收（任务 06）。"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import recover_work_packages as recover
import split_work_packages as swp
from _verification import file_sha256

SOURCE = """# 1. Sample Chapter

## 1.1. Alpha

A warp has 32 threads.

- item one
- item two

```c
int a = 1;
```

## 1.2. Beta

脚注引用[^1]。

[^1]: 注
"""

TRANS = {
    'wp_001.md': '# 1. Sample Chapter（样例章）\n\n## 1.1. Alpha（阿尔法）\n\n'
                 'warp 有 32 个线程。\n\n- 第一项\n- 第二项\n\n```c\nint a = 1;\n```\n',
    'wp_002.md': '## 1.2. Beta（贝塔）\n\n脚注引用[^1]。\n\n[^1]: 注\n',
}


class RecoveryTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='recover_test_')
        self.src = os.path.join(self.tmp, 'src.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(SOURCE)
        self.wps = os.path.join(self.tmp, 'wps')
        self.trans = os.path.join(self.tmp, 'trans')
        swp.split(self.src, self.wps, self.trans, 'h2')
        # 两个翻译目标
        for name, body in TRANS.items():
            meta, _ = self._front(os.path.join(self.wps, name))
            with open(meta['target_file'], 'w', encoding='utf-8') as f:
                f.write(body)

    def _front(self, path):
        text = open(path).read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        if not m:
            return {}, text
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta, text[m.end():]

    def _expected_digests(self):
        digests = {}
        for name in sorted(os.listdir(self.wps)):
            if name.endswith('.md'):
                meta, _ = self._front(os.path.join(self.wps, name))
                digests[name] = meta['fragment_digest']
        return digests

    def _evidence(self, names, mutate=None):
        digests = self._expected_digests()
        evidence = {}
        for name in names:
            meta, _ = self._front(os.path.join(self.wps, name))
            target = meta['target_file']
            _, body = self._front(target)
            _, pkg_body = self._front(os.path.join(self.wps, name))
            entry = {
                'source_digest': digests[name],
                'target_digest': recover._sha256(body),
                'resource_digests': [],
                'source_resource_digests': recover._source_resource_digests(
                    pkg_body, self.tmp),
                'checker': recover._script_identity(),
                'strong_tokens': [],
                'review': {'semantic': 'done', 'unresolved': []},
            }
            if mutate:
                mutate(name, entry)
            evidence[name] = entry
        return evidence

    def _write_evidence(self, evidence):
        path = os.path.join(self.tmp, 'evidence.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)
        return path

    def run_recover(self, evidence=None):
        ev = self._write_evidence(evidence) if evidence is not None else None
        return recover.recover(self.src, self.wps, self.trans,
                               'h2', ev, [], [])

    def test_no_evidence_means_pending_not_reusable(self):
        reusable, missing, invalidated, pending, _ = self.run_recover({})
        self.assertEqual(reusable, [])
        self.assertEqual(len(pending), 2)
        self.assertTrue(all('无复核证据' in p['reason'] for p in pending))

    def test_valid_evidence_reuses(self):
        evidence = self._evidence(['wp_001.md', 'wp_002.md'])
        reusable, missing, invalidated, pending, _ = self.run_recover(evidence)
        self.assertEqual(len(reusable), 2)
        self.assertEqual(pending, [])

    def test_source_change_invalidates_only_affected_package(self):
        # A3：源数字 32→64
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(SOURCE.replace('32 threads', '64 threads'))
        evidence = self._evidence(['wp_001.md', 'wp_002.md'])
        reusable, missing, invalidated, pending, _ = self.run_recover(evidence)
        names = [i['name'] for i in invalidated]
        self.assertEqual(names, ['wp_001.md'])
        self.assertEqual([r['name'] for r in reusable], ['wp_002.md'])

    def test_heading_only_translation_fails(self):
        # A4：只剩标题
        meta, _ = self._front(os.path.join(self.wps, 'wp_001.md'))
        with open(meta['target_file'], 'w', encoding='utf-8') as f:
            f.write('# 1. Sample Chapter（样例章）\n\n## 1.1. Alpha（阿尔法）\n')
        evidence = self._evidence(['wp_001.md'])
        reusable, missing, invalidated, pending, _ = self.run_recover(evidence)
        self.assertEqual(reusable, [])
        self.assertTrue(any('仅剩标题' in i['reason'] for i in invalidated))

    def test_tampered_target_invalidates_evidence(self):
        evidence = self._evidence(['wp_001.md'])
        meta, _ = self._front(os.path.join(self.wps, 'wp_001.md'))
        with open(meta['target_file'], 'a', encoding='utf-8') as f:
            f.write('多出来的一个字')
        reusable, missing, invalidated, pending, _ = self.run_recover(evidence)
        self.assertEqual(reusable, [])
        self.assertTrue(any('目标正文摘要' in p['reason'] for p in pending))

    def test_forged_semantic_pass_not_accepted(self):
        # 伪造“计数 PASS”字段不能替代语义证据
        def mutate(name, entry):
            entry['review'] = {'semantic': 'done', 'unresolved': ['缺一段']}
            entry['mechanical_count'] = 'PASS'
        evidence = self._evidence(['wp_001.md'], mutate)
        reusable, _, _, pending, _ = self.run_recover(evidence)
        self.assertEqual(reusable, [])
        self.assertTrue(any('未解决项' in p['reason'] for p in pending))

    def test_old_source_packages_never_overwritten(self):
        before = {name: file_sha256(os.path.join(self.wps, name))
                  for name in os.listdir(self.wps)}
        self.run_recover({})
        after = {name: file_sha256(os.path.join(self.wps, name))
                 for name in os.listdir(self.wps)}
        self.assertEqual(before, after)

    def test_evidence_without_source_resources_is_pending(self):
        # 证据缺少源资源摘要字段 → 不能放行，也不误报为已失效重做
        evidence = self._evidence(['wp_001.md'])
        for entry in evidence.values():
            del entry['source_resource_digests']
        reusable, missing, invalidated, pending, _ = self.run_recover(evidence)
        self.assertEqual(reusable, [])
        self.assertEqual(invalidated, [])
        self.assertTrue(any('源资源摘要' in p['reason'] for p in pending))


class ImageSourceRecoveryTest(unittest.TestCase):
    """源资源内容绑定：仅改源图片字节必须使旧证据失效（评审 P1-4）。"""

    SOURCE = '## Image Section\n\n看图。\n\n![示意](images/d.svg)\n'
    RED_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>'
    BLUE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg">'
                '<rect fill="blue"/></svg>')
    TRANS = '## Image Section（图示小节）\n\n看图。\n\n![示意](images/d.svg)\n'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='recover_img_test_')
        self.src = os.path.join(self.tmp, 'src.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(self.SOURCE)
        os.makedirs(os.path.join(self.tmp, 'images'))
        with open(os.path.join(self.tmp, 'images', 'd.svg'), 'w',
                  encoding='utf-8') as f:
            f.write(self.RED_SVG)
        self.wps = os.path.join(self.tmp, 'wps')
        self.trans = os.path.join(self.tmp, 'trans')
        written = swp.split(self.src, self.wps, self.trans, 'h2')
        meta, _ = self._front(written[0])
        target = meta['target_file']
        os.makedirs(os.path.join(os.path.dirname(target), 'images'))
        with open(target, 'w', encoding='utf-8') as f:
            f.write(self.TRANS)
        with open(os.path.join(os.path.dirname(target), 'images', 'd.svg'),
                  'w', encoding='utf-8') as f:
            f.write(self.RED_SVG)
        self.target = target
        self._write_evidence(self._evidence())

    def _front(self, path):
        text = open(path).read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        if not m:
            return {}, text
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta, text[m.end():]

    def _evidence(self):
        meta, pkg_body = self._front(os.path.join(self.wps, 'wp_001.md'))
        _, body = self._front(self.target)
        return {'wp_001.md': {
            'source_digest': meta['fragment_digest'],
            'target_digest': recover._sha256(body),
            'resource_digests': recover._resource_digests(
                body, os.path.dirname(os.path.abspath(self.target))),
            'source_resource_digests': recover._source_resource_digests(
                pkg_body, self.tmp),
            'checker': recover._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
        }}

    def _write_evidence(self, evidence):
        with open(os.path.join(self.tmp, 'evidence.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)

    def run_recover(self):
        return recover.recover(
            self.src, self.wps, self.trans, 'h2',
            os.path.join(self.tmp, 'evidence.json'), [], [])

    def test_unchanged_source_stays_reusable(self):
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual([r['name'] for r in reusable], ['wp_001.md'])
        self.assertEqual(pending, [])

    def test_source_image_byte_change_invalidates_reuse(self):
        with open(os.path.join(self.tmp, 'images', 'd.svg'), 'w',
                  encoding='utf-8') as f:
            f.write(self.BLUE_SVG)
        reusable, missing, invalidated, pending, _ = self.run_recover()
        self.assertEqual(reusable, [])
        self.assertEqual(invalidated, [])
        self.assertTrue(any('源资源摘要与当前源资源不符' in p['reason']
                            for p in pending))

    def test_restored_source_reusable_again(self):
        with open(os.path.join(self.tmp, 'images', 'd.svg'), 'w',
                  encoding='utf-8') as f:
            f.write(self.BLUE_SVG)
        self.run_recover()
        with open(os.path.join(self.tmp, 'images', 'd.svg'), 'w',
                  encoding='utf-8') as f:
            f.write(self.RED_SVG)
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual([r['name'] for r in reusable], ['wp_001.md'])


class FencedImageExampleTest(unittest.TestCase):
    """源与译文相同的围栏内 [IMG: 代码示例不构成漏图（评审 P2-4）。"""

    def test_identical_fenced_marker_example_not_counted(self):
        block = '\n```text\n[IMG: example.png]\n```\n'
        src = '## S\n\n正文。\n' + block
        trans = '## S（节）\n\n正文。\n' + block
        fails, _ = recover._fragment_hard_checks(src, trans, 't.md', [], [])
        self.assertFalse(any('图片数量不足' in f for f in fails),
                         '围栏内代码示例被误计为图片: %s' % fails)


class SvgDependencyEvidenceTest(unittest.TestCase):
    """SVG 子资源纳入证据绑定：仅换子资源字节即失效（评审 P1/P3）。"""

    SOURCE = '## Image Section\n\n看图。\n\n![示意](images/parent.svg)\n'
    PARENT = ('<svg xmlns="http://www.w3.org/2000/svg">'
              '<image href="child.svg"/></svg>')
    RED = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>'
    BLUE = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="blue"/></svg>'
    TRANS = '## Image Section（图示小节）\n\n看图。\n\n![示意](images/parent.svg)\n'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='recover_svg_test_')
        self.src = os.path.join(self.tmp, 'src.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(self.SOURCE)
        self._write_svg(os.path.join(self.tmp, 'images', 'parent.svg'),
                        self.PARENT)
        self._write_svg(os.path.join(self.tmp, 'images', 'child.svg'),
                        self.RED)
        self.wps = os.path.join(self.tmp, 'wps')
        self.trans = os.path.join(self.tmp, 'trans')
        written = swp.split(self.src, self.wps, self.trans, 'h2')
        meta, _ = self._front(written[0])
        self.target = meta['target_file']
        self._write_svg(self.target, self.TRANS, front=os.path.join(
            self.wps, 'wp_001.md'))
        self._write_svg(os.path.join(self.trans, 'images', 'parent.svg'),
                        self.PARENT)
        self._write_svg(os.path.join(self.trans, 'images', 'child.svg'),
                        self.RED)
        self._write_evidence(self._evidence())

    def _write_svg(self, path, content, front=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            if front:
                text = open(front, encoding='utf-8').read()
                m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.S)
                f.write(m.group(0))
            f.write(content)

    def _front(self, path):
        text = open(path).read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        if not m:
            return {}, text
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta, text[m.end():]

    def _evidence(self):
        meta, pkg_body = self._front(os.path.join(self.wps, 'wp_001.md'))
        _, body = self._front(self.target)
        return {'wp_001.md': {
            'source_digest': meta['fragment_digest'],
            'target_digest': recover._sha256(body),
            'resource_digests': recover._resource_digests(
                body, os.path.dirname(os.path.abspath(self.target))),
            'source_resource_digests': recover._source_resource_digests(
                pkg_body, self.tmp),
            'checker': recover._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
        }}

    def _write_evidence(self, evidence):
        with open(os.path.join(self.tmp, 'evidence.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)

    def run_recover(self):
        return recover.recover(
            self.src, self.wps, self.trans, 'h2',
            os.path.join(self.tmp, 'evidence.json'), [], [])

    def test_baseline_reusable(self):
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual([r['name'] for r in reusable], ['wp_001.md'])
        self.assertEqual(pending, [])

    def test_source_subresource_swap_invalidates(self):
        # 仅修改源侧子资源，旧证据不得继续判可复用
        self._write_svg(os.path.join(self.tmp, 'images', 'child.svg'),
                        self.BLUE)
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual(reusable, [])
        self.assertTrue(any('源资源摘要与当前源资源不符' in p['reason']
                            for p in pending))

    def test_delivery_subresource_swap_invalidates(self):
        # 仅修改译侧子资源，旧证据不得继续放行
        self._write_svg(os.path.join(self.trans, 'images', 'child.svg'),
                        self.BLUE)
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual(reusable, [])
        self.assertTrue(any('资源摘要与当前文件不符' in p['reason']
                            for p in pending))

    def test_unreadable_resource_pending_not_crash(self):
        # 不可读资源：按待复核报告，不抛未处理异常，也不授予复用资格
        child = os.path.join(self.trans, 'images', 'child.svg')
        os.chmod(child, 0)
        try:
            reusable, _, _, pending, _ = self.run_recover()
        finally:
            os.chmod(child, 0o644)
        self.assertEqual(reusable, [])
        self.assertTrue(any('无法核验' in p['reason'] for p in pending))

    def test_both_sides_unverifiable_never_valid(self):
        # 两侧都无法核验时摘要可能恰好相等：仍不得判为有效
        os.remove(os.path.join(self.tmp, 'images', 'child.svg'))
        os.remove(os.path.join(self.trans, 'images', 'child.svg'))
        self._write_evidence(self._evidence())
        reusable, _, _, pending, _ = self.run_recover()
        self.assertEqual(reusable, [])
        self.assertTrue(any('无法核验' in p['reason'] for p in pending))


class UnsupportedStructureRecoveryTest(unittest.TestCase):
    """评审 P1/P2：未支持处理指令与 CSS 解析错误的资源，恢复不得判可复用。

    有效证据也不放行：证据核对重新计算资源摘要，无法核验即待复核。
    """

    NS = 'xmlns="http://www.w3.org/2000/svg"'
    PI_SVG = ('<?xml version="1.0"?>\n'
              '<?xml-stylesheet type="text/css" href="paint.css"?>\n'
              '<svg %s><rect width="10" height="10"/></svg>' % NS)
    BAD_SVG = ('<svg %s><rect width="10" height="10" fill="url(foo bar)"/>'
               '</svg>' % NS)
    BAD_IMPORT_SVG = ('<svg %s><style>@import "paint.css" url(foo bar);'
                      '</style><rect width="10" height="10"/></svg>' % NS)
    LEGAL_SVG = ('<svg %s><rect width="10" height="10" fill="red"/>'
                 '</svg>' % NS)
    SOURCE = '## Image Section\n\n看图。\n\n![示意](images/fig.svg)\n'
    TRANS = '## Image Section（图示小节）\n\n看图。\n\n![示意](images/fig.svg)\n'

    def setUp(self):
        self._tmp_pool = []

    def _setup(self, svg_text):
        tmp = tempfile.mkdtemp(prefix='recover_unsup_test_')
        self._tmp_pool.append(tmp)
        self.tmp = tmp
        self.src = os.path.join(tmp, 'src.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(self.SOURCE)
        for base in (os.path.join(tmp, 'images'),
                     os.path.join(tmp, 'trans', 'images')):
            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, 'fig.svg'), 'w',
                      encoding='utf-8') as f:
                f.write(svg_text)
            with open(os.path.join(base, 'paint.css'), 'w',
                      encoding='utf-8') as f:
                f.write('rect { fill: red; }\n')
        self.wps = os.path.join(tmp, 'wps')
        self.trans = os.path.join(tmp, 'trans')
        written = swp.split(self.src, self.wps, self.trans, 'h2')
        meta, _ = self._front(written[0])
        self.target = meta['target_file']
        # 与真实流程一致：译文目标保留源包 frontmatter
        pkg_text = open(written[0], encoding='utf-8').read()
        m = re.match(r'^---\s*\n.*?\n---\s*\n', pkg_text, re.S)
        with open(self.target, 'w', encoding='utf-8') as f:
            f.write(m.group(0) + self.TRANS)
        self.evidence = self._evidence()
        return tmp

    def _front(self, path):
        text = open(path).read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta, text[m.end():]

    def _evidence(self):
        meta, pkg_body = self._front(os.path.join(self.wps, 'wp_001.md'))
        _, body = self._front(self.target)
        return {'wp_001.md': {
            'source_digest': meta['fragment_digest'],
            'target_digest': recover._sha256(body),
            'resource_digests': recover._resource_digests(
                body, os.path.dirname(os.path.abspath(self.target))),
            'source_resource_digests': recover._source_resource_digests(
                pkg_body, self.tmp),
            'checker': recover._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
        }}

    def _write_evidence(self):
        path = os.path.join(self.tmp, 'evidence.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.evidence, f, ensure_ascii=False)
        return path

    def _recover(self):
        return recover.recover(self.src, self.wps, self.trans, 'h2',
                               self._write_evidence(), [], [])

    def test_pi_svg_never_reusable(self):
        # 反例：目标 CSS 缺失/被替换时旧行为仍判可复用
        self._setup(self.PI_SVG)
        for mutate in (lambda: None,
                       lambda: os.unlink(os.path.join(
                           self.trans, 'images', 'paint.css'))):
            mutate()
            self.evidence = self._evidence()  # 模拟"有效旧恢复证据"
            reusable, _, invalidated, pending, _ = self._recover()
            self.assertEqual(reusable, [])
            reasons = [p['reason'] for p in pending + invalidated]
            self.assertTrue(any('无法核验' in r for r in reasons), reasons)

    def test_bad_url_svg_never_reusable(self):
        self._setup(self.BAD_SVG)
        self.evidence = self._evidence()
        reusable, _, invalidated, pending, _ = self._recover()
        self.assertEqual(reusable, [])
        reasons = [p['reason'] for p in pending + invalidated]
        self.assertTrue(any('无法核验' in r for r in reasons), reasons)

    def test_import_trailing_error_svg_never_reusable(self):
        # 复审 P2：导入目标存在但参数尾部有解析错误，同样不得复用
        self._setup(self.BAD_IMPORT_SVG)
        self.evidence = self._evidence()
        reusable, _, invalidated, pending, _ = self._recover()
        self.assertEqual(reusable, [])
        reasons = [p['reason'] for p in pending + invalidated]
        self.assertTrue(any('无法核验' in r for r in reasons), reasons)

    def test_legal_svg_still_reusable(self):
        # 合法相邻输入：无处理指令、无解析错误的资源保持原有复用行为
        self._setup(self.LEGAL_SVG)
        self.evidence = self._evidence()
        reusable, _, _, pending, _ = self._recover()
        self.assertEqual([r['name'] for r in reusable], ['wp_001.md'])
        self.assertEqual(pending, [])


if __name__ == '__main__':
    unittest.main()
