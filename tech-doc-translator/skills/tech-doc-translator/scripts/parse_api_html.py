#!/usr/bin/env python3
"""多页面 API/DSL 文档的单页 HTML → 源 Markdown 提取器。

用法：
    python3 parse_api_html.py <page.html> <out.md>

特性：
- 页面级标题（H1–H6）原样提取。
- 代码标签页（sphinx-tabs）按 Tab 标签展开，保留各面板代码。
- 暗亮图片对只取 light 版本。
- 保留代码围栏、公式、表格、脚注、API 签名（定义列表）等结构。
- 未识别块级元素输出 [TAGNAME] 占位。
"""
import argparse
import json
import os
import re
import sys
import tempfile

from bs4 import Comment, Tag

from _html_fidelity import HtmlFidelity, warn_if_temp_output
from _source_reconcile import reconcile_html_to_markdown
from _verification import file_sha256
from _api_navigation import source_anchor_ids, anchor_diffs


# 按 HTML5 惯例视为块级、本脚本未显式展开的元素；遇到时输出占位。
_BLOCK_TAGS = {
    'address', 'article', 'aside', 'blockquote', 'details', 'dialog',
    'fieldset', 'figcaption', 'footer', 'form', 'header', 'hgroup',
    'main', 'nav', 'section', 'summary',
}

def _is_dark_only(img):
    cls = ' '.join(img.get('class') or [])
    return 'only-dark' in cls or img.get('data-dark') and not img.get('data-light')


def _is_light(img):
    cls = ' '.join(img.get('class') or [])
    return 'only-light' in cls or img.get('data-light')


def _image_src(img):
    if img.get('data-light'):
        return img['data-light']
    return img.get('src', '')


def _has_block_content(tag):
    """判断一个容器是否含有块级内容或受保护的 pre 占位。"""
    if tag.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure', 'img'], recursive=True):
        return True
    for c in tag.find_all(string=lambda t: isinstance(t, Comment)):
        if re.match(r'\s*__TECHDOC_PRE_\d+__\s*', c):
            return True
    return False


def _has_rich_content(tag):
    """纯文字包装沿原合同；可能丢结构的内容必须显式分派。"""
    return tag.find(['pre', 'ul', 'ol', 'table', 'dl', 'img', 'figure', 'details',
                     'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']) is not None \
        or any(re.match(r'\s*__TECHDOC_PRE_\d+__\s*', str(c))
               for c in tag.find_all(string=lambda t: isinstance(t, Comment)))


def _image_inline(tag, fidelity):
    if _is_dark_only(tag):
        return ''
    src = _image_src(tag)
    alt = tag.get('alt', '')
    if src:
        fidelity.note_image(tag, src)
        return '![%s](%s)' % (alt, src)
    return ''


def _image_block(tag, out, fidelity):
    text = _image_inline(tag, fidelity)
    if text:
        out.append('\n' + text)


def _tabs_block(tag, out, fidelity):
    """处理 sphinx-tabs：为每个 tab 输出标签行，再递归渲染面板内容。"""
    if 'sd-tab-set' in (tag.get('class') or []):
        buttons = tag.find_all(class_='sd-tab-label', recursive=False)
        panels = tag.find_all(class_='sd-tab-content', recursive=False)
        for button, panel in zip(buttons, panels):
            control = tag.find('input', id=button.get('for'), recursive=False)
            if control is None or panel.find_previous_sibling(class_='sd-tab-label') is not button:
                raise ValueError('sd-tab-set 标签 / 面板关系不明确: %s' % button)
    else:
        tablist = tag.find(attrs={'role': 'tablist'})
        buttons = (tablist.find_all(attrs={'role': 'tab'}) if tablist
                   else tag.find_all(class_='sphinx-tabs-tab'))
        panels = tag.find_all(attrs={'role': 'tabpanel'})
        if not panels:
            panels = tag.find_all(class_='sphinx-tabs-panel')
        def owned(node):
            return next((p for p in node.parents if isinstance(p, Tag)
                         and 'sphinx-tabs' in (p.get('class') or [])), None) is tag
        buttons = [b for b in buttons if owned(b)]
        panels = [p for p in panels if owned(p)]
    if buttons and panels and len(buttons) == len(panels):
        selected = []
        for index, btn in enumerate(buttons):
            target = btn.get('aria-controls')
            matches = [p for p in panels if p.get('id') == target] if target else [panels[index]]
            if len(matches) != 1 or any(p is matches[0] for p in selected):
                raise ValueError('标签页面板无法唯一定位: %s' % target)
            panel = matches[0]
            selected.append(panel)
            label = fidelity.render_inline(btn)
            if label:
                out.append('\n**[Tab: %s]**' % label)
            render(panel, out, fidelity)
    else:
        raise ValueError('标签页无法配对: %s（标签 %d，面板 %d）'
                         % (tag.get('id') or tag.get('class'), len(buttons), len(panels)))


