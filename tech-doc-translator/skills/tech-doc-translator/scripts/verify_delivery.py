#!/usr/bin/env python3
"""交付完成统一检查入口（R4/R7：目录允许清单、持久证据、复核闭合）。

用法：
    python3 verify_delivery.py --record <record.json> --evidence-dir <dir>

交付记录（record.json）声明本次范围与证据索引，不是目录状态库：

    {
      "version": 1,
      "mode": "translation+pdf" | "pdf" | "translation",
      "delivery_root": "/abs/path/to/交付根",
      "inputs": ["00_目录.md", "01_章.md"],          // 相对交付根
      "outputs": [{"path": "book.pdf", "sha256": "…"}],
      "images_display": "export/images_display.json", // 有图时必须
      "sources": [                              // 翻译模式必须；pdf 模式不强加
        {"family": "single", "source_version": "13.4",
         "parsed_markdown": "docs/source_en.md",       // 解析 Markdown（检查实际英文输入）
         "snapshots": [{"snapshot": "source/page.html",
                        "section_id": null}],           // 同版本快照与选区（默认全文根）
                                                          // 合并源加 "range": [起行, 止行]
                                                          // （闭区间；多快照须按序无缝覆盖整份）
                                                          // 有图快照须各自关联解析期映射：可在
                                                          // 快照级声明 "per_stem_map"；多快照的
                                                          // entry 级旧声明只归属其记录来源实际
                                                          // 匹配的快照；两级同时声明须为同一映射
         "per_stem_map": "docs/source_en.images_display.json",  // 单快照旧写法（有图时关联两级映射）
         "table_conversions": "docs/table_conversions.json",    // 可选逐表转换映射
         "covers": ["01_章.md"]}}],               // 该源链覆盖的交付输入
      "checks": [
        {"tool": "verify_pdf",
         "args": ["--pdf", "book.pdf", "--work-dir", "/abs/work",
                  "00_目录.md", "01_章.md"]},
        {"tool": "verify_translation",
         "args": ["01_章.md", "docs/source_en.md", "--strong-token", "标题"]}
      ],
      "files": {"00_目录.md": "toc", "01_章.md": "chapter",
                "book.pdf": "pdf", "术语表.md": "glossary"},
      "reviews": [{"kind": "visual", "target": "book.pdf",
                   "status": "closed", "sha256": "…",
                   "items": ["报告 relaxed_matches 中 review=true 的 segment…"],
                   "binding": {…该 PDF 的完整检查上下文（有序输入、映射、
                                资源、检查器与依赖版本）…},
                   "note": "…"},
                  {"kind": "semantic", "target": "01_章.md",
                   "status": "closed", "sha256": "…当前译文摘要…",
                   "binding": {…该译文的完整上下文（全部覆盖检查、有序源、
                                源链与图片资源身份）…},
                   "note": "…"}]
    }

检查内容：记录结构与模式、交付根一级文件与登记角色逐一相符（额外文件
拒绝，两份用户说明可选，符号链接/隐藏文件不豁免）、输入/输出/映射身份、
映射迁移布局（export/ 位置、条目相对映射目录可解析、无根目录副本）、
只重跑已知核验入口并发布证据。参数只有一个解释来源：每个工具的记录
参数先按其真实 CLI 解析（verify_pdf 的 argparse、翻译家族的 extract_* 语义）核对输入覆盖、PDF 完整路径与工作目录；执行以交付根为路径基点
（子进程设 cwd=交付根、原样传参，字面量不拼路径），PDF 由同一核验计算
函数在进程内取得本次机器证据——不读取、鉴真或深度比较任何预存核验
JSON；check.report 字段可保留但不影响判断。导出报告与已绑定政策仍必需。
预检先核对源链（sources）：每份实际英文输入关联同版本快照、家族/版本与
选区，有图关联两级映射；缺快照、选区不存在、版本错配或漏关联在复跑前
拒绝。通过预检后先执行独立原 HTML→解析 Markdown 全量对账（含逐表转换
映射），再复跑翻译核验与最终路径 PDF 核验。
复核按模式分别闭合：源全量对账、语义复核、PDF 视觉复核缺一不可（链接
复核不构成替代）；每条复核除目标摘要外还必须携带完整 binding——机器
按当前完整依赖身份（译文、全部覆盖检查及其有序源/口径/共享脚本、源链、
图片资源、映射、环境与样式政策）计算期望上下文，记录的 binding 与期望
不符或缺失即须重新复核，不自动补签；旧记录的零散绑定字段
（source_sha256/checker/semantic_args）不构成完整上下文。visual 复核须
逐项列明报告中的待复核 segment（items）。

发布只切换索引：全部检查与复核通过后，报告（含导出证据副本）写入证据
目录内一个新的独立批次，重读核对摘要（归档导出报告须与核验前基线版本
一致），并复查输入/产物/口径身份未变、全部必需依赖摘要可得，再以同
文件系统临时文件原子替换 delivery_index.json。索引引用相对证据目录
的路径；任何旧索引已引用的报告、导出证据均不覆盖。失败或中断最多留下
未引用的新批次，上一索引及全部引用内容保持可读且摘要不变。
"""
import argparse
from collections import Counter
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _verification import file_sha256 as sha256_file

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWN_TOOLS = {
    "verify_pdf": "verify_pdf.py",
    "verify_translation": "verify_translation.py",
    "verify_paginated_translation": "verify_paginated_translation.py",
    "verify_reference_translation": "verify_reference_translation.py",
    "verify_api_translation": "verify_api_translation.py",
}
RECORD_VERSION = 1
MODES = ("translation", "pdf", "translation+pdf")
TRANSLATION_FAMILIES = ("single", "paginated", "reference", "api")
USER_NOTE_NAMES = ("导出前准备说明.md", "PDF导出交付说明.md")
TOC_NAME = "00_目录.md"
GLOSSARY_NAME = "术语表.md"

# 复核类别（R4/4.7）：按交付模式分别落实源全量对账、语义复核与
# PDF 视觉复核，不能把不同类别合并成一个“目标已复核”集合。
REVIEW_SOURCE_RECONCILE = "source-reconcile"
REVIEW_SEMANTIC = "semantic"
REVIEW_VISUAL = "visual"
REVIEW_LINK = "link"
KNOWN_REVIEW_KINDS = {REVIEW_SOURCE_RECONCILE, REVIEW_SEMANTIC,
                      REVIEW_VISUAL, REVIEW_LINK, "content"}
TRANSLATION_TOOLS = {"verify_translation", "verify_paginated_translation",
                     "verify_reference_translation", "verify_api_translation"}
# 各翻译家族解析结果中“译文路径”的字段名（输入覆盖按它核对）。
TRANSLATED_PATH_KEYS = {
    "verify_translation": "doc_path",
    "verify_paginated_translation": "merged_path",
    "verify_reference_translation": "translated_path",
    "verify_api_translation": "merged_path",
}
# 各翻译家族解析结果中“源路径”的字段名（有序源输入）。
SOURCE_PATH_KEYS = {
    "verify_translation": ("src_path",),
    "verify_paginated_translation": ("src_paths",),
    "verify_reference_translation": ("source_path",),
    "verify_api_translation": ("src_paths",),
}

# 根目录一级文件角色登记表；未登记文件必须失败，不按“用户可读”扩充。
ROLE_PATTERNS = (
    ("toc", lambda name: name == TOC_NAME),
    ("glossary", lambda name: name == GLOSSARY_NAME),
    ("user-note", lambda name: name in USER_NOTE_NAMES),
    ("pdf", lambda name: name.lower().endswith(".pdf")),
    ("chapter", lambda name: name.lower().endswith(".md")),
)


class DeliveryError(ValueError):
    """交付检查失败。"""


def review_item_label(item, channel, index):
    """把报告待处置项转为稳定、可定位的 items 字符串。

    channel + 1 起顺序号保留报告中的具体发生次数；即使两项的
    code/message/input/line 完全相同，也不能被一条笼统记录代闭。
    input/line 作为人工复核的回源定位证据一并保留。
    """
    if channel == "relaxed_matches":
        subject = str(item.get("segment"))
    else:
        subject = "%s: %s" % (item.get("code"), item.get("message"))
    locator = ["%s#%d" % (channel, index + 1)]
    if item.get("input"):
        locator.append("input=%s" % item.get("input"))
    if item.get("line") is not None:
        locator.append("line=%s" % item.get("line"))
    return "%s [%s]" % (subject, "; ".join(locator))


def load_record(path):
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        raise DeliveryError("交付记录不可读: %s（%s）" % (path, exc))
    if not isinstance(record, dict) or record.get("version") != RECORD_VERSION:
        raise DeliveryError("交付记录版本无效（需 version=%d）" % RECORD_VERSION)
    if record.get("mode") not in MODES:
        raise DeliveryError("交付模式无效: %r（需 %s）" % (record.get("mode"), "/".join(MODES)))
    for key in ("delivery_root", "inputs", "outputs", "checks", "reviews"):
        if key not in record:
            raise DeliveryError("交付记录缺少 %s" % key)
    return record


def check_root_layout(root, record, problems, record_path=None):
    """枚举交付根一级全部文件（含隐藏项与链接），与登记角色逐一核对。

    交付记录本身若放在交付根内，同样按未登记文件拒绝（应放在根外或
    docs/）；chapter 角色的文件必须属于声明的输入清单，输入必须登记。
    """
    declared = record.get("files") or {}
    allowed_roles = {role for role, _pred in ROLE_PATTERNS}
    for role in declared.values():
        if role not in allowed_roles:
            problems.append("登记了未知的文件角色: %r" % role)
    inputs = set(record.get("inputs") or [])
    actual = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full) and not os.path.islink(full):
            continue  # 子目录本身不计入文件清单
        actual.append(name)
        if name not in declared:
            problems.append(
                "交付根存在未登记文件: %s（额外文件必须归位或登记，"
                "不因隐藏/改名豁免）" % name)
    for name, role in declared.items():
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            problems.append("登记的文件不存在: %s（%s）" % (name, role))
            continue
        true_roles = [role_name for role_name, pred in ROLE_PATTERNS
                      if pred(name)]
        if role not in true_roles:
            problems.append(
                "文件 %s 的登记角色 %r 与其形态不符（可为 %s）"
                % (name, role, "/".join(true_roles) or "无（不该出现在根目录）"))
            continue
        if role == "chapter" and name not in inputs:
            problems.append(
                "登记为章节译文的文件不属于本次输入清单: %s" % name)
    for name in inputs:
        if name not in declared:
            problems.append("输入未在根目录清单登记: %s" % name)
    if record.get("images_display"):
        map_rel = record["images_display"]
        if os.path.basename(map_rel) != "images_display.json":
            problems.append("交付级映射文件名必须是 images_display.json: %s" % map_rel)
        # 位置合同（R7/§9.3）：以交付根为基点词法绝对化/规范化后必须
        # 是 export/images_display.json；./ 与指向该位置的正确绝对路径
        # 等价写法允许，other/、归档目录、根副本及其他位置拒绝。词法
        # 规范化而非 realpath：其他位置指向同一 realpath 的别名不等于
        # 获准位置。不新增 export/ 子目录的物理包含限制。
        base = os.path.abspath(root)
        normalized = os.path.normpath(
            map_rel if os.path.isabs(map_rel)
            else os.path.join(base, map_rel))
        permitted = os.path.normpath(
            os.path.join(base, "export", "images_display.json"))
        if normalized != permitted:
            problems.append(
                "交付级映射必须位于 export/images_display.json（允许 ./ 与"
                "指向该位置的正确绝对路径等价写法），实际: %s" % map_rel)
        map_path = os.path.join(root, map_rel)
        if not os.path.isfile(map_path):
            problems.append("交付级映射缺失: %s" % map_rel)
        root_copy = os.path.join(root, "images_display.json")
        if os.path.isfile(root_copy):
            problems.append("交付根存在映射副本，迁移未完成: images_display.json")
    return actual


