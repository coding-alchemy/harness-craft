"""LaTeXML 来源依据（version:1 / format:latexml）共享合同、适配器与绑定。

设计 §4.2/§4.3/§4.6（二期 D1/D4，ticket 01 最小来源闭环）：

- 来源依据文件只描述当前 LaTeXML 来源、身份与转换裁决；不承担任务状态。
  输入由主 Agent 在独立确认论文身份后提供（paper_identity 含预期/实际
  题名、论文 ID、实际版本、最终 URL、取得时间与确认依据）；消费者
  （预检/拆包/片段检查/恢复/合并/交付）重读原始快照重算摘要、重读实际
  Markdown 切片核对，不把生成器自报摘要当作独立证明。
- 适配器在原节点上直接转换（设计选择①）：MathML ``<math alttext>``
  取实体解码后的 alttext 作为 TeX，保持原表达式与行内/展示类型；无
  alttext/空 TeX/类型冲突逐节点进 unresolved，保留原节点序列化内容，
  不猜写、不丢弃、不留内部占位符。输入中的旧 correspondences 不能代替
  本次重建。
- check_policy（D4 最小实现）：拆包 frontmatter 附加 source_adaptation
  引用；recover/merge 证据中的 check_policy 块只投影本包字符范围实际
  涉及的原节点/对应/裁决与适配器身份，无关事实变化不使本包证据失效。
"""
import hashlib
import json
import os
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from _html_fidelity import (HtmlFidelity, clean_code_html,
                            contains_block_content,
                            escape_text_backslashes)
from _verification import (fenced_line_numbers, scan_code_fences, scan_math,
                           markdown_table_row_lines, table_math_spans, encode_table_math,
                           decode_table_math)

ADAPTATION_VERSION = 1
ADAPTATION_FORMAT = 'latexml'

# 身份确认必填字段（R1.1：预期/实际题名、论文 ID、实际版本、最终 URL、
# 取得时间、独立确认依据；缺项即“缺依据”，阻止分派/完整交付）
IDENTITY_FIELDS = ('expected_title', 'actual_title', 'paper_id', 'version',
                   'final_url', 'retrieved_at', 'confirmation')

_SKIP_TAGS = {'script', 'style', 'noscript'}
_INLINE_CONTAINER_TAGS = {
    'a', 'abbr', 'b', 'bdi', 'bdo', 'big', 'cite', 'code', 'data', 'del',
    'dfn', 'em', 'font', 'i', 'ins', 'kbd', 'mark', 'q', 'rp', 'rt', 'ruby',
    's', 'samp', 'small', 'span', 'strike', 'strong', 'sub', 'sup', 'time',
    'tt', 'u', 'var', 'wbr',
}

_HEADING_RE = re.compile(r'h[1-6]')


