#!/usr/bin/env python3
"""多页面 API 译文校验脚本。

用法：
    python3 verify_api_translation.py <merged.md> <manifest.txt> <official_toc.txt> <site_root> <src1.md> [<src2.md> ...]
        [--official-headings-file <文件>]
        [--approved-extra-math <表达式>]...
        [--navigation-record <source_record.json>]

--official-headings-file 提供 UTF-8 官方原题清单文件（每行一项，按官方
页面顺序）；与 manifest/TOC/site root/源路径可并存，角色不变。原 TOC
继续独立核对页面集合与顺序，标题文件不替代 TOC。

--approved-extra-math 按原文表达式逐条豁免获准译注公式（可重复；不掩盖源公式遗漏）。

official_toc.txt 是独立的官方导航/TOC 快照（每行一个页面相对路径，按官方顺序），
与 discover_pages.py 的发现结果互为独立基准；闭合对账使用官方 TOC，
避免“发现器与验证器使用同一算法同时漏页”。

校验项：
1. 页面闭合：manifest 与 official_toc 完全一致（集合与顺序）。
2. 页面标题顺序：合并文件中各页首标题与源文件顺序一致。
3. 无编号标题多重集：排除每页首标题后，无编号标题数量/种类一致。
4. 代码围栏：配对、数量及逐字节内容与源一致。
5. 图片：每页数量/顺序一致，最终 Markdown 的相对引用存在，并做魔数 / `file` 验证。
6. 暗亮图片对只计一次。

--numeric-review 显式启用数字与单位复核辅助（R5/§4.7）：按 manifest
确认顺序拼接全部源页与合并译文比较，报告数字、百分比、数量级与单位
差异及位置（页来源角色保留在定位标签中），只报告不换算、不改文、
不授予语义完成；漏页/页序不符由页面闭合门禁拒绝。未启用时明示未检查。
--numeric-policy 引用本次实际适用的 UTF-8 项目数字约定：记录路径与
内容摘要作复核上下文，不执行为换算规则。
"""
import os
import re
import subprocess
import sys

from _official_headings import (
    extract_official_headings_option,
    load_official_headings,
    official_titles_diff,
)
from _verification import (
    check_image_file,
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_numeric_review_options,
    extract_strong_tokens,
    fenced_line_numbers,
    heading_entries,
    image_occurrence_fails,
    image_references,
    load_image_digests,
    math_issue_fails,
    resource_identity_digest,
    resolve_delivery_image,
    scan_code_fences,
    scan_math,
    markdown_list_count,
    strong_token_report,
)


def _resolve_image(site_root, page_rel, src):
    """返回本地图片绝对路径；非本地返回 None。"""
    if not src or re.match(r'^[a-z][a-z0-9+.-]*://', src, re.I):
        return None
    if os.path.isabs(src):
        return None
    return os.path.normpath(os.path.join(site_root, os.path.dirname(page_rel), src))


def _visible_html_images(site_root, page_rel):
    """复用独立来源的 API 暗亮选择，包含 figure 外的行内图片。"""
    from _source_reconcile import snapshot_image_facts
    path = os.path.join(site_root, page_rel)
    with open(path, encoding='utf-8') as handle:
        facts = snapshot_image_facts(handle.read(), 'api')
    return [resolved for fact in (facts or [])
            if (resolved := _resolve_image(site_root, page_rel, fact['source_ref']))]


def _split_pages(text):
    """按独立一行的 --- 切分合并文件为多页；代码围栏内的 --- 不参与切分。"""
    lines = text.split('\n')
    code_lines = fenced_line_numbers(text)
    pages = []
    cur = []
    for line_no, line in enumerate(lines, start=1):
        if line_no not in code_lines and line.strip() == '---':
            pages.append('\n'.join(cur))
            cur = []
        else:
            cur.append(line)
    pages.append('\n'.join(cur))
    return [p for p in pages if p.strip()]


