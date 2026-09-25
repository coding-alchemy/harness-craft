"""HTML 提取器共享的保真实现。

本文件是内部模块；各源家族 adapter 继续负责树遍历及差异化规则。
"""
import copy
import json
import os
import re

from bs4 import BeautifulSoup, Comment, Tag

from _verification import file_sha256, parse_inline_code_spans, \
    resource_identity_digest


# 内联 CSS width 属性（仅取 width 声明；max-width 等不作为显示宽度依据）。
_INLINE_WIDTH_RE = re.compile(
    r'(?:^|;)\s*width\s*:\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z%]*)\s*(?:;|$)')
_INTEGER_RE = re.compile(r'^[0-9]+$')
_INLINE_PX_WIDTH_RE = re.compile(
    r'(?:^|;)\s*width\s*:\s*([0-9]*\.?[0-9]+)px\s*(?:;|$)', re.I)
# 高度约束（高度推导宽度用；百分比高度无参照不推导）。
_INLINE_HEIGHT_RE = re.compile(
    r'(?:^|;)\s*height\s*:\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z%]*)\s*(?:;|$)', re.I)

DISPLAY_MAP_VERSION = 1

# render_inline 内受保护行内代码的占位哨兵（不含空白，外层空白/标点
# 整理与 strip 不会改写其内容；\x00 不会出现在正常 HTML 文本中）。
_CODE_TOKEN_FMT = '\x00%d\x00'

# 富容器内按行内内容处理的标签；其余真实元素视为块级子节点。
_INLINE_TAGS = frozenset({
    'a', 'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'data', 'dfn',
    'del', 'em', 'font', 'i', 'ins', 'kbd', 'label', 'mark', 'nobr', 'q',
    'rp', 'rt', 'ruby', 's', 'samp', 'small', 'span', 'strong', 'sub',
    'sup', 'time', 'tt', 'u', 'var', 'wbr',
})

# 提示框类名（与解析器分支一致的包含匹配）
_ADMONITION_CLASS_TOKENS = ('admonition', 'note', 'warning', 'important', 'tip')


def _is_admonition_div(tag):
    if not isinstance(tag, Tag) or tag.name != 'div':
        return False
    cls = ' '.join(tag.get('class') or [])
    return any(token in cls for token in _ADMONITION_CLASS_TOKENS)

def _is_line_number_node(node):
    """已识别的 Pygments 行号装饰节点（class 含 lineno* 前缀）。"""
    classes = node.get('class') or []
    return any(cls.startswith('lineno') for cls in classes)

def clean_code_html(body):
    """清理 `<pre>` 内部包装：仅删除已识别装饰，其余真实标签解包保留文字。

    先按 HTML 语义解析包装结构：删除已识别的 Pygments 行号节点与
    script/style，注释按原文保留为文本；随后解包其余真实标签（span、
    div、code 等高亮包装），保留全部文本与空白。片段解析前包一层
    `<pre>`：bs4 在非保留空白上下文会把标签间纯空白文本节点压成单个
    换行，高亮包装间的行首缩进随之丢失；渲染端与独立对账端共用本
    保护，两侧拿到同一份无损代码文字。实体由解析器解码一次，
    不做二次 unescape——`&lt;span&gt;` 解码为字面 `<span>` 后不再被剥除，
    代码自身的数字、反引号与 `C#` 等内容原样保留。
    """
    soup = BeautifulSoup('<pre>%s</pre>' % body, 'html.parser')
    for text in list(soup.find_all(string=lambda s: isinstance(s, Comment))):
        text.replace_with('<!--%s-->' % text)
    for node in soup.find_all(lambda tag: isinstance(tag, Tag)
                              and (_is_line_number_node(tag)
                                   or tag.name in ('script', 'style'))):
        node.decompose()
    for node in list(soup.find_all(lambda tag: isinstance(tag, Tag))):
        if node.name == 'br':
            node.replace_with('\n')
        else:
            node.unwrap()
    return soup.get_text()

def contains_block_content(tag, block_tags):
    """容器是否含块级子内容：显式块标签、字面 pre 或受保护 pre 占位。"""
    if tag.find(list(block_tags) + ['pre'], recursive=True):
        return True
    for node in tag.descendants:
        if isinstance(node, Comment) and re.match(
                r'\s*__TECHDOC_PRE_\d+__\s*', node):
            return True
    return False

def protect_code_entities(raw, skip_pre=False):
    """转义 `<code>` 内容中的字面尖括号，使其不被 HTML 解析器当标记吃掉。

    `kernel<<<blocks>>>` 一类代码字面量在源 HTML 中未转义时，任何
    BeautifulSoup 解析路径都会丢字符；渲染端与独立对账端共用本保护，
    保证两侧拿到同一份代码文字。skip_pre 为 True 时跳过 `<pre>` 内的
    内容（对账端直接读取真实 pre 标签，不做占位替换）。
    """
    if not skip_pre:
        return re.sub(r'(<code[^>]*>)(.*?)(</code>)', _protect_code_match,
                      raw, flags=re.S)
    segments = re.split(r'(<pre[^>]*>.*?</pre>)', raw, flags=re.S)
    return ''.join(
        segment if segment.startswith('<pre') else
        re.sub(r'(<code[^>]*>)(.*?)(</code>)', _protect_code_match,
               segment, flags=re.S)
        for segment in segments)

