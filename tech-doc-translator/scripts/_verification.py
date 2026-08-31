"""译文校验器共享的 Markdown 结构扫描实现。

本文件是内部模块；各源家族 adapter 继续定义自己的通过条件和报告文案。
"""
import os
import re
from dataclasses import dataclass


_BLOCK_PLACEHOLDER = re.compile(r'^\[([A-Z][A-Z0-9_-]*)\]\s', re.M)
_IMAGE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_LINK = re.compile(r'(?<!!)\[(?:\\.|[^\\\]])+\]\(([^)]+)\)')


@dataclass(frozen=True)
class FenceScan:
    blocks: tuple
    boundary_count: int
    balanced: bool


def normalize(text):
    """统一空白和英文弯引号，供标题比较使用。"""
    return re.sub(r'\s+', ' ', text.replace('\u2019', "'").strip())


def strip_chinese_suffix(text):
    """去掉标题中第一个全角 `（` 及之后的内容。"""
    index = text.find('（')
    return text[:index].strip() if index >= 0 else text.strip()


def heading_lines(text, ignore_fences=False, strip_lines=False):
    """按顺序返回 Markdown 标题 ``(级别, 原始文本)``。"""
    headings = []
    in_fence = False
    for line in text.splitlines():
        candidate = line.strip() if strip_lines else line
        if ignore_fences and candidate.startswith('```'):
            in_fence = not in_fence
            continue
        if ignore_fences and in_fence:
            continue
        match = re.match(r'^(#{1,6})\s+(.+)$', candidate)
        if match:
            headings.append((len(match.group(1)), match.group(2)))
    return headings


def scan_fences(text, strip_lines=True):
    """扫描三反引号围栏，返回内容、边界数和配对状态。"""
    blocks = []
    current = None
    in_fence = False
    boundary_count = 0
    for line in text.split('\n'):
        candidate = line.strip() if strip_lines else line
        if candidate.startswith('```'):
            boundary_count += 1
            if not in_fence:
                in_fence = True
                current = []
            else:
                blocks.append('\n'.join(current))
                current = None
                in_fence = False
            continue
        if in_fence:
            current.append(line)
    return FenceScan(tuple(blocks), boundary_count, not in_fence)


def literal_fence_count(text):
    """返回文本中三反引号字面量的数量。"""
    return text.count('```')


def image_sources(text):
    """按文档顺序返回 Markdown 图片引用。"""
    return _IMAGE.findall(text)


def link_targets(text):
    """按文档顺序返回 Markdown 非图片链接目标。"""
    return _LINK.findall(text)


def invalid_math_delimiters(text):
    """逐次返回嵌套在 Markdown 定界符中的 LaTeX 定界符模式。"""
    patterns = (r'\$\\\(', r'\\\)\$', r'\$\$\s*\\\[', r'\\\]\s*\$\$')
    return [pattern for pattern in patterns
            for _ in re.finditer(pattern, text)]


def invalid_math_expressions(text):
    """返回使用嵌套 Markdown/LaTeX 定界符的完整公式原文。"""
    patterns = (
        r'\$\\\([^$\n]*?\\\)\$',
        r'\$\$\s*\\\[[\s\S]*?\\\]\s*\$\$',
    )
    return [match.group(0) for pattern in patterns
            for match in re.finditer(pattern, text)]


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
