#!/usr/bin/env python3
"""合并翻译 Agent 上报的术语候选到项目术语表。

用法：
    python3 merge_glossary.py <术语表.md> <输出术语表.md> <冲突文件.md> \\
        [--approve <批准文件.txt>] [--pending <待定文件.md>] <候选1.md> [<候选2.md> ...]

行为：
    - 解析现有术语表和候选文件中的 Markdown 表格。
    - 英文原词已存在且中文译法不一致时：保留现有，写入冲突文件。
    - 英文原词已存在且中文译法一致时：不重复追加。
    - 英文原词不存在时，仅当该词列入 --approve 文件（主 Agent 逐条裁决结果）
      才写入输出术语表；其余候选写入 --pending 指定的待定文件，不自动入库。
    - 批准文件格式：每行一个英文原词（空白与注释 # 会被忽略）。
"""
import argparse
import sys
import os
import re


def _extract_table(text):
    """从 Markdown 文本中提取第一个表格的行数据，忽略标题行和分隔行。"""
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            if in_table:
                break
            continue
        cells = [c.strip() for c in line.split('|')]
        # 去掉首尾空单元
        cells = [c for c in cells if c or c == '']
        cells = cells[1:-1] if len(cells) >= 2 and cells[0] == '' and cells[-1] == '' else cells
        if not cells:
            continue
        # 跳过分隔行
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _normalize_term(t):
    return re.sub(r'\s+', ' ', t.strip().lower())


def _normalize_chinese(t):
    return re.sub(r'\s+', ' ', t.strip())


def load_glossary(path):
    """返回 {normalized_english: row_dict}。"""
    rows = _extract_table(open(path, encoding='utf-8').read())
    if not rows:
        return {}
    data = {}
    for cells in rows[1:]:
        if len(cells) < 2:
            continue
        key = _normalize_term(cells[0])
        data[key] = {
            '英文原词': cells[0] if len(cells) > 0 else '',
            '中文译法': cells[1] if len(cells) > 1 else '',
            '处理方式': cells[2] if len(cells) > 2 else '',
            '首现': cells[3] if len(cells) > 3 else '',
        }
    return data


def load_approved(path):
    """读取主 Agent 批准词表：每行一个英文原词，# 开头为注释。"""
    if not path or not os.path.isfile(path):
        return set()
    approved = set()
    for line in open(path, encoding='utf-8').read().splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        approved.add(_normalize_term(s))
    return approved


def merge(existing_path, candidate_paths, out_path, conflict_path,
          approved=None, pending_path=None):
    existing = load_glossary(existing_path)
    merged = dict(existing)
    approved = approved or set()
    conflicts = []
    new_terms = []
    pending = []

    for cand_path in candidate_paths:
        rows = _extract_table(open(cand_path, encoding='utf-8').read())
        for cells in rows[1:] if rows else []:
            if len(cells) < 2:
                continue
            eng = cells[0]
            chn = cells[1] if len(cells) > 1 else ''
            method = cells[2] if len(cells) > 2 else ''
            first = cells[3] if len(cells) > 3 else ''
            key = _normalize_term(eng)
            if key in merged:
                if _normalize_chinese(merged[key]['中文译法']) != _normalize_chinese(chn):
                    conflicts.append({
                        '英文原词': eng,
                        '现有译法': merged[key]['中文译法'],
                        '候选译法': chn,
                        '来源': cand_path,
                    })
                continue
            entry = {
                '英文原词': eng,
                '中文译法': chn,
                '处理方式': method,
                '首现': first,
                '来源': cand_path,
            }
            if key in approved:
                merged[key] = entry
                new_terms.append(entry)
            else:
                pending.append(entry)

    # 写入合并后的术语表（现有 + 已批准新增）
    all_terms = list(existing.values()) + new_terms
    _write_glossary_table(out_path, all_terms)

    # 写入冲突文件
    if conflicts:
        _write_conflict_table(conflict_path, conflicts)
    elif os.path.exists(conflict_path):
        os.remove(conflict_path)

    # 写入待定文件
    if pending_path:
        if pending:
            _write_pending_table(pending_path, pending)
        elif os.path.exists(pending_path):
            os.remove(pending_path)

    return len(new_terms), len(conflicts), len(pending)


def _write_glossary_table(path, rows):
    headers = ['英文原词', '中文译法', '处理方式', '首现']
    _write_markdown_table(path, '# 术语表\n\n', headers, rows)


def _write_conflict_table(path, rows):
    headers = ['英文原词', '现有译法', '候选译法', '来源']
    _write_markdown_table(path, '# 术语冲突列表\n\n', headers, rows)


def _write_pending_table(path, rows):
    headers = ['英文原词', '中文译法', '处理方式', '首现', '来源']
    _write_markdown_table(path, '# 待定术语（需主 Agent 逐条裁决）\n\n', headers, rows)


def _write_markdown_table(path, preamble, headers, rows):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(preamble)
        f.write('| %s |\n' % ' | '.join(headers))
        f.write('| %s |\n' % ' | '.join(['---'] * len(headers)))
        for r in rows:
            cells = [str(r.get(h, '')) for h in headers]
            f.write('| %s |\n' % ' | '.join(cells))
        if not rows:
            f.write('| %s |\n' % ' | '.join([''] * len(headers)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('existing')
    ap.add_argument('out')
    ap.add_argument('conflicts')
    ap.add_argument('candidates', nargs='+')
    ap.add_argument('--approve', help='主 Agent 批准词表（每行一个英文原词）')
    ap.add_argument('--pending', help='待定候选输出文件（未批准候选）')
    a = ap.parse_args()

    if not os.path.isfile(a.existing):
        sys.exit('术语表不存在: %s' % a.existing)
    for p in a.candidates:
        if not os.path.isfile(p):
            sys.exit('候选文件不存在: %s' % p)

    approved = load_approved(a.approve)
    new_count, conflict_count, pending_count = merge(
        a.existing, a.candidates, a.out, a.conflicts,
        approved=approved, pending_path=a.pending,
    )
    print('术语合并完成: 新增 %d 条（已批准）, 待定 %d 条, 冲突 %d 条 -> %s'
          % (new_count, pending_count, conflict_count, a.out))
    if conflict_count:
        print('冲突已写入: %s' % a.conflicts)
    if pending_count and a.pending:
        print('待定候选已写入: %s' % a.pending)


if __name__ == '__main__':
    main()
