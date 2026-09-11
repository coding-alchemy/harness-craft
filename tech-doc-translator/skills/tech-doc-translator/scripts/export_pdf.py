#!/usr/bin/env python3
"""tech-doc-translator PDF 导出入口。

把一个或多个有序 Markdown 文档转换为单个 PDF：
    python3 export_pdf.py --output <候选.pdf> --work-dir <临时目录> <章节1.md> [...]

输入与原始资源只读；组合 HTML、来源映射、机器检查证据与 PDF 候选都写入
--work-dir。只有全部机器检查通过后，候选才会复制到 --output；失败时不
触碰 --output 上已有文件。所有引用资源以 data URI 内联，渲染阶段拦截
外部网络请求，转换可离线完成。
"""
import argparse
import base64
import hashlib
import json
import mimetypes
import re
import shutil
import sys
import unicodedata
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "pdf"
REPORT_NAME = "export_report.json"
CANDIDATE_NAME = "candidate.pdf"
HTML_NAME = "combined.html"

EXTERNAL_IMAGE_SCHEMES = ("http", "https", "ftp")

# 机器检查通过后写出的状态；不代表成品已通过视觉复核。
STATUS_MACHINE_PASS = "machine-pass-pending-visual"
STATUS_MACHINE_FAIL = "machine-fail"


class ExportError(Exception):
    """阻断导出的输入或环境问题。"""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Markdown 解析层（verify_pdf.py 复用同一解析，另用独立原始扫描交叉核对）
# ---------------------------------------------------------------------------

LEGACY_INLINE_RE = re.compile(r"\\\((.*)\\\)", re.S)
LEGACY_DISPLAY_RE = re.compile(r"\\\[(.*)\\\]", re.S)


def classify_math(content, display_mode):
    """识别历史数学包装，返回 (latex, mode, original_form)。

    真实译文存在 $\\(...\\)$ 行内与 $\\[...\\]$ 块级包装；按数学含义在导出层
    剥离包装，保留 original_form 供逐项对照。无法识别时按原内容处理。
    """
    text = content.strip()
    if display_mode:
        return text, "display", "dollar_block"
    match = LEGACY_DISPLAY_RE.fullmatch(text)
    if match:
        return match.group(1).strip(), "display", "legacy_bracket"
    match = LEGACY_INLINE_RE.fullmatch(text)
    if match:
        return match.group(1).strip(), "inline", "legacy_paren"
    return text, "inline", "dollar_inline"


def build_markdown(math_sink, chapter_prefix):
    """构造按本章作用域工作的解析器；math_sink 收集公式条目。"""
    def render_math(content, env):
        latex, mode, original_form = classify_math(
            content, env.get("display_mode", False)
        )
        index = len(math_sink)
        dom_id = "%sm%04d" % (chapter_prefix, index)
        math_sink.append(
            {
                "id": dom_id,
                "latex": latex,
                "mode": mode,
                "original_form": original_form,
                "source": content,
            }
        )
        tag = "div" if mode == "display" else "span"
        css = "math-block" if mode == "display" else "math-inline"
        return '<%s class="%s" id="%s" data-tex="%s" data-mode="%s"></%s>' % (
            tag,
            css,
            dom_id,
            escape(latex, quote=True),
            mode,
            tag,
        )

    markdown = MarkdownIt("commonmark", {"html": False})
    markdown.enable("table")
    markdown.enable("strikethrough")
    markdown.use(
        dollarmath_plugin,
        allow_labels=False,
        allow_space=False,
        allow_digits=False,
        double_inline=False,
        renderer=render_math,
    )
    markdown.use(footnote_plugin)
    markdown.core.ruler.before("inline", "pdf_deep_headings", split_deep_headings)
    markdown.inline.ruler.before("html_inline", "pdf_anchor", parse_anchor)
    markdown.add_render_rule("pdf_anchor", render_anchor)

    formatter = HtmlFormatter(nowrap=False, style="default")

    def render_fence(_renderer, tokens, idx, options, env):
        token = tokens[idx]
        info = (token.info or "").strip().split()[0] if token.info.strip() else ""
        try:
            lexer = get_lexer_by_name(info or "text", stripnl=False, ensurenl=False)
            body = pygments_highlight(token.content, lexer, formatter)
        except ClassNotFound:
            body = "<pre><code>%s</code></pre>" % escape(token.content)
        return body

    markdown.add_render_rule("fence", render_fence)
    return markdown, formatter


