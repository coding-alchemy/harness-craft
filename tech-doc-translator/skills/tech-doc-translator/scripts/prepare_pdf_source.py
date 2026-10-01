#!/usr/bin/env python3
"""PDF 源处理统一入口：勘察（inspect）与按裁决物化（materialize）。

用法：
    python3 prepare_pdf_source.py inspect <pdf> --pages <范围> --output <目录>
    python3 prepare_pdf_source.py materialize <pdf> --checklist <清单.json> \
        --output <源Markdown路径>
    python3 prepare_pdf_source.py extract-code <pdf> --checklist <清单.json> \
        --output <golden目录>
    python3 prepare_pdf_source.py extract-figures <pdf> --checklist <清单.json> \
        --output <图片目录>

inspect：记录源身份（realpath/sha256/字节数/页数/页面尺寸/旋转/坐标口径）
与环境探测（解释器、PyMuPDF 版本、实际兼容性；依赖缺失清晰报错，绝不
自动安装）；逐页统计文本层覆盖、嵌入位图、矢量绘图、批注与链接（文件名/
元数据声明不作事实依据）；给出 text / scanned / mixed / undetermined
正文类型判定及证据；逐页落盘保版面与通读两种文本快照；输出标题、图题、
表格页、脚注候选（含页码与位置，候选为空显式标记为空）；位图素材（D3）
与文本层公式（D4）记录页码位置为待处理项，不静默删除、不自动 OCR。
首次运行生成 adjudication_checklist.json 草稿；再次勘察保留既有裁决
（blocks/rejected/pending/reading_order 等），只刷新身份、环境与候选。

materialize：按已裁决清单 blocks 顺序物化源 Markdown 草稿；每块可回页
（页面/区域定位），物化时重新从 PDF 区域提取正文；已固化的 code_region
块由 golden 生成源围栏（语言信息取块 lang，缺省裸围栏，弯引号等字符
原样保留），未固化代码区域与其余未闭合素材（图形区域、位图素材、公式）
写入显式 [PENDING-*] 标记；正文类型为
scanned/undetermined 的源拒绝物化（不能宣称全文准备完成），mixed 源
在需 OCR 区域未获用户明确处置前拒绝物化。物化同时写出
<output>.blocks.json（块 → Markdown 行区间映射，供独立对账定位）。

extract-code：把清单中已裁决的 code_region 块按页/矩形从文本层程序化
提取为 golden（char 级重建：行首缩进由首字符 x 偏移/等宽字宽换算，
空行按行距重建，区域外页眉/分页符由裁剪矩形排除；逐字节保留字符与
行序，无行尾空白剥除）。块与 golden 的对应须在清单中显式记录
（golden 文件名，块 id ↔ golden 不凭图号/顺序猜测）；提取后 golden 的
sha256 与取舍口径回写清单，golden 经主 Agent 回源确认后才成为固化基准。

清单为带版本（version=1）单一 JSON，schema 见 references/pdf_source.md。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pdf_source import (
    CHECKLIST_VERSION,
    MIN_BODY_CHARS,
    MIN_READABLE_RATIO,
    check_adjudication_conflict,
    check_type_migration,
    classify_pages,
    dump_json,
    extract_code_region,
    extract_region_text,
    fail,
    file_sha256,
    load_checklist,
    load_fitz,
    norm_words,
    page_bitmap_regions,
    page_facts,
    parse_pages_arg,
    probe_environment,
    region_object_census,
    render_figure,
    snapshot_layout,
    snapshot_reading,
    source_identity,
    structure_candidates,
)

DEFAULT_FIGURE_DPI = 200

LAYOUT_SNAPSHOT = "snapshots_layout.txt"
READING_SNAPSHOT = "snapshots_reading.txt"
CANDIDATES_NAME = "structure_candidates.json"
REPORT_NAME = "inspection_report.json"
CHECKLIST_NAME = "adjudication_checklist.json"

# 既有解析 Markdown 风格的显式待处理标记（校验器据此核对未闭合素材）
PENDING_MARKERS = {
    "code_region": "PENDING-CODE",
    "figure_region": "PENDING-FIGURE",
    "bitmap": "PENDING-BITMAP",
    "formula": "PENDING-FORMULA",
    "ocr_region": "PENDING-OCR",
}


def _ensure_output_dir(path):
    os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        fail("输出目录不可写: %s" % path)


def _empty_marked(candidates):
    """候选为空显式标记为空，不得当作零。"""
    marked = {}
    for key, items in candidates.items():
        marked[key] = items
        marked[key + "_empty"] = not items
    return marked


def cmd_inspect(args):
    fitz = load_fitz()
    if not os.path.isfile(args.pdf):
        fail("PDF 源不存在: %s" % args.pdf)
    doc = fitz.open(args.pdf)
    pages = parse_pages_arg(args.pages, doc.page_count)
    identity = source_identity(args.pdf, doc)
    environment = probe_environment()
    facts = [page_facts(doc[p - 1]) for p in pages]
    doc_type, evidence = classify_pages(facts)
    candidates = structure_candidates(doc, pages)

    _ensure_output_dir(args.output)
    layout_path = os.path.join(args.output, LAYOUT_SNAPSHOT)
    reading_path = os.path.join(args.output, READING_SNAPSHOT)
    with open(layout_path, "w", encoding="utf-8") as handle:
        handle.write(snapshot_layout(doc, pages))
    with open(reading_path, "w", encoding="utf-8") as handle:
        handle.write(snapshot_reading(doc, pages))
    candidates_path = os.path.join(args.output, CANDIDATES_NAME)
    dump_json(_empty_marked(candidates), candidates_path)

    classification = {"type": doc_type, "evidence": evidence}
    # 待处理项（不自动执行 OCR）：页级=文本层不可用页定位；页内=无文本
    # 层覆盖的嵌入位图区域，一律为"待裁决"候选（用途由主 Agent 对照原页
    # 确定），不参与正文类型判定
    pending = []
    covered_pages = set()
    for f in facts:
        if f["chars"] < MIN_BODY_CHARS \
                or f["readable_ratio"] < MIN_READABLE_RATIO:
            pending.append({
                "kind": "ocr_region",
                "page": f["page"],
                "rect": [0, 0, f["width_pt"], f["height_pt"]],
                "status": "正文需 OCR：仅用户明确要求且使用宿主 OCR 工具，"
                          "本链路不自动执行",
            })
            covered_pages.add(f["page"])
    for pno in pages:
        if pno in covered_pages:
            continue  # 该页已有整页级定位，区域级重复
        for region in page_bitmap_regions(doc[pno - 1]):
            pending.append({
                "kind": "bitmap_region",
                "page": pno,
                "rect": region["rect"],
                "area_ratio": region["area_ratio"],
                "status": "待裁决：插图素材或需 OCR 正文区域，由主 Agent "
                          "对照原页确定并记录依据；裁决前不得按全文完成交付",
                "basis": region["basis"],
            })
    report = {
        "version": CHECKLIST_VERSION,
        "source": identity,
        "environment": environment,
        "scope": pages,
        "classification": classification,
        "pages": facts,
        "candidates": _empty_marked(candidates),
        "artifacts": {
            "layout_snapshot": os.path.basename(layout_path),
            "reading_snapshot": os.path.basename(reading_path),
            "candidates": os.path.basename(candidates_path),
            "checklist": CHECKLIST_NAME,
        },
    }
    report_path = os.path.join(args.output, REPORT_NAME)
    dump_json(report, report_path)

    # 裁决清单：首次生成草稿；再次勘察保留既有裁决，只刷新事实与候选
    checklist_path = os.path.join(args.output, CHECKLIST_NAME)
    checklist = {
        "version": CHECKLIST_VERSION,
        "source": identity,
        "environment": environment,
        "scope": pages,
        "classification": classification,
        "candidates": _empty_marked(candidates),
        "blocks": [],
        "rejected": [],
        "pending": pending,
        "reading_order": {"adjudicated": False, "basis": ""},
        "conventions": {
            "references": "english-by-default(D1，可逐项目覆盖)",
            "strong_tokens": [],
        },
    }
    preserved = []
    if os.path.isfile(checklist_path):
        old = load_checklist(checklist_path)
        for key in ("blocks", "rejected", "reading_order",
                    "conventions"):
            if old.get(key):
                checklist[key] = old[key]
                preserved.append(key)
        if old.get("pending"):
            # 按稳定区域身份 (page, rect) 合并：旧项裁决状态保留、已对应
            # 区域的同源候选抑制、新发现追加、旧有键未发现者保留
            checklist["pending"] = _merge_pending(old["pending"], pending)
            preserved.append("pending")
        if old.get("classification", {}).get("adjudicated"):
            checklist["classification"]["adjudicated"] = \
                old["classification"]["adjudicated"]
            preserved.append("classification.adjudicated")
            # 机器 classify_pages 的新判定只写入勘察报告作候选，不回写
            # 清单：已裁决时继承裁决类型值（含依据），随 stale 冻结待重核
            if "type" in old["classification"]:
                checklist["classification"]["type"] = \
                    old["classification"]["type"]
                preserved.append("classification.type")
        if old.get("stale"):
            # stale 不因再次勘察消失：源/范围变化后的重核只能由显式的
            # revalidate 依据清除，二次勘察继承旧标记
            checklist["stale"] = old["stale"]
            preserved.append("stale")
        if preserved:
            # 裁决身份绑定：继承旧绑定；旧版清单回填为旧源身份/范围
            # （旧裁决即针对旧源作出）；全新清单不写该字段
            bound = old.get("adjudicated_against")
            if not isinstance(bound, dict):
                bound = {
                    "sha256": (old.get("source") or {}).get("sha256"),
                    "scope": old.get("scope"),
                }
            checklist["adjudicated_against"] = bound
            if old.get("revalidate"):
                checklist["revalidate"] = old["revalidate"]
        old_source = old.get("source") or {}
        if preserved and (
                old_source.get("sha256") not in (None, identity["sha256"])
                or old.get("scope") != pages):
            stale_fields = list(preserved)
            checklist["stale"] = {
                "reason": "源/范围已变化（sha256 %s→%s，scope %s→%s），"
                          "保留的旧裁决须逐项重新核对"
                          % (str(old_source.get("sha256"))[:12],
                             identity["sha256"][:12], old.get("scope"),
                             pages),
                "fields": stale_fields,
            }
            print("WARN: %s；已标记 stale: %s" % (checklist["stale"]["reason"],
                                                "、".join(stale_fields)),
                  file=sys.stderr)
        dump_json(checklist, checklist_path)
        print("勘察完成（已保留既有裁决: %s）" % "、".join(preserved))
    else:
        dump_json(checklist, checklist_path)
        print("勘察完成（已生成裁决清单草稿，候选待主 Agent 逐项裁决）")

    print("正文类型: %s" % doc_type)
    for item in evidence[:1]:
        print("  证据: %s" % item)
    print("报告: %s" % report_path)
    print("快照: %s / %s" % (layout_path, reading_path))
    return 0


def cmd_extract_code(args):
    """按裁决清单把 code_region 块程序化提取为 golden 并回写清单。"""
    fitz = load_fitz()
    if not os.path.isfile(args.pdf):
        fail("PDF 源不存在: %s" % args.pdf)
    checklist = load_checklist(args.checklist)
    doc = fitz.open(args.pdf)
    identity = source_identity(args.pdf, doc)
    source = checklist.get("source") or {}
    if source.get("sha256") and source["sha256"] != identity["sha256"]:
        fail("源 PDF 身份与清单不符（sha256 %s vs %s）：源变化后旧裁决"
             "须重新核对，拒绝提取"
             % (str(source.get("sha256"))[:12], identity["sha256"][:12]))
    code_blocks = [b for b in checklist.get("blocks") or []
                   if b.get("type") == "code_region"]
    if not code_blocks:
        fail("清单没有任何 code_region 块（候选不是权威，须先逐项裁决）")
    names = [b.get("golden") for b in code_blocks]
    if any(not n or not isinstance(n, str) for n in names):
        fail("每个 code_region 块必须在清单中显式记录 golden 文件名"
             "（块 id ↔ golden 对应不凭图号/顺序猜测）")
    if len(set(names)) != len(names):
        fail("code_region 块的 golden 文件名重复: %s"
             % sorted({n for n in names if names.count(n) > 1}))
    for block in code_blocks:
        if not block.get("page") or not block.get("rect"):
            fail("code_region 块 %s 缺少 page/rect，无法回页定位"
                 % block.get("id"))
        text, info = extract_code_region(doc[block["page"] - 1],
                                         block["rect"])
        if not text.strip():
            fail("code_region 块 %s 区域提取为空（page=%s rect=%s）："
                 "缺失不能当作零，须回源核对区域"
                 % (block.get("id"), block.get("page"), block.get("rect")))
        path = os.path.join(args.output, block["golden"])
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        digest = file_sha256(path)
        block["golden_sha256"] = digest
        block["golden_extraction"] = {
            "lines": info["lines"],
            "char_width_pt": info["char_width_pt"],
            "pitch_pt": info["pitch_pt"],
            "basis": "char 级重建：行首缩进按首字符 x 偏移/等宽字宽中位数"
                     "换算；空行按行距重建；区域外页眉/分页符由裁剪矩形"
                     "排除；逐字节保留字符与行序，无行尾空白剥除",
        }
        print("golden: %s（块 %s, page=%d, %d 行, sha256 %s…）"
              % (path, block.get("id"), block["page"], info["lines"],
                 digest[:12]))
    dump_json(checklist, args.checklist)
    print("已提取 %d 个 golden，对应关系与提取取舍回写清单" % len(code_blocks))
    return 0


def cmd_extract_figures(args):
    """按裁决清单把 figure_region 块渲染为 PNG 并回写来源身份。"""
    fitz = load_fitz()
    if not os.path.isfile(args.pdf):
        fail("PDF 源不存在: %s" % args.pdf)
    checklist = load_checklist(args.checklist)
    doc = fitz.open(args.pdf)
    identity = source_identity(args.pdf, doc)
    source = checklist.get("source") or {}
    if source.get("sha256") and source["sha256"] != identity["sha256"]:
        fail("源 PDF 身份与清单不符（sha256 %s vs %s）：源变化后旧裁决"
             "须重新核对，拒绝提取"
             % (str(source.get("sha256"))[:12], identity["sha256"][:12]))
    figure_blocks = [b for b in checklist.get("blocks") or []
                     if b.get("type") == "figure_region"]
    if not figure_blocks:
        fail("清单没有任何 figure_region 块（候选不是权威，须先逐项裁决）")
    names = [b.get("image") for b in figure_blocks]
    if any(not n or not isinstance(n, str) for n in names):
        fail("每个 figure_region 块必须在清单中显式记录 image 文件名"
             "（块 id ↔ 图片对应不凭图号/顺序猜测）")
    if len(set(names)) != len(names):
        fail("figure_region 块的 image 文件名重复: %s"
             % sorted({n for n in names if names.count(n) > 1}))
    for block in figure_blocks:
        if not block.get("page") or not block.get("rect"):
            fail("figure_region 块 %s 缺少 page/rect，无法回页定位"
                 % block.get("id"))
        dpi = block.get("dpi", DEFAULT_FIGURE_DPI)
        path = os.path.join(args.output, block["image"])
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        width_px, height_px = render_figure(doc[block["page"] - 1],
                                            block["rect"], dpi, path)
        digest = file_sha256(path)
        census = region_object_census(doc[block["page"] - 1], block["rect"])
        width_pt = round(block["rect"][2] - block["rect"][0], 2)
        block["image_sha256"] = digest
        block["figure_extraction"] = {
            "dpi": dpi,
            "width_px": width_px,
            "height_px": height_px,
            "width_pt": width_pt,
            # 显示宽度口径沿用 images_display 合同：1 CSS px = 0.75 pt，
            # 物理宽度换算；渲染 dpi 只影响栅格分辨率，不充当显示宽度
            "display_width_px": round(width_pt / 0.75, 1),
            "display_basis": "physical-width（pt→CSS px，1px=0.75pt）",
            "census": census,
            "basis": "按清单裁决矩形与 dpi 渲染；归属覆盖核对对象=区域内"
                     "绘图(面积占比≥50%)与文字行(行框中心)；区域外对象"
                     "（其他图/表格边框/装饰）独立归属不计入",
        }
        print("figure: %s（块 %s, page=%d, dpi=%d, %dx%d, sha256 %s…）"
              % (path, block.get("id"), block["page"], dpi, width_px,
                 height_px, digest[:12]))
        print("  归属对象: 绘图 %d、文字 %d 行" % (census["drawings"],
                                                 len(census["texts"])))
    dump_json(checklist, args.checklist)
    print("已提取 %d 个图形，来源身份与覆盖核对依据回写清单" % len(figure_blocks))
    return 0


def _block_text(doc, block):
    """块正文：清单裁决值优先，否则按页/区域从 PDF 重新提取。"""
    if block.get("text"):
        return block["text"]
    page_no = block.get("page")
    rect = block.get("rect")
    if not page_no or not rect:
        fail("清单块 %r 缺少 text 或 page/rect，无法物化" % block.get("id"))
    return extract_region_text(doc[page_no - 1], rect)


def _pending_marker(kind, block):
    marker = PENDING_MARKERS.get(kind, "PENDING")
    parts = ["[%s" % marker]
    if block.get("page"):
        parts.append("page=%d" % block["page"])
    if block.get("rect"):
        parts.append("rect=(%s)" % ",".join("%.1f" % v
                                            for v in block["rect"]))
    label = block.get("label") or block.get("note")
    if label:
        parts.append(str(label))
    parts.append("待回源处理]")
    return " ".join(parts)


def _merge_pending(old_items, new_items):
    """按稳定区域身份 (page, 规范化 rect) 合并 pending（kind 不参与键）。

    同一 PDF 同一区域内位图出现的枚举是确定性的：已按区域身份对应
    的旧裁决项（无论 kind，如已转为 ocr_region 的项）会抑制再次勘察
    对同一物理区域重新产生的候选，不作为新未裁决项追加；rect 不同
    的位图出现是不同键，不误合并。无 rect 的项退回 (kind, page) 键。
    旧项裁决状态保留，旧有键但新勘察未再发现者保留原样（去留由重核
    裁决）。"""
    def key(item):
        rect = item.get("rect")
        if isinstance(rect, list) and rect:
            norm = json.dumps([round(float(v), 2) for v in rect])
        else:
            norm = None
        if norm is None:
            return (item.get("kind"), item.get("page"), None)
        return (item.get("page"), norm)

    merged = [dict(item) for item in old_items]
    existing = {key(item) for item in merged}
    for item in new_items:
        if key(item) not in existing:
            merged.append(item)
            existing.add(key(item))
    return merged


def _check_stale(checklist):
    """源/范围变化后保留的旧裁决：须主 Agent 逐项重新核对（清单记录
    revalidate 依据）并清除 stale 标记，否则物化/对账拒绝。"""
    stale = checklist.get("stale")
    if stale:
        fail("清单标记 stale: %s（字段: %s）；源/范围已变化，须重新核对"
             "旧裁决、记录依据并清除 stale 后再物化"
             % (stale.get("reason"), "、".join(stale.get("fields") or [])))


def _check_dispatchable(checklist):
    """未确定/扫描/混合（未处置）源不能物化，不能宣称全文准备完成。"""
    doc_type = checklist.get("classification", {}).get("type")
    if doc_type in ("scanned", "undetermined"):
        fail("正文类型为 %s，不能宣称全文准备完成，拒绝物化分派"
             "（需用户明确处置，如宿主 OCR 授权）" % doc_type)
    if doc_type == "mixed":
        unresolved = [p for p in checklist.get("pending", [])
                      if p.get("kind") == "ocr_region"
                      and p.get("adjudication") != "user-resolved"]
        if unresolved:
            fail("混合源存在未处置的需 OCR 区域: %s；不自动执行 OCR，"
                 "须用户明确处置并记录后重试"
                 % ", ".join("P%d" % p.get("page", "?")
                             for p in unresolved))


def cmd_materialize(args):
    fitz = load_fitz()
    if not os.path.isfile(args.pdf):
        fail("PDF 源不存在: %s" % args.pdf)
    checklist = load_checklist(args.checklist)
    checklist_dir = os.path.dirname(os.path.abspath(args.checklist))
    _check_stale(checklist)
    conflict = check_adjudication_conflict(checklist)
    if conflict:
        fail(conflict)
    migration = check_type_migration(checklist)
    if migration:
        fail(migration)
    _check_dispatchable(checklist)
    source = checklist.get("source") or {}
    blocks = checklist.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        fail("清单缺少已裁决 blocks（候选不是权威，须先逐项裁决）")
    for index, block in enumerate(blocks, start=1):
        block.setdefault("id", "b%03d" % index)
        block.setdefault("order", index)
    blocks = sorted(blocks, key=lambda b: b.get("order", 0))
    if not checklist.get("reading_order", {}).get("adjudicated"):
        fail("阅读顺序未记录裁决（reading_order.adjudicated=false），"
             "拒绝物化：跨栏顺序须以实际页面为准并在清单中记录依据")

    doc = fitz.open(args.pdf)
    identity = source_identity(args.pdf, doc)
    if source.get("sha256") and source["sha256"] != identity["sha256"]:
        fail("源 PDF 身份与清单不符（sha256 %s vs %s）：源变化后旧裁决"
             "须重新核对，拒绝物化"
             % (str(source.get("sha256"))[:12], identity["sha256"][:12]))

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    lines = []
    block_map = []
    for block in blocks:
        start_line = len(lines) + 1
        btype = block.get("type")
        if btype == "heading":
            level = block.get("level")
            text = (block.get("text") or "").strip()
            if not isinstance(level, int) or not (1 <= level <= 8) \
                    or not text:
                fail("清单块 %s 标题缺少 level/text" % block.get("id"))
            lines.append("#" * level + " " + text)
            lines.append("")
        elif btype == "paragraph":
            text = _block_text(doc, block)
            if not norm_words(text):
                fail("清单块 %s 区域提取为空（page=%s rect=%s）："
                     "缺失不能当作零，须回源核对区域"
                     % (block.get("id"), block.get("page"),
                        block.get("rect")))
            joiner = "\n" if block.get("keep_lines") else " "
            lines.append(joiner.join(text.split("\n")))
            lines.append("")
        elif btype == "figure_caption":
            text = (block.get("text") or "").strip()
            if not text:
                fail("清单块 %s 图题缺少 text" % block.get("id"))
            lines.append("**Figure: %s**" % text)
            lines.append("")
        elif btype == "table_region":
            lines.append("[TABLE page=%d rect=(%s)]"
                         % (block["page"],
                            ",".join("%.1f" % v for v in block["rect"])))
            text = _block_text(doc, block)
            lines.extend(text.split("\n"))
            lines.append("[TABLE-END]")
            lines.append("")
        elif btype == "code_region":
            golden_rel = block.get("golden")
            if not golden_rel:
                lines.append(_pending_marker(btype, block))
                lines.append("")
            else:
                golden_path = os.path.join(checklist_dir, golden_rel)
                if not os.path.isfile(golden_path):
                    fail("code_region 块 %s 的 golden 缺失: %s（须先运行 "
                         "extract-code 提取并回源确认）"
                         % (block.get("id"), golden_path))
                with open(golden_path, encoding='utf-8', newline='') as handle:
                    body = handle.read()
                if body.endswith("\n"):
                    body = body[:-1]
                lines.append("```" + (block.get("lang") or ""))
                lines.extend(body.split("\n"))
                lines.append("```")
                lines.append("")
        elif btype == "figure_region":
            image_rel = block.get("image")
            if not image_rel:
                lines.append(_pending_marker(btype, block))
                lines.append("")
            else:
                image_path = os.path.join(checklist_dir, image_rel)
                if not os.path.isfile(image_path):
                    fail("figure_region 块 %s 的图片缺失: %s（须先运行 "
                         "extract-figures 提取并回源确认）"
                         % (block.get("id"), image_path))
                declared = block.get("image_sha256")
                if declared and declared != file_sha256(image_path):
                    fail("figure_region 块 %s 的图片摘要与清单固化记录不符"
                         "（%s vs %s），资源被改动须重新回源确认"
                         % (block.get("id"), declared[:12],
                            file_sha256(image_path)[:12]))
                rel = os.path.relpath(os.path.abspath(image_path), out_dir)
                label = block.get("label") or ""
                lines.append("![%s](%s)" % (label, rel))
                lines.append("")
        elif btype in ("bitmap", "formula", "ocr_region"):
            lines.append(_pending_marker(btype, block))
            lines.append("")
        else:
            fail("清单块 %s 类型未知: %r" % (block.get("id"), btype))
        block_map.append({
            "id": block["id"],
            "type": block.get("type"),
            "page": block.get("page"),
            "rect": block.get("rect"),
            "md_lines": [start_line, len(lines) - 1
                         if lines and lines[-1] == "" else len(lines)],
        })
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")
    map_path = args.output + ".blocks.json"
    dump_json({"version": CHECKLIST_VERSION, "blocks": block_map}, map_path)
    # 解析期显示映射（两级映射的 PDF 分支）：每次图片出现保留来源
    # （页面/区域 + 提取口径）、资源身份与确定尺寸或未确定原因；
    # 代码清单转围栏不生成伪图片条目。
    display_entries = []
    display_undetermined = []
    occurrence = 0
    for block in blocks:
        if block.get("type") != "figure_region" or not block.get("image"):
            continue
        occurrence += 1
        image_abs = os.path.join(checklist_dir, block["image"])
        rel = os.path.relpath(os.path.abspath(image_abs), out_dir)
        extraction = block.get("figure_extraction") or {}
        width_px = extraction.get("display_width_px")
        entry = {
            "occurrence": occurrence,
            "image": rel,
            "sha256": block.get("image_sha256"),
            "width": ({"value": width_px, "unit": "px",
                       "basis": "physical-width", "reference": None}
                      if isinstance(width_px, (int, float)) else None),
            "source": {
                "pdf": source.get("realpath"),
                "pdf_sha256": source.get("sha256"),
                "page": block.get("page"),
                "rect": block.get("rect"),
                "dpi": extraction.get("dpi"),
                "resource_sha256": block.get("image_sha256"),
            },
            "source_block": block.get("id"),
        }
        if entry["width"] is None:
            entry.pop("width")
            display_undetermined.append({
                "occurrence": occurrence, "image": rel,
                "reason_code": "unresolved-size",
                "reason": "区域物理宽度不可确定（清单未记录 "
                          "display_width_px）",
                "source_block": block.get("id"),
            })
        display_entries.append(entry)
    if display_entries or display_undetermined:
        dump_json({
            "version": 1,
            "markdown": os.path.basename(args.output),
            "family": "pdf-source",
            "pdf": source.get("realpath"),
            "pdf_sha256": source.get("sha256"),
            "scope": checklist.get("scope"),
            "entries": display_entries,
            "undetermined": display_undetermined,
        }, args.output + ".images_display.json")
    print("源 Markdown 草稿: %s（%d 块）" % (args.output, len(block_map)))
    print("块区间映射: %s" % map_path)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="PDF 源处理统一入口（勘察 / 按裁决物化）")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="源身份、类型判定、双快照与结构候选")
    inspect.add_argument("pdf", help="只读 PDF 源")
    inspect.add_argument("--pages", default="all",
                         help="页面范围（默认 all；如 1-3,7）")
    inspect.add_argument("--output", required=True, help="输出目录")
    inspect.set_defaults(func=cmd_inspect)

    materialize = sub.add_parser(
        "materialize", help="按已裁决清单物化源 Markdown 草稿")
    materialize.add_argument("pdf", help="只读 PDF 源")
    materialize.add_argument("--checklist", required=True,
                             help="裁决清单 JSON")
    materialize.add_argument("--output", required=True,
                             help="源 Markdown 输出路径")
    materialize.set_defaults(func=cmd_materialize)

    extract = sub.add_parser(
        "extract-code", help="按裁决把 code_region 块提取为 golden")
    extract.add_argument("pdf", help="只读 PDF 源")
    extract.add_argument("--checklist", required=True, help="裁决清单 JSON")
    extract.add_argument("--output", required=True, help="golden 输出目录")
    extract.set_defaults(func=cmd_extract_code)

    figures = sub.add_parser(
        "extract-figures", help="按裁决把 figure_region 块渲染为 PNG")
    figures.add_argument("pdf", help="只读 PDF 源")
    figures.add_argument("--checklist", required=True, help="裁决清单 JSON")
    figures.add_argument("--output", required=True,
                         help="图片输出目录（块 image 相对路径的基点）")
    figures.set_defaults(func=cmd_extract_figures)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
