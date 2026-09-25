#!/usr/bin/env python3
"""通用单页译文核对脚本。

用法：
    python3 verify_translation.py <译文.md> <源文.md> "官方标题1" "官方标题2" ...
        [--approved-extra-math <表达式>]... [--strong-token <token>]...
        [--image-map <map.json>] [--delivery-root <dir>] [--fragment]

官方标题只需编号 + 英文原题（如 "1. Introduction"），顺序传入。
脚本会兼容中文后缀 `（中文）` 与无后缀标题。
--approved-extra-math 按原文表达式逐条豁免获准译注公式（可重复；不掩盖源公式遗漏）。
--image-map 按出现顺序提供来源身份 sha256（原始快照独立建立）；未提供映射时
改由可靠的当前源资源推导身份（源引用须可解析为源文件旁的真实文件），两者都
不可用而译文含图时不判定完整通过。
--delivery-root 指定交付根（默认 Markdown 所在目录）；片段校验用 --fragment
（仅免除整篇 H1 要求，标题与图片出现次数仍与源对照，不提供豁免开关）。
"""
import sys
import re
import os
from collections import Counter

from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_strong_tokens,
    footnote_diffs,
    heading_entries,
    heading_title_matches,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
    link_targets,
    load_image_digests,
    residual_markers,
    scan_code_fences,
    scan_math_spans,
    source_occurrence_digests,
    strong_token_report,
)

# 必须由主 Agent 在最终译文中消除的解析占位标记
_RESIDUAL_MARKERS = [
    '[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:', 'ADMONITION',
    '¶', '\uf0c1',
]


