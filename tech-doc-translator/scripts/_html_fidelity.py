"""HTML 提取器共享的保真实现。

本文件是内部模块；各源家族 adapter 继续负责树遍历及差异化规则。
"""
import copy
import html
import re

from bs4 import BeautifulSoup, Comment


class HtmlFidelity:
    """保护代码并渲染各源家族一致的 Markdown 结构。"""

    def __init__(self, unknown_footnote='[?]'):
        self._pre_blocks = []
        self._unknown_footnote = unknown_footnote

    def parse(self, raw):
        """保护代码内容后解析 HTML；每次调用重置 `<pre>` 占位池。"""
        self._pre_blocks = []

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
        return BeautifulSoup(protected, 'html.parser')

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
