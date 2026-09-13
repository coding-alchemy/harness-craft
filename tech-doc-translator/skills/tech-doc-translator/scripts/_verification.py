"""译文校验器共享的 Markdown 结构扫描实现。

本文件是内部模块；各源家族 adapter 继续定义自己的通过条件和报告文案。
"""
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass

import tinycss2


_BLOCK_PLACEHOLDER = re.compile(r'^\[([A-Z][A-Z0-9_-]*)\]\s', re.M)
_IMAGE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_LINK = re.compile(r'(?<!!)\[(?:\\.|[^\\\]])+\]\(([^)]+)\)')
_FENCE_OPEN = re.compile(r'^(`{3,}|~{3,})(.*)$')
_FENCE_CLOSE = re.compile(r'^(`{3,}|~{3,})\s*$')
_MATH_BLOCK = re.compile(r'\$\$[\s\S]*?\$\$')
_MATH_BRACKET_BLOCK = re.compile(r'\\\[[\s\S]*?\\\]')
_MATH_INLINE = re.compile(r'\$([^\s$][^$\n]*?[^\s$]|[^\s$])\$(?!\d)')


@dataclass(frozen=True)
class CodeFence:
    """一个围栏代码块及其在原文中的确切位置。"""
    opener: str        # 开启行原文（不含换行）
    info: str          # 开启行围栏标记后的信息串（语言标签等，已去首尾空白）
    body: str          # 正文原文切片，逐字节保留空白与内部换行
    closer: str        # 关闭行原文（不含换行）
    fence_char: str    # 围栏字符：'`' 或 '~'
    fence_length: int  # 开启标记长度
    start: int         # 开启行首字符在原文中的偏移
    end: int           # 关闭行末字符之后的偏移（不含其后的换行符）
    start_line: int    # 开启行行号（1 起）
    end_line: int      # 关闭行行号（1 起）


@dataclass(frozen=True)
class CodeScan:
    blocks: tuple          # CodeFence 元组，按出现顺序
    boundary_count: int    # 围栏边界行数（成对时为 2×块数）
    balanced: bool         # 所有围栏是否正确闭合
    unclosed_line: int     # 未闭合围栏的开启行号；全部闭合时为 0


@dataclass(frozen=True)
class _OpenFence:
    """扫描过程中尚未闭合的围栏状态。"""
    fence_char: str
    fence_length: int
    opener: str
    info: str
    start: int
    start_line: int


def scan_code_fences(text):
    """扫描围栏代码块，返回 CodeScan。

    - 开启行：0-3 个空格缩进后至少 3 个相同围栏字符（`` ` `` 或 `` ~ ``），
      其后为信息串；反引号围栏的信息串内不得再含反引号。
    - 关闭行：0-3 个空格缩进、同字符且长度不小于开启标记，不得带信息串。
    - 围栏内部一切内容（短围栏、标题、分隔线、公式、图片语法）不参与外部结构。
    - body/start/end 均为原文切片或偏移，不做任何换行或空白重组。
    """
    lines = text.split('\n')
    blocks = []
    boundary_count = 0
    unclosed_line = 0
    offset = 0
    open_state = None
    body_start = 0
    for line_no, line in enumerate(lines, start=1):
        line_start = offset
        offset += len(line) + 1
        indented = line.lstrip(' ')
        indent = len(line) - len(indented)
        if open_state is None:
            if indent <= 3:
                mark = _FENCE_OPEN.match(indented)
                if mark:
                    fence = mark.group(1)
                    info = mark.group(2).strip()
                    if not (fence[0] == '`' and '`' in info):
                        open_state = _OpenFence(
                            fence[0], len(fence), line, info,
                            line_start, line_no)
                        body_start = line_start + len(line) + 1
                        boundary_count += 1
        else:
            close_mark = _FENCE_CLOSE.match(indented) if indent <= 3 else None
            if (close_mark and close_mark.group(1)[0] == open_state.fence_char
                    and len(close_mark.group(1)) >= open_state.fence_length):
                blocks.append(CodeFence(
                    opener=open_state.opener, info=open_state.info,
                    body=text[body_start:max(body_start, line_start - 1)],
                    closer=line, fence_char=open_state.fence_char,
                    fence_length=open_state.fence_length, start=open_state.start,
                    end=line_start + len(line),
                    start_line=open_state.start_line, end_line=line_no))
                open_state = None
                boundary_count += 1
    if open_state is not None:
        unclosed_line = open_state.start_line
    return CodeScan(tuple(blocks), boundary_count, unclosed_line == 0,
                    unclosed_line)


def fenced_line_numbers(text):
    """返回被代码围栏覆盖的行号集合（1 起）；未闭合围栏覆盖到文件尾。"""
    lines = text.split('\n')
    scan = scan_code_fences(text)
    code_lines = set()
    for fence in scan.blocks:
        code_lines.update(range(fence.start_line, fence.end_line + 1))
    if scan.unclosed_line:
        code_lines.update(range(scan.unclosed_line, len(lines) + 1))
    return code_lines


def normalize(text):
    """统一空白和英文弯引号，供标题比较使用。"""
    return re.sub(r'\s+', ' ', text.replace('\u2019', "'").strip())


def strip_chinese_suffix(text):
    """去掉标题中第一个全角 `（` 及之后的内容。"""
    index = text.find('（')
    return text[:index].strip() if index >= 0 else text.strip()


def heading_lines(text, ignore_fences=False, strip_lines=False):
    """按顺序返回 Markdown 标题 ``(级别, 原始文本)``。

    ignore_fences=True 时排除代码围栏内部行（含围栏标记行）；
    未闭合围栏的开启行之后整篇视为代码。
    """
    headings = []
    lines = text.split('\n')
    code_lines = fenced_line_numbers(text) if ignore_fences else set()
    for line_no, line in enumerate(lines, start=1):
        if line_no in code_lines:
            continue
        candidate = (line.strip() if strip_lines else line.rstrip('\r'))
        match = re.match(r'^(#{1,8})\s+(.+)$', candidate)
        if match:
            headings.append((len(match.group(1)), match.group(2)))
    return headings