def check_map_entries(root, record, problems):
    """映射条目的 markdown/image 按相对映射目录解析并命中真实文件。"""
    map_rel = record.get("images_display")
    if not map_rel:
        return
    map_path = os.path.join(root, map_rel)
    if not os.path.isfile(map_path):
        return
    map_dir = os.path.dirname(map_path)
    try:
        payload = json.load(open(map_path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append("映射无法解析: %s（%s）" % (map_rel, exc))
        return
    for item in payload.get("entries", []) + payload.get("undetermined", []):
        for key in ("markdown", "image"):
            target = item.get(key)
            if not target:
                continue
            resolved = os.path.normpath(os.path.join(map_dir, target))
            if not os.path.isfile(resolved):
                problems.append(
                    "映射条目 %s 无法按映射目录解析: %s" % (key, target))


def check_identities(root, record, problems):
    for rel in record.get("inputs", []):
        if not os.path.isfile(os.path.join(root, rel)):
            problems.append("输入缺失: %s" % rel)
    for output in record.get("outputs", []):
        path = os.path.join(root, output.get("path", ""))
        if not os.path.isfile(path):
            problems.append("输出缺失: %s" % output.get("path"))
            continue
        expected = output.get("sha256")
        if expected and expected != sha256_file(path):
            problems.append(
                "输出摘要不符: %s（记录 %s）" % (output.get("path"), expected[:12]))


# 各核验入口影响结果的本地共享脚本（显式依赖集合，不扫描整个仓库）；
# 沿用 recover_work_packages._script_identity 的做法。
CHECK_SHARED_DEPS = {
    "verify_pdf": ("verify_pdf.py", "export_pdf.py", "_verification.py",
                   "_html_fidelity.py", "_source_reconcile.py",
                   "_image_binding.py", "_image_preflight.py"),
    "verify_translation": ("verify_translation.py", "_verification.py",
                           "_html_fidelity.py", "_source_reconcile.py"),
    "verify_paginated_translation": ("verify_paginated_translation.py",
                                     "_verification.py", "_html_fidelity.py",
                                     "_source_reconcile.py"),
    "verify_reference_translation": ("verify_reference_translation.py",
                                     "_verification.py", "_html_fidelity.py",
                                     "_source_reconcile.py"),
    "verify_api_translation": ("verify_api_translation.py",
                               "_verification.py", "_html_fidelity.py",
                               "_source_reconcile.py"),
}

# 运行环境版本按复核目标投影（§9.3）：翻译检查覆盖其实际调用的
# BeautifulSoup/tinycss2/markdown-it-py、图片资源处理所用 Pillow 与
# Python；PDF 检查另含 pypdf/uniseg。不混入其他目标独有的依赖。
TRANSLATION_ENV_KEYS = ("python", "beautifulsoup4", "tinycss2",
                        "markdown-it-py", "pillow")


def _environment_identity():
    """参与导出/核验的依赖版本（按实际调用覆盖，不可得记 None）。"""
    import platform

    versions = {"python": platform.python_version()}
    try:
        import bs4

        versions["beautifulsoup4"] = getattr(bs4, "__version__", "unknown")
    except ImportError:
        versions["beautifulsoup4"] = None
    try:
        import tinycss2

        versions["tinycss2"] = getattr(tinycss2, "__version__", "unknown")
    except ImportError:
        versions["tinycss2"] = None
    try:
        import markdown_it

        versions["markdown-it-py"] = getattr(
            markdown_it, "__version__", "unknown")
    except ImportError:
        versions["markdown-it-py"] = None
    try:
        import pypdf

        versions["pypdf"] = getattr(pypdf, "__version__", "unknown")
    except ImportError:
        versions["pypdf"] = None
    try:
        from PIL import __version__ as pillow_version

        versions["pillow"] = pillow_version
    except ImportError:
        versions["pillow"] = None
    try:
        import uniseg

        versions["uniseg"] = getattr(uniseg, "__version__", "unknown")
    except ImportError:
        versions["uniseg"] = None
    return versions


def _digest_or_none(path):
    return sha256_file(path) if os.path.isfile(path) else None


def _source_identity(entry, rooted):
    """单条源链的依赖身份：全部按声明路径重新枚举计算，不沿用缓存值。"""
    return {
        "parsed_markdown": entry["parsed_markdown"],
        "parsed_sha256": _digest_or_none(rooted(entry["parsed_markdown"])),
        "snapshots": [{
            "snapshot": snap["snapshot"],
            "section_id": snap.get("section_id"),
            "range": snap.get("range"),
            "snapshot_sha256": _digest_or_none(rooted(snap["snapshot"])),
            "per_stem_map": (
                None if not snap.get("per_stem_map") else {
                    "path": snap["per_stem_map"]["path"],
                    "sha256": _digest_or_none(
                        rooted(snap["per_stem_map"]["path"]))}),
        } for snap in entry["snapshots"]],
        "table_conversions": (
            None if not entry.get("table_conversions") else {
                "path": entry["table_conversions"],
                "sha256": _digest_or_none(rooted(entry["table_conversions"]))}),
    }


def _snapshot_source_facts(family, snapshots, rooted, problems=None,
                           label="源链"):
    """逐快照枚举实际图片资源事实（§9.3 单一事实来源）。

    从每份原始 HTML 的实际家族选区枚举（复用 _source_reconcile 的既有
    源事实与家族选区/代码排除规则），保留源节点与原始引用；原始引用
    按声明快照路径的目录解析（资源基点取声明路径目录，文件身份另取
    realpath——沿用 R1/R3 四元组语义），摘要沿用递归覆盖 SVG/CSS 依赖
    的既有函数。缺文件、引用不可解析或摘要不可得时在 problems 中定位，
    不静默缩小范围。返回逐快照有序事实：
    {'snapshot', 'resource_base', 'images': [{node, source_ref, src,
    path, sha256}]}。不以 None==None 判相等：摘要不来的条目保留 None，
    由预检定位、绑定按不完整拒绝。
    """
    from _html_fidelity import resolve_snapshot_resource
    from _source_reconcile import snapshot_image_facts
    from _verification import resource_identity_digest

    per_snapshot = []
    for snap in snapshots or []:
        declared = snap["snapshot"]
        snapshot_path = rooted(declared)
        snapshot_dir = os.path.dirname(snapshot_path)
        record = {
            "snapshot": declared,
            "resource_base": os.path.realpath(snapshot_dir),
            "images": [],
        }
        try:
            with open(snapshot_path, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError:
            if problems is not None:
                problems.append("%s 的快照不可读，无法枚举源图片资源: %s"
                                % (label, declared))
            per_snapshot.append(record)
            continue
        facts = snapshot_image_facts(raw, family, snap.get("section_id"))
        if facts is None:
            if problems is not None:
                problems.append("%s 的快照 %s 选区根缺失，无法枚举源图片"
                                "资源" % (label, declared))
            per_snapshot.append(record)
            continue
        for fact in facts:
            path, reason = resolve_snapshot_resource(
                fact["source_ref"], snapshot_dir)
            digest = (resource_identity_digest(path)
                      if path is not None else None)
            if problems is not None and digest is None:
                problems.append(
                    "%s 的快照 %s 图片资源无法确定身份: %s（%s）"
                    % (label, declared, fact["source_ref"],
                       reason or "摘要不可得"))
            record["images"].append({
                "node": fact["node"],
                "source_ref": fact["source_ref"],
                "src": fact["src"],
                "path": path,
                "sha256": digest,
            })
        per_snapshot.append(record)
    return per_snapshot


def _snapshot_ranges(snapshots, parsed_path, problems, label):
    """合并源快照行区间（§4.7/§8.4）：单快照缺省全文；多快照必须声明
    range（解析 Markdown 起止行闭区间）且按声明顺序无缝覆盖整份
    Markdown，缺口、重叠或乱序拒绝。返回逐快照 (起, 止) 元组列表；
    不合法时记入 problems 并返回 None。"""
    try:
        with open(parsed_path, encoding="utf-8") as handle:
            total = len(handle.read().split("\n"))
    except OSError:
        problems.append("%s 的解析 Markdown 不可读，无法核对快照区间" % label)
        return None
    ranges = []
    for index, snap in enumerate(snapshots):
        declared = snap.get("range")
        if declared is None:
            if len(snapshots) == 1:
                ranges.append((1, total))
                continue
            problems.append("%s 的快照 #%d 缺少 range（多快照合并源必须"
                            "声明各自行区间）" % (label, index + 1))
            return None
        if (not isinstance(declared, list) or len(declared) != 2
                or not all(isinstance(v, int) and not isinstance(v, bool)
                           and 1 <= v <= total for v in declared)
                or declared[0] > declared[1]):
            problems.append("%s 的快照 #%d range 非法: %r（需 1..%d 闭区间）"
                            % (label, index + 1, declared, total))
            return None
        ranges.append((declared[0], declared[1]))
    cursor = 1
    for index, (start, end) in enumerate(ranges):
        if start != cursor:
            problems.append(
                "%s 的快照 #%d range 起点应为第 %d 行（实际 %d）：合并范围"
                "必须按序无缝覆盖" % (label, index + 1, cursor, start))
            return None
        cursor = end + 1
    if cursor != total + 1:
        problems.append("%s 的合并快照范围未覆盖解析 Markdown 末行"
                        "（覆盖至第 %d/%d 行）" % (label, cursor - 1, total))
        return None
    return ranges


def _resource_identities(text, base_dir):
    """按实际引用枚举文档图片的递归资源身份（SVG/CSS 依赖一并覆盖）。"""
    from _verification import image_marker_refs, image_references, \
        resource_identity_digest

    identities = []
    for _line, src in image_references(text):
        path = (os.path.normpath(os.path.join(base_dir, src))
                if not os.path.isabs(src) else src)
        identities.append((src, resource_identity_digest(path)))
    for _line, ref in image_marker_refs(text):
        path = (os.path.normpath(os.path.join(base_dir, ref))
                if not os.path.isabs(ref) else ref)
        identities.append((ref, resource_identity_digest(path)))
    return identities


def _source_entries(record):
    return record.get("sources") or []


def check_source_chains(root, record, problems):
    """源链预检（§4.7）：解析 Markdown → 同版本快照、家族/版本与选区。

    每份实际英文输入都须关联快照与选区；选区不存在、快照缺失、
    per-stem 映射版本不符或有图缺两级映射均在复跑前拒绝。无图不要求
    per-stem 映射；pdf 模式不强加英文源。返回带身份与对账结果的条目
    列表（预检失败时为尽量填充的部分结果，调用方在有 problems 时不
    发布）。
    """
    from _html_fidelity import HtmlFidelity

    root_abs = os.path.realpath(root)
    entries = []

    def rooted(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(root_abs, rel))

    declared_markdowns = []
    for order, entry in enumerate(_source_entries(record), start=1):
        label = "源链 #%d" % order
        if not isinstance(entry, dict):
            problems.append("%s 必须是对象" % label)
            continue
        parsed = entry.get("parsed_markdown")
        if not isinstance(parsed, str) or not parsed:
            problems.append("%s 缺少解析 Markdown（parsed_markdown）" % label)
            continue
        parsed_path = rooted(parsed)
        if not os.path.isfile(parsed_path):
            problems.append("%s 的解析 Markdown 缺失: %s" % (label, parsed))
            continue
        declared_markdowns.append(os.path.realpath(parsed_path))
        family = entry.get("family")
        if family not in TRANSLATION_FAMILIES:
            problems.append("%s 的 family 无效: %r（需 %s）"
                            % (label, family,
                               "/".join(sorted(TRANSLATION_FAMILIES))))
            continue
        version = entry.get("source_version")
        if not isinstance(version, str) or not version.strip():
            problems.append("%s 缺少 source_version，不能宣称同版本" % label)
            continue
        snapshots = []
        snap_map_decls = []
        for snap in entry.get("snapshots") or []:
            if not isinstance(snap, dict) or not isinstance(
                    snap.get("snapshot"), str):
                problems.append("%s 的 snapshots 项需要 snapshot 路径" % label)
                continue
            snapshot_path = rooted(snap["snapshot"])
            if not os.path.isfile(snapshot_path):
                problems.append("%s 的快照缺失: %s（不得用最新版替代）"
                                % (label, snap["snapshot"]))
                continue
            section_id = snap.get("section_id")
            if section_id is not None and not isinstance(section_id, str):
                problems.append("%s 的 section_id 无效: %r"
                                % (label, section_id))
                continue
            map_decl = snap.get("per_stem_map")
            if map_decl is not None and not isinstance(map_decl, str):
                problems.append("%s 的快照 %s 的 per_stem_map 无效: %r"
                                % (label, snap["snapshot"], map_decl))
                continue
            snapshots.append({
                "snapshot": snap["snapshot"],
                "snapshot_sha256": sha256_file(snapshot_path),
                "section_id": section_id,
                "range": snap.get("range"),
            })
            snap_map_decls.append(map_decl)
        if not snapshots:
            problems.append("%s 未声明任何快照" % label)
            continue
        # per-stem 映射声明（§9.4.1）：快照级声明绑定各自快照；entry 级
        # 旧声明在单快照时绑定唯一快照，多快照时按映射记录的来源对应
        # 实际快照（核实来源与上下文后归属，不能自动复制给其他页面）；
        # 两级同时声明必须指向同一映射文件，否则歧义拒绝。每份绑定核对
        # 记录快照、摘要与资源解析上下文；错源/错上下文/缺证明拒绝。
        entry_map_decl = entry.get("per_stem_map")
        if entry_map_decl is not None and not isinstance(entry_map_decl, str):
            problems.append("%s 的 per_stem_map 无效: %r"
                            % (label, entry_map_decl))
            continue

        def load_map(declared_map, map_label):
            """加载解析期映射；不可读/缺失/结构或版本不符记问题并返回
            None（复用 _image_binding 的既有结构校验——可读 JSON 不代替
            有效映射，§9.6）。"""
            from _image_binding import BindingError, validate_parse_map

            map_path = rooted(declared_map)
            if not os.path.isfile(map_path):
                problems.append("%s 的解析期映射缺失: %s"
                                % (map_label, declared_map))
                return None
            try:
                with open(map_path, encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError) as exc:
                problems.append("%s 的解析期映射不可读: %s（%s）"
                                % (map_label, declared_map, exc))
                return None
            try:
                validate_parse_map(payload, map_label)
            except BindingError as exc:
                problems.append("%s 的解析期映射无效: %s（%s）"
                                % (map_label, declared_map, exc))
                return None
            return payload

        def verify_map_binding(payload, declared_map, snap, map_label):
            """核对映射与指定快照的绑定：缺来源证明、错源、版本错配、
            错上下文均拒绝（§9.6：来源身份字段是证明，存在才核对不足）。
            """
            snapshot_path = rooted(snap["snapshot"])
            recorded = payload.get("snapshot")
            if not (isinstance(recorded, str) and recorded):
                problems.append(
                    "%s 的解析期映射缺少来源快照记录，不构成独立来源证明"
                    % map_label)
                return False
            if os.path.realpath(
                    rooted(recorded)) != os.path.realpath(snapshot_path):
                problems.append(
                    "%s 的解析期映射绑定快照 %s 与源链快照 %s 不符（错源/"
                    "版本错配）" % (map_label, recorded, snap["snapshot"]))
                return False
            recorded_sha = payload.get("snapshot_sha256")
            if not (isinstance(recorded_sha, str) and recorded_sha):
                problems.append(
                    "%s 的解析期映射缺少快照摘要记录，不构成独立来源证明"
                    % map_label)
                return False
            if recorded_sha != snap["snapshot_sha256"]:
                problems.append(
                    "%s 的解析期映射快照摘要与当前快照不符（版本错配）"
                    % map_label)
                return False
            items = [item for item in (payload.get("entries", [])
                                       + payload.get("undetermined", []))
                     if isinstance(item, dict) and item.get("resource_sha256")
                     and item.get("source_node")]
            if items:
                declared_base = payload.get("resource_base")
                if not (isinstance(declared_base, str)
                        and os.path.isabs(declared_base)):
                    problems.append(
                        "%s 的解析期映射为旧版来源记录（缺 resource_base），"
                        "资源解析上下文不可确定；请重新解析生成含资源上下文"
                        "的记录" % map_label)
                    return False
                expected_base = os.path.realpath(
                    os.path.dirname(snapshot_path))
                if os.path.realpath(declared_base) != expected_base:
                    problems.append(
                        "%s 的解析期映射来自其他资源解析上下文（错上下文）:"
                        " 记录 %s vs 快照声明目录 %s"
                        % (map_label, declared_base, expected_base))
                    return False
            return True

        def bind_map(declared_map, snap, map_label):
            payload = load_map(declared_map, map_label)
            if payload is None:
                return None
            if not verify_map_binding(payload, declared_map, snap, map_label):
                return None
            return {"path": declared_map,
                    "sha256": sha256_file(rooted(declared_map)),
                    "_payload": payload}

        snap_maps = [None] * len(snapshots)
        snap_payloads = [None] * len(snapshots)  # 证明覆盖核对用，不进身份
        for index, declared_map in enumerate(snap_map_decls):
            if declared_map is None:
                continue
            snap_maps[index] = bind_map(
                declared_map, snapshots[index],
                "%s 的快照 #%d（%s）" % (label, index + 1,
                                         snapshots[index]["snapshot"]))
            if snap_maps[index] is not None:
                snap_payloads[index] = snap_maps[index].pop("_payload")
        if entry_map_decl is not None:
            if len(snapshots) == 1:
                bound_index = 0
            else:
                # 多快照旧 entry 级声明：按映射记录的来源对应实际快照
                payload = load_map(entry_map_decl, label)
                recorded = (payload or {}).get("snapshot")
                matches = [] if not recorded else [
                    index for index, snap in enumerate(snapshots)
                    if os.path.realpath(rooted(recorded))
                    == os.path.realpath(rooted(snap["snapshot"]))]
                if payload is None:
                    bound_index = None
                elif len(matches) == 1:
                    bound_index = matches[0]
                else:
                    problems.append(
                        "%s 的 entry 级解析期映射无法对应唯一声明快照（记录"
                        "来源 %r，多快照来源必须能核实归属，不能自动复制给"
                        "其他页面）" % (label, recorded))
                    bound_index = None
            if bound_index is not None:
                if snap_maps[bound_index] is not None:
                    if os.path.realpath(rooted(entry_map_decl)) != \
                            os.path.realpath(rooted(
                                snap_maps[bound_index]["path"])):
                        problems.append(
                            "%s 的快照 #%d 两级 per_stem_map 声明不一致（歧"
                            "义）: entry 级 %s vs 快照级 %s"
                            % (label, bound_index + 1, entry_map_decl,
                               snap_maps[bound_index]["path"]))
                else:
                    snap_maps[bound_index] = bind_map(
                        entry_map_decl, snapshots[bound_index], label)
                    if snap_maps[bound_index] is not None:
                        snap_payloads[bound_index] = snap_maps[
                            bound_index].pop("_payload")
        for snap_dict, map_info in zip(snapshots, snap_maps):
            snap_dict["per_stem_map"] = map_info
        # 逐快照枚举实际图片资源事实（原始引用与资源上下文）
        per_snapshot_facts = _snapshot_source_facts(
            family, snapshots, rooted, problems, label)
        # 独立来源证明（§9.6）：绑定映射的条目须按 source_node 与快照
        # 实际图片出现一一对应，携带的资源身份须一致；有图快照的映射
        # 缺来源身份字段或条目不对应即缺证明拒绝；无图快照的映射不得
        # 含条目（无从证明的内容）。可读 JSON 不代替独立来源证明。
        for snap_index, (snap, facts, payload) in enumerate(
                zip(snapshots, per_snapshot_facts, snap_payloads),
                start=1):
            if payload is None:
                continue
            snap_label = "%s 的快照 #%d（%s）解析期映射" % (
                label, snap_index, snap["snapshot"])
            fact_by_node = {fact["node"]: fact
                            for fact in (facts["images"] if facts else [])}
            items = [item for item in (payload.get("entries", [])
                                       + payload.get("undetermined", []))
                     if isinstance(item, dict)]
            item_nodes = [item.get("source_node") for item in items]
            if (any(not isinstance(node, str) or not node
                    for node in item_nodes)
                    or sorted(item_nodes) != sorted(fact_by_node)):
                problems.append(
                    "%s 的条目与快照实际图片出现不对应（缺证明）：映射记录"
                    " %s，快照实际 %s" % (snap_label, sorted(
                        str(node) for node in item_nodes),
                                          sorted(fact_by_node)))
                continue
            for item in items:
                fact = fact_by_node[item["source_node"]]
                if not item.get("resource_sha256"):
                    problems.append(
                        "%s 的条目 %s 缺资源身份记录（缺证明）"
                        % (snap_label, item["source_node"]))
                    continue
                if fact["sha256"] is not None and item[
                        "resource_sha256"] != fact["sha256"]:
                    problems.append(
                        "%s 的条目 %s 资源身份与快照实际资源不符（错源/"
                        "版本错配）" % (snap_label, item["source_node"]))
        # 选区存在性：选区声明属于快照，逐快照核对
        for snap in entry.get("snapshots") or []:
            section_id = snap.get("section_id")
            if not section_id:
                continue
            snapshot_path = rooted(snap["snapshot"])
            soup = HtmlFidelity().parse(
                open(snapshot_path, encoding="utf-8").read())
            if soup.find(id=section_id) is None:
                problems.append("%s 指定选区在快照中不存在: %s（%s）"
                                % (label, section_id, snap["snapshot"]))
        ranges = _snapshot_ranges(
            snapshots, parsed_path, problems, label)
        entries.append({
            "order": order,
            "family": family,
            "source_version": version,
            "parsed_markdown": parsed,
            "parsed_sha256": sha256_file(parsed_path),
            "snapshots": snapshots,
            "ranges": ranges,
            "covers": list(entry.get("covers") or []),
            "table_conversions": entry.get("table_conversions"),
            "_parsed_abs": os.path.realpath(parsed_path),
            "_source_facts": per_snapshot_facts,
        })
    # 覆盖对账：translation 模式下每个交付输入都须被源链覆盖
    if record.get("mode") in ("translation", "translation+pdf"):
        covered = set()
        for entry in entries:
            covered.update(entry["covers"])
        for rel in record.get("inputs") or []:
            if rel not in covered:
                problems.append("交付输入 %s 缺少源链关联（漏关联）" % rel)
    # 两级映射要求由实际图片出现决定（§8.3/§9.3）：源链解析 Markdown 或
    # 其覆盖译文任一侧有实际图片出现，即须声明交付级映射；有图快照逐份
    # 绑定各自解析期映射（无图快照免映射）；交付映射条目按出现数覆盖
    # 有图输入。pdf 模式的普通导出告警策略保持不变。
    if record.get("mode") in ("translation", "translation+pdf"):
        from _verification import image_occurrence_count

        input_counts = {}
        for rel in record.get("inputs") or []:
            path = rooted(rel)
            if os.path.isfile(path):
                try:
                    input_counts[rel] = image_occurrence_count(
                        open(path, encoding="utf-8").read())
                except OSError:
                    input_counts[rel] = 0
        map_rel = record.get("images_display")
        for entry in entries:
            parsed_count = 0
            try:
                parsed_count = image_occurrence_count(
                    open(rooted(entry["parsed_markdown"]),
                         encoding="utf-8").read())
            except OSError:
                pass
            covered_counts = sum(
                input_counts.get(rel, 0)
                for rel in entry["covers"] if isinstance(rel, str))
            if parsed_count or covered_counts:
                if not map_rel:
                    problems.append(
                        "源链 #%d 存在实际图片出现，但交付记录未声明交付级"
                        "映射 images_display（两级映射）" % entry["order"])
            for snap_index, (snap, facts) in enumerate(
                    zip(entry["snapshots"], entry["_source_facts"]), start=1):
                if facts["images"] and snap.get("per_stem_map") is None:
                    problems.append(
                        "源链 #%d 的快照 #%d（%s）存在实际图片出现，未关联"
                        "解析期映射（两级映射）"
                        % (entry["order"], snap_index, snap["snapshot"]))
        if any(input_counts.values()) and not map_rel:
            problems.append(
                "交付输入存在实际图片出现，但未声明交付级映射 images_display")
        if map_rel and os.path.isfile(rooted(map_rel)):
            map_path = rooted(map_rel)
            map_dir = os.path.dirname(map_path)
            try:
                payload = json.load(open(map_path, encoding="utf-8"))
                entry_counts = {}
                for item in (payload.get("entries", [])
                             + payload.get("undetermined", [])):
                    markdown = (item.get("markdown")
                                if isinstance(item, dict) else None)
                    if not isinstance(markdown, str) or not markdown:
                        continue
                    real = os.path.realpath(os.path.normpath(
                        os.path.join(map_dir, markdown)))
                    entry_counts[real] = entry_counts.get(real, 0) + 1
                for rel, count in sorted(input_counts.items()):
                    if not count:
                        continue
                    real = os.path.realpath(rooted(rel))
                    if entry_counts.get(real) != count:
                        problems.append(
                            "交付输入 %s 有 %d 处图片出现，交付级映射条目为"
                            " %d 条（映射漏项）"
                            % (rel, count, entry_counts.get(real, 0)))
            except (OSError, ValueError):
                pass  # 映射不可读/结构无效由根目录与映射检查另行报告
    return entries


def run_source_reconcile(root, record, source_entries, problems):
    """对每条源链执行独立原 HTML → 解析 Markdown 对账（§4.10）。

    合并源按声明的快照行区间（range）核对对应范围，不把每个快照与
    整份解析 Markdown 比较（§8.4）；区间合法性由 `_snapshot_ranges`
    判定（预检已核，此处直接调用兜底）。含逐表转换映射（声明时）；
    差异即拒绝。返回逐条目的对账结果摘要，进入本次证据（不读取或
    补签任何预存对账结果）。
    """
    from _source_reconcile import reconcile_html_to_markdown

    root_abs = os.path.realpath(root)

    def rooted(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(root_abs, rel))

    results = []
    for entry in source_entries:
        parsed_path = rooted(entry["parsed_markdown"])
        label = "源链 #%d" % entry["order"]
        try:
            md_lines = open(parsed_path, encoding="utf-8").read().split("\n")
        except OSError as exc:
            problems.append("%s 对账读取失败: %s" % (label, exc))
            md_lines = None
        ranges = entry.get("ranges")
        if md_lines is not None and ranges is None:
            ranges = _snapshot_ranges(entry["snapshots"], parsed_path,
                                      problems, label)
        diffs = []
        if md_lines is not None and ranges is not None:
            for snap, (start, end) in zip(entry["snapshots"], ranges):
                snapshot_path = rooted(snap["snapshot"])
                conversions = None
                if entry.get("table_conversions"):
                    conversion_path = rooted(entry["table_conversions"])
                    try:
                        conversions = json.load(
                            open(conversion_path, encoding="utf-8"))
                    except (OSError, ValueError) as exc:
                        problems.append(
                            "%s 的逐表转换映射不可读: %s（%s）"
                            % (label, entry["table_conversions"], exc))
                        continue
                try:
                    diffs += reconcile_html_to_markdown(
                        open(snapshot_path, encoding="utf-8").read(),
                        "\n".join(md_lines[start - 1:end]),
                        entry["family"], section_id=snap.get("section_id"),
                        table_conversions=conversions)
                except OSError as exc:
                    problems.append("%s 对账读取失败: %s" % (label, exc))
        if diffs:
            problems.append(
                "源链 #%d（%s）源全量对账失败: %s"
                % (entry["order"], entry["parsed_markdown"],
                   "；".join(diffs[:3])))
        results.append({
            "order": entry["order"],
            "parsed_markdown": entry["parsed_markdown"],
            "family": entry["family"],
            "snapshots": entry["snapshots"],
            "diffs": diffs,
        })
    return results


def compute_delivery_identity(root, record, source_entries=None):
    """完整依赖身份（§4.7/§9.3）：输入/产物、源链（逐快照资源）、两侧
    图片资源、映射、全部实际检查的真实 CLI 语义事实与文件依赖、共享
    脚本、依赖版本与样式政策的同一计算口径。

    这是本次运行的值，不是状态库；发布前以同一函数重新枚举计算比对，
    不能只复查预先列出的旧路径。文件摘要缺失记 None；绑定按不完整
    拒绝、发布前完整性检查拒绝（两侧同为 None 不判相等，必需文件
    缺失同时由预检定位）。
    """
    root_abs = os.path.realpath(root)

    def rooted(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(root_abs, rel))

    identity = {
        "inputs": {},
        "outputs": {},
        "resources": {"inputs": {}},
        "sources": [],
        "checks": [],
        "environment": _environment_identity(),
    }
    for rel in record.get("inputs") or []:
        path = rooted(rel)
        identity["inputs"][rel] = _digest_or_none(path)
        if os.path.isfile(path):
            identity["resources"]["inputs"][rel] = _resource_identities(
                open(path, encoding="utf-8").read(), os.path.dirname(path))
    for output in record.get("outputs", []):
        rel = output.get("path")
        identity["outputs"][rel] = _digest_or_none(rooted(rel or ""))
    if record.get("images_display"):
        identity["images_display"] = _digest_or_none(
            rooted(record["images_display"]))
    for entry in source_entries or []:
        identity["sources"].append(_source_identity(entry, rooted))
        # 源资源身份按每份原始快照的实际家族选区枚举（§9.3）：原始引用
        # 按各自声明快照目录解析，不再把整份解析 Markdown 按首快照目录
        # 解释；range 只用于解析结果归属，不复制引用到所有快照。
        identity["resources"].setdefault("sources", {})[
            entry["parsed_markdown"]] = _snapshot_source_facts(
            entry.get("family"), entry["snapshots"], rooted)
    for order, check in enumerate(record.get("checks") or [], start=1):
        tool = check.get("tool")
        facts = None
        if tool in KNOWN_TOOLS:
            facts, _parsed = _check_facts(
                root_abs, tool, list(check.get("args") or []), order)
        identity["checks"].append({"order": order, "tool": tool,
                                   "facts": facts})
    # 交付入口自身参与结果判断，纳入有限依赖集合（§9.3）
    identity["delivery_entry"] = {
        "script_sha256": _digest_or_none(
            os.path.join(SCRIPTS_DIR, "verify_delivery.py"))}
    if "pdf" in record.get("mode", ""):
        style = os.path.join(os.path.dirname(SCRIPTS_DIR),
                             "assets/pdf/style.css")
        identity["style_policy"] = {"pdf_style_css": _digest_or_none(style)}
    return identity


def align_sources_with_checks(source_entries, input_checks, problems,
                              mode=None):
    """检查实际使用的英文输入与声明源链一一对应，双向都不缺不悬空。

    检查使用的英文输入必须落在声明源链内（不能按文件名猜快照）；
    声明的解析 Markdown 须被至少一条检查使用——仅翻译模式强制（pdf
    模式不强加英文源，遗留声明只作附加对账证据）。
    """
    used = {path for checks in (input_checks or {}).values()
            for check in checks
            for path, _digest in check["facts"]["files"]["sources"]}
    declared = {entry["_parsed_abs"] for entry in source_entries or []}
    for path in sorted(used - declared):
        problems.append(
            "检查实际使用的英文输入未声明源链（不能按文件名猜快照）: %s"
            % path)
    if mode in ("translation", "translation+pdf"):
        for entry in source_entries or []:
            if entry["_parsed_abs"] not in used:
                problems.append(
                    "源链 #%d 声明的解析 Markdown 未被任何检查使用: %s"
                    % (entry["order"], entry["parsed_markdown"]))


def _rooted(root, path):
    """以交付根为基点解释相对路径；绝对路径原样保留。"""
    return path if os.path.isabs(path) else os.path.normpath(
        os.path.join(root, path))


def _parse_tool_args(tool, args, problems, order):
    """按工具真实 CLI 解析记录参数（参数单源）；解析失败记问题。"""
    module = __import__(tool)
    try:
        return module.parse_args(list(args))
    except SystemExit:
        problems.append(
            "核验记录 #%d 的参数无法按 %s 真实 CLI 解析（缺值、未知参数或"
            "位置参数不足）: %r" % (order, tool, list(args)))
        return None


def _check_facts(root_abs, tool, args, order, problems=None):
    """一条核验记录的规范化检查事实（§9.3 单一事实来源）。

    用真实 CLI parse_args 取得实际有序输入/输出、有效语义参数与文件
    依赖摘要：image_map、images_display、provenance、work-dir 导出报告、
    已声明转换映射之外的相关源（api 的清单/目录）等。等价参数写法
    （--pdf=x、布尔开关紧接路径、相对/绝对等价路径）经同一解释得到同一
    语义事实，不凭字符串差异制造新口径；标题/strong token 等字面值不
    拼路径。导出报告内容即使位于 work-dir 也是必需依赖。文件身份按
    规范化完整路径记录；缺失文件摘要记 None（绑定按不完整拒绝）。
    返回 (facts, parsed)；解析失败返回 (None, None)（problems 给定时
    记录问题）。parsed 仅 verify_pdf 需要（路径已按交付根解释）。
    """
    local_problems = problems if problems is not None else []
    parsed = _parse_tool_args(tool, args, local_problems, order)
    if parsed is None:
        return None, None

    def dep(path):
        real = os.path.realpath(_rooted(root_abs, path))
        return [real, _digest_or_none(real)]

    facts = {
        "script_sha256": _digest_or_none(
            os.path.join(SCRIPTS_DIR, KNOWN_TOOLS[tool])),
        "shared_deps": {
            name: _digest_or_none(os.path.join(SCRIPTS_DIR, name))
            for name in CHECK_SHARED_DEPS[tool]},
        "params": {},
        "files": {},
    }
    if tool == "verify_pdf":
        import verify_pdf as pdf_verifier

        facts["files"]["pdf"] = dep(parsed.pdf)
        facts["files"]["inputs"] = [dep(p) for p in parsed.inputs]
        facts["files"]["images_display"] = [dep(p)
                                            for p in parsed.images_display]
        if parsed.provenance:
            facts["files"]["provenance"] = dep(parsed.provenance)
        facts["files"]["unlink_target"] = [dep(p)
                                           for p in parsed.unlink_target]
        report_path = os.path.realpath(os.path.join(
            _rooted(root_abs, parsed.work_dir), pdf_verifier.REPORT_NAME))
        facts["files"]["export_report"] = [report_path,
                                           _digest_or_none(report_path)]
        facts["params"] = {
            "toc_sections": bool(parsed.toc_sections),
            "require_display_map": bool(parsed.require_display_map),
        }
        # 进程内复验以交付根解释相对路径（与子进程 cwd=交付根口径一致）
        parsed.pdf = _rooted(root_abs, parsed.pdf)
        parsed.work_dir = _rooted(root_abs, parsed.work_dir)
        parsed.inputs = [_rooted(root_abs, p) for p in parsed.inputs]
        parsed.images_display = [_rooted(root_abs, p)
                                 for p in parsed.images_display]
        parsed.unlink_target = [_rooted(root_abs, p)
                                for p in parsed.unlink_target]
        if parsed.provenance:
            parsed.provenance = _rooted(root_abs, parsed.provenance)
    else:
        facts["files"]["translated"] = dep(
            parsed[TRANSLATED_PATH_KEYS[tool]])
        sources = []
        for key in SOURCE_PATH_KEYS[tool]:
            value = parsed[key]
            for item in (value if isinstance(value, list) else [value]):
                # 按真实解析顺序登记（保留重复）：同一源以不同角色/次序
                # 重复传入是不同的检查语义，不折叠
                sources.append(dep(item))
        facts["files"]["sources"] = sources
        if parsed.get("image_map"):
            facts["files"]["image_map"] = dep(parsed["image_map"])
        facts["params"] = {
            "strong_tokens": list(parsed["strong_tokens"]),
            "approved_extra_math": list(parsed["approved_extra_math"]),
            "official": list(parsed.get("official", [])),
            "fragment": bool(parsed.get("fragment", False)),
        }
        if parsed.get("delivery_root"):
            facts["params"]["delivery_root"] = os.path.realpath(
                _rooted(root_abs, parsed["delivery_root"]))
        if tool == "verify_api_translation":
            facts["files"]["manifest"] = dep(parsed["manifest_path"])
            facts["files"]["toc"] = dep(parsed["toc_path"])
            facts["params"]["site_root"] = os.path.realpath(
                _rooted(root_abs, parsed["site_root"]))
    return facts, parsed


def _facts_complete(facts):
    """检查事实的全部文件依赖摘要可得才构成完整绑定/身份。

    已声明但缺失（摘要 None）即不完整；未声明的可选依赖（None 值或
    键缺失）不影响。不能以 None==None 判相等放行。
    """
    if facts is None:
        return False
    if facts.get("script_sha256") is None:
        return False
    if any(digest is None
           for digest in (facts.get("shared_deps") or {}).values()):
        return False

    def pairs(node):
        if node is None:
            return True
        if (isinstance(node, list) and len(node) == 2
                and isinstance(node[0], str)):
            return node[1] is not None
        if isinstance(node, list):
            return all(pairs(item) for item in node)
        return True

    return all(pairs(value) for value in (facts.get("files") or {}).values())


def rerun_checks(root, record, problems):
    """只重跑已知核验入口，取得本次机器证据；不向证据目录写入任何内容。

    模式绑定：含 PDF 的模式至少有一条 verify_pdf 记录且其 --pdf 按规范
    化完整路径绑定已声明输出；translation 模式至少一条翻译家族记录。
    PDF 以同一核验计算函数在进程内复验（相对路径按交付根解释），本次
    结果即机器证据；翻译家族以交付根为 cwd 原样复跑，保存实际参数、
    检查器、输出与退出码。翻译家族检查必须覆盖交付记录声明的每个输入。
    返回 (candidates, pending_reviews)：candidates 为待发布条目
    {order, entry, verify_report, export_report_path}。
    """
    import verify_pdf as pdf_verifier

    mode = record.get("mode")
    checks = record.get("checks") or []
    if not checks:
        problems.append("checks 为空：没有可复跑的核验记录，不构成完成依据")
        return [], {}, {}, {}
    root_abs = os.path.realpath(root)
    # 输出绑定按规范化完整路径（basename 相同的其他目录 PDF 不能替验）
    pdf_outputs = {
        os.path.realpath(os.path.join(root_abs, o.get("path", ""))): o
        for o in record.get("outputs", [])
        if str(o.get("path", "")).lower().endswith(".pdf")}
    record_inputs = {os.path.realpath(os.path.join(root_abs, rel))
                     for rel in record.get("inputs") or []}
    tools_used = set()
    verified_pdfs = set()
    covered_inputs = set()  # 翻译家族检查实际核验过的交付输入（P1-3）
    pdf_covered_inputs = set()  # PDF 核验并集覆盖的交付输入（§9.6 分篇）
    # 译文 abs 路径 -> 覆盖它的检查绑定（源资源、检查器、语义参数与
    # 共享脚本依赖），供复核记录的完整 binding 核对（设计 §4.7：复用
    # 人工结论须证明口径未变）。
    input_checks = {}
    # 成品 abs 路径 -> 覆盖它的 verify_pdf 检查上下文（供视觉/链接复核
    # 的完整 binding）。
    pdf_checks = {}
    # 成品 abs 路径 -> 复核类别 -> 报告要求逐项闭合的事项。
    # relaxed_matches 属视觉复核；reviews 列表中的链接与
    # 布局事项分别由 link/visual 复核处置。
    pending_reviews = {}
    candidates = []
    for order, check in enumerate(checks, start=1):
        tool = check.get("tool")
        args = check.get("args") or []
        if tool not in KNOWN_TOOLS:
            problems.append("未知的核验入口: %r（不执行记录中的任意命令）" % tool)
            continue
        tools_used.add(tool)
        script = os.path.join(SCRIPTS_DIR, KNOWN_TOOLS[tool])
        # 检查事实与完整身份同源：真实 CLI 解析 + 文件依赖摘要
        facts, parsed = _check_facts(root_abs, tool, list(args), order,
                                     problems)
        if facts is None:
            continue
        entry = {"tool": tool, "args": args}
        if tool == "verify_pdf":
            # 直接调用的 PDF 计算也以交付根解释相对路径（与 cwd=交付根
            # 的子进程口径一致）；规范化完整路径只用于输出绑定比较。
            pdf_arg = facts["files"]["pdf"][0]
            if pdf_arg not in pdf_outputs:
                problems.append(
                    "verify_pdf 记录 #%d 的 --pdf (%s) 未按规范化完整路径绑定"
                    "任何已声明输出" % (order, pdf_arg))
                continue
            verified_pdfs.add(pdf_arg)
            # R7/§9.3：核验实际参数所用的映射必须就是记录声明的交付级
            # 映射（同一交付映射）；翻译侧 image_map 是来源用途的独立
            # 参数，不与此混淆。记录缺声明或检查未显式绑定均拒绝。
            declared_map = record.get("images_display")
            declared_real = (os.path.realpath(_rooted(root_abs,
                                                      declared_map))
                             if declared_map else None)
            check_maps = {path for path, _digest
                          in facts["files"]["images_display"]}
            if check_maps != ({declared_real} if declared_real
                              else set()):
                problems.append(
                    "verify_pdf 记录 #%d 的 --images-display 与交付记录声明"
                    "的交付级映射不一致（声明 %r vs 实际 %s）；记录与实际"
                    "核验参数必须使用同一交付映射"
                    % (order, declared_map,
                       sorted(check_maps) or "（未显式绑定）"))
                continue
            pdf_checks.setdefault(pdf_arg, []).append({
                'order': order,
                'tool': tool,
                'script_sha256': facts["script_sha256"],
                'shared_deps': facts["shared_deps"],
                'facts': facts,
                'args': list(args)})
            machine_pass, report = pdf_verifier.run_verification(parsed)
            entry["exit_code"] = 0 if machine_pass else 1
            if not machine_pass:
                summary = "; ".join(str(item.get("code"))
                                    for item in report.get("failures", [])[:5])
                problems.append(
                    "核验入口复验失败: verify_pdf（exit 1）%s" % summary)
            else:
                # 逐检查范围：报告绑定的输入须与该检查实际参数一致；
                # 交付级整体覆盖由下方并集门禁负责（§9.6：合法多 PDF
                # 分篇交付中每份报告只覆盖自己实际核验的输入）。
                check_inputs = {os.path.realpath(path)
                                for path in parsed.inputs}
                report_inputs = {
                    os.path.realpath(str(item.get("input")))
                    for item in report.get("management_exclusions", [])
                    if isinstance(item, dict) and item.get("input")}
                if report_inputs != check_inputs:
                    problems.append(
                        "核验报告 #%d 绑定的输入(%s)与该检查实际参数输入"
                        "(%s)不一致，核验证据必须与本次检查范围对应"
                        % (order, sorted(report_inputs),
                           sorted(check_inputs)))
                if not check_inputs <= record_inputs:
                    problems.append(
                        "核验记录 #%d 覆盖了交付记录之外的输入(%s)"
                        % (order, sorted(check_inputs - record_inputs)))
                pdf_covered_inputs.update(check_inputs & record_inputs)
            by_kind = pending_reviews.setdefault(
                pdf_arg, {REVIEW_VISUAL: Counter(), REVIEW_LINK: Counter()})
            for item_index, item in enumerate(
                    report.get("relaxed_matches", [])):
                if not (isinstance(item, dict) and item.get("review", True)):
                    continue
                by_kind[REVIEW_VISUAL].update([
                    review_item_label(item, "relaxed_matches", item_index)])
            for item_index, item in enumerate(report.get("reviews", [])):
                if not isinstance(item, dict):
                    continue
                kind = (REVIEW_LINK if item.get("code") == "range-out-link"
                        else REVIEW_VISUAL)
                by_kind.setdefault(kind, Counter()).update([
                    review_item_label(item, "reviews", item_index)])
            export_report = facts["files"]["export_report"][0]
            candidates.append({
                "order": order, "entry": entry, "verify_report": report,
                "export_report_path": (export_report
                                       if os.path.isfile(export_report)
                                       else None)})
        else:
            # 翻译家族：记录参数原样传给真实 CLI，cwd=交付根；字面值
            # （官方标题/strong token/表达式）不拼路径。
            run = subprocess.run(
                [sys.executable, script] + list(args),
                capture_output=True, text=True, cwd=root_abs)
            entry["exit_code"] = run.returncode
            entry["stdout"] = run.stdout[-4000:]
            entry["stderr"] = run.stderr[-4000:]
            covered = facts["files"]["translated"][0]
            covered_inputs.add(covered)
            input_checks.setdefault(covered, []).append({
                'order': order,
                'tool': tool,
                'script_sha256': facts["script_sha256"],
                'shared_deps': facts["shared_deps"],
                'facts': facts,
            })
            candidates.append({
                "order": order, "entry": entry, "verify_report": None,
                "export_report_path": None})
            if run.returncode != 0:
                problems.append(
                    "核验入口复验失败: %s（exit %d）%s"
                    % (tool, run.returncode, run.stderr.strip()[:200]))
    if "pdf" in mode and "verify_pdf" not in tools_used:
        problems.append("PDF 模式必须有 verify_pdf 核验记录")
    if mode == "translation" and not (tools_used - {"verify_pdf"}):
        problems.append("translation 模式必须有翻译家族核验记录")
    if mode == "translation+pdf":
        if "verify_pdf" not in tools_used:
            problems.append("translation+pdf 模式缺少 verify_pdf 核验记录")
        if not (tools_used - {"verify_pdf"}):
            problems.append("translation+pdf 模式缺少翻译家族核验记录")
    for pdf_path in pdf_outputs:
        if pdf_path not in verified_pdfs:
            problems.append("成品 %s 缺少绑定其规范化路径的 verify_pdf 记录"
                            % pdf_path)
    # P1-3：翻译检查范围必须与交付输入对应——每个声明的输入都必须被
    # 至少一条翻译家族检查的译文参数实际覆盖，不能用指向其他目录正常
    # 文件的检查冒充对本交付的核验。
    if mode in ("translation", "translation+pdf"):
        for rel in record.get("inputs") or []:
            real = os.path.realpath(os.path.join(root_abs, rel))
            if real not in covered_inputs:
                problems.append(
                    "交付输入 %s 未被任何翻译家族检查覆盖：检查范围必须与实际"
                    "交付输入对应，不能凭其他文件的 PASS 完成" % rel)
    # 交付级整体覆盖（§9.6）：每个声明输入都须被至少一条 PDF 核验
    # 实际覆盖，不能用指向其他目录正常文件的核验冒充对本交付的核验。
    if mode in ("pdf", "translation+pdf"):
        for rel in record.get("inputs") or []:
            real = os.path.realpath(os.path.join(root_abs, rel))
            if real not in pdf_covered_inputs:
                problems.append(
                    "交付输入 %s 未被任何 PDF 核验覆盖：检查范围必须与实际"
                    "交付输入对应，不能凭其他文件的 PASS 完成" % rel)
    return candidates, pending_reviews, input_checks, pdf_checks


def _binding_digest(binding):
    """binding 的稳定摘要（问题定位用；比较仍用完整对象）。"""
    return hashlib.sha256(json.dumps(
        binding, ensure_ascii=False, sort_keys=True).encode(
            "utf-8")).hexdigest()[:16]


def expected_review_binding(kind, target, root, record, source_entries,
                            input_checks, pdf_checks, identity):
    """计算一条复核应绑定的完整上下文（§4.7 reviews[].binding）。

    语义/源对账复核绑定译文及其全部源链、覆盖检查（工具/脚本/共享
    依赖/语义参数/有序源）与译文图片资源身份；视觉/链接复核绑定对应
    PDF 的有序输入、映射、资源、检查与环境/样式政策。两类绑定均投影
    交付入口脚本身份（§9.6）。无关产物不进入该条绑定；binding 不含
    复核正文、交付记录自身摘要或本次生成报告，避免循环依赖。无法构成
    完整绑定时返回 None（由调用方按缺绑定拒绝）。
    """
    root_abs = os.path.realpath(root) if root else None
    # 交付入口自身参与结果判断（§9.3 有限依赖集合）：其摘要必须投影
    # 进复核绑定，入口口径变化须使既有复核失效（§9.6）。
    delivery_entry = (identity or {}).get("delivery_entry") or {}

    def rooted(rel):
        return rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(root_abs, rel)) if root_abs else rel

    def chain_of(covers_target):
        """该目标的源链投影：统一身份中的源链 + 逐快照解析侧资源身份。

        每份快照的实际图片（含 SVG/CSS 递归依赖）按声明快照与原始引用
        进入绑定；任一源图/子资源变化改变统一身份，同样必须使旧复核
        失效；摘要缺失即视为绑定不完整。"""
        chains = []
        for entry in source_entries or []:
            if covers_target not in (entry.get("covers") or []):
                continue
            chain = dict(_source_identity(entry, rooted),
                         family=entry["family"],
                         source_version=entry["source_version"])
            resources = []
            for snap_record in (identity.get("resources", {})
                                .get("sources", {})
                                .get(entry["parsed_markdown"]) or []):
                for image in snap_record.get("images") or []:
                    resources.append([snap_record["snapshot"],
                                      image["source_ref"],
                                      image["sha256"]])
            chain["resources"] = resources
            chains.append(chain)
        return chains

    if kind in (REVIEW_SOURCE_RECONCILE, REVIEW_SEMANTIC):
        covering = (input_checks or {}).get(
            os.path.realpath(os.path.join(root_abs, target))
            if root_abs else target, [])
        if not covering:
            return None
        if delivery_entry.get("script_sha256") is None:
            return None  # 交付入口摘要缺失：绑定不完整（§9.6）
        if any(not _facts_complete(item.get("facts")) for item in covering):
            return None  # 检查依赖缺文件/缺摘要：不能得到有效绑定
        resources = (identity.get("resources", {}).get("inputs", {})
                     .get(target) or [])
        if any(digest is None for _src, digest in resources):
            return None  # 资源身份不可得不构成完整绑定（不豁免图片身份）
        chains = chain_of(target)
        if any(digest is None
               for chain in chains
               for _snap, _ref, digest in chain["resources"]):
            return None  # 源链资源摘要缺失：绑定不完整，须重新复核
        environment = identity.get("environment") or {}
        target_digest = (identity.get("inputs", {}).get(target))
        if target_digest is None:
            return None
        return {
            "target_sha256": target_digest,
            "checks": [{
                "order": item["order"],
                "tool": item["tool"],
                "script_sha256": item["script_sha256"],
                "shared_deps": item["shared_deps"],
                "facts": item["facts"],
            } for item in covering],
            "source_chains": chains,
            "resources": [[src, digest] for src, digest in resources],
            "environment": {key: environment.get(key)
                            for key in TRANSLATION_ENV_KEYS},
            "delivery_entry": delivery_entry,
        }
    if kind in (REVIEW_VISUAL, REVIEW_LINK):
        covering = (pdf_checks or {}).get(
            os.path.realpath(os.path.join(root_abs, target)), [])
        if not covering:
            return None
        if delivery_entry.get("script_sha256") is None:
            return None  # 交付入口摘要缺失：绑定不完整（§9.6）
        if any(not _facts_complete(context.get("facts"))
               for context in covering):
            return None
        # 按该 PDF 全部覆盖检查的实际有序输入投影（§9.3 按实际覆盖
        # 关系，不混入其他目标的独有依赖）：输入摘要回到统一身份的
        # 声明路径键，资源只取这些输入的实际枚举。
        rel_of = {}
        for rel in (identity.get("inputs") or {}):
            rel_of[os.path.realpath(rooted(rel))] = rel
        ordered_inputs = {}
        covered_real = []
        for context in covering:
            for path, digest in ((context["facts"].get("files") or {})
                                 .get("inputs") or []):
                if digest is None:
                    return None  # 覆盖输入摘要不可得：绑定不完整
                rel = rel_of.get(path, path)
                if rel not in ordered_inputs:
                    ordered_inputs[rel] = digest
                    covered_real.append(path)
        resources = []
        seen_resources = set()
        for path in covered_real:
            rel = rel_of.get(path)
            if rel is None:
                continue  # 记录外输入的资源不在交付身份枚举范围
            for item in (identity.get("resources", {})
                         .get("inputs", {}).get(rel) or []):
                key = tuple(item)
                if key not in seen_resources:
                    seen_resources.add(key)
                    resources.append(item)
        if any(digest is None for _src, digest in resources):
            return None
        target_digest = (identity.get("outputs", {}).get(target))
        if target_digest is None:
            return None
        map_declared = record.get("images_display")
        map_digest = identity.get("images_display")
        if map_declared and map_digest is None:
            return None  # 已声明交付映射但摘要不可得：绑定不完整
        return {
            "target_sha256": target_digest,
            "ordered_inputs": ordered_inputs,
            "images_display": {
                "path": record.get("images_display"),
                "sha256": identity.get("images_display"),
            },
            "resources": [[src, digest] for src, digest in resources],
            "checks": [{
                "order": context["order"],
                "tool": context["tool"],
                "script_sha256": context["script_sha256"],
                "shared_deps": context["shared_deps"],
                "facts": context["facts"],
            } for context in covering],
            "environment": dict(identity.get("environment") or {}),
            "style_policy": identity.get("style_policy"),
            "delivery_entry": delivery_entry,
        }
    return None


def check_reviews(record, problems, pending_reviews=None, root=None,
                   input_checks=None, pdf_checks=None, source_entries=None,
                   identity=None):
    """按交付模式分别落实必需复核类别并绑定产物与待复核项（R4/4.7/4.9）。

    复核类别合法不等于必需复核齐全：translation 需要源全量对账+语义
    复核；每个 PDF 成品需要视觉复核（链接复核不构成替代）；translation+pdf
    需要全部类别。每条复核必须绑定本交付声明的实际产物（target 须为
    声明的输入或输出路径；源对账/语义复核须绑定当前输入摘要，PDF 复核
    须绑定成品摘要）；PDF 报告的机器容忍项（review=true 的待复核
    segment）必须由绑定该成品的闭合视觉复核逐项列明（items），不得
    笼统声明“已复核”。
    """
    mode = record.get("mode")
    reviews = record.get("reviews") or []
    if "pdf" in mode and not reviews:
        problems.append("PDF 模式必须引用已闭合的视觉复核记录，不能只靠机器通过")
    pdf_outputs = {o.get("path"): o.get("sha256")
                   for o in record.get("outputs", [])
                   if str(o.get("path", "")).lower().endswith(".pdf")}
    input_digests = {}
    for rel in record.get("inputs") or []:
        path = os.path.join(root, rel) if root else None
        input_digests[rel] = (sha256_file(path)
                              if path and os.path.isfile(path) else None)
    declared = set(input_digests) | set(pdf_outputs) | {
        o.get("path") for o in record.get("outputs", [])}
    valid_by_kind = {kind: set() for kind in KNOWN_REVIEW_KINDS}
    covered_items = {}  # (kind, target) -> 该复核逐项列明的事项及次数
    for review in reviews:
        if review.get("status") != "closed":
            problems.append(
                "复核未闭合不能宣布完成: %r（%s）"
                % (review.get("target"), review.get("status")))
            continue
        kind = review.get("kind")
        if kind not in KNOWN_REVIEW_KINDS:
            problems.append("复核类别未知: %r（需 %s 之一）"
                            % (kind, "/".join(sorted(KNOWN_REVIEW_KINDS))))
        if not (review.get("note") or "").strip():
            problems.append("复核 %r 缺少实际记录内容（note 为空）" % review.get("target"))
        target = review.get("target")
        # 复核必须绑定本交付声明的产物：给不存在/未声明目标的复核
        # （如对 nonexistent.pdf 的 visual）不能闭合任何类别或待复核项。
        if not target or target not in declared:
            problems.append(
                "复核 %r 未绑定本交付声明的输入或输出，不能闭合复核"
                % target)
            continue
        digest = review.get("sha256")
        if target in input_digests and kind in (
                REVIEW_SOURCE_RECONCILE, REVIEW_SEMANTIC):
            current_digest = input_digests[target]
            if not digest:
                problems.append(
                    "复核 %r 未绑定输入摘要，无法证明针对当前译文" % target)
                continue
            if current_digest is None or digest != current_digest:
                problems.append(
                    "复核摘要与当前输入不符: %s（输入变化后旧证据失效）"
                    % target)
                continue
        if target in pdf_outputs:
            if digest and digest != pdf_outputs[target]:
                problems.append(
                    "复核 %s 绑定的摘要与成品不符" % target)
                continue
            elif not digest:
                problems.append(
                    "复核 %r 未绑定成品摘要，无法证明针对同一成品" % target)
                continue
        if kind in (REVIEW_SOURCE_RECONCILE, REVIEW_SEMANTIC,
                    REVIEW_VISUAL, REVIEW_LINK):
            expected = expected_review_binding(
                kind, target, root, record, source_entries, input_checks,
                pdf_checks, identity)
            declared_binding = review.get("binding")
            if expected is None:
                problems.append(
                    "复核 %r（%s）无法构成完整绑定上下文（覆盖检查或源链"
                    "缺失），须补齐后重新复核" % (target, kind))
            elif not isinstance(declared_binding, dict):
                problems.append(
                    "复核 %r（%s）缺少完整 binding（期望摘要 %s）；旧记录"
                    "的零散绑定字段不构成完整上下文，须重新复核"
                    % (target, kind, _binding_digest(expected)))
            elif declared_binding != expected:
                problems.append(
                    "复核 %r（%s）的 binding 与当前完整上下文不符（期望"
                    "摘要 %s，记录摘要 %s）：依赖变化后旧结论失效，须重新"
                    "复核" % (target, kind, _binding_digest(expected),
                              _binding_digest(declared_binding)))
        if kind in valid_by_kind:
            valid_by_kind[kind].add(target)
        items = review.get("items")
        if items is not None:
            if not (isinstance(items, list)
                    and all(isinstance(i, str) for i in items)):
                problems.append(
                    "复核 %r 的 items 必须是 segment 字符串列表" % target)
            else:
                covered_items.setdefault(
                    (kind, target), Counter()).update(items)
    # 每个成品都必须有绑定其摘要的闭合视觉复核（唯一判定点，不再
    # 按模式重复检查同一类别）。
    for target in pdf_outputs:
        if target not in valid_by_kind[REVIEW_VISUAL]:
            problems.append("成品 %s 缺少绑定其摘要的闭合视觉复核" % target)
    # 逐项对账：核验报告要求人工复核的待复核项必须由绑定该成品的
    # 闭合视觉复核逐条列明（4.7/4.9：报告所依赖的人工兜底真正闭合；
    # items 按产物归属，别的成品的复核不能代闭）。
    if pending_reviews:
        root_abs = os.path.realpath(root) if root else None
        for rel, digest in pdf_outputs.items():
            abs_path = os.path.realpath(os.path.join(root_abs, rel)) \
                if root_abs else rel
            for kind, pending in pending_reviews.get(abs_path, {}).items():
                pending_counts = (pending if isinstance(pending, Counter)
                                  else Counter(pending))
                uncovered_counts = pending_counts - covered_items.get(
                    (kind, rel), Counter())
                uncovered = sorted(uncovered_counts.elements())
                if uncovered:
                    problems.append(
                        "成品 %s 的核验报告待处置项未由绑定该成品的 "
                        "%s 复核逐项闭合（%d 项）：%s"
                        % (rel, kind, len(uncovered),
                           "；".join(uncovered[:3])))
    # 按模式核对复核范围：翻译模式中每个输入均需源对账与语义复核。
    if mode in ("translation", "translation+pdf"):
        for target in record.get("inputs") or []:
            missing = [kind for kind in (REVIEW_SOURCE_RECONCILE,
                                         REVIEW_SEMANTIC)
                       if target not in valid_by_kind[kind]]
            if missing:
                problems.append(
                    "交付输入 %s 缺少必需复核类别（须绑定该产物）: %s"
                    % (target, "、".join(missing)))


def ensure_persistent(evidence_dir):
    """证据目录必须真实、可写，且不在系统临时根下。"""
    from _html_fidelity import temp_root_paths

    real = os.path.realpath(evidence_dir)
    for root in temp_root_paths():
        if real == root or real.startswith(root + os.sep):
            raise DeliveryError(
                "证据目录不得位于系统临时根（清理后无法回查）: %s" % evidence_dir)
    os.makedirs(evidence_dir, exist_ok=True)
    probe = os.path.join(evidence_dir, ".write-probe")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("ok")
    os.remove(probe)


def _new_batch_dir(evidence_dir):
    """在证据目录下开一个未占用的新批次目录；旧批次永不覆盖。"""
    while True:
        name = "batch-%s" % uuid.uuid4().hex[:12]
        path = os.path.join(evidence_dir, name)
        if not os.path.exists(path):
            os.makedirs(path)
            return name, path


def _batch_files(candidates, source_report=None):
    """待写入批次的文件：源链对账报告 + 核验报告 + 导出证据副本。"""
    files = []
    if source_report is not None:
        files.append(("00_sources_report.json", ("json", source_report)))
    for candidate in candidates:
        if candidate["verify_report"] is not None:
            files.append(("%02d_verify_report.json" % candidate["order"],
                          ("json", candidate["verify_report"])))
        if candidate["export_report_path"]:
            files.append(("%02d_export_report.json" % candidate["order"],
                          ("copy", candidate["export_report_path"])))
    return files


def _identity_missing_digests(identity):
    """完整身份中必需摘要不可得的位置列表（发布前拒绝，§9.3）。

    任一必需文件摘要为 None 即列出；两侧同为 None 不能判相等放行。
    未声明的可选项（键缺失/None 值）不在必需范围。
    """
    missing = []
    for rel, digest in (identity.get("inputs") or {}).items():
        if digest is None:
            missing.append("输入 %s" % rel)
    for rel, digest in (identity.get("outputs") or {}).items():
        if digest is None:
            missing.append("输出 %s" % rel)
    if "images_display" in identity and identity["images_display"] is None:
        missing.append("交付级映射")
    for entry in identity.get("sources") or []:
        label = entry.get("parsed_markdown")
        if entry.get("parsed_sha256") is None:
            missing.append("源链 %s 的解析 Markdown" % label)
        for snap in entry.get("snapshots") or []:
            if snap.get("snapshot_sha256") is None:
                missing.append("源链 %s 的快照 %s" % (label, snap["snapshot"]))
            map_info = snap.get("per_stem_map")
            if map_info and map_info.get("sha256") is None:
                missing.append("源链 %s 的解析期映射 %s"
                               % (label, map_info["path"]))
        conv = entry.get("table_conversions")
        if conv and conv.get("sha256") is None:
            missing.append("源链 %s 的转换映射 %s" % (label, conv["path"]))
    resources = identity.get("resources") or {}
    for rel, items in (resources.get("inputs") or {}).items():
        for src, digest in items:
            if digest is None:
                missing.append("输入 %s 的资源 %s" % (rel, src))
    for parsed, snaps in (resources.get("sources") or {}).items():
        for snap_record in snaps:
            for image in snap_record.get("images") or []:
                if image.get("sha256") is None:
                    missing.append("源链 %s 的快照 %s 资源 %s"
                                   % (parsed, snap_record["snapshot"],
                                      image["source_ref"]))
    for check in identity.get("checks") or []:
        if not _facts_complete(check.get("facts")):
            missing.append("核验记录 #%d（%s）的检查依赖"
                           % (check.get("order"), check.get("tool")))
    if (identity.get("delivery_entry") or {}).get("script_sha256") is None:
        missing.append("交付入口脚本")
    for key, digest in (identity.get("style_policy") or {}).items():
        if digest is None:
            missing.append("样式政策 %s" % key)
    return missing


def publish_evidence(evidence_dir, record, root, candidates,
                     baseline_identity, record_path=None,
                     record_digest=None, source_entries=None,
                     source_report=None):
    """全部检查通过后发布证据：独立批次 + 重读核对 + 原子替换索引。

    批次写入并重读核对后、切换索引前以同一身份函数重新枚举计算完整
    依赖身份（输入/产物/源链/资源/检查/环境/样式政策，含交付记录文件
    自身摘要），与检查开始时的基线一致才发布；运行期间变化即拒绝。
    任一必需依赖摘要不可得（含核验前基线）直接失败，不能以
    None==None 判相等通过；归档导出报告须与核验前基线版本一致，复制
    后的当前摘要不能重新当成基线。任何写入/核对失败抛 DeliveryError：
    最多留下未引用的新批次，上一索引及其全部引用内容保持原样。
    """
    if not record_path or not record_digest:
        raise DeliveryError(
            "发布必须提供交付记录路径与装载时摘要（记录自身摘要检查"
            "不可跳过）")
    missing = _identity_missing_digests(baseline_identity)
    if missing:
        raise DeliveryError(
            "必需依赖摘要不可得，不能发布: %s" % "; ".join(missing[:5]))
    baseline_reports = {}
    for check in baseline_identity.get("checks") or []:
        facts = check.get("facts") or {}
        pair = (facts.get("files") or {}).get("export_report")
        if pair:
            baseline_reports[check.get("order")] = pair[1]
    batch_name, batch_path = _new_batch_dir(evidence_dir)
    written = []
    for name, (kind, payload) in _batch_files(candidates, source_report):
        target = os.path.join(batch_path, name)
        if kind == "copy":
            shutil.copyfile(payload, target)
            if sha256_file(target) != sha256_file(payload):
                raise DeliveryError("批次文件 %s 与导出证据重读摘要不一致" % name)
            # 归档导出报告须与核验前基线版本一致（复制时当前摘要不是
            # 基线；基线缺失由上面的完整性检查先行拒绝）。要归档导出
            # 报告却没有对应基线记录是口径不一致，同样拒绝发布。
            expected = baseline_reports.get(int(name.split("_", 1)[0]))
            if expected is None:
                raise DeliveryError(
                    "核验前基线缺少批次文件 %s 对应的导出报告摘要，"
                    "拒绝发布" % name)
            if sha256_file(target) != expected:
                raise DeliveryError(
                    "批次文件 %s 与核验前基线的导出报告版本不一致，拒绝发布"
                    % name)
        else:
            data = json.dumps(payload, ensure_ascii=False, indent=2)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(data)
            # 重读核对：落盘内容必须与本次结果深度一致
            with open(target, encoding="utf-8") as handle:
                reread = json.load(handle)
            if reread != payload:
                raise DeliveryError("批次文件 %s 重读内容与本次结果不一致" % name)
        written.append((name, sha256_file(target)))
    # 批次写入并重读后、切换索引前：以同一函数重新枚举完整身份并比对
    # （运行期间变化即拒绝；此时只留下未引用新批次，上一索引不变）。
    if record_path and record_digest \
            and sha256_file(record_path) != record_digest:
        raise DeliveryError(
            "交付记录在运行期间被改写（输入/产物/口径身份变化），拒绝发布")
    current = compute_delivery_identity(root, record, source_entries)
    if current != baseline_identity:
        changed = [key for key in set(current) | set(baseline_identity)
                   if current.get(key) != baseline_identity.get(key)]
        raise DeliveryError(
            "发布前复查发现依赖身份在运行期间变化（%s），拒绝发布"
            % "、".join(sorted(str(key) for key in changed)))
    missing = _identity_missing_digests(current)
    if missing:
        raise DeliveryError(
            "发布前复查发现必需依赖摘要不可得（%s），拒绝发布"
            % "; ".join(missing[:5]))
    by_order = {candidate["order"]: candidate for candidate in candidates}
    for name, digest in written:
        candidate = by_order.get(int(name.split("_", 1)[0]))
        if candidate is None:
            continue  # 00_ 前缀为批次级文件（源链对账报告），不属检查
        key = ("report" if name.endswith("verify_report.json")
               else "export_report")
        candidate["entry"][key] = "%s/%s" % (batch_name, name)
        candidate["entry"]["%s_sha256" % key] = digest
    checks_index = [candidate["entry"]
                    for candidate in sorted(candidates,
                                            key=lambda c: c["order"])]
    root_real = os.path.realpath(root)
    index = {
        "version": RECORD_VERSION,
        "mode": record["mode"],
        "delivery_root": root_real,
        "inputs": record["inputs"],
        "identity": baseline_identity,
        "outputs": [
            {"path": o.get("path"), "sha256": o.get("sha256")}
            for o in record.get("outputs", [])
        ],
        "images_display": record.get("images_display"),
        "batch": batch_name,
        "sources_report": ("%s/00_sources_report.json" % batch_name
                           if source_report is not None else None),
        "checks": checks_index,
        "reviews": record.get("reviews", []),
    }
    index_path = os.path.join(evidence_dir, "delivery_index.json")
    tmp_path = os.path.join(evidence_dir,
                            ".delivery_index.json.%s.tmp" % uuid.uuid4().hex[:8])
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, index_path)
    except OSError as exc:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise DeliveryError("证据索引写入失败（上一索引保持原样）: %s" % exc)
    return index_path


def _report_problems(problems):
    print("FAIL: 交付检查未通过（%d 项）" % len(problems), file=sys.stderr)
    for item in problems[:20]:
        print("  - %s" % item, file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="交付完成统一检查：目录允许清单、身份、核验复跑与持久证据")
    parser.add_argument("--record", required=True, help="交付记录 JSON")
    parser.add_argument("--evidence-dir", required=True,
                        help="持久证据目录（须在工作区外且不在系统临时根）")
    args = parser.parse_args(argv)

    problems = []
    record_digest = None
    try:
        record_digest = (sha256_file(args.record)
                         if os.path.isfile(args.record) else None)
        record = load_record(args.record)
        root = record["delivery_root"]
        if not os.path.isdir(root):
            raise DeliveryError("交付根不存在: %s" % root)
        ensure_persistent(args.evidence_dir)
        check_root_layout(root, record, problems, record_path=args.record)
        check_map_entries(root, record, problems)
        check_identities(root, record, problems)
        source_entries = check_source_chains(root, record, problems)
        if problems:
            # 范围/目录/身份/源链预检失败即停止，不执行核验复跑（§4.7）
            _report_problems(problems)
            return 1
        baseline = compute_delivery_identity(root, record, source_entries)
        # 通过预检后先做独立源全量对账（含逐表转换映射），再复跑核验
        source_report = run_source_reconcile(
            root, record, source_entries, problems)
        candidates, pending_reviews, input_checks, pdf_checks = rerun_checks(
            root, record, problems)
        align_sources_with_checks(source_entries, input_checks, problems,
                                  mode=record.get("mode"))
        check_reviews(record, problems, pending_reviews, root=root,
                      input_checks=input_checks, pdf_checks=pdf_checks,
                      source_entries=source_entries, identity=baseline)
    except DeliveryError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    if problems:
        _report_problems(problems)
        return 1
    try:
        index_path = publish_evidence(
            args.evidence_dir, record, root, candidates, baseline,
            record_path=args.record, record_digest=record_digest,
            source_entries=source_entries, source_report=source_report)
    except (DeliveryError, OSError) as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    print("交付检查通过：证据索引 %s" % index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
