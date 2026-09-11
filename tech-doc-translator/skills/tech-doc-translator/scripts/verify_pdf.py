#!/usr/bin/env python3
"""tech-doc-translator PDF 独立核验入口。

    python3 verify_pdf.py --pdf <候选.pdf> --work-dir <同一临时目录> <章节1.md> [...]

以原始输入重建预期，与导出证据及最终 PDF 相互核对：输入摘要保护、逐章
标题顺序、文本/代码覆盖、公式机器检查、内外链接目标与大纲。核验器独立
重读输入，不信任导出器统计；原始扫描与解析结果相互交叉核对。机器检查
通过只表示机器层通过，成品仍需 Agent 视觉复核后才能发布。
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import pypdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_pdf as exporter  # noqa: E402  复用同一解析层，另有独立原始扫描交叉核对

# 与导出证据共用同一命名与状态口径（单一事实源）。
REPORT_NAME = exporter.REPORT_NAME
VERIFY_NAME = "verify_report.json"
STATUS_MACHINE_PASS = exporter.STATUS_MACHINE_PASS
STATUS_MACHINE_FAIL = exporter.STATUS_MACHINE_FAIL


def normalize(text):
    """PDF 文本提取允许排版空白差异：比较时去掉全部空白字符与变体选择符，
    并做 NFKC 归一（防御个别字体把汉字映射到兼容码位）。"""
    cleaned = re.sub(r"[\s\uFE0E\uFE0F]+", "", text or "")
    return unicodedata.normalize("NFKC", cleaned)


# ---------------------------------------------------------------------------
# 独立原始扫描：不经过 Markdown 解析器，直接在原文上统计
# ---------------------------------------------------------------------------

FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")
ATX_HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
ASCII_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def code_span_intervals(chunk_lines):
    """返回段内行内代码的字符区间列表（独立实现，与解析层交叉核对）。

    配对规则与 CommonMark/markdown-it 一致：未被转义的反引号串开启代码
    串，按原文搜索下一个等长串闭合——搜索不跳过被转义的反引号；找不到
    等长闭合串的反引号是字面文本，不保持打开。调用方据此判断标题前缀
    所在位置是否落在代码内，而不是整行是否与代码相交。
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
            and text[position + 1] in ASCII_PUNCTUATION
        ):
            # 转义对中的反引号不能开启代码串（但仍可能被闭合搜索命中）。
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


