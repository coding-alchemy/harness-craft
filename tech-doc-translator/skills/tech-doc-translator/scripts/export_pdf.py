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
import datetime
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

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from _html_fidelity import reason_code
from _image_preflight import (
    Occurrence,
    bitmap_facts,
    classify_occurrences,
    coverage_diagnostics,
    coverage_summary,
    decode_budget,
    undetermined_binding_diagnostics,
)

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


DISPLAY_MAP_NAME = "images_display.json"
# A4 版心：210mm − 16mm×2 = 178mm；1 CSS px = 1/96 inch，1 pt = 1/72 inch。
CONTENT_WIDTH_MM = 210 - 16 * 2
CONTENT_WIDTH_PX = CONTENT_WIDTH_MM / 25.4 * 96
PT_PER_CSS_PX = 0.75


def _display_px(width):
    """把映射中的宽度换算为 CSS 像素；无法确定返回 None。"""
    if not width or width.get("unit") not in ("px", "%"):
        return None
    value = width.get("value")
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    if width["unit"] == "px":
        return float(value)
    reference = width.get("reference") or {}
    reference_px = reference.get("width_px")
    if not isinstance(reference_px, (int, float)) or reference_px <= 0:
        return None
    return value / 100.0 * reference_px


def load_display_maps(chapters, explicit_paths, diagnostics):
    """读取各章的显示尺寸映射，返回 (绑定, 未确定编码, 未确定原始条目, 清单)。

    显式 --images-display 优先；否则使用输入 Markdown 同目录的
    images_display.json（不递归猜测项目根）。条目按 markdown 归属分派；
    无映射的章按自然尺寸回退并记录，不视为失败。绑定不一致（出现越界、
    资源路径或摘要不符、非法宽度）记为 fail。未确定条目按 reason_code
    单独返回供覆盖分类与严格策略使用；其原始条目一并返回，由预检按与
    确定条目相同的出现序号与资源身份规则核对（是否有尺寸不决定已声明
    身份是否须核对）。
    """
    bindings = {}  # chapter.path -> {occurrence: {"px": float, "entry": dict}}
    undetermined_map = {}  # (chapter.path, occurrence) -> reason_code
    undetermined_raw = {}  # chapter.path -> [(entry, map_path)]
    used_paths = set()
    explicit_files = []
    for raw in explicit_paths:
        path = Path(raw).expanduser()
        if path.is_file():
            explicit_files.append(path)
        else:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-missing",
                    "message": "显式显示尺寸映射不存在：%s" % path,
                    "input": str(path),
                }
            )
    # 同名 Markdown 歧义审计：文件名兜底只在唯一命中时允许，否则拒绝绑定。
    name_counts = {}
    input_paths = set()
    for chapter in chapters:
        name_counts[chapter.path.name] = name_counts.get(chapter.path.name, 0) + 1
        input_paths.add(chapter.path)

    def attribute(payload, map_path, chapter, key):
        """把映射中 key 列表的条目按 markdown 归属分派到本章。"""
        entries = []
        map_entries = payload.get(key, [])
        base_counts = {}
        for entry in map_entries:
            markdown = entry.get("markdown", payload.get("markdown", ""))
            if isinstance(markdown, str) and markdown:
                name = Path(markdown).name
                base_counts[name] = base_counts.get(name, 0) + 1
        for entry in map_entries:
            markdown = entry.get("markdown", payload.get("markdown", ""))
            entry_path = (
                (map_path.parent / str(markdown)).resolve()
                if isinstance(markdown, str) and markdown else None
            )
            if entry_path == chapter.path:
                entries.append(entry)
                continue
            if (
                isinstance(markdown, str) and markdown
                and Path(markdown).name == chapter.path.name
            ):
                if entry_path in input_paths:
                    continue  # 条目已精确归属其他输入章，不参与兜底
                if (name_counts.get(chapter.path.name, 0) > 1
                        or base_counts.get(chapter.path.name, 0) > 1):
                    # 同名多章或多条目同名：按文件名无法唯一归属，
                    # 拒绝绑定并要求映射改用完整相对路径，不静默串用。
                    diagnostics.append(
                        {
                            "severity": "fail",
                            "code": "images-display-ambiguous-markdown",
                            "message": "显示尺寸条目按文件名命中多个同名 "
                            "Markdown，需用完整相对路径消歧：%s" % chapter.path,
                            "input": str(map_path),
                        }
                    )
                else:
                    entries.append(entry)
        return entries

    for chapter in chapters:
        candidates = list(explicit_files)
        same_dir = chapter.dir / DISPLAY_MAP_NAME
        if same_dir.is_file() and same_dir not in candidates:
            candidates.append(same_dir)
        chapter_entries = []
        chapter_undetermined = []
        undetermined_raw[chapter.path] = []
        processed_maps = set()  # 显式路径与缺省路径指向同一文件时只读一次
        for map_path in candidates:
            resolved_map = str(map_path.resolve())
            if resolved_map in processed_maps:
                continue
            processed_maps.add(resolved_map)
            used_paths.add(resolved_map)
            try:
                payload = json.loads(map_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-invalid",
                        "message": "显示尺寸映射无法解析：%s（%s）" % (map_path, exc),
                        "input": str(chapter.path),
                    }
                )
                continue
            chapter_entries.extend(
                (entry, map_path)
                for entry in attribute(payload, map_path, chapter, "entries"))
            chapter_undetermined.extend(
                (entry, map_path)
                for entry in attribute(payload, map_path, chapter,
                                       "undetermined"))
        occurrence_map = {}
        for entry, map_path in chapter_entries:
            occurrence = entry.get("occurrence")
            record = {
                "occurrence": occurrence,
                "image": entry.get("image"),
                "sha256": entry.get("sha256"),
                "width": entry.get("width"),
            }
            if not isinstance(occurrence, int) or occurrence < 1:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-binding",
                        "message": "显示尺寸条目出现序号非法：%r" % (entry,),
                        "input": str(chapter.path),
                    }
                )
                continue
            px = _display_px(entry.get("width"))
            if px is None:
                if entry.get("width") is not None:
                    diagnostics.append(
                        {
                            "severity": "fail",
                            "code": "images-display-invalid-width",
                            "message": "显示尺寸非法或缺少可确定参照：%r"
                            % (entry.get("width"),),
                            "input": str(chapter.path),
                        }
                    )
                continue
            record["applied_px"] = px
            record["capped"] = px > CONTENT_WIDTH_PX
            held = occurrence_map.get(occurrence)
            if held is not None and (
                held["px"] != px
                or held["record"].get("image") != record.get("image")
                or held["record"].get("sha256") != record.get("sha256")
            ):
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-duplicate",
                        "message": "同一图片出现序号 %d 被多个映射条目冲突绑定"
                        "（宽度或资源不一致）" % occurrence,
                        "input": str(chapter.path),
                    }
                )
                continue
            if held is None:
                occurrence_map[occurrence] = {"px": px, "record": record,
                                              "map_path": map_path}
        for entry, map_path in chapter_undetermined:
            occurrence = entry.get("occurrence")
            if not isinstance(occurrence, int) or occurrence < 1:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-binding",
                        "message": "未确定尺寸条目出现序号非法：%r" % (entry,),
                        "input": str(chapter.path),
                    }
                )
                continue
            code = entry.get("reason_code")
            if code not in ("no-source-constraint", "unresolved-size"):
                code = reason_code(entry.get("reason") or "")
            undetermined_map[(chapter.path, occurrence)] = code
            undetermined_raw[chapter.path].append((entry, map_path))
        bindings[chapter.path] = occurrence_map
    return bindings, undetermined_map, undetermined_raw, sorted(used_paths)


def apply_display_widths(chapter, bindings, diagnostics):
    """按出现序号把受限宽度注入对应图片，并核验资源身份。

    映射命中才注入；无映射命中按自然尺寸回退。命中但资源路径或摘要与
    实际不符时失败，不忽略损坏映射后宣称恢复成功。
    """
    occurrence_map = bindings.get(chapter.path, {})
    images = soup_images(chapter)
    applied = []
    for occurrence, binding in sorted(occurrence_map.items()):
        if occurrence > len(chapter.images):
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-binding",
                    "message": "显示尺寸条目出现序号 %d 超出本章图片数 %d"
                    % (occurrence, len(chapter.images)),
                    "input": str(chapter.path),
                }
            )
            continue
        image = chapter.images[occurrence - 1]
        entry_image = binding["record"].get("image")
        if entry_image:
            resolved = (binding["map_path"].parent / str(entry_image)).resolve()
            if resolved != Path(image["path"]):
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-binding",
                        "message": "显示尺寸条目资源与第 %d 次出现不符：%s != %s"
                        % (occurrence, resolved, image["path"]),
                        "input": str(chapter.path),
                    }
                )
                continue
        entry_sha = binding["record"].get("sha256")
        if entry_sha and entry_sha != image["sha256"]:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-digest",
                    "message": "显示尺寸条目资源摘要与第 %d 次出现不符：%s"
                    % (occurrence, entry_image or image["path"]),
                    "input": str(chapter.path),
                }
            )
            continue
        if occurrence > len(images):
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-binding",
                    "message": "第 %d 次出现的图片节点缺失" % occurrence,
                    "input": str(chapter.path),
                }
            )
            continue
        width_px = binding["px"]
        images[occurrence - 1]["style"] = (
            "width:%spx" % (int(width_px) if width_px == int(width_px) else width_px)
        )
        record = dict(binding["record"])
        applied.append(record)
    return applied


# ---------------------------------------------------------------------------
# 代码块分页分类（R8/D7：10 个逻辑行分界，末尾换行不增行）
# ---------------------------------------------------------------------------
CODE_BLOCK_MAX_LINES = 10


def logical_code_lines(code):
    """代码块的逻辑行列表：统一 CRLF/LF，末尾单个终止换行不增行，
    内部与真实末尾空行计入；空块为 0 行。视觉折行不改变逻辑行数。"""
    text = code.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return text.split("\n")


def code_block_class(code):
    """10 行及以下短块（整体避免分页），超过 10 行长块（允许跨页续排）。"""
    return "code-long" if len(logical_code_lines(code)) > CODE_BLOCK_MAX_LINES \
        else "code-short"


def wrap_code_block(rendered_html, code):
    """在统一收集边界为渲染后的代码块加分页分类容器。"""
    return '<div class="code-block %s">%s</div>' % (
        code_block_class(code), rendered_html)


def soup_images(chapter):
    return [img for img in chapter.soup.find_all("img") if img.get("src")]


# ---------------------------------------------------------------------------
# 出处前置与生成门禁（R6/D6：字段投影单源；来源不足在任何打印前失败；
# 新政策：出处只留证据，PDF 导出视图不显示前置出处）
# ---------------------------------------------------------------------------

# 可定位原文的标记：URL、机器路径或指向具体页面/文档文件的引用。
# 仅有文档名称或网站首页文字不构成“可定位具体原文”。
_PROVENANCE_LOCATOR_RE = re.compile(
    r"(https?://\S+|/[^\s）)】，。]*|[^\s）)】，。]*\.(?:html?|md|pdf))", re.I)


def head_field_values(text):
    """章首管理字段内容（含完整续行），边界与投影共用同一实现。

    投影删除的字段段（含无标签续行、lazy 续行与列表延续）就是收集
    保留的同一段：已知版本/日期写在续行时既不从 PDF 丢失，也不靠
    行首关键词另猜边界。首行剥离字段标签，续行原样并入该字段内容。
    """
    values = {}
    lines = text.split("\n")
    for label, start, end in _management_field_segments(text):
        chunks = []
        for number in range(start, end + 1):
            stripped = lines[number - 1].strip()
            content = stripped[1:].strip() \
                if stripped.startswith(">") else stripped
            if number == start:
                match = HEAD_FIELD_RE.match(stripped)
                if match:
                    content = match.group(2).strip()
            if content:
                chunks.append(content)
        if chunks:
            values.setdefault(label, []).append("\n".join(chunks))
    return values


def _norm_prov(text):
    """出处文字比较口径：空白折叠。"""
    return _WS_PROV_RE.sub("", text or "")


_WS_PROV_RE = re.compile(r"\s+")


def has_provenance_locator(text):
    """来源文字是否可定位具体原文（A15 最低标准）。

    机器路径或指向具体文档文件的引用算定位；URL 必须带有主机内路径
    （指向具体页面/文档），裸域名或站点首页不算。"""
    for token in _PROVENANCE_LOCATOR_RE.findall(text or ""):
        if token.lower().startswith("http"):
            rest = re.sub(r"^[a-z]+://[^/]+", "", token, flags=re.I)
            rest = rest.rstrip("/#?")
            if not rest:
                continue  # 裸域名/站点首页
            if re.match(r"^[^/]+\.[a-z]{2,}$", rest.split("/")[0],
                        re.I) and "/" not in rest:
                continue  # 仅域名+无路径
            return True
        if token.startswith("/") or token.lower().endswith(
                (".html", ".md", ".pdf")):
            return True
        parts = [seg for seg in token.split("/") if seg]
        if len(parts) >= 2:
            return True
    return False


def _toc_prov_error(line_no, reason):
    return ExportError(
        "目录“译自…”出处行（L%d）无法确认整行仅为出处（%s），不猜测"
        "删除；请改用 --view-declaration 显式声明排除" % (line_no, reason))


# 裸定位符（裸 URL/本地路径）须连续无空白；?、=、&、#、_ 与路径斜线是
# 定位符内部字符，未转义的中英分号、全角分隔符与括号则使整行失败
# （确需分号的真实 URL 可写成 Markdown 链接或对分号编码）。
_TOC_BARE_FORBIDDEN_RE = re.compile(r"[\s;；，、。：（）()\[\]<>【】]")
# 书目尾注完整值：有效公历日期、vN.N(.N) 版本或“单个拉丁会议词 + 年份”。
_TOC_BIB_TAIL_RE = re.compile(r"^（([^（）]*)）$")
_TOC_BIB_TAIL_SEARCH_RE = re.compile(r"（[^（）]*）$")
_TOC_BIB_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOC_BIB_VERSION_RE = re.compile(r"^v\d+\.\d+(\.\d+)?$")
_TOC_BIB_CONF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]* \d{4}$")
# 书名只接受非空的汉字、ASCII 字母、数字、空格、点、连字符和下划线，
# 首尾不能是空格或标点，且不得含另一个定位符或分隔冒号。
_TOC_TITLE_RE = re.compile(r"^[一-鿿A-Za-z0-9 ._\-]+$")
_TOC_TITLE_EDGE = " ._-"