# ---------------------------------------------------------------------------
# 章节模型与目标映射
# ---------------------------------------------------------------------------

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")
# 仅识别内容为空的锚点元素；带内容的 HTML 在 html=False 下按转义文本保留。
ANCHOR_TAG_RE = re.compile(
    r"<a\s+[^>]*?\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"'][^>]*>\s*</a>",
    re.I,
)
DEEP_HEADING_RE = re.compile(r"^(#{7,})\s+(.+?)\s*$")

def parse_anchor(state, silent):
    """只允许空锚点；代码和转义由此前的行内规则处理。"""
    match = ANCHOR_TAG_RE.match(state.src, state.pos)
    if match is None:
        return False
    if not silent:
        token = state.push("pdf_anchor", "a", 0)
        token.attrSet("id", match.group(1))
    state.pos = match.end()
    return True


def render_anchor(_renderer, tokens, idx, options, env):
    return '<a id="%s"></a>' % escape(tokens[idx].attrGet("id"), quote=True)


def split_deep_headings(state):
    """在块解析后拆分 H7+，让标题与正文共享引用、脚注的行内解析环境。

    仅拆分段落 token；围栏、缩进代码不参与。先用隔离环境探测整段行内
    代码，避免把跨行代码中的井号拆成标题。此阶段不渲染，也不收集公式。
    """
    result = []
    index = 0
    while index < len(state.tokens):
        opening = state.tokens[index]
        if (opening.type != "paragraph_open" or index + 2 >= len(state.tokens)
                or state.tokens[index + 1].type != "inline"):
            result.append(opening)
            index += 1
            continue
        inline = state.tokens[index + 1]
        lines = inline.content.split("\n")
        headings = {}
        for number, line in enumerate(lines):
            match = DEEP_HEADING_RE.match(line)
            if not match:
                continue
            marker = "PDFDEEPPROBE"
            while marker in inline.content:
                marker += "X"
            probe = lines.copy()
            probe[number] = marker + line[match.end(1):]
            tokens = state.md.parseInline("\n".join(probe), {})[0].children or []
            if any(t.type == "code_inline" and marker in t.content for t in tokens):
                continue
            headings[number] = match
        if not headings:
            result.extend(state.tokens[index:index + 3])
        else:
            def append_block(start, end, match=None):
                tag = "h6" if match else "p"
                kind = "heading" if match else "paragraph"
                first = Token(kind + "_open", tag, 1)
                body = Token("inline", "", 0)
                last = Token(kind + "_close", tag, -1)
                first.level = last.level = opening.level
                body.level = inline.level
                first.map = [opening.map[0] + start, opening.map[0] + end]
                body.map = first.map.copy()
                body.content = match.group(2) if match else "\n".join(lines[start:end])
                body.children = []
                if match:
                    first.attrSet("data-source-level", str(len(match.group(1))))
                else:
                    first.hidden = last.hidden = opening.hidden
                result.extend((first, body, last))
            start = 0
            for number, match in headings.items():
                if number > start:
                    append_block(start, number)
                append_block(number, number + 1, match)
                start = number + 1
            if start < len(lines):
                append_block(start, len(lines))
        index += 3
    state.tokens = result


def find_source_line(chapter, needle, start=0):
    """在原始 Markdown 中定位诊断位置（1 起）；找不到返回 None。"""
    if not needle:
        return None
    lines = chapter.text.splitlines()
    for index in range(start, len(lines)):
        if needle in lines[index]:
            return index + 1
    return None


def github_slug(text):
    """GitHub 风格标题 slug：小写、去标点、空白转连字符、保留 CJK。"""
    result = []
    for char in text.strip().lower():
        if char == " ":
            result.append("-")
        elif char in "-_":
            result.append(char)
        else:
            category = unicodedata.category(char)
            if category[0] in ("L", "N"):
                result.append(char)
    return "".join(result)


