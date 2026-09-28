#!/usr/bin/env python3
"""PDF 源勘察与物化共用的内部实现。

本文件是内部模块；`prepare_pdf_source.py` 与 `verify_pdf_source.py`
各自定义自己的 CLI 与通过条件。只读 PDF，绝不改写源文件；
依赖缺失时给出清晰诊断，绝不自动安装。
"""
import hashlib
import os
import re
import sys
from statistics import median

MIN_PYTHON = (3, 10)
CHECKLIST_VERSION = 1

# 逐页文本层可读性判定的最低正文字符数；低于该值视为该页正文需 OCR
# （可能为扫描图像页），留作证据而非按零处理。
MIN_BODY_CHARS = 20
# 可读字符占比下限：低于该占比的文本层按乱码嫌疑处理（进入 undetermined
# 证据，不静默当作正文）。
MIN_READABLE_RATIO = 0.6

_COMMON_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " \t\n.,;:!?()[]{}<>/\\|'\"-_=+*&%$#@~`^"
    "，。；：！？（）【】《》、·—“”‘’…￥"
    "àâäçéèêëîïôöùûüÿñáéíóú"
)


def fail(message, code=2):
    """阻断性诊断：中文、非零退出。"""
    print("FAIL: %s" % message, file=sys.stderr)
    raise SystemExit(code)


def load_fitz():
    """按 D5 探测 PyMuPDF；缺失或解释器不兼容时清晰报错退出，不自动安装。"""
    if sys.version_info < MIN_PYTHON:
        fail("解释器版本不满足 PDF 源处理要求: Python %s（需 >= %d.%d）；"
             "请用目标解释器安装 %s 后重试"
             % (platform_python(), MIN_PYTHON[0], MIN_PYTHON[1],
                "requirements-pdf-source.txt"))
    try:
        import pymupdf as fitz
        return fitz
    except ImportError:
        pass
    try:
        import fitz
    except ImportError:
        fail("缺少 PyMuPDF，无法处理 PDF 源；按 <SKILL目录>/requirements-pdf-source.txt"
             " 用目标解释器安装后重试（本脚本绝不自动安装依赖）")
    return fitz


def platform_python():
    return "%d.%d.%d" % sys.version_info[:3]


def probe_environment():
    """记录解释器与 PyMuPDF 实际版本及 API 兼容性（D5 环境探测口径）。"""
    info = {
        "python": platform_python(),
        "pymupdf": None,
        "pymupdf_import": "pymupdf",
        "api": {},
        "compatible": False,
        "notes": [],
    }
    try:
        import pymupdf
        info["pymupdf"] = getattr(pymupdf, "__version__", "unknown")
    except ImportError:
        # 旧版只提供 fitz 包名
        try:
            import fitz
            info["pymupdf"] = getattr(fitz, "VersionBind",
                                      getattr(fitz, "__version__", "unknown"))
            info["pymupdf_import"] = "fitz"
        except ImportError:
            info["notes"].append("PyMuPDF 未安装")
            return info
    fitz = load_fitz()
    for name in ("open",):
        info["api"][name] = hasattr(fitz, name)
    # Page 方法按实际属性探测，不预置结论（D5：记录实际兼容性）
    for name in ("get_text", "get_drawings", "get_image_info", "annots",
                 "get_links"):
        info["api"]["Page.%s" % name] = hasattr(fitz.Page, name)
    info["compatible"] = all(info["api"].values())
    if not info["compatible"]:
        info["notes"].append("PyMuPDF API 面不完整，按 requirements-pdf-source.txt"
                             " 升级后重试")
    return info


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pages_arg(spec, page_count):
    """解析 --pages 范围（如 all、3、1-3,7）；返回 1 起页号列表。"""
    if spec in (None, "", "all"):
        return list(range(1, page_count + 1))
    pages = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            fail("--pages 含空段: %r" % spec)
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            fail("--pages 段格式非法: %r（需如 1-3,7）" % part)
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end > page_count or start > end:
            fail("--pages 超出实际页数 1..%d: %r" % (page_count, part))
        pages.extend(range(start, end + 1))
    seen = set()
    ordered = []
    for page in pages:
        if page not in seen:
            seen.add(page)
            ordered.append(page)
    return ordered


