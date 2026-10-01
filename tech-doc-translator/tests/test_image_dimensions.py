#!/usr/bin/env python3
"""第二批迁移 01：图片尺寸提取增强的直接行为证据（不经回补 CLI）。

覆盖 ticket 01 的直接验收：
- 四类真实解析入口在可靠比例下正确处理 px/pt 高度推导宽度；
- 已有有效宽度优先；未知比例、约束冲突明确未确定且不猜测宽度；
- 映射保留源节点、快照/资源身份及推导依据；未确定项附 reason_code；
- 同一源样例迁移前后正文 Markdown 逐字节一致（含代码缩进）。

正反例改编自 zn_dev 回补测试（A10/A28 相关场景），脱离完整回补 CLI。
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
SCRIPTS = MODULE / 'skills/tech-doc-translator/scripts'
FIXTURES = MODULE / 'tests/fixtures'


def make_png(path, w, h, color=b'\x01\x02\x03'):
    """生成 w×h 的真实 PNG（与 zn_dev 回补测试同一构造）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + color * w for _ in range(h))
    with open(path, 'wb') as handle:
        handle.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                     + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


# 各家族：解析脚本、CLI 参数形态（输出 Markdown / 映射定位）。
FAMILIES = ('single', 'reference', 'api', 'paginated')

CASE_HTML = '''<html><body><article>
<h1>尺寸推导</h1>
<img src="images/pic.png" style="height:50px">
<img src="images/pic.png" style="height:36pt">
<img src="images/pic.png" style="width:30px; height:50px">
<img src="images/pic.png" width="70" height="35">
<img src="images/unknown.bin" style="height:50px">
<img src="images/pic.png" style="height:50px" height="60">
<img src="images/pic.png">
<img src="images/pic.svg" style="height:25px">
</article></body></html>
'''

SVG_2_TO_1 = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
              '<rect width="200" height="100"/></svg>')


