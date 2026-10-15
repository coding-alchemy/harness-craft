#!/usr/bin/env python3
"""数学密集 / 深层嵌套参考手册译文校验。

用法：
    python3 verify_reference_translation.py <译文.md> <源文.md> [strong_token ...]
        [--official-headings-file <文件>]
        [--approved-extra-math <表达式>]...
        [--source-adaptation <依据.json> [--source-adaptation <依据.json> ...]]
        [--numeric-review] [--numeric-policy <UTF-8 项目约定文件>]

--numeric-review 显式启用数字与单位复核辅助（R5/§4.7）：报告数字、
百分比、数量级与单位差异及源/译位置，只报告不换算、不改文、不授予
语义完成。未启用时明示未检查，原人工数字复核义务不变。
--numeric-policy 引用本次实际适用的 UTF-8 项目数字约定：记录路径与
内容摘要作复核上下文，不执行为换算规则；未提供时采用“保留原值、
报告差异、不自动判换算”的明示默认口径。

--official-headings-file 提供 UTF-8 官方原题清单文件（每行一项，与
旧位置强 token 可并存，角色不变）；相对路径按调用 cwd 解释。

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

from _official_headings import (
    extract_official_headings_option,
    load_official_headings,
    official_titles_diff,
)
from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_numeric_review_options,
    extract_source_adaptation,
    extract_strong_tokens,
    normalize_strong_tokens,
    footnote_diffs,
    heading_entries,
    image_marker_refs,
    load_image_digests,
    link_targets,
    image_occurrence_fails,
    image_references,
    math_issue_fails,
    residual_markers,
    scan_code_fences,
    MathScan,
    scan_math,
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
           doc_label='译文', src_label='源文', official=(),
           source_adaptation=None, source_adaptations=None,
           numeric_review=False, numeric_policy=None):
    """参考手册检查核心：接收候选文本与实际目标目录，返回 (fails, warns)。

    doc_text 可来自工作区外临时候选（草稿预检）；doc_dir 必须是最终
    Markdown 目录——图片等资源一律按最终目标路径定位，不按候选临时
    路径定位。doc_label/src_label 沿用调用方路径标签用于诊断定位。
    official 为加载后的官方原题清单（独立基准，可与旧位置强 token 并存）。
    source_adaptation 为 LaTeXML 来源依据引用：公式事实按已确认定界与
    原表达式精确核对（漏参数/不符不降级为普通来源）。可重复传入（多快
    照 F7/§7.5，source_adaptations 为有序路径列表）：按给定顺序切片校
    验后合并整文视图，覆盖不完整/漂移如实拒绝。
    numeric_review 显式启用数字与单位复核辅助：只报告差异与定位 ID，
    不换算、不改文、不授予语义完成；numeric_policy 引用本次实际适用的
    项目数字约定（只作复核上下文，不执行为规则）。
    """
    if source_adaptations is None:
        source_adaptations = [source_adaptation] if source_adaptation else []
    source_adaptations = list(source_adaptations)
    # 译文侧表示形态：LaTeXML 候选文档以 [TABLE]/[IMG:] 等登记标记承载
    # 对应内容（独立对账已逐项核对），按源侧同一口径计数；最终译文（真实
    # 表格与图片语法）与普通来源文档沿用常规口径。按文档自身内容判定，
    # 不以是否提供来源依据判定。
    doc_candidate_form = bool(source_adaptations) and any(
        m in doc_text for m in ('[TABLE]', '[IMG:', '[FIGURE]', '[FIGCAP]'))
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
    if official:
        # 官方原题清单独立基准：源与译文同时漏标题时仍被检出
        diff = official_titles_diff(
            official, [t for _, _, t in doc_entries])
        if diff is not None:
            fails.append('标题: 与官方清单不一致（%s）' % diff)

    # 4) 公式逐项核对（类型/顺序/原表达式，含历史包装告警）与未解决定界
    if source_adaptations:
        # LaTeXML 来源：源侧公式事实以已确认来源依据为准（逐字表达式与
        # 已确认类型），绑定失败即拒绝，不降级为普通扫描；译侧同一扫描
        # 器消费已确认限定上下文（D2，多行/边界空白行内识别）。宿主
        # （脚注定义等）内字面公式源侧按 bound_math_spans 逐字进入比较，
        # 译侧同口径保留（两侧对称），脚注公式损伤由本比较发现。多快照
        # （F7/§7.5）按给定顺序切片校验后合并整文视图。
        import _latexml_source as latexml
        payload = None
        try:
            payload = latexml.source_view_payload(src, source_adaptations)
        except ValueError as exc:
            bind_problems = [str(exc)]
            src_spans = []
        if payload is not None:
            scan_context = latexml.scan_context_from_payload(payload)
            doc_scan = scan_math(doc, source_context=scan_context)
            src_spans, bind_problems = latexml.precise_math_spans(
                src, source_adaptations[0], full=True, label=src_label,
                payload=payload)
        else:
            doc_scan = scan_math(doc)
        fails.extend('公式来源绑定: %s' % p for p in bind_problems)
        if bind_problems:
            # 绑定失败即拒绝：精确比较口径已不成立，不再以空源跨度继续
            # 比较制造"公式数不一致/未闭合"等误导噪音（如实诊断）
            math_warns = []
        else:
            math_diffs, math_warns = compare_math_spans(
                src_spans, doc_scan.spans, src_label, doc_label,
                approved_extra_exprs=approved_extra_math, doc_text=doc,
                precise=True)
            fails.extend('公式逐项核对: %s' % d for d in math_diffs)
            fails.extend(math_issue_fails(doc_scan.issues, doc_label))
        warns.extend(math_warns)
    else:
        doc_scan = scan_math(doc)
        src_scan = scan_math(src)
        math_diffs, math_warns = compare_math_spans(
            src_scan.spans, doc_scan.spans, src_label, doc_label,
            approved_extra_exprs=approved_extra_math, doc_text=doc)
        fails.extend('公式逐项核对: %s' % d for d in math_diffs)
        fails.extend(math_issue_fails(src_scan.issues, src_label))
        fails.extend(math_issue_fails(doc_scan.issues, doc_label))
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
    if '[TABLE]' in doc and not doc_candidate_form:
        fails.append('残留表格标记: [TABLE]')
    s_rows = table_data_rows(src, is_source=True)
    # 候选形态译文仍是 [TABLE] 格位表示（同一生成语法），按源侧同一口径
    # 计数；最终译文的真实表格与普通来源沿用常规口径
    d_rows = table_data_rows(doc, is_source=doc_candidate_form)
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
    # 候选形态译文以 [IMG:] 标记为已登记对应的候选表示（数量对齐即可，
    # 标记替换为图片语法是最终译文义务）；最终译文与普通来源按实际图片
    # 语法计数
    d_imgs = source_image_markers(doc) if doc_candidate_form \
        else len(image_references(doc))
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
    if identity is None and d_imgs and not doc_candidate_form:
        # 候选形态译文的图片来源身份已由来源依据对应与独立对账覆盖
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
    exempt = ('[TABLE]', '[FIGURE]', '[FIGCAP]', '[IMG:') \
        if doc_candidate_form else ()
    for marker in residual_markers(doc, _RESIDUAL_MARKERS):
        if any(marker.startswith(base) for base in exempt):
            # 候选形态译文的图题/图片/表格格位标记是已登记对应的事实性
            # 候选内容（独立对账已逐字核对），不是待消除的解析残留
            continue
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

    # 数字与单位复核辅助（R5/§4.7）：显式启用才检查；只报告差异与定位
    # ID，不换算、不改文、不授予语义完成；未启用明示未检查
    if numeric_review:
        import _numeric_review as numeric
        try:
            review = numeric.compute_numeric_review(
                src, doc, src_label=src_label, doc_label=doc_label,
                scope='full', policy_path=numeric_policy)
        except ValueError as exc:
            fails.append('数字辅助: %s' % exc)
        else:
            warns.append(numeric.format_policy_line(review['policy']))
            for diff in review['diffs']:
                warns.append(numeric.format_diff_hint(diff))
            if not review['diffs']:
                warns.append('数字提示: 本次范围源/译逐字保留，无统计差异'
                             '（仍须独立语义复核，不授予完成）')
            warns.extend(numeric.unchecked_notes(review))
    else:
        warns.append('数字辅助: 未启用 --numeric-review，此项未检查'
                     '（原人工数字复核义务不变）')

    return fails, warns


def parse_args(argv, *, base_dir=None):
    """解析既有 CLI 参数，返回语义结构（verify_delivery 复用同一解释）。

    --official-headings-file 与旧位置强 token 角色互不影响，可并存。
    --source-adaptation 引用 LaTeXML 来源依据（公式按已确认口径核对）。
    --numeric-review 显式启用数字与单位复核辅助；--numeric-policy 引用
    本次实际适用的 UTF-8 项目数字约定（只作复核上下文，不执行为规则）。
    """
    argv, official_headings_file = extract_official_headings_option(argv)
    argv, approved_extra_math = extract_approved_extra_math(argv)
    token_files = []
    argv, flag_tokens = extract_strong_tokens(argv, base_dir=base_dir, files=token_files)
    argv, image_map, delivery_root = extract_image_options(argv)
    argv, source_adaptations = extract_source_adaptation(argv)
    argv, numeric_review, numeric_policy = extract_numeric_review_options(argv)
    if len(argv) < 2:
        sys.exit(__doc__)
    return {
        'translated_path': argv[0],
        'source_path': argv[1],
        'strong_token_files': token_files,
        'strong_tokens': normalize_strong_tokens(list(argv[2:]) + flag_tokens),
        'official_headings_file': official_headings_file,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
        'source_adaptation': source_adaptations[0] if source_adaptations
        else None,
        'source_adaptations': source_adaptations,
        'numeric_review': numeric_review,
        'numeric_policy': numeric_policy,
    }


def main():
    parsed = parse_args(sys.argv[1:])
    translated_path = parsed['translated_path']
    source_path = parsed['source_path']
    strong_tokens = parsed['strong_tokens']
    approved_extra_math = parsed['approved_extra_math']
    delivery_root = parsed['delivery_root']
    image_map = parsed['image_map']
    source_adaptation = parsed['source_adaptation']
    numeric_review = parsed['numeric_review']
    numeric_policy = parsed['numeric_policy']
    image_digests = load_image_digests(image_map) if image_map else None
    official = None
    if parsed['official_headings_file']:
        # 共享加载器在 CLI 实际调用基点（本进程 cwd）读取
        _path, official = load_official_headings(
            parsed['official_headings_file'])
    fails, warns = verify(
        read(translated_path), read(source_path), strong_tokens,
        approved_extra_math, delivery_root, image_digests,
        doc_dir=os.path.dirname(os.path.abspath(translated_path)),
        doc_label=translated_path, src_label=source_path,
        official=official or (), source_adaptation=source_adaptation,
        source_adaptations=parsed['source_adaptations'],
        numeric_review=numeric_review, numeric_policy=numeric_policy)

    print('%s: %s' % (os.path.basename(translated_path), 'PASS' if not fails else 'FAIL'))
    for f in fails:
        print('   ✗', f)
    for w in warns:
        print('   ⚠', w)
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
