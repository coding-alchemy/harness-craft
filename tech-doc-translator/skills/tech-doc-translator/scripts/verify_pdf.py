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
from collections import Counter
from markdown_it import MarkdownIt
from uniseg.linebreak import line_break_boundaries

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_pdf as exporter  # noqa: E402  复用同一解析层，另有独立原始扫描交叉核对

# 与导出证据共用同一命名与状态口径（单一事实源）。
REPORT_NAME = exporter.REPORT_NAME
VERIFY_NAME = "verify_report.json"
STATUS_MACHINE_PASS = exporter.STATUS_MACHINE_PASS
STATUS_MACHINE_FAIL = exporter.STATUS_MACHINE_FAIL

# 代码几何核验必须与 assets/pdf/style.css 的实际打印策略一致。对应关系由
# test_pdf_integrity.py 的样式契约测试直接锁定，样式变更时必须同步审查这些
# 物理边界，不能让核验器继续使用过期的裸常量。
MM_TO_PT = 72 / 25.4
PDF_PAGE_MARGIN_VERTICAL_PT = 18 * MM_TO_PT
PDF_PAGE_MARGIN_HORIZONTAL_PT = 16 * MM_TO_PT
PDF_PRE_PADDING_VERTICAL_PT = 7.0
PDF_PRE_PADDING_HORIZONTAL_PT = 9.0
PDF_PRE_LINE_HEIGHT = 1.45


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
    """逐页解析内容流，返回每页按绘制顺序的 (绘制宽度 pt, 底边 y pt,
    顶边 y pt) 列表。

    图片 XObject 以单位正方形进入用户空间：当前 CTM 的 x 轴向量长度即
    绘制宽度，单位正方形四角变换后的最小/最大 y 即页内物理底/顶边
    （供分页占用与前导内容范围计算——页底排满图片时，剩余空间不能
    再按文本基线高估；图片随块移页时，其整幅高度参与前页空间核算）。
    矩阵语义独立于导出器；无法解析的页面返回空并让计数对账暴露差异。
    """
    result = []
    for page in pdf.reader.pages:
        images_drawn = []
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
                result.append(images_drawn)
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
                        width = (a * a + b * b) ** 0.5
                        corners_y = [
                            ctm[1] * x + ctm[3] * y + ctm[5]
                            for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))
                        ]
                        images_drawn.append(
                            (width, min(corners_y), max(corners_y)))
            result.append(images_drawn)
        except Exception:  # noqa: BLE001  内容流异常由计数对账暴露
            result.append([])
    return result


def check_image_coverage(chapters, bindings, undetermined_map,
                         undetermined_raw, report, require, failures):
    """从原 Markdown、映射与资源独立重算逐次覆盖，并与导出证据对账。

    真实图片出现由与导出相同的渲染级枚举重建（核验独立重读原输入建立
    章节对象后调用同一只读枚举；行内代码/缩进代码中的图片语法与未定义
    引用式图片不产生 <img>，不计出现）；分类口径与导出侧共用
    （_image_preflight）。未确定条目按与确定条目相同的出现序号与资源
    身份规则核对。导出报告的覆盖摘要与本地重算不一致、或严格策略下
    存在未恢复项，均判 FAIL。
    """
    from _image_preflight import (
        Occurrence,
        classify_occurrences,
        coverage_diagnostics,
        coverage_summary,
        undetermined_binding_diagnostics,
    )

    occurrences = []
    for chapter in chapters:
        enumeration = exporter.enumerate_images(chapter, [])
        for index, record in enumerate(enumeration):
            occurrences.append(
                Occurrence(
                    chapter=str(chapter.path), occurrence=index + 1,
                    ref=record["src"], path=record["path"],
                    sha256=record["sha256"], line=record["line"],
                    kind=record["kind"], pixel_size=record["pixel_size"],
                    frames=record["frames"],
                    pixel_known=record["pixel_known"],
                )
            )
        for diagnostic in undetermined_binding_diagnostics(
                str(chapter.path),
                (undetermined_raw or {}).get(chapter.path, []),
                enumeration):
            if diagnostic.get("severity") == "fail":
                failures.append(
                    {
                        "code": diagnostic["code"],
                        "message": diagnostic["message"],
                        "input": diagnostic.get("input"),
                    }
                )
    items = classify_occurrences(
        occurrences,
        {str(k): v for k, v in bindings.items()},
        {(str(k[0]), k[1]): v for k, v in undetermined_map.items()},
    )
    summary = coverage_summary(items)
    exported = report.get("image_coverage")
    if exported is not None and exported != summary:
        failures.append(
            {
                "code": "image-coverage-mismatch",
                "message": "覆盖分类与导出证据不一致：核验 %r vs 导出 %r"
                % (summary, exported),
            }
        )
    for diagnostic in coverage_diagnostics(items, require,
                                           "images-display-absent"):
        if diagnostic.get("severity") == "fail":
            failures.append(
                {
                    "code": diagnostic["code"],
                    "message": diagnostic["message"],
                    "input": diagnostic.get("input"),
                }
            )


def check_provenance(chapters, report, pdf, args_provenance, failures,
                     heading_pages=None):
    """独立重建出处预期并核对前置位置（R6/D6）。

    预期从原始输入重建（共享字段提取实现，不读导出器结论）；与导出证据
    核对政策、模式与逐章分类，再从最终 PDF 文本核对前置说明先于首章。
    章首四类管理字段的移除区间由既有投影核验独立对账。
    """
    exported = report.get("provenance")
    if not exported:
        failures.append(
            {
                "code": "provenance-evidence-missing",
                "message": "导出证据缺少出处记录；旧证据须重新导出核验",
            }
        )
        return
    policy = exported.get("policy", {}).get("fields")
    if policy != list(exporter.MANAGEMENT_FIELD_LABELS):
        failures.append(
            {
                "code": "provenance-policy-mismatch",
                "message": "出处字段政策与当前版本不一致：%r vs %r"
                % (policy, list(exporter.MANAGEMENT_FIELD_LABELS)),
            }
        )
    if (exported.get("mapping") or None) != (args_provenance or None):
        failures.append(
            {
                "code": "provenance-mapping-mismatch",
                "message": "出处区间映射参数与导出不一致（导出 %r / 核验 %r）"
                % (exported.get("mapping"), args_provenance),
            }
        )
        return
    try:
        provenance_map = exporter.load_provenance_map(
            args_provenance, chapters, [])
    except exporter.ExportError as exc:
        failures.append({"code": "provenance-mapping-invalid",
                         "message": str(exc)})
        return
    toc_chapter = next((c for c in chapters if c.is_toc), None)
    facts = exporter.collect_provenance(chapters, toc_chapter, provenance_map)
    if facts["incomplete"]:
        failures.append(
            {
                "code": "provenance-incomplete",
                "message": "以下章节只有无法定位具体原文的来源：%s"
                % facts["incomplete"],
            }
        )
    if facts["unavailable"]:
        failures.append(
            {
                "code": "provenance-unavailable",
                "message": "以下章节完全缺少出处信息：%s"
                % facts["unavailable"],
            }
        )
    for key in ("mode", "complete", "incomplete", "unavailable"):
        if exported.get(key) != facts[key]:
            failures.append(
                {
                    "code": "provenance-evidence-mismatch",
                    "message": "出处 %s 与导出证据不一致：核验 %r vs 导出 %r"
                    % (key, facts[key], exported.get(key)),
                }
            )
    if pdf is None:
        return
    # 无渲染前置区时，被采用的集中出处段（生成前置、目录“译自…”段或
    # 映射区间段，由 collect_provenance 以实际可见文字给出）同样必须先于
    # 首章标题：位置保证不能只靠装载规则或文件名顺序，须在成品中实测。
    adopted = (facts.get("adopted_front") or "").strip()
    if not adopted:
        return
    # 前置说明先于首章：前置文本所在页不晚于首章标题目的地页；同页时
    # 文本位置必须先于章首标题。首章页取自大纲目的地（heading_pages），
    # 不被目录页中的同名条目干扰。
    compact_pages = [re.sub(r"\s+", "", page) for page in pdf.pages]
    first_content = next((c for c in chapters if not c.is_toc), None)
    if first_content is None or not first_content.headings:
        return
    heading = first_content.headings[0]
    heading_page = (heading_pages or {}).get(heading["id"])
    first_line = next(
        (line for line in adopted.split("\n") if line.strip()),
        None)
    if first_line is None:
        return
    token = re.sub(r"\s+", "", first_line)
    token = token[: max(12, min(len(token), 30))]
    front_page = next(
        (i for i, text in enumerate(compact_pages) if token in text), None)
    if front_page is None:
        failures.append(
            {
                "code": "provenance-front-missing",
                "message": "前置出处说明未出现在最终 PDF：%r" % first_line[:40],
            }
        )
        return
    if heading_page is None:
        return
    if front_page > heading_page:
        failures.append(
            {
                "code": "provenance-position",
                "message": "前置出处说明（第 %d 页）晚于首章标题"
                "（第 %d 页）" % (front_page + 1, heading_page + 1),
            }
        )
    elif front_page == heading_page:
        heading_token = re.sub(r"\s+", "", heading["text"])
        heading_token = heading_token[: max(12, min(len(heading_token), 30))]
        if compact_pages[front_page].find(token) > \
                compact_pages[front_page].find(heading_token):
            failures.append(
                {
                    "code": "provenance-position",
                    "message": "同页时前置出处说明未先于首章标题",
                }
            )


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
            for width, _bottom, _top in drawn_per_page[index]
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