def _toc_bibliographic_tail_ok(value):
    """书目尾注完整值校验：YYYY-MM-DD（有效公历日期）、vN.N(.N) 或会议词+年份。"""
    if _TOC_BIB_VERSION_RE.fullmatch(value) \
            or _TOC_BIB_CONF_RE.fullmatch(value):
        return True
    if not _TOC_BIB_DATE_RE.fullmatch(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _toc_title_separator(text):
    """书名分隔符：首个不在 :// 中的中英文冒号下标，无则 None。"""
    for index, char in enumerate(text):
        if char in ":：" and text[index + 1:index + 3] != "//":
            return index
    return None


def _toc_check_locator(value, line_no, resolve_nav, bare):
    """来源定位符验证：可定位具体原文；本地目标不得解析为纳入章节。

    窄语法已保证定位符是整个值，故按完整值校验（设计 §8.3）：含
    “://”的 URL 形态必须有主机及实际文档路径，查询串和片段不算路径；
    其余沿用本地来源标准并做导航歧义检查。
    """
    if not value:
        raise _toc_prov_error(line_no, "缺少来源定位符")
    if bare and _TOC_BARE_FORBIDDEN_RE.search(value):
        raise _toc_prov_error(
            line_no, "裸定位符须连续无空白且不含分号/括号等分隔字符：%r"
            % value[:40])
    if "://" in value:
        url = urlsplit(value)
        if not url.netloc:
            raise _toc_prov_error(
                line_no, "URL 定位符缺少主机：%r" % value[:40])
        if not url.path.rstrip("/"):
            raise _toc_prov_error(
                line_no, "URL 定位符缺少主机内文档路径：%r" % value[:40])
    elif not has_provenance_locator(value):
        raise _toc_prov_error(
            line_no, "缺少可定位具体原文的来源：%r" % value[:40])
    if "://" not in value and resolve_nav is not None:
        path_part = unquote(value.partition("#")[0])
        if resolve_nav(path_part):
            raise _toc_prov_error(
                line_no, "来源定位符解析为本次纳入的目录/章节文件"
                "（导航歧义）：%r" % value[:40])


def _parse_toc_provenance_line(content, line_no, resolve_nav):
    """整行出处语法校验（设计 §8.3）：完整消费一条来源语法，否则定位失败。

    content 为去掉引用标记与首尾空白、以“译自”开头的行内容。“译自”后
    只允许至多一个空格或一个中英文冒号；主表达式只接受单一链接
    （Markdown 链接或 CommonMark 自动链接，标签为单个非空 text 子节点）、
    单一裸定位符或“书名：裸定位符”，之后至多再有一对全角书目尾注括号
    与一个句末“。”。任何未消费文字、第二定位符或第二链接都定位失败。
    """
    rest = content[len("译自"):]
    if rest[:1] in (" ", "：", ":"):
        rest = rest[1:]
    if not rest:
        raise _toc_prov_error(line_no, "“译自”后缺少来源内容")
    if rest[:1] in (" ", "：", ":"):
        raise _toc_prov_error(
            line_no, "“译自”与来源之间只允许一个空格或一个中英文冒号")
    if rest.endswith("。"):
        rest = rest[:-1]
    if not rest or rest.endswith("。"):
        raise _toc_prov_error(line_no, "只允许至多一个句末“。”")
    children = list(
        (_DECL_STRUCTURE_MD.parseInline(rest, {})[0].children or []))

    def _check_tail(value):
        if not _toc_bibliographic_tail_ok(value):
            raise _toc_prov_error(
                line_no, "书目尾注须为有效公历日期、vN.N(.N) 版本或"
                "“单个拉丁会议词 + 四位年份”：%r" % value)

    # 链接形态后的尾注是独立 text token；裸定位符/书名形态的尾注嵌在
    # 同一 text token 末尾。
    if children and children[-1].type == "text":
        match = _TOC_BIB_TAIL_RE.fullmatch(children[-1].content)
        if match:
            _check_tail(match.group(1))
            children = children[:-1]
    if not children:
        raise _toc_prov_error(line_no, "缺少来源定位符")
    if (len(children) == 3 and children[0].type == "link_open"
            and children[1].type == "text" and children[1].content.strip()
            and children[2].type == "link_close"):
        href = dict(children[0].attrs or []).get("href") or ""
        _toc_check_locator(href, line_no, resolve_nav, bare=False)
        return
    if len(children) == 1 and children[0].type == "text":
        main = children[0].content
        match = _TOC_BIB_TAIL_SEARCH_RE.search(main)
        if match:
            _check_tail(match.group(0)[1:-1])
            main = main[:match.start()]
        separator = _toc_title_separator(main)
        if separator is not None:
            title = main[:separator]
            if (title and _TOC_TITLE_RE.fullmatch(title)
                    and title[0] not in _TOC_TITLE_EDGE
                    and title[-1] not in _TOC_TITLE_EDGE
                    and not has_provenance_locator(title)):
                _toc_check_locator(
                    main[separator + 1:], line_no, resolve_nav, bare=True)
                return
        _toc_check_locator(main, line_no, resolve_nav, bare=True)
        return
    raise _toc_prov_error(
        line_no, "行内构成超出“一条来源”语法（含未消费文字、第二定位符"
        "或第二链接）")


def toc_provenance_span(text, declared_ranges=(), resolve_nav=None):
    """目录出处段的块边界投影区间：(起始行, 结束行, 段落文本)。

    窄格式自动语法（设计 §8.3）：候选是目录中未被声明接管、以“译自”
    开头的行（取 CommonMark inline 内容，围栏/缩进代码不产生候选）。
    一个目录至多自动采用一个出处块；多个候选定位行号并拒绝，要求用
    --view-declaration 逐处明确范围。结构条件先于行内条件：候选必须
    位于顶层独立单行段落，或内容恰为一个单行段落的顶层单行引用块；
    同段多行、共享块、列表/标题/表格/嵌套块中的候选一律定位失败，
    不猜测删除。结构通过后整行须完整消费一条来源语法
    （_parse_toc_provenance_line）。识别口径与 find_toc_provenance
    单源（同一段落既是门禁证据又是排除对象）。
    declared_ranges：已被 toc-provenance 声明接管的行区间，其中的
    “译自”候选不再进入自动判断（设计 §8.4 声明接管顺序）。
    resolve_nav：本地路径→是否解析为本次纳入的目录/章节文件（导航
    歧义检查），None 表示不做该检查。
    """
    tokens = _DECL_STRUCTURE_MD.parse(text)
    lines = text.split("\n")
    candidates = []
    for token in tokens:
        if token.type != "inline" or token.map is None:
            continue
        for offset, content_line in enumerate(token.content.split("\n")):
            line_no = token.map[0] + offset + 1
            if any(start <= line_no <= end for start, end in declared_ranges):
                continue
            if content_line.strip().startswith("译自"):
                candidates.append((line_no, content_line.strip()))
    if not candidates:
        return None
    if len(candidates) > 1:
        raise ExportError(
            "一个目录至多自动采用一个出处块；发现 %d 个“译自”候选"
            "（L%s），请用 --view-declaration 逐处明确范围"
            % (len(candidates),
               "、L".join(str(line_no) for line_no, _c in candidates)))
    line_no, content_line = candidates[0]
    for index, token in enumerate(tokens):
        if token.type not in ("paragraph_open", "blockquote_open") \
                or not token.map or token.level != 0:
            continue  # 非顶层块（列表项内段落、嵌套引用等）不可能是独立出处段
        start, end = token.map[0] + 1, token.map[1]
        if not (start <= line_no <= end):
            continue
        if token.type == "paragraph_open":
            if end != start:
                # 多行顶层段落：无法确认整段均为出处。
                raise ExportError(
                    "目录“译自…”出处段跨多行（L%d-L%d），无法确认整段"
                    "均为出处，不猜测删除；请用空行分隔为单行独立段，"
                    "或在 --view-declaration 中显式声明排除" % (start, end))
            _parse_toc_provenance_line(content_line, line_no, resolve_nav)
            return start, end, _toc_block_paragraph(lines, start, end)
        # 顶层引用块：内容须恰为单个出处段落（无列表、无多段落、无
        # 更深嵌套），否则边界无法确定，定位行号并拒绝。
        close = index + 1
        while close < len(tokens) and not (
                tokens[close].type == "blockquote_close"
                and tokens[close].level == 0):
            close += 1
        children = [
            child for child in tokens[index + 1:close]
            if child.level == 1 and child.map is not None
            and (child.type.endswith("_open")
                 or child.type in ("fence", "code_block", "hr", "html_block"))
        ]
        if not (len(children) == 1
                and children[0].type == "paragraph_open"):
            raise ExportError(
                "目录“译自…”出处段与导航等内容共享同一块（L%d-L%d），"
                "投影边界无法确定，不猜测删除；请用空行把出处段单独成块，"
                "或在 --view-declaration 中显式声明排除" % (start, end))
        if end != start:
            # 单段多行引用块：段落内除译自行外还有其余内容行，
            # 无法确认整段均为出处。
            raise ExportError(
                "目录“译自…”出处段跨多行（L%d-L%d），无法确认整段"
                "均为出处，不猜测删除；请用空行分隔为单行独立段，"
                "或在 --view-declaration 中显式声明排除" % (start, end))
        _parse_toc_provenance_line(content_line, line_no, resolve_nav)
        return start, end, _toc_block_paragraph(lines, start, end)
    raise ExportError(
        "目录“译自…”出处段未形成独立顶层段落块（L%d），投影边界无法"
        "确定，不猜测删除；请调整目录文件，或在 --view-declaration 中"
        "显式声明排除" % line_no)


def _toc_block_paragraph(lines, start, end):
    """块区间的段落文本口径：非空行去首尾空白后按行拼接。"""
    return "\n".join(
        line.strip() for line in lines[start - 1:end] if line.strip())


def find_toc_provenance(toc_chapter):
    """目录出处原文（自动排除段 + toc-provenance 声明片段），无则 None。

    不重新推导边界：自动段与声明片段在 decide_toc_provenance 时已定位
    并记录到章对象（声明接管的候选可能不满足自动模板，重新推导会误
    判）；同一份原文既是来源门禁证据又是核验排除预期。
    """
    if toc_chapter is None:
        return None
    parts = []
    exclusion = toc_chapter.toc_provenance_exclusion
    if exclusion is not None:
        lines = toc_chapter.text.split("\n")
        parts.append(_toc_block_paragraph(
            lines, exclusion["start_line"], exclusion["end_line"]))
    parts.extend(toc_chapter.toc_provenance_fragments)
    return "\n".join(part for part in parts if part) or None


TOC_PROVENANCE_EXCLUSION_REASON = (
    "目录前置出处段默认排除（PDF 不显示出处；来源证据与门禁保留，"
    "Markdown 原样）")


def remove_line_spans(text, spans):
    """按原文行区间集合（1 起含端点）移除行，返回投影文本。"""
    drop = set()
    for start, end in spans:
        drop.update(range(start - 1, end))
    return "\n".join(
        line for number, line in enumerate(text.split("\n"))
        if number not in drop
    )


def visible_provenance_text(markdown_text):
    """出处段的实际可见文字：按 CommonMark 渲染后取文本，链接只留显示文字。

    核验用该可见文字在成品 PDF 中定位被采用的出处段——读者在 PDF 中
    看到的是渲染后的文字而非 Markdown 标记；链接目标本身仍由既有链接
    核验负责，位置核验只关心实际显示内容。块级段落边界保留为换行：
    不同段落是各自独立的可见文字，不合并成假想的连续文本。
    """
    if not markdown_text:
        return ""
    html = _HEAD_STRUCTURE_MD.render(markdown_text)
    soup = BeautifulSoup(html, "html.parser")
    blocks = [child.get_text(" ", strip=True)
              for child in soup.find_all(recursive=False)]
    blocks = [text for text in blocks if text]
    if not blocks:
        return soup.get_text(" ", strip=True)
    return "\n".join(blocks)


def load_provenance_map(path, chapters, diagnostics):
    """读取并校验只读出处区间映射（--provenance）；非法即失败。

    映射格式：{"inputs": [{"path": "...", "sha256": "...",
    "sections": [{"lines": [起, 止], "chapters": [1, 2, ...]}]}], ...}
    行区间为输入文件中构成完整出处说明的段落；chapters 为 1 起输入序号，
    声明该段落覆盖的章。区间映射只证明来源与章节对应，不掩盖来源缺失。
    输入摘要必填且必须匹配（缺失或替换输入即拒绝，不能用映射绕开输入
    绑定）；区间只支持目录文件（00_目录.md，渲染在最前）中的出处段落，
    正文章节内的区间不构成前置出处，明确拒绝。
    """
    if path is None:
        return None
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError("出处区间映射无法解析：%s（%s）" % (path, exc))
    by_path = {str(chapter.path): chapter for chapter in chapters}
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    if toc_chapter is not None and chapters[0] is not toc_chapter:
        # 映射的效力以目录渲染在最前为前提；目录未列首位时被采用出处段
        # 必然落在其后的章之后，无法满足前置要求。不擅自重排输入，沿用
        # 生成门禁的既有失败保护明确拒绝（零生成、已有 PDF 不变）。
        raise ExportError(
            "目录文件未列在输入首位，出处区间映射无法保证被采用出处段"
            "先于首章：请将 %s 列在输入首位后重试" % TOC_FILE_NAME)
    covered = {}
    resolve = lambda p: str(Path(p).expanduser().resolve())
    for item in payload.get("inputs", []):
        chapter = by_path.get(resolve(item.get("path", "")))
        if chapter is None:
            raise ExportError(
                "出处区间映射指向未纳入输入的文件：%r" % item.get("path"))
        if toc_chapter is None or chapter is not toc_chapter:
            raise ExportError(
                "出处区间映射只支持目录文件（00_目录.md）中的前置出处"
                "段落，不支持正文章节内区间：%r" % item.get("path"))
        digest = item.get("sha256")
        if not digest:
            raise ExportError(
                "出处区间映射缺少输入摘要（sha256 必填）：%s"
                % item.get("path"))
        if digest != sha256_file(chapter.path):
            raise ExportError(
                "出处区间映射摘要与输入不符：%s" % item.get("path"))
        for section in item.get("sections", []):
            start, end = section.get("lines", [0, 0])
            lines = chapter.text.split("\n")
            if not (1 <= start <= end <= len(lines)):
                raise ExportError(
                    "出处区间越界：%s L%d-L%d"
                    % (item.get("path"), start, end))
            mapped_text = "\n".join(lines[start - 1:end])
            if not has_provenance_locator(mapped_text):
                raise ExportError(
                    "出处区间不含可定位来源：%s L%d-L%d"
                    % (item.get("path"), start, end))
            for index in section.get("chapters", []):
                if not 1 <= index <= len(chapters):
                    raise ExportError("出处区间覆盖章序号越界：%r" % index)
                covered[index] = mapped_text
    if not covered:
        raise ExportError("出处区间映射未声明任何章节覆盖")
    # 章节覆盖关系（covered）与实际出处段落分开：同一段落覆盖多章时
    # 实际段落只有一份，核验定位按实际段落进行；真正不同的段落（不同
    # 来源、版本或日期）原样保留，不合并、不丢弃。
    paragraphs = []
    for index in sorted(covered):
        if covered[index] not in paragraphs:
            paragraphs.append(covered[index])
    return {"text": "\n\n".join(paragraphs),
            "covered": covered}


# ---------------------------------------------------------------------------
# PDF 视图声明（--view-declaration）：受输入摘要绑定的授权排除范围
# ---------------------------------------------------------------------------

VIEW_DECLARATION_VERSION = 1
# block 型排除只允许对齐这类 Markdown 块；标题/代码围栏/表格等是技术正文。
VIEW_DECLARATION_BLOCK_KINDS = ("paragraph", "blockquote", "list")
VIEW_DECLARATION_TECH_KINDS = ("heading", "code", "table", "hr", "html")

# 声明块边界校验使用独立 CommonMark 实例（开启表格）：与章首结构分析
# 的纯 commonmark 实例分开，表格块必须被识别为技术正文。
_DECL_STRUCTURE_MD = MarkdownIt("commonmark")
_DECL_STRUCTURE_MD.enable("table")


def _decl_block_maps(text):
    """块级 token 的行区间 [(起始行, 结束行, 种类)]，1 起含端点。"""
    maps = []
    for token in _DECL_STRUCTURE_MD.parse(text):
        if token.map is None:
            continue
        kind = {
            "paragraph_open": "paragraph",
            "blockquote_open": "blockquote",
            "bullet_list_open": "list",
            "ordered_list_open": "list",
            "heading_open": "heading",
            "fence": "code",
            "code_block": "code",
            "table_open": "table",
            "hr": "hr",
            "html_block": "html",
        }.get(token.type)
        if kind is not None:
            maps.append((token.map[0] + 1, token.map[1], kind))
    return maps


def _declared_original_heading(chapters):
    """单篇首章 H1 原文（用于核对声明 original）；无法确定返回 None。

    多章合订（两个及以上正文章）的书名不是首章标题，返回 None 不作
    核对；首章无标题或只有深层标题（CommonMark 不识别 H7+）同样返回
    None。用带表格的 CommonMark 实例解析，标题内行内标记取原文。
    """
    content = [c for c in chapters if not c.is_toc]
    if len(content) != 1:
        return None
    tokens = _DECL_STRUCTURE_MD.parse(content[0].text)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1" \
                and index + 1 < len(tokens) \
                and tokens[index + 1].type == "inline":
            return tokens[index + 1].content.strip() or None
    return None


TOC_PROVENANCE_DECLARATION_KIND = "toc-provenance"


def _strip_block_markers(text):
    """去除各行引用标记与首尾空白后的文本（声明内容判定用）。"""
    return "\n".join(
        line.lstrip("> ").strip() for line in text.split("\n")
    ).strip()


def _declared_chapter_links(text, chapter, chapters):
    """文本中指向本次纳入目录/章节文件的本地链接目标列表。"""
    targets = []
    for token in _DECL_STRUCTURE_MD.parse(text):
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type != "link_open":
                continue
            href = dict(child.attrs or []).get("href") or ""
            if not href or urlsplit(href).scheme:
                continue
            path_part = unquote(href.partition("#")[0])
            target = ((chapter.dir / path_part).resolve()
                      if path_part else chapter.path)
            if any(c.path == target for c in chapters):
                targets.append(href)
    return targets


def _check_toc_provenance_declaration(entry, chapter, chapters, ex_type,
                                      fragment, ranged_text):
    """toc-provenance 声明校验：只接管目录出处，不得吞掉章节导航。

    声明内容须来自原始目录、以“译自”开头且含可定位来源；指向纳入
    目录/章节文件的链接不能作为出处片段获准删除（设计 §8.4）。
    """
    start, end = entry["lines"]
    if not chapter.is_toc:
        raise ExportError(
            "视图声明 kind=toc-provenance 只适用于目录文件（%s）：%s"
            % (TOC_FILE_NAME, entry.get("input")))
    content = fragment if ex_type == "inline" else ranged_text
    stripped = _strip_block_markers(content)
    if not stripped.startswith("译自"):
        raise ExportError(
            "toc-provenance 声明排除的内容必须以“译自”开头（非出处内容"
            "不得按出处排除）：%s L%d-L%d" % (entry.get("input"), start, end))
    if not has_provenance_locator(stripped):
        raise ExportError(
            "toc-provenance 声明排除的内容须含可定位来源：%s L%d-L%d"
            % (entry.get("input"), start, end))
    nav = _declared_chapter_links(content, chapter, chapters)
    if nav:
        raise ExportError(
            "toc-provenance 声明不得吞掉指向纳入章节的导航链接：%s "
            "L%d-L%d（%s）"
            % (entry.get("input"), start, end, "、".join(nav)))


def load_view_declaration(path, chapters):
    """读取并校验 PDF 视图声明（--view-declaration）；非法即 ExportError。

    声明格式（version 1）：
        {"version": 1,
         "inputs": [{"path": "...", "sha256": "..."}],
         "exclusions": [{"input": "...", "lines": [起, 止],
                         "type": "block|inline", "kind": "...",
                         "fragment": "...", "reason": "..."}],
         "document_title": {"original": "...", "chinese": "...",
                            "basis": "..."}}
    inputs 与实际有序输入一一对应且摘要必须匹配（漂移即拒绝）；行区间在
    文件内、fragment 与实际文本匹配、范围互不重叠；block 型必须对齐
    Markdown 块边界（整块引用块/段落/列表），区间覆盖标题、代码围栏、
    表格等技术正文即失败；inline 型删除文本片段。document_title 本阶段
    只在加载校验时接受并记录（ticket 04 才消费）。
    kind=toc-provenance 只适用于目录文件（00_目录.md）：声明内容须以
    “译自”开头且含可定位来源，且不得含指向纳入目录/章节文件的导航
    链接；接管的候选不再进入目录出处自动判断（decide_toc_provenance）。
    其他 kind 不接管目录出处候选，不绕过自动判断。
    """
    if path is None:
        return None
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError("视图声明无法解析：%s（%s）" % (path, exc))
    if not isinstance(payload, dict):
        raise ExportError("视图声明必须是 JSON 对象：%s" % path)
    if payload.get("version") != VIEW_DECLARATION_VERSION:
        raise ExportError(
            "视图声明版本不受支持：%r（本工具只接受 version %d）"
            % (payload.get("version"), VIEW_DECLARATION_VERSION))
    items = payload.get("inputs")
    if not isinstance(items, list) or len(items) != len(chapters):
        raise ExportError(
            "视图声明 inputs 必须与导出命令的有序输入一一对应"
            "（声明 %d 条 / 实际 %d 条）"
            % (len(items) if isinstance(items, list) else -1, len(chapters)))
    for item, chapter in zip(items, chapters):
        declared = Path(str(item.get("path", ""))).expanduser().resolve()
        if declared != chapter.path:
            raise ExportError(
                "视图声明输入与实际有序输入不符：%r != %s"
                % (item.get("path"), chapter.path))
        digest = item.get("sha256")
        if not digest:
            raise ExportError(
                "视图声明缺少输入摘要（sha256 必填）：%s" % item.get("path"))
        if digest != sha256_file(chapter.path):
            raise ExportError(
                "视图声明摘要与输入不符：%s" % item.get("path"))
    document_title = payload.get("document_title")
    if document_title is not None and not isinstance(document_title, dict):
        raise ExportError("视图声明 document_title 必须是对象或缺省")
    if isinstance(document_title, dict) \
            and str(document_title.get("chinese") or "").strip():
        # 采用声明题名时校验可回查性与中文口径（R3/C5）：题名须含 CJK
        # 字符，依据与原题必填；单篇能从输入确定原题（首章 H1）时核对
        # 一致，多章合订的书名非首章标题，不作此核对。
        chinese_title = str(document_title["chinese"]).strip()
        if not _CJK_CHAR_RE.search(chinese_title):
            raise ExportError(
                "视图声明 document_title.chinese 须为含中文（CJK）的题名："
                "%r" % chinese_title[:40])
        if not str(document_title.get("basis") or "").strip():
            raise ExportError(
                "视图声明 document_title.basis 必填：题名依据须可回查")
        original_title = str(document_title.get("original") or "").strip()
        if not original_title:
            raise ExportError(
                "视图声明 document_title.original 必填：原题须可回查")
        heading_text = _declared_original_heading(chapters)
        if heading_text is not None and original_title != heading_text:
            raise ExportError(
                "视图声明 document_title.original 与首章实际题名不符："
                "%r != %r" % (original_title[:40], heading_text[:40]))
    by_path = {chapter.path: chapter for chapter in chapters}
    exclusions = []
    for entry in payload.get("exclusions") or []:
        if not isinstance(entry, dict):
            raise ExportError("视图声明排除条目必须是对象：%r" % (entry,))
        target = Path(str(entry.get("input", ""))).expanduser().resolve()
        chapter = by_path.get(target)
        if chapter is None:
            raise ExportError(
                "视图声明排除指向未纳入输入的文件：%r" % entry.get("input"))
        lines = entry.get("lines")
        if (not isinstance(lines, list) or len(lines) != 2
                or not all(isinstance(n, int) for n in lines)):
            raise ExportError(
                "视图声明排除行区间非法：%r" % (entry.get("lines"),))
        start, end = lines
        source_lines = chapter.text.split("\n")
        if not (1 <= start <= end <= len(source_lines)):
            raise ExportError(
                "视图声明排除区间越界：%s L%d-L%d（文件共 %d 行）"
                % (entry.get("input"), start, end, len(source_lines)))
        kind = entry.get("kind")
        reason = entry.get("reason")
        if not isinstance(kind, str) or not kind.strip():
            raise ExportError("视图声明排除缺少 kind（排除类型说明）")
        if not isinstance(reason, str) or not reason.strip():
            raise ExportError("视图声明排除缺少 reason（排除理由）")
        ex_type = entry.get("type")
        if ex_type not in ("block", "inline"):
            raise ExportError(
                "视图声明排除类型必须是 block 或 inline：%r" % ex_type)
        fragment = entry.get("fragment")
        if not isinstance(fragment, str) or not fragment:
            raise ExportError("视图声明排除缺少 fragment（原文定位片段）")
        ranged_text = "\n".join(source_lines[start - 1:end])
        occurrences = ranged_text.count(fragment)
        if occurrences == 0:
            raise ExportError(
                "视图声明 fragment 与实际文本不符：%s L%d-L%d %r"
                % (entry.get("input"), start, end, fragment[:40]))
        if ex_type == "inline" and occurrences != 1:
            raise ExportError(
                "视图声明 inline 排除的 fragment 在区间内必须恰好出现"
                "一次（避免误删同行其他同文内容）：%s L%d-L%d %r 出现 %d "
                "次；请改用 block 整块排除或给出更完整的片段"
                % (entry.get("input"), start, end, fragment[:40],
                   occurrences))
        if kind.strip() == TOC_PROVENANCE_DECLARATION_KIND:
            _check_toc_provenance_declaration(
                entry, chapter, chapters, ex_type, fragment, ranged_text)
        exclusions.append(
            {
                "input": str(target),
                "chapter": chapter,
                "lines": [start, end],
                "type": ex_type,
                "kind": kind.strip(),
                "fragment": fragment,
                "reason": reason.strip(),
            })
    # 范围互不重叠（同一输入内）；边界与技术正文校验按输入分别进行。
    for chapter in chapters:
        own = sorted(
            (ex["lines"][0], ex["lines"][1]) for ex in exclusions
            if ex["chapter"] is chapter
        )
        for prev, current in zip(own, own[1:]):
            if current[0] <= prev[1]:
                raise ExportError(
                    "视图声明排除范围重叠：%s L%d-L%d 与 L%d-L%d"
                    % (chapter.path.name, prev[0], prev[1],
                       current[0], current[1]))
        block_maps = _decl_block_maps(chapter.text)
        for ex in exclusions:
            if ex["chapter"] is not chapter:
                continue
            start, end = ex["lines"]
            intersects_tech = any(
                kind in VIEW_DECLARATION_TECH_KINDS
                and not (end < first or start > last)
                for first, last, kind in block_maps
            )
            if intersects_tech:
                raise ExportError(
                    "视图声明排除区间覆盖技术正文（标题/代码围栏/表格等）："
                    "%s L%d-L%d" % (chapter.path.name, start, end))
            if ex["type"] == "block":
                aligned = any(
                    kind in VIEW_DECLARATION_BLOCK_KINDS
                    and (first, last) == (start, end)
                    for first, last, kind in block_maps
                )
                if not aligned:
                    raise ExportError(
                        "block 型排除未对齐 Markdown 块边界"
                        "（整块引用块/段落/列表）：%s L%d-L%d"
                        % (chapter.path.name, start, end))
    return {
        "path": str(Path(path).expanduser()),
        "sha256": sha256_file(Path(path).expanduser()),
        "document_title": document_title,
        "exclusions": exclusions,
    }


def project_view_declared(text, block_spans, inline_exclusions):
    """按声明区间投影导出视图（原文行号）：block 整块移除，inline 删片段。

    block_spans 为 1 起含端点的行区间集合（可与管理字段/目录出处段区间
    合并传入）；inline 删除区间内各行中的全部 fragment 出现。找不到
    fragment 时明确失败（校验已先行，此处为双保险）。
    """
    drop = set()
    for start, end in block_spans:
        drop.update(range(start - 1, end))
    kept = [
        (number, line)
        for number, line in enumerate(text.split("\n"), start=1)
        if number - 1 not in drop
    ]
    for exclusion in inline_exclusions:
        start, end = exclusion["lines"]
        fragment = exclusion["fragment"]
        hit = False
        for index, (number, line) in enumerate(kept):
            if start <= number <= end and fragment in line:
                kept[index] = (number, line.replace(fragment, ""))
                hit = True
        if not hit:
            raise ExportError(
                "视图声明行内片段不在排除区间内：%r" % fragment[:40])
    return "\n".join(line for _number, line in kept)


def decide_toc_provenance(chapters, view_declaration=None):
    """目录出处决定（设计 §8.4 顺序）：声明接管优先，其余候选自动判断。

    在视图声明加载校验之后、章节解析之前调用。kind=toc-provenance 声明
    覆盖的“译自”候选不再进入自动判断（声明内容已在加载时校验：以
    “译自”开头、含可定位来源、不含章节导航）；未被覆盖的候选按设计
    §8.3 窄格式自动语法判定（结构条件 + 整行完整消费一条来源语法）。
    声明覆盖与自动区间不得重叠；任何边界/语法失败在生成候选前
    ExportError（旧 PDF 不变）。声明接管的出处原文记入
    chapter.toc_provenance_fragments，与自动段一起作为来源门禁证据。
    """
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    if toc_chapter is None:
        return
    declared, others = [], []
    for ex in (view_declaration or {}).get("exclusions") or []:
        if ex["chapter"] is not toc_chapter:
            continue
        bucket = declared \
            if ex["kind"] == TOC_PROVENANCE_DECLARATION_KIND else others
        bucket.append(ex)
    lines = toc_chapter.text.split("\n")
    for ex in declared:
        if ex["type"] == "inline":
            toc_chapter.toc_provenance_fragments.append(ex["fragment"])
        else:
            toc_chapter.toc_provenance_fragments.append(
                _toc_block_paragraph(lines, ex["lines"][0], ex["lines"][1]))

    def _resolve_nav(path_part):
        target = ((toc_chapter.dir / path_part).resolve()
                  if path_part else toc_chapter.path)
        return any(c.path == target for c in chapters)

    def _takeover_range(ex):
        """声明实际接管的行区间：block 为整区间；inline 为 fragment 实际
        覆盖的行（区间内其余行不是获准内容，仍须进入自动判断）。"""
        start, end = ex["lines"]
        if ex["type"] == "block":
            return (start, end)
        haystack = "\n".join(lines[start - 1:end])
        at = haystack.find(ex["fragment"])
        if at < 0:
            # 加载校验已保证 fragment 在区间内出现；兜底不扩大接管范围
            return (start, end)
        first = start + haystack[:at].count("\n")
        return (first, first + ex["fragment"].count("\n"))

    takeover = [_takeover_range(ex) for ex in declared]
    span = toc_provenance_span(
        toc_chapter.text,
        declared_ranges=takeover,
        resolve_nav=_resolve_nav)
    if span is None:
        return
    start, end, _paragraph = span
    for ex_start, ex_end in takeover + [tuple(ex["lines"]) for ex in others]:
        if not (ex_end < start or ex_start > end):
            raise ExportError(
                "目录出处自动区间与视图声明排除范围重叠：%s L%d-L%d 与声明"
                " L%d-L%d；同一出处只能由一种机制排除"
                % (toc_chapter.path.name, start, end, ex_start, ex_end))
    toc_chapter.toc_provenance_exclusion = {
        "start_line": start,
        "end_line": end,
        "reason": TOC_PROVENANCE_EXCLUSION_REASON,
    }
    spans = [(item["start_line"], item["end_line"])
             for item in toc_chapter.exclusions]
    spans.append((start, end))
    toc_chapter.projected_text = remove_line_spans(toc_chapter.text, spans)


def apply_view_declaration(chapter, declaration):
    """把视图声明的授权排除叠加到本章导出视图（在既有投影之上）。"""
    if declaration is None:
        return
    own = [ex for ex in declaration["exclusions"] if ex["chapter"] is chapter]
    if not own:
        return
    spans = [(item["start_line"], item["end_line"])
             for item in chapter.exclusions]
    if chapter.toc_provenance_exclusion is not None:
        spans.append(
            (
                chapter.toc_provenance_exclusion["start_line"],
                chapter.toc_provenance_exclusion["end_line"],
            )
        )
    spans.extend(
        tuple(ex["lines"]) for ex in own if ex["type"] == "block"
    )
    inline = [ex for ex in own if ex["type"] == "inline"]
    chapter.projected_text = project_view_declared(
        chapter.text, spans, inline)


def collect_provenance(chapters, toc_chapter, provenance_map):
    """收集实际输出范围的出处事实并按最低标准分类，返回事实字典。

    最低标准：每章均可定位其具体原文；输入中已知的版本/日期原样保留，
    源未提供不编造。章首四类管理字段全部从章首移除；彼此不同的来源
    信息以组合形式保留在导出报告（front_text）；与目录出处段/映射文本
    完全一致的组合不再重复。返回事实字典供门禁、报告与核验预期使用
    （PDF 不显示前置出处，见 TOC_PROVENANCE_EXCLUSION_REASON）。
    """
    chapter_facts = []
    for chapter in chapters:
        values = head_field_values(chapter.text)
        chapter_facts.append(
            {
                "chapter": chapter,
                "source": " ".join(values.get("来源", [])),
                "original": " ".join(values.get("原文", [])),
                "fetch_date": "；".join(values.get("抓取日期", [])),
            }
        )
    toc_text = find_toc_provenance(toc_chapter)
    covered = dict(provenance_map["covered"]) if provenance_map else {}
    basis_text = (toc_text or "") + "\n" + (
        provenance_map["text"] if provenance_map else "")
    def represented(combo):
        """组合是否已由目录出处段/映射文本集中呈现。

        已知版本/日期与原文限定说明属于不可丢失字段：组合中每个非空
        字段（来源定位符、原文文字、抓取日期）都必须出现在集中说明里，
        否则该组合仍需在前置区保留，不能只比对来源 URL。
        """
        source = combo["combo"]["source"]
        original = combo["combo"]["original"]
        fetch_date = combo["combo"]["fetch_date"]
        if fetch_date and fetch_date not in basis_text:
            return False
        if original and _norm_prov(original) not in _norm_prov(basis_text):
            return False
        if source:
            if has_provenance_locator(source):
                locators = _PROVENANCE_LOCATOR_RE.findall(source)
                if not all(token in basis_text for token in locators):
                    return False
                # 定位符之外的剩余文字（版本/抓取说明等）同样不可丢失
                remainder = _norm_prov(source)
                for token in locators:
                    remainder = remainder.replace(_norm_prov(token), ' ')
                remainder = remainder.strip()
                return (not remainder
                        or _norm_prov(remainder) in _norm_prov(basis_text))
            return _norm_prov(source) in _norm_prov(basis_text)
        return True

    def _combo_represented(fact):
        return represented({"combo": {
            "source": fact["source"], "original": fact["original"],
            "fetch_date": fact["fetch_date"]}})


    complete, incomplete, unavailable = [], [], []
    combos = []
    for index, fact in enumerate(chapter_facts, start=1):
        chapter = fact["chapter"]
        if chapter.is_toc:
            continue  # 目录文件不是正文章节，不适用每章可定位原文标准
        if index in covered:
            complete.append(index)
        elif has_provenance_locator(fact["source"]) \
                or has_provenance_locator(fact["original"]):
            complete.append(index)
        elif (toc_text is not None or provenance_map is not None) \
                and (fact["source"] or fact["original"]) \
                and _combo_represented(fact):
            # 目录出处段/映射集中说明存在，且该章的来源文字确实被集中
            # 说明覆盖（定位符/文字逐项出现在其中）；无法对应的章节
            # （如写了另一本书的来源）不能借目录段落通过门禁。
            complete.append(index)
        elif fact["source"] or fact["original"]:
            incomplete.append(index)
        else:
            unavailable.append(index)
        if not (fact["source"] or fact["original"] or fact["fetch_date"]):
            continue
        combo = {"source": fact["source"], "original": fact["original"],
                 "fetch_date": fact["fetch_date"]}
        for existing in combos:
            if existing["combo"] == combo:
                existing["chapters"].append(index)
                break
        else:
            combos.append({"combo": combo, "chapters": [index]})

    front_combos = [item for item in combos if not represented(item)]
    front_lines = []
    for item in front_combos:
        combo = item["combo"]
        parts = []
        if combo["source"]:
            parts.append("来源：%s" % combo["source"])
        if combo["original"]:
            parts.append("原文：%s" % combo["original"])
        if combo["fetch_date"]:
            parts.append("抓取日期：%s" % combo["fetch_date"])
        scope = "、".join("第 %d 章" % i for i in item["chapters"])
        front_lines.append("%s（适用：%s）" % ("；".join(parts), scope))
    front_text = "\n".join(front_lines)
    # 实际采用的集中出处段（核验成品位置用）：生成前置 > 目录“译自…”段
    # > 映射区间段。目录/映射段以渲染后的可见文字传递——Markdown 链接等
    # 标记不会出现在 PDF 可见文本中，用原始源码定位会误判缺失。
    if front_text:
        adopted_front = front_text
    elif toc_text is not None:
        adopted_front = visible_provenance_text(toc_text)
    elif provenance_map is not None:
        adopted_front = visible_provenance_text(provenance_map["text"])
    else:
        adopted_front = ""
    return {
        "mode": ("mapping" if provenance_map is not None
                 else "toc" if toc_text is not None else "generated"),
        "complete": complete,
        "incomplete": incomplete,
        "unavailable": unavailable,
        "combos": [{"source": item["combo"]["source"],
                    "original": item["combo"]["original"],
                    "fetch_date": item["combo"]["fetch_date"],
                    "chapters": item["chapters"]} for item in combos],
        "front_text": front_text,
        "toc_paragraph": toc_text,
        "adopted_front": adopted_front,
        "covered": sorted(covered),
    }

# ---------------------------------------------------------------------------
# 印刷目录（显式目录角色：00_目录.md；两遍打印，页码为 PDF 实际页序）
# ---------------------------------------------------------------------------

TOC_FILE_NAME = "00_目录.md"
TOC_PAGE_PLACEHOLDER = "…"
MAX_TOC_PRINTS = 3  # 探测 1 次 + 回填 1 次 + 修正 1 次


class TocError(Exception):
    """印刷目录无法建立或页码未收敛。"""


def _toc_link_targets(toc_chapter, chapters):
    """定位目录正文中的章节链接；返回 [(anchor, 目标章, fragment)]。

    只认表格/列表中的本地文档链接；范围外目标由调用方显式报告。
    """
    results = []
    for anchor in toc_chapter.soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if urlsplit(href).scheme or href.startswith("#"):
            continue
        path_part, _, raw_fragment = href.partition("#")
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        included = next((c for c in chapters if c.path == target), None)
        if included is None:
            continue
        results.append((anchor, included, unquote(raw_fragment) if raw_fragment else None))
    return results


def build_print_toc(toc_chapter, chapters, diagnostics, include_sections):
    """把目录文件的导航列表合成为一次印刷目录，返回条目列表。

    条目标题取自已消解的译文标题（章首 H1 或链接指向的标题），保留官方
    编号；重复章名按链接目标消歧，不按第一个同名标题猜测。被消费的导航
    表格/列表连同空容器壳与其纯引导句从目录正文中移除，其余说明文字保留；
    范围外链接记录待处置，其纯导航行（分篇导出时未纳入章）一并移除。
    """
    entries = []
    link_sections = []
    seen_chapters = set()
    out_links = []
    consumed = []
    blocked = False
    for anchor, included, fragment in _toc_link_targets(toc_chapter, chapters):
        container = anchor.find_parent(["li", "tr"])
        if container is None:
            continue
        if container in consumed:
            continue
        if fragment and fragment not in included.targets:
            # 坏目标在消费前定位并阻断：不回退章首掩盖错误，也不静默
            # 省略该导航条目（T12/T13 合同）。
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "toc-fragment-unresolved",
                    "message": "目录链接片段无法消解：%s#%s"
                    % (included.path.name, fragment),
                    "input": str(toc_chapter.path),
                }
            )
            blocked = True
            continue
        target_info = included.targets.get(fragment) or {}
        if (include_sections and fragment
                and target_info.get("kind") == "anchor"):
            # 普通锚点与节标题没有可可靠确定的关联：明确定位并阻断，
            # 不猜测、不静默省略（T06 合同）。默认章级模式按章折叠。
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "toc-anchor-unassociated",
                    "message": "目录链接片段指向普通锚点，无法确定关联的"
                    "一级节标题：%s#%s" % (included.path.name, fragment),
                    "input": str(toc_chapter.path),
                }
            )
            blocked = True
            continue
        consumed.append(container)
        # 目录链接按章级折叠：同一章的首个链接产生章级条目（标题恒取
        # 章首标题），节/片段链接默认折叠进所属章。
        if included.index not in seen_chapters:
            seen_chapters.add(included.index)
            if included.headings:
                target_id = included.headings[0]["id"]
                title = included.headings[0]["text"]
            else:
                target_id = included.prefix + "body"
                title = included.path.stem
            entries.append(
                {"level": 1, "title": title, "target": target_id,
                 "chapter_index": included.index}
            )
        # --toc-sections 时，指向二级标题的可消解片段并入一级节；章首
        # （H1）与更深层（H3+）及普通锚点按章级折叠，不另立条目。
        if not (include_sections and fragment):
            continue
        target_info = included.targets.get(fragment) or {}
        if not (target_info.get("kind") == "heading"
                and target_info.get("level") == 2):
            continue
        target_id = included.prefix + fragment
        heading = next(
            (h for h in included.headings if h["id"] == target_id), None
        )
        if heading is not None:
            section = {
                "level": 2, "title": heading["text"], "target": target_id,
                "chapter_index": included.index,
            }
            if section not in link_sections:
                link_sections.append(section)

    # 纯文本层级列表（无链接）：目录导航的官方层级来源。列表过半条目
    # 的“编号+标题”或标题能对上已纳入章节的标题才算层级列表；消费时
    # 只移除已确认的导航条目，其余说明条目保留，普通说明列表整体不动。
    # 选择一级节时按节号映射到目标章标题后再并入打印导航。注意
    # markdown-it 会把“- 1. 章名”的编号解析为嵌套有序列表，判定必须
    # 看全部后代条目文本而非仅顶层子项。
    def _corroborated(item_text):
        if not item_text:
            return False
        match = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", item_text)
        if match is not None:
            number, title = match.group(1), match.group(2).strip()
            return any(
                heading["text"].startswith(number) and title in heading["text"]
                for chapter in chapters if chapter is not toc_chapter
                for heading in chapter.headings
            )
        # 无编号形态（编号被解析为嵌套有序列表的章名项）：按标题对应。
        return any(
            item_text in entry["title"] and entry["level"] == 1
            for entry in entries
        ) or any(
            item_text in heading["text"]
            for chapter in chapters if chapter is not toc_chapter
            for heading in chapter.headings
        )

    hierarchy_lists = []  # [(列表元素, 已确认导航条目列表)]
    for element in toc_chapter.soup.find_all(["ul", "ol"]):
        if element.find_parent(["li"]) is not None:
            continue  # 只取顶层列表
        if element.find("a", href=True) is not None:
            continue  # 含链接的列表已按章级处理
        items = element.find_all("li")
        nav_items = [
            item for item in items
            if _corroborated(item.get_text(" ", strip=True))
        ]
        if not nav_items or len(nav_items) * 2 < len(items):
            continue  # 与本书标题对不上的按说明列表保留
        hierarchy_lists.append((element, nav_items))
    entries.extend(link_sections)
    if include_sections:
        for _element, nav_items in hierarchy_lists:
            # 只在已确认的导航条目中找节号（章级项无多点节号，不匹配）。
            for item in nav_items:
                text = item.get_text(" ", strip=True)
                match = re.match(r"^(\d+(?:\.\d+)+)\.?\s+(.+)$", text)
                if not match:
                    continue
                number = match.group(1)
                chapter_number = number.split(".")[0]
                matched = None
                for entry in entries:
                    if entry["level"] != 1:
                        continue
                    if re.match(
                        r"^%s[.\s（(]" % re.escape(chapter_number),
                        entry["title"],
                    ) or re.search(
                        r"第\s*%s\s*章" % re.escape(chapter_number),
                        entry["title"],
                    ):
                        matched = entry
                        break
                if matched is None:
                    diagnostics.append(
                        {
                            "severity": "warn",
                            "code": "toc-section-unmatched",
                            "message": "目录一级节未匹配到所属章条目：%s" % text[:60],
                            "input": str(toc_chapter.path),
                        }
                    )
                    continue
                included = next(
                    (c for c in chapters if c.index == matched["chapter_index"]),
                    None,
                )
                if included is None:
                    continue
                heading = next(
                    (
                        h
                        for h in included.headings
                        if h["text"].startswith(number)
                        or h["text"].split("（")[0].startswith(number)
                    ),
                    None,
                )
                if heading is None:
                    diagnostics.append(
                        {
                            "severity": "warn",
                            "code": "toc-section-unmatched",
                            "message": "目录一级节未在译文中找到对应标题：%s" % text[:60],
                            "input": str(toc_chapter.path),
                        }
                    )
                    continue
                entries.append(
                    {
                        "level": 2,
                        "title": heading["text"],
                        "target": heading["id"],
                        "chapter_index": included.index,
                    }
                )

    # 章级在前、节级随后并入所属章；按文档目标顺序重排为打印顺序。
    by_target = {e["target"]: e for e in entries}
    ordered = []
    for entry in entries:
        if entry["level"] == 1:
            ordered.append(entry)
            for section in [
                e for e in entries
                if e["level"] == 2 and e["chapter_index"] == entry["chapter_index"]
            ]:
                if section not in ordered:
                    ordered.append(section)
    entries = [by_target[e["target"]] for e in ordered]

    # 范围外链接：目录文件中全部未纳入导出的本地文档链接都记录待处置，
    # 不生成伪内部链接（分篇导出时未纳入章的链接在这里显式报告）。
    recorded_out = set()
    out_anchors = []
    out_identity = set()
    for anchor in toc_chapter.soup.find_all("a", href=True):
        href = anchor.get("href", "")
        path_part = href.partition("#")[0]
        if not path_part or urlsplit(href).scheme:
            continue
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        if any(c.path == target for c in chapters):
            continue
        out_anchors.append((anchor, target))
        for name in (target.stem, target.name, anchor.get_text(strip=True)):
            if name:
                out_identity.add(name)
        key = (href, anchor.get_text(strip=True)[:80])
        if key in recorded_out:
            continue
        recorded_out.add(key)
        out_links.append(
            {
                "href": href,
                "text": anchor.get_text(strip=True)[:80],
                "exists": target.exists(),
            }
        )

    # 从目录正文移除被消费的导航容器。层级列表只移除已确认的导航条目，
    # 被导航条目覆盖的祖先随条目一并消失，其余说明条目与说明文字保留；
    # 整个列表因此清空时才连同纯引导句移除。数据行全部被消费的表格只剩
    # 表头壳；紧邻被移除容器、以冒号结尾且不含链接的纯引导句指向已消失
    # 的导航内容，随容器一并移除。
    def _previous_element(node):
        for sibling in node.previous_siblings:
            if isinstance(sibling, Tag):
                return sibling
        return None

    def _is_lead_in(node):
        return (
            node is not None
            and node.name == "p"
            and node.find("a") is None
            and node.get_text(" ", strip=True).endswith(("：", ":"))
        )

    def _consume_with_lead_in(element):
        lead = _previous_element(element)
        element.decompose()
        if _is_lead_in(lead) and not lead.decomposed:
            # 设计允许“保留说明，或无法无损增强时报告”；引导句指向已
            # 消失的导航内容，移除时按报告分支记录证据。
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "toc-lead-in-removed",
                    "message": "目录导航引导句随被消费容器移除：%s"
                    % lead.get_text(" ", strip=True)[:60],
                    "input": str(toc_chapter.path),
                }
            )
            lead.decompose()

    def _nav_only(element, extra_identity=()):
        """容器去掉导航链接后是否只剩导航元数据（无说明/图片）。

        章编号、目标章标题、文件名与纯数字单元是导航自身的组成部分；
        除此之外的可见内容（技术说明、注记、图片）说明容器是混合的。
        extra_identity 仅供范围外目标的行使用（分篇时未纳入章的链接
        文本与文件名同样是导航元数据），不改变已纳入容器的判定。
        """
        identity = set(extra_identity)
        for chapter in chapters:
            if chapter is toc_chapter:
                continue
            if chapter.headings:
                identity.add(chapter.headings[0]["text"])
            identity.add(chapter.path.stem)
            identity.add(chapter.path.name)
        numeric = re.compile(r"^[\s\d.、,，;；()（）#\-]*$")

        def scan(node):
            for child in node.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if not text or numeric.match(text):
                        continue
                    if any(text in name or name in text for name in identity):
                        continue
                    return False
                elif isinstance(child, Tag):
                    if child.name == "a" and child.get("href"):
                        continue
                    if child.name == "img":
                        return False
                    if not scan(child):
                        return False
            return True

        return scan(element)

    def _included_target(anchor):
        path_part = anchor.get("href", "").partition("#")[0]
        if not path_part or urlsplit(anchor.get("href", "")).scheme:
            return None
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        return target if any(c.path == target for c in chapters) else None

    for container in consumed:
        if _nav_only(container):
            container.decompose()
        else:
            # 混合容器（导航链接 + 技术说明，如 li 内说明段或表格说明
            # 单元格）：只解除导航链接本身，说明内容原样保留。
            for anchor in container.find_all("a", href=True):
                if _included_target(anchor) is not None:
                    anchor.replace_with(anchor.get_text(strip=True))
    for anchor, _target in out_anchors:
        if anchor.decomposed:
            continue  # 已随所属的已纳入导航行一并消费
        # 分篇导出：范围外目标的纯导航行不是本书印刷目录的内容，随消费
        # 一并移除（仍按 toc-out-link 记录待处置）；混合容器与不在导航
        # 行内的裸链接只解除链接，说明文字保留。
        container = anchor.find_parent(["li", "tr"])
        if container is not None and _nav_only(container, out_identity):
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "toc-out-of-scope-removed",
                    "message": "范围外导航行已从印刷目录移除：%s"
                    % container.get_text(" ", strip=True)[:60],
                    "input": str(toc_chapter.path),
                }
            )
            container.decompose()
        else:
            anchor.replace_with(anchor.get_text(strip=True))
    for _element, nav_items in hierarchy_lists:
        # 只消费已确认的导航条目；被消费祖先覆盖的后代不再单独处理。
        nav_ids = {id(item) for item in nav_items}
        for item in nav_items:
            if any(id(parent) in nav_ids for parent in item.parents):
                continue
            item.decompose()
    for item in list(toc_chapter.soup.find_all("li")):
        # 导航后代被消费后残留的空列表项渲染为空圆点，一并清理。
        if not item.get_text(strip=True) and item.find(["a", "img"]) is None:
            item.decompose()
    for table in list(toc_chapter.soup.find_all("table")):
        if table.find("td") is None:
            _consume_with_lead_in(table)
    for element in list(toc_chapter.soup.find_all(["ul", "ol"])):
        if element.find("li") is None:
            _consume_with_lead_in(element)

    if not entries:
        if blocked:
            # 阻断诊断已定位具体坏目标，交由失败诊断路径终止导出，
            # 不再用“无导航条目”掩盖具体原因。
            return [], out_links
        raise TocError("目录文件 %s 未包含任何指向已纳入章节的导航条目" % toc_chapter.path.name)
    return entries, out_links