def run_checks(doc_text, src_text, official=(), *, doc_dir, doc_label,
               src_label, image_digests=None, delivery_root=None,
               strong_tokens=(), approved_extra_math=(), fragment=False):
    """通用单页检查核心：接收候选文本与实际目标目录，返回 (失败数, 输出行)。

    doc_text 可来自工作区外临时候选（草稿预检）；doc_dir 必须是最终
    Markdown 目录——图片等资源一律按最终目标路径定位，不按候选临时
    路径定位。CLI 与预检共用本核心，输出行与既有 CLI 完全一致。
    """
    fail = 0
    lines = []
    doc = doc_text
    src = src_text
    doc_headings = heading_entries(doc)
    src_headings = heading_entries(src)
    h1s = [t for _, lvl, t in doc_headings if lvl == 1]

    # 1) H1 唯一性（完整文档约束；--fragment 片段只免除这一项，不豁免其余）
    if fragment:
        lines.append('H1 唯一性: 片段模式跳过（片段不要求 H1）')
    elif len(h1s) != 1:
        fail += 1
        lines.append('H1 数量: %d（应为 1）FAIL: %s' % (len(h1s), h1s[:3]))

    # 2) 标题核对：与源逐项对照层级与官方原题（后缀边界对照）。
    #    片段模式的源实参即片段源切片，同样逐项对照；只免除整篇 H1 要求。
    heading_diffs = compare_headings(src_headings, doc_headings,
                                     src_label, doc_label)
    if heading_diffs:
        for diff in heading_diffs:
            fail += 1
            lines.append('标题核对: %s FAIL' % diff)
    else:
        lines.append('标题核对: %d 条与源逐项一致（层级与官方原题） PASS'
                     % len(doc_headings))
    if official:
        # 官方标题清单作为独立基准（防源文件标题本身缺漏时盲从源文）
        got = [t for _, _, t in doc_headings]
        if len(got) == len(official) and all(
                heading_title_matches(e, g) for e, g in zip(official, got)):
            lines.append('标题: 与官方清单一致（含顺序） PASS')
        else:
            fail += 1
            lines.append('标题: 与官方清单不一致 FAIL（译文 %d 条 vs 官方 %d 条）'
                         % (len(got), len(official)))

    # 3) 残留解析标记
    for marker in residual_markers(doc, _RESIDUAL_MARKERS):
        fail += 1
        if marker in _RESIDUAL_MARKERS:
            lines.append('残留标记: %s FAIL' % marker)
        else:
            lines.append('残留块级占位符: %s FAIL' % marker)

    # 4) 脚注：译文内部配对 + 以源引用/定义关系为基准
    for num in sorted(set(re.findall(r'\[\^(\d+)\]', doc))):
        refs = len(re.findall(r'\[\^%s\](?!:)' % num, doc))
        defs = len(re.findall(r'^\[\^%s\]:' % num, doc, re.M))
        if not (refs and defs):
            fail += 1
            lines.append('脚注 [^%s]: 引用 %d / 定义 %d 不成对 FAIL' % (num, refs, defs))
    fn_diffs, fn_warns = footnote_diffs(src, doc, src_label, doc_label)
    for diff in fn_diffs:
        fail += 1
        lines.append('脚注核对: %s FAIL' % diff)
    for warn in fn_warns:
        lines.append('脚注核对: %s WARN' % warn)

    # 5) 强 token（项目显式指定；未配置时明示未检查）
    token_diffs, token_warns = strong_token_report(src, doc, strong_tokens,
                                                   src_label, doc_label)
    if token_diffs is not None:
        for diff in token_diffs:
            fail += 1
            lines.append('强 token: %s FAIL' % diff)
    for warn in token_warns:
        lines.append('强 token: %s WARN' % warn)

    # 6) 图片核验：源译出现次数对账（常开）+ 外链/绝对路径/cwd 伪匹配/
    #    伪图/缺图/身份不符均阻断。完整通过必须建立每次出现的来源身份：
    #    --image-map 或可靠的当前源资源二者有其一，否则明确失败
    src_image_count = image_occurrence_count(src)
    doc_image_count = len(image_references(doc))
    if doc_image_count < src_image_count:
        fail += 1
        lines.append('图片对账: 源出现 %d 次但译文仅 %d 次 FAIL（漏图）'
                     % (src_image_count, doc_image_count))
    elif doc_image_count > src_image_count:
        lines.append('图片对账: 译文出现 %d 次多于源 %d 次 WARN（回源确认是否译注图）'
                     % (doc_image_count, src_image_count))
    else:
        lines.append('图片对账: 源译出现次数一致（%d 次） PASS' % src_image_count)
    identity = image_digests
    identity_basis = '映射'
    if identity is None:
        identity = source_occurrence_digests(
            src, os.path.dirname(os.path.abspath(src_label)))
        identity_basis = '当前源资源'
    image_fails = image_occurrence_fails(
        doc, doc_dir, delivery_root, expected_digests=identity)
    if image_fails:
        for msg in image_fails:
            fail += 1
            lines.append('图片核验: %s FAIL' % msg)
    elif identity is not None:
        lines.append('图片核验: 离线引用、类型与来源身份（%s） PASS' % identity_basis)
    if identity is None and doc_image_count:
        fail += 1
        lines.append('图片核验: 来源身份未核验（无 --image-map 且源资源不可解析），'
                     '不判定完整通过 FAIL')

    # 7) 代码围栏配对与逐块内容核对
    doc_fences = scan_code_fences(doc)
    src_fences = scan_code_fences(src)
    code_fails = 0
    if not doc_fences.balanced:
        code_fails += 1
        lines.append('代码围栏不成对: 第 %d 行开启的代码块未闭合 FAIL'
                     % doc_fences.unclosed_line)
    if not src_fences.balanced:
        code_fails += 1
        lines.append('源文代码围栏不成对: 第 %d 行开启的代码块未闭合 FAIL'
                     % src_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    src_label, doc_label):
        code_fails += 1
        lines.append('代码逐块核对: %s FAIL' % diff)
    if code_fails:
        fail += code_fails
    elif doc_fences.blocks:
        lines.append('代码逐块核对: %d 块与源一致（开启行/语言/正文/关闭行） PASS'
                     % len(doc_fences.blocks))

    # 8) 公式逐项核对（类型/顺序/原表达式）与链接目标
    src_math = scan_math_spans(src)
    doc_math = scan_math_spans(doc)
    math_diffs, math_warns = compare_math_spans(
        src_math, doc_math, src_label, doc_label,
        approved_extra_exprs=approved_extra_math, doc_text=doc)
    for diff in math_diffs:
        fail += 1
        lines.append('公式逐项核对: %s FAIL' % diff)
    for warn in math_warns:
        lines.append('公式逐项核对: %s WARN' % warn)
    if not math_diffs and src_math:
        lines.append('公式逐项核对: %d 处（行内 %d/块级 %d）与源逐项一致 PASS'
                     % (len(doc_math),
                        sum(1 for s in doc_math if s.kind == 'inline'),
                        sum(1 for s in doc_math if s.kind == 'block')))
    if src:
        missing_links = Counter(link_targets(src)) - Counter(link_targets(doc))
        if missing_links:
            fail += 1
            lines.append('链接目标缺失: %s FAIL' % dict(missing_links))
        else:
            lines.append('链接目标: 源 %d / 译 %d PASS' %
                         (len(link_targets(src)), len(link_targets(doc))))

    # 9) 内容块覆盖率（信息性）
    if src:
        pairs = [
            ('代码围栏', len(src_fences.blocks), len(doc_fences.blocks)),
            ('提示框', src.count('ADMONITION'), doc.count('> **注（Note）**') + doc.count('> **警告（Warning）**') + doc.count('> **重要（Important）**')),
            ('公式', len(re.findall(r'\$[^$\n]+\$', src)), len(re.findall(r'\$[^$\n]+\$', doc))),
            ('列表项', len([l for l in src.splitlines() if l.startswith('  - ')]),
             len([l for l in doc.splitlines() if l.strip().startswith(('- ', '* '))])),
        ]
        for name, s, d in pairs:
            lines.append('覆盖率 %s: 源 %d / 译 %d（差值供人工判断）' % (name, s, d))

    lines.append('结果: %s' % ('ALL PASS' if fail == 0 else '%d 项 FAIL' % fail))
    return fail, lines


