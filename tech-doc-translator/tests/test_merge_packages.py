"""全量范围合并的固定语义验收：权威目标映射与候选身份核验（评审修复）。"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))
import merge_work_packages as merge
import recover_work_packages as rwp
import split_work_packages as swp
from _verification import (
    file_sha256,
    image_occurrence_fails,
    source_occurrence_digests,
)

SOURCE = """# 1. Sample

## 1.1. Alpha

A warp has 32 threads.

## 1.2. Beta

Second section body.
"""

TRANS = {
    'wp_001.md': ('# 1. Sample（样例）\n\n## 1.1. Alpha（阿尔法）\n\n'
                  'warp 有 32 个线程。\n'),
    'wp_002.md': '## 1.2. Beta（贝塔）\n\n第二小节正文。\n',
}

_FRONT_RE = re.compile(r'^(---\s*\n.*?\n---\s*\n)', re.S)


def _with_frontmatter(pkg_path, body):
    """保留源包 frontmatter 并替换正文，模拟真实译文目标文件。"""
    text = open(pkg_path, encoding='utf-8').read()
    m = _FRONT_RE.match(text)
    return (m.group(1) if m else '') + body


class MergePackagesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='merge_test_')
        self.src = os.path.join(self.tmp, 'src.md')
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(SOURCE)
        self.wps = os.path.join(self.tmp, 'wps')
        self.trans = os.path.join(self.tmp, 'trans')
        swp.split(self.src, self.wps, self.trans, 'h2')
        for name, body in TRANS.items():
            meta = self._front(os.path.join(self.wps, name))
            # 与真实流程一致：保留源包 frontmatter，把译文写入目标文件
            with open(meta['target_file'], 'w', encoding='utf-8') as f:
                f.write(_with_frontmatter(os.path.join(self.wps, name), body))
        self.targets = {
            name: self._front(os.path.join(self.wps, name))['target_file']
            for name in TRANS}
        self.evidence = os.path.join(self.tmp, 'evidence.json')
        self._write_evidence([name for name in TRANS])

    def _front(self, path):
        text = open(path, encoding='utf-8').read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta

    def _body_of(self, path):
        text = open(path, encoding='utf-8').read()
        m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.S)
        return text[m.end():]

    def _write_evidence(self, names):
        evidence = {}
        for name in names:
            target = self.targets[name]
            pkg = os.path.join(self.wps, name)
            evidence[name] = {
                'source_digest': self._front(pkg)['fragment_digest'],
                'target_digest': rwp._sha256(self._body_of(target)),
                'resource_digests': rwp._resource_digests(
                    self._body_of(target),
                    os.path.dirname(os.path.abspath(target))),
                'source_resource_digests': rwp._source_resource_digests(
                    self._body_of(pkg), self.tmp),
                'checker': rwp._script_identity(),
                'strong_tokens': [],
                'review': {'semantic': 'done', 'unresolved': []},
            }
        with open(self.evidence, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)

    def _mutated_copy(self, source_name, replacements):
        """保留映射字段的译文包副本，按替换规则改动 frontmatter。"""
        text = open(self.targets[source_name], encoding='utf-8').read()
        for old, new in replacements:
            text = re.sub(old, new, text, flags=re.M)
        name = 'mut_%s' % source_name
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def _merge(self, inputs):
        return merge.merge(
            os.path.join(self.tmp, 'out.md'), inputs, self.src, 'h2',
            self.wps, self.evidence, None, (), (), None, None)

    def test_correct_mapping_merges(self):
        received = self._merge([self.targets[name] for name in sorted(TRANS)])
        self.assertEqual(len(received), 2)
        out = os.path.join(self.tmp, 'out.md')
        text = open(out, encoding='utf-8').read()
        self.assertIn('阿尔法', text)
        self.assertIn('贝塔', text)

    def test_swapped_existing_targets_rejected(self):
        # 评审 P2-1：交换两个现存目标路径必须失败
        copy_a = self._mutated_copy('wp_001.md', [
            (r'^target_file:.*$', 'target_file: %s' % self.targets['wp_002.md'])])
        copy_b = self._mutated_copy('wp_002.md', [
            (r'^target_file:.*$', 'target_file: %s' % self.targets['wp_001.md'])])
        with self.assertRaises(ValueError) as ctx:
            self._merge([copy_a, copy_b])
        self.assertIn('错误目标映射', str(ctx.exception))

    def test_unrelated_existing_target_rejected(self):
        # 评审 P2-1：指向另一个现存但无关的文件必须失败
        unrelated = os.path.join(self.tmp, 'unrelated.md')
        with open(unrelated, 'w', encoding='utf-8') as f:
            f.write('与任何包无关的现存文件\n')
        copy = self._mutated_copy('wp_002.md', [
            (r'^target_file:.*$', 'target_file: %s' % unrelated)])
        with self.assertRaises(ValueError) as ctx:
            self._merge([self.targets['wp_001.md'], copy])
        self.assertIn('错误目标映射', str(ctx.exception))

    def test_missing_target_still_rejected(self):
        copy = self._mutated_copy('wp_002.md', [
            (r'^target_file:.*$', 'target_file: %s' % os.path.join(
                self.tmp, 'nowhere.md'))])
        with self.assertRaises(ValueError) as ctx:
            self._merge([self.targets['wp_001.md'], copy])
        self.assertIn('错误目标映射', str(ctx.exception))

    def test_wrong_order_still_rejected(self):
        copy = self._mutated_copy('wp_002.md', [
            (r'^source_order:.*$', 'source_order: 999')])
        with self.assertRaises(ValueError) as ctx:
            self._merge([self.targets['wp_001.md'], copy])
        self.assertIn('错误顺序映射', str(ctx.exception))

    def test_reverse_arguments_still_assemble_in_source_order(self):
        received = self._merge([self.targets['wp_002.md'],
                                self.targets['wp_001.md']])
        out = os.path.join(self.tmp, 'out.md')
        text = open(out, encoding='utf-8').read()
        self.assertLess(text.index('阿尔法'), text.index('贝塔'))


class CandidateImageIdentityTest(unittest.TestCase):
    """合并候选检查：完整通过必须建立每次图片出现的来源身份。"""

    PNG_A = b'\x89PNG\r\n\x1a\n' + b'A' * 32
    PNG_B = b'\x89PNG\r\n\x1a\n' + b'B' * 32

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='merge_img_test_')
        self.out_dir = os.path.join(self.tmp, 'out')
        os.makedirs(self.out_dir)
        # 源资源与交付资源各一份：源侧推导用 self.tmp，候选解析用 out_dir
        for name, data in (('a.png', self.PNG_A), ('b.png', self.PNG_B)):
            for base in (self.tmp, self.out_dir):
                os.makedirs(os.path.join(base, 'images'), exist_ok=True)
                with open(os.path.join(base, 'images', name), 'wb') as f:
                    f.write(data)
        self.source = '## S\n\n![a](images/a.png)\n\n![b](images/b.png)\n'

    def _candidate(self, body):
        path = os.path.join(self.tmp, 'candidate.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)
        return path

    def _check(self, candidate_text, source_text=None, digests=None):
        return merge._candidate_check_failures(
            candidate_text, source_text or self.source, self.out_dir,
            None, digests, (), (), '候选', source_dir=self.tmp)

    def test_same_content_passes_without_map(self):
        candidate = '## S（节）\n\n![图一](images/a.png)\n\n![图二](images/b.png)\n'
        self.assertEqual(self._check(candidate), [])

    def test_swapped_images_fail_without_map(self):
        candidate = '## S（节）\n\n![图一](images/b.png)\n\n![图二](images/a.png)\n'
        fails = self._check(candidate)
        self.assertTrue(any('来源身份不符' in f for f in fails))

    def test_fenced_image_example_not_missing(self):
        # 评审 P2-4：源与候选包含完全相同的围栏内 [IMG: 示例不构成漏图
        block = '\n```text\n[IMG: example.png]\n```\n'
        source = '## S\n\n正文\n' + block
        candidate = '## S（节）\n\n正文\n' + block
        self.assertEqual(
            merge._candidate_check_failures(
                candidate, source, self.out_dir, None, None, (), (),
                '候选', source_dir=self.tmp),
            [])

    def test_unverifiable_identity_blocks_full_merge(self):
        # 源 [IMG: 标记无法解析为本地资源且未提供映射：不得宣布完整通过
        source = '## S\n\n[IMG: snapshot/origin.png]\n'
        candidate = '## S（节）\n\n![图](images/a.png)\n'
        fails = self._check(candidate, source_text=source)
        self.assertTrue(any('来源身份未核验' in f for f in fails))

    def test_unverifiable_identity_passes_with_map(self):
        source = '## S\n\n[IMG: snapshot/origin.png]\n'
        candidate = '## S（节）\n\n![图](images/a.png)\n'
        fails = merge._candidate_check_failures(
            candidate, source, self.out_dir, None,
            [file_sha256(os.path.join(self.tmp, 'images', 'a.png'))],
            (), (), '候选', source_dir=self.tmp)
        self.assertEqual(fails, [])


class SourceOccurrenceDigestsTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='src_digest_test_')
        with open(os.path.join(self.tmp, 'a.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'A' * 32)

    def test_digests_follow_document_order(self):
        text = '![x][p]\n\n[IMG: b.png]\n\n![y](a.png)\n\n[p]: a.png\n'
        self.assertIsNone(source_occurrence_digests(text, self.tmp))

    def test_resolvable_occurrences_yield_digests(self):
        text = '![x][p]\n\n![y](a.png)\n\n[p]: a.png\n'
        digests = source_occurrence_digests(text, self.tmp)
        expected = file_sha256(os.path.join(self.tmp, 'a.png'))
        self.assertEqual(digests, [expected, expected])

    def test_no_images_yields_empty_basis(self):
        self.assertEqual(source_occurrence_digests('纯文本。\n', self.tmp), [])

    def test_source_digests_drive_occurrence_check(self):
        with open(os.path.join(self.tmp, 'renamed.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'A' * 32)
        text = '![x](a.png)\n'
        digests = source_occurrence_digests(text, self.tmp)
        self.assertEqual(
            image_occurrence_fails('![x](renamed.png)\n', self.tmp,
                                   expected_digests=digests), [])


class MergeSvgIdentityTest(unittest.TestCase):
    """最终合并入口：SVG 子资源换图在候选复验被检出且不覆盖成品（评审 P1）。"""

    PARENT = ('<svg xmlns="http://www.w3.org/2000/svg">'
              '<image href="child.svg"/></svg>')
    RED = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>'
    BLUE = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="blue"/></svg>'
    SOURCE = '## Image Doc\n\n看图。\n\n![p](images/parent.svg)\n'
    TRANS = '## Image Doc（图示文档）\n\n看图。\n\n![p](images/parent.svg)\n'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='merge_svg_test_')
        self.src = os.path.join(self.tmp, 'src', 'source.md')
        os.makedirs(os.path.dirname(self.src))
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(self.SOURCE)
        self._write_svg(os.path.join(self.tmp, 'src', 'images', 'parent.svg'),
                        self.PARENT)
        self._write_svg(os.path.join(self.tmp, 'src', 'images', 'child.svg'),
                        self.RED)
        self.wps = os.path.join(self.tmp, 'wps')
        self.trans = os.path.join(self.tmp, 'trans')
        written = swp.split(self.src, self.wps, self.trans, 'h2')
        self.target = self._front(written[0])['target_file']
        self._write_svg(self.target, self.TRANS,
                        front=os.path.join(self.wps, 'wp_001.md'))
        self._write_svg(os.path.join(self.trans, 'images', 'parent.svg'),
                        self.PARENT)
        self._write_svg(os.path.join(self.trans, 'images', 'child.svg'),
                        self.RED)
        self._write_svg(os.path.join(self.tmp, 'images', 'parent.svg'),
                        self.PARENT)
        self._write_svg(os.path.join(self.tmp, 'images', 'child.svg'),
                        self.RED)
        self.out = os.path.join(self.tmp, 'out.md')
        self.evidence = os.path.join(self.tmp, 'evidence.json')
        self._write_evidence()
        self._merge()
        self.out_before = open(self.out, 'rb').read()

    def _write_svg(self, path, content, front=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            if front:
                text = open(front, encoding='utf-8').read()
                f.write(re.match(r'^---\s*\n.*?\n---\s*\n', text,
                                 re.S).group(0))
            f.write(content)

    def _front(self, path):
        text = open(path, encoding='utf-8').read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta

    def _write_evidence(self):
        pkg = os.path.join(self.wps, 'wp_001.md')
        body = _body_of(self.target)
        pkg_body = _body_of(pkg)
        evidence = {'wp_001.md': {
            'source_digest': self._front(pkg)['fragment_digest'],
            'target_digest': rwp._sha256(body),
            'resource_digests': rwp._resource_digests(
                body, os.path.dirname(os.path.abspath(self.target))),
            'source_resource_digests': rwp._source_resource_digests(
                pkg_body, os.path.join(self.tmp, 'src')),
            'checker': rwp._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
        }}
        with open(self.evidence, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)

    def _merge(self):
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            merge.merge(self.out, [self.target], self.src, 'h2',
                        self.wps, self.evidence, None, (), (), None, None)
        return self.output

    def test_delivery_subresource_swap_rejected_and_keeps_previous(self):
        # 仅换译侧子资源：候选复验检出，已有成品不被覆盖
        self._write_svg(os.path.join(self.tmp, 'images', 'child.svg'),
                        self.BLUE)
        with self.assertRaises(SystemExit):
            self._merge()
        self.assertIn('来源身份不符', self.output.getvalue())
        self.assertEqual(open(self.out, 'rb').read(), self.out_before)

    def test_missing_delivered_dependency_rejected(self):
        # 译侧依赖缺失：离线核验拒绝，不静默通过
        os.remove(os.path.join(self.tmp, 'images', 'child.svg'))
        with self.assertRaises(SystemExit):
            self._merge()
        self.assertIn('本地依赖缺失', self.output.getvalue())
        self.assertEqual(open(self.out, 'rb').read(), self.out_before)

    def test_restored_tree_merges_again(self):
        output = self._merge()
        self.assertIn('全量范围', output.getvalue())


def _body_of(path):
    """去掉 frontmatter 的包正文（测试辅助，供证据摘要计算）。"""
    text = open(path, encoding='utf-8').read()
    m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.S)
    return text[m.end():] if m else text


class MergeUnsupportedStructureTest(unittest.TestCase):
    """评审 P1/P2：未验证结构阻断合并，失败保持已有成品字节不变。"""

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
    SOURCE = '## Image Doc\n\n看图。\n\n![p](images/fig.svg)\n'
    TRANS = '## Image Doc（图示文档）\n\n看图。\n\n![p](images/fig.svg)\n'

    def setUp(self):
        self._tmp_pool = []

    def _setup(self, svg_text):
        tmp = tempfile.mkdtemp(prefix='merge_unsup_test_')
        self._tmp_pool.append(tmp)
        self.tmp = tmp
        self.src = os.path.join(tmp, 'src', 'source.md')
        os.makedirs(os.path.dirname(self.src))
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(self.SOURCE)
        for base in (os.path.join(tmp, 'src', 'images'),
                     os.path.join(tmp, 'trans', 'images'),
                     os.path.join(tmp, 'images')):
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
        pkg_text = open(written[0], encoding='utf-8').read()
        self.target = self._front(written[0])['target_file']
        with open(self.target, 'w', encoding='utf-8') as f:
            f.write(_with_frontmatter(written[0], self.TRANS))
        self.out = os.path.join(tmp, 'out.md')
        with open(self.out, 'wb') as f:
            f.write('# 既有有效成品\n\n旧内容保持不变。\n'.encode('utf-8'))
        self.sentinel = open(self.out, 'rb').read()
        self.evidence = os.path.join(tmp, 'evidence.json')
        self._write_evidence()
        return tmp

    def _front(self, path):
        text = open(path, encoding='utf-8').read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        return meta

    def _write_evidence(self):
        pkg = os.path.join(self.wps, 'wp_001.md')
        body = _body_of(self.target)
        pkg_body = _body_of(pkg)
        evidence = {'wp_001.md': {
            'source_digest': self._front(pkg)['fragment_digest'],
            'target_digest': rwp._sha256(body),
            'resource_digests': rwp._resource_digests(
                body, os.path.dirname(os.path.abspath(self.target))),
            'source_resource_digests': rwp._source_resource_digests(
                pkg_body, os.path.join(self.tmp, 'src')),
            'checker': rwp._script_identity(),
            'strong_tokens': [],
            'review': {'semantic': 'done', 'unresolved': []},
        }}
        with open(self.evidence, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, ensure_ascii=False)

    def _candidate_fails(self):
        return merge._candidate_check_failures(
            self.TRANS, self.SOURCE, self.tmp, None, None, (), (),
            '候选', source_dir=os.path.join(self.tmp, 'src'))

    def test_pi_svg_candidate_rejected(self):
        self._setup(self.PI_SVG)
        fails = self._candidate_fails()
        self.assertTrue(any('未验证' in f for f in fails), fails)

    def test_bad_url_candidate_rejected(self):
        self._setup(self.BAD_SVG)
        fails = self._candidate_fails()
        self.assertTrue(any('无法解析' in f for f in fails), fails)

    def test_import_trailing_error_candidate_rejected(self):
        # 复审 P2：@import 目标存在但参数尾部有解析错误，候选不放行
        self._setup(self.BAD_IMPORT_SVG)
        fails = self._candidate_fails()
        self.assertTrue(any('无法解析' in f for f in fails), fails)

    def test_legal_neighbor_candidate_passes(self):
        self._setup(self.LEGAL_SVG)
        self.assertEqual(self._candidate_fails(), [])

    def test_merge_failure_preserves_existing_output(self):
        # 含处理指令的交付：合并拒绝（证据与候选两道门均不放行），
        # 已有成品字节不变
        self._setup(self.PI_SVG)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises((SystemExit, ValueError)):
                merge.merge(self.out, [self.target], self.src, 'h2',
                            self.wps, self.evidence, None, (), (), None, None)
        self.assertEqual(open(self.out, 'rb').read(), self.sentinel)

    def test_import_merge_failure_preserves_existing_output(self):
        # 复审 P2：导入参数尾部解析错误同样阻断合并，成品字节不变
        self._setup(self.BAD_IMPORT_SVG)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises((SystemExit, ValueError)):
                merge.merge(self.out, [self.target], self.src, 'h2',
                            self.wps, self.evidence, None, (), (), None, None)
        self.assertEqual(open(self.out, 'rb').read(), self.sentinel)


if __name__ == '__main__':
    unittest.main()