def render_toc_nav(entries, pages=None):
    """渲染印刷目录导航容器；pages 为 None 时页码用占位符（探测打印）。"""
    items = []
    for index, entry in enumerate(entries, start=1):
        page = (
            TOC_PAGE_PLACEHOLDER
            if pages is None
            else str(pages.get(entry["target"], TOC_PAGE_PLACEHOLDER))
        )
        items.append(
            '<div class="toc-entry toc-level-%d">'
            '<a href="#%s"><span class="toc-text">%s</span>'
            '<span class="toc-leader" aria-hidden="true"></span>'
            '<span class="toc-page" id="tocpage-%d">%s</span></a></div>'
            % (
                entry["level"],
                escape(entry["target"], quote=True),
                escape(entry["title"]),
                index,
                escape(page),
            )
        )
    return '<nav class="print-toc">%s</nav>' % "".join(items)


def insert_toc_nav(toc_chapter, nav_html):
    """把导航容器插入目录标题之后、说明文字之前。"""
    nav = BeautifulSoup(nav_html, "html.parser").nav
    heading = toc_chapter.soup.find(["h1", "h2"])
    if heading is not None:
        heading.insert_after(nav)
        return
    first = toc_chapter.soup.find(["p", "ul", "ol", "table"])
    if first is None:
        toc_chapter.soup.insert(0, nav)
    else:
        first.insert_before(nav)