class Chapter:
    def __init__(self, index, source_path):
        self.index = index
        self.prefix = "ch%02d-" % index
        self.path = source_path
        self.dir = source_path.parent
        self.text = source_path.read_text(encoding="utf-8")
        self.math = []
        self.headings = []  # {level, text, slug, id}
        self.targets = {}  # 未加前缀片段 -> 描述（用于链接消解）
        self.internal_links = []  # {fragment, kind, source_line}
        self.external_links = []  # href
        self.range_out_links = []  # {href, source_line, exists}
        self.images = []  # {src, path, sha256, bytes}
        self.image_srcs = []  # 解析层记录的图片引用（核验交叉核对用）
        self.footnote_labels = []  # 原始 [^label]
        self.code_blocks = []  # 代码原文
        self.blocks = []  # 文本块（正文、标题、单元格），用于核验
        self.slug_duplicates = []  # 同章重复标题 slug 的原文
        self.source_anchors = []  # 显式锚点 id（未加前缀）
        self.soup = None
        self.pygments_css = ""
        self.html = ""


def parse_chapter(chapter):
    """解析单章并渲染为带前缀的 HTML 片段。"""
    markdown, formatter = build_markdown(chapter.math, chapter.prefix)
    raw_html = markdown.render(chapter.text)
    soup = BeautifulSoup(raw_html, "html.parser")
    for anchor in soup.find_all("a", id=True, href=False):
        chapter.targets.setdefault(anchor["id"], {"kind": "anchor"})
        chapter.source_anchors.append(anchor["id"])

    # 1) 解析器生成的既有 id（脚注等）统一加章前缀，避免跨章冲突。
    for element in soup.find_all(id=True):
        element["id"] = chapter.prefix + element["id"]

    # 2) 标题补 slug id；同章重复标题按 GitHub 规则追加 -N 别名并显式报告。
    slug_seen = {}
    chapter.slug_duplicates = []
    for tag in soup.find_all(HEADING_TAGS):
        text = tag.get_text().strip()
        slug = github_slug(text)
        count = slug_seen.get(slug, 0)
        slug_seen[slug] = count + 1
        alias = slug if count == 0 else "%s-%d" % (slug, count)
        if count > 0:
            chapter.slug_duplicates.append(text[:60])
        dom_id = chapter.prefix + alias
        tag["id"] = dom_id
        source_level = tag.get("data-source-level")
        chapter.headings.append(
            {
                "level": int(tag.name[1]),
                "text": text,
                "segments": block_text_segments(tag),
                "slug": alias,
                "id": dom_id,
                "source_level": int(source_level) if source_level else None,
            }
        )
        chapter.targets[alias] = {"kind": "heading", "level": int(tag.name[1])}

    # 3) 脚注目标也注册为可跳转片段（id 已加前缀，注册时用未前缀原名）。
    for element in soup.find_all(id=True):
        raw = element["id"]
        if raw.startswith(chapter.prefix):
            fragment = raw[len(chapter.prefix):]
            if fragment not in chapter.targets:
                chapter.targets[fragment] = {"kind": "anchor"}

    chapter.soup = soup
    chapter.pygments_css = formatter.get_style_defs(".highlight")
    return chapter


MATH_SENTINEL = "\uFFF9"


def _collect_text(node, parts):
    from bs4 import NavigableString, Tag

    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.get("data-tex") is not None:
                parts.append(MATH_SENTINEL)
            else:
                _collect_text(child, parts)


def block_text_segments(element):
    """按公式节点把块内文本切成段。

    KaTeX 的 MathML 文本在 PDF 提取时会插在句子中间，整块连续匹配会误报；
    公式本身用浏览器层逐项检查，文本对账只针对公式之间的文字段。
    """
    parts = []
    _collect_text(element, parts)
    return "".join(parts).split(MATH_SENTINEL)


def walk_text_blocks(soup):
    """收集正文文本块（段落、标题、列表项、引用、表格单元格）及其分段。"""
    blocks = []
    for element in soup.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "th", "td"]
    ):
        if element.find(["p", "ul", "ol", "table", "pre"]):
            continue  # 容器元素，等叶子节点自己出现
        segments = block_text_segments(element)
        text = " ".join(s.strip() for s in segments if s.strip())
        if text:
            blocks.append({"text": text, "segments": segments})
    return blocks


# ---------------------------------------------------------------------------
# 链接与图片处理
# ---------------------------------------------------------------------------

