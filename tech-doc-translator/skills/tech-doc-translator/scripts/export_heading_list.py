#!/usr/bin/env python3
"""从显式源 Markdown 导出标题工作清单（设计 D5，围栏感知）。

用法：
    python3 export_heading_list.py <源.md> <输出.txt>

复用共享 heading_entries：每行一个原题写入显式独立输出路径（不覆盖
输入源）；较长反引号、波浪线围栏及行内代码内的标题样式注释不导出。
源围栏不配对（未闭合）时给出明确诊断并拒绝导出，不把隐藏了后半篇
内容的清单声称为完整。清单只是任务准备数据，不自动成为官方基准；
官方标题基准须来自已确认权威原始来源。
"""
import os
import sys

from _verification import file_sha256, heading_entries, scan_code_fences


def export_heading_list(source_path, output_path):
    """从显式源 Markdown 导出每行一个原题的工作清单，返回原题列表。

    输出路径必须独立于输入源（不覆盖源）；未闭合围栏明确诊断并拒绝。
    """
    if os.path.realpath(source_path) == os.path.realpath(output_path):
        sys.exit('输出路径必须独立于输入源，不得覆盖源: %s FAIL' % output_path)
    text = open(source_path, encoding='utf-8').read()
    fences = scan_code_fences(text)
    if not fences.balanced:
        sys.exit('源 Markdown 围栏不配对: 第 %d 行开启的代码块未闭合，'
                 '标题工作清单可能隐藏了围栏内及后续内容，拒绝导出并'
                 '不声称清单完整 FAIL' % fences.unclosed_line)
    titles = [title for _, _, title in heading_entries(text)]
    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(titles))
        if titles:
            handle.write('\n')
    return titles


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    source_path, output_path = sys.argv[1:3]
    titles = export_heading_list(source_path, output_path)
    print('OK: %s 导出 %d 条标题工作清单（源摘要 %s…，清单仅供任务准备）'
          % (output_path, len(titles), file_sha256(source_path)[:12]))


if __name__ == '__main__':
    main()
