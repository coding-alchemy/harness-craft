#!/usr/bin/env python3
"""将源 Markdown 拆分为可独立翻译、可无损还原的工作包。

用法：
    python3 split_work_packages.py <source.md> <wps_dir> <trans_dir> [strategy]

strategy:
    h2              按 H2 小节切分（默认）
    chars:<N>       N 为目标体量（已批准 D1）：优先整节组包，超限小节在
                    安全块边界细分；单个不可拆块（代码围栏、公式、表格、
                    列表等）超限时保留整包并在报告中说明实际体量与范围

结构边界与依赖：
    - 代码围栏（含长反引号/波浪线）、行内/块级公式、表格、段落、列表
      （含嵌套子项）、引用、定义与脚注定义均为原子块，切点只落在块间；
    - 脚注、普通引用链接与引用式图片的定义按引用依赖扩大连续范围，
      跨节依赖合并相邻范围，引用与定义不会被拆进不同包；
    - 图片与其后的图题段落绑定，不在切点两侧分离；
    - 代码围栏内的标题、分隔线、美元符号、图片语法不参与结构识别。

frontmatter 在既有 source_file / target_file / source_order / rules_path /
section_id / fragment_index 基础上补充：strategy / section_instance（同名
小节按实例区分）/ source_line_start-end / source_char_start-end（包正文
在源文件中的确切范围，字符区间含首不含尾）/ fragment_digest（包正文
sha256）/ content_blocks（headings、paragraphs、list_items、tables、
code_fences 计数）。续片正文是真实源切片，不注入重复标题；小节上下文
只存在于元数据。

拆分后脚本自检：包区间无重叠无缺口、按 source_order 还原与源逐字节一致；
自检失败时不写出任何工作包。源与译文目标必须分离，重复拆包不改写译文。
"""
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _verification import fenced_line_numbers

_SKILL_DIR = Path(__file__).resolve().parent.parent
_RULES_PATH = str(_SKILL_DIR / "references" / "translation_conventions.md")

_HEADING_RE = re.compile(r'^#{1,6}\s+')
_H2_RE = re.compile(r'^##\s+(?!#)')
_LIST_RE = re.compile(r'^\s*(?:[*+-]\s+|\d+[.)]\s+)')
_TABLE_RE = re.compile(r'^\|')
_QUOTE_RE = re.compile(r'^>')
_FOOTNOTE_DEF_RE = re.compile(r'^\[\^([^\]]+)\]:')
_FOOTNOTE_REF_RE = re.compile(r'\[\^([^\]\s]+)\](?!:)')
_LINK_DEF_RE = re.compile(r'^\[([^\]^][^\]]*)\]:\s*\S+')
_IMG_REF_LABEL_RE = re.compile(r'!\[[^\]]*\]\[([^\]]+)\]')
_LINK_REF_LABEL_RE = re.compile(r'(?<!!)\[(?:\\.|[^\\\]])*\]\[([^\]]+)\]')
_BLOCK_MARK_RE = re.compile(r'^\[[A-Z][A-Z0-9_-]*\]\s*$')
_IMAGE_LINE_RE = re.compile(r'^\s*!\[')
_CAPTION_RE = re.compile(r'^\s*\*\*\s*(?:图|Figure|Fig)')


class Block:
    """一个原子结构块；start/end 为 0 起含端行号。"""

    def __init__(self, kind, start, end):
        self.kind = kind
        self.start = start
        self.end = end

    def __repr__(self):
        return 'Block(%s, %d-%d)' % (self.kind, self.start, self.end)


class _Unit:
    """依赖闭包后的连续不可拆范围。"""

    def __init__(self, start, end, merged_count=1):
        self.start = start
        self.end = end
        self.merged_count = merged_count


