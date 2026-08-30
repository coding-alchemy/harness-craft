#!/usr/bin/env python3
"""多页面 API 译文校验脚本。

用法：
    python3 verify_api_translation.py <merged.md> <manifest.txt> <official_toc.txt> <site_root> <src1.md> [<src2.md> ...]

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
from collections import Counter

from bs4 import BeautifulSoup
from _verification import (
    heading_lines,
    image_sources,
    scan_fences,
    strip_chinese_suffix,
)


def _headings(lines):
    """返回 [(级别, 原文)]。"""
    return [
        (level, strip_chinese_suffix(text))
        for level, text in heading_lines('\n'.join(lines))
    ]


def _unnumbered_headings(lines):
    """排除页面首标题后的无编号标题多重集。"""
    hs = _headings(lines)
    if not hs:
        return []
    out = []
    for lvl, t in hs[1:]:
        if not re.match(r'^\d[\d.]*\.?\s', t):
            out.append(t)
    return out


def _resolve_image(site_root, page_rel, src):
    """返回本地图片绝对路径；非本地返回 None。"""
    if not src or re.match(r'^[a-z][a-z0-9+.-]*://', src, re.I):
        return None
    if os.path.isabs(src):
        return None
    return os.path.normpath(os.path.join(site_root, os.path.dirname(page_rel), src))


def _resolve_delivery_image(merged_path, src):
    """按最终 Markdown 所在目录解析交付图片；越界、绝对或外链返回 None。"""
    if not src or re.match(r'^[a-z][a-z0-9+.-]*:', src, re.I):
        return None
    clean = src.split('#', 1)[0].split('?', 1)[0]
    if os.path.isabs(clean):
        return None
    base = os.path.dirname(os.path.abspath(merged_path))
    path = os.path.abspath(os.path.normpath(os.path.join(base, clean)))
    if os.path.commonpath([base, path]) != base:
        return None
    return path


def _image_identity(src):
    """合法本地化允许目录变化，以文件名对账图片身份。"""
    clean = src.split('#', 1)[0].split('?', 1)[0]
    return os.path.basename(clean)


def _check_magic(path):
    """读取魔数；可选调用 file 命令。返回 (ok, msg)。"""
    with open(path, 'rb') as f:
        head = f.read(12)
    magics = [
        (b'\x89PNG\r\n\x1a\n', 'PNG'),
        (b'\xff\xd8\xff', 'JPEG'),
        (b'GIF87a', 'GIF'),
        (b'GIF89a', 'GIF'),
        (b'RIFF', 'WEBP'),  # RIFF....WEBP
    ]
    kind = None
    for m, name in magics:
        if head.startswith(m):
            kind = name
            break
    if kind == 'WEBP' and b'WEBP' not in head[:12]:
        kind = None
    if kind:
        return True, kind
    # 回退到 file 命令
    try:
        out = subprocess.run(['file', '-b', path], capture_output=True, text=True, check=True).stdout
    except Exception:
        return False, 'unknown magic and file unavailable'
    if 'image' in out.lower():
        return True, out.strip().split()[0]
    return False, out.strip()


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
    """按独立一行的 --- 切分合并文件为多页。"""
    pages = []
    cur = []
    for line in text.split('\n'):
        if line.strip() == '---':
            pages.append('\n'.join(cur))
            cur = []
        else:
            cur.append(line)
    pages.append('\n'.join(cur))
    return [p for p in pages if p.strip()]


def main():
    if len(sys.argv) < 6:
        sys.exit(__doc__)
    merged_path = sys.argv[1]
    manifest_path = sys.argv[2]
    toc_path = sys.argv[3]
    site_root = sys.argv[4]
    src_paths = sys.argv[5:]

    fails = []

    with open(manifest_path, encoding='utf-8') as f:
        manifest = [l.strip() for l in f if l.strip()]
    if not manifest:
        sys.exit('empty manifest')

    # 1) 闭合校验：manifest 与独立官方 TOC 快照一致（集合与顺序）
    with open(toc_path, encoding='utf-8') as f:
        official = [l.strip() for l in f if l.strip()]
    if manifest != official:
        missing = [p for p in official if p not in manifest]
        extra = [p for p in manifest if p not in official]
        fails.append('页面清单与官方 TOC 不闭合: 缺失 %s / 多余 %s / 顺序一致=%s'
                     % (missing or '无', extra or '无',
                        missing == [] and extra == [] and manifest == official))

    if len(src_paths) != len(manifest):
        fails.append('源文件数 %d 与清单 %d 不一致' % (len(src_paths), len(manifest)))

    merged = open(merged_path, encoding='utf-8').read()
    trans_pages = _split_pages(merged)
    if len(trans_pages) != len(manifest):
        fails.append('合并文件页数 %d 与清单 %d 不一致' % (len(trans_pages), len(manifest)))

    # 逐页校验
    for idx, page_rel in enumerate(manifest):
        src_text = open(src_paths[idx], encoding='utf-8').read() if idx < len(src_paths) else ''
        trans_text = trans_pages[idx] if idx < len(trans_pages) else ''
        src_lines = src_text.split('\n')
        trans_lines = trans_text.split('\n')

        # 页面标题顺序
        src_titles = _headings(src_lines)
        trans_titles = _headings(trans_lines)
        if src_titles and trans_titles:
            if src_titles[0][1] != trans_titles[0][1]:
                fails.append('页 %s 标题顺序不一致: 源 %r vs 译 %r' % (page_rel, src_titles[0][1], trans_titles[0][1]))

        # 无编号标题多重集
        su = _unnumbered_headings(src_lines)
        tu = _unnumbered_headings(trans_lines)
        if Counter(su) != Counter(tu):
            fails.append('页 %s 无编号标题多重集不一致: 源 %s vs 译 %s' % (page_rel, Counter(su), Counter(tu)))

        # 代码围栏
        source_fences = scan_fences(src_text)
        translated_fences = scan_fences(trans_text)
        if not source_fences.balanced:
            fails.append('页 %s 源文围栏不配对' % page_rel)
        if not translated_fences.balanced:
            fails.append('页 %s 译文围栏不配对' % page_rel)
        if len(source_fences.blocks) != len(translated_fences.blocks):
            fails.append('页 %s 代码块数不一致: 源 %d vs 译 %d' % (
                page_rel, len(source_fences.blocks),
                len(translated_fences.blocks)))
        else:
            for i, (s, t) in enumerate(zip(
                    source_fences.blocks, translated_fences.blocks)):
                if s != t:
                    fails.append('页 %s 代码块 #%d 内容不一致' % (page_rel, i + 1))

        # 图片数量/顺序
        src_imgs = image_sources(src_text)
        trans_imgs = image_sources(trans_text)
        if ([_image_identity(s) for s in src_imgs] !=
                [_image_identity(s) for s in trans_imgs]):
            fails.append('页 %s 图片列表不一致: 源 %s vs 译 %s' % (page_rel, src_imgs, trans_imgs))

        # 最终交付目录中的图片存在性与魔数
        for src in trans_imgs:
            p = _resolve_delivery_image(merged_path, src)
            if not p:
                fails.append('页 %s 图片不是交付目录内的相对路径: %s' % (page_rel, src))
                continue
            if not os.path.exists(p):
                fails.append('页 %s 交付图片缺失: %s' % (page_rel, src))
                continue
            ok, info = _check_magic(p)
            if not ok:
                fails.append('页 %s 图片魔数异常 %s: %s' % (page_rel, src, info))

        # 暗亮图片对只计一次：HTML 实际可见数应等于译文图片数
        html_visible = _visible_html_images(site_root, page_rel)
        if len(trans_imgs) != len(html_visible):
            fails.append('页 %s 暗亮图片计数异常: HTML 可见 %d vs 译文 %d' % (page_rel, len(html_visible), len(trans_imgs)))

    print('校验: %s' % os.path.basename(merged_path))
    if fails:
        for f in fails:
            print('FAIL:', f)
        sys.exit(1)
    print('PASS: %d pages, %d fences, %d images' % (
        len(manifest),
        sum(1 for _ in re.finditer(r'^```\s*$', merged, re.M)) // 2,
        len(image_sources(merged)),
    ))


if __name__ == '__main__':
    main()