def _protect_code_match(match):
    # 先解包代码内的真实高亮包装标签（Pygments 的 span 等）；正文字面
    # 尖括号在合法 HTML 中以实体出现，不受影响
    body = re.sub(r'</?span(?:\s[^>]*)?>', '', match.group(2))
    body = body.replace('<', '&lt;').replace('>', '&gt;')
    return match.group(1) + body + match.group(3)

def markdown_inline_code(content):
    """把 `<code>` 内容序列化为 Markdown 行内代码，可被反向解析还原。

    界符长度 = 内容中最长反引号串 + 1；内容以空格或反引号开头/结尾时
    在两侧各填充一个空格，使定界符与边界字符隔离（否则 `` + `foo 会
    合并成三反引号串，按 CommonMark 不再构成等长闭合）。成对填充的
    空格按代码跨度规则解析时剥除各一层，内容不因填充改变；全空白内容
    不填充（填充反而会引入被剥除的边界）。空内容用双反引号表示。

    行结束符按 CommonMark 代码跨度语义逐个转为空格；其余空白（连续
    空格、制表符）逐字节保留，不折叠——字符串字面量中的连续空格是
    代码内容，压缩即改义。
    """
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    content = content.replace('\n', ' ')
    if not content:
        return '````'
    longest = max((len(run) for run in re.findall(r'`+', content)),
                  default=0)
    delimiter = '`' * (longest + 1)
    if content.strip() and (content != content.strip(' ')
                            or content[0] == '`' or content[-1] == '`'):
        return delimiter + ' ' + content + ' ' + delimiter
    return delimiter + content + delimiter


class TableStructureError(ValueError):
    """表格含无法可靠表示的跨行/跨列结构；必须定位并阻断分派。"""


def image_display_width(img, soup, snapshot_dir=None):
    """提取 img 节点的显示宽度，返回 entry 字典（不含出现序号与路径）。

    依据优先级：可解析的内联 CSS width，再 HTML width 属性（按整数像素）。
    百分比必须记录可确定的参照容器（祖先链中最近的内联像素宽度），否则
    作为“百分比无参照”单列，不冒充已恢复。无宽度约束时尝试高度推导
    （px/pt 高度 × 源资源固有比例，快照资源按 snapshot_dir 定位）；比例
    未知、资源缺失或约束冲突均单列未确定原因。返回的
    basis/undetermined_reason 可回查到源节点定位。
    """
    node = 'img[%d]' % list(soup.find_all('img')).index(img) if soup is not None else 'img[?]'
    style = img.get('style') or ''
    match = _INLINE_WIDTH_RE.search(style)
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or 'px').lower()
        if unit == 'px':
            return _attach_resource_identity(
                {'value': value, 'unit': 'px', 'basis': 'inline-css-width',
                 'reference': None, 'source_node': node},
                img, snapshot_dir, node)
        if unit == '%':
            reference = _percent_reference(img)
            if reference is not None:
                return _attach_resource_identity(
                    {'value': value, 'unit': '%', 'basis': 'inline-css-width',
                     'reference': reference, 'source_node': node},
                    img, snapshot_dir, node)
            return _undetermined('百分比宽度缺少可确定的参照容器',
                                 img, snapshot_dir, node)
        return _undetermined('内联 CSS width 使用不支持的单位：%s' % unit,
                             img, snapshot_dir, node)
    width_attr = img.get('width')
    if width_attr and _INTEGER_RE.match(str(width_attr).strip()):
        return _attach_resource_identity(
            {'value': float(str(width_attr).strip()), 'unit': 'px',
             'basis': 'html-width-attribute', 'reference': None,
             'source_node': node},
            img, snapshot_dir, node)

    src = img.get('data-light') or img.get('src') or ''
    derived_entry = _derived_width_from_height(img, src, snapshot_dir, node)
    if derived_entry is not None:
        return derived_entry
    return _undetermined('源节点无宽度约束', img, snapshot_dir, node)


def _attach_resource_identity(entry, img, snapshot_dir, node):
    """确定尺寸条目补充独立来源资源身份（A28：解析后换图必被绑定拒绝）。"""
    src = img.get('data-light') or img.get('src') or ''
    if snapshot_dir is None:
        return entry
    path, reason = resolve_snapshot_resource(src, snapshot_dir)
    if path is None:
        return entry
    digest = resource_identity_digest(path)
    if digest is not None:
        entry['resource_sha256'] = digest
    return entry


def _undetermined(reason, img, snapshot_dir, node, **extra):
    """未确定条目：保留原因，并尽可能附独立来源资源身份。

    身份核对不应依赖尺寸是否确定——无宽度图片在解析后被同路径换图，
    同样必须由绑定拒绝（S05）；资源不可解析时退化为无身份（无从核对）。
    """
    entry = {'undetermined_reason': reason, 'source_node': node}
    entry.update(extra)
    return _attach_resource_identity(entry, img, snapshot_dir, node)


