#!/usr/bin/env python3
"""校验合并后的译文与多个源文文件。

用法：
    python3 verify_paginated_translation.py merged.md src1.md src2.md ...

检查项：
1. 标题集合与顺序（按节号前缀匹配，兼容 ASCII 括号中文后缀）
2. 合并后 H1 唯一性
3. 代码围栏配对
4. 图片存在性
5. CUDA 标志性语法（<<<、#include <）数量不减少
6. 残留解析标记（[TAGNAME]、[TABLE]、ADMONITION 等）

FAIL（硬失败）与覆盖率差值警告（信息性）分别报告。
"""
import sys
import re
import os

from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_strong_tokens,
    footnote_diffs,
    heading_entries,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
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


def check_headings(merged_path, src_paths):
    """按 (层级, 官方原题) 有序核对标题。

    本路线的已批准标题装配：章节头 H1 由头部文件提供（跳过逐项对照），
    各源页标题统一降一级（level_shift=+1）。
    """
    fails = 0
    msgs = []

    merged = heading_entries(open(merged_path, encoding='utf-8').read())
    h1_count = sum(1 for _, lvl, _ in merged if lvl == 1)

    if h1_count != 1:
        fails += 1
        msgs.append('H1 唯一性: 发现 %d 个 H1（应为 1）FAIL' % h1_count)
    else:
        msgs.append('H1 唯一性: 1 个 PASS')

    src_entries = []
    for p in src_paths:
        src_entries.extend(heading_entries(open(p, encoding='utf-8').read()))

    diffs = compare_headings(src_entries, merged, '源文拼接', '合并产物',
                             level_shift=1, doc_skip_head=1)
    if diffs:
        fails += len(diffs)
        msgs.append('标题: FAIL（源 %d 条 vs 译文 %d 条）'
                    % (len(src_entries), len(merged) - 1))
        for diff in diffs:
            msgs.append('  %s' % diff)
    else:
        msgs.append('标题: %d 条与源逐项一致（层级含已批准降级、官方原题） PASS'
                    % len(src_entries))
    return fails, msgs


def check_fences(path):
    fails = 0
    msgs = []
    text = open(path, encoding='utf-8').read()
    fences = scan_code_fences(text)
    if not fences.balanced:
        fails += 1
        msgs.append('代码围栏: 第 %d 行开启的代码块未闭合，不成对 FAIL'
                    % fences.unclosed_line)
    else:
        msgs.append('代码围栏: %d 个边界，配对 PASS' % fences.boundary_count)
    return fails, msgs


def check_code_blocks(merged_path, src_paths):
    """合并产物代码围栏与拼接源逐块核对（开启行/语言/正文/关闭行）。"""
    fails = 0
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    src_scan = scan_code_fences(src_text)
    doc_scan = scan_code_fences(merged_text)
    if not src_scan.balanced:
        fails += 1
        msgs.append('源文代码围栏: 第 %d 行开启的代码块未闭合 FAIL'
                    % src_scan.unclosed_line)
    if not doc_scan.balanced:
        fails += 1
        msgs.append('代码围栏: 第 %d 行开启的代码块未闭合 FAIL'
                    % doc_scan.unclosed_line)
    src_label = '源文拼接(%s)' % '+'.join(
        os.path.basename(p) for p in src_paths)
    for diff in compare_code_fences(src_scan.blocks, doc_scan.blocks,
                                    src_label, os.path.basename(merged_path)):
        fails += 1
        msgs.append('代码逐块核对: %s FAIL' % diff)
    if fails == 0:
        msgs.append('代码逐块核对: %d 块与源一致 PASS' % len(doc_scan.blocks))
    return fails, msgs


def check_math(merged_path, src_paths, approved_extra_math):
    """合并产物公式与拼接源逐项核对（类型/顺序/原表达式）。"""
    fails = 0
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    src_math = scan_math_spans(src_text)
    doc_math = scan_math_spans(merged_text)
    src_label = '源文拼接(%s)' % '+'.join(
        os.path.basename(p) for p in src_paths)
    math_diffs, math_warns = compare_math_spans(
        src_math, doc_math, src_label, os.path.basename(merged_path),
        approved_extra_exprs=approved_extra_math)
    for diff in math_diffs:
        fails += 1
        msgs.append('公式逐项核对: %s FAIL' % diff)
    msgs.extend('公式逐项核对: %s WARN' % w for w in math_warns)
    if not math_diffs and doc_math:
        msgs.append('公式逐项核对: %d 处与源逐项一致 PASS' % len(doc_math))
    return fails, msgs


def check_footnotes(merged_path, src_paths):
    """脚注以源引用/定义关系为基准核对（支持命名标签）。"""
    fails = 0
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    diffs, warns = footnote_diffs(src_text, merged_text, '源文拼接', '合并产物')
    for diff in diffs:
        fails += 1
        msgs.append('脚注核对: %s FAIL' % diff)
    msgs.extend('脚注核对: %s WARN' % w for w in warns)
    if not diffs:
        msgs.append('脚注核对: 与源引用/定义关系一致 PASS')
    return fails, msgs


