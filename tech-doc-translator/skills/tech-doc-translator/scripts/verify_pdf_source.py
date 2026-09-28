#!/usr/bin/env python3
"""PDF → 源 Markdown 独立对账（结构/区域/代码/图形）+ 译文机器硬检查。

用法：
    python3 verify_pdf_source.py <pdf> --checklist <清单.json> \
        --source-md <源Markdown> [--block-map <映射.json>] \
        [--translation <译文.md>]

独立于物化操作重新打开源 PDF：核对源身份（realpath/sha256/页数）与清单
一致；按清单逐块定位重读页面区域内容，与源 Markdown 的对应行区间
（materialize 写出的 <源Markdown>.blocks.json 仅作定位）独立对账。
提供 --translation 时追加译文机器硬检查（权威标题层级/原题/顺序、
代码围栏逐字节、图片来源身份与次序、脚注相对权威清单覆盖、强 token
逐字命中、R5 裁决值落实）；FAIL 区分【产物】与【口径】问题，机器
PASS 不登记语义复核完成。诊断中文；退出码 0 = PASS，1 = FAIL。

- 标题：清单裁决 (层级, 原题) 与源 Markdown 标题按出现顺序逐项对照；
- 正文/表格区域：重新从 PDF 区域提取的正文（按词归一口径）必须与
  源 Markdown 对应区间逐词相等；
- 代码 golden：源 Markdown 围栏正文取原始字节切片（共享
  scan_code_fences，不做行尾空白剥除/归一化），与清单显式对应
  （块 id ↔ golden 文件，不凭图号/顺序猜测）的 golden 按块逐字节一致；
  改字符、弯引号、缩进、换块或添加一处行尾空格均 FAIL 并定位块与
  差异行列；golden 摘要同时与清单固化记录核对；
- 图形：源 Markdown 图片引用按块区间定位（漏图/多余定位），实际文件
  PNG 魔数有效且字节摘要与清单固化的来源身份一致（同名换图 FAIL，
  期望身份来自清单固定依据，不从待验文件重算）；归属覆盖核对按当前
  PDF 区域重建对象普查（绘图/文字行），与清单固化普查不符（删目标
  绘图或文字标签）FAIL 并定位差异；其他图、表格边框与装饰在区域外
  独立归属，不计入目标图；
- 未闭合素材：[PENDING-*] 标记必须在对应区间显式存在且类型一致，
  清单登记的待处理项不得从源 Markdown 静默删除；
- 覆盖：源 Markdown 每个非空行都必须落在某个块区间内（漏区域/多余
  定位），区间不得重叠、块顺序不得与清单裁决顺序不一致。

未解释的缺失、多余或错位（含阅读顺序换块）一律 FAIL 并定位页/区域
与 Markdown 行号，阻断分派。图片身份核对属后续 ticket，本入口不做。
诊断中文；退出码 0 = PASS，1 = FAIL。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pdf_source import (
    CHECKLIST_VERSION,
    check_adjudication_conflict,
    check_type_migration,
    extract_region_text,
    fail,
    file_sha256,
    load_checklist,
    load_fitz,
    norm_words,
    region_object_census,
    source_identity,
)
from _verification import (
    check_image_file,
    compare_code_fences,
    compare_headings,
    count_token,
    fenced_line_numbers,
    heading_entries,
    image_references,
    scan_code_fences,
)

_PENDING_LINE_RE = re.compile(r"^\[(PENDING-[A-Z]+)")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _byte_diff(expected, actual):
    """逐字节比较的首个差异定位（行/列与两侧原文）。"""
    elines = expected.split("\n")
    alines = actual.split("\n")
    for index in range(min(len(elines), len(alines))):
        if elines[index] != alines[index]:
            e, a = elines[index], alines[index]
            shared = min(len(e), len(a))
            col = next((j for j in range(shared) if e[j] != a[j]), shared)
            return "第 %d 行第 %d 列: golden %r vs 源围栏 %r" % (
                index + 1, col + 1, e, a)
    return "行数不一致: golden %d 行 vs 源围栏 %d 行" % (
        len(elines), len(alines))


def _load_block_map(path, md_path):
    if path is None:
        path = md_path + ".blocks.json"
    if not os.path.isfile(path):
        fail("缺少块区间映射: %s（须先运行 materialize 生成；映射只作"
             "定位，对账内容独立重读 PDF）" % path)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        fail("块区间映射不可读: %s（%s）" % (path, exc))
    if not isinstance(payload, dict) \
            or payload.get("version") != CHECKLIST_VERSION \
            or not isinstance(payload.get("blocks"), list):
        fail("块区间映射版本/结构无效: %s（需 version=%d 与 blocks 数组）"
             % (path, CHECKLIST_VERSION))
    return payload["blocks"]


def _md_headings(text):
    """源 Markdown 标题 (行号, 层级, 原文) 有序列表；排除代码围栏内行。"""
    entries = []
    fenced = fenced_line_numbers(text)
    for line_no, line in enumerate(text.split("\n"), start=1):
        if line_no in fenced:
            continue
        match = re.match(r"^(#{1,8})\s+(.+)$", line.rstrip("\r"))
        if match:
            entries.append((line_no, len(match.group(1)),
                            match.group(2).strip()))
    return entries


def _figure_fails(doc, block, span, md_text, md_dir, label):
    """figure_region 块的图片引用、来源身份与归属覆盖核对。"""
    fails = []
    refs = [(line_no, src) for line_no, src in image_references(md_text)
            if span[0] <= line_no <= span[1]]
    if len(refs) != 1:
        fails.append("%s: 图片引用数 %d（期望 1；漏图/多余即错位，不凭总数"
                     "反推）" % (label, len(refs)))
        return fails
    _line_no, src = refs[0]
    if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) or os.path.isabs(src):
        fails.append("%s: 图片引用不允许外链或绝对路径: %r" % (label, src))
        return fails
    path = os.path.normpath(os.path.join(md_dir, src))
    if not os.path.isfile(path):
        fails.append("%s: 图片交付缺失: %s" % (label, src))
        return fails
    with open(path, "rb") as handle:
        if handle.read(8) != _PNG_MAGIC:
            fails.append("%s: 图片非有效 PNG（魔数不符）: %s" % (label, src))
            return fails
    # 来源身份：期望摘要取自清单固定依据，不从待验文件重算后放行
    expected_sha = block.get("image_sha256")
    if expected_sha:
        actual_sha = file_sha256(path)
        if actual_sha != expected_sha:
            fails.append("%s: 同名换图/资源不符: %s 实际摘要 %s… 与清单固化"
                         "身份 %s… 不一致"
                         % (label, src, actual_sha[:12], expected_sha[:12]))
            return fails
    extraction = block.get("figure_extraction") or {}
    expected_census = extraction.get("census")
    if expected_census and block.get("page") and block.get("rect"):
        actual = region_object_census(doc[block["page"] - 1], block["rect"])
        if actual["drawings"] != expected_census.get("drawings"):
            fails.append("%s: 归属覆盖核对失败: 区域内绘图 %d 个 vs 清单固化 "
                         "%s 个（目标绘图被删改或区域漂移）"
                         % (label, actual["drawings"],
                            expected_census.get("drawings")))
        missing = sorted(set(expected_census.get("texts") or [])
                         - set(actual["texts"]))
        extra = sorted(set(actual["texts"])
                       - set(expected_census.get("texts") or []))
        if missing or extra:
            fails.append("%s: 归属覆盖核对失败: 图中文字标签差异（缺失 %s；"
                         "新增 %s）" % (label, missing[:3], extra[:3]))
    return fails


def run_translation_checks(checklist, source_md_text, translation_text,
                           translation_dir):
    """源 Markdown → 译文硬检查；返回 (产物 fails, 口径 fails, warns)。

    全部复用共享比较器（compare_headings/compare_code_fences/
    strong_token_report 与共享图片事实），不复制比较规则。期望身份
    一律取自清单固定依据，不从待验译文重算。机器硬检查不登记语义复核。
    """
    product = []
    convention = []
    warns = []
    blocks = sorted(checklist.get("blocks") or [],
                    key=lambda b: b.get("order", 0))
    conventions = checklist.get("conventions") or {}

    # 标题：权威清单 (层级, 原题) 有序对照；中文后缀按边界规则允许
    expected = [(0, b.get("level"), (b.get("text") or "").strip())
                for b in blocks if b.get("type") == "heading"]
    actual = heading_entries(translation_text)
    product += compare_headings(expected, actual,
                                src_label="权威清单", doc_label="译文")

    # 代码：译文围栏与源文按出现顺序逐块对照（正文逐字节）
    product += compare_code_fences(
        scan_code_fences(source_md_text).blocks,
        scan_code_fences(translation_text).blocks,
        src_label="源文", doc_label="译文")

    # 图片：出现次序与来源身份（清单固化摘要）逐项核对
    figure_blocks = [b for b in blocks
                     if b.get("type") == "figure_region"
                     and b.get("image_sha256")]
    refs = image_references(translation_text)
    if len(refs) != len(figure_blocks):
        product.append("【产物】译文图片出现 %d 次 vs 权威清单 %d 次"
                       "（漏图/多余，不凭总数反推）"
                       % (len(refs), len(figure_blocks)))
    else:
        for order, (block, (line_no, src)) in enumerate(
                zip(figure_blocks, refs), start=1):
            tag = "图片出现 #%d（清单块 %s）L%d" % (order, block.get("id"),
                                                   line_no)
            if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) \
                    or os.path.isabs(src):
                product.append("【产物】%s: 外链或绝对路径不允许: %r"
                               % (tag, src))
                continue
            path = os.path.normpath(os.path.join(translation_dir, src))
            if not os.path.isfile(path):
                product.append("【产物】%s: 交付缺失: %s" % (tag, src))
                continue
            ok, _kind, reason = check_image_file(path)
            if not ok:
                product.append("【产物】%s: 类型异常: %s（%s）"
                               % (tag, src, reason))
                continue
            expected_sha = block["image_sha256"]
            actual_sha = file_sha256(path)
            if actual_sha != expected_sha:
                product.append("【产物】%s: 同名换图/乱序: %s 实际摘要 %s… "
                               "与清单固化身份 %s… 不一致"
                               % (tag, src, actual_sha[:12],
                                  expected_sha[:12]))

    # 脚注：相对权威清单覆盖（清单 footnote_label），整对删除也检出，
    # 不以译文内部配对代替源覆盖
    for block in blocks:
        label = block.get("footnote_label")
        if not label:
            continue
        ref = re.compile(r"\[\^%s\](?!:)" % re.escape(str(label)))
        deff = re.compile(r"^\[\^%s\]:" % re.escape(str(label)), re.M)
        if not ref.search(translation_text):
            product.append("【产物】脚注 [^%s] 引用缺失（相对权威清单，"
                           "整对删除也须检出）" % label)
        if not deff.search(translation_text):
            product.append("【产物】脚注 [^%s] 定义缺失（相对权威清单）"
                           % label)

    # 强 token（D2）：清单显式提供；PDF 译文路线的"逐字命中"按出现
    # 语义（A5 缺失即 FAIL，标识符与含单位数值均须覆盖）：译文合法改写
    # 造成的计数漂移（如译文中文化后源侧重复出现减少）不构成缺失。
    # 未配置明示"未检查"（WARN，不阻断），不构成数字复核完成的证据。
    tokens = list(conventions.get("strong_tokens") or [])
    if not tokens:
        warns.append("【口径】强 token: 未配置项目指定 token，此项未检查"
                     "，不能作为数字复核完成的证据")
    else:
        missing = [t for t in tokens
                   if count_token(translation_text, t) == 0]
        for token in missing:
            product.append("【产物】强 token 缺失 %r: 译文未逐字命中"
                           "（标识符/含单位数值覆盖）" % token)

    # 文本层缺陷（R5）：裁决值必须在译文落实（译注要求记入清单）
    for defect in conventions.get("defects") or []:
        if defect.get("kind") == "url-text-layer":
            adjudicated = defect.get("adjudicated") or ""
            if adjudicated and adjudicated not in translation_text:
                product.append("【产物】R5 裁决值未落实: %r（文本层缺陷，"
                               "须按清单记录加译注）" % adjudicated)
    return product, convention, warns


def run_verification(pdf_path, checklist, md_text, block_map,
                     checklist_dir=None, md_dir=None,
                     translation_text=None, translation_dir=None):
    """独立对账核心；返回 (fails, warns)。CLI 与后续预检共用。

    checklist_dir 为 golden/图片相对路径（块显式记录）的解析基点，
    md_dir 为源 Markdown 图片引用的解析基点，默认取 cwd；提供
    translation_text 时追加译文硬检查（机器硬检查，不登记语义复核）。
    """
    if checklist_dir is None:
        checklist_dir = os.getcwd()
    if md_dir is None:
        md_dir = os.getcwd()
    fails = []
    warns = []
    fitz = load_fitz()
    doc = fitz.open(pdf_path)
    identity = source_identity(pdf_path, doc)
    declared = checklist.get("source") or {}
    if declared.get("sha256") and declared["sha256"] != identity["sha256"]:
        fails.append("源身份不符: 清单 sha256 %s vs 实际 %s（源变化后旧"
                     "裁决须重新核对）"
                     % (declared["sha256"][:12], identity["sha256"][:12]))
    if declared.get("realpath") \
            and os.path.realpath(declared["realpath"]) != identity["realpath"]:
        fails.append("源 realpath 与清单不符: %s vs %s"
                     % (declared["realpath"], identity["realpath"]))
    stale = checklist.get("stale")
    if stale:
        fails.append("清单标记 stale: %s（字段: %s）；源/范围已变化，旧裁决"
                     "须重新核对后才能对账"
                     % (stale.get("reason"),
                        "、".join(stale.get("fields") or [])))
    conflict = check_adjudication_conflict(checklist)
    if conflict:
        fails.append(conflict)
    migration = check_type_migration(checklist)
    if migration:
        fails.append(migration)
    doc_type = (checklist.get("classification") or {}).get("type")
    if doc_type in ("scanned", "undetermined"):
        fails.append("正文类型为 %s，不能宣称全文准备完成" % doc_type)

    lines = md_text.split("\n")
    blocks = sorted(checklist.get("blocks") or [],
                    key=lambda b: b.get("order", 0))
    by_id = {b.get("id"): b for b in blocks}
    if not blocks:
        fails.append("清单没有任何已裁决块（候选不是权威）")
    scope = checklist.get("scope")
    if isinstance(scope, list) and scope:
        for block in blocks:
            page = block.get("page")
            if isinstance(page, int) and page not in scope:
                fails.append("清单块 %s（%s, page=%s）落在声明范围 %s 之外"
                             "（源/范围变化后旧裁决须重新核对）"
                             % (block.get("id"), block.get("type"), page,
                                scope))

    # 块顺序与区间：重叠、乱序、映射不一致即错位
    ranges = []
    prev_end = 0
    for entry in block_map:
        block = by_id.get(entry.get("id"))
        span = entry.get("md_lines")
        if block is None:
            fails.append("块映射 %r 不在清单裁决块中（多余块）"
                         % entry.get("id"))
            continue
        if (not isinstance(span, list) or len(span) != 2
                or not all(isinstance(v, int) for v in span)
                or not (1 <= span[0] <= span[1] <= len(lines))):
            fails.append("块 %s 的 Markdown 行区间非法: %r"
                         % (entry.get("id"), span))
            continue
        if span[0] <= prev_end:
            fails.append("块 %s 行区间 L%d-%d 与前块重叠或乱序（阅读顺序"
                         "换块必须解释）" % (entry["id"], span[0], span[1]))
        prev_end = span[1]
        ranges.append((block, span))
    mapped_ids = {e.get("id") for e in block_map}
    for block in blocks:
        if block.get("id") not in mapped_ids:
            fails.append("清单块 %s（%s, page=%s）在源 Markdown 中没有"
                         "对应区间（漏区域）"
                         % (block.get("id"), block.get("type"),
                            block.get("page")))
    # 覆盖：每个非空行必须属于某个块区间
    covered = set()
    for _block, span in ranges:
        covered.update(range(span[0], span[1] + 1))
    for line_no, line in enumerate(lines, start=1):
        if line.strip() and line_no not in covered:
            fails.append("源 Markdown L%d 不属于任何已裁决块区间（多余或"
                         "漏裁决）: %r" % (line_no, line[:60]))

    # 逐块独立重读 PDF 对账
    heading_expected = []
    for block, span in ranges:
        btype = block.get("type")
        label = "块 %s（%s, page=%s, L%d-%d）" % (
            block.get("id"), btype, block.get("page"), span[0], span[1])
        slice_lines = lines[span[0] - 1:span[1]]
        if btype == "heading":
            level, text = block.get("level"), (block.get("text") or "").strip()
            found = re.match(r"^(#{1,8})\s+(.+)$",
                             slice_lines[0].rstrip("\r")) if slice_lines else None
            if not found:
                fails.append("%s: 期望标题 %r，实际区间首行不是标题: %r"
                             % (label, text, slice_lines[0][:60]
                                if slice_lines else ""))
            else:
                if len(found.group(1)) != level:
                    fails.append("%s: 标题层级不符: 期望 H%d vs 实际 H%d"
                                 % (label, level, len(found.group(1))))
                if found.group(2).strip() != text:
                    fails.append("%s: 标题不一致: 期望 %r vs 实际 %r"
                                 % (label, text, found.group(2).strip()))
            heading_expected.append((level, text, block, span))
        elif btype in ("paragraph", "table_region"):
            if not block.get("page") or not block.get("rect"):
                fails.append("%s: 缺少 page/rect，无法回页定位" % label)
                continue
            expected = extract_region_text(doc[block["page"] - 1],
                                           block["rect"])
            joiner = "\n" if block.get("keep_lines") else " "
            expected = joiner.join(expected.split("\n"))
            if btype == "table_region":
                body = [ln for ln in slice_lines
                        if not re.match(r"^\[(TABLE|TABLE-END)", ln.strip())]
                actual = "\n".join(body)
            else:
                actual = "\n".join(slice_lines)
            if norm_words(expected) != norm_words(actual):
                fails.append("%s: 区域对账不一致: PDF 重读 %r vs 源 Markdown "
                             "%r" % (label, norm_words(expected)[:80],
                                     norm_words(actual)[:80]))
        elif btype == "figure_caption":
            text = (block.get("text") or "").strip()
            joined = norm_words("\n".join(slice_lines)).strip("*")
            if norm_words(text) not in joined:
                fails.append("%s: 图题 %r 不在源 Markdown 对应区间: %r"
                             % (label, text, joined[:80]))
        elif btype == "code_region":
            golden_rel = block.get("golden")
            if golden_rel:
                golden_path = os.path.join(checklist_dir, golden_rel)
                if not os.path.isfile(golden_path):
                    fails.append("%s: golden 缺失: %s（未闭合素材不得静默"
                                 "删除）" % (label, golden_path))
                    continue
                declared_digest = block.get("golden_sha256")
                if declared_digest \
                        and declared_digest != file_sha256(golden_path):
                    fails.append("%s: golden 摘要与清单固化记录不符（%s vs "
                                 "%s），基准被改动须重新回源确认"
                                 % (label, declared_digest[:12],
                                    file_sha256(golden_path)[:12]))
                    continue
                with open(golden_path, encoding='utf-8', newline='') as handle:
                    expected = handle.read()
                if expected.endswith("\n"):
                    expected = expected[:-1]
                # 原始字节切片比较：不得经 extract_region_text 的
                # rstrip 通道，行尾空白差异必须可检出
                fences = [fence for fence in scan_code_fences(md_text).blocks
                          if span[0] <= fence.start_line <= span[1]]
                if len(fences) != 1:
                    fails.append("%s: 对应围栏数 %d（期望 1，golden ↔ 块"
                                 "显式对应不凭顺序猜测）" % (label, len(fences)))
                    continue
                if fences[0].body != expected:
                    fails.append("%s: 围栏与 golden 逐字节不一致: %s"
                                 % (label, _byte_diff(expected,
                                                      fences[0].body)))
            else:
                marker = None
                for ln in slice_lines:
                    match = _PENDING_LINE_RE.match(ln.strip())
                    if match:
                        marker = match.group(1)
                        break
                if marker is None:
                    fails.append("%s: 未闭合素材缺少显式待处理标记（D3/D4："
                                 "不能静默删除）" % label)
        elif btype == "figure_region":
            if block.get("image"):
                fails += _figure_fails(doc, block, span, md_text, md_dir,
                                       label)
            else:
                marker = None
                for ln in slice_lines:
                    match = _PENDING_LINE_RE.match(ln.strip())
                    if match:
                        marker = match.group(1)
                        break
                if marker is None:
                    fails.append("%s: 未闭合素材缺少显式待处理标记（D3/D4："
                                 "不能静默删除）" % label)
        elif btype in ("bitmap", "formula", "ocr_region"):
            marker = None
            for ln in slice_lines:
                match = _PENDING_LINE_RE.match(ln.strip())
                if match:
                    marker = match.group(1)
                    break
            if marker is None:
                fails.append("%s: 未闭合素材缺少显式待处理标记（D3/D4："
                             "不能静默删除）" % label)
        else:
            fails.append("%s: 块类型未知: %r" % (label, btype))

    # 标题全量对照：清单裁决标题 vs 源 Markdown 实际标题序列
    md_headings = _md_headings(md_text)
    expected_headings = [(b.get("level"), (b.get("text") or "").strip())
                         for b in blocks if b.get("type") == "heading"]
    if len(expected_headings) != len(md_headings):
        fails.append("标题数不一致: 清单裁决 %d 条 vs 源 Markdown %d 条"
                     % (len(expected_headings), len(md_headings)))
    for index, (level, text) in enumerate(expected_headings):
        if index >= len(md_headings):
            break
        line_no, md_level, actual_title = md_headings[index]
        if md_level != level:
            fails.append("标题 #%d 层级不一致: 清单 H%d vs 源 Markdown L%d "
                         "H%d" % (index + 1, level, line_no, md_level))
        elif actual_title != text:
            fails.append("标题 #%d 不一致: 清单 %r vs 源 Markdown L%d %r"
                         % (index + 1, text, line_no, actual_title))

    # 未解释的待处理标记：区间外的 [PENDING-*] 属于多余/漏裁决
    in_range = set()
    for _block, span in ranges:
        in_range.update(range(span[0], span[1] + 1))
    for line_no, line in enumerate(lines, start=1):
        if _PENDING_LINE_RE.match(line.strip()) and line_no not in in_range:
            fails.append("源 Markdown L%d 出现未裁决的待处理标记: %r"
                         % (line_no, line.strip()[:60]))

    # 译文硬检查（机器结论；不登记语义复核完成）
    if translation_text is not None:
        product, convention, translation_warns = run_translation_checks(
            checklist, md_text, translation_text,
            translation_dir or os.getcwd())
        fails += product + convention
        warns += translation_warns
    return fails, warns


def build_parser():
    parser = argparse.ArgumentParser(
        description="PDF → 源 Markdown 独立对账（结构/区域/代码/图形）"
                    "与译文机器硬检查")
    parser.add_argument("pdf", help="只读 PDF 源")
    parser.add_argument("--checklist", required=True, help="裁决清单 JSON")
    parser.add_argument("--source-md", required=True, help="源 Markdown")
    parser.add_argument("--block-map", default=None,
                        help="块区间映射（默认 <源Markdown>.blocks.json）")
    parser.add_argument("--translation", default=None,
                        help="译文 Markdown（提供时追加译文硬检查）")
    return parser


def parse_args(argv):
    """按真实 CLI 解析参数（交付记录复跑与检查事实共用同一解释）。"""
    return build_parser().parse_args(argv)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not os.path.isfile(args.pdf):
        fail("PDF 源不存在: %s" % args.pdf)
    if not os.path.isfile(args.source_md):
        fail("源 Markdown 不存在: %s" % args.source_md)
    checklist = load_checklist(args.checklist)
    block_map = _load_block_map(args.block_map, args.source_md)
    with open(args.source_md, encoding='utf-8', newline='') as handle:
        md_text = handle.read()
    translation_text = None
    translation_dir = None
    if args.translation:
        if not os.path.isfile(args.translation):
            fail("译文不存在: %s" % args.translation)
        with open(args.translation, encoding='utf-8', newline='') as handle:
            translation_text = handle.read()
        translation_dir = os.path.dirname(os.path.abspath(args.translation))
    fails, warns = run_verification(
        args.pdf, checklist, md_text, block_map,
        checklist_dir=os.path.dirname(os.path.abspath(args.checklist)),
        md_dir=os.path.dirname(os.path.abspath(args.source_md)),
        translation_text=translation_text,
        translation_dir=translation_dir)
    for item in warns:
        print("WARN: %s" % item)
    if fails:
        product = [f for f in fails if f.startswith("【产物】")]
        convention = [f for f in fails if f.startswith("【口径】")]
        other = [f for f in fails if f not in product and f not in convention]
        print("FAIL: 机器硬检查未通过（产物问题 %d 项、口径/数据问题 %d 项），"
              "阻断交付" % (len(product) + len(other), len(convention)),
              file=sys.stderr)
        for item in (product + other + convention)[:20]:
            print("  - %s" % item, file=sys.stderr)
        return 1
    print("机器硬检查通过: %s（块数 %d）" % (args.source_md, len(block_map)))
    if translation_text is not None:
        print("译文硬检查通过: %s" % args.translation)
    print("人工语义复核: 未登记——本入口只做机器硬检查，语义复核由主 "
          "Agent 对照权威源独立登记，机器 PASS 不构成语义复核完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