def source_identity(pdf_path, doc):
    """源身份：realpath、sha256、字节数、页数与逐页尺寸/旋转。"""
    real = os.path.realpath(pdf_path)
    page_geom = []
    for page in doc:
        rect = page.rect
        page_geom.append({
            "page": page.number + 1,
            "width_pt": round(rect.width, 2),
            "height_pt": round(rect.height, 2),
            "rotation": page.rotation,
        })
    return {
        "path": os.path.abspath(pdf_path),
        "realpath": real,
        "sha256": file_sha256(real),
        "bytes": os.path.getsize(real),
        "page_count": doc.page_count,
        "pages": page_geom,
        "coordinate_system": {
            "unit": "pt",
            "origin": "top-left",
            "axis": "x 向右、y 向下",
            "space": "PyMuPDF 页面坐标（page.rect；rotation != 0 时"
                     " 文本提取坐标遵循 PyMuPDF 未旋转页面空间，"
                     " 裁决裁剪前须按页旋转换算）",
        },
    }


def _readable_ratio(text):
    """字符级可读占比：字母数字/常见标点/空白之外记为可疑。"""
    if not text:
        return 1.0
    good = sum(1 for ch in text
               if ch in _COMMON_CHARS or ch.isalnum() or ch.isspace())
    return good / len(text)


def _page_text_stats(page):
    text = page.get_text("text") or ""
    blocks = [b for b in page.get_text("blocks")
              if b[6] == 0 and (b[4] or "").strip()]
    area = page.rect.width * page.rect.height
    text_area = 0.0
    for block in blocks:
        width = max(0.0, min(block[2], page.rect.width)
                    - max(block[0], 0.0))
        height = max(0.0, min(block[3], page.rect.height)
                     - max(block[1], 0.0))
        text_area += width * height
    return {
        "chars": len(text.strip()),
        "readable_ratio": round(_readable_ratio(text), 3),
        "text_blocks": len(blocks),
        "text_area_ratio": round(text_area / area, 3) if area else 0.0,
    }


def page_facts(page):
    """单页对象统计：文本层、绘图、位图、批注与链接（对象级核查，
    文件名/元数据声明不作事实依据）。"""
    stats = _page_text_stats(page)
    drawings = page.get_drawings()
    images = page.get_image_info(xrefs=True)
    annots = list(page.annots())
    links = page.get_links()
    return {
        "page": page.number + 1,
        "width_pt": round(page.rect.width, 2),
        "height_pt": round(page.rect.height, 2),
        "rotation": page.rotation,
        "chars": stats["chars"],
        "readable_ratio": stats["readable_ratio"],
        "text_blocks": stats["text_blocks"],
        "text_area_ratio": stats["text_area_ratio"],
        "vector_drawings": len(drawings),
        "embedded_bitmaps": len(images),
        "annotations": len(annots),
        "links": len(links),
    }


def _page_usable_text(facts):
    """该页正文文本层是否可靠：字符量与可读占比双门槛。"""
    return (facts["chars"] >= MIN_BODY_CHARS
            and facts["readable_ratio"] >= MIN_READABLE_RATIO)


def page_bitmap_regions(page):
    """页面上全部嵌入位图区域，返回待裁决候选（附区域证据线索）。

    枚举不做任何"消失性"过滤（设计 §7.3）：面积占比、与文本块是否相交
    只作线索写入 basis，不影响是否入列；区域是插图素材还是需 OCR 正文
    一律由主 Agent 对照原页裁决；不自动执行 OCR。整页级 ocr_region 已
    覆盖的页面由调用方去重。
    """
    fitz = load_fitz()
    page_area = page.rect.width * page.rect.height
    text_rects = [fitz.Rect(block[:4]) for block in page.get_text("blocks")
                  if block[6] == 0 and (block[4] or "").strip()]
    regions = []
    for info in page.get_image_info(xrefs=True):
        rect = fitz.Rect(info["bbox"])
        ratio = (rect.width * rect.height / page_area) if page_area > 0             else 0.0
        overlapped = any(rect.intersects(text) for text in text_rects)
        regions.append({
            "rect": fitz_rect(rect),
            "area_ratio": round(ratio, 4),
            "basis": "嵌入位图区域：面积占比 %.2f%%、%s文本块相交"
                     "（线索；用途待裁决：插图素材或需 OCR 正文区域）"
                     % (100.0 * ratio, "与" if overlapped else "不与"),
        })
    return regions