def _derived_width_from_height(img, src, snapshot_dir, node):
    """高度推导宽度：仅无可用宽度时尝试；不确定一律给出原因返回 None。"""
    height_px, meta = _height_constraint(img)
    if height_px is None:
        if meta is not None:  # 有高度约束但不可用（单位/冲突），原因保留
            return _undetermined(meta, img, snapshot_dir, node)
        return None  # 完全无约束；由无宽度约束条目兜底
    if snapshot_dir is None:
        return _undetermined('高度推导需要快照资源定位（缺少快照目录）',
                             img, snapshot_dir, node)
    path, reason = resolve_snapshot_resource(src, snapshot_dir)
    if path is None:
        return _undetermined('高度推导失败: %s' % reason,
                             img, snapshot_dir, node)
    ratio, aspect_source = intrinsic_aspect_ratio(path)
    if ratio is None:
        return _undetermined('高度推导失败: %s' % aspect_source,
                             img, snapshot_dir, node, height=meta)
    entry = {'value': height_px * ratio, 'unit': 'px',
             'basis': 'height-derived-width', 'reference': None,
             'source_node': node,
             'derived': {'height': meta, 'aspect_ratio': ratio,
                         'aspect_source': aspect_source,
                         'resource': src}}
    digest = resource_identity_digest(path)
    if digest is not None:
        entry['resource_sha256'] = digest
    return entry


def shaped_display_entries(image_display):
    """解析期内存条目 → 映射文件条目形状；返回 (确定项, 未确定项)。"""
    determined = []
    for e in image_display:
        if 'value' not in e:
            continue
        item = {'occurrence': e['occurrence'], 'image': e['image'],
                'width': {'value': e['value'], 'unit': e['unit'],
                          'basis': e['basis'], 'reference': e['reference']},
                'source_node': e['source_node']}
        if 'derived' in e:
            item['derived'] = e['derived']
        if 'resource_sha256' in e:
            item['resource_sha256'] = e['resource_sha256']
        determined.append(item)
    undetermined = [
        {'occurrence': e['occurrence'], 'image': e['image'],
         'reason_code': reason_code(e['undetermined_reason']),
         'reason': e['undetermined_reason'],
         'source_node': e['source_node'],
         **({'height': e['height']} if 'height' in e else {}),
         **({'resource_sha256': e['resource_sha256']}
            if 'resource_sha256' in e else {})}
        for e in image_display if 'undetermined_reason' in e
    ]
    return determined, undetermined


def reason_code(reason):
    """未确定原因的两类编码：源无约束 / 有约束但无法确定尺寸。"""
    if reason == '源节点无宽度约束':
        return 'no-source-constraint'
    return 'unresolved-size'


def _percent_reference(img):
    """沿祖先链寻找最近的内联像素宽度作为百分比参照。

    只有内联 style 的 px 宽度视为可确定参照（外部 CSS 布局不猜测）；
    返回 {'container': 标签描述, 'width_px': 数值} 或 None。
    """
    parent = img.parent
    depth = 0
    while parent is not None and getattr(parent, 'name', None) and depth < 8:
        style = parent.get('style') or ''
        match = _INLINE_PX_WIDTH_RE.search(style)
        if match:
            css = ' '.join(parent.get('class') or [])
            container = parent.name + ('.' + css.split()[0] if css else '')
            return {'container': container, 'width_px': float(match.group(1))}
        parent = parent.parent
        depth += 1
    return None


def resolve_snapshot_resource(src, snapshot_dir):
    """把图片引用解析为快照目录内的文件绝对路径；不可解析返回 (None, 原因)。"""
    clean = (src or '').split('#', 1)[0].split('?', 1)[0].strip()
    if not clean:
        return None, '空图片引用'
    if re.match(r'^[a-z][a-z0-9+.-]*:', clean, re.I):
        return None, '外链引用不参与本地推导'
    if os.path.isabs(clean) or clean.startswith('~'):
        return None, '机器绝对路径引用'
    path = os.path.normpath(os.path.join(snapshot_dir, clean))
    if not os.path.isfile(path):
        return None, '快照资源缺失: %s' % src
    return path, None


