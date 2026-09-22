"""导出/核验共用的图片出现枚举、覆盖分类与解码预算（R2/R5）。

导出器在全量内联/解码/打印之前调用；核验器从最终 Markdown、映射与
资源独立重算同一分类。逐项区分 missing / no-source-constraint /
unresolved-size 三类未恢复，严格策略要求全部有效确定出现。预算是只读
估算（Σ宽×高×4），不代表实际峰值，不改变退出语义。
"""
import os
from pathlib import Path

from _verification import check_image_file


# 初始告警阈值：保守工程提示值，不是 Chromium 内存上限。
IMAGE_BUDGET_WARN_BYTES = 512 * 1024 * 1024

COVER_RESTORED = "restored"
COVER_MISSING = "missing"
COVER_NO_CONSTRAINT = "no-source-constraint"
COVER_UNRESOLVED = "unresolved-size"

_COVER_LABELS = {
    COVER_MISSING: "无映射条目",
    COVER_NO_CONSTRAINT: "源无尺寸约束",
    COVER_UNRESOLVED: "源尺寸无法确定",
}


class Occurrence:
    """一次真实图片出现的只读事实。"""

    def __init__(self, chapter, occurrence, ref, path=None, sha256=None,
                 line=None, kind=None, pixel_size=None, frames=None,
                 pixel_known=False):
        self.chapter = chapter
        self.occurrence = occurrence
        self.ref = ref
        self.path = path
        self.sha256 = sha256
        self.line = line
        self.kind = kind
        self.pixel_size = pixel_size
        self.frames = frames
        self.pixel_known = pixel_known


def bitmap_facts(path):
    """只读资源判型与位图尺寸（Pillow 头部信息，不做全量像素解码）。"""
    try:
        ok, kind, _reason = check_image_file(path)
    except Exception:  # noqa: BLE001  判型失败按未知处理，不阻断枚举
        return "unknown", None, None, False
    if not ok:
        return "unknown", None, None, False
    if kind in ("PNG", "JPEG", "GIF", "WEBP"):
        try:
            from PIL import Image
        except ImportError:
            return kind, None, None, False
        try:
            image = Image.open(path)
        except Exception:  # noqa: BLE001
            return kind, None, None, False
        try:
            size = image.size
            frames = getattr(image, "n_frames", 1)
        except Exception:  # noqa: BLE001
            image.close()
            return kind, None, None, False
        image.close()
        if size and size[0] > 0 and size[1] > 0:
            return kind, (int(size[0]), int(size[1])), frames, True
        return kind, None, None, False
    return kind, None, None, False  # SVG 等非位图：无法可靠估算


def undetermined_binding_diagnostics(chapter_label, raw_entries, enumeration):
    """未确定条目沿用确定条目的出现序号与资源身份规则。

    raw_entries: [(entry, map_path)]（映射文件原始未确定条目）；
    enumeration: enumerate_images 的记录（与实际渲染图片同序）。出现
    越界、声明资源与第 N 次出现的路径或摘要不符均判失败——是否有尺寸
    不决定已声明的身份是否须核对，坏映射不因未确定而降级为回退告警。
    """
    diagnostics = []
    for entry, map_path in raw_entries:
        occurrence = entry.get("occurrence")
        if not isinstance(occurrence, int) or occurrence < 1:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-binding",
                    "message": "未确定尺寸条目出现序号非法：%r" % (entry,),
                    "input": chapter_label,
                }
            )
            continue
        if occurrence > len(enumeration):
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-binding",
                    "message": "未确定尺寸条目出现序号 %d 超出本章图片数 %d"
                    % (occurrence, len(enumeration)),
                    "input": chapter_label,
                }
            )
            continue
        record = enumeration[occurrence - 1]
        entry_image = entry.get("image")
        if entry_image:
            resolved = (Path(map_path).parent / str(entry_image)).resolve()
            if resolved != Path(record["path"]):
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "images-display-binding",
                        "message": "未确定尺寸条目资源与第 %d 次出现不符：%s != %s"
                        % (occurrence, resolved, record["path"]),
                        "input": chapter_label,
                    }
                )
                continue
        entry_sha = entry.get("sha256")
        if entry_sha and entry_sha != record["sha256"]:
            diagnostics.append(
                {
                    "severity": "fail",
                    "code": "images-display-digest",
                    "message": "未确定尺寸条目资源摘要与第 %d 次出现不符：%s"
                    % (occurrence, entry_image or record["path"]),
                    "input": chapter_label,
                }
            )
    return diagnostics


def classify_occurrences(occurrences, bindings, undetermined_map):
    """逐出现归类；返回 [(Occurrence, 类别, 说明)]。

    bindings: {chapter: {occurrence: 绑定记录}}；undetermined_map:
    {(chapter, occurrence): reason_code}。两者都来自映射文件，由调用方
    校验合法性（坏映射在映射装载层失败，不在此降级）。bindings 的章键
    与 occ.chapter 同为字符串形式。
    """
    items = []
    for occ in occurrences:
        chapter_bindings = bindings.get(occ.chapter) or {}
        if occ.occurrence in chapter_bindings:
            items.append((occ, COVER_RESTORED, None))
            continue
        code = undetermined_map.get((occ.chapter, occ.occurrence))
        if code == COVER_NO_CONSTRAINT:
            items.append((occ, COVER_NO_CONSTRAINT, _COVER_LABELS[COVER_NO_CONSTRAINT]))
        elif code == COVER_UNRESOLVED:
            items.append((occ, COVER_UNRESOLVED, _COVER_LABELS[COVER_UNRESOLVED]))
        else:
            items.append((occ, COVER_MISSING, _COVER_LABELS[COVER_MISSING]))
    return items