def render(node, out, fidelity):
    fidelity.inline_image = lambda img: _image_inline(img, fidelity)
    _render_children(node, out, fidelity)


def _render_children(node, out, fidelity, include_self=False):
    render_block = lambda tag, o: _render_children(tag, o, fidelity, include_self=True)
    emit_image = lambda tag, o: _image_block(tag, o, fidelity)
    for child in ([node] if include_self else node.children):
        fenced = fidelity.fenced_pre(child)
        if fenced is not None:
            out.append(fenced)
            continue
        if isinstance(child, str):
            continue
        if not isinstance(child, Tag):
            continue
        name, cls = child.name, ' '.join(child.get('class') or [])
        for anchor in source_anchor_ids(child):
            from html import escape
            out.append('\n<a id="%s"></a>\n' % escape(anchor, quote=True))
        if name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            out.append('\n' + fidelity.heading_line(
                int(name[1]), fidelity.clean_heading(
                    fidelity.heading_text(child, escape_backslashes=True))))
        elif name == 'p':
            t = fidelity.paragraph_text(child)
            if t:
                out.append('\n' + t)
        elif name in ('ul', 'ol'):
            fidelity.list_lines(child, out, '  ', render_block, emit_image)
        elif name == 'pre':
            text = child.get_text()
            out.append('\n```\n' + text.rstrip('\n') + '\n```')
        elif name == 'dl':
            out.extend(fidelity.definition_list(
                child, render_block, emit_image))
        elif name == 'table':
            out.extend(fidelity.table_block(child))
        elif name == 'img':
            _image_block(child, out, fidelity)
        elif name == 'figure':
            render(child, out, fidelity)
        elif name == 'figcaption' and _has_rich_content(child):
            render(child, out, fidelity)
        elif name == 'aside' and 'footnote-list' in (child.get('class') or []):
            render(child, out, fidelity)
        elif name == 'aside' and fidelity.is_footnote_aside(child):
            rich = child.find(['ul', 'ol', 'table', 'dl', 'details', 'div', 'img']) is not None \
                or any(fidelity.fenced_pre(c) is not None for c in child.children)
            out.extend(fidelity.footnote_aside_lines(
                child, render_block if rich else None, emit_image if rich else None))
        elif name == 'details':
            summary = child.find('summary')
            label = fidelity.render_inline(summary) if summary else ''
            out.append('\n[DETAILS] %s' % label.strip())
            fidelity.rich_container_lines(
                child, out, render_block=render_block, emit_image=emit_image,
                skip={summary} if summary is not None else None)
        elif name == 'blockquote' and _has_block_content(child):
            out.append('\n[BLOCKQUOTE]')
            fidelity.rich_container_lines(child, out, render_block=render_block,
                                          emit_image=emit_image)
        elif name == 'div' and ({'sphinx-tabs', 'sd-tab-set'} & set(child.get('class') or [])):
            _tabs_block(child, out, fidelity)
        elif name == 'div' and any(c in cls for c in ('admonition', 'note', 'warning', 'important', 'tip')):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            fidelity.admonition_content_lines(
                child, out, render_block, emit_image)
        elif name == 'div' and 'math' in cls:
            t = fidelity.render_inline(child)
            if t:
                out.append('\n' + t)
        elif name == 'div':
            if _has_block_content(child):
                render(child, out, fidelity)
            else:
                t = fidelity.paragraph_text(child)
                if t:
                    out.append('\n' + t)
        elif name == 'section':
            render(child, out, fidelity)
        elif name in ('script', 'style', 'noscript'):
            continue
        elif name == 'a':
            text = fidelity.render_inline(child)
            if text:
                out.append('\n' + text)
        elif name in _BLOCK_TAGS:
            if _has_rich_content(child):
                raise ValueError('未识别的富容器 <%s> id=%r L%s，可能丢失结构'
                                 % (name, child.get('id'), child.sourceline))
            # 未知块级容器的文字内容按行内语义序列化（代码/公式保真）
            t = fidelity.render_inline(child)
            if t:
                out.append('\n[' + name.upper() + '] ' + t)
            else:
                render(child, out, fidelity)
        else:
            if _has_rich_content(child):
                raise ValueError('未识别的富容器 <%s> id=%r L%s，可能丢失结构'
                                 % (name, child.get('id'), child.sourceline))
            elif _has_block_content(child):
                text = fidelity.render_inline(child)
                if text:
                    out.append('\n[' + name.upper() + '] ' + text)
            else:
                render(child, out, fidelity)