def raw_scan(text):
    """围栏感知的原始扫描，返回关键结构计数（用于交叉核对解析层）。"""
    counts = {
        "headings": [],
        "fences": 0,
        "fence_bodies": [],
        "legacy_inline_math": 0,
        "legacy_display_math": 0,
        "std_block_math": 0,
        "images": [],
        "fragment_links": [],
        "external_links": [],
        "footnote_labels": [],
    }
    in_fence = False
    fence_char = None
    fence_len = 0
    in_dollar_block = False
    chunk = []  # (行号, 行内容)：当前段落候选行
    prefix_in_code = set()  # 行首位置落在行内代码区间内的行号
    deep_candidates = []  # (行号, 级别, 文本)：段落闭合后统一判定
    lines = text.splitlines()

    def flush_chunk():
        nonlocal chunk
        if chunk:
            intervals = code_span_intervals([line for _, line in chunk])
            starts = []
            offset = 0
            for _number, line in chunk:
                starts.append(offset)
                offset += len(line) + 1
            for index, (number, _line) in enumerate(chunk):
                if any(s <= starts[index] < e for s, e in intervals):
                    prefix_in_code.add(number)
            chunk = []

    for line_number, line in enumerate(lines):
        stripped = line.lstrip()
        if in_fence:
            # 闭合围栏须与开启围栏同字符且不短于其长度（CommonMark），
            # 因此四反引号围栏内的三反引号行不会提前闭合。
            if re.match(
                r"^%s{%d,}\s*$" % (re.escape(fence_char), fence_len), stripped
            ):
                in_fence = False
                fence_char = None
                fence_len = 0
            continue
        fence_match = FENCE_OPEN_RE.match(stripped)
        if fence_match:
            in_fence = True
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            counts["fences"] += 1
            flush_chunk()
            continue
        if in_dollar_block:
            # 多行 $$ 块的内容行不属于任何其他结构。
            if "$$" in stripped:
                in_dollar_block = False
                counts["std_block_math"] += 1
            continue
        heading = re.match(r"^(#{1,})\s+(.*)$", stripped)
        indent = len(line) - len(stripped)
        if not stripped:
            flush_chunk()
        elif heading and len(heading.group(1)) <= 6:
            flush_chunk()
            counts["headings"].append(
                (len(heading.group(1)), heading.group(2).strip())
            )
        elif ATX_HEADING_RE.match(stripped):
            # 独立 # 行同样是真实 ATX 标题：结束当前段落。
            flush_chunk()
        elif heading and indent == 0:
            # 深层标题候选（与解析层同为列 0 口径）：是否计入标题数取决于
            # 所在段落的行内代码覆盖，段落结束时统一判定。
            deep_candidates.append(
                (line_number, len(heading.group(1)), heading.group(2).strip())
            )
            chunk.append((line_number, line))
        elif indent < 4 or chunk:
            chunk.append((line_number, line))
        # 量级上限只为防御病态长行的回溯爆炸；真实公式不会接近这些长度。
        counts["legacy_inline_math"] += len(
            re.findall(r"\$\\\(.{1,800}?\\\)\$", line)
        )
        counts["legacy_display_math"] += len(
            re.findall(r"\$\\\[.{1,4000}?\\\]\$", line)
        )
        counts["std_block_math"] += len(re.findall(r"\$\$.+?\$\$", stripped))
        # 同行未闭合的 $$ 开启多行块（$$、内容行、$$ 的标准三行形式）。
        if stripped.startswith("$$") and stripped.count("$$") % 2 == 1:
            flush_chunk()
            in_dollar_block = True
        counts["images"] += re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", line)
        counts["fragment_links"] += re.findall(r"\]\(#([^)\s]+)\)", line)
        counts["external_links"] += re.findall(
            r"\]\((https?://[^)\s]+)\)", line
        )
        counts["footnote_labels"] += re.findall(r"\[\^([^\]\s]+)\]", line)
    flush_chunk()
    for line_number, level, heading_text in deep_candidates:
        if line_number not in prefix_in_code:
            counts["headings"].append((level, heading_text))
    return counts


# ---------------------------------------------------------------------------
# PDF 读取
# ---------------------------------------------------------------------------

class PdfFacts:
    def __init__(self, path):
        self.reader = pypdf.PdfReader(str(path))
        self.pages = [p.extract_text() or "" for p in self.reader.pages]
        self.norm_text = "".join(normalize(p) for p in self.pages)
        offsets = []
        position = 0
        for index, text in enumerate(self.pages):
            length = len(normalize(text))
            offsets.append((position, position + length))
            position += length
        self.page_offsets = offsets
        self.page_id_to_index = {
            page.indirect_reference.idnum: index
            for index, page in enumerate(self.reader.pages)
        }
        self.uri_links = set()
        self.internal_annots = []  # {page, dest_page}
        self.broken_named_dests = []
        self.collect_annotations()
        self.outline = []
        self.collect_outline()

    def page_of_offset(self, offset):
        for index, (start, end) in enumerate(self.page_offsets):
            if start <= offset < end:
                return index
        return len(self.page_offsets) - 1

    def find(self, needle, start=0):
        return self.norm_text.find(needle, start)

    def collect_annotations(self):
        named = {}
        for name, dest in self.reader.named_destinations.items():
            try:
                named[str(name).lstrip("/")] = self.reader.get_destination_page_number(
                    dest
                )
            except Exception:  # noqa: BLE001  个别目标无法解析时跳过
                continue
        self.named_dest_pages = named
        for page_index, page in enumerate(self.reader.pages):
            annotations = page.get("/Annots") or []
            for ref in annotations:
                obj = ref.get_object()
                if obj.get("/Subtype") != "/Link":
                    continue
                action = obj.get("/A")
                if action is not None:
                    action = action.get_object()
                    if action.get("/S") == "/URI":
                        self.uri_links.add(str(action.get("/URI")))
                        continue
                dest = obj.get("/Dest")
                if dest is None and action is not None:
                    action_obj = action.get_object()
                    if action_obj.get("/S") == "/GoTo":
                        dest = action_obj.get("/D")
                if dest is None:
                    continue
                dest = dest.get_object() if hasattr(dest, "get_object") else dest
                name_key = None
                if isinstance(dest, str):
                    name_key = dest.lstrip("/")
                elif isinstance(dest, bytes):
                    name_key = dest.decode("utf-8", "replace").lstrip("/")
                if name_key is not None:
                    if name_key in named:
                        self.internal_annots.append(
                            {"page": page_index, "dest_page": named[name_key]}
                        )
                    else:
                        self.broken_named_dests.append(str(name_key))
                    continue
                if isinstance(dest, (list, tuple)) or hasattr(dest, "__getitem__"):
                    try:
                        target_ref = dest[0]
                        index = self.page_id_to_index.get(
                            getattr(target_ref, "idnum", None)
                        )
                        if index is not None:
                            self.internal_annots.append(
                                {"page": page_index, "dest_page": index}
                            )
                    except (KeyError, TypeError, IndexError):
                        continue

    def collect_outline(self):
        def walk(items):
            for item in items:
                if isinstance(item, list):
                    walk(item)
                    continue
                try:
                    page_number = self.reader.get_destination_page_number(item)
                except Exception:
                    page_number = None
                self.outline.append({"title": item.title or "", "page": page_number})

        try:
            walk(self.reader.outline)
        except Exception:
            self.outline = []