def run_checks(merged_text, merged_dir, manifest, official, site_root,
               src_texts, *, merged_label, delivery_root=None,
               image_digests=None, approved_extra_math=(),
               strong_tokens=(), official_headings=(),
               numeric_review=False, numeric_policy=None, navigation_record=None):
    """多页 API 检查核心：接收候选文本与实际目标目录，返回 (失败诊断, 告警)。

    merged_text 可来自工作区外临时候选（草稿预检）；merged_dir 必须是
    最终 Markdown 目录——图片按最终目标路径定位，不按候选临时路径定位。
    强 token 的缺席/未配置告警与失败诊断一并返回，不丢弃。
    official_headings 为加载后的官方原题清单：按 manifest 页面顺序对
    全部译文标题做有序逐项对照；页面集合与顺序仍由官方 TOC 独立核对，
    标题文件不替代 TOC。
    """
    fails = []
    warns = []
    navigation=None
    if navigation_record:
        from _api_navigation import load_navigation
        try:navigation=load_navigation(navigation_record,site_root)
        except (OSError,ValueError,KeyError) as exc:return ['导航来源: '+str(exc)],warns

    if not manifest:
        raise SystemExit('empty manifest')

    # 1) 闭合校验：manifest 与独立官方 TOC 快照一致（集合与顺序）
    if manifest != official:
        missing = [p for p in official if p not in manifest]
        extra = [p for p in manifest if p not in official]
        fails.append('页面清单与官方 TOC 不闭合: 缺失 %s / 多余 %s / 顺序一致=%s'
                     % (missing or '无', extra or '无',
                        missing == [] and extra == [] and manifest == official))

    if len(src_texts) != len(manifest):
        fails.append('源文件数 %d 与清单 %d 不一致' % (len(src_texts), len(manifest)))

    trans_pages = _split_pages(merged_text)
    if len(trans_pages) != len(manifest):
        fails.append('合并文件页数 %d 与清单 %d 不一致' % (len(trans_pages), len(manifest)))

    # 逐页校验
    for idx, page_rel in enumerate(manifest):
        src_text = src_texts[idx] if idx < len(src_texts) else ''
        trans_text = trans_pages[idx] if idx < len(trans_pages) else ''

        src_label = '源页 %d' % (idx + 1)
        doc_label = '%s 第 %d 页' % (merged_label, idx + 1)

        # 页面标题顺序：按 (层级, 官方原题) 有序对照（后缀边界匹配）
        src_titles = heading_entries(src_text)
        trans_titles = heading_entries(trans_text)
        for diff in compare_headings(src_titles, trans_titles,
                                     src_label, doc_label):
            fails.append('页 %s 标题对照: %s' % (page_rel, diff))

        from _source_reconcile import compare_translation_tables, table_code_problems
        from _api_navigation import links
        if navigation is not None:
            from _api_navigation import verify_page
            chapter=os.path.join(merged_dir,merged_label)
            try:
                fails.extend(verify_page(src_text,trans_text,page_rel,navigation,chapter))
            except (ValueError,KeyError) as exc:fails.append('页 %s 导航: %s' % (page_rel,exc))
        else:
            from _api_navigation import compare_anchors
            fails.extend('页 %s %s' % (page_rel,diff) for diff in compare_anchors(src_text,trans_text))
            if links(src_text)!=links(trans_text):fails.append('页 %s 原链接目标或出现顺序改变' % page_rel)
            fails.extend('页 %s 表格核对: %s' % (page_rel, diff)
                         for diff in compare_translation_tables(src_text, trans_text))
        fails.extend('页 %s 表格代码: %s' % (page_rel, problem)
                     for problem in table_code_problems(trans_text))

        # 代码围栏
        source_fences = scan_code_fences(src_text)
        translated_fences = scan_code_fences(trans_text)
        if not source_fences.balanced:
            fails.append('页 %s 源文围栏不配对' % page_rel)
        if not translated_fences.balanced:
            fails.append('页 %s 译文围栏不配对' % page_rel)
        for diff in compare_code_fences(
                source_fences.blocks, translated_fences.blocks,
                src_label, doc_label):
            fails.append('页 %s 代码逐块核对: %s' % (page_rel, diff))

        # 公式逐项核对（类型/顺序/原表达式）与未解决定界
        src_scan = scan_math(src_text)
        doc_scan = scan_math(trans_text)
        math_diffs, _ = compare_math_spans(
            src_scan.spans, doc_scan.spans, src_label, doc_label,
            approved_extra_exprs=approved_extra_math, doc_text=trans_text, src_text=src_text)
        for diff in math_diffs:
            fails.append('页 %s 公式逐项核对: %s' % (page_rel, diff))
        for issue_fail in math_issue_fails(src_scan.issues, src_label) + \
                math_issue_fails(doc_scan.issues, doc_label):
            fails.append('页 %s 公式逐项核对: %s' % (page_rel, issue_fail))

        # 强 token（项目显式指定；未配置或源中缺席时明示未检查）
        token_diffs, token_warns = strong_token_report(src_text, trans_text,
                                                       strong_tokens,
                                                       src_label, doc_label)
        for diff in token_diffs or []:
            fails.append('页 %s 强 token %s' % (page_rel, diff))
        for warn in token_warns:
            warns.append('页 %s 强 token %s' % (page_rel, warn))

        warns.append('页 %s 覆盖率 列表项: 源 %d / 译 %d（差值供人工判断）'
                     % (page_rel, markdown_list_count(src_text),
                        markdown_list_count(trans_text)))

        # 图片：按出现顺序以来源文件摘要核对身份（不依赖 basename），
        # 交付引用解析、离线类型与暗亮出现数一并核验
        trans_refs = image_references(trans_text)
        trans_imgs = [s for _, s in trans_refs]
        html_visible = _visible_html_images(site_root, page_rel)
        if len(trans_imgs) != len(html_visible):
            fails.append('页 %s 暗亮图片计数异常: HTML 可见 %d vs 译文 %d'
                         % (page_rel, len(html_visible), len(trans_imgs)))
        for order, src in enumerate(trans_imgs, start=1):
            p, reason = resolve_delivery_image(src, merged_dir, delivery_root)
            if reason:
                fails.append('页 %s 图片 #%d: %s' % (page_rel, order, reason))
                continue
            if not os.path.isfile(p):
                fails.append('页 %s 交付图片缺失: %s' % (page_rel, src))
                continue
            ok, kind, reason = check_image_file(p, delivery_root or merged_dir)
            if not ok:
                fails.append('页 %s 图片类型异常 %s: %s' % (page_rel, src, reason))
                continue
            if order <= len(html_visible) and os.path.isfile(html_visible[order - 1]):
                if resource_identity_digest(p) != resource_identity_digest(
                        html_visible[order - 1]):
                    fails.append('页 %s 图片 #%d 来源身份不符: %s 与快照资源摘要不一致'
                                 % (page_rel, order, src))
            elif order <= len(html_visible):
                fails.append('页 %s 图片 #%d 源快照资源缺失: %s'
                             % (page_rel, order, html_visible[order - 1]))

    if official_headings:
        # 官方原题清单独立基准：按 manifest 页面顺序拼接译文标题原题
        # 后逐项对照；源页与译文同时漏标题时仍被检出。
        got = [t for page in trans_pages for _, _, t in heading_entries(page)]
        diff = official_titles_diff(official_headings, got)
        if diff is not None:
            fails.append('官方标题清单: 与官方清单不一致（%s）' % diff)

    if numeric_review:
        # R5/§4.7：按 manifest 确认顺序拼接全部源页与合并译文比较；
        # 只报告差异与定位 ID，不换算/改文/授予完成。
        import _numeric_review as numeric
        src_label = '源页拼接(%s)' % '+'.join(manifest)
        try:
            review = numeric.compute_numeric_review(
                '\n'.join(src_texts), merged_text, src_label=src_label,
                doc_label=merged_label, scope='full',
                policy_path=numeric_policy)
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

    # 全局出现序号的来源身份映射（--image-map，按交付出现顺序）
    global_refs = [(page_idx, order, src)
                   for page_idx, page in enumerate(trans_pages)
                   for order, (_, src) in enumerate(image_references(page),
                                                    start=1)]
    if image_digests is not None:
        if len(global_refs) != len(image_digests):
            fails.append('图片身份映射 %d 条与交付出现 %d 次不符'
                         % (len(image_digests), len(global_refs)))
        else:
            for page_idx, order, src in global_refs:
                p, reason = resolve_delivery_image(src, merged_dir,
                                                   delivery_root)
                if reason or not os.path.isfile(p):
                    continue  # 逐页检查已报告
                if resource_identity_digest(p) != image_digests[order - 1 + sum(
                        len(image_references(trans_pages[i]))
                        for i in range(page_idx))]:
                    fails.append('第 %d 页图片 #%d 来源身份不符: %s 与 --image-map 摘要不一致'
                                 % (page_idx + 1, order, src))
    return fails, warns


