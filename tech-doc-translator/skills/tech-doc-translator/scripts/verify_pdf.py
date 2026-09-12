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
from urllib.parse import unquote

import pypdf
from markdown_it import MarkdownIt

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
# PDF 图片逐次绘制量测（内容流 q/cm/Do 矩阵解析）
# ---------------------------------------------------------------------------

# 打印舍入容差：以固定已知宽度样例实测确定（见阶段 02 回归），只吸收
# Chromium 打印的亚点级舍入，不用于掩盖串用或错误宽度。
IMAGE_WIDTH_TOLERANCE_PT = 0.75


def _matmul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def collect_drawn_images(pdf):
    """逐页解析内容流，返回每页按绘制顺序的图片宽度（pt）列表。

    图片 XObject 以单位正方形进入用户空间，当前 CTM 的 x 轴向量长度
    即绘制宽度。矩阵语义独立于导出器；无法解析的页面返回空并让计数
    对账暴露差异。
    """
    result = []
    for page in pdf.reader.pages:
        widths = []
        try:
            resources = page["/Resources"].get_object()
            xobjects = resources.get("/XObject")
            images = {}
            if xobjects is not None:
                xobjects = xobjects.get_object()
                for name, ref in xobjects.items():
                    obj = ref.get_object()
                    if obj.get("/Subtype") == "/Image":
                        images[str(name)] = obj
            if not images:
                result.append(widths)
                continue
            from pypdf.generic import ContentStream

            stream = ContentStream(page.get_contents(), pdf.reader)
            stack = []
            ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            for operands, operator in stream.operations:
                op = operator.decode("latin-1") if isinstance(operator, bytes) else str(operator)
                if op == "q":
                    stack.append(ctm)
                elif op == "Q":
                    ctm = stack.pop() if stack else ctm
                elif op == "cm" and len(operands) == 6:
                    ctm = _matmul(tuple(float(x) for x in operands), ctm)
                elif op == "Do":
                    name = str(operands[0])
                    if name in images:
                        a, b = ctm[0], ctm[1]
                        widths.append((a * a + b * b) ** 0.5)
            result.append(widths)
        except Exception:  # noqa: BLE001  内容流异常由计数对账暴露
            result.append([])
    return result


def check_image_widths(chapters, pdf, bounds, bindings, report, failures):
    """核对映射命中的图片逐次实际绘制宽度符合 min(显示宽度, 版心上限)。

    期望值由映射文件与原始输入独立重建（不信任导出器统计），量测从最终
    PDF 的内容流独立取得（q/cm/Do 矩阵）。导出证据记录同时被交叉对账；
    绘制次数不足或宽度超差都判 FAIL。无映射命中的出现按自然尺寸回退，
    仅受既有溢出检查约束。
    """
    drawn_per_page = collect_drawn_images(pdf)
    page_range = {chapter.path: (start, end) for chapter, start, end in bounds}
    recorded = report.get("image_display", {})
    for chapter in chapters:
        occurrence_map = bindings.get(chapter.path, {})
        if not occurrence_map:
            continue
        context = {"input": str(chapter.path)}
        chapter_records = {
            item.get("occurrence"): item
            for item in recorded.get(str(chapter.path), [])
        }
        start_page, end_page = page_range.get(
            chapter.path, (0, len(pdf.pages))
        )
        in_chapter = [
            width
            for index in range(start_page, end_page)
            for width in drawn_per_page[index]
        ]
        for occurrence, binding in sorted(occurrence_map.items()):
            px = binding["px"]
            expected_pt = (
                min(px, exporter.CONTENT_WIDTH_PX) * exporter.PT_PER_CSS_PX
            )
            record = chapter_records.get(occurrence)
            if record is None or abs(
                (record.get("applied_px") or -1) - px
            ) > 1e-6:
                failures.append(
                    {
                        "code": "image-display-evidence-mismatch",
                        "message": "第 %d 次出现的显示尺寸与导出证据记录不一致"
                        % occurrence,
                        **context,
                    }
                )
            if occurrence > len(in_chapter):
                failures.append(
                    {
                        "code": "image-draw-count",
                        "message": "第 %d 次图片出现未在 PDF 章区间内绘制"
                        % occurrence,
                        **context,
                    }
                )
                continue
            measured = in_chapter[occurrence - 1]
            if abs(measured - expected_pt) > IMAGE_WIDTH_TOLERANCE_PT:
                failures.append(
                    {
                        "code": "image-width-mismatch",
                        "message": "第 %d 次图片绘制宽度 %.2fpt 与期望 %.2fpt"
                        "（%spx，%s）不符"
                        % (
                            occurrence,
                            measured,
                            expected_pt,
                            px,
                            "受限版心" if px > exporter.CONTENT_WIDTH_PX else "源显示宽度",
                        ),
                        **context,
                    }
                )