# ---------------------------------------------------------------------------
# 核验主流程
# ---------------------------------------------------------------------------

def reparse_inputs(paths, failures):
    """用同一解析层重读输入，重建预期（与原始扫描交叉核对）。"""
    chapters = exporter.load_inputs(paths)
    for chapter in chapters:
        exporter.parse_chapter(chapter)
        exporter.collect_chapter_facts(chapter)
    resolve_diagnostics = []
    for chapter in chapters:
        exporter.resolve_links(chapter, chapters, resolve_diagnostics)
    for diagnostic in resolve_diagnostics:
        if diagnostic.get("severity") == "fail":
            failures.append(
                {
                    "code": diagnostic["code"],
                    "message": diagnostic["message"],
                    "input": diagnostic.get("input"),
                }
            )
    return chapters


def cross_check(chapters, failures):
    """原始扫描与解析层计数必须一致，防止共享解析缺陷同时骗过双方。"""
    for chapter in chapters:
        scan = raw_scan(chapter.text)
        context = {"input": str(chapter.path)}
        if len(scan["headings"]) != len(chapter.headings):
            failures.append(
                {
                    "code": "parse-divergence-headings",
                    "message": "原始扫描标题数 %d 与解析层数 %d 不一致"
                    % (len(scan["headings"]), len(chapter.headings)),
                    **context,
                }
            )
        legacy_total = scan["legacy_inline_math"] + scan["legacy_display_math"]
        legacy_parsed = sum(
            1
            for m in chapter.math
            if m["original_form"] in ("legacy_paren", "legacy_bracket")
        )
        std_block = sum(1 for m in chapter.math if m["original_form"] == "dollar_block")
        if legacy_total != legacy_parsed or scan["std_block_math"] != std_block:
            failures.append(
                {
                    "code": "parse-divergence-math",
                    "message": "原始扫描公式数（legacy %d / block %d）与解析层"
                    "（legacy %d / block %d）不一致"
                    % (
                        legacy_total,
                        scan["std_block_math"],
                        legacy_parsed,
                        std_block,
                    ),
                    **context,
                }
            )
        if len(scan["images"]) != len(chapter.image_srcs):
            failures.append(
                {
                    "code": "parse-divergence-images",
                    "message": "原始扫描图片数 %d 与解析层数 %d 不一致"
                    % (len(scan["images"]), len(chapter.image_srcs)),
                    **context,
                }
            )
        scan_labels = sorted(set(scan["footnote_labels"]))
        if scan_labels != sorted(set(chapter.footnote_labels)):
            failures.append(
                {
                    "code": "parse-divergence-footnotes",
                    "message": "脚注标签集合与原始扫描不一致",
                    **context,
                }
            )