def _parse_blocks(lines, fenced):
    """把行序列切成原子块，覆盖全部非空行；返回按起点排序的 Block 列表。"""
    blocks = []
    n = len(lines)
    i = 0
    while i < n:
        line_no = i + 1
        if line_no in fenced:
            j = i
            while j < n and (j + 1) in fenced:
                j += 1
            blocks.append(Block('code_fence', i, j))
            i = j + 1
            continue
        s = lines[i].strip()
        if s == '':
            i += 1
            continue
        if _HEADING_RE.match(lines[i]):
            blocks.append(Block('heading', i, i))
            i += 1
            continue
        if _FOOTNOTE_DEF_RE.match(s):
            j = i
            while j + 1 < n:
                nxt = lines[j + 1]
                if nxt.strip() == '':
                    cont = j + 2 < n and (j + 3) not in fenced and (
                        lines[j + 2].startswith('  ')
                        or lines[j + 2].startswith('\t'))
                    if cont:
                        j += 2
                        continue
                    break
                if nxt.startswith('  ') or nxt.startswith('\t'):
                    j += 1
                    continue
                break
            blocks.append(Block('footnote_def', i, j))
            i = j + 1
            continue
        if _BLOCK_MARK_RE.match(s):
            j = i
            while (j + 1 < n and lines[j + 1].strip() != ''
                   and (j + 2) not in fenced
                   and not _HEADING_RE.match(lines[j + 1])):
                j += 1
            blocks.append(Block('block_marker', i, j))
            i = j + 1
            continue
        if _TABLE_RE.match(s):
            j = i
            while j + 1 < n and _TABLE_RE.match(lines[j + 1].strip()):
                j += 1
            blocks.append(Block('table', i, j))
            i = j + 1
            continue
        if _QUOTE_RE.match(s):
            j = i
            while j + 1 < n and _QUOTE_RE.match(lines[j + 1].strip()):
                j += 1
            blocks.append(Block('blockquote', i, j))
            i = j + 1
            continue
        if _LIST_RE.match(s):
            j = i
            while j + 1 < n:
                nxt = lines[j + 1]
                if nxt.strip() == '':
                    cont = j + 2 < n and (
                        lines[j + 2].startswith(' ')
                        or lines[j + 2].startswith('\t'))
                    if cont:
                        j += 2
                        continue
                    break
                if _LIST_RE.match(nxt) or nxt.startswith(' ') or nxt.startswith('\t'):
                    j += 1
                    continue
                break
            blocks.append(Block('list', i, j))
            i = j + 1
            continue
        j = i
        while (j + 1 < n and lines[j + 1].strip() != ''
               and (j + 2) not in fenced
               and not _HEADING_RE.match(lines[j + 1])
               and not _LIST_RE.match(lines[j + 1])
               and not _TABLE_RE.match(lines[j + 1].strip())
               and not _QUOTE_RE.match(lines[j + 1].strip())
               and not _FOOTNOTE_DEF_RE.match(lines[j + 1].strip())
               and not _BLOCK_MARK_RE.match(lines[j + 1].strip())):
            j += 1
        blocks.append(Block('paragraph', i, j))
        i = j + 1

    # 图片与其后的图题段落绑定为一个原子块
    bound = []
    k = 0
    while k < len(blocks):
        block = blocks[k]
        nxt = blocks[k + 1] if k + 1 < len(blocks) else None
        if (block.kind == 'paragraph'
                and any(_IMAGE_LINE_RE.match(lines[p])
                        for p in range(block.start, block.end + 1))
                and nxt is not None and nxt.kind == 'paragraph'
                and _CAPTION_RE.match(lines[nxt.start])):
            bound.append(Block('figure', block.start, nxt.end))
            k += 2
            continue
        bound.append(block)
        k += 1
    return bound


def _footnote_labels(lines, start, end, fenced):
    """行区间内引用与定义的脚注标签（排除围栏内行）。"""
    refs, defs = set(), set()
    for p in range(start, end + 1):
        if (p + 1) in fenced:
            continue
        refs.update(_FOOTNOTE_REF_RE.findall(lines[p]))
        m = _FOOTNOTE_DEF_RE.match(lines[p].strip())
        if m:
            defs.add(m.group(1))
    return refs, defs


def _merge_overlapping(units):
    """把真正重叠的连续范围合并（相邻不算重叠），直到稳定。"""
    units = sorted(units, key=lambda u: (u.start, u.end))
    merged = []
    for unit in units:
        if merged and unit.start <= merged[-1].end:
            prev = merged[-1]
            prev.end = max(prev.end, unit.end)
        else:
            merged.append(unit)
    return merged


def _link_ref_labels(lines, start, end, fenced):
    """行区间内普通引用链接与引用式图片的标签（排除围栏内行，小写归一）。"""
    labels = set()
    for p in range(start, end + 1):
        if (p + 1) in fenced:
            continue
        for m in _IMG_REF_LABEL_RE.finditer(lines[p]):
            labels.add(m.group(1).strip().lower())
        for m in _LINK_REF_LABEL_RE.finditer(lines[p]):
            labels.add(m.group(1).strip().lower())
    return labels