def resolve_links(chapter, chapters, diagnostics):
    soup = chapter.soup
    own_prefix = chapter.prefix

    def resolve_fragment(fragment):
        """返回 (加前缀片段, 状态)；状态为 ok/missing/ambiguous。"""
        if fragment in chapter.targets:
            return own_prefix + fragment, "ok"
        owners = [c for c in chapters if fragment in c.targets]
        if not owners:
            return None, "missing"
        if len(owners) > 1:
            return None, "ambiguous"
        return owners[0].prefix + fragment, "ok"

    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if href is None:
            continue
        line = find_source_line(chapter, "](%s)" % href) or find_source_line(
            chapter, "](%s)" % unquote(href)
        )
        if href.startswith("#"):
            fragment = unquote(href[1:])
            new_fragment, status = resolve_fragment(fragment)
            if status == "ok":
                anchor["href"] = "#" + new_fragment
                chapter.internal_links.append(
                    {
                        "fragment": fragment,
                        "resolved": new_fragment,
                        "source_line": line,
                        "text": anchor.get_text(strip=True)[:80],
                    }
                )
            else:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "broken-internal-link",
                        "message": "内部链接目标无法消解（%s）：%s"
                    % (status, fragment),
                        "input": str(chapter.path),
                        "line": line,
                        "link_text": anchor.get_text(strip=True)[:80],
                    }
                )
                anchor["href"] = "#" + fragment  # 保持文本与原样，交给人工复核
            continue
        scheme = urlsplit(href).scheme.lower()
        if scheme in ("http", "https", "mailto"):
            chapter.external_links.append(href)
            continue
        if scheme in EXTERNAL_IMAGE_SCHEMES:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "external-link-unsupported",
                    "message": "非 HTTP(S) 外链未纳入支持范围：%s" % href,
                    "input": str(chapter.path),
                    "line": line,
                }
            )
            continue
        # 本地相对链接：可带片段（b.md#target）。指向已纳入章节时转为该章
        # 内部目标；其余为范围外文件并显式报告。
        path_part, _, raw_fragment = href.partition("#")
        fragment = unquote(raw_fragment) if raw_fragment else None
        target = (chapter.dir / unquote(path_part)).resolve()
        included = next((c for c in chapters if c.path == target), None)
        if included is not None:
            if fragment is None:
                if included.headings:
                    resolved_id = included.headings[0]["id"]
                    fragment_label = included.headings[0]["slug"]
                else:
                    # 无标题章节：跳转到章容器（组合 HTML 中每章的 section）。
                    resolved_id = included.prefix + "body"
                    fragment_label = included.path.stem
            elif fragment in included.targets:
                resolved_id = included.prefix + fragment
                fragment_label = fragment
            else:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "broken-internal-link",
                        "message": "跨章链接片段在目标章节中不存在：%s#%s"
                        % (path_part, fragment),
                        "input": str(chapter.path),
                        "line": line,
                    }
                )
                continue
            anchor["href"] = "#" + resolved_id
            chapter.internal_links.append(
                {
                    "fragment": fragment_label,
                    "resolved": resolved_id,
                    "source_line": line,
                    "text": anchor.get_text(strip=True)[:80],
                }
            )
            continue
        chapter.range_out_links.append(
            {
                "href": href,
                "source_line": line,
                "exists": target.exists(),
                "resolved_path": str(target),
                "text": anchor.get_text(strip=True)[:80],
            }
        )


def inline_images(chapter, diagnostics, resource_registry):
    soup = chapter.soup
    for image in soup.find_all("img"):
        src = image.get("src")
        if src is None:
            continue
        line = find_source_line(chapter, "](%s)" % src)
        scheme = urlsplit(src).scheme.lower()
        if scheme in EXTERNAL_IMAGE_SCHEMES:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "external-image",
                    "message": "外部图片需先本地化后导出：%s" % src,
                    "input": str(chapter.path),
                    "line": line,
                }
            )
            continue
        path = (chapter.dir / unquote(src)).resolve()
        if not path.is_file():
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "missing-image",
                    "message": "图片不存在：%s" % src,
                    "input": str(chapter.path),
                    "line": line,
                }
            )
            image.decompose()
            continue
        digest = sha256_file(path)
        key = str(path)
        if key not in resource_registry:
            mime = mimetypes.guess_type(str(path))[0]
            if not mime:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "unknown-image-type",
                        "message": "无法识别图片类型：%s" % path.name,
                        "input": str(chapter.path),
                        "line": line,
                    }
                )
                image.decompose()
                continue
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
            resource_registry[key] = {
                "path": str(path),
                "sha256": digest,
                "bytes": path.stat().st_size,
                "mime": mime,
                "data_uri": "data:%s;base64,%s" % (mime, payload),
            }
        record = resource_registry[key]
        image["src"] = record["data_uri"]
        chapter.images.append(
            {k: record[k] for k in ("path", "sha256", "bytes")}
            | {"src": src, "source_line": line}
        )