def check_inputs_protection(report, failures):
    for item in report.get("inputs", []):
        path = Path(item["path"])
        if not path.is_file():
            failures.append(
                {"code": "input-missing", "message": "输入文件消失：%s" % path}
            )
            continue
        current = exporter.sha256_file(path)
        if current != item["sha256"]:
            failures.append(
                {
                    "code": "input-modified",
                    "message": "输入摘要与导出时不一致：%s" % path,
                }
            )
    for resource in report.get("resources", []):
        path = Path(resource["path"])
        if not path.is_file() or exporter.sha256_file(path) != resource["sha256"]:
            failures.append(
                {
                    "code": "resource-modified",
                    "message": "资源摘要与导出时不一致：%s" % resource["path"],
                }
            )


def heading_matches(heading, title):
    # 只在源标题的公式位置允许插入渲染字形；其他文字必须完整连续保留。
    segments = heading.get("segments", [heading["text"]])
    pattern = ".*".join(re.escape(normalize(segment)) for segment in segments)
    return re.fullmatch(pattern, normalize(title)) is not None


def check_headings(chapters, pdf, failures, heading_pages):
    """标题定位优先使用 PDF 大纲（目录行的链接文字与标题文字相同，
    纯文本顺序搜索会先命中目录行）；大纲缺失时回退文本搜索。"""
    def outline_page_of(heading, start_index):
        for index in range(start_index, len(pdf.outline)):
            if heading_matches(heading, pdf.outline[index]["title"]):
                return index, pdf.outline[index]["page"]
        return start_index, None

    outline_cursor = 0
    text_position = 0
    for chapter in chapters:
        for heading in chapter.headings:
            needle = normalize(heading["text"])
            cursor, page = outline_page_of(heading, outline_cursor)
            if page is not None:
                outline_cursor = cursor + 1
                heading_pages[heading["id"]] = page
                continue
            found = pdf.find(needle, text_position)
            if found < 0:
                found = pdf.find(needle)
            if found < 0:
                failures.append(
                    {
                        "code": "heading-missing",
                        "message": "标题未在 PDF 文本中按序出现：%s" % heading["text"],
                        "input": str(chapter.path),
                    }
                )
                continue
            text_position = found + 1
            heading_pages[heading["id"]] = pdf.page_of_offset(found)


def chapter_bounds(chapters, pdf, heading_pages, failures):
    """读取 Chromium tagged PDF 中与 HTML 章容器对应的结构节点。

    每章强制新页；章区间必须非空、有序且互不重叠。不用正文或大纲猜测
    边界，结构缺失或不符合导出格式时明确失败，禁止借用相邻章内容。
    """
    def children(node):
        value = node.get("/K", [])
        value = value.get_object() if hasattr(value, "get_object") else value
        return value if isinstance(value, list) else [value]

    def pages_of(value, seen):
        value = value.get_object() if hasattr(value, "get_object") else value
        if not isinstance(value, dict):
            return set()
        identity = id(value)
        if identity in seen:
            raise ValueError("章节结构存在循环或重复节点")
        seen.add(identity)
        pages = set()
        ref = value.get("/Pg")
        if ref is not None:
            page = pdf.page_id_to_index.get(getattr(ref, "idnum", None))
            if page is None:
                raise ValueError("章节结构引用了不存在的页面")
            pages.add(page)
        for child in children(value):
            pages.update(pages_of(child, seen))
        return pages

    try:
        root = pdf.reader.trailer["/Root"]["/StructTreeRoot"]
        documents = children(root)
        if len(documents) != 1:
            raise ValueError("预期唯一的 Document 结构")
        document = documents[0].get_object()
        if document.get("/S") != "/Document":
            raise ValueError("缺少 Document 结构")
        sections = children(document)
        if len(sections) != len(chapters):
            raise ValueError("PDF 章容器数与输入章节数不一致")
        bounds = []
        previous_end = 0
        for chapter, section in zip(chapters, sections):
            pages = pages_of(section, set())
            if not pages:
                raise ValueError("章容器没有页面内容：" + chapter.path.name)
            start, end = min(pages), max(pages) + 1
            if start != previous_end or pages != set(range(start, end)):
                raise ValueError("章节页面重叠、乱序或存在缺页：" + chapter.path.name)
            bounds.append((chapter, start, end))
            previous_end = end
        if previous_end != len(pdf.pages):
            raise ValueError("存在不属于任何章节的页面")
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as exc:
        failures.append({"code": "chapter-structure", "message": str(exc)})
        return []
    for chapter, start, end in bounds:
        heading_pages[chapter.prefix + "body"] = start
        for heading in chapter.headings:
            page = heading_pages.get(heading["id"])
            if page is not None and not start <= page < end:
                failures.append({"code": "heading-chapter", "input": str(chapter.path),
                                 "message": "标题目标页不在所属章节内：" + heading["text"]})
    return bounds


