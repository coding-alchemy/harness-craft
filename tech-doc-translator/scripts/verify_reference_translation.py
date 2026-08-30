#!/usr/bin/env python3
"""数学密集 / 深层嵌套参考手册译文校验。

用法：
    python3 verify_reference_translation.py <译文.md> <源文.md> [strong_token ...]

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
    '[TABLE]', '[DEF-LIST]', '[FOOTNOTE-LIST]', '[IMG:',
    '[FIGURE]', '[FIGCAP]', '[BLOCKQUOTE]', 'ADMONITION',
]


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def num_of(h):
    m = re.match(r'#+ (\d+(?:\.\d+)*)\.?', h)
    return m.group(1).rstrip('.') if m else None


def extract_headings(text):
    """返回 (levels, h1s)。levels 为按文档顺序的 (level, stripped_text) 列表。"""
    h1s = []
    levels = []
    for level, raw in heading_lines(text):
        stripped = strip_chinese_suffix(raw)
        levels.append((level, normalize(stripped)))
        if level == 1:
            h1s.append(normalize(stripped))
    return levels, h1s


def display_math_count(text):
    """$$...$$ 块数。"""
    return len(re.findall(r'\$\$[\s\S]*?\$\$', text))


def inline_math_count(text):
    """$...$ 行内公式数，排除 $$ 块。"""
    cleaned = re.sub(r'\$\$[\s\S]*?\$\$', '', text)
    return len(re.findall(r'\$[^$\n]+\$', cleaned))


def fence_pairs(text):
    return literal_fence_count(text) // 2


def source_image_markers(text):
    return len(re.findall(r'^\s*\[IMG:', text, re.M))


def translation_images(text):
    return len(re.findall(r'!\[', text))


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


def count_token(text, token):
    if re.search(r'\w', token):
        return len(re.findall(r'(?<!\w)' + re.escape(token) + r'(?!\w)', text))
    return text.count(token)


def verify(translated_path, source_path, strong_tokens):
    fails = []
    warns = []
    doc = read(translated_path)
    src = read(source_path)

    # 1) H1 唯一性
    doc_levels, doc_h1s = extract_headings(doc)
    src_levels, src_h1s = extract_headings(src)
    if len(doc_h1s) != 1:
        fails.append('H1 数量: %d（应为 1）' % len(doc_h1s))

    # 2) 标题集合与顺序
    if len(doc_levels) != len(src_levels):
        fails.append('标题数量: 源 %d vs 译 %d' % (len(src_levels), len(doc_levels)))
    else:
        for i, ((sl, st), (dl, dt)) in enumerate(zip(src_levels, doc_levels)):
            if sl != dl or st != dt:
                fails.append('标题 #%d 不一致: 源 %s / 译 %s' % (i + 1, (sl, st), (dl, dt)))
                break

    # 3) H5-H8 深级标题
    src_deep = [t for lv, t in src_levels if lv >= 5]
    doc_deep = [t for lv, t in doc_levels if lv >= 5]
    if src_deep and not doc_deep:
        fails.append('深级标题 H5-H8 在译文中丢失')
    elif len(doc_deep) < len(src_deep):
        fails.append('深级标题数量减少: 源 %d vs 译 %d' % (len(src_deep), len(doc_deep)))

    # 4) 块级公式
    s_disp = display_math_count(src)
    d_disp = display_math_count(doc)
    if d_disp < s_disp:
        fails.append('块级公式丢失: 源 %d vs 译 %d' % (s_disp, d_disp))
    elif d_disp > s_disp:
        warns.append('块级公式增加: 源 %d vs 译 %d（可能为译注公式）' % (s_disp, d_disp))

    # 5) 行内公式
    s_inline = inline_math_count(src)
    d_inline = inline_math_count(doc)
    if d_inline < s_inline:
        fails.append('行内公式丢失: 源 %d vs 译 %d' % (s_inline, d_inline))
    elif d_inline > s_inline:
        warns.append('行内公式增加: 源 %d vs 译 %d' % (s_inline, d_inline))
    if invalid_math_delimiters(doc):
        fails.append('公式定界符嵌套: Markdown 与 LaTeX 定界符不得叠加')

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
    s_fences = fence_pairs(src)
    d_fences = fence_pairs(doc)
    if literal_fence_count(doc) % 2 != 0:
        fails.append('译文代码围栏不成对')
    if s_fences != d_fences:
        fails.append('代码围栏数不一致: 源 %d 对 vs 译 %d 对' % (s_fences, d_fences))

    # 9) 图片数量与存在性
    s_imgs = source_image_markers(src)
    d_imgs = translation_images(doc)
    if d_imgs < s_imgs:
        fails.append('图片数量不足: 源 %d vs 译 %d' % (s_imgs, d_imgs))
    elif d_imgs > s_imgs:
        warns.append('图片数量增加: 源 %d vs 译 %d' % (s_imgs, d_imgs))
    for image in missing_images(doc, os.path.dirname(translated_path)):
        fails.append('图片缺失: %s' % image)

    # 10) 强 token 多重集
    for token in strong_tokens:
        sc = count_token(src, token)
        dc = count_token(doc, token)
        if dc < sc:
            fails.append('强 token 遗漏 %s: 源 %d vs 译 %d' % (token, sc, dc))
        elif dc > sc:
            warns.append('强 token 增加 %s: 源 %d vs 译 %d（可能为译注引用）' % (token, sc, dc))

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

    # 脚注配对（信息性检查，防止 [^n] 被破坏）
    refs = set(re.findall(r'\[\^(\d+)\](?!:)', doc))
    defs = set(re.findall(r'^\[\^(\d+)\]:', doc, re.M))
    if refs != defs:
        fails.append('脚注不配对: refs=%s defs=%s' % (sorted(refs - defs), sorted(defs - refs)))

    return fails, warns


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    translated_path = sys.argv[1]
    source_path = sys.argv[2]
    strong_tokens = sys.argv[3:]
    fails, warns = verify(translated_path, source_path, strong_tokens)

    print('%s: %s' % (os.path.basename(translated_path), 'PASS' if not fails else 'FAIL'))
    for f in fails:
        print('   ✗', f)
    for w in warns:
        print('   ⚠', w)
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
