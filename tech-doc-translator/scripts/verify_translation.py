#!/usr/bin/env python3
"""通用单页译文核对脚本。

用法：
    python3 verify_translation.py <译文.md> <源文.md> "官方标题1" "官方标题2" ...

官方标题只需编号 + 英文原题（如 "1. Introduction"），顺序传入。
脚本会兼容中文后缀 `（中文）` 与无后缀标题。
"""
import sys
import re
import os
from collections import Counter

from _verification import (
    heading_lines,
    invalid_math_delimiters,
    link_targets,
    literal_fence_count,
    missing_images,
    normalize,
    residual_markers,
    strip_chinese_suffix,
)

# 必须由主 Agent 在最终译文中消除的解析占位标记
_RESIDUAL_MARKERS = [
    '[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:', 'ADMONITION',
    '¶', '\uf0c1',
]


def extract_headings(doc):
    """返回 (h1s, subs) 其中 subs 按文档顺序包含所有 H2-H6。"""
    h1s = []
    subs = []
    for level, raw_text in heading_lines(doc):
        text = normalize(strip_chinese_suffix(raw_text))
        if level == 1:
            h1s.append(text)
        else:
            subs.append(text)
    return h1s, subs


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    doc_path = sys.argv[1]
    src_path = sys.argv[2] if len(sys.argv) > 2 and os.path.exists(sys.argv[2]) else None
    official = [normalize(strip_chinese_suffix(a)) for a in sys.argv[3:]]

    doc = open(doc_path, encoding='utf-8').read()
    src = open(src_path, encoding='utf-8').read() if src_path else ''
    fail = 0

    # 1) H1 唯一性
    h1s, subs = extract_headings(doc)
    if len(h1s) != 1:
        fail += 1
        print('H1 数量: %d（应为 1）FAIL: %s' % (len(h1s), h1s[:3]))

    # 2) 标题核对（含顺序）
    if official:
        got = h1s + subs
        if got == official:
            print('标题: %d 条与官方完全一致（含顺序） PASS' % len(got))
        else:
            fail += 1
            print('标题: FAIL（译文 %d 条 vs 官方 %d 条）' % (len(got), len(official)))
            for i in range(max(len(got), len(official))):
                g = got[i] if i < len(got) else ''
                e = official[i] if i < len(official) else ''
                if g != e:
                    print('  第 %d 条: 译文 %r vs 官方 %r' % (i + 1, g, e))

    # 3) 残留解析标记
    for marker in residual_markers(doc, _RESIDUAL_MARKERS):
        fail += 1
        if marker in _RESIDUAL_MARKERS:
            print('残留标记: %s FAIL' % marker)
        else:
            print('残留块级占位符: %s FAIL' % marker)

    # 4) 脚注配对
    for num in sorted(set(re.findall(r'\[\^(\d+)\]', doc))):
        refs = len(re.findall(r'\[\^%s\](?!:)' % num, doc))
        defs = len(re.findall(r'^\[\^%s\]:' % num, doc, re.M))
        if not (refs and defs):
            fail += 1
            print('脚注 [^%s]: 引用 %d / 定义 %d 不成对 FAIL' % (num, refs, defs))

    # 5) 图片存在性
    for image in missing_images(
            doc, os.path.dirname(doc_path), allow_cwd=True):
        fail += 1
        print('图片缺失: %s FAIL' % image)

    # 6) 代码围栏配对
    fence_count = literal_fence_count(doc)
    if fence_count % 2 != 0:
        fail += 1
        print('代码围栏不成对: %d 个反引号边界 FAIL' % fence_count)

    # 7) 公式定界符与链接目标
    if invalid_math_delimiters(doc):
        fail += 1
        print('公式定界符嵌套: Markdown 与 LaTeX 定界符不得叠加 FAIL')
    if src:
        missing_links = Counter(link_targets(src)) - Counter(link_targets(doc))
        if missing_links:
            fail += 1
            print('链接目标缺失: %s FAIL' % dict(missing_links))
        else:
            print('链接目标: 源 %d / 译 %d PASS' %
                  (len(link_targets(src)), len(link_targets(doc))))

    # 8) 内容块覆盖率（信息性）
    if src:
        pairs = [
            ('代码围栏', src.count('```') // 2, doc.count('```') // 2),
            ('提示框', src.count('ADMONITION'), doc.count('> **注（Note）**') + doc.count('> **警告（Warning）**') + doc.count('> **重要（Important）**')),
            ('公式', len(re.findall(r'\$[^$\n]+\$', src)), len(re.findall(r'\$[^$\n]+\$', doc))),
            ('列表项', len([l for l in src.splitlines() if l.startswith('  - ')]),
             len([l for l in doc.splitlines() if l.strip().startswith(('- ', '* '))])),
        ]
        for name, s, d in pairs:
            print('覆盖率 %s: 源 %d / 译 %d（差值供人工判断）' % (name, s, d))

    print('结果: %s' % ('ALL PASS' if fail == 0 else '%d 项 FAIL' % fail))
    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