class HeightDerivationParseEntriesTest(unittest.TestCase):
    """四类解析入口的高度推导与未确定原因（A10 正反例，隔离回补）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_case(self):
        make_png(os.path.join(self.tmp, 'images/pic.png'), 200, 100)
        with open(os.path.join(self.tmp, 'images/unknown.bin'), 'wb') as h:
            h.write(b'\x89PNG\r\n\x1a\ngarbage')  # 无法判型/读取元信息
        with open(os.path.join(self.tmp, 'images/pic.svg'), 'w',
                  encoding='utf-8') as h:
            h.write(SVG_2_TO_1)
        html_path = os.path.join(self.tmp, 'page.html')
        with open(html_path, 'w', encoding='utf-8') as h:
            h.write(CASE_HTML)
        return html_path

    def run_family(self, family, html_path):
        """按家族实际 CLI 运行解析，返回 (Markdown 文本, 映射 payload)。"""
        if family == 'paginated':
            subprocess.run(
                [sys.executable, str(SCRIPTS / 'parse_paginated_html.py'),
                 html_path], capture_output=True, text=True, check=True)
            md_path = os.path.splitext(html_path)[0] + '.md'
        else:
            script = {'single': 'parse_single_page_html.py',
                      'reference': 'parse_reference_html.py',
                      'api': 'parse_api_html.py'}[family]
            md_path = os.path.join(self.tmp, '%s_out.md' % family)
            subprocess.run(
                [sys.executable, str(SCRIPTS / script), html_path, md_path],
                capture_output=True, text=True, check=True)
        map_path = os.path.splitext(md_path)[0] + '.images_display.json'
        with open(map_path, encoding='utf-8') as h:
            payload = json.load(h)
        with open(md_path, encoding='utf-8') as h:
            return h.read(), payload

    def check_family(self, family):
        html_path = self.build_case()
        md_text, payload = self.run_family(family, html_path)
        entries = {e['occurrence']: e for e in payload['entries']}
        undetermined = {e['occurrence']: e for e in payload['undetermined']}

        # 可靠比例：px 高度 50 × 2.0 = 100；依据与来源身份可回查
        first = entries[1]
        self.assertEqual(first['width']['value'], 100.0, entries)
        self.assertEqual(first['width']['basis'], 'height-derived-width')
        self.assertEqual(first['derived']['height'],
                         {'value': 50.0, 'unit': 'px',
                          'origin': 'inline-css-height'})
        self.assertEqual(first['derived']['aspect_ratio'], 2.0)
        self.assertEqual(first['derived']['aspect_source'], 'pillow-size')
        self.assertEqual(first['derived']['resource'], 'images/pic.png')
        self.assertTrue(first['resource_sha256'])
        self.assertTrue(first['source_node'])
        self.assertTrue(payload['snapshot_sha256'])

        # pt 高度：36pt → 48px × 2.0 = 96
        second = entries[2]
        self.assertEqual(second['width']['value'], 96.0, entries)
        self.assertEqual(second['derived']['height']['unit'], 'pt')
        self.assertEqual(second['derived']['height']['converted_px'], 48.0)

        # 已有有效宽度优先：内联 CSS 宽度与 HTML 属性宽度均不触发推导
        self.assertEqual(entries[3]['width']['value'], 30.0)
        self.assertEqual(entries[3]['width']['basis'], 'inline-css-width')
        self.assertNotIn('derived', entries[3])
        self.assertEqual(entries[4]['width']['value'], 70.0)
        self.assertEqual(entries[4]['width']['basis'], 'html-width-attribute')

        # SVG 固有比例（viewBox）推导：25 × 2.0 = 50
        self.assertEqual(entries[8]['width']['value'], 50.0)
        self.assertEqual(entries[8]['derived']['aspect_source'], 'svg-viewbox')

        # 未确定不猜测：未知比例、冲突约束、无约束各有明确原因
        self.assertEqual(undetermined[5]['reason_code'], 'unresolved-size')
        self.assertIn('高度推导失败', undetermined[5]['reason'])
        self.assertEqual(undetermined[6]['reason_code'], 'unresolved-size')
        self.assertIn('冲突', undetermined[6]['reason'])
        self.assertEqual(undetermined[7]['reason_code'], 'no-source-constraint')
        self.assertNotIn('width', undetermined[7])

        # 正文 Markdown 只含图片引用，尺寸走旁路不改写正文
        self.assertNotIn('height', md_text)
        return md_text

    def test_single_page_family(self):
        self.check_family('single')

    def test_reference_family(self):
        self.check_family('reference')

    def test_api_family(self):
        self.check_family('api')

    def test_paginated_family(self):
        self.check_family('paginated')

    def test_missing_snapshot_resource_undetermined_not_guessed(self):
        """快照资源缺失：高度推导明确未确定，不用交付图或像素猜宽度。"""
        html_path = self.build_case()
        os.remove(os.path.join(self.tmp, 'images/pic.png'))
        _, payload = self.run_family('single', html_path)
        undetermined = {e['occurrence']: e for e in payload['undetermined']}
        self.assertEqual(undetermined[1]['reason_code'], 'unresolved-size')
        self.assertIn('快照资源缺失', undetermined[1]['reason'])
        self.assertFalse(payload['entries'][:1]
                         and payload['entries'][0]['occurrence'] == 1)


class MarkdownUnchangedTest(unittest.TestCase):
    """解析正文与固定预期逐字节一致（含代码缩进），不依赖可移动分支引用。

    迁移时曾以 `git show main:` 动态对照证明与基线逐字节一致（一次性
    证据，记录于迁移评审）；该对照合入 main 后退化为自比较，改用
    tests/fixtures/expected_markdown/ 固定预期长期锁定正文行为。
    """

    FIXTURE_BY_FAMILY = {
        'single': 'sample_single_page.html',
        'reference': 'nested_reference.html',
        'api': 'multipage_site/api_page1.html',
        'paginated': 'paginated_page1.html',
    }

    EXPECTED_DIR = FIXTURES / 'expected_markdown'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def parse_current(self, family, html_path):
        env = dict(os.environ)
        if family == 'paginated':
            subprocess.run(
                [sys.executable,
                 os.path.join(str(SCRIPTS), 'parse_paginated_html.py'),
                 html_path], capture_output=True, text=True, check=True)
            md_path = os.path.splitext(html_path)[0] + '.md'
        else:
            script = {'single': 'parse_single_page_html.py',
                      'reference': 'parse_reference_html.py',
                      'api': 'parse_api_html.py'}[family]
            md_path = os.path.join(self.tmp, '%s_current.md' % family)
            subprocess.run(
                [sys.executable, os.path.join(str(SCRIPTS), script),
                 html_path, md_path],
                capture_output=True, text=True, check=True, env=env)
        with open(md_path, 'rb') as h:
            return h.read()

    def test_body_markdown_matches_fixed_expectation_per_family(self):
        for family, fixture in self.FIXTURE_BY_FAMILY.items():
            src = FIXTURES / fixture
            work = os.path.join(self.tmp, family)
            os.makedirs(work, exist_ok=True)
            html_path = os.path.join(work, os.path.basename(fixture))
            shutil.copyfile(src, html_path)
            actual = self.parse_current(family, html_path)
            expected_path = self.EXPECTED_DIR / ('%s.md' % family)
            self.assertTrue(expected_path.is_file(), expected_path)
            with open(expected_path, 'rb') as h:
                expected = h.read()
            self.assertEqual(
                expected, actual,
                '%s 家族正文 Markdown 与固定预期不一致（解析行为变化）'
                % family)


if __name__ == '__main__':
    unittest.main()