def check_images(merged_path, src_paths, delivery_root, image_digests):
    """合并产物图片核验：源译出现次数对账（常开）+ 离线引用/类型/来源身份。

    完整通过必须建立每次出现的来源身份：优先 --image-map，其次按各源文件
    目录从可靠的当前源资源推导；两者都不可用而译文含图时不判定完整通过。
    """
    fails = 0
    msgs = []
    text = open(merged_path, encoding='utf-8').read()
    src_count = 0
    derived = []
    for p in src_paths:
        src_text = open(p, encoding='utf-8').read()
        src_count += image_occurrence_count(src_text)
        digests = source_occurrence_digests(
            src_text, os.path.dirname(os.path.abspath(p)))
        if digests is None:
            derived = None
        elif derived is not None:
            derived.extend(digests)
    doc_count = len(image_references(text))
    if doc_count < src_count:
        fails += 1
        msgs.append('图片对账: 源出现 %d 次但译文仅 %d 次 FAIL（漏图）'
                    % (src_count, doc_count))
    elif doc_count > src_count:
        msgs.append('图片对账: 译文出现 %d 次多于源 %d 次 WARN（回源确认）'
                    % (doc_count, src_count))
    else:
        msgs.append('图片对账: 源译出现次数一致（%d 次） PASS' % src_count)
    identity = image_digests
    identity_basis = '映射'
    if identity is None:
        identity = derived
        identity_basis = '当前源资源'
    image_fails = image_occurrence_fails(
        text, os.path.dirname(os.path.abspath(merged_path)), delivery_root,
        expected_digests=identity)
    if image_fails:
        fails += len(image_fails)
        msgs.extend('图片核验: %s FAIL' % m for m in image_fails)
    elif identity is not None:
        msgs.append('图片核验: 离线引用、类型与来源身份（%s） PASS'
                    % identity_basis)
    if identity is None and doc_count:
        fails += 1
        msgs.append('图片核验: 来源身份未核验（无 --image-map 且源资源不可解析），'
                    '不判定完整通过 FAIL')
    return fails, msgs


def check_syntax(merged_path, src_paths, strong_tokens):
    """项目强 token 多重集差异（未配置时明示未检查）。"""
    fails = 0
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    diffs, warns = strong_token_report(src_text, merged_text, strong_tokens,
                                       '源文拼接', '合并产物')
    if diffs is None:
        msgs.extend('强 token: %s' % w for w in warns)
        return fails, msgs
    for diff in diffs:
        fails += 1
        msgs.append('强 token: %s FAIL' % diff)
    msgs.extend('强 token: %s WARN' % w for w in warns)
    if not diffs:
        msgs.append('强 token: %d 个与源一致或仅增加 PASS' % len(strong_tokens))
    return fails, msgs


def check_residual(merged_path):
    fails = 0
    msgs = []
    text = open(merged_path, encoding='utf-8').read()
    for marker in residual_markers(text, _RESIDUAL_MARKERS):
        fails += 1
        if marker in _RESIDUAL_MARKERS:
            msgs.append('残留解析标记: %s FAIL' % marker)
        else:
            msgs.append('残留块级占位符: %s FAIL' % marker)
    if fails == 0:
        msgs.append('残留解析标记: PASS')
    return fails, msgs


def coverage_warnings(merged_path, src_paths):
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    pairs = [
        ('代码围栏', src_text.count('```') // 2, merged_text.count('```') // 2),
        ('提示框', src_text.count('ADMONITION'),
         merged_text.count('> **注（Note）**') + merged_text.count('> **警告（Warning）**') + merged_text.count('> **重要（Important）**')),
        ('公式', len(re.findall(r'\$[^$\n]+\$', src_text)), len(re.findall(r'\$[^$\n]+\$', merged_text))),
        ('列表项',
         len([l for l in src_text.splitlines() if l.startswith('  - ')]),
         len([l for l in merged_text.splitlines() if l.strip().startswith(('- ', '* '))])),
    ]
    for name, s, d in pairs:
        msgs.append('覆盖率 %s: 源 %d / 译 %d（差值供人工判断）' % (name, s, d))
    return msgs


def main():
    argv, approved_extra_math = extract_approved_extra_math(sys.argv[1:])
    argv, strong_tokens = extract_strong_tokens(argv)
    argv, image_map, delivery_root = extract_image_options(argv)
    if len(argv) < 2:
        sys.exit(__doc__)

    merged_path = argv[0]
    src_paths = argv[1:]
    image_digests = load_image_digests(image_map) if image_map else None

    total_fail = 0
    all_msgs = []

    for fn, func, args in [
        ('标题与顺序', check_headings, (merged_path, src_paths)),
        ('代码围栏', check_fences, (merged_path,)),
        ('代码逐块核对', check_code_blocks, (merged_path, src_paths)),
        ('公式逐项核对', check_math,
         (merged_path, src_paths, approved_extra_math)),
        ('脚注核对', check_footnotes, (merged_path, src_paths)),
        ('图片核验', check_images,
         (merged_path, src_paths, delivery_root, image_digests)),
        ('强 token', check_syntax, (merged_path, src_paths, strong_tokens)),
        ('残留解析标记', check_residual, (merged_path,)),
    ]:
        f, msgs = func(*args)
        total_fail += f
        all_msgs.append('## %s' % fn)
        all_msgs.extend(msgs)

    all_msgs.append('## 覆盖率警告（信息性）')
    all_msgs.extend(coverage_warnings(merged_path, src_paths))

    print('\n'.join(all_msgs))
    print('\n结果: %s' % ('ALL PASS' if total_fail == 0 else '%d 项 FAIL' % total_fail))
    sys.exit(0 if total_fail == 0 else 1)


if __name__ == '__main__':
    main()