def _opener_consistent(src_fence, doc_fence):
    """开启行一致性判定。

    围栏字符与长度必须一致；开启行的缩进与标记/信息串之间的空白差异
    不参与比较（嵌套容器内的源围栏在译文中合法去缩进）。语言信息按项目
    固定转换处理：源裸围栏可补语言标签；已有标签不得修改或删除。
    """
    if src_fence.opener == doc_fence.opener:
        return True
    return (src_fence.fence_char == doc_fence.fence_char
            and src_fence.fence_length == doc_fence.fence_length
            and (src_fence.info == '' or src_fence.info == doc_fence.info))


def compare_code_fences(src_fences, doc_fences,
                        src_label='源文', doc_label='译文'):
    """逐块比较两组代码围栏，返回差异诊断列表；空列表表示逐块一致。

    正文逐字节比较（含空白与内部换行）；开启行按 _opener_consistent 判定，
    关闭行去除首尾空白后比较（围栏标记行不参与容器缩进差异，正文不受此
    豁免）。诊断包含源/译标签、块序号、可定位行号与期望/实际原文。
    """
    diffs = []
    if len(src_fences) != len(doc_fences):
        diffs.append('代码块数不一致: 源 %s %d 块 vs 译 %s %d 块'
                     % (src_label, len(src_fences), doc_label, len(doc_fences)))
        for j in range(min(len(src_fences), len(doc_fences)), len(src_fences)):
            fence = src_fences[j]
            diffs.append('  源 %s 多余代码块 #%d（L%d）: %r'
                         % (src_label, j + 1, fence.start_line, fence.opener))
        for j in range(min(len(src_fences), len(doc_fences)), len(doc_fences)):
            fence = doc_fences[j]
            diffs.append('  译 %s 多余代码块 #%d（L%d）: %r'
                         % (doc_label, j + 1, fence.start_line, fence.opener))
    for i in range(min(len(src_fences), len(doc_fences))):
        src, doc = src_fences[i], doc_fences[i]
        tag = '代码块 #%d' % (i + 1)
        if not _opener_consistent(src, doc):
            diffs.append(
                '%s 开启行不一致: 源 %s L%d %r vs 译 %s L%d %r'
                % (tag, src_label, src.start_line, src.opener,
                   doc_label, doc.start_line, doc.opener))
        src_lines = src.body.split('\n')
        doc_lines = doc.body.split('\n')
        if src_lines != doc_lines:
            for k in range(min(len(src_lines), len(doc_lines))):
                if src_lines[k] != doc_lines[k]:
                    diffs.append(
                        '%s 正文第 %d 行不一致: 源 %s L%d %r vs 译 %s L%d %r'
                        % (tag, k + 1, src_label, src.start_line + 1 + k,
                           src_lines[k], doc_label, doc.start_line + 1 + k,
                           doc_lines[k]))
                    break
            else:
                if len(src_lines) > len(doc_lines):
                    k = len(doc_lines)
                    diffs.append(
                        '%s 正文行数不一致: 源 %d 行 vs 译 %d 行；源多出 %s L%d %r'
                        % (tag, len(src_lines), len(doc_lines), src_label,
                           src.start_line + 1 + k, src_lines[k]))
                else:
                    k = len(src_lines)
                    diffs.append(
                        '%s 正文行数不一致: 源 %d 行 vs 译 %d 行；译多出 %s L%d %r'
                        % (tag, len(src_lines), len(doc_lines), doc_label,
                           doc.start_line + 1 + k, doc_lines[k]))
        if src.closer.strip() != doc.closer.strip():
            diffs.append(
                '%s 关闭行不一致: 源 %s L%d %r vs 译 %s L%d %r'
                % (tag, src_label, src.end_line, src.closer,
                   doc_label, doc.end_line, doc.closer))
    return diffs


def image_sources(text):
    """按文档顺序返回 Markdown 图片引用。"""
    return _IMAGE.findall(text)


def link_targets(text):
    """按文档顺序返回 Markdown 非图片链接目标。"""
    return _LINK.findall(text)


@dataclass(frozen=True)
class MathSpan:
    """一个公式及其在原文中的确切位置。"""
    kind: str        # 'inline'（行内 $…$）或 'block'（块级 $$…$$）
    expr: str        # 不含定界符的原始表达式切片，逐字节保留
    raw: str         # 含定界符的原文切片
    start: int       # 含定界符起始偏移
    end: int         # 含定界符结束偏移（不含）
    start_line: int  # 起始行号（1 起）


def _mask_inline_code(line):
    """把行内代码 span 替换为等长空格；未配对的反引号保持原样。"""
    chars = list(line)
    n = len(line)
    i = 0
    while i < n:
        if chars[i] == '`':
            j = i
            while j < n and chars[j] == '`':
                j += 1
            run = '`' * (j - i)
            k = line.find(run, j)
            masked = False
            while k != -1:
                end = k + len(run)
                if end < n and line[end] == '`':
                    k = line.find(run, end)
                    continue
                for p in range(i, end):
                    chars[p] = ' '
                i = end
                masked = True
                break
            if not masked:
                i = j
                continue
        i += 1
    return ''.join(chars)


def _math_scan_mask(text):
    """返回与原文等长的掩蔽副本：代码围栏行、行内代码、\\$ 转义替换为空格。"""
    fenced = fenced_line_numbers(text)
    out = []
    for line_no, line in enumerate(text.split('\n'), start=1):
        if line_no in fenced:
            out.append(' ' * len(line))
        else:
            masked = _mask_inline_code(line).replace('\\$', '  ')
            out.append(masked)
    return '\n'.join(out)


def scan_math_spans(text):
    """按文档顺序返回行内/块级公式 span，供校验与拆包共享。

    排除代码围栏内部、行内代码与转义美元。行内公式为同一行内成对
    `` $…$ ``：内容首尾不得为空白，闭合 `` $ `` 不得紧跟数字，以排除
    普通货币文本；块级公式为 `` $$…$$ `` 或源家族的 `` \\[…\\] `` 表示，
    可跨行。expr/raw 均为原文切片，不做任何归一化。
    """
    masked = _math_scan_mask(text)
    spans = []
    block_regions = []
    for regex in (_MATH_BLOCK, _MATH_BRACKET_BLOCK):
        for match in regex.finditer(masked):
            raw = text[match.start():match.end()]
            expr = raw[2:-2]
            if not expr.strip():
                continue
            spans.append(MathSpan(
                kind='block', expr=expr, raw=raw,
                start=match.start(), end=match.end(),
                start_line=masked.count('\n', 0, match.start()) + 1))
            block_regions.append((match.start(), match.end()))
        chars = list(masked)
        for start, end in block_regions:
            for p in range(start, end):
                if chars[p] != '\n':
                    chars[p] = ' '
        masked = ''.join(chars)
        block_regions = []
    for match in _MATH_INLINE.finditer(masked):
        raw = text[match.start():match.end()]
        spans.append(MathSpan(
            kind='inline', expr=raw[1:-1], raw=raw,
            start=match.start(), end=match.end(),
            start_line=masked.count('\n', 0, match.start()) + 1))
    spans.sort(key=lambda span: span.start)
    return spans