def _dependency_units(lines, fenced, seeds):
    """对 seed 范围做脚注与引用链接依赖闭包并合并重叠，返回连续 _Unit 列表。

    引用了其他范围中定义的脚注，或普通引用链接/引用式图片的定义落在
    其他范围时，相关范围合并为更大的连续范围；引用与定义不拆进不同包。
    """
    def_ranges = {}
    for p, line in enumerate(lines):
        if (p + 1) in fenced:
            continue
        m = _FOOTNOTE_DEF_RE.match(line.strip())
        if m:
            def_ranges.setdefault(m.group(1), []).append(p)
            continue
        m = _LINK_DEF_RE.match(line.strip())
        if m:
            def_ranges.setdefault(m.group(1).strip().lower(), []).append(p)

    parent = list(range(len(seeds)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for idx, (start, end) in enumerate(seeds):
        refs, defs = _footnote_labels(lines, start, end, fenced)
        wanted = (refs - defs) | _link_ref_labels(lines, start, end, fenced)
        for label in wanted:
            for def_line in def_ranges.get(label, []):
                for jdx, (s2, e2) in enumerate(seeds):
                    if s2 <= def_line <= e2:
                        union(idx, jdx)
    groups = {}
    for idx in range(len(seeds)):
        groups.setdefault(find(idx), []).append(idx)
    units = []
    for members in groups.values():
        units.append(_Unit(
            min(seeds[i][0] for i in members),
            max(seeds[i][1] for i in members),
            len(members)))
    return _merge_overlapping(units)


def _parse_sections(lines, fenced):
    """按真实 H2 小节划分；返回 [(section_id, instance, start, end)]。

    start/end 为 0 起含端行号，范围覆盖全部行；导语区仅含 H1 与空白时
    并入第一个 H2 小节，含实质导语时自成 '[top]' 小节；同名小节按
    instance（1 起）区分。
    """
    n = len(lines)
    h2_lines = [p for p in range(n)
                if (p + 1) not in fenced and _H2_RE.match(lines[p])]
    if not h2_lines:
        title = '[top]'
        for p in range(n):
            if (p + 1) not in fenced and lines[p].startswith('# '):
                title = lines[p].lstrip('#').strip()
                break
        return [(title, 1, 0, n - 1)]

    first = h2_lines[0]
    non_blank = [lines[p] for p in range(0, first) if lines[p].strip()]
    preamble_trivial = (not non_blank) or (
        len(non_blank) == 1 and non_blank[0].startswith('# '))

    cuts = list(h2_lines)
    if not preamble_trivial:
        cuts.insert(0, 0)

    out = []
    seen = {}
    for k, cut in enumerate(cuts):
        start = 0 if (k == 0 and preamble_trivial) else cut
        end = (cuts[k + 1] - 1) if k + 1 < len(cuts) else n - 1
        sid = '[top]' if (cut == 0 and not preamble_trivial) \
            else lines[cut].lstrip('#').strip()
        seen[sid] = seen.get(sid, 0) + 1
        out.append((sid, seen[sid], start, end))
    return out


def _span_text(lines, start, end):
    return '\n'.join(lines[start:end + 1])


def _char_range(lines, start, end):
    """行区间 [start, end]（0 起含端）的字符偏移；区间含首不含尾。"""
    char_start = sum(len(lines[p]) + 1 for p in range(start))
    char_end = char_start + sum(
        len(lines[p]) + 1 for p in range(start, end)) + len(lines[end])
    return char_start, char_end


def _count_units(lines, start, end, fenced):
    """基于块解析的结构计数（headings/paragraphs/list_items/tables/code_fences）。"""
    blocks = _parse_blocks(lines, fenced)
    counts = {'headings': 0, 'paragraphs': 0, 'list_items': 0,
              'tables': 0, 'code_fences': 0}
    for b in blocks:
        if b.end < start or b.start > end:
            continue
        if b.kind == 'heading':
            counts['headings'] += 1
        elif b.kind in ('paragraph', 'figure', 'blockquote', 'block_marker'):
            counts['paragraphs'] += 1
        elif b.kind == 'table':
            counts['tables'] += 1
        elif b.kind == 'code_fence':
            counts['code_fences'] += 1
        elif b.kind == 'list':
            counts['list_items'] += sum(
                1 for p in range(b.start, b.end + 1)
                if (p + 1) not in fenced and _LIST_RE.match(lines[p]))
    return counts


def _count_blocks(lines):
    """兼容旧接口：统计 headings / paragraphs / list_items / code_fences / tables。"""
    if isinstance(lines, (list, tuple)):
        text = '\n'.join(lines)
    else:
        text = lines
    doc_lines = text.split('\n')
    return _count_units(doc_lines, 0, len(doc_lines) - 1,
                        fenced_line_numbers(text))


def _unit_kind(lines, fenced, unit):
    blocks = [b for b in _parse_blocks(lines, fenced)
              if b.start >= unit.start and b.end <= unit.end]
    if len(blocks) == 1:
        return blocks[0].kind
    return '依赖闭包'


def _candidates(lines, fenced, units, strategy, max_chars):
    """把每个依赖闭包范围展开为候选包范围 (start, end, fragment_index, over_limit)。"""
    candidates = []
    over_limit_reports = []
    for unit in units:
        size = len(_span_text(lines, unit.start, unit.end))
        if strategy == 'h2' or size <= max_chars:
            candidates.append((unit.start, unit.end, 0, False))
            continue
        blocks = [b for b in _parse_blocks(lines, fenced)
                  if b.start >= unit.start and b.end <= unit.end]
        groups = _dependency_units(
            lines, fenced, [(b.start, b.end) for b in blocks])
        # 仅含标题的块组并入其后内容组：标题不单独成片
        heading_only = []
        for k, grp in enumerate(groups):
            blk = [b for b in blocks
                   if b.start >= grp.start and b.end <= grp.end]
            if blk and all(b.kind == 'heading' for b in blk):
                heading_only.append(k)
        for k in reversed(heading_only):
            if k + 1 < len(groups):
                groups[k + 1].start = groups[k].start
                del groups[k]
            elif groups:
                # 末尾孤立标题并入前一组
                groups[k - 1].end = groups[k].end
                del groups[k]
        for k in range(len(groups) - 1):
            groups[k].end = groups[k + 1].start - 1
        groups[-1].end = unit.end
        fragment_index = 0
        current = None
        for grp in groups:
            grp_size = len(_span_text(lines, grp.start, grp.end))
            if grp_size > max_chars:
                over_limit_reports.append(
                    '行 %d-%d 因单个不可拆块（%s）超限保留整包: 实际 %d 字符（目标 %d）'
                    % (grp.start + 1, grp.end + 1,
                       _unit_kind(lines, fenced, grp), grp_size, max_chars))
                if current is not None:
                    candidates.append((current[0], current[1],
                                       fragment_index, False))
                    fragment_index += 1
                    current = None
                candidates.append((grp.start, grp.end, fragment_index, True))
                fragment_index += 1
                continue
            if current is None:
                current = [grp.start, grp.end]
            elif (len(_span_text(lines, current[0], current[1]))
                  + grp_size + 1 > max_chars):
                candidates.append((current[0], current[1], fragment_index, False))
                fragment_index += 1
                current = [grp.start, grp.end]
            else:
                current[1] = grp.end
        if current is not None:
            candidates.append((current[0], current[1], fragment_index, False))
    return candidates, over_limit_reports


def split(source_path, out_dir, trans_dir, strategy):
    if not os.path.isfile(source_path):
        sys.exit('源文件不存在: %s' % source_path)
    if strategy != 'h2' and not strategy.startswith('chars:'):
        sys.exit('未知拆分策略: %s（支持 h2 或 chars:N）' % strategy)
    if strategy.startswith('chars:'):
        try:
            max_chars = int(strategy.split(':', 1)[1])
        except ValueError:
            sys.exit('chars:N 的 N 必须为正整数')
        if max_chars <= 0:
            sys.exit('chars:N 的 N 必须为正整数')
    else:
        max_chars = 0

    source_abs = os.path.abspath(source_path)
    out_abs = os.path.abspath(out_dir)
    trans_abs = os.path.abspath(trans_dir)
    if out_abs == trans_abs:
        sys.exit('工作包目录与译文目标目录相同，输入与译文目标必须分离: %s' % out_dir)
    if source_abs.startswith(out_abs + os.sep) or source_abs.startswith(trans_abs + os.sep):
        sys.exit('源文件位于输出/译文目录内，可能被覆盖: %s' % source_path)

    doc = open(source_path, encoding='utf-8').read()
    lines = doc.split('\n')
    fenced = fenced_line_numbers(doc)

    sections = _parse_sections(lines, fenced)
    units = _dependency_units(lines, fenced,
                              [(s, e) for _, _, s, e in sections])
    candidates, over_limit_reports = _candidates(
        lines, fenced, units, strategy, max_chars)

    # chars 策略下把候选范围按目标体量组包；超限范围独立成包且不再吸收后续内容
    packages = []
    if strategy == 'h2':
        packages = [{'start': s, 'end': e, 'fragments': [(f, over)]}
                    for s, e, f, over in candidates]
    else:
        current = None
        for start, end, fragment_index, over in candidates:
            make_new = (current is None or current['fragments'][-1][1]
                        or over
                        or len(_span_text(lines, current['start'], current['end']))
                        + len(_span_text(lines, start, end)) + 1 > max_chars)
            if make_new:
                if current is not None:
                    packages.append(current)
                current = {'start': start, 'end': end,
                           'fragments': [(fragment_index, over)]}
            else:
                current['end'] = end
                current['fragments'].append((fragment_index, over))
        if current is not None:
            packages.append(current)

    section_of_line = {}
    for sid, instance, s, e in sections:
        for p in range(s, e + 1):
            section_of_line[p] = (sid, instance)

    # 自检：范围无重叠无缺口 + 按序还原与源逐字节一致；失败不写出任何文件
    for k in range(len(packages) - 1):
        if packages[k]['end'] + 1 != packages[k + 1]['start']:
            sys.exit('拆分自检失败: 包范围存在缺口或重叠: %s' % packages)
    if packages and (packages[0]['start'] != 0
                     or packages[-1]['end'] != len(lines) - 1):
        sys.exit('拆分自检失败: 包范围未覆盖全文')
    bodies = [_span_text(lines, p['start'], p['end']) for p in packages]
    if '\n'.join(bodies) != doc:
        sys.exit('拆分自检失败: 按序还原与源不一致')

    if not os.path.isdir(out_abs):
        os.makedirs(out_abs)
    if not os.path.isdir(trans_abs):
        os.makedirs(trans_abs)

    written = []
    for index, (pkg, body) in enumerate(zip(packages, bodies), start=1):
        start, end = pkg['start'], pkg['end']
        sid, instance = section_of_line.get(start, ('[top]', 1))
        fragment_index = pkg['fragments'][0][0]
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        char_start, char_end = _char_range(lines, start, end)
        counts = _count_units(lines, start, end, fenced)
        target_abs = os.path.join(trans_abs, 'wp_%03d.md' % index)
        header = _make_header(source_abs, target_abs, index, strategy, sid,
                              instance, fragment_index, start, end,
                              char_start, char_end, digest, counts)
        path = os.path.join(out_abs, 'wp_%03d.md' % index)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(header)
            f.write(body)
        written.append(path)

    for report in over_limit_reports:
        print('注意: %s' % report)
    print('已生成 %d 个工作包到 %s（译文目标目录 %s）' % (len(written), out_abs, trans_abs))
    return written


def _make_header(source_path, target_path, source_order, strategy, section_id,
                 section_instance, fragment_index, line_start, line_end,
                 char_start, char_end, digest, counts):
    lines = [
        "---",
        "source_file: %s" % source_path,
        "target_file: %s" % target_path,
        "source_order: %d" % source_order,
        "strategy: %s" % strategy,
        "content_blocks:",
        "  headings: %d" % counts['headings'],
        "  paragraphs: %d" % counts['paragraphs'],
        "  list_items: %d" % counts['list_items'],
        "  tables: %d" % counts['tables'],
        "  code_fences: %d" % counts['code_fences'],
        "rules_path: %s" % _RULES_PATH,
        "section_id: \"%s\"" % section_id,
        "section_instance: %d" % section_instance,
        "fragment_index: %d" % fragment_index,
        "source_line_start: %d" % (line_start + 1),
        "source_line_end: %d" % (line_end + 1),
        "source_char_start: %d" % char_start,
        "source_char_end: %d" % char_end,
        "fragment_digest: %s" % digest,
        "---",
        "",
    ]
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        sys.exit(__doc__)
    source_path = sys.argv[1]
    out_dir = sys.argv[2]
    trans_dir = sys.argv[3]
    strategy = sys.argv[4] if len(sys.argv) > 4 else 'h2'

    written = split(source_path, out_dir, trans_dir, strategy)
    for p in written:
        print('  %s' % p)


if __name__ == '__main__':
    main()
