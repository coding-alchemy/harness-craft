#!/usr/bin/env python3
"""数学密集 / 深层嵌套参考手册译文校验。

用法：
    python3 verify_reference_translation.py <译文.md> <源文.md> [strong_token ...]
        [--approved-extra-math <表达式>]...

--approved-extra-math 按原文表达式逐条豁免获准译注公式（可重复；不掩盖源公式遗漏）。

检查项：
  1. H1 唯一性
  2. 标题集合与顺序（按编号前缀或英文原题；兼容中文后缀）
  3. H5-H8 深级标题存在性
  4. 块级公式数量守恒
  5. 行内公式数量（翻译 ≥ 源文）
  6. 定义列表语义不被误删
  7. 表格残留标记与行数漂移
  8. 代码围栏配对
  9. 图片数量与文件存在性
  10. 项目指定强 token 多重集差异
  11. 解析占位符 / 残留块级元素

合法重建导致的列表项 / 段落 / 表格行等分类漂移只降为警告，不误判通过。
"""
import sys
import re
import os
from collections import Counter

from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    count_token,
    extract_approved_extra_math,
    extract_image_options,
    extract_strong_tokens,
    footnote_diffs,
    heading_entries,
    image_marker_refs,
    load_image_digests,
    link_targets,
    image_occurrence_fails,
    image_references,
    residual_markers,
    scan_code_fences,
    scan_math_spans,
    source_occurrence_digests,
    strong_token_report,
)


# 必须由主 Agent 在最终译文中消除的解析占位标记
_RESIDUAL_MARKERS = [
    '[TABLE]', '[DEF-LIST]', '[FOOTNOTE-LIST]', '[IMG:',
    '[FIGURE]', '[FIGCAP]', '[BLOCKQUOTE]', 'ADMONITION',
]


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def num_of(h):
    m = re.match(r'#+ (\d+(?:\.\d+)*)\.?', h)
    return m.group(1).rstrip('.') if m else None


def source_image_markers(text):
    """源侧 [IMG:] 标记出现数；代码围栏内的图片语法示例不计数。"""
    return len(image_marker_refs(text))


def def_list_region_counts(text, is_source=True):
    """返回源文 [DEF-LIST] 条目数或译文对应 `- **Term**` 条目数。"""
    if is_source:
        in_def = False
        count = 0
        for line in text.splitlines():
            s = line.strip()
            if s == '[DEF-LIST]':
                in_def = True
                continue
            if in_def:
                if re.match(r'^#', s) or re.match(r'^```', s):
                    break
                if s.startswith('['):
                    # 遇到下一个块级标记，结束计数
                    break
                if re.match(r'^\*\*.+?\*\*', s):
                    count += 1
        return count
    else:
        return len(re.findall(r'^\s*- \*\*.+?\*\*', text, re.M))


def table_data_rows(text, is_source=True):
    if is_source:
        in_table = False
        count = 0
        for line in text.splitlines():
            s = line.strip()
            if s == '[TABLE]':
                in_table = True
                continue
            if in_table:
                if re.match(r'^#', s) or re.match(r'^```', s) or s.startswith('['):
                    break
                if ' | ' in s and '---' not in s:
                    count += 1
        return count
    else:
        rows = 0
        in_table = False
        for line in text.splitlines():
            s = line.strip()
            if re.match(r'^\|', s) and '---' not in s:
                in_table = True
                rows += 1
            elif in_table and not s.startswith('|') and s:
                break
        return rows


def content_counts(text, is_source=True):
    """段落、列表项、表格行、提示框计数（用于漂移警告，不直接判 FAIL）。"""
    paras, lis, trows, admon = 0, 0, 0, 0
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('```'):
            in_table = False
            continue
        if s.startswith('#'):
            in_table = False
            continue
        if s.startswith('>') and ('ADMONITION' in s or '> **注' in s or '> **警告' in s or '> **重要' in s):
            admon += 1
            continue
        if is_source:
            if s == '[TABLE]':
                in_table = True
                continue
            if in_table:
                if '---' not in s and ' | ' in s:
                    trows += 1
                elif s.startswith('[') or not s.startswith('  - '):
                    in_table = False
        else:
            if re.match(r'^\|', s):
                in_table = True
                if '---' not in s:
                    trows += 1
                continue
            elif in_table and not s.startswith('|') and s:
                in_table = False
        if s.startswith('  - ') or s.startswith('- '):
            lis += 1
            continue
        # 源文占位标记、图题等不计为段落
        if s.startswith('[') or s.startswith('!'):
            continue
        paras += 1
    return paras, lis, trows, admon


