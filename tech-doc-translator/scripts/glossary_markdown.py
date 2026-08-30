#!/usr/bin/env python3
"""共享术语脚本使用的最小 Markdown 表格解析器。"""
import os
import re
import unicodedata


VALID_METHODS = {'中文', '首现中英，后文中文', '首现中英，后文英文', '英文'}


def clean(value):
    value = unicodedata.normalize('NFKC', value or '').strip()
    value = re.sub(r'^`(.*)`$', r'\1', value)
    return re.sub(r'\s+', ' ', value)


def key(value):
    return clean(value).casefold()


def source_name(path):
    basename = os.path.basename(path)
    if basename == '术语表.md':
        return '%s/%s' % (os.path.basename(os.path.dirname(path)), basename)
    return basename


def cells(line):
    return [clean(cell) for cell in line.strip().strip('|').split('|')]


def table_rows(path):
    lines = open(path, encoding='utf-8').read().splitlines()
    index = 0
    section = ''
    while index < len(lines):
        heading = re.match(r'^#{1,6}\s+(.+?)\s*#*\s*$', lines[index])
        if heading:
            section = clean(heading.group(1))
        if not lines[index].lstrip().startswith('|'):
            index += 1
            continue
        start = index
        block = []
        while index < len(lines) and lines[index].lstrip().startswith('|'):
            block.append((index + 1, cells(lines[index])))
            index += 1
        if len(block) >= 2:
            yield section, start + 1, block


def column(headers, names):
    return next((index for index, name in enumerate(headers) if name in names), None)


def method(value):
    value = clean(value)
    if value in VALID_METHODS:
        return value
    if value in ('保留英文', '英文', '保留'):
        return '英文'
    if value in ('首现附英文', '首现中英', '首现中英,后文中文'):
        return '首现中英，后文中文'
    if value in ('保留+首现注', '首现中英,后文英文'):
        return '首现中英，后文英文'
    if value.startswith('首现'):
        if ('后文' in value and '中文' not in value) or '后保留' in value:
            return '首现中英，后文英文'
        return '首现中英，后文中文'
    if '首现' in value or '附英文' in value:
        return '首现中英，后文中文'
    if value.startswith(('译', '承')) or value == '意译':
        return '首现中英，后文中文'
    if value == '半保留':
        return '首现中英，后文英文'
    if '保留' in value:
        return '英文'
    return value


def split_sources(value):
    """按顶层分号拆分来源，不拆标题方括号内的说明。"""
    sources = []
    current = []
    bracket_depth = 0
    for character in clean(value):
        if character == '[':
            bracket_depth += 1
        elif character == ']' and bracket_depth:
            bracket_depth -= 1
        if character == ';' and bracket_depth == 0:
            source = clean(''.join(current))
            if source:
                sources.append(source)
            current = []
        else:
            current.append(character)
    source = clean(''.join(current))
    if source:
        sources.append(source)
    return sources


def join_sources(sources):
    by_location = {}
    for source in sources:
        location = source.split(' [', 1)[0]
        current = by_location.get(location)
        if current is None or (' [' in source, len(source), source) > (
                ' [' in current, len(current), current):
            by_location[location] = source
    return '; '.join(sorted(by_location.values()))


def read_terms(path, authority=False, baseline=False):
    """读取文件中所有可识别术语表，返回记录、错误和输入行数。"""
    found = []
    errors = []
    count = 0
    for section, table_line, table in table_rows(path):
        headers = table[0][1]
        english = column(headers, {'英文原词'})
        if english is None:
            continue
        chinese = column(headers, {'中文译法', '定稿译法', '中文译法/保留形式'})
        handling = column(headers, {'处理方式'})
        context = column(headers, {'语境/备注'})
        source = column(headers, {'来源'})
        pending = column(headers, {'暂定处理'})
        description = column(headers, {'说明'})

        if authority and any(index is None for index in (chinese, handling, context, source)):
            errors.append((table_line, '权威表缺少中文译法/保留形式、处理方式、语境/备注或来源列'))
            continue
        special = pending is not None or (description is not None and '保留不译' in section)
        if chinese is None and handling is None and not special:
            for line, _ in table[2:]:
                count += 1
                errors.append((line, '术语表列含义无法识别'))
            continue

        for line, row in table[2:]:
            count += 1

            def value(index):
                return row[index] if index is not None and index < len(row) else ''

            raw_english = clean(value(english))
            if not raw_english:
                errors.append((line, '英文原词为空或列数不足'))
                continue

            raw_chinese = clean(value(chinese))
            raw_handling = clean(value(handling))
            if pending is not None:
                decision = clean(value(pending))
                mapped = method(decision)
                if mapped == '英文':
                    raw_chinese = raw_english
                else:
                    raw_chinese = decision
                    mapped = '首现中英，后文中文'
            elif description is not None and '保留不译' in section:
                raw_chinese = raw_english
                mapped = '英文'
            else:
                mapped = method(raw_handling) if handling is not None else '首现中英，后文中文'
                if not raw_chinese and mapped == '英文':
                    raw_chinese = raw_english

            raw_source = clean(value(source))
            if authority and not raw_source:
                errors.append((line, '权威术语行缺少来源'))
                continue
            if not raw_chinese or mapped not in VALID_METHODS:
                errors.append((line, '中文译法/保留形式或处理方式不足'))
                continue

            location = '%s:%d' % (source_name(path), line)
            if section:
                location += ' [%s]' % section
            sources = set(split_sources(raw_source)) if baseline and raw_source else {location}
            found.append({
                'english': raw_english,
                'chinese': raw_chinese,
                'method': mapped,
                'context': clean(value(context)),
                'source': join_sources(sources),
                'sources': sources,
                'file': source_name(path),
                'baseline': baseline,
            })
    return found, errors, count
