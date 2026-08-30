#!/usr/bin/env python3
"""将源 Markdown 拆分为翻译工作包。

用法：
    python3 split_work_packages.py <source.md> <wps_dir> <trans_dir> [strategy]

strategy:
    h2              按 H2 小节切分（默认）
    chars:<N>       按字符数上限切分，优先保持小节完整；
                    单个小节仍超限时在段落边界拆分为片段

输出：
    wps_dir/wp_001.md, wp_002.md, ...   工作包（源文 + 机械上下文 frontmatter）
    翻译 Agent 只写 target_file 指定的独立目标 trans_dir/wp_001.md 等，
    不得覆写工作包源文件。
    工作包文件不是完整的 Agent 任务；主 Agent 还须按 Skill 的工作包任务模板
    提供项目规则、相关术语、输出模板、特殊规则和完成上报格式。
    每个文件头部写入上下文块（YAML frontmatter），包含：
      - source_file / target_file / source_order
      - content_blocks: headings, paragraphs, list_items, code_fences
      - rules_path（指向 tech-doc-translator/rules/translation_conventions.md）
      - section_id / fragment_index / source_order（同一小节拆分片段时）
"""
import sys
import os
import re
import math

_RULES_PATH = "tech-doc-translator/rules/translation_conventions.md"


def _parse_sections(doc):
    """按 H2 切分文档。返回 [(section_id, lines)], section_id 取 H2 文本。

    若首个 H2 之前只有 H1 与空白，则将 H1 合并到第一个 H2 小节中。
    """
    lines = doc.splitlines()
    sections = []
    current_id = "[top]"
    current_lines = []
    for line in lines:
        m = re.match(r'^##\s+(.+)$', line)
        if m:
            if current_lines:
                sections.append((current_id, current_lines))
            current_id = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines or not sections:
        sections.append((current_id, current_lines))

    # 将只有 H1 的前导区合并到第一个 H2
    if len(sections) >= 2:
        first_id, first_lines = sections[0]
        if first_id == "[top]":
            non_blank = [l for l in first_lines if l.strip()]
            if len(non_blank) == 1 and re.match(r'^#\s+', non_blank[0]):
                _, second_lines = sections[1]
                sections[1] = (sections[1][0], first_lines + [""] + second_lines)
                sections = sections[1:]
    return sections


def _count_blocks(lines):
    """统计 headings / paragraphs / list_items / code_fences。"""
    headings = 0
    paragraphs = 0
    list_items = 0
    code_fences = 0
    in_code = False
    para_open = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            if in_code:
                code_fences += 1
            continue
        if in_code:
            continue
        if re.match(r'^#{1,6}\s+', stripped):
            headings += 1
            para_open = False
            continue
        if re.match(r'^(?:[*+-]\s+|\d+\.\s+)', stripped):
            list_items += 1
            para_open = False
            continue
        # 表格行
        if re.match(r'^\|', stripped):
            para_open = False
            continue
        if stripped == '':
            if para_open:
                para_open = False
            continue
        # 表格分隔行（已无 | 前缀的情况兜底）
        if re.match(r'^:?-+:?$', stripped):
            continue
        if re.match(r'^>', stripped):
            if not para_open:
                paragraphs += 1
                para_open = True
            continue
        if not para_open:
            paragraphs += 1
            para_open = True

    return {
        'headings': headings,
        'paragraphs': paragraphs,
        'list_items': list_items,
        'code_fences': code_fences,
    }


def _split_section(section_id, lines, max_chars):
    """按段落边界把一个小节拆成多个片段。"""
    text = '\n'.join(lines)
    if max_chars <= 0 or len(text) <= max_chars:
        return [(section_id, 0, lines)]

    fragments = []
    current = []
    current_len = 0
    fragment_index = 0
    for line in lines:
        line_len = len(line) + 1  # + newline
        # 标题单独成段时，尽量让它开启新片段
        if current_len and re.match(r'^##\s+', line) and current_len + line_len > max_chars:
            fragments.append((section_id, fragment_index, current))
            fragment_index += 1
            current = [line]
            current_len = line_len
            continue

        if current_len + line_len > max_chars and current:
            fragments.append((section_id, fragment_index, current))
            fragment_index += 1
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        fragments.append((section_id, fragment_index, current))

    # 确保每个片段都有 section_id 行；第一个片段已含原 H2，其余片段需补 H2
    result = []
    for sid, idx, frag in fragments:
        if frag and idx > 0 and not re.match(r'^##\s+', frag[0].strip()):
            frag = ['## %s' % sid] + frag
        result.append((sid, idx, frag))
    return result


def _make_header(source_path, target_path, source_order, section_id, fragment_index, blocks):
    lines = [
        "---",
        "source_file: %s" % source_path,
        "target_file: %s" % target_path,
        "source_order: %d" % source_order,
        "content_blocks:",
        "  headings: %d" % blocks['headings'],
        "  paragraphs: %d" % blocks['paragraphs'],
        "  list_items: %d" % blocks['list_items'],
        "  code_fences: %d" % blocks['code_fences'],
        "rules_path: %s" % _RULES_PATH,
        "section_id: \"%s\"" % section_id,
        "fragment_index: %d" % fragment_index,
        "---",
        "",
    ]
    return '\n'.join(lines)


def _write_package(out_dir, index, header, body_lines):
    name = "wp_%03d.md" % index
    path = os.path.join(out_dir, name)
    body = '\n'.join(body_lines).strip('\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write(body)
        f.write('\n')
    return path


def split(source_path, out_dir, trans_dir, strategy):
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    if not os.path.exists(trans_dir):
        os.makedirs(trans_dir)

    max_chars = 0
    if strategy.startswith('chars:'):
        max_chars = int(strategy.split(':', 1)[1])

    doc = open(source_path, encoding='utf-8').read()
    sections = _parse_sections(doc)

    source_abs = os.path.abspath(source_path)
    index = 0
    written = []
    for section_id, lines in sections:
        if section_id == "[top]" and all(not l.strip() for l in lines):
            continue
        fragments = _split_section(section_id, lines, max_chars)
        for sid, fragment_index, frag_lines in fragments:
            index += 1
            # 译文目标是与工作包源文件分离的独立路径
            target_abs = os.path.abspath(os.path.join(trans_dir, "wp_%03d.md" % index))
            blocks = _count_blocks(frag_lines)
            header = _make_header(source_abs, target_abs, index, sid, fragment_index, blocks)
            path = _write_package(out_dir, index, header, frag_lines)
            written.append(path)

    return written


def main():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        sys.exit(__doc__)
    source_path = sys.argv[1]
    out_dir = sys.argv[2]
    trans_dir = sys.argv[3]
    strategy = sys.argv[4] if len(sys.argv) > 4 else 'h2'

    if not os.path.isfile(source_path):
        sys.exit('源文件不存在: %s' % source_path)

    written = split(source_path, out_dir, trans_dir, strategy)
    print('已生成 %d 个工作包到 %s（译文目标目录 %s）' % (len(written), out_dir, trans_dir))
    for p in written:
        print('  %s' % p)


if __name__ == '__main__':
    main()
