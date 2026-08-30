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
import sys
import re
from bs4 import Tag

from _html_fidelity import HtmlFidelity


# 按 HTML5 惯例视为块级、但本脚本未显式展开的元素；遇到时输出 [TAGNAME]。
_BLOCK_TAGS = {
    'address', 'article', 'aside', 'details', 'dialog',
    'fieldset', 'figcaption', 'footer', 'form', 'header',
    'hgroup', 'main', 'nav', 'section', 'summary',
}

def clean_caption(txt):
    return re.sub(r'\s+', ' ', txt.replace('¶', '').replace('\uf0c1', '').strip())


def _image_block(tag, out):
    src = tag.get('src', '')
    if src:
        out.append('\n[IMG: images/%s]' % src.rsplit('/', 1)[-1])


def _figure_block(tag, out):
    img = tag.find('img')
    if img:
        src = img.get('src', '')
        if src:
            out.append('\n[IMG: images/%s]' % src.rsplit('/', 1)[-1])
    cap = tag.find('figcaption')
    if cap:
        out.append('[FIGURE] ' + clean_caption(cap.get_text(' ', strip=True)))


def _emit_nested_blocks(el, out, fidelity, indent='  '):
    """提取 li/dd/blockquote 等嵌套容器内的 figure/pre/img，保持源顺序。

    注意：<pre> 在解析前已被替换为占位注释，因此必须同时处理 Comment 占位。
    """
    def walk(node):
        for child in node.children:
            fenced = fidelity.fenced_pre(child)
            if fenced is not None:
                out.append(fenced.replace('\n```', '\n%s```' % indent))
                continue
            if isinstance(child, str):
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == 'figure':
                img = child.find('img')
                if img:
                    src = img.get('src', '')
                    if src:
                        out.append('\n%s[IMG: images/%s]' % (indent, src.rsplit('/', 1)[-1]))
                cap = child.find('figcaption')
                if cap:
                    out.append('%s[FIGURE] %s' % (indent, clean_caption(cap.get_text(' ', strip=True))))
                # figure 内部已由本分支整体处理，不再递归
                continue
            if child.name == 'img':
                src = child.get('src', '')
                if src:
                    out.append('\n%s[IMG: images/%s]' % (indent, src.rsplit('/', 1)[-1]))
                continue
            if child.name == 'pre':
                text = child.get_text()
                out.append('\n%s```\n%s\n%s```' % (indent, text.rstrip('\n'), indent))
                continue
            walk(child)

    walk(el)


def _definition_list(tag, out, fidelity):
    dts = tag.find_all('dt', recursive=False)
    is_fn = dts and all(
        re.fullmatch(r'\[\d+\]|\(\d+\)|\d+', d.get_text(strip=True))
        for d in dts
    )
    out.append('\n[FOOTNOTE-LIST]' if is_fn else '\n[DEF-LIST]')
    for dt, dd in zip(tag.find_all('dt'), tag.find_all('dd')):
        dt_text = dt.get_text(' ', strip=True)
        dd_text = fidelity.render_inline(dd)
        if is_fn:
            out.append('  [%s] %s' % (dt_text, dd_text))
        else:
            out.append('  **%s** %s' % (dt_text, dd_text))
            _emit_nested_blocks(dd, out, fidelity, indent='  ')


def render(node, out, fidelity):
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
            out.append('\n' + '#' * int(name[1]) + ' ' + fidelity.clean_heading(child.get_text(' ', strip=True)))
        elif name == 'p':
            t = fidelity.render_inline(child)
            if t:
                out.append('\n' + t)
        elif name in ('ul', 'ol'):
            for li in child.find_all('li', recursive=False):
                out.append('  - ' + fidelity.render_inline(li))
                _emit_nested_blocks(li, out, fidelity, indent='  ')
        elif name == 'pre':
            text = child.get_text()
            out.append('\n```\n' + text.rstrip('\n') + '\n```')
        elif name == 'dl':
            _definition_list(child, out, fidelity)
        elif name == 'table':
            out.extend(fidelity.table_block(child))
        elif name == 'img':
            _image_block(child, out)
        elif name == 'figure':
            _figure_block(child, out)
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
            for p in child.find_all('p'):
                if 'admonition-title' in ' '.join(p.get('class') or []):
                    continue
                out.append('> ' + fidelity.render_inline(p))
        elif name == 'div':
            if child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                             'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure', 'blockquote'], recursive=True):
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
            if child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'h1', 'h2', 'h3',
                           'h4', 'h5', 'h6', 'figure', 'blockquote'], recursive=True):
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

    fidelity = HtmlFidelity(unknown_footnote='[^?]')
    soup = fidelity.parse(open(html_path, encoding='utf-8').read())
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
    open(out_path, 'w', encoding='utf-8').write('\n'.join(out).strip() + '\n')
    print('%s: %d blocks, %d chars -> %s' % (
        section_id or root.name, len(out), sum(len(x) for x in out), out_path))


if __name__ == '__main__':
    main()
