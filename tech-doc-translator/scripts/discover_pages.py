#!/usr/bin/env python3
"""多页面 API/DSL 站点的页面发现脚本。

用法：
    python3 discover_pages.py <entry.html> <manifest.txt>

从入口 HTML 递归提取 <a class="reference internal"> 的相对链接，规范化路径、去掉锚点，
限制在站点目录内，直到页面清单不再增长。输出每行一个相对路径（按字典序）。
"""
import os
import re
import sys

from bs4 import BeautifulSoup


_HTML_EXTS = {'.html', '.htm'}


def _is_external(href):
    if not href:
        return True
    if href.startswith('#') or href.startswith('mailto:') or href.startswith('javascript:'):
        return True
    if re.match(r'^[a-z][a-z0-9+.-]*://', href, re.I):
        return True
    return False


def _internal_links(html_path, site_dir):
    """返回 html_path 页中范围内 HTML 链接的规范化相对路径集合。"""
    rel_dir = os.path.dirname(os.path.relpath(html_path, site_dir))
    raw = open(html_path, encoding='utf-8').read()
    soup = BeautifulSoup(raw, 'html.parser')
    found = set()
    for a in soup.find_all('a', class_='reference internal'):
        href = (a.get('href') or '').strip()
        if _is_external(href):
            continue
        # 去掉锚点
        href = href.split('#')[0]
        # 跳过纯 query / 绝对路径
        if not href or href.startswith('?'):
            continue
        if os.path.isabs(href):
            continue
        target = os.path.normpath(os.path.join(site_dir, rel_dir, href))
        if not os.path.commonpath([target, site_dir]) == site_dir:
            continue
        if os.path.isfile(target) and os.path.splitext(target)[1].lower() in _HTML_EXTS:
            found.add(os.path.relpath(target, site_dir))
    return found


def discover(entry_path):
    """返回从 entry_path 发现的规范化相对路径列表（含入口本身）。"""
    entry_abs = os.path.abspath(entry_path)
    site_dir = os.path.dirname(entry_abs)
    entry_rel = os.path.relpath(entry_abs, site_dir)

    manifest = {entry_rel}
    queue = [entry_rel]
    while queue:
        cur = queue.pop(0)
        for nxt in _internal_links(os.path.join(site_dir, cur), site_dir):
            if nxt not in manifest:
                manifest.add(nxt)
                queue.append(nxt)
    return sorted(manifest)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    entry_path, out_path = sys.argv[1], sys.argv[2]
    pages = discover(entry_path)
    with open(out_path, 'w', encoding='utf-8') as f:
        for p in pages:
            f.write(p + '\n')
    print('discovered %d pages -> %s' % (len(pages), out_path))


if __name__ == '__main__':
    main()