def _svg_intrinsic_ratio(path):
    """SVG 可确定固有比例：(ratio, 来源) 或 (None, 原因)。"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None, 'SVG XML 无效'
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        return None, '非 SVG 根元素'

    def _length(value):
        match = re.fullmatch(r'([0-9]*\.?[0-9]+)(px)?',
                             (value or '').strip())
        return float(match.group(1)) if match else None

    width = _length(root.get('width'))
    height = _length(root.get('height'))
    if width and height and width > 0 and height > 0:
        return width / height, 'svg-intrinsic-size'
    view_box = root.get('viewBox')
    if view_box:
        parts = view_box.replace(',', ' ').split()
        if len(parts) == 4:
            try:
                box_w, box_h = float(parts[2]), float(parts[3])
            except ValueError:
                return None, 'viewBox 数值无效'
            if box_w > 0 and box_h > 0:
                return box_w / box_h, 'svg-viewbox'
    return None, 'SVG 无可确定的固有比例'


def _bitmap_intrinsic_ratio(path):
    """位图固有比例：Pillow 只读头部元信息，不做全量像素解码。"""
    try:
        from PIL import Image  # noqa: F401 — 依赖在 requirements 声明
    except ImportError:
        return None, 'Pillow 不可用（见 requirements.txt 声明）'
    try:
        image = Image.open(path)
    except Exception as exc:
        return None, '位图元信息不可读: %s' % exc
    try:
        width, height = image.size  # 仅头部，未触发像素解码
    except Exception as exc:
        image.close()
        return None, '位图尺寸缺失: %s' % exc
    image.close()
    if width > 0 and height > 0:
        return width / height, 'pillow-size'
    return None, '位图尺寸非法'


def intrinsic_aspect_ratio(path):
    """按真实字节判型读取源资源固有宽高比；不确定时返回具体原因。"""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(4096)
    except OSError:
        return None, '源资源不可读'
    if not head:
        return None, '源资源为空'
    if (head.startswith(b'\x89PNG') or head.startswith(b'\xff\xd8\xff')
            or head.startswith((b'GIF87a', b'GIF89a'))
            or (head[:4] == b'RIFF' and len(head) >= 12
                and head[8:12] == b'WEBP')):
        return _bitmap_intrinsic_ratio(path)
    text_head = head.decode('utf-8', 'replace').lstrip()
    if text_head.startswith('<?xml') or '<svg' in text_head.lower():
        return _svg_intrinsic_ratio(path)
    return None, '源资源类型未知，比例不可确定'


def _height_constraint(img):
    """节点的显示高度约束：(px 值, 元信息) 或 (None, 未确定原因)。

    仅取内联 CSS height（px/pt）与 HTML height 属性（整数 px）；两种来源
    同时存在且不一致属冲突，百分比或其他单位不支持，均明确返回原因。
    """
    style = img.get('style') or ''
    css_px = None
    match = _INLINE_HEIGHT_RE.search(style)
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or 'px').lower()
        if unit == 'px':
            css_px = value
            meta = {'value': value, 'unit': 'px', 'origin': 'inline-css-height'}
        elif unit == 'pt':
            css_px = value * 4.0 / 3.0
            meta = {'value': value, 'unit': 'pt', 'origin': 'inline-css-height',
                    'converted_px': css_px}
        else:
            return None, '内联 CSS height 使用不支持的单位：%s' % unit
    attr = img.get('height')
    attr_px = None
    if attr is not None and _INTEGER_RE.match(str(attr).strip()):
        attr_px = float(str(attr).strip())
        attr_meta = {'value': attr_px, 'unit': 'px',
                     'origin': 'html-height-attribute'}
    elif attr is not None:
        return None, 'HTML height 属性不是无单位整数: %r' % attr
    if css_px is not None and attr_px is not None:
        if abs(css_px - attr_px) > 1e-6:
            return None, '高度约束冲突: 内联 CSS %r px vs HTML 属性 %r px' % (
                css_px, attr_px)
        return css_px, meta
    if css_px is not None:
        return css_px, meta
    if attr_px is not None:
        return attr_px, attr_meta
    return None, None


def temp_root_paths():
    """宿主临时根的真实路径集合（含平台别名，全部经符号链接解析）。"""
    import tempfile
    candidates = [tempfile.gettempdir(), '/tmp', '/var/tmp',
                  os.environ.get('TMPDIR')]
    roots = set()
    for candidate in candidates:
        if candidate:
            roots.add(os.path.realpath(candidate))
    return roots


def warn_if_temp_output(paths):
    """产物落入系统临时根时醒目告警；仅告警，不改变调用方退出状态。

    路径先规范化并解析符号链接，再按目录包含关系判断，同名前缀的普通
    目录不误报。返回是否发生告警。
    """
    import sys
    roots = temp_root_paths()
    hit = []
    for path in paths:
        if not path:
            continue
        real = os.path.realpath(path)
        if any(real == root or real.startswith(root + os.sep)
               for root in roots):
            hit.append((path, real))
    if hit:
        print('警告: 以下产物位于系统临时目录，临时目录清理后将无法回查'
              '（仅影响持久性，不影响本次命令状态）:', file=sys.stderr)
        for path, real in hit:
            print('  %s -> %s' % (path, real), file=sys.stderr)
    return bool(hit)


class HtmlFidelity:
    """保护代码并渲染各源家族一致的 Markdown 结构。"""

    def __init__(self, unknown_footnote='[?]', snapshot_dir=None):
        self._pre_blocks = []
        self._unknown_footnote = unknown_footnote
        self.image_display = []  # 按输出顺序登记的图片显示尺寸条目
        self._soup = None
        self.snapshot_dir = snapshot_dir  # 快照 HTML 所在目录（高度推导与 resource_base 用）

    def parse(self, raw):
        """保护代码内容后解析 HTML；每次调用重置 `<pre>` 占位池。"""
        self._pre_blocks = []
        self.image_display = []

        def protect_pre(match):
            body = clean_code_html(match.group(2))
            index = len(self._pre_blocks)
            self._pre_blocks.append(body)
            return '<!-- __TECHDOC_PRE_%d__ -->' % index

        protected = re.sub(
            r'(<pre[^>]*>)(.*?)(</pre>)', protect_pre, raw, flags=re.S)
        protected = protect_code_entities(protected)
        soup = BeautifulSoup(protected, 'html.parser')
        self._soup = soup
        return soup

    def note_image(self, img, src_as_written, snapshot_dir=None):
        """登记一个进入输出的图片出现及其源显示宽度（暗亮只记选中版本）。

        snapshot_dir 为快照 HTML 所在目录；仅高度推导需要读取源资源时使用，
        缺省取构造时传入的目录。
        """
        entry = image_display_width(
            img, self._soup, snapshot_dir=snapshot_dir or self.snapshot_dir)
        entry['occurrence'] = len(self.image_display) + 1
        entry['image'] = src_as_written
        self.image_display.append(entry)

    def write_display_map(self, out_md_path, snapshot_path):
        """把解析期登记的显示尺寸写入 <stem>.images_display.json。

        有条目才写文件；条目与未确定项分开列示，供翻译与导出链路对账。
        新输出附快照摘要与独立来源资源身份，未确定项附 reason_code，
        供回补/绑定与导出核验独立复核，不依赖本地摘要自证。snapshot
        统一记录解析后的绝对路径（HTML 文件身份，与回补读取端同义，
        不随解析执行目录或 CLI 参数形式变化；F3）；resource_base 记录
        资源解析上下文——相对图片引用按声明路径的目录解析（文件级
        符号链接下不同于 realpath 目录），realpath 仅归一目录自身的
        符号链接与平台别名，目录别名即同一上下文（F3 第八轮）。
        """
        determined, undetermined = shaped_display_entries(self.image_display)
        if not self.image_display:
            return None
        try:
            snapshot_digest = file_sha256(snapshot_path)
        except OSError:
            snapshot_digest = None
        payload = {
            'version': DISPLAY_MAP_VERSION,
            'markdown': os.path.basename(out_md_path),
            'snapshot': os.path.realpath(snapshot_path),
            'snapshot_sha256': snapshot_digest,
            'entries': determined,
            'undetermined': undetermined,
        }
        if self.snapshot_dir is not None:
            payload['resource_base'] = os.path.realpath(self.snapshot_dir)
        path = os.path.splitext(out_md_path)[0] + '.images_display.json'
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def clean_heading(text):
        """去掉 Sphinx headerlink 带来的 ¶ 与链接图标。"""
        return text.replace('¶', '').replace('\uf0c1', '').strip()

    def heading_text(self, tag):
        """移除实际 headerlink 链接节点后按行内语义序列化标题文字。

        只删除已识别的 `a.headerlink` 节点，不用删除尾部 `#` 或 `¶` 的
        正则代替；标题内容经 render_inline 序列化，行内代码、公式、
        链接与脚注引用保留语义（标题内 `a*b*` 不得拍平成 Markdown
        强调），`C#` 等内容不受影响。
        """
        copied = copy.deepcopy(tag)
        for link in copied.find_all('a', class_='headerlink'):
            link.decompose()
        return self.render_inline(copied)

    @staticmethod
    def _postprocess_inline(text):
        """行内文字的标点紧排（与 render_inline 尾部处理一致，幂等）。"""
        text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
        text = re.sub(r'([\[(]) ', r'\1', text)
        return text

    def render_inline(self, element):
        """渲染行内节点，保留公式、链接、脚注引用与行内代码语义。

        `<code>` 先转为 Markdown 行内代码并以哨兵占位：外层的空白归一、
        标点紧排与 strip 只作用于正文，不进入代码内容；占位在链接标签
        内同样保留，最终统一替换为代码跨度。元素自身即 code（富容器的
        直接 code 子节点）时整体转为代码跨度；元素自身即带 href 的链接
        时，其行内处理结果作为标签整体包装为链接，自身链接语义不因
        “只处理后代”而丢失。
        """
        copied = copy.copy(element)
        if copied.name == 'code':
            return markdown_inline_code(copied.get_text())
        self_href = (copied.get('href', '').strip()
                     if copied.name == 'a' else None)
        if 'math' in (copied.get('class') or []):
            # 元素自身即公式容器（span/div.math）；内部换行折叠为单空格，
            # 保持 $…$ 跨度在同一行内（对账口径空白不敏感）
            body = copied.get_text().strip()
            if body.startswith(r'\(') and body.endswith(r'\)'):
                body = body[2:-2].strip()
            if body.startswith(r'\[') and body.endswith(r'\]'):
                body = body[2:-2].strip()
            return '$' + re.sub(r'\s+', ' ', body) + '$'
        for math in copied.find_all(class_='math'):
            body = math.get_text().strip()
            if body.startswith(r'\(') and body.endswith(r'\)'):
                body = body[2:-2].strip()
            if body.startswith(r'\[') and body.endswith(r'\]'):
                body = body[2:-2].strip()
            math.replace_with('$' + body + '$')
        for ref in copied.find_all(class_='footnote-reference'):
            number = re.sub(r'\D', '', ref.get_text(strip=True))
            ref.replace_with(
                '[^%s]' % number if number else self._unknown_footnote)
        for superscript in copied.find_all('sup'):
            text = superscript.get_text(strip=True)
            if re.fullmatch(r'\[\d+\]|\(\d+\)', text):
                superscript.replace_with('[^%s]' % text.strip('[]()'))
        code_spans = []
        for code in copied.find_all('code'):
            code_spans.append(markdown_inline_code(code.get_text()))
            code.replace_with(_CODE_TOKEN_FMT % (len(code_spans) - 1))
        for link in copied.find_all('a', href=True):
            label = link.get_text(' ', strip=True)
            href = link.get('href', '').strip()
            if label and href:
                label = label.replace('[', r'\[').replace(']', r'\]')
                link.replace_with('[%s](%s)' % (label, href))
        text = copied.get_text(' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        text = self._postprocess_inline(text).strip()
        if self_href and text:
            text = '[%s](%s)' % (
                text.replace('[', r'\[').replace(']', r'\]'), self_href)
        for index, span in enumerate(code_spans):
            text = text.replace(_CODE_TOKEN_FMT % index, span)
        return text

    # ---- 富容器：直接子节点按源序只消费一次 ----

    def _block_sequence(self, node, skip=None):
        """把直接子节点分为按源序的 ('inline', 片段列表)/('fence', 围栏)/
        ('tag', 元素) 序列；受保护 pre 占位为 fence，行内标签与文本累积，
        其余真实元素为块级。skip(元素) 为 True 时跳过该子节点。"""
        seq = []
        inline_buf = []

        def flush():
            if inline_buf:
                seq.append(('inline', list(inline_buf)))
                inline_buf.clear()

        for child in node.children:
            fenced = self.fenced_pre(child)
            if fenced is not None:
                flush()
                seq.append(('fence', fenced))
                continue
            if isinstance(child, Comment):
                continue
            if isinstance(child, str):
                inline_buf.append(child)
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in ('script', 'style', 'noscript'):
                continue
            if skip is not None and skip(child):
                continue
            if child.name in _INLINE_TAGS:
                inline_buf.append(child)
                continue
            flush()
            seq.append(('block', child))
        flush()
        return seq

    def _inline_run_text(self, frags):
        """合并一组行内片段为段落文本（等价于整段 render_inline）。

        片段自身文字保持原样；仅在两侧都不以空白结尾时补一个连接空格，
        片段边界的既有空白不叠加成双空格——直接子节点与 p 包装的行内
        序列化保持一致。代码跨度在正文标点紧排前以占位掩蔽，整理不得
        进入代码内容（与 render_inline 的哨兵保护同一规则）。
        """
        text = ''
        for frag in frags:
            if isinstance(frag, str):
                part = re.sub(r'\s+', ' ', frag)
            else:
                part = self.render_inline(frag)
            if not part:
                continue
            if text and not text[-1].isspace() and not part[0].isspace():
                text += ' '
            text += part
        spans = []
        pieces = []
        cursor = 0
        for _content, (start, end) in parse_inline_code_spans(text):
            pieces.append(text[cursor:start])
            pieces.append('\x00%d\x00' % len(spans))
            spans.append(text[start:end])
            cursor = end
        pieces.append(text[cursor:])
        text = self._postprocess_inline(''.join(pieces)).strip()
        for index, span in enumerate(spans):
            text = text.replace('\x00%d\x00' % index, span)
        return text

    @staticmethod
    def _indented_fence(fenced, indent):
        """围栏标记行加缩进（正文保持原样；标记行缩进随项层级 2×level）。"""
        if not indent:
            return fenced
        return fenced.replace('\n```', '\n%s```' % indent)

    @staticmethod
    def _indented_block(entry, indent):
        """块级输出条目的行级缩进：段落/表格/标记行按项层级缩进。

        围栏正文行保持原样（代码字节不变），开启/关闭标记行随层级缩进；
        空行保持空行。项内一切块级内容与项文本处于同一缩进不变量下，
        供对账端按层级归属重建。
        """
        if not indent:
            return entry
        out = []
        fence_char = None
        for line in entry.split('\n'):
            if fence_char is not None:
                if re.match(r'^%s{3,}\s*$' % re.escape(fence_char),
                            line.lstrip(' ')):
                    fence_char = None
                    out.append(indent + line)
                else:
                    out.append(line)
                continue
            out.append(indent + line if line else line)
            mark = re.match(r'^(`{3,}|~{3,})', line.lstrip(' '))
            if mark:
                fence_char = mark.group(1)[0]
        return '\n'.join(out)

    def rich_container_lines(self, node, out, bullet=None, indent='',
                              render_block=None, emit_image=None,
                              inline_prefix='', skip=None):
        """按源序渲染 li/dd/details 等富容器的直接子节点。

        - 行内片段汇入首行（bullet 前缀）或缩进续行；
        - 受保护 pre 与字面 pre 输出为围栏（标记行缩进 ≤3 空格）；
        - p 按源序输出；嵌套 ul/ol 递归为更深层列表项；img 交给
          emit_image；其余块级元素交给家族 render_block。
        skip(元素) 为 True（或属于给定元素集合）的直接子节点不输出。
        每个直接子节点只消费一次，不以 find_all 先收后补。
        """
        if skip is not None and not callable(skip):
            skipped = set(skip)
            skip = lambda child: child in skipped  # noqa: E731
        first_text_done = False
        for kind, item in self._block_sequence(node, skip=skip):
            if kind == 'fence':
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                out.append(self._indented_fence(item, indent))
                continue
            if kind == 'inline':
                text = self._inline_run_text(item)
                if not text:
                    continue
                if bullet and not first_text_done:
                    out.append(inline_prefix + bullet + text)
                    first_text_done = True
                else:
                    out.append('\n' + inline_prefix + (indent or '') + text)
                continue
            name = item.name
            if name == 'p':
                t = self.render_inline(item)
                if not t:
                    continue
                if bullet and not first_text_done:
                    out.append(inline_prefix + bullet + t)
                    first_text_done = True
                else:
                    out.append('\n' + inline_prefix + (indent or '') + t)
            elif name in ('ul', 'ol'):
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                self.list_lines(item, out, (indent or '') + '  ',
                                render_block, emit_image)
            elif name == 'dl':
                # 直接子级定义列表须按定义列表输出：经 render_block 进入
                # 其子节点循环会退化为普通段落
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                before = len(out)
                out.extend(self.definition_list(
                    item, render_block, emit_image))
                for idx in range(before, len(out)):
                    out[idx] = self._indented_block(out[idx], indent)
            elif name == 'table':
                # 直接子级表格须按表格输出（同上，避免退化为单元格段落）
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                before = len(out)
                out.extend(self.table_block(item))
                for idx in range(before, len(out)):
                    out[idx] = self._indented_block(out[idx], indent)
            elif name == 'img':
                if emit_image is not None:
                    if bullet and not first_text_done:
                        out.append(bullet.rstrip())
                        first_text_done = True
                    emit_image(item, out)
            elif name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                out.append('\n' + '#' * int(name[1]) + ' '
                           + self.clean_heading(self.heading_text(item)))
            else:
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                before = len(out)
                if _is_admonition_div(item):
                    # 提示框作为项内块级子节点同样按提示框输出：直接
                    # render_block 会进入其子节点循环而丢失提示框结构
                    title = item.find(['p', 'div'], class_='admonition-title')
                    label = title.get_text(strip=True) if title else 'Note'
                    out.append('\n> **ADMONITION [%s]**' % label)
                    self.admonition_content_lines(
                        item, out, render_block, emit_image)
                elif render_block is not None:
                    render_block(item, out)
                # 项内块级内容（段落、表格标记行、围栏标记）一律按层级
                # 缩进；围栏正文原样。列 0 块级内容只属于顶层，供对账
                # 区分项内代码/段落与列表之间的顶层内容
                for idx in range(before, len(out)):
                    out[idx] = self._indented_block(out[idx], indent)
                # 无 render_block 时忽略未知包装容器

    def list_lines(self, tag, out, indent='  ', render_block=None,
                   emit_image=None):
        """按源序渲染 ul/ol 的直接 li；嵌套块保留在条目内。"""
        for li in tag.find_all('li', recursive=False):
            self.rich_container_lines(
                li, out, bullet=indent + '- ', indent=indent,
                render_block=render_block, emit_image=emit_image)

    def admonition_content_lines(self, tag, out, render_block=None,
                                 emit_image=None):
        """按源序输出提示框内容：段落与行内文字为引用行，其余块级
        （围栏、列表、表格等）按序原样输出，保持围栏扫描器可识别。"""
        def skip_title(child):
            return 'admonition-title' in ' '.join(child.get('class') or [])

        for kind, item in self._block_sequence(tag, skip=skip_title):
            if kind == 'fence':
                out.append(item)
            elif kind == 'inline':
                text = self._inline_run_text(item)
                if text:
                    out.append('> ' + text)
                continue
            elif item.name == 'p':
                t = self.render_inline(item)
                if t:
                    out.append('> ' + t)
            elif item.name in ('ul', 'ol'):
                self.list_lines(item, out, '  ', render_block, emit_image)
            elif item.name == 'img':
                if emit_image is not None:
                    emit_image(item, out)
            else:
                if render_block is not None:
                    render_block(item, out)

    def is_footnote_aside(self, tag):
        """现代 Sphinx 脚注定义容器：aside[role=doc-footnote] / .footnote。"""
        role = tag.get('role') or ''
        cls = ' '.join(tag.get('class') or [])
        return (tag.name == 'aside'
                and ('doc-footnote' in role or 'footnote' in cls.split()))

    def footnote_aside_lines(self, tag):
        """把脚注 aside 渲染为脚注定义条目（[FOOTNOTE-LIST] 组）。

        标签定位与正文行内序列化分离：标签常包在 `.label` 容器内（Sphinx
        多为 `<span class="label"><a role="doc-backlink">[1]</a></span>`），
        取该元素的纯文字匹配裸数字标签——整段行内序列化会把标签锚点
        变成 Markdown 链接使正则失配；正文对移除标签节点后的深拷贝复用
        render_inline（行内代码/公式/链接保真，R9 脚注定义内容保留）。
        无 `.label` 元素时回退到渲染文本正则，标签匹配须容忍括号内空白
        与全半角括号，不得据此丢弃脚注正文。
        """
        label_re = r'^[\[(]\s*(\d+)\s*[\])]'
        label_tag = tag.find(class_='label')
        if label_tag is not None:
            label_text = label_tag.get_text(' ', strip=True)
            match = re.match(label_re + r'\s*$', label_text)
            label = match.group(1) if match else label_text[:10] or '?'
            copied = copy.deepcopy(tag)
            copied.find(class_='label').decompose()
            body = self.render_inline(copied).strip()
        else:
            text = self.render_inline(tag)
            match = re.match(label_re + r'\s*(.*)$', text)
            label = match.group(1) if match else text.strip()[:10] or '?'
            body = match.group(2).strip() if match else ''
        return ['\n[FOOTNOTE-LIST]', '  [[%s]] %s' % (label, body)]

    def cell_fences(self, cell):
        """按文档顺序返回表格单元格内的代码围栏（受保护占位与字面 pre）。"""
        fences = []
        for node in cell.descendants:
            fenced = self.fenced_pre(node)
            if fenced is not None:
                fences.append(fenced)
            elif isinstance(node, Tag) and node.name == 'pre':
                text = clean_code_html(node.decode_contents())
                fences.append('\n```\n' + text.rstrip('\n') + '\n```')
        return fences

    def fenced_pre(self, node):
        """把受保护的 `<pre>` 注释恢复为代码围栏；非占位返回 ``None``。"""
        if not isinstance(node, Comment):
            return None
        match = re.match(r'\s*__TECHDOC_PRE_(\d+)__\s*', node)
        if not match:
            return None
        text = self._pre_blocks[int(match.group(1))]
        return '\n```\n' + text.rstrip('\n') + '\n```'

    @staticmethod
    def _span_guard(cell, attr, row_no, col_no):
        """跨行/跨列属性检查：缺省或 1 放行，其余定位并阻断。"""
        raw = cell.get(attr)
        if raw is None:
            return
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            value = None
        if value != 1:
            raise TableStructureError(
                '表格第 %d 行第 %d 列含 %s=%r，跨行/跨列无法可靠表示，'
                '已阻断分派' % (row_no, col_no, attr, raw))

    def table_block(self, tag):
        """渲染简单表格；单元格内代码以可回查的行列定位单独输出。

        输出 [TABLE] 行保留单元格文本与表头分隔行；单元格中的代码围栏
        跟在表格之后，用 `[TABLE-CODE r=行 c=列#序]` 标注原表格第几行第
        几格（1 起，含表头行）。任一单元格含无法可靠表示的跨行/跨列时
        抛出 TableStructureError，不静默展平。
        """
        caption = tag.find('caption')
        if caption is not None and caption.find_parent('table') is tag:
            caption_text = self.render_inline(caption)
            if caption_text:
                # 表题可含行内代码/公式，随表格渲染参与内容流对账
                lines = ['\n[TABLE-CAPTION] %s #' % caption_text]
            else:
                lines = []
        else:
            lines = []
        rows = []
        code_entries = []
        for row in tag.find_all('tr'):
            if row.find_parent('table') is not tag:
                continue  # 嵌套表格的行属于其自身表格
            row_no = len(rows) + 1
            cells = []
            col_no = 0
            for cell in row.find_all(['td', 'th']):
                if cell.find_parent('table') is not tag:
                    continue
                col_no += 1
                self._span_guard(cell, 'colspan', row_no, col_no)
                self._span_guard(cell, 'rowspan', row_no, col_no)
                cells.append(self.render_inline(cell))
                for order, fenced in enumerate(self.cell_fences(cell),
                                               start=1):
                    code_entries.append((row_no, col_no, order, fenced))
            if cells:
                rows.append(cells)
        lines.append('\n[TABLE]')
        for index, cells in enumerate(rows):
            line = ' | '.join(cells)
            if line.startswith('#'):
                # 首格为 #（序号列）时整行会被 Markdown 标题扫描误判；
                # 前置一个空格保持列界（两侧归一后内容不变）
                line = ' ' + line
            elif line == '':
                # 单列全空格行输出单个空格，与块间零长空行区分
                line = ' '
            lines.append(line)
            if index == 0:
                lines.append(' | '.join(['---'] * len(cells)))
        for row_no, col_no, order, fenced in code_entries:
            lines.append('')
            lines.append('[TABLE-CODE r=%d c=%d#%d]' % (row_no, col_no, order))
            lines.append(fenced)
        return lines

    def definition_list(self, tag, render_block=None, emit_image=None):
        """渲染定义列表；dd 内嵌代码等块级内容按源序保留在条目内。"""
        terms = tag.find_all('dt', recursive=False)
        is_footnote = terms and all(
            re.fullmatch(r'\[\d+\]|\(\d+\)|\d+', term.get_text(strip=True))
            for term in terms
        )
        lines = [
            '\n[FOOTNOTE-LIST]' if is_footnote else '\n[DEF-LIST]'
        ]
        for term, definition in zip(tag.find_all('dt'), tag.find_all('dd')):
            # 非脚注术语按行内语义序列化：术语中的行内代码等语义保留
            term_text = (term.get_text(' ', strip=True) if is_footnote
                         else self.render_inline(term))
            if is_footnote:
                bullet = '  [%s] ' % term_text
            else:
                bullet = '  **%s** ' % term_text
            before = len(lines)
            self.rich_container_lines(
                definition, lines, bullet=bullet, indent='  ',
                render_block=render_block, emit_image=emit_image)
            if len(lines) == before:
                lines.append(bullet.rstrip())  # 空定义仍保留条目占位
        return lines