def check_type_migration(checklist):
    """ocr_region ⇒ mixed 强制迁移校验（设计 §7.3 机制 A）。

    存在未处置 ocr_region 待处理项但正文类型仍为 text 属不一致状态：
    须将类型裁决为 mixed 并记录依据。返回错误消息或 None。
    """
    pending = checklist.get("pending") or []
    has_ocr = any(item.get("kind") == "ocr_region" for item in pending)
    doc_type = (checklist.get("classification") or {}).get("type")
    if has_ocr and doc_type == "text":
        return ("存在 ocr_region 项（页内区域裁决为需 OCR 正文），但正文"
                "类型仍为 text：须按 A10 口径将类型裁决为 mixed 并在清单"
                "记录依据")
    return None


def check_adjudication_conflict(checklist):
    """裁决身份绑定校验（设计 §7.3 机制 B）。

    adjudicated_against（裁决作出时绑定的源 sha256/范围）与当前清单
    source.sha256/scope 不符时，须有覆盖该变化的有效 revalidate 记录
    （from 匹配旧绑定、to 匹配当前、basis 非空）才放行——即使 stale
    字段被删除也无妨；无绑定记录（旧版清单）且无其他不一致证据时按
    兼容口径放行。返回错误消息或 None。
    """
    bound = checklist.get("adjudicated_against")
    if not isinstance(bound, dict):
        return None
    source = checklist.get("source") or {}
    current_sha = source.get("sha256")
    current_scope = checklist.get("scope")
    if bound.get("sha256") == current_sha             and bound.get("scope") == current_scope:
        return None
    reval = checklist.get("revalidate")
    valid = isinstance(reval, dict)         and bool(str(reval.get("basis") or "").strip())         and isinstance(reval.get("from"), dict)         and reval["from"].get("sha256") == bound.get("sha256")         and reval["from"].get("scope") == bound.get("scope")         and isinstance(reval.get("to"), dict)         and reval["to"].get("sha256") == current_sha         and reval["to"].get("scope") == current_scope
    if valid:
        return None
    return ("裁决身份绑定与当前源/范围不符（裁决时 sha256 %s scope %s vs "
            "当前 %s %s），且缺少覆盖该变化的有效 revalidate 记录（from "
            "匹配旧绑定、to 匹配当前、basis 非空）：源/范围已变化，须重新"
            "核对旧裁决"
            % (str(bound.get("sha256"))[:12], bound.get("scope"),
               str(current_sha)[:12], current_scope))


def classify_pages(facts_list):
    """正文类型判定，返回 (类型, 证据列表)。

    判定只依据文本层证据：text：范围内每页正文文本层可靠（含嵌入位图
    仍为文字版，位图区域另列待裁决项，不参与类型判定）；scanned：正文
    需 OCR（无可用文本层、有版面对象）；mixed：可靠文本页与文本层不可
    用页并存；undetermined：文本为空、乱码或证据不足。页内无文本层位图
    区域的用途不由本函数裁决；不自动执行 OCR。
    """
    usable = [f for f in facts_list if _page_usable_text(f)]
    broken = [f for f in facts_list if not _page_usable_text(f)]
    evidence = [
        "范围内 %d 页：%d 页正文文本层可靠、%d 页文本层不可用"
        % (len(facts_list), len(usable), len(broken)),
    ]
    for f in facts_list:
        evidence.append(
            "P%d: 字符 %d、可读占比 %.2f、文本块 %d、文本面积占比 %.2f、"
            "嵌入位图 %d、矢量绘图 %d、批注 %d、链接 %d"
            % (f["page"], f["chars"], f["readable_ratio"], f["text_blocks"],
               f["text_area_ratio"], f["embedded_bitmaps"],
               f["vector_drawings"], f["annotations"], f["links"]))
    if not facts_list:
        return "undetermined", evidence + ["范围内没有任何页面"]
    if not usable:
        visual = [f for f in facts_list
                  if f["embedded_bitmaps"] or f["vector_drawings"]]
        if facts_list and all(f["chars"] == 0 for f in facts_list) and visual:
            evidence.append("全部页面无文本层但存在位图/矢量对象，"
                            "正文需 OCR；不自动执行 OCR")
            return "scanned", evidence
        evidence.append("文本为空或乱码，证据不足，保留未确定状态")
        return "undetermined", evidence
    if broken:
        evidence.append("以下页面正文需 OCR 区域定位: %s"
                        % ", ".join("P%d" % f["page"] for f in broken))
        return "mixed", evidence
    evidence.append("范围内每页均有可靠正文文本层，判为文字版")
    return "text", evidence


_HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+){0,3}|[A-Z])\s+\S")
_FIGCAP_RE = re.compile(r"^(Figure|Fig\.?)\s*\d+", re.I)
_TABCAP_RE = re.compile(r"^(Table)\s*\d+", re.I)
_FOOTNOTE_START_RE = re.compile(r"^(\[?\d+\]?|\*+)\s*\S")
_FORMULA_CHARS = set("∑∏∫√≈≠≤≥∈⊂⊆∪∩∀∃∂∇λθπσαβγδΔΩωμφ")
_FORMULA_RE = re.compile(
    r"[A-Za-z]\^[\d({]|[A-Za-z]_[\d({]|\\[A-Za-z]+|[≤≥≈≠∈∑∏∫√]")


def _page_lines(doc_page):
    """返回 [(text, rect, max_size, bold, line_no)]：dict 模式的成行文本。"""
    entries = []
    body_sizes = []
    for block in doc_page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = line.get("spans", [])
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            sizes = [round(s["size"], 1) for s in spans if s["text"].strip()]
            bold = any(s["flags"] & 16 for s in spans if s["text"].strip())
            entries.append([text, fitz_rect(line["bbox"]),
                            max(sizes) if sizes else 0.0, bold])
            body_sizes.extend(sizes)
    body = max(set(body_sizes), key=body_sizes.count) if body_sizes else 0.0
    return entries, body


def fitz_rect(seq):
    return [round(float(v), 2) for v in seq]


def structure_candidates(doc, pages):
    """结构候选：标题、图题、表格页、脚注候选与文本层公式候选（D4）。

    正则只作线索，候选一律带页码、位置与判定依据，交给主 Agent 对照
    原页逐项裁决；空类别显式输出空列表，不当作零。
    """
    fitz = load_fitz()
    headings = []
    figure_captions = []
    table_captions = []
    footnotes = []
    formulas = []
    bitmaps = []
    for pno in pages:
        page = doc[pno - 1]
        lines, body_size = _page_lines(page)
        height = page.rect.height
        for text, rect, size, bold in lines:
            basis = []
            numbered = _HEADING_NUM_RE.match(text)
            short = len(text) <= 90 and not text.endswith(('.', ';', ','))
            if size and body_size and size >= body_size + 1.0:
                basis.append("字号 %.1f > 正文 %.1f" % (size, body_size))
            if bold:
                basis.append("粗体")
            if numbered and size >= body_size and short:
                basis.append("编号模式 %r" % numbered.group(1))
            if basis and short:
                headings.append({
                    "page": pno, "rect": rect, "text": text,
                    "size": size, "basis": "、".join(basis),
                })
            if _FIGCAP_RE.match(text):
                figure_captions.append({"page": pno, "rect": rect,
                                        "text": text})
            if _TABCAP_RE.match(text):
                table_captions.append({"page": pno, "rect": rect,
                                       "text": text})
            if (body_size and size and size < body_size - 0.3
                    and rect[1] > height * 0.85
                    and _FOOTNOTE_START_RE.match(text)):
                footnotes.append({"page": pno, "rect": rect, "text": text,
                                  "size": size})
            if (any(ch in _FORMULA_CHARS for ch in text)
                    or _FORMULA_RE.search(text)):
                formulas.append({"page": pno, "rect": rect, "text": text})
        for info in page.get_image_info(xrefs=True):
            bitmaps.append({
                "page": pno,
                "xref": info.get("xref"),
                "rect": fitz_rect(info["bbox"]),
                "width": info.get("width"),
                "height": info.get("height"),
            })
    return {
        "headings": headings,
        "figure_captions": figure_captions,
        "table_captions": table_captions,
        "footnotes": footnotes,
        "formulas": formulas,
        "bitmaps": bitmaps,
    }