def classify_block(tag):
    """块级节点分类（适配端与独立对账端共用同一识别口径；遍历本身各自
    独立）：supported=本票支持转换；inline=透明行内容器递归；skip=装饰
    排除；unsupported=未支持内容容器（保留原文并定位为未解决项）；
    math-group=公式组/式号容器（ticket 02：成员分别输出且组关系入对应）。"""
    name = tag.name
    if name in _SKIP_TAGS:
        return 'skip'
    cls = tag.get('class') or []
    cls = cls if isinstance(cls, list) else [cls]
    if name == 'div' and any('subequations' in c for c in cls):
        return 'math-group'
    if name == 'table' and any('equation' in c for c in cls):
        return 'math-group'
    # 表格（04）：无跨行/跨列为简单表（既有格位表示）；含跨度为复杂表，
    # 必须经 table_conversions 逐源格裁决映射，不展平、不转代码
    if name == 'table':
        if _table_has_spans(tag):
            return 'table-complex'
        return 'table-simple'
    # 参考文献条目列表（04/08）：逐条保留文字与源序
    if name == 'ul' and any('biblist' in c for c in cls):
        return 'biblist'
    # 简单无序列表（08）：条目行表示，嵌套/复杂列表仍为未支持容器
    if name == 'ul' and any('itemize' in c for c in cls):
        return 'itemize'
    # 无类名的简单 ul（F4 列表项宿主）：条目仅行内容时同 itemize 逐条
    # 表示；含嵌套列表/块内容的仍为未支持容器
    if name == 'ul' and not cls:
        items = tag.find_all('li', recursive=False)
        if items and all(not contains_block_content(
                li, ['p', 'ul', 'ol', 'table', 'dl', 'div', 'pre', 'figure',
                     'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                for li in items):
            return 'itemize'
    # 算法/代码清单行容器：保留结构（含行内公式），不转代码（03-2/08）；
    # 精确匹配 ltx_listing，避免把 ltx_listingline 行容器误判为清单
    if any(c == 'ltx_listing' for c in cls):
        return 'listing'
    # 算法清单：标题保留官方编号，正文递归保持结构，不转代码（03-2）
    if any('algorithm' in c for c in cls):
        return 'algorithm'
    # LaTeXML 脚注定义节点（含真实命名标签 id），由 footnote-def 分支处理
    if tag.get('id') and any('note' in c for c in cls) and name == 'div' \
            and tag.find(['p', 'pre', 'div']) is not None:
        return 'footnote-def'
    # ltx_notes 容器：透明递归，各定义分别处理
    if name == 'div' and any('notes' in c for c in cls):
        return 'inline'
    # 纯文字 aside（无块内容）：段落化支持，可参与同源重复合并裁决
    if name == 'aside' and not contains_block_content(
            tag, ['p', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure',
                  'blockquote']):
        return 'supported'
    if _HEADING_RE.fullmatch(name) or name in (
            'p', 'pre', 'blockquote', 'figure', 'img'):
        return 'supported'
    if name in ('div', 'section', 'article', 'main', 'blockquote'):
        if 'math' in cls:
            return 'supported'
        if name == 'blockquote':
            return 'inline'  # 透明递归：引用容器本身不产生输出
        if any(c in cls for c in ('admonition', 'note')):
            return 'unsupported'
        if contains_block_content(
                tag, ['p', 'ul', 'ol', 'table', 'dl', 'div', 'section',
                      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figure',
                      'blockquote']):
            return 'inline'  # 透明块容器：递归直接子节点
        return 'supported'   # 无块内容的 div：段落化输出
    if name in _INLINE_CONTAINER_TAGS:
        return 'inline'
    return 'unsupported'


def group_node_ids(root):
    """公式组容器的稳定命名（文档序；div 组整体命名，组内 equation 表随组；
    独立 equation 表单独命名）。"""
    groups = []
    for node in root.find_all(['div', 'table']):
        if classify_block(node) != 'math-group':
            continue
        if node.name == 'table' and node.find_parent(
                'div', class_=lambda v: v and 'subequations' in ' '.join(
                    v if isinstance(v, list) else [v])) is not None:
            continue  # 组内成员行不单独命名
        groups.append(node)
    return {id(node): 'group[%d]' % ordinal
            for ordinal, node in enumerate(groups, start=1)}


def _table_has_spans(table):
    for cell in table.find_all(['td', 'th']):
        for attr in ('rowspan', 'colspan'):
            raw = cell.get(attr)
            if raw is None:
                continue
            try:
                if int(str(raw).strip()) != 1:
                    return True
            except (TypeError, ValueError):
                return True
    return False


def table_node_ids(root):
    '顶层表格（排除嵌套）的稳定命名（文档序，跨进程可重算）。'
    top = [n for n in root.find_all('table')
           if n.find_parent('table') is None]
    return {id(node): 'table[%d]' % ordinal
            for ordinal, node in enumerate(top, start=1)}


def _span_value(cell, attr):
    raw = cell.get(attr)
    try:
        return int(str(raw).strip()) if raw is not None else 1
    except (TypeError, ValueError):
        return None


_PRE_PLACEHOLDER_RE = re.compile(r'^__TECHDOC_PRE_(\d+)__$')


def table_cell_facts(table, pre_bodies=None):
    '独立可重算的逐格事实：{(row, col): (text, rowspan, colspan, order)}'
    ' 与格内代码 [(row, col, n, body)]；文字口径与 _SourceFacts._cell_text'
    ' 保留同一数学内容及代码/链接叶子角色。pre_bodies'
    ' 供适配树（pre 被 HtmlFidelity 占位注释保护）还原格内代码正文。'
    import copy as _copy
    cells = {}
    codes = []
    row_no = 0
    for row in table.find_all('tr'):
        if row.find_parent('table') is not table:
            continue
        row_no += 1
        col_no = 0
        for cell in row.find_all(['td', 'th']):
            if cell.find_parent('table') is not table:
                continue
            col_no += 1
            copied = _copy.deepcopy(cell)
            for pre in copied.find_all('pre'):
                pre.decompose()  # 格内代码由 [TABLE-CODE] 表示，不入格文字
            math_values = []
            for math in copied.find_all('math') + copied.find_all(
                    class_='math'):
                if math.name == 'math':
                    alttext = math.get('alttext')
                    if alttext and alttext.strip():
                        body = alttext
                    else:
                        body = _strip_math_wrappers(
                            re.sub(r'\s+', ' ', math.get_text()).strip())
                else:
                    body = _strip_math_wrappers(
                        re.sub(r'\s+', ' ', math.get_text()).strip())
                math.replace_with('\x00TM%d\x00' % len(math_values))
                math_values.append('$' + body + '$')
            # Raw-source re-reading also protects literal TeX before ordinary
            # backslash escaping, using the existing code-aware text view.
            for run_text, segs in _unit_text_runs(copied):
                marks = []
                for span in scan_math(run_text).spans:
                    marks.append((span, '\x00TM%d\x00' % len(math_values)))
                    math_values.append(span.raw)
                _apply_literal_marks(segs, marks)
            # Reuse the mature leaf serializer; only ordinary text is normalized.
            text = HtmlFidelity().render_inline(copied, escape_backslashes=True)
            for index, value in enumerate(math_values):
                text = text.replace('\x00TM%d\x00' % index, value)
            cells[(row_no, col_no)] = (
                text, _span_value(cell, 'rowspan'),
                _span_value(cell, 'colspan'), len(cells) + 1)
            code_nodes = []
            for node in cell.descendants:
                if isinstance(node, Tag) and node.name == 'pre':
                    code_nodes.append(node)
                elif _PRE_PLACEHOLDER_RE.match(str(node).strip()):
                    code_nodes.append(node)
            for order, node in enumerate(code_nodes, start=1):
                if isinstance(node, Tag):
                    body = clean_code_html(
                        node.decode_contents()).rstrip('\n')
                else:
                    match = _PRE_PLACEHOLDER_RE.match(str(node).strip())
                    body = pre_bodies[int(match.group(1))].rstrip('\n')
                codes.append((row_no, col_no, order, body))
    return cells, codes


def _strip_math_wrappers(body):
    if (body.startswith('\\(') and body.endswith('\\)')) \
            or (body.startswith('\\[') and body.endswith('\\]')):
        return body[2:-2].strip()
    return body


def locate_table_mapping(table, table_id, mappings):
    '按 locate（table 序号或 table_id）在声明的逐表映射中找条目。'
    for entry in mappings or []:
        if not isinstance(entry, dict):
            continue
        locate = entry.get('locate') or {}
        if 'table' in locate and locate['table'] == table_id:
            return entry
        if 'table_id' in locate and locate['table_id'] is not None \
                and locate['table_id'] == (table.get('id') or None):
            return entry
    return None


def render_mapped_table(cells, codes, mapping_entry, *, gfm=False):
    '按人工裁决映射物化输出表（共享渲染：适配端输出与独立对账端预期'
    ' 由同一份 (cells, codes, mapping) 决定）。输出 [TABLE] 行表示、'
    ' 格内代码 [TABLE-CODE] 围栏与移出说明行；不复制逐格 schema 到'
    ' 来源依据，依据只保存 locate 与裁决引用（04-1）。'
    declared = {}
    cell_map = {}
    for cell in mapping_entry.get('cells') or []:
        if not isinstance(cell, dict):
            continue
        position = (cell.get('row'), cell.get('col'))
        declared[position] = cell
        cell_map[position] = cell
    out_cells = {}
    note_lines = []
    for position in sorted(cells):
        cell = cell_map.get(position)
        if cell is None:
            continue
        for target in cell.get('targets') or []:
            if not isinstance(target, dict):
                continue
            if 'table' in target:
                out_cells.setdefault(
                    (target.get('row'), target.get('col')), []).append(
                        (cells[position][3], cells[position][0]))
            elif 'note' in target:
                lines = target.get('note')
                if isinstance(lines, list) and len(lines) == 2:
                    note_lines.append((lines[0], cells[position][0]))
    lines = [] if gfm else ['[TABLE]']
    if out_cells:
        max_row = max(r for r, _c in out_cells)
        max_col = max(c for _r, c in out_cells)
        for row in range(1, max_row + 1):
            values = []
            for col in range(1, max_col + 1):
                parts = out_cells.get((row, col))
                if not parts:
                    values.append('')
                    continue
                ordered = [text for _order, text in sorted(parts)]
                values.append(' / '.join(ordered) if len(ordered) > 1
                              else ordered[0])
            # 行尾空白是末列空格位标记的一部分（与简单表 ' | ' 行表示同
            # 一合同），原样保留；文档末尾的首尾整理由 _serialize 区间算
            # 术吸收
            if gfm:
                lines.append('| ' + ' | '.join(v.replace('|', r'\|') for v in values) + ' |')
                if row == 1:
                    lines.append('| ' + ' | '.join('---' for _ in values) + ' |')
            else:
                lines.append(' | '.join(values) if max_col > 1 else values[0])
    for row_no, col_no, order, body in codes:
        cell = cell_map.get((row_no, col_no))
        has_target = cell is not None and any(
            isinstance(t, dict) and 'table' in t
            for t in (cell.get('targets') or []))
        if has_target:
            lines.append('')
            lines.append('[TABLE-CODE r=%d c=%d#%d]' % (row_no, col_no,
                                                        order))
            lines.append('```\n' + body + '\n```')
    if gfm and note_lines:
        lines.append('')
    for _start, text in sorted(note_lines):
        lines.append(text)
    return '\n'.join(lines), declared


# ---- 来源出现标记与精确区间（§7.11.4，ticket 19）----
#
# 每个受保护来源出现（MathML/遗留文本公式/字面公式/未解决公式节点）在
# 原 DOM 冻结后登记身份（node、内容类型、原内容、展开文本、所属章节），
# 并以唯一临时标记代替其 DOM 内容随既有行内/块渲染传递；最终写出时按
# 实际写入位置展开并算术累计精确区间。相同 TeX、宿主包含与内容反查均
# 不再充当出现身份或位置依据。

_MARK_FMT = '\x00K%d\x00'
_MARK_RE = re.compile('\x00K(\\d+)\x00')


class OccurrenceRegistry:
    """一次适配的来源出现注册表（私有内存数据，不写入依据文件）。

    occ 字段：node（出现身份）、kind、tex（依据口径：块级剥一层包装
    换行）、raw（实际展开文本——MathML/遗留为 math_wrap，字面上公式为
    原切片，未解决节点为序列化原文）、section、source
    （mathml/legacy/literal）、unresolved（原因或 None）、serialized。"""

    def __init__(self):
        self.occurrences = {}
        self._next = 0

    def add(self, occ):
        key = self._next
        self._next += 1
        self.occurrences[key] = occ
        return _MARK_FMT % key


def _is_marker_string(node):
    return isinstance(node, NavigableString) \
        and _MARK_RE.fullmatch(str(node)) is not None


def _unit_text_runs(unit):
    """内容单元的代码感知文字段：按文档序连接行内文字（跨行内标签直接
    连接，不加写空白）；代码/pre/script/style、MathML 与遗留公式容器
    子树以及已登记来源标记为硬屏障（公式定界不得跨越公式/代码语境），
    屏障之间的连续文字各自成段。返回 [(text, segs)]；segs 元素为
    (vstart, vend, node, nstart)——视图区间到文字节点的映射。"""
    if isinstance(unit, NavigableString):
        strings = [unit]
    else:
        strings = [n for n in unit.descendants
                   if isinstance(n, NavigableString)
                   and not isinstance(n, Comment)]

    def _barrier(node):
        if _is_marker_string(node):
            return True
        parent = node.parent
        while parent is not None and parent is not unit:
            if parent.name in ('code', 'pre', 'script', 'style', 'math'):
                return True
            if parent.name in ('span', 'div') \
                    and 'math' in (parent.get('class') or []):
                return True
            parent = parent.parent
        return False

    runs = []
    cur_text = []
    cur_segs = []
    pos = 0
    for node in strings:
        if _barrier(node):
            if cur_text:
                runs.append((''.join(cur_text), cur_segs))
            cur_text, cur_segs = [], []
            pos = 0
            continue
        text = str(node)
        cur_text.append(text)
        cur_segs.append((pos, pos + len(text), node, 0))
        pos += len(text)
    if cur_text:
        runs.append((''.join(cur_text), cur_segs))
    return runs


def _is_literal_unit(node):
    """字面数学识别的内容单元（进入行内序列化的最大元素）。"""
    name = node.name
    if name in ('p', 'figcaption', 'li', 'td', 'th', 'caption'):
        return True
    if _HEADING_RE.fullmatch(name):
        return True
    cls = node.get('class') or []
    if name == 'aside':
        return classify_block(node) == 'supported'
    if name == 'div':
        if any('listingline' in c for c in cls):
            return True
        if classify_block(node) == 'supported' and 'math' not in cls:
            return True
        if any('title' in c for c in cls) and node.find_parent(
                lambda t: isinstance(t, Tag)
                and classify_block(t) == 'algorithm') is not None:
            return True
    return False


def _literal_units(root):
    """字面识别单元（DOM 文档序）：内容单元元素 + 不被任何元素单元覆盖
    的直属文字串（容器直属文字按同一扫描口径，不孤立到单个文本节点之外
    的语境）。代码/pre/script/style 与公式子树内的文字、未支持容器的
    保留文字、表格/列表结构中的游离文字不做字面识别（代码不进数学；
    未支持容器保留原文；游离文字不进入既有渲染出口）。"""
    flat = list(root.descendants)
    position = {id(node): index for index, node in enumerate(flat)}
    # pre 祖先排除与 prepare_math_dom 同一口径：适配端 DOM 的 pre 已被
    # 占位注释整体替换（单元不存在），独立端 DOM 的 pre 完好，排除后两
    # 侧字面识别范围一致
    named = [node for node in root.find_all(True)
             if _is_literal_unit(node)
             and node.find_parent('pre') is None]
    named_ids = {id(node) for node in named}
    named = [node for node in named
             if node.find_parent(lambda t: id(t) in named_ids) is None]
    covered = set()
    for node in named:
        covered.add(id(node))
        for desc in node.descendants:
            covered.add(id(desc))
    units = list(named)

    def _excluded_string(node):
        parent = node.parent
        while parent is not None and parent is not root:
            if parent.name in ('pre', 'code', 'script', 'style', 'math'):
                return True
            if parent.name in ('table', 'ul', 'ol', 'dl'):
                return True
            if isinstance(parent, Tag) \
                    and classify_block(parent) == 'unsupported':
                return True
            parent = parent.parent
        return False

    for node in flat:
        if not isinstance(node, NavigableString) \
                or isinstance(node, Comment):
            continue
        if id(node) in covered or not str(node).strip():
            continue
        if _is_marker_string(node) or _excluded_string(node):
            continue
        units.append(node)
    units.sort(key=lambda node: position.get(id(node), len(position)))
    return units


def _apply_literal_marks(segs, marks):
    """把同一段文字视图上的全部跨度（(span, marker)，视图序、互不交叠）
    一次性映射回来源文字：按目标文字节点分组后逐节点一次重写（同节点
    多跨度不会命中已被摘除的旧节点）；跨节点跨度摘除中间节点。视图区间
    无法映射属内部错误。"""
    edits = {}  # id(node) -> [node, [(local_start, local_end, marker_or_None)]]
    for span, marker in marks:
        start, end = span.start, span.end
        first = last = None
        for seg in segs:
            vstart, vend, _node, _nstart = seg
            if first is None and vstart <= start < vend:
                first = seg
            if vstart < end <= vend:
                last = seg
        if first is None or last is None:
            raise ValueError('内部错误: 字面公式区间无法映射回来源文字')
        for seg in segs:
            vstart, vend, node, nstart = seg
            if vend <= start or vstart >= end:
                continue
            local_s = nstart + max(start - vstart, 0)
            local_e = nstart + min(end - vstart, vend - vstart)
            mark = marker if seg is first else None
            entry = edits.setdefault(id(node), [node, []])
            entry[1].append((local_s, local_e, mark))
    for _id, (node, ops) in edits.items():
        ops.sort()
        text = str(node)
        parts = []
        cursor = 0
        for local_s, local_e, mark in ops:
            parts.append(text[cursor:local_s])
            if mark is not None:
                parts.append(mark)
            cursor = local_e
        parts.append(text[cursor:])
        node.replace_with(NavigableString(''.join(parts)))


def mark_literal_occurrences(root, registry, base):
    """字面数学出现识别（§7.11.4）：先于普通空白整理，在完整内容单元
    的代码感知视图上按共享扫描默认边界识别字面公式，保留原符号与换行
    （未确认的跨行行内公式不取得识别资格）；出现身份接续 math 命名空间
    （math[base+k]，与 MathML/遗留节点序号无冲突），出现内容以唯一标记
    替换。返回诊断问题列表（未闭合/歧义定界），非空即不得生成候选。"""
    from _verification import scan_math
    problems = []
    ordinal = [base]
    for unit in _literal_units(root):
        for run_text, segs in _unit_text_runs(unit):
            scan = scan_math(run_text)
            for issue in scan.issues:
                problems.append(
                    '字面数学定界未解决 L%d %r: %s（跨行字面公式不在默认'
                    '边界内，D2）' % (issue.start_line, issue.raw,
                                     issue.reason))
            marks = []
            for span in scan.spans:
                ordinal[0] += 1
                tex = span.expr
                if span.kind == 'block' and tex.startswith('\n') \
                        and tex.endswith('\n'):
                    # 依据口径：块级剥一层包装换行（math_wrap 逆运算）
                    tex = tex[1:-1]
                # 章节归属锚定出现起始文字节点自身（宿主为标题时不错节，
                # 与 MathML 节点锚定自身同一口径，F4）
                anchor = None
                for seg in segs:
                    if seg[0] <= span.start < seg[1]:
                        anchor = seg[2]
                        break
                occ = {'node': 'math[%d]' % ordinal[0],
                       'content_type': 'math', 'kind': span.kind,
                       'tex': tex, 'raw': span.raw,
                       'section': section_of(root, anchor if anchor
                                             is not None else unit),
                       'source': 'literal', 'unresolved': None,
                       'serialized': None}
                marks.append((span, registry.add(occ)))
            if marks:
                _apply_literal_marks(segs, marks)
    return problems


def marked_text_frags(text, registry):
    """把含来源标记的文字拆成 ('t', 文字)/('m', kind, tex, node) 片段
    （独立端镜像构造：字面/MathML 出现各自成为有序片段，身份来自独立
    重建的注册表，不消费适配端标记表）；未解决出现还原为其写出文字
    （occ raw，与适配端写出同字节）。"""
    frags = []
    cursor = 0
    for match in _MARK_RE.finditer(text):
        occ = registry.occurrences[int(match.group(1))]
        if text[cursor:match.start()]:
            frags.append(('t', text[cursor:match.start()]))
        if occ['unresolved'] is not None:
            frags.append(('t', occ['raw']))
        else:
            frags.append(('m', occ['kind'], occ['tex'], occ['node']))
        cursor = match.end()
    if text[cursor:]:
        frags.append(('t', text[cursor:]))
    return frags


def has_marker(node):
    '子树是否含来源标记（决定宿主走逐字路径还是既有纯文字路径）。'
    for string in node.find_all(string=True):
        if _MARK_RE.search(str(string)):
            return True
    return False


def _expand_markers_inline(text, registry, table_math=False):
    """把文字中的来源标记展开为实际写出内容（仅用于登记进依据的记录
    文本——组成员行、式号等；输出中的标记仍由 _serialize 消费展开，
    两者按同一注册表展开，内容必然一致）。"""
    rows = markdown_table_row_lines(text) if table_math else set()
    def expand(match):
        raw = registry.occurrences[int(match.group(1))]['raw']
        return encode_table_math(raw) if text.count('\n', 0, match.start()) + 1 in rows else raw
    return _MARK_RE.sub(expand, text)


def plan_image_targets(root, substitutions=None):
    """全部图片出现的无冲突目标命名（05-2）：同名异资源（同 basename、
    不同源路径）保留目录前缀互不覆盖；获准替换的使用已确认产物名。
    返回 {id(img): 'images/<name>'}，适配端与独立对账端共用同一规划。"""
    by_base = {}
    imgs = []
    for img in root.find_all('img'):
        if img.find_parent('pre') is not None:
            continue
        src = img.get('src') or ''
        if not src:
            continue
        imgs.append(img)
        by_base.setdefault(src.rsplit('/', 1)[-1], {}).setdefault(
            src, []).append(img)
    targets = {}
    for basename, by_src in by_base.items():
        if len(by_src) > 1:
            for src, group in by_src.items():
                parent = src.rsplit('/', 1)[-2] if '/' in src else 'root'
                name = '%s--%s' % (parent.replace('/', '_'), basename)
                for img in group:
                    targets[id(img)] = 'images/%s' % name
        else:
            for group in by_src.values():
                for img in group:
                    targets[id(img)] = 'images/%s' % basename
    for entry in substitutions or []:
        if not isinstance(entry, dict):
            continue
        product = (entry.get('product') or {}).get('path')
        if not product:
            continue
        name = product.rsplit('/', 1)[-1]
        for img in imgs:
            if img.get('src') == entry.get('original_ref'):
                targets[id(img)] = 'images/%s' % name
    return targets


def validate_resource_substitutions(payload, snapshot_dir,
                                    identity_version=None):
    """resource_substitutions 合同核对（05-3/05-4）：逐项重读文件重算
    摘要——原引用真实缺失、PDF 同版本与页/区域、裁剪口径、产物身份与
    视觉/身份依据缺一不可；不以空摘要放行，不自动回退。返回问题列表。
    """
    problems = []
    entries = (payload or {}).get('resource_substitutions') or []
    if not entries:
        return problems
    for index, entry in enumerate(entries, start=1):
        label = '资源替换 #%d' % index
        if not isinstance(entry, dict):
            problems.append('%s 必须是对象' % label)
            continue
        original = entry.get('original_ref')
        if not isinstance(original, str) or not original:
            problems.append('%s 缺少 original_ref（原始引用）' % label)
            continue
        from _html_fidelity import resolve_snapshot_resource
        path, reason = resolve_snapshot_resource(original, snapshot_dir)
        if path is not None:
            problems.append('%s 的原资源 %s 实际可读（%s），不得按缺失'
                            '替换' % (label, original, path))
            continue
        missing_fact = entry.get('missing_fact')
        if not isinstance(missing_fact, str) or not missing_fact.strip():
            problems.append('%s 缺少真实缺失事实记录' % label)
        pdf = entry.get('pdf') or {}
        pdf_path = pdf.get('path')
        pdf_digest = pdf.get('sha256')
        if not pdf_path or not pdf_digest:
            problems.append('%s 缺少已确认 PDF 路径/摘要（缺必需摘要）'
                            % label)
        else:
            if not os.path.isfile(pdf_path):
                problems.append('%s 的 PDF 不可读: %s' % (label, pdf_path))
            else:
                actual = hashlib.sha256(
                    open(pdf_path, 'rb').read()).hexdigest()
                if actual != pdf_digest:
                    problems.append('%s 的 PDF 摘要不符（不同版本/错文件）: '
                                    '声明 %s… vs 实际 %s…'
                                    % (label, pdf_digest[:12],
                                       actual[:12]))
        pdf_version = pdf.get('version')
        if identity_version:
            if not pdf_version:
                problems.append('%s 未声明 PDF 版本（版本不明，不能宣称'
                                '同版本）' % label)
            elif pdf_version != identity_version:
                problems.append('%s 的 PDF 版本 %s 与论文实际版本 %s 不符'
                                '（不同版本不替换）'
                                % (label, pdf_version, identity_version))
        if not isinstance(entry.get('page'), int) or entry['page'] < 1:
            problems.append('%s 缺少合法页码（对应页/区域不明）' % label)
        rect = entry.get('rect')
        if not (isinstance(rect, list) and len(rect) == 4
                and all(isinstance(v, (int, float)) for v in rect)):
            problems.append('%s 缺少合法裁剪区域 rect' % label)
        crop = entry.get('crop') or {}
        if not isinstance(crop.get('basis'), str) or not crop['basis']:
            problems.append('%s 缺少裁剪口径依据' % label)
        product = entry.get('product') or {}
        product_path = product.get('path')
        product_digest = product.get('sha256')
        if not product_path or not product_digest:
            problems.append('%s 缺少替换产物路径/摘要' % label)
        elif not os.path.isfile(product_path):
            problems.append('%s 的替换产物不可读: %s'
                            % (label, product_path))
        else:
            actual = hashlib.sha256(
                open(product_path, 'rb').read()).hexdigest()
            if actual != product_digest:
                problems.append('%s 的替换产物摘要不符: 声明 %s… vs 实际 '
                                '%s…' % (label, product_digest[:12],
                                         actual[:12]))
        if not isinstance(entry.get('identity_basis'), str) \
                or not entry['identity_basis'].strip():
            problems.append('%s 缺少身份依据（依据不完整）' % label)
        if not isinstance(entry.get('visual_basis'), str) \
                or not entry['visual_basis'].strip():
            problems.append('%s 缺少视觉依据（图内文字/图例核对）' % label)
    return problems


def substitution_by_ref(payload):
    return {e.get('original_ref'): e for e in
            ((payload or {}).get('resource_substitutions') or [])
            if isinstance(e, dict)}


def listing_node_ids(root):
    "清单容器的稳定命名（文档序，跨进程可重算）。"
    listings = [n for n in root.find_all('div')
                if classify_block(n) == 'listing']
    return {id(node): 'listing[%d]' % ordinal
            for ordinal, node in enumerate(listings, start=1)}


def aside_node_ids(root):
    "纯文字 aside 段落的稳定命名（文档序，跨进程可重算）。"
    asides = [n for n in root.find_all('aside')
              if classify_block(n) == 'supported']
    return {id(node): 'aside[%d]' % ordinal
            for ordinal, node in enumerate(asides, start=1)}


def figure_node_ids(root):
    "图浮动体的稳定命名（文档序；嵌套子图同样命名，父关系由对账端独立重建）。"
    return {id(node): 'figure[%d]' % ordinal for ordinal, node in
            enumerate(root.find_all('figure'), start=1)}


def note_ref_label(node):
    "LaTeXML 脚注引用 → 真实目标标签（href 片段原样，不抽数字合并）。"
    href = node.get('href', '')
    if href.startswith('#') and len(href) > 1:
        return href[1:]
    return None


def prepare_notes_dom(root):
    """把脚注引用锚点换成 [^标签] 字面量（命名标签不抽数字合并），
    使行内序列化与既有脚注消费口径一致。"""
    labels = []
    for anchor in root.find_all('a'):
        cls = anchor.get('class') or []
        if not any('note_ref' in c for c in cls):
            continue
        label = note_ref_label(anchor)
        if label is None:
            continue
        labels.append(label)
        anchor.replace_with(NavigableString('[^%s]' % label))
    return labels


def scan_context_from_payload(payload):
    """来源依据的公式对应 → 共享扫描上下文（通过原始对账后的消费端）。"""
    from _verification import SourceMathContext
    entries = []
    for corr in (payload or {}).get('correspondences') or []:
        if not isinstance(corr, dict) or corr.get('content_type') != 'math':
            continue
        tex = corr.get('tex') or ''
        if corr.get('kind') == 'inline' \
                and (tex != tex.strip() or '\n' in tex):
            entries.append((tex, corr.get('section') or 0))
    return SourceMathContext(entries)


def container_node_ids(root):
    """未支持内容容器的稳定命名（文档序，跨进程可重算）。"""
    unsupported = [n for n in root.find_all(True)
                   if classify_block(n) == 'unsupported']
    return {id(node): '%s#%d' % (node.name, ordinal)
            for ordinal, node in enumerate(unsupported, start=1)}


def paragraph_div_ids(root):
    """无块内容 div（段落化输出）的稳定命名（文档序，跨进程可重算）。"""
    divs = [n for n in root.find_all('div')
            if classify_block(n) == 'supported'
            and 'math' not in (n.get('class') or [])]
    return {id(node): 'divp[%d]' % ordinal
            for ordinal, node in enumerate(divs, start=1)}


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def adapter_identity():
    """适配器/合同实现的身份（check_policy 与 checker 依赖同一口径）。"""
    return sha256_text(open(os.path.abspath(__file__),
                            encoding='utf-8').read())


def load_adaptation(path):
    """读取并结构性校验来源依据文件；无效时抛出带定位的 ValueError。"""
    try:
        with open(path, encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError('来源依据不可读: %s（%s）' % (path, exc))
    problems = validate_adaptation(payload)
    if problems:
        raise ValueError('来源依据无效: %s: %s'
                         % (path, '；'.join(problems)))
    return payload


def validate_adaptation(payload, raw_html=None, snapshot_path=None):
    """校验来源依据合同；返回问题列表（空 = 通过）。

    raw_html 提供时独立重算快照摘要并与声明核对，同时核对实际题名出现在
    快照可见内容中（不只信 H1/文件名）；snapshot_path 提供时核对声明快照
    位置与实际文件为同一 realpath。缺必需身份字段、摘要或确认依据即返回
    问题，由调用方阻止分派/完整交付。
    """
    problems = []
    if not isinstance(payload, dict):
        return ['依据必须是 JSON 对象']
    if payload.get('version') != ADAPTATION_VERSION:
        problems.append('version 必须是 %d（实际 %r）'
                        % (ADAPTATION_VERSION, payload.get('version')))
    if payload.get('format') != ADAPTATION_FORMAT:
        problems.append('format 必须是 %r（实际 %r）'
                        % (ADAPTATION_FORMAT, payload.get('format')))
    identity = payload.get('paper_identity')
    if not isinstance(identity, dict):
        problems.append('缺少 paper_identity（预期/实际题名、论文 ID、'
                        '实际版本、最终 URL、取得时间与确认依据）')
        identity = {}
    for field in IDENTITY_FIELDS:
        value = identity.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append('paper_identity.%s 缺失或为空（缺独立确认依据）'
                            % field)
    if identity.get('expected_title') and identity.get('actual_title') \
            and identity['expected_title'].strip() \
            != identity['actual_title'].strip():
        problems.append('预期题名 %r 与实际题名 %r 不符（身份错配）'
                        % (identity['expected_title'],
                           identity['actual_title']))
    snapshot = payload.get('snapshot')
    if not isinstance(snapshot, dict) or not snapshot.get('sha256'):
        problems.append('缺少 snapshot.sha256（消费者无法独立核对摘要）')
        snapshot = {}
    if snapshot.get('path') and snapshot_path is not None:
        declared = os.path.realpath(snapshot['path'])
        if declared != os.path.realpath(snapshot_path):
            problems.append('声明快照 %s 与实际输入 %s 不是同一文件'
                            % (snapshot['path'], snapshot_path))
    if raw_html is not None and snapshot.get('sha256'):
        actual = sha256_text(raw_html)
        if actual != snapshot['sha256']:
            problems.append('快照摘要不符: 依据 %s vs 实际 %s（原始快照'
                            '已变化，不得追认）'
                            % (snapshot['sha256'][:12], actual[:12]))
    if raw_html is not None and identity.get('actual_title'):
        visible = BeautifulSoup(raw_html, 'html.parser').get_text(' ')
        if identity['actual_title'].strip() not in re.sub(
                r'\s+', ' ', visible):
            problems.append('实际题名 %r 未出现在快照可见内容中'
                            '（身份错配，不只信 H1/文件名）'
                            % identity['actual_title'])
    return problems


def adjudicated_tex(decisions):
    """从裁决记录提取主 Agent 回源补齐的公式 TeX：{node: (tex, basis)}。

    decisions 仅记录具体裁决（原位置、依据与结果）；无 TeX 的公式由主
    Agent 独立回源确认后在此登记，适配器据此转换，不猜写。
    """
    out = {}
    for decision in decisions or []:
        if not isinstance(decision, dict):
            continue
        node = decision.get('node')
        tex = decision.get('tex')
        basis = decision.get('basis')
        if isinstance(node, str) and isinstance(tex, str) and tex.strip() \
                and isinstance(basis, str) and basis.strip():
            out[node] = (tex, basis)
    return out


def math_node_kind(node):
    """行内/展示类型由节点自身 display 属性与已确认容器共同决定。

    返回 (kind, conflict_reason)；冲突时 kind 为 None，逐节点进
    unresolved，不能从是否含换行猜类型。
    """
    display = (node.get('display') or '').strip().lower() \
        if node.name == 'math' else ''

    def _holder(names, tag):
        return node.find_parent(lambda t: isinstance(t, Tag)
                                and t.name == tag
                                and any(c in ('math', 'equation')
                                        for c in (t.get('class') or []))
                                ) if tag in names else None

    block_holder = node.find_parent(lambda t: isinstance(t, Tag)
                                    and t.name in ('div', 'table')
                                    and any(c in ('math', 'equation')
                                            for c in (t.get('class') or [])))
    inline_holder = node.find_parent(lambda t: isinstance(t, Tag)
                                     and t.name == 'span'
                                     and 'math' in (t.get('class') or []))
    if display == 'block' and inline_holder is not None:
        return None, 'display=block 与行内容器（span.math）冲突'
    if display == 'inline' and block_holder is not None:
        return None, 'display=inline 与块级容器（div/table.math）冲突'
    if display == 'block' or block_holder is not None:
        return 'block', None
    return 'inline', None


def math_wrap(kind, tex):
    """已确认定界转换：行内 $…$；展示 $$\n…\n$$（新增包装换行属于
    定界，与原表达式内换行范围分明，独立对账逐字核对）。"""
    return '$%s$' % tex if kind == 'inline' else '$$\n%s\n$$' % tex


def _raw_conversion(kind, raw):
    """从实际写出 raw 派生定界事实（§7.11/24：字面块级单行 $$…$$ 无包装
    换行，登记必须与写出一致，消费端按登记形式逐字重建候选）。"""
    delimiter = '$$' if raw.startswith('$$') else '$'
    wrap_newline = kind == 'block' and raw.startswith(delimiter + '\n')
    return {'delimiter': delimiter, 'wrap_newline': wrap_newline}


def corr_written_raw(corr):
    """按依据登记的定界事实重建候选写出形式（缺登记字段的旧手工依据
    回退 math_wrap 默认口径）。"""
    kind = corr.get('kind')
    conv = corr.get('conversion') or {}
    delimiter = conv.get('delimiter') or ('$' if kind == 'inline'
                                          else '$$')
    tex = corr.get('tex') or ''
    if kind == 'block' and conv.get('wrap_newline', True):
        return '%s\n%s\n%s' % (delimiter, tex, delimiter)
    return '%s%s%s' % (delimiter, tex, delimiter)


def _heading_ordinals(root):
    flat = list(root.descendants)
    index = {id(node): i for i, node in enumerate(flat)}
    ordinals = {idx: ordinal + 1 for ordinal, idx in enumerate(
        i for i, node in enumerate(flat)
        if isinstance(node, Tag) and _HEADING_RE.fullmatch(node.name))}
    return flat, index, ordinals


def section_of(root, node):
    """节点所属章节 = 最后一个位于其之前的标题序号（0 = 前置区）。"""
    flat, index, ordinals = _heading_ordinals(root)
    idx = index.get(id(node))
    if idx is None:
        return 0
    section = -1
    for h_idx in ordinals:
        if h_idx < idx and h_idx > section:
            section = h_idx
    return ordinals.get(section, 0)


def _math_ordinal_map(root):
    # pre 内的数学节点不参与命名：适配端 DOM 的 pre 已被占位注释整体
    # 替换（节点不存在），独立端按同一口径排除，两侧 math[k] 命名一致
    return {id(node): 'math[%d]' % ordinal for ordinal, node in
            enumerate((n for n in root.find_all('math')
                       if n.find_parent('pre') is None), start=1)}


def prepare_math_dom(root, decisions, registry):
    """在原 DOM 上识别全部公式出现（MathML 与遗留 span/div.math 文本公
    式），登记身份后以唯一临时标记替换原节点内容随序列化传递（§7.11.4，
    ticket 19）；返回逐节点适配记录。

    无 alttext/空 TeX/类型冲突的节点不猜写、不删除：出现以标记携带，
    写出时逐字展开为原节点序列化内容，记录 unresolved 原因。返回记录：
    {'node', 'ordinal', 'kind', 'tex', 'unresolved', 'serialized'}。
    """
    adjudicated = adjudicated_tex(decisions)
    # pre 内的数学节点不属于正文事实：适配端 DOM 的 pre 已被占位注释
    # 整体替换（节点不存在），独立端按同一口径排除，两侧命名一致
    ids = _math_ordinal_map(root)
    records = []
    for node in list(root.find_all('math')):
        if node.find_parent('pre') is not None:
            continue
        node_id = ids[id(node)]
        alttext = node.get('alttext')
        has_tex = isinstance(alttext, str) and alttext.strip()
        kind, conflict = math_node_kind(node)
        # 原 TeX 逐字保持（02-1/D2）：展示与行内均保留 alttext 首尾
        # 空白与换行，不做任何 strip
        if has_tex:
            tex = alttext
        else:
            tex = adjudicated.get(node_id, (None,))[0]
        record = {'node': node_id, 'ordinal': None, 'kind': kind,
                  'tex': tex, 'unresolved': None, 'serialized': None,
                  'section': section_of(root, node)}
        if conflict is not None:
            record['unresolved'] = conflict
        elif tex is None:
            record['unresolved'] = '无 TeX（缺 alttext 且无回源裁决）'
        if record['unresolved'] is not None:
            # 保留原节点序列化内容（不猜写、不丢弃），定位由标记展开给出
            record['serialized'] = str(node)
        records.append(record)
        marker = registry.add(
            {'node': node_id, 'content_type': 'math',
             'kind': kind if record['unresolved'] is None else None,
             'tex': tex if record['unresolved'] is None else None,
             'raw': (math_wrap(kind, tex)
                     if record['unresolved'] is None
                     else record['serialized']),
             'section': record['section'], 'source': 'mathml',
             'unresolved': record['unresolved'],
             'serialized': record['serialized'],
             'table_host': node.find_parent('table')})
        node.replace_with(NavigableString(marker))
    # legacy span.math / div.math（不含 MathML 子树的文本公式）：逐字节取
    # 文本（行内按行内格式空白序列化口径），同样逐节点登记并以标记替换；
    # pre 内节点同 MathML 口径排除（适配端 DOM 无此节点）
    legacy = [n for n in root.find_all(['span', 'div'], class_='math')
              if n.find('math') is None
              and n.find_parent('pre') is None]
    for ordinal, node in enumerate(legacy, start=1):
        node_id = '%s.math[%d]' % (node.name, ordinal)
        kind = 'block' if node.name == 'div' else 'inline'
        raw = node.get_text()
        if kind == 'inline':
            body = raw.strip()
            if body.startswith('\\(') and body.endswith('\\)'):
                body = body[2:-2].strip()
            if body.startswith('\\[') and body.endswith('\\]'):
                body = body[2:-2].strip()
            tex = re.sub(r'\s+', ' ', body)
        else:
            # 与渲染端 div.math 口径一致（get_text(' ', strip=True)）
            tex = node.get_text(' ', strip=True)
        record = {'node': node_id, 'ordinal': None, 'kind': kind,
                  'tex': tex or None, 'unresolved': None,
                  'serialized': None,
                  'section': section_of(root, node)}
        if not tex:
            record['unresolved'] = '空 TeX（文本公式节点无内容）'
            record['serialized'] = raw
        records.append(record)
        marker = registry.add(
            {'node': node_id, 'content_type': 'math',
             'kind': kind if record['unresolved'] is None else None,
             'tex': tex or None,
             'raw': math_wrap(kind, tex) if tex else raw,
             'section': record['section'], 'source': 'legacy',
             'unresolved': record['unresolved'],
             'serialized': record['serialized'],
             'table_host': node.find_parent('table')})
        node.replace_with(NavigableString(marker))
    return records


class _Emission(object):
    """一次 Markdown 输出片段及其来源节点元数据。"""

    __slots__ = ('text', 'meta')

    def __init__(self, text, meta):
        self.text = text
        self.meta = meta


class _Piece(object):
    """标记展开后的最终写出片段（一个发射可拆成多个写出片段）。"""

    __slots__ = ('text', 'meta', 'is_block', 'marks')

    def __init__(self, text, meta, is_block, marks):
        self.text = text
        self.meta = meta
        self.is_block = is_block
        # marks: [(occ_key, start, end)]，相对 text 的字符区间
        self.marks = marks


class LatexmlAdapter(object):
    """LaTeXML 原节点适配器（01 最小范围、02 数学、03 浮动体/脚注、
    04 表格逐格）；未支持的内容性容器保留为 [TAGNAME] 文字并登记
    unresolved，不静默丢弃。"""

    def __init__(self, fidelity, decisions, table_conversions=None,
                 resource_substitutions=None):
        self.fidelity = fidelity
        self.decisions = decisions or []
        self.table_conversions = table_conversions
        self.resource_substitutions = resource_substitutions or []
        self.unresolved_containers = []
        self._fig_ctx = []

    def adapt(self, raw_html, section_id):
        fidelity = self.fidelity
        soup = fidelity.parse(raw_html)
        if section_id:
            root = soup.find(id=section_id)
            if root is None:
                raise ValueError('section id not found: %s' % section_id)
        else:
            root = (soup.find('article') or soup.find('main')
                    or soup.find('body'))
        if root is None:
            raise ValueError('no <article>/<main>/<body> found')
        self.root = root
        # 节点命名在所有 DOM 变更前按原始文档序计算，与独立对账端口径一致
        self._p_ordinals = {id(n): 'p[%d]' % i for i, n in
                            enumerate(root.find_all('p'), start=1)}
        h_counts = {}
        self._h_ordinals = {}
        for node in root.find_all(_HEADING_RE):
            h_counts[node.name] = h_counts.get(node.name, 0) + 1
            self._h_ordinals[id(node)] = '%s[%d]' % (
                node.name, h_counts[node.name])
        self._figcaption_ordinals = {
            id(n): 'figcaption[%d]' % i for i, n in
            enumerate(root.find_all('figcaption'), start=1)}
        self._img_ordinals = {}
        ordinal = 0
        for img in root.find_all('img'):
            if img.find_parent('pre') is not None:
                continue
            ordinal += 1
            self._img_ordinals[id(img)] = 'img[%d]' % ordinal
        self._container_ids = container_node_ids(root)
        self._paragraph_div_ids = paragraph_div_ids(root)
        self._group_ids = group_node_ids(root)
        self._figure_ids = figure_node_ids(root)
        self._aside_ids = aside_node_ids(root)
        self._table_ids = table_node_ids(root)
        self._listing_ids = listing_node_ids(root)
        self._image_targets = plan_image_targets(
            root, (getattr(self, 'resource_substitutions', None) or []))
        self.decision_results = []
        self._apply_decisions(root)
        # 来源出现身份先于输出：全部公式出现登记后以唯一标记替换（§7.11.4）
        self.registry = OccurrenceRegistry()
        self.math_records = prepare_math_dom(root, self.decisions,
                                             self.registry)
        literal_problems = mark_literal_occurrences(
            root, self.registry, base=len(self.math_records))
        if literal_problems:
            raise ValueError('字面数学定界未解决（不折叠取得资格，D2）:\n'
                             + '\n'.join(literal_problems))
        self.groups = []
        self.emissions = []
        self._note_labels = prepare_notes_dom(root)
        self._walk(root)
        md_text, ranges, occ_ranges = self._serialize()
        correspondences, unresolved = self._records(ranges, md_text,
                                                    occ_ranges)
        self._annotate_groups(correspondences)
        return md_text, correspondences, unresolved

    def _annotate_groups(self, correspondences):
        """把组/成员序标注到成员公式对应上，供对账与 check_policy 投影。"""
        by_node = {}
        for corr in correspondences:
            if corr.get('content_type') == 'math':
                by_node[corr['node']] = corr
        for group in self.groups:
            for index, member in enumerate(group['members']):
                corr = by_node.get(member)
                if corr is not None:
                    corr['group'] = group['node']
                    corr['group_index'] = index

    # ---- 输出拼接与字符区间（§7.11.4：标记展开 + 算术累计，不回查） ----

    # 块级出现可拆分为独立块片段的宿主（前后文字各自成片，与图片拆段
    # 同一字节布局规则）；保留文字宿主（_unsupported_container）经
    # _no_split 保持行内语境，块级出现在其中按目标原因 fail-fast。
    _SPLITTABLE_TYPES = frozenset({'paragraph', 'listing', 'math-group'})

    def _expand_emission(self, emission, consumed):
        """展开一个输出片段内的来源标记，返回 [_Piece]。

        行内出现就地展开为 raw（MathML/遗留为 math_wrap，字面为源切片
        逐字，未解决为序列化原文）；块级出现在可拆宿主中拆为独立块片段
        （前后文字各自成片）；表格格位语境为单行（字面块级逐字留在格内，
        与既有已批准表示一致；MathML/遗留块级入格现状即拒绝，ticket 21
        前不新增降级形态）；其余宿主块级 fail-fast（现状为内部错误或误
        拒，改为明确诊断）。每个标记必须恰好展开一次。"""
        text = emission.text
        meta = emission.meta
        matches = list(_MARK_RE.finditer(text))
        table_rows = markdown_table_row_lines(text) if meta and meta.get('type') == 'footnote-def' else set()
        if not matches:
            return [_Piece(text, meta, False, [])]
        for match in matches:
            occ = self.registry.occurrences[int(match.group(1))]
            if occ['unresolved'] is None and occ['kind'] == 'block' \
                    and not self._split_allowed(meta):
                if meta is not None and meta.get('type') == 'table' \
                        and occ['source'] == 'literal':
                    continue  # 字面块级逐字留在格内（既有格位表示）
                raise ValueError(
                    '块级公式出现 %s 落在不可拆宿主（%s）中，无法形成'
                    '可回查的块级输出' % (
                        occ['node'],
                        meta.get('type') if meta else '无元数据'))
        pieces = []
        cur_text = []
        cur_marks = []
        cursor = 0
        did_split = False

        def cur_len():
            return sum(len(part) for part in cur_text)

        def close_piece():
            """收尾当前文字片段；块级拆出的文字片段与图片拆段同一字
            节约定（strip + '\\n' 前缀，标记随内容平移不被裁切）。"""
            content = ''.join(cur_text)
            if not content.strip():
                return
            lead_ws = len(content) - len(content.lstrip())
            text_out = '\n' + content.strip()
            shift = 1 - lead_ws
            pieces.append(_Piece(
                text_out, meta, False,
                [(k, s + shift, e + shift) for k, s, e in cur_marks]))

        for match in matches:
            key = int(match.group(1))
            occ = self.registry.occurrences[key]
            if key in consumed:
                raise ValueError('内部错误: 来源标记 %s（%s）被重复展开'
                                 % (match.group(0), occ['node']))
            consumed.add(key)
            front = text[cursor:match.start()]
            if occ['unresolved'] is None and occ['kind'] == 'block' \
                    and self._split_allowed(meta):
                did_split = True
                cur_text.append(front)
                close_piece()
                cur_text, cur_marks = [], []
                pieces.append(_Piece('\n' + occ['raw'], meta, True,
                                     [(key, 1, 1 + len(occ['raw']))]))
            else:
                cur_text.append(front)
                start = cur_len()
                raw = occ['raw']
                if text.count('\n', 0, match.start()) + 1 in table_rows:
                    raw = encode_table_math(raw)
                cur_text.append(raw)
                cur_marks.append((key, start, start + len(raw)))
            cursor = match.end()
        cur_text.append(text[cursor:])
        if did_split:
            close_piece()
        else:
            pieces.append(_Piece(''.join(cur_text), meta, False,
                                 cur_marks))
        return pieces

    def _split_allowed(self, meta):
        if meta is None:
            return True
        if meta.get('_no_split'):
            return False
        return meta.get('type') in self._SPLITTABLE_TYPES

    def _serialize(self):
        """最终写出：标记展开为精确内容，拼接按算术累计字符区间
        （禁止按内容反查）；首尾排版整理只裁普通空白，裁到标记即内部
        错误。返回 (md_text, piece_ranges, occ_ranges)。"""
        consumed = set()
        pieces = []
        for emission in self.emissions:
            pieces.extend(self._expand_emission(emission, consumed))
        missing = [k for k in self.registry.occurrences if k not in consumed]
        if missing:
            raise ValueError('内部错误: 来源出现未写入输出: %s'
                             % ', '.join(self.registry.occurrences[k]['node']
                                        for k in missing[:5]))
        joined = '\n'.join(p.text for p in pieces)
        lead = len(joined) - len(joined.lstrip())
        trail = len(joined.rstrip())
        if _MARK_RE.search(joined[:lead]) or _MARK_RE.search(joined[trail:]):
            raise ValueError('内部错误: 首尾排版整理裁到了来源标记')
        base = joined.strip()
        md_text = base + '\n'
        if _MARK_RE.search(md_text):
            raise ValueError('内部错误: 来源标记残留于最终输出')
        ranges = []
        occ_ranges = {}
        cursor = 0
        for piece in pieces:
            needle = piece.text.strip('\n')
            local = len(piece.text) - len(piece.text.lstrip('\n'))
            start = cursor + local - lead
            end = start + len(needle)
            if end > len(base):
                # 末片段尾部的普通空白被首尾整理裁掉（上方已守卫裁不到标
                # 记）：对应区间收缩到实际保留的内容
                clipped = len(base) - start
                if clipped < 0 or base[start:] != needle[:clipped] \
                        or needle[clipped:].strip():
                    raise ValueError(
                        '内部错误: 片段区间算术与最终输出不符: %r'
                        % needle[:40])
                end = len(base)
            elif base[start:end] != needle:
                raise ValueError('内部错误: 片段区间算术与最终输出不符: %r'
                                 % needle[:40])
            ranges.append((start, end))
            for key, mstart, mend in piece.marks:
                occ_ranges[key] = (cursor + mstart - lead,
                                   cursor + mend - lead)
            cursor += len(piece.text) + 1
        self._pieces = pieces
        return md_text, ranges, occ_ranges

    def _records(self, ranges, md_text, occ_ranges):
        correspondences = []
        unresolved = []
        # 同一来源节点的多个写出片段合并为单一覆盖区间（图片/块级拆段；
        # 父范围可以覆盖内部图片或展示公式，但不代替叶子的精确对应）。
        # 零宽片段（空清单行等无实际字节的写出）不扩展覆盖区间：声明范围
        # 是实际内容区间，与独立对齐口径一致（复评 F1）
        merged = {}
        order = []
        for piece, (start, end) in zip(self._pieces, ranges):
            meta = piece.meta
            if meta is None or meta.get('node') is None:
                continue
            if start == end:
                continue
            key = (meta.get('type'), meta['node'])
            if key in merged:
                bound = merged[key]
                bound[0] = min(bound[0], start)
                bound[1] = max(bound[1], end)
            else:
                merged[key] = [start, end, meta]
                order.append(key)
        for key in order:
            start, end, meta = merged[key]
            ctype, _node = key
            if ctype == 'paragraph':
                # 段落事实登记口径（与独立端一致）：宿主片段全部为块级
                # 公式时无正文事实（块级公式是独立成块的数学片段）
                node_pieces = [p for p in self._pieces
                               if p.meta is not None
                               and (p.meta.get('type'), p.meta.get('node'))
                               == key]
                if all(p.is_block for p in node_pieces):
                    continue
            entry = {k: v for k, v in meta.items()
                     if not k.startswith('_')}
            entry['content_type'] = entry.pop('type', None)
            entry['md_start'] = start
            entry['md_end'] = end
            if entry.pop('kind_marker', None) == 'unresolved-container':
                # preserved 与 md 范围坐标一致（范围不含片段首尾换行）
                entry['preserved'] = md_text[start:end]
                unresolved.append(entry)
            else:
                correspondences.append(entry)
        # 公式出现对应：直接由标记展开的实际写入区间产生（身份先于输
        # 出，位置随生成传递；不扫描成品、不按同文本挑选）
        math_corrs = []
        for key, (start, end) in sorted(occ_ranges.items(),
                                        key=lambda kv: kv[1]):
            occ = self.registry.occurrences[key]
            if occ['unresolved'] is not None:
                unresolved.append({
                    'node': occ['node'], 'content_type': 'math',
                    'section': occ['section'],
                    'md_start': start, 'md_end': end,
                    'reason': occ['unresolved'],
                    'preserved': occ['serialized']})
                continue
            math_corrs.append({
                'node': occ['node'],
                'content_type': 'math',
                'section': occ['section'],
                'md_start': start,
                'md_end': end,
                'conversion': _raw_conversion(occ['kind'], occ['raw']),
                'kind': occ['kind'],
                'tex': occ['tex'],
            })
        correspondences.extend(math_corrs)
        return correspondences, unresolved

    # ---- 原节点遍历（直接子节点源序，每个内容节点只消费一次） ----

    def _emit(self, text, meta=None):
        self.emissions.append(_Emission(text, meta))

    def _walk(self, node):
        for child in node.children:
            self._dispatch_child(child, node)

    def _dispatch_child(self, child, parent):
        """分派单个子节点（含本节点自身的角色判定）；parent 为直属文字
        的章节归属上下文。算法等容器对直属子节点必须调用本方法分派，
        不能 walk 进子节点内部而跳过其角色（§7.11.5：直属 p/pre/table
        与透明包装后同型内容保持各自语义）。"""
        fidelity = self.fidelity
        fenced = fidelity.fenced_pre(child)
        if fenced is not None:
            self._emit(fenced, {'type': 'code', 'node': None})
            return
        if isinstance(child, str):
            # 容器直属文字（含公式出现标记替换后的遗留公式位置）照常
            # 输出；块级标记在写出时拆段
            if child.strip():
                self._emit('\n' + child.strip(), {
                    'type': 'paragraph', 'node': None,
                    'section': section_of(self.root, parent)})
            return
        if not isinstance(child, Tag):
            return
        name = child.name
        cls = ' '.join(child.get('class') or [])
        if _HEADING_RE.fullmatch(name):
            text = fidelity.clean_heading(fidelity.heading_text(
                child, escape_backslashes=True))
            self._emit('\n' + fidelity.heading_line(
                int(name[1]), text), {
                'type': 'heading', 'node': self._h_ordinals[id(child)],
                'section': section_of(self.root, child),
                'level': int(name[1])})
        elif name == 'p':
            self._paragraph_host(child, {
                'type': 'paragraph',
                'section': section_of(self.root, child),
                'node': self._p_ordinals.get(id(child), 'p[?]')})
        elif name == 'pre':
            self._emit('\n```\n' + child.get_text().rstrip('\n')
                       + '\n```', {'type': 'code', 'node': None})
        elif name == 'img':
            ctx = self._fig_ctx[-1] if self._fig_ctx else (None, None)
            self._image(child, ctx[0], ctx[1])
        elif name == 'figcaption':
            ctx = self._fig_ctx[-1] if self._fig_ctx else (None, None)
            self._figure_caption(child, ctx[0], ctx[1])
        elif name == 'figure':
            self._figure(child)
        elif classify_block(child) == 'table-simple':
            self._table_simple(child)
        elif classify_block(child) == 'table-complex':
            self._table_complex(child)
        elif classify_block(child) == 'math-group':
            self._math_group(child)
        elif classify_block(child) == 'biblist':
            self._biblist(child)
        elif classify_block(child) == 'itemize':
            self._itemize(child)
        elif classify_block(child) == 'listing':
            self._listing(child)
        elif classify_block(child) == 'algorithm':
            self._algorithm(child)
        elif classify_block(child) == 'footnote-def':
            self._footnote_def(child)
        elif name == 'aside':
            self._paragraph_host(child, {
                'type': 'paragraph',
                'section': section_of(self.root, child),
                'node': self._aside_ids.get(id(child))})
        elif name == 'blockquote' or (
                name in ('div', 'section', 'article', 'main')):
            if name == 'div' and not contains_block_content(
                    child, ['p', 'ul', 'ol', 'table', 'dl', 'div',
                            'section', 'h1', 'h2', 'h3', 'h4', 'h5',
                            'h6', 'figure', 'blockquote']):
                self._paragraph_host(child, {
                    'type': 'paragraph',
                    'section': section_of(self.root, child),
                    'node': self._paragraph_div_ids.get(id(child))})
            else:
                self._walk(child)
        elif name in _SKIP_TAGS:
            return
        elif classify_block(child) == 'unsupported':
            # 未支持的内容性容器（列表/表格/脚注等后续 ticket 范围）：
            # 保留为 [TAGNAME] 文字并登记 unresolved，不静默丢弃
            self._unsupported_container(child)
        else:
            self._walk(child)

    def _paragraph_host(self, child, meta):
        """段落宿主（p/div/aside）：行内图片在源位置成为独立 [IMG] 块行
        （08，不静默丢弃），前后文字各自成段并按文档序与图片交错输出；
        图片归属当前图上下文。图片-only 宿主（如图面板 flex 单元）只输出
        [IMG] 行，不产生空段落。拆出的文字片段保留宿主节点身份，对应区间
        在记录阶段合并为覆盖范围（§7.11.4：父范围不代替叶子精确对应）。"""
        imgs = [img for img in child.find_all('img')
                if img.find_parent('pre') is None and img.get('src')]
        if not imgs:
            # 按阅读语义加写原文字面反斜线与强调定界（复评 S1：裸 `*`/`_`
            # 会在真实阅读中丢字符），使实际阅读与原文字面一致
            text = self.fidelity.paragraph_text(child,
                                                escape_backslashes=True)
            if text:
                self._emit('\n' + text, meta)
            return
        import copy as _copy
        copied = _copy.deepcopy(child)
        copied_imgs = [img for img in copied.find_all('img')
                       if img.find_parent('pre') is None
                       and img.get('src')]
        for index, img in enumerate(copied_imgs):
            img.replace_with(NavigableString('\x01%d\x01' % index))
        text = self.fidelity.paragraph_text(copied, escape_backslashes=True)
        ctx = self._fig_ctx[-1] if self._fig_ctx else (None, None)
        pieces = re.split(r'\x01(\d+)\x01', text)
        for position, piece in enumerate(pieces):
            if position % 2 == 1:
                self._image(imgs[int(piece)], ctx[0], ctx[1])
            elif piece.strip():
                self._emit('\n' + piece.strip(), meta)

    def _math_group(self, node):
        """公式组/式号容器：行内容格按源序空格拼接为行（含来源标记），
        成员 = 行内已解决公式出现的身份（文档序，不扫描成品、不按同文
        本挑选）；无公式行按行登记（字面 TeX 等式行保持现状）。块级出
        现由写出阶段拆为独立块片段（与现状逐式一行字节一致）；式号官
        方文字保留为相邻文字（可含引用目标），不往 TeX 插 \tag；组关
        系、成员序与式号登记进来源依据（记录文本展开标记，不含内部记
        号）。"""
        gid = self._group_ids.get(id(node))
        if gid is None:
            self._unsupported_container(node)
            return
        if node.name == 'table':
            rows = [node]
        else:
            rows = [c for c in node.children
                    if isinstance(c, Tag)
                    and classify_block(c) == 'math-group']
            if not rows:
                rows = [node]
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
                row_occs = [self.registry.occurrences[int(m.group(1))]
                            for m in _MARK_RE.finditer(line)]
                resolved = [o for o in row_occs if o['unresolved'] is None]
                if resolved and all(o['source'] == 'literal'
                                    for o in resolved):
                    # 纯字面行（无 MathML 快照，08）：组关系按行登记，
                    # 记录文本展开标记（不含内部记号）
                    members.append(
                        _expand_markers_inline(line, self.registry))
                elif resolved:
                    # 含 MathML/遗留节点的行：成员 = 已解决出现身份
                    # （文档序，不扫描成品、不按同文本挑选）
                    members.extend(o['node'] for o in resolved)
                else:
                    members.append(
                        _expand_markers_inline(line, self.registry))
                # 写出文字按阅读语义加写原文字面反斜线与强调定界（复评
                # S1）；组关系记录保持未加写的原文字面
                self._emit('\n' + escape_text_backslashes(line), {
                    'type': 'math-group', 'node': gid,
                    'section': section_of(self.root, node)})
            for td in row.find_all('td'):
                tcls = td.get('class') or []
                if not any('eqno' in c for c in tcls):
                    continue
                # 式号官方文字：元素级拼接 + 排版紧排，与独立对账端
                # _norm_text 口径一致（空格差异不构成式号差异）
                text = re.sub(r'\s+', ' ', td.get_text()).strip()
                text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
                text = re.sub(r'([\[(]) ', r'\1', text)
                if not text:
                    continue
                anchor = td.find('a', href=True)
                self._emit('\n' + escape_text_backslashes(text), {
                    'type': 'math-group', 'node': gid,
                    'section': section_of(self.root, node)})
                eqnos.append({
                    'member': len(members) - 1,
                    'text': _expand_markers_inline(text, self.registry),
                    'target': anchor['href'] if anchor else None,
                })
        self.groups.append({
            'node': gid,
            'section': section_of(self.root, node),
            'members': members,
            'eqnos': eqnos,
        })

    @staticmethod
    def _is_decorative(node):
        if node.name in ('nav', 'header', 'footer'):
            return True
        cls = node.get('class') or []
        return any(any(token in c for token in (
            'pagination', 'page-nav', 'ltx_page_nav',
            'html-header-logo', 'ltx_page_logo', 'ds-announcement',
            'ds-site-footer'))
            for c in cls)

    def _table_simple(self, table):
        "简单表：复用既有 [TABLE] 格位与代码表示（04-1）；格内公式出现"
        "以来源标记随格位序列化传递，写出时逐字展开（§7.11.4）。"
        node_id = self._table_ids.get(id(table))
        try:
            lines = self.fidelity.table_block(table)
        except Exception:
            self._unsupported_container(table)
            return
        text = '\n'.join(lines).strip('\n')
        self._emit('\n' + text, {
            'type': 'table', 'node': node_id,
            'section': section_of(self.root, table),
            'conversion': {'style': 'simple'}})

    def _table_complex(self, table):
        "复杂表：仅按 table_conversions 逐源格裁决映射物化；缺映射时"
        "保留原文并列未解决，不展平、不转代码（04-1/04-2）。"
        node_id = self._table_ids.get(id(table))
        ordinal = int(node_id.split('[')[1].rstrip(']')) \
            if node_id else None
        mapping = locate_table_mapping(table, ordinal,
                                       (self.table_conversions or {}).get(
                                           'tables'))
        if mapping is None:
            # 表内已确认公式随宿主保留（不猜写、不丢弃），逐出现登记；
            # 保留文字中的公式维持既有 $…$ 包裹字节（preserved 与实际
            # 写出内容一致）；已未解决的出现保持原序列化内容
            for occ in self.registry.occurrences.values():
                host = occ.get('table_host')
                if host is None or occ['unresolved'] is not None:
                    continue
                if host is table or table in host.parents:
                    occ['unresolved'] = ('所在复杂表缺少 table_conversions'
                                         ' 裁决映射（公式随宿主保留）')
                    occ['serialized'] = '$%s$' % occ['tex']
                    occ['raw'] = occ['serialized']
            self._unsupported_container(
                table, node_id=node_id,
                reason='复杂表缺少 table_conversions 逐源格裁决映射'
                       '（已保留原文，不展平不转代码）')
            return
        cells, codes = table_cell_facts(table,
                                        pre_bodies=self.fidelity._pre_blocks)
        text, _declared = render_mapped_table(cells, codes, mapping)
        self._emit('\n' + text, {
            'type': 'table', 'node': node_id,
            'section': section_of(self.root, table),
            'conversion': {'style': 'mapped',
                           'locate': mapping.get('locate')}})

    def _listing(self, node):
        """清单行容器：逐行保留字符/空白/次序与行内公式，不转代码、不
        展平（03-2/08）；行内公式出现以来源标记随 render_inline 序列化
        传递（原 TeX 逐字，D2/F4），写出时逐字展开。"""
        node_id = self._listing_ids.get(id(node)) or 'listing'
        count = 0
        for line in node.children:
            if not isinstance(line, Tag):
                continue
            lcls = line.get('class') or []
            if not any('listingline' in c for c in lcls):
                continue
            count += 1
            text = self.fidelity.render_inline(line,
                                               escape_backslashes=True)
            meta = {'type': 'listing', 'node': node_id,
                    'section': section_of(self.root, node)}
            self._emit('\n' + text if text else '', meta)
        if count == 0:
            self._unsupported_container(node)

    def _biblist(self, node):
        "参考文献条目列表：逐条文字按源序输出（默认保留英文，04）；条内"
        "公式出现以来源标记传递、写出时逐字展开。块级出现在条内拆段为"
        "独立块片段（与图片拆段同一字节约定，ticket 20）。"
        count = 0
        for item in node.find_all('li', recursive=False):
            count += 1
            text = self.fidelity.render_inline(item,
                                               escape_backslashes=True)
            if text:
                self._emit('\n' + text, {
                    'type': 'paragraph', 'node': None,
                    'section': section_of(self.root, item)})
        if count == 0:
            self._unsupported_container(node)

    def _itemize(self, node):
        "简单无序列表：`- ` 条目行表示，逐条保留（08）；条内公式出现以"
        "来源标记传递、写出时逐字展开；块级出现拆段为独立块片段（同"
        " _biblist）。"
        count = 0
        for item in node.find_all('li', recursive=False):
            count += 1
            text = self.fidelity.render_inline(item,
                                               escape_backslashes=True)
            self._emit('\n- ' + text if text else '\n-', {
                'type': 'paragraph', 'node': None,
                'section': section_of(self.root, item)})
        if count == 0:
            self._unsupported_container(node)

    def _unsupported_container(self, child, node_id=None, reason=None):
        """未支持的内容性容器：保留为 [TAGNAME] 文字输出并登记
        unresolved（含保留内容核对依据），不静默丢弃、不声称已支持。
        公式出现以来源标记随保留文字传递，写出时逐字展开（原 TeX 不被
        可见文字提取改写，F4）；块级出现在保留文字行内语境按目标原因
        fail-fast。node_id/reason 供有既有命名与具体原因的宿主（如缺
        裁决映射的复杂表）覆盖通用命名。"""
        text = ' '.join(child.get_text(' ', strip=True).split())
        # 保留文字按阅读语义加写原文字面反斜线与强调定界（复评 S1：裸
        # `*`/`_` 会在真实阅读中丢字符）；来源标记无此类字符，不受影响
        text = escape_text_backslashes(text)
        tag = child.name.upper()
        self._emit('\n[%s] %s' % (tag, text), {
            'node': node_id or self._container_ids.get(id(child)),
            'type': 'unresolved-container',
            'kind_marker': 'unresolved-container',
            '_no_split': True,
            'section': section_of(self.root, child),
            'reason': reason or ('未支持内容容器 <%s>（ticket 01 范围外），'
                                 '已保留原文' % child.name)})

    def _image(self, img, figure_id=None, sub_index=None):
        src = img.get('src', '')
        if not src:
            return
        reference = self._image_targets.get(id(img)) or (
            'images/%s' % src.rsplit('/', 1)[-1])
        subs = {e.get('original_ref'): e
                for e in self.resource_substitutions
                if isinstance(e, dict)}
        style = 'substituted' if src in subs else 'img-marker'
        self._emit('\n[IMG: %s]' % reference, {
            'type': 'image', 'node': self._img_ordinals.get(id(img)),
            'section': section_of(self.root, img),
            'figure': figure_id,
            'subfigure': sub_index,
            'conversion': {'style': style,
                           'reference': reference,
                           'source_ref': src}})
        self.fidelity.note_image(img, reference)
        if style == 'substituted' and self.fidelity.image_display:
            entry = self.fidelity.image_display[-1]
            product = (subs.get(src) or {}).get('product') or {}
            product_path = product.get('path')
            if product_path and os.path.isfile(product_path):
                entry['resource_sha256'] = hashlib.sha256(
                    open(product_path, 'rb').read()).hexdigest()
                entry['substituted'] = True

    def _algorithm(self, node):
        """算法清单：官方编号题注归属本清单；正文递归保持结构（公式/
        段落走既有口径），不为绕过门禁转成代码（03-2）。"""
        node_id = self._container_ids.get(id(node)) or 'algorithm'
        title = None
        for child in node.children:
            if isinstance(child, Tag):
                cls = child.get('class') or []
                if any('title' in c for c in cls):
                    title = child
                    break
        if title is not None:
            if has_marker(title):
                # 含公式出现：标记随行内序列化传递（原 TeX 逐字，
                # F4/三轮 F2），不被可见文字提取改写；记录文本展开标记
                # （不含内部记号）；按阅读语义加写原文字面反斜线与强调
                # 定界（复评 S1），记录保持未加写的原文字面
                text = self.fidelity.render_inline(
                    title, escape_backslashes=True)
                title_text = _expand_markers_inline(
                    self.fidelity.render_inline(title), self.registry)
            else:
                text = re.sub(r'\s+', ' ', title.get_text(' ', strip=True))
                title_text = text
                text = escape_text_backslashes(text)
            self._emit('\n[ALGORITHM] ' + text, {
                'type': 'algorithm', 'node': node_id,
                'section': section_of(self.root, node),
                'conversion': {'style': 'algorithm-title'},
                'title': title_text})
        for child in node.children:
            if title is not None and child is title:
                continue
            # 直属子节点逐个分派（p/pre/table 保持各自角色与节点身份），
            # 不跳过直属节点只解析其孩子（§7.11.5，ticket 20）
            self._dispatch_child(child, node)

    def _footnote_def(self, node):
        """LaTeXML 脚注定义：真实命名标签（id 原样，不抽数字），定义内容
        按文档序完整消费（03-3/§7.11.5，复评 F2）——直属文字、多个段落、
        列表与简单表保持块结构，代码块（含 pre 占位注释）在原位置
        恢复为定义内缩进围栏，其余内容标签以行内序列化
        保留；任何内容不静默丢弃，两端不共同忽略未消费内容。公式出现
        以来源标记随序列化传递（原 TeX 逐字），不被空白折叠改写。"""
        label = node.get('id')
        node_id = 'fn[%d]' % (len([c for c in self.emissions
                                   if c.meta and c.meta.get('type')
                                   == 'footnote-def']) + 1)
        section = section_of(self.root, node)
        parts = []
        body = next((child for child in node.children
                     if isinstance(child, Tag) and any(
                         'content' in c for c in (child.get('class') or []))),
                    node)
        def blocks(parent):
            result = []
            inline = []

            def flush():
                if inline:
                    result.append(' '.join(inline))
                    inline.clear()

            for child in parent.children:
                fenced = self.fidelity.fenced_pre(child)
                if fenced is not None:
                    flush()
                    result.append(fenced.strip('\n'))
                elif isinstance(child, Comment):
                    continue
                elif isinstance(child, NavigableString):
                    text = re.sub(r'\s+', ' ', str(child)).strip()
                    if text:
                        inline.append(escape_text_backslashes(text))
                elif isinstance(child, Tag):
                    block_names = ('pre', 'p', 'ul', 'ol', 'table', 'div')
                    has_blocks = child.find(block_names) or any(
                        self.fidelity.fenced_pre(descendant) is not None
                        for descendant in child.descendants)
                    if child.name not in block_names and not has_blocks:
                        text = self.fidelity.render_inline(child, escape_backslashes=True)
                        if text:
                            inline.append(text)
                        continue
                    flush()
                    if child.name == 'pre':
                        result.append('```\n' + clean_code_html(
                            child.decode_contents()).rstrip('\n') + '\n```')
                    elif child.name == 'p':
                        result.append(self.fidelity.paragraph_text(
                            child, escape_backslashes=True))
                    elif child.name in ('ul', 'ol'):
                        items = []
                        for ordinal, item in enumerate(
                                child.find_all('li', recursive=False), start=1):
                            marker = '%d. ' % ordinal if child.name == 'ol' else '- '
                            content = '\n\n'.join(blocks(item))
                            first, *rest = content.split('\n')
                            items.append(marker + first + ''.join(
                                '\n' + ' ' * len(marker) + line for line in rest))
                        result.append('\n'.join(items))
                    elif child.name == 'table':
                        if classify_block(child) == 'table-complex':
                            table_id = self._table_ids.get(id(child))
                            ordinal = int(table_id.split('[')[1].rstrip(']'))
                            mapping = locate_table_mapping(child, ordinal,
                                (self.table_conversions or {}).get('tables'))
                            if mapping is None:
                                raise ValueError('复杂表 %s 缺少 table_conversions 裁决映射' % table_id)
                            cells, codes = table_cell_facts(child, self.fidelity._pre_blocks)
                            rendered, _ = render_mapped_table(cells, codes, mapping, gfm=True)
                            result.append(rendered)
                            continue
                        rows = []
                        for row in child.find_all('tr'):
                            # Table syntax consumes the escaped delimiter even
                            # within code spans; the code reader receives a|b.
                            cells = [self.fidelity.render_inline(
                                td, escape_backslashes=True).replace('|', r'\|')
                                for td in row.find_all(['td', 'th'])]
                            rows.append('| ' + ' | '.join(cells) + ' |')
                            if len(rows) == 1:
                                rows.append('| ' + ' | '.join('---' for _ in cells) + ' |')
                        result.append('\n'.join(rows))
                    else:
                        result.extend(blocks(child))
            flush()
            return result

        parts = blocks(body)
        # Each block stays at its source position and within the definition.
        content = '\n\n'.join(parts)
        first, *rest = content.split('\n')
        # A first list starts on the indented definition line so the real
        # footnote parser measures its child indentation relative to that list.
        if re.match(r'(?:- |[0-9]+\. )', first):
            text = '[^%s]:\n    %s' % (label, first)
        else:
            text = '[^%s]: %s' % (label, first) if first else '[^%s]:' % label
        for line in rest:
            text += '\n    ' + line
        self._emit('\n' + text, {
            'type': 'footnote-def', 'node': node_id,
            'section': section, 'label': label,
            'conversion': {'style': 'footnote-def'}})
        if not hasattr(self, '_note_labels'):
            self._note_labels = []
        self._note_labels.append(label)

    def _apply_decisions(self, root):
        """装饰排除与同源重复表示合并裁决（03-4）：只按具体 decisions
        处理；无法确认的一律保留内容并登记未解决，不静默丢弃。"""
        container_ids = self._container_ids
        by_name = {}
        tag_first = {}
        for node in root.find_all(True):
            tag_first.setdefault(node.name, node)
            for mapping in (container_ids, self._group_ids,
                            self._figure_ids, self._aside_ids):
                name = mapping.get(id(node))
                if name:
                    by_name[name] = node

        def _lookup(node_name):
            if not isinstance(node_name, str):
                return None
            if node_name in by_name:
                return by_name[node_name]
            # 便捷回退仅限装饰标签（nav/header/footer），避免把
            # 'div#k' 之类误定位到第一个 div（03-4）
            tag = node_name.split('#', 1)[0]
            if tag in ('nav', 'header', 'footer'):
                return tag_first.get(tag)
            return None
        for decision in self.decisions:
            if not isinstance(decision, dict):
                continue
            node_name = decision.get('node')
            node = _lookup(node_name)
            result = dict(decision)
            if decision.get('action') == 'exclude-decoration':
                if node is None:
                    result['result'] = 'unresolved'
                    result['reason'] = '排除裁决节点 %s 不存在' % node_name
                elif self._is_decorative(node):
                    node.decompose()
                    result['result'] = 'excluded'
                else:
                    result['result'] = 'unresolved'
                    result['reason'] = ('排除裁决未被确认（非装饰节点），'
                                        '内容已保留')
            elif decision.get('action') == 'merge-duplicate':
                target = _lookup(decision.get('into'))
                if node is None or target is None:
                    result['result'] = 'unresolved'
                    result['reason'] = '合并裁决节点不存在'
                else:
                    a = re.sub(r'\s+', ' ', node.get_text(' ')).strip()
                    b = re.sub(r'\s+', ' ', target.get_text(' ')).strip()
                    if a == b and a:
                        node.decompose()
                        result['result'] = 'merged'
                    else:
                        result['result'] = 'unresolved'
                        result['reason'] = ('合并裁决不成立（同源内容'
                                            '不相等），两处均保留')
            else:
                continue
            self.decision_results.append(result)

    def _figure(self, figure, parent_id=None, sub_index=None):
        """图浮动体：以上下文栈遍历全部图内容与子图（含 flex 面板内的
        表格/清单等），每个图片出现与题注按实际出现记录父浮动体与子图
        序（03-1/08）；同号异内容/官方重复/相同字节均不自动去重。

        嵌套判定按 DOM 宿主（find_parent('figure')），子图序 = 同一父
        浮动体内按文档序的出现序（中间隔 flex 单元等包装不影响计数）。"""
        figure_id = self._figure_ids.get(id(figure))
        if parent_id is None:
            dom_parent = figure.find_parent('figure')
            if dom_parent is not None:
                parent_id = self._figure_ids.get(id(dom_parent))
                sub_index = 1 + sum(
                    1 for sib in figure.find_all_previous('figure')
                    if sib.find_parent('figure') is dom_parent)
            else:
                parent_id = figure_id
        self._fig_ctx.append((parent_id, sub_index))
        try:
            # walk 按子节点分发：对 figure 自身调用即遍历其全部内容
            # （含 flex 面板内的表格/清单），嵌套子图由 figure 分支递归
            self._walk(figure)
        finally:
            self._fig_ctx.pop()

    def _figure_caption(self, cap, figure_id, sub_index):
        text = self.fidelity.clean_heading(
            self.fidelity.heading_text(cap, escape_backslashes=True))
        self._emit('[FIGURE] ' + text, {
            'type': 'figure-caption',
            'node': self._figcaption_ordinals.get(id(cap)),
            'section': section_of(self.root, cap),
            'figure': figure_id,
            'subfigure': sub_index})
def adapt_latexml_snapshot(raw_html, section_id, decisions, snapshot_dir,
                           table_conversions=None,
                           resource_substitutions=None):
    """入口：原快照 → (候选 Markdown, correspondences, unresolved, fidelity, adapter)。

    输入、Markdown 候选与依据输出互不覆盖由调用方保证；候选经独立对账
    通过后才允许写出（调用方负责）。table_conversions 为逐表人工裁决
    映射（version:1），复杂表只按它物化（04）。
    """
    fidelity = HtmlFidelity(unknown_footnote='[^?]',
                            snapshot_dir=snapshot_dir)
    adapter = LatexmlAdapter(fidelity, decisions, table_conversions,
                             resource_substitutions=resource_substitutions)
    md_text, correspondences, unresolved = adapter.adapt(raw_html,
                                                         section_id)
    return md_text, correspondences, unresolved, fidelity, adapter


def build_candidate_adaptation(input_payload, raw_html, snapshot_path,
                               correspondences, unresolved, groups=None,
                               decision_results=None,
                               table_conversions=None, selection=None,
                               md_text=None):
    """生成候选依据输出：复制实际适用的身份/裁决，重建 correspondences
    与 unresolved（及公式组/内容归属，ticket 02/03）；快照摘要按实际输入
    重算，不沿用输入；输入中的旧 correspondences 不能代替本次重建。
    装饰排除/重复合并的实际处理结果（含未确认保留）进 decision_results，
    由独立对账逐条验证。md_text 提供时记录本次解析的确认选区（selection，
    无选区为 null）与本快照 Markdown 的范围事实（markdown.sha256/lines），
    供多快照切片与选区准入消费（§7.5 F2/F7）；旧依据无此二键。"""
    candidate = {
        'version': ADAPTATION_VERSION,
        'format': ADAPTATION_FORMAT,
        'snapshot': {
            'path': os.path.realpath(snapshot_path),
            'sha256': sha256_text(raw_html),
        },
        'paper_identity': dict(input_payload.get('paper_identity') or {}),
        'decisions': list(input_payload.get('decisions') or []),
        'correspondences': correspondences,
        'unresolved': unresolved,
    }
    if md_text is not None:
        candidate['selection'] = selection
        candidate['markdown'] = markdown_range_facts(md_text)
    if groups:
        candidate['groups'] = groups
    if decision_results is not None:
        candidate['decision_results'] = list(decision_results)
    if table_conversions is not None:
        candidate['table_conversions'] = table_conversions
    if input_payload.get('resource_substitutions'):
        candidate['resource_substitutions'] = list(
            input_payload.get('resource_substitutions') or [])
    return candidate


def bound_math_spans(md_text, payload, full=True, label='源文'):
    """按来源依据核对实际 Markdown 的公式事实，返回 (spans, problems)。

    full=True（完整源范围）：实际扫描的公式必须与 correspondences 的数量、
    顺序、类型与定界包装逐字一致，漏项/多项/改写即问题；full=False（包或
    片段范围）：给定文本中的每个公式都必须绑定到依据（类型与包装逐字），
    不允许来源文件自报范围之外的数学进入精确比较口径，也不降级为普通
    来源。返回的 spans 为 (kind, tex, md_start, md_end) 有序列表。
    """
    problems = []
    corrs = [c for c in (payload.get('correspondences') or [])
             if isinstance(c, dict) and c.get('content_type') == 'math']
    spans = []
    scan = scan_math(md_text,
                     source_context=scan_context_from_payload(payload))
    for issue in scan.issues:
        problems.append('%s L%d 未解决数学定界 %r: %s'
                        % (label, issue.start_line, issue.raw,
                           issue.reason))
    scan = type(scan)(tuple(table_math_spans(scan.spans, md_text, decode_entities=True)), scan.issues)
    table_rows = markdown_table_row_lines(md_text)
    fence_lines = fenced_line_numbers(md_text)
    # §7.11（ticket 19–24）：各类宿主内公式出现均有各自的精确对应，
    # 宿主范围不再授予任何覆盖资格——绑定只承认逐字匹配的对应（及
    # 片段口径的确认集合），宽宿主成功回退已删除
    # 片段/包范围（full=False）：全篇字符区间在切片中不成立，改用内容级
    # 确认集合——公式对应 tex + 公式组成员行内的字面公式（表内公式经
    # 对应登记已在确认集合内，五轮 F2：删除本地 [TABLE] 行无条件豁免，
    # 表行公式与其他位置同一绑定口径）
    confirmed_exprs = None
    if not full:
        confirmed_exprs = set()
        for corr in corrs:
            if corr.get('kind') and isinstance(corr.get('tex'), str):
                confirmed_exprs.add((corr['kind'], corr['tex']))
        from _verification import scan_math as _sm
        for group in (payload.get('groups') or []):
            if not isinstance(group, dict):
                continue
            for member in group.get('members') or []:
                if not isinstance(member, str):
                    continue
                for sp in _sm(member).spans:
                    confirmed_exprs.add((sp.kind, sp.expr))
            for eqno in group.get('eqnos') or []:
                if isinstance(eqno, dict) and isinstance(
                        eqno.get('text'), str):
                    for sp in _sm(eqno['text']).spans:
                        confirmed_exprs.add((sp.kind, sp.expr))

    def _expr_key(span):
        expr = span.expr
        if span.kind == 'block' and expr.startswith('\n') \
                and expr.endswith('\n'):
            expr = expr[1:-1]
        return (span.kind, expr)

    for span in scan.spans:
        if span.start_line in fence_lines:
            continue  # 围栏内美元是代码文字
        raw = decode_table_math(span.raw) if span.start_line in table_rows else span.raw
        hit = None
        for corr in corrs:
            expected = corr_written_raw(corr)
            if expected == raw:
                hit = corr
                break
        if hit is None:
            if confirmed_exprs is not None:
                # 片段口径：只承认依据侧事实——已确认表达式（公式对应 +
                # 组成员/式号）；片段自身包含某公式或公式位于本地
                # [TABLE] 块行均不构成绑定（四轮 F2 删除自证豁免，
                # 五轮 F2 删除表行豁免；合法服务对象已由三轮 F3 的
                # 字面公式对应登记承接）
                key = _expr_key(span)
                key_expr = key[1]
                if key in confirmed_exprs:
                    spans.append((span.kind, key_expr, span.start,
                                  span.end))
                    continue
            problems.append(
                '%s L%d 公式未绑定到来源依据（类型/定界/原文不符）: %r'
                % (label, span.start_line, span.expr))
            continue
        spans.append((span.kind, hit['tex'], span.start, span.end))
    if full and len(spans) != len(corrs):
        problems.append('公式与来源依据不一致: 依据 %d 处 vs 实际 %d 处'
                        % (len(corrs), len(spans)))
    return spans, problems


def precise_math_spans(md_text, adaptation_path, full=True, label='源文',
                       payload=None):
    """消费端绑定：读取来源依据并核对实际 Markdown 的公式事实，返回
    (MathSpan 列表, problems)。用于 compare_math_spans 的 precise 口径
    （表达式逐字、类型已确认）；核对失败时 problems 非空，调用方须拒绝，
    不降级为普通来源扫描。full=True 要求完整覆盖（完整源范围）。payload
    提供时跳过路径装载（多依据整文视图等内存消费端，§7.5 F7）。"""
    from _verification import MathSpan

    if payload is None:
        try:
            payload = load_adaptation(adaptation_path)
        except ValueError as exc:
            return [], [str(exc)]
    spans, problems = bound_math_spans(md_text, payload, full=full,
                                       label=label)
    if problems:
        return [], problems
    out = []
    for kind, tex, start, end in spans:
        out.append(MathSpan(
            kind=kind, expr=tex, raw=md_text[start:end], start=start,
            end=end,
            start_line=md_text.count('\n', 0, start) + 1))
    return out, []


def markdown_slice_form(md_text):
    """快照 Markdown 的切片形式：去掉一个结尾换行（多快照按序拼接时该
    换行是片间接缝，属于合并文档而非本片内容；不以换行结尾的文本原样）。
    切片行数 = 切片形式按 \\n 切分的行数。"""
    return md_text[:-1] if md_text.endswith('\n') else md_text


def markdown_range_facts(md_text):
    """本快照 Markdown 的范围事实（F7/§7.5）：切片形式的 sha256 与行数。
    消费者据此把当前源按序切片并独立校验（证明无缝拼接且未漂移）。"""
    sliced = markdown_slice_form(md_text)
    return {'sha256': sha256_text(sliced),
            'lines': len(sliced.split('\n'))}


def recorded_markdown_problems(md_text, payload, label='来源依据'):
    """核对该依据记录的本快照 Markdown 范围事实与给定文本一致（§7.5
    F2/F7）：按切片形式（去掉一个结尾换行）比较行数与 sha256。旧格式依
    据（无 markdown 键）返回空列表——既有整文行为完全不变；范围事实不
    符返回问题列表（覆盖不完整或内容漂移）。"""
    record = (payload or {}).get('markdown')
    if record is None:
        return []
    if not isinstance(record, dict) \
            or not isinstance(record.get('sha256'), str) \
            or not isinstance(record.get('lines'), int):
        return ['%s 的 markdown 范围事实无效（需 sha256/lines）' % label]
    problems = []
    sliced = markdown_slice_form(md_text)
    lines = sliced.split('\n')
    if record['lines'] != len(lines):
        problems.append('%s 记录本快照 Markdown %d 行，实际 %d 行（覆盖不'
                        '完整或已漂移）' % (label, record['lines'],
                                          len(lines)))
    actual = sha256_text(sliced)
    if actual != record['sha256']:
        problems.append('%s 记录本快照 Markdown 摘要 %s，实际 %s（内容漂移）'
                        % (label, record['sha256'][:12], actual[:12]))
    return problems


def slice_source_markdown(source_text, payloads, paths):
    """多依据按序切片（§7.5 F7）：把当前源 Markdown 切成与逐份依据记录
    一一对应的片段。每片行数须等于依据 markdown.lines 且 sha256 一致
    （证明无缝拼接且未漂移）；行数合计不等于当前源总行数即覆盖不完整。
    任一依据缺 markdown 范围事实（旧格式）即拒绝。末片允许带合并文档的
    结尾换行（拼接接缝口径）。返回与依据对齐的片段列表；不符抛
    ValueError，诊断如实指明缺口/漂移/顺序错误，不以"未闭合数学定界"
    等错误原因失败。"""
    lines = source_text.split('\n')
    pieces = []
    cursor = 0
    total = len(payloads)
    for index, (payload, path) in enumerate(zip(payloads, paths), start=1):
        record = (payload or {}).get('markdown')
        if not isinstance(record, dict) \
                or not isinstance(record.get('sha256'), str) \
                or not isinstance(record.get('lines'), int) \
                or record['lines'] < 1:
            raise ValueError('依据 #%d %s 缺少本快照 Markdown 范围事实'
                             '（markdown.sha256/lines），多依据切片无法校'
                             '验：请用当前解析器重新生成依据' % (index, path))
        end = cursor + record['lines']
        label = '依据 #%d %s 声明的 Markdown 段' % (index, path)
        if index < total and end >= len(lines):
            raise ValueError('%s（第 %d-%d 行）超出当前源总行数 %d：覆盖'
                             '不完整（依据行数合计超过当前源）'
                             % (label, cursor + 1, end, len(lines)))
        if index < total:
            piece = '\n'.join(lines[cursor:end])
        else:
            piece = '\n'.join(lines[cursor:])
        actual = sha256_text(piece)
        matched = actual == record['sha256']
        if not matched and index == total \
                and piece.endswith('\n') \
                and sha256_text(piece[:-1]) == record['sha256']:
            matched = True
        if not matched:
            raise ValueError('%s（第 %d-%d 行）sha256 与当前源不符：依据 '
                             '%s vs 实际 %s（切片漂移或依据顺序错误）'
                             % (label, cursor + 1,
                                end if index < total else len(lines),
                                record['sha256'][:12], actual[:12]))
        pieces.append(piece)
        cursor = end if index < total else len(lines)
    if cursor != len(lines):
        raise ValueError('依据行数合计 %d 行，当前源共 %d 行：覆盖不完整'
                         '（当前源第 %d 行起无依据声明，缺 %d 行），多依'
                         '据切片无法无缝拼接'
                         % (cursor, len(lines), cursor + 1,
                            len(lines) - cursor))
    return pieces


def merge_slice_payloads(payloads, pieces):
    """把逐快照依据合并为整文视图（§7.5 F7）：correspondences/unresolved
    的 md 字符区间按累计偏移平移到拼接后整文坐标（公式绑定、check_
    policy 投影、跨包核对直接消费整文坐标）；groups/decision_results
    按序拼接（成员为文本/节点键，无坐标）；扫描上下文取并集（确认表达式
    逐字，D2 匹配忽略章节序）。返回的合并 payload 仅供消费端整文视图，
    不再承载单一快照身份；逐片对账仍各用原始依据。"""
    merged = {
        'version': ADAPTATION_VERSION,
        'format': ADAPTATION_FORMAT,
        'snapshot': None,
        'paper_identity': dict((payloads[0] or {}).get('paper_identity')
                               or {}),
        'correspondences': [],
        'unresolved': [],
    }
    for key in ('groups', 'decision_results', 'table_conversions',
                'resource_substitutions'):
        merged[key] = []
    offset = 0
    for payload, piece in zip(payloads, pieces):
        payload = payload or {}

        def _shift(entry):
            entry = dict(entry)
            for key in ('md_start', 'md_end'):
                if isinstance(entry.get(key), int):
                    entry[key] += offset
            return entry

        merged['correspondences'].extend(
            _shift(c) for c in (payload.get('correspondences') or [])
            if isinstance(c, dict))
        merged['unresolved'].extend(
            _shift(u) for u in (payload.get('unresolved') or [])
            if isinstance(u, dict))
        for key in ('groups', 'decision_results', 'table_conversions',
                    'resource_substitutions'):
            merged[key].extend(payload.get(key) or [])
        offset += len(piece) + 1
    for key in ('groups', 'decision_results', 'table_conversions',
                'resource_substitutions'):
        if not merged[key]:
            del merged[key]
    return merged


def multi_admission_view(source_text, payloads, paths, label='当前源'):
    """多依据整文准入视图（§7.5 F7）：按序切片（行数/sha 证明无缝且未
    漂移），逐片做完整原始源对账（身份+摘要+全量独立对账，各用自己的
    selection，不降级、不抽查），再合并为整文视图 payload。返回
    (pieces, merged payload)。任一环节失败抛 ValueError，诊断如实指明
    覆盖缺口/漂移/对账差异，不以"未闭合数学定界"等错误原因失败。调用方
    负责先 load_adaptation（结构与未解决项口径同单依据入口）。"""
    from _source_reconcile import reconcile_latexml_to_markdown
    pieces = slice_source_markdown(source_text, payloads, paths)
    for index, (payload, path, piece) in enumerate(
            zip(payloads, paths, pieces), start=1):
        _spans, bind_problems = bound_math_spans(
            piece, payload, full=True, label='%s切片#%d' % (label, index))
        if bind_problems:
            raise ValueError('%s切片 #%d 与依据 #%d 公式事实不符: %s'
                             % (label, index, index,
                                '；'.join(bind_problems[:5])))
        snapshot = payload.get('snapshot') or {}
        snap_path = snapshot.get('path')
        if not isinstance(snap_path, str) or not snap_path:
            raise ValueError('依据 #%d %s 缺 snapshot.path，无法定位原始'
                             '快照做完整对账' % (index, path))
        try:
            with open(snap_path, encoding='utf-8') as handle:
                raw = handle.read()
        except OSError as exc:
            raise ValueError('原始快照不可读，无法完整对账: %s（%s）'
                             % (snap_path, exc))
        problems = validate_adaptation(payload, raw_html=raw,
                                       snapshot_path=snap_path)
        if problems:
            raise ValueError('依据 #%d %s 身份/摘要核对失败: %s'
                             % (index, path, '；'.join(problems)))
        selection = payload.get('selection') \
            if 'selection' in payload else None
        diffs = reconcile_latexml_to_markdown(
            raw, piece, selection, payload,
            table_conversions=payload.get('table_conversions'))
        if diffs:
            raise ValueError('%s切片 #%d 与原始快照完整对账失败（不降级）: '
                             '%s' % (label, index, '；'.join(diffs[:5])))
    return pieces, merge_slice_payloads(payloads, pieces)


def source_view_payload(src_text, adaptation_paths):
    """核验端共用的来源视图装载（§7.5 F7）：单依据独立重读并核对其记录
    的 Markdown 范围事实（旧格式无新键则保持既有整文行为）；多依据按给
    定顺序切片校验（行数/sha 证明无缝未漂移，覆盖不完整/漂移如实拒绝）
    并逐片完整对账后合并整文视图 payload。装载、范围事实或切片失败抛
    ValueError，由调用方记为公式来源绑定失败（不降级为普通来源）。"""
    if len(adaptation_paths) == 1:
        payload = load_adaptation(adaptation_paths[0])
        problems = recorded_markdown_problems(
            src_text, payload, label='来源依据 %s' % adaptation_paths[0])
        if problems:
            raise ValueError('；'.join(problems))
        return payload
    payloads = [load_adaptation(p) for p in adaptation_paths]
    _pieces, merged = multi_admission_view(
        src_text, payloads, list(adaptation_paths))
    return merged


def fragment_view_payload(adaptation_paths):
    """片段/包范围核验的来源视图装载（三轮 F4）：逐份装载并做结构校验
    （同 load_adaptation 口径），多依据按给定顺序拼接 correspondences/
    groups 为包范围视图——full=False 的内容级确认集合不消费字符坐标，
    无需整篇文本做切片校验与偏移平移。整源准入由拆包/恢复/合并的当前
    源预检承担；完整文档核验仍走 source_view_payload 的全篇范围事实
    核对，本函数不替代它。装载失败抛 ValueError。"""
    payloads = [load_adaptation(p) for p in adaptation_paths]
    if len(payloads) == 1:
        return payloads[0]
    merged = {'correspondences': [], 'groups': []}
    for payload in payloads:
        merged['correspondences'].extend(
            c for c in (payload.get('correspondences') or [])
            if isinstance(c, dict))
        merged['groups'].extend(
            g for g in (payload.get('groups') or [])
            if isinstance(g, dict))
    if not merged['groups']:
        del merged['groups']
    return merged


def check_policy_projection(payload, char_start, char_end, source_path):
    """D4 最小 check_policy：只投影 [char_start, char_end) 实际涉及的原
    节点对应/裁决与适配器身份；整份快照或整份依据摘要不绑定到包。

    证据（recover/merge）中的 check_policy 块与本投影一致才具备复用资格；
    仅改无关包专属事实时本包投影不变，当前全源预检成立后仍可复验复用。
    投影只含事实身份（节点对应/裁决与适配器身份），不绑定整份依据文件
    摘要——否则任何无关改动都会使全部包失效，违背 D4 分层口径。
    §7.11.5 包资格中的身份：全源准入通过后，本包涉及出现按已核验局部
    出现命名（角色前缀 + 包内 md 出现序），资格比较使用局部角色、出现
    序、父属与原内容，消除别包新增/删除造成的全篇别名重编号。不删除
    node 字段、不退成表达式多重集：同包中的顺序、类型、所属及组/式号
    关系仍逐项参加比较；真实标签（脚注 label）、官方编号（式号文本/
    锚点）与资源身份（图片目标）不作别名归一。
    """
    def _hit(entry):
        start = entry.get('md_start')
        end = entry.get('md_end')
        return isinstance(start, int) and isinstance(end, int) \
            and start < char_end and end > char_start

    def _by_md(entry):
        return (entry['md_start'], entry['md_end'])

    hit_corrs = sorted((c for c in (payload.get('correspondences') or [])
                        if isinstance(c, dict) and _hit(c)), key=_by_md)
    hit_unres = sorted((u for u in (payload.get('unresolved') or [])
                        if isinstance(u, dict) and _hit(u)), key=_by_md)
    # 局部出现命名：本包涉及节点按角色前缀 + 包内出现序重命名，全局
    # 别名（math[k]/p[k]/fn[k]…）不进入资格比较
    local = {}
    counters = {}
    for entry in sorted(hit_corrs + hit_unres, key=_by_md):
        node = entry.get('node')
        if not isinstance(node, str):
            continue
        prefix = re.split(r'[\[#]', node)[0] \
            or str(entry.get('content_type') or 'node')
        counters[prefix] = counters.get(prefix, 0) + 1
        local[node] = '%s#%d' % (prefix, counters[prefix])

    def _local(node):
        return local.get(node, node)

    # 图浮动体别名不是对应节点（无独立 corr），按本包内首次出现序局部化
    figures = {}

    def _local_figure(alias):
        if not isinstance(alias, str):
            return alias
        if alias not in figures:
            figures[alias] = 'figure#%d' % (len(figures) + 1)
        return figures[alias]

    nodes = []
    for corr in hit_corrs:
        entry = {'node': _local(corr.get('node')),
                 'content_type': corr.get('content_type'),
                 'kind': corr.get('kind')}
        if corr.get('content_type') == 'math':
            entry['tex_sha256'] = sha256_text(corr.get('tex') or '')
            entry['wrap'] = ('$' if corr.get('kind') == 'inline' else '$$')
        for extra in ('figure', 'subfigure', 'label', 'group'):
            if corr.get(extra) is not None:
                value = corr.get(extra)
                if extra == 'figure':
                    value = _local_figure(value)
                elif extra == 'group':
                    value = _local(value)
                entry[extra] = value
        if corr.get('content_type') == 'table':
            conversion = corr.get('conversion') or {}
            entry['table_style'] = conversion.get('style')
            entry['locate_sha256'] = sha256_text(json.dumps(
                conversion.get('locate'), sort_keys=True, ensure_ascii=False))
        if corr.get('content_type') == 'image':
            conversion = corr.get('conversion') or {}
            entry['image_target'] = conversion.get('reference')
            entry['image_style'] = conversion.get('style')
            entry['source_ref'] = conversion.get('source_ref')
        nodes.append(entry)
    unresolved = [{'node': _local(u.get('node')), 'reason': u.get('reason')}
                  for u in hit_unres]
    member_nodes = {c.get('node') for c in hit_corrs}
    groups = []
    for group in payload.get('groups') or []:
        if not isinstance(group, dict):
            continue
        members = [m for m in (group.get('members') or [])]
        if not any(m in member_nodes for m in members):
            continue
        groups.append({
            'node': _local(group.get('node')),
            'members': [_local(m) for m in members],
            'eqnos': [{'member': e.get('member'), 'text': e.get('text'),
                       'target': e.get('target')}
                      for e in (group.get('eqnos') or [])],
        })
    # 03-7：内容/归属裁决按本包实际涉及的节点投影（无关裁决不影响本包）；
    # 裁决引用随同一局部映射归一，跨包目标变化仍使投影不符
    node_ids = {c.get('node') for c in hit_corrs}
    decisions = []
    for decision in (payload.get('decision_results') or []):
        if not isinstance(decision, dict):
            continue
        if decision.get('node') in node_ids \
                or decision.get('into') in node_ids:
            decisions.append({k: (_local(v) if k in ('node', 'into') else v)
                              for k, v in decision.items()})
    return {
        'adapter_sha256': adapter_identity(),
        'nodes': nodes,
        'unresolved': unresolved,
        'groups': groups,
        'decisions': decisions,
    }



def correspondence_package_problems(payload, package_ranges):
    """逐包范围核对公式对应完整性（02-5）：任一公式对应不得跨两包
    （范围起点与终点落在不同包即拒绝）；调用方负责先通过当前全源预检。
    返回问题列表（空 = 通过）。"""
    problems = []
    for corr in (payload.get('correspondences') or []):
        if not isinstance(corr, dict) or corr.get('content_type') != 'math':
            continue
        start = corr.get('md_start')
        end = corr.get('md_end')
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        hit = [index for index, (ps, pe) in enumerate(package_ranges)
               if start < pe and end > ps]
        contains = [index for index, (ps, pe) in enumerate(package_ranges)
                    if ps <= start and end <= pe]
        if len(hit) > 1 and not contains:
            problems.append('公式对应 %s 跨多个工作包（范围 [%d,%d)），'
                            '拒绝按包投影' % (corr.get('node'), start, end))
    return problems
