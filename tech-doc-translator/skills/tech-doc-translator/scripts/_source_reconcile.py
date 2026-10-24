"""解析入口共用的原 HTML → 解析 Markdown 独立对账。

源事实直接从原始快照 HTML 独立提取（全新 BeautifulSoup 实例，不接触
渲染器的处理后 DOM、占位池或输出清单）；解析侧复用 `_verification` 的
成熟扫描能力识别输出范围。逐项比较标题、代码、公式、图片、脚注引用/
定义、表格与列表的内容、位置和顺序；计数只作摘要。任何无法解释为合法
转换的差异都计为损伤，由调用方在分派前非零退出。
"""
import copy
import hashlib
import json
from html import escape
import os
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from _html_fidelity import (
    _INLINE_TAGS,
    HtmlFidelity,
    clean_code_html,
    markdown_inline_code,
    protect_code_entities,
)
from _verification import (
    SourceMathContext as _SourceMathContext,
    _HEADING_FACTS_MD,
    fenced_line_numbers,
    heading_entries,
    image_marker_spans,
    image_reference_spans,
    line_code_spans,
    parse_inline_code_spans,
    resolve_backslash_escapes,
    scan_code_fences,
    scan_math,
    table_math_spans, markdown_table_row_lines, markdown_table_tokens,
    decode_table_math,
    footnote_definition_block,
)

_WS_RE = re.compile(r'\s+')
# 链接标签可含转义括号（\[ \]）；标签与 URL 均按转义感知匹配，
# 避免在标签内的 \] 或 ( 处提前截断
_MD_LINK_RE = re.compile(r'\[((?:\\.|[^\[\]])*)\]\(((?:\\.|[^()])*)\)')
_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_IMG_MARKER_RE = re.compile(r'\[IMG:\s*[^\]]*\]')
_MD_FOOTNOTE_RE = re.compile(r'\[\^([^\]]+)\]')
_MD_MATH_RE = re.compile(r'\$+([^$]*)\$+')
_MD_CODE_SPAN_RE = re.compile(r'(`+)(.*?)\1', re.S)
_SRC_MATH_WRAP_RE = re.compile(r'\\\(|\\\)|\\\[|\\\]')
_FENCE_LINE_RE = re.compile(r'^\s*(`{3,}|~{3,})')
_TABLE_CODE_MARKER_RE = re.compile(
    r'^\[TABLE-CODE r=(\d+) c=(\d+)#(\d+)\]$')
_TABLE_CODE_NOTE_RE = re.compile(r'^本表第 (\d+) 行、第 (\d+) 列的代码 (\d+)：$')
_TABLE_CAPTION_LINE_RE = re.compile(r'\s*(?:\*\*)?(?:\[TABLE-CAPTION\]|(?:Table\s+|表\s*)[0-9A-Za-z])')
_MD_LIST_MARKER_RE = re.compile(r'^(\s*)-(?: (\S.*?))?\s*$')

# 实际 Markdown 的真实行内阅读（CommonMark）：强调、反斜线转义、链接
# 与行内代码的生成语法只解码一次，得到阅读文字（§7.11.5：实际端按真实
# 阅读取事实，不消费生成侧自报文字）
from markdown_it import MarkdownIt as _MarkdownIt

_MD_INLINE_READ = _MarkdownIt('commonmark', {'html': False})

# 真实阅读的跨度占位符（私用区字符，markdown-it 原样保留）：数学/图片
# 跨度先换成占位符整段一次行内阅读，强调/链接等成对语法跨跨度时仍能正
# 确解码，阅读后按占位符切回
_MD_READ_PLACEHOLDER_RE = re.compile('(\\d+)')


def _md_inline_reading(text, preserve_roles=False):
    """实际行内语法只阅读一次；LaTeXML 保留代码与链接叶子事实。"""
    if not text or not text.strip():
        return text
    rendered = BeautifulSoup(_MD_INLINE_READ.renderInline(text),
                             'html.parser')
    if preserve_roles:
        return _direct_read(rendered)
    return rendered.get_text()


class _ReadText(str):
    """已读文字及真实保护叶子；归一时不再次解释 Markdown 语法。"""
    def __new__(cls, template, leaves=()):
        value = re.sub('\ue004(\\d+)\ue005',
                       lambda m: leaves[int(m.group(1))], template)
        obj = str.__new__(cls, value)
        obj.template, obj.leaves = template, tuple(leaves)
        return obj


def _code_fact(content):
    # Internal role fact, never emitted into Markdown or the public record.
    return '\ue00a' + json.dumps(_norm_code_text(content)) + '\ue00b'


def _read_replace(pattern, replacement, text):
    if isinstance(text, _ReadText):
        return _ReadText(re.sub(pattern, replacement, text.template), text.leaves)
    return re.sub(pattern, replacement, text)


def _norm_reading(text, source_context=None, **kwargs):
    """只归一普通文字。代码使用成熟跨度规则解码，精确内容不参与归一。"""
    already_read = isinstance(text, _ReadText)
    codes = list(text.leaves) if already_read else []
    parts = []
    cursor = 0
    if not already_read:
        def keep_fact(match):
            codes.append(match.group(0))
            return '\ue004%d\ue005' % (len(codes) - 1)
        text = re.sub('\ue00a.*?\ue00b', keep_fact, text, flags=re.S)
        for content, (start, end) in parse_inline_code_spans(text):
            parts.append(text[cursor:start])
            parts.append('\ue004%d\ue005' % len(codes))
            codes.append(_code_fact(content))
            cursor = end
        parts.append(text[cursor:])
    else:
        parts.append(text.template)
    # Ordinary normalization never defines math boundaries. The shared scanner
    # protects confirmed spans until after whitespace and syntax normalization.
    ordinary = ''.join(parts)
    maths = scan_math(ordinary, source_context=source_context).spans
    for index, span in reversed(list(enumerate(maths))):
        ordinary = ordinary[:span.start] + '\ue008%d\ue009' % index + ordinary[span.end:]
    normalized = _norm_text(ordinary, unwrap_links=False, reading=already_read, **kwargs)
    normalized = re.sub('\ue008(\\d+)\ue009',
                        lambda m: maths[int(m.group(1))].expr, normalized)
    result = _ReadText(normalized, codes)
    return result if already_read else str(result)


def _protected_reading(text, source_context=None, keep_math=False, table=False, preserve_roles=True):
    """共享扫描先保护公式，再且仅再做一次普通行内阅读。"""
    spans = scan_math(text, source_context=source_context).spans
    parts = []
    cursor = 0
    for index, span in enumerate(spans):
        parts.extend((text[cursor:span.start], '\ue006%d\ue007' % index))
        cursor = span.end
    parts.append(text[cursor:])
    reading = _md_inline_reading(''.join(parts), preserve_roles=preserve_roles)
    def restore(match):
        span = spans[int(match.group(1))]
        value = span.raw if keep_math else span.expr
        return decode_table_math(value, parsed=True) if table else value
    return _read_replace('\ue006(\\d+)\ue007', restore, reading)