def snapshot_layout(doc, pages):
    """保版面快照：逐页文本块带坐标矩形，按提取顺序输出。"""
    out = []
    for pno in pages:
        page = doc[pno - 1]
        out.append("===== 第 %d 页（%.0f x %.0f pt，旋转 %d°）====="
                   % (pno, page.rect.width, page.rect.height,
                      page.rotation))
        for block in page.get_text("blocks"):
            if block[6] != 0 or not (block[4] or "").strip():
                continue
            out.append("[块] (%.1f,%.1f)-(%.1f,%.1f)"
                       % (block[0], block[1], block[2], block[3]))
            out.append(block[4].rstrip("\n"))
    return "\n".join(out) + "\n"


def _reading_order_blocks(page):
    """栏感知的块排序：全宽块（跨栏标题/图题）作锚点，相邻锚点之间
    先左栏后右栏按纵向排列。只作通读辅助，不单独裁定跨栏顺序（R2）。"""
    blocks = [b for b in page.get_text("blocks")
              if b[6] == 0 and (b[4] or "").strip()]
    width = page.rect.width
    anchors = sorted((b for b in blocks
                      if (b[2] - b[0]) > 0.55 * width),
                     key=lambda b: b[1])
    ordered = []
    emitted = set()
    for anchor in anchors:
        segment = [b for b in blocks if id(b) not in emitted
                   and b[1] < anchor[1] and b is not anchor]
        left = sorted((b for b in segment if (b[0] + b[2]) / 2 < width / 2),
                      key=lambda b: (b[1], b[0]))
        right = sorted((b for b in segment if (b[0] + b[2]) / 2 >= width / 2),
                       key=lambda b: (b[1], b[0]))
        ordered.extend(left)
        ordered.extend(right)
        ordered.append(anchor)
        emitted.update(id(b) for b in segment)
        emitted.add(id(anchor))
    rest = [b for b in blocks if id(b) not in emitted]
    left = sorted((b for b in rest if (b[0] + b[2]) / 2 < width / 2),
                  key=lambda b: (b[1], b[0]))
    right = sorted((b for b in rest if (b[0] + b[2]) / 2 >= width / 2),
                   key=lambda b: (b[1], b[0]))
    ordered.extend(left)
    ordered.extend(right)
    return ordered


def snapshot_reading(doc, pages):
    """通读快照：栏感知阅读顺序拼接的纯文本，接近栏序通读。"""
    out = []
    for pno in pages:
        page = doc[pno - 1]
        out.append("===== 第 %d 页（%.0f x %.0f pt，旋转 %d°）====="
                   % (pno, page.rect.width, page.rect.height,
                      page.rotation))
        for block in _reading_order_blocks(page):
            out.append(block[4].rstrip("\n"))
    return "\n".join(out) + "\n"


