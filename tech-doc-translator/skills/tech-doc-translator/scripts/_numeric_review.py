"""共享数字与单位提取/差异职责（二期 R5 / 设计 §4.7，二期 Ticket 06）。

显式启用的数字辅助：从当前源/译 Markdown 提取数字 token，保留原始写法
（正负号、小数/指数/千位形式、百分比符号）、紧邻单位与数量级词，以及
文件、行/字符位置和已知宿主（章节/表格格位/题注/脚注）。代码与公式
区间按共享 ``scan_math``/``scan_code_fences`` 的真实跨度标注为硬检查
保护内容，不作为可换算正文；URL/标识符中的数字单列上下文。

输出保留完整位置清单和源/译差异多重集（源缺失/译新增，含数量级或
单位相关上下文及位置）；不能可靠识别的写法列入 unclassified，明示
未检查/待确认。每个本次差异生成定位 ID（角色、确认范围、原值/单位、
出现序号、当前位置），供既有 semantic ``items`` 逐项对应；ID 从本次
扫描生成，不承担跨版本稳定状态。

本模块是全部源家族共用的单一实现（Ticket 07 直接调用），消费者（各
家族核验入口、包恢复/合并、最终交付）按当前输入重新计算，不从自由
文本输出反推第二种数字事实。只做定位与报告：不换算、不改文、不裁决
语义、不写 ``closed``、不维护跨版本差异台账。
"""
import hashlib
import os
import re
from collections import Counter

from _verification import (
    fenced_line_numbers,
    heading_entries,
    line_code_spans,
    scan_math,
)

# 未提供 --numeric-policy 时的明示默认口径（设计 §4.7：不执行为规则）
DEFAULT_POSTURE = '保留原值、报告差异、不自动判换算'

# 有限的常见单位写法（定位规则，不扩大为规则平台/等价词典）
UNIT_SYMBOLS = frozenset({
    '%', '°c', '°f',
    's', 'ms', 'us', 'µs', 'ns', 'min', 'h',
    'm', 'km', 'cm', 'mm', 'nm',
    'kg', 'g', 'mg',
    'b', 'kb', 'mb', 'gb', 'tb', 'pb',
    'bps', 'kbps', 'mbps', 'gbps',
    'hz', 'khz', 'mhz', 'ghz', 'thz',
    'w', 'kw', 'mw', 'v', 'mv', 'a', 'ma',
    'px', 'dpi', 'flops', 'gflops', 'tflops', 'tops',
    'gb/s', 'mb/s', 'kb/s', 'tb/s',
})
UNIT_WORDS = frozenset({
    'second', 'seconds', 'minute', 'minutes', 'hour', 'hours',
    'byte', 'bytes', 'bit', 'bits', 'row', 'rows', 'column', 'columns',
    'item', 'items', 'parameter', 'parameters', 'token', 'tokens',
    'layer', 'layers', 'epoch', 'epochs', 'percent', 'point', 'points',
})
MAGNITUDE_WORDS = frozenset({
    'thousand', 'million', 'billion', 'trillion', '万', '亿', '兆',
})