def update_toc_nav(toc_chapter, entries, pages):
    """回填页码：替换现有导航容器，保持布局条件不变（固定页码列宽）。"""
    nav = toc_chapter.soup.find("nav", class_="print-toc")
    fresh = BeautifulSoup(render_toc_nav(entries, pages), "html.parser").nav
    if nav is None:
        insert_toc_nav(toc_chapter, str(fresh))
    else:
        nav.replace_with(fresh)


def extract_toc_pages(pdf_path, entries):
    """从 PDF 实际命名目的地读取各条目目标页（0 起），不推算分页。"""
    import pypdf
    from urllib.parse import quote

    reader = pypdf.PdfReader(str(pdf_path))
    named = {}
    for name, dest in reader.named_destinations.items():
        try:
            named[str(name).lstrip("/")] = reader.get_destination_page_number(dest)
        except Exception:  # noqa: BLE001  个别目的地无法解析时跳过
            continue
    result = {}
    missing = []
    for entry in entries:
        target = entry["target"]
        # Chromium 会把目的地名称中的非 ASCII 片段按 URL 编码写出。
        page = named.get(target)
        if page is None:
            page = named.get(quote(target, safe=""))
        if page is None:
            missing.append(target)
        else:
            result[target] = page
    if missing:
        raise TocError("目录条目目标未在 PDF 中生成命名目的地：%s" % ", ".join(missing[:5]))
    return result