# ---------------------------------------------------------------------------
# HTML 组装与浏览器渲染
# ---------------------------------------------------------------------------

CHECK_SCRIPT = """
(async () => {
  const checks = {katex: [], images: [], fonts: {}, overflow: [],
                  scrollWidth: 0, clientWidth: 0, mathTotal: 0};
  const nodes = document.querySelectorAll('[data-tex]');
  checks.mathTotal = nodes.length;
  nodes.forEach(n => {
    try {
      katex.render(n.dataset.tex, n,
                   {displayMode: n.dataset.mode === 'display',
                    throwOnError: true, strict: false, output: 'htmlAndMathml'});
      n.dataset.katexOk = '1';
    } catch (e) {
      n.classList.add('katex-error-node');
      checks.katex.push({id: n.id, message: String(e && e.message || e)});
    }
  });
  try { await document.fonts.ready; } catch (e) {}
  const probe = (family) => {
    try {
      return document.fonts.check('16px "' + family + '"', '中文等宽AgX1');
    } catch (e) { return false; }
  };
  ['STFangsong', 'STHeiti', 'Menlo'].forEach(
    f => { checks.fonts[f] = probe(f); });
  const images = Array.from(document.images);
  await Promise.all(images.map(img =>
    img.decode().catch(e =>
      checks.images.push({src: img.src.slice(0, 60), error: String(e)}))));
  images.forEach(img => {
    if (!img.complete || img.naturalWidth === 0) {
      checks.images.push({src: img.src.slice(0, 60), error: 'natural size 0'});
    }
  });
  const pageWidth = document.documentElement.clientWidth;
  document.querySelectorAll('table, pre, .math-block, img').forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && (rect.right > pageWidth + 1 || rect.left < -1)) {
      checks.overflow.push({
        tag: el.tagName, id: el.id || '',
        text: (el.textContent || '').trim().slice(0, 60),
        right: Math.round(rect.right), pageWidth: pageWidth});
    }
  });
  checks.scrollWidth = document.documentElement.scrollWidth;
  checks.clientWidth = pageWidth;
  window.__pdfExportChecks = checks;
  window.__pdfExportDone = true;
})();
"""


def file_uri(path):
    return Path(path).as_uri()


