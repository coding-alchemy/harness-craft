#!/usr/bin/env python3
"""官方标题原题文件的共享选项解析与最小加载器（设计 D5）。

四类 HTML 译文检查共用同一份 `--official-headings-file <文件>` 选项与
文件语法：UTF-8，按行读原题，移除行结束符与首尾排版空白，忽略空行，
保留内部字符、行首 `#`、重复原题与顺序；不解析注释、编号或层级。
缺文件、不可读、坏 UTF-8、空清单、选项缺值、空路径、重复声明均明确失败，
不降级为未提供官方基准。

路径角色由真实 parse_args 返回 `official_headings_file`；共享加载器在
CLI 实际调用基点读取（独立 CLI 相对路径按调用 cwd，交付复验按明确
交付根解释），不在 parse_args 阶段依进程 cwd 读文件。
"""
import os
import sys

from _verification import file_sha256, heading_title_matches

OPTION = '--official-headings-file'

# 各家族官方原题清单的确认范围口径（加载后随检查事实登记，进入交付
# 身份与复核绑定）：官方文件是纯原题清单，层级仍由原 HTML→解析及
# 源→译文独立有序检查证明，这里只描述原题对照的适用范围。
SCOPE_BY_TOOL = {
    'verify_translation': 'full-doc-order',
    'verify_reference_translation': 'full-doc-order',
    'verify_paginated_translation': 'assembly:skip-head-1',
    'verify_api_translation': 'manifest-page-order',
}


def extract_official_headings_option(argv):
    """从 argv 摘除 --official-headings-file <文件>（仅接受一份）。

    返回 (剩余 argv, 文件路径或 None)。缺值、空路径与重复声明均明确
    失败：显式空值不降级为未提供官方基准（设计 D5/§7.7）。
    """
    path = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == OPTION:
            if path is not None:
                sys.exit('重复声明官方标题文件: %s（仅接受一份）FAIL' % OPTION)
            if i + 1 >= len(argv):
                sys.exit('官方标题文件选项缺值: %s <文件> FAIL' % OPTION)
            path = argv[i + 1]
            if not path:
                sys.exit('官方标题文件路径为空: %s <文件> FAIL'
                         '（显式空值不降级为未提供官方基准）' % OPTION)
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest, path


def load_official_headings(path, base_dir=None):
    """按 D5 文件语法读取官方原题清单。

    base_dir 为相对路径的解释基点：独立 CLI 传 None（调用 cwd），
    交付复验传明确交付根。返回 (规范化绝对路径, 有效原题列表)。
    缺失、不可读、坏 UTF-8、空清单均明确失败，不降级。
    """
    if base_dir is not None and not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    abs_path = os.path.realpath(path)
    try:
        with open(abs_path, 'rb') as handle:
            raw = handle.read()
    except OSError:
        sys.exit('官方标题文件缺失或不可读: %s FAIL（不提供官方基准降级）'
                 % path)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        sys.exit('官方标题文件不是有效 UTF-8: %s FAIL' % path)
    titles = []
    for line in text.splitlines():
        title = line.strip()
        if title:
            titles.append(title)
    if not titles:
        sys.exit('官方标题文件清单为空: %s FAIL（空清单不降级为未提供基准）'
                 % path)
    return abs_path, titles


def official_headings_identity(path, base_dir=None):
    """标题文件依赖身份：规范化路径 + 内容摘要 + 加载后的有效原题。

    同路径改内容使摘要与有效原题同时变化，相关旧复核失效；只记录
    参数字符串不算数。文件缺失/语法无效时摘要/原题记 None（绑定按
    不完整拒绝），由 CLI 复验失败另行定位。
    """
    abs_path, digest, titles = None, None, None
    try:
        if base_dir is not None and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        abs_path = os.path.realpath(path)
        if os.path.isfile(abs_path):
            digest = file_sha256(abs_path)
            try:
                _p, titles = load_official_headings(abs_path)
            except SystemExit:
                titles = None
    except OSError:
        abs_path, digest, titles = None, None, None
    return abs_path, digest, titles


def official_titles_diff(official, got_titles):
    """官方原题按序逐项对照译文标题原题，返回差异描述或 None。

    对照口径与逐项官方原题输入一致：数量相等且每条按
    heading_title_matches（空白归一 + 可选（中文）后缀）顺序匹配。
    """
    if len(got_titles) == len(official) and all(
            heading_title_matches(expected, got)
            for expected, got in zip(official, got_titles)):
        return None
    return '译文 %d 条 vs 官方 %d 条' % (len(got_titles), len(official))