def _direct_read(node):
    """独立 DOM 阅读：按源序保留代码、链接及文字，复用叶子表示规则。

    代码先保护再归一普通文字；链接目标直接读 href，标签递归读取。
    不调用生成器的宿主遍历或行内/块渲染出口。
    """
    protected = []

    def keep(value):
        protected.append(value)
        return '\ue004%d\ue005' % (len(protected) - 1)

    def read(el):
        parts = []
        for child in el.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                # Quote the private fact delimiters in literal DOM text;
                # only actual nodes may introduce protected role facts.
                parts.append(re.sub('[\ue004\ue005\ue00a\ue00b\ue00c\ue00d]',
                    lambda m: json.dumps(m.group(0))[1:-1], str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in ('script', 'style', 'noscript'):
                continue
            if child.name == 'br':
                parts.append(' ')
                continue
            if child.name == 'a' and any(
                    'headerlink' in c for c in (child.get('class') or [])):
                continue
            if child.name == 'code':
                parts.append(keep(_code_fact(child.get_text())))
                continue
            label = read(child)
            if child.name == 'a' and child.get('href') and label:
                target = _MD_INLINE_READ.normalizeLink(child['href'].strip())
                # Keep the real link boundary and protected target; the label
                # retains its ordinary text, code and math reading rules.
                parts.append('\ue00c' + label + keep(
                    '\ue00a' + json.dumps(['link', target]) + '\ue00b') + '\ue00d')
            else:
                parts.append(label)
        return ' '.join(part for part in parts if part.strip())

    text = read(node)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
    text = re.sub(r'([\[(]) ', r'\1', text).strip()
    return _ReadText(text, protected)


def _block_reading_facts(node, normalize=_norm_reading, table_facts=None):
    """有限的定义内有序块事实；DOM 来源与实际阅读 DOM 各自调用。"""
    facts = []
    inline = []

    def flush():
        if inline:
            fragment = BeautifulSoup(''.join(inline), 'html.parser')
            text = normalize(_direct_read(fragment))
            if text:
                facts.append(('p', text))
            inline.clear()

    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            inline.append(escape(str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        block_names = ('pre', 'p', 'ul', 'ol', 'table', 'div')
        if child.name not in block_names and not child.find(block_names):
            inline.append(str(child))
            continue
        flush()
        if child.name == 'pre':
            facts.append(('code', clean_code_html(
                child.decode_contents()).rstrip('\n')))
        elif child.name in ('ul', 'ol'):
            facts.append((child.name, tuple(
                _block_reading_facts(item, normalize, table_facts)
                for item in child.find_all('li', recursive=False))))
        elif child.name == 'table' and table_facts is not None:
            facts.extend(table_facts(child))
        elif child.name == 'table':
            facts.append(('table', tuple(tuple(
                normalize(_direct_read(cell))
                for cell in row.find_all(['td', 'th']))
                for row in child.find_all('tr'))))
        elif child.name != 'p':
            facts.extend(_block_reading_facts(child, normalize, table_facts))
        else:
            text = normalize(_direct_read(child))
            if text:
                facts.append(('p', text))
    flush()
    return tuple(facts)


def _markdown_block_facts(text, source_context):
    """真实块解析先确定结构；仅在行内阅读前保护共享数学跨度。"""
    expressions = []
    def protect_math(state):
        in_table = False
        for token in state.tokens:
            if token.type in ('table_open', 'table_close'):
                in_table = token.type == 'table_open'
            if token.type != 'inline':
                continue
            spans = scan_math(token.content, source_context=source_context).spans
            parts, cursor = [], 0
            for span in spans:
                parts.extend((token.content[cursor:span.start],
                              '\ue006%d\ue007' % len(expressions)))
                expressions.append(decode_table_math(span.expr, parsed=True) if in_table else span.expr)
                cursor = span.end
            parts.append(token.content[cursor:])
            token.content = ''.join(parts)
    reader = _MarkdownIt('commonmark', {'html': False}).enable('table')
    reader.core.ruler.before('inline', 'protect_math', protect_math)
    dom = BeautifulSoup(reader.render(text), 'html.parser')
    def normalize(value):
        return re.sub('\ue006(\\d+)\ue007',
                      lambda m: expressions[int(m.group(1))], _norm_reading(value))
    return _block_reading_facts(dom, normalize)

def _norm_code_text(content):
    """行内代码事实的文字口径：行结束符逐个转空格，其余逐字节保留。

    与渲染端 markdown_inline_code 同一口径（CommonMark 代码跨度的行
    结束语义）；语法填充由 _pad_code_content 按定界规则解码，真实边界
    空白是代码内容，两侧同用本口径比较，删除边界空格即为确定差异。
    """
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    return content.replace('\n', ' ')

# 与解析器分支一致的提示框识别口径（对 class 串做包含匹配）
_ADMONITION_TOKENS = ('admonition', 'note', 'warning', 'important', 'tip')


_MD_TABLE_SEP_CELL_RE = re.compile(r'^-*$')


def _norm_text(text, unwrap_links=True, mark_code=False,
               decode_heading_escape=False, resolve_escapes=False,
               strip_bracket_escapes=True, reading=False):
    """内容归一化：行内代码、链接/脚注/公式记法、空白与标点紧排。

    链接解包只用于输出侧（渲染后的 [标签](URL)）；源侧是纯文本，
    其中形似链接的字面量（如 “__fadd_[rn,rz,ru,rd](x, y)”）须保持
    原样，与输出侧链接标签归一后的文字一致。

    mark_code 为 True（标题流）：行内代码最先隔离为 \\x00 定界占位、
    内容不参与任何后续归一（图片语法删除、空白折叠都不能改写代码
    字面量），公式保留 ``$`` 定界（去定界的拍平必须可检）；其余步骤
    与普通口径一致。

    decode_heading_escape 仅由输出侧普通文本角色开启，且只在编码实际
    生效的位置（列表项首/续行、提示框引用行文字等行首角色）调用：
    按 Markdown 阅读语义解码——行首反斜线串偶数对折叠（\\\\→\\），尾余
    一个的转义反斜线消解（\\#→#），# 裸写，即还原实际阅读文字；源侧、
    代码与公式流不开启，不做全局反斜线删除。

    resolve_escapes 为 True（表格格位等行内语境）：全文按 Markdown
    行内阅读语义解析反斜线（\\+ASCII 标点→标点、\\\\→\\），代码跨度与
    公式内容字面保留（resolve_backslash_escapes），与源格字面文字比较
    实际阅读（F1）。此路径下链接先行解包，标签内的 \\[ \\] 由同一次
    阅读解析解释，不再手工二次替换。

    strip_bracket_escapes 为 False（真实标题路径）：标题事实已是
    按阅读语义解释过的文字（heading_entries），余下的 \\[ \\] 是阅读
    内容本身，不再当作生成语法剥离（F1：剥离会把阅读文字二次解释，
    与独立 DOM 预期不符而误拒合法输入）。生成语法侧（如源侧
    render_inline 序列化）保持默认 True，撤销生成的标签转义。"""
    code_spans = []
    if mark_code:
        def _keep_code(match):
            code_spans.append(_pad_code_content(match.group(2)))
            return '\x00%d\x00' % (len(code_spans) - 1)
        text = _MD_CODE_SPAN_RE.sub(_keep_code, text)
    link_labels = []
    if unwrap_links and resolve_escapes:
        # 链接解包先于反斜线解析，且标签以哨兵保护到归一化结束：标签内
        # 的 \[ \] 是链接语法，由 resolve_backslash_escapes 按阅读语义
        # 一次解释；若解析后再经下方的 \[ \] 剥离，同一反斜线被解释
        # 两次，双重加写的阅读损伤会被掩盖（R2）。图片语法先移除：
        # 图片的 [alt](src) 不是链接
        text = _MD_IMAGE_RE.sub(' ', text)
        text = _MD_IMG_MARKER_RE.sub(' ', text)

        def _keep_label(match):
            link_labels.append(match.group(1))
            return '\x00L%d\x00' % (len(link_labels) - 1)
        text = _MD_LINK_RE.sub(_keep_label, text)
    if resolve_escapes:
        text = resolve_backslash_escapes(text)
    if decode_heading_escape:
        text = re.sub(
            r'^(\\+)(#{1,8})(?=\s|$)',
            lambda m: '\\' * (len(m.group(1)) // 2) + m.group(2), text)
    if not resolve_escapes:
        text = _MD_IMAGE_RE.sub(' ', text)
        text = _MD_IMG_MARKER_RE.sub(' ', text)
    if not mark_code and not reading:
        text = _MD_CODE_SPAN_RE.sub(lambda m: _pad_code_content(m.group(2)),
                                    text)
    if unwrap_links and not resolve_escapes:
        text = _MD_LINK_RE.sub(lambda m: m.group(1).replace(
            '\\[', '[').replace('\\]', ']'), text)
    text = _MD_FOOTNOTE_RE.sub(r'[\1]', text)
    if not mark_code:
        text = _MD_MATH_RE.sub(r'\1', text)
    if strip_bracket_escapes:
        text = text.replace('\\]', ']').replace('\\[', '[')
    if not mark_code:
        text = _SRC_MATH_WRAP_RE.sub('', text)
    text = _WS_RE.sub(' ', text).strip()
    text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
    text = re.sub(r'([\[(]) ', r'\1', text)
    for index, span in enumerate(code_spans):
        text = text.replace('\x00%d\x00' % index, '\x00%s\x00' % span)
    for index, label in enumerate(link_labels):
        text = text.replace('\x00L%d\x00' % index,
                            _norm_link_label(label, resolve=True))
    return text


def _pad_code_content(content):
    """按 CommonMark 规则剥除代码跨度内容的成对边界空格。"""
    if content.startswith(' ') and content.endswith(' ') and content.strip():
        return content[1:-1]
    return content


def _norm_link_label(label, resolve):
    r"""链接标签的文字口径。

    输出侧（resolve=True）标签是 Markdown 源：取 markdown-it 实际行内
    阅读文字——转义、强调与代码跨度由真实解析一次完成，不再用反斜线
    解码加语法剥离的组合冒充阅读（F2：解码不是完整阅读，强调吃掉的
    字面星号会被漏过）。公式段先由代码感知的 scan_math 隔离为原文
    片段：普通阅读器无数学规则，会把 $a*b*c$ 的 *b* 当强调吃掉
    （P2-1），隔离后普通阅读只解释其余文字段，公式表达式按共享事实
    原文还原。只隔离美元定界跨度：链接标签是行内语境，其中的 \[ \]
    是生成的标签括号转义而非块级公式定界（R2 口径），由普通阅读的
    转义解析一次还原。源侧（resolve=False）是 DOM 字面文字：不做
    Markdown 强调剥离，字面标点保留；字面数学复用共享 scan_math
    边界去定界（与输出侧同一公式事实，相邻公式的闭合/开启美元不被
    吞并），代码跨度记法归一保持（与既有单元格文字口径一致）。两侧
    共有：脚注引用与剩余文字的数学记法归一、空白与标点紧排。
    """
    if resolve:
        math_exprs = []
        parts = []
        cursor = 0
        # scan_math 的链接语法转义掩蔽（_math_scan_mask）只在完整
        # [标签](URL) 形态下生效；抽出后的裸标签中的 \[ \] 会被当作
        # 块级公式定界，吞掉内部 $…$（P2-1 方括号包公式）。扫描前把
        # 标签包回合成链接语法还原掩蔽语境（标签由 _MD_LINK_RE 抽出，
        # 不含未转义 ]，包裹无歧义），跨度偏移回移一个字符；raw 非 $
        # 开头的过滤保留为 R2 角色防线
        wrapped = '[%s]()' % label
        for span in scan_math(wrapped).spans:
            if not span.raw.startswith('$'):
                continue  # 标签内 \[ \] 是括号转义，不是公式定界
            start, end = span.start - 1, span.end - 1
            parts.append(BeautifulSoup(
                _HEADING_FACTS_MD.renderInline(label[cursor:start]),
                'html.parser').get_text())
            parts.append('\x00M%d\x00' % len(math_exprs))
            math_exprs.append(span.expr)
            cursor = end
        parts.append(BeautifulSoup(
            _HEADING_FACTS_MD.renderInline(label[cursor:]),
            'html.parser').get_text())
        label = ''.join(parts)
    else:
        math_exprs = []
        # 源标签字面数学复用共享 scan_math 边界隔离为原文片段（与输出
        # 侧同一公式事实）：旧 _MD_MATH_RE 的 \$+ 会吞掉相邻公式的
        # 闭合/开启美元（$x$$y$ 被误归一为 xy$），与输出侧正确归一不
        # 一致而误拒。代码跨度由扫描器既有代码感知掩蔽（与输出侧口径
        # 一致），隔离后代码记法归一与剩余文字的 _MD_MATH_RE 行为不变
        # （金额等旧口径两侧同型保持）。只隔离美元定界跨度：源标签内
        # 的 \[ \] 是字面文字而非公式定界（与 _literal_math_exprs
        # 口径一致）
        parts = []
        cursor = 0
        # 按 _literal_math_exprs 的源字面角色在扫描前消除括号定界影响；
        # 等长掩蔽仅用于定位，文字及表达式仍从原标签截取。
        masked = label.replace('\\[', '  ').replace('\\]', '  ')
        for span in scan_math(masked).spans:
            if not span.raw.startswith('$'):
                continue
            parts.append(label[cursor:span.start])
            parts.append('\x00M%d\x00' % len(math_exprs))
            width = 1 if span.kind == 'inline' else 2
            math_exprs.append(label[span.start + width:span.end - width])
            cursor = span.end
        parts.append(label[cursor:])
        label = ''.join(parts)
        label = _MD_CODE_SPAN_RE.sub(lambda m: _pad_code_content(m.group(2)),
                                     label)
    label = _MD_FOOTNOTE_RE.sub(r'[\1]', label)
    label = _MD_MATH_RE.sub(r'\1', label)
    label = _WS_RE.sub(' ', label).strip()
    label = re.sub(r' ([.,;:!?)\]])', r'\1', label)
    label = re.sub(r'([\[(]) ', r'\1', label)
    for index, expr in enumerate(math_exprs):
        label = label.replace('\x00M%d\x00' % index, expr)
    return label


def _strip_math_wrappers(body):
    r"""DOM 已确认的数学包装去除：\(…\) 与 \[…\] 整体包裹时剥除。"""
    if (body.startswith('\\(') and body.endswith('\\)')) \
            or (body.startswith('\\[') and body.endswith('\\]')):
        return body[2:-2].strip()
    return body


def _family_math_expectation(node, family):
    r"""已识别数学节点按现行家族的行内/块级表示生成独立预期。

    源侧继续独立读取原 DOM，不接触渲染器输出；允许转换仅限家族合同
    已确认的表示：包装去除（\(…\)/\[…\]）、实体解码（DOM get_text）
    与行内格式空白序列化。序列化口径与各家族渲染器一致：paginated/
    reference 的 div.math 为块级（$$\n…\n$$，t = get_text(' ', strip=True)），
    paginated 为单行 $$…$$；api 的 div.math 为行内；
    其余（single 家族全部节点与各家族 span.math）走 render_inline 的
    行内序列化（换行折叠 + 一对最外层包装去除）。块级首尾排版空白在事实提取时
    归一（strip），内部逐字节保留。
    """
    if node.name == 'div' and family in ('paginated', 'reference'):
        body = _strip_math_wrappers(node.get_text(' ', strip=True))
        expr = body if family == 'paginated' else '\n' + body + '\n'
        return 'block', expr.strip()
    body = node.get_text().strip()
    body = _strip_math_wrappers(body)
    return 'inline', re.sub(r'\s*\n\s*', ' ', body)


def _footnote_label(text):
    digits = re.sub(r'\D', '', text or '')
    return digits or '?'


def _literal_math_exprs(text):
    """文本节点中的字面公式流 (kind, expr)；转义括号 `\\[…\\]` 是
    字面文字而非公式定界（与解析侧的剥离口径一致），行内格式空白
    序列化仅折叠换行，保留水平空白——两侧都
    在序列化后的文字上运行同一次共享扫描，类型与原表达式逐字节比较。"""
    serialized = re.sub(r'\s*\n\s*', ' ', text)
    stripped = serialized.replace('\\[', 'xx').replace('\\]', 'xx')
    result = []
    for span in scan_math(stripped).spans:
        width = 1 if span.kind == 'inline' else 2
        expr = serialized[span.start + width:span.end - width]
        result.append((span.kind, expr.strip() if width == 2 else expr))
    return result


def _literal_math_issues(text):
    """文本节点字面公式扫描的未解决定界（原偏移在序列化后的文字上）。"""
    serialized = re.sub(r'\s*\n\s*', ' ', text)
    stripped = serialized.replace('\\[', 'xx').replace('\\]', 'xx')
    return list(scan_math(stripped).issues)


def _in_pre(node):
    """节点（含文本节点）是否位于真实 `<pre>` 内。

    代码内美元串、反引号等是代码文字，不是正文公式/行内代码事实；
    文本节点同样按真实祖先排除（S08），否则 pre 内 `$x$` 会被同时
    登记为代码与公式，正确候选反而被对账拒绝。
    """
    return node.find_parent('pre') is not None


def _in_heading(node):
    """节点是否位于标题内；标题公式/行内代码由标题流按行内语义对账（S02）。

    图片不受此排除：图片是独立源事实，序列化无法表达的标题图片必须
    阻断分派，不能靠两侧同时排除获得通过。
    """
    for parent in node.parents:
        if isinstance(parent, Tag) and re.fullmatch(r'h[1-6]', parent.name):
            return True
    return False


def _rendered_raw_ancestors(node):
    """行内代码是否已由其他对账流按行内语义覆盖，避免双计。

    标题流按行内语义标记代码跨度（mark_code），标题内 `<code>` 不
    再进入行内代码事实流。图题、脚注 aside 与定义术语的内容同样经
    行内序列化输出（渲染侧保留代码跨度），其中 `<code>` 是独立源
    事实，必须留在事实流中由输出侧扫描对账——不得由渲染策略决定
    源事实有无（03-S1）。
    """
    for parent in node.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in ('pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            return True
    return False


def _api_tab_pairs(container):
    """独立读取一组标签与面板关系，不消费适配端的渲染顺序。"""
    design = 'sd-tab-set' in (container.get('class') or [])
    if design:
        labels = container.find_all(class_='sd-tab-label', recursive=False)
        panels = container.find_all(class_='sd-tab-content', recursive=False)
    else:
        def owned(node):
            return next((p for p in node.parents if isinstance(p, Tag)
                         and 'sphinx-tabs' in (p.get('class') or [])), None) is container
        labels = [node for node in container.find_all(True)
                  if (node.get('role') == 'tab' or 'sphinx-tabs-tab' in (node.get('class') or []))
                  and owned(node)]
        panels = [node for node in container.find_all(True)
                  if (node.get('role') == 'tabpanel' or 'sphinx-tabs-panel' in (node.get('class') or []))
                  and owned(node)]
    if not labels or len(labels) != len(panels):
        raise ValueError('标签页来源关系不完整: %s' % container.get('class'))
    pairs = []
    for ordinal, label in enumerate(labels):
        target = label.get('aria-controls')
        matches = [p for p in panels if p.get('id') == target] if target else [panels[ordinal]]
        if len(matches) != 1 or any(p is matches[0] for _, p in pairs):
            raise ValueError('标签页来源面板无法唯一定位: %s' % target)
        pairs.append((label, matches[0]))
    return pairs


class _SourceFacts:
    """从原始 HTML 独立提取的有序源事实流。"""

    def __init__(self, raw_html, family, section_id,
                 mathml_alttext=False):
        # LaTeXML 来源（二期）：MathML 格内公式以实体解码后的 alttext 为
        # 原 TeX（02 精确口径）；其他家族保持渲染文字口径不变
        self._mathml_alttext = mathml_alttext
        # `<code>` 内未转义的尖括号会被 HTML 解析器当标记吃掉；与渲染端
        # 共用同一保护（跳过 pre），保证源侧独立提取拿到相同的代码文字。
        soup = BeautifulSoup(protect_code_entities(raw_html, skip_pre=True),
                             'html.parser')
        if section_id:
            root = soup.find(id=section_id)
        else:
            root = (soup.find('article') or soup.find('main')
                    or soup.find('body'))
        self.root = root
        self.family = family
        self._soup = soup
        # 标题行内序列化与渲染端共用同一实现（S02），源事实仍从原始
        # HTML 的独立 DOM 提取，不接触渲染器输出
        self._inline = HtmlFidelity()
        # 章节归属：扁平节点序 + 标题节点位置（标题文字由 _headings 单独
        # 计算，这里只保留位置）
        self._flat = list(root.descendants) if root is not None else []
        self._index = {id(node): i for i, node in enumerate(self._flat)}
        # 章节唯一身份 = 标题在文档中的序号（同名小节不合并）
        self._heading_ordinals = {
            idx: ordinal + 1
            for ordinal, idx in enumerate(
                i for i, node in enumerate(self._flat)
                if isinstance(node, Tag) and re.fullmatch(r'h[1-6]', node.name))}
        if root is None:
            # 选区根缺失：事实流为空，由调用方（snapshot_image_stream/
            # snapshot_image_facts）按 None 合同处理，不抛属性异常。
            self.headings = []
            self.code = []
            self.math = []
            self.math_issues = []
            self.inline_code = []
            self.images = []
            self.image_facts = []
            self.footnote_refs = []
            self.footnote_defs = []
            self.admonitions = []
            self.table_records = []
            self.list_records = []
            self.terms = []
            return
        self.headings = self._headings()
        self.code = self._code()
        self.math_issues = []
        self.math = self._math()
        self.inline_code = self._inline_code()
        self.images = self._images()
        self.footnote_refs = self._footnote_refs()
        self.footnote_defs = self._footnote_defs()
        self.admonitions = self._admonitions()
        self.table_records = self._table_records()
        self.list_records = self._list_records()
        self.terms = self._terms()

    def _section_of(self, el):
        """元素所属章节：最后一个位于其之前的标题的序号（唯一身份）。

        序号从 1 起；返回 0 表示位于首个标题之前（前置区）。
        """
        idx = self._index.get(id(el))
        if idx is None:
            return 0
        section = -1
        for h_idx in self._heading_ordinals:
            if h_idx < idx and h_idx > section:
                section = h_idx
        return self._heading_ordinals.get(section, 0)

    def _headings(self):
        r"""标题事实 (层级, 行内序列化文字)：与渲染端 heading_text 同一
        序列化，行内代码以 \x00 定界参与比较——拍平或改字即差异。
        render_inline 对链接标签生成的 \[ \] 转义只在标签内撤销一层，
        恢复 DOM 字面标签（F1：标题路径不再全局剥离，纯文本中的字面
        \[ 保持；链接目标身份保留）。"""
        entries = []
        for h in self.root.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            if _in_pre(h):
                continue
            copied = copy.deepcopy(h)
            for link in copied.find_all('a', class_='headerlink'):
                link.decompose()
            text = self._inline.render_inline(copied)
            text = _MD_LINK_RE.sub(
                lambda m: '[%s](%s)' % (
                    m.group(1).replace('\\[', '[').replace('\\]', ']'),
                    m.group(2)),
                text)
            entries.append((int(h.name[1]), _norm_text(
                text.replace('¶', '').replace('\uf0c1', ''),
                unwrap_links=False, mark_code=True,
                strip_bracket_escapes=False)))
        return entries

    def _code(self):
        blocks = []
        for pre in self.root.find_all('pre'):
            body = clean_code_html(pre.decode_contents())
            blocks.append((self._section_of(pre), self._index[id(pre)], 0,
                           'code', body.rstrip('\n')))
        return blocks

    def _math(self):
        """公式流 (kind, expr)：class=math 元素与文本节点中的字面 $…$。

        解析器把 span/div.math 转成 `$…$`（或 paginated/reference 的
        `$$…$$`），正文中本就存在的 `$…$` 文字原样保留并同样参与公式
        扫描；源侧流必须同时覆盖两类，才能与解析结果的扫描口径一致。
        已识别节点按 `_family_math_expectation` 生成独立预期（保留
        行内/块级类型与原表达式，不做任意归一）；字面数学用共享
        scan_math 的同一次扫描定义。issues 单独登记，由对账入口阻断。
        """
        spans = []

        sub_by_index = {}
        for node in self.root.descendants:
            if _in_pre(node) or _in_heading(node):
                continue
            if isinstance(node, Tag):
                classes = node.get('class') or []
                if 'math' in classes:
                    order = self._index[id(node)]
                    sub = sub_by_index.get(order, 0)
                    sub_by_index[order] = sub + 1
                    kind, expr = _family_math_expectation(node, self.family)
                    spans.append((self._section_of(node), order, sub, kind,
                                  expr))
                continue
            if isinstance(node, str):
                if (node.find_parent(class_='math') is not None
                        or node.find_parent('code') is not None):
                    continue
                order = self._index[id(node)]
                sub = sub_by_index.get(order, 0)
                self.math_issues.extend(_literal_math_issues(str(node)))
                for kind, expr in _literal_math_exprs(str(node)):
                    spans.append((self._section_of(node), order, sub, kind,
                                  expr))
                    sub += 1
                sub_by_index[order] = sub
        return spans

    def _inline_code(self):
        """行内代码事实流：真实 `<code>` 与文本中的字面反引号跨度。

        文本里的字面 `x` 在 Markdown 中同样是代码跨度，两侧都计入才能
        与输出侧扫描口径一致（与公式流覆盖两类来源的口径相同）。
        第 5 位为同文档序内的子序，供节内稳定排序使用。
        """
        spans = []
        sub_by_index = {}
        for node in self.root.descendants:
            if _in_pre(node) or _rendered_raw_ancestors(node):
                continue
            if isinstance(node, Tag):
                if node.name != 'code' or node.find_parent('code') is not None:
                    continue
                order = self._index[id(node)]
                sub = sub_by_index.get(order, 0)
                sub_by_index[order] = sub + 1
                spans.append((self._section_of(node), order, sub,
                              'inline-code', _norm_code_text(node.get_text())))
                continue
            if isinstance(node, str):
                if node.find_parent('code') is not None:
                    continue
                for content, _range in parse_inline_code_spans(str(node)):
                    order = self._index[id(node)]
                    sub = sub_by_index.get(order, 0)
                    sub_by_index[order] = sub + 1
                    spans.append((self._section_of(node), order, sub,
                                  'inline-code', _norm_code_text(content)))
        return spans

    def _image_src(self, img):
        if self.family == 'api':
            cls = ' '.join(img.get('class') or [])
            if 'only-dark' in cls or (img.get('data-dark')
                                      and not img.get('data-light')):
                return None
            return img.get('data-light') or img.get('src', '')
        return img.get('src', '')

    def _images(self):
        refs = []
        self.image_facts = []
        # 源节点序号与解析期映射的 source_node 同一命名空间：全文 img 中
        # 排除 pre 内图片后的文档序（HtmlFidelity 解析时 pre 被占位保护，
        # 其 find_all('img') 同样不含 pre 内图片）。
        selectable = [img for img in self._soup.find_all('img')
                      if not _in_pre(img)]
        ordinals = {id(img): index
                    for index, img in enumerate(selectable)}
        for img in self.root.find_all('img'):
            if _in_pre(img):
                continue
            source_ref = self._image_src(img)
            if not source_ref:
                continue
            src = source_ref
            if self.family == 'reference':
                src = 'images/%s' % src.rsplit('/', 1)[-1]
            refs.append((self._section_of(img), self._index[id(img)], 0,
                         'image', src))
            # 结构化事实保留原始源引用（reference 的 images/<basename>
            # 改写只用于交付匹配/对账投影，不覆盖源路径）与源节点，
            # 供交付身份按声明快照目录定位资源（§9.3）。
            self.image_facts.append({
                'section': self._section_of(img),
                'order': self._index[id(img)],
                'node': 'img[%d]' % ordinals[id(img)],
                'src': src,
                'source_ref': source_ref,
            })
        return refs

    def _footnote_refs(self):
        labels = []
        for el in self.root.find_all(True):
            if _in_pre(el):
                continue
            if el.find_parent(class_='footnote-reference') is not None:
                continue  # 引用元素整体只计一次
            cls = ' '.join(el.get('class') or [])
            if 'footnote-reference' in cls:
                labels.append((_footnote_label(el.get_text()),
                               self._index[id(el)]))
                continue
            if el.name == 'sup':
                text = el.get_text(strip=True)
                if re.fullmatch(r'\[\d+\]|\(\d+\)', text):
                    labels.append((_footnote_label(text), self._index[id(el)]))
        return labels

    def mapped_cell_of(self, order):
        """内容事实所属的顶层表格格位；不在（已登记的）表格内返回 None。"""
        node = (self._flat[order]
                if order is not None and 0 <= order < len(self._flat) else None)
        cell = node.find_parent(['td', 'th']) if node is not None else None
        return self._cell_positions.get(id(cell)) if cell is not None else None

    def _footnote_defs(self):
        """脚注定义：dl 全编号 dt 列表与 aside[doc-footnote]，含正文文字。

        返回 [(label, 正文)]；与解析侧脚注定义条目成对比较，正文被替换
        即可检出（R9：脚注定义内容保留）。
        """
        defs = []
        for dl in self.root.find_all('dl'):
            if _in_pre(dl) or dl.find_parent('table') is not None:
                continue
            dts = dl.find_all('dt', recursive=False)
            if not dts or not all(
                    re.fullmatch(r'\[\d+\]|\(\d+\)|\d+',
                                 dt.get_text(strip=True)) for dt in dts):
                continue
            dds = dl.find_all('dd', recursive=False)
            for dt, dd in zip(dts, dds):
                defs.append((_footnote_label(dt.get_text()),
                             self._footnote_prose(dd) if self.family == 'api'
                             else _norm_text(dd.get_text(' '))))
        for aside in self.root.find_all('aside'):
            if _in_pre(aside):
                continue
            role = aside.get('role') or ''
            cls = ' '.join(aside.get('class') or [])
            if 'doc-footnote' not in role and 'footnote' not in cls.split():
                continue
            text = re.sub(r'\s+', ' ', aside.get_text(' ', strip=True))
            match = re.match(r'^[\[(]\s*(\d+)\s*[\])]\s*(.*)$', text)
            if match:
                defs.append((match.group(1), self._footnote_prose(aside)
                             if self.family == 'api' else _norm_text(
                                 match.group(2), unwrap_links=False)))
        return defs

    def _footnote_prose(self, node):
        # 富脚注的代码、列表、表格和图片由各自事实对账；独立保留全部正文段落。
        copied = copy.deepcopy(node)
        for label in copied.find_all(class_='label'):
            label.decompose()
        return ' '.join(text for kind, text in self._content_seq(copied) if kind == 'text')

    @staticmethod
    def _is_admonition(el):
        if not isinstance(el, Tag) or el.name != 'div':
            return False
        cls = ' '.join(el.get('class') or [])
        return any(token in cls for token in _ADMONITION_TOKENS)

    def _admonition_texts(self, div, title):
        """提示框内的段落/行内文字流（排除标题与代码等块级）。"""
        texts = []
        for child in div.children:
            if isinstance(child, Tag):
                if title is not None and child is title:
                    continue
                if child.name in ('script', 'style', 'noscript'):
                    continue
                if child.name == 'p':
                    texts.append(_norm_text(child.get_text(' '),
                                            unwrap_links=False))
            elif isinstance(child, str):
                text = _norm_text(child, unwrap_links=False)
                if text:
                    texts.append(text)
        return [t for t in texts if t]

    def _admonitions(self):
        items = []
        for div in self.root.find_all(self._is_admonition):
            if _in_pre(div):
                continue
            title = div.find(['p', 'div'], class_='admonition-title')
            label = title.get_text(strip=True) if title else 'Note'
            items.append((_norm_text(label, unwrap_links=False),
                           self._admonition_texts(
                div, title)))
        return items

    @staticmethod
    def _primary_text(el):
        """块容器首个行内片段或首段的文字（渲染为条目行/定义首行的内容）。"""
        parts = []
        for child in el.children:
            if isinstance(child, str):
                parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in ('script', 'style', 'noscript'):
                continue
            if child.name in _INLINE_TAGS:
                parts.append(child.get_text(' '))
                continue
            if child.name == 'p' and not parts:
                # 首个块级子节点为段落时，该段即条目首行（definition_list
                # 的 rich_container_lines 把首段并入条目行）
                parts.append(child.get_text(' '))
            break  # 首个块级子节点为止
        return _norm_text(' '.join(parts), unwrap_links=False)

    def _list_records(self):
        """列表归属事实：层级、项序号与项内内容顺序（文字/代码/子列表）。

        项序号为该项在父列表直接 `li` 子节点中的位置（1 起）；项内顺序按
        直接子节点递归重建，`pre` 记为代码、嵌套 `ul/ol` 记为子列表边界，
        与渲染端 rich_container_lines 的消费顺序一致。
        """
        records = []
        # 序号组：无 li/dd 祖先的顶层列表按“渲染可见分隔”合并编号——
        # 渲染端把中间无其他输出内容的相邻列表（可隔着透明容器）合并成
        # 一条缩进流；被任何会产出内容的部分隔开时才重新编号。处于同一
        # li/dd 容器内的同层连续列表同样连续编号。
        group_counts = {}
        transparent = {'ul', 'ol', 'div', 'section', 'article', 'main', 'body'}
        top_lists = []
        for lst in self.root.find_all(['ul', 'ol']):
            if _in_pre(lst) or lst.find_parent('table') is not None:
                continue
            if lst.find_parent(['li', 'dd', 'dt']) is not None:
                continue  # 嵌套列表随其列表项编号
            top_lists.append(lst)
        top_lists.sort(key=lambda lst: self._index[id(lst)])
        run_of = {}
        run_id = 0
        prev_end = None
        for lst in top_lists:
            start = self._index[id(lst)]
            merged = prev_end is not None and all(
                (isinstance(self._flat[i], str)
                 and not self._flat[i].strip())
                or (isinstance(self._flat[i], Tag)
                    and self._flat[i].name in transparent)
                for i in range(prev_end + 1, start))
            if not merged:
                run_id += 1
            run_of[id(lst)] = run_id
            prev_end = max(prev_end or 0, self._list_end_index(lst))

        for li in self.root.find_all('li'):
            if _in_pre(li) or li.find_parent('table') is not None:
                # 表格单元格内的 li 随单元格文字渲染，不构成列表项
                continue
            parent_list = li.find_parent(['ul', 'ol'])
            if parent_list is None:
                continue
            # 层级 = 包裹的列表上下文深度：祖先 li 与定义项 dd 各计一层
            # （dd 内的 ul 渲染时比顶层多一级缩进；项内 dl 的条目与嵌套
            # 列表整体随项层级再缩进，dd 层照计）
            level = 1
            context_ancestor = None
            ancestor = li.parent
            while ancestor is not None and getattr(ancestor, 'name', None):
                if ancestor.name in ('li', 'dd', 'dt') or (
                        self.family == 'api' and ancestor.name == 'aside'
                        and (ancestor.get('role') == 'doc-footnote'
                             or 'footnote' in (ancestor.get('class') or []))):
                    level += 1
                    if context_ancestor is None:
                        context_ancestor = ancestor
                ancestor = ancestor.parent
            if context_ancestor is not None:
                if context_ancestor.name in ('dd', 'dt'):
                    # 同一定义列表的各 dd 渲染为连续缩进流，编号连续
                    context_group = context_ancestor.find_parent('dl')
                    if context_group is None:
                        context_group = context_ancestor
                else:
                    context_group = context_ancestor
                group_key = ('nested', id(context_group), level)
            else:
                group_key = ('top', run_of[id(parent_list)], level)
            group_counts[group_key] = group_counts.get(group_key, 0) + 1
            ordinal = group_counts[group_key]
            records.append({
                'level': level,
                'ordinal': ordinal,
                'seq': self._content_seq(li),
            })
        return records

    def _list_end_index(self, lst):
        """列表（含嵌套内容）在扁平节点流中的末序号。"""
        end = self._index[id(lst)]
        for descendant in lst.descendants:
            idx = self._index.get(id(descendant))
            if idx is not None:
                end = max(end, idx)
        return end

    def _content_seq(self, el):
        """容器直接子节点的 (类型, 内容) 顺序流；包装 div/details 按渲染端递归。

        figure/img/figcaption、dl、table、blockquote、aside、标题与
        summary 渲染为独立结构行（[IMG:]/[FIGCAPTION]/[DEF-LIST]/[TABLE]/
        [BLOCKQUOTE]/[FOOTNOTE-LIST]/#/[DETAILS] 标签行），其内容由图片/
        表格/定义列表/脚注/标题等流对账，这里不重复计入项内顺序；
        details 的其余子节点（围栏、段落、子列表）按渲染顺序计入。
        """
        seq = []
        buffer = []
        structural = {
            'figure', 'img', 'figcaption', 'dl', 'table', 'blockquote',
            'aside', 'summary', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        }

        def flush():
            text = _norm_text(' '.join(buffer), unwrap_links=False)
            buffer.clear()
            if text:
                seq.append(('text', text))

        def walk(node):
            for child in node.children:
                if isinstance(child, Comment):
                    continue
                if isinstance(child, str):
                    buffer.append(str(child))
                    continue
                if not isinstance(child, Tag):
                    continue
                if child.name in ('script', 'style', 'noscript'):
                    continue
                if self.family == 'api' and (
                        'sd-tab-label' in (child.get('class') or [])
                        or child.get('role') == 'tab'
                        or 'sphinx-tabs-tab' in (child.get('class') or [])):
                    flush()
                    seq.append(('text', _norm_text('**[Tab: %s]**' %
                                child.get_text(' ', strip=True))))
                    continue
                if self.family == 'api' and child.name == 'div' and (
                        'sd-tab-set' in (child.get('class') or [])
                        or 'sphinx-tabs' in (child.get('class') or [])):
                    flush()
                    for label, panel in _api_tab_pairs(child):
                        seq.append(('text', _norm_text('**[Tab: %s]**' %
                                    label.get_text(' ', strip=True))))
                        walk(panel)
                        flush()
                    continue
                if _SourceFacts._is_admonition(child):
                    # 提示框由提示框流对账，其文字不计入项内顺序
                    flush()
                    continue
                if child.name == 'blockquote':
                    # 项内引用按渲染端递归：其中的段落成为续行文字，
                    # 嵌套列表/代码保持结构（不作为独立结构行跳过）
                    flush()
                    walk(child)
                    continue
                if child.name in structural:
                    flush()
                    continue
                if child.name == 'pre':
                    flush()
                    seq.append(('code',
                                clean_code_html(
                                    child.decode_contents()).rstrip('\n')))
                elif child.name in ('ul', 'ol'):
                    flush()
                    # 相邻子列表在渲染端合并为一条缩进流，只记一次边界
                    if not seq or seq[-1] != ('list', None):
                        seq.append(('list', None))
                elif child.name == 'p':
                    flush()
                    text = _norm_text(child.get_text(' '),
                                      unwrap_links=False)
                    if text:
                        seq.append(('text', text))
                elif child.name == 'div' and 'line' in (
                        child.get('class') or []):
                    # line-block 逐行渲染为独立段落，逐行计入项内顺序
                    flush()
                    text = _norm_text(child.get_text(' '),
                                      unwrap_links=False)
                    if text:
                        seq.append(('text', text))
                elif child.name in _INLINE_TAGS:
                    buffer.append(child.get_text(' '))
                else:
                    walk(child)

        walk(el)
        flush()
        return seq

    def _cell_text(self, cell):
        copied = copy.deepcopy(cell)
        for pre in copied.find_all('pre'):
            pre.decompose()
        # 格内公式按家族合同做包装去除（\(…\)/\[…\]），与渲染端
        # render_inline 同一口径投影为 $…$，使格文字与输出侧归一后的
        # 阅读文字一致（块级 \[…\] 不再残留字面方括号）；LaTeXML 来源
        # 的 MathML 节点优先取实体解码后的 alttext 原 TeX（04/02）
        maths = copied.find_all('math') + copied.find_all(class_='math') \
            if self._mathml_alttext else copied.find_all(class_='math')
        math_context = []
        for math in maths:
            body = None
            if self._mathml_alttext and math.name == 'math':
                alttext = math.get('alttext')
                if alttext and alttext.strip():
                    body = alttext
            if body is None:
                body = _strip_math_wrappers(
                    re.sub(r'\s+', ' ', math.get_text()).strip())
            math.replace_with('\ue006%d\ue007' % len(math_context)
                              if self._mathml_alttext else '$' + body + '$')
            math_context.append((body, None))
        if self._mathml_alttext:
            reading = _read_replace('\ue006(\\d+)\ue007',
                             lambda m: '$' + math_context[int(m.group(1))][0] + '$',
                             _direct_read(copied))
            return _norm_reading(reading,
                source_context=_SourceMathContext(math_context))
        # 链接标签是源字面文字：其中的 \[ \] 不是数学包装/语法转义，
        # 以哨兵保护穿过文本归一化，按标签口径还原（R2：与输出侧
        # 解包后的阅读文字逐字对应）
        labels = []
        for link in copied.find_all('a', href=True):
            label = link.get_text(' ', strip=True)
            link.replace_with('\x00L%d\x00' % len(labels))
            labels.append(label)
        text = _norm_text(copied.get_text(' '), unwrap_links=False)
        for index, label in enumerate(labels):
            text = text.replace('\x00L%d\x00' % index,
                                _norm_link_label(label, resolve=False))
        return text

    @staticmethod
    def _span_value(cell, attr):
        raw = cell.get(attr)
        try:
            return int(str(raw).strip()) if raw is not None else 1
        except (TypeError, ValueError):
            return None

    def _table_records(self):
        """表格归属事实：序号、行列格位、跨行/跨列与格内代码。

        格位按 DOM 单元格计数（1 起，含表头行），与 `[TABLE-CODE]` 标记
        口径一致；跨行/跨列保留实际值供未解释跨度阻断与转换映射核对。
        """
        records = []
        tables = [table for table in self.root.find_all('table')
                  if table.find_parent('table') is None and not _in_pre(table)]
        # 格内 pre 的文档位置 → 所属表序号；供映射表的代码从通用内容流
        # 中排除（其对应由格内代码归属比较负责）
        self.cell_pre_orders = {}
        # 格元素 → (表序号, 行, 列)；供映射一对多展开推导内容倍数
        self._cell_positions = {}
        image_refs = {fact['order']: fact['src'] for fact in self.image_facts}
        for ordinal, table in enumerate(tables, start=1):
            rows = []
            cells_spans = {}
            headers = {}
            links = {}
            codes = {}
            for row in table.find_all('tr'):
                if row.find_parent('table') is not table:
                    continue
                row_no = len(rows) + 1
                cells = []
                col_no = 0
                for cell in row.find_all(['td', 'th']):
                    if cell.find_parent('table') is not table:
                        continue
                    col_no += 1
                    self._cell_positions[id(cell)] = (ordinal, row_no, col_no)
                    cells.append(self._cell_text(cell))
                    headers[row_no, col_no] = cell.name == 'th'
                    links[row_no, col_no] = [(a['href'], tuple(image_refs[self._index[id(img)]]
                        for img in a.find_all('img') if self._index.get(id(img)) in image_refs))
                        for a in cell.find_all('a', href=True) if 'footnote-reference' not in (a.get('class') or [])
                        and a.find_parent(class_='footnote-reference') is None]
                    cells_spans[(row_no, col_no)] = (
                        self._span_value(cell, 'rowspan'),
                        self._span_value(cell, 'colspan'))
                    for order, pre in enumerate(cell.find_all('pre'), start=1):
                        self.cell_pre_orders.setdefault(
                            self._index[id(pre)], ordinal)
                        codes[(row_no, col_no, order)] = \
                            clean_code_html(pre.decode_contents()).rstrip('\n')
                if cells or self.family == 'api':
                    rows.append(cells)
            records.append({
                'ordinal': ordinal,
                'id': table.get('id'),
                'rows': rows,
                'spans': cells_spans,
                'codes': codes,
                'headers': headers,
                'links': links,
                'nested': table.find('table') is not None,
            })
        return records

    def _terms(self):
        """非脚注定义列表的 (术语, dd 首行文字) 有序流。"""
        pairs = []
        for dl in self.root.find_all('dl'):
            if _in_pre(dl) or dl.find_parent('table') is not None:
                # 表格单元格内的定义列表随单元格文字渲染
                continue
            if dl.find_parent('figcaption') is not None and self.family != 'api':
                # 图例定义列表随图题整段行内序列化输出，术语流不重复计入
                continue
            dts = dl.find_all('dt', recursive=False)
            if not dts:
                continue
            if all(re.fullmatch(r'\[\d+\]|\(\d+\)|\d+',
                                dt.get_text(strip=True)) for dt in dts):
                continue  # 脚注列表由 footnote_defs 对账
            dds = dl.find_all('dd', recursive=False)
            for dt, dd in zip(dts, dds):
                pairs.append((_norm_text(dt.get_text(' ', strip=True),
                                          unwrap_links=False),
                              self._primary_text(dd)))
        return pairs


class _MarkdownFacts:
    """用既有扫描器从解析 Markdown 提取的有序输出事实流。"""

    def __init__(self, text, source_context=None):
        self.text = text
        self.lines = text.split('\n')
        self.fenced = fenced_line_numbers(text)
        self._source_context = source_context
        self._heading_entries = heading_entries(text)
        # 标题行文字由标题流对账（源侧同样排除标题内容），标题公式与
        # 行内代码不进入通用流避免双计；图片不受排除（独立事实，标题
        # 图片序列化缺失必须阻断）
        self._heading_lines = {entry[0] for entry in self._heading_entries}
        self.headings = [
            (level, _norm_text(title, unwrap_links=False, mark_code=True,
                               strip_bracket_escapes=False))
            for _, level, title in self._heading_entries]
        # 章节唯一身份 = 标题在文档中的序号（同名小节不合并）
        self._heading_ordinals = {entry[0]: ordinal + 1
                                  for ordinal, entry in
                                  enumerate(self._heading_entries)}
        self.code = self._tagged_code()
        # math 流剥离转义括号后再扫描（家族合同：字面 \[ \] 不是公式
        # 定界），类型与表达式从同一次共享 scan_math 结果投影，issues
        # 由对账入口作为阻断项上报
        self.math = self._tagged_math()
        self.inline_code = self._tagged_inline_code()
        self.images = self._tagged_images()

    def _md_section(self, line_no):
        section = 0
        for entry_line, h_ord in self._heading_ordinals.items():
            if entry_line < line_no and h_ord > section:
                section = h_ord
        return section

    def _tagged_code(self):
        tagged = []
        for fence in scan_code_fences(self.text).blocks:
            tagged.append((self._md_section(fence.start_line),
                           fence.start_line, 0, 'code', fence.body))
        return tagged

    def _tagged_math(self):
        stripped = self.text.replace('\\[', 'xx').replace('\\]', 'xx')
        line_starts = {}
        offset = 0
        for line_no, line in enumerate(stripped.split('\n'), start=1):
            line_starts[line_no] = offset
            offset += len(line) + 1
        scan = scan_math(stripped)
        self.math_issues = scan.issues
        return [(self._md_section(span.start_line), span.start_line,
                 max(0, span.start - line_starts.get(span.start_line, 0)),
                 span.kind,
                 (_strip_math_wrappers(self.text[span.start + 2:span.end - 2].strip())
                  if span.kind == 'block'
                  else self.text[span.start + 1:span.end - 1]))
                for span in scan.spans
                if span.start_line not in self._heading_lines]

    def _tagged_inline_code(self):
        tagged = []
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced or line_no in self._heading_lines:
                continue
            for content, (start, _end) in line_code_spans(line):
                tagged.append((self._md_section(line_no), line_no, start,
                               'inline-code', _norm_code_text(content)))
        return tagged

    def _tagged_images(self):
        # 行内代码跨度内的图片语法由共享枚举统一排除（03-S3），
        # 这里不再叠加本地口径；[IMG:] 标记行锚定，不受行内代码影响
        entries = [(line_no, 0, start, end, src)
                   for line_no, start, end, src
                   in image_reference_spans(self.text)]
        entries.extend((line_no, 1, start, end, path)
                       for line_no, start, end, path
                       in image_marker_spans(self.text))
        entries.sort(key=lambda item: (item[0], item[1]))
        return [(self._md_section(line_no), line_no, start, 'image', src)
                for line_no, _kind, start, _end, src in entries]

    def footnote_streams(self, rich=False):
        refs = []
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            for match in re.finditer(r'\[\^([^\]]+)\](?!:)', line):
                refs.append(_footnote_label(match.group(1)))
        defs = []
        if rich:
            table_lines = set().union(*(r['row_lines'] for r in self.table_records()))
            current, base_indent = None, 0
            in_fn = False
            for line_no, line in enumerate(self.lines, start=1):
                if line_no in self.fenced or not line.strip():
                    continue
                stripped = line.strip()
                indent = len(line) - len(line.lstrip(' '))
                if stripped == '[FOOTNOTE-LIST]':
                    in_fn, current = True, None
                    continue
                if not in_fn:
                    continue
                match = re.match(r'^\s+\[+\s*(\d+)\s*\]+\s*(.*)$', line)
                if match:
                    current = [_footnote_label(match[1]), _norm_text(match[2])]
                    defs.append(current)
                    base_indent = indent
                elif indent <= base_indent and _MD_LIST_MARKER_RE.match(line):
                    in_fn, current = False, None
                elif indent == 0:
                    in_fn, current = False, None
                elif current is not None and indent == base_indent \
                        and line_no not in table_lines \
                        and not re.fullmatch(r'[-| :]+', stripped) \
                        and not re.match(r'^(\[[A-Z]|!\[|\*\*|[-*+]\s|\d+[.)]\s)', stripped):
                    current[1] = (current[1] + ' ' + _norm_text(stripped)).strip()
            return refs, [tuple(item) for item in defs]
        in_fn = False
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            if line.strip() == '[FOOTNOTE-LIST]':
                in_fn = True
                continue
            if not in_fn:
                continue
            if not line.startswith(' '):
                in_fn = False
                continue
            s = line.strip()
            if re.match(r'^\[[A-Z]', s) or s.startswith('#'):
                in_fn = False
                continue
            m = re.match(r'^\s+\[+\s*([^\[\]]+?)\s*\]+\s*(.*)$', line)
            if m:
                # 脚注正文不经行首 # 编码（行首是缩进的 [[标签]]），不解码
                defs.append((_footnote_label(m.group(1)),
                             _norm_text(m.group(2))))
        return refs, defs

    def admonition_records(self):
        """提示框 (label, 文字流) 记录；围栏/列表/表格行视为可跳过的间插。"""
        records = []
        cur = None
        cur_closed = True
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            s = line.strip()
            if not s:
                continue
            if s.startswith('> **ADMONITION [') and s.endswith(']**'):
                cur = {'label': s[len('> **ADMONITION ['):-3], 'texts': []}
                records.append(cur)
                cur_closed = False
            elif s.startswith('>'):
                if cur is None or (cur_closed and cur is not None):
                    cur = {'label': None, 'texts': []}
                    records.append(cur)
                    cur_closed = False
                # 剥掉引用前缀后的前导空白（引用行空白无语义，归一化后
                # 与原先一致），使行首转义（\#）的解码锚点能够命中
                text = _norm_text(s[1:].lstrip(),
                                  decode_heading_escape=True)
                if text:
                    cur['texts'].append(text)
            else:
                if not s.startswith(('  - ', '- ', '[TABLE-CODE')):
                    cur_closed = True
        return [(r['label'], r['texts']) for r in records
                if r['label'] is not None]

    def list_records(self):
        """从缩进与标记重建列表归属：层级、项序号与项内内容顺序。

        顶层标记缩进 2 空格，每层 +2；裸 `-`（代码先于文字时渲染端如此
        输出）同样是项标记。以栈维护未闭合项：更深层标记行在栈顶父项记
        一次 ('list', None) 边界（同层连续标记不重复记，父级续文之后的
        新子列表可再次记录）；标记/续行/缩进围栏归属深度不大于其层级的
        最近项，归属前先关闭其上更深项（父级续文结束子列表）。缩进围栏
        属项内代码；列 0 围栏与列 0 正文结束列表上下文。表格行、提示框、
        图片等结构行（含项内缩进形态）由各自流对账，不计入项内顺序也不
        结束列表。
        """
        records = []
        table_lines=set()
        for table in self.table_records():
            table_lines.update(range(table['start_line'],table['group_end_line']+1))
        marker_lines = set()
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in table_lines:
                continue  # 格位及格代码由独立表记录核对，不属于列表正文。
            if line_no not in self.fenced and re.fullmatch(r'\s*<a\s+id="[^"]+"></a>\s*',line):
                continue
            if line_no in self.fenced:
                continue
            if _MD_LIST_MARKER_RE.match(line) is not None:
                marker_lines.add(line_no)
        fences = {block.start_line: block
                  for block in scan_code_fences(self.text).blocks}
        stack = []          # 未闭合项（含层级/序号/内容顺序）
        context_alive = False
        last_ordinal = {}
        def_region = None   # [DEF-LIST]/[FOOTNOTE-LIST] 缩进内容区的列深
        near_table = False  # 位于 [TABLE] 之后的表格区域
        pending_table_code = False  # 表格区域的 [TABLE-CODE] 待 consume 围栏

        def finalize_to(level):
            # 关闭层级不低于 level 的待定项（从内向外）
            while stack and stack[-1]['level'] >= level:
                records.append(stack.pop())

        def close_context():
            finalize_to(0)

        def target_at(level):
            """深度不大于 level 的最近未闭合项；先关闭其上更深项。"""
            for item in reversed(stack):
                if item['level'] <= level:
                    while stack[-1] is not item:
                        records.append(stack.pop())
                    return item
            return None

        for line_no, line in enumerate(self.lines, start=1):
            if line_no in table_lines:
                continue
            if line_no not in self.fenced and re.fullmatch(r'\s*<a\s+id="[^"]+"></a>\s*',line):
                continue
            if line_no in self.fenced:
                if line_no in fences:
                    if line.startswith(' '):
                        if pending_table_code:
                            # 表格区域 [TABLE-CODE] 的围栏属格内代码，
                            # 不计入项内顺序
                            pending_table_code = False
                        else:
                            # 缩进围栏按其层级归属项内代码
                            target = target_at(max(
                                1, (len(line) - len(line.lstrip(' '))) >> 1))
                            if target is not None:
                                target['seq'].append(
                                    ('code', fences[line_no].body))
                            near_table = False
                    else:
                        # 列 0 围栏是顶层内容：列表上下文结束
                        close_context()
                        context_alive = False
                        last_ordinal = {}
                        near_table = False
                        pending_table_code = False
                continue
            stripped = line.strip()
            if not stripped:
                continue
            # [DEF-LIST]/[FOOTNOTE-LIST] 开启缩进内容区：列 0 属顶层内容，
            # 结束列表上下文；项内形态已按层缩进，只跳过不结束。其后的
            # 更深缩进的非标记行属定义条目，不计入项内顺序（dd 内嵌套
            # 列表的标记行照常处理）
            if stripped in ('[DEF-LIST]', '[FOOTNOTE-LIST]'):
                if line.startswith((' ', '\t')):
                    def_region = len(line) - len(line.lstrip(' '))
                    continue
                def_region = 0
                close_context()
                context_alive = False
                last_ordinal = {}
                continue
            if def_region is not None and line_no in marker_lines \
                    and len(line)-len(line.lstrip(' ')) <= def_region+2:
                def_region=None
            if def_region is not None and line_no not in marker_lines:
                if not stripped:
                    continue
                indent = len(line) - len(line.lstrip(' '))
                if indent > def_region:
                    continue
                def_region = None  # 缩进回到标记层：内容区结束
            indented_line = line.startswith((' ', '\t'))
            if near_table:
                # 表格区域：行/分隔行/格内代码标记都属表格作用域，
                # 不计入项内顺序；区域在首个非表格行处结束
                if (' | ' in line
                        or re.fullmatch(r'[-| :]+', stripped)
                        or stripped.startswith('[TABLE-CODE')):
                    if stripped.startswith('[TABLE-CODE'):
                        pending_table_code = True
                    continue
                near_table = False
            if stripped.startswith(
                    ('>', '**Figure:', '[TABLE]', '[TABLE-CAPTION',
                     '[DETAILS]')) or (
                        re.match(r'^\[[A-Z][A-Z0-9_-]*\](\s|$)', stripped)
                        is not None
                        and not stripped.startswith('[TABLE-CODE')):
                # [TABLE] 开启表格区域；其他结构行结束该区域
                near_table = stripped.startswith('[TABLE]')
                # 表格/提示框/图题/引用等结构行由各自流对账：项内形态
                # 已按层缩进，只跳过；列 0 出现即顶层内容，结束列表上下文
                if indented_line:
                    continue
                close_context()
                context_alive = False
                last_ordinal = {}
                continue
            if stripped.startswith(('![', '[IMG:', '[TABLE-CODE')):
                # 图片引用与格内代码标记在项内以列 0 表示，不结束列表
                continue
            if line_no in marker_lines:
                match = _MD_LIST_MARKER_RE.match(line)
                level = max(1, len(match.group(1)) // 2)
                near_table = False  # 列表标记之后的 ' | ' 是正文续行
                if stack and level > stack[-1]['level'] \
                        and def_region is None:
                    # 更深层首个标记 = 栈顶项的子列表边界（可多次记录）；
                    # 定义区内的列表属 dt/dd 内容，边界不记入宿主页
                    stack[-1]['seq'].append(('list', None))
                finalize_to(level)
                ordinal = (last_ordinal.get(level, 0) + 1
                           if context_alive else 1)
                for deeper in [k for k in last_ordinal if k > level]:
                    del last_ordinal[deeper]
                last_ordinal[level] = ordinal
                text_value = _norm_text(match.group(2) or '',
                                        decode_heading_escape=True)
                stack.append({'level': level, 'ordinal': ordinal,
                              'seq': ([('text', text_value)]
                                      if text_value else []),
                              'start_line': line_no})
                context_alive = True
                continue
            if line.startswith((' ', '\t')) and stripped:
                # 续行归属深度不大于其层级的最近项（父级续文回到父项）
                target = target_at(max(
                    1, (len(line) - len(line.lstrip(' '))) >> 1))
                if target is not None:
                    text_value = _norm_text(stripped,
                                            decode_heading_escape=True)
                    if text_value:
                        target['seq'].append(('text', text_value))
                continue
            close_context()
            context_alive = False
            last_ordinal = {}
        finalize_to(0)
        # 文档顺序 = 标记行序（栈弹出先内后外，父子顺序由此恢复）
        records.sort(key=lambda item: item['start_line'])
        return [{k: v for k, v in item.items() if k != 'start_line'}
                for item in records]

    def table_records(self):
        """解析 [TABLE] 块与 [TABLE-CODE] 归属标记的输出侧表格事实。

        行按 `' | '` 识别列界并保留首尾空单元格（仅剥行尾换行，不先
        strip 整行）；[TABLE-CODE r c#n] 标记归属最近一个 [TABLE] 块，
        其后首个围栏即该格代码。提供来源依据限定上下文（LaTeXML 家族，
        D2）时，被多行公式跨度覆盖的续行并入起始行——格内换行是公式
        逐字内容，不构成新行（F4 表格格宿主）。
        """
        def cell_reading(text, gfm=False):
            if self._source_context is not None:
                return _norm_reading(_protected_reading(text, self._source_context, keep_math=True, table=gfm),
                                     source_context=self._source_context)
            if gfm:
                return _norm_text(_protected_reading(text, keep_math=True, preserve_roles=False),
                                  unwrap_links=False, reading=True)
            return _norm_text(text, resolve_escapes=True)

        merged_lines = {}
        merged_away = set()
        if self._source_context is not None:
            scan = scan_math(self.text,
                             source_context=self._source_context)
            for span in scan.spans:
                end_line = self.text.count('\n', 0, span.end - 1) + 1
                if end_line == span.start_line \
                        or span.start_line in merged_away:
                    continue
                parts = [self.lines[span.start_line - 1]]
                for ln in range(span.start_line + 1, end_line + 1):
                    parts.append(self.lines[ln - 1])
                    merged_away.add(ln)
                merged_lines[span.start_line] = '\n'.join(parts)
        records = []
        current = None
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in merged_away:
                continue
            line = merged_lines.get(line_no, line)
            if line_no in self.fenced:
                # 围栏不属于格行；相邻代码组在行读取完成后统一解析。
                current = None
                continue
            stripped = line.strip()
            if stripped == '[TABLE]':
                current = {'ordinal': len(records) + 1, 'start_line': line_no, 'rows': [], 'raw_rows': [],
                           'codes': {}, 'marker_lines': [], 'row_lines': set()}
                records.append(current)
                continue
            if current is None:
                continue
            if line_no in self._heading_lines:
                # 标题行可含 ' | '（含管道真实标题）：属于标题流对账，
                # 不得被吞作当前表格的输出行
                current = None
                continue
            if stripped.startswith('[TABLE-CODE'):
                continue
            if current.get('rows_closed') and stripped:
                current = None
                continue
            if not stripped and line:
                # 单列全空单元格行（渲染端以单个空格输出，与零长空行区分）
                current['raw_rows'].append([''])
                current['rows'].append([_norm_text('',
                                                   decode_heading_escape=True)])
                current['row_lines'].add(line_no)
                continue
            if not stripped:
                if current['rows']:
                    current['rows_closed'] = True
                if current.get('single_column') and not line:
                    # 空行结束单列表格的行收集（单列行无列界记号）；
                    # 记录保留以继续接受其后的 [TABLE-CODE] 标记
                    current['single_closed'] = True
                continue
            if line.endswith('|') and (' | ' in line or (
                    current['rows'] and len(current['rows'][-1]) > 1)):
                # 行尾独立竖线 = 末列空格位（写作端可能剥掉尾随空格；两列
                # 行被剥后行内不再残留 ' | ' 列界，按前序行已建立的多列
                # 形态识别；单列行内容以 | 结尾时不受影响）
                line = line + ' '
            cells = line.split(' | ')
            if all(cell.strip() and _MD_TABLE_SEP_CELL_RE.match(cell.strip())
                   for cell in cells):
                continue  # 表头分隔行（单列 --- 同样适用）
            if ' | ' in line:
                # 逐格按实际阅读核对：格位序列化对 \+ASCII 标点按阅读语义
                # 加写（\\ 阅读为一个反斜线），此处解析回阅读文字，与源
                # 格字面文字一致（F1：非首格字面反斜线可读可验）
                current['raw_rows'].append(cells)
                current['rows'].append(
                    [cell_reading(cell) for cell in cells])
                current['row_lines'].add(line_no)
            elif not current.get('single_closed') and (
                    current.get('single_column') or not current['rows']):
                # 单列表格行（无列界记号）：自首行起进入单列模式，空行结束
                current['single_column'] = True
                current['raw_rows'].append([line])
                current['rows'].append([cell_reading(line)])
                current['row_lines'].add(line_no)
            else:
                current = None
        # GFM facts come from the same actual block reader as PDF export.
        covered = merged_away | set().union(*(r['row_lines'] for r in records))
        current_gfm = None
        for token in markdown_table_tokens(self.text):
            if token.type == 'table_open':
                lines = set(range(token.map[0] + 1, token.map[1] + 1))
                current_gfm = None if lines & covered else {
                    'start_line': token.map[0] + 1, 'rows': [], 'raw_rows': [], 'codes': {},
                    'marker_lines': [], 'row_lines': lines, 'gfm': True}
                if current_gfm is not None:
                    records.append(current_gfm)
            elif token.type == 'table_close':
                current_gfm = None
            elif current_gfm is not None and token.type == 'tr_open':
                current_gfm['rows'].append([])
                current_gfm['raw_rows'].append([])
            elif current_gfm is not None and token.type == 'inline':
                current_gfm['raw_rows'][-1].append(token.content)
                current_gfm['rows'][-1].append(cell_reading(token.content, gfm=True))
        records.sort(key=lambda record: record['start_line'])
        fences = {block.start_line: block for block in scan_code_fences(self.text).blocks}
        for ordinal, record in enumerate(records, 1):
            record['ordinal'] = ordinal
            record['marker_lines'] = []
            record['code_fence_lines'] = set()
            record['group_end_line'] = max((line + merged_lines.get(line, '').count('\n')
                for line in record['row_lines']), default=record['start_line'])
            cursor = record['group_end_line'] + 1
            while cursor <= len(self.lines):
                raw = self.lines[cursor - 1].strip()
                if not raw:
                    cursor += 1
                    continue
                match = _TABLE_CODE_MARKER_RE.fullmatch(raw) or _TABLE_CODE_NOTE_RE.fullmatch(raw)
                if not match:
                    if record['codes'] and cursor in fences:
                        record.setdefault('errors', []).append('L%d 表格代码组多出无归属围栏' % cursor)
                    break
                key = tuple(int(value) for value in match.groups())
                record['marker_lines'].append((cursor, key, None))
                marker_line = cursor
                cursor += 1
                while cursor <= len(self.lines) and not self.lines[cursor - 1].strip():
                    cursor += 1
                fence = fences.get(cursor)
                if fence is None:
                    record.setdefault('errors', []).append('L%d 格内代码标记后缺少紧随围栏' % marker_line)
                    break
                row, col, number = key
                if not (1 <= row <= len(record['rows']) and 1 <= col <= len(record['rows'][row - 1])):
                    record.setdefault('errors', []).append('L%d 格内代码坐标越界 %r' % (marker_line, key))
                if key in record['codes']:
                    record.setdefault('errors', []).append('L%d 格内代码坐标重复 %r' % (marker_line, key))
                expected = 1 + sum(r == row and c == col for r, c, _ in record['codes'])
                if number != expected:
                    record.setdefault('errors', []).append('L%d 格内代码序号不连续 %r' % (marker_line, key))
                body = fence.body
                if record.get('gfm') and self._source_context is not None:
                    indent = re.match(r' *', self.lines[fence.start_line - 1]).group()
                    body = '\n'.join(line[len(indent):] if line.startswith(indent) else line
                                     for line in body.split('\n'))
                record['codes'][key] = body
                record['code_fence_lines'].add(fence.start_line)
                record['group_end_line'] = fence.end_line
                cursor = fence.end_line + 1
        return records

    def terms(self):
        pairs = []
        in_def = False
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            if line.strip() == '[DEF-LIST]':
                in_def = True
                continue
            if not in_def:
                continue
            if not line.startswith(' '):
                in_def = False
                continue
            s = line.strip()
            if re.match(r'^\[[A-Z]', s) or s.startswith('#'):
                in_def = False
                continue
            m = re.match(r'^\*\*(.+?)\*\*\s*(.*)$', s)
            if m:
                pairs.append((_norm_text(m.group(1),
                                         decode_heading_escape=True),
                              _norm_text(m.group(2),
                                         decode_heading_escape=True)))
        return pairs


def markdown_table_facts(text, source_context=None):
    """复用独立输出读取；拆包、计数与翻译门禁采用相同实际格位。"""
    records = _MarkdownFacts(text, source_context).table_records()
    lines = text.splitlines()
    for record in records:
        record['caption'] = None
        for line in reversed(lines[:record['start_line'] - 1]):
            if not line.strip() or re.fullmatch(r'\s*<a\s+[^>]*></a>\s*', line):
                continue
            if _TABLE_CAPTION_LINE_RE.match(line):
                record['caption'] = line.strip()
            break
    return records


def _grid_header_role(text):
    """v2 非首行 th 的整格 strong 表示；局部/分离强调不是整格角色。"""
    tokens = [token for token in _MD_INLINE_READ.parseInline(text)[0].children or []
              if token.type != 'text' or token.content]
    if not tokens or tokens[0].type != 'strong_open' or tokens[-1].type != 'strong_close':
        return False
    depth = 0
    for token in tokens[:-1]:
        if token.type in ('strong_open', 'strong_close'):
            depth += token.nesting
        if depth == 0:
            return False
    return depth == 1


def _mapped_table_headers(source, mapping, section_id=None):
    """从已准入的原DOM及v2映射读取角色；不从Markdown强调猜th。"""
    if not mapping or mapping.get('version') != 2:
        return set()  # v1人工表示没有v2整格strong合同。
    headers = set()
    for item in mapping['tables']:
        original, problems = _locate_source_table(item, source.table_records, section_id)
        if problems:
            raise ValueError('来源表头不可定位: ' + '；'.join(problems))
        for cell in item['cells']:
            row, col = cell['row'], cell['col']
            if original['headers'].get((row, col)) and original['rows'][row-1][col-1]:
                headers.update((target['table'], target['row'], target['col'])
                               for target in cell['targets'] if 'table' in target and target['row'] > 1)
    return headers


def compare_translation_tables(source, translated, *, exact=False,
                               source_context=None, header_cells=()):
    """翻译检查格位及逐格硬不变量；确定性中文转换额外核对实际格值。"""
    from _verification import parse_inline_code_spans, link_targets, image_references
    src = markdown_table_facts(source, source_context)
    doc = markdown_table_facts(translated, source_context)
    header_cells = set(header_cells)

    def cell_math(text, gfm):
        return [(span.kind, decode_table_math(span.expr, parsed=True)
                 if gfm and source_context is not None else span.expr)
                for span in scan_math(text, source_context=source_context).spans]
    diffs = []
    if len(src) != len(doc):
        diffs.append('表格数不一致: 源 %d vs 译 %d' % (len(src), len(doc)))
    for index, (s, d) in enumerate(zip(src, doc), 1):
        label = '表#%d（源 L%d / 译 L%d）' % (index, s['start_line'], d['start_line'])
        diffs.extend(label + ' ' + error for record in (s, d)
                     for error in record.get('errors', []))
        if s['codes'] != d['codes']:
            diffs.append(label + ' 格内代码归属或内容不一致')
        if [len(r) for r in s['rows']] != [len(r) for r in d['rows']]:
            diffs.append(label + ' 行数或列位不一致')
            continue
        if exact and s['caption'] != d['caption']:
            diffs.append(label + ' 确定性转换改变题注归属')
        if exact and s['rows'] != d['rows']:
            diffs.append(label + ' 确定性转换改变格值或顺序')
        for row, (sr, dr) in enumerate(zip(s['raw_rows'], d['raw_rows']), 1):
            for col, (sc, dc) in enumerate(zip(sr, dr), 1):
                if (index, row, col) in header_cells:
                    if not _grid_header_role(dc):
                        diffs.append('%s r=%d c=%d 表头角色丢失' % (label, row, col))
                if bool(sc.strip()) != bool(dc.strip()):
                    diffs.append('%s r=%d c=%d 空格位状态不一致' % (label, row, col))
                for name, read in (
                    ('行内代码', lambda text: [value for value, _ in parse_inline_code_spans(text)]),
                    ('链接', link_targets),
                    # 路径可迁移；逐次资源身份由调用方已有的全局门禁核对。
                    ('图片格位', lambda text: len(image_references(text))
                     + len(image_marker_spans(text))),
                ):
                    if read(sc) != read(dc):
                        diffs.append('%s r=%d c=%d %s 不一致' % (label, row, col, name))
                if cell_math(sc, s.get('gfm')) != cell_math(dc, d.get('gfm')):
                    diffs.append('%s r=%d c=%d 公式 不一致' % (label, row, col))
    return diffs


def table_code_problems(text, stage='final', source_context=None):
    """仅解释实际独立标记/说明行；围栏及行内代码中的字面记法不参与。"""
    if stage not in ('final', 'intermediate', 'source'):
        raise ValueError('未知 table-code-stage: %s' % stage)
    facts = markdown_table_facts(text, source_context)
    owned = {line for record in facts for line, _, _ in record['marker_lines']}
    fenced = fenced_line_numbers(text)
    problems = ['表#%d %s' % (record['ordinal'], error)
                for record in facts for error in record.get('errors', [])]
    for line, raw in enumerate(text.splitlines(), 1):
        if line in fenced:
            continue
        value = raw.strip()
        marker = value.startswith('[TABLE-CODE')
        note = _TABLE_CODE_NOTE_RE.fullmatch(value)
        if not marker and not note:
            continue
        if line not in owned:
            problems.append('L%d 孤儿或无效格内代码标记/说明' % line)
        if marker and stage == 'final':
            problems.append('L%d 最终成品残留 TABLE-CODE 标记' % line)
    return problems


def finalize_table_code(text, source_context=None, header_cells=()):
    """在已核验中间中文上只替换标记行，格位说明留在最终正文内。"""
    problems = table_code_problems(text, 'intermediate', source_context)
    if problems:
        raise ValueError('；'.join(problems))
    lines = text.splitlines(keepends=True)
    for record in markdown_table_facts(text, source_context):
        for line, key, _ in record['marker_lines']:
            if not _TABLE_CODE_MARKER_RE.fullmatch(lines[line - 1].strip()):
                continue
            original = lines[line - 1]
            indent = original[:len(original) - len(original.lstrip())]
            ending = '\r\n' if original.endswith('\r\n') else '\n' if original.endswith('\n') else ''
            lines[line - 1] = indent + '本表第 %d 行、第 %d 列的代码 %d：' % key + ending
    result = ''.join(lines)
    problems = compare_translation_tables(text, result, exact=True, source_context=source_context,
                                          header_cells=header_cells)
    problems.extend(table_code_problems(result, source_context=source_context))
    if problems:
        raise ValueError('；'.join(problems))
    return result


def snapshot_image_facts(raw_html, family, section_id=None):
    """从原始快照独立提取结构化图片事实，按文档顺序返回字典列表。

    与渲染/尺寸提取不同路径（全新 BeautifulSoup、无 pre 保护替换），
    家族口径一致：api 只取亮版、排除 pre 内图片。每条事实保留：
    source_ref（原始源引用，相对声明快照目录解析；reference 的
    images/<basename> 改写不覆盖它）、src（投影引用，与解析结果对账
    口径一致）、node（源节点，与解析期映射 source_node 同一命名空间）、
    section/order（章节与文档序）。快照未找到选区根时返回 None。
    """
    facts = _SourceFacts(raw_html, family, section_id)
    if facts.root is None:
        return None
    return list(facts.image_facts)


def snapshot_grid_image_counts(raw_html, family, section_id=None):
    """v2 图片投影次数来自独立 DOM 跨度，不能由尺寸映射自报。"""
    source = _SourceFacts(raw_html, family, section_id)
    records = {record['ordinal']: record for record in source.table_records}
    counts = {}
    for fact in source.image_facts:
        cell = source.mapped_cell_of(fact['order'])
        spans = records[cell[0]]['spans'][cell[1:]] if cell else (1, 1)
        if not all(isinstance(n, int) and n > 0 for n in spans):
            raise ValueError('图片所在格含无效跨度: %s' % fact['node'])
        counts[fact['node']] = spans[0] * spans[1]
    return counts


def snapshot_image_stream(raw_html, family, section_id=None):
    """从原始快照独立提取图片出现流，返回按文档顺序的引用列表。

    由 snapshot_image_facts 的同一事实投影（reference 改写为
    images/<basename>），供回补入口独立核对图片出现，不能由尺寸提取
    结果自证完整。快照未找到选区根时返回 None。
    """
    facts = snapshot_image_facts(raw_html, family, section_id)
    if facts is None:
        return None
    return [fact['src'] for fact in facts]


def _section_ordered_diffs(category, src_tagged, md_tagged, src_label,
                           md_label):
    """按章节唯一身份分组，节内按文档顺序比较跨类别有序流。

    同名小节各持有唯一序号，不合并；同节内代码/公式/图片的互换或
    跨节移动都会在有序流比较中被定位。
    """
    src_groups = {}
    for sec, order, sub, cat, value in src_tagged:
        src_groups.setdefault(sec, []).append(((order, sub), cat, value))
    md_groups = {}
    for sec, line, col, cat, value in md_tagged:
        md_groups.setdefault(sec, []).append(((line, col), cat, value))
    # 节内按位置（文档序/行内列）排序后再比较：跨类别实际顺序是对账的
    # 一部分，同一节内“代码→图片”换成“图片→代码”必须检出（等数换序
    # 不能放行）；同一条目流内的类别分组不再决定顺序。
    for groups in (src_groups, md_groups):
        for items in groups.values():
            items.sort(key=lambda item: item[0])
    src_groups = {sec: [(cat, value) for _pos, cat, value in items]
                  for sec, items in src_groups.items()}
    md_groups = {sec: [(cat, value) for _pos, cat, value in items]
                 for sec, items in md_groups.items()}
    diffs = []
    for sec in sorted(set(src_groups) | set(md_groups)):
        sec_diffs = _stream_diffs(
            '%s#%d' % (category, sec), src_groups.get(sec, []),
            md_groups.get(sec, []), src_label, md_label)
        if sec_diffs:
            diffs.append('%s 章节归属或内容差异（节 #%d）: %s'
                         % (category, sec, sec_diffs[0]))
    return diffs


def _stream_diffs(category, src_seq, md_seq, src_label, md_label):
    """有序流逐项差异；数量只作摘要，等数换内容/乱序/重复均逐项定位。"""
    diffs = []
    if len(src_seq) != len(md_seq):
        diffs.append('%s数量不一致: %s %d 项 vs %s %d 项'
                     % (category, src_label, len(src_seq),
                        md_label, len(md_seq)))
    for i in range(min(len(src_seq), len(md_seq))):
        if src_seq[i] != md_seq[i]:
            diffs.append('%s第 %d 项不一致: %s %r vs %s %r'
                         % (category, i + 1, src_label, src_seq[i],
                            md_label, md_seq[i]))
    return diffs


def _list_record_diffs(src_records, md_records, html_label, md_label):
    """列表归属比较：层级、父列表内项序号与项内内容顺序共同参与。"""

    def shape(record):
        return (record['level'], record['ordinal'],
                tuple((kind, value) for kind, value in record['seq']))

    return _stream_diffs('列表项', [shape(r) for r in src_records],
                         [shape(r) for r in md_records], html_label, md_label)


def _table_record_diffs(src_records, md_records, mapped_src, claimed_md,
                        html_label, md_label):
    """表格归属比较：行列格位、格文字与格内代码的归属；未解释跨度阻断。"""
    diffs = []
    src_rest = [r for r in src_records if r['ordinal'] not in mapped_src]
    md_rest = [r for r in md_records if r['ordinal'] not in claimed_md]
    if len(src_rest) != len(md_rest):
        diffs.append('表格数量不一致: %s %d 张 vs %s %d 张'
                     % (html_label, len(src_rest), md_label, len(md_rest)))
    for i in range(min(len(src_rest), len(md_rest))):
        source, output = src_rest[i], md_rest[i]
        prefix = '表格第 %d 张' % (i + 1)
        if source.get('nested'):
            diffs.append('%s 含未解释嵌套表，已阻断分派' % prefix)
        for error in output.get('errors', []):
            diffs.append('%s %s' % (prefix, error))
        unexplained = sorted(
            pos for pos, spans in source['spans'].items()
            if spans != (1, 1))
        if unexplained:
            diffs.append('%s 含未解释跨行/跨列（如 %s），未提供逐表转换映射'
                         % (prefix, unexplained[:3]))
        if len(source['rows']) != len(output['rows']):
            diffs.append('%s行数不一致: %s %d 行 vs %s %d 行'
                         % (prefix, html_label, len(source['rows']),
                            md_label, len(output['rows'])))
        for row_no in range(1, min(len(source['rows']),
                                    len(output['rows'])) + 1):
            src_row = source['rows'][row_no - 1]
            md_row = output['rows'][row_no - 1]
            if len(src_row) != len(md_row):
                diffs.append('%s第 %d 行格数不一致: %s %d 格 vs %s %d 格'
                             % (prefix, row_no, html_label, len(src_row),
                                md_label, len(md_row)))
            elif src_row != md_row:
                diffs.append('%s第 %d 行不一致: %s %r vs %s %r'
                             % (prefix, row_no, html_label, src_row,
                                md_label, md_row))
        if source['codes'] != output['codes']:
            keys = sorted(set(source['codes']) | set(output['codes']))
            for key in keys:
                if source['codes'].get(key) != output['codes'].get(key):
                    diffs.append(
                        '%s格内代码归属不一致 r=%d c=%d#%d: %s %r vs %s %r'
                        % (prefix, key[0], key[1], key[2], html_label,
                           source['codes'].get(key), md_label,
                           output['codes'].get(key)))
    return diffs


def _locate_source_table(entry, src_records, section_id):
    """解析逐表转换映射的定位项；返回 (源表记录, 差异列表)。"""
    diffs = []
    locate = entry.get('locate')
    if not isinstance(locate, dict):
        return None, ['转换映射缺少 locate 定位项']
    declared_section = locate.get('section_id')
    if declared_section is not None and declared_section != section_id:
        return None, ['转换映射定位选区 %r 与对账选区 %r 不符'
                      % (declared_section, section_id)]
    if 'table' in locate:
        ordinal = locate['table']
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            return None, ['转换映射 table 序号非法: %r' % (ordinal,)]
        record = next((r for r in src_records if r['ordinal'] == ordinal),
                      None)
        if record is None:
            return None, ['转换映射 table 序号 %d 超出选区表格数' % ordinal]
        return record, diffs
    if 'table_id' in locate:
        table_id = locate['table_id']
        if not isinstance(table_id, str):
            return None, ['转换映射 table_id 非法: %r' % (table_id,)]
        record = next((r for r in src_records if r.get('id') == table_id),
                      None)
        if record is None:
            return None, ['转换映射 table_id=%r 在选区内未找到' % table_id]
        return record, diffs
    return None, ['转换映射 locate 需要 table 序号或 table_id']


def _conversion_map_diffs(raw_html, section_id, src, md, table_conversions,
                          html_label, md_label):
    """核对逐表转换映射（§4.10 限定合同、§8.2 收敛核验）；返回
    (差异列表, 已映射源表序号集合, 被声明占用的输出表序号集合,
    格内容倍数, 源格→声明输出格位表, 源格→声明说明区间表)。

    逐输出格核验：非空输出格的文字按 ' / ' 分段后须与声明指向它的
    源格文字（行优先序、归一口径）一一相等，空段对应空源格；单一
    源格的输出格须整体相等——表头/共享值展开由多源格分段相等解释，
    数值篡改与附加文字均为确定性拒绝。格内代码按源格 (行,列,序)
    映射到声明目标格位的 TABLE-CODE 键逐一相等，输出表孤儿代码必拒。
    移出说明按声明行区间保留包含关系。映射未覆盖的表外内容照常
    全量检查；含义层面的重建正确性由绑定当前身份的回源复核确认。
    """
    diffs = []
    mapped_src = set()
    claimed_md = set()
    # (源表序号, row, col) -> 声明目标数（表格位 + 说明区间）
    cell_target_counts = {}
    # (源表序号, row, col) -> 声明输出格位列表 / 声明说明区间列表
    cell_table_targets = {}
    note_targets = {}
    if not isinstance(table_conversions, dict) \
            or table_conversions.get('version') not in (1, 2) \
            or not isinstance(table_conversions.get('tables'), list):
        return (['逐表转换映射结构无效（需 version=1/2 与 tables 数组）'],
                mapped_src, claimed_md, cell_target_counts,
                cell_table_targets, note_targets)
    digest = table_conversions.get('snapshot_sha256')
    grid_mode = table_conversions['version'] == 2
    if grid_mode and not isinstance(digest, str):
        return (['v2 逐表转换映射必须绑定 snapshot_sha256'],
                mapped_src, claimed_md, cell_target_counts, cell_table_targets, note_targets)
    if digest is not None:
        actual = hashlib.sha256(raw_html.encode('utf-8')).hexdigest()
        if digest != actual:
            return (['逐表转换映射快照摘要不符: 映射 %s vs 本次 %s'
                     % (digest[:12], actual[:12])], mapped_src, claimed_md,
                    cell_target_counts, cell_table_targets, note_targets)
    src_by_ordinal = {r['ordinal']: r for r in src.table_records}
    declared_targets = {}  # (输出表序号, row, col) -> [(源表序号, row, col)]
    # 目标格位 -> 按源序登记的格内代码正文（源表序号、格位、正文）
    declared_codes = {}
    for entry in table_conversions['tables']:
        record, locate_diffs = _locate_source_table(
            entry, src.table_records, section_id)
        diffs += locate_diffs
        if record is None:
            continue
        if record['ordinal'] in mapped_src:
            diffs.append('转换映射重复声明源表 #%d' % record['ordinal'])
            continue
        mapped_src.add(record['ordinal'])
        expected_grid, occupied = {}, {}
        if grid_mode:
            if record.get('nested'):
                diffs.append('源表 #%d 含嵌套表，不能网格展开' % record['ordinal'])
            # 独立从原 DOM 格事实重建，不调用 HtmlFidelity 的生成网格。
            for row_no, row in enumerate(record['rows'], 1):
                cursor = 1
                for col_no, text in enumerate(row, 1):
                    while (row_no, cursor) in occupied:
                        cursor += 1
                    rs, cs = record['spans'][row_no, col_no]
                    if not all(isinstance(n, int) and n > 0 for n in (rs, cs)) \
                            or row_no + rs - 1 > len(record['rows']):
                        diffs.append('源表 #%d 格 %s 跨度非法或越界'
                                     % (record['ordinal'], (row_no, col_no)))
                        continue
                    positions = []
                    for r in range(row_no, row_no + rs):
                        for c in range(cursor, cursor + cs):
                            if (r, c) in occupied:
                                diffs.append('源表 #%d 覆盖格 %s 冲突' % (record['ordinal'], (r, c)))
                            occupied[r, c] = (row_no, col_no)
                            positions.append({'table': record['ordinal'], 'row': r, 'col': c})
                    expected_grid[row_no, col_no] = positions
                    cursor += cs
            output = next((r for r in md.table_records() if r['ordinal'] == record['ordinal']), None)
            width = max((c for r, c in occupied), default=0)
            if output is None or not output.get('gfm') or len(output['rows']) != len(record['rows']) \
                    or any(len(row) != width for row in output['rows']):
                diffs.append('源表 #%d v2 输出必须为保留全部行列的真实 GFM 网格' % record['ordinal'])
            elif any(output['rows'][r-1][c-1] for r in range(1, len(record['rows'])+1)
                     for c in range(1, width+1) if (r, c) not in occupied):
                diffs.append('源表 #%d 无覆盖洞被填入内容' % record['ordinal'])
        cells = entry.get('cells')
        if not isinstance(cells, list) or not cells:
            diffs.append('源表 #%d 转换映射 cells 必须是非空数组'
                         % record['ordinal'])
            continue
        declared_positions = {}
        for cell in cells:
            if not isinstance(cell, dict):
                diffs.append('源表 #%d 转换单元格必须是对象' % record['ordinal'])
                continue
            row, col = cell.get('row'), cell.get('col')
            if not all(isinstance(v, int) and not isinstance(v, bool)
                       and v >= 1 for v in (row, col)):
                diffs.append('源表 #%d 转换单元格行列非法: %r'
                             % (record['ordinal'], (row, col)))
                continue
            position = (row, col)
            if position in declared_positions:
                diffs.append('源表 #%d 格 %s 被重复声明'
                             % (record['ordinal'], position))
                continue
            declared_positions[position] = cell
            actual_spans = record['spans'].get(position)
            if actual_spans is None:
                diffs.append('源表 #%d 声明的格 %s 不存在'
                             % (record['ordinal'], position))
                continue
            declared_spans = (cell.get('rowspan', 1), cell.get('colspan', 1))
            if declared_spans != actual_spans:
                diffs.append('源表 #%d 格 %s 跨度不符: 声明 %s vs 实际 %s'
                             % (record['ordinal'], position, declared_spans,
                                actual_spans))
            targets = cell.get('targets', [])
            if not isinstance(targets, list):
                diffs.append('源表 #%d 格 %s targets 必须是数组'
                             % (record['ordinal'], position))
                continue
            if grid_mode:
                expected = expected_grid.get(position, [])
                if targets != expected:
                    diffs.append('源表 #%d 格 %s v2 覆盖声明不符（包括空格位）'
                                 % (record['ordinal'], position))
                has_code = any(key[:2] == position for key in record['codes'])
                if (has_code and (not expected or cell.get('code_target') != expected[0])) \
                        or (not has_code and 'code_target' in cell):
                    diffs.append('源表 #%d 格 %s v2 code_target 须唯一对应含代码格原点'
                                 % (record['ordinal'], position))
                if record.get('headers', {}).get(position):
                    for target in expected:
                        out = next((r for r in md.table_records() if r['ordinal'] == target['table']), None)
                        r, c = target['row'], target['col']
                        if out and r > 1 and r <= len(out['rows']) and c <= len(out['rows'][r-1]) \
                                and out['rows'][r-1][c-1]:
                            if not _grid_header_role(out['raw_rows'][r-1][c-1]):
                                diffs.append('源表 #%d th 分组在输出 r=%d c=%d 未保留加粗区别'
                                             % (record['ordinal'], r, c))
            has_table_target = False
            note_target_count = 0
            for target in targets:
                if not isinstance(target, dict):
                    diffs.append('源表 #%d 格 %s target 非法: %r'
                                 % (record['ordinal'], position, target))
                    continue
                if 'table' in target:
                    out_ordinal = target.get('table')
                    out_row, out_col = target.get('row'), target.get('col')
                    if not all(isinstance(v, int) and not isinstance(v, bool)
                               and v >= 1
                               for v in (out_ordinal, out_row, out_col)):
                        diffs.append('源表 #%d 格 %s 输出格位非法: %r'
                                     % (record['ordinal'], position, target))
                        continue
                    out_record = next(
                        (r for r in md.table_records()
                         if r['ordinal'] == out_ordinal), None)
                    if out_record is None:
                        diffs.append('源表 #%d 格 %s 指向的输出表 #%d 不存在'
                                     % (record['ordinal'], position,
                                        out_ordinal))
                        continue
                    claimed_md.add(out_ordinal)
                    if out_row > len(out_record['rows']) \
                            or out_col > len(
                                out_record['rows'][out_row - 1]):
                        diffs.append('源表 #%d 格 %s 指向输出表 #%d 格 '
                                     '(r=%d c=%d) 越界'
                                     % (record['ordinal'], position,
                                        out_ordinal, out_row, out_col))
                        continue
                    has_table_target = True
                    declared_targets.setdefault(
                        (out_ordinal, out_row, out_col),
                        []).append((record['ordinal'], row, col))
                    cell_table_targets.setdefault(
                        (record['ordinal'], row, col), []).append(
                        (out_ordinal, out_row, out_col))
                elif 'note' in target:
                    lines = target.get('note')
                    if not isinstance(lines, list) or len(lines) != 2 \
                            or not all(isinstance(v, int) and v >= 1
                                       for v in lines) \
                            or lines[0] > lines[1] or lines[1] > len(md.lines):
                        diffs.append('源表 #%d 格 %s note 行区间非法: %r'
                                     % (record['ordinal'], position, lines))
                        continue
                    note_target_count += 1
                    note_targets.setdefault(
                        (record['ordinal'], row, col), []).append(
                        tuple(lines))
                    row_cells = record['rows'][row - 1] if row <= len(
                        record['rows']) else None
                    cell_text = row_cells[col - 1] if row_cells and col <= len(
                        row_cells) else ''
                    note_raw = ' '.join(md.lines[lines[0] - 1:lines[1]])
                    if src._mathml_alttext:
                        note_text = _norm_reading(_protected_reading(note_raw, md._source_context, keep_math=True),
                                                  source_context=md._source_context)
                        expected_text = cell_text
                    else:
                        note_text = _norm_text(note_raw, decode_heading_escape=True)
                        expected_text = _norm_text(cell_text)
                    if cell_text and expected_text not in note_text:
                        diffs.append('源表 #%d 格 %s 内容未在声明说明区间找到: %r'
                                     % (record['ordinal'], position, cell_text))
                else:
                    diffs.append('源表 #%d 格 %s target 缺少 table 或 note'
                                 % (record['ordinal'], position))
            row_cells = record['rows'][row - 1] if row <= len(
                record['rows']) else None
            cell_text = row_cells[col - 1] if row_cells and col <= len(
                row_cells) else ''
            if cell_text and not targets:
                diffs.append('源表 #%d 格 %s 有内容但未声明任何对应位置'
                             % (record['ordinal'], position))
            # 格内容倍数：一对多展开/移出说明决定格内行内代码、公式、
            # 图片与脚注引用在输出侧的合法出现次数（由映射解释）
            cell_target_counts[(record['ordinal'], row, col)] = (
                len([t for t in targets if isinstance(t, dict)
                     and 'table' in t]) + note_target_count)
            # 格内代码的目标格位登记（无 table 目标即拒，代码不能随说明移出）；
            # 键按 (行,列,序) 投影到格位判断（二元组查三元组恒不命中，S11）
            if any(key[:2] == position for key in record['codes']) \
                    and not has_table_target:
                diffs.append('源表 #%d 格 %s 含格内代码但未声明输出格位'
                             % (record['ordinal'], position))
        missing = sorted(set(record['spans']) - set(declared_positions))
        if missing:
            diffs.append('源表 #%d 未声明的源格: %s'
                         % (record['ordinal'], missing[:5]))
        # 源代码按 (格位, 序) 行优先序登记到各目标格位
        for (crow, ccol, _n), body in sorted(record['codes'].items()):
            cell = declared_positions.get((crow, ccol))
            if cell is None:
                continue  # 不存在的格位已另行报告
            code_targets = [cell.get('code_target')] if grid_mode else cell.get('targets', [])
            for target in code_targets:
                if isinstance(target, dict) and 'table' in target:
                    declared_codes.setdefault(
                        (target['table'], target['row'], target['col']),
                        []).append((record['ordinal'], crow, ccol, body))
    # 逐输出格核验：声明指向它的源格文字（行优先序）与输出格文字一一相等
    md_records = {r['ordinal']: r for r in md.table_records()}
    for out_position in sorted(declared_targets):
        sources = sorted(declared_targets[out_position])
        out_ordinal, out_row, out_col = out_position
        out_record = md_records[out_ordinal]
        out_text = out_record['rows'][out_row - 1][out_col - 1]
        src_texts = []
        for src_ordinal, s_row, s_col in sources:
            record = src_by_ordinal[src_ordinal]
            row_cells = record['rows'][s_row - 1] if s_row <= len(
                record['rows']) else None
            src_texts.append(row_cells[s_col - 1] if row_cells and s_col <=
                             len(row_cells) else '')
        segments = out_text.split(' / ') if len(sources) > 1 else [out_text]
        if segments != src_texts:
            diffs.append(
                '输出表 #%d 格 (r=%d c=%d) 与声明源格不符: %s %r vs 输出 %r'
                % (out_ordinal, out_row, out_col, md_label, src_texts,
                   segments))
    # 输出覆盖：被声明的输出表内每个非空格必须有源格依据
    for out_ordinal in sorted(claimed_md):
        out_record = md_records[out_ordinal]
        for row_no, row in enumerate(out_record['rows'], start=1):
            for col_no, text in enumerate(row, start=1):
                if text and (out_ordinal, row_no, col_no) not in declared_targets:
                    diffs.append('输出表 #%d 格 (r=%d c=%d) 无源格依据: %r'
                                 % (out_ordinal, row_no, col_no, text))
        # 格内代码：输出 TABLE-CODE 键与声明源代码按格位逐一相等，孤儿必拒
        out_code_positions = {}
        for (crow, ccol, n), body in sorted(out_record['codes'].items()):
            out_code_positions.setdefault((crow, ccol), []).append((n, body))
        for key, body in sorted(out_record['codes'].items()):
            if body is None:
                diffs.append('输出表 #%d 格内代码 %s 缺少围栏'
                             % (out_ordinal, key))
        for position in sorted(set(out_code_positions) | {
                (p[1], p[2]) for p in declared_codes if p[0] == out_ordinal}):
            actual = [body for _n, body in
                      sorted(out_code_positions.get(position, []))]
            # 声明侧保持登记序（源表、格位、格内序的行优先源序）
            expected = [entry[3] for entry in declared_codes.get(
                (out_ordinal, position[0], position[1]), [])]
            if actual != expected:
                diffs.append(
                    '输出表 #%d 格 (r=%d c=%d) 格内代码归属不一致: 声明 %r '
                    'vs 输出 %r' % (out_ordinal, position[0], position[1],
                                    expected[:3], actual[:3]))
    return (diffs, mapped_src, claimed_md, cell_target_counts,
            cell_table_targets, note_targets)


def reconcile_html_to_markdown(raw_html, md_text, family,
                               section_id=None,
                               html_label='原 HTML',
                               md_label='解析 Markdown',
                               table_conversions=None):
    """独立对账原 HTML 与解析 Markdown；返回损伤诊断列表（空 = 一致）。

    family 为 'single'/'paginated'/'reference'/'api'，仅决定图片引用形式
    与暗亮选择口径；比较逻辑共用。section_id 与解析入口的选区一致。

    table_conversions 为可选的逐表转换映射（version=1）：以快照摘要与
    表序号/ID 定位源表，逐格登记行列、跨度与对应输出格位或移出说明。
    提供映射的表按限定合同核对（定位、源格覆盖、内容/代码对应、输出格
    来源）；未提供映射的表含跨行/跨列仍阻断，表外内容始终全量检查。
    """
    src = _SourceFacts(raw_html, family, section_id)
    md = _MarkdownFacts(md_text)
    if src.root is None:
        return ['%s 未找到 article/main/body 选区' % html_label]

    diffs = []
    diffs.extend(table_code_problems(md_text, 'source'))
    # 未解决数学定界：源与解析两侧都不得忽略；忠实解析含未闭合定界的
    # 输入同样阻断分派（不能用剩余跨度相等消除未解决项）
    for issue in src.math_issues:
        diffs.append('%s 未解决数学定界 %r: %s'
                     % (html_label, issue.raw, issue.reason))
    for issue in md.math_issues:
        diffs.append('%s L%d 未解决数学定界 %r: %s'
                     % (md_label, issue.start_line, issue.raw, issue.reason))

    if table_conversions is None:
        (map_diffs, mapped_src, claimed_md, cell_factors, cell_table_targets,
         note_targets) = [], set(), set(), {}, {}, {}
    else:
        (map_diffs, mapped_src, claimed_md, cell_factors, cell_table_targets,
         note_targets) = _conversion_map_diffs(
            raw_html, section_id, src, md, table_conversions, html_label,
            md_label)

    def cell_runs(entries, keyed, order_key=lambda item: (item[1], item[2])):
        """按所属格位切分连续段并整体重复：脚注引用等计数事实由声明
        目标数（一对多展开/移出说明）解释，格内容与代码的归属比较见
        逐目标格位比较。"""
        expanded = []
        pending, pending_cell = [], None

        def flush():
            factor = (cell_factors.get(pending_cell, 1)
                      if pending_cell is not None else 1)
            for _ in range(max(factor, 0)):
                expanded.extend(pending)

        for entry in sorted(entries, key=order_key):
            cell = keyed(entry)
            if cell != pending_cell:
                flush()
                pending, pending_cell = [], cell
            pending.append(entry)
        flush()
        return expanded

    diffs += _stream_diffs('标题', src.headings, md.headings,
                           html_label, md_label)
    # 内容流含行内代码事实；映射表格的格内代码由格内代码归属比较负责，
    # 从通用内容流两侧排除，避免表后置表示造成位置误判。格内其余内容
    # （行内代码/公式/图片）同样移出有序流：按声明源格→目标格位/说明
    # 区间归属比较（S04）——全局多重集无法证明格位，交换两格图片须拒绝；
    # 一对多展开由同一源格的多个声明目标自然解释，表外内容照常按章节
    # 有序比较
    md_tables = md.table_records()
    claimed_fence_lines = set()
    claimed_row_lines = set()
    for record in md_tables:
        if record['ordinal'] in claimed_md:
            claimed_fence_lines |= record['code_fence_lines']
            claimed_row_lines |= record['row_lines']
    note_ranges = sorted({lines for ranges in note_targets.values()
                          for lines in ranges})
    src_inside, src_content = [], []
    for entry in (src.code + src.math + src.images + src.inline_code):
        if entry[3] == 'code' and src.cell_pre_orders.get(
                entry[1]) in mapped_src:
            continue
        # 公式条目标签为 inline/block（_family_math_expectation 与输出侧
        # scan_math 的 kind），格位分类须覆盖两类；image/inline-code 照旧
        cell = (src.mapped_cell_of(entry[1])
                if entry[3] in ('inline', 'block', 'image', 'inline-code')
                else None)
        if cell is not None and cell[0] in mapped_src:
            src_inside.append(entry)
        else:
            src_content.append(entry)
    md_note, md_content = [], []
    for entry in (md.code + md.math + md.images + md.inline_code):
        if entry[3] == 'code' and entry[1] in claimed_fence_lines:
            continue
        if entry[1] in claimed_row_lines:
            continue
        elif any(start <= entry[1] <= end for start, end in note_ranges):
            md_note.append(entry)
        else:
            md_content.append(entry)
    if src.family == 'api':
        source_links = [(link.get('href'), tuple(src._image_src(image)
                        for image in link.find_all('img') if src._image_src(image)))
                        for link in src.root.find_all('a', href=True) if not _in_pre(link)
                        and (src.mapped_cell_of(src._index[id(link)]) or (None,))[0] not in mapped_src
                        and any(src._image_src(image) for image in link.find_all('img'))]
        output_links = []
        reader = _MarkdownIt('commonmark')
        for number, line in enumerate(md.lines, start=1):
            if number in md.fenced or number in claimed_row_lines:
                continue
            for inline in reader.parseInline(line.strip()):
                active = None
                for token in inline.children or []:
                    if token.type == 'link_open':
                        active = [token.attrGet('href'), []]
                    elif token.type == 'image' and active is not None:
                        active[1].append(token.attrGet('src'))
                    elif token.type == 'link_close' and active is not None:
                        if active[1]:
                            output_links.append((active[0], tuple(active[1])))
                        active = None
        diffs += _stream_diffs('链接图片', source_links, output_links, html_label, md_label)
        # 标签与代码 / 图片在同一有序事实流中；只比较标签集合会漏掉错绑面板。
        for container in src.root.find_all('div'):
            if _in_pre(container) or not ({'sd-tab-set', 'sphinx-tabs'}
                                         & set(container.get('class') or [])):
                continue
            for label, panel in _api_tab_pairs(container):
                start = src._index[id(label)]
                end = max([start] + [src._index[id(n)] for n in label.descendants
                                     if id(n) in src._index])
                position = src._index[id(panel)]
                src_content = [(entry[0], position, entry[1] - start, entry[3], entry[4])
                               if start <= entry[1] <= end else entry for entry in src_content]
                src_content.append((src._section_of(label), position, -1,
                                    'tab-label', _norm_text(label.get_text(' ', strip=True))))
        for number, line in enumerate(md.lines, start=1):
            if number in md.fenced:
                continue
            match = re.fullmatch(r'\s*\*\*\[Tab: (.*)\]\*\*\s*', line)
            if match:
                md_content.append((md._md_section(number), number, 0,
                                   'tab-label', _norm_text(match[1])))
    cell_content = {}
    for entry in sorted(src_inside, key=lambda item: (item[1], item[2])):
        cell_content.setdefault(src.mapped_cell_of(entry[1]), []).append(
            (entry[3], entry[4]))
    expected_by_target = {}
    expected_by_note = {}
    for cell in sorted(cell_content):
        contents = cell_content[cell]
        if not cell_table_targets.get(cell) and not note_targets.get(cell):
            diffs.append('映射表格格 (表#%d r=%d c=%d) 内容事实未声明任何'
                         '对应位置: %r' % (cell + (contents[:3],)))
            continue
        for position in cell_table_targets.get(cell, ()):
            expected_by_target.setdefault(position, []).extend(contents)
        for lines in note_targets.get(cell, ()):
            expected_by_note.setdefault(lines, []).extend(contents)
    # 输出侧归属：声明输出表的行内容按 ' | ' 列界定位到输出格位
    actual_by_target = {}
    expected_links, actual_links = {}, {}
    source_tables = {r['ordinal']: r for r in src.table_records}
    for (table, row, col), targets in sorted(cell_table_targets.items()):
        for target in targets:
            expected_links.setdefault(target, []).extend(source_tables[table].get('links', {}).get((row,col), []))
    for record in md_tables:
        if record['ordinal'] not in claimed_md:
            continue
        for row_no, row in enumerate(record['raw_rows'], 1):
            for col_no, text in enumerate(row, 1):
                pairs, active = [], None
                for token in _MarkdownIt('commonmark').parseInline(text)[0].children or []:
                    if token.type == 'link_open':
                        active = [token.attrGet('href'), []]
                    elif token.type == 'image' and active is not None:
                        active[1].append(token.attrGet('src'))
                    elif token.type == 'link_close' and active is not None:
                        pairs.append((active[0], tuple(active[1])))
                        active = None
                if pairs:
                    actual_links[record['ordinal'], row_no, col_no] = pairs
                facts = [(start, 'inline-code', _norm_code_text(content))
                         for content, (start, end) in parse_inline_code_spans(text)]
                facts += [(span.start, span.kind, decode_table_math(span.expr, parsed=True)
                           if record.get('gfm') and src._mathml_alttext else span.expr)
                          for span in scan_math(text).spans]
                facts += [(start, 'image', path) for line, start, end, path in image_reference_spans(text)]
                if facts:
                    actual_by_target[record['ordinal'], row_no, col_no] = [
                        (kind, value) for start, kind, value in sorted(facts)]
    for position in sorted(set(expected_links) | set(actual_links)):
        if expected_links.get(position, []) != actual_links.get(position, []):
            diffs.append('映射表格链接归属不一致 表#%d r=%d c=%d' % position)
    # 逐格有序比较：格内出现顺序（流程前后/左右对照）与格位共同参与，
    # 同格两张图片交换必须检出（A27 等数乱序失败）；多源格按源格
    # （表序、行、列）顺序、输出格内按行列序拼接
    for position in sorted(set(expected_by_target) | set(actual_by_target)):
        expected = expected_by_target.get(position, [])
        actual = actual_by_target.get(position, [])
        if expected != actual:
            diffs.append(
                '映射表格格内内容归属不一致 表#%d (r=%d c=%d): %s %r vs %s %r'
                % (position + (html_label, expected[:4],
                               md_label, actual[:4])))
    actual_by_note = {}
    for entry in sorted(md_note, key=lambda item: (item[1], item[2])):
        for lines in note_ranges:
            if lines[0] <= entry[1] <= lines[1]:
                actual_by_note.setdefault(lines, []).append(
                    (entry[3], entry[4]))
    for lines in sorted(set(expected_by_note) | set(actual_by_note)):
        expected = expected_by_note.get(lines, [])
        actual = actual_by_note.get(lines, [])
        if expected != actual:
            diffs.append(
                '映射表格移出说明区间 L%d-%d 内容不一致: %s %r vs %s %r'
                % (lines + (html_label, expected[:4], md_label, actual[:4])))
    diffs += _section_ordered_diffs('内容', src_content, md_content,
                                    html_label, md_label)
    md_refs, md_defs = md.footnote_streams(rich=src.family == 'api')
    # 脚注引用次数按映射倍数解释：colspan/共享值展开到多个输出格时，
    # 格内引用随格文字一起重复，次数由声明目标数推导，不全局忽略
    src_refs = [label for label, _order in cell_runs(
        src.footnote_refs, lambda item: src.mapped_cell_of(item[1]),
        order_key=lambda item: item[1])]
    diffs += _stream_diffs('脚注引用', src_refs, md_refs,
                           html_label, md_label)
    # 脚注定义按标签配对后比较正文：编号一致但内容被替换即检出
    md_def_map = dict(md_defs)
    for label, text in src.footnote_defs:
        if label not in md_def_map:
            diffs.append('脚注定义 [%s] 在解析 Markdown 中缺失' % label)
        elif md_def_map[label] != text:
            diffs.append('脚注定义 [%s] 正文不一致: %r vs %r'
                         % (label, text, md_def_map[label]))
    extra_defs = sorted(set(md_def_map) - {label for label, _ in src.footnote_defs})
    if extra_defs:
        diffs.append('解析 Markdown 多出脚注定义: %s' % extra_defs)
    diffs += _list_record_diffs(src.list_records, md.list_records(),
                                html_label, md_label)

    src_adm = src.admonitions
    md_adm = md.admonition_records()
    diffs += _stream_diffs('提示框', [label for label, _ in src_adm],
                           [label for label, _ in md_adm],
                           html_label, md_label)
    for i in range(min(len(src_adm), len(md_adm))):
        text_diffs = _stream_diffs(
            '提示框文字', src_adm[i][1], md_adm[i][1], html_label, md_label)
        diffs += ['提示框第 %d 项 %s' % (i + 1, d) for d in text_diffs]

    diffs += _table_record_diffs(src.table_records, md_tables,
                                 mapped_src, claimed_md, html_label, md_label)
    diffs += map_diffs
    diffs += _stream_diffs('定义列表', src.terms, md.terms(),
                           html_label, md_label)
    return diffs


# ---------------------------------------------------------------------------
# LaTeXML 来源分支（二期 ticket 01）：独立原 DOM 重建正文流并核对候选与
# 来源依据。与适配端不共享渲染遍历或“已输出”清单；事实规则（节点命名、
# 类型确认、TeX 提取）与适配端共用同一口径，如同两侧共用 _norm_text。

def _latexml_src_stream(raw_html, section_id, decisions,
                        decision_results=None, table_conversions=None,
                        adaptation=None):
    """从原始快照独立重建有序源 token 流与逐节点事实。

    返回 (tokens, facts, confirmed, problems, occ_stream, hosts)；tokens 供有序
    比较，facts 按节点身份登记独立重建的内容（类型/TeX/所属/文字），用于
    核对来源依据的 correspondences 与 unresolved；problems 为字面数学
    识别诊断（未闭合/歧义定界）；occ_stream 是已解决公式出现的文档序流
    （与候选 Markdown 公式跨度按序配对）；hosts 与 tokens 一一对应，登记
    各 token 的来源节点身份（§7.11.4 出现→实际区间独立对齐用，无对应
    身份的 token 为 None）。公式出现身份按 §7.11.4 与适配
    端同一机制：原 DOM 冻结后登记全部出现（MathML/遗留文本公式/字面公
    式）并以唯一标记替换，标记随同一序列化出口传递后展开为有序片段；
    不使用生成标记表，不按同文本反查。代码/TeX/内容性字符不随普通排版
    空白归一。
    """
    from _latexml_source import (_MARK_RE, OccurrenceRegistry,
                                 _expand_markers_inline,
                                 aside_node_ids as _lx_aside_node_ids,
                                 classify_block, container_node_ids,
                                 figure_node_ids as _lx_figure_node_ids,
                                 group_node_ids as _lx_group_node_ids,
                                 has_marker, mark_literal_occurrences,
                                 marked_text_frags, math_wrap,
                                 note_ref_label, paragraph_div_ids,
                                 plan_image_targets,
                                 listing_node_ids as _lx_listing_ids,
                                 prepare_math_dom, prepare_notes_dom,
                                 render_mapped_table,
                                 section_of, table_cell_facts,
                                 table_node_ids as _lx_table_node_ids)

    soup = BeautifulSoup(protect_code_entities(raw_html, skip_pre=True),
                         'html.parser')
    if section_id:
        root = soup.find(id=section_id)
    else:
        root = (soup.find('article') or soup.find('main')
                or soup.find('body'))
    if root is None:
        return None, None, None, [], None, None
    fidelity = HtmlFidelity()
    # 节点命名在任何 DOM 变更前按原始文档序计算（与适配端同一时点）
    container_ids = container_node_ids(root)
    paragraph_divs = paragraph_div_ids(root)
    group_ids = _lx_group_node_ids(root)
    figure_ids = _lx_figure_node_ids(root)
    aside_ids = _lx_aside_node_ids(root)
    table_ids = _lx_table_node_ids(root)
    listing_ids = _lx_listing_ids(root)
    image_targets = plan_image_targets(
        root, ((adaptation or {}).get('resource_substitutions')
               if adaptation else None))
    p_ids = {id(node): 'p[%d]' % ordinal for ordinal, node in
             enumerate(root.find_all('p'), start=1)}
    h_counts = {}
    h_ids = {}
    for node in root.find_all(re.compile(r'h[1-6]')):
        h_counts[node.name] = h_counts.get(node.name, 0) + 1
        h_ids[id(node)] = '%s[%d]' % (node.name, h_counts[node.name])
    figcaption_ids = {id(node): 'figcaption[%d]' % ordinal
                      for ordinal, node in
                      enumerate(root.find_all('figcaption'), start=1)}
    img_ids = {}
    ordinal = 0
    for img in root.find_all('img'):
        if img.find_parent('pre') is not None:
            continue
        ordinal += 1
        img_ids[id(img)] = 'img[%d]' % ordinal
    tokens = []
    hosts = []
    facts = {}
    fn_ordinal = [0]
    _fig_ctx = []

    def _push(token, host=None):
        """登记一个有序 token 及其来源节点身份（§7.11.4 出现→实际区间
        独立对齐用；无对应身份的 token 为 None）。"""
        tokens.append(token)
        hosts.append(host)

    def _norm(value):
        return _norm_reading(value, source_context=reading_context)

    def _register(node_id, fact):
        facts[node_id] = fact

    # 03-4：已确认的装饰排除/重复合并裁决按节点身份摘除（与适配端同一
    # 时点：命名映射计算之后、公式出现登记之前；节点名在原始 DOM 独立
    # 解析，不能凭适配端 DOM）；未确认的裁决内容保留
    _decision_results = [d for d in (decision_results or [])
                         if isinstance(d, dict)
                         and d.get('action') in
                         ('exclude-decoration', 'merge-duplicate')]
    if _decision_results:
        name_map = {}
        tag_first = {}
        for node in root.find_all(True):
            tag_first.setdefault(node.name, node)
            for mapping in (container_ids, group_ids, figure_ids,
                            aside_ids):
                name = mapping.get(id(node))
                if name:
                    name_map[name] = node

        def _lookup(node_name):
            if not isinstance(node_name, str):
                return None
            if node_name in name_map:
                return name_map[node_name]
            return tag_first.get(node_name.split('#', 1)[0])

        for decision in _decision_results:
            node = _lookup(decision.get('node'))
            if node is not None and decision.get('result') in (
                    'excluded', 'merged'):
                node.decompose()

    # 来源出现身份先于输出（§7.11.4 独立端镜像）：全部公式出现登记入
    # 独立注册表并以唯一标记替换原节点内容；未闭合/歧义定界上报诊断，
    # 不用剩余跨度相等消除
    registry = OccurrenceRegistry()
    prepare_math_dom(root, decisions, registry)
    problems = mark_literal_occurrences(
        root, registry, base=len(registry.occurrences))
    reading_context = _SourceMathContext([
        (occ['tex'], occ.get('section') or 0)
        for occ in registry.occurrences.values()
        if occ['kind'] == 'inline' and occ['unresolved'] is None])

    # 脚注引用：真实命名标签全局替换（与适配端 prepare_notes_dom 同一
    # 时点）；替换前按锚点所属段落登记引用事实（键格式不变）
    for anchor in root.find_all('a'):
        cls = anchor.get('class') or []
        if not any('note_ref' in c for c in cls):
            continue
        label = note_ref_label(anchor)
        if label is None:
            continue
        host = anchor.find_parent('p')
        host_id = p_ids.get(id(host), '?') if host is not None else '?'
        _register('ref:%s@%s' % (label, host_id),
                  {'type': 'footnote-ref', 'label': label,
                   'host': host_id})
    prepare_notes_dom(root)

    def _paragraph_frags(p):
        """含来源标记的宿主 → 有序片段：直接 DOM 行内阅读（_direct_read，
        不调用生成侧序列化出口，复评 S1），标记展开为 ('m', kind, tex,
        node) 片段（原 TeX 逐字，身份来自独立注册表）；未解决出现还原
        为其写出文字并入相邻文字段。"""
        return marked_text_frags(_direct_read(p), registry)

    def _preserved_container_frags(child):
        """未支持容器保留文字的分段事实（F4）：直接 DOM 阅读
        （_direct_read），来源标记展开为独立 m 片段（原 TeX 逐字）；
        未解决出现还原为写出文字并入相邻文字段。"""
        return marked_text_frags(_direct_read(child), registry)

    def _image_token(img, figure_id, sub_index):
        if img.find_parent('pre') is not None:
            return
        src = img.get('src', '')
        if not src:
            return
        reference = image_targets.get(id(img)) or (
            'images/%s' % src.rsplit('/', 1)[-1])
        _push(('img', reference), img_ids.get(id(img)))
        _register(img_ids.get(id(img)), {
            'type': 'image', 'reference': reference, 'source_ref': src,
            'figure': figure_id, 'subfigure': sub_index,
            'section': section_of(root, img)})

    def _figure_caption_token(cap, figure_id, sub_index):
        cap_id = figcaption_ids.get(id(cap))
        # 直接 DOM 阅读（不调用生成侧题注出口，复评 S1）；headerlink
        # 在阅读中本就不出现，¶/链接图标按既有阅读清理
        text = _direct_read(cap).replace('¶', '').replace('\uf0c1', '')
        frags = marked_text_frags('[FIGURE] ' + text, registry)
        if any(f[0] == 'm' for f in frags):
            _push(('pm', tuple(frags)), cap_id)
            fact_text = _norm(''.join(
                f[1] if f[0] == 't' else math_wrap(f[1], f[2])
                for f in frags))
        else:
            _push(('p', _norm('[FIGURE] ' + text)), cap_id)
            fact_text = _norm('[FIGURE] ' + text)
        _register(cap_id, {
            'type': 'figure-caption',
            'text': fact_text,
            'figure': figure_id, 'subfigure': sub_index,
            'section': section_of(root, cap)})

    def _algorithm_tokens(node):
        """算法清单独立重建（03-2）：官方编号题注归属本清单；正文由
        既有分支递归处理，未知内容不转代码。"""
        node_id = container_ids.get(id(node)) or 'algorithm'
        title = None
        for child in node.children:
            if isinstance(child, Tag):
                cls = child.get('class') or []
                if any('title' in c for c in cls):
                    title = child
                    break
        if title is not None:
            # 直接 DOM 阅读（不调用生成侧序列化出口，复评 S1）；含公式
            # 出现时标记展开为 pm 分段事实（原 TeX 逐字，三轮 F2/F4）
            frags = marked_text_frags(
                '[ALGORITHM] ' + _direct_read(title), registry)
            if any(f[0] == 'm' for f in frags):
                _push(('pm', tuple(frags)), node_id)
                text = ''.join(
                    f[1] if f[0] == 't' else math_wrap(f[1], f[2])
                    for f in frags)[len('[ALGORITHM] '):]
            else:
                text = _norm(_direct_read(title))
                _push(('p', '[ALGORITHM] ' + text), node_id)
            _register(node_id, {'type': 'algorithm', 'title': text,
                                'section': section_of(root, node)})
        for child in node.children:
            if title is not None and child is title:
                continue
            # 直属子节点逐个分派（p/pre/table 保持各自角色与节点身份），
            # 不跳过直属节点只解析其孩子（§7.11.5，ticket 20）
            walk(node, only=child)

    def _footnote_def_tokens(node):
        """LaTeXML 脚注定义独立重建：命名标签原样；定义内容按文档序完整
        消费——直属文字、段落、列表和简单表分别保留块事实，代码块
        保留在定义内的原位置（角色与所属保留），未知内容
        以直接阅读文字保留；任何内容不静默丢弃（§7.11.5，复评 F2）。
        定义内公式出现以标记逐字展开为实际写出文字（文字$TeX$文字）。"""
        label = node.get('id')
        fn_ordinal[0] += 1
        node_id = 'fn[%d]' % fn_ordinal[0]
        body = next((child for child in node.children
                     if isinstance(child, Tag) and any(
                         'content' in c for c in (child.get('class') or []))),
                    node)
        def table_facts(table):
            if classify_block(table) != 'table-complex':
                return _block_reading_facts(BeautifulSoup(str(table), 'html.parser'), normalize)
            ordinal = int(table_ids[id(table)].split('[')[1].rstrip(']'))
            mapping = _lx_locate_mapping(table, ordinal)
            if mapping is None:
                return (('table-unresolved', '缺少 table_conversions 裁决映射'),)
            cells, codes = table_cell_facts(table)
            rendered, _ = render_mapped_table(cells, codes, mapping, gfm=True)
            return _markdown_block_facts(_expand_markers_inline(rendered, registry, table_math=True), reading_context)
        def normalize(text):
            return _norm_reading(_expand_markers_inline(text, registry),
                                 source_context=reading_context)
        content = _block_reading_facts(body, normalize, table_facts)
        _push(('fndef', label, content), node_id)
        _register(node_id, {'type': 'footnote-def', 'label': label,
                            'content': content,
                            'section': section_of(root, node)})

    def _table_tokens(node, style):
        "表格独立重建（04）：简单表复用既有格位表示；复杂表仅按声明映射物化。"
        node_id = table_ids.get(id(node))
        if style == 'complex':
            ordinal = int(node_id.split('[')[1].rstrip(']')) \
                if node_id else None
            mapping = _lx_locate_mapping(node, ordinal)
            if mapping is None:
                # 与适配端同一口径：表内已确认公式出现随宿主保留（不猜写、
                # 不丢弃），逐出现置未解决，保留文字中的公式维持既有
                # $…$ 包裹字节（preserved 与实际写出内容一致）
                for occ in registry.occurrences.values():
                    host = occ.get('table_host')
                    if host is None or occ['unresolved'] is not None:
                        continue
                    if host is node or node in host.parents:
                        occ['unresolved'] = (
                            '所在复杂表缺少 table_conversions 裁决映射'
                            '（公式随宿主保留）')
                        occ['serialized'] = '$%s$' % occ['tex']
                        occ['raw'] = occ['serialized']
                frags = _preserved_container_frags(node)
                if any(f[0] == 'm' for f in frags):
                    if frags and frags[0][0] == 't':
                        frags = [('t', '[%s] %s' % (
                            node.name.upper(), frags[0][1]))] + list(
                            frags[1:])
                    else:
                        frags = [('t', '[%s]' % node.name.upper())] + list(
                            frags)
                    _push(('pm', tuple(frags)), node_id or node.name)
                else:
                    text = _norm('[%s] %s' % (
                        node.name.upper(),
                        ''.join(f[1] for f in frags)))
                    if text.strip():
                        _push(('p', text), node_id or node.name)
                _register(node_id or node.name, {
                    'type': 'unresolved-container',
                    'text': _norm('[%s] %s' % (
                        node.name.upper(),
                        ''.join(f[1] for f in frags))),
                    'reason': '复杂表缺少 table_conversions 逐源格裁决映射'
                              '（已保留原文，不展平不转代码）',
                    'section': section_of(root, node)})
                return
            cells, codes = table_cell_facts(node)
            _register(node_id, {'type': 'table', 'style': 'mapped',
                                'ordinal': ordinal,
                                'section': section_of(root, node)})
        else:
            _register(node_id, {'type': 'table', 'style': 'simple',
                                'section': section_of(root, node)})
        _push(('table', node_id), node_id)

    def _lx_locate_mapping(node, ordinal):
        conversions = table_conversions
        for entry in (conversions or {}).get('tables') or []:
            if not isinstance(entry, dict):
                continue
            locate = entry.get('locate') or {}
            if 'table' in locate and locate['table'] == ordinal:
                return entry
            if 'table_id' in locate and locate['table_id'] is not None \
                    and locate['table_id'] == (node.get('id') or None):
                return entry
        return None

    def _listing_tokens(node):
        '清单行独立重建：逐行文字与行内公式出现按源序进入事实流。'
        lid = listing_ids.get(id(node))
        _register(lid, {
            'type': 'listing',
            'section': section_of(root, node)})
        for line in node.children:
            if not isinstance(line, Tag):
                continue
            lcls = line.get('class') or []
            if not any('listingline' in c for c in lcls):
                continue
            # 直接 DOM 阅读（不调用生成侧序列化出口，复评 S1）；含公式
            # 出现时标记展开为分段事实（原 TeX 逐字；未解决出现还原为
            # 写出文字），块级出现按拆段口径成为独立块级 token
            frags = marked_text_frags(_direct_read(line), registry)
            if any(f[0] == 'm' for f in frags):
                _emit_paragraph_tokens(frags, [], lid)
                continue
            text = ' '.join(
                ''.join(f[1] for f in frags).split())
            if not text:
                continue
            _push(('p', _norm(text)), lid)

    def _math_group_tokens(node):
        """公式组/式号容器独立重建（ticket 02 + §7.11.4）：行内容格按源序
        空格拼接为行（含来源标记），成员 = 行内已解决公式出现的身份（文
        档序，不扫描成品、不按同文本挑选）；纯字面行按行登记展开文本；
        块级出现拆为独立块级 token；式号官方文字保留为相邻文字 token；
        组/成员序/式号登记事实供来源依据核对。"""
        gid = group_ids.get(id(node))
        section = section_of(root, node)
        if gid is None:
            return
        if node.name == 'table':
            rows = [node]
        else:
            rows = [c for c in node.children
                    if isinstance(c, Tag)
                    and classify_block(c) == 'math-group']
            if not rows:
                rows = [node]
        occ_by_node = {occ['node']: occ
                       for occ in registry.occurrences.values()}
        members = []
        eqnos = []
        for row in rows:
            cells = [td for td in row.find_all('td')
                     if not any('eqn_center_pad' in c or 'eqno' in c
                                for c in (td.get('class') or []))]
            line = ' '.join(
                ' '.join(td.get_text(' ', strip=True).split())
                for td in cells).strip()
            if line:
                frags = marked_text_frags(line, registry)
                resolved = [occ_by_node[f[3]] for f in frags
                            if f[0] == 'm']
                if resolved and all(o['source'] == 'literal'
                                    for o in resolved):
                    # 纯字面行（无 MathML 快照，08）：组关系按行登记，
                    # 记录文本展开标记（不含内部记号）
                    members.append(_expand_markers_inline(line, registry))
                elif resolved:
                    # 含 MathML/遗留节点的行：成员 = 已解决出现身份
                    members.extend(o['node'] for o in resolved)
                else:
                    members.append(_expand_markers_inline(line, registry))
                _emit_paragraph_tokens(frags, [], gid)
            for td in row.find_all('td'):
                tcls = td.get('class') or []
                if not any('eqno' in c for c in tcls):
                    continue
                text = re.sub(r'\s+', ' ', td.get_text(' ', strip=True))
                text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
                text = re.sub(r'([\[(]) ', r'\1', text).strip()
                if not text:
                    continue
                anchor = td.find('a', href=True)
                efrags = marked_text_frags(text, registry)
                if any(f[0] == 'm' for f in efrags):
                    _push(('pm', tuple(efrags)), gid)
                else:
                    _push(('p', text), gid)
                eqnos.append({
                    'member': len(members) - 1,
                    'text': _expand_markers_inline(text, registry),
                    'target': anchor['href'] if anchor else None})
        _register(gid, {'type': 'group', 'members': members,
                        'eqnos': eqnos, 'section': section})

    def _emit_paragraph_tokens(frags, all_frags, host=None):
        """文字/公式片段 token 化：块级公式出现拆为独立块级公式 token
        （与适配端写出拆段同一布局），前后文字/行内公式段各自成为
        p/pm token。frags 并入 all_frags（宿主段落事实合并登记用）。
        host 为来源节点身份（出现→实际区间独立对齐用）。"""
        buffer = []

        def flush_text():
            if not buffer:
                return
            if any(f[0] == 'm' for f in buffer):
                _push(('pm', tuple(buffer)), host)
            else:
                joined = _norm(''.join(f[1] for f in buffer))
                if joined:
                    _push(('p', joined), host)
            del buffer[:]

        for frag in frags:
            if frag[0] == 'm' and frag[1] == 'block':
                flush_text()
                _push(('math', 'block', frag[2]), host)
            else:
                buffer.append(frag)
        flush_text()
        all_frags.extend(frags)

    def _register_paragraph(node_id, all_frags, section):
        """段落事实登记（与适配端同一口径）：存在非空文字片段或行内公
        式片段才登记；宿主片段全部为块级公式时无正文事实（块级公式是
        独立成块的数学片段）。"""
        if node_id is None:
            return
        if not any((f[0] == 't' and str(f[1]).strip())
                   or (f[0] == 'm' and f[1] != 'block')
                   for f in all_frags):
            return
        _register(node_id, {
            'type': 'paragraph', 'frags': all_frags,
            'text': _norm(''.join(f[1] for f in all_frags
                                  if f[0] == 't')),
            'section': section})

    def _flush_paragraph(frags, node_id, section):
        "段落 token 化 + 段落事实登记（同一宿主只登记一次）。"
        all_frags = []
        _emit_paragraph_tokens(frags, all_frags, node_id)
        _register_paragraph(node_id, all_frags, section)

    def _paragraph_host_tokens(child, node_id):
        """段落宿主（p/div/aside）：行内图片在源位置成为独立 img token
        （08，与适配端 _paragraph_host 同序，不静默丢弃），前后文字段按
        文档序与图片交错输出。含图片的宿主登记覆盖性段落事实（聚合全部
        文字/公式片段，段界计一个空白银分，与适配端段落对应区间合并
        口径一致；图片本身由 img token 与图片对应独立核对）；无图片宿
        主照常登记。"""
        imgs = [img for img in child.find_all('img')
                if img.find_parent('pre') is None and img.get('src')]
        if not imgs:
            _flush_paragraph(_paragraph_frags(child), node_id,
                             section_of(root, child))
            return
        ctx = _fig_ctx[-1] if _fig_ctx else (None, None)
        copied = copy.deepcopy(child)
        copied_imgs = [img for img in copied.find_all('img')
                       if img.find_parent('pre') is None
                       and img.get('src')]
        for index, img in enumerate(copied_imgs):
            img.replace_with(NavigableString('\x01%d\x01' % index))
        text = _direct_read(copied)
        all_frags = []
        segment = []

        def flush_segment():
            _emit_paragraph_tokens(segment, all_frags, node_id)
            del segment[:]

        for position, piece in enumerate(
                re.split(r'\x01(\d+)\x01', text)):
            if position % 2 == 1:
                flush_segment()
                if all_frags:
                    all_frags.append(('t', ' '))
                _image_token(imgs[int(piece)], ctx[0], ctx[1])
            elif piece:
                segment.extend(marked_text_frags(piece, registry))
        flush_segment()
        _register_paragraph(node_id, all_frags, section_of(root, child))

    def walk(node, only=None):
        for child in node.children:
            if only is not None and child is not only:
                continue
            if isinstance(child, str):
                # 与适配端 _walk 同口径：容器直属文字（含出现标记替换后
                # 的公式位置）照常输出；块级出现拆为独立块级 token
                if child.strip():
                    _emit_paragraph_tokens(
                        marked_text_frags(child.strip(), registry), [])
                continue
            if not isinstance(child, Tag):
                continue
            kind_class = classify_block(child)
            name = child.name
            if name in ('img', 'figcaption', 'figure'):
                ctx = _fig_ctx[-1] if _fig_ctx else (None, None)
                if name == 'img':
                    _image_token(child, ctx[0], ctx[1])
                elif name == 'figcaption':
                    _figure_caption_token(child, ctx[0], ctx[1])
                else:
                    figure_id = figure_ids.get(id(child))
                    dom_parent = child.find_parent('figure')
                    if dom_parent is not None:
                        # 嵌套子图：按 DOM 宿主归属父浮动体，子图序 = 同一
                        # 父内文档序（与适配端 _figure 同口径；中间 flex
                        # 单元等包装不影响计数）
                        parent_id = figure_ids.get(id(dom_parent))
                        sub_index = 1 + sum(
                            1 for sib in child.find_all_previous('figure')
                            if sib.find_parent('figure') is dom_parent)
                        _fig_ctx.append((parent_id, sub_index))
                    else:
                        _fig_ctx.append((figure_id, None))
                    try:
                        walk_skip(child)
                    finally:
                        _fig_ctx.pop()
                continue
            if kind_class == 'skip':
                continue
            if kind_class == 'unsupported':
                node_id = container_ids[id(child)]
                frags = _preserved_container_frags(child)
                if any(f[0] == 'm' for f in frags):
                    # F4：含已确认公式的保留文字按分段事实输出（[TAG]
                    # 前缀并入首个文字段），公式逐字、文字/公式相对位置
                    # 可逐段核对
                    if frags and frags[0][0] == 't':
                        frags = [('t', '[%s] %s' % (name.upper(),
                                                    frags[0][1]))
                                 ] + list(frags[1:])
                    else:
                        frags = [('t', '[%s]' % name.upper())] + list(frags)
                    _push(('pm', tuple(frags)), node_id)
                else:
                    text = _norm('[%s] %s'
                                 % (name.upper(), ''.join(
                                     f[1] for f in frags)))
                    if text.strip():
                        _push(('p', text), node_id)
                _register(node_id, {
                    'type': 'unresolved-container',
                    'text': _norm('[%s] %s' % (
                        name.upper(),
                        ''.join(f[1] for f in frags))),
                    'reason': '未支持内容容器 <%s>（ticket 01 范围外），'
                              '已保留原文' % name,
                    'section': section_of(root, child)})
                continue
            if re.fullmatch(r'h[1-6]', name):
                # 直接 DOM 阅读（不调用生成侧序列化出口，复评 S1）；
                # headerlink 在阅读中本就不出现；标记逐字保留并展开为
                # 实际写出文字（原 TeX 逐字）
                title_raw = _expand_markers_inline(
                    _direct_read(child), registry)
                title = _norm_reading(
                    title_raw.replace('¶', '').replace('\uf0c1', ''),
                    mark_code=True,
                    strip_bracket_escapes=False)
                _push(('h', int(name[1]), title), h_ids[id(child)])
                _register(h_ids[id(child)], {
                    'type': 'heading', 'level': int(name[1]),
                    'section': section_of(root, child)})
                continue
            if name == 'p':
                _paragraph_host_tokens(child, p_ids.get(id(child)))
                continue
            if name == 'pre':
                body = clean_code_html(child.decode_contents()).rstrip('\n')
                _push(('code', body))
                continue
            if kind_class == 'table-simple':
                _table_tokens(child, 'simple')
                continue
            if kind_class == 'table-complex':
                _table_tokens(child, 'complex')
                continue
            if kind_class == 'math-group':
                _math_group_tokens(child)
                continue
            if kind_class == 'biblist':
                for item in child.find_all('li', recursive=False):
                    # 条内公式出现按标记逐字重建（原 TeX 逐字，三轮 F2）；
                    # 块级出现拆为独立块级 token（与适配端写出拆段同一布
                    # 局，ticket 20）；文字直接 DOM 阅读（复评 S1）
                    frags = marked_text_frags(_direct_read(item), registry)
                    if any(f[0] == 'm' for f in frags):
                        _emit_paragraph_tokens(frags, [])
                        continue
                    text = _norm_reading(''.join(f[1] for f in frags))
                    if text:
                        _push(('p', _norm(text)))
                continue
            if kind_class == 'itemize':
                for item in child.find_all('li', recursive=False):
                    # F4：条内公式出现按标记逐字重建（原 TeX 逐字），
                    # `- ` 前缀并入首个文字段；块级出现拆为独立块级
                    # token（ticket 20）；文字直接 DOM 阅读（复评 S1）
                    frags = marked_text_frags(_direct_read(item), registry)
                    if frags and frags[0][0] == 't':
                        frags = [('t', '- ' + frags[0][1])] + list(
                            frags[1:])
                    else:
                        frags = [('t', '- ')] + list(frags)
                    if any(f[0] == 'm' for f in frags):
                        _emit_paragraph_tokens(frags, [])
                        continue
                    text = _norm_reading(''.join(f[1] for f in frags))
                    if text:
                        _push(('p', _norm(text)))
                continue
            if kind_class == 'listing':
                _listing_tokens(child)
                continue
            if kind_class == 'algorithm':
                _algorithm_tokens(child)
                continue
            if kind_class == 'footnote-def':
                _footnote_def_tokens(child)
                continue
            if name == 'aside':
                _paragraph_host_tokens(child, aside_ids.get(id(child)))
                continue
            if name == 'div' and id(child) in paragraph_divs:
                _paragraph_host_tokens(child, paragraph_divs[id(child)])
                continue
            walk_skip(node=child)

    def walk_skip(node):
        walk(node)

    walk_skip(root)

    # 公式出现事实由独立注册表全局登记（含行走期间按宿主置未解决的出
    # 现，如未映射复杂表）；confirmed 只收集已确认 MathML 行内出现
    # （多行或边界空白，D2 限定扫描上下文），与旧逐宿主登记同一口径
    confirmed = []
    for occ in registry.occurrences.values():
        if occ['unresolved'] is not None:
            _register(occ['node'], {
                'type': 'math-unresolved', 'reason': occ['unresolved'],
                'serialized': occ['serialized'],
                'section': occ['section']})
            continue
        _register(occ['node'], {
            'type': 'math', 'kind': occ['kind'], 'tex': occ['tex'],
            'raw': occ['raw'], 'section': occ['section']})
        if occ['source'] == 'mathml' and occ['kind'] == 'inline' \
                and (occ['tex'] != occ['tex'].strip()
                     or '\n' in occ['tex']):
            confirmed.append((occ['tex'], occ['section']))
    # 出现流（只取已解决）：标记在 DOM 中的顺序即来源出现顺序，供与候
    # 选 Markdown 公式跨度流按序配对（同表达式身份交换、共同漏内容都
    # 在此现形）。已映射复杂表内的出现按裁决映射的目标输出序——与共
    # 享渲染器 render_mapped_table 同一顺序（目标行主序、格内源格序、
    # 格内标记序），而非 DOM 文档序；未映射复杂表的出现已在行走期间置
    # 未解决，被下方过滤
    occ_stream = []

    def _occ_scan(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            for match in _MARK_RE.finditer(str(node)):
                occ = registry.occurrences[int(match.group(1))]
                if occ['unresolved'] is None:
                    occ_stream.append(occ)
            return
        if not isinstance(node, Tag):
            return
        if node.name == 'table' and classify_block(node) == 'table-complex':
            node_id = table_ids.get(id(node))
            ordinal = int(node_id.split('[')[1].rstrip(']')) \
                if node_id else None
            mapping = _lx_locate_mapping(node, ordinal)
            if mapping is not None:
                cells, codes = table_cell_facts(
                    node, pre_bodies=getattr(fidelity, '_pre_blocks', None))
                rendered, _declared = render_mapped_table(cells, codes,
                                                          mapping)
                for match in _MARK_RE.finditer(rendered):
                    occ = registry.occurrences[int(match.group(1))]
                    if occ['unresolved'] is None:
                        occ_stream.append(occ)
                return
        if node.name == 'table' and classify_block(node) == 'math-group':
            # 公式组表的输出序为“内容格先行、式号格随后”（与
            # _math_group_tokens/适配端组序列化同一口径），式号格在 DOM
            # 中可先于后续内容行，不能按文档序配对
            for td in node.find_all('td'):
                tcls = td.get('class') or []
                if any('eqn_center_pad' in c or 'eqno' in c for c in tcls):
                    continue
                for match in _MARK_RE.finditer(
                        td.get_text(' ', strip=True)):
                    occ = registry.occurrences[int(match.group(1))]
                    if occ['unresolved'] is None:
                        occ_stream.append(occ)
            for td in node.find_all('td'):
                tcls = td.get('class') or []
                if not any('eqno' in c for c in tcls):
                    continue
                for match in _MARK_RE.finditer(
                        td.get_text(' ', strip=True)):
                    occ = registry.occurrences[int(match.group(1))]
                    if occ['unresolved'] is None:
                        occ_stream.append(occ)
            return
        for child in node.children:
            _occ_scan(child)

    _occ_scan(root)
    return tokens, facts, confirmed, problems, occ_stream, hosts


def _latexml_md_stream(md_text, source_context=None,
                       table_ranges=None):
    """从实际候选 Markdown 独立重建有序 token 流（解析侧）。

    返回 (tokens, scan, ranges)：ranges 与 tokens 一一对应，为各 token
    在实际候选中的精确字符区间（按行扫描独立推导，不消费生成端声明的
    范围）；文字事实按真实阅读取得（markdown-it 行内解析，强调/转义/
    链接/行内代码语法只解码一次，§7.11.5：实际端不消费生成侧自报文字）。
    """
    from _verification import (fenced_line_numbers, heading_entries,
                               image_marker_spans, scan_code_fences,
                               scan_math)

    def _read(value):
        return _md_inline_reading(value, preserve_roles=True)

    tokens = []
    ranges = []
    lines = md_text.split('\n')
    fences = {block.start_line: block
              for block in scan_code_fences(md_text).blocks}
    fenced = fenced_line_numbers(md_text)
    headings = {entry[0]: (entry[1], entry[2])
                for entry in heading_entries(md_text)}
    line_offsets = {}
    offset = 0
    for index, text in enumerate(lines, start=1):
        line_offsets[index] = offset
        offset += len(text) + 1

    def _line_end(line_no):
        return line_offsets[line_no] + len(lines[line_no - 1])

    markers = {}
    for line_no, start, end, path in image_marker_spans(md_text):
        markers.setdefault(line_no, []).append((start, end, ('i', path)))
    scan = scan_math(md_text, source_context=source_context)
    scan = type(scan)(tuple(table_math_spans(scan.spans, md_text, decode_entities=True)), scan.issues)
    inline_by_line = {}
    block_spans = []
    cross = {}
    for span in scan.spans:
        if span.kind == 'block':
            block_spans.append(span)
        else:
            end_line = md_text.count('\n', 0, span.end - 1) + 1
            if end_line != span.start_line:
                cross[span.start_line] = (span, end_line)
                continue
            line_base = line_offsets[span.start_line]
            inline_by_line.setdefault(span.start_line, []).append(
                (span.start - line_base, span.end - line_base,
                 ('m', span.kind, span.raw)))
    block_lines = {}
    for span in block_spans:
        for line_no in range(span.start_line,
                             md_text.count('\n', 0, span.end - 1) + 2):
            block_lines[line_no] = span

    def _norm(value):
        return _norm_reading(value)

    _PLACEHOLDER_RE = re.compile('(\\d+)')

    def _masked_reading_frags(prefix, frag_list, suffix):
        """跨片段边界的真实阅读：数学/图片跨度先换成私用区占位符，整段
        一次行内阅读（强调等成对语法跨跨度时仍能正确解码），再按占位符
        切回（文字片段, 跨度片段）交错流。"""
        masked = [prefix]
        for index, _frag in enumerate(frag_list):
            masked.append('%d' % index)
        masked.append(suffix)
        reading = _read(''.join(masked))
        out = []
        for position, part in enumerate(
                _PLACEHOLDER_RE.split(reading)):
            if position % 2 == 1:
                out.append(frag_list[int(part)])
            elif part:
                out.append(('t', part))
        return out

    # 表格对应范围整体吸收为单个 ('table', node) token（内容与格位由
    # 逐格核对负责，04）；其区间来自声明范围本身，不参与出现→区间核对
    table_zones = sorted(table_ranges or [])
    line_no = 1
    while line_no <= len(lines):
        zone = next((z for z in table_zones
                     if z[0] <= line_offsets[line_no] < z[1]), None)
        if zone is not None:
            tokens.append(('table', zone[2]))
            ranges.append((zone[0], zone[1]))
            while line_no <= len(lines) and \
                    line_offsets[line_no] < zone[1]:
                line_no += 1
            continue
        line = lines[line_no - 1]
        if line_no in fenced:
            if line_no in fences:
                tokens.append(('code', fences[line_no].body))
                ranges.append((fences[line_no].start,
                               fences[line_no].end))
            line_no += 1
            continue
        if line_no in headings:
            level, title = headings[line_no]
            end_line = line_no
            if line_no in cross:
                # 标题内跨行公式（D2 逐字）：标题文字贯通重建到公式
                # 跨度末行，与源侧哨兵口径重建的标题事实同一 _norm 比较
                _span, end_line = cross[line_no]
                raw_lines = [lines[line_no - 1][len('#' * level) + 1:]]
                raw_lines += lines[line_no:end_line]
                title = '\n'.join(raw_lines)
            if end_line == line_no:
                title = re.sub(r'^\s*#{1,6}\s+', '', line)
                title = re.sub(r'\s+#+\s*$', '', title)
            title = _protected_reading(title, source_context, keep_math=True)
            tokens.append(('h', level, _norm_reading(
                title, mark_code=True, strip_bracket_escapes=False)))
            ranges.append((line_offsets[line_no], _line_end(end_line)))
            line_no = end_line + 1
            continue
        fn_match = re.match(r'^\[\^([^\]]+)\]:\s*(.*)$', line)
        if fn_match:
            body, last_content, cursor = footnote_definition_block(lines, line_no, cross)
            text = _markdown_block_facts(body, source_context)
            tokens.append(('fndef', fn_match.group(1), text))
            ranges.append((line_offsets[line_no], _line_end(last_content)))
            line_no = cursor
            continue
        if line_no in block_lines:
            # 块级公式跨度所在行的前后文字拆为独立 p token（§7.11.4：适配
            # 端把块级出现拆为独立块片段，前后文字各自成行，不再整行吞并）
            span = block_lines[line_no]
            end_line = md_text.count('\n', 0, span.end - 1) + 1
            if span.start_line == line_no:
                col = span.start - line_offsets[line_no]
                prefix = line[:col]
                if prefix.strip():
                    tokens.append(('p', _norm(_read(prefix))))
                    ranges.append((line_offsets[line_no], span.start))
                tokens.append(('math', 'block', span.expr))
                ranges.append((span.start, span.end))
            if end_line == line_no:
                col_end = span.end - line_offsets[end_line]
                suffix = line[col_end:]
                if suffix.strip():
                    tokens.append(('p', _norm(_read(suffix))))
                    ranges.append((span.end, _line_end(end_line)))
            line_no += 1
            continue
        if line_no in cross:
            span, end_line = cross[line_no]
            col_start = span.start - line_offsets[line_no]
            col_end = span.end - line_offsets[end_line]
            frags = _masked_reading_frags(
                line[:col_start], [('m', 'inline', span.raw)],
                lines[end_line - 1][col_end:])
            tokens.append(('pm', tuple(frags)))
            ranges.append((line_offsets[line_no], _line_end(end_line)))
            line_no = end_line + 1
            continue
        if not line.strip():
            line_no += 1
            continue
        spans = sorted((inline_by_line.get(line_no) or [])
                       + (markers.get(line_no) or []))
        if spans:
            frag_list = [frag for _start, _end, frag in spans]
            segments = []
            cursor = 0
            for start, end, _frag in spans:
                segments.append(line[cursor:start])
                cursor = end
            segments.append(line[cursor:])
            images = [f for f in frag_list if f[0] == 'i']
            if images and not ''.join(segments).strip() \
                    and len(images) == len(frag_list):
                for start, end, frag in spans:
                    tokens.append(('img', frag[1]))
                    ranges.append((line_offsets[line_no] + start,
                                   line_offsets[line_no] + end))
            else:
                # 文字段按真实阅读取得（复评 S1）；跨度先换成私用区占位
                # 符整段一次行内阅读，强调等成对语法跨跨度时仍能正确解
                # 码，再按占位符切回交错片段流
                masked = []
                for index, segment in enumerate(segments[:-1]):
                    masked.append(segment)
                    masked.append('\ue000%d\ue001' % index)
                masked.append(segments[-1])
                reading = _read(''.join(masked))
                frags = []
                for position, part in enumerate(
                        _PLACEHOLDER_RE.split(reading)):
                    if position % 2 == 1:
                        frags.append(frag_list[int(part)])
                    elif part:
                        frags.append(('t', part))
                tokens.append(('pm', tuple(frags)))
                ranges.append((line_offsets[line_no],
                               _line_end(line_no)))
        else:
            tokens.append(('p', _norm(_read(line))))
            ranges.append((line_offsets[line_no], _line_end(line_no)))
        line_no += 1
    return tokens, scan, ranges


def _latexml_tok_eq(src_tok, md_tok):
    """源/输出 token 相等：公式只比较已确认定界与逐字原表达式（行内与
    展示同一精确口径），文字经同一归一；类型冲突即不等。"""
    from _latexml_source import math_wrap

    if src_tok[0] != md_tok[0]:
        return False
    if src_tok[0] == 'h':
        return src_tok[1] == md_tok[1] and src_tok[2] == md_tok[2]
    if src_tok[0] in ('p', 'code', 'img'):
        return src_tok[1] == md_tok[1]
    if src_tok[0] == 'fndef':
        return src_tok[1] == md_tok[1] and src_tok[2] == md_tok[2]
    if src_tok[0] == 'table':
        return src_tok[1] == md_tok[1]
    if src_tok[0] == 'math':
        if src_tok[1] != md_tok[1]:
            return False
        if src_tok[1] == 'block':
            # 块级：两侧同为扫描表达式；MathML 适配包装（$$\n…\n$$）的
            # 已确认包装换行可剥，表达式本体逐字
            return md_tok[2] == src_tok[2] or (
                md_tok[2].startswith('\n') and md_tok[2].endswith('\n')
                and md_tok[2][1:-1] == src_tok[2])
        return md_tok[2] == math_wrap(src_tok[1], src_tok[2])
    if src_tok[0] == 'pm':
        # 分段事实比较（F5）：先丢弃两侧纯空白文字片段（图片块行化使
        # 边界纯空白片段计数漂移，不构成内容差异），再按（种类, 归一
        # 内容）逐段比较——文字片段经 _WS_RE 折叠+strip 后逐段相等，
        # 保留文字相对公式/图片的位置分布（位置盲的拼接比较会漏判
        # 公式移位）；公式维持 math_wrap 精确口径，图片维持引用相等。
        def _segs(frags):
            segs = []
            for frag in frags:
                if frag[0] == 't':
                    text = _norm_reading(frag[1])
                    if text:
                        segs.append(('t', text))
                else:
                    segs.append(frag)
            return segs

        a_segs, b_segs = _segs(src_tok[1]), _segs(md_tok[1])
        if len(a_segs) != len(b_segs):
            return False
        for a, b in zip(a_segs, b_segs):
            if a[0] != b[0]:
                return False
            if a[0] == 't' and a[1] != b[1]:
                return False
            if a[0] == 'm' and (a[1] != b[1]
                                or b[2] != math_wrap(a[1], a[2])):
                return False
            if a[0] == 'i' and a[1] != b[1]:
                return False
        return True
    return src_tok == md_tok


def _latexml_is_decorative(node):
    """可确认装饰（导航/页码）判定：标签或类 token 命中；不认识的类名
    不构成排除依据（03-4）。"""
    if node.name in ('nav', 'header', 'footer'):
        return True
    cls = node.get('class') or []
    return any(any(token in c for token in ('pagination', 'page-nav',
                                            'ltx_page_nav'))
               for c in cls)


def _expected_table_block(label, entry, expected_map):
    """独立重算表格对应声明的候选块（简单表=既有 table_block 表示；
    映射表=按声明映射物化）；expected_map 由对账入口预计算。"""
    return expected_map.get(label)


def reconcile_latexml_to_markdown(raw_html, md_text, section_id,
                                  adaptation, html_label='原快照',
                                  md_label='解析 Markdown',
                                  table_conversions=None):
    """LaTeXML 来源独立对账：身份/摘要核对 + 候选 correspondences 与
    unresolved 逐节点核对 + 两侧有序流比较。返回损伤诊断（空 = 通过）。

    删正文、漏节点、范围交叠、额外输出、错归属、无解释重复、等数替换、
    改类型都按各自目标原因失败；两侧不共享渲染遍历或“已输出”清单。
    """
    from _latexml_source import (math_wrap, substitution_by_ref,
                                 validate_adaptation,
                                 validate_resource_substitutions)

    diffs = []
    diffs += validate_adaptation(adaptation, raw_html=raw_html)
    decisions = (adaptation or {}).get('decisions') \
        if isinstance(adaptation, dict) else None
    decision_results = ((adaptation or {}).get('decision_results') or []) \
        if isinstance(adaptation, dict) else []
    if table_conversions is None:
        table_conversions = \
            ((adaptation or {}).get('table_conversions') or None) \
            if isinstance(adaptation, dict) else None
    (src_tokens, facts, confirmed, src_problems,
     occ_stream, hosts) = _latexml_src_stream(
        raw_html, section_id, decisions, decision_results,
        table_conversions=table_conversions, adaptation=adaptation)
    if isinstance(adaptation, dict) \
            and adaptation.get('resource_substitutions'):
        snap_path = (adaptation.get('snapshot') or {}).get('path')
        snapshot_dir = (os.path.dirname(os.path.abspath(snap_path))
                        if isinstance(snap_path, str)
                        and os.path.isfile(snap_path) else None)
        if snapshot_dir is None:
            diffs.append('来源依据缺 snapshot.path，无法核对资源替换基点')
        else:
            diffs += validate_resource_substitutions(
                adaptation, snapshot_dir,
                ((adaptation.get('paper_identity') or {}).get('version')))
    if src_tokens is None:
        return diffs + ['%s 未找到选区根（article/main/body 或 section_id）'
                        % html_label]
    for problem in src_problems:
        diffs.append('%s %s' % (html_label, problem))
    # 共享扫描上下文只来自独立重建的已确认行内事实（多行或边界空白，
    # D2 逐字）：待验证
    # 对应不能自行授予跨行资格；核对失败由正文流/切片逐字比较兜底
    context = _SourceMathContext(confirmed)
    table_zones = [
        (entry['md_start'], entry['md_end'], entry.get('node'))
        for entry in ((adaptation or {}).get('correspondences') or [])
        if isinstance(entry, dict) and entry.get('content_type') == 'table'
        and isinstance(entry.get('md_start'), int)]
    md_tokens, scan, md_ranges = _latexml_md_stream(
        md_text, source_context=context, table_ranges=table_zones)
    actual_table_rows = markdown_table_row_lines(md_text)
    for issue in scan.issues:
        diffs.append('%s L%d 未解决数学定界 %r: %s'
                     % (md_label, issue.start_line, issue.raw, issue.reason))

    # ---- 表格候选块的独立重算（简单=既有表示；映射=按声明物化） ----
    expected_table_blocks = {}
    if any(c.get('content_type') == 'table'
           for c in ((adaptation or {}).get('correspondences') or [])
           if isinstance(c, dict)):
        from _latexml_source import (locate_table_mapping as _ltm,
                                     render_mapped_table, table_cell_facts,
                                     table_node_ids as _tids)
        check_soup = BeautifulSoup(
            protect_code_entities(raw_html, skip_pre=True), 'html.parser')
        check_root = (check_soup.find(id=section_id)
                      if section_id else
                      (check_soup.find('article') or check_soup.find('main')
                       or check_soup.find('body')))
        if check_root is not None:
            tids = _tids(check_root)
            for entry in ((adaptation or {}).get('correspondences') or []):
                if not (isinstance(entry, dict)
                        and entry.get('content_type') == 'table'):
                    continue
                node_id = entry.get('node')
                table = next((n for n in check_root.find_all('table')
                              if tids.get(id(n)) == node_id
                              and n.find_parent('table') is None), None)
                if table is None:
                    diffs.append('表格对应 %s 在原始快照选区内不存在' % node_id)
                    continue
                style = (entry.get('conversion') or {}).get('style')
                if style == 'simple':
                    try:
                        from _latexml_source import (
                            OccurrenceRegistry as _OccReg,
                            _expand_markers_inline as _expand_marks,
                            prepare_math_dom as _pmd)
                        converted = copy.deepcopy(table)
                        fidelity2 = HtmlFidelity()
                        # 与适配端同一 DOM 形态：格内 <pre> 先换为占位注释
                        # （代码正文不进格文字），格内代码由 cell_fences
                        # 恢复为 [TABLE-CODE] 围栏
                        for pre in converted.find_all('pre'):
                            body = clean_code_html(pre.decode_contents())
                            marker = ' __TECHDOC_PRE_%d__ ' % len(
                                fidelity2._pre_blocks)
                            fidelity2._pre_blocks.append(body)
                            pre.replace_with(Comment(marker))
                        registry2 = _OccReg()
                        _pmd(converted, [], registry2)
                        expected_table_blocks[node_id] = _expand_marks(
                            '\n'.join(fidelity2.table_block(converted)
                                      ).strip('\n'), registry2)
                    except Exception:
                        diffs.append('表格 %s 含未解释跨度且缺少映射'
                                     % node_id)
                elif style == 'mapped':
                    ordinal = int(node_id.split('[')[1].rstrip(']'))
                    mapping = _ltm(table, ordinal,
                                   (table_conversions or {}).get('tables'))
                    if mapping is None:
                        diffs.append('表格 %s 声明映射但 locate 无对应条目'
                                     % node_id)
                        continue
                    cells, codes = table_cell_facts(table)
                    expected_table_blocks[node_id] = render_mapped_table(
                        cells, codes, mapping)[0]

    # ---- 来源依据（correspondences/unresolved）逐节点核对 ----
    corrs = [c for c in ((adaptation or {}).get('correspondences') or [])
             if isinstance(c, dict)]
    unres = [u for u in ((adaptation or {}).get('unresolved') or [])
             if isinstance(u, dict)]
    ranges = []
    seen_nodes = {}
    for entry in corrs + unres:
        label = entry.get('node')
        start, end = entry.get('md_start'), entry.get('md_end')
        if not isinstance(label, str) or not label:
            diffs.append('依据条目缺少节点身份: %r' % (entry,))
            continue
        if not isinstance(start, int) or not isinstance(end, int) \
                or start < 0 or end > len(md_text) or start >= end:
            diffs.append('依据条目 %s 的 Markdown 范围非法: %r'
                         % (label, (start, end)))
            continue
        ranges.append((start, end, label))
        if label in seen_nodes:
            diffs.append('依据条目 %s 被重复声明（无解释重复）' % label)
        seen_nodes[label] = entry
    ranges.sort()
    # 出现身份区间为精确字符区间（§7.11.4）：公式对应落在宿主覆盖区间
    # 内（含相等）是正常归属；部分交叠与非公式间的重复/包含区间一律
    # 拦截。
    math_labels = {e.get('node') for e in corrs
                   if e.get('content_type') == 'math'}
    for (prev_s, prev_e, prev_l), (s, e, label) in zip(ranges, ranges[1:]):
        if s < prev_e and not (prev_s < s and e < prev_e):
            if (prev_l in math_labels) != (label in math_labels):
                # 精确公式区间落在宿主覆盖区间内（含相等、含同起点）是
                # 正常归属；排序不保证宿主在前，按角色判定包含方向
                m_s, m_e = (prev_s, prev_e) if prev_l in math_labels \
                    else (s, e)
                h_s, h_e = (s, e) if prev_l in math_labels \
                    else (prev_s, prev_e)
                if h_s <= m_s and m_e <= h_e:
                    continue
            diffs.append('依据条目范围交叠: %s [%d,%d) 与 %s [%d,%d)'
                         % (prev_l, prev_s, prev_e, label, s, e))
    fence_lines = fenced_line_numbers(md_text)

    # ---- 出现流配对（§7.11.4）：独立重建的来源出现（文档序，只取已解
    #      决）与候选 Markdown 公式跨度（排除围栏行）按序一一配对——数
    #      量、类型与逐字表达式必须一致；同表达式身份交换、源文与候选
    #      共同漏内容都会在此现形。配对结果为各出现身份给出独立预期区
    #      间，逐条核对声明的公式对应区间。 ----
    paired_ranges = {}
    if occ_stream is not None:
        md_spans = [span for span in scan.spans
                    if span.start_line not in fence_lines]
        if len(md_spans) != len(occ_stream):
            diffs.append('公式出现数量不一致: %s %d 处 vs %s %d 处'
                         % (html_label, len(occ_stream), md_label,
                            len(md_spans)))
        for occ, span in zip(occ_stream, md_spans):
            expr = span.expr
            if span.kind == 'block' and expr.startswith('\n') \
                    and expr.endswith('\n'):
                # 块级证据口径：剥一层 $$ 包装换行（math_wrap 逆运算）
                expr = expr[1:-1]
            if occ['kind'] != span.kind or occ['tex'] != expr:
                diffs.append('公式出现 %s 与候选跨度不符（身份交换/错位/'
                             '缺漏）: %s (%s, %r) vs %s L%d (%s, %r)'
                             % (occ['node'], html_label, occ['kind'],
                                occ['tex'], md_label, span.start_line,
                                span.kind, expr))
                continue
            paired_ranges[occ['node']] = (span.start, span.end)

    # ---- 出现→实际区间独立对齐（复评 F1）：两侧正文流全等时，按对齐
    #      token 聚合各来源节点身份的独立实际字符区间（区间由解析侧行扫
    #      描独立推导，不消费生成端声明），与依据声明范围逐节点精确核
    #      对——标题/段落/图片等同文或同资源节点的声明范围互换、错绑他
    #      处区间即不符。流不等时已有流差异，区间对齐不可靠，不再核对。
    #      表格 token 的区间来自声明范围（自证），由逐格核对负责；公式
    #      由上方出现流配对负责。 ----
    paired_node_ranges = {}
    streams_equal = len(src_tokens) == len(md_tokens) and all(
        _latexml_tok_eq(s_tok, m_tok)
        for s_tok, m_tok in zip(src_tokens, md_tokens))
    if streams_equal:
        for host, m_tok, rng in zip(hosts, md_tokens, md_ranges):
            if host is None or m_tok[0] == 'table':
                continue
            bound = paired_node_ranges.get(host)
            if bound is None:
                paired_node_ranges[host] = [rng[0], rng[1]]
            else:
                bound[0] = min(bound[0], rng[0])
                bound[1] = max(bound[1], rng[1])

    _RANGE_CHECKED_TYPES = (
        'heading', 'paragraph', 'image', 'figure-caption', 'footnote-def',
        'listing', 'algorithm', 'math-group', 'unresolved-container')

    md_fences = scan_code_fences(md_text).blocks

    def _slice_reading(slice_text, base):
        """候选切片的真实阅读：切片内的公式跨度（共享扫描口径）换成占位
        符、完整落入切片的代码围栏整块剔除（代码由独立 code token 逐字
        对账），剩余文字整段一次行内阅读后把占位符还原为表达式——公式
        在链接标签内时链接语法不被拆断，\\[ 等公式定界不被普通阅读当成
        括号转义，强调/反斜线转义只解码一次。"""
        end_limit = base + len(slice_text)
        fence_events = [(fence.start, fence.end)
                        for fence in md_fences
                        if fence.start >= base and fence.end <= end_limit]

        def _in_fence(pos):
            return any(f_start <= pos < f_end
                       for f_start, f_end in fence_events)

        events = [(f_start, f_end, None)
                  for f_start, f_end in fence_events]
        exprs = []
        for span in scan.spans:
            if span.start < base or span.end > end_limit \
                    or _in_fence(span.start):
                continue
            events.append((span.start, span.end, span.raw))
        events.sort()
        masked = []
        cursor = 0
        read_exprs = []
        for ev_start, ev_end, replacement in events:
            if ev_start - base < cursor:
                continue
            masked.append(slice_text[cursor:ev_start - base])
            if replacement is not None:
                masked.append('%d' % len(read_exprs))
                read_exprs.append(replacement)
            cursor = ev_end - base
        masked.append(slice_text[cursor:])
        reading = _md_inline_reading(''.join(masked), preserve_roles=True)
        return _MD_READ_PLACEHOLDER_RE.sub(
            lambda m: read_exprs[int(m.group(1))], reading)

    def _check_declared_range(label, entry):
        """声明范围 == 独立对齐的实际区间（复评 F1）；类型不符等致命问
        题已单独报告时不再重复。"""
        if not streams_equal:
            return
        d_start, d_end = entry.get('md_start'), entry.get('md_end')
        if not isinstance(d_start, int) or not isinstance(d_end, int):
            return  # 范围非法已在登记检查中报告
        paired = paired_node_ranges.get(label)
        if paired is None:
            diffs.append('对应节点 %s 未在独立对齐的实际输出区间中登记'
                         '（正文流未覆盖该身份）' % label)
            return
        if (d_start, d_end) != (paired[0], paired[1]):
            diffs.append('对应节点 %s 的声明范围 [%d,%d) 与独立对齐的实'
                         '际区间 [%d,%d) 不符（错绑输出区间/范围互换）'
                         % (label, d_start, d_end,
                            paired[0], paired[1]))

    for entry in corrs:
        label = entry.get('node')
        fact = facts.get(label)
        if fact is None:
            # 全部公式出现（含字面）在独立重建中均有身份登记；无身份的
            # 对应一律为依据与快照不符，不再按同文本/宿主区间找补
            diffs.append('对应节点 %s 在原始快照选区内不存在（依据与'
                         '快照不符）' % label)
            continue
        if fact.get('section') is not None \
                and entry.get('section') != fact.get('section'):
            diffs.append('对应节点 %s 章节归属不符: 依据 #%s vs 独立重建 #%s'
                         % (label, entry.get('section'), fact['section']))
        ctype = entry.get('content_type')
        start, end = entry['md_start'], entry['md_end']
        slice_text = md_text[start:end]
        if ctype in _RANGE_CHECKED_TYPES:
            # 非公式节点的声明范围与独立对齐实际区间精确核对（复评 F1）
            _check_declared_range(label, entry)
        if ctype == 'math':
            if fact['type'] != 'math':
                diffs.append('对应节点 %s 内容类型不符: 依据 math vs 实际 %s'
                             % (label, fact['type']))
                continue
            if entry.get('kind') != fact['kind']:
                diffs.append('公式 %s 类型冲突: 依据 %s vs 原节点 %s'
                             % (label, entry.get('kind'), fact['kind']))
                continue
            if (entry.get('tex') or '') != fact['tex']:
                diffs.append('公式 %s 表达式与原节点不符（等数替换/改写）: '
                             '依据 %r vs 原节点 %r'
                             % (label, entry.get('tex'), fact['tex']))
                continue
            if md_text.count('\n', 0, start) + 1 in actual_table_rows:
                slice_text = decode_table_math(slice_text)
            if slice_text != fact['raw']:
                diffs.append('公式 %s 的候选切片与实际写出内容不符: %r'
                             % (label, slice_text))
            paired = paired_ranges.get(label)
            if paired is None:
                diffs.append('公式 %s 未通过出现流配对（数量/类型/表达式'
                             '不符或缺失）' % label)
            elif (start, end) != paired:
                diffs.append('公式 %s 的候选区间 [%d,%d) 与出现身份传递'
                             '区间 [%d,%d) 不符'
                             % (label, start, end, paired[0], paired[1]))
        elif ctype == 'heading':
            if fact['type'] != 'heading':
                diffs.append('对应节点 %s 内容类型不符: 依据 heading vs 实际 %s'
                             % (label, fact['type']))
            elif entry.get('level') is not None \
                    and entry.get('level') != fact['level']:
                diffs.append('标题 %s 层级不符: 依据 %r vs 原节点 %r'
                             % (label, entry.get('level'), fact['level']))
        elif ctype == 'paragraph':
            if fact['type'] != 'paragraph':
                diffs.append('对应节点 %s 内容类型不符: 依据 paragraph vs '
                             '实际 %s' % (label, fact['type']))
                continue
            expected = ''.join(
                f[1] if f[0] == 't' else math_wrap(f[1], f[2])
                for f in fact['frags'])
            if _norm_reading(_slice_reading(slice_text, start), source_context=context) \
                    != _norm_reading(expected, source_context=context):
                diffs.append('段落 %s 候选内容被改写/删除: 依据范围文字与'
                             '独立重建不符' % label)
        elif ctype == 'image':
            if fact['type'] != 'image':
                diffs.append('对应节点 %s 内容类型不符: 依据 image vs 实际 %s'
                             % (label, fact['type']))
                continue
            for field in ('figure', 'subfigure'):
                if entry.get(field) != fact.get(field):
                    diffs.append('图片 %s %s 归属不符: 依据 %r vs 独立重建 %r'
                                 '（错父节点）' % (label, field,
                                                 entry.get(field),
                                                 fact.get(field)))
            expected = '[IMG: %s]' % fact['reference']
            if slice_text.strip() != expected:
                diffs.append('图片 %s 候选切片不符: %r vs %r'
                             % (label, slice_text.strip(), expected))
            declared_ref = (entry.get('conversion') or {}).get('reference')
            if declared_ref is not None \
                    and declared_ref != fact['reference']:
                diffs.append('图片 %s 目标引用与独立规划不符: 依据 %r vs '
                             '实际 %r（同名异资源不得静默覆盖）'
                             % (label, declared_ref, fact['reference']))
            style = (entry.get('conversion') or {}).get('style')
            if style == 'substituted':
                subs = substitution_by_ref(adaptation)
                if fact.get('source_ref') not in subs:
                    diffs.append('图片 %s 声明替换但 resource_substitutions '
                                 '无对应原引用（依据不完整）' % label)
        elif ctype == 'figure-caption':
            if fact['type'] != 'figure-caption':
                diffs.append('对应节点 %s 内容类型不符: 依据 figure-caption '
                             'vs 实际 %s' % (label, fact['type']))
                continue
            for field in ('figure', 'subfigure'):
                if entry.get(field) != fact.get(field):
                    diffs.append('图题 %s %s 归属不符: 依据 %r vs 独立重建 '
                                 '%r（错父节点）' % (label, field,
                                                  entry.get(field),
                                                  fact.get(field)))
            if _norm_reading(_slice_reading(slice_text, start), source_context=context) != fact['text']:
                diffs.append('图题 %s 候选内容被改写' % label)
        elif ctype == 'footnote-def':
            if fact['type'] != 'footnote-def':
                diffs.append('对应节点 %s 内容类型不符: 依据 footnote-def '
                             'vs 实际 %s' % (label, fact['type']))
                continue
            if entry.get('label') != fact.get('label'):
                diffs.append('脚注定义 %s 标签不符: 依据 %r vs 原节点 %r'
                             '（命名标签被抽数字合并）' % (label,
                                                     entry.get('label'),
                                                     fact.get('label')))
        elif ctype == 'listing':
            if fact['type'] != 'listing':
                diffs.append('对应节点 %s 内容类型不符: 依据 listing vs '
                             '实际 %s' % (label, fact['type']))
                continue
            if slice_text.strip() == '':
                diffs.append('清单 %s 候选块为空' % label)
        elif ctype == 'math-group':
            if fact['type'] != 'group':
                diffs.append('对应节点 %s 内容类型不符: 依据 math-group vs '
                             '实际 %s' % (label, fact['type']))
        elif ctype == 'table':
            if fact['type'] != 'table':
                diffs.append('对应节点 %s 内容类型不符: 依据 table vs 实际 %s'
                             % (label, fact['type']))
                continue
            expected = _expected_table_block(label, entry,
                                             expected_table_blocks)
            if expected is not None and \
                    _norm_text(slice_text, unwrap_links=False) \
                    != _norm_text(expected, unwrap_links=False):
                diffs.append('表格 %s 候选切片与独立重建输出不符（错格/'
                             '展平/转代码）' % label)
        elif ctype == 'algorithm':
            if fact['type'] != 'algorithm':
                diffs.append('对应节点 %s 内容类型不符: 依据 algorithm vs '
                             '实际 %s' % (label, fact['type']))
                continue
            if entry.get('title') != fact.get('title'):
                diffs.append('算法题注 %s 与独立重建不符: 依据 %r vs 实际 %r'
                             % (label, entry.get('title'),
                                fact.get('title')))
        else:
            diffs.append('对应节点 %s 的 content_type 未识别: %r'
                         % (label, ctype))

    for entry in unres:
        label = entry.get('node')
        fact = facts.get(label)
        if fact is None:
            diffs.append('未解决项 %s 在原始快照选区内不存在（依据与快照'
                         '不符）' % label)
            continue
        if entry.get('reason') != fact.get('reason'):
            diffs.append('未解决项 %s 原因不符: 依据 %r vs 独立重建 %r'
                         % (label, entry.get('reason'), fact.get('reason')))
            continue
        if entry.get('content_type') in _RANGE_CHECKED_TYPES:
            # 保留容器的声明范围同样与独立对齐实际区间精确核对（复评 F1）
            _check_declared_range(label, entry)
        preserved = entry.get('preserved')
        if preserved is not None \
                and md_text[entry['md_start']:entry['md_end']] != preserved:
            diffs.append('未解决项 %s 的保留内容在候选中被改写/删除' % label)

    # ---- 公式组：独立重建的组/成员序/式号与依据核对（02-4） ----
    group_facts = {label: fact for label, fact in facts.items()
                   if fact.get('type') == 'group'}
    declared_groups = [g for g in ((adaptation or {}).get('groups') or [])
                       if isinstance(g, dict)]
    declared_by_node = {}
    for group in declared_groups:
        label = group.get('node')
        if label in declared_by_node:
            diffs.append('公式组 %s 被重复声明（无解释重复）' % label)
        declared_by_node[label] = group
        fact = group_facts.get(label)
        if fact is None:
            diffs.append('公式组 %s 在原始快照选区内不存在（依据与快照不符）'
                         % label)
            continue
        if fact.get('section') is not None                 and group.get('section') != fact.get('section'):
            diffs.append('公式组 %s 章节归属不符: 依据 #%s vs 独立重建 #%s'
                         % (label, group.get('section'), fact['section']))
        if list(group.get('members') or []) != list(fact['members']):
            diffs.append('公式组 %s 成员或顺序与独立重建不符: 依据 %r vs '
                         '原快照 %r' % (label, group.get('members'),
                                       fact['members']))
        declared_eqnos = [{'member': e.get('member'), 'text': e.get('text'),
                           'target': e.get('target')}
                          for e in (group.get('eqnos') or [])]
        if declared_eqnos != fact['eqnos']:
            diffs.append('公式组 %s 式号与独立重建不符: 依据 %r vs 原快照 %r'
                         % (label, declared_eqnos, fact['eqnos']))
    for label, fact in group_facts.items():
        if label not in declared_by_node:
            diffs.append('原始快照公式组 %s 缺少来源依据登记（漏组）' % label)

    # ---- 脚注真实标签配对：引用出现 ↔ 定义（不抽数字合并，03-3） ----
    def_labels = {f['label'] for f in facts.values()
                  if f.get('type') == 'footnote-def'}
    for label, fact in facts.items():
        if fact.get('type') == 'footnote-ref' \
                and fact.get('label') not in def_labels:
            diffs.append('脚注引用 %s 的标签 %r 在原始快照中无定义节点配对'
                         % (label, fact.get('label')))

    # ---- 装饰排除/重复合并裁决的独立验证（03-4）：节点名在原始快照
    #      重新定位，装饰性与同源内容相等由独立 DOM 重算 ----
    if decision_results:
        from _latexml_source import (aside_node_ids as _aids,
                                     container_node_ids as _cids,
                                     figure_node_ids as _fids,
                                     group_node_ids as _gids)
        check_soup = BeautifulSoup(
            protect_code_entities(raw_html, skip_pre=True), 'html.parser')
        check_root = (check_soup.find(id=section_id)
                      if section_id else
                      (check_soup.find('article') or check_soup.find('main')
                       or check_soup.find('body')))
        name_map = {}
        tag_first = {}
        if check_root is not None:
            for node in check_root.find_all(True):
                tag_first.setdefault(node.name, node)
                for mapping in (_cids(check_root), _gids(check_root),
                                _fids(check_root), _aids(check_root)):
                    name = mapping.get(id(node))
                    if name:
                        name_map[name] = node

        def _lookup_result(node_name):
            if not isinstance(node_name, str):
                return None
            if node_name in name_map:
                return name_map[node_name]
            return tag_first.get(node_name.split('#', 1)[0])

        for result in decision_results:
            if not isinstance(result, dict):
                continue
            node_name = result.get('node')
            action = result.get('action')
            outcome = result.get('result')
            node = _lookup_result(node_name)
            if action == 'exclude-decoration':
                if outcome == 'excluded':
                    if node is None:
                        diffs.append('装饰排除裁决 %s 的节点在原始快照不'
                                     '存在' % node_name)
                    elif not _latexml_is_decorative(node):
                        diffs.append('装饰排除裁决 %s 不成立：节点不是可确'
                                     '认装饰（导航/页码）' % node_name)
                    else:
                        text = _WS_RE.sub(' ', node.get_text(' ')).strip()
                        if text and text in _WS_RE.sub(' ', md_text):
                            diffs.append('装饰排除裁决 %s 未落实：被排除内'
                                         '容仍在候选中' % node_name)
                elif outcome != 'unresolved':
                    diffs.append('装饰排除裁决 %s 结果状态非法: %r'
                                 % (node_name, outcome))
            elif action == 'merge-duplicate':
                target = _lookup_result(result.get('into'))
                if outcome == 'merged':
                    if node is None or target is None:
                        diffs.append('重复合并裁决 %s 的节点不存在'
                                     % node_name)
                    else:
                        a = _WS_RE.sub(' ', node.get_text(' ')).strip()
                        b = _WS_RE.sub(' ', target.get_text(' ')).strip()
                        if not a or a != b:
                            diffs.append('重复合并裁决 %s 不成立：同源内容'
                                         '不相等，不能只按图号/题注前缀/'
                                         '字节去重' % node_name)
                elif outcome != 'unresolved':
                    diffs.append('重复合并裁决 %s 结果状态非法: %r'
                                 % (node_name, outcome))

    # ---- 表格逐格核对（04）：复用现行逐表转换映射合同——_SourceFacts
    #      独立提取源格（跨度/空值/代码/公式），_MarkdownFacts 扫描实际
    #      输出格位，_conversion_map_diffs 逐源格验证映射；未映射表按
    #      既有格位/代码表示比较。转代码、展平串、总计数不能豁免。 ----
    if any(fact.get('type') == 'table' for fact in facts.values()) \
            or table_conversions:
        try:
            src_facts_all = _SourceFacts(raw_html, 'reference', section_id,
                                         mathml_alttext=True)
            md_facts_all = _MarkdownFacts(md_text,
                                          source_context=context)
        except Exception as exc:  # 独立提取失败按损伤定位，不静默跳过
            diffs.append('表格独立事实提取失败: %s' % exc)
            src_facts_all = md_facts_all = None
        if src_facts_all is not None:
            mapped_src = set()
            claimed_md = set()
            if table_conversions:
                (map_diffs, mapped_src, claimed_md, _factors,
                 _cell_targets, _note_targets) = _conversion_map_diffs(
                    raw_html, section_id, src_facts_all, md_facts_all,
                    table_conversions, html_label, md_label)
                diffs.extend(map_diffs)
            data_table_ordinals = set()
            _check_soup = BeautifulSoup(
                protect_code_entities(raw_html, skip_pre=True),
                'html.parser')
            _check_root = (_check_soup.find(id=section_id)
                           if section_id else
                           (_check_soup.find('article')
                            or _check_soup.find('main')
                            or _check_soup.find('body')))
            if _check_root is not None:
                # 以顶层表格的文档序号为键（与 _SourceFacts._table_records
                # 同一枚举口径）：表 id 属性可缺失，无 id 时 None 碰撞会把
                # 等式表误并入数据表
                _ordinal = 0
                for _t in _check_root.find_all('table'):
                    if _t.find_parent('table') is not None or _in_pre(_t):
                        continue
                    _ordinal += 1
                    if 'equation' in ' '.join(_t.get('class') or []):
                        continue  # 等式表由公式组核对负责
                    data_table_ordinals.add(_ordinal)
            data_records = [r for r in src_facts_all.table_records
                            if r['ordinal'] in data_table_ordinals]
            table_diffs = _table_record_diffs(
                data_records, md_facts_all.table_records(),
                mapped_src, claimed_md, html_label, md_label)
            diffs.extend(table_diffs)

    # ---- 覆盖：独立重建的每个内容节点必须有依据（漏节点/漏正文） ----
    for label, fact in facts.items():
        if fact['type'] in ('math', 'paragraph', 'image', 'heading',
                            'figure-caption', 'footnote-def', 'algorithm',
                            'table', 'listing'):
            if label not in seen_nodes:
                diffs.append('原始快照节点 %s（%s）缺少来源依据对应'
                             '（漏节点/漏正文）' % (label, fact['type']))
        elif fact['type'] in ('math-unresolved', 'unresolved-container'):
            if label not in seen_nodes:
                diffs.append('原始快照未解决节点 %s（%s）未在依据中登记'
                             % (label, fact['type']))

    # ---- 输出覆盖：候选中的每个公式必须落在某个公式对应范围内 ----
    corr_math_ranges = sorted(
        (entry['md_start'], entry['md_end'])
        for entry in corrs
        if entry.get('content_type') == 'math'
        and isinstance(entry.get('md_start'), int))
    # 各类宿主内公式出现均有各自的精确对应（§7.11 ticket 19–22），宿主
    # 范围不再授予覆盖资格：无对应范围的公式输出即无依据额外输出
    for span in scan.spans:
        if span.start_line in fence_lines:
            continue
        if any(s <= span.start and span.end <= e for s, e in corr_math_ranges):
            continue
        diffs.append('%s 存在无来源依据的公式输出（额外输出）: L%d %r'
                     % (md_label, span.start_line, span.raw))

    # ---- 两侧有序流比较（删正文/漏公式/乱序/错归属/额外输出） ----
    for index, (src_tok, md_tok) in enumerate(zip(src_tokens, md_tokens)):
        if not _latexml_tok_eq(src_tok, md_tok):
            diffs.append('正文流第 %d 项不一致: %s %r vs %s %r'
                         % (index + 1, html_label, src_tok,
                            md_label, md_tok))
    if len(src_tokens) != len(md_tokens):
        diffs.append('正文流长度不一致: %s %d 项 vs %s %d 项（删正文/'
                     '额外输出）' % (html_label, len(src_tokens),
                                    md_label, len(md_tokens)))
    return diffs