def subsequence_in_window(needle, haystack, start, end):
    """有界窗口内的有序子序列匹配：字符全齐且顺序一致才算已解释差异。

    返回消费结束位置（供调用方推进单调游标，防止重复内容漏报），无匹配
    返回 None。窗口预算 = 4 倍段长 + 60，覆盖 KaTeX MathML 文本穿插。
    """
    budget = len(needle) * 4 + 60
    j = 0
    for i in range(start, min(end, start + len(needle) + budget)):
        if haystack[i] == needle[j]:
            j += 1
            if j == len(needle):
                return i + 1
    return None


def check_blocks(chapters, pdf, bounds, failures, relaxed, kind):
    """kind: text 或 code；在章区间内做严格单调的顺序包含检查。

    匹配位置只前进不回退：后一块不能复用前一块已消费的文本，因此源文中
    重复的块在 PDF 中缺一份时必然 FAIL。文本块按公式边界分段（KaTeX 的
    MathML 文本会插入句子中间），连续匹配失败时用"自当前位置起的有界窗口
    有序子序列"作已解释差异（字符全齐且顺序一致），不再回退章首。
    """
    for chapter, start_page, end_page in bounds:
        start_offset = pdf.page_offsets[start_page][0]
        end_offset = pdf.page_offsets[end_page - 1][1]
        position = start_offset
        if kind == "text":
            for block in chapter.blocks:
                for segment in block["segments"]:
                    needle = normalize(segment)
                    if not needle:
                        continue
                    found = pdf.find(needle, position)
                    if found >= 0 and found + len(needle) <= end_offset:
                        position = found + len(needle)
                        continue
                    consumed = None
                    if position < end_offset:
                        consumed = subsequence_in_window(
                            needle, pdf.norm_text, position, end_offset
                        )
                    if consumed is not None:
                        relaxed.append(
                            {
                                "segment": segment.strip()[:80],
                                "reason": "数学渲染文本穿插导致的非连续提取",
                                "input": str(chapter.path),
                            }
                        )
                        position = consumed
                        continue
                    failures.append(
                        {
                            "code": "text-missing",
                            "message": "文本段未在 PDF 对应章节中按顺序出现：%r"
                            % segment.strip()[:60],
                            "input": str(chapter.path),
                        }
                    )
        else:
            for item in chapter.code_blocks:
                needle = normalize(item)
                if not needle:
                    continue
                found = pdf.find(needle, position)
                if found < 0 or found + len(needle) > end_offset:
                    failures.append(
                        {
                            "code": "code-missing",
                            "message": "代码块未在 PDF 对应章节中按顺序出现：%r"
                            % item[:60],
                            "input": str(chapter.path),
                        }
                    )
                    continue
                position = found + len(needle)


def check_math(chapters, report, failures):
    browser = report.get("browser_checks", {})
    katex_errors = browser.get("katex") or []
    for error in katex_errors:
        failures.append(
            {
                "code": "katex-error",
                "message": "公式渲染失败 %s：%s" % (error.get("id"), error.get("message")),
            }
        )
    total = 0
    for chapter in chapters:
        total += len(chapter.math)
    if browser.get("mathTotal", total) != total:
        failures.append(
            {
                "code": "math-count-mismatch",
                "message": "浏览器公式节点数 %s 与解析预期 %d 不一致"
                % (browser.get("mathTotal"), total),
            }
        )