def coverage_summary(items):
    """按章节汇总：总数 = 已恢复 + 三类未恢复（按出现次数计）。"""
    summary = {}
    for occ, cls, _detail in items:
        chapter = summary.setdefault(occ.chapter, {
            "total": 0, "restored": 0, "missing": 0,
            "no-source-constraint": 0, "unresolved-size": 0,
        })
        chapter["total"] += 1
        chapter[cls if cls != COVER_RESTORED else "restored"] += 1
    return summary


def coverage_diagnostics(items, require, base_code):
    """把覆盖分类转为诊断；普通模式告警继续，严格模式未恢复即失败。"""
    diagnostics = []
    for occ, cls, detail in items:
        if cls == COVER_RESTORED:
            continue
        context = {
            "severity": "warn",
            "code": "%s-%s" % (base_code, cls),
            "message": "第 %d 次图片出现未恢复源尺寸（%s）" % (occ.occurrence, detail),
            "input": occ.chapter,
        }
        if occ.line is not None:
            context["line"] = occ.line
        if require:
            context["severity"] = "fail"
            context["code"] = "images-display-required"
            context["message"] = (
                "严格尺寸保真策略：第 %d 次图片出现未恢复源尺寸（%s），"
                "已拒绝导出" % (occ.occurrence, detail))
        diagnostics.append(context)
    return diagnostics


def decode_budget(items):
    """只读解码预算：按摘要去重与按出现累加两种 Σ(w×h×4)。

    未知非位图/无法读取尺寸的资源单列为 unknown，不记零；GIF/WebP
    多帧额外开销单独列示。返回 (预算 dict, 告警诊断列表)。
    """
    dedup = {}
    occurrence_total = 0
    unknown = []
    multi_frame = []
    per_resource = {}
    per_resource_loc = {}
    for occ, _cls, _detail in items:
        if not occ.pixel_known:
            unknown.append("%s#%d %s" % (occ.chapter, occ.occurrence,
                                         os.path.basename(occ.ref or "")))
            continue
        width, height = occ.pixel_size
        estimate = width * height * 4
        occurrence_total += estimate
        # 同一资源各出现估算相同，记首次出现的章/出现序号/资源名作定位
        per_resource_loc.setdefault(
            occ.sha256, "%s#%d %s" % (occ.chapter, occ.occurrence,
                                      os.path.basename(occ.ref or "")))
        per_resource[occ.sha256] = max(
            per_resource.get(occ.sha256, 0), estimate)
        dedup.setdefault(occ.sha256, estimate)
        if occ.frames and occ.frames > 1:
            multi_frame.append("%s#%d %s（%d 帧）"
                               % (occ.chapter, occ.occurrence,
                                  os.path.basename(occ.ref or ""),
                                  occ.frames))
    diagnostics = []
    budget = {
        "threshold_bytes": IMAGE_BUDGET_WARN_BYTES,
        "dedup_estimate_bytes": sum(dedup.values()),
        "occurrence_estimate_bytes": occurrence_total,
        "unknown_items": sorted(set(unknown)),
        "multi_frame_items": sorted(set(multi_frame)),
        "largest": [
            {"sha256": digest[:12], "estimate_bytes": size,
             "location": per_resource_loc[digest]}
            for digest, size in sorted(per_resource.items(),
                                       key=lambda kv: -kv[1])[:5]
        ],
    }
    if occurrence_total > IMAGE_BUDGET_WARN_BYTES:
        diagnostics.append({
            "severity": "warn",
            "code": "image-decode-budget",
            "message": "按出现累加的解码估算 %.1f MiB 超过阈值 %d MiB"
                       "（去重口径 %.1f MiB）；最大资源: %s"
                       % (occurrence_total / (1 << 20),
                          IMAGE_BUDGET_WARN_BYTES // (1 << 20),
                          budget["dedup_estimate_bytes"] / (1 << 20),
                          "; ".join("%s…%d MiB（%s）"
                                    % (item["sha256"],
                                       item["estimate_bytes"] // (1 << 20),
                                       item["location"])
                                    for item in budget["largest"][:3])),
        })
    if unknown:
        diagnostics.append({
            "severity": "warn",
            "code": "image-budget-incomplete",
            "message": "%d 项资源无法可靠估算解码负担（非位图或尺寸未知），"
                       "未计入预算: %s"
                       % (len(budget["unknown_items"]),
                          "; ".join(budget["unknown_items"][:5])),
        })
    if multi_frame:
        diagnostics.append({
            "severity": "warn",
            "code": "image-budget-multiframe",
            "message": "%d 项 GIF/WebP 多帧资源存在额外解码开销: %s"
                       % (len(budget["multi_frame_items"]),
                          "; ".join(budget["multi_frame_items"][:5])),
        })
    return budget, diagnostics
