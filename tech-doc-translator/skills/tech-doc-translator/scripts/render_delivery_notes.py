#!/usr/bin/env python3
"""交付文书统计段渲染（第 2 批 R12）：只读交付记录与证据，写出统计段。

用法：
    python3 render_delivery_notes.py --record <交付记录.json>
        --kind visual|link|delivery|files [--evidence-dir <证据目录>]
        --output <新路径>

visual、link 读记录里 verify_pdf 检查的 --work-dir 下的导出报告与核验报告；
delivery 读 --evidence-dir 下的 delivery_index.json；files 列出源快照及其
资源与成品的路径、sha256、字节数（JSON）。需要人判断的位置写占位
〔待补：…〕：含占位的复核备注与交付根用户说明不能通过 verify_delivery。
--output 必须是新路径；落在交付根一级时只能是记录 files 已登记为
user-note 的两份用户说明之一。不改交付记录。
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter

import verify_delivery as delivery

KINDS = ("visual", "link", "delivery", "files")


def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _load_json(path, what):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise delivery.DeliveryError("%s不可读：%s（%s）" % (what, path, exc))


def _rel(root, path):
    """交付根内的路径写成相对路径，根外的保留完整路径。"""
    path = os.path.realpath(path)
    relative = os.path.relpath(path, root)
    return path if relative.startswith("..") else relative


def _counts(values):
    counts = Counter(values)
    if not counts:
        return ""
    return "（%s）" % "、".join("%s %d" % (key, number) for key, number
                               in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def _adaptation(root, item):
    parts = []
    if item.get("viewbox"):
        parts.append("viewBox %s" % " ".join("%g" % value for value in item["viewbox"]))
    if item.get("display_width_px"):
        parts.append("显示宽度 %gpx" % item["display_width_px"])
    return "%s（%s）" % (_rel(root, item["image"]), "，".join(parts))


def _pages(pages):
    return "、".join("p%d" % page for page in pages) or "无"


def _key_pages(key_pages):
    return "、".join(
        ("p%d" % item["first"] if item["first"] == item["last"]
         else "p%d–%d" % (item["first"], item["last"]))
        + "（%s）" % "、".join(item["reasons"]) for item in key_pages)


def programmatic_block(aid):
    """R13：无读图能力时视觉复核备注的开头段（设计 §12.3 的固定格式）。"""
    if aid.get("dependency_error"):
        raise delivery.DeliveryError("辅助渲染不可用，不能做程序化目检：%s" % aid["dependency_error"])
    pages = aid.get("pages") or []
    summary = aid.get("summary") or {}
    total = len(pages)
    rendered = sum(1 for entry in pages if entry.get("render_ok"))
    failed = summary.get("render_failed") or []
    footers = summary.get("footer_anomalies") or []
    return [
        "%s会话与子代理均无读图能力，未做逐页人眼目检。" % delivery.PROGRAMMATIC_VISUAL_TAG,
        "最少检查：%s；疑似空白页 %s；页脚页码 %s；导出与 PDF 机器核验通过。" % (
            "%d 页渲染成功" % total if rendered == total
            else "%d/%d 页渲染成功（渲染失败 %s）" % (rendered, total, _pages(failed)),
            _pages(summary.get("blank_suspects") or []),
            "异常页 %s" % _pages(footers) if footers
            else "1/%d 至 %d/%d 连续" % (total, total, total)),
        "关键页：%s" % _key_pages(aid.get("key_pages") or []),
        "用户抽查：〔待补：用户抽查的页码、日期与结论〕",
        "",
    ]


def pdf_reports(root, record):
    """记录里每条 verify_pdf 检查：(PDF, work-dir, 导出报告, 核验报告)，并核对报告对应当前 PDF。"""
    import verify_pdf

    found = []
    for order, check in enumerate(record.get("checks") or [], start=1):
        if check.get("tool") != "verify_pdf":
            continue
        problems = []
        parsed = delivery._parse_tool_args(
            "verify_pdf", list(check.get("args") or []), problems, order, root)
        if parsed is None:
            raise delivery.DeliveryError("；".join(problems))
        pdf = os.path.realpath(delivery._rooted(root, parsed.pdf))
        work_dir = os.path.realpath(delivery._rooted(root, parsed.work_dir))
        export = _load_json(os.path.join(work_dir, verify_pdf.REPORT_NAME), "导出报告")
        verify = _load_json(os.path.join(work_dir, verify_pdf.VERIFY_NAME), "核验报告")
        if not os.path.isfile(pdf) or export.get("pdf_sha256") != _sha256(pdf):
            raise delivery.DeliveryError(
                "导出报告与当前 PDF 不一致：%s（先重新导出并核验）" % pdf)
        if verify.get("status") != verify_pdf.STATUS_MACHINE_PASS:
            raise delivery.DeliveryError(
                "核验报告不是机器通过：%s（先运行 verify_pdf）" % work_dir)
        found.append((pdf, work_dir, export, verify))
    if not found:
        raise delivery.DeliveryError("记录里没有 verify_pdf 检查，不能渲染视觉或链接统计")
    return found


def render_visual(root, record):
    lines = []
    for pdf, work_dir, export, verify in pdf_reports(root, record):
        relaxed = verify.get("relaxed_matches") or []
        reviews = verify.get("reviews") or []
        coverage = Counter()
        for chapter in (export.get("image_coverage") or {}).values():
            coverage.update({key: value for key, value in chapter.items()
                             if isinstance(value, int) and not isinstance(value, bool)})
        unrestored = (coverage["missing"] + coverage["no-source-constraint"]
                      + coverage["unresolved-size"])
        macros = (export.get("katex_macros") or {}).get("macros") or {}
        adaptations = (export.get("image_adaptations") or {}).get("images") or []
        if verify.get("visual_aid") is not None:
            lines += programmatic_block(verify["visual_aid"])
        lines += [
            "- 成品：%s（sha256 %s…，%s 页）；依据：%s"
            % (_rel(root, pdf), export["pdf_sha256"][:12], verify.get("pages"),
               _rel(root, work_dir)),
            "- 放宽项：%d 项%s" % (len(relaxed), _counts(item.get("reason") for item in relaxed)),
            "- 待复核项：%d 项%s" % (len(reviews), _counts(item.get("code") for item in reviews)),
            "- 图片：%d 次出现，已恢复 %d，未恢复 %d（缺映射 %d、源无约束 %d、尺寸未定 %d）"
            % (coverage["total"], coverage["restored"], unrestored, coverage["missing"],
               coverage["no-source-constraint"], coverage["unresolved-size"]),
            "- KaTeX 宏表：%s" % ("、".join("%s → %s" % item for item in sorted(macros.items()))
                                 or "未使用"),
            "- 图片适配声明：%s" % ("；".join(_adaptation(root, item) for item in adaptations)
                                    or "未使用"),
        ]
    return lines + ["- 视觉检查结论：〔待补：视觉检查结论〕",
                    "- 例外与未解决项：〔待补：例外与未解决项〕"]


def render_link(root, record):
    lines = []
    for pdf, _work_dir, export, verify in pdf_reports(root, record):
        unlinked = [link for item in verify.get("unlinked_links") or []
                    for link in item.get("links") or []]
        range_out = export.get("range_out_links") or []
        toc_out = (export.get("toc") or {}).get("out_links") or []
        lines += [
            "- 成品：%s" % _rel(root, pdf),
            "- 内部链接注解：%s 个" % verify.get("internal_link_annots"),
            "- 外部链接：%d 个（去重 URI）" % len(verify.get("external_uri_annots") or []),
            "- 目标默认排除、转为纯文本的链接：%d 处%s"
            % (len(unlinked), _counts(link.get("href") for link in unlinked)),
            "- 范围外本地链接：%d 处%s" % (len(range_out), _counts(
                "目标存在" if link.get("exists") else "目标缺失" for link in range_out)),
            "- 目录里的范围外链接：%d 处" % len(toc_out),
        ]
        if range_out or toc_out:
            lines.append("- 范围外链接的处置：〔待补：经用户确认的处置方式〕")
    return lines + ["- 链接复核结论：〔待补：实际点击的代表性内部链接、脚注回链与外链〕"]


def render_delivery(root, record, evidence_dir):
    if not evidence_dir:
        raise delivery.DeliveryError("--kind delivery 需要 --evidence-dir")
    index = _load_json(os.path.join(evidence_dir, "delivery_index.json"), "证据索引")
    if index.get("inputs") != record.get("inputs") or index.get("outputs") != record.get("outputs"):
        raise delivery.DeliveryError("证据索引的输入或输出与交付记录不一致，先重跑 verify_delivery")
    identity = index.get("identity") or {}
    environment = identity.get("environment") or {}
    lines = ["- 交付模式：%s；证据批次：%s" % (index.get("mode"), index.get("batch")),
             "- 输入顺序：%s" % "；".join(
                 "%d. %s（sha256 %s…）" % (number, rel, (identity.get("inputs") or {}).get(rel, "")[:12])
                 for number, rel in enumerate(index.get("inputs") or [], start=1))]
    lines += ["- 输出：%s（sha256 %s…）" % (item["path"], item["sha256"][:12])
              for item in index.get("outputs") or []]
    lines.append("- 检查：%s" % "；".join(
        "%d. %s 退出码 %s" % (number, check.get("tool"), check.get("exit_code"))
        for number, check in enumerate(index.get("checks") or [], start=1)))
    lines.append("- 复核：%s" % "；".join(
        "%s %s %s（%d 项）" % (review.get("kind"), review.get("target"), review.get("status"),
                              len(review.get("items") or []))
        for review in index.get("reviews") or []))
    lines.append("- 依赖版本：%s" % ("、".join(
        "%s %s" % item for item in sorted(environment.items())) or "无记录"))
    return lines + ["- 例外与未解决项：〔待补：例外与未解决项〕"]


def _file_entry(root, path):
    return {"path": _rel(root, path), "sha256": _sha256(path), "bytes": os.path.getsize(path)}


def render_files(root, record):
    """源快照及其资源、成品的清单；与 source_dependency_paths 的快照资源部分同口径。"""
    from _verification import resource_identity_digest

    problems = []
    entries = delivery.check_source_chains(root, record, problems, source_only=True)
    if problems:
        raise delivery.DeliveryError("来源链预检失败：" + "；".join(problems[:5]))
    sources = set()
    for source in record.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for declaration in [source] + list(source.get("snapshots") or []):
            if isinstance(declaration, dict) and declaration.get("snapshot"):
                sources.add(os.path.realpath(delivery._rooted(root, declaration["snapshot"])))
    for entry in entries:
        for facts in entry.get("_source_facts") or []:
            for item in (facts or {}).get("images", []):
                if item.get("path"):
                    memo = {}
                    resource_identity_digest(item["path"], _memo=memo)
                    sources.add(os.path.realpath(item["path"]))
                    sources.update(os.path.realpath(path) for path in memo)
    outputs = [os.path.realpath(delivery._rooted(root, item["path"]))
               for item in record.get("outputs") or []]
    missing = [path for path in sorted(sources) + outputs if not os.path.isfile(path)]
    if missing:
        raise delivery.DeliveryError("清单文件不存在：%s" % "、".join(missing[:5]))
    return {"version": 1, "delivery_root": root,
            "sources": [_file_entry(root, path) for path in sorted(sources)],
            "outputs": [_file_entry(root, path) for path in outputs]}


def check_output(root, record, output):
    """--output 必须是新路径；交付根一级只允许已登记为 user-note 的用户说明。"""
    if os.path.lexists(output):
        raise delivery.DeliveryError("--output 须是新路径，不覆盖已有文件：%s" % output)
    path = os.path.realpath(output)
    if os.path.dirname(path) != os.path.realpath(root):
        return
    name = os.path.basename(path)
    if name not in delivery.USER_NOTE_NAMES:
        raise delivery.DeliveryError("交付根一级只能写用户说明（%s）：%s"
                                     % ("、".join(delivery.USER_NOTE_NAMES), name))
    if (record.get("files") or {}).get(name) != "user-note":
        raise delivery.DeliveryError(
            "交付记录 files 未把 %s 登记为 user-note；先在记录的 files 里加入：%s"
            % (name, json.dumps({name: "user-note"}, ensure_ascii=False)))


def render(record_path, kind, output, evidence_dir=None):
    record = delivery.load_record(record_path)
    root = os.path.realpath(record["delivery_root"])
    check_output(root, record, output)
    if kind == "files":
        text = json.dumps(render_files(root, record), ensure_ascii=False, indent=2) + "\n"
    else:
        lines = {"visual": lambda: render_visual(root, record),
                 "link": lambda: render_link(root, record),
                 "delivery": lambda: render_delivery(root, record, evidence_dir)}[kind]()
        text = "\n".join(lines) + "\n"
    with open(output, "x", encoding="utf-8") as handle:
        handle.write(text)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description="渲染交付文书与复核备注的统计段（只读记录与证据）")
    parser.add_argument("--record", required=True, help="交付记录 JSON")
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--evidence-dir", help="持久证据目录（--kind delivery 需要）")
    parser.add_argument("--output", required=True, help="输出新路径")
    args = parser.parse_args(argv)
    try:
        render(args.record, args.kind, args.output, args.evidence_dir)
    except (delivery.DeliveryError, OSError) as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    print("已渲染 %s：%s（〔待补：…〕处由执行者补写）" % (args.kind, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
