#!/usr/bin/env python3
"""把分节翻译后的工作文件合并成一个章节文件。

用法：
    python3 merge_sections.py -o chapter.md header.md sec1.md sec2.md ...

- 第一个文件是章节头（译例说明/目录/导读），标题层级不降级；
- 其余为各节工作文件：标题整体降一级（#→##…，最深不超过 H6），
  删除面包屑导航行（如 "> 第 N 章…" 或 "> 译自官方…"）；
- 节间以 --- 分隔。
- 全程感知代码围栏，围栏内不做任何改写或空白压缩。
"""
import re
import argparse

_BREADCRUMB = re.compile(r'^> 第 \d+ 章|^> 译自官方')


def load(path, demote):
    out, infence = [], False
    for raw_line in open(path, encoding='utf-8').read().split('\n'):
        s = raw_line.strip()
        if s.startswith('```'):
            infence = not infence
            out.append(raw_line)
            continue
        if not infence:
            if _BREADCRUMB.match(s):
                continue
            if demote and re.match(r'^#{1,5} ', s):
                raw_line = '#' + raw_line
        out.append(raw_line)
    return re.sub(r'^\n+', '', '\n'.join(out)).rstrip() + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('files', nargs='+', help='第一个为章节头，其余为各节文件（按文档顺序）')
    a = ap.parse_args()

    parts = [load(a.files[0], demote=False)] + [load(f, demote=True) for f in a.files[1:]]
    merged = '\n\n---\n\n'.join(parts) + '\n'
    open(a.out, 'w', encoding='utf-8').write(merged)
    print('合并完成: %s, %d 字符, %d 节' % (a.out, len(merged), len(a.files) - 1))


if __name__ == '__main__':
    main()
