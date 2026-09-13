"""离线图片身份与交付路径的固定语义验收（任务 05）。"""
import hashlib
import os
import sys
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