def check_links(chapters, pdf, bounds, heading_pages, failures, reviews):
    expected_internal = []
    for chapter, start_page, end_page in bounds:
        for link in chapter.internal_links:
            expected_internal.append((chapter, link, start_page, end_page))

    internal_count = len(pdf.internal_annots)
    if internal_count < len(expected_internal):
        failures.append(
            {
                "code": "internal-link-count",
                "message": "PDF 内部链接注解 %d 少于预期 %d"
                % (internal_count, len(expected_internal)),
            }
        )

    dest_pages = {a["dest_page"] for a in pdf.internal_annots}
    annots_by_page = {}
    for annot in pdf.internal_annots:
        annots_by_page.setdefault(annot["page"], []).append(annot["dest_page"])

    for chapter, link, start_page, end_page in expected_internal:
        # 目标判定优先采用消解结果（跨章文件链接的片段属于其他章），
        # 退化为"本章 slug 优先、其他章唯一命中"的规则。
        target_id = link.get("resolved")
        if target_id not in heading_pages:
            target_id = None
            for heading in chapter.headings:
                if heading["slug"] == link["fragment"]:
                    target_id = heading["id"]
                    break
            if target_id is None:
                others = [
                    heading["id"]
                    for other in chapters
                    if other is not chapter
                    for heading in other.headings
                    if heading["slug"] == link["fragment"]
                ]
                if len(others) == 1:
                    target_id = others[0]
        if target_id and target_id in heading_pages:
            target_page = heading_pages[target_id]
            text_norm = normalize(link.get("text") or "")
            source_page = None
            if text_norm:
                for page_index in range(start_page, end_page):
                    if text_norm and text_norm in normalize(pdf.pages[page_index]):
                        source_page = page_index
                        break
            if (
                source_page is not None
                and target_page not in annots_by_page.get(source_page, [])
            ):
                failures.append(
                    {
                        "code": "internal-link-target",
                        "message": "内部链接未指向正确目标页（链接 %r，期望第 %d 页）"
                        % (link.get("text"), target_page + 1),
                        "input": str(chapter.path),
                    }
                )
            elif target_page not in dest_pages:
                failures.append(
                    {
                        "code": "internal-link-target",
                        "message": "没有任何内部链接指向目标页 %d（片段 %s）"
                        % (target_page + 1, link["fragment"]),
                        "input": str(chapter.path),
                    }
                )

    expected_external = sorted(
        {href for chapter in chapters for href in chapter.external_links}
    )
    missing = [href for href in expected_external if href not in pdf.uri_links]
    for href in missing:
        failures.append(
            {"code": "external-link-missing", "message": "外链未保留：%s" % href}
        )

    for chapter in chapters:
        for link in chapter.range_out_links:
            reviews.append(
                {
                    "code": "range-out-link",
                    "message": "范围外本地文档链接待处置：%s（%s）"
                    % (link["href"], "文件存在" if link["exists"] else "文件不存在"),
                    "input": str(chapter.path),
                    "line": link.get("source_line"),
                }
            )