def parse_args(argv, *, base_dir=None):
    """解析既有 CLI 参数，返回语义结构（verify_delivery 复用同一解释）。

    --official-headings-file 与 manifest/official TOC/site root/源路径可
    并存，角色不变；官方 TOC 继续独立核对页面集合与顺序。
    """
    argv, official_headings_file = extract_official_headings_option(argv)
    argv, approved_extra_math = extract_approved_extra_math(argv)
    token_files = []
    argv, strong_tokens = extract_strong_tokens(argv, base_dir=base_dir, files=token_files)
    argv, image_map, delivery_root = extract_image_options(argv)
    argv, numeric_review, numeric_policy = extract_numeric_review_options(argv)
    navigation_record=None
    if '--navigation-record' in argv:
        position=argv.index('--navigation-record')
        if position+1>=len(argv):raise SystemExit('--navigation-record 缺少路径')
        navigation_record=argv[position+1];argv=argv[:position]+argv[position+2:]
        if '--navigation-record' in argv:raise SystemExit('--navigation-record 只能声明一次')
    if len(argv) < 5:
        sys.exit(__doc__)
    return {
        'merged_path': argv[0],
        'manifest_path': argv[1],
        'toc_path': argv[2],
        'site_root': argv[3],
        'src_paths': list(argv[4:]),
        'official_headings_file': official_headings_file,
        'strong_token_files': token_files,
        'strong_tokens': strong_tokens,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
        'numeric_review': numeric_review,
        'numeric_policy': numeric_policy,
        'navigation_record': navigation_record,
    }


