"""离线图片身份与交付路径的固定语义验收（任务 05）。"""
import glob
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _verification import (
    check_image_file,
    file_sha256,
    image_marker_refs,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
    local_resource_digest,
    resolve_delivery_image,
    resource_identity_digest,
)


PNG_HEAD = b'\x89PNG\r\n\x1a\n' + b'0' * 32


def make_png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(PNG_HEAD)


class ImageReferencesTest(unittest.TestCase):

    def test_inline_and_reference_style_in_order(self):
        text = '![a](images/a.png)\n\n![b][pic]\n\n[pic]: images/b.png\n'
        refs = image_references(text)
        self.assertEqual([s for _, s in refs],
                         ['images/a.png', 'images/b.png'])

    def test_code_fence_image_syntax_ignored(self):
        text = '```c\n![fake](images/none.png)\n```\n\n![real](images/r.png)\n'
        refs = image_references(text)
        self.assertEqual([s for _, s in refs], ['images/r.png'])

    def test_undefined_reference_is_none(self):
        refs = image_references('![b][missing]\n')
        self.assertEqual([s for _, s in refs], [None])

    def test_mixed_syntax_same_line_keeps_source_order(self):
        # 评审 P2-7：同一行混用两种语法时按实际字符位置排序
        text = '前文 ![A][a] 中段 ![B](b.png) 尾\n\n[a]: a.png\n'
        refs = image_references(text)
        self.assertEqual([s for _, s in refs], ['a.png', 'b.png'])
        swapped = '前文 ![B](b.png) 中段 ![A][a] 尾\n\n[a]: a.png\n'
        refs = image_references(swapped)
        self.assertEqual([s for _, s in refs], ['b.png', 'a.png'])

    def test_repeated_occurrences_keep_independent_order(self):
        text = ('![a](a.png) ![b][pic] ![a](a.png)\n\n[pic]: b.png\n')
        refs = image_references(text)
        self.assertEqual([s for _, s in refs],
                         ['a.png', 'b.png', 'a.png'])

    def test_occurrence_count_covers_markdown_and_markers(self):
        text = ('前言 ![a](a.png)\n\n```c\n![fake](none.png)\n```\n\n'
                '[IMG: images/adv.png]\n\n![b][pic]\n\n[pic]: b.png\n')
        self.assertEqual(image_occurrence_count(text), 3)
        self.assertEqual(image_occurrence_count('纯文本，无图。\n'), 0)

    def test_occurrence_count_excludes_fenced_marker_example(self):
        # 评审 P2-4：代码围栏内的 [IMG: 示例不是真实图片出现
        text = ('```text\n[IMG: example.png]\n```\n\n[IMG: real.png]\n')
        self.assertEqual(image_marker_refs(text)[0][1], 'real.png')
        self.assertEqual(image_occurrence_count(text), 1)

    def test_inline_code_image_literal_not_a_reference(self):
        # 03-S3：行内代码内的图片字面量是代码内容，共享枚举统一排除；
        # 代码字面量与真实引用同路径共存不误删真实图片
        text = ('示例 `![example](fake.png)` 与 ![real](same.png)\n\n'
                '后文 `![example](same.png)` 结束\n')
        refs = image_references(text)
        self.assertEqual([s for _, s in refs], ['same.png'])
        self.assertEqual(image_occurrence_count(text), 1)

    def test_reference_style_inside_code_excluded(self):
        text = '`![a][pic]`\n\n![b](b.png)\n\n[pic]: a.png\n'
        refs = image_references(text)
        self.assertEqual([s for _, s in refs], ['b.png'])

    def test_image_alt_backtick_kept_as_real_reference(self):
        # alt 内反引号不构成代码跨度（幻影防护），图片仍是真实出现
        refs = image_references('![a`x`](r.png)\n')
        self.assertEqual([s for _, s in refs], ['r.png'])


class ResolveDeliveryImageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_rejects_hotlink_absolute_and_escape(self):
        self.assertIsNone(resolve_delivery_image(
            'https://x/y.png', self.tmp)[0])
        self.assertIsNone(resolve_delivery_image(
            '/var/machine/y.png', self.tmp)[0])
        self.assertIsNone(resolve_delivery_image(
            '../outside/y.png', self.tmp)[0])

    def test_relative_resolves_under_root(self):
        path, reason = resolve_delivery_image(
            'images/y.png', self.tmp, self.tmp)
        self.assertIsNone(reason)
        self.assertEqual(path, os.path.join(self.tmp, 'images', 'y.png'))

    def test_shared_root_keeps_cross_chapter_resources(self):
        shared = os.path.join(self.tmp, 'shared')
        path, reason = resolve_delivery_image(
            '../shared/y.png', os.path.join(self.tmp, 'ch1'), shared)
        self.assertIsNone(reason)
        self.assertEqual(path, os.path.join(shared, 'y.png'))


class CheckImageFileTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def test_png_gif_webp_svg(self):
        ok, kind, _ = check_image_file(self.write('a.png', PNG_HEAD))
        self.assertTrue(ok and kind == 'PNG')
        ok, kind, _ = check_image_file(
            self.write('a.gif', b'GIF89a' + b'0' * 16))
        self.assertTrue(ok and kind == 'GIF')
        ok, kind, _ = check_image_file(
            self.write('a.webp', b'RIFF' + b'0' * 4 + b'WEBP'))
        self.assertTrue(ok and kind == 'WEBP')
        ok, kind, _ = check_image_file(
            self.write('a.svg', b'<svg xmlns="http-nothing"></svg>'))
        self.assertTrue(ok and kind == 'SVG')

    def test_empty_html_disguise_and_unknown_rejected(self):
        ok, _, reason = check_image_file(self.write('empty.png', b''))
        self.assertFalse(ok and '空' in reason)
        ok, _, reason = check_image_file(
            self.write('fake.png', b'<html><body>404</body></html>'))
        self.assertFalse(ok and '伪装' not in reason)

    def test_pseudo_network_text_in_comments_and_data_attrs_pass(self):
        # 设计 7.2 / S1：注释与 data-*/说明属性中的 http 文本不是资源引用；
        # 网络依赖只按语义引用位置（href/src/@import/url(...)）判定
        svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
               b'data-source="https://example.com/spec">'
               b'<desc>see https://example.com/spec</desc>'
               b'<!-- https://cdn.example/x.png --><rect/></svg>')
        ok, kind, reason = check_image_file(self.write('a.svg', svg))
        self.assertTrue(ok, reason)
        self.assertEqual(kind, 'SVG')

    def test_svg_with_external_dependency_rejected(self):
        ok, _, reason = check_image_file(self.write(
            'a.svg', b'<svg><image href="https://cdn.example/x.png"/></svg>'))
        self.assertFalse(ok and '外部网络依赖' in reason)

    def test_invalid_xml_svg_rejected(self):
        ok, _, reason = check_image_file(
            self.write('a.svg', b'<svg this is not valid xml'))
        self.assertFalse(ok)
        self.assertIn('不是有效的 XML', reason)

    def test_non_svg_document_rejected(self):
        ok, _, reason = check_image_file(self.write(
            'a.svg', b'<?xml version="1.0"?><html><body>err</body></html>'))
        self.assertFalse(ok and '非 SVG 文档' in reason)
        # HTML 错误页内嵌 svg 片段不是 SVG 文档
        ok, _, reason = check_image_file(self.write(
            'b.svg', b'<html><body><svg><rect/></svg></body></html>'))
        self.assertFalse(ok)

    def test_svg_missing_local_dependency_rejected(self):
        ok, _, reason = check_image_file(self.write(
            'a.svg', b'<svg xmlns="http://www.w3.org/2000/svg">'
                     b'<image href="missing_local.png"/></svg>'))
        self.assertFalse(ok and '本地依赖缺失' in reason)

    def test_svg_with_existing_local_dependency_passes(self):
        self.write('dep.png', PNG_HEAD)
        ok, kind, _ = check_image_file(self.write(
            'a.svg', b'<svg xmlns="http://www.w3.org/2000/svg">'
                     b'<image href="dep.png"/></svg>'))
        self.assertTrue(ok and kind == 'SVG')

    def test_svg_single_quoted_namespace_and_prolog_pass(self):
        ok, kind, _ = check_image_file(self.write(
            'a.svg', b"<?xml version='1.0'?>"
                     b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"))
        self.assertTrue(ok and kind == 'SVG')

    def test_comment_leading_svg_still_validated(self):
        # 前导注释的 SVG 不能借 file 兜底绕过依赖校验
        ok, _, reason = check_image_file(self.write(
            'a.svg', b'<!-- drawing -->'
                     b'<svg xmlns="http://www.w3.org/2000/svg">'
                     b'<image href="https://cdn.example/x.png"/></svg>'))
        self.assertFalse(ok and '外部' in reason)
        ok, kind, _ = check_image_file(self.write(
            'b.svg', b'<!-- drawing --><svg xmlns="http://www.w3.org/2000/svg">'
                     b'<rect/></svg>'))
        self.assertTrue(ok and kind == 'SVG')


class SvgDependencyTest(unittest.TestCase):
    """SVG 实际资源依赖核验：CSS url、嵌套依赖、交付根与循环（评审 P2-3）。"""

    SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def test_missing_css_url_dependency_rejected(self):
        ok, _, reason = check_image_file(self.write(
            'a.svg', '<svg %s><style>rect{fill: url(missing.svg#paint)}'
                     '</style><rect/></svg>' % self.SVG_NS))
        self.assertFalse(ok)
        self.assertIn('本地依赖缺失', reason)
        self.assertIn('missing.svg', reason)
    def test_css_url_in_style_attribute_passes(self):
        self.write('paint.svg', '<svg %s><rect/></svg>' % self.SVG_NS)
        ok, kind, _ = check_image_file(self.write(
            'a.svg', '<svg %s><rect style="fill: url(paint.svg#paint)"/>'
                     '</svg>' % self.SVG_NS))
        self.assertTrue(ok and kind == 'SVG')

    def test_fragment_and_data_url_pass(self):
        ok, kind, _ = check_image_file(self.write(
            'a.svg', '<svg %s><rect fill="url(#grad)"/>'
                     '<image href="data:image/png;base64,AAAA"/></svg>'
                     % self.SVG_NS))
        self.assertTrue(ok and kind == 'SVG')

    def test_nested_missing_dependency_rejected(self):
        self.write('child.svg', '<svg %s><image href="missing.png"/></svg>'
                   % self.SVG_NS)
        ok, _, reason = check_image_file(self.write(
            'parent.svg', '<svg %s><image href="child.svg"/></svg>'
            % self.SVG_NS))
        self.assertFalse(ok)
        self.assertIn('嵌套依赖', reason)
        self.assertIn('本地依赖缺失', reason)

    def test_nested_existing_dependency_passes(self):
        make_png(os.path.join(self.tmp, 'images', 'deep.png'))
        self.write('sub/child.svg', '<svg %s><image href="../images/deep.png"/>'
                   '</svg>' % self.SVG_NS)
        ok, _, _ = check_image_file(self.write(
            'parent.svg', '<svg %s><image href="sub/child.svg"/></svg>'
            % self.SVG_NS))
        self.assertTrue(ok)

    def test_dependency_outside_delivery_root_rejected(self):
        # 交付根默认为 SVG 所在目录：现存但越出交付根的依赖失败
        os.makedirs(os.path.join(self.tmp, 'outside'))
        make_png(os.path.join(self.tmp, 'outside', 'nearby.png'))
        ok, _, reason = check_image_file(self.write(
            os.path.join('delivery', 'a.svg'),
            '<svg %s><image href="../outside/nearby.png"/></svg>'
            % self.SVG_NS))
        self.assertFalse(ok)
        self.assertIn('越出交付根', reason)

    def test_shared_delivery_root_keeps_cross_dir_resource(self):
        # 显式交付根覆盖跨章共享资源：同一引用按共同交付根通过
        os.makedirs(os.path.join(self.tmp, 'shared'))
        make_png(os.path.join(self.tmp, 'shared', 'nearby.png'))
        ok, _, _ = check_image_file(
            self.write(os.path.join('delivery', 'a.svg'),
                       '<svg %s><image href="../shared/nearby.png"/></svg>'
                       % self.SVG_NS),
            delivery_root=self.tmp)
        self.assertTrue(ok)

    def test_cycle_is_handled_without_infinite_recursion(self):
        self.write('a.svg', '<svg %s><image href="b.svg"/></svg>' % self.SVG_NS)
        self.write('b.svg', '<svg %s><image href="a.svg"/></svg>' % self.SVG_NS)
        ok, kind, _ = check_image_file(os.path.join(self.tmp, 'a.svg'))
        self.assertTrue(ok and kind == 'SVG')
        # 循环引用中存在缺失依赖仍按实际有效性失败
        self.write('c.svg', '<svg %s><image href="d.svg"/></svg>' % self.SVG_NS)
        self.write('d.svg', '<svg %s><image href="c.svg"/>'
                            '<image href="gone.png"/></svg>' % self.SVG_NS)
        ok, _, reason = check_image_file(os.path.join(self.tmp, 'c.svg'))
        self.assertFalse(ok)
        self.assertIn('gone.png', reason)

    def test_delivery_tree_relocation_still_passes(self):
        make_png(os.path.join(self.tmp, 'first', 'dep.png'))
        self.write(os.path.join('first', 'a.svg'),
                   '<svg %s><image href="dep.png"/></svg>' % self.SVG_NS)
        second = os.path.join(self.tmp, 'second')
        os.rename(os.path.join(self.tmp, 'first'), second)
        ok, kind, _ = check_image_file(
            os.path.join(second, 'a.svg'), delivery_root=second)
        self.assertTrue(ok and kind == 'SVG')

    def test_presentation_attribute_missing_dependency_rejected(self):
        # 评审 P2：展示属性中的 url(...) 是真实资源引用
        for attr in ('fill', 'stroke', 'filter', 'clip-path', 'mask',
                     'marker', 'marker-start', 'marker-end'):
            ok, _, reason = check_image_file(self.write(
                'a.svg', '<svg %s><rect %s="url(missing.svg#p)"/></svg>'
                % (self.SVG_NS, attr)))
            self.assertFalse(ok, attr)
            self.assertIn('本地依赖缺失', reason, attr)

    def test_presentation_attribute_existing_dependency_passes(self):
        self.write('paint.svg', '<svg %s><rect/></svg>' % self.SVG_NS)
        ok, kind, _ = check_image_file(self.write(
            'a.svg', '<svg %s><rect fill="url(paint.svg#p)" '
                     'stroke="url(paint.svg#p)" filter="url(#f)" '
                     'mask="url(paint.svg#p)"/></svg>' % self.SVG_NS))
        self.assertTrue(ok and kind == 'SVG')

    def test_css_import_missing_rejected(self):
        # 评审 P2：@import 的字符串与 url(...) 形式均被识别
        for stmt in ('@import "missing.css";', "@import 'missing.css';",
                     '@import url(missing.css);',
                     '@import url("missing.css") screen;'):
            ok, _, reason = check_image_file(self.write(
                'a.svg', '<svg %s><style>%s</style><rect/></svg>'
                % (self.SVG_NS, stmt)))
            self.assertFalse(ok, stmt)
            self.assertIn('本地依赖缺失', reason, stmt)
            self.assertIn('missing.css', reason, stmt)

    def test_imported_css_missing_resource_rejected(self):
        # 被导入样式表中的后续资源必须核验，不能只确认样式表存在
        self.write('theme.css', '.r { fill: url(gone.png); }')
        ok, _, reason = check_image_file(self.write(
            'a.svg', '<svg %s><style>@import "theme.css";</style></svg>'
            % self.SVG_NS))
        self.assertFalse(ok)
        self.assertIn('嵌套依赖', reason)
        self.assertIn('gone.png', reason)

    def test_imported_css_chain_missing_rejected(self):
        self.write('outer.css', '@import url(inner.css);')
        self.write('inner.css', '.x { fill: url(also-gone.png); }')
        ok, _, reason = check_image_file(self.write(
            'a.svg', '<svg %s><style>@import url("outer.css")</style></svg>'
            % self.SVG_NS))
        self.assertFalse(ok)
        self.assertIn('also-gone.png', reason)

    def test_css_and_xml_comments_not_dependencies(self):
        # 注释与普通文本不产生依赖
        ok, kind, _ = check_image_file(self.write(
            'a.svg', '<svg %s><!-- url(missing.png) --><desc>not a url() '
                     'dependency</desc><style>/* url(missing.png) */ '
                     'rect { fill: red }</style><rect/></svg>' % self.SVG_NS))
        self.assertTrue(ok and kind == 'SVG')

    def test_pseudo_urls_in_strings_and_data_attrs_pass(self):
        # 设计 7.1 / S1：CSS 字符串与 SVG data-* 属性中的 url 文本不是资源依赖
        svg = ('<svg %s data-example="url(example.png)" '
               'aria-label="see url(elsewhere.png)">'
               '<style>.a { content: "url(example.png)"; }</style>'
               '<desc>url(example.png) as plain text</desc>'
               '<rect fill="url(#local)"/></svg>' % self.SVG_NS)
        ok, kind, reason = check_image_file(self.write('a.svg', svg))
        self.assertTrue(ok, reason)
        self.assertEqual(kind, 'SVG')

    def test_css_url_quote_whitespace_escape_forms(self):
        # S1：真实引用的合法单双引号、空白与反斜杠转义写法都指向同一文件
        self.write('paint.svg', '<svg %s><rect/></svg>' % self.SVG_NS)
        for attr in ('fill="url(paint.svg#p)"',
                     "fill=\"url('paint.svg#p')\"",
                     'fill="url(&quot;paint.svg#p&quot;)"',
                     'fill="url( paint.svg#p )"',
                     'fill="url(pa\\69 nt.svg#p)"'):
            ok, _, reason = check_image_file(self.write(
                'a.svg', '<svg %s><rect %s/></svg>' % (self.SVG_NS, attr)))
            self.assertTrue(ok, '%s: %s' % (attr, reason))

    def test_css_string_import_is_not_reference(self):
        # @import 只在真实 at-rule 语境生效；字符串内的 @import 文本不是导入
        ok, kind, _ = check_image_file(self.write(
            'a.svg', '<svg %s><style>.a { content: "@import missing.css"; }'
                     '</style><rect/></svg>' % self.SVG_NS))
        self.assertTrue(ok and kind == 'SVG')


class SvgIdentityTest(unittest.TestCase):
    """SVG 依赖内容纳入来源身份：子资源换图无法绕过（评审 P1）。"""

    NS = 'xmlns="http://www.w3.org/2000/svg"'
    PARENT = ('<svg %s><image href="child.svg"/></svg>' % NS)
    RED = '<svg %s><rect fill="red"/></svg>' % NS
    BLUE = '<svg %s><rect fill="blue"/></svg>' % NS

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def build(self, base, child):
        """搭建 parent.svg → child.svg 树，返回 parent 路径。"""
        os.makedirs(os.path.join(base, 'images'), exist_ok=True)
        parent = os.path.join(base, 'images', 'parent.svg')
        with open(parent, 'w', encoding='utf-8') as f:
            f.write(self.PARENT)
        with open(os.path.join(base, 'images', 'child.svg'), 'w',
                  encoding='utf-8') as f:
            f.write(child)
        return parent

    def test_same_tree_same_identity(self):
        a = self.build(os.path.join(self.tmp, 'a'), self.RED)
        b = self.build(os.path.join(self.tmp, 'b'), self.RED)
        self.assertEqual(resource_identity_digest(a),
                         resource_identity_digest(b))

    def test_top_level_rename_keeps_identity(self):
        # S3：合法顶层改名（同内容）身份不变
        a = self.build(os.path.join(self.tmp, 'tree'), self.RED)
        renamed = os.path.join(os.path.dirname(a), 'renamed.svg')
        os.rename(a, renamed)
        b = self.build(os.path.join(self.tmp, 'other'), self.RED)
        self.assertEqual(resource_identity_digest(renamed),
                         resource_identity_digest(b))

    def test_swapped_child_changes_identity(self):
        # 顶层 SVG 逐字节相同，仅子资源内容不同：身份必须不同
        a = self.build(os.path.join(self.tmp, 'a'), self.RED)
        b = self.build(os.path.join(self.tmp, 'b'), self.BLUE)
        self.assertNotEqual(resource_identity_digest(a),
                            resource_identity_digest(b))

    def test_multilevel_dependency_in_identity(self):
        os.makedirs(os.path.join(self.tmp, 'a', 'images'))
        os.makedirs(os.path.join(self.tmp, 'b', 'images'))
        child_a = os.path.join(self.tmp, 'a', 'images', 'child.svg')
        child_b = os.path.join(self.tmp, 'b', 'images', 'child.svg')
        grand = ('<svg %s><image href="grand.svg"/></svg>' % self.NS)
        for path, fill in ((child_a, 'red'), (child_b, 'red')):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(grand)
            with open(os.path.join(os.path.dirname(path), 'grand.svg'), 'w',
                      encoding='utf-8') as f:
                f.write('<svg %s><rect fill="%s"/></svg>' % (self.NS, fill))
        parent = '<svg %s><image href="child.svg"/></svg>' % self.NS
        pa = os.path.join(self.tmp, 'a', 'images', 'parent.svg')
        pb = os.path.join(self.tmp, 'b', 'images', 'parent.svg')
        for path in (pa, pb):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(parent)
        self.assertEqual(resource_identity_digest(pa),
                         resource_identity_digest(pb))
        # 仅改多层之下的 grand 内容，顶层身份随之变化
        with open(os.path.join(self.tmp, 'b', 'images', 'grand.svg'), 'w',
                  encoding='utf-8') as f:
            f.write('<svg %s><rect fill="gold"/></svg>' % self.NS)
        self.assertNotEqual(resource_identity_digest(pa),
                            resource_identity_digest(pb))

    def test_bitmap_and_self_contained_identity_unchanged(self):
        png = os.path.join(self.tmp, 'a.png')
        make_png(png)
        self.assertEqual(resource_identity_digest(png), file_sha256(png))
        svg = os.path.join(self.tmp, 'plain.svg')
        with open(svg, 'wb') as f:
            f.write(self.RED.encode())
        self.assertEqual(resource_identity_digest(svg),
                         hashlib.sha256(self.RED.encode()).hexdigest())

    def test_cycle_stable_and_location_independent(self):
        def build_cycle(base, second_fill):
            os.makedirs(os.path.join(base, 'images'))
            with open(os.path.join(base, 'images', 'a.svg'), 'w',
                      encoding='utf-8') as f:
                f.write('<svg %s><image href="b.svg"/></svg>' % self.NS)
            with open(os.path.join(base, 'images', 'b.svg'), 'w',
                      encoding='utf-8') as f:
                f.write('<svg %s><image href="a.svg"/>'
                        '<rect fill="%s"/></svg>' % (self.NS, second_fill))
            return os.path.join(base, 'images', 'a.svg')

        one = build_cycle(os.path.join(self.tmp, 'one'), 'red')
        two = build_cycle(os.path.join(self.tmp, 'two'), 'red')
        self.assertEqual(resource_identity_digest(one),
                         resource_identity_digest(two))
        three = build_cycle(os.path.join(self.tmp, 'three'), 'gold')
        self.assertNotEqual(resource_identity_digest(one),
                            resource_identity_digest(three))

    def test_missing_dependency_identity_is_none(self):
        os.makedirs(os.path.join(self.tmp, 'images'))
        parent = os.path.join(self.tmp, 'images', 'parent.svg')
        with open(parent, 'w', encoding='utf-8') as f:
            f.write(self.PARENT)
        self.assertIsNone(resource_identity_digest(parent))

    def test_unreadable_dependency_identity_is_none(self):
        parent = self.build(os.path.join(self.tmp, 'tree'), self.RED)
        child = os.path.join(os.path.dirname(parent), 'child.svg')
        os.chmod(child, 0)
        try:
            self.assertIsNone(resource_identity_digest(parent))
        finally:
            os.chmod(child, 0o644)

    def test_css_dependency_content_in_identity(self):
        def build(base, css_fill):
            os.makedirs(os.path.join(base, 'images'))
            with open(os.path.join(base, 'images', 'a.svg'), 'w',
                      encoding='utf-8') as f:
                f.write('<svg %s><style>@import "theme.css";</style>'
                        '<rect fill="url(paint.svg#p)"/></svg>' % self.NS)
            with open(os.path.join(base, 'images', 'theme.css'), 'w',
                      encoding='utf-8') as f:
                f.write('.r { fill: %s; }' % css_fill)
            with open(os.path.join(base, 'images', 'paint.svg'), 'w',
                      encoding='utf-8') as f:
                f.write('<svg %s><rect/></svg>' % self.NS)
            return os.path.join(base, 'images', 'a.svg')

        a = build(os.path.join(self.tmp, 'a'), 'red')
        b = build(os.path.join(self.tmp, 'b'), 'blue')
        self.assertNotEqual(resource_identity_digest(a),
                            resource_identity_digest(b))

    def test_occurrence_fails_catch_delivery_subresource_swap(self):
        src_parent = self.build(os.path.join(self.tmp, 'src'), self.RED)
        delivery = os.path.join(self.tmp, 'delivery')
        self.build(delivery, self.RED)
        expected = [resource_identity_digest(src_parent)]
        text = '![p](images/parent.svg)\n'
        self.assertEqual(
            image_occurrence_fails(text, delivery,
                                   expected_digests=expected), [])
        self.build(delivery, self.BLUE)
        fails = image_occurrence_fails(text, delivery,
                                       expected_digests=expected)
        self.assertTrue(any('来源身份不符' in f for f in fails))

    def test_explicit_map_catches_delivery_subresource_swap(self):
        # S3：由源树独立建立的显式映射同样拒绝译侧子资源换图
        src_parent = self.build(os.path.join(self.tmp, 'map_src'), self.RED)
        delivery = os.path.join(self.tmp, 'map_delivery')
        self.build(delivery, self.RED)
        expected = [resource_identity_digest(src_parent)]
        text = '![p](images/parent.svg)\n'
        self.assertEqual(
            image_occurrence_fails(text, delivery,
                                   expected_digests=expected), [])
        self.build(delivery, self.BLUE)
        fails = image_occurrence_fails(text, delivery,
                                       expected_digests=expected)
        self.assertTrue(any('来源身份不符' in f for f in fails))

    def test_local_resource_digest_is_dependency_aware(self):
        parent = self.build(os.path.join(self.tmp, 'tree'), self.RED)
        base = os.path.join(self.tmp, 'tree')
        self.assertEqual(local_resource_digest('images/parent.svg', base),
                         resource_identity_digest(parent))
        self.assertEqual(local_resource_digest('images/parent.svg', base),
                         local_resource_digest('images/parent.svg', base))


class ImageOccurrenceFailsTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        make_png(os.path.join(self.tmp, 'images', 'a.png'))
        with open(os.path.join(self.tmp, 'images', 'b.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'9' * 32)

    def test_ok_and_digest_identity(self):
        text = '![a](images/a.png)\n![b](images/b.png)\n'
        self.assertEqual(
            image_occurrence_fails(text, self.tmp), [])
        from _verification import file_sha256
        digests = [
            file_sha256(os.path.join(self.tmp, 'images', 'a.png')),
            file_sha256(os.path.join(self.tmp, 'images', 'b.png')),
        ]
        self.assertEqual(
            image_occurrence_fails(text, self.tmp,
                                   expected_digests=digests), [])
        # 同名换图：b.png 位置放了 a.png 内容 → 身份不符
        wrong = [digests[1], digests[0]]
        self.assertTrue(image_occurrence_fails(
            text, self.tmp, expected_digests=wrong))

    def test_missing_and_count_mismatch(self):
        self.assertTrue(image_occurrence_fails(
            '![x](images/none.png)\n', self.tmp))
        self.assertTrue(image_occurrence_fails(
            '![a](images/a.png)\n', self.tmp, expected_digests=['x', 'y']))


class SvgProcessingInstructionTest(unittest.TestCase):
    """xml-stylesheet 处理指令：尚未支持的结构明确报告未验证并阻断（评审 P1）。

    合法的 XML 声明、注释与转义文本中形似处理指令的内容不得误拦截；
    已支持的 style/展示属性/@import 路径不受影响。
    """

    NS = 'xmlns="http://www.w3.org/2000/svg"'
    PI_SVG = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<?xml-stylesheet type="text/css" href="paint.css"?>\n'
              '<svg %s><rect width="10" height="10"/></svg>' % NS)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def test_pi_svg_rejected_regardless_of_target_css_state(self):
        # 反例：源译顶层 SVG 相同，目标 CSS 不同/缺失/被替换，旧行为 ALL PASS
        svg_path = self.write('fig.svg', self.PI_SVG)
        self.write('paint.css', 'rect { fill: red; }\n')
        ok, _, reason = check_image_file(svg_path)
        self.assertFalse(ok)
        self.assertIn('处理指令', reason)
        self.assertIn('xml-stylesheet', reason)
        self.assertIn('未验证', reason)
        self.assertIn('fig.svg', reason)  # 诊断含所属文件
        # 目标 CSS 缺失同样未验证（而不是当作零依赖通过）
        os.unlink(os.path.join(self.tmp, 'paint.css'))
        ok, _, reason = check_image_file(svg_path)
        self.assertFalse(ok)
        self.assertIn('未验证', reason)
        # 目标 CSS 被替换同样未验证
        self.write('paint.css', 'circle { stroke: green; }\n')
        ok, _, reason = check_image_file(svg_path)
        self.assertFalse(ok)
        self.assertIn('未验证', reason)

    def test_pi_svg_has_no_usable_identity(self):
        # 资源身份不能为含处理指令的 SVG 提供可用依据
        svg_path = self.write('fig.svg', self.PI_SVG)
        self.write('paint.css', 'rect { fill: red; }\n')
        self.assertIsNone(resource_identity_digest(svg_path))
        self.assertIsNone(local_resource_digest('fig.svg', self.tmp))

    def test_pi_svg_not_bypassed_by_explicit_map(self):
        # 显式映射提供旧字节摘要也不能让未验证结构通过
        svg_path = self.write('fig.svg', self.PI_SVG)
        self.write('paint.css', 'rect { fill: red; }\n')
        byte_digest = file_sha256(svg_path)
        fails = image_occurrence_fails(
            '![图](fig.svg)\n', self.tmp, expected_digests=[byte_digest])
        self.assertTrue(any('未验证' in f or '无法核验' in f for f in fails),
                        fails)

    def test_declaration_comment_and_escaped_text_not_flagged(self):
        # 普通 XML 声明、注释中形似 PI 的内容、转义文本均不误拦截
        legal = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<!-- <?xml-stylesheet href="fake.css"?> 说明 -->\n'
                 '<svg %s><desc>literal &lt;?xml-stylesheet?&gt; '
                 'text</desc><rect/></svg>' % self.NS)
        ok, kind, reason = check_image_file(self.write('legal.svg', legal))
        self.assertTrue(ok, reason)
        self.assertEqual(kind, 'SVG')

    def test_pi_svg_in_nested_dependency_rejected(self):
        # 处理指令出现在被引用 SVG 中同样阻断
        self.write('sub/child.svg', self.PI_SVG)
        self.write('sub/paint.css', 'rect { fill: red; }\n')
        ok, _, reason = check_image_file(self.write(
            'parent.svg', '<svg %s><image href="sub/child.svg"/></svg>'
            % self.NS))
        self.assertFalse(ok)
        self.assertIn('未验证', reason)

    def test_supported_style_constructs_still_work(self):
        # 已支持的 <style>、style 属性、展示属性与 @import 继续正常
        self.write('dep.svg', '<svg %s><rect/></svg>' % self.NS)
        self.write('theme.css', '.a { fill: url(dep.svg#p); }\n')
        svg = ('<svg %s><style>@import url(theme.css);</style>'
               '<rect fill="url(dep.svg#p)" style="stroke: url(dep.svg#p)"/>'
               '</svg>' % self.NS)
        ok, kind, reason = check_image_file(self.write('ok.svg', svg))
        self.assertTrue(ok, reason)
        self.assertEqual(kind, 'SVG')


class CssParseErrorTest(unittest.TestCase):
    """CSS 组件值与导入参数的解析错误进入 _PARSE_ERROR 路径（评审 P2）。"""

    NS = 'xmlns="http://www.w3.org/2000/svg"'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def check(self, inner):
        return check_image_file(self.write(
            'a.svg', '<svg %s>%s</svg>' % (self.NS, inner)))

    def test_bad_url_rejected_in_all_contexts(self):
        # 反例：url(foo bar) 产生 bad-url 错误 token，旧行为静默放行
        cases = [
            '<rect fill="url(foo bar)"/>',                    # 展示属性
            '<rect style="fill: url(foo bar)"/>',             # style 声明
            '<style>rect { fill: url(foo bar); }</style>',    # <style> 规则
            '<style>@import url(foo bar);</style>',           # @import 参数
            '<style>.a { content: "未终止字符串</style>',      # eof-in-string
        ]
        for inner in cases:
            ok, _, reason = self.check(inner)
            self.assertFalse(ok, inner)
            self.assertIn('无法解析', reason, inner)
            self.assertIn('a.svg', reason, inner)  # 诊断含所属文件

    def test_parse_error_distinguished_from_missing_file(self):
        # CSS 解析错误与真实文件缺失分别报告，核对具体原因
        ok, _, reason = self.check('<rect fill="url(foo bar)"/>')
        self.assertFalse(ok)
        self.assertIn('无法解析', reason)
        self.assertNotIn('本地依赖缺失', reason)
        ok, _, reason = self.check('<rect fill="url(gone.svg#p)"/>')
        self.assertFalse(ok)
        self.assertIn('本地依赖缺失', reason)
        self.assertNotIn('无法解析', reason)

    def test_nested_component_parse_error_not_swallowed(self):
        # 嵌套函数/块中的解析错误不能被递归扫描吞掉
        ok, _, reason = self.check('<rect clip-path="inset(url(foo bar))"/>')
        self.assertFalse(ok)
        self.assertIn('无法解析', reason)
        ok, _, reason = self.check(
            '<style>.a { background: linear-gradient(url(foo bar)); }</style>')
        self.assertFalse(ok)
        self.assertIn('无法解析', reason)

    def test_parse_error_has_no_identity(self):
        svg_path = self.write('bad.svg', '<svg %s><rect fill="url(foo bar)"/>'
                             '</svg>' % self.NS)
        self.assertIsNone(resource_identity_digest(svg_path))
        self.assertIsNone(local_resource_digest('bad.svg', self.tmp))

    def test_import_trailing_parse_error_rejected_and_legal_passes(self):
        # 复审 P2：@import 找到目标后，剩余参数及嵌套节点中的
        # 解析错误同样拒绝；合法媒体/supports 条件仍通过
        self.write('ok.css', 'rect { fill: red; }\n')
        bad_stmts = (
            '@import "ok.css" url(foo bar);',
            '@import "ok.css" supports(background: url(foo bar));',
            '@import url("ok.css") url(foo bar);',
            "@import url(ok.css) supports(background: url(foo bar));",
            '@import "ok.css" '
            'supports(background: linear-gradient(url(foo bar)));',
        )
        for stmt in bad_stmts:
            ok, _, reason = self.check(
                '<svg %s><style>%s</style><rect/></svg>' % (self.NS, stmt))
            self.assertFalse(ok, stmt)
            self.assertIn('无法解析', reason, stmt)
            self.assertIn('a.svg', reason, stmt)  # 诊断含所属文件
            self.assertNotIn('本地依赖缺失', reason, stmt)  # 不误报缺失
        legal_stmts = (
            '@import "ok.css";',
            "@import 'ok.css' screen;",
            '@import url(ok.css) screen and (min-width: 100px);',
            '@import url("ok.css") supports(display: grid);',
            # 参数中的普通字符串与注释不产生虚假解析错误或资源依赖
            '@import "ok.css" /* url(fake.png) */ "stray text" screen;',
        )
        for stmt in legal_stmts:
            ok, kind, reason = self.check(
                '<svg %s><style>%s</style><rect/></svg>' % (self.NS, stmt))
            self.assertTrue(ok, '%s: %s' % (stmt, reason))
            self.assertEqual(kind, 'SVG', stmt)

    def test_import_trailing_error_identity_and_tree_stability(self):
        # 身份：错误参数返回不可核验；相同导入资源树身份稳定，
        # 被导入样式表换内容即身份变化（导入只计一次，子资源可核对）
        self.write('ok.css', 'rect { fill: red; }\n')
        bad = self.write('bad.svg', '<svg %s><style>@import "ok.css" '
                         'url(foo bar);</style><rect/></svg>' % self.NS)
        self.assertIsNone(resource_identity_digest(bad))

        def build(base, css_text):
            os.makedirs(os.path.join(base, 'images'), exist_ok=True)
            svg = os.path.join(base, 'images', 'fig.svg')
            with open(svg, 'w', encoding='utf-8') as f:
                f.write('<svg %s><style>@import "theme.css";</style>'
                        '<rect/></svg>' % self.NS)
            with open(os.path.join(base, 'images', 'theme.css'), 'w',
                      encoding='utf-8') as f:
                f.write(css_text)
            return svg

        a = build(os.path.join(self.tmp, 'tree-a'), 'rect { fill: red; }\n')
        same = build(os.path.join(self.tmp, 'tree-b'),
                     'rect { fill: red; }\n')
        changed = build(os.path.join(self.tmp, 'tree-c'),
                        'rect { fill: blue; }\n')
        self.assertEqual(resource_identity_digest(a),
                         resource_identity_digest(same))
        self.assertNotEqual(resource_identity_digest(a),
                            resource_identity_digest(changed))

    def test_legal_url_forms_and_pseudo_text_still_pass(self):
        # 合法单双引号、空白、转义写法通过；字符串/注释/data-* 中的
        # url(...) 文本不产生依赖；普通节点不误判为错误
        self.write('paint.svg', '<svg %s><rect/></svg>' % self.NS)
        legal = ('<svg %s data-note="url(fake.png)" '
                 'aria-label="url(fake.png)">'
                 '<!-- url(fake.png) -->'
                 '<style>/* url(fake.png) */ .a { content: "url(fake.png)"; '
                 'fill: url( \'paint.svg#p\' ); } '
                 '@import url("paint.svg");</style>'
                 '<rect fill="url( paint.svg#p )" style="stroke: url(paint.svg)"/>'
                 '</svg>' % self.NS)
        ok, kind, reason = self.check(legal)
        self.assertTrue(ok, reason)
        self.assertEqual(kind, 'SVG')


class VerifyCliSvgGateTest(unittest.TestCase):
    """真实校验 CLI 成对验收：错误输入拒绝、合法相邻输入通过（评审 P1/P2）。"""

    SCRIPT = Path(__file__).resolve().parents[1] / \
        'skills/tech-doc-translator/scripts/verify_translation.py'
    NS = 'xmlns="http://www.w3.org/2000/svg"'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run(self, doc, src):
        import subprocess
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), doc, src],
            capture_output=True, text=True)

    def _pair(self, svg_text, extra_files=None):
        """源译各放一份相同 SVG 与配套文件，返回 (doc_md, src_md)。"""
        self.tmp = tempfile.mkdtemp()  # 每次调用独立目录，避免同测试两次搭建冲突
        for side in ('src', 'doc'):
            base = os.path.join(self.tmp, side)
            os.makedirs(base)
            with open(os.path.join(base, 'fig.svg'), 'w',
                      encoding='utf-8') as f:
                f.write(svg_text)
            for name, content in (extra_files or {}).items():
                with open(os.path.join(base, name), 'w',
                          encoding='utf-8') as f:
                    f.write(content)
            md = os.path.join(base, 'main.md')
            with open(md, 'w', encoding='utf-8') as f:
                f.write('# 测试\n\n![图](fig.svg)\n')
        return (os.path.join(self.tmp, 'doc', 'main.md'),
                os.path.join(self.tmp, 'src', 'main.md'))

    def test_pi_svg_blocked_cli_and_legal_neighbor_passes(self):
        pi_svg = ('<?xml version="1.0"?>\n'
                  '<?xml-stylesheet type="text/css" href="paint.css"?>\n'
                  '<svg %s><rect width="10" height="10"/></svg>' % self.NS)
        doc, src = self._pair(pi_svg, {'paint.css': 'rect{fill:red}\n'})
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('未验证', result.stdout)
        self.assertNotIn('ALL PASS', result.stdout)
        # 合法相邻输入：去掉处理指令后同一文档通过
        legal_svg = ('<?xml version="1.0"?>\n'
                     '<svg %s><rect width="10" height="10"/></svg>' % self.NS)
        doc, src = self._pair(legal_svg)
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('ALL PASS', result.stdout)

    def test_bad_url_blocked_cli_and_legal_neighbor_passes(self):
        bad_svg = ('<svg %s><rect width="10" height="10" fill="url(foo bar)"/>'
                   '</svg>' % self.NS)
        doc, src = self._pair(bad_svg)
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('无法解析', result.stdout)
        self.assertNotIn('ALL PASS', result.stdout)
        # 合法相邻输入：正确引用的 SVG 通过
        legal_svg = ('<svg %s><rect width="10" height="10" fill="red"/>'
                     '</svg>' % self.NS)
        doc, src = self._pair(legal_svg)
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('ALL PASS', result.stdout)

    def test_import_trailing_error_blocked_cli_and_legal_passes(self):
        # 复审 P2：@import 目标存在但参数尾部有解析错误，
        # 真实 CLI 非零退出且不误报文件缺失
        bad_svg = ('<svg %s><style>@import "paint.css" url(foo bar);</style>'
                   '<rect width="10" height="10"/></svg>' % self.NS)
        doc, src = self._pair(bad_svg, {'paint.css': 'rect{fill:red}\n'})
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('无法解析', result.stdout)
        self.assertIn('fig.svg', result.stdout)  # 诊断含所属文件
        self.assertNotIn('本地依赖缺失', result.stdout)
        self.assertNotIn('ALL PASS', result.stdout)
        # 合法相邻输入：同样导入加合法 supports 条件通过
        legal_svg = ('<svg %s><style>@import "paint.css" '
                     'supports(display: grid);</style>'
                     '<rect width="10" height="10"/></svg>' % self.NS)
        doc, src = self._pair(legal_svg, {'paint.css': 'rect{fill:red}\n'})
        result = self._run(doc, src)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('ALL PASS', result.stdout)


