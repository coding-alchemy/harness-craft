#!/usr/bin/env python3
"""通用单页译文核对脚本。

用法：
    python3 verify_translation.py <译文.md> <源文.md> "官方标题1" "官方标题2" ...
        [--official-headings-file <文件>]
        [--approved-extra-math <表达式>]... [--strong-token <token>]...
        [--image-map <map.json>] [--delivery-root <dir>] [--fragment]
        [--source-adaptation <依据.json> [--source-adaptation <依据.json> ...]]
        [--numeric-review] [--numeric-policy <UTF-8 项目约定文件>]

官方标题只需编号 + 英文原题（如 "1. Introduction"），顺序传入。
--official-headings-file 提供 UTF-8 官方原题清单文件（每行一项），与
逐项官方标题互斥，同时提供时拒绝；相对路径按调用 cwd 解释。
脚本会兼容中文后缀 `（中文）` 与无后缀标题。
--approved-extra-math 按原文表达式逐条豁免获准译注公式（可重复；不掩盖源公式遗漏）。
--image-map 按出现顺序提供来源身份 sha256（原始快照独立建立）；未提供映射时
改由可靠的当前源资源推导身份（源引用须可解析为源文件旁的真实文件），两者都
不可用而译文含图时不判定完整通过。
--delivery-root 指定交付根（默认 Markdown 所在目录）；片段校验用 --fragment
（仅免除整篇 H1 要求，标题与图片出现次数仍与源对照，不提供豁免开关）。
--source-adaptation 可重复传入（多快照 F7/§7.5）：完整文档核验按给定顺序
把源 Markdown 切片（每片行数对得上依据记录的 markdown 范围事实、sha256
证明无缝未漂移；覆盖不完整/漂移如实拒绝），逐片对账后合并整文视图核对
公式；--fragment 片段校验按包范围口径（与恢复链路的片段硬检查同一实现），
逐份装载后拼接包范围视图，不对切片做全篇范围事实核对。
--numeric-review 显式启用数字与单位复核辅助（R5/§4.7）：报告数字、百
分比、数量级与单位差异及源/译位置，只报告不换算、不改文、不授予语义
完成。未启用时明示未检查，原人工数字复核义务不变。
--numeric-policy 引用本次实际适用的 UTF-8 项目数字约定：记录路径与内
容摘要作复核上下文，不执行为换算规则；未提供时采用“保留原值、报告差
异、不自动判换算”的明示默认口径。
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
    footnote_diffs,
    heading_entries,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
    link_targets,
    load_image_digests,
    math_issue_fails,
    residual_markers,
    scan_code_fences,
    scan_math,
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
               strong_tokens=(), approved_extra_math=(), fragment=False,
               source_adaptation=None, source_adaptations=None,
               numeric_review=False, numeric_policy=None,
               pdf_view=None, source_range=None):
    """通用单页检查核心：接收候选文本与实际目标目录，返回 (失败数, 输出行)。

    doc_text 可来自工作区外临时候选（草稿预检）；doc_dir 必须是最终
    Markdown 目录——图片等资源一律按最终目标路径定位，不按候选临时
    路径定位。CLI 与预检共用本核心，输出行与既有 CLI 完全一致。
    source_adaptation 为 LaTeXML 来源依据引用：片段内公式逐条绑定依据
    （类型与定界逐字），绑定失败即拒绝，不降级为普通来源。可重复传入
    （多快照 F7/§7.5，source_adaptations 为有序路径列表）：按给定顺序
    切片校验后合并整文视图，覆盖不完整/漂移如实拒绝。
    numeric_review 显式启用数字与单位复核辅助：只报告差异与定位 ID，
    不换算、不改文、不授予语义完成；numeric_policy 引用本次实际适用的
    项目数字约定（只作复核上下文，不执行为规则）。
    """
    if source_adaptations is None:
        source_adaptations = [source_adaptation] if source_adaptation else []
    source_adaptations = list(source_adaptations)
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
        diff = official_titles_diff(official, got)
        if diff is None:
            lines.append('标题: 与官方清单一致（含顺序） PASS')
        else:
            fail += 1
            lines.append('标题: 与官方清单不一致 FAIL（%s）' % diff)

    # 3) 残留解析标记
    for marker in residual_markers(doc, _RESIDUAL_MARKERS):
        if pdf_view and marker=='[ALGORITHM]':
            continue  # 当前PDF来源准入后，由实际算法身份/子块核验消费该结构标记。
        fail += 1
        if marker in _RESIDUAL_MARKERS:
            lines.append('残留标记: %s FAIL' % marker)
        else:
            lines.append('残留块级占位符: %s FAIL' % marker)

    # 4) 脚注：译文内部配对 + 以源引用/定义关系为基准
    for num in ([] if pdf_view else sorted(set(re.findall(r'\[\^(\d+)\]', doc)))):
        refs = len(re.findall(r'\[\^%s\](?!:)' % num, doc))
        defs = len(re.findall(r'^\[\^%s\]:' % num, doc, re.M))
        if not (refs and defs):
            fail += 1
            lines.append('脚注 [^%s]: 引用 %d / 定义 %d 不成对 FAIL' % (num, refs, defs))
    fn_diffs, fn_warns = ([],[]) if pdf_view else footnote_diffs(src, doc, src_label, doc_label)
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
    code_doc,code_src=doc,src
    if pdf_view:
        import _pdf_math
        code_doc=_pdf_math.footnote_view(doc,_pdf_math.context(pdf_view['checklist']))[0]
        code_src=_pdf_math.footnote_view(src,_pdf_math.context(pdf_view['checklist']))[0]
    doc_fences = scan_code_fences(code_doc)
    src_fences = scan_code_fences(code_src)
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
    if pdf_view:
        import _pdf_math
        doc_scan=None;src_spans=()
        math_diffs,math_warns,fails_issues=[],[],[]
        try:
            _pdf_math.check_fragment(pdf_view,*source_range,doc,approved_extra_math)
            _,doc_scan=_pdf_math.markdown_blocks(doc,_pdf_math.context(pdf_view['checklist']))
            _,src_scan=_pdf_math.markdown_blocks(src,_pdf_math.context(pdf_view['checklist']))
            src_spans=src_scan.spans
        except (ValueError,KeyError,IndexError,TypeError) as exc:
            fails_issues=['PDF确认数学: '+str(exc)]
    elif source_adaptations:
        import _latexml_source as latexml
        payload = None
        try:
            if fragment:
                # 片段模式（三轮 F4）：包范围视图——逐份装载结构校验后
                # 按序拼接，不对包切片做全篇 Markdown 范围事实核对
                # （整源准入由拆包/恢复/合并预检承担；完整文档模式仍走
                # source_view_payload 全篇核对）
                payload = latexml.fragment_view_payload(source_adaptations)
            else:
                payload = latexml.source_view_payload(src, source_adaptations)
        except ValueError as exc:
            bind_problems = [str(exc)]
            src_spans = []
        if payload is not None:
            # 宿主（脚注定义等）内字面公式源侧按 bound_math_spans 逐字进入比较，
            # 译侧同口径保留（两侧对称）：脚注公式损伤由本比较发现，不丢弃
            scan_context = latexml.scan_context_from_payload(payload)
            doc_scan = scan_math(doc, source_context=scan_context)
            src_spans, bind_problems = latexml.precise_math_spans(
                src, source_adaptations[0], full=not fragment,
                label=src_label, payload=payload)
        else:
            doc_scan = scan_math(doc)
        for problem in bind_problems:
            fail += 1
            lines.append('公式来源绑定: %s FAIL' % problem)
        if bind_problems:
            # 绑定失败即拒绝：精确比较口径已不成立，不再以空源跨度
            # 继续比较制造"公式数不一致/未闭合"等误导噪音（如实诊断）
            math_diffs, math_warns, fails_issues = [], [], []
        else:
            math_diffs, math_warns = compare_math_spans(
                src_spans, doc_scan.spans, src_label, doc_label,
                approved_extra_exprs=approved_extra_math, doc_text=doc,
                precise=True)
            fails_issues = math_issue_fails(doc_scan.issues, doc_label)
    else:
        doc_scan = scan_math(doc)
        src_scan = scan_math(src)
        math_diffs, math_warns = compare_math_spans(
            src_scan.spans, doc_scan.spans, src_label, doc_label,
            approved_extra_exprs=approved_extra_math, doc_text=doc)
        fails_issues = (math_issue_fails(src_scan.issues, src_label)
                        + math_issue_fails(doc_scan.issues, doc_label))
    for diff in math_diffs:
        fail += 1
        lines.append('公式逐项核对: %s FAIL' % diff)
    for issue_fail in fails_issues:
        fail += 1
        lines.append('公式逐项核对: %s FAIL' % issue_fail)
    for warn in math_warns:
        lines.append('公式逐项核对: %s WARN' % warn)
    if not math_diffs and not fails_issues and not (
            source_adaptations and bind_problems):
        src_count = len(src_spans) if source_adaptations or pdf_view \
            else len(scan_math(src).spans)
        if src_count:
            lines.append('公式逐项核对: %d 处（行内 %d/块级 %d）与源逐项一致 PASS'
                         % (len(doc_scan.spans),
                            sum(1 for s in doc_scan.spans if s.kind == 'inline'),
                            sum(1 for s in doc_scan.spans if s.kind == 'block')))
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

    # 10) 数字与单位复核辅助（R5/§4.7）：显式启用才检查；只报告差异与
    # 定位 ID，不换算、不改文、不授予语义完成；未启用明示未检查
    if numeric_review:
        import _numeric_review as numeric
        try:
            review = numeric.compute_numeric_review(
                src, doc, src_label=src_label, doc_label=doc_label,
                scope='full', policy_path=numeric_policy)
        except ValueError as exc:
            fail += 1
            lines.append('数字辅助: %s FAIL' % exc)
        else:
            lines.append(numeric.format_policy_line(review['policy']))
            for diff in review['diffs']:
                lines.append(numeric.format_diff_hint(diff))
            if not review['diffs']:
                lines.append('数字提示: 本次范围源/译逐字保留，无统计差异'
                             '（仍须独立语义复核，不授予完成）')
            lines.extend(numeric.unchecked_notes(review))
    else:
        lines.append('数字辅助: 未启用 --numeric-review，此项未检查'
                     '（原人工数字复核义务不变）')

    lines.append('结果: %s' % ('ALL PASS' if fail == 0 else '%d 项 FAIL' % fail))
    return fail, lines


def parse_args(argv, *, base_dir=None):
    """解析既有 CLI 参数，返回语义结构（verify_delivery 复用同一解释）。

    doc_path/src_path 为路径；official 为官方标题字面值；--strong-token、
    --approved-extra-math、--image-map、--delivery-root、--fragment 按真实
    语义拆出。路径与字面值不做任何改写，由调用方按自己的基点解释。
    --official-headings-file 与逐项官方原题互斥（同角色官方输入），
    同时提供时拒绝；文件路径由调用方在实际调用基点读取。
    """
    argv, official_headings_file = extract_official_headings_option(argv)
    import recover_work_packages as rwp
    argv, project_context = rwp.extract_project_context(argv)
    argv, approved_extra_math = extract_approved_extra_math(argv)
    token_files = []
    argv, strong_tokens = extract_strong_tokens(argv, base_dir=base_dir, files=token_files)
    argv, image_map, delivery_root = extract_image_options(argv)
    argv, source_adaptations = extract_source_adaptation(argv)
    argv, numeric_review, numeric_policy = extract_numeric_review_options(argv)
    fragment = '--fragment' in argv
    argv = [a for a in argv if a != '--fragment']
    if len(argv) < 2:
        sys.exit(__doc__)
    if official_headings_file and len(argv) > 2:
        sys.exit('--official-headings-file 与逐项官方原题位置参数互斥，'
                 '同时提供 FAIL')
    return {
        'doc_path': argv[0],
        'project_context': project_context,
        'src_path': argv[1],
        'official': list(argv[2:]),
        'official_headings_file': official_headings_file,
        'strong_token_files': token_files,
        'strong_tokens': strong_tokens,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
        'fragment': fragment,
        'source_adaptation': source_adaptations[0] if source_adaptations
        else None,
        'source_adaptations': source_adaptations,
        'numeric_review': numeric_review,
        'numeric_policy': numeric_policy,
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
    source_adaptation = parsed['source_adaptation']
    image_digests = load_image_digests(image_map) if image_map else None

    if not os.path.isfile(src_path):
        sys.exit('源文缺失或不可读: %s FAIL（输入不足，不得把缺源解释成跳过检查）'
                 % src_path)
    if parsed['official_headings_file']:
        # 共享加载器在 CLI 实际调用基点（本进程 cwd）读取
        _path, official = load_official_headings(
            parsed['official_headings_file'])
    import _pdf_math
    try:
        pdf_view,source_range=_pdf_math.translation_view(src_path,parsed['project_context'])
    except (ValueError,KeyError,IndexError,TypeError) as exc:
        sys.exit('PDF来源核验拒绝: '+str(exc))
    doc = _pdf_math.read_document(doc_path,exact=bool(pdf_view))
    src = _pdf_math.read_document(src_path,exact=bool(pdf_view))
    fail, lines = run_checks(
        doc, src, official,
        doc_dir=os.path.dirname(os.path.abspath(doc_path)),
        doc_label=doc_path, src_label=src_path,
        image_digests=image_digests, delivery_root=delivery_root,
        strong_tokens=strong_tokens,
        approved_extra_math=approved_extra_math, fragment=fragment,
        source_adaptations=parsed['source_adaptations'],
        numeric_review=parsed['numeric_review'],
        numeric_policy=parsed['numeric_policy'],pdf_view=pdf_view,source_range=source_range)
    print('\n'.join(lines))
    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