def main():
    parsed = parse_args(sys.argv[1:])
    merged_path = parsed['merged_path']
    manifest_path = parsed['manifest_path']
    toc_path = parsed['toc_path']
    site_root = parsed['site_root']
    src_paths = parsed['src_paths']
    strong_tokens = parsed['strong_tokens']
    approved_extra_math = parsed['approved_extra_math']
    delivery_root = parsed['delivery_root']
    image_map = parsed['image_map']
    image_digests = load_image_digests(image_map) if image_map else None
    official_headings = ()
    if parsed['official_headings_file']:
        # 共享加载器在 CLI 实际调用基点（本进程 cwd）读取
        _path, official_headings = load_official_headings(
            parsed['official_headings_file'])

    with open(manifest_path, encoding='utf-8') as f:
        manifest = [l.strip() for l in f if l.strip()]
    with open(toc_path, encoding='utf-8') as f:
        official = [l.strip() for l in f if l.strip()]
    merged = open(merged_path, encoding='utf-8').read()
    src_texts = [open(p, encoding='utf-8').read() for p in src_paths]

    fails, warns = run_checks(
        merged, os.path.dirname(os.path.abspath(merged_path)),
        manifest, official, site_root, src_texts,
        merged_label=os.path.basename(merged_path),
        delivery_root=delivery_root, image_digests=image_digests,
        approved_extra_math=approved_extra_math,
        strong_tokens=strong_tokens, official_headings=official_headings,
        numeric_review=parsed['numeric_review'],
        numeric_policy=parsed['numeric_policy'],navigation_record=parsed['navigation_record'])

    print('校验: %s' % os.path.basename(merged_path))
    for w in warns:
        print('WARN:', w)
    if fails:
        for f in fails:
            print('FAIL:', f)
        sys.exit(1)
    print('PASS: %d pages, %d fences, %d images%s' % (
        len(manifest),
        sum(1 for _ in re.finditer(r'^```\s*$', merged, re.M)) // 2,
        len([s for page in _split_pages(merged)
             for _, s in image_references(page)]),
        '，来源身份映射一致' if image_digests is not None else '',
    ))


if __name__ == '__main__':
    main()