# ---------------------------------------------------------------------------
# 章首管理字段投影（只作用于导出视图；Markdown 原文与输入摘要不变）
# ---------------------------------------------------------------------------

# PDF 默认排除的章首模板字段（D6/A14）：管理字段全部移出章首；出处信息
# 保留在导出报告与来源门禁中，PDF 导出视图不显示前置出处（R2/C2）。
MANAGEMENT_FIELD_LABELS = ("原文", "译例说明", "来源", "抓取日期")
# 章首管理引用块的家族标签：引用块首个块是这些标签的字段段时才属于
# 章首管理区；注（Note）等其他标签的引用块是技术正文边界。
MANAGEMENT_FAMILY_LABELS = ("原文", "译例说明", "来源", "抓取日期")
EXCLUSION_REASON = "章首管理字段默认排除（获准投影，Markdown 保留）"

# 字段行形态：`> **标签**：内容` 或 `> 标签：内容`。标签不含空白、列表符
# 与引用符；列表项和普通续行即使含冒号也不构成新字段。
HEAD_FIELD_RE = re.compile(
    r"^>\s*(?:\*\*)?\s*([^\s*：:>#-][^\s*：:>#-]{0,14})\s*(?:\*\*)?\s*[：:]\s*(.*)$"
)

# 章首结构分析使用独立 CommonMark 实例：只关心块结构与源行位置，
# 不带公式/脚注等渲染插件，也不信任源内联 HTML。
_HEAD_STRUCTURE_MD = MarkdownIt("commonmark")


def head_field_label(line):
    """返回引用块行的字段标签；非字段行返回 None。"""
    stripped = line.strip()
    if not stripped.startswith(">"):
        return None
    match = HEAD_FIELD_RE.match(stripped)
    return match.group(1) if match else None


def _quote_child_blocks(tokens, open_index, close_index, base_level, lines):
    """列出引用块的直接子块：[(起始行, 结束行(不含), 标签或 None, 类型)]。

    标签取段落首行按字段形态匹配的结果（任意家族外标签也算字段行，
    用于终止前一字段的续行）；围栏、列表、嵌套引用等块级 token 自带
    覆盖整个块的源行区间。类型用于限定续行范围：只有无标签的段落与
    列表是字段延续，围栏、缩进代码与嵌套引用是技术内容，终止续行。
    """
    blocks = []
    for token in tokens[open_index + 1:close_index]:
        if token.level != base_level + 1 or token.map is None:
            continue
        if token.type in ("fence", "code_block"):
            blocks.append([token.map[0], token.map[1], None, "code"])
        elif token.type in ("hr", "html_block"):
            blocks.append([token.map[0], token.map[1], None, "other"])
        elif token.type.endswith("_open"):
            kind = {"paragraph_open": "paragraph", "list_item_open": "list",
                    "ordered_list_open": "list", "bullet_list_open": "list",
                    "blockquote_open": "quote"}.get(token.type, "other")
            label = head_field_label(lines[token.map[0]]) \
                if token.type == "paragraph_open" else None
            blocks.append([token.map[0], token.map[1], label, kind])
    return blocks


def _management_field_segments(text):
    """章首管理区字段段：[(label, start_line, end_line)]，1 起含完整续行。

    与字段投影共用同一 token 边界（引用块、围栏、缩进代码、嵌套引用与
    CommonMark lazy 续行均由解析器判定）：投影删除的每一段就是出处
    收集要保留的同一段，二者不各自按行猜测。
    """
    tokens = _HEAD_STRUCTURE_MD.parse(text)
    lines = text.split("\n")
    segments = []
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if token.type == "heading_open":
            index += 3
            continue
        if token.type == "hr":
            index += 1
            continue
        if token.type != "blockquote_open":
            break  # 首个非章首块级 token：技术正文边界
        close_index = index + 1
        depth = 0
        while close_index < total:
            if tokens[close_index].type == "blockquote_open":
                depth += 1
            elif tokens[close_index].type == "blockquote_close":
                if depth == 0:
                    break
                depth -= 1
            close_index += 1
        blocks = _quote_child_blocks(
            tokens, index, close_index, token.level, lines
        )
        if not blocks or not (
            blocks[0][2] in MANAGEMENT_FAMILY_LABELS
        ):
            break  # 首个子块不是家族字段段：技术引用块，正文边界
        # 字段段按行识别：同一引用段落可能合并多个字段行（模板中
        # “原文”“来源”间常无空行），块内逐行定字段边界；段落与列表
        # 块的无标签行是延续，围栏/嵌套引用/其他块是技术内容，终止延续。
        active = None
        for start, block_end, _label, kind in blocks:
            if kind == "paragraph":
                for line_no in range(start, block_end):
                    label = head_field_label(lines[line_no])
                    if label is not None:
                        active = [label, line_no + 1, line_no + 1]
                        segments.append(active)
                    elif active is not None:
                        active[2] = line_no + 1
            elif active is not None and kind == "list":
                active[2] = max(active[2], block_end)
            else:
                active = None
        index = close_index + 1
    return segments


