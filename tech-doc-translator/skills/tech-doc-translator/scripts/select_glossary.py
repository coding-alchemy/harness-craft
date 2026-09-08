#!/usr/bin/env python3
"""从显式选择的共享术语库生成当前源文的有效术语子集。"""
import argparse
import re

from glossary_markdown import clean, key, read_terms as read_glossary_terms


def read_terms(path, authority):
    terms, errors, _ = read_glossary_terms(path, authority=authority, baseline=authority)
    return terms, ['%s:%d %s' % (path, line, message) for line, message in errors]


def parse_context(values):
    selected = {}
    for value in values:
        if '=' not in value:
            raise ValueError('--context 必须采用 英文原词=语境 格式: %s' % value)
        english, context = value.split('=', 1)
        selected[key(english)] = clean(context)
    return selected


def occurs(source, english):
    pattern = r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])' % re.escape(english)
    return re.search(pattern, source, re.IGNORECASE) is not None


def select(source_path, library_paths, project_path, contexts):
    source_text = open(source_path, encoding='utf-8').read()
    selected = {}
    notes = []
    for library in library_paths:
        terms, errors = read_terms(library, authority=True)
        if errors:
            raise ValueError('\n'.join(errors))
        seen = set()
        for term in terms:
            identity = (key(term['english']), key(term['context']))
            if identity in seen:
                raise ValueError('%s 中存在重复权威键: %s / %s' % (library, term['english'], term['context']))
            seen.add(identity)
            if not occurs(source_text, term['english']):
                continue
            previous = selected.get(identity)
            if previous and (previous['chinese'], previous['method']) != (term['chinese'], term['method']):
                notes.append('共享库覆盖: %s 的 %s 覆盖 %s 的 %s' %
                             (previous['file'], term['english'], term['file'], term['english']))
                continue
            selected.setdefault(identity, term)
    if project_path:
        terms, errors = read_terms(project_path, authority=False)
        if errors:
            raise ValueError('\n'.join(errors))
        for term in terms:
            if not occurs(source_text, term['english']):
                continue
            identity = (key(term['english']), key(term['context']))
            previous = selected.get(identity)
            if previous and (previous['chinese'], previous['method']) != (term['chinese'], term['method']):
                notes.append('项目覆盖: %s 的 %s 覆盖 %s 的 %s' %
                             (term['file'], term['english'], previous['file'], term['english']))
            selected[identity] = term
    by_english = {}
    for identity, term in selected.items():
        by_english.setdefault(identity[0], []).append((identity, term))
    result = []
    for english, variants in by_english.items():
        requested_context = contexts.get(english)
        if requested_context is not None:
            variants = [item for item in variants if key(item[1]['context']) == key(requested_context)]
            if not variants:
                raise ValueError('未找到所选语境: %s=%s' % (english, requested_context))
        if len(variants) != 1:
            raise ValueError('术语语境不明确，需使用 --context 选择: %s' % variants[0][1]['english'])
        result.append(variants[0][1])
    return sorted(result, key=lambda term: (key(term['english']), key(term['context']))), notes


def write_output(path, terms, notes):
    with open(path, 'w', encoding='utf-8') as out:
        out.write('# 有效术语子集\n\n')
        out.write('| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |\n')
        out.write('| --- | --- | --- | --- | --- |\n')
        for term in terms:
            out.write('| {english} | {chinese} | {method} | {context} | {source} |\n'.format(**term))
        if notes:
            out.write('\n## 覆盖说明\n\n')
            for note in notes:
                out.write('- %s\n' % note)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--library', action='append', default=[])
    parser.add_argument('--project')
    parser.add_argument('--context', action='append', default=[])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        terms, notes = select(args.source, args.library, args.project, parse_context(args.context))
    except ValueError as error:
        raise SystemExit('术语选择失败: %s' % error)
    write_output(args.output, terms, notes)


if __name__ == '__main__':
    main()
