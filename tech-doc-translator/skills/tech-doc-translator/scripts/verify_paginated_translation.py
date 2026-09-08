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
    heading_lines,
    missing_images,
    normalize,
    residual_markers,
    scan_fences,
    strip_chinese_suffix,
)

# 必须由主 Agent 在最终译文中消除的解析占位标记
_RESIDUAL_MARKERS = [
    '[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:', 'ADMONITION',
    '¶', '\uf0c1',
]

# CUDA 标志性语法 token；译文数量不得少于源文
_SYNTAX_TOKENS = ['<<<', '#include <']


def extract_headings(path, strip_cn=False):
    """按文档顺序返回所有标题文本（含级别）。"""
    out = []
    text = open(path, encoding='utf-8').read()
    for level, raw_text in heading_lines(
            text, ignore_fences=True, strip_lines=True):
        title = strip_chinese_suffix(raw_text) if strip_cn else raw_text
        out.append((level, normalize(title)))
    return out


def _section_key(t):
    """取标题节号前缀，用于集合/顺序匹配。"""
    m = re.match(r'^(\d[\d.]*)\s*[.\s]\s*', t)
    return m.group(1).rstrip('.') if m else t


def _is_section(t):
    """标题是否以官方节号前缀开头。"""
    return bool(re.match(r'^\d[\d.]*\s*[.\s]\s*', t))


def check_headings(merged_path, src_paths):
    """检查标题集合、顺序与 H1 唯一性。返回 (fail_count, message_list)。"""
    fails = 0
    msgs = []

    merged = extract_headings(merged_path, strip_cn=True)
    h1s = [t for lvl, t in merged if lvl == 1]
    subs = [(lvl, t) for lvl, t in merged if lvl > 1]

    if len(h1s) != 1:
        fails += 1
        msgs.append('H1 唯一性: 发现 %d 个 H1（应为 1）FAIL' % len(h1s))
    else:
        msgs.append('H1 唯一性: 1 个 PASS')

    official = []
    for p in src_paths:
        official.extend(extract_headings(p, strip_cn=False))

    official_seq = [_section_key(t) for lvl, t in official if _is_section(t)]
    merged_seq = [_section_key(t) for lvl, t in merged if _is_section(t)]

    official_dict = {_section_key(t): t for lvl, t in official if _is_section(t)}
    merged_dict = {_section_key(t): t for lvl, t in merged if _is_section(t)}

    missing = [n for n in official_dict if n not in merged_dict]
    extra = [n for n in merged_dict if n not in official_dict]
    diff = [(official_dict[k], merged_dict[k]) for k in official_dict if k in merged_dict and official_dict[k] != merged_dict[k]]

    it = iter(merged_seq)
    order_ok = all(k in it for k in official_seq)

    if not missing and not extra and not diff and order_ok:
        msgs.append('标题: %d 条与官方完全一致（含顺序） PASS' % len(official))
    else:
        fails += 1
        msgs.append('标题: FAIL（官方 %d 条 vs 译文 %d 条）' % (len(official), len(merged)))
        if missing:
            msgs.append('  缺失节号: %s' % missing)
        if extra:
            msgs.append('  多余节号: %s' % extra)
        for a, b in diff:
            msgs.append('  异字: %r vs %r' % (a, b))
        if not order_ok:
            msgs.append('  顺序不一致')

    return fails, msgs


def check_fences(path):
    fails = 0
    msgs = []
    text = open(path, encoding='utf-8').read()
    fences = scan_fences(text, strip_lines=False)
    if not fences.balanced:
        fails += 1
        msgs.append('代码围栏: %d 个边界，不成对 FAIL' % fences.boundary_count)
    else:
        msgs.append('代码围栏: %d 个边界，配对 PASS' % fences.boundary_count)
    return fails, msgs


def check_images(merged_path):
    fails = 0
    msgs = []
    text = open(merged_path, encoding='utf-8').read()
    base = os.path.dirname(os.path.abspath(merged_path))
    missing = missing_images(text, base, allow_cwd=True)
    if missing:
        fails += 1
        msgs.append('图片缺失: %s FAIL' % missing)
    else:
        msgs.append('图片存在性: PASS')
    return fails, msgs


def check_syntax(merged_path, src_paths):
    fails = 0
    msgs = []
    merged_text = open(merged_path, encoding='utf-8').read()
    src_text = ''.join(open(p, encoding='utf-8').read() for p in src_paths)
    for pat in _SYNTAX_TOKENS:
        src_n = src_text.count(pat)
        merged_n = merged_text.count(pat)
        if src_n == 0:
            msgs.append("语法 '%s': 源文 0 次，跳过" % pat)
        elif merged_n >= src_n:
            msgs.append("语法 '%s': 源文 %d / 译文 %d PASS" % (pat, src_n, merged_n))
        else:
            fails += 1
            msgs.append("语法 '%s': 源文 %d / 译文 %d 可能丢失 FAIL" % (pat, src_n, merged_n))
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
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    merged_path = sys.argv[1]
    src_paths = sys.argv[2:]

    total_fail = 0
    all_msgs = []

    for fn, func, args in [
        ('标题与顺序', check_headings, (merged_path, src_paths)),
        ('代码围栏', check_fences, (merged_path,)),
        ('图片存在性', check_images, (merged_path,)),
        ('CUDA 标志性语法', check_syntax, (merged_path, src_paths)),
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
