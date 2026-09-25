#!/usr/bin/env python3
"""多页面 API 译文校验脚本。

用法：
    python3 verify_api_translation.py <merged.md> <manifest.txt> <official_toc.txt> <site_root> <src1.md> [<src2.md> ...]
        [--approved-extra-math <表达式>]...

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
"""
import os
import re
import subprocess
import sys

from bs4 import BeautifulSoup
from _verification import (
    check_image_file,
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_strong_tokens,
    fenced_line_numbers,
    heading_entries,
    image_occurrence_fails,
    image_references,
    load_image_digests,
    resource_identity_digest,
    resolve_delivery_image,
    scan_code_fences,
    scan_math_spans,
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
    """从原始 HTML 统计应交付的图片：暗亮对只计一个。"""
    path = os.path.join(site_root, page_rel)
    soup = BeautifulSoup(open(path, encoding='utf-8').read(), 'html.parser')
    imgs = soup.find_all('img')
    # 分组：figure 内图片优先按容器去重，其余单独计数
    seen = set()
    visible = []
    for fig in soup.find_all('figure'):
        fig_imgs = fig.find_all('img')
        light = [i for i in fig_imgs if i.get('data-light') or 'only-light' in ' '.join(i.get('class') or [])]
        dark = [i for i in fig_imgs if i.get('data-dark') or 'only-dark' in ' '.join(i.get('class') or [])]
        if light:
            visible.append(_resolve_image(site_root, page_rel, _image_src(light[0])))
        elif dark:
            visible.append(_resolve_image(site_root, page_rel, _image_src(dark[0])))
        else:
            for i in fig_imgs:
                visible.append(_resolve_image(site_root, page_rel, _image_src(i)))
        for i in fig_imgs:
            seen.add(id(i))
    for i in imgs:
        if id(i) not in seen:
            visible.append(_resolve_image(site_root, page_rel, _image_src(i)))
    return [v for v in visible if v]


def _image_src(img):
    if img.get('data-light'):
        return img['data-light']
    return img.get('src', '')


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
               strong_tokens=()):
    """多页 API 检查核心：接收候选文本与实际目标目录，返回失败诊断列表。

    merged_text 可来自工作区外临时候选（草稿预检）；merged_dir 必须是
    最终 Markdown 目录——图片按最终目标路径定位，不按候选临时路径定位。
    """
    fails = []

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

        # 公式逐项核对（类型/顺序/原表达式）
        src_math = scan_math_spans(src_text)
        doc_math = scan_math_spans(trans_text)
        math_diffs, _ = compare_math_spans(
            src_math, doc_math, src_label, doc_label,
            approved_extra_exprs=approved_extra_math, doc_text=trans_text)
        for diff in math_diffs:
            fails.append('页 %s 公式逐项核对: %s' % (page_rel, diff))

        # 强 token（项目显式指定；未配置时明示未检查）
        token_diffs, _ = strong_token_report(src_text, trans_text,
                                             strong_tokens,
                                             src_label, doc_label)
        if token_diffs is not None:
            for diff in token_diffs:
                fails.append('页 %s 强 token %s' % (page_rel, diff))

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
    return fails


def parse_args(argv):
    """解析既有 CLI 参数，返回语义结构（本 CLI 的单一解释入口）。"""
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, strong_tokens = extract_strong_tokens(argv)
    argv, image_map, delivery_root = extract_image_options(argv)
    if len(argv) < 6:
        sys.exit(__doc__)
    return {
        'merged_path': argv[0],
        'manifest_path': argv[1],
        'toc_path': argv[2],
        'site_root': argv[3],
        'src_paths': list(argv[4:]),
        'strong_tokens': strong_tokens,
        'approved_extra_math': approved_extra_math,
        'image_map': image_map,
        'delivery_root': delivery_root,
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

    with open(manifest_path, encoding='utf-8') as f:
        manifest = [l.strip() for l in f if l.strip()]
    with open(toc_path, encoding='utf-8') as f:
        official = [l.strip() for l in f if l.strip()]
    merged = open(merged_path, encoding='utf-8').read()
    src_texts = [open(p, encoding='utf-8').read() for p in src_paths]

    fails = run_checks(
        merged, os.path.dirname(os.path.abspath(merged_path)),
        manifest, official, site_root, src_texts,
        merged_label=os.path.basename(merged_path),
        delivery_root=delivery_root, image_digests=image_digests,
        approved_extra_math=approved_extra_math,
        strong_tokens=strong_tokens)

    print('校验: %s' % os.path.basename(merged_path))
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