def _publish_new_group(items, validator):
    """显式展开只发布全新的文件；已有目标即拒绝，不改动来源引用。"""
    staged, published = {}, []
    try:
        for target, text in items:
            if os.path.lexists(target):
                raise ValueError('显式展开拒绝覆盖已有输出: %s' % target)
            fd, candidate = tempfile.mkstemp(prefix='.api-grid-', dir=os.path.dirname(target) or '.')
            staged[target] = candidate
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        validator(staged)
        # link 的排他创建防止预检后出现目标时被替换；每个成员同目录暂存。
        for target, _ in items:
            os.link(staged[target], target)
            published.append(target)
    except BaseException:
        for target in reversed(published):
            os.unlink(target)
        raise
    finally:
        for candidate in staged.values():
            if os.path.lexists(candidate):
                os.unlink(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html_path')
    parser.add_argument('out_path')
    parser.add_argument('--expand-tables', choices=['grid'])
    parser.add_argument('--table-conversions-output')
    args = parser.parse_args()
    if bool(args.expand_tables) != bool(args.table_conversions_output):
        parser.error('--expand-tables grid 与 --table-conversions-output 必须配对')
    html_path, out_path = args.html_path, args.out_path

    fidelity = HtmlFidelity(
        unknown_footnote='[^?]',
        snapshot_dir=os.path.dirname(os.path.abspath(html_path)))
    fidelity.expand_tables = bool(args.expand_tables)
    raw = open(html_path, encoding='utf-8', newline='').read()
    soup = fidelity.parse(raw)
    root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        sys.exit('no <article>/<main>/<body> found')

    out = []
    render(root, out, fidelity)
    md_text = '\n'.join(out).strip() + '\n'
    conversions = ({'version': 2, 'snapshot_sha256': file_sha256(html_path),
                    'tables': fidelity.table_conversions} if args.expand_tables else None)
    diffs = reconcile_html_to_markdown(raw, md_text, 'api',
                                       html_label=html_path,
                                       md_label=out_path, table_conversions=conversions)
    diffs += anchor_diffs(raw, md_text)
    if diffs:
        sys.exit('源对账失败: %s 与 %s 不一致，已阻断分派\n%s' % (
            html_path, out_path,
            '\n'.join('  - ' + d for d in diffs)))
    if args.expand_tables:
        map_path = args.table_conversions_output
        display_map = os.path.splitext(out_path)[0] + '.images_display.json' if fidelity.image_display else None
        items = [(map_path, json.dumps(conversions, ensure_ascii=False, indent=2))]
        if display_map:
            items.append((display_map, json.dumps(fidelity.display_map_payload(out_path, html_path),
                                                 ensure_ascii=False, indent=2)))
        items.append((out_path, md_text))
        targets = [os.path.realpath(path) for path, _ in items]
        if len(set(targets)) != len(targets):
            sys.exit('配套输出路径重复，拒绝发布')
        def validate(staged):
            candidate = open(staged[out_path], encoding='utf-8', newline='').read()
            mapping = json.load(open(staged[map_path], encoding='utf-8'))
            current_raw = open(html_path, encoding='utf-8', newline='').read()
            problems = reconcile_html_to_markdown(
                current_raw, candidate, 'api',
                table_conversions=mapping)
            problems += anchor_diffs(current_raw,candidate)
            if problems:
                raise ValueError('候选独立重读失败: ' + '；'.join(problems))
            if display_map:
                from _image_binding import load_parse_map
                if load_parse_map(staged[display_map]) != fidelity.display_map_payload(out_path, html_path):
                    raise ValueError('候选图片映射重读不符')
        _publish_new_group(items, validate)
    else:
        open(out_path, 'w', encoding='utf-8').write(md_text)
        display_map = fidelity.write_display_map(out_path, html_path)
    warn_if_temp_output([out_path, display_map])
    determined = sum(1 for e in fidelity.image_display if 'value' in e)
    print('%s: %d blocks, %d chars -> %s%s' % (
        html_path, len(out), sum(len(x) for x in out), out_path,
        '（显示尺寸 %d 项，未确定 %d 项 -> %s）' % (
            determined, len(fidelity.image_display) - determined, display_map)
        if display_map else ''))


if __name__ == '__main__':
    main()