def verify(doc_text, src_text, strong_tokens, approved_extra_math=(),
           delivery_root=None, image_digests=None, doc_dir=None,
           doc_label='译文', src_label='源文'):
    """参考手册检查核心：接收候选文本与实际目标目录，返回 (fails, warns)。

    doc_text 可来自工作区外临时候选（草稿预检）；doc_dir 必须是最终
    Markdown 目录——图片等资源一律按最终目标路径定位，不按候选临时
    路径定位。doc_label/src_label 沿用调用方路径标签用于诊断定位。
    """
    fails = []
    warns = []
    doc = doc_text
    src = src_text
    if doc_dir is None:
        doc_dir = os.path.curdir

    # 1) 标题：H1 唯一性 + 与源按 (层级, 官方原题) 有序对照
    doc_entries = heading_entries(doc)
    src_entries = heading_entries(src)
    doc_h1s = [t for _, lvl, t in doc_entries if lvl == 1]
    if len(doc_h1s) != 1:
        fails.append('H1 数量: %d（应为 1）' % len(doc_h1s))
    for diff in compare_headings(src_entries, doc_entries,
                                 src_label, doc_label):
        fails.append(diff)

    # 4) 公式逐项核对（类型/顺序/原表达式，含历史包装告警）
    src_math = scan_math_spans(src)
    doc_math = scan_math_spans(doc)
    math_diffs, math_warns = compare_math_spans(
        src_math, doc_math, src_label, doc_label,
        approved_extra_exprs=approved_extra_math, doc_text=doc)
    fails.extend('公式逐项核对: %s' % d for d in math_diffs)
    warns.extend(math_warns)

    missing_links = Counter(link_targets(src)) - Counter(link_targets(doc))
    if missing_links:
        fails.append('链接目标缺失: %s' % dict(missing_links))

    # 6) 定义列表语义
    s_def = def_list_region_counts(src, is_source=True)
    d_def = def_list_region_counts(doc, is_source=False)
    if s_def:
        if d_def == 0:
            fails.append('定义列表语义被删除: 源 %d 条' % s_def)
        elif abs(s_def - d_def) > 1:
            warns.append('定义列表条目漂移: 源 %d vs 译 %d' % (s_def, d_def))
    if '[DEF-LIST]' in doc:
        fails.append('残留定义列表标记: [DEF-LIST]')

    # 7) 表格残留标记与行数
    if '[TABLE]' in doc:
        fails.append('残留表格标记: [TABLE]')
    s_rows = table_data_rows(src, is_source=True)
    d_rows = table_data_rows(doc, is_source=False)
    if s_rows and d_rows == 0:
        fails.append('表格数据行丢失: 源 %d 行' % s_rows)
    elif s_rows and abs(s_rows - d_rows) > 0:
        warns.append('表格数据行漂移: 源 %d vs 译 %d' % (s_rows, d_rows))

    # 8) 代码围栏
    doc_fences = scan_code_fences(doc)
    src_fences = scan_code_fences(src)
    if not doc_fences.balanced:
        fails.append('译文代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % doc_fences.unclosed_line)
    if not src_fences.balanced:
        fails.append('源文代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % src_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    src_label, doc_label):
        fails.append('代码逐块核对: %s' % diff)

    # 9) 图片：源 [IMG:] 出现数对照 + 离线核验（围栏内图片语法不计）。
    #    完整通过必须建立每次出现的来源身份：--image-map 或可靠的当前源资源，
    #    两者都不可用而译文含图时不判定完整通过
    s_imgs = source_image_markers(src)
    d_imgs = len(image_references(doc))
    if d_imgs < s_imgs:
        fails.append('图片数量不足: 源 %d vs 译 %d' % (s_imgs, d_imgs))
    elif d_imgs > s_imgs:
        warns.append('图片数量增加: 源 %d vs 译 %d' % (s_imgs, d_imgs))
    identity = image_digests
    identity_basis = '映射'
    if identity is None:
        identity = source_occurrence_digests(
            src, os.path.dirname(os.path.abspath(src_label)))
        identity_basis = '当前源资源'
    for msg in image_occurrence_fails(
            doc, doc_dir,
            delivery_root, expected_digests=identity):
        fails.append('图片核验: %s' % msg)
    if identity is None and d_imgs:
        fails.append('图片来源身份未核验（无 --image-map 且源资源不可解析），'
                     '不判定完整通过')

    # 10) 强 token 多重集（未配置时明示未检查）
    token_diffs, token_warns = strong_token_report(src, doc, strong_tokens,
                                                   src_label, doc_label)
    if token_diffs is not None:
        fails.extend(token_diffs)
        warns.extend(token_warns)
    else:
        warns.extend(token_warns)

    # 11) 残留解析占位符
    for marker in residual_markers(doc, _RESIDUAL_MARKERS):
        if marker in _RESIDUAL_MARKERS:
            fails.append('残留标记: %s' % marker)
        else:
            fails.append('残留块级占位符: %s' % marker)

    # 12) 内容块覆盖率漂移（仅警告）
    sp, sl, st, sa = content_counts(src, is_source=True)
    dp, dl, dt, da = content_counts(doc, is_source=False)
    if dl - sl < -2 and (dp + dl) - (sp + sl) < -2:
        fails.append('列表项显著丢失: 源 %d vs 译 %d（伴随语义块总数下降）' % (sl, dl))
    elif abs(sl - dl) > 1:
        warns.append('列表项漂移: 源 %d vs 译 %d' % (sl, dl))
    if st and dt < st * 0.8:
        warns.append('表格行漂移: 源 %d vs 译 %d' % (st, dt))
    if dp < sp * 0.8:
        warns.append('段落数漂移: 源 %d vs 译 %d' % (sp, dp))
    if sa and da != sa:
        fails.append('提示框数量变化: 源 %d vs 译 %d' % (sa, da))

    # 脚注：译文内部配对 + 以源引用/定义关系为基准（支持命名标签）
    refs = set(re.findall(r'\[\^([^\]]+)\](?!:)', doc))
    defs = set(re.findall(r'^\[\^([^\]]+)\]:', doc, re.M))
    if refs != defs:
        fails.append('脚注不配对: refs=%s defs=%s' % (sorted(refs - defs), sorted(defs - refs)))
    fn_diffs, fn_warns = footnote_diffs(src, doc, src_label, doc_label)
    fails.extend(fn_diffs)
    warns.extend(fn_warns)

    return fails, warns


def parse_args(argv):
    """解析既有 CLI 参数，返回语义结构（本 CLI 的单一解释入口）。"""
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, flag_tokens = extract_strong_tokens(argv)
    argv, image_map, delivery_root = extract_image_options(argv)
    if len(argv) < 2:
        sys.exit(__doc__)
    return {
        'translated_path': argv[0],
        'source_path': argv[1],
        'strong_tokens': list(argv[2:]) + flag_tokens,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
    }


def main():
    parsed = parse_args(sys.argv[1:])
    translated_path = parsed['translated_path']
    source_path = parsed['source_path']
    strong_tokens = parsed['strong_tokens']
    approved_extra_math = parsed['approved_extra_math']
    delivery_root = parsed['delivery_root']
    image_map = parsed['image_map']
    image_digests = load_image_digests(image_map) if image_map else None
    fails, warns = verify(
        read(translated_path), read(source_path), strong_tokens,
        approved_extra_math, delivery_root, image_digests,
        doc_dir=os.path.dirname(os.path.abspath(translated_path)),
        doc_label=translated_path, src_label=source_path)

    print('%s: %s' % (os.path.basename(translated_path), 'PASS' if not fails else 'FAIL'))
    for f in fails:
        print('   ✗', f)
    for w in warns:
        print('   ⚠', w)
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
