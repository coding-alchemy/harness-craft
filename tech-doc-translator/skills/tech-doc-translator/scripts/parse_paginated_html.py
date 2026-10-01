#!/usr/bin/env python3
"""分页 NVIDIA/Sphinx 风格 HTML → 源 Markdown 提取器。

用法：
    python3 parse_paginated_html.py page1.html page2.html ...

每页输出同名 .md 文件（如 page1.html → page1.md）。

输出标记约定（供校验脚本消费）：
    [DEF-LIST] / [FOOTNOTE-LIST]  定义列表 / 脚注列表
    > **ADMONITION [Note]**       提示框（最终译文中应替换为中文提示）
    [TABLE] + 逐行 ` | `          表格（首行后跟 --- 分隔行）
    ``` 围栏                      代码块
    $...$                         行内公式
    $$...$$                       块级公式
    [^n]                          脚注引用
    ![alt](src)                   图片
    [TAGNAME] text                未显式处理的块级元素（不得静默丢弃）
"""
import sys
import os
from bs4 import Tag

from _html_fidelity import (HtmlFidelity, contains_block_content,
                            warn_if_temp_output)
from _source_reconcile import reconcile_html_to_markdown


# 按 HTML5 惯例视为块级、但本脚本未显式展开的元素；遇到时输出 [TAGNAME]。
_BLOCK_TAGS = {
    'address', 'article', 'aside', 'blockquote', 'details', 'dialog',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'header',
    'hgroup', 'main', 'nav', 'section', 'summary',
}


def _image_block(tag, out, fidelity):
    alt = tag.get('alt', '')
    src = tag.get('src', '')
    if src:
        out.append('\n![%s](%s)' % (alt, src))
        fidelity.note_image(tag, src)


def _math_block(tag, out):
    """块级公式 div.math / span.math display。"""
    t = tag.get_text(' ', strip=True)
    if t:
        out.append('\n$$' + t + '$$')


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
            # 只收集已经在外的文本节点；列表等结构会自行处理
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
            # 只提取图片；figcaption 等未处理子元素会被继续遍历并标记
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
        elif name == 'div' and 'math' in cls:
            _math_block(child, out)
        elif name == 'div' and any(c in cls for c in ('admonition', 'note', 'warning', 'important', 'tip')):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            fidelity.admonition_content_lines(
                child, out, render_block, emit_image)
        elif name == 'div':
            # 容器：含块级内容（或受保护 pre 占位）则递归，否则当成段落
            if contains_block_content(
                    child, ['p', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                            'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
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
            # 未知元素：如果是块级结构则标记，否则按行内处理（若处于段落中）
            if contains_block_content(
                    child, ['p', 'ul', 'ol', 'table', 'dl',
                            'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                t = fidelity.render_inline(child)
                if t:
                    out.append('\n[' + name.upper() + '] ' + t)
            else:
                # 可能是行内标记；忽略但递归到子块级元素
                render(child, out, fidelity)


def extract_one(html_path):
    fidelity = HtmlFidelity(
        snapshot_dir=os.path.dirname(os.path.abspath(html_path)))
    raw = open(html_path, encoding='utf-8').read()
    soup = fidelity.parse(raw)
    root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        raise RuntimeError('no <article>/<main>/<body> found in %s' % html_path)

    out = []
    render(root, out, fidelity)
    text = '\n'.join(out).strip() + '\n'
    out_path = os.path.splitext(html_path)[0] + '.md'
    diffs = reconcile_html_to_markdown(raw, text, 'paginated',
                                       html_label=html_path,
                                       md_label=out_path)
    if diffs:
        raise SystemExit('源对账失败: %s 与 %s 不一致，已阻断分派\n%s' % (
            html_path, out_path, '\n'.join('  - ' + d for d in diffs)))
    display_map = fidelity.write_display_map(out_path, html_path)
    warn_if_temp_output([out_path, display_map])
    return text


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    for html_path in sys.argv[1:]:
        out_path = os.path.splitext(html_path)[0] + '.md'
        text = extract_one(html_path)
        open(out_path, 'w', encoding='utf-8').write(text)
        print('%s -> %s: %d chars' % (html_path, out_path, len(text)))


if __name__ == '__main__':
    main()
