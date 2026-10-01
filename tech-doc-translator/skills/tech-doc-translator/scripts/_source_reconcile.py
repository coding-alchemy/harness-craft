"""解析入口共用的原 HTML → 解析 Markdown 独立对账。

源事实直接从原始快照 HTML 独立提取（全新 BeautifulSoup 实例，不接触
渲染器的处理后 DOM、占位池或输出清单）；解析侧复用 `_verification` 的
成熟扫描能力识别输出范围。逐项比较标题、代码、公式、图片、脚注引用/
定义、表格与列表的内容、位置和顺序；计数只作摘要。任何无法解释为合法
转换的差异都计为损伤，由调用方在分派前非零退出。
"""
import copy
import hashlib
import re

from bs4 import BeautifulSoup, Comment, Tag

from _html_fidelity import (
    _INLINE_TAGS,
    HtmlFidelity,
    clean_code_html,
    protect_code_entities,
)
from _verification import (
    fenced_line_numbers,
    heading_entries,
    image_marker_spans,
    image_reference_spans,
    line_code_spans,
    parse_inline_code_spans,
    scan_code_fences,
    scan_math_spans,
)

_WS_RE = re.compile(r'\s+')
# 链接标签可含转义括号（\[ \]）；标签与 URL 均按转义感知匹配，
# 避免在标签内的 \] 或 ( 处提前截断
_MD_LINK_RE = re.compile(r'\[((?:\\.|[^\[\]])*)\]\(((?:\\.|[^()])*)\)')
_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_IMG_MARKER_RE = re.compile(r'\[IMG:\s*[^\]]*\]')
_MD_FOOTNOTE_RE = re.compile(r'\[\^([^\]]+)\]')
_MD_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_MD_MATH_RE = re.compile(r'\$+([^$]*)\$+')
_MD_CODE_SPAN_RE = re.compile(r'(`+)(.*?)\1', re.S)
_SRC_MATH_WRAP_RE = re.compile(r'\\\(|\\\)|\\\[|\\\]')
_FENCE_LINE_RE = re.compile(r'^\s*(`{3,}|~{3,})')
_TABLE_CODE_MARKER_RE = re.compile(
    r'^\[TABLE-CODE r=(\d+) c=(\d+)#(\d+)\]$')
_MD_LIST_MARKER_RE = re.compile(r'^(\s*)-(?: (\S.*?))?\s*$')


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


def _norm_text(text, unwrap_links=True, mark_code=False):
    """内容归一化：行内代码、链接/强调/脚注/公式记法、空白与标点紧排。

    链接解包只用于输出侧（渲染后的 [标签](URL)）；源侧是纯文本，
    其中形似链接的字面量（如 “__fadd_[rn,rz,ru,rd](x, y)”）须保持
    原样，与输出侧链接标签归一后的文字一致。

    mark_code 为 True（标题流）：行内代码最先隔离为 \\x00 定界占位、
    内容不参与任何后续归一（图片语法删除、空白折叠都不能改写代码
    字面量），公式保留 ``$`` 定界（去定界的拍平必须可检）；其余步骤
    与普通口径一致。"""
    code_spans = []
    if mark_code:
        def _keep_code(match):
            code_spans.append(_pad_code_content(match.group(2)))
            return '\x00%d\x00' % (len(code_spans) - 1)
        text = _MD_CODE_SPAN_RE.sub(_keep_code, text)
    text = _MD_IMAGE_RE.sub(' ', text)
    text = _MD_IMG_MARKER_RE.sub(' ', text)
    if not mark_code:
        text = _MD_CODE_SPAN_RE.sub(lambda m: _pad_code_content(m.group(2)),
                                    text)
    if unwrap_links:
        text = _MD_LINK_RE.sub(lambda m: m.group(1).replace(
            '\\[', '[').replace('\\]', ']'), text)
    text = _MD_FOOTNOTE_RE.sub(r'[\1]', text)
    text = _MD_BOLD_RE.sub(r'\1', text)
    if not mark_code:
        text = _MD_MATH_RE.sub(r'\1', text)
    text = text.replace('\\]', ']').replace('\\[', '[')
    if not mark_code:
        text = _SRC_MATH_WRAP_RE.sub('', text)
    text = _WS_RE.sub(' ', text).strip()
    text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
    text = re.sub(r'([\[(]) ', r'\1', text)
    for index, span in enumerate(code_spans):
        text = text.replace('\x00%d\x00' % index, '\x00%s\x00' % span)
    return text