def parse_args(argv):
    """解析既有 CLI 参数，返回语义结构（本 CLI 的单一解释入口）。

    doc_path/src_path 为路径；official 为官方标题字面值；--strong-token、
    --approved-extra-math、--image-map、--delivery-root、--fragment 按真实
    语义拆出。路径与字面值不做任何改写，由调用方按自己的基点解释。
    """
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, strong_tokens = extract_strong_tokens(argv)
    argv, image_map, delivery_root = extract_image_options(argv)
    fragment = '--fragment' in argv
    argv = [a for a in argv if a != '--fragment']
    if len(argv) < 2:
        sys.exit(__doc__)
    return {
        'doc_path': argv[0],
        'src_path': argv[1],
        'official': list(argv[2:]),
        'strong_tokens': strong_tokens,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
        'fragment': fragment,
    }


def main():
    parsed = parse_args(sys.argv[1:])
    doc_path = parsed['doc_path']
    src_path = parsed['src_path']
    official = parsed['official']
    strong_tokens = parsed['strong_tokens']
    approved_extra_math = parsed['approved_extra_math']
    fragment = parsed['fragment']
    image_map = parsed['image_map']
    delivery_root = parsed['delivery_root']
    image_digests = load_image_digests(image_map) if image_map else None

    if not os.path.isfile(src_path):
        sys.exit('源文缺失或不可读: %s FAIL（输入不足，不得把缺源解释成跳过检查）'
                 % src_path)
    doc = open(doc_path, encoding='utf-8').read()
    src = open(src_path, encoding='utf-8').read()
    fail, lines = run_checks(
        doc, src, official,
        doc_dir=os.path.dirname(os.path.abspath(doc_path)),
        doc_label=doc_path, src_label=src_path,
        image_digests=image_digests, delivery_root=delivery_root,
        strong_tokens=strong_tokens,
        approved_extra_math=approved_extra_math, fragment=fragment)
    print('\n'.join(lines))
    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
