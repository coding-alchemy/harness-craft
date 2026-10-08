#!/usr/bin/env python3
"""共享术语脚本使用的最小 Markdown 表格解析器。"""
import os
import re
import unicodedata


VALID_METHODS = {'中文', '首现中英，后文中文', '首现中英，后文英文', '英文'}

# 有限表头别名集合（D6）：显式列出已确认列名，不模糊匹配、不猜测列义。
# 目标译法列别名一律映射到 chinese 角色；`直译` 不推导处理方式。
CHINESE_HEADERS = ('中文译法', '定稿译法', '中文译法/保留形式',
                   '中文译法/保留', '直译')
ROLE_HEADERS = (
    ('english', ('英文原词',)),
    ('chinese', CHINESE_HEADERS),
    ('handling', ('处理方式',)),
    ('context', ('语境/备注',)),
    ('source', ('来源',)),
    ('pending', ('暂定处理',)),
    ('description', ('说明',)),
)
ROLE_LABELS = {'english': '英文原词列', 'chinese': '目标译法列',
               'handling': '处理方式列', 'context': '语境/备注列',
               'source': '来源列', 'pending': '暂定处理列',
               'description': '说明列'}


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
    """分列只去真正的最外层 Markdown 分隔符，保留首尾空单元格。

    不逐个剥掉全部首尾管道：`| kernel ||` 须得到 ['kernel', '']，
    缺值错列不能被吞掉。
    """
    text = line.strip()
    if text.startswith('|'):
        text = text[1:]
    if text.endswith('|'):
        text = text[:-1]
    return [clean(cell) for cell in text.split('|')]


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


def role_columns(headers):
    """按有限角色别名收集每列的匹配；同一角色多列即表头歧义。

    歧义时该角色返回 None 并给出全部候选列号——即使两列当前内容相同
    也不选择首列。无匹配返回 (None, [])，与歧义区分开。
    """
    roles = {}
    ambiguous = []
    for role, names in ROLE_HEADERS:
        matches = [index for index, header in enumerate(headers)
                   if header in names]
        roles[role] = matches[0] if len(matches) == 1 else None
        if len(matches) > 1:
            ambiguous.append((role, matches))
    return roles, ambiguous


def describe_columns(headers, indexes):
    return '、'.join('第%d列“%s”' % (index + 1, headers[index])
                     for index in indexes)


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
        roles, ambiguous = role_columns(headers)
        english = roles['english']
        if english is None and not any(
                role == 'english' for role, _matches in ambiguous):
            # 确实无英文原词角色一律按普通非术语表跳过，不因其他角色列
            # 重复（ambiguous）误收；表头歧义/缺角色报错只适用于已
            # 识别为术语表（含英文原词角色）的表。英文原词列重复属于
            # 已识别术语表的表头歧义，落入下方歧义诊断，不能按无英文
            # 列静默吞表。
            continue
        header_text = '| %s |' % ' | '.join(headers)

        def reject_table(message):
            # 表头级错误 + 每个数据行一条带行号错误，整表不静默跳过；
            # 数据行计入核算，保持 records/errors/count 对账完整。
            errors.append((table_line, message))
            for line, _row in table[2:]:
                reject_row(line, message)

        def reject_row(line, message):
            nonlocal count
            count += 1
            errors.append((line, message))

        if ambiguous:
            details = '；'.join(
                '%s匹配多列（%s），不猜测首列'
                % (ROLE_LABELS[role], describe_columns(headers, matches))
                for role, matches in ambiguous)
            reject_table('表头歧义：%s；表头：%s' % (details, header_text))
            continue
        chinese = roles['chinese']
        handling = roles['handling']
        context = roles['context']
        source = roles['source']
        pending = roles['pending']
        description = roles['description']

        if authority and any(index is None for index in (chinese, handling, context, source)):
            reject_table('权威表缺少中文译法/保留形式、处理方式、语境/备注或来源列；'
                         '表头：%s' % header_text)
            continue
        special = pending is not None or (description is not None and '保留不译' in section)
        if chinese is None and handling is None and not special:
            reject_table('术语表列含义无法识别；表头：%s' % header_text)
            continue

        for line, row in table[2:]:
            count += 1
            if len(row) != len(headers):
                errors.append((line, '数据行列数（%d）与表头列数（%d）不符，无法可靠解释'
                               % (len(row), len(headers))))
                continue

            def value(index):
                return row[index] if index is not None else ''

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
                # 来源定位元信息（D6）：可回查原目标表头、表头行号与列号；
                # 不参与“英文原词+语境”身份，不改变优先级/处理方式/来源聚合。
                'header': headers[chinese] if chinese is not None else '',
                'header_line': table_line,
                'column': (chinese + 1) if chinese is not None else None,
            })
    return found, errors, count