def compare_math_spans(src_spans, doc_spans, src_label='源文', doc_label='译文',
                       approved_extra_exprs=()):
    """按（类型、顺序、原表达式）逐项比较公式。

    返回 (diffs, warns)：diffs 非空即硬失败；warns 为回源定性告警
    （如源译一致的历史包装）。doc 侧表达式逐条命中 approved_extra_exprs
    的视为获准译注公式，豁免后参与对账，不掩盖源公式遗漏。
    """
    diffs = []
    warns = []

    doc_aligned = []
    pending = list(approved_extra_exprs)
    for span in doc_spans:
        if span.expr in pending:
            pending.remove(span.expr)
            continue
        doc_aligned.append(span)
    if len(approved_extra_exprs) != len(pending):
        warns.append('获准译注公式: %d 处已按显式清单豁免对账'
                     % (len(approved_extra_exprs) - len(pending)))
    if pending:
        warns.append('获准译注清单中 %d 条未匹配到译文公式: %r'
                     % (len(pending), pending))

    _KIND_CN = {'inline': '行内', 'block': '块级'}
    if len(src_spans) != len(doc_aligned):
        diffs.append('公式数不一致: 源 %s %d 处（行内 %d/块级 %d）vs 译 %s %d 处'
                     % (src_label, len(src_spans),
                        sum(1 for s in src_spans if s.kind == 'inline'),
                        sum(1 for s in src_spans if s.kind == 'block'),
                        doc_label, len(doc_aligned)))
        for j in range(min(len(src_spans), len(doc_aligned)), len(src_spans)):
            span = src_spans[j]
            diffs.append('  源 %s 多余公式 #%d（L%d %s）: %r'
                         % (src_label, j + 1, span.start_line,
                            _KIND_CN[span.kind], span.expr))
        for j in range(min(len(src_spans), len(doc_aligned)), len(doc_aligned)):
            span = doc_aligned[j]
            diffs.append('  译 %s 多余公式 #%d（L%d %s）: %r'
                         % (doc_label, j + 1, span.start_line,
                            _KIND_CN[span.kind], span.expr))
    for i in range(min(len(src_spans), len(doc_aligned))):
        src, doc = src_spans[i], doc_aligned[i]
        tag = '公式 #%d' % (i + 1)
        if src.kind != doc.kind:
            diffs.append('%s 类型不一致: 源 %s L%d %s vs 译 %s L%d %s'
                         % (tag, src_label, src.start_line, _KIND_CN[src.kind],
                            doc_label, doc.start_line, _KIND_CN[doc.kind]))
        elif src.expr != doc.expr and (
                src.kind == 'inline' or src.expr.strip() != doc.expr.strip()):
            # 行内表达式逐字节比较；块级表达式仅首尾空白属排版差异
            # （内部空白与换行仍逐字节保留）
            diffs.append('%s 表达式不一致: 源 %s L%d %r vs 译 %s L%d %r'
                         % (tag, src_label, src.start_line, src.expr,
                            doc_label, doc.start_line, doc.expr))
            diffs.append('%s 表达式不一致: 源 %s L%d %r vs 译 %s L%d %r'
                         % (tag, src_label, src.start_line, src.expr,
                            doc_label, doc.start_line, doc.expr))

    # 历史数学包装（\(...\) / \[...\]）：源译一致仅告警，译文新增失败
    def _wrapped(spans):
        return [s.expr.strip() for s in spans
                if (s.expr.startswith('\\(') and s.expr.endswith('\\)'))
                or (s.expr.startswith('\\[') and s.expr.endswith('\\]'))]

    src_wrapped = _wrapped(src_spans)
    doc_wrapped = _wrapped(doc_aligned)
    if doc_wrapped:
        if sorted(doc_wrapped) == sorted(src_wrapped):
            warns.append('历史数学包装: %d 处与源逐项一致，保留为回源定性告警'
                         % len(doc_wrapped))
        else:
            diffs.append('历史数学包装变化: 源 %r vs 译 %r'
                         % (sorted(src_wrapped), sorted(doc_wrapped)))
    return diffs, warns