# ---------------------------------------------------------------------------
# 印刷目录独立对账（可见页码、链接目的地与目标标题位置逐条比对）
# ---------------------------------------------------------------------------

TOC_FILE_NAME = exporter.TOC_FILE_NAME
_TOC_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(#[^)\s]*)?\)")
# 引用定义与引用式链接（[标签][ref]、[标签][]、快捷式 [标签]）。
_TOC_DEF_RE = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*<?([^<>\s]+)>?", re.M)
_TOC_USAGE_RE = re.compile(
    r"(?<!!)\[([^\]\[]+)\]\(([^)\s]+)\)"          # inline 链接
    r"|(?<!!)\[([^\]\[^]+)\](?:\[([^\]\[]*)\])?"  # 引用/折叠/快捷式
)


def _toc_link_destinations(text):
    """按文档顺序提取目录文本中的本地文档链接目的地（含引用定义）。

    返回 [(路径原文, 片段或 None)]；引用定义行本身不算使用。
    """
    definitions = {
        match.group(1).lower(): match.group(2)
        for match in _TOC_DEF_RE.finditer(text)
    }
    usage_text = _TOC_DEF_RE.sub("", text)
    destinations = []
    for match in _TOC_USAGE_RE.finditer(usage_text):
        if match.group(2) is not None:
            destination = match.group(2)
        else:
            key = (match.group(4) or match.group(3)).lower()
            destination = definitions.get(key)
            if destination is None:
                continue
        path_part, _, fragment = destination.partition("#")
        if not path_part.endswith(".md"):
            continue
        destinations.append((path_part, fragment or None))
    return destinations


def derive_toc_expectations(chapters, include_sections, failures=None):
    """从原输入与自有授权投影独立重建印刷目录预期。

    与导出器相互独立：目录文本中指向已纳入章节的本地链接（inline 与
    引用式）按文档顺序生成章级条目，标题取目标章首个标题；同一章的
    节/片段链接折叠；include_sections 时补充指向二级标题的可消解
    片段与纯文本层级列表中能按节号定位的一级节。无法消解的片段按
    合同阻断（failures 记录），不静默省略。
    """
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    if toc_chapter is None:
        return None
    text = apply_authorized_spans(
        toc_chapter.text, authorized_head_exclusions(toc_chapter.text))
    expectations = []
    seen = set()
    link_sections = []
    for path_part, raw_fragment in _toc_link_destinations(text):
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        included = next((c for c in chapters if c.path == target), None)
        if included is None or included is toc_chapter:
            continue
        fragment = unquote(raw_fragment) if raw_fragment else None
        if fragment is not None and fragment not in included.targets:
            if failures is not None:
                failures.append(
                    {
                        "code": "toc-fragment-unresolved",
                        "message": "目录链接片段无法消解：%s#%s"
                        % (included.path.name, fragment),
                        "input": str(toc_chapter.path),
                    }
                )
            continue
        if included.index not in seen:
            seen.add(included.index)
            title = (included.headings[0]["text"] if included.headings
                     else included.path.stem)
            expectations.append(
                {"level": 1, "title": title, "chapter_index": included.index}
            )
        # --toc-sections 期望同步：指向二级标题的可消解片段并入一级节；
        # 章首（H1）、更深层（H3+）与普通锚点不构成一级节。
        if not (include_sections and fragment):
            continue
        target_info = included.targets.get(fragment) or {}
        if target_info.get("kind") == "anchor":
            if failures is not None:
                failures.append(
                    {
                        "code": "toc-anchor-unassociated",
                        "message": "目录链接片段指向普通锚点，无法确定"
                        "关联的一级节标题：%s#%s"
                        % (included.path.name, fragment),
                        "input": str(toc_chapter.path),
                    }
                )
            continue
        if not (target_info.get("kind") == "heading"
                and target_info.get("level") == 2):
            continue
        target_id = included.prefix + fragment
        heading = next(
            (h for h in included.headings if h["id"] == target_id), None
        )
        if heading is not None:
            section = {
                "level": 2, "title": heading["text"],
                "chapter_index": included.index,
            }
            if section not in link_sections:
                link_sections.append(section)
    if include_sections:
        sections = list(link_sections)
        for match in re.finditer(
            r"^\s*[-*]\s+(\d+(?:\.\d+)+)\.?\s+", text, re.M
        ):
            number = match.group(1)
            chapter_number = number.split(".")[0]
            parent = next(
                (
                    e
                    for e in expectations
                    if e["level"] == 1
                    and (re.match(r"^%s[.\s（(]" % re.escape(chapter_number), e["title"])
                         or re.search(
                             r"第\s*%s\s*章" % re.escape(chapter_number), e["title"]
                         ))
                ),
                None,
            )
            if parent is None:
                continue
            included = next(
                (c for c in chapters if c.index == parent["chapter_index"]), None
            )
            if included is None:
                continue
            heading = next(
                (h for h in included.headings if h["text"].startswith(number)), None
            )
            if heading is not None:
                candidate = {
                    "level": 2, "title": heading["text"],
                    "chapter_index": included.index,
                }
                if candidate not in sections:
                    sections.append(candidate)
        # 打印顺序：一级节紧跟其所属章级条目。
        ordered = []
        for entry in expectations:
            ordered.append(entry)
            ordered.extend(
                s for s in sections if s["chapter_index"] == entry["chapter_index"]
            )
        expectations = ordered
    return expectations


def _toc_find_entry(lines, title_norm, cursor):
    """在目录页文本行中定位条目及其可见页码。

    标题可能跨任意多行（长中文标题换行，不设行数上限）；页码在标题
    同行行尾或下一行行首。按行解析避免“页码 + 下一章号”在全卷拼接时
    粘连成更大数字。标题已完整出现但页码不在其后时换起始行继续找。
    返回 (页码或 None, 消费到的行游标)。
    """
    for index in range(cursor, len(lines)):
        for end in range(index, len(lines)):
            chunk = "".join(lines[index:end + 1])
            position = chunk.find(title_norm)
            if position < 0:
                continue
            tail = chunk[position + len(title_norm):]
            match = re.match(r"^(\d{1,4})(?!\d)", tail)
            if match:
                return int(match.group(1)), end + 1
            if end + 1 < len(lines):
                match = re.match(r"^(\d{1,4})(?!\d)", lines[end + 1])
                if match:
                    return int(match.group(1)), end + 2
            break  # 标题出现处无页码：从下一起始行重找
    return None, cursor


def check_print_toc(chapters, pdf, report, bounds, heading_pages, failures):
    """印刷目录核验：条目齐全、只出现一次、可见页码=目标页、链接到达。"""
    expectations = derive_toc_expectations(
        chapters, report.get("toc", {}).get("sections", False), failures
    )
    if expectations is None:
        if report.get("toc", {}).get("enabled"):
            failures.append(
                {"code": "toc-evidence-mismatch",
                 "message": "导出证据声明有印刷目录，但输入中无目录文件"}
            )
        return
    recorded = report.get("toc", {})
    if not recorded.get("enabled"):
        failures.append(
            {"code": "toc-evidence-mismatch",
             "message": "输入包含 00_目录.md 但导出证据未声明印刷目录"}
        )
        return
    recorded_titles = [e.get("title") for e in recorded.get("entries", [])]
    expected_titles = [e["title"] for e in expectations]
    if recorded_titles != expected_titles:
        failures.append(
            {
                "code": "toc-evidence-mismatch",
                "message": "印刷目录条目与独立重建不一致（%r != %r）"
                % (recorded_titles, expected_titles),
            }
        )
        return
    if recorded.get("prints", 0) > exporter.MAX_TOC_PRINTS:
        failures.append(
            {"code": "toc-prints", "message": "印刷目录打印次数超过上限"}
        )

    toc_chapter = next(c for c in chapters if c.is_toc)
    toc_bounds = next(
        ((s, e) for c, s, e in bounds if c is toc_chapter), None
    )
    if toc_bounds is None:
        return  # 章区间已因结构问题判 FAIL，目录对账无从进行
    start_page, end_page = toc_bounds
    toc_lines = [
        normalize(line)
        for index in range(start_page, end_page)
        for line in pdf.pages[index].splitlines()
    ]
    toc_joined = "".join(toc_lines)
    # 分篇合同（T16）：核验器判定为纯导航的范围外章节行不应出现在
    # 印刷目录页；整行文本（编号+标题+文件名）足以区分说明文字中的
    # 合法提及。
    for text in getattr(toc_chapter, "excluded_nav_texts", ()):
        if normalize(text) in toc_joined:
            failures.append(
                {
                    "code": "toc-out-of-scope-entry",
                    "message": "印刷目录仍包含范围外章节的导航条目：%s"
                    % text[:60],
                }
            )
    # 位置绑定：目录页内的内部链接注解按“页序 + 自上而下”排列后与
    # 条目一一对应；数量一致时逐条比对注解实际目的地，交换目的地而
    # 标题/页码/目标页集合不变也会被逐位关联检出（N02/T20）。
    toc_annots = sorted(
        (
            annot for annot in pdf.internal_annots
            if start_page <= annot["page"] < end_page
        ),
        key=lambda annot: (annot["page"], -annot.get("top", 0.0)),
    )
    positional = len(toc_annots) == len(expectations)
    position = 0
    for ordinal, (entry, record) in enumerate(
        zip(expectations, recorded.get("entries", []))
    ):
        title_norm = normalize(entry["title"])
        printed, found_at = _toc_find_entry(toc_lines, title_norm, position)
        if printed is None:
            failures.append(
                {
                    "code": "toc-entry-missing",
                    "message": "印刷目录缺少条目或未找到可见页码：%s" % entry["title"],
                }
            )
            continue
        position = found_at
        # 印刷目录只出现一次：标题连同其可见页码的邻接组合在目录页
        # 不应再次出现。目录页保留的散文（如未消费的说明表格）可能
        # 合法地重复标题文字，但不会重复“标题+页码”的目录条目形态。
        if printed is not None and toc_joined.count(title_norm + str(printed)) > 1:
            failures.append(
                {
                    "code": "toc-duplicated",
                    "message": "目录条目在目录页重复出现：%s" % entry["title"],
                }
            )
        target_page = record.get("page")
        if not isinstance(target_page, int) or target_page < 1:
            failures.append(
                {
                    "code": "toc-page-missing",
                    "message": "目录条目页码缺失：%s" % entry["title"],
                }
            )
            continue
        if printed != target_page:
            failures.append(
                {
                    "code": "toc-page-number",
                    "message": "可见页码 %d 与导出记录 %d 不一致：%s"
                    % (printed, target_page, entry["title"]),
                }
            )
        # 目标页：章级条目指向章起始页；一级节指向标题实际页。
        included = next(
            c for c in chapters if c.index == entry["chapter_index"]
        )
        chapter_start = next(
            s for c, s, _ in bounds if c is included
        )
        if entry["level"] == 1:
            expected_target = chapter_start + 1
        else:
            heading_id = next(
                (
                    h["id"]
                    for h in included.headings
                    if h["text"] == entry["title"]
                ),
                None,
            )
            expected_target = (
                heading_pages[heading_id] + 1 if heading_id in heading_pages else None
            )
        if expected_target is not None and target_page != expected_target:
            failures.append(
                {
                    "code": "toc-target-page",
                    "message": "页码 %d 与目标实际页 %d 不一致：%s"
                    % (target_page, expected_target, entry["title"]),
                }
            )
        # 点击到达：目录页上的链接注解必须实际指向目标页。数量一致时
        # 按位置逐条绑定（自上而下第 N 条注解属于第 N 条目录条目），
        # 交换目的地不能靠“某条注解恰好指向目标页”混过。
        target_index = target_page - 1
        if positional:
            annot = toc_annots[ordinal]
            if annot["dest_page"] != target_index:
                failures.append(
                    {
                        "code": "toc-link-target",
                        "message": "目录条目链接未实际指向目标页 %d"
                        "（实际指向第 %d 页）：%s"
                        % (target_page, annot["dest_page"] + 1,
                           entry["title"]),
                    }
                )
        elif not any(
            start_page <= annot["page"] < end_page
            and annot["dest_page"] == target_index
            for annot in pdf.internal_annots
        ):
            failures.append(
                {
                    "code": "toc-link-target",
                    "message": "目录条目链接未实际指向目标页 %d：%s"
                    % (target_page, entry["title"]),
                }
            )


# ---------------------------------------------------------------------------
# 章首管理字段投影的独立授权扫描（不照抄导出器的排除清单）
# ---------------------------------------------------------------------------

AUTHORIZED_LABELS = ("原文", "译例说明")
# 章首管理引用块家族：与导出器独立声明的同一合同口径。
_AUTHORIZED_FAMILY = {"原文", "译例说明", "来源", "抓取日期"}
_AUTHORIZED_FIELD = re.compile(r"^>\s*\*{0,2}\s*(\S{1,15}?)\s*\*{0,2}\s*[：:]")
_AUTHORIZED_STRUCTURE = MarkdownIt("commonmark")


def authorized_head_exclusions(text):
    """独立重derive章首管理字段的授权排除区间。

    与导出器相互独立：用自有 CommonMark 实例按块 token 与源行位置重建
    章首结构——标题/分隔线/管理引用块顺延构成章首，管理引用块首个子块
    必须是家族标签字段段；授权标签字段段连同其无标签的段落/列表延续块
    （含 lazy 续行，解析器已并入字段段）排除，围栏、缩进代码与嵌套引用
    属技术内容终止延续。返回 [(起始行0基, 最后行1基, 标签)]；核验器用
    本结果与导出证据对账，伪造排除正文时两侧不一致必须 FAIL。
    """
    tokens = _AUTHORIZED_STRUCTURE.parse(text)
    source = text.split("\n")
    spans = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.type == "heading_open":
            cursor += 3
            continue
        if token.type == "hr":
            cursor += 1
            continue
        if token.type != "blockquote_open":
            break
        # 引用块整体区间见 token.map；收集直接子块（紧邻层级、带源行区间）。
        children = []
        scan = cursor + 1
        while scan < len(tokens) and tokens[scan].type != "blockquote_close":
            child = tokens[scan]
            if (child.level == token.level + 1 and child.map is not None
                    and (child.type.endswith("_open")
                         or child.type in ("fence", "code_block",
                                           "hr", "html_block"))):
                first_line = source[child.map[0]]
                label = None
                if child.type == "paragraph_open":
                    matched = _AUTHORIZED_FIELD.match(first_line.strip())
                    if matched:
                        label = matched.group(1).strip("*")
                children.append((child.map[0], child.map[1], label, child.type))
            scan += 1
        if not children or children[0][2] not in _AUTHORIZED_FAMILY:
            break  # 非管理引用块：技术正文边界
        # 字段按行推进：引用段落可合并多个字段行（无空行分隔），行级
        # 标签定边界；无标签段落/列表行延续活动字段，代码与嵌套引用等
        # 技术块终止延续。仅授权标签的区间进入结果。
        segments = []
        running = None
        for c_start, c_end, _c_label, c_kind in children:
            if c_kind == "paragraph_open":
                for line_no in range(c_start, c_end):
                    matched = _AUTHORIZED_FIELD.match(source[line_no].strip())
                    if matched is not None:
                        running = [matched.group(1).strip("*"),
                                   line_no, line_no + 1]
                        segments.append(running)
                    elif running is not None:
                        running[2] = line_no + 1
            elif running is not None and c_kind in (
                    "bullet_list_open", "ordered_list_open"):
                running[2] = max(running[2], c_end)
            else:
                running = None
        spans.extend(
            (start, end, label) for label, start, end in segments
            if label in AUTHORIZED_LABELS
        )
        cursor = scan + 1
    return spans


def apply_authorized_spans(text, spans):
    """按授权区间生成投影文本（与导出器投影结果做字符串级对账）。"""
    drop = set()
    for start, end, _label in spans:
        drop.update(range(start, end))
    return "\n".join(
        line for number, line in enumerate(text.split("\n")) if number not in drop
    )


def check_projection(chapters, report, pdf, failures):
    """排除区间必须与独立扫描一致，且被排除内容确实不在 PDF 中。"""
    recorded_chapters = {
        item.get("path"): item
        for item in report.get("chapters", [])
    }
    for chapter in chapters:
        authorized = authorized_head_exclusions(chapter.text)
        expected_text = apply_authorized_spans(chapter.text, authorized)
        context = {"input": str(chapter.path)}
        if expected_text != chapter.projected_text:
            failures.append(
                {
                    "code": "exclusion-unauthorized",
                    "message": "导出投影与独立授权扫描不一致（存在未授权排除或投影缺陷）",
                    **context,
                }
            )
        expected_records = [
            {
                "label": label,
                "start_line": start + 1,
                "end_line": end,
                "reason": exporter.EXCLUSION_REASON,
            }
            for start, end, label in authorized
        ]
        if chapter.exclusions != expected_records:
            failures.append(
                {
                    "code": "exclusion-unauthorized",
                    "message": "章节排除区间与独立扫描不一致",
                    **context,
                }
            )
        recorded = recorded_chapters.get(str(chapter.path), {})
        if recorded.get("management_exclusions") != expected_records:
            failures.append(
                {
                    "code": "exclusion-evidence-mismatch",
                    "message": "导出证据中的排除区间与独立扫描不一致",
                    **context,
                }
            )
        if pdf is None:
            continue
        lines = chapter.text.split("\n")
        for start, end, label in authorized:
            for line in lines[start:end]:
                needle = normalize(line)
                if len(needle) >= 4 and needle in pdf.norm_text:
                    failures.append(
                        {
                            "code": "excluded-content-present",
                            "message": "被排除字段内容仍出现在 PDF 中（%s）：%r"
                            % (label, line[:60]),
                            **context,
                        }
                    )


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
        self.internal_annots = []  # {page, dest_page, top}
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
                rect = obj.get("/Rect")
                top = float(rect[3]) if rect is not None else 0.0
                if name_key is not None:
                    if name_key in named:
                        self.internal_annots.append(
                            {"page": page_index,
                             "dest_page": named[name_key], "top": top}
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
                        rect = obj.get("/Rect")
                        top = float(rect[3]) if rect is not None else 0.0
                        if index is not None:
                            self.internal_annots.append(
                                {"page": page_index, "dest_page": index,
                                 "top": top}
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

def consume_toc_navigation(toc_chapter, chapters, failures, include_sections):
    """核验器自有的目录导航消费，与导出器相互独立实现同一合同。

    在事实收集前从目录章 soup 中移除已确认的导航内容，使“PDF 应包含
    哪些正文”的预期来自核验器自己的判定，而不是导出器的删除决定：
    链接容器按目标可消解性定位（坏片段记 failures 且不消费），纯导航
    容器删除、混合容器仅解除导航链接；范围外目标的纯导航行按分篇合同
    一并移除并记录，供目录页断言其不再出现；层级列表按条目对应关系
    消费已确认的导航项；数据行全消费的表格与空列表连同纯引导句清理。
    返回是否发现任何导航条目。
    """
    included_paths = {c.path for c in chapters if c is not toc_chapter}
    found_nav = False

    def _resolves(anchor):
        href = anchor.get("href", "")
        path_part = href.partition("#")[0]
        if not path_part or re.match(r"^[a-z][a-z0-9+.-]*:", path_part, re.I):
            return None
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        return target if target in included_paths else None

    def _nav_only(element, extra_identity=()):
        # 非链接文本只剩章编号/标题/文件名等导航元数据即视为纯导航；
        # 其他可见内容（说明、注记、图片）表示混合容器。extra_identity
        # 仅供范围外目标的行使用，不改变已纳入容器的判定。
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
                if isinstance(child, exporter.NavigableString):
                    text = str(child).strip()
                    if not text or numeric.match(text):
                        continue
                    if any(text in name or name in text for name in identity):
                        continue
                    return False
                elif isinstance(child, exporter.Tag):
                    if child.name == "a" and child.get("href"):
                        continue
                    if child.name == "img":
                        return False
                    if not scan(child):
                        return False
            return True

        return scan(element)

    consumed_containers = []
    seen_containers = set()
    for anchor in list(toc_chapter.soup.find_all("a", href=True)):
        target = _resolves(anchor)
        if target is None:
            continue
        included = next(c for c in chapters if c.path == target)
        fragment = unquote(anchor.get("href", "").partition("#")[2] or "")
        if fragment and fragment not in included.targets:
            failures.append(
                {
                    "code": "toc-fragment-unresolved",
                    "message": "目录链接片段无法消解：%s#%s"
                    % (included.path.name, fragment),
                    "input": str(toc_chapter.path),
                }
            )
            continue
        if include_sections and fragment:
            info = included.targets.get(fragment) or {}
            if info.get("kind") == "anchor":
                failures.append(
                    {
                        "code": "toc-anchor-unassociated",
                        "message": "目录链接片段指向普通锚点，无法确定"
                        "关联的一级节标题：%s#%s"
                        % (included.path.name, fragment),
                        "input": str(toc_chapter.path),
                    }
                )
                continue
        container = anchor.find_parent(["li", "tr"])
        if container is None or id(container) in seen_containers:
            continue
        seen_containers.add(id(container))
        consumed_containers.append(container)
        found_nav = True

    for container in consumed_containers:
        if _nav_only(container):
            container.decompose()
        else:
            for anchor in container.find_all("a", href=True):
                if _resolves(anchor) is not None:
                    anchor.replace_with(anchor.get_text(strip=True))

    # 分篇合同（与导出器独立同构）：指向未纳入章节的链接不是本书导航
    # 目标。纯导航行从核验器自己的正文预期中移除并记录行文本，供
    # check_print_toc 断言范围外条目不出现在印刷目录页；混合容器与
    # 裸链接只解除链接，说明保留。
    all_paths = {c.path for c in chapters}
    out_identity = set()
    out_anchors = []
    for anchor in list(toc_chapter.soup.find_all("a", href=True)):
        href = anchor.get("href", "")
        path_part = href.partition("#")[0]
        if not path_part or re.match(r"^[a-z][a-z0-9+.-]*:", path_part, re.I):
            continue
        target = (toc_chapter.dir / unquote(path_part)).resolve()
        if target in all_paths:
            continue
        out_anchors.append((anchor, target))
        for name in (target.stem, target.name, anchor.get_text(strip=True)):
            if name:
                out_identity.add(name)
    excluded_nav_texts = []
    for anchor, _target in out_anchors:
        if anchor.decomposed:
            continue  # 已随所属的已纳入导航行一并消费
        container = anchor.find_parent(["li", "tr"])
        if container is not None and _nav_only(container, out_identity):
            excluded_nav_texts.append(container.get_text(" ", strip=True))
            container.decompose()
        else:
            anchor.replace_with(anchor.get_text(strip=True))
    toc_chapter.excluded_nav_texts = excluded_nav_texts

    # 层级列表：条目文本与已纳入章节标题能对应上的才是导航条目；
    # 只移除对应项，其余说明保留。
    def _item_corroborates(item_text):
        if not item_text:
            return False
        numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", item_text)
        if numbered is not None:
            number, title = numbered.group(1), numbered.group(2).strip()
            return any(
                heading["text"].startswith(number) and title in heading["text"]
                for chapter in chapters if chapter is not toc_chapter
                for heading in chapter.headings
            )
        return any(
            item_text in heading["text"]
            for chapter in chapters if chapter is not toc_chapter
            for heading in chapter.headings
        )

    for element in list(toc_chapter.soup.find_all(["ul", "ol"])):
        if element.find_parent(["li"]) is not None:
            continue
        if element.find("a", href=True) is not None:
            continue
        items = element.find_all("li")
        nav_items = [i for i in items
                     if _item_corroborates(i.get_text(" ", strip=True))]
        if not nav_items or len(nav_items) * 2 < len(items):
            continue
        found_nav = True
        nav_ids = {id(item) for item in nav_items}
        for item in nav_items:
            if any(id(parent) in nav_ids for parent in item.parents):
                continue
            item.decompose()

    def _drop_with_lead_in(element):
        lead = element.previous_sibling
        while lead is not None and not isinstance(lead, exporter.Tag):
            lead = lead.previous_sibling
        element.decompose()
        if (lead is not None and lead.name == "p"
                and lead.find("a") is None
                and lead.get_text(" ", strip=True).endswith(("：", ":"))):
            lead.decompose()

    for item in list(toc_chapter.soup.find_all("li")):
        if not item.get_text(strip=True) and item.find(["a", "img"]) is None:
            item.decompose()
    for table in list(toc_chapter.soup.find_all("table")):
        if table.find("td") is None:
            _drop_with_lead_in(table)
    for element in list(toc_chapter.soup.find_all(["ul", "ol"])):
        if element.find("li") is None:
            _drop_with_lead_in(element)
    return found_nav


def reparse_inputs(paths, failures, unlink_targets=(), toc_sections=False):
    """用同一解析层重读输入，重建预期（与原始扫描交叉核对）。

    目录章的导航消费用核验器自有的 consume_toc_navigation，不复用
    导出器的删除决定；坏目标由核验器自己的定位阻断。
    """
    chapters = exporter.load_inputs(paths)
    for chapter in chapters:
        exporter.parse_chapter(chapter)
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    if toc_chapter is not None:
        if not consume_toc_navigation(
            toc_chapter, chapters, failures, toc_sections
        ):
            failures.append(
                {
                    "code": "toc-unusable",
                    "message": "目录文件未包含任何指向已纳入章节的导航条目",
                    "input": str(toc_chapter.path),
                }
            )
    for chapter in chapters:
        exporter.collect_chapter_facts(chapter)
    resolve_diagnostics = []
    for chapter in chapters:
        exporter.resolve_links(
            chapter, chapters, resolve_diagnostics, unlink_targets
        )
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
    """原始扫描与解析层计数必须一致，防止共享解析缺陷同时骗过双方。

    双方都在授权投影后的导出视图上工作；投影本身由
    check_projection 用独立扫描单独对账。
    """
    for chapter in chapters:
        scan = raw_scan(chapter.projected_text)
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


def check_unlinked_links(chapters, pdf, unlink_targets, report, failures):
    """独立核对指向默认排除目标的链接投影。

    从授权投影后的文本独立扫描指向排除目标的链接：导出层记录必须与之
    一致，且链接文字仍完整出现在 PDF 中（转为纯文本而非删除）。核验参
    数必须与导出证据记录的排除目标一致，保证同一投影被独立复现。
    """
    targets = {
        Path(p).expanduser().resolve() for p in unlink_targets
    }
    arg_targets = sorted(str(t) for t in targets)
    recorded_targets = sorted(report.get("unlink_targets", []))
    if recorded_targets != arg_targets:
        failures.append(
            {
                "code": "unlink-targets-mismatch",
                "message": "核验的排除目标参数与导出证据不一致（%r != %r）"
                % (arg_targets, recorded_targets),
            }
        )
    for chapter in chapters:
        expected = []
        in_fence = False
        fence_char, fence_len = None, 0
        for line in chapter.projected_text.split("\n"):
            stripped = line.lstrip()
            if in_fence:
                if re.match(
                    r"^%s{%d,}\s*$" % (re.escape(fence_char), fence_len), stripped
                ):
                    in_fence = False
                continue
            fence_match = FENCE_OPEN_RE.match(stripped)
            if fence_match:
                in_fence = True
                fence_char = fence_match.group(1)[0]
                fence_len = len(fence_match.group(1))
                continue
            for match in re.finditer(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", line):
                href = match.group(2)
                path_part = href.split("#", 1)[0]
                if not path_part or re.match(r"^[a-z][a-z0-9+.-]*:", path_part, re.I):
                    continue
                if (chapter.dir / unquote(path_part)).resolve() in targets:
                    expected.append(href)
        context = {"input": str(chapter.path)}
        # Markdown 标签可能含行内格式（加粗等），与渲染后的链接文字不必逐字
        # 相同；href 在渲染层可能被百分号编码。对账按解码后的目标与出现次
        # 数，PDF 文字保留检查用导出层渲染文本。
        expected_hrefs = sorted(
            unquote(item.split("#", 1)[0]) for item in expected
        )
        recorded_hrefs = sorted(
            unquote(item["href"].split("#", 1)[0])
            for item in chapter.unlinked_links
        )
        if expected_hrefs != recorded_hrefs:
            failures.append(
                {
                    "code": "unlink-projection-mismatch",
                    "message": "排除目标链接的纯文本投影与独立扫描不一致（%r != %r）"
                    % (recorded_hrefs, expected_hrefs),
                    **context,
                }
            )
        if pdf is None:
            continue
        for item in chapter.unlinked_links:
            if normalize(item["text"]) not in pdf.norm_text:
                failures.append(
                    {
                        "code": "unlinked-text-missing",
                        "message": "转为纯文本的链接文字未保留在 PDF 中：%r"
                        % item["text"][:60],
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
    parser.add_argument(
        "--unlink-target",
        action="append",
        default=[],
        metavar="PATH",
        help="与导出一致的默认排除目标（如 术语表.md）",
    )
    parser.add_argument(
        "--images-display",
        action="append",
        default=[],
        metavar="PATH",
        help="与导出一致的显示尺寸映射 images_display.json",
    )
    parser.add_argument(
        "--toc-sections",
        action="store_true",
        help="与导出一致：印刷目录加入一级节",
    )
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

    chapters = reparse_inputs(
        args.inputs, failures, args.unlink_target, args.toc_sections
    )
    cross_check(chapters, failures)
    check_inputs_protection(report, failures)

    # 显示尺寸映射独立重建：绑定失败同样判 FAIL，并核对与导出参数一致。
    display_diagnostics = []
    bindings, display_map_paths = exporter.load_display_maps(
        chapters, list(args.images_display), display_diagnostics
    )
    for diagnostic in display_diagnostics:
        if diagnostic.get("severity") == "fail":
            failures.append(
                {
                    "code": diagnostic["code"],
                    "message": diagnostic["message"],
                    "input": diagnostic.get("input"),
                }
            )
    if sorted(report.get("images_display_maps", [])) != display_map_paths:
        failures.append(
            {
                "code": "images-display-maps-mismatch",
                "message": "核验使用的显示尺寸映射与导出证据不一致（%r != %r）"
                % (display_map_paths, report.get("images_display_maps", [])),
            }
        )

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

    check_projection(chapters, report, pdf, failures)
    check_unlinked_links(chapters, pdf, args.unlink_target, report, failures)

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
        check_image_widths(chapters, pdf, bounds, bindings, report, failures)
        check_print_toc(chapters, pdf, report, bounds, heading_pages, failures)

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
        "management_exclusions": [
            {"input": str(c.path), "exclusions": c.exclusions} for c in chapters
        ],
        "unlinked_links": [
            {"input": str(c.path), "links": c.unlinked_links} for c in chapters
        ],
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