def project_management_fields(text):
    """按 Markdown 块结构投影章首管理字段，返回 (投影文本, 排除区间列表)。

    章首区域由块级 token 顺延构成：标题、主题分隔线与管理引用块；管理
    引用块的首个子块必须是家族标签（原文/译例说明/来源/抓取日期）的
    字段段，其后的块（围栏、列表、嵌套引用、段落，含 CommonMark lazy
    续行，续行由解析器并入字段段）都算字段延续，直到下一个字段行。
    首个非章首内容——正文段、列表、表格、缩进代码、Note 等其他标签
    引用块——即技术正文边界。只排除"原文""译例说明"字段段及其在
    同一引用块内的延续块；代码围栏、缩进代码与嵌套结构由解析器给出
    确定边界，不按文本行猜测。区间为 1 起始行号，end 为最后被排除行。
    """
    lines = text.split("\n")
    exclusions = [
        {
            "label": label,
            "start_line": start,
            "end_line": end,
            "reason": EXCLUSION_REASON,
        }
        for label, start, end in _management_field_segments(text)
        if label in MANAGEMENT_FIELD_LABELS
    ]
    if not exclusions:
        return text, []
    removed = set()
    for span in exclusions:
        removed.update(range(span["start_line"] - 1, span["end_line"]))
    projected = [
        line for number, line in enumerate(lines) if number not in removed
    ]
    return "\n".join(projected), exclusions



# ---------------------------------------------------------------------------
# Markdown 解析层（verify_pdf.py 复用同一解析，另用独立原始扫描交叉核对）
# ---------------------------------------------------------------------------

LEGACY_INLINE_RE = re.compile(r"\\\((.*)\\\)", re.S)
LEGACY_DISPLAY_RE = re.compile(r"\\\[(.*)\\\]", re.S)
# KaTeX 仅在 display 模式接受的环境；内联包装含此类环境时按数学含义
# 提升为显示模式渲染（LaTeX 语义本身即为块级），否则 KaTeX 拒绝渲染。
DISPLAY_ONLY_ENV_RE = re.compile(
    r"\\begin\{(?:equation|align|gather|flalign|multline|alignat|split)\*?\}")


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
    latex = match.group(1).strip() if match else text
    original_form = "legacy_paren" if match else "dollar_inline"
    mode = "display" if DISPLAY_ONLY_ENV_RE.search(latex) else "inline"
    return latex, mode, original_form


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
        return wrap_code_block(body, token.content)

    def render_code_block(_renderer, tokens, idx, options, env):
        token = tokens[idx]
        body = "<pre><code>%s</code></pre>" % escape(token.content)
        return wrap_code_block(body, token.content)

    markdown.add_render_rule("fence", render_fence)
    markdown.add_render_rule("code_block", render_code_block)
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
        self.is_toc = source_path.name == TOC_FILE_NAME
        self.text = source_path.read_text(encoding="utf-8")
        # 导出视图：章首管理字段已在解析前投影掉；text 始终是完整原件。
        # 目录出处段在视图声明加载后由 decide_toc_provenance 决定（声明接管
        # 优先于自动判断，设计 §8.4），此处不先行判定，保证显式声明退路可达。
        self.projected_text, self.exclusions = project_management_fields(self.text)
        self.toc_provenance_exclusion = None
        # toc-provenance 声明接管的出处原文片段（block 块文本 / inline
        # fragment），与自动段一起作为来源门禁证据与核验预期。
        self.toc_provenance_fragments = []
        self.math = []
        self.headings = []  # {level, text, slug, id}
        self.targets = {}  # 未加前缀片段 -> 描述（用于链接消解）
        self.internal_links = []  # {fragment, kind, source_line}
        self.external_links = []  # href
        self.range_out_links = []  # {href, source_line, exists}
        self.unlinked_links = []  # 转为纯文字的术语表等目标链接投影
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
    """解析单章（经授权投影后的导出视图）并渲染为带前缀的 HTML 片段。"""
    markdown, formatter = build_markdown(chapter.math, chapter.prefix)
    raw_html = markdown.render(chapter.projected_text)
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
# 已标识译注的导出视图排除（R2/C6：【译注：…】 只从 PDF 视图移除片段）
# ---------------------------------------------------------------------------

# 已标识译注语法（references/translation_conventions.md）：只处理正文文本
# 节点中的完整片段；代码块、行内 code 与原文引用块不扫描、不删除。
TRANSLATOR_NOTE_RE = re.compile(r"【译注：[^】]*】")
TRANSLATOR_NOTE_SKIP_ANCESTORS = ("pre", "code", "blockquote")

_ASCII_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def _note_code_span_intervals(chunk_lines):
    """段内行内代码的字符区间（CommonMark 反引号串配对）。

    核验侧同规则的独立实现：转义反引号不开启代码串，按原文搜索等长
    闭合串，未闭合的串按字面文本处理。
    """
    text = "\n".join(chunk_lines)
    total = len(text)
    intervals = []
    position = 0
    while position < total:
        char = text[position]
        if (
            char == "\\"
            and position + 1 < total
            and text[position + 1] in _ASCII_PUNCTUATION
        ):
            position += 2
            continue
        if char != "`":
            position += 1
            continue
        run_end = position
        while run_end < total and text[run_end] == "`":
            run_end += 1
        length = run_end - position
        closer_end = None
        search = run_end
        while search < total:
            if text[search] == "`":
                end = search
                while end < total and text[end] == "`":
                    end += 1
                if end - search == length:
                    closer_end = end
                    break
                search = end
            else:
                search += 1
        if closer_end is None:
            position = run_end
            continue
        intervals.append((position, closer_end))
        position = closer_end
    return intervals


def _flush_note_chunk(chunk, found):
    """在段落候选行（拼接文本）上登记译注出现，排除行内代码区间。"""
    if not chunk:
        return
    intervals = _note_code_span_intervals([line for _, line in chunk])
    starts = []
    offset = 0
    for _number, line in chunk:
        starts.append(offset)
        offset += len(line) + 1
    joined = "\n".join(line for _, line in chunk)
    for match in TRANSLATOR_NOTE_RE.finditer(joined):
        if any(s <= match.start() < e for s, e in intervals):
            continue  # 行内代码中的同形文字不是译注
        line_no = next(
            number
            for index, (number, line) in enumerate(chunk)
            if starts[index] <= match.start() < starts[index] + len(line) + 1
        )
        found.append((line_no, match.group(0)))
    del chunk[:]


def translator_note_occurrences(text):
    """按源序列出正文中已标识译注的逐次出现：[(原始行号, 片段)]。

    核验侧 scan_translator_notes 同一语言规则的独立实现（双向独立重建
    是证据核对的设计属性，不共享实现）：CommonMark 解析给出围栏/缩进
    代码与引用块的保护行，段内排除行内代码区间，跨软换行的片段归属
    起始行。
    """
    protected_lines = set()
    for token in _HEAD_STRUCTURE_MD.parse(text):
        if token.type in {"fence", "code_block", "blockquote_open"} and token.map:
            protected_lines.update(range(token.map[0] + 1, token.map[1] + 1))
    found = []
    chunk = []  # (行号, 行内容)：当前段落候选行
    for number, line in enumerate(text.split("\n"), start=1):
        if number in protected_lines or not line.strip():
            _flush_note_chunk(chunk, found)
            continue
        chunk.append((number, line))
    _flush_note_chunk(chunk, found)
    return found


def strip_translator_notes(chapter, records):
    """从本章导出视图删除已标识译注片段，逐处记录位置与原文片段。

    只改渲染 soup（导出视图）；chapter.text 与 projected_text 不变。
    records 追加 {"input", "line", "fragment"}。

    按叶子块元素聚合子孙文本节点后匹配：译注内嵌行内 code/强调等
    标记时会被拆成多个文本节点，逐节点匹配既漏剥（残留在 PDF）又
    漏记；聚合匹配保证整段移除。匹配起点落在行内代码区间的同形
    文字保留（与核验侧口径一致）。行号按源序与
    translator_note_occurrences 的逐次出现一一配对（渲染视图与
    源文同序；渲染剥去行内标记字符，故按序配对而不按片段内容
    配对，登记片段取源文原文）。队列耗尽时登记 line=None，由核验侧
    计数对账暴露。
    """
    queue = None  # translator_note_occurrences 的 [(行号, 片段)]，按源序
    for element in chapter.soup.find_all(
            ["p", "h1", "h2", "h3", "h4", "h5", "h6",
             "li", "dt", "dd", "th", "td"]):
        if element.find(["p", "ul", "ol", "table", "pre"]):
            continue  # 容器元素，等叶子节点自己出现
        if element.find_parent(TRANSLATOR_NOTE_SKIP_ANCESTORS):
            continue
        nodes = []  # (文本节点, 起点, 终点, 是否保护区)
        offset = 0
        for node in element.find_all(string=True):
            if isinstance(node, Comment):
                continue
            text = str(node)
            if not text:
                continue
            nodes.append(
                (node, offset, offset + len(text),
                 node.find_parent(TRANSLATOR_NOTE_SKIP_ANCESTORS)
                 is not None))
            offset += len(text)
        joined = "".join(str(node) for node, _s, _e, _p in nodes)
        if not TRANSLATOR_NOTE_RE.search(joined):
            continue
        if queue is None:
            queue = list(translator_note_occurrences(chapter.text))
        edits = []  # (节点, 局部起点, 局部终点)
        for match in TRANSLATOR_NOTE_RE.finditer(joined):
            begin = match.start()
            if any(protected and s <= begin < e
                   for _n, s, e, protected in nodes):
                continue  # 行内代码中的同形文字保留
            if queue:
                line, fragment = queue.pop(0)
            else:
                line, fragment = None, match.group(0)
            records.append(
                {
                    "input": str(chapter.path),
                    "line": line,
                    "fragment": fragment,
                }
            )
            for node, s, e, _protected in nodes:
                if s < match.end() and match.start() < e:
                    edits.append((node, max(match.start(), s) - s,
                                  min(match.end(), e) - s))
        # 同一文本节点可能有多处编辑：按节点合并后自后往前一次替换，
        # 避免第一次 replace_with 使节点脱离文档树。
        by_node = {}
        for node, local_start, local_end in edits:
            by_node.setdefault(id(node), [node, []])[1].append(
                (local_start, local_end))
        for node, spans in by_node.values():
            text = str(node)
            for local_start, local_end in sorted(spans, reverse=True):
                text = text[:local_start] + text[local_end:]
            node.replace_with(text)


# ---------------------------------------------------------------------------
# 中文文档总标题（R3/A4/C5，设计 5.2）：题名决定与导出视图投影
# ---------------------------------------------------------------------------

# 中英双语 H1 形态：外文部分 + 括号内中文题名（全角或半角括号）。
_BILINGUAL_TITLE_RE = re.compile(
    r"^(?P<outer>.*[A-Za-z].*)[（(](?P<zh>[^（）()]*[一-鿿][^（）()]*)[)）]$")
_CJK_CHAR_RE = re.compile(r"[一-鿿]")


def decide_document_title(chapters, view_declaration):
    """决定 PDF 中文文档总标题（R3/A4/C5），返回决定字典。

    单篇（一个正文章，含带 00_目录.md 的单篇）：视图声明
    document_title.chinese > 首章 H1（纯中文原样采用 / 中英双语取括号内
    中文）> 仅外文题名或缺少 H1 拒绝生成（ExportError，不回退为外文原题）。
    多章合订（两个及以上正文章）：书名只能由 Agent 依据有序输入范围与
    章题拟定并经视图声明记录依据——无声明一律拒绝生成，绝不把目录或
    第一章标题冒充全书标题。
    """
    declared = (view_declaration or {}).get("document_title") or None
    if declared is not None and str(declared.get("chinese") or "").strip():
        return {
            "title": str(declared["chinese"]).strip(),
            "original": str(declared.get("original") or ""),
            "basis": str(declared.get("basis") or ""),
            "source": "declaration",
        }
    content = [c for c in chapters if not c.is_toc]
    if len(content) > 1:
        raise ExportError(
            "合订缺书名：多章合订无法从输入确定中文书名，请通过 "
            "--view-declaration 的 document_title 提供有依据的中文题名"
            "（original/chinese/basis）；不能把目录或第一章标题冒充全书标题")
    if not content:
        raise ExportError(
            "导出缺少正文章节，无法确定中文文档总标题；请在 "
            "--view-declaration 的 document_title 中提供有依据的中文题名")
    chapter = content[0]
    # 首章第一个 H1 即文章总标题（重审结论，机制二）：题名决定、投影
    # 与声明 original 核对共用同一 H1 选择，无 H1 定位失败并指向声明。
    heading = next(
        (item for item in chapter.headings if item["level"] == 1), None)
    if heading is None:
        raise ExportError(
            "首章缺少 H1 标题，无法确定中文文档总标题：%s；请在 "
            "--view-declaration 的 document_title 中提供有依据的中文题名"
            % chapter.path)
    # 单篇投影后该 H1 已是可见题名；original_text 保留输入原题，供核
    # 验侧独立重建同一决定（投影幂等，不影响首次决定）。
    text = (heading.get("original_text") or heading["text"]).strip()
    match = _BILINGUAL_TITLE_RE.match(text)
    if match:
        return {
            "title": match.group("zh").strip(),
            "original": text,
            "basis": "首章 H1 括号内中文题名：%s" % text,
            "source": "bilingual-h1",
        }
    if _CJK_CHAR_RE.search(text):
        return {
            "title": text,
            "original": text,
            "basis": "首章 H1 为中文题名",
            "source": "plain-chinese",
        }
    raise ExportError(
        "仅外文题名且无视图声明，无法确定中文文档总标题：%r；请通过 "
        "--view-declaration 的 document_title 提供有依据的中文译名"
        % text)


def project_document_title(chapters, decision):
    """把中文总标题投影进导出视图（只改渲染 soup 与标题记录）。

    单篇：替换首章 H1 的可见文字（保留层级、锚点 id 与链接目标）；
    标题含行内链接/公式等结构时无法保真替换，定位失败。合订：在首个
    章节容器（目录章或首章）最前加入非章节性的 document-title 段落，
    不新建封面页、不改各章标题。
    """
    content = [c for c in chapters if not c.is_toc]
    if len(content) == 1:
        chapter = content[0]
        heading = next(
            (item for item in chapter.headings if item["level"] == 1), None)
        if heading is None:
            raise ExportError(
                "首章缺少 H1 标题，总标题投影失败：%s" % chapter.path)
        tag = chapter.soup.find(id=heading["id"])
        if tag is None:
            raise ExportError(
                "总标题投影失败：首章标题节点缺失（%s）" % heading["text"][:40])
        if tag.find("a", href=True) is not None \
                or tag.find(attrs={"data-tex": True}) is not None:
            raise ExportError(
                "首章 H1 含行内链接或公式，无法保真替换为中文总标题：%r"
                % heading["text"][:40])
        tag.clear()
        tag.append(NavigableString(decision["title"]))
        heading["original_text"] = heading["text"]  # 供独立重建同一决定
        heading["text"] = decision["title"]
        heading["segments"] = [decision["title"]]
        return
    target = chapters[0]
    paragraph = target.soup.new_tag("p", attrs={"class": "document-title"})
    paragraph.append(NavigableString(decision["title"]))
    target.soup.insert(0, paragraph)


# ---------------------------------------------------------------------------
# 链接与图片处理
# ---------------------------------------------------------------------------

