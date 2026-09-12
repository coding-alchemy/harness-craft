"""HTML 提取器共享的保真实现。

本文件是内部模块；各源家族 adapter 继续负责树遍历及差异化规则。
"""
import copy
import html
import json
import os
import re

from bs4 import BeautifulSoup, Comment


# 内联 CSS width 属性（仅取 width 声明；max-width 等不作为显示宽度依据）。
_INLINE_WIDTH_RE = re.compile(
    r'(?:^|;)\s*width\s*:\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z%]*)\s*(?:;|$)')
_INTEGER_RE = re.compile(r'^[0-9]+$')
_INLINE_PX_WIDTH_RE = re.compile(
    r'(?:^|;)\s*width\s*:\s*([0-9]*\.?[0-9]+)px\s*(?:;|$)', re.I)

DISPLAY_MAP_VERSION = 1


def image_display_width(img, soup):
    """提取 img 节点的显示宽度，返回 entry 字典（不含出现序号与路径）。

    依据优先级：可解析的内联 CSS width，再 HTML width 属性（按整数像素）。
    百分比必须记录可确定的参照容器（祖先链中最近的内联像素宽度），否则
    作为“百分比无参照”单列，不冒充已恢复。无宽度约束同样单列。返回的
    basis/undetermined_reason 可回查到源节点定位。
    """
    node = 'img[%d]' % list(soup.find_all('img')).index(img) if soup is not None else 'img[?]'
    style = img.get('style') or ''
    match = _INLINE_WIDTH_RE.search(style)
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or 'px').lower()
        if unit == 'px':
            return {'value': value, 'unit': 'px', 'basis': 'inline-css-width',
                    'reference': None, 'source_node': node}
        if unit == '%':
            reference = _percent_reference(img)
            if reference is not None:
                return {'value': value, 'unit': '%', 'basis': 'inline-css-width',
                        'reference': reference, 'source_node': node}
            return {'undetermined_reason': '百分比宽度缺少可确定的参照容器',
                    'source_node': node}
        return {'undetermined_reason': '内联 CSS width 使用不支持的单位：%s' % unit,
                'source_node': node}
    width_attr = img.get('width')
    if width_attr and _INTEGER_RE.match(str(width_attr).strip()):
        return {'value': float(str(width_attr).strip()), 'unit': 'px',
                'basis': 'html-width-attribute', 'reference': None,
                'source_node': node}
    return {'undetermined_reason': '源节点无宽度约束', 'source_node': node}


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


class HtmlFidelity:
    """保护代码并渲染各源家族一致的 Markdown 结构。"""

    def __init__(self, unknown_footnote='[?]'):
        self._pre_blocks = []
        self._unknown_footnote = unknown_footnote
        self.image_display = []  # 按输出顺序登记的图片显示尺寸条目
        self._soup = None

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

    def note_image(self, img, src_as_written):
        """登记一个进入输出的图片出现及其源显示宽度（暗亮只记选中版本）。"""
        entry = image_display_width(img, self._soup)
        entry['occurrence'] = len(self.image_display) + 1
        entry['image'] = src_as_written
        self.image_display.append(entry)

    def write_display_map(self, out_md_path, snapshot_path):
        """把解析期登记的显示尺寸写入 <stem>.images_display.json。

        有条目才写文件；条目与未确定项分开列示，供翻译与导出链路对账。
        """
        determined = [
            {'occurrence': e['occurrence'], 'image': e['image'],
             'width': {'value': e['value'], 'unit': e['unit'],
                       'basis': e['basis'], 'reference': e['reference']},
             'source_node': e['source_node']}
            for e in self.image_display if 'value' in e
        ]
        undetermined = [
            {'occurrence': e['occurrence'], 'image': e['image'],
             'reason': e['undetermined_reason'], 'source_node': e['source_node']}
            for e in self.image_display if 'undetermined_reason' in e
        ]
        if not self.image_display:
            return None
        payload = {
            'version': DISPLAY_MAP_VERSION,
            'markdown': os.path.basename(out_md_path),
            'snapshot': snapshot_path,
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
