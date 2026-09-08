#!/usr/bin/env python3
"""通用单页 HTML → 源 Markdown 提取器（Sphinx / 单页指南家族）。

用法：
    python3 parse_single_page_html.py <index.html> [section_id] <out.md>

section_id 为可选锚点；不提供时解析 <article> / <main> / <body>。

输出标记约定（供校验脚本消费）：
    [DEF-LIST] / [FOOTNOTE-LIST]  定义列表 / 脚注列表
    > **ADMONITION [Note]**       提示框
    [TABLE] + 逐行 ` | `          表格（首行后跟 --- 分隔行）
    ``` 围栏                      代码块
    $...$                         行内公式
    [^n]                          脚注引用
    ![alt](src)                   图片
    [TAGNAME] text                未显式处理的块级元素（不得静默丢弃）
"""
import sys
import re
from bs4 import Comment, Tag

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


def _has_protected_pre(tag):
    """`HtmlFidelity.parse()` 将 pre 替换成注释后仍识别其外层容器。"""
    return any(
        isinstance(node, Comment) and re.match(r'\s*__TECHDOC_PRE_\d+__\s*', node)
        for node in tag.descendants
    )


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
            # 图题是图的一部分，不能作为未知块级元素留下占位符。
            render(child, out, fidelity)
            caption = child.find('figcaption')
            if caption:
                text = fidelity.clean_heading(caption.get_text(' ', strip=True))
                if text:
                    out.append('\n**Figure: %s**' % text)
        elif name == 'figcaption':
            # 由父 figure 统一输出，避免重复或产生 [FIGCAPTION] 占位符。
            continue
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
            if (_has_protected_pre(child) or
                    child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'div', 'section', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'], recursive=True)):
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


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        sys.exit(__doc__)
    html_path = sys.argv[1]
    if len(sys.argv) == 4:
        section_id, out_path = sys.argv[2], sys.argv[3]
    else:
        section_id, out_path = None, sys.argv[2]

    fidelity = HtmlFidelity()
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
    print('%s: %d blocks, %d chars -> %s' % (section_id or root.name, len(out), sum(len(x) for x in out), out_path))


if __name__ == '__main__':
    main()