def resolve_links(chapter, chapters, diagnostics, unlink_targets=()):
    soup = chapter.soup
    own_prefix = chapter.prefix
    unlink_targets = {
        path.resolve() if isinstance(path, Path) else Path(path).resolve()
        for path in unlink_targets
    }

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
        if anchor.find_parent("nav", class_="print-toc") is not None:
            continue  # 印刷目录条目使用已消解的最终目标，不走片段消解
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
        # 内部目标；指向已排除术语表等目标时保留文字转为纯文本；其余为范
        # 围外文件并显式报告。
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
        if target in unlink_targets:
            # 已排除术语表等目标的链接：保留可见文字，转为纯文本节点，
            # 作为固定投影记录（不再按范围外链接要求处置）。
            chapter.unlinked_links.append(
                {
                    "href": href,
                    "text": anchor.get_text(strip=True)[:80],
                    "source_line": line,
                    "reason": "目标文档默认排除，链接转为纯文本",
                }
            )
            anchor.unwrap()
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


def enumerate_images(chapter, diagnostics):
    """只读枚举本章真实图片出现：解析路径并判型，不修改 soup、不内联。

    与内联共用同一遍历顺序（soup 中带 src 的 img）；外部引用与缺失
    资源在此即记 fail，供内联/打印前的预检门禁提前阻断。
    """
    enumeration = []
    for image in chapter.soup.find_all("img"):
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
            continue
        kind, pixel_size, frames, pixel_known = bitmap_facts(str(path))
        enumeration.append(
            {
                "img": image,
                "src": src,
                "path": str(path),
                "sha256": sha256_file(path),
                "line": line,
                "kind": kind,
                "pixel_size": pixel_size,
                "frames": frames,
                "pixel_known": pixel_known,
            }
        )
    return enumeration


# 嵌入位图的长边界限：Chromium 对超大位图的解码存在实际上限（本真实样例
# 11 张 >2600px 原图全部解码失败）。重采样只影响 data URI，交付文件的
# 字节、身份核对（枚举阶段按原文件完成）与显示宽度注入均不受影响。
EMBED_MAX_EDGE = 2600


def _resampled_embed(path, record):
    """超限位图的嵌入负载；返回 (负载字节或 None, 重采样记录或 None)。

    PNG/JPEG 单帧之外（GIF/WEBP/多帧/尺寸未知）与未超限者原样内联；
    重采样失败同样回退原字节，真实解码问题仍由浏览器检查暴露，不静默。
    """
    if not record.get("pixel_known") or record.get("kind") not in ("PNG", "JPEG"):
        return None, None
    if (record.get("frames") or 1) > 1:
        return None, None
    width, height = record["pixel_size"]
    edge = max(width, height)
    if edge <= EMBED_MAX_EDGE:
        return None, None
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
        with Image.open(path) as image:
            # EXIF 方向必须烘焙进负载像素：重采样结果不再携带方向标记，
            # 浏览器按像素自然显示；不转置会把竖图交付成横图（方向丢失）。
            oriented = ImageOps.exif_transpose(image)
            display_width, display_height = oriented.size
            scale = EMBED_MAX_EDGE / max(display_width, display_height)
            resized = oriented.resize(
                (max(1, round(display_width * scale)),
                 max(1, round(display_height * scale))),
                Image.LANCZOS)
            buffer = BytesIO()
            if record["kind"] == "JPEG":
                resized.save(buffer, format="JPEG", quality=90, optimize=True)
            else:
                resized.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), {
            "original": [width, height],
            "embedded": list(resized.size),
            # 原图的浏览器自然显示宽度（EXIF 方向已计入）：负载像素变小
            # 后由它钉住无映射图片的显示宽度；高度随固有比例自动保持
            # （style.css 的 img height:auto），明确映射的 style 宽度
            # 照旧优先于该呈现提示。
            "display_width": display_width,
        }
    except Exception:  # noqa: BLE001 回退原字节；解码失败由浏览器检查判 FAIL
        return None, None


