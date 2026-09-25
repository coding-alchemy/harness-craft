#!/usr/bin/env python3
"""单页参考手册变体（数学密集 + 深层嵌套）HTML → Markdown 提取器。

用法：
    python3 parse_reference_html.py <index.html> [section_id] <out.md>

section_id 不提供时解析 <article> / <main> / <body>。

输出标记约定（供校验脚本消费）：
    $...$                         行内公式
    $$...$$                       块级公式
    ``` 围栏                      代码块
    [TABLE] + 逐行 ` | `          表格（不合并复杂表头 / rowspan 续行）
    [DEF-LIST] / [FOOTNOTE-LIST]  定义列表 / 脚注列表
    [IMG: images/<basename>]      图片占位
    [FIGURE] caption              图题占位
    [TAGNAME] text                未显式处理的块级元素（不得静默丢弃）
"""
import os
import sys
import re
from bs4 import Tag

from _html_fidelity import (HtmlFidelity, contains_block_content,
                            warn_if_temp_output)
from _source_reconcile import reconcile_html_to_markdown


# 按 HTML5 惯例视为块级、但本脚本未显式展开的元素；遇到时输出 [TAGNAME]。
_BLOCK_TAGS = {
    'address', 'article', 'aside', 'details', 'dialog',
    'fieldset', 'figcaption', 'footer', 'form', 'header',
    'hgroup', 'main', 'nav', 'section', 'summary',
}

def clean_caption(txt):
    return re.sub(r'\s+', ' ', txt.replace('¶', '').replace('\uf0c1', '').strip())


def _image_block(tag, out, fidelity):
    src = tag.get('src', '')
    if src:
        reference = 'images/%s' % src.rsplit('/', 1)[-1]
        out.append('\n[IMG: %s]' % reference)
        fidelity.note_image(tag, reference)


def _figure_block(tag, out, fidelity):
    img = tag.find('img')
    if img:
        src = img.get('src', '')
        if src:
            reference = 'images/%s' % src.rsplit('/', 1)[-1]
            out.append('\n[IMG: %s]' % reference)
            fidelity.note_image(img, reference)
    cap = tag.find('figcaption')
    if cap:
        # 图题按行内语义序列化（去 headerlink、行内代码保真）
        out.append('[FIGURE] ' + clean_caption(fidelity.heading_text(cap)))


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
            out.extend(fidelity.definition_list(child, render_block,
                                               emit_image))
        elif name == 'table':
            out.extend(fidelity.table_block(child))
        elif name == 'img':
            _image_block(child, out, fidelity)
        elif name == 'figure':
            _figure_block(child, out, fidelity)
        elif name == 'aside' and fidelity.is_footnote_aside(child):
            out.extend(fidelity.footnote_aside_lines(child))
        elif name == 'details':
            summary = child.find('summary')
            label = fidelity.render_inline(summary) if summary else ''
            out.append('\n[DETAILS] %s' % label.strip())
            fidelity.rich_container_lines(
                child, out, render_block=render_block, emit_image=emit_image,
                skip={summary} if summary is not None else None)
        elif name == 'blockquote':
            render(child, out, fidelity)
        elif name == 'div' and 'math' in cls:
            t = child.get_text(' ', strip=True)
            if t:
                out.append('\n$$\n' + t + '\n$$')
        elif name == 'div' and any(c in cls for c in ('admonition', 'note', 'warning', 'important', 'tip')):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            fidelity.admonition_content_lines(
                child, out, render_block, emit_image)
        elif name == 'div':
            if contains_block_content(
                    child, ['p', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                            'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure',
                            'blockquote']):
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
            t = child.get_text(' ', strip=True)
            if t:
                out.append('\n[' + name.upper() + '] ' + t)
            else:
                render(child, out, fidelity)
        else:
            # 未知元素：若内部含块级结构则显式占位；否则当成行内容器递归
            if contains_block_content(
                    child, ['p', 'ul', 'ol', 'table', 'dl',
                            'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure',
                            'blockquote']):
                t = child.get_text(' ', strip=True)
                if t:
                    out.append('\n[' + name.upper() + '] ' + t)
            else:
                render(child, out, fidelity)


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        sys.exit(__doc__)
    html_path = sys.argv[1]
    if len(sys.argv) == 4:
        section_id, out_path = sys.argv[2], sys.argv[3]
    else:
        section_id, out_path = None, sys.argv[2]

    fidelity = HtmlFidelity(
        unknown_footnote='[^?]',
        snapshot_dir=os.path.dirname(os.path.abspath(html_path)))
    raw = open(html_path, encoding='utf-8').read()
    soup = fidelity.parse(raw)
    if section_id:
        root = soup.find(id=section_id)
        if root is None:
            sys.exit('section id not found: %s' % section_id)
    else:
        root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        sys.exit('no <article>/<main>/<body> found')

    out = []
    render(root, out, fidelity)
    md_text = '\n'.join(out).strip() + '\n'
    diffs = reconcile_html_to_markdown(raw, md_text, 'reference',
                                       section_id=section_id,
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
        section_id or root.name, len(out), sum(len(x) for x in out), out_path,
        '（显示尺寸 %d 项，未确定 %d 项 -> %s）' % (
            determined, len(fidelity.image_display) - determined, display_map)
        if display_map else ''))


if __name__ == '__main__':
    main()