# 字段政策单源：与导出器共用同一政策对象（设计 4.6），核验不自带集合。
AUTHORIZED_LABELS = exporter.MANAGEMENT_FIELD_LABELS
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
        # 统一绘制事实（设计 §4.9）：一份物理坐标事件（绘制序、原文、
        # 字体、经变换的页内坐标），一次收集供代码归属、折行与分页检查
        # 共同消费。原始 tm 只在提取层用于定位 MCID 标记（mcid_marks），
        # 结构容器候选也在此关联；不再有第二套 run 采集。
        self.drawn_events = _collect_text_run_geometry(self)
        self.line_buckets = build_line_buckets(self.drawn_events)
        self.mcid_marks = _walk_content_stream_positions(self.reader)
        self.structure_containers = (
            _walk_structure_containers(self.reader)
            if self.mcid_marks is not None else None)

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
    """kind: text；在章区间内做严格单调的顺序包含检查。

    匹配位置只前进不回退：后一块不能复用前一块已消费的文本，因此源文中
    重复的块在 PDF 中缺一份时必然 FAIL。文本块按公式边界分段（KaTeX 的
    MathML 文本会插入句子中间），连续匹配失败时用"自当前位置起的有界窗口
    有序子序列"作已解释差异（字符全齐且顺序一致），不再回退章首。
    代码块核验见 check_code_blocks_per_line（结构树容器归属）。
    """
    assert kind == "text"
    for chapter, start_page, end_page in bounds:
        start_offset = pdf.page_offsets[start_page][0]
        end_offset = pdf.page_offsets[end_page - 1][1]
        position = start_offset
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


def logical_lines_of(code):
    """逻辑行列表：统一换行符，末尾单个终止换行不增行，空行计入。"""
    text = code.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return text.split("\n")


# ---------------------------------------------------------------------------
# 结构树归属：从 tagged PDF 的结构树与内容流标记内容收集代码容器
# ---------------------------------------------------------------------------