def build_document(chapters, title):
    katex_dir = ASSETS_DIR / "katex"
    for name in ("katex.min.css", "katex.min.js"):
        if not (katex_dir / name).is_file():
            raise ExportError("缺少离线 KaTeX 资产：%s" % (katex_dir / name))
    pygments_css = "\n".join(c.pygments_css for c in chapters if c.pygments_css)
    body = "\n".join(
        '<section class="chapter" id="%sbody">%s</section>' % (c.prefix, c.soup)
        for c in chapters
    )
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>%s</title>
<link rel="stylesheet" href="%s">
<link rel="stylesheet" href="%s">
<style>
%s
</style>
</head>
<body>
%s
<script src="%s"></script>
<script>%s</script>
</body>
</html>
""" % (
        escape(title),
        file_uri(katex_dir / "katex.min.css"),
        file_uri(ASSETS_DIR / "style.css"),
        pygments_css,
        body,
        file_uri(katex_dir / "katex.min.js"),
        CHECK_SCRIPT,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def load_inputs(paths):
    if not paths:
        raise ExportError("未提供任何输入 Markdown 文件")
    chapters = []
    seen = set()
    for index, raw in enumerate(paths, start=1):
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise ExportError("输入文件不存在：%s" % path)
        if path in seen:
            raise ExportError("输入文件重复或以不同拼写重复：%s" % path)
        seen.add(path)
        try:
            chapter = Chapter(index, path)
        except UnicodeDecodeError as exc:
            raise ExportError("输入不是 UTF-8 文本：%s（%s）" % (path, exc))
        chapters.append(chapter)
    return chapters


def collect_chapter_facts(chapter):
    chapter.blocks = walk_text_blocks(chapter.soup)
    soup = chapter.soup
    for code in soup.find_all("pre"):
        chapter.code_blocks.append(code.get_text())
    chapter.image_srcs = [
        img.get("src") for img in soup.find_all("img") if img.get("src")
    ]
    raw_text = chapter.text
    chapter.footnote_labels = sorted(set(re.findall(r"\[\^([^\]\s]+)\]", raw_text)))


def summarize_inputs(chapters):
    inputs = []
    resources = {}
    for chapter in chapters:
        inputs.append(
            {
                "path": str(chapter.path),
                "sha256": sha256_file(chapter.path),
                "bytes": chapter.path.stat().st_size,
                "index": chapter.index,
            }
        )
        for image in chapter.images:
            resources.setdefault(
                image["path"],
                {"path": image["path"], "sha256": image["sha256"], "bytes": image["bytes"]},
            )
    return inputs, sorted(resources.values(), key=lambda r: r["path"])


def export(paths, output, work_dir):
    work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = []
    report = {"diagnostics": diagnostics}

    try:
        chapters = load_inputs(paths)
    except ExportError as exc:
        report["status"] = STATUS_MACHINE_FAIL
        report["error"] = str(exc)
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1

    resource_registry = {}
    # 先完成全部章节解析，再做链接消解：跨章文件链接与片段链接都依赖
    # 所有章节的目标映射就绪。
    for chapter in chapters:
        parse_chapter(chapter)
        collect_chapter_facts(chapter)
    for chapter in chapters:
        resolve_links(chapter, chapters, diagnostics)
        inline_images(chapter, diagnostics, resource_registry)
        for text in chapter.slug_duplicates:
            diagnostics.append(
                {
                    "severity": "warn",
                    "code": "duplicate-heading-slug",
                    "message": "同章标题 slug 重复，链接按 GitHub 规则指向首次出现：%s"
                    % text,
                    "input": str(chapter.path),
                }
            )
        for heading in chapter.headings:
            if heading.get("source_level"):
                diagnostics.append(
                    {
                        "severity": "warn",
                        "code": "deep-heading-mapped",
                        "message": "超过 HTML 层级的标题已映射为 h6（原 %d 级，文字与相对位置保留）：%s"
                        % (heading["source_level"], heading["text"][:60]),
                        "input": str(chapter.path),
                    }
                )

    title = chapters[0].headings[0]["text"] if chapters[0].headings else chapters[0].path.stem
    document = build_document(chapters, title)
    html_path = work_dir / HTML_NAME
    html_path.write_text(document, encoding="utf-8")

    # 惰性导入：普通翻译环境不安装 playwright 时，导入本模块的其他脚本不受影响。
    from playwright.sync_api import sync_playwright

    browser_checks = {}
    candidate = work_dir / CANDIDATE_NAME
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        def block_network(route, request):
            if urlsplit(request.url).scheme in ("http", "https"):
                route.abort()
            else:
                route.continue_()

        context.route("**/*", block_network)
        page = context.new_page()
        page.goto(file_uri(html_path), wait_until="load")
        page.wait_for_function("window.__pdfExportDone === true", timeout=120000)
        browser_checks = page.evaluate("window.__pdfExportChecks")
        # Chromium 的 PDF 结构树不保留 KaTeX 的 MathML；仅在打印阶段让
        # 实际绘制的公式字形参与标记，否则纯公式章节会从结构树消失。
        page.evaluate("document.querySelectorAll('.katex-html').forEach("
                      "node => node.removeAttribute('aria-hidden'))")
        page.pdf(
            path=str(candidate),
            prefer_css_page_size=True,
            print_background=True,
            outline=True,
            tagged=True,
        )
        browser.close()

    inputs, resources = summarize_inputs(chapters)
    range_out = [
        link
        for chapter in chapters
        for link in chapter.range_out_links
    ]
    math_index = {
        m["id"]: m["latex"] for c in chapters for m in c.math
    }

    hard_failures = [
        d for d in diagnostics if d.get("severity") == "fail"
    ]
    fonts = browser_checks.get("fonts", {}) if browser_checks else {}
    # 正文与代码的 CJK 回退族必须至少一项可用，否则中文会退到不可控字体。
    cjk_font_ok = any(fonts.get(f, False) for f in ("STFangsong", "STHeiti"))
    machine_ok = (
        not hard_failures
        and browser_checks
        and not browser_checks.get("katex")
        and not browser_checks.get("images")
        and not browser_checks.get("overflow")
        and browser_checks.get("scrollWidth", 0) <= browser_checks.get("clientWidth", 0) + 1
        and cjk_font_ok
    )

    report.update(
        {
            "status": STATUS_MACHINE_PASS if machine_ok else STATUS_MACHINE_FAIL,
            "candidate": str(candidate),
            "pdf_sha256": sha256_file(candidate),
            "output_target": str(output),
            "browser_checks": browser_checks,
            "inputs": inputs,
            "resources": resources,
            "range_out_links": range_out,
            "chapters": [
                {
                    "index": c.index,
                    "path": str(c.path),
                    "sha256": sha256_file(c.path),
                    "prefix": c.prefix,
                    "headings": c.headings,
                    "math_total": len(c.math),
                    "math": [
                        {
                            "id": m["id"],
                            "mode": m["mode"],
                            "original_form": m["original_form"],
                            "latex": m["latex"],
                        }
                        for m in c.math
                    ],
                    "images": c.images,
                    "internal_links": c.internal_links,
                    "external_links": sorted(set(c.external_links)),
                    "range_out_links": c.range_out_links,
                    "footnote_labels": c.footnote_labels,
                    "anchors": c.source_anchors,
                    "code_blocks": [b for b in c.code_blocks],
                    "blocks": [
                        {"text": b["text"], "segments": b["segments"]}
                        for b in c.blocks
                    ],
                }
                for c in chapters
            ],
        }
    )
    (work_dir / REPORT_NAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not machine_ok:
        print("FAIL: 机器检查未通过，候选保留在 %s" % candidate, file=sys.stderr)
        for diag in hard_failures:
            print(
                "  [%s] %s:%s %s"
                % (
                    diag["code"],
                    diag.get("input", "?"),
                    diag.get("line", "?"),
                    diag["message"],
                ),
                file=sys.stderr,
            )
        for error in (browser_checks or {}).get("katex", []):
            latex = math_index.get(error.get("id", ""), "")
            print(
                "  [katex-error] 公式节点 %s 渲染失败：%s（%s）"
                % (error.get("id"), error.get("message"), latex[:80]),
                file=sys.stderr,
            )
        for error in (browser_checks or {}).get("images", []):
            print(
                "  [image-error] 图片解码失败：%s（%s）"
                % (error.get("src"), error.get("error")),
                file=sys.stderr,
            )
        for overflow in (browser_checks or {}).get("overflow", []):
            print(
                "  [overflow] %s 超出版心（right=%s > %s）：%r"
                % (
                    overflow.get("tag"),
                    overflow.get("right"),
                    overflow.get("pageWidth"),
                    overflow.get("text"),
                ),
                file=sys.stderr,
            )
        if browser_checks and not any(browser_checks.get("fonts", {}).values()):
            print("  [fonts] 未检测到可用中文字体", file=sys.stderr)
        return 1

    # 全部检查通过后才允许触碰最终目标；目标不得是输入文件或原始资源。
    protected = {Path(item["path"]).resolve() for item in inputs}
    protected |= {Path(r["path"]).resolve() for r in resources}
    if output.resolve() in protected:
        print(
            "FAIL: 输出路径不得指向输入文件或原始资源：%s" % output, file=sys.stderr
        )
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, output)
    print(
        "机器检查通过：%s（候选与证据见 %s）\n成品待视觉复核后才能发布。"
        % (output, work_dir)
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把有序 Markdown 文档导出为单个 PDF（机器检查通过才写目标文件）。"
    )
    parser.add_argument("--output", required=True, help="最终 PDF 路径")
    parser.add_argument(
        "--work-dir", required=True, help="工作区外临时目录，存放 HTML/候选/证据"
    )
    parser.add_argument("inputs", nargs="+", help="有序 Markdown 输入")
    args = parser.parse_args(argv)
    try:
        return export(
            args.inputs, Path(args.output).expanduser(), Path(args.work_dir).expanduser()
        )
    except ExportError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
