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
import os
import sys
import re
from bs4 import Comment, Tag

from _html_fidelity import HtmlFidelity, _is_admonition_div, warn_if_temp_output
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


def _has_protected_pre(tag):
    """`HtmlFidelity.parse()` 将 pre 替换成注释后仍识别其外层容器。"""
    return any(
        isinstance(node, Comment) and re.match(r'\s*__TECHDOC_PRE_\d+__\s*', node)
        for node in tag.descendants
    )


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
        name = child.name
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
            # 图题是图的一部分，不能作为未知块级元素留下占位符。
            render(child, out, fidelity)
            caption = child.find('figcaption')
            if caption:
                # 图题按行内语义序列化（去 headerlink、行内代码保真）
                text = fidelity.clean_heading(fidelity.heading_text(caption))
                if text:
                    out.append('\n**Figure: %s**' % text)
        elif name == 'figcaption':
            # 由父 figure 统一输出，避免重复或产生 [FIGCAPTION] 占位符。
            continue
        elif name == 'aside' and fidelity.is_footnote_aside(child):
            out.extend(fidelity.footnote_aside_lines(child))
        elif name == 'details':
            summary = child.find('summary')
            label = fidelity.render_inline(summary) if summary else ''
            out.append('\n[DETAILS] %s' % label.strip())
            fidelity.rich_container_lines(
                child, out, render_block=render_block, emit_image=emit_image,
                skip={summary} if summary is not None else None)
        elif _is_admonition_div(child):
            title = child.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            out.append('\n> **ADMONITION [%s]**' % label)
            fidelity.admonition_content_lines(
                child, out, render_block, emit_image)
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
            # 含表格/列表/代码等结构或脚注容器的引用/aside 递归渲染保持
            # [TABLE] 等结构；纯文本的未识别块保持 [TAGNAME] 显式占位
            # （未识别块级结构必须显式暴露，供核验的残留标记检查）
            has_structure = child.find(
                ['table', 'ul', 'ol', 'pre', 'dl'], recursive=True)
            has_footnotes = child.find('aside', class_='footnote') \
                or child.find('aside', role='doc-footnote')
            if has_structure or has_footnotes or _has_protected_pre(child):
                render(child, out, fidelity)
            elif name == 'blockquote':
                # 引用正文保留行内代码/公式/链接语义（get_text 会拍平）
                t = fidelity.render_inline(child)
                if t:
                    out.append('\n[BLOCKQUOTE] ' + t)
                else:
                    render(child, out, fidelity)
            else:
                t = child.get_text(' ', strip=True)
                if t:
                    out.append('\n[' + name.upper() + '] ' + t)
                else:
                    render(child, out, fidelity)
        else:
            # 未知元素：含块级后代（含图片/受保护 pre）时递归渲染保持
            # 结构；纯行内内容按行内渲染（保留行内代码/公式/链接语义）
            if child.find(['p', 'pre', 'ul', 'ol', 'table', 'dl', 'img',
                           'h1', 'h2', 'h3', 'h4', 'h5', 'h6'],
                          recursive=True) or _has_protected_pre(child):
                render(child, out, fidelity)
            else:
                t = fidelity.render_inline(child)
                if t:
                    out.append('\n' + t)


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        sys.exit(__doc__)
    html_path = sys.argv[1]
    if len(sys.argv) == 4:
        section_id, out_path = sys.argv[2], sys.argv[3]
    else:
        section_id, out_path = None, sys.argv[2]

    fidelity = HtmlFidelity(
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
    diffs = reconcile_html_to_markdown(raw, md_text, 'single',
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