def _pad_code_content(content):
    """按 CommonMark 规则剥除代码跨度内容的成对边界空格。"""
    if content.startswith(' ') and content.endswith(' ') and content.strip():
        return content[1:-1]
    return content


def _norm_math(expr):
    """公式表达式比较口径：空白不敏感（LaTeX 排版空白无语义）。"""
    return _WS_RE.sub('', expr)


def _footnote_label(text):
    digits = re.sub(r'\D', '', text or '')
    return digits or '?'


def _literal_math_exprs(text):
    """文本中的字面公式流；转义括号 `\\[…\\]` 是字面文字而非公式定界。"""
    stripped = text.replace('\\[', ' ').replace('\\]', ' ')
    return [_norm_math(span.expr) for span in scan_math_spans(stripped)]


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


class _SourceFacts:
    """从原始 HTML 独立提取的有序源事实流。"""

    def __init__(self, raw_html, family, section_id):
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
        """标题事实 (层级, 行内序列化文字)：与渲染端 heading_text 同一
        序列化，行内代码以 \x00 定界参与比较——拍平或改字即差异。"""
        entries = []
        for h in self.root.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            if _in_pre(h):
                continue
            copied = copy.deepcopy(h)
            for link in copied.find_all('a', class_='headerlink'):
                link.decompose()
            text = self._inline.render_inline(copied)
            entries.append((int(h.name[1]), _norm_text(
                text.replace('¶', '').replace('\uf0c1', ''),
                unwrap_links=False, mark_code=True)))
        return entries

    def _code(self):
        blocks = []
        for pre in self.root.find_all('pre'):
            body = clean_code_html(pre.decode_contents())
            blocks.append((self._section_of(pre), self._index[id(pre)], 0,
                           'code', body.rstrip('\n')))
        return blocks

    def _math(self):
        """公式流：class=math 元素与文本节点中的字面 $…$，按文档顺序。

        解析器把 span/div.math 转成 `$…$`，正文中本就存在的 `$…$` 文字
        原样保留并同样参与公式扫描；源侧流必须同时覆盖两类，才能与
        解析结果的扫描口径一致。
        """
        spans = []

        def strip_wrappers(expr):
            e = expr.strip()
            if (e.startswith('\\(') and e.endswith('\\)')) \
                    or (e.startswith('\\[') and e.endswith('\\]')):
                return e[2:-2].strip()
            return e

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
                    spans.append((self._section_of(node), order, sub, 'math',
                                  _norm_math(strip_wrappers(node.get_text()))))
                continue
            if isinstance(node, str):
                if node.find_parent(class_='math') is not None:
                    continue
                order = self._index[id(node)]
                sub = sub_by_index.get(order, 0)
                for expr in _literal_math_exprs(str(node)):
                    spans.append((self._section_of(node), order, sub, 'math',
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
            dts = dl.find_all('dt')
            if not dts or not all(
                    re.fullmatch(r'\[\d+\]|\(\d+\)|\d+',
                                 dt.get_text(strip=True)) for dt in dts):
                continue
            dds = dl.find_all('dd')
            for dt, dd in zip(dts, dds):
                defs.append((_footnote_label(dt.get_text()),
                             _norm_text(dd.get_text(' '))))
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
                defs.append((match.group(1), _norm_text(match.group(2),
                                                            unwrap_links=False)))
        return defs

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
        transparent = {'ul', 'ol', 'div', 'section', 'article', 'main',
                       'body', 'blockquote'}
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
                for i in range(prev_end, start))
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
                if ancestor.name in ('li', 'dd', 'dt'):
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

    @staticmethod
    def _cell_text(cell):
        copied = copy.deepcopy(cell)
        for pre in copied.find_all('pre'):
            pre.decompose()
        return _norm_text(copied.get_text(' '), unwrap_links=False)

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
        for ordinal, table in enumerate(tables, start=1):
            rows = []
            cells_spans = {}
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
                    cells_spans[(row_no, col_no)] = (
                        self._span_value(cell, 'rowspan'),
                        self._span_value(cell, 'colspan'))
                    for order, pre in enumerate(cell.find_all('pre'), start=1):
                        self.cell_pre_orders.setdefault(
                            self._index[id(pre)], ordinal)
                        codes[(row_no, col_no, order)] = \
                            clean_code_html(pre.decode_contents()).rstrip('\n')
                if cells:
                    rows.append(cells)
            records.append({
                'ordinal': ordinal,
                'id': table.get('id'),
                'rows': rows,
                'spans': cells_spans,
                'codes': codes,
            })
        return records

    def _terms(self):
        """非脚注定义列表的 (术语, dd 首行文字) 有序流。"""
        pairs = []
        for dl in self.root.find_all('dl'):
            if _in_pre(dl) or dl.find_parent('table') is not None:
                # 表格单元格内的定义列表随单元格文字渲染
                continue
            if dl.find_parent('figcaption') is not None:
                # 图例定义列表随图题整段行内序列化输出，术语流不重复计入
                continue
            dts = dl.find_all('dt')
            if not dts:
                continue
            if all(re.fullmatch(r'\[\d+\]|\(\d+\)|\d+',
                                dt.get_text(strip=True)) for dt in dts):
                continue  # 脚注列表由 footnote_defs 对账
            dds = dl.find_all('dd')
            for dt, dd in zip(dts, dds):
                pairs.append((_norm_text(dt.get_text(' ', strip=True),
                                          unwrap_links=False),
                              self._primary_text(dd)))
        return pairs


class _MarkdownFacts:
    """用既有扫描器从解析 Markdown 提取的有序输出事实流。"""

    def __init__(self, text):
        self.text = text
        self.lines = text.split('\n')
        self.fenced = fenced_line_numbers(text)
        self._heading_entries = heading_entries(text)
        # 标题行文字由标题流对账（源侧同样排除标题内容），标题公式与
        # 行内代码不进入通用流避免双计；图片不受排除（独立事实，标题
        # 图片序列化缺失必须阻断）
        self._heading_lines = {entry[0] for entry in self._heading_entries}
        self.headings = [
            (level, _norm_text(title, unwrap_links=False, mark_code=True))
            for _, level, title in self._heading_entries]
        # 章节唯一身份 = 标题在文档中的序号（同名小节不合并）
        self._heading_ordinals = {entry[0]: ordinal + 1
                                  for ordinal, entry in
                                  enumerate(self._heading_entries)}
        self.code = self._tagged_code()
        # math 流剥离转义括号后再扫描，链接标签中的 `\[字面\]` 不算公式
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
        stripped = self.text.replace('\\[', ' ').replace('\\]', ' ')
        line_starts = {}
        offset = 0
        for line_no, line in enumerate(stripped.split('\n'), start=1):
            line_starts[line_no] = offset
            offset += len(line) + 1
        return [(self._md_section(span.start_line), span.start_line,
                 max(0, span.start - line_starts.get(span.start_line, 0)),
                 'math', _norm_math(span.expr))
                for span in scan_math_spans(stripped)
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

    def footnote_streams(self):
        refs = []
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            for match in re.finditer(r'\[\^([^\]]+)\](?!:)', line):
                refs.append(_footnote_label(match.group(1)))
        defs = []
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
                text = _norm_text(s[1:])
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
        marker_lines = set()
        for line_no, line in enumerate(self.lines, start=1):
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
                text_value = _norm_text(match.group(2) or '')
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
                    text_value = _norm_text(stripped)
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
        其后首个围栏即该格代码。
        """
        records = []
        current = None
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            stripped = line.strip()
            if stripped == '[TABLE]':
                current = {'ordinal': len(records) + 1, 'rows': [],
                           'codes': {}, 'marker_lines': [], 'row_lines': set()}
                records.append(current)
                continue
            if current is None:
                continue
            if stripped.startswith('[TABLE-CODE'):
                match = _TABLE_CODE_MARKER_RE.match(stripped)
                if match is None:
                    current['marker_lines'].append(
                        (line_no, None, 'TABLE-CODE 标记格式无效: %s'
                         % stripped))
                    continue
                key = tuple(int(group) for group in match.groups())
                current['marker_lines'].append((line_no, key, None))
                continue
            if not stripped and line:
                # 单列全空单元格行（渲染端以单个空格输出，与零长空行区分）
                current['rows'].append([_norm_text('')])
                current['row_lines'].add(line_no)
                continue
            if not stripped:
                if current.get('single_column') and not line:
                    # 空行结束单列表格的行收集（单列行无列界记号）；
                    # 记录保留以继续接受其后的 [TABLE-CODE] 标记
                    current['single_closed'] = True
                continue
            if line.endswith('|') and ' | ' in line:
                # 行尾独立竖线 = 末列空格位（写作端可能剥掉尾随空格）
                line = line + ' '
            cells = line.split(' | ')
            if all(cell.strip() and _MD_TABLE_SEP_CELL_RE.match(cell.strip())
                   for cell in cells):
                continue  # 表头分隔行（单列 --- 同样适用）
            if ' | ' in line:
                current['rows'].append([_norm_text(cell) for cell in cells])
                current['row_lines'].add(line_no)
            elif not current.get('single_closed') and (
                    current.get('single_column') or not current['rows']):
                # 单列表格行（无列界记号）：自首行起进入单列模式，空行结束
                current['single_column'] = True
                current['rows'].append([_norm_text(line)])
                current['row_lines'].add(line_no)
            else:
                current = None
        fences = sorted(scan_code_fences(self.text).blocks,
                        key=lambda block: block.start_line)
        used_fences = set()
        for record in records:
            record['code_fence_lines'] = set()
            for line_no, key, error in record['marker_lines']:
                if error is not None:
                    record.setdefault('errors', []).append(error)
                    continue
                fence = next((block for block in fences
                              if block.start_line > line_no
                              and block.start_line not in used_fences), None)
                if fence is not None:
                    used_fences.add(fence.start_line)
                    record['code_fence_lines'].add(fence.start_line)
                record['codes'][key] = fence.body if fence else None
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
                pairs.append((_norm_text(m.group(1)),
                              _norm_text(m.group(2))))
        return pairs


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
            or table_conversions.get('version') != 1 \
            or not isinstance(table_conversions.get('tables'), list):
        return (['逐表转换映射结构无效（需 version=1 与 tables 数组）'],
                mapped_src, claimed_md, cell_target_counts,
                cell_table_targets, note_targets)
    digest = table_conversions.get('snapshot_sha256')
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
                    note_text = _norm_text(' '.join(
                        md.lines[lines[0] - 1:lines[1]]))
                    if cell_text and _norm_text(cell_text) not in note_text:
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
            for target in cell.get('targets', []):
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

    diffs = []
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
        cell = (src.mapped_cell_of(entry[1])
                if entry[3] in ('math', 'image', 'inline-code') else None)
        if cell is not None and cell[0] in mapped_src:
            src_inside.append(entry)
        else:
            src_content.append(entry)
    md_inside, md_note, md_content = [], [], []
    for entry in (md.code + md.math + md.images + md.inline_code):
        if entry[3] == 'code' and entry[1] in claimed_fence_lines:
            continue
        if entry[1] in claimed_row_lines:
            md_inside.append(entry)
        elif any(start <= entry[1] <= end for start, end in note_ranges):
            md_note.append(entry)
        else:
            md_content.append(entry)
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
    row_lookup = {}
    cell_bounds = {}
    for record in md_tables:
        if record['ordinal'] not in claimed_md:
            continue
        for row_no, line_no in enumerate(sorted(record['row_lines']),
                                         start=1):
            row_lookup[line_no] = (record['ordinal'], row_no)
            bounds = []
            cursor = 0
            for cell_text in md.lines[line_no - 1].split(' | '):
                bounds.append((cursor, cursor + len(cell_text)))
                cursor += len(cell_text) + 3
            cell_bounds[line_no] = bounds
    actual_by_target = {}
    for entry in sorted(md_inside, key=lambda item: (item[1], item[2])):
        ordinal, row_no = row_lookup[entry[1]]
        col_no = len(cell_bounds[entry[1]])
        for index, (_start, end) in enumerate(cell_bounds[entry[1]],
                                              start=1):
            if entry[2] < end:
                col_no = index
                break
        actual_by_target.setdefault((ordinal, row_no, col_no),
                                    []).append((entry[3], entry[4]))
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
    md_refs, md_defs = md.footnote_streams()
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
