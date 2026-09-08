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

from _html_fidelity import HtmlFidelity


# 按 HTML5 惯例视为块级、但本脚本未显式展开的元素；遇到时输出 [TAGNAME]。
_BLOCK_TAGS = {
    'address', 'article', 'aside', 'blockquote', 'details', 'dialog',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'header',
    'hgroup', 'main', 'nav', 'section', 'summary',
}


def _image_block(tag, out):
    alt = tag.get('alt', '')
    src = tag.get('src', '')
    if src:
        out.append('\n![%s](%s)' % (alt, src))


def _math_block(tag, out):
    """块级公式 div.math / span.math display。"""
    t = tag.get_text(' ', strip=True)
    if t:
        out.append('\n$$' + t + '$$')


def render(node, out, fidelity):
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
            out.append('\n' + '#' * int(name[1]) + ' ' + fidelity.clean_heading(child.get_text(' ', strip=True)))
        elif name == 'p':
            t = fidelity.render_inline(child)
            if t:
                out.append('\n' + t)
        elif name in ('ul', 'ol'):
            for li in child.find_all('li', recursive=False):
                out.append('  - ' + fidelity.render_inline(li))
        elif name == 'pre':
            text = child.get_text()
            out.append('\n```\n' + text.rstrip('\n') + '\n```')
        elif name == 'dl':
            out.extend(fidelity.definition_list(child))
        elif name == 'table':
            out.extend(fidelity.table_block(child))
        elif name == 'img':
            _image_block(child, out)
        elif name == 'figure':
            # 只提取图片；figcaption 等未处理子元素会被继续遍历并标记
            render(child, out, fidelity)
        elif name == 'div' and 'math' in cls:
            _math_block(child, out)
        elif name == 'div' and any(c in cls for c in ('admonition', 'note', 'warning', 'important', 'tip')):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            for p in child.find_all('p'):
                if 'admonition-title' in ' '.join(p.get('class') or []):
                    continue
                out.append('> ' + fidelity.render_inline(p))
        elif name == 'div':
            # 容器：含块级内容则递归，否则当成段落
            if child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'div', 'section', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'], recursive=True):
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
            # 未知元素：如果是块级结构则标记，否则按行内处理（若处于段落中）
            if child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'], recursive=True):
                t = child.get_text(' ', strip=True)
                if t:
                    out.append('\n[' + name.upper() + '] ' + t)
            else:
                # 可能是行内标记；忽略但递归到子块级元素
                render(child, out, fidelity)


def extract_one(html_path):
    fidelity = HtmlFidelity()
    soup = fidelity.parse(open(html_path, encoding='utf-8').read())
    root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        raise RuntimeError('no <article>/<main>/<body> found in %s' % html_path)

    out = []
    render(root, out, fidelity)
    return '\n'.join(out).strip() + '\n'


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