def inline_images(chapter, diagnostics, resource_registry, enumeration):
    """把预检通过的枚举结果内联为 data URI；每个文件只编码一次。"""
    for record in enumeration:
        image = record["img"]
        path = record["path"]
        key = path
        if key not in resource_registry:
            mime = mimetypes.guess_type(path)
            mime = mime[0] if mime and mime[0] else None
            if not mime:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "unknown-image-type",
                        "message": "无法识别图片类型：%s"
                        % Path(path).name,
                        "input": str(chapter.path),
                        "line": record["line"],
                    }
                )
                image.decompose()
                continue
            payload_bytes, embed_resample = _resampled_embed(path, record)
            if payload_bytes is None:
                payload_bytes = Path(path).read_bytes()
            payload = base64.b64encode(payload_bytes).decode("ascii")
            resource_registry[key] = {
                "path": path,
                "sha256": record["sha256"],
                "bytes": Path(path).stat().st_size,
                "mime": mime,
                "data_uri": "data:%s;base64,%s" % (mime, payload),
                "embed_resample": embed_resample,
            }
        registry = resource_registry[key]
        image["src"] = registry["data_uri"]
        if registry.get("embed_resample"):
            # 重采样只准改变嵌入负载：钉住原图的自然显示宽度，无映射
            # 图片的版心内显示尺寸不随内联负载缩小。
            image["width"] = str(registry["embed_resample"]["display_width"])
        chapter.images.append(
            {k: registry[k] for k in ("path", "sha256", "bytes")}
            | {"src": record["src"], "source_line": record["line"]}
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


# 短块（≤10 逻辑行）超页预检（设计 §4.9）：连一整页版心都放不下时报告
# code-short-too-tall，不私自拆块/缩字/裁切。量测必须在打印版心宽度、
# 字体已加载的视图中进行——默认 1280px 窗口的折行与 A4 打印不一致
# （评审实测同一短块默认宽度下高 673px，打印宽度下达 1268px），
# 会漏诊超页短块。版心宽为 @page A4 210mm 减 16mm×2 横边距的 96dpi
# 换算，与 PdfStyleGeometryContractTest 的样式契约锁定一致。
PRINT_CONTENT_WIDTH_PX = round((210 - 16 * 2) / 25.4 * 96)

CODE_SHORT_TALL_SCRIPT = """
(() => {
  const pageContentPx = (297 - 18 * 2) / 25.4 * 96;
  const tooTall = [];
  // 后代选择器同时覆盖回退 <pre> 与 Pygments 的 .highlight 包装节点。
  document.querySelectorAll('.code-block.code-short pre').forEach(pre => {
    const h = pre.getBoundingClientRect().height;
    if (h > pageContentPx) {
      tooTall.push({height: Math.round(h)});
    }
  });
  return tooTall;
})()
"""


def file_uri(path):
    return Path(path).as_uri()


# 页眉/页脚模板（R4/A5，设计 5.3）：底部边距内居中显示 当前页 / 总页数
# （Chromium 模板的 pageNumber/totalPages 类取打印分页事实，含封面/目录/
# 正文全部页面，与印刷目录同一页序）。样式必须内联；字号 11.3px =
# 8.5pt，低对比灰 #666。页眉为空：Chromium 对空 header_template 会渲染
# 默认页眉（日期/标题），用零尺寸 div 显式抑制。实测（Chromium 134）：
# prefer_css_page_size 下模板正常渲染，页脚基线约 16.9pt（18mm=51.02pt
# 底边距内），版心宽度不变。
HEADER_TEMPLATE = '<div style="font-size:0;line-height:0;">&nbsp;</div>'
FOOTER_TEMPLATE = (
    '<div style="width:100%;font-size:11.3px;color:#666;'
    'text-align:center;margin:0;padding:0;">'
    '<span class="pageNumber"></span> / '
    '<span class="totalPages"></span></div>'
)


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
<style>
%s
</style>
<link rel="stylesheet" href="%s">
<link rel="stylesheet" href="%s">
</head>
<body>
%s
<script src="%s"></script>
<script>%s</script>
</body>
</html>
""" % (
        escape(title),
        pygments_css,
        file_uri(katex_dir / "katex.min.css"),
        file_uri(ASSETS_DIR / "style.css"),
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
    raw_text = chapter.projected_text
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


def candidate_code_check(input_paths, unlink_targets, toc_sections,
                         candidate_path, view_declaration_path=None):
    """对候选 PDF 运行与核验器同一实现的代码检查（设计 §4.9）。

    候选完成目录页码收敛后、复制到最终目标前调用：独立重读候选内容
    流与原 Markdown（不信任导出器统计），覆盖块对账、短块整块与长块
    页尾续排检查。返回失败列表（空 = 通过）；任何失败阻止候选替换
    成品，旧 PDF 保持原样。惰性导入避免模块级循环（本模块常作为
    verify_pdf 的依赖被先行加载）。
    """
    import verify_pdf as verifier

    failures = []
    chapters = verifier.reparse_inputs(
        list(input_paths), failures, list(unlink_targets), toc_sections,
        view_declaration_path)
    pdf = verifier.PdfFacts(candidate_path)
    heading_pages = {}
    verifier.check_headings(chapters, pdf, failures, heading_pages)
    bounds = verifier.chapter_bounds(chapters, pdf, heading_pages, failures)
    relaxed = []
    infos = verifier.check_code_blocks_per_line(
        chapters, pdf, bounds, failures, relaxed)
    verifier.check_short_block_not_split(bounds, failures, infos)
    gate_relaxed = []
    verifier.check_code_pagination(chapters, pdf, bounds, failures, [],
                                   infos, gate_relaxed)
    return failures


def export(paths, output, work_dir, unlink_targets=(), images_display_paths=(),
           toc_sections=False, require_display_map=False,
           provenance_map_path=None, translation_record_path=None,
           view_declaration_path=None):
    work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = []
    report = {"diagnostics": diagnostics}

    # 翻译验收身份门禁（§4.7，只读）：翻译加导出必须传入验收记录；
    # 生成任何候选之前核对验收绑定与当前翻译身份并重跑当前检查。
    readiness_projection = None
    if translation_record_path:
        from verify_delivery import check_translation_readiness_cli
        ready, readiness = check_translation_readiness_cli(
            translation_record_path,
            [str(Path(p).expanduser().resolve()) for p in paths])
        if not ready:
            report["status"] = STATUS_MACHINE_FAIL
            report["error"] = "；".join(readiness.get("reasons") or [])
            (work_dir / REPORT_NAME).write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print("FAIL: 翻译验收就绪检查未通过，本次导出停止（旧成品不变）: %s"
                  % report["error"], file=sys.stderr)
            return 1
        readiness_projection = readiness.get("identity") or {}

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

    # 视图声明（受输入摘要绑定的授权排除范围）：必须在解析前加载校验，
    # 任何漂移/越界/重叠/跨技术正文在生成任何候选前失败。
    try:
        view_declaration = load_view_declaration(view_declaration_path,
                                                 chapters)
    except ExportError as exc:
        report["status"] = STATUS_MACHINE_FAIL
        report["error"] = str(exc)
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    # 目录出处决定（设计 §8.4）：声明加载校验之后、解析之前；toc-provenance
    # 声明接管对应候选，未被覆盖的候选才进入自动判断。
    try:
        decide_toc_provenance(chapters, view_declaration)
    except ExportError as exc:
        report["status"] = STATUS_MACHINE_FAIL
        report["error"] = str(exc)
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    for chapter in chapters:
        apply_view_declaration(chapter, view_declaration)
    if view_declaration is not None:
        report["view_declaration"] = {
            "path": view_declaration["path"],
            "sha256": view_declaration["sha256"],
            "document_title": view_declaration["document_title"],
            "exclusions": [
                {
                    "input": ex["input"],
                    "lines": ex["lines"],
                    "type": ex["type"],
                    "kind": ex["kind"],
                    "fragment": ex["fragment"],
                    "reason": ex["reason"],
                }
                for ex in view_declaration["exclusions"]
            ],
        }

    resource_registry = {}
    # 显示尺寸映射先于渲染读取：命中条目在图片内联后注入受限宽度。
    bindings, display_undetermined, display_undetermined_raw, \
        display_map_paths = load_display_maps(
            chapters, list(images_display_paths), diagnostics
        )
    # 先完成全部章节解析，再做链接消解：跨章文件链接与片段链接都依赖
    # 所有章节的目标映射就绪。
    for chapter in chapters:
        parse_chapter(chapter)

    # 中文文档总标题决定（R3/A4/C5）：必须在印刷目录合成与正文事实
    # 收集前投影（印刷目录条目与正文预期使用投影后的可见标题）；
    # 依据不足时定位失败，不生成候选。
    try:
        document_title = decide_document_title(chapters, view_declaration)
        project_document_title(chapters, document_title)
    except ExportError as exc:
        report["status"] = STATUS_MACHINE_FAIL
        report["error"] = str(exc)
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    report["document_title"] = {
        key: document_title[key]
        for key in ("title", "original", "basis", "source")
    }

    # 印刷目录合成：仅需各章标题映射，且必须在 collect_chapter_facts 之前，
    # 使被消费的导航列表不进入目录章的正文预期。
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    toc_entries = []
    toc_out_links = []
    if toc_chapter is not None:
        if chapters[0] is not toc_chapter:
            diagnostics.append(
                {
                    "severity": "warn",
                    "code": "toc-not-first",
                    "message": "目录文件未列在输入首位，印刷目录按当前顺序插入",
                    "input": str(toc_chapter.path),
                }
            )
        try:
            toc_entries, toc_out_links = build_print_toc(
                toc_chapter, chapters, diagnostics, toc_sections
            )
            insert_toc_nav(toc_chapter, render_toc_nav(toc_entries, None))
        except TocError as exc:
            print("FAIL: %s" % exc, file=sys.stderr)
            return 1

    # 已标识译注只从导出视图排除（原始 Markdown 与输入摘要不变）：
    # 在收集正文事实前从渲染 soup 删除正文文本节点中的 【译注：…】 片段。
    note_records = []
    for chapter in chapters:
        strip_translator_notes(chapter, note_records)
    report["translator_note_exclusions"] = note_records

    for chapter in chapters:
        collect_chapter_facts(chapter)

    # 出处门禁（R6/D6）：字段投影单源；来源不足在任何内联/打印前失败，
    # 不生成候选或成品；已知版本/日期原样保留，缺失不编造。
    try:
        provenance_map = load_provenance_map(provenance_map_path, chapters,
                                             diagnostics)
    except ExportError as exc:
        report["status"] = STATUS_MACHINE_FAIL
        report["error"] = str(exc)
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    provenance_facts = collect_provenance(chapters, toc_chapter,
                                          provenance_map)
    if provenance_facts["incomplete"]:
        chapters_text = "、".join(
            "第 %d 章" % i for i in provenance_facts["incomplete"])
        diagnostics.append(
            {
                "severity": "fail",
                "code": "provenance-incomplete",
                "message": "以下章节只有无法定位具体原文的来源（文档名/首页"
                "不算定位）：%s" % chapters_text,
            }
        )
    if provenance_facts["unavailable"]:
        chapters_text = "、".join(
            "第 %d 章" % i for i in provenance_facts["unavailable"])
        diagnostics.append(
            {
                "severity": "fail",
                "code": "provenance-unavailable" if not provenance_facts["incomplete"]
                else "provenance-incomplete",
                "message": "以下章节完全缺少出处信息：%s" % chapters_text,
            }
        )
    report["provenance"] = {
        "policy": {"fields": list(MANAGEMENT_FIELD_LABELS)},
        "mode": provenance_facts["mode"],
        "complete": provenance_facts["complete"],
        "incomplete": provenance_facts["incomplete"],
        "unavailable": provenance_facts["unavailable"],
        "combos": provenance_facts["combos"],
        "front_generated": bool(provenance_facts["front_text"]),
        "mapping": str(provenance_map_path) if provenance_map_path else None,
        # 新政策（R2/C2）：PDF 不显示前置出处；出处清单与定位证据留在报告。
        "pdf_visibility": "excluded",
        "toc_exclusion": (
            toc_chapter.toc_provenance_exclusion
            if toc_chapter is not None else None
        ),
    }

    # 资源预检（内联/解码/打印之前）：只读枚举真实图片出现，逐项核对
    # 尺寸覆盖并估算解码预算。任何 fail（含严格策略）都在此阻断，不新增
    # 候选或成品；预算与回退告警不阻断，真实错误保留原因。
    enumerations = {}
    for chapter in chapters:
        enumerations[chapter.path] = enumerate_images(chapter, diagnostics)
    occurrences = [
        Occurrence(
            chapter=str(chapter.path),
            occurrence=index + 1,
            ref=record["src"],
            path=record["path"],
            sha256=record["sha256"],
            line=record["line"],
            kind=record["kind"],
            pixel_size=record["pixel_size"],
            frames=record["frames"],
            pixel_known=record["pixel_known"],
        )
        for chapter in chapters
        for index, record in enumerate(enumerations[chapter.path])
    ]
    preflight_items = classify_occurrences(
        occurrences,
        {str(k): v for k, v in bindings.items()},
        {(str(k[0]), k[1]): v for k, v in display_undetermined.items()},
    )
    # 未确定条目身份核对：与确定条目同一出现序号/路径/摘要规则。
    for chapter in chapters:
        diagnostics.extend(undetermined_binding_diagnostics(
            str(chapter.path),
            display_undetermined_raw.get(chapter.path, []),
            enumerations[chapter.path],
        ))
    diagnostics.extend(
        coverage_diagnostics(
            preflight_items, require_display_map, "images-display-absent"))
    image_budget, budget_diagnostics = decode_budget(preflight_items)
    diagnostics.extend(budget_diagnostics)
    report["require_display_map"] = bool(require_display_map)
    report["image_coverage"] = coverage_summary(preflight_items)
    report["image_budget"] = image_budget
    preflight_failures = [d for d in diagnostics if d.get("severity") == "fail"]
    if preflight_failures:
        report["status"] = STATUS_MACHINE_FAIL
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "FAIL: 打印前预检未通过（%d 项），未生成候选或成品 PDF"
            % len(preflight_failures),
            file=sys.stderr,
        )
        for diag in preflight_failures:
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
        return 1

    # 预算与覆盖提示在内联/解码开始前输出（承诺的提前提示）：此后任何
    # 内联或浏览器失败，用户已能看见逐章覆盖与两种口径的预算估算。
    # 已生成的预算告警（超阈值主要资源、无法估算项、多帧额外开销）在同
    # 一处展示可定位明细；它们仍是纯告警，不改变退出语义，成功尾部不再
    # 重复。
    coverage = report.get("image_coverage", {})
    total_occ = sum(v["total"] for v in coverage.values())
    missing = sum(v["missing"] for v in coverage.values())
    no_constraint = sum(v["no-source-constraint"] for v in coverage.values())
    unresolved = sum(v["unresolved-size"] for v in coverage.values())
    if total_occ:
        print(
            "覆盖分类（按出现次数）：总数 %d = 已恢复 %d + 未恢复 %d"
            "（无映射条目 %d、源无尺寸约束 %d、源尺寸无法确定 %d）。"
            % (total_occ, total_occ - missing - no_constraint - unresolved,
               missing + no_constraint + unresolved,
               missing, no_constraint, unresolved)
        )
        budget = report.get("image_budget", {})
        if budget:
            print(
                "解码预算估算：按出现累加 %.1f MiB / 按摘要去重 %.1f MiB"
                "（阈值 %d MiB，仅为候选估算）；无法估算项 %d 处。"
                % (budget.get("occurrence_estimate_bytes", 0) / (1 << 20),
                   budget.get("dedup_estimate_bytes", 0) / (1 << 20),
                   budget.get("threshold_bytes", 0) // (1 << 20),
                   len(budget.get("unknown_items", [])))
            )
            for diag in budget_diagnostics:
                print("  [%s] %s" % (diag["code"], diag["message"]))

    display_records = {}
    natural_fallback = {}
    for chapter in chapters:
        resolve_links(chapter, chapters, diagnostics, unlink_targets)
        inline_images(chapter, diagnostics, resource_registry,
                      enumerations[chapter.path])
        applied = apply_display_widths(chapter, bindings, diagnostics)
        display_records[str(chapter.path)] = applied
        valid_occurrences = {r["occurrence"] for r in applied}
        natural_fallback[str(chapter.path)] = max(
            0, len(chapter.images) - len(valid_occurrences)
        )
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

    report["embed_resampled"] = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "original": entry["embed_resample"]["original"],
            "embedded": entry["embed_resample"]["embedded"],
        }
        for entry in resource_registry.values()
        if entry.get("embed_resample")
    ]

    # PDF 元数据 <title> 与可见中文总标题取同一题名决定（Chromium 据此写
    # /Title）；不再简单取首个输入标题。
    title = document_title["title"]
    html_path = work_dir / HTML_NAME
    candidate = work_dir / CANDIDATE_NAME

    # 惰性导入：普通翻译环境不安装 playwright 时，导入本模块的其他脚本不受影响。
    from playwright.sync_api import sync_playwright

    def render_print():
        """渲染组合 HTML 并打印到候选 PDF，返回浏览器层检查结果。"""
        html_path.write_text(build_document(chapters, title), encoding="utf-8")
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
            checks = page.evaluate("window.__pdfExportChecks")
            # 短块超页预检切到打印版心宽度量测（见 PRINT_CONTENT_WIDTH_PX）。
            page.emulate_media(media="print")
            page.set_viewport_size(
                {"width": PRINT_CONTENT_WIDTH_PX, "height": 1123})
            checks["codeShortTooTall"] = page.evaluate(CODE_SHORT_TALL_SCRIPT)
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
                # 每页页脚页码（R4/A5）：底部边距内居中 当前页 / 总页数；
                # 模板只接受内联样式，页眉为零尺寸 div（Chromium 对空
                # header_template 会回落默认页眉，须显式抑制）。页脚渲染
                # 在 @page 边距区内，不占用正文版心。
                display_header_footer=True,
                header_template=HEADER_TEMPLATE,
                footer_template=FOOTER_TEMPLATE,
            )
            browser.close()
        return checks

    # 印刷目录两遍打印：占位页码探测 → 实际目的地回填 → 必要时一次修正。
    toc_pages = None
    toc_prints = 0
    while True:
        browser_checks = render_print()
        toc_prints += 1
        if toc_chapter is None:
            break
        try:
            actual_pages = extract_toc_pages(candidate, toc_entries)
        except TocError as exc:
            print("FAIL: %s" % exc, file=sys.stderr)
            return 1
        if toc_pages is not None and all(
            actual_pages[entry["target"]] == toc_pages[entry["target"]] - 1
            for entry in toc_entries
        ):
            break  # 页码收敛：印刷页码与实际目的地一致
        if toc_prints >= MAX_TOC_PRINTS:
            print(
                "FAIL: 印刷目录页码经 %d 次打印仍未收敛" % toc_prints,
                file=sys.stderr,
            )
            return 1
        toc_pages = {
            entry["target"]: actual_pages[entry["target"]] + 1
            for entry in toc_entries
        }
        update_toc_nav(toc_chapter, toc_entries, toc_pages)

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
    # 候选代码门禁（设计 §4.9 分页验收与失败保护）：候选完成目录页码
    # 收敛后调用与核验器同一实现的代码检查，不通过则不复制到最终目标，
    # 已有成品保持原样。
    code_gate_failures = candidate_code_check(
        [str(c.path) for c in chapters], unlink_targets, toc_sections,
        candidate, view_declaration_path)
    hard_failures.extend(code_gate_failures)
    fonts = browser_checks.get("fonts", {}) if browser_checks else {}
    # 正文与代码的 CJK 回退族必须至少一项可用，否则中文会退到不可控字体。
    cjk_font_ok = any(fonts.get(f, False) for f in ("STFangsong", "STHeiti"))
    machine_ok = (
        not hard_failures
        and browser_checks
        and not browser_checks.get("katex")
        and not browser_checks.get("images")
        and not browser_checks.get("overflow")
        and not browser_checks.get("codeShortTooTall")
        and browser_checks.get("scrollWidth", 0) <= browser_checks.get("clientWidth", 0) + 1
        and cjk_font_ok
    )

    report.update(
        {
            "status": STATUS_MACHINE_PASS if machine_ok else STATUS_MACHINE_FAIL,
            "candidate": str(candidate),
            "pdf_sha256": sha256_file(candidate),
            "output_target": str(output),
            "code_gate_failures": code_gate_failures,
            "unlink_targets": sorted(
                str(Path(p).expanduser().resolve()) for p in unlink_targets
            ),
            "images_display_maps": display_map_paths,
            "image_display": {
                path: records for path, records in display_records.items()
            },
            "images_natural_fallback": natural_fallback,
            "toc": {
                "enabled": toc_chapter is not None,
                "file": str(toc_chapter.path) if toc_chapter else None,
                "sections": bool(toc_sections),
                "prints": toc_prints,
                "entries": [
                    dict(entry, page=(toc_pages or {}).get(entry["target"]))
                    for entry in toc_entries
                ],
                "out_links": toc_out_links,
            },
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
                    "unlinked_links": c.unlinked_links,
                    "management_exclusions": c.exclusions,
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
    if translation_record_path:
        # 导出证据记录本次只读就绪身份投影（运行事实；验收记录路径关联）
        report["translation_readiness"] = {
            "record": str(translation_record_path),
            "ready": True,
            "identity": readiness_projection,
            "reconfirmed_before_replace": False,
        }
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
        for tall in (browser_checks or {}).get("codeShortTooTall", []):
            print(
                "  [code-short-too-tall] 短代码块（10 行以内）高度 %spx 超过一整页版心，"
                "无法满足不分页约束" % tall.get("height"),
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
    # 替换目标前以同一口径再确认翻译验收身份：运行中变化不覆盖旧 PDF。
    protected = {Path(item["path"]).resolve() for item in inputs}
    protected |= {Path(r["path"]).resolve() for r in resources}
    if output.resolve() in protected:
        print(
            "FAIL: 输出路径不得指向输入文件或原始资源：%s" % output, file=sys.stderr
        )
        return 1
    if translation_record_path:
        from verify_delivery import check_translation_readiness_cli
        ready, readiness = check_translation_readiness_cli(
            translation_record_path,
            [str(Path(p).expanduser().resolve()) for p in paths])
        if not ready:
            print("FAIL: 导出期间输入或验收身份变化，按同一口径复确认失败，"
                  "不替换旧成品: %s" % "；".join(readiness.get("reasons") or []),
                  file=sys.stderr)
            return 1
        readiness_projection = readiness.get("identity") or {}
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, output)
    if translation_record_path:
        report["translation_readiness"]["reconfirmed_before_replace"] = True
        (work_dir / REPORT_NAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        "机器检查通过：%s（候选与证据见 %s）\n成品待视觉复核后才能发布。"
        % (output, work_dir)
    )
    unlinked = [
        (str(c.path), link)
        for c in chapters
        for link in c.unlinked_links
    ]
    if unlinked:
        print("已按默认排除目标转为纯文本的链接（记录入交付说明）：")
        for path, link in unlinked:
            print("  %s:%s %s -> %s" % (
                path, link.get("source_line", "?"), link["text"], link["href"]))
    restored = sum(len(r) for r in display_records.values())
    natural = sum(natural_fallback.values())
    if restored or natural:
        print(
            "图片显示尺寸：恢复 %d 处；%d 处无映射命中，按自然尺寸与版心上限导出。"
            % (restored, natural)
        )
    if toc_chapter is not None:
        print(
            "印刷目录：%d 条（含一级节：%s），共打印 %d 次，页码为 PDF 实际页序。"
            % (len(toc_entries), "是" if toc_sections else "否", toc_prints)
        )
        for link in toc_out_links:
            print(
                "  待处置 [toc-out-link] %s（%s）"
                % (link["href"], "文件存在" if link["exists"] else "文件不存在")
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
    parser.add_argument(
        "--unlink-target",
        action="append",
        default=[],
        metavar="PATH",
        help="默认排除的目标文档（如 术语表.md）：指向它的链接保留文字转为纯文本",
    )
    parser.add_argument(
        "--images-display",
        action="append",
        default=[],
        metavar="PATH",
        help="显示尺寸映射 images_display.json；缺省时读取各输入同目录映射",
    )
    parser.add_argument(
        "--toc-sections",
        action="store_true",
        help="印刷目录在章级条目外加入一级节（默认仅章级）",
    )
    parser.add_argument(
        "--require-display-map",
        action="store_true",
        help="严格尺寸保真：每次真实图片出现都必须有确定有效的源尺寸，"
             "缺失、部分覆盖与未确定均拒绝导出（无图输入豁免）",
    )
    parser.add_argument(
        "--provenance",
        default=None,
        metavar="PATH",
        help="只读出处区间映射 JSON：声明目录段落行区间与覆盖章，"
             "用于非标准出处段落；不以映射掩盖来源缺失",
    )
    parser.add_argument(
        "--view-declaration",
        default=None,
        metavar="PATH",
        help="PDF 视图声明 JSON（version 1）：绑定有序输入摘要与授权排除"
             "区间（block/inline），用于无法从语法定位的非原文说明；"
             "摘要漂移、越界、重叠或跨技术正文即在生成候选前失败",
    )
    parser.add_argument(
        "--translation-record",
        default=None,
        metavar="PATH",
        help="翻译验收交付记录（translation/translation+pdf 模式）：翻译"
             "加导出必须传入；导出前与替换目标前只读核对验收身份与当前"
             "翻译身份（含检查复跑），漂移或证据不足即停止且旧成品不变；"
             "仅导出既有 Markdown 时不传，行为不变",
    )
    parser.add_argument("inputs", nargs="+", help="有序 Markdown 输入")
    args = parser.parse_args(argv)
    try:
        return export(
            args.inputs,
            Path(args.output).expanduser(),
            Path(args.work_dir).expanduser(),
            unlink_targets=args.unlink_target,
            images_display_paths=args.images_display,
            toc_sections=args.toc_sections,
            require_display_map=args.require_display_map,
            provenance_map_path=args.provenance,
            translation_record_path=args.translation_record,
            view_declaration_path=args.view_declaration,
        )
    except ExportError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
