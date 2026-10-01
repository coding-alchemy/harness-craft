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
import os
import re
import sys

from bs4 import Comment, Tag

from _html_fidelity import HtmlFidelity, warn_if_temp_output
from _source_reconcile import reconcile_html_to_markdown


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


def _image_block(tag, out, fidelity):
    if _is_dark_only(tag):
        return
    src = _image_src(tag)
    alt = tag.get('alt', '')
    if src:
        out.append('\n![%s](%s)' % (alt, src))
        fidelity.note_image(tag, src)


def _tabs_block(tag, out, fidelity):
    """处理 sphinx-tabs：为每个 tab 输出标签行，再递归渲染面板内容。"""
    tablist = tag.find(attrs={'role': 'tablist'})
    if tablist:
        buttons = tablist.find_all(attrs={'role': 'tab'})
    else:
        buttons = tag.find_all(class_='sphinx-tabs-tab')
    panels = tag.find_all(attrs={'role': 'tabpanel'})
    if not panels:
        panels = tag.find_all(class_='sphinx-tabs-panel')
    if buttons and panels and len(buttons) == len(panels):
        for btn, panel in zip(buttons, panels):
            label = btn.get_text(strip=True)
            if label:
                out.append('\n**[Tab: %s]**' % label)
            render(panel, out, fidelity)
    else:
        # 未知结构：当成普通 div 递归，避免静默丢弃
        render(tag, out, fidelity)


def render(node, out, fidelity):
    _render_children(node, out, fidelity)


def _render_children(node, out, fidelity):
    render_block = lambda tag, o: _render_children(tag, o, fidelity)
    emit_image = lambda tag, o: _image_block(tag, o, fidelity)
    for child in node.children:
        fenced = fidelity.fenced_pre(child)
        if fenced is not None:
            out.append(fenced)
            continue
        if isinstance(child, str):
            continue
        if not isinstance(child, Tag):
            continue
        name, cls = child.name, ' '.join(child.get('class') or [])
        if name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            out.append('\n' + '#' * int(name[1]) + ' '
                       + fidelity.clean_heading(fidelity.heading_text(child)))
        elif name == 'p':
            t = fidelity.render_inline(child)
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
        elif name == 'aside' and fidelity.is_footnote_aside(child):
            out.extend(fidelity.footnote_aside_lines(child))
        elif name == 'details':
            summary = child.find('summary')
            label = fidelity.render_inline(summary) if summary else ''
            out.append('\n[DETAILS] %s' % label.strip())
            fidelity.rich_container_lines(
                child, out, render_block=render_block, emit_image=emit_image,
                skip={summary} if summary is not None else None)
        elif name == 'div' and 'sphinx-tabs' in cls:
            _tabs_block(child, out, fidelity)
        elif name == 'div' and any(c in cls for c in ('admonition', 'note', 'warning', 'important', 'tip')):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            fidelity.admonition_content_lines(
                child, out, render_block, emit_image)
        elif name == 'div' and 'math' in cls:
            t = re.sub(r'\s*\n\s*', ' ', child.get_text()).strip()
            if t:
                out.append('\n$' + t + '$')
        elif name == 'div':
            if _has_block_content(child):
                render(child, out, fidelity)
            else:
                t = fidelity.render_inline(child)
                if t:
                    out.append('\n' + t)
        elif name == 'section':
            render(child, out, fidelity)
        elif name in ('script', 'style', 'noscript'):
            continue
        elif name in _BLOCK_TAGS:
            # 未知块级容器的文字内容按行内语义序列化（代码/公式保真）
            t = fidelity.render_inline(child)
            if t:
                out.append('\n[' + name.upper() + '] ' + t)
            else:
                render(child, out, fidelity)
        else:
            if _has_block_content(child):
                t = fidelity.render_inline(child)
                if t:
                    out.append('\n[' + name.upper() + '] ' + t)
            else:
                render(child, out, fidelity)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    html_path, out_path = sys.argv[1], sys.argv[2]

    fidelity = HtmlFidelity(
        unknown_footnote='[^?]',
        snapshot_dir=os.path.dirname(os.path.abspath(html_path)))
    raw = open(html_path, encoding='utf-8').read()
    soup = fidelity.parse(raw)
    root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        sys.exit('no <article>/<main>/<body> found')

    out = []
    render(root, out, fidelity)
    md_text = '\n'.join(out).strip() + '\n'
    diffs = reconcile_html_to_markdown(raw, md_text, 'api',
                                       html_label=html_path,
                                       md_label=out_path)
    if diffs:
        sys.exit('源对账失败: %s 与 %s 不一致，已阻断分派\n%s' % (
            html_path, out_path,
            '\n'.join('  - ' + d for d in diffs)))
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