_NUMBER = re.compile(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?')
_ATTACHED_SYMBOL = re.compile(r'[µ°%/A-Za-z]{1,12}')
_BARE_URL = re.compile(r'https?://[^\s)>"]+')
_LINK_TARGET = re.compile(r'!?\[[^\]]*\]\(([^)]+)\)')
_FULLWIDTH_DIGIT = re.compile(r'[０-９]+')
_ANY_DIGIT = re.compile(r'\d')
_CJK_MAGNITUDE = re.compile(r'[万亿兆]')
_HEADING_LINE = re.compile(r'^(#{1,8})\s+(.+)$')
_FOOTNOTE_DEF = re.compile(r'^\[\^([^\]]+)\]:')
_FOOTNOTE_REF = re.compile(r'\[\^([^\]\s]+)\](?!:)')
_CAPTION_HINT = re.compile(
    r'(?:\*\*(?:图|表|Figure|Fig\.?|Table)|\[FIGCAP\]|\[TABLE\])')

# 报告/清单上限：完整位置清单不受限，诊断性未识别清单有界
_UNCLASSIFIED_LIMIT = 20


def module_identity():
    """数字提取/差异实现的内容身份（包证据与统一检查事实共用）。"""
    return {'_numeric_review.py': _sha256_file(os.path.abspath(__file__))}


def _sha256_file(path):
    try:
        with open(path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def policy_identity(policy_path):
    """数字约定标识：路径 + 当前内容摘要（复核上下文，不执行为规则）。

    未提供时返回显式默认口径；文件不可读/非 UTF-8 抛 ValueError（显式
    声明的输入依赖缺失，由各入口按缺绑定/缺输入拒绝）。
    """
    if not policy_path:
        return {'path': None, 'sha256': None, 'posture': DEFAULT_POSTURE}
    path = os.path.abspath(policy_path)
    try:
        with open(path, encoding='utf-8') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError('数字约定文件不可读（须 UTF-8）: %s（%s）'
                         % (policy_path, exc))
    return {'path': path,
            'sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
            'posture': None}


def _line_offsets(text):
    offsets = []
    cursor = 0
    for line in text.split('\n'):
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def _intervals(text):
    """共享扫描的真实保护区间：公式跨度、行内代码跨度、URL 目标区间。

    代码围栏按行集合在逐行判定中处理（见 extract_numeric_tokens）。
    """
    intervals = {'math': [], 'code': [], 'url': []}
    for span in scan_math(text).spans:
        intervals['math'].append((span.start, span.end))
    lines = text.split('\n')
    offsets = _line_offsets(text)
    for line_no, line in enumerate(lines):
        base = offsets[line_no]
        for _content, (start, end) in line_code_spans(line):
            intervals['code'].append((base + start, base + end))
    for match in _LINK_TARGET.finditer(text):
        intervals['url'].append((match.start(1), match.end(1)))
    for match in _BARE_URL.finditer(text):
        intervals['url'].append((match.start(), match.end()))
    return intervals


def _in_intervals(intervals, offset):
    for start, end in intervals:
        if start <= offset < end:
            return True
    return False


def _host_facts(text, table_lines):
    """逐行已知宿主：所属章节、表格格位、题注、脚注。"""
    headings = [(line, title)
                for line, _level, title in heading_entries(text)]
    hosts = {}
    for line_no, line in enumerate(text.split('\n'), start=1):
        section = None
        for hline, title in headings:
            if hline <= line_no:
                section = title
            else:
                break
        host = {'section': section, 'table': False, 'column': None,
                'caption': False, 'footnote': None}
        if line_no in table_lines:
            host['table'] = True
        match = _CAPTION_HINT.search(line)
        if match:
            host['caption'] = True
        def_match = _FOOTNOTE_DEF.match(line)
        if def_match:
            host['footnote'] = def_match.group(1)
        else:
            ref_match = _FOOTNOTE_REF.search(line)
            if ref_match:
                host['footnote'] = ref_match.group(1)
        hosts[line_no] = host
    return hosts


def extract_numeric_tokens(text, label='正文'):
    """提取一侧文本的数字事实；返回 JSON 可序列化字典。

    body token 参与源/译差异多重集；math/code 是受硬检查保护的事实，
    url/identifier 单列上下文；unclassified 是不能可靠识别、明示未检查
    的写法（有位置，供回源确认）。
    """
    fence_lines = fenced_line_numbers(text)
    table_lines = _table_lines(text)
    intervals = _intervals(text)
    hosts = _host_facts(text, table_lines)
    lines = text.split('\n')
    offsets = _line_offsets(text)

    tokens = []
    unclassified = []
    consumed = [False] * len(text)

    for line_no, line in enumerate(lines, start=1):
        base = offsets[line_no - 1]
        in_fence = line_no in fence_lines
        for match in _NUMBER.finditer(line):
            start, end = match.span()
            offset = base + start
            value = match.group(0)
            for i in range(start, end):
                consumed[base + i] = True
            raw = value
            unit = None
            magnitude = None
            context = 'body'
            if in_fence:
                context = 'code'
            elif _in_intervals(intervals['math'], offset):
                context = 'math'
            elif _in_intervals(intervals['code'], offset):
                context = 'code'
            elif _in_intervals(intervals['url'], offset):
                context = 'url'
            else:
                prev_ch = line[start - 1] if start > 0 else ''
                next_ch = line[end] if end < len(line) else ''
                after_two = line[end:end + 2]
                attached = None
                if (prev_ch.isascii() and prev_ch.isalpha()) \
                        or (prev_ch and prev_ch in '_%') \
                        or (prev_ch == '.' and start >= 2
                            and line[start - 2].isdigit()):
                    # 左邻标识符粘连（TPUv3s、Model5ms、x1.2）优先判
                    # identifier，避免误判为正文单位数量
                    context = 'identifier'
                else:
                    if next_ch.isascii() and next_ch.isalpha():
                        # 右邻 ASCII 字母时先试已支持紧附单位（5ms、
                        # 100ns、10gb/s）：命中按正文；未命中（3DES、
                        # 10x、5msx 整体非单位）仍落回标识符判定
                        cand = _take_unit(line, start, end)
                        if cand[1] is not None and cand[3] > end:
                            attached = cand
                    if attached is None and (
                            (next_ch.isascii() and next_ch.isalpha()) \
                            or next_ch == '_' \
                            or (next_ch == '.' and end + 1 < len(line)
                                and line[end + 1].isdigit())):
                        # 标识符/版本号片段（v2、3DES、1.2.3）：单列上下文
                        context = 'identifier'
                    elif (prev_ch and prev_ch in '^×' and not
                            (prev_ch == '^' and start >= 2
                             and line[start - 2] == '[')) \
                            or after_two.lstrip().startswith('^'):
                        # 数量级上标残片（×10^3 的指数）：不能可靠判为数量；
                        # [^1] 脚注标号是宿主事实，不算上标
                        context = 'unclassified'
            if context == 'body':
                if attached is not None:
                    raw, unit, magnitude, end = attached
                else:
                    raw, unit, magnitude, end = _take_unit(line, start, end)
                for i in range(match.end(), end):
                    consumed[base + i] = True
            token = {
                'raw': raw,
                'value': value,
                'unit': unit,
                'magnitude': magnitude,
                'context': context,
                'label': label,
                'line': line_no,
                'char': start,
                'offset': offset,
                'host': dict(hosts[line_no]),
            }
            if context == 'unclassified':
                unclassified.append(token)
            else:
                tokens.append(token)

    # 明示未检查：全角数字、未消费的 ASCII 数字残片、孤立中文数量级词
    for match in _FULLWIDTH_DIGIT.finditer(text):
        unclassified.append({
            'raw': match.group(0), 'value': match.group(0),
            'unit': None, 'magnitude': None, 'context': 'unclassified',
            'label': label,
            'line': text.count('\n', 0, match.start()) + 1,
            'char': match.start() - text.rfind('\n', 0, match.start()) - 1,
            'offset': match.start(),
            'host': None,
        })
    for index, ch in enumerate(text):
        if consumed[index] or not _ANY_DIGIT.match(ch):
            continue
        line_no = text.count('\n', 0, index) + 1
        if line_no in fence_lines:
            continue  # 围栏内数字已按 code 上下文列出
        if _in_intervals(intervals['math'], index) \
                or _in_intervals(intervals['code'], index):
            continue
        prev_ch = text[index - 1] if index > 0 else ''
        if prev_ch.isalpha() or (prev_ch and prev_ch in '_.%^×'):
            continue  # 标识符/上标残片，上面已列或不可靠
        consumed[index] = True
        unclassified.append({
            'raw': ch, 'value': ch, 'unit': None, 'magnitude': None,
            'context': 'unclassified', 'label': label,
            'line': line_no,
            'char': index - text.rfind('\n', 0, index) - 1,
            'offset': index,
            'host': None,
        })
    for match in _CJK_MAGNITUDE.finditer(text):
        index = match.start()
        line_no = text.count('\n', 0, index) + 1
        prev_ch = text[index - 1] if index > 0 else ''
        if prev_ch.isdigit() or (prev_ch in ' \t' and index >= 2
                                 and text[index - 2].isdigit()):
            continue  # 已随数字 token 登记为数量级
        if _in_intervals(intervals['math'], index) \
                or _in_intervals(intervals['code'], index) \
                or line_no in fence_lines:
            continue
        unclassified.append({
            'raw': match.group(0), 'value': None, 'unit': None,
            'magnitude': match.group(0), 'context': 'unclassified',
            'label': label,
            'line': text.count('\n', 0, index) + 1,
            'char': index - text.rfind('\n', 0, index) - 1,
            'offset': index,
            'host': None,
        })

    unclassified.sort(key=lambda item: item['offset'])
    return {
        'label': label,
        'tokens': tokens,
        'unclassified': unclassified[:_UNCLASSIFIED_LIMIT],
        'unclassified_total': len(unclassified),
    }


def _table_lines(text):
    """真实 Markdown 表格块行号（共享 markdown_table_row_lines 同口径）。"""
    from _verification import markdown_table_row_lines
    return markdown_table_row_lines(text)


def _unit_boundary_ok(after):
    """单位/数量级右侧紧邻字符不继续该词形（ASCII 字母/下划线/单位符）。

    中文数量级/量词后随 CJK 是正常正文（如 "1040 亿参数"），不因此失效。
    """
    return not (bool(after) and ((after.isascii() and after.isalpha())
                                 or after in '_µ°/'))


def _take_unit(line, value_start, end):
    """从数字匹配区间取紧邻单位/数量级（紧附符号、空隔符号、词）。

    返回 (raw, unit, magnitude, new_end)；只接受有限词典内的写法，其他
    字符原样不动。中文数量级与英文 magnitude 均保留原 token，raw 为
    数字+单位/数量级的原始写法切片（含其间空隔）。
    """
    n = len(line)
    unit = None
    magnitude = None
    raw_end = end
    if end < n and line[end] == '%':
        unit = '%'
        raw_end = end + 1
        return line[value_start:raw_end], unit, magnitude, raw_end
    match = _ATTACHED_SYMBOL.match(line, end)
    if match:
        symbol = match.group(0).lower()
        if symbol in UNIT_SYMBOLS and _unit_boundary_ok(
                line[match.end():match.end() + 1]):
            unit = match.group(0)
            raw_end = match.end()
            return line[value_start:raw_end], unit, magnitude, raw_end
    if end < n and line[end] in ' \t':
        word_match = re.match(r'([A-Za-zµ°/]+|[万亿兆]+)', line[end + 1:])
        if word_match:
            word = word_match.group(1)
            after = line[end + 1 + word_match.end():
                         end + 2 + word_match.end()]
            lower = word.lower()
            if lower in MAGNITUDE_WORDS and _unit_boundary_ok(after):
                magnitude = word
                raw_end = end + 1 + word_match.end()
            elif (lower in UNIT_SYMBOLS or lower in UNIT_WORDS) \
                    and _unit_boundary_ok(after):
                unit = word
                raw_end = end + 1 + word_match.end()
    if magnitude is None and unit is None and end < n \
            and line[end] in '万亿兆':
        # 中文数量级紧附数字（1.5万、3亿）
        magnitude = line[end]
        raw_end = end + 1
    return line[value_start:raw_end], unit, magnitude, raw_end


def diff_numeric_tokens(src_result, doc_result, scope):
    """源/译 body token 多重集差异；返回带定位 ID 的差异列表。

    源缺失/译新增按精确原值及明确词法形式（raw 含紧邻单位/数量级）
    统计；同值不同单位的 token 给出 counterpart 提示。ID 从本次扫描
    生成：角色、确认范围、原值/单位、出现序号与当前位置。
    """
    src_body = [t for t in src_result['tokens'] if t['context'] == 'body']
    doc_body = [t for t in doc_result['tokens'] if t['context'] == 'body']
    src_counts = Counter(t['raw'] for t in src_body)
    doc_counts = Counter(t['raw'] for t in doc_body)
    missing = src_counts - doc_counts
    added = doc_counts - src_counts

    def value_key(raw):
        # 同值口径：raw 的数值前缀（紧附单位 5ms/5s 与空隔单位 5 ms/5 s
        # 归一同值，供同值异单位 counterpart 提示命中）
        match = _NUMBER.match(raw.replace(',', '').split(' ', 1)[0].lower())
        return match.group(0) if match else raw

    doc_values = {}
    for token in doc_body:
        doc_values.setdefault(value_key(token['raw']), []).append(token)
    src_values = {}
    for token in src_body:
        src_values.setdefault(value_key(token['raw']), []).append(token)

    def build(side_tokens, remaining, role, counterpart_values):
        diffs = []
        occurrence = Counter()
        for token in side_tokens:
            raw = token['raw']
            if remaining.get(raw, 0) <= 0:
                continue
            remaining[raw] -= 1
            occurrence[raw] += 1
            note = ''
            for other in counterpart_values.get(value_key(raw), []):
                if other['raw'] != raw:
                    note = ('同值异单位/数量级: 另一侧 %r（%s L%d）'
                            % (other['raw'], other['label'], other['line']))
                    break
            diff_id = 'NUM[%s][%s]#%d %s @%s:L%d' % (
                scope, role, occurrence[raw], raw,
                token['label'], token['line'])
            diffs.append({
                'id': diff_id,
                'role': role,
                'raw': raw,
                'value': token['value'],
                'unit': token['unit'],
                'magnitude': token['magnitude'],
                'occurrence': occurrence[raw],
                'label': token['label'],
                'line': token['line'],
                'char': token['char'],
                'host': token['host'],
                'note': note,
            })
        return diffs

    diffs = build(src_body, missing, 'src_missing', doc_values)
    diffs += build(doc_body, added, 'doc_added', src_values)
    diffs.sort(key=lambda d: (0 if d['role'] == 'src_missing' else 1,
                              d['label'], d['line'], d['char']))
    return diffs


def summarize(result):
    tokens = result['tokens']
    by_context = Counter(t['context'] for t in tokens)
    return {
        'body': by_context.get('body', 0),
        'math': by_context.get('math', 0),
        'code': by_context.get('code', 0),
        'url': by_context.get('url', 0),
        'identifier': by_context.get('identifier', 0),
        'unclassified': result['unclassified_total'],
    }


def compute_numeric_review(src_text, doc_text, src_label='源文',
                           doc_label='译文', scope='full',
                           policy_path=None):
    """一次共享数字复核：完整位置清单 + 源/译差异多重集（JSON 字典）。

    scope 为确认范围标识（'full' 最终/全量范围、'package' 包正文），进入
    每个差异的定位 ID。policy_path 为可选 UTF-8 项目数字约定：只记录
    路径/内容摘要作复核上下文，不执行为规则。
    """
    policy = policy_identity(policy_path)
    src_result = extract_numeric_tokens(src_text, label=src_label)
    doc_result = extract_numeric_tokens(doc_text, label=doc_label)
    diffs = diff_numeric_tokens(src_result, doc_result, scope)
    return {
        'enabled': True,
        'scope': scope,
        'policy': policy,
        'checker': module_identity(),
        'source': src_result,
        'translated': doc_result,
        'diffs': diffs,
        'summary': {
            'source': summarize(src_result),
            'translated': summarize(doc_result),
            'diffs_src_missing': sum(1 for d in diffs
                                     if d['role'] == 'src_missing'),
            'diffs_doc_added': sum(1 for d in diffs
                                   if d['role'] == 'doc_added'),
        },
    }


def numeric_binding(src_text, doc_text, scope, policy_path=None):
    """包证据/恢复核对的数字绑定投影：口径 + 实现身份 + 本次差异 ID。

    证据中的 numeric 块与本投影一致且 disposed 覆盖全部本次差异 ID 才
    具备复用资格；不比较自由文本说明。
    """
    review = compute_numeric_review(src_text, doc_text, scope=scope,
                                    policy_path=policy_path)
    return {
        'enabled': True,
        'scope': scope,
        'policy': review['policy'],
        'checker': review['checker'],
        'diff_ids': sorted(d['id'] for d in review['diffs']),
    }


def numeric_check_policy_block(policy_path=None):
    """check_policy（D4）中的数字口径投影：约定身份 + 实现身份。

    复用 Ticket 01 的 check_policy 机制，不建第二套状态库；口径文件或
    实现变化使相关包证据的 check_policy 不符而失效。
    """
    return {'policy': policy_identity(policy_path),
            'checker': module_identity()}


def format_policy_line(policy):
    """口径行的共享文案：约定路径/摘要或明示默认口径（复核上下文）。"""
    if policy.get('path'):
        return ('数字口径: %s（sha256=%s…，仅作复核上下文，不执行为规则）'
                % (policy['path'], (policy.get('sha256') or '')[:12]))
    return '数字口径: 未提供 --numeric-policy，采用默认口径“%s”' % \
        policy['posture']


def format_diff_hint(diff):
    """单个数字差异提示行的共享文案（定位 ID + 宿主 + 同值异单位注记）。"""
    host = diff['host'] or {}
    where = []
    if host.get('section'):
        where.append('章节 %r' % host['section'])
    if host.get('table'):
        where.append('表格')
    if host.get('caption'):
        where.append('题注')
    if host.get('footnote'):
        where.append('脚注 [^%s]' % host['footnote'])
    text = '数字提示 %s' % diff['id']
    if where:
        text += '（%s）' % '、'.join(where)
    if diff['note']:
        text += '：%s' % diff['note']
    return text


def unchecked_notes(review):
    """不能可靠识别写法的共享未检查文案（有界，回源定性）。"""
    notes = []
    for side in ('source', 'translated'):
        result = review[side]
        if result['unclassified_total']:
            notes.append('数字提示: %s 有 %d 处数字写法未能可靠识别，未检'
                         '查/待确认（回源定性），如: %s'
                         % (result['label'], result['unclassified_total'],
                            '、'.join(repr(u['raw'])
                                      for u in result['unclassified'][:3])))
    return notes