class RebuildImagesDisplayTest(unittest.TestCase):
    """通用回补 CLI 的成对正反例（A7–A10、A28 绑定部分）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def build_project(self, html, md_text, images=(('pic_a.png', 20, 10),)):
        tmp = self.tmp
        for name, w, h in images:
            self.make_png(os.path.join(tmp, 'source/images', name), w, h)
            self.make_png(os.path.join(tmp, 'delivery/images', name), w, h)
        os.makedirs(os.path.join(tmp, 'source'), exist_ok=True)
        open(os.path.join(tmp, 'source/page.html'), 'w',
             encoding='utf-8').write(html)
        os.makedirs(os.path.join(tmp, 'delivery'), exist_ok=True)
        open(os.path.join(tmp, 'delivery/final.md'), 'w',
             encoding='utf-8').write(md_text)
        manifest = {
            'version': 1, 'source_version': '13.4-test', 'family': 'single',
            'pages': [{'snapshot': 'source/page.html',
                       'markdown': 'delivery/final.md'}],
        }
        open(os.path.join(tmp, 'manifest.json'), 'w',
             encoding='utf-8').write(json.dumps(manifest, indent=2))
        return manifest

    def run_rebuild(self, output=None, extra=()):
        output = output or os.path.join(self.tmp,
                                        'delivery/export/images_display.json')
        return subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', os.path.join(self.tmp, 'manifest.json'),
             '--output', output, *extra],
            capture_output=True, text=True)

    def test_rebuild_derives_width_and_is_deterministic(self):
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<img src="images/pic_a.png" style="height:50px">'
            '<img src="images/pic_a.png" style="width:30px">'
            '</article></body></html>',
            '# 最终\n\n![1](images/pic_a.png)\n\n![2](images/pic_a.png)\n')
        out = os.path.join(self.tmp, 'delivery/export/images_display.json')
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.load(open(out, encoding='utf-8'))
        self.assertEqual(payload['entries'][0]['width']['value'], 100.0)
        self.assertEqual(payload['entries'][0]['width']['basis'],
                         'height-derived-width')
        self.assertEqual(payload['entries'][1]['width']['value'], 30.0)
        self.assertTrue(payload['entries'][0]['source']['resource_sha256'])
        self.assertTrue(payload['entries'][0]['source']['snapshot_sha256'])
        first = json.dumps(payload, sort_keys=True)
        os.remove(out)
        self.assertEqual(self.run_rebuild().returncode, 0)
        again = json.dumps(
            json.load(open(out, encoding='utf-8')), sort_keys=True)
        self.assertEqual(first, again)  # 同输入连续两次语义一致

    def test_wrong_reference_rejected_and_old_map_protected(self):
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<img src="images/pic_a.png" style="width:60px">'
            '<img src="images/pic_b.png" style="width:33px">'
            '</article></body></html>',
            '# 最终\n\n![A](images/pic_a.png)\n\n![B](images/pic_b.png)\n',
            images=(('pic_a.png', 20, 10), ('pic_b.png', 10, 30)))
        out = os.path.join(self.tmp, 'delivery/export/images_display.json')
        self.assertEqual(self.run_rebuild().returncode, 0)
        baseline = open(out, 'rb').read()
        md_path = os.path.join(self.tmp, 'delivery/final.md')
        text = open(md_path, encoding='utf-8').read()
        open(md_path, 'w', encoding='utf-8').write(
            text.replace('![B](images/pic_b.png)', '![B](images/pic_a.png)'))
        result = self.run_rebuild()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('身份不符', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)  # 旧映射不变

    def test_missing_image_count_rejected(self):
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<img src="images/pic_a.png" style="width:60px">'
            '<img src="images/pic_a.png" style="width:120px">'
            '</article></body></html>',
            '# 最终\n\n![1](images/pic_a.png)\n')
        result = self.run_rebuild()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('次不符', result.stderr)

    def test_code_image_literal_not_counted_in_rebuild(self):
        # 03-S3：行内代码内的图片字面量不是真实出现——不要求其目标文件
        # 存在、不计入出现序列；合法输入首次与重复回补语义稳定
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<p>Use <code>![example](fake.png)</code>.</p>'
            '<img src="images/pic_a.png" style="width:60px">'
            '</article></body></html>',
            '# 最终\n\nUse `![example](fake.png)`.\n\n'
            '![1](images/pic_a.png)\n')
        out = os.path.join(self.tmp, 'delivery/export/images_display.json')
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.load(open(out, encoding='utf-8'))
        self.assertEqual(len(payload['entries']), 1)
        first = json.dumps(payload, sort_keys=True)
        os.remove(out)
        self.assertEqual(self.run_rebuild().returncode, 0)
        self.assertEqual(first, json.dumps(
            json.load(open(out, encoding='utf-8')), sort_keys=True))

    def test_undetermined_occurrence_kept_with_reason_code(self):
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<img src="images/pic_a.png" style="width:60px">'
            '<img src="images/pic_a.png">'
            '</article></body></html>',
            '# 最终\n\n![1](images/pic_a.png)\n\n![2](images/pic_a.png)\n')
        out = os.path.join(self.tmp, 'delivery/export/images_display.json')
        self.assertEqual(self.run_rebuild().returncode, 0)
        payload = json.load(open(out, encoding='utf-8'))
        self.assertEqual(len(payload['entries']), 1)
        self.assertEqual(len(payload['undetermined']), 1)
        self.assertEqual(payload['undetermined'][0]['occurrence'], 2)
        self.assertEqual(payload['undetermined'][0]['reason_code'],
                         'no-source-constraint')

    def test_unknown_ratio_reports_unresolved_size(self):
        self.build_project(
            '<html><body><article><h1>T</h1>'
            '<img src="images/pic_a.png" style="height:50px">'
            '</article></body></html>',
            '# 最终\n\n![1](images/pic_a.png)\n')
        # 源与交付都换成无法判型的资源：比例未知 → unresolved-size
        garbage = b'\x89PNG\r\n\x1a\ngarbage'
        open(os.path.join(self.tmp, 'source/images/pic_a.png'),
             'wb').write(garbage)
        open(os.path.join(self.tmp, 'delivery/images/pic_a.png'),
             'wb').write(garbage)
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 0)  # 未确定不算回补失败
        out = os.path.join(self.tmp, 'delivery/export/images_display.json')
        payload = json.load(open(out, encoding='utf-8'))
        self.assertEqual(len(payload['entries']), 0)
        self.assertEqual(payload['undetermined'][0]['reason_code'],
                         'unresolved-size')

    def test_manifest_without_version_rejected(self):
        self.build_project(
            '<html><body><article><h1>T</h1></article></body></html>',
            '# 无图交付\n')
        manifest_path = os.path.join(self.tmp, 'manifest.json')
        manifest = json.load(open(manifest_path, encoding='utf-8'))
        del manifest['source_version']
        open(manifest_path, 'w', encoding='utf-8').write(json.dumps(manifest))
        result = self.run_rebuild()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source_version', result.stderr)

    def test_fetch_missing_with_local_service_and_redirect_refusal(self):
        import http.server
        import threading

        page = (b'<html><body><article><h1>T</h1>'
                b'<p>no images</p></article></body></html>')

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(inner_self):
                if inner_self.path == '/page.html':
                    inner_self.send_response(200)
                    inner_self.end_headers()
                    inner_self.wfile.write(page)
                elif inner_self.path == '/redirect':
                    inner_self.send_response(302)
                    inner_self.send_header('Location', '/page.html')
                    inner_self.end_headers()
                else:
                    inner_self.send_response(404)
                    inner_self.end_headers()

            def log_message(inner_self, *args):
                pass

        import socketserver
        server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever,
                         daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]

        self.build_project('', '# 无图交付\n')
        os.remove(os.path.join(self.tmp, 'source/page.html'))
        manifest_path = os.path.join(self.tmp, 'manifest.json')
        manifest = json.load(open(manifest_path, encoding='utf-8'))
        manifest['missing'] = [{
            'url': 'http://127.0.0.1:%d/page.html' % port,
            'save': 'source/page.html',
        }]
        open(manifest_path, 'w', encoding='utf-8').write(
            json.dumps(manifest, indent=2))
        snapshot = os.path.join(self.tmp, 'source/page.html')

        # 未获准补抓：失败且不落盘
        result = self.run_rebuild()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(snapshot))
        # 获准补抓：保存并完成
        result = self.run_rebuild(extra=('--fetch-missing',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(snapshot))
        # 完整快照复用：停服后仍成功（不发网络请求）
        server.shutdown()
        self.assertEqual(self.run_rebuild().returncode, 0)
        # 重定向导致版本不可确认：拒绝
        os.remove(snapshot)
        redirect = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=redirect.serve_forever,
                         daemon=True).start()
        self.addCleanup(redirect.shutdown)
        self.addCleanup(redirect.server_close)
        manifest['missing'][0]['url'] = (
            'http://127.0.0.1:%d/redirect' % redirect.server_address[1])
        open(manifest_path, 'w', encoding='utf-8').write(
            json.dumps(manifest, indent=2))
        result = self.run_rebuild(extra=('--fetch-missing',))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('重定向', result.stderr)
        self.assertFalse(os.path.exists(snapshot))


class RebuildDecouplingTest(unittest.TestCase):
    """图片回补与正文渲染解耦（精简 01）：无关表格不阻断回补。

    同一图片旁出现与图片归属无关的复杂跨列/跨行表格时，回补仍得到相同
    逐次绑定及尺寸；同一 HTML 进入新翻译解析时，复杂表格原有门禁仍有效。
    """

    COLSPAN_TABLE = ('<table><tr><th colspan="2">复杂表头</th></tr>'
                     '<tr><td rowspan="2">a</td><td>b</td></tr>'
                     '<tr><td>c</td></tr></table>')

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    # 各家族快照正文（{table} 占位注入无关复杂表格）；图片选择与
    # 引用形式遵循各家族规则：single/paginated 直引、reference 改写为
    # images/<basename>、api 只取亮版。
    FAMILY_CASES = {
        'single': {
            'img_a': '<img src="images/pic_a.png" style="width:40px">',
            'img_b': '<img src="images/pic_b.png" style="width:25px">',
            'sources': ('images/pic_a.png', 'images/pic_b.png'),
            'delivered': ('images/pic_a.png', 'images/pic_b.png'),
            'md': '# 章\n\n![1](images/pic_a.png)\n\n![2](images/pic_b.png)\n',
        },
        'paginated': {
            'img_a': '<img src="images/pic_a.png" style="width:40px">',
            'img_b': '<img src="images/pic_b.png" style="width:25px">',
            'sources': ('images/pic_a.png', 'images/pic_b.png'),
            'delivered': ('images/pic_a.png', 'images/pic_b.png'),
            'md': '# 章\n\n![1](images/pic_a.png)\n\n![2](images/pic_b.png)\n',
        },
        'reference': {
            'img_a': '<img src="_static/pic_a.png" style="width:40px">',
            'img_b': '<img src="_static/pic_b.png" style="width:25px">',
            'sources': ('_static/pic_a.png', '_static/pic_b.png'),
            'delivered': ('images/pic_a.png', 'images/pic_b.png'),
            'md': '# 章\n\n[IMG: images/pic_a.png]\n\n[IMG: images/pic_b.png]\n',
        },
        'api': {
            'img_a': ('<img class="only-dark" src="images/skip_dark.png">'
                      '<img src="images/pic_a.png" data-light="images/pic_a.png"'
                      ' data-dark="images/skip_dark.png" style="width:40px">'),
            'img_b': '<img src="images/pic_b.png" style="width:25px">',
            'sources': ('images/pic_a.png', 'images/pic_b.png'),
            'delivered': ('images/pic_a.png', 'images/pic_b.png'),
            'md': '# 章\n\n![1](images/pic_a.png)\n\n![2](images/pic_b.png)\n',
        },
    }

    def build_and_rebuild(self, family, with_table):
        # 每次构建独立子目录，避免不同家族/轮次的同名文件串扰
        self._runs = getattr(self, '_runs', 0) + 1
        tmp = os.path.join(self.tmp, 'run%d' % self._runs)
        case = self.FAMILY_CASES[family]
        table = self.COLSPAN_TABLE if with_table else ''
        for src_rel, delivered in zip(case['sources'], case['delivered']):
            self.make_png(os.path.join(tmp, 'source', src_rel), 20, 10)
            self.make_png(os.path.join(tmp, 'delivery', delivered), 20, 10)
        if family == 'api':
            self.make_png(os.path.join(tmp, 'source/images/skip_dark.png'),
                          20, 10)
        html = ('<html><body><article><h1>T</h1>'
                + case['img_a'] + table + case['img_b']
                + '</article></body></html>')
        open(os.path.join(tmp, 'source/page.html'), 'w',
             encoding='utf-8').write(html)
        open(os.path.join(tmp, 'delivery/final.md'), 'w',
             encoding='utf-8').write(case['md'])
        manifest = {
            'version': 1, 'source_version': '13.4-test', 'family': family,
            'pages': [{'snapshot': 'source/page.html',
                       'markdown': 'delivery/final.md'}],
        }
        open(os.path.join(tmp, 'manifest.json'), 'w',
             encoding='utf-8').write(json.dumps(manifest, indent=2))
        output = os.path.join(tmp,
                              'delivery/export/images_display.json')
        result = subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', os.path.join(tmp, 'manifest.json'),
             '--output', output],
            capture_output=True, text=True)
        return result, output

    def test_unrelated_table_keeps_binding_for_all_families(self):
        def binding(path):
            # 逐次绑定语义：出现、引用、交付字节与宽度。快照路径/摘要
            # 记录的是两次构建各自的快照（HTML 本就不同），不参与比较。
            payload = json.load(open(path, encoding='utf-8'))
            def shape(item):
                item = dict(item)
                item.pop('source', None)
                return item
            return ([shape(e) for e in payload['entries']],
                    [shape(u) for u in payload['undetermined']])
        for family in ('single', 'paginated', 'reference', 'api'):
            with self.subTest(family=family):
                plain_result, plain_out = self.build_and_rebuild(
                    family, with_table=False)
                self.assertEqual(plain_result.returncode, 0,
                                 plain_result.stderr)
                table_result, table_out = self.build_and_rebuild(
                    family, with_table=True)
                self.assertEqual(table_result.returncode, 0,
                                 table_result.stderr)
                self.assertEqual(binding(plain_out), binding(table_out))
                payload = json.load(open(table_out, encoding='utf-8'))
                self.assertEqual(
                    [e['width']['value'] for e in payload['entries']],
                    [40.0, 25.0])
                self.assertEqual([e['occurrence'] for e in payload['entries']],
                                 [1, 2])

    def test_same_html_still_blocked_by_new_translation_parse(self):
        # 同一 HTML 进入新翻译解析：复杂表格原有门禁仍有效（回补成功
        # 不解除解析侧的全文对账与结构阻断）
        case = self.FAMILY_CASES['single']
        html = ('<html><body><article><h1>T</h1>'
                + case['img_a'] + self.COLSPAN_TABLE + case['img_b']
                + '</article></body></html>')
        open(os.path.join(self.tmp, 'page.html'), 'w',
             encoding='utf-8').write(html)
        result = subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'parse_single_page_html.py'),
             os.path.join(self.tmp, 'page.html'),
             os.path.join(self.tmp, 'out.md')],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('跨行/跨列', result.stderr + result.stdout)

    def test_reference_same_basename_explicit_paths_bind(self):
        """同名异图（A8）：显式源路径直接命中各自源图，无关同名文件不阻断。

        reference 的 images/<basename> 改写只用于交付匹配；left/plot.png
        与 right/plot.png 按原始源引用解析，快照其他位置的同名文件不参与。
        交换交付图字节后身份核对拒绝，旧映射保持不变。
        """
        def make(path, w, h, color):
            self.make_png(path, w, h, color=color)
        tmp = self.tmp
        # 快照：两个子目录各有一张 plot.png（字节不同），另有一个无关
        # 目录也放了同名文件——都不再触发 basename 歧义
        make(os.path.join(tmp, 'source/left/plot.png'), 20, 10,
             b'\x10\x00\x00')
        make(os.path.join(tmp, 'source/right/plot.png'), 20, 10,
             b'\x20\x00\x00')
        make(os.path.join(tmp, 'source/decoy/plot.png'), 20, 10,
             b'\x30\x00\x00')
        # 交付：两处出现引用不同交付文件，字节与各自源一致
        make(os.path.join(tmp, 'delivery/images/plot_left.png'), 20, 10,
             b'\x10\x00\x00')
        make(os.path.join(tmp, 'delivery/images/plot_right.png'), 20, 10,
             b'\x20\x00\x00')
        html = ('<html><body><article><h1>T</h1>'
                '<img src="left/plot.png" style="width:40px">'
                '<img src="right/plot.png" style="width:25px">'
                '</article></body></html>')
        open(os.path.join(tmp, 'source/page.html'), 'w',
             encoding='utf-8').write(html)
        open(os.path.join(tmp, 'delivery/final.md'), 'w',
             encoding='utf-8').write(
                '# 章\n\n[IMG: images/plot_left.png]\n\n'
                '[IMG: images/plot_right.png]\n')
        manifest = {
            'version': 1, 'source_version': '13.4-test',
            'family': 'reference',
            'pages': [{'snapshot': 'source/page.html',
                       'markdown': 'delivery/final.md'}],
        }
        open(os.path.join(tmp, 'manifest.json'), 'w',
             encoding='utf-8').write(json.dumps(manifest))
        output = os.path.join(tmp, 'delivery/export/images_display.json')
        result = subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', os.path.join(tmp, 'manifest.json'),
             '--output', output],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.load(open(output, encoding='utf-8'))
        self.assertEqual([e['occurrence'] for e in payload['entries']],
                         [1, 2])
        self.assertEqual([e['width']['value'] for e in payload['entries']],
                         [40.0, 25.0])
        self.assertNotIn('歧义', result.stderr)
        # 损伤：交换两处交付图字节 → 身份核对拒绝，旧映射不变
        baseline = open(output, 'rb').read()
        left = open(os.path.join(tmp, 'delivery/images/plot_left.png'),
                    'rb').read()
        right = open(os.path.join(tmp, 'delivery/images/plot_right.png'),
                     'rb').read()
        open(os.path.join(tmp, 'delivery/images/plot_left.png'),
             'wb').write(right)
        open(os.path.join(tmp, 'delivery/images/plot_right.png'),
             'wb').write(left)
        result = subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', os.path.join(tmp, 'manifest.json'),
             '--output', output],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('身份不符', result.stderr)
        self.assertEqual(open(output, 'rb').read(), baseline)


class UndeterminedIdentityTest(unittest.TestCase):
    """未确定尺寸图片同样记录解析期身份（S05）：解析后同路径换图，API
    合并拒绝且不写新映射；未变图正常通过、原因与身份保持。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def build_site(self):
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'site/api'), exist_ok=True)
        open(os.path.join(tmp, 'site/api/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(tmp, 'site/api/pic.png'), 20, 10)
        open(os.path.join(tmp, 'site/api/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
        open(os.path.join(tmp, 'manifest.txt'), 'w',
             encoding='utf-8').write('api/page.html\n')
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'parse_api_html.py'),
             os.path.join(tmp, 'site/api/page.html'),
             os.path.join(tmp, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        with open(os.path.join(tmp, 'display/page.images_display.json'),
                  encoding='utf-8') as handle:
            return json.load(handle)

    def run_merge(self, label):
        out = os.path.join(self.tmp, 'out_%s/book.md' % label)
        return out, subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'merge_api.py'),
             os.path.join(self.tmp, 'manifest.txt'),
             os.path.join(self.tmp, 'site'), out,
             '--display-src', os.path.join(self.tmp, 'display')],
            capture_output=True, text=True)

    def test_undetermined_entry_records_identity_and_merge_normal(self):
        parse_map = self.build_site()
        self.assertEqual(len(parse_map['undetermined']), 1)
        self.assertTrue(parse_map['undetermined'][0]['resource_sha256'])
        out, result = self.run_merge('normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(os.path.dirname(out), 'export',
                               'images_display.json'), encoding='utf-8') as h:
            payload = json.load(h)
        self.assertEqual(len(payload['undetermined']), 1)
        self.assertEqual(payload['undetermined'][0]['reason'],
                         '源节点无宽度约束')
        self.assertTrue(payload['undetermined'][0]['source']
                        ['resource_sha256'])

    def test_same_path_swap_after_parse_rejected(self):
        self.build_site()
        # 解析后同路径换图（不同字节）：解析期身份与快照当前字节不符
        self.make_png(os.path.join(self.tmp, 'site/api/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        out, result = self.run_merge('swap')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份不符', result.stderr)
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(out), 'export',
                         'images_display.json')))

    def test_missing_parse_map_with_images_rejected(self):
        # F4：显式 --display-src 时删除有图页面的解析期映射必须失败，
        # 不得以空映射合并并覆盖既有交付映射
        self.build_site()
        out, result = self.run_merge('normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        export_map = os.path.join(os.path.dirname(out), 'export',
                                  'images_display.json')
        baseline = open(export_map, 'rb').read()
        os.remove(glob.glob(os.path.join(self.tmp,
                                         'display/*.images_display.json'))[0])
        _out2, result = self.run_merge('missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('解析期显示尺寸映射缺失', result.stderr)
        self.assertEqual(open(export_map, 'rb').read(), baseline)

    def test_empty_parse_map_rejected_and_old_map_preserved(self):
        # F4 第三轮：空壳 {} 映射没有可核对的独立来源事实，与缺文件
        # 同样失败保旧，不得绕过结构校验以空映射覆盖既有交付映射
        self.build_site()
        out, result = self.run_merge('normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        export_map = os.path.join(os.path.dirname(out), 'export',
                                  'images_display.json')
        baseline = open(export_map, 'rb').read()
        open(os.path.join(self.tmp, 'display/page.images_display.json'),
             'w', encoding='utf-8').write('{}')
        _out2, result = self.run_merge('empty')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未知映射版本', result.stderr)
        self.assertEqual(open(export_map, 'rb').read(), baseline)


class ConflictingDuplicateDeterminedEntryTest(unittest.TestCase):
    """03-S2：同一出现号内容冲突的确定项在共享绑定边界顺序无关拒绝；
    相同内容重复维持既有通过合同，正常单项不变。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def build_site(self):
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'site/api'), exist_ok=True)
        open(os.path.join(tmp, 'site/api/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img width="20" src="pic.png"/></article>')
        self.make_png(os.path.join(tmp, 'site/api/pic.png'), 20, 10)
        open(os.path.join(tmp, 'site/api/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n')
        open(os.path.join(tmp, 'manifest.txt'), 'w',
             encoding='utf-8').write('api/page.html\n')
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'parse_api_html.py'),
             os.path.join(tmp, 'site/api/page.html'),
             os.path.join(tmp, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        with open(os.path.join(tmp, 'display/page.images_display.json'),
                  encoding='utf-8') as handle:
            return json.load(handle)

    def write_entries(self, entries):
        map_path = os.path.join(self.tmp,
                                'display/page.images_display.json')
        with open(map_path, encoding='utf-8') as handle:
            payload = json.load(handle)
        payload['entries'] = entries
        open(map_path, 'w', encoding='utf-8').write(json.dumps(payload))

    def run_merge(self, label):
        out = os.path.join(self.tmp, 'out_%s/book.md' % label)
        return out, subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'merge_api.py'),
             os.path.join(self.tmp, 'manifest.txt'),
             os.path.join(self.tmp, 'site'), out,
             '--display-src', os.path.join(self.tmp, 'display')],
            capture_output=True, text=True)

    def test_conflicting_duplicates_rejected_regardless_of_order(self):
        base_map = self.build_site()
        self.assertEqual(len(base_map['entries']), 1)
        entry = base_map['entries'][0]
        bad = dict(entry, resource_sha256='0' * 64)
        for label, items in (('bad_first', [bad, entry]),
                             ('good_first', [entry, bad])):
            with self.subTest(order=label):
                self.write_entries(items)
                out, result = self.run_merge(label)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('确定项记录冲突', result.stderr)
                self.assertFalse(os.path.exists(os.path.join(
                    os.path.dirname(out), 'export',
                    'images_display.json')))

    def test_identical_duplicates_keep_existing_contract(self):
        base_map = self.build_site()
        entry = base_map['entries'][0]
        out, result = self.run_merge('single')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write_entries([entry, entry])
        _out2, result = self.run_merge('dup')
        self.assertEqual(result.returncode, 0, result.stderr)


class CodeImageLiteralMergeTest(unittest.TestCase):
    """03-S3：行内代码内的图片字面量在 API 合并不是真实出现——不改写、
    不要求目标文件存在、不触发缺映射门禁与出现号偏移；真实图片照常。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def run_merge(self, label):
        out = os.path.join(self.tmp, 'out_%s/book.md' % label)
        return out, subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'merge_api.py'),
             os.path.join(self.tmp, 'manifest.txt'),
             os.path.join(self.tmp, 'site'), out,
             '--display-src', os.path.join(self.tmp, 'display')],
            capture_output=True, text=True)

    def build_site(self, trans_bodies):
        """trans_bodies: {页面名: 译文 Markdown}；页面均含一张真实图片。"""
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        pages = []
        for name, body in trans_bodies.items():
            os.makedirs(os.path.join(tmp, 'site/api'), exist_ok=True)
            html = ('<article><h1>H</h1><p>Use '
                    '<code>![example](fake.png)</code>.</p>'
                    '<img width="20" src="pic.png"/></article>')
            open(os.path.join(tmp, 'site/api/%s.html' % name), 'w',
                 encoding='utf-8').write(html)
            self.make_png(os.path.join(tmp, 'site/api/pic.png'), 20, 10)
            open(os.path.join(tmp, 'site/api/trans_%s.md' % name), 'w',
                 encoding='utf-8').write(body)
            parse = subprocess.run(
                [sys.executable,
                 os.path.join(self.scripts, 'parse_api_html.py'),
                 os.path.join(tmp, 'site/api/%s.html' % name),
                 os.path.join(tmp, 'display/%s.md' % name)],
                capture_output=True, text=True)
            self.assertEqual(parse.returncode, 0, parse.stderr)
            pages.append('api/%s.html' % name)
        open(os.path.join(tmp, 'manifest.txt'), 'w',
             encoding='utf-8').write('\n'.join(pages) + '\n')

    def test_code_literal_untouched_and_real_image_localized(self):
        self.build_site({
            'page': '# H\n\nUse `![example](fake.png)`.\n\n![pic](pic.png)\n'})
        out, result = self.run_merge('normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = open(out, encoding='utf-8').read()
        # 代码字面量保持原文（目标 fake.png 不存在也不影响）
        self.assertIn('`![example](fake.png)`', text)
        self.assertIn('![pic](images/pic.png)', text)
        with open(os.path.join(os.path.dirname(out), 'export',
                               'images_display.json'), encoding='utf-8') as h:
            payload = json.load(h)
        self.assertEqual(len(payload['entries']), 1)

    def test_literal_only_page_needs_no_parse_map(self):
        # 仅含代码字面量的页面不是"有图页面"：无解析期映射也可合并，
        # 且不占出现号偏移（后页真实图片出现号不受影响）
        tmp = self.tmp
        self.build_site({
            'a': '# A\n\nUse `![example](fake.png)`.\n\n![pic](pic.png)\n'})
        # 追加一个仅代码字面量的页面 b（无解析期映射）
        open(os.path.join(tmp, 'site/api/b.html'), 'w',
             encoding='utf-8').write('<article><h1>B</h1></article>')
        open(os.path.join(tmp, 'site/api/trans_b.md'), 'w',
             encoding='utf-8').write('# B\n\nUse `![example](fake.png)`.\n')
        open(os.path.join(tmp, 'manifest.txt'), 'w',
             encoding='utf-8').write('api/a.html\napi/b.html\n')
        out, result = self.run_merge('literal_only')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = open(out, encoding='utf-8').read()
        self.assertIn('`![example](fake.png)`', text)
        with open(os.path.join(os.path.dirname(out), 'export',
                               'images_display.json'), encoding='utf-8') as h:
            payload = json.load(h)
        self.assertEqual(len(payload['entries']), 1)


class RebuildHistoricalIdentityTest(unittest.TestCase):
    """回补消费既有交付映射的历史身份（F3/S05）：同路径换图后回补必须
    拒绝且旧映射不变，不能用重算摘要覆盖既有独立证明。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def build_project(self):
        # API 翻译的正常共享资源布局：译文与快照引用同一 pic.png
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
        open(os.path.join(tmp, 'src/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(tmp, 'src/pic.png'), 20, 10)
        open(os.path.join(tmp, 'src/page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
        manifest = os.path.join(tmp, 'manifest.json')
        open(manifest, 'w', encoding='utf-8').write(json.dumps({
            'version': 1, 'source_version': 't', 'family': 'api',
            'pages': [{'snapshot': 'src/page.html',
                       'markdown': 'src/page.md'}]}))
        return manifest

    def run_rebuild(self, manifest, output):
        return subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', manifest, '--output', output,
             '--work-dir', os.path.join(self.tmp, 'work')],
            capture_output=True, text=True)

    def test_shared_resource_swap_rejected_and_old_map_kept(self):
        manifest = self.build_project()
        out = os.path.join(self.tmp, 'images_display.json')
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)
        baseline = open(out, 'rb').read()
        # 解析/回补后同路径换图：交付与快照同字节，唯有既有映射的
        # 历史身份可以证明换图——拒绝且旧映射不变
        self.make_png(os.path.join(self.tmp, 'src/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)
        # 换回原字节后同输入重跑恢复成功（同输入绑定语义一致）
        self.make_png(os.path.join(self.tmp, 'src/pic.png'), 20, 10)
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)


class RebuildParseHistoryTest(unittest.TestCase):
    """回补消费声明的解析期映射身份（F3 第三轮）：解析后同路径换图在
    任意输出路径（含首次回补）拒绝且旧映射不变；资源不变的显式重排
    通过；声明的映射与当前快照版本不符拒绝。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = str(Path(__file__).resolve().parents[1]
                           / 'skills/tech-doc-translator/scripts')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_png(path, w, h, color=b'\x01\x02\x03'):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        def chunk(tag, data):
            body = tag + data
            return (struct.pack('>I', len(data)) + body
                    + struct.pack('>I', zlib.crc32(body)))

        ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        raw = b''.join(b'\x00' + color * w for _ in range(h))
        open(path, 'wb').write(
            b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    def build_site(self):
        # API 翻译布局：快照与译文同目录共享 pic.png；解析期映射由真实
        # parse_api_html 产生，manifest 页显式声明为历史身份证明
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
        open(os.path.join(tmp, 'src/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(tmp, 'src/pic.png'), 20, 10)
        open(os.path.join(tmp, 'src/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts, 'parse_api_html.py'),
             os.path.join(tmp, 'src/page.html'),
             os.path.join(tmp, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        manifest = os.path.join(tmp, 'manifest.json')
        open(manifest, 'w', encoding='utf-8').write(json.dumps({
            'version': 1, 'source_version': 't', 'family': 'api',
            'pages': [{'snapshot': 'src/page.html',
                       'markdown': 'src/trans_page.md',
                       'parse_map': 'display/page.images_display.json'}]}))
        return manifest

    def run_rebuild(self, manifest, output):
        return subprocess.run(
            [sys.executable,
             os.path.join(self.scripts, 'rebuild_images_display.py'),
             '--manifest', manifest, '--output', output,
             '--work-dir', os.path.join(self.tmp, 'work')],
            capture_output=True, text=True)

    def test_first_rebuild_after_parse_swap_rejected(self):
        # 尚无任何交付映射的首次回补：解析期历史身份在磁盘上，换图
        # 必须拒绝，不能绑定新字节
        manifest = self.build_site()
        self.make_png(os.path.join(self.tmp, 'src/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        out = os.path.join(self.tmp, 'export/images_display.json')
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertFalse(os.path.exists(out))

    def test_changed_output_after_parse_swap_rejected(self):
        # 已有交付映射但换 --output：拒绝强度不得由输出路径决定
        manifest = self.build_site()
        out = os.path.join(self.tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)
        baseline = open(out, 'rb').read()
        self.make_png(os.path.join(self.tmp, 'src/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        other = os.path.join(self.tmp, 'candidate/images_display.json')
        result = self.run_rebuild(manifest, other)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertFalse(os.path.exists(other))
        self.assertEqual(open(out, 'rb').read(), baseline)

    def test_explicit_scope_reorder_passes(self):
        # 资源不变、manifest 与译文同步把出现对应 A/B 重排为 B/A：
        # 历史身份按来源关联（快照摘要+源节点），不是目标出现键，
        # 合法显式重排不得误判为换图
        tmp = self.tmp
        for name, color in (('a', b'\x01\x02\x03'), ('b', b'\x05\x06\x07')):
            self.make_png(os.path.join(tmp, name + '.png'), 20, 10,
                          color=color)
            open(os.path.join(tmp, name + '.html'), 'w',
                 encoding='utf-8').write(
                '<article><h1>%s</h1><img src="%s.png"/></article>'
                % (name, name))

        def write_inputs(names):
            open(os.path.join(tmp, 'trans_page.md'), 'w',
                 encoding='utf-8').write(
                '# H\n\n'
                + '\n\n'.join('![x](%s.png)' % n for n in names) + '\n')
            open(os.path.join(tmp, 'manifest.json'), 'w',
                 encoding='utf-8').write(json.dumps({
                     'version': 1, 'source_version': 't', 'family': 'api',
                     'pages': [{'snapshot': n + '.html',
                                'markdown': 'trans_page.md',
                                'image_range': [i, i]}
                               for i, n in enumerate(names, 1)]}))

        out = os.path.join(tmp, 'export/images_display.json')
        write_inputs(['a', 'b'])
        self.assertEqual(
            self.run_rebuild(os.path.join(tmp, 'manifest.json'),
                             out).returncode, 0)
        baseline = open(out, 'rb').read()
        write_inputs(['b', 'a'])
        result = self.run_rebuild(os.path.join(tmp, 'manifest.json'), out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(open(out, 'rb').read(), baseline)  # 新合法顺序

    def test_declared_parse_map_snapshot_mismatch_rejected(self):
        # 声明的解析期映射来自不同快照版本：不能宣称同版本回补
        manifest = self.build_site()
        open(os.path.join(self.tmp, 'src/page.html'), 'a',
             encoding='utf-8').write('<p>changed</p>')
        out = os.path.join(self.tmp, 'export/images_display.json')
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('快照版本不符', result.stderr)
        self.assertFalse(os.path.exists(out))

    def _build_twins(self):
        # 不同目录中内容相同的快照，各自引用本目录内不同的 pic.png
        # （R3 同名不同图）；解析期映射由真实 parse_api_html 逐目录产生
        tmp = self.tmp
        pages = []
        for name, color in (('left', b'\x01\x02\x03'),
                            ('right', b'\x05\x06\x07')):
            page_dir = os.path.join(tmp, name)
            os.makedirs(os.path.join(page_dir, 'display'), exist_ok=True)
            open(os.path.join(page_dir, 'page.html'), 'w',
                 encoding='utf-8').write(
                '<article><h1>H</h1><img src="pic.png"/><p>text</p>'
                '</article>')
            self.make_png(os.path.join(page_dir, 'pic.png'), 20, 10,
                          color=color)
            open(os.path.join(page_dir, 'trans_page.md'), 'w',
                 encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
            parse = subprocess.run(
                [sys.executable, os.path.join(self.scripts,
                                              'parse_api_html.py'),
                 os.path.join(page_dir, 'page.html'),
                 os.path.join(page_dir, 'display/page.md')],
                capture_output=True, text=True)
            self.assertEqual(parse.returncode, 0, parse.stderr)
            pages.append({'snapshot': name + '/page.html',
                          'markdown': name + '/trans_page.md',
                          'parse_map': name
                          + '/display/page.images_display.json'})
        return pages

    def _write_manifest(self, pages):
        manifest = os.path.join(self.tmp, 'manifest.json')
        open(manifest, 'w', encoding='utf-8').write(json.dumps({
            'version': 1, 'source_version': 't', 'family': 'api',
            'pages': pages}))
        return manifest

    def test_twin_snapshots_distinct_images_stable_and_swap_rejected(self):
        # F3 第四轮：来源身份含目录上下文——声明各自解析映射时首次
        # 回补与完全同输入重跑都通过；把 left 图片换成 right 的字节
        # （真实同路径换图）必须拒绝且旧映射不变
        manifest = self._write_manifest(self._build_twins())
        out = os.path.join(self.tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)
        baseline = open(out, 'rb').read()
        result = self.run_rebuild(manifest, out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)  # 重复回补语义一致
        open(os.path.join(self.tmp, 'left/pic.png'), 'wb').write(
            open(os.path.join(self.tmp, 'right/pic.png'), 'rb').read())
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)

    def test_twin_snapshots_without_declaration_repeatable(self):
        # 同上布局，不声明解析映射：首次回补产生的旧交付映射在第二
        # 次同输入回补时按来源身份命中，不因同名不同图误拒
        pages = self._build_twins()
        for page in pages:
            page.pop('parse_map')
        manifest = self._write_manifest(pages)
        out = os.path.join(self.tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)
        result = self.run_rebuild(manifest, out)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_conflicting_proofs_rejected_instead_of_overwritten(self):
        # F3 第四轮：同路径换图后重新解析产生的新证明与旧交付证明对
        # 同一来源冲突——声明新 parse_map 不得静默覆盖旧证明，冲突
        # 拒绝且旧映射不变（更换已确认来源须人工移除过时记录）
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
        open(os.path.join(tmp, 'src/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(tmp, 'src/pic.png'), 20, 10)
        open(os.path.join(tmp, 'src/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')

        def parse(out_name):
            os.makedirs(os.path.dirname(os.path.join(tmp, out_name)),
                        exist_ok=True)
            result = subprocess.run(
                [sys.executable,
                 os.path.join(self.scripts, 'parse_api_html.py'),
                 os.path.join(tmp, 'src/page.html'),
                 os.path.join(tmp, out_name)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

        def write_manifest(parse_map=None):
            page = {'snapshot': 'src/page.html',
                    'markdown': 'src/trans_page.md'}
            if parse_map:
                page['parse_map'] = parse_map
            manifest = os.path.join(tmp, 'manifest.json')
            open(manifest, 'w', encoding='utf-8').write(json.dumps({
                'version': 1, 'source_version': 't', 'family': 'api',
                'pages': [page]}))
            return manifest

        parse('display/page.md')
        out = os.path.join(tmp, 'export/images_display.json')
        self.assertEqual(
            self.run_rebuild(write_manifest(), out).returncode, 0)
        baseline = open(out, 'rb').read()
        # 同路径换图并重新解析：不声明新映射时按既有证明正确拒绝
        self.make_png(os.path.join(tmp, 'src/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        parse('display2/page.md')
        result = self.run_rebuild(write_manifest(), out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        # 声明重新生成的映射：两份既有独立证明冲突，不得覆盖
        result = self.run_rebuild(
            write_manifest('display2/page.images_display.json'), out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('独立来源证明冲突', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)

    def test_unified_absolute_source_refs_and_legacy_relative_fail(self):
        # F3 第六轮：来源字段写入端与读取端统一为绝对规范化路径。
        # 评审布局 project/source：解析/合并从 project/ 以相对参数
        # source/page.html 执行（记录基点随解析执行目录变化），回补
        # 清单位于 project/ 声明 source/page.html——同一条记录两端
        # 含义一致；旧版相对记录（修复前产物）明确失败保旧，不猜基点
        tmp = self.tmp
        src = os.path.join(tmp, 'source')
        os.makedirs(os.path.join(src, 'display'), exist_ok=True)
        open(os.path.join(src, 'page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(src, 'pic.png'), 20, 10)
        open(os.path.join(src, 'trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
        open(os.path.join(src, 'manifest.txt'), 'w',
             encoding='utf-8').write('page.html\n')

        def call(script, args, cwd):
            return subprocess.run(
                [sys.executable, os.path.join(self.scripts, script)]
                + [os.path.join(tmp, a) if a.startswith('..') else a
                   for a in args],
                capture_output=True, text=True, cwd=cwd)

        self.assertEqual(
            call('parse_api_html.py', ['source/page.html',
                                       'source/display/page.md'],
                 tmp).returncode, 0)
        merged = call('merge_api.py',
                      ['source/manifest.txt', 'source', 'source/book.md',
                       '--display-src', 'source/display'], tmp)
        self.assertEqual(merged.returncode, 0, merged.stderr)
        parse_map_path = os.path.join(
            src, 'display/page.images_display.json')
        recorded = json.load(open(parse_map_path, encoding='utf-8'))
        # 写入端统一：无论 CLI 参数形式，持久记录都是解析后的绝对来源
        self.assertEqual(recorded['snapshot'],
                         os.path.realpath(os.path.join(src, 'page.html')))
        out = os.path.join(src, 'export/images_display.json')
        baseline = open(out, 'rb').read()
        manifest_plain = os.path.join(tmp, 'manifest.json')
        open(manifest_plain, 'w', encoding='utf-8').write(json.dumps({
            'version': 1, 'source_version': 't', 'family': 'api',
            'pages': [{'snapshot': 'source/page.html',
                       'markdown': 'source/book.md'}]}))
        manifest_declared = os.path.join(tmp, 'declared.json')

        def write_declared():
            open(manifest_declared, 'w', encoding='utf-8').write(
                json.dumps({
                    'version': 1, 'source_version': 't', 'family': 'api',
                    'pages': [{'snapshot': 'source/page.html',
                               'markdown': 'source/book.md',
                               'parse_map': 'source/display/'
                                            'page.images_display.json'}]}))

        write_declared()

        def rb(manifest, cwd):
            return call('rebuild_images_display.py',
                        ['--manifest', manifest, '--output', out,
                         '--work-dir', os.path.join(tmp, 'work')], cwd)

        def swap_image():
            self.make_png(os.path.join(src, 'pic.png'), 40, 10,
                          color=b'\x09\x08\x07')
            open(os.path.join(src, 'images/pic.png'), 'wb').write(
                open(os.path.join(src, 'pic.png'), 'rb').read())

        def restore_image():
            self.make_png(os.path.join(src, 'pic.png'), 20, 10)
            open(os.path.join(src, 'images/pic.png'), 'wb').write(
                open(os.path.join(src, 'pic.png'), 'rb').read())

        # 未声明 + 未换图：通过
        self.assertEqual(rb(manifest_plain, '/private/tmp').returncode, 0)
        open(out, 'wb').write(baseline)
        # 未声明 + 同路径换图：两个 cwd 均拒绝保旧（绝对历史正确关联）
        swap_image()
        for cwd in (src, '/private/tmp'):
            result = rb(manifest_plain, cwd)
            self.assertNotEqual(result.returncode, 0, cwd)
            self.assertIn('源资源身份与既有独立记录不符', result.stderr)
            self.assertEqual(open(out, 'rb').read(), baseline, cwd)
        # 声明 + 未换图：正确声明通过
        restore_image()
        result = rb(manifest_declared, '/private/tmp')
        self.assertEqual(result.returncode, 0, result.stderr)
        open(out, 'wb').write(baseline)
        # 声明 + 同路径换图：拒绝保旧
        swap_image()
        result = rb(manifest_declared, src)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)
        restore_image()
        open(out, 'wb').write(baseline)
        # 旧版相对来源记录（模拟修复前产物）：明确失败保旧，不猜基点、
        # 不静默降为无历史
        payload = json.load(open(parse_map_path, encoding='utf-8'))
        payload['snapshot'] = 'page.html'
        open(parse_map_path, 'w', encoding='utf-8').write(
            json.dumps(payload, ensure_ascii=False))
        result = rb(manifest_declared, '/private/tmp')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('旧版相对来源记录', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)
        delivery = json.loads(baseline.decode('utf-8'))
        for item in delivery['undetermined']:
            item['source']['snapshot'] = 'page.html'
        open(out, 'w', encoding='utf-8').write(
            json.dumps(delivery, ensure_ascii=False))
        legacy_baseline = open(out, 'rb').read()
        swap_image()
        result = rb(manifest_plain, src)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('旧版相对来源记录', result.stderr)
        self.assertEqual(open(out, 'rb').read(), legacy_baseline)

    def test_file_symlink_keeps_resource_base_consistent(self):
        # F3 第七轮：alias/page.html 是指向 ../real/page.html 的文件
        # 符号链接，两目录各有不同的 pic.png。来源文件身份按 realpath
        # 归一（历史键/持久记录），相对资源基点保持清单声明路径的目录
        # ——解析按声明路径 dirname 读 alias/pic.png，回补读同一资源，
        # 不因规范化 HTML 路径而改变图片目录（无搬迁/换图/改映射）
        tmp = self.tmp
        real = os.path.join(tmp, 'real')
        alias = os.path.join(tmp, 'alias')
        os.makedirs(real, exist_ok=True)
        os.makedirs(os.path.join(alias, 'display'), exist_ok=True)
        open(os.path.join(real, 'page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        self.make_png(os.path.join(real, 'pic.png'), 20, 10)
        self.make_png(os.path.join(alias, 'pic.png'), 20, 10,
                      color=b'\x05\x06\x07')
        os.symlink(os.path.join(real, 'page.html'),
                   os.path.join(alias, 'page.html'))
        open(os.path.join(alias, 'trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts,
                                          'parse_api_html.py'),
             os.path.join(alias, 'page.html'),
             os.path.join(alias, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        parse_map = json.load(open(
            os.path.join(alias, 'display/page.images_display.json'),
            encoding='utf-8'))
        # 写入端身份归一：记录指向真实文件；但解析期资源身份取自
        # 声明路径目录的 alias/pic.png
        self.assertEqual(parse_map['snapshot'],
                         os.path.realpath(os.path.join(alias, 'page.html')))
        parse_digest = parse_map['undetermined'][0]['resource_sha256']

        def write_manifest(with_map):
            page = {'snapshot': 'alias/page.html',
                    'markdown': 'alias/trans_page.md'}
            if with_map:
                page['parse_map'] = 'alias/display/page.images_display.json'
            manifest = os.path.join(tmp, 'manifest.json')
            open(manifest, 'w', encoding='utf-8').write(json.dumps({
                'version': 1, 'source_version': 't', 'family': 'api',
                'pages': [page]}))
            return manifest

        out = os.path.join(tmp, 'export/images_display.json')
        # 声明解析映射 + 未换图：解析/回补读取同一资源，通过并可重复
        result = self.run_rebuild(write_manifest(True), out)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = open(out, 'rb').read()
        payload = json.loads(first.decode('utf-8'))
        self.assertEqual(payload['undetermined'][0]['source']
                         ['resource_sha256'], parse_digest)
        result = self.run_rebuild(write_manifest(True), out)
        self.assertEqual(result.returncode, 0, result.stderr)
        # 未声明分支：同输入重复回补同样语义一致
        result = self.run_rebuild(write_manifest(False), out)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_rebuild(write_manifest(False), out)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_parse_map_from_other_source_rejected(self):
        # F3 第五轮：声明的解析映射自身记录的来源必须与清单页同一文件；
        # 字节相同的不同目录快照（twins）互为证明时按误指来源拒绝，
        # 不得把其他来源的证明重标为当前页历史
        pages = self._build_twins()
        pages[0]['parse_map'] = 'right/display/page.images_display.json'
        manifest = self._write_manifest(pages[:1])
        out = os.path.join(self.tmp, 'export/images_display.json')
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不是同一来源', result.stderr)
        self.assertFalse(os.path.exists(out))
        # 换图成 right 字节后同样拒绝（不能让误指证明放行换图）
        open(os.path.join(self.tmp, 'left/pic.png'), 'wb').write(
            open(os.path.join(self.tmp, 'right/pic.png'), 'rb').read())
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不是同一来源', result.stderr)
        self.assertFalse(os.path.exists(out))

    def test_conflicting_records_within_one_parse_map_order_agnostic(self):
        # F3 第五轮：同一解析映射文件内同来源不同摘要的冲突记录，
        # 无论顺序一律拒绝；同摘要记录照常通过
        import copy
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        open(os.path.join(tmp, 'src/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        open(os.path.join(tmp, 'src/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')

        def parse(color, out_name):
            self.make_png(os.path.join(tmp, 'src/pic.png'), 20, 10,
                          color=color)
            os.makedirs(os.path.dirname(os.path.join(tmp, out_name)),
                        exist_ok=True)
            result = subprocess.run(
                [sys.executable,
                 os.path.join(self.scripts, 'parse_api_html.py'),
                 os.path.join(tmp, 'src/page.html'),
                 os.path.join(tmp, out_name)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.load(open(
                os.path.splitext(os.path.join(tmp, out_name))[0]
                + '.images_display.json', encoding='utf-8'))

        map_a = parse(b'\x01\x02\x03', 'display/a.md')
        map_b = parse(b'\x04\x05\x06', 'display/b.md')

        def combined(entries):
            payload = copy.deepcopy(map_b)
            payload['undetermined'] = copy.deepcopy(entries)
            for index, item in enumerate(payload['undetermined'], start=1):
                item['occurrence'] = index
            path = os.path.join(tmp, 'display/combined.json')
            open(path, 'w', encoding='utf-8').write(
                json.dumps(payload, ensure_ascii=False))
            return path

        def rebuild_with(parse_map):
            manifest = os.path.join(tmp, 'manifest.json')
            open(manifest, 'w', encoding='utf-8').write(json.dumps({
                'version': 1, 'source_version': 't', 'family': 'api',
                'pages': [{'snapshot': 'src/page.html',
                           'markdown': 'src/trans_page.md',
                           'parse_map': parse_map}]}))
            return self.run_rebuild(
                manifest, os.path.join(tmp, 'export/images_display.json'))

        # 当前字节为 B：A→B 与 B→A 两种冲突顺序都拒绝，与记录顺序无关
        for entries in ((map_a['undetermined'][0], map_b['undetermined'][0]),
                        (map_b['undetermined'][0], map_a['undetermined'][0])):
            result = rebuild_with(combined(list(entries)))
            self.assertNotEqual(result.returncode, 0, entries)
            self.assertIn('独立来源证明冲突', result.stderr)
        # 同摘要（B/B）控制照常通过
        result = rebuild_with(
            combined([map_b['undetermined'][0], map_b['undetermined'][0]]))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _build_symlink_twins(self):
        # 两个文件别名指向同一 real/page.html（文件级符号链接），HTML
        # 相对引用 pic.png，left/right 各自目录有不同的 pic.png。两页
        # 分别真实 parse/merge（F3 第八轮评审布局）
        tmp = self.tmp
        real = os.path.join(tmp, 'real')
        os.makedirs(real, exist_ok=True)
        open(os.path.join(real, 'page.html'), 'w', encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>text</p></article>')
        pages = []
        for name, color in (('left', b'\x01\x02\x03'),
                            ('right', b'\x05\x06\x07')):
            page_dir = os.path.join(tmp, name)
            os.makedirs(os.path.join(page_dir, 'display'), exist_ok=True)
            os.symlink(os.path.join(real, 'page.html'),
                       os.path.join(page_dir, 'page.html'))
            self.make_png(os.path.join(page_dir, 'pic.png'), 20, 10,
                          color=color)
            open(os.path.join(page_dir, 'trans_page.md'), 'w',
                 encoding='utf-8').write('# H\n\n![pic](pic.png)\n\ntext\n')
            open(os.path.join(page_dir, 'manifest.txt'), 'w',
                 encoding='utf-8').write('page.html\n')
            parse = subprocess.run(
                [sys.executable, os.path.join(self.scripts,
                                              'parse_api_html.py'),
                 os.path.join(page_dir, 'page.html'),
                 os.path.join(page_dir, 'display/page.md')],
                capture_output=True, text=True)
            self.assertEqual(parse.returncode, 0, parse.stderr)
            merged = subprocess.run(
                [sys.executable, os.path.join(self.scripts, 'merge_api.py'),
                 'manifest.txt', '.', 'book.md',
                 '--display-src', 'display'],
                capture_output=True, text=True, cwd=page_dir)
            self.assertEqual(merged.returncode, 0, merged.stderr)
            pages.append({'snapshot': name + '/page.html',
                          'markdown': name + '/book.md',
                          'parse_map': name
                          + '/display/page.images_display.json'})
        return pages

    def test_symlink_aliases_declared_and_undeclared_stable(self):
        # F3 第八轮：双文件别名不同资源。来源身份含资源解析上下文——
        # 各自正确声明的联合回补首次与重复均通过；未声明分支首次成功、
        # 完全相同输入重跑语义一致（不再自报证明冲突）
        pages = self._build_symlink_twins()
        declared = self._write_manifest(pages)
        out = os.path.join(self.tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(declared, out).returncode, 0)
        baseline = open(out, 'rb').read()
        result = self.run_rebuild(declared, out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)
        # 两个上下文各自的资源身份分别记录
        payload = json.loads(baseline.decode('utf-8'))
        bases = sorted(item['source']['resource_base']
                       for item in payload['undetermined'])
        self.assertEqual(bases, [os.path.realpath(
            os.path.join(self.tmp, name)) for name in ('left', 'right')])
        # 未声明：首次与原样重跑均成功，绑定语义稳定
        for page in pages:
            page.pop('parse_map')
        plain = self._write_manifest(pages)
        out2 = os.path.join(self.tmp, 'export2/images_display.json')
        self.assertEqual(self.run_rebuild(plain, out2).returncode, 0)
        result = self.run_rebuild(plain, out2)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symlink_alias_wrong_context_proof_rejected(self):
        # F3 第八轮：left 错用 right 的解析期映射——无论 left 源图与
        # 交付图是否换成 right 字节，其他资源上下文的证明都不能当作
        # left 历史；改回 left 原映射则正确拒绝换图
        pages = self._build_symlink_twins()
        left_only = [dict(pages[0],
                          parse_map='right/display/page.images_display.json')]
        manifest = self._write_manifest(left_only)
        out = os.path.join(self.tmp, 'export/images_display.json')
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('资源解析上下文', result.stderr)
        self.assertFalse(os.path.exists(out))
        # 换图成 right 字节后错误证明仍不得通过
        for path in ([os.path.join(self.tmp, 'left/pic.png')]
                     + glob.glob(os.path.join(self.tmp, 'left/images/*'))):
            open(path, 'wb').write(
                open(os.path.join(self.tmp, 'right/pic.png'), 'rb').read())
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('资源解析上下文', result.stderr)
        self.assertFalse(os.path.exists(out))
        # 改回 left 原映射：按同路径换图正确拒绝（证明归于正确上下文）
        manifest = self._write_manifest(pages[:1])
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertFalse(os.path.exists(out))

    def test_symlink_alias_swap_rejected_restore_passes(self):
        # F3 第八轮：双别名下正确声明——正常图通过，同路径换图拒绝且
        # 旧映射逐字节不变，恢复原图后再次通过
        pages = self._build_symlink_twins()
        manifest = self._write_manifest(pages[:1])
        out = os.path.join(self.tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(manifest, out).returncode, 0)
        # 同路径换图：拒绝且旧映射逐字节不变（基线取自失败操作前）
        self.make_png(os.path.join(self.tmp, 'left/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        for path in glob.glob(os.path.join(self.tmp, 'left/images/*')):
            open(path, 'wb').write(
                open(os.path.join(self.tmp, 'left/pic.png'), 'rb').read())
        baseline = open(out, 'rb').read()  # 失败操作前的最新产物
        result = self.run_rebuild(manifest, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源资源身份与既有独立记录不符', result.stderr)
        self.assertEqual(open(out, 'rb').read(), baseline)
        # 恢复原图：合法输入恢复通过
        self.make_png(os.path.join(self.tmp, 'left/pic.png'), 20, 10)
        for path in glob.glob(os.path.join(self.tmp, 'left/images/*')):
            open(path, 'wb').write(
                open(os.path.join(self.tmp, 'left/pic.png'), 'rb').read())
        result = self.run_rebuild(manifest, out)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dir_symlink_same_resource_context_accepted(self):
        # F3 第八轮兼容：目录级符号链接经 realpath 归一为同一资源
        # 上下文——经 linkA 解析、经 linkB 声明同一目录仍为同一来源
        tmp = self.tmp
        proj = os.path.join(tmp, 'proj')
        os.makedirs(os.path.join(proj, 'display'), exist_ok=True)
        open(os.path.join(proj, 'page.html'), 'w', encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>t</p></article>')
        self.make_png(os.path.join(proj, 'pic.png'), 20, 10)
        open(os.path.join(proj, 'trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\nt\n')
        os.symlink('proj', os.path.join(tmp, 'linkA'))
        os.symlink('proj', os.path.join(tmp, 'linkB'))
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts,
                                          'parse_api_html.py'),
             os.path.join(tmp, 'linkA/page.html'),
             os.path.join(proj, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        manifest = self._write_manifest([{
            'snapshot': 'linkB/page.html',
            'markdown': 'proj/trans_page.md',
            'parse_map': 'proj/display/page.images_display.json'}])
        out = os.path.join(tmp, 'export/images_display.json')
        result = self.run_rebuild(manifest, out)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_records_missing_resource_base_fail(self):
        # F3 第八轮兼容：含完整身份但缺 resource_base 的旧记录（第六/
        # 七轮格式）资源上下文不可确定——明确失败保旧，不静默降为无
        # 历史；重新解析/合并即生成含上下文记录
        tmp = self.tmp
        os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
        os.makedirs(os.path.join(tmp, 'display'), exist_ok=True)
        open(os.path.join(tmp, 'src/page.html'), 'w',
             encoding='utf-8').write(
            '<article><h1>H</h1><img src="pic.png"/><p>t</p></article>')
        self.make_png(os.path.join(tmp, 'src/pic.png'), 20, 10)
        open(os.path.join(tmp, 'src/trans_page.md'), 'w',
             encoding='utf-8').write('# H\n\n![pic](pic.png)\n\nt\n')
        parse = subprocess.run(
            [sys.executable, os.path.join(self.scripts,
                                          'parse_api_html.py'),
             os.path.join(tmp, 'src/page.html'),
             os.path.join(tmp, 'display/page.md')],
            capture_output=True, text=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        plain = self._write_manifest([{'snapshot': 'src/page.html',
                                       'markdown': 'src/trans_page.md'}])
        out = os.path.join(tmp, 'export/images_display.json')
        self.assertEqual(self.run_rebuild(plain, out).returncode, 0)
        # 旧格式交付历史：剥离 resource_base，换图不得静默通过
        delivery = json.load(open(out, encoding='utf-8'))
        for item in delivery['undetermined']:
            item['source'].pop('resource_base', None)
        open(out, 'w', encoding='utf-8').write(
            json.dumps(delivery, ensure_ascii=False))
        legacy_baseline = open(out, 'rb').read()
        self.make_png(os.path.join(tmp, 'src/pic.png'), 40, 10,
                      color=b'\x09\x08\x07')
        result = self.run_rebuild(plain, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('resource_base', result.stderr)
        self.assertEqual(open(out, 'rb').read(), legacy_baseline)
        # 旧格式声明映射：同样明确失败，不产生新映射
        parse_map_path = os.path.join(
            tmp, 'display/page.images_display.json')
        recorded = json.load(open(parse_map_path, encoding='utf-8'))
        recorded.pop('resource_base', None)
        open(parse_map_path, 'w', encoding='utf-8').write(
            json.dumps(recorded, ensure_ascii=False))
        os.unlink(out)
        declared = self._write_manifest([{
            'snapshot': 'src/page.html',
            'markdown': 'src/trans_page.md',
            'parse_map': 'display/page.images_display.json'}])
        result = self.run_rebuild(declared, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('resource_base', result.stderr)
        self.assertFalse(os.path.exists(out))


if __name__ == '__main__':
    unittest.main()