def extract_region_text(page, rect):
    """按页面/矩形区域重读文本（物化与独立对账的共同提取口径）。

    口径警示：本函数逐行 rstrip（剥行尾空白）并去除首尾空行，仅供
    正文/表格的结构对账使用；代码 golden 的逐字节比较（后续 ticket）
    不得复用此通道，以免行尾空白差异被吞掉。
    """
    fitz = load_fitz()
    clip = fitz.Rect(rect)
    text = page.get_text("text", clip=clip) or ""
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def extract_code_region(page, rect):
    """从页面矩形区域按 char 级重建代码清单文本，返回 (text, info)。

    保留字符、行序与等宽缩进（规避按行 clip 提取丢行首缩进的已知陷阱，
    需求 R3）：行首缩进由首字符 x 偏移（相对区域最左列）按等宽字宽
    （区域内相邻字符步进的中位数）换算为空格；同基线的多个文本 run
    （行内右侧注释等）合并为一行并按字宽补足间隔；文本层不产出空行，
    按行距（相邻行 y0 差中位数）重建区域内空行；区域外内容（页眉、
    分页符、邻栏）由裁剪矩形排除。text 逐字节保留字符、以换行结尾，
    不做任何行尾空白剥除——固化后即为 golden 的逐字节基准。
    """
    fitz = load_fitz()
    clip = fitz.Rect(rect)
    raw = page.get_text("rawdict", clip=clip)
    lines = []
    advances = []
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            chars = []
            for span in line["spans"]:
                chars.extend(span["chars"])
            if not chars:
                continue
            y0, y1 = line["bbox"][1], line["bbox"][3]
            # 排除贴边行：裁剪矩形的包含性边界可能带进区域外行
            if y1 < clip.y0 + 0.5 or y0 > clip.y1 - 0.5:
                continue
            lines.append([y0, chars[0]["bbox"][0],
                          "".join(c["c"] for c in chars)])
            for first, second in zip(chars, chars[1:]):
                step = second["bbox"][0] - first["bbox"][0]
                if step > 0:
                    advances.append(step)
    if not lines:
        return "", {"lines": 0, "char_width_pt": None, "pitch_pt": None}
    lines.sort(key=lambda item: item[0])
    char_w = median(advances) if advances else 0.0
    anchor = min(item[1] for item in lines)
    spacings = sorted(second[0] - first[0]
                      for first, second in zip(lines, lines[1:]))
    pitch = median(spacings) if spacings else 0.0
    # 同基线多 run（行内右侧注释等）合并为一行：按字宽补足间隔，
    # 重叠或紧邻时保留单个空格（间隔宽度是排版，不是代码内容）。
    merged = []
    for y0, x0, text in lines:
        if merged and pitch > 0 \
                and abs(y0 - merged[-1][0]) <= max(1.0, 0.3 * pitch):
            _py0, px0, ptext = merged[-1]
            pad = int(round((x0 - (px0 + len(ptext) * char_w)) / char_w)) \
                if char_w > 0 else 1
            merged[-1][2] = ptext + " " * max(1, pad) + text
            continue
        merged.append([y0, x0, text])
    lines = merged
    out = []
    prev_y0 = None
    for y0, x0, text in lines:
        if prev_y0 is not None and pitch > 0:
            gap_ratio = (y0 - prev_y0) / pitch
            if gap_ratio > 1.6:
                out.extend([""] * max(0, int(round(gap_ratio)) - 1))
        indent = int(round((x0 - anchor) / char_w)) if char_w > 0 else 0
        out.append(" " * max(0, indent) + text)
        prev_y0 = y0
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + "\n", {
        "lines": len(out),
        "char_width_pt": round(char_w, 3),
        "pitch_pt": round(pitch, 3),
    }


def region_object_census(page, rect):
    """枚举矩形区域内的矢量绘图与文字对象，返回 {"drawings": int,
    "texts": [str, ...]}。

    归属口径（覆盖核对的固定依据）：绘图按面积占比 ≥50% 落入区域归本
    图；文字行按行框中心落入区域归本图。区域外对象（其他图、表格
    边框、页眉装饰）有独立归属，不计入本图——不因邻接对象误计遗漏。
    """
    fitz = load_fitz()
    clip = fitz.Rect(rect)
    drawings = 0
    for item in page.get_drawings():
        area = item["rect"].width * item["rect"].height
        if area > 0:
            inter = fitz.Rect(item["rect"]) & clip
            if inter.width * inter.height >= 0.5 * area:
                drawings += 1
        else:
            # 零面积线对象（坐标轴、刻度线等）：与区域相交即归属
            if fitz.Rect(item["rect"]).intersects(clip):
                drawings += 1
    texts = set()
    for block in page.get_text("blocks"):
        if block[6] != 0 or not (block[4] or "").strip():
            continue
        center_x = (block[0] + block[2]) / 2
        center_y = (block[1] + block[3]) / 2
        if clip.contains(fitz.Point(center_x, center_y)):
            texts.update(line.strip() for line in block[4].splitlines()
                         if line.strip())
    return {"drawings": drawings, "texts": sorted(texts)}


def render_figure(page, rect, dpi, path):
    """按页面矩形与 dpi 口径把矢量图区域渲染为 PNG 并落盘。"""
    fitz = load_fitz()
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(rect))
    pix.save(path)
    return pix.width, pix.height


def norm_words(text):
    """对账比较口径：全部空白折叠为单空格后的词序列（逐词相等比较）。"""
    return " ".join(text.split())


def load_checklist(path):
    import json
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        fail("裁决清单不可读: %s（%s）" % (path, exc))
    if not isinstance(payload, dict) \
            or payload.get("version") != CHECKLIST_VERSION:
        fail("裁决清单版本无效: %s（需 version=%d 的单一 JSON）"
             % (path, CHECKLIST_VERSION))
    return payload


def dump_json(payload, path):
    import json
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
        handle.write("\n")
