#!/usr/bin/env python3
"""保守整合 Markdown 项目术语表为共享术语库草稿。"""
import argparse
from collections import defaultdict

from glossary_markdown import clean, join_sources, key, read_terms, source_name


def equivalent(record):
    return (key(record['english']), key(record['context']), clean(record['chinese']), record['method'])


def write_table(path, rows):
    with open(path, 'w', encoding='utf-8') as out:
        out.write('# 共享术语库草稿\n\n')
        out.write('| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |\n')
        out.write('| --- | --- | --- | --- | --- |\n')
        for record in rows:
            row = dict(record)
            row['sources'] = join_sources(record['sources'])
            out.write('| {english} | {chinese} | {method} | {context} | {sources} |\n'.format(**row))


def consolidate(baseline_path, input_paths):
    base, base_errors, _ = read_terms(baseline_path, authority=True, baseline=True)
    errors = [(source_name(baseline_path), line, message) for line, message in base_errors]
    inputs = []
    total = 0
    for path in input_paths:
        rows, found_errors, count = read_terms(path)
        inputs.extend(rows)
        total += count
        errors.extend((source_name(path), line, message) for line, message in found_errors)

    groups = defaultdict(list)
    for record in base + inputs:
        groups[(key(record['english']), key(record['context']))].append(record)

    draft, conflicts = [], []
    duplicates = 0
    for group in groups.values():
        variants = defaultdict(list)
        for record in group:
            variants[equivalent(record)].append(record)
        if len(variants) > 1:
            baseline_variants = [variant for variant in variants.values() if any(record['baseline'] for record in variant)]
            if len(baseline_variants) == 1:
                merged = baseline_variants[0]
                canonical = merged[0].copy()
                canonical['sources'] = set().union(*(record['sources'] for record in merged))
                draft.append(canonical)
                duplicates += max(0, len(merged) - 1)
            conflicts.extend(record for variant in variants.values() for record in variant
                             if not record['baseline'] and variant not in baseline_variants)
            if baseline_variants:
                continue
            continue
        merged = next(iter(variants.values()))
        canonical = merged[0].copy()
        canonical['sources'] = set().union(*(record['sources'] for record in merged))
        draft.append(canonical)
        duplicates += max(0, len(merged) - 1)
    draft.sort(key=lambda record: (key(record['english']), key(record['context'])))
    return draft, conflicts, errors, total, duplicates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--draft', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('inputs', nargs='+')
    args = parser.parse_args()
    draft, conflicts, errors, total, duplicates = consolidate(args.baseline, args.inputs)
    write_table(args.draft, draft)
    candidates = sum(1 for row in draft if not row['baseline'])
    with open(args.report, 'w', encoding='utf-8') as out:
        out.write('# 术语整合报告\n\n')
        out.write('输入记录: %d / 权威候选: %d / 重复: %d / 冲突: %d / 错误: %d\n\n' %
                  (total, candidates, duplicates, len(conflicts), len(errors)))
        out.write('## 冲突\n\n| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |\n| --- | --- | --- | --- | --- |\n')
        for row in sorted(conflicts, key=lambda r: (key(r['english']), r['source'])):
            out.write('| {english} | {chinese} | {method} | {context} | {source} |\n'.format(**row))
        if errors:
            out.write('\n## 错误\n\n')
            for error in errors:
                out.write('- %s:%d：%s\n' % error)
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
