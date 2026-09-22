"""HTML 提取器共享的保真实现。

本文件是内部模块；各源家族 adapter 继续负责树遍历及差异化规则。
"""
import copy
import html
import json
import os
import re

from bs4 import BeautifulSoup, Comment

from _verification import file_sha256, resource_identity_digest


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
            return {'undetermined_reason': '百分比宽度缺少可确定的参照容器',
                    'source_node': node}
        return {'undetermined_reason': '内联 CSS width 使用不支持的单位：%s' % unit,
                'source_node': node}
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
    return {'undetermined_reason': '源节点无宽度约束', 'source_node': node}


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


def _derived_width_from_height(img, src, snapshot_dir, node):
    """高度推导宽度：仅无可用宽度时尝试；不确定一律给出原因返回 None。"""
    height_px, meta = _height_constraint(img)
    if height_px is None:
        if meta is not None:  # 有高度约束但不可用（单位/冲突），原因保留
            return {'undetermined_reason': meta, 'source_node': node}
        return None  # 完全无约束；由无宽度约束条目兜底
    if snapshot_dir is None:
        return {'undetermined_reason': '高度推导需要快照资源定位（缺少快照目录）',
                'source_node': node}
    path, reason = resolve_snapshot_resource(src, snapshot_dir)
    if path is None:
        return {'undetermined_reason': '高度推导失败: %s' % reason,
                'source_node': node}
    ratio, aspect_source = intrinsic_aspect_ratio(path)
    if ratio is None:
        return {'undetermined_reason': '高度推导失败: %s' % aspect_source,
                'source_node': node, 'height': meta}
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
         **({'height': e['height']} if 'height' in e else {})}
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
        self.snapshot_dir = snapshot_dir  # 快照 HTML 所在目录（高度推导用）

    def parse(self, raw):
        """保护代码内容后解析 HTML；每次调用重置 `<pre>` 占位池。"""
        self._pre_blocks = []
        self.image_display = []

        def protect_pre(match):
            body = match.group(2)
            body = re.sub(r'^\s*<code[^>]*>\s*', '', body, flags=re.S)
            body = re.sub(r'\s*</code>\s*$', '', body, flags=re.S)
            # Sphinx/Pygments 使用 span 标注 token；仅移除已知高亮标签，
            # 绝不以泛匹配吞掉 CUDA/C++ 代码中的 <...> 语法。
            body = re.sub(r'</?(?:span|div|a|em|strong)(?:\s[^>]*)?>', '',
                          body, flags=re.I)
            body = html.unescape(body)
            index = len(self._pre_blocks)
            self._pre_blocks.append(body)
            return '<!-- __TECHDOC_PRE_%d__ -->' % index

        def protect_inline_code(match):
            body = match.group(2).replace('<', '&lt;').replace('>', '&gt;')
            return match.group(1) + body + match.group(3)

        protected = re.sub(
            r'(<pre[^>]*>)(.*?)(</pre>)', protect_pre, raw, flags=re.S)
        protected = re.sub(
            r'(<code[^>]*>)(.*?)(</code>)', protect_inline_code,
            protected, flags=re.S)
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
        供回补/绑定与导出核验独立复核，不依赖本地摘要自证。
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
            'snapshot': snapshot_path,
            'snapshot_sha256': snapshot_digest,
            'entries': determined,
            'undetermined': undetermined,
        }
        path = os.path.splitext(out_md_path)[0] + '.images_display.json'
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def clean_heading(text):
        """去掉 Sphinx headerlink 带来的 ¶ 与链接图标。"""
        return text.replace('¶', '').replace('\uf0c1', '').strip()

    def render_inline(self, element):
        """渲染行内节点，保留公式、链接与脚注引用。"""
        copied = copy.copy(element)
        for math in copied.find_all('span', class_='math'):
            body = math.get_text().strip()
            if body.startswith(r'\(') and body.endswith(r'\)'):
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
        for link in copied.find_all('a', href=True):
            label = link.get_text(' ', strip=True)
            href = link.get('href', '').strip()
            if label and href:
                label = label.replace('[', r'\[').replace(']', r'\]')
                link.replace_with('[%s](%s)' % (label, href))
        text = copied.get_text(' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r' ([.,;:!?)\]])', r'\1', text)
        text = re.sub(r'([\[(]) ', r'\1', text)
        return text.strip()

    def fenced_pre(self, node):
        """把受保护的 `<pre>` 注释恢复为代码围栏；非占位返回 ``None``。"""
        if not isinstance(node, Comment):
            return None
        match = re.match(r'\s*__TECHDOC_PRE_(\d+)__\s*', node)
        if not match:
            return None
        text = self._pre_blocks[int(match.group(1))]
        return '\n```\n' + text.rstrip('\n') + '\n```'

    def table_block(self, tag):
        """渲染各源家族通用的简单表格。"""
        lines = ['\n[TABLE]']
        for index, row in enumerate(tag.find_all('tr')):
            cells = [
                self.render_inline(cell)
                for cell in row.find_all(['td', 'th'])
            ]
            if not cells:
                continue
            lines.append(' | '.join(cells))
            if index == 0:
                lines.append(' | '.join(['---'] * len(cells)))
        return lines

    def definition_list(self, tag):
        """渲染不含源家族专有嵌套块的定义列表。"""
        terms = tag.find_all('dt', recursive=False)
        is_footnote = terms and all(
            re.fullmatch(r'\[\d+\]|\(\d+\)|\d+', term.get_text(strip=True))
            for term in terms
        )
        lines = [
            '\n[FOOTNOTE-LIST]' if is_footnote else '\n[DEF-LIST]'
        ]
        for term, definition in zip(tag.find_all('dt'), tag.find_all('dd')):
            term_text = term.get_text(' ', strip=True)
            definition_text = self.render_inline(definition)
            if is_footnote:
                lines.append('  [%s] %s' % (term_text, definition_text))
            else:
                lines.append('  **%s** %s' % (term_text, definition_text))
        return lines