def _walk_content_stream_positions(reader):
    """逐页解析内容流，返回 {page: {mcid: [(seq, x, y), ...]}}。

    只跟踪文本行矩阵的 y（Tm.f）与 x（Tm.e）：Chromium 为每个绘制串显式
    设置绝对 Tm，y 不受字形宽度影响；Td/TD/T* 按 PDF 规范推进行矩阵。
    解析失败返回 None；缺少归属证据的源代码块由调用方列为待复核。
    """
    from pypdf.generic import ContentStream

    def matmul(m1, m2):
        return [
            [sum(m1[i][k] * m2[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)
        ]

    result = {}
    for page_index, page in enumerate(reader.pages):
        try:
            contents = ContentStream(page.get_contents(), reader)
        except Exception:  # noqa: BLE001  单页解析失败按无标记处理
            result[page_index] = {}
            continue
        tlm = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        tm = [row[:] for row in tlm]
        leading = 0.0
        current_mcid = None
        seq = 0
        ops = {}
        for operands, operator in contents.operations:
            if operator == b"Tm":
                a, b_, c, d, e, f = (float(v) for v in operands)
                tm = [[a, b_, 0], [c, d, 0], [e, f, 1]]
                tlm = [row[:] for row in tm]
            elif operator in (b"Td", b"TD"):
                tx, ty = float(operands[0]), float(operands[1])
                if operator == b"TD":
                    leading = -ty
                tlm = matmul(tlm, [[1, 0, 0], [0, 1, 0], [tx, ty, 1]])
                tm = [row[:] for row in tlm]
            elif operator == b"T*":
                tlm = matmul(tlm, [[1, 0, 0], [0, 1, 0], [0, -leading, 1]])
                tm = [row[:] for row in tlm]
            elif operator == b"BDC":
                props = operands[1] if len(operands) > 1 else {}
                if isinstance(props, dict) and "/MCID" in props:
                    try:
                        current_mcid = int(props["/MCID"])
                    except (TypeError, ValueError):
                        current_mcid = None
            elif operator == b"EMC":
                current_mcid = None
            elif operator in (b"Tj", b"'", b'"', b"TJ"):
                if current_mcid is not None:
                    ops.setdefault(current_mcid, []).append(
                        (seq, tm[2][0], tm[2][1]))
                    seq += 1
        result[page_index] = ops
    return result


def _walk_structure_containers(reader):
    """前序遍历结构树，返回 [(order, subtype, [(page, mcid), ...])]。

    每个含 MCID 后代的元素都是候选容器（文档顺序 = 前序序号）；消费时
    按 MCID 去重，嵌套容器在子容器被消费后自然跳过。无法解析返回 None。
    """
    from pypdf.generic import IndirectObject, DictionaryObject

    def resolve(node):
        if isinstance(node, IndirectObject):
            try:
                return node.get_object()
            except Exception:  # noqa: BLE001
                return None
        return node

    page_index_cache = {}

    def page_index_of(ref):
        ref = resolve(ref)
        if not isinstance(ref, DictionaryObject):
            return None
        try:
            target = ref.indirect_reference
            if target not in page_index_cache:
                page_index_cache[target] = None
                for index, page in enumerate(reader.pages):
                    if page.indirect_reference == target:
                        page_index_cache[target] = index
                        break
            return page_index_cache[target]
        except Exception:  # noqa: BLE001
            return None

    containers = []

    def kids_of(element):
        k = element.get("/K")
        if k is None:
            return []
        if isinstance(k, IndirectObject):
            return [k]
        if isinstance(k, list):
            return k
        return [k]

    def walk(node, order_box, inherited_page):
        node = resolve(node)
        if isinstance(node, int):
            if inherited_page is not None:
                return [(inherited_page, int(node))]
            return []
        if not isinstance(node, DictionaryObject):
            return []
        subtype = str(node.get("/S") or "")
        own_page = page_index_of(node.get("/Pg"))
        page = own_page if own_page is not None else inherited_page
        mcids = []
        for child in kids_of(node):
            mcids.extend(walk(child, order_box, page))
        if subtype and mcids:
            containers.append((order_box[0], subtype, mcids))
            order_box[0] += 1
        return mcids

    try:
        root_ref = reader.trailer["/Root"].get("/StructTreeRoot")
        if root_ref is None:
            return None
        root = resolve(root_ref)
        if not isinstance(root, DictionaryObject):
            return None
        order_box = [0]
        for child in kids_of(root):
            walk(child, order_box, None)
        return containers
    except Exception:  # noqa: BLE001  结构树不可用时，由调用方记录缺失的归属证据
        return None


def _make_bucket_lookup(buckets_by_page):
    """按页和基线查找最近的行桶，保留 1.5pt 容差及同距选择顺序。"""
    by_page = {}
    for page, y, bucket in buckets_by_page:
        by_page.setdefault(page, []).append((y, bucket))
    for rows in by_page.values():
        rows.sort(key=lambda item: item[0])

    def bucket_at(page, y):
        rows = by_page.get(page)
        if not rows:
            return None
        best = None
        best_dist = 1.5
        for row_y, bucket in rows:
            dist = abs(row_y - y)
            if dist <= best_dist:
                best = bucket
                best_dist = dist
        return best

    return bucket_at


def _chapter_containers(containers, marks, buckets_by_page, start_page,
                        end_page):
    """把候选容器解析为有序代码行序列（结构路径 + 桶文本 + 坐标）。

    返回容器列表，元素为 {"lines": [{"page","y","text","bucket"}]}。
    容器中出现无法对应到任何桶的非空绘制内容时，该容器判为不可用。
    """
    bucket_at = _make_bucket_lookup(buckets_by_page)

    sequence = []
    seen_line_sets = set()
    for _order, _subtype, mcids in containers:
        pages = {page for page, _mcid in mcids
                 if start_page <= page < end_page}
        if not pages:
            continue
        lines = []
        seen = set()
        usable = True
        for page, mcid in mcids:
            if not (start_page <= page < end_page):
                continue
            for seq, x, y in marks.get(page, {}).get(mcid, []):
                key = (page, round(y, 1))
                if key in seen:
                    continue
                bucket = bucket_at(page, y)
                if bucket is None:
                    usable = False
                    break
                seen.add(key)
                lines.append({"page": page, "y": y,
                              "text": bucket["text"], "bucket": bucket})
        if not usable:
            # 结构行无法全部解码：排除该候选；调用方继续处理可用候选，
            # 缺少归属证据的源代码块不得自动判为完整。
            continue
        if not lines:
            continue
        # 嵌套包装（Div 与逐 MCID 的 NonStruct 包裹）会映射到同一组绘制
        # 行：按行集合去重，只保留前序最先（最外层）的一个，避免同一行
        # 被多次对账。
        line_set = frozenset(id(line["bucket"]) for line in lines)
        if line_set in seen_line_sets:
            continue
        seen_line_sets.add(line_set)
        sequence.append({"lines": lines})
    return sequence


def _align_code_fragment(needle, pos, text, phantom=None, tabs=None,
                         allow_tail_shortfall=False):
    """把一个视觉行 text 与源行 needle 的 pos 起对齐，返回新位置或 None。

    非空白字符必须逐字按码位相等（改字/插字必拒；不做 NFKC 归一——
    全角Ａ被渲染成半角 A 属字符替换，必须拒）。needle 中的空白被删除
    （`printf("a  b")` → `printf("a b")` / `printf("ab")`）必拒：空白
    run 按个数严格对账，绝不做删除空白后的通用 normalize 比较。例外：
    - 制表位：源 `\\t` 的渲染展开宽度由排版决定，只要求绘制了空白，
      宽度差异计入 tabs（交视觉复核）；
    - 视觉行在源空白 run 中间折行、行尾空白未被绘制（仅当短fall发生在
      本视觉行末尾时，由调用方以 allow_tail_shortfall 按折行点处理）；
    - text 中 needle 没有的空白按“混合字体边界 phantom 空白”宽容并
      计入 phantom（插入方向与边界空白不可区分，交视觉复核）。
    """
    i = pos
    j = 0
    while j < len(text):
        ch = text[j]
        if ch.isspace():
            if i < len(needle) and needle[i].isspace():
                ks = i
                while i < len(needle) and needle[i].isspace():
                    i += 1
                n_run = needle[ks:i]
                js = j
                while j < len(text) and text[j].isspace():
                    j += 1
                t_run = j - js
                if "\t" in n_run:
                    # 制表位展开：只要求绘制了空白，宽度差异交视觉复核
                    if t_run < 1:
                        return None
                    if tabs is not None and t_run != len(n_run):
                        tabs[0] += 1
                elif t_run < len(n_run):
                    # 源空白被删短：仅当本视觉行在源空白 run 处结束
                    # （折行点、行尾空白未绘制）时允许按折行处理；行中
                    # 删短（j 之后仍有本行内容）必拒。
                    if not (allow_tail_shortfall and j >= len(text)):
                        return None
                elif t_run > len(n_run) and phantom is not None:
                    phantom[0] += t_run - len(n_run)
            else:
                js = j
                while j < len(text) and text[j].isspace():
                    j += 1
                # text 多出的空白：字体边界 phantom 空白
                if phantom is not None:
                    phantom[0] += j - js
        else:
            if i >= len(needle) or needle[i] != ch:
                return None
            i += 1
            j += 1
    return i


def _visual_text(item):
    if isinstance(item, dict):
        return str(item.get("text", ""))
    return str(item)


def _page_boundary_wrap(current_bucket, following_bucket):
    """两个视觉行是否由实际 PDF 页底/页首位置证明跨页续排。

    Chromium 的文本矩阵 y 在整份打印文档中累计，所以收集阶段已
    换算为每页 PDF 物理坐标。只接受相邻页，且前行已无法在 18mm
    下边距 + pre 内边距内再排一整行、后行确实从下页对应顶部
    续排。缺少任一几何事实时保守返回 False。
    """
    page = current_bucket.get("page")
    next_page = following_bucket.get("page")
    if not (isinstance(page, int) and isinstance(next_page, int)
            and next_page == page + 1):
        return False
    values = (
        current_bucket.get("baseline_y_pt"),
        current_bucket.get("page_bottom_pt"),
        current_bucket.get("line_height_pt"),
        following_bucket.get("baseline_y_pt"),
        following_bucket.get("page_top_pt"),
        following_bucket.get("line_height_pt"),
    )
    if not all(isinstance(value, (int, float)) for value in values):
        return False
    current_y, current_bottom, current_height, next_y, next_top, next_height = values
    usable_bottom = (current_bottom + PDF_PAGE_MARGIN_VERTICAL_PT
                     + PDF_PRE_PADDING_VERTICAL_PT)
    usable_top = (next_top - PDF_PAGE_MARGIN_VERTICAL_PT
                  - PDF_PRE_PADDING_VERTICAL_PT)
    tolerance_pt = 0.75
    at_bottom = current_y - current_height <= usable_bottom + tolerance_pt
    at_top = next_y + next_height >= usable_top - tolerance_pt
    return at_bottom and at_top


def _visual_wrap_boundary(visual_lines, current_index, needle=None,
                          next_source_pos=None, row_start_pos=None):
    """当前视觉行继续到下一行时，是否有真实排版边界证据。

    只接受两类可观测原因：下一行已进入新页，或当前行的实际
    字形右缘到达代码版心右界。纯字符列表没有几何信息，按无证据
    处理，不把“提取行结束”本身当作折行。
    """
    if current_index < 0 or current_index + 1 >= len(visual_lines):
        return False
    current = visual_lines[current_index]
    following = visual_lines[current_index + 1]
    if not isinstance(current, dict) or not isinstance(following, dict):
        return False
    current_bucket = current.get("bucket", current)
    following_bucket = following.get("bucket", following)
    page = current_bucket.get("page")
    next_page = following_bucket.get("page")
    if page is not None and next_page is not None and next_page != page:
        return _page_boundary_wrap(current_bucket, following_bucket)
    if current_bucket.get("wrap_at_right"):
        return True
    right = current_bucket.get("right_pt")
    limit = current_bucket.get("code_right_pt")
    advance = current_bucket.get("mono_advance_pt")
    if not all(isinstance(value, (int, float))
               for value in (right, limit, advance)):
        return False
    remaining = max(0.0, limit - right)
    # 使用 Unicode UAX #14 的软断点，而非逐个追加标点白名单。
    # pre-wrap 会把剩余宽度放不下的下一不可拆片段移到下一行；
    # 无软断点的长 token 只能由真实右界（或页界）证明折行。
    if needle is None or next_source_pos is None:
        return False
    pos = next_source_pos
    while pos < len(needle) and needle[pos].isspace():
        pos += 1
    boundaries = tuple(line_break_boundaries(needle))
    start = current_bucket.get("start_pt")
    line_capacity = limit - start \
        if isinstance(start, (int, float)) else None
    filled = remaining <= 2 * advance

    def _unit_justified(width):
        if width <= remaining - advance:
            return False
        if line_capacity is not None and width > line_capacity \
                and not filled:
            return False
        return True

    if pos not in boundaries:
        # pos 位于不可拆片段内部：Chromium 在片段整体放不进剩余
        # 空间时会在片段内部强制断行（长模板实参行真实样例复现）。
        # 以 pos 之前最近的软断点与之后最近的软断点界定整个片段；
        # 片段整体明显放不进剩余空间时，片段内断行有排版依据。
        prev = next((b for b in reversed(boundaries) if b <= pos), 0)
        end = next((b for b in boundaries if b > prev), len(needle))
        fragment = needle[prev:end].strip()
        if not fragment:
            return False
        # 防提前断行篡改：人为在片段开头断行时，本行只绘制片段的
        # 一小部分（首行距右界很远）；Chromium 的片段内强制断行只
        # 在片段已按剩余空间尽量排满时发生，已绘制部分应过半。
        # 该形态只在片段覆盖整行起点时成立：行中段开始的片段受行
        # 容量限制，已绘制比例天然可能不足一半（长标识符初始化列表
        # 行真实样例：片段自行内中途起始，行满后 Chromium 把下一
        # 子片段整段下移，real-sample 04 章 #108 复现）。
        if (pos - prev) * 2 < end - prev:
            if row_start_pos is None or prev <= row_start_pos:
                return False
        # 放行依据：断点之后的下一排版单元放不进剩余空间。排版单元按
        # 两种口径取最贴近 Chromium 行为的证据，任一足以证明放不下：
        # 1) pos 到其后最近 UAX 软断点（即所在不可拆片段的未绘制部分；
        #    注释等无空格 token 在 UAX 中仍可能被拆出紧邻单字符断点，
        #    口径偏松）；
        # 2) pos 到其后最近空白的最长非空 run（Blink 以空格为折行
        #    单元，real-sample 04 章 #108 的 /*remainder*/ 注释复现：
        #    UAX 片段 'nullptr ' 宽度足够，注释 run 超出剩余空间）。
        # 不得使用整个包含已绘制前缀的片段宽度作为单元：right 已计入
        # 前缀的占位，合法片段内断行恒有“未绘制部分 > 剩余空间”，整段
        # 宽度只会把前缀重复计数，接受“未绘制尾部本放得下”的人为提前
        # 断行（60 字符单行被拆为 40+20、剩余 281.22pt 而尾部仅
        # 102.32pt 的损伤复现）。
        # 统一不变量：单元宽度超过整行容量（超长词）时，Chromium 只能
        # 把行填到满才在词内断行；此时行尾必须贴近右界。人为提前断行
        # 的行尾远离右界，不满足“已填满”，必须拒绝（五轮复审
        # test_soft_boundary_still_requires_insufficient_space 形态）。
        next_end = next((b for b in boundaries if b > pos), len(needle))
        run_end = pos
        while run_end < len(needle) and not needle[run_end].isspace():
            run_end += 1
        return (_unit_justified((next_end - pos) * advance)
                or _unit_justified((run_end - pos) * advance))
    # 断点之后到下一个软断点的片段是“下一不可拆片段”；其后再无断点时，
    # 行尾剩余整体即该片段（长 token 收尾不能被当成没有片段）。
    end = next((boundary for boundary in boundaries if boundary > pos),
               len(needle))
    # 尾部空白本身不要求把前面的片段整体移行。
    while end > pos and needle[end - 1].isspace():
        end -= 1
    if end <= pos:
        return False
    # 片段宽度按等宽 advance 估算，跨长片段有逐字累积误差；片段与剩余
    # 空间在一个字形以内时分不清真实排版是否放得下，按“放不下”（折行
    # 有依据）处理，只有明显放得下才判折行无依据。
    # UAX 可能在相邻符号间给出单字符“片段”（如 '++' 之间的断点），
    # 与 Blink 的空格分隔折行单元不一致；pos 之后到最近空白的非空
    # run 同样作为放不下的证据（real-sample 04 章 #156 复现：UAX 下
    # 一片段为单字符 '+'，而实际下移单元 '++compute_batch,' 超剩余）。
    # run 超过整行容量（超长词）时要求行已填满，与片段内断行分支的
    # 不变量一致：超长词只能在行满时在词内断行，人为提前断行的行尾
    # 远离右界，不满足“已填满”必须拒绝（test_soft_boundary_still_
    # requires_insufficient_space 复现：'short—' 行尾剩余 449pt，
    # 无空格 run 为整行剩余 96 字符，超过行容量却未填满）。
    frag_ok = _unit_justified((end - pos) * advance)
    run_end = pos
    while run_end < len(needle) and not needle[run_end].isspace():
        run_end += 1
    return frag_ok or _unit_justified((run_end - pos) * advance)


def _indent_columns(prefix):
    """前导空白的等宽列宽：制表符按 8 列制表位对齐到下一制表位。

    与渲染口径一致：`\t` 与 ` \t`（空格后接制表符）都起于第 8 列；
    缩进几何比对与行首 x 复验共用这一换算，不按固定 8 空格折算。
    """
    columns = 0
    for char in prefix:
        if char == "\t":
            columns += 8 - (columns % 8)
        else:
            columns += 1
    return columns


def _geometry_backed_indent_skip(needle, visual_item, tabs):
    """前导空白未编入提取文本时，用实际行首 x 核对缩进。

    Chromium 常将行首空格/tab 体现为文本起点偏移，而不在
    extract_text 中返回空白字符。此时以版心左界、实际等宽
    advance 和 8 列 tab stop 计算应有起点；缺几何或位置不符
    即拒绝，不以 lstrip 放宽。返回已由几何消费的源字符位置。
    """
    indent_end = 0
    while indent_end < len(needle) and needle[indent_end].isspace():
        indent_end += 1
    if indent_end == 0:
        return 0
    text = _visual_text(visual_item)
    if text and text[0].isspace():
        return 0  # 空白已在 token 中，由 _align_code_fragment 严格对账
    if not isinstance(visual_item, dict):
        return None
    bucket = visual_item.get("bucket", visual_item)
    values = (bucket.get("start_pt"), bucket.get("code_left_pt"),
              bucket.get("mono_advance_pt"))
    if not all(isinstance(value, (int, float)) for value in values):
        return None
    start_pt, code_left_pt, advance_pt = values
    prefix = needle[:indent_end]
    columns = _indent_columns(prefix)
    tab_count = prefix.count("\t")
    expected = code_left_pt + columns * advance_pt
    tolerance = max(0.75, advance_pt * 0.2)
    if abs(start_pt - expected) > tolerance:
        return None
    tabs[0] += tab_count
    return indent_end


def _consume_block_tokens(visual_lines, logical_lines):
    """块内完整对账（R8/4.9）：每个视觉行必须被某逻辑行消费，反之亦然。

    源逻辑行与容器视觉行按字符对齐（见 _align_code_fragment）：非空白逐
    字按码位相等，空白 run 按个数严格对账（删短必拒；制表位展开与折行
    点行尾未绘制空白除外，分别计入 tabs/重试）；折行不视为损伤；块尾
    剩余的非空视觉行（如块尾插入的非等宽回退文字行）判为插入损伤。
    返回 (line_starts, used_visual_count, phantom, tabs) 或 None。
    """
    vi = 0
    line_starts = []
    phantom = [0]
    tabs = [0]
    for line in logical_lines:
        # 前导空格/tab 也是代码内容：不做 lstrip，否则单行或
        # 全块同缩进被删时没有相对 x 参照行，会被静默放行。
        # 不做 NFKC：码位替换（全角→半角）必拒。
        needle = line
        if not needle.strip():
            continue  # 空逻辑行：无可绘制字符，不产生视觉行
        # 纯空白视觉行（缩进空行、Chromium 可能绘制尾随空白 run）不携带
        # token，跳过并对齐到下一行；空白保真由逐块的空白复核项覆盖。
        while vi < len(visual_lines) and not _visual_text(visual_lines[vi]).strip():
            vi += 1
        line_starts.append(vi)
        if vi >= len(visual_lines):
            return None
        i = _geometry_backed_indent_skip(needle, visual_lines[vi], tabs)
        if i is None:
            return None
        # 每个视觉行起始的源位置：片段内断行的防篡改形态判定需要
        # 知道当前行是否从片段起点开始绘制。
        row_starts = {vi: i}
        while i < len(needle):
            if vi >= len(visual_lines):
                return None
            text = _visual_text(visual_lines[vi])
            hard_wrap_boundary = _visual_wrap_boundary(visual_lines, vi)
            nxt = _align_code_fragment(needle, i, text,
                                       phantom, tabs)
            if nxt is None:
                # 空白 run 短缺只有在本行真实到达版心右界或页界
                # 时才能解释为视觉折行；任意提取行尾不再触发宽容。
                if hard_wrap_boundary:
                    nxt = _align_code_fragment(
                        needle, i, text, phantom, tabs,
                        allow_tail_shortfall=True)
            if nxt is None or nxt == i:
                return None
            i = nxt
            vi += 1
            if i < len(needle):
                # 同一源逻辑行继续到下一视觉行，无论分隔点是
                # 空白还是普通字符，都必须有右界/页界几何证据。
                if not _visual_wrap_boundary(
                        visual_lines, vi - 1, needle, i,
                        row_starts.get(vi - 1)):
                    return None
                while i < len(needle) and needle[i].isspace():
                    i += 1
                row_starts[vi] = i
        if needle[i:].strip():
            return None
    # 块尾剩余的可视内容 = 插入损伤（如块尾插入非等宽回退文字行）
    if any(_visual_text(item).strip() for item in visual_lines[vi:]):
        return None
    return line_starts, vi, phantom[0], tabs[0]


def _with_orphan_code_rows(container_seq, buckets, buckets_by_page, marks,
                           all_containers, start_page, end_page):
    """把结构树未认领的纯等宽行按页内视觉连续性补全为孤立代码容器。

    Chromium 打印输出的已知缺口：跨页代码块第二页起的分片文本不绑定
    到任何结构树元素（MCID 无所属容器），/Div 候选序列因此缺失这些
    行，跨页长块永远无法完整消费（真实六章样例 91 块复现）。这里只做
    提取补全：结构树任一元素（含 /P、/TD 等非代码容器）都未认领、且
    整行等宽的行桶按同页基线连续性成组，按 (页, 视觉自上而下) 插入
    序列。对账仍由结构归属路径逐 token 严格完成——补全的行同样受
    插入/删字/改字/乱序与块尾清扫约束，未被任何源块消费的孤立等宽
    内容仍按未归属代码拒绝，不放宽任何检查。
    """
    bucket_at = _make_bucket_lookup(buckets_by_page)

    claimed = {id(line["bucket"])
               for container in container_seq for line in container["lines"]}
    owner_mcids = {(page, mcid)
                   for _order, _subtype, mcids in all_containers
                   for page, mcid in mcids
                   if start_page <= page < end_page}
    for page, mcid in owner_mcids:
        for _seq, _x, y in marks.get(page, {}).get(mcid, []):
            bucket = bucket_at(page, y)
            if bucket is not None:
                claimed.add(id(bucket))

    groups = []
    current = None
    last = None
    for bucket in buckets:  # 列表序 = 页序 + 页内视觉自上而下
        # 纯空白行（如 pre 内空白 run 的独立绘制段）无可对账 token，
        # 消费端按空白视觉行跳过，不构成结构缺失，不参与孤立组。
        orphan = (start_page <= bucket["page"] < end_page
                  and id(bucket) not in claimed
                  and bucket.get("all_mono")
                  and bucket["text"].strip())
        contiguous = (
            orphan and current is not None
            and bucket["page"] == last["page"]
            and 0 < last["baseline_y_pt"] - bucket["baseline_y_pt"] <= 30.0)
        if contiguous:
            current.append(bucket)
        elif orphan:
            current = [bucket]
            groups.append(current)
        else:
            current = None
        if orphan:
            last = bucket

    def position(bucket):
        return (bucket["page"], -bucket["baseline_y_pt"])

    merged = list(container_seq)
    for group in groups:
        group_position = position(group[0])
        index = len(merged)
        for i, container in enumerate(merged):
            first = min(position(line["bucket"])
                        for line in container["lines"])
            if first > group_position:
                index = i
                break
        merged.insert(index, {
            "structure_orphan": True,
            "lines": [{"page": bucket["page"], "y": bucket.get("y"),
                       "x": bucket.get("x"), "text": bucket["text"],
                       "bucket": bucket} for bucket in group],
        })
    return merged


def _match_chapter_blocks_structural(containers, chapter, failures, relaxed):
    """结构归属：源块与容器按序单调消费，逐块完整对账。

    每个源代码块必须独占一组实际绘制片段（结构容器行），顺序单调、
    一一消费；容器行内出现源块没有的内容（插入、删字、改字、乱序）或
    源行没有对应绘制内容（遗漏）都判 code-line-missing。归属不明的候选
    不会自动判完整。返回逐块位置信息列表。
    """
    infos = []
    cursor_ci = 0
    cursor_off = 0

    def advance(ci, off, used):
        """从 (ci, off) 消费 used 个视觉行，返回新 (ci, off)。"""
        while used > 0:
            avail = len(containers[ci]["lines"]) - off
            if used < avail:
                return ci, off + used
            used -= avail
            ci += 1
            off = 0
        return ci, off

    consumed = set()

    for block_no, item in enumerate(chapter.code_blocks, start=1):
        lines = logical_lines_of(item)
        info = {"first_page": None, "last_page": None,
                "long": len(lines) > exporter.CODE_BLOCK_MAX_LINES}
        infos.append(info)

        def group_slice(first_ci, first_off, last_ci):
            rows = []
            for part_ci in range(first_ci, last_ci + 1):
                part_lines = containers[part_ci]["lines"]
                if part_ci == first_ci:
                    part_lines = part_lines[first_off:]
                rows.extend(part_lines)
            return rows

        matched = None
        # 快路径：首行不对齐的容器不可能匹配（对账严格顺序），跳过以免
        # 在正文容器上反复全量尝试。
        first_needle = None
        for line in lines:
            # 快路只定位候选容器；Chromium 可能不把前导空白
            # 编入文本。完整缩进由 _consume_block_tokens 的行首
            # 物理 x + token 双证据复验，不在快路宣告通过。
            candidate = line.lstrip()
            if candidate.strip():
                first_needle = candidate
                break
        if first_needle is None:
            # 源块仅含空行/空白（无可绘制 token）：不消费视觉行即属完整
            # 对账，记一条空白复核项，避免对空块报缺失。
            matched = (cursor_ci, cursor_off, cursor_ci, [], 0, 0, 0)
        for start_ci in range(cursor_ci, len(containers)):
            if matched is not None:
                break
            start_off = cursor_off if start_ci == cursor_ci else 0
            first_lines = containers[start_ci]["lines"][start_off:]
            if first_needle is None or not first_lines:
                continue
            probe_text = next((row["text"] for row in first_lines
                               if row["text"].strip()), None)
            if probe_text is None:
                continue
            if _align_code_fragment(first_needle, 0, probe_text) is None:
                # 首行在版心右界折行时，行尾空白 run 可能整体移到
                # 下行（对账循环内的短缺重试口径），与
                # _consume_block_tokens 一致允许尾部短缺后再跳过；
                # 短缺重试仍需折行几何证据，不放宽对账。
                if not _visual_wrap_boundary(first_lines, 0) or \
                        _align_code_fragment(
                            first_needle, 0, probe_text,
                            allow_tail_shortfall=True) is None:
                    continue
            ci = start_ci
            while ci < len(containers):
                group_flat = group_slice(start_ci, start_off, ci)
                result = _consume_block_tokens(group_flat, lines)
                if result is not None:
                    matched = (start_ci, start_off, ci,
                               result[0], result[1], result[2], result[3])
                    break
                ci += 1
            if matched:
                break
        if matched is None:
            # 归属失败仍判 FAIL（tamper-safe），同时记录候选区域与尝试范围
            # 作为复核证据（4.9：定位歧义记录候选页和区域进入待复核流程）。
            tail_lines = []
            for probe_ci in range(cursor_ci, min(cursor_ci + 5,
                                                 len(containers))):
                tail_lines.extend(row["text"]
                                  for row in containers[probe_ci]["lines"])
            relaxed.append(
                {
                    "segment": "代码块 #%d 归属失败候选区域：%r"
                               % (block_no, " / ".join(
                                   t for t in tail_lines if t.strip())[:80]),
                    "reason": "结构容器无法完整对账，候选内容需人工核对",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
            failures.append(
                {"code": "code-line-missing", "input": str(chapter.path),
                 "message": "代码块 #%d 未能按结构归属并完整对账"
                            "（内容缺失、插入、改字或乱序）" % block_no})
            continue
        start_ci, start_off, end_ci, line_starts, used, phantom, tabs = matched
        if phantom:
            relaxed.append(
                {
                    "segment": "代码块 #%d 混合字体边界空白（%d 处）"
                               % (block_no, phantom),
                    "reason": "CJK/等宽字体切换处的绘制边界空白，精确空白"
                              "保真需视觉复核",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
        if tabs:
            relaxed.append(
                {
                    "segment": "代码块 #%d 制表位展开宽度（%d 处）"
                               % (block_no, tabs),
                    "reason": "制表位渲染展开宽度由排版决定，精确宽度保真"
                              "需视觉复核",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
        if used == 0:
            relaxed.append(
                {
                    "segment": "代码块 #%d 仅含空行/空白（无可绘制内容）"
                               % block_no,
                    "reason": "空白块无 token 可对账，空行保真需视觉复核",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
        # 零消费空块（无可绘制 token）只保留上面的空白复核项：不借用
        # 后续容器的绘制区域充当自身几何，也避免章末空块在容器已耗尽
        # 时越界访问（游标已指到末尾容器之后）。
        flat = group_slice(start_ci, start_off, end_ci) if used else []
        # 分页几何取首个/末个有绘制内容的行：容器序首可能是纯空白
        # 视觉行（空白 run 独立绘制段），其坐标不参与行高/位置估计。
        drawable = [row for row in flat if _visual_text(row).strip()]
        if drawable:
            info["first_page"] = drawable[0]["page"]
            info["last_page"] = drawable[-1]["page"]
            info["first_baseline_pt"] = \
                drawable[0]["bucket"]["baseline_y_pt"]
        if len(drawable) >= 2 and \
                drawable[0]["page"] == drawable[1]["page"]:
            # 行高取该块自身前两个视觉行的物理基线差（分页检查消费，
            # 不按源码字符重新定位行）
            pitch = (drawable[0]["bucket"]["baseline_y_pt"]
                     - drawable[1]["bucket"]["baseline_y_pt"])
            if pitch > 0:
                info["line_height_pt"] = pitch
        line_first = []
        # 逐逻辑行映射到视觉行，记录缩进几何（物理行首）与归属证据
        logical_nonempty = [l for l in lines if l.lstrip().strip()]
        for line_index, start_vi in enumerate(line_starts):
            source = logical_nonempty[line_index]
            # 与 _geometry_backed_indent_skip 同一制表位口径：混合
            # tab/空格缩进按制表位列宽比较，不按固定 8 空格折算。
            indent_width = _indent_columns(
                source[:len(source) - len(source.lstrip())])
            line_first.append(
                (indent_width,
                 flat[start_vi]["bucket"].get(
                     "first_char_pt", flat[start_vi]["bucket"]["start_pt"])))
            relaxed.append(
                {
                    "segment": "代码块 #%d 第 %d 行归属结构行（第 %d 页，"
                               "起点 %.1fpt）" % (block_no, line_index + 1,
                                                  flat[start_vi]["page"] + 1,
                                                  flat[start_vi]["bucket"]["start_pt"]),
                    "reason": "结构容器归属与逐行字符对账证据",
                    "input": str(chapter.path),
                    "review": False,
                }
            )
        _check_code_indent_geometry(line_first, chapter, block_no, failures)
        relaxed.append(
            {
                "segment": "代码块 #%d 行内空白/空行保真（%d 逻辑行）"
                           % (block_no, len(lines)),
                "reason": "空白 run 已按个数严格对账（制表位/边界空白除外），"
                          "精确空白保真仍需视觉复核",
                "input": str(chapter.path),
                "review": True,
            }
        )
        cursor_ci, cursor_off = advance(start_ci, start_off, used)
        if used > 0:
            consumed.update(range(start_ci, end_ci + 1))
    # 块间/块前/章末未归属容器清扫。未消费容器若在快路径跳过（首行不
    # 对齐）则不参与逐块对账，必须逐一定性：
    # - 全等宽容器：代码内容只应出现在归属消费内（表格内代码、行内代码
    #   均非 /Div），未归属的等宽容器即多出整块代码（含与源相同内容的
    #   重复块——“能在原文找到”不排除出现次数），必拒 code-line-missing；
    # - 与某个源代码块严格对账一致的未归属容器（含混合字体行渲染的代码
    #   重复块）→ 有等宽行必拒，纯回退字体的重复记待复核，不得静默；
    # - 非全等宽且全部绘制行按出现次数能在章原文找到（提示框等预期内
    #   容，渲染顺序不同）→ 静默放行（出现次数必须扣减，防重复块借
    #   “原文出现过”蒙混）；
    # - 其余（含混合字体的插入围栏）→ 无法机器定性，记入待复核，不得
    #   静默通过（4.9：定位歧义进入既有待复核流程）。
    # 部分消费的末尾容器由末尾检查按“部分消费必拒”单独判。
    chapter_norm = normalize(chapter.text)
    block_lines = [logical_lines_of(item) for item in chapter.code_blocks]
    seen_counts = {}

    def _explainable(row_texts):
        key = normalize(" ".join(row_texts))  # normalize 去全部空白
        seen_counts[key] = seen_counts.get(key, 0) + 1
        return seen_counts[key] <= chapter_norm.count(key)

    def _matches_a_source_block(texts):
        for lines in block_lines:
            probe = [0]
            if _consume_block_tokens(texts, lines) is not None:
                return True
        return False

    def _classify_leftover(rows, where):
        texts = [row["text"] for row in rows if row["text"].strip()]
        if not texts:
            return False
        has_mono = any(row["bucket"].get("all_mono") for row in rows
                       if row["text"].strip())
        if has_mono and _matches_a_source_block(texts):
            failures.append(
                {"code": "code-line-missing", "input": str(chapter.path),
                 "message": "存在与源代码块一致的未归属容器（重复块，%s）：%r"
                            % (where, texts[0][:40])})
            return True
        if all(row["bucket"].get("all_mono") for row in rows
               if row["text"].strip()):
            failures.append(
                {"code": "code-line-missing", "input": str(chapter.path),
                 "message": "存在未归属的代码内容（%s）：%r"
                            % (where, texts[0][:40])})
            return True
        if _matches_a_source_block(texts):
            # 纯回退字体渲染（无等宽行）但与某源代码块严格一致：重复块
            # 无法按字体机器定性，记入待复核，不得静默通过。
            relaxed.append(
                {
                    "segment": "未归属容器与源代码块一致（重复？%s）：%r"
                               % (where, texts[0][:40]),
                    "reason": "纯回退字体渲染的重复代码块，需视觉复核",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
            return False
        if _explainable(texts):
            return False
        relaxed.append(
            {
                "segment": "未归属容器（%s）：%r" % (where, texts[0][:40]),
                "reason": "容器内容无法在章原文按出现次数解释且非全等宽，"
                          "无法机器定性，需视觉复核",
                "input": str(chapter.path),
                "review": True,
            }
        )
        return False

    swept = set()
    for ci, container in enumerate(containers):
        if ci in consumed or ci >= cursor_ci and consumed:
            # 末尾容器由末尾检查负责（含部分消费）
            continue
        swept.add(ci)
        if _classify_leftover(container["lines"], "块间/块前"):
            break
    # 末尾多余内容：块尾插入（含非等宽回退字体行）落在最后一个容器内
    # 未消费的部分，属确定损伤（部分消费必拒）；未触碰的整容器按定性
    # 规则处理（全等宽必拒，其余记待复核）。
    for ci in range(cursor_ci, len(containers)):
        if ci in swept:
            continue
        off = cursor_off if ci == cursor_ci else 0
        rows = containers[ci]["lines"][off:]
        leftover = [row["text"] for row in rows if row["text"].strip()]
        if not leftover:
            continue
        partial = ci == cursor_ci and cursor_off > 0
        if partial:
            failures.append(
                {"code": "code-line-missing", "input": str(chapter.path),
                 "message": "章末存在未归属的代码内容：%r"
                            % leftover[0][:40]})
            break
        if _classify_leftover(rows, "章末"):
            break
    return infos


def check_code_blocks_per_line(chapters, pdf, bounds, failures, relaxed):
    """块内逐逻辑行核验（R8/A22/A23）：结构树容器归属 + token 完整对账。

    归属证据是 tagged PDF 的结构树（候选容器 → 内容流 MCID → 绘制行），
    而不是字体名称、固定 x 阈值或源码字符搜索：容器内全部实际绘制内容
    必须被源逻辑行恰好消费——块内插入（含非等宽回退字体的行）、删字、
    改字、乱序、重复块缺失都是 code-line-missing；视觉折行与跨页由
    结构行拼接解释。行内空白删伤改变 token 序列必拒；缩进按行首 x 几何
    核对。结构不足（无结构树或容器行无法解码）时逐块记录源位置、候选
    页/区域与未证实的内容/分页项，进入待复核，不运行几何猜测匹配，也
    不自动判完整（verify_delivery 在逐项复核闭合前必拒）。
    返回逐块位置信息 {chapter.path: [{'first_page','last_page','long'}]}。
    """
    buckets = pdf.line_buckets
    marks = pdf.mcid_marks
    containers = pdf.structure_containers
    if containers is not None:
        # 代码块的渲染容器在结构树中稳定呈现为 /Div（正文为 /P、标题
        # /H1-H6、逐 MCID 包装为 /NonStruct）；只把 /Div 作为代码候选，
        # 避免行级包装让块绕过父容器对账，也避免整章包装参与匹配。
        containers = [item for item in containers if item[1] == "/Div"]
    buckets_by_page = [(b["page"], b["y"], b) for b in buckets]
    infos = {}
    for chapter, start_page, end_page in bounds:
        chapter_infos = infos.setdefault(str(chapter.path), [])
        if not chapter.code_blocks:
            continue
        container_seq = None
        if containers:
            container_seq = _chapter_containers(
                containers, marks, buckets_by_page, start_page, end_page)
            container_seq = _with_orphan_code_rows(
                container_seq, buckets, buckets_by_page, marks,
                pdf.structure_containers, start_page, end_page)
        if container_seq:
            chapter_infos.extend(
                _match_chapter_blocks_structural(
                    container_seq, chapter, failures, relaxed))
            continue
        # 结构不足：逐块待复核（源位置 + 候选页/区域 + 未证实项）。
        # 不再用等宽桶几何猜测匹配整块归属——该路径原有的部分硬失败
        # 改为未闭合的人工复核项（设计 §2 差异③，非等价重构）；可靠
        # 归属区域仍由上面的结构路径严格检查，确定损伤不降级。
        relaxed.append(
            {
                "segment": "本章代码核验结构不足（%s），无结构归属证据"
                           % ("内容流不可解析" if marks is None
                              else "结构树不可用或容器行无法解码"),
                "reason": "结构归属缺失，本章代码块逐块待复核；正常受支持"
                          "输出普遍进入此分支时应修复提取层",
                "input": str(chapter.path),
                "review": True,
            }
        )
        for block_no, item in enumerate(chapter.code_blocks, start=1):
            lines = logical_lines_of(item)
            preview = next(
                (line.strip() for line in lines if line.strip()), "（空块）")
            chapter_infos.append(
                {"first_page": None, "last_page": None,
                 "long": len(lines) > exporter.CODE_BLOCK_MAX_LINES})
            relaxed.append(
                {
                    "segment": "代码块 #%d（%d 行，首行 %r）待复核：候选区域"
                               " 第 %d–%d 页（本章全部范围）"
                               % (block_no, len(lines), preview[:40],
                                  start_page + 1, end_page),
                    "reason": "结构不足：字符/空白/块次数/顺序的内容完整性与"
                              "短块整块、长块页尾续排的分页约束均未证实，"
                              "需绑定本 PDF 逐项人工核对",
                    "input": str(chapter.path),
                    "review": True,
                }
            )
    return infos


def _check_code_indent_geometry(line_first_buckets, chapter, block_no,
                                failures):
    """按行桶 x 核对缩进（几何证据）：

    源行前导空白等宽展开后相同 → 桶 x 必须一致；不同缩进 → 行首 x 必须不同
    （容差 1pt）。不假设缩进单调变化：合法的反缩进不误报。
    """
    x_by_indent = {}
    for indent_width, x in line_first_buckets:
        known = x_by_indent.get(indent_width)
        if known is None:
            for other_indent, other_x in x_by_indent.items():
                if abs(other_x - x) <= 1.0:
                    failures.append(
                        {
                            "code": "code-indent-mismatch",
                            "input": str(chapter.path),
                            "message": "代码块 #%d 不同缩进（%d 与 %d 字符）行首 x "
                            "相同（%.1f）：缩进未渲染或被改写"
                            % (block_no, other_indent, indent_width, x),
                        }
                    )
                    return
            x_by_indent[indent_width] = x
        elif abs(known - x) > 1.0:
            failures.append(
                {
                    "code": "code-indent-mismatch",
                    "input": str(chapter.path),
                    "message": "代码块 #%d 同缩进（%d 字符）行首 x 不一致："
                    "%.1f vs %.1f" % (block_no, indent_width, known, x),
                }
            )
            return


def check_short_block_not_split(bounds, failures, block_infos):
    """短块（10 逻辑行以内）整体不分页：跨页绘制即失败（design 4.9）。"""
    for chapter, _start, _end in bounds:
        for block_no, info in enumerate(
                block_infos.get(str(chapter.path), []), start=1):
            if info.get("long"):
                continue
            if info.get("first_page") is None:
                continue
            if info["first_page"] != info["last_page"]:
                failures.append(
                    {
                        "code": "code-short-split",
                        "input": str(chapter.path),
                        "message": "短代码块 #%d（10 行以内）跨页绘制于第 %d-%d 页，"
                        "违反整块不分页约束"
                        % (block_no, info["first_page"] + 1,
                           info["last_page"] + 1),
                    }
                )


_CODE_FONT_MARKERS = ("MONO", "MENLO", "COURIER", "CONSOLAS")


def _is_mono_font(font_name):
    upper = (font_name or "").upper()
    return any(marker in upper for marker in _CODE_FONT_MARKERS)


def _collect_text_run_geometry(pdf):
    """收集行右缘所需的实际绘制几何，不改变旧行桶坐标口径。

    pypdf visitor 给出文本矩阵、页面变换和字号。代码等宽字体以
    Menlo/Courier 的实际 0.602em 推算字形右缘；回退字体对 ASCII
    取 0.62em、宽字符取 1em。该估算只用于判定行是否真实到达
    版心右界，不用于字符完整性比较。
    """
    import unicodedata

    result = []
    for page in pdf.reader.pages:
        events = []
        try:
            page_left = float(page.mediabox.left)
            page_bottom = float(page.mediabox.bottom)
            page_right = float(page.mediabox.right)
            page_top = float(page.mediabox.top)
        except (AttributeError, TypeError, ValueError):
            page_left = page_bottom = page_right = page_top = None
        # @page 横边距与 pre 横内边距；容差覆盖边框、
        # 字形 advance 与 visitor 分段边界的一至两字符误差。
        code_right = (page_right - PDF_PAGE_MARGIN_HORIZONTAL_PT
                      - PDF_PRE_PADDING_HORIZONTAL_PT
                      if page_right is not None else None)
        code_left = (page_left + PDF_PAGE_MARGIN_HORIZONTAL_PT
                     + PDF_PRE_PADDING_HORIZONTAL_PT
                     if page_left is not None else None)

        def visitor(text, cm, tm, font_dict, font_size, _events=events):
            if not text:
                return
            font = ""
            try:
                if isinstance(font_dict, dict):
                    font = str(font_dict.get("/BaseFont") or "")
                else:
                    font = str(font_dict or "")
            except Exception:  # noqa: BLE001
                font = ""
            mono = _is_mono_font(font)
            em = 0.0
            for char in text:
                if mono:
                    em += 0.60205078
                elif unicodedata.east_asian_width(char) in ("W", "F"):
                    em += 1.0
                else:
                    em += 0.62
            # PDF 仿射变换：(x, y) -> (a*x + c*y + e, b*x + d*y + f)。
            matrix = (cm if isinstance(cm, (list, tuple)) and len(cm) >= 6
                      else (1, 0, 0, 1, 0, 0))
            start_x = (float(matrix[0]) * float(tm[4])
                       + float(matrix[2]) * float(tm[5]) + float(matrix[4]))
            scale_x = (float(matrix[0]) ** 2
                       + float(matrix[1]) ** 2) ** 0.5
            scale_y = (float(matrix[2]) ** 2
                       + float(matrix[3]) ** 2) ** 0.5
            baseline_y = (float(matrix[1]) * float(tm[4])
                          + float(matrix[3]) * float(tm[5])
                          + float(matrix[5]))
            end_x = start_x + abs(float(font_size)) * em * scale_x
            advance_pt = abs(float(font_size)) * (0.60205078 if mono else 0.62) \
                * scale_x
            _events.append(
                {"y": float(tm[5]), "x": float(tm[4]),
                 "font": font.lstrip("/"), "text": text,
                 "start_pt": start_x, "right_pt": end_x,
                 "code_left_pt": code_left, "code_right_pt": code_right,
                 "advance_pt": advance_pt,
                 "baseline_y_pt": baseline_y,
                 "font_size_pt": abs(float(font_size)) * scale_y,
                 "page_left_pt": page_left,
                 "page_bottom_pt": page_bottom,
                 "page_right_pt": page_right,
                 "page_top_pt": page_top})

        try:
            page.extract_text(visitor_text=visitor)
        except Exception:  # noqa: BLE001
            events = []
        result.append(events)
    return result


def build_line_buckets(drawn_events):
    """把统一绘制事实聚合为视觉行桶序列（代码块归属的几何证据）。

    行聚合与排序使用页内物理基线（baseline_y_pt，pt 口径）：同一物理
    布局以不同文本矩阵表达时结论一致；页内按物理基线降序（PDF y 向上，
    降序即视觉自上而下）、同基线 6pt 容差聚桶（吸收 CJK 回退字体的
    基线差），桶内按绘制序拼接（Chromium 按字体分段绘制混合脚本行，
    x 坐标在 Tm 重置时不可靠，绘制序才是逻辑序）。原始 tm 的 y/x 仅
    保留在桶上供提取层（MCID 标记联接）使用，不参与几何判定。
    """
    buckets = []
    for page_index, page_runs in enumerate(drawn_events):
        clusters = []
        for event in page_runs:
            baseline = event["baseline_y_pt"]
            placed = False
            for cluster in clusters:
                if abs(cluster["baseline"] - baseline) <= 6.0:
                    cluster["items"].append(event)
                    placed = True
                    break
            if not placed:
                clusters.append({"baseline": baseline, "items": [event]})
        # 物理基线降序 = 视觉自上而下
        page_buckets = []
        for cluster in sorted(clusters,
                              key=lambda c: c["baseline"], reverse=True):
            text = "".join(item["text"] for item in cluster["items"])
            text_items = [item for item in cluster["items"]
                          if item["text"].strip()]
            code_rights = [item["code_right_pt"]
                           for item in cluster["items"]
                           if isinstance(item["code_right_pt"], (int, float))]
            geometry_items = text_items or cluster["items"]
            right_pt = max(item["right_pt"] for item in cluster["items"])
            start_pt = min(item["start_pt"] for item in geometry_items)
            # 行内首个非空白字符的物理 x。行首空白有两种绘制方式：
            # 普通空格体现为文本起点偏移、不产生空白字形（NBSP 则与
            # 后续文本同 run 绘制成字形，使行起点落在版心左界）。缩进
            # 几何必须取首个非空白字符 x，两种绘制方式口径才一致。
            first_chars = []
            for item in geometry_items:
                lead = 0
                for ch in item["text"]:
                    if ch.isspace():
                        lead += 1
                    else:
                        break
                first_chars.append(item["start_pt"] + lead * item["advance_pt"])
            first_char_pt = min(first_chars) if first_chars else start_pt
            code_right_pt = min(code_rights) if code_rights else None
            baselines = [item["baseline_y_pt"] for item in geometry_items]
            font_sizes = [item["font_size_pt"] for item in geometry_items]
            page_bounds = geometry_items[0]
            page_buckets.append(
                {
                    "page": page_index,
                    # 原始 tm 坐标：仅作提取层标记联接键
                    "y": cluster["items"][0]["y"],
                    # 物理行首（非空白 run 的最小起点）：缩进与列几何用
                    "start_pt": start_pt,
                    # 行内首个非空白字符 x（行首空白绘制成字形时与
                    # start_pt 不同，如 NBSP 行首）；缩进比对取此值
                    "first_char_pt": first_char_pt,
                    "code_left_pt": page_bounds["code_left_pt"],
                    "right_pt": right_pt,
                    "code_right_pt": code_right_pt,
                    "all_mono": bool(cluster["items"]) and all(
                        _is_mono_font(item["font"])
                        for item in cluster["items"]),
                    "text": text,
                    "mono_advance_pt": max(
                        item["advance_pt"] for item in cluster["items"]
                        if _is_mono_font(item["font"]))
                    if any(_is_mono_font(item["font"])
                           for item in cluster["items"]) else None,
                    # 页界判定使用页内 PDF 物理坐标，不使用
                    # Chromium 跨页累计的 tm.y，也不把页码变化
                    # 本身当成折行证据。
                    "baseline_y_pt": sum(baselines) / len(baselines),
                    "line_height_pt": max(font_sizes) * PDF_PRE_LINE_HEIGHT,
                    "page_left_pt": page_bounds["page_left_pt"],
                    "page_bottom_pt": page_bounds["page_bottom_pt"],
                    "page_right_pt": page_bounds["page_right_pt"],
                    "page_top_pt": page_bounds["page_top_pt"],
                    # 18pt = pre 内边距已扣除后，再容纳一至两个
                    # 8.5pt 等宽字形的 visitor/advance 边界误差。
                    "wrap_at_right": (
                        code_right_pt is not None
                        and right_pt >= code_right_pt - 18.0),
                }
            )
        buckets.extend(page_buckets)
    return buckets


def check_code_pagination(chapters, pdf, bounds, failures, reviews,
                          block_infos, relaxed=None):
    """长代码块整块移页检查（A21：code-page-gap）。

    长块（>10 逻辑行）允许跨页，但必须利用当前页可容纳完整代码行的
    剩余空间：若长块起于前一内容所在页的下一页，且前页底部剩余空间
    还能排下代码行，即判整块移页 FAIL。分页直接消费统一绘制事实的
    物理坐标：剩余空间按该页最低占用点（文本基线与绘制图片底边取低）
    与 @page 底边距 + pre 内边距计算。前一内容页取本章内块前最后一
    个有实际内容（文字/图片）的页，不用前一代码块末页代替。本页块上
    方的前导内容（标题、正文、图片随块移来）不构成豁免：前页放得下
    前导内容、块间必要间距与至少一完整代码行时仍判 code-page-gap——
    增加一个 H2 不改变这一空间判断；确实放不下时该移页有依据，记录
    实际前导区域、所需空间与前页占用的空间证据。行高取该块自身前两
    个视觉行的物理基线差（由结构归属记录在逐块信息中），不按源码字
    符重新定位行。行高无法估计时记录待复核，不假判通过。短块整体移
    页的页尾空白明确放行。
    """
    usable_bottom = (PDF_PAGE_MARGIN_VERTICAL_PT
                     + PDF_PRE_PADDING_VERTICAL_PT)
    occupied_by_page = {}
    for bucket in pdf.line_buckets:
        if bucket["text"].strip():
            occupied_by_page.setdefault(bucket["page"], []).append(
                bucket["baseline_y_pt"])
    image_extents_by_page = collect_drawn_images(pdf)
    for page_index, images_drawn in enumerate(image_extents_by_page):
        for _width, bottom_pt, _top in images_drawn:
            occupied_by_page.setdefault(page_index, []).append(bottom_pt)
    for chapter, start_page, end_page in bounds:
        infos = block_infos.get(str(chapter.path), [])
        for bi, cur in enumerate(infos):
            if not cur.get("long"):
                continue
            if cur.get("first_page") is None:
                continue
            # 前一内容页：本章内块前最后一个有实际内容的页（正文/图片
            # 可延伸到前一代码块末页之后，不以代码块末页代替）
            prev_page = None
            for page in range(cur["first_page"] - 1, start_page - 1, -1):
                if occupied_by_page.get(page):
                    prev_page = page
                    break
            if prev_page is None:
                continue  # 章首强制分页，无前页可让
            if cur["first_page"] <= prev_page:
                continue
            block_base = cur.get("first_baseline_pt")
            line_height = cur.get("line_height_pt")
            if not line_height or line_height <= 0 or block_base is None:
                reviews.append(
                    {
                        "code": "code-page-gap-review",
                        "input": str(chapter.path),
                        "message": "代码块 #%d 起于前一内容下一页，但行高无法"
                                   "从绘制坐标估计，需视觉复核是否有整块移页"
                                   % (bi + 1),
                    }
                )
                continue
            # 本页块上方的前导内容（标题/正文/图片随块移来）：不豁免，
            # 参与前页空间核算；文字行按基线各外扩半行高，图片按整幅
            # 顶底范围（底边低于块首行的图片覆盖块上方区域）
            leading_text = [
                y for y in occupied_by_page.get(cur["first_page"], [])
                if y > block_base + 2.0
            ]
            leading_images = [
                (bottom, top)
                for _w, bottom, top in (
                    image_extents_by_page[cur["first_page"]]
                    if cur["first_page"] < len(image_extents_by_page)
                    else [])
                if bottom > block_base + 2.0
            ]
            leading = bool(leading_text or leading_images)
            leading_height = 0.0
            if leading:
                lows = ([y - line_height * 0.5 for y in leading_text]
                        + [bottom for bottom, _top in leading_images])
                highs = ([y + line_height * 0.5 for y in leading_text]
                         + [top for _bottom, top in leading_images])
                leading_height = max(highs) - min(lows)
            page_occupied = occupied_by_page[prev_page]
            remaining_pt = min(page_occupied) - usable_bottom
            # 前页须能容纳前导内容、块间必要间距（前后各约一行高的
            # 元素边距）与至少一完整代码行。无前导内容时，除一行高外
            # 还须容纳块起始开销：首行行盒 + pre 上内边距 7pt + 边框
            # 0.5pt + 上外边距 0.7em≈6pt + 前行行尾下沉 ≈16pt。旧口径
            # 只按一行高计算，把物理上放不下块起始的 11-21pt 页尾误判
            # 为整块移页（真实六章样例 4 处复现， orphans/widows=1 亦
            # 无法放入）。块起始处尾隙非大半页空白且有物理解释时，后移
            # 不构成 A21 违规；放得下却后移仍按原样 FAIL。
            block_start_overhead = 16.0
            required_pt = (leading_height + line_height * 2.0
                           if leading else
                           line_height + block_start_overhead)
            if remaining_pt >= required_pt:
                block = chapter.code_blocks[bi]
                lines = logical_lines_of(block)
                failures.append(
                    {
                        "code": "code-page-gap",
                        "input": str(chapter.path),
                        "message": "代码块 #%d（%d 行）整块移到第 %d 页，"
                                   "前页第 %d 页底部仍剩约 %.0fpt"
                                   "（放得下%s至少一完整代码行），"
                                   "未利用页尾续排"
                                   % (bi + 1, len(lines), cur["first_page"] + 1,
                                      prev_page + 1, remaining_pt,
                                      "前导内容%.0fpt 及" % leading_height
                                      if leading else ""),
                    }
                )
            elif leading and relaxed is not None:
                # 移页有依据：记录前导区域、所需空间与前页占用的证据
                relaxed.append(
                    {
                        "segment": "代码块 #%d 整块移到第 %d 页有空间依据："
                                   "前导内容约 %.0fpt，前页第 %d 页剩余约 "
                                   "%.0fpt，放不下前导内容与至少一完整代码行"
                                   % (bi + 1, cur["first_page"] + 1,
                                      leading_height, prev_page + 1,
                                      remaining_pt),
                        "reason": "分页按源序排布，前页空间不足以回填",
                        "input": str(chapter.path),
                        "review": False,
                    }
                )


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


def parse_args(argv=None):
    """解析核验 CLI 参数（交付检查复用同一解释，参数单源）。"""
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
    parser.add_argument(
        "--require-display-map",
        action="store_true",
        help="与导出一致的严格尺寸保真策略；省略时若导出为严格模式则判 FAIL",
    )
    parser.add_argument(
        "--provenance",
        default=None,
        metavar="PATH",
        help="与导出一致的只读出处区间映射；导出使用时核验必须传入同一文件",
    )
    parser.add_argument("inputs", nargs="+", help="有序 Markdown 输入")
    return parser.parse_args(argv)


def run_verification(args):
    """核验计算（不落盘、不打印）：返回 (机器是否通过, 核验报告 dict)。

    CLI 与交付入口共用同一计算：交付检查直接取得本次结果作为机器证据，
    不读取或比较任何预存核验 JSON。导出报告（export_report.json）与其中
    绑定的政策仍是必需输入；缺失或不可解析按 export-evidence-missing
    失败，不回落到任何旧报告。
    """
    work_dir = Path(args.work_dir).expanduser()
    report_path = work_dir / REPORT_NAME
    report = None
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            report = None
    report_usable = isinstance(report, dict)
    if not report_usable:
        report = {}
    failures = []
    relaxed = []
    reviews = []
    if not report_usable:
        failures.append({"code": "export-evidence-missing",
                         "message": "导出证据缺失或不可解析: %s" % report_path})

    chapters = reparse_inputs(
        args.inputs, failures, args.unlink_target, args.toc_sections
    )
    cross_check(chapters, failures)
    check_inputs_protection(report, failures)

    # 显示尺寸映射独立重建：绑定失败同样判 FAIL，并核对与导出参数一致。
    display_diagnostics = []
    bindings, display_undetermined, display_undetermined_raw, \
        display_map_paths = (
            exporter.load_display_maps(
                chapters, list(args.images_display), display_diagnostics
            )
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
    # 省略核验严格参数不能把一次严格导出改验成普通模式：两侧参数必须一致。
    exported_require = bool(report.get("require_display_map"))
    if exported_require != bool(args.require_display_map):
        failures.append(
            {
                "code": "images-display-require-mismatch",
                "message": "严格尺寸保真参数与导出不一致（导出 %s / 核验 %s）"
                % (exported_require, bool(args.require_display_map)),
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

    # 覆盖独立重算不依赖 PDF 存在：从原输入与映射即可核对分类与严格策略。
    check_image_coverage(chapters, bindings, display_undetermined,
                         display_undetermined_raw, report,
                         bool(args.require_display_map), failures)

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
        # 出处预期独立重建与前置位置核对（首章页依赖大纲目的地）。
        check_provenance(chapters, report, pdf, args.provenance, failures,
                         heading_pages)
        bounds = chapter_bounds(chapters, pdf, heading_pages, failures)
        check_blocks(chapters, pdf, bounds, failures, relaxed, "text")
        # R8：块内核验（结构归属逐行对账）、短块整块与长块页尾续排检查。
        code_block_infos = check_code_blocks_per_line(
            chapters, pdf, bounds, failures, relaxed)
        check_short_block_not_split(bounds, failures, code_block_infos)
        check_code_pagination(chapters, pdf, bounds, failures, reviews,
                              code_block_infos, relaxed)
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
    return machine_pass, verify_report


def main(argv=None):
    args = parse_args(argv)
    work_dir = Path(args.work_dir).expanduser()

    machine_pass, verify_report = run_verification(args)
    (work_dir / VERIFY_NAME).write_text(
        json.dumps(verify_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failures = verify_report["failures"]
    relaxed = verify_report["relaxed_matches"]
    reviews = verify_report["reviews"]

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
        % (Path(args.pdf).expanduser(), work_dir / VERIFY_NAME)
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
