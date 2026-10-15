#!/usr/bin/env python3
"""单页参考手册变体（数学密集 + 深层嵌套）HTML → Markdown 提取器。

用法：
    python3 parse_reference_html.py <index.html> [section_id] <out.md>
        [--source-adaptation <依据.json> --adaptation-output <候选依据.json>]

section_id 不提供时解析 <article> / <main> / <body>。

--source-adaptation 显式声明当前输入为已确认身份的 LaTeXML 快照来源
（依据文件 version:1 / format:latexml，含 paper_identity 与裁决；旧
correspondences 不代替本次重建）。提供时：身份与快照摘要按实际输入独立
核对 → 原节点适配生成候选 Markdown 与候选依据（互不覆盖）→ 独立原始
快照对账通过后才整组原子写出 out.md、候选依据与派生的显示尺寸映射
（三个产物路径在适配前一并计算并纳入同一组冲突检查；先预检输出父目录，
目录内临时文件整组替换——已存在目标先备份、失败按序恢复；任一失败旧
产物字节不动）；失败保
留旧源/旧依据。候选含未解决
项（无 TeX 等）即定位并阻断分派。未提供时保持原参考手册行为。

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
import tempfile
from bs4 import Tag

from _html_fidelity import (HtmlFidelity, contains_block_content,
                            warn_if_temp_output)
from _source_reconcile import reconcile_html_to_markdown


def _select_root(soup, section_id):
    if section_id:
        root = soup.find(id=section_id)
        if root is None:
            sys.exit('section id not found: %s' % section_id)
        return root
    root = soup.find('article') or soup.find('main') or soup.find('body')
    if root is None:
        sys.exit('no <article>/<main>/<body> found')
    return root


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
                t = fidelity.paragraph_text(child)
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


def _publish_group(items):
    """整组原子发布全部产物（候选依据、Markdown、尺寸映射）：先预检各
    输出的父目录可写，再各自在目标目录内写临时文件（tempfile.mkstemp），
    已存在的目标先改名备份（目录目标不备份，替换时如实失败），然后按传入
    顺序逐个 os.replace。预检或暂存失败时旧产物字节不动；替换阶段任一
    失败时清除未替换暂存文件、按序恢复备份、并撤销本轮新创建（无备份）
    而已就位的成员，恢复或撤销失败如实列入人工核对诊断、非零退出；全部
    成功才删除备份。依据先就位、Markdown 后至——崩溃窗口内旧 Markdown
    配新依据的组合会被拆包/恢复/合并准入的完整对账拒识，方向安全。
    """
    staged = []
    backups = []
    placed = []
    try:
        for target, _text in items:
            parent = os.path.dirname(target) or os.curdir
            if not os.path.isdir(parent):
                raise OSError('输出父目录不存在: %s' % parent)
            if not os.access(parent, os.W_OK):
                raise OSError('输出父目录不可写: %s' % parent)
        for target, text in items:
            fd, tmp = tempfile.mkstemp(prefix='.publish_', dir=os.path.dirname(
                target) or os.curdir)
            staged.append((tmp, target))
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(text)
        for target, _text in items:
            if os.path.lexists(target) and not os.path.isdir(target):
                bak_fd, bak = tempfile.mkstemp(
                    prefix='.publish_bak_',
                    dir=os.path.dirname(target) or os.curdir)
                os.close(bak_fd)
                os.unlink(bak)
                os.replace(target, bak)
                backups.append((bak, target))
        for tmp, target in list(staged):
            os.replace(tmp, target)
            staged.remove((tmp, target))
            placed.append(target)
    except OSError as exc:
        for tmp, _target in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        restored, unrestored = [], []
        for bak, target in reversed(backups):
            try:
                os.replace(bak, target)
                restored.append(target)
            except OSError:
                unrestored.append(target)
        # 本轮新创建（无旧文件、无备份）而已就位的成员一并撤销，
        # 闭合同组发布"失败保旧"合同（第三轮 F1）
        backed = set(target for _bak, target in backups)
        unremoved = []
        for target in placed:
            if target in backed:
                continue
            try:
                os.unlink(target)
            except OSError:
                unremoved.append(target)
        problems = unrestored + unremoved
        if problems:
            sys.exit('整组发布失败，旧产物恢复或新产物撤销失败（需人工核对 '
                     '%s）: %s' % (', '.join(problems), exc))
        removed_new = [t for t in placed if t not in backed]
        if restored and removed_new:
            sys.exit('整组发布失败，旧产物已按序恢复、本轮新产物已撤销'
                     '（保留旧源/旧依据）: %s' % exc)
        if restored:
            sys.exit('整组发布失败，旧产物已按序恢复（保留旧源/旧依据）: %s'
                     % exc)
        if removed_new:
            sys.exit('整组发布失败，本轮新产物已撤销（无旧产物被改动）: %s'
                     % exc)
        sys.exit('整组发布失败，旧产物未改动（保留旧源/旧依据）: %s' % exc)
    for bak, _target in backups:
        os.unlink(bak)


def _publish_pair(adapt_path, adapt_text, md_path, md_text):
    """整组原子发布候选依据与 Markdown（先依据后 Markdown），
    语义同 _publish_group 的两产物组。"""
    _publish_group(((adapt_path, adapt_text), (md_path, md_text)))


def _display_map_text(fidelity, out_path, html_path):
    """把显示尺寸映射写入目标目录暂存文件并回读文本：派生路径由
    write_display_map 按暂存 Markdown 路径推导，'markdown' 字段回填为
    最终产物名（与直接写目标一致），文本交由 _publish_group 原子发布。"""
    import json

    parent = os.path.dirname(out_path) or os.curdir
    tmp_md = staged = None
    try:
        fd, tmp_md = tempfile.mkstemp(prefix='.displaymap_', suffix='.md',
                                      dir=parent)
        os.close(fd)
        staged = fidelity.write_display_map(tmp_md, html_path)
        with open(staged, encoding='utf-8') as handle:
            payload = json.load(handle)
    except OSError as exc:
        sys.exit('尺寸映射暂存失败，旧产物未改动（保留旧源/旧依据）: %s' % exc)
    finally:
        for path in (tmp_md, staged):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    payload['markdown'] = os.path.basename(out_path)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _adapted_main(html_path, section_id, out_path, args):
    """LaTeXML 来源分支：身份/摘要核对 → 适配候选 → 独立对账 → 通过才写出。"""
    import json

    import _latexml_source as latexml
    from _source_reconcile import reconcile_latexml_to_markdown

    in_path = os.path.realpath(args.source_adaptation)
    out_abs = os.path.realpath(out_path)
    adapt_out = os.path.realpath(args.adaptation_output)
    html_abs = os.path.realpath(html_path)
    display_out = os.path.splitext(out_abs)[0] + '.images_display.json'
    if adapt_out == in_path:
        sys.exit('候选依据输出与输入是同一文件，禁止就地覆盖: %s'
                 % args.adaptation_output)
    if adapt_out == out_abs:
        sys.exit('候选依据输出与 Markdown 输出是同一文件: %s'
                 % args.adaptation_output)
    if adapt_out == display_out:
        sys.exit('候选依据输出与尺寸映射输出是同一文件: %s'
                 % args.adaptation_output)
    if out_abs == in_path:
        sys.exit('Markdown 输出与只读依据输入是同一文件，禁止就地覆盖: %s'
                 % out_path)
    if out_abs == html_abs:
        sys.exit('Markdown 输出与原始 HTML 快照是同一文件，禁止就地覆盖: %s'
                 % out_path)
    if adapt_out == html_abs:
        sys.exit('候选依据输出与原始 HTML 快照是同一文件，禁止就地覆盖: %s'
                 % args.adaptation_output)
    if display_out == in_path:
        sys.exit('尺寸映射输出与只读依据输入是同一文件，禁止就地覆盖: %s'
                 % display_out)
    if display_out == html_abs:
        sys.exit('尺寸映射输出与原始 HTML 快照是同一文件，禁止就地覆盖: %s'
                 % display_out)
    if display_out == out_abs:
        sys.exit('尺寸映射输出与 Markdown 输出是同一文件: %s' % display_out)

    try:
        payload = latexml.load_adaptation(in_path)
    except ValueError as exc:
        sys.exit(str(exc))

    raw = open(html_path, encoding='utf-8').read()
    problems = latexml.validate_adaptation(
        payload, raw_html=raw, snapshot_path=html_path)
    if problems:
        sys.exit('来源身份/摘要核对失败，已阻断分派:\n%s'
                 % '\n'.join('  - %s' % p for p in problems))

    table_conversions = payload.get('table_conversions')
    resource_substitutions = payload.get('resource_substitutions') or []
    if resource_substitutions:
        problems = latexml.validate_resource_substitutions(
            payload, os.path.dirname(os.path.abspath(html_path)),
            (payload.get('paper_identity') or {}).get('version'))
        if problems:
            sys.exit('资源替换核对失败，已阻断分派:\n%s'
                     % '\n'.join('  - %s' % p for p in problems))
    md_text, correspondences, unresolved, fidelity, adapter = \
        latexml.adapt_latexml_snapshot(
            raw, section_id, payload.get('decisions') or [],
            os.path.dirname(os.path.abspath(html_path)),
            table_conversions=table_conversions,
            resource_substitutions=resource_substitutions)

    candidate = latexml.build_candidate_adaptation(
        payload, raw, html_path, correspondences, unresolved,
        groups=getattr(adapter, 'groups', None),
        decision_results=getattr(adapter, 'decision_results', None),
        table_conversions=table_conversions, selection=section_id,
        md_text=md_text)
    candidate_text = json.dumps(candidate, ensure_ascii=False, indent=1)

    diffs = reconcile_latexml_to_markdown(
        raw, md_text, section_id, candidate,
        html_label=html_path, md_label=out_path)
    if diffs:
        sys.exit('LaTeXML 源对账失败: %s 与 %s 不一致，已阻断分派（保留旧源/'
                 '旧依据）\n%s' % (html_path, out_path,
                                '\n'.join('  - ' + d for d in diffs)))
    if unresolved:
        sys.exit('候选含未解决项，阻断分派（不猜写、不丢弃；主 Agent 回源补齐'
                 '依据后重新解析）:\n%s'
                 % '\n'.join('  - %s: %s' % (u.get('node'), u.get('reason'))
                             for u in unresolved))

    items = [(adapt_out, candidate_text), (out_abs, md_text)]
    display_map = None
    if fidelity.image_display:
        items.append((display_out, _display_map_text(fidelity, out_abs,
                                                     html_path)))
        display_map = display_out
    _publish_group(items)
    warn_if_temp_output([out_path, display_map, adapt_out])
    determined = sum(1 for e in fidelity.image_display if 'value' in e)
    print('%s: LaTeXML 来源适配 %d 对应 -> %s%s（候选依据 %s）'
          % (section_id or 'root', len(correspondences), out_path,
             '（显示尺寸 %d 项，未确定 %d 项 -> %s）' % (
                 determined, len(fidelity.image_display) - determined,
                 display_map) if display_map else '', adapt_out))


def main():
    argv = sys.argv[1:]
    source_adaptation = None
    adaptation_output = None
    rest = []
    index = 0
    while index < len(argv):
        if argv[index] == '--source-adaptation' and index + 1 < len(argv):
            source_adaptation = argv[index + 1]
            index += 2
        elif argv[index] == '--adaptation-output' and index + 1 < len(argv):
            adaptation_output = argv[index + 1]
            index += 2
        else:
            rest.append(argv[index])
            index += 1
    if len(rest) < 2 or len(rest) > 3:
        sys.exit(__doc__)
    html_path = rest[0]
    if len(rest) == 3:
        section_id, out_path = rest[1], rest[2]
    else:
        section_id, out_path = None, rest[1]

    if source_adaptation:
        class _Args(object):
            pass
        args = _Args()
        args.source_adaptation = source_adaptation
        args.adaptation_output = adaptation_output
        _adapted_main(html_path, section_id, out_path, args)
        return

    fidelity = HtmlFidelity(
        unknown_footnote='[^?]',
        snapshot_dir=os.path.dirname(os.path.abspath(html_path)))
    raw = open(html_path, encoding='utf-8').read()
    soup = fidelity.parse(raw)
    root = _select_root(soup, section_id)

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