def check_outline(chapters, pdf, heading_pages, failures):
    expected = [(chapter, heading) for chapter in chapters for heading in chapter.headings]
    if len(pdf.outline) != len(expected):
        failures.append({"code": "outline-count", "message": "PDF 大纲条目数与标题数不一致"})
    # 消费全部层级，避免上一章同名小节被误认为下一章的章首。
    for (chapter, heading), entry in zip(expected, pdf.outline):
        if not heading_matches(heading, entry["title"]):
            failures.append({"code": "outline-entry-missing", "input": str(chapter.path),
                             "message": "大纲标题顺序或文字不一致：" + heading["text"]})
        elif entry["page"] != heading_pages.get(heading["id"]):
            failures.append({"code": "outline-entry-page", "input": str(chapter.path),
                             "message": "大纲目标页与标题实际页不一致：" + heading["text"]})


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="独立核验导出 PDF 与原始输入的一致性（机器层）。"
    )
    parser.add_argument("--pdf", required=True, help="待核验 PDF 路径")
    parser.add_argument("--work-dir", required=True, help="导出时使用的同一临时目录")
    parser.add_argument("inputs", nargs="+", help="有序 Markdown 输入")
    args = parser.parse_args(argv)

    work_dir = Path(args.work_dir).expanduser()
    report_path = work_dir / REPORT_NAME
    if not report_path.is_file():
        print("FAIL: 找不到导出证据 %s" % report_path, file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))

    failures = []
    relaxed = []
    reviews = []

    chapters = reparse_inputs(args.inputs, failures)
    cross_check(chapters, failures)
    check_inputs_protection(report, failures)

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.is_file():
        failures.append({"code": "pdf-missing", "message": "PDF 不存在：%s" % pdf_path})
        pdf = None
    else:
        try:
            pdf = PdfFacts(pdf_path)
        except Exception as exc:  # noqa: BLE001  任何解析失败都判机器不通过
            failures.append(
                {"code": "pdf-unreadable", "message": "PDF 无法解析：%s" % exc}
            )
            pdf = None

    if pdf is not None:
        if report.get("pdf_sha256") != exporter.sha256_file(pdf_path):
            failures.append({"code": "pdf-evidence-mismatch",
                             "message": "PDF 与导出证据不匹配，请重新导出并核验"})
        expected_inputs = [str(c.path) for c in chapters]
        if expected_inputs != [item.get("path") for item in report.get("inputs", [])]:
            failures.append({"code": "input-order-mismatch",
                             "message": "核验输入及顺序与导出证据不一致"})
        if report.get("status") != STATUS_MACHINE_PASS:
            failures.append({"code": "export-not-passed", "message": "导出机器检查未通过"})
        if len(pdf.pages) < len(chapters):
            failures.append(
                {
                    "code": "page-count",
                    "message": "PDF 页数 %d 少于章节数 %d" % (len(pdf.pages), len(chapters)),
                }
            )
        heading_pages = {}
        check_headings(chapters, pdf, failures, heading_pages)
        bounds = chapter_bounds(chapters, pdf, heading_pages, failures)
        check_blocks(chapters, pdf, bounds, failures, relaxed, "text")
        check_blocks(chapters, pdf, bounds, failures, [], "code")
        check_math(chapters, report, failures)
        check_links(chapters, pdf, bounds, heading_pages, failures, reviews)
        check_outline(chapters, pdf, heading_pages, failures)

    machine_pass = not failures
    verify_report = {
        "status": STATUS_MACHINE_PASS if machine_pass else STATUS_MACHINE_FAIL,
        "failures": failures,
        "reviews": reviews,
        "relaxed_matches": relaxed,
        "pages": len(pdf.pages) if pdf is not None else None,
        "outline_entries": len(pdf.outline) if pdf is not None else None,
        "internal_link_annots": len(pdf.internal_annots) if pdf is not None else None,
        "external_uri_annots": sorted(pdf.uri_links) if pdf is not None else [],
    }
    (work_dir / VERIFY_NAME).write_text(
        json.dumps(verify_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not machine_pass:
        print("FAIL: 核验未通过（%d 项），详见 %s" % (len(failures), work_dir / VERIFY_NAME), file=sys.stderr)
        for failure in failures[:20]:
            print(
                "  [%s] %s %s"
                % (failure["code"], failure.get("input", ""), failure["message"]),
                file=sys.stderr,
            )
        return 1
    print(
        "机器检查通过，成品待视觉复核：%s（核验证据 %s）"
        % (pdf_path, work_dir / VERIFY_NAME)
    )
    for item in relaxed:
        print(
            "  待复核 [%s] %s（已解释：数学渲染文本穿插，逐段字符齐全且顺序一致）"
            % (item["input"], item["segment"])
        )
    for review in reviews:
        print(
            "  待处置 [%s] %s:%s %s"
            % (review["code"], review.get("input", ""), review.get("line", ""), review["message"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