def extract_approved_extra_math(argv):
    """从 argv 摘除重复的 --approved-extra-math <表达式>，返回 (剩余argv, 表达式列表)。"""
    exprs = []
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == '--approved-extra-math' and i + 1 < len(argv):
            exprs.append(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest, exprs


def extract_strong_tokens(argv):
    """从 argv 摘除重复的 --strong-token <token>，返回 (剩余argv, token 列表)。

    既有强 token 位置参数可与该显式参数并存，合并为同一检查列表。
    """
    tokens = []
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == '--strong-token' and i + 1 < len(argv):
            tokens.append(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest, tokens


_WS_RE = re.compile(r'\s+')


def heading_entries(text):
    """按文档顺序返回标题 (line_no, level, title)；排除代码围栏内行。

    title 保留官方原题的内容性字符（弯引号、全角括号等），仅去除首尾空白。
    参考手册源家族的深层嵌套标题（H7/H8）同样识别，不截断到 H6。
    """
    fenced = fenced_line_numbers(text)
    entries = []
    for line_no, line in enumerate(text.split('\n'), start=1):
        if line_no in fenced:
            continue
        m = re.match(r'^(#{1,8})\s+(.+)$', line.rstrip('\r'))
        if m:
            entries.append((line_no, len(m.group(1)), m.group(2).strip()))
    return entries


def heading_title_matches(expected, actual):
    """官方原题边界对照：空白归一化后，actual 等于 expected，或为
    expected 附加一个非空（…）中文后缀组。

    不做弯引号等内容性字符归一化，也不无条件截断第一个全角括号。
    """
    exp = _WS_RE.sub(' ', expected).strip()
    act = _WS_RE.sub(' ', actual).strip()
    if act == exp:
        return True
    if exp and act.startswith(exp):
        rest = act[len(exp):].strip()
        if len(rest) >= 3 and rest.startswith('（') and rest.endswith('）'):
            return True
    return False


def compare_headings(src_entries, doc_entries, src_label='源文',
                     doc_label='译文', level_shift=0, doc_skip_head=0):
    """按 (层级, 官方原题) 有序比较标题，返回差异诊断列表。

    level_shift 为源标题在交付物中的统一层级偏移（正数 = 降级，如分页
    路线整节降一级的已批准装配）；doc_skip_head 为交付开头由装配模板
    额外生成的标题数（如章节头），跳过后才逐项对照。
    """
    diffs = []
    aligned = doc_entries[doc_skip_head:]
    if len(src_entries) != len(aligned):
        diffs.append('标题数不一致: 源 %s %d 条 vs 译 %s %d 条'
                     % (src_label, len(src_entries), doc_label, len(aligned)))
        for j in range(min(len(src_entries), len(aligned)),
                       len(src_entries)):
            line_no, _, title = src_entries[j]
            diffs.append('  源 %s 缺失标题 #%d（L%d）: %r'
                         % (src_label, j + 1, line_no, title))
        for j in range(min(len(src_entries), len(aligned)),
                       len(aligned)):
            line_no, _, title = aligned[j]
            diffs.append('  译 %s 多余标题 #%d（L%d）: %r'
                         % (doc_label, j + 1, line_no, title))
    for i in range(min(len(src_entries), len(aligned))):
        s_line, s_level, s_title = src_entries[i]
        d_line, d_level, d_title = aligned[i]
        if s_level + level_shift != d_level:
            diffs.append('标题 #%d 层级不一致: 源 %s L%d H%d vs 译 %s L%d H%d'
                         % (i + 1, src_label, s_line, s_level,
                            doc_label, d_line, d_level))
        elif not heading_title_matches(s_title, d_title):
            diffs.append('标题 #%d 不一致: 源 %s L%d %r vs 译 %s L%d %r'
                         % (i + 1, src_label, s_line, s_title,
                            doc_label, d_line, d_title))
    return diffs


_FOOTNOTE_DEF_LINE_RE = re.compile(r'^\[\^([^\]]+)\]:', re.M)
_FOOTNOTE_REF_RE = re.compile(r'\[\^([^\]\s]+)\](?!:)')


def _footnote_counts(text):
    refs = {}
    for m in _FOOTNOTE_REF_RE.finditer(text):
        refs[m.group(1)] = refs.get(m.group(1), 0) + 1
    defs = {}
    for m in _FOOTNOTE_DEF_LINE_RE.finditer(text):
        defs[m.group(1)] = defs.get(m.group(1), 0) + 1
    return refs, defs


def footnote_diffs(src_text, doc_text, src_label='源文', doc_label='译文'):
    """以源引用/定义关系为基准核对脚注，返回 (diffs, warns)。

    支持数字与命名标签；译文删除引用、定义或完整一对均相对源检出；
    译文新增的脚注（如译注）仅作回源告警。
    """
    diffs = []
    warns = []
    s_refs, s_defs = _footnote_counts(src_text)
    d_refs, d_defs = _footnote_counts(doc_text)
    for label in sorted(set(s_refs) | set(s_defs)):
        sr, sd = s_refs.get(label, 0), s_defs.get(label, 0)
        dr, dd = d_refs.get(label, 0), d_defs.get(label, 0)
        if dr < sr:
            diffs.append('脚注 [^%s] 引用缺失: 源 %s %d 处 vs 译 %s %d 处'
                         % (label, src_label, sr, doc_label, dr))
        if dd < sd:
            diffs.append('脚注 [^%s] 定义缺失: 源 %s %d 处 vs 译 %s %d 处'
                         % (label, src_label, sd, doc_label, dd))
    for label in sorted((set(d_refs) | set(d_defs)) - set(s_refs) - set(s_defs)):
        warns.append('译文新增脚注 [^%s]（源无此标签），回源确认是否为译注' % label)
    return diffs, warns


def count_token(text, token):
    """项目强 token 出现次数；词形 token 按词边界计数。"""
    if re.search(r'\w', token):
        return len(re.findall(r'(?<!\w)' + re.escape(token) + r'(?!\w)', text))
    return text.count(token)


def strong_token_report(src_text, doc_text, tokens, src_label='源文',
                        doc_label='译文'):
    """项目强 token 多重集差异；返回 (diffs, warns)。

    tokens 为空时 diffs 为 None 并给出未配置告警，不冒称已检查。
    """
    if not tokens:
        return None, ['强 token: 未配置项目指定 token，此项未检查']
    diffs = []
    warns = []
    for token in tokens:
        sc = count_token(src_text, token)
        dc = count_token(doc_text, token)
        if dc < sc:
            diffs.append('强 token 遗漏 %r: 源 %s %d 处 vs 译 %s %d 处'
                         % (token, src_label, sc, doc_label, dc))
        elif dc > sc:
            warns.append('强 token 增加 %r: 源 %s %d 处 vs 译 %s %d 处'
                         % (token, src_label, sc, doc_label, dc))
    return diffs, warns


def extract_image_options(argv):
    """摘除 --image-map <file> 与 --delivery-root <dir>，返回 (剩余argv, 映射路径, 交付根)。"""
    image_map = None
    delivery_root = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == '--image-map' and i + 1 < len(argv):
            image_map = argv[i + 1]
            i += 2
        elif argv[i] == '--delivery-root' and i + 1 < len(argv):
            delivery_root = argv[i + 1]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return rest, image_map, delivery_root


def load_image_digests(image_map_path):
    """读取图片身份映射 JSON：{"digests": ["<identity>", ...]}（按出现顺序）。

    每条为该次出现的资源身份摘要（resource_identity_digest）：位图与
    自包含 SVG 为文件字节 sha256，含依赖的 SVG/CSS 递归纳入依赖身份。
    映射由原始快照独立建立，不从待验译文反推。
    """
    import json
    with open(image_map_path, encoding='utf-8') as f:
        payload = json.load(f)
    digests = payload.get('digests') if isinstance(payload, dict) else payload
    if not isinstance(digests, list) or not all(
            isinstance(d, str) for d in digests):
        raise SystemExit('图片身份映射格式无效: %s（需 {"digests": [sha256, ...]}）'
                         % image_map_path)
    return digests


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


_IMAGE_REF_STYLE = re.compile(r'!\[[^\]]*\]\[([^\]]+)\]')


def image_references(text):
    """按文档顺序返回实际图片引用 (line_no, src)。

    排除代码围栏内的图片字符串（图片语法示例不计为真实图片）；支持内联
    `` ![alt](src) `` 与引用式 `` ![alt][label] ``（由 `` [label]: url ``
    定义解析；未定义的引用 src 记为 None，按缺失处理）。同一行内两种
    语法混用时按实际字符位置统一排序，出现顺序与源文一致。
    """
    fenced = fenced_line_numbers(text)
    lines = text.split('\n')
    defs = {}
    for line_no, line in enumerate(lines, start=1):
        if line_no in fenced:
            continue
        m = re.match(r'^\s*\[([^\]]+)\]:\s*(\S+)', line)
        if m:
            defs[m.group(1).strip().lower()] = m.group(2)
    refs = []
    for line_no, line in enumerate(lines, start=1):
        if line_no in fenced:
            continue
        found = []
        for m in _IMAGE.finditer(line):
            found.append((m.start(), m.group(1)))
        for m in _IMAGE_REF_STYLE.finditer(line):
            label = m.group(1).strip().lower()
            found.append((m.start(), defs.get(label)))
        found.sort(key=lambda item: item[0])
        for _, src in found:
            refs.append((line_no, src))
    return refs


_IMG_MARKER_LINE = re.compile(r'^\s*\[IMG:\s*([^\]]+)\]')


def image_marker_refs(text):
    """按文档顺序返回非代码围栏内 `` [IMG: path] `` 标记 (line_no, path)。

    代码示例中的 `` [IMG:…] `` 字符串不是真实图片出现，不计入对账与身份。
    """
    fenced = fenced_line_numbers(text)
    refs = []
    for line_no, line in enumerate(text.split('\n'), start=1):
        if line_no in fenced:
            continue
        m = _IMG_MARKER_LINE.match(line)
        if m:
            refs.append((line_no, m.group(1).strip()))
    return refs


def image_occurrence_count(text):
    """源侧图片出现次数：Markdown 图片引用与 `` [IMG:…] `` 标记之和。

    代码围栏内的图片语法与标记不计数；用于源译出现次数对账，不依赖
    可选的身份映射参数。
    """
    return len(image_references(text)) + len(image_marker_refs(text))


def local_resource_digest(src, base_dir):
    """把一个图片引用解析为 base_dir 内文件的资源身份摘要；不可解析记 None。

    只接受 base_dir 内真实存在的相对路径文件；外链、机器绝对路径、
    纯片段、缺失与不可读文件均返回 None，不做任何联网或 cwd 回退。
    引用清理与路径解析复用 _clean_reference_target，摘要为资源身份
    （含 SVG/CSS 依赖，见 resource_identity_digest），是源译身份推导
    与恢复证据绑定的共同实现。
    """
    if not src:
        return None
    path = _clean_reference_target(src.strip(), base_dir)
    if path is None or not os.path.isfile(path):
        return None
    return resource_identity_digest(path)


def source_occurrence_digests(text, base_dir):
    """由可靠的当前源资源推导每次图片出现的来源身份摘要（按出现顺序）。

    Markdown 图片引用与 `` [IMG:…] `` 标记按行序合并为完整出现序列；
    全部出现都能解析为 base_dir 内可读本地文件时返回摘要列表（源无图时
    为空列表，同样是完整依据），任一出现无法解析时返回 None——身份依据
    不完整，调用方不得据此宣布完整通过。摘要取自当前源资源，不从待验
    译文反推。
    """
    entries = [(line_no, 0, src) for line_no, src in image_references(text)]
    entries.extend((line_no, 1, path)
                   for line_no, path in image_marker_refs(text))
    entries.sort(key=lambda item: (item[0], item[1]))
    digests = []
    for _, _, src in entries:
        digest = local_resource_digest(src, base_dir)
        if digest is None:
            return None
        digests.append(digest)
    return digests


def resolve_delivery_image(src, markdown_dir, delivery_root=None):
    """把交付引用解析为交付根内的绝对路径；不合法时返回 (None, 原因)。

    不允许外链/带协议引用与机器绝对路径；相对引用必须落在交付根内
    （默认 Markdown 所在目录，跨章共享资源时显式指定），不回退 cwd。
    """
    if not src:
        return None, '空图片引用'
    clean = src.split('#', 1)[0].split('?', 1)[0].strip()
    if not clean:
        return None, '空图片引用'
    if re.match(r'^[a-z][a-z0-9+.-]*:', clean, re.I):
        return None, '外链或带协议引用不允许（离线交付不热链）: %s' % src
    if os.path.isabs(clean) or clean.startswith('~'):
        return None, '机器绝对路径不允许: %s' % src
    root = os.path.abspath(delivery_root or markdown_dir)
    path = os.path.abspath(os.path.normpath(
        os.path.join(os.path.abspath(markdown_dir), clean)))
    if path != root and not path.startswith(root + os.sep):
        return None, '引用越出交付根: %s' % src
    return path, None


_PROTOCOL_RE = re.compile(r'^[a-z][a-z0-9+.-]*:', re.I)
_XLINK_HREF = '{http://www.w3.org/1999/xlink}href'
_HREF_ATTRS = (_XLINK_HREF, 'href', 'src')
# 按资源语义产生 CSS url(...) 引用的 SVG 属性（设计 7.2）；
# data-*、aria-*、说明与标识属性不扫描
_PRESENTATION_URL_ATTRS = frozenset({
    'fill', 'stroke', 'filter', 'clip-path', 'mask', 'marker',
    'marker-start', 'marker-mid', 'marker-end', 'cursor',
})
_PARSE_ERROR = 'error'
_CYCLE_IDENTITY = hashlib.sha256(b'techdoc-resource-cycle').hexdigest()


def _token_urls(tokens):
    """组件值序列中的 URL 节点 [(raw, False)]，按出现顺序递归进函数/块。

    tinycss2 语义：未加引号的 `` url(x) `` 是 URL token；带引号的
    `` url("x") `` 是名为 url 的函数块（实参为字符串 token），两者都
    产生引用。普通字符串 token 是字面文本，其内部的 url 字样不产生
    引用；注释由解析器跳过。bad-url、eof-in-string 等解析错误 token
    以 ``(诊断说明, _PARSE_ERROR)`` 上报：畸形片段可能截断或隐藏真实
    资源引用，不能默默当作零依赖。
    """
    refs = []
    for token in tokens:
        token_type = token.type
        if token_type == 'url':
            refs.append((token.value, False))
        elif token_type == 'error':
            refs.append(('CSS 组件值无法解析（可能隐藏资源引用）: %s'
                         % token.message, _PARSE_ERROR))
        elif token_type == 'function':
            if token.lower_name == 'url':
                for arg in token.arguments:
                    if arg.type == 'string':
                        refs.append((arg.value, False))
                        break
            refs.extend(_token_urls(token.arguments))
        elif token_type in ('()block', '[]block', '{}block'):
            refs.extend(_token_urls(token.content))
    return refs


def _stylesheet_refs(text):
    """样式表语境（.css 文件与 `` <style> `` 文本）的资源引用。

    `` [(raw, is_import)] ``：URL 节点产生普通引用；@import 的字符串与
    url(...) 参数产生导入引用（只取第一个，导入不重复计数）；无法解析
    的片段以 ``(诊断说明, _PARSE_ERROR)`` 返回，不默默当作零依赖。
    """
    refs = []
    for rule in tinycss2.parse_stylesheet(text, skip_comments=True,
                                          skip_whitespace=True):
        rule_type = rule.type
        if rule_type == 'qualified-rule':
            refs.extend(_token_urls(rule.content))
        elif rule_type == 'at-rule':
            if rule.lower_at_keyword == 'import':
                # @import 只取一个目标：字符串形式或 url(...) 形式
                for token in rule.prelude:
                    token_type = token.type
                    if token_type in ('string', 'url'):
                        refs.append((token.value, True))
                        break
                    if token_type == 'function' \
                            and token.lower_name == 'url':
                        for arg in token.arguments:
                            if arg.type == 'string':
                                refs.append((arg.value, True))
                                break
                        break
                # 错误检查独立于目标提取：遍历整个参数序列（含嵌套
                # 函数/块），找到目标后剩余参数中的解析错误同样上报，
                # 不静默跳过；条件中的 URL 只随错误路径处理，不产生引用
                refs.extend(
                    entry for entry in _token_urls(rule.prelude)
                    if entry[1] == _PARSE_ERROR)
            if rule.content is not None:
                refs.extend(_token_urls(rule.content))
        elif rule_type == 'error':
            refs.append(('CSS 片段无法解析（可能隐藏资源引用）: %s'
                         % rule.message, _PARSE_ERROR))
    return refs


def _declaration_list_refs(text):
    """style 声明列表语境的资源引用；声明值中的 URL 节点产生引用。

    该语境没有 @import（只在样式表顶层有效），无法解析的声明同样上报。
    """
    refs = []
    for node in tinycss2.parse_declaration_list(text, skip_comments=True,
                                                skip_whitespace=True):
        if node.type == 'declaration':
            refs.extend(_token_urls(node.value))
        elif node.type == 'error':
            refs.append(('CSS 声明无法解析: %s' % node.message, _PARSE_ERROR))
    return refs


def _attribute_value_refs(text):
    """展示属性值语境的资源引用（组件值序列中的 URL 节点）。"""
    return _token_urls(tinycss2.parse_component_value_list(text))


def _svg_resource_refs(root):
    """SVG 文档的原始资源引用 `` [(raw, is_import)] ``，按文档顺序。

    href/src/xlink:href 属性整体作为引用；style 属性按声明列表解析；
    fill/stroke/filter/clip-path/mask/marker 及 marker-start/mid/end、
    cursor 等展示属性按属性值解析 url(...)；`` <style> `` 元素文本按
    样式表解析（含 @import 两种形式）。data-*、aria-* 与说明/标识属性
    不扫描，元素普通文本与 XML 注释不产生依赖。
    """
    refs = []
    for elem in root.iter():
        for name, value in elem.attrib.items():
            if name in _HREF_ATTRS:
                refs.append((value.strip(), False))
                continue
            local = name.rsplit('}', 1)[-1]
            if local in ('href', 'src'):
                refs.append((value.strip(), False))
            elif local == 'style':
                refs.extend(_declaration_list_refs(value))
            elif local in _PRESENTATION_URL_ATTRS:
                refs.extend(_attribute_value_refs(value))
        if elem.tag.rsplit('}', 1)[-1] == 'style' and elem.text:
            refs.extend(_stylesheet_refs(elem.text))
    return refs


def _effective_reference(raw):
    """返回参与核验的引用；空、纯内部片段与自包含 data: 返回 None。"""
    ref = raw.strip()
    if not ref or ref.startswith('#') or ref.lower().startswith('data:'):
        return None
    return ref


def _clean_reference_target(ref, base_dir):
    """去掉片段/查询后把相对引用解析为绝对路径；非本地引用返回 None。"""
    clean = ref.split('#', 1)[0].split('?', 1)[0].strip()
    if not clean:
        return None
    if _PROTOCOL_RE.match(clean) or os.path.isabs(clean) \
            or clean.startswith('~'):
        return None
    return os.path.normpath(os.path.join(base_dir, clean))


def _dependency_kind(path, is_import=False):
    """依赖文档类型：@import 与 .css 目标按 CSS 递归，含 `` <svg `` 者按
    SVG 递归，其余为普通文件（存在性核验即可）。"""
    if is_import or path.lower().endswith('.css'):
        return 'css'
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return 'file'
    if b'<svg' in data.lower():
        return 'svg'
    return 'file'


def _svg_processing_instruction_targets(text):
    """按 XML 语义返回处理指令 target 列表（按文档顺序）。

    普通 XML 声明（`` <?xml ...?> ``）不是处理指令，不产生 pi 事件；
    注释与元素文本中形似处理指令的内容分别走 comment 事件或文本节点，
    不会被误报。文档无效时返回空列表，XML 有效性由调用方另行诊断。
    """
    import io
    import xml.etree.ElementTree as ET
    targets = []
    try:
        for _event, node in ET.iterparse(io.StringIO(text), events=('pi',)):
            # pi 事件的节点 tag 是 ProcessingInstruction 工厂，target 在
            # text 首部（"target data" 形式）
            data = (node.text or '').strip()
            if data:
                targets.append(data.split(None, 1)[0])
    except ET.ParseError:
        pass
    return targets


def _unsupported_svg_structures_fails(text):
    """尚未支持但会影响资源核验的 SVG 结构诊断列表（按文档顺序）。

    `` xml-stylesheet `` 处理指令声明外部样式表关联，当前未实现其加载
    与 CSS 绑定，相关资源依赖无法核验；报告所属结构与未验证原因，
    不默默当作零依赖。不要求在本层实现处理指令的完整语义。
    """
    fails = []
    for target in _svg_processing_instruction_targets(text):
        if target == 'xml-stylesheet':
            fails.append(
                'SVG 含未支持的 XML 处理指令 xml-stylesheet：'
                '样式表关联结构尚未实现，资源依赖未验证')
    return fails


def _dependency_fails(path, text, kind, delivery_root, visited):
    """递归核验一个 SVG/CSS 文档的实际资源依赖；返回失败诊断列表。

    - SVG：XML 无效或根元素非 svg 即失败；xml-stylesheet 等尚未支持且
      影响资源核验的结构按所属文件报告未验证原因，阻断完整通过；
    - 引用（属性 href/src、展示属性与 style 的 url(...)、`` <style> `` 的
      @import）不允许外部协议与机器绝对路径，必须落在交付根内且真实存在；
      网络/伪 URL 只按语义引用位置判定，注释、字符串与 data-*/aria 属性
      中的 url 文本不产生依赖（设计 7.2）；
    - 被引用 SVG/CSS 递归核验后续资源（导入样式表中的缺失资源与继续导入
      同样失败），相对引用以实际所属文件为基点；诊断带所属文件与语境标签；
      visited 以规范化绝对路径去重，循环引用不会无限递归，按其实际有效性
      处理。
    """
    import xml.etree.ElementTree as ET
    real = os.path.realpath(path)
    if real in visited:
        return []
    visited.add(real)
    kind_label = 'SVG' if kind == 'svg' else 'CSS'
    owner = os.path.basename(path)
    if kind == 'svg':
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            return ['SVG 不是有效的 XML 文档: %s' % exc]
        local = root.tag.rsplit('}', 1)[-1]
        if local != 'svg':
            return ['非 SVG 文档: 根元素 %s' % local]
        unsupported = _unsupported_svg_structures_fails(text)
        if unsupported:
            return ['[%s] %s' % (owner, msg) for msg in unsupported]
        refs = _svg_resource_refs(root)
    else:
        refs = _stylesheet_refs(text)
    fails = []
    base = os.path.dirname(path)
    root_abs = os.path.abspath(delivery_root)
    for raw, is_import in refs:
        if is_import == _PARSE_ERROR:
            fails.append('[%s] %s' % (owner, raw))  # 片段可能隐藏资源引用
            continue
        ref = _effective_reference(raw)
        if ref is None:
            continue
        if _PROTOCOL_RE.match(ref):
            fails.append('%s 含外部网络依赖引用: %s' % (kind_label, ref))
            continue
        if os.path.isabs(ref) or ref.startswith('~'):
            fails.append('%s 依赖机器绝对路径: %s' % (kind_label, ref))
            continue
        target = _clean_reference_target(ref, base)
        if target is None:
            continue
        if target != root_abs and not target.startswith(root_abs + os.sep):
            fails.append('%s 依赖越出交付根: %s' % (kind_label, ref))
            continue
        if not os.path.isfile(target):
            fails.append('[%s] %s 本地依赖缺失: %s' % (owner, kind_label, ref))
            continue
        child_kind = _dependency_kind(target, is_import)
        if child_kind == 'file':
            continue  # 非 SVG/CSS 资源（位图等）只需存在且在交付根内
        try:
            with open(target, encoding='utf-8') as f:
                child_text = f.read()
        except OSError as exc:
            fails.append('SVG 嵌套依赖不可读 %s: %s' % (ref, exc))
            continue
        for msg in _dependency_fails(target, child_text, child_kind,
                                     delivery_root, visited):
            fails.append('%s 嵌套依赖 %s: %s' % (kind_label, ref, msg))
    return fails


def _check_svg_document(path, text, delivery_root=None):
    """把文件按真实 SVG 文档校验：XML 有效、根元素为 svg、依赖离线可用。

    交付根默认为本文件所在目录；调用方处于最终路径语境时显式传入与
    Markdown 引用一致的交付根。
    """
    root_abs = os.path.abspath(delivery_root) if delivery_root \
        else os.path.dirname(os.path.abspath(path))
    fails = _dependency_fails(path, text, 'svg', root_abs, set())
    if fails:
        return False, None, fails[0]
    return True, 'SVG', None


def resource_identity_digest(path, kind=None, _stack=(), _memo=None):
    """资源的内容身份摘要：决定实际图片内容的依赖一并纳入。

    位图与自包含文件为其字节 sha256；SVG/CSS 文档按文档引用顺序把每个
    依赖的身份摘要纳入自身摘要——子资源内容变化即身份变化，顶层文件
    相同而依赖被换图无法绕过身份核对。

    - 引用字符串已包含在自身字节中，不重复计入身份；
    - 循环依赖以固定环标记贡献，结果稳定；realpath 只用作单次计算内的
      去重键，机器绝对路径不进入身份本身，交付目录搬迁后身份不变；
    - 任一依赖缺失、不可读或为外部/绝对路径引用时返回 None——身份依据
      不完整，调用方不得据此宣布完整通过，可补验（补资源或改用映射）；
      SVG 含 xml-stylesheet 等尚未支持的处理指令时同样返回 None；
    - 不联网；身份计算与交付根无关，交付侧依赖边界由离线核验负责。
    """
    real = os.path.realpath(path)
    if real in _stack:
        return _CYCLE_IDENTITY
    if _memo is None:
        _memo = {}
    if real in _memo:
        return _memo[real]
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if kind is None:
        kind = _dependency_kind(path)
    if kind == 'file':
        digest = hashlib.sha256(data).hexdigest()
        _memo[real] = digest
        return digest
    parts = []
    if kind == 'svg':
        import xml.etree.ElementTree as ET
        text = data.decode('utf-8', 'replace')
        if _unsupported_svg_structures_fails(text):
            return None  # 处理指令结构未支持，依赖身份依据不完整
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            root = None
        refs = _svg_resource_refs(root) \
            if root is not None and root.tag.rsplit('}', 1)[-1] == 'svg' \
            else []
    else:
        refs = _stylesheet_refs(data.decode('utf-8', 'replace'))
    base = os.path.dirname(path)
    for raw, is_import in refs:
        if is_import == _PARSE_ERROR:
            return None  # 文档无法可靠解析，依赖清单不完整
        ref = _effective_reference(raw)
        if ref is None:
            continue
        target = _clean_reference_target(ref, base)
        if target is None or not os.path.isfile(target):
            return None  # 外部/绝对路径或缺失依赖，身份依据不完整
        child = resource_identity_digest(
            target, _dependency_kind(target, is_import),
            _stack + (real,), _memo)
        if child is None:
            return None
        parts.append(child.encode())
    if parts:
        # 含依赖文档：v1 复合摘要（依赖内容变化即身份变化）
        digest = hashlib.sha256(b'\x00'.join(
            [b'techdoc-identity-v1', data] + parts)).hexdigest()
    else:
        # 位图与自包含文档：字节 sha256，与既有映射/证据摘要兼容
        digest = hashlib.sha256(data).hexdigest()
    _memo[real] = digest
    return digest


def check_image_file(path, delivery_root=None):
    """读取实际资源并判型；返回 (ok, kind, reason)。不联网。

    覆盖 PNG/JPEG/GIF/WebP 魔数；疑似 SVG 的文件必须解析为有效 XML 文档
    （根元素 svg）并核对其离线依赖（href/src、fill/stroke/filter/
    clip-path/mask/marker 等展示属性与 style 的 url(...)、<style> 的
    @import 与 url(...)，导入样式表递归，全部约束在交付根内），不能凭
    `<svg` 字符串接受；空文件、HTML 伪装与未知类型一律拒绝。
    """
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
            f.seek(0)
            data = f.read()
    except OSError as exc:
        return False, None, '资源不可读: %s' % exc
    if not data:
        return False, None, '空文件'
    magics = [(b'\x89PNG\r\n\x1a\n', 'PNG'), (b'\xff\xd8\xff', 'JPEG'),
              (b'GIF87a', 'GIF'), (b'GIF89a', 'GIF')]
    for magic, kind in magics:
        if head.startswith(magic):
            return True, kind, None
    if head[:4] == b'RIFF' and len(head) >= 12 and head[8:12] == b'WEBP':
        return True, 'WEBP', None
    text = data.decode('utf-8', 'replace')
    if '<svg' in text.lower() or text.lstrip().startswith('<?xml'):
        return _check_svg_document(path, text, delivery_root)
    try:
        out = subprocess.run(['file', '-b', path], capture_output=True,
                             text=True, check=True).stdout
    except Exception:
        return False, None, '未知文件类型'
    if 'image' in out.lower():
        return True, out.strip().split()[0], None
    return False, None, '非图片文件: %s' % out.strip()


def image_occurrence_fails(text, markdown_dir, delivery_root=None,
                           expected_digests=None, label='交付'):
    """按最终路径语境核验离线图片；返回失败诊断列表。

    每次出现都解析到交付根内、读取实际文件并判型（SVG 依赖同步按交付根
    递归核验）；expected_digests 为按出现顺序的来源身份摘要
    （resource_identity_digest，含 SVG/CSS 依赖内容），可来自既定独立
    映射（原始快照与暗亮选择建立）或可靠的当前源资源（见
    source_occurrence_digests），不能从待验译文反推；数量或任一身份不符
    即失败，顶层换图、子资源换图与重命名绕过均被检出。
    """
    fails = []
    refs = image_references(text)
    if expected_digests is not None and len(refs) != len(expected_digests):
        fails.append('图片身份映射 %d 条与 %s 实际出现 %d 次不符'
                     % (len(expected_digests), label, len(refs)))
    for order, (line_no, src) in enumerate(refs, start=1):
        path, reason = resolve_delivery_image(src, markdown_dir, delivery_root)
        if reason:
            fails.append('%s L%d 图片 #%d: %s' % (label, line_no, order, reason))
            continue
        if not os.path.isfile(path):
            fails.append('%s L%d 图片 #%d 交付缺失: %s'
                         % (label, line_no, order, src))
            continue
        ok, kind, reason = check_image_file(path, delivery_root or markdown_dir)
        if not ok:
            fails.append('%s L%d 图片 #%d 类型异常: %s（%s）'
                         % (label, line_no, order, src, reason))
            continue
        if expected_digests is not None and order <= len(expected_digests):
            digest = resource_identity_digest(path)
            if digest is None:
                fails.append('%s L%d 图片 #%d 来源身份无法核验: %s'
                             '（依赖缺失或不可读）' % (label, line_no, order, src))
            elif digest != expected_digests[order - 1]:
                fails.append('%s L%d 图片 #%d 来源身份不符: %s 与映射摘要不一致'
                             % (label, line_no, order, src))
    return fails


def missing_images(text, base_dir, allow_cwd=False):
    """返回不存在的本地图片引用；HTTP(S) 外链不参与本地检查。"""
    missing = []
    for source in image_sources(text):
        path = source.split('#')[0].split('?')[0]
        if os.path.exists(os.path.join(base_dir, path)):
            continue
        if source.startswith('http://') or source.startswith('https://'):
            continue
        if allow_cwd and os.path.exists(path):
            continue
        missing.append(source)
    return missing


def residual_markers(text, markers):
    """返回残留的已知标记和块级占位符，保留出现顺序。"""
    residuals = [marker for marker in markers if marker in text]
    residuals.extend('[%s]' % match.group(1)
                     for match in _BLOCK_PLACEHOLDER.finditer(text))
    return residuals
