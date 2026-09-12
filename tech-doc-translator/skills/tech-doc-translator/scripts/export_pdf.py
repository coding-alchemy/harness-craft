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

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

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
    """读取各章的显示尺寸映射，返回 (绑定结果, 映射文件清单)。

    显式 --images-display 优先；否则使用输入 Markdown 同目录的
    images_display.json（不递归猜测项目根）。条目按 markdown 归属分派；
    无映射的章按自然尺寸回退并记录，不视为失败。绑定不一致（出现越界、
    资源路径或摘要不符、非法宽度）记为 fail。
    """
    bindings = {}  # chapter.path -> {occurrence: {"px": float, "entry": dict}}
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
    for chapter in chapters:
        candidates = list(explicit_files)
        same_dir = chapter.dir / DISPLAY_MAP_NAME
        if same_dir.is_file() and same_dir not in candidates:
            candidates.append(same_dir)
        chapter_entries = []
        for map_path in candidates:
            used_paths.add(str(map_path.resolve()))
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
            map_entries = payload.get("entries", [])
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
                    chapter_entries.append((entry, map_path))
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
                        chapter_entries.append((entry, map_path))
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
        bindings[chapter.path] = occurrence_map
    return bindings, sorted(used_paths)


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


def soup_images(chapter):
    return [img for img in chapter.soup.find_all("img") if img.get("src")]


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

# PDF 默认排除的章首模板字段；独立“来源”字段未被点名，保留。
MANAGEMENT_FIELD_LABELS = ("原文", "译例说明")
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
    tokens = _HEAD_STRUCTURE_MD.parse(text)
    lines = text.split("\n")
    exclusions = []
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
        segments = []
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
        exclusions.extend(
            {
                "label": label,
                "start_line": seg_start,
                "end_line": seg_end,
                "reason": EXCLUSION_REASON,
            }
            for label, seg_start, seg_end in segments
            if label in MANAGEMENT_FIELD_LABELS
        )
        index = close_index + 1
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
    if match:
        return match.group(1).strip(), "inline", "legacy_paren"
    return text, "inline", "dollar_inline"


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
        return body

    markdown.add_render_rule("fence", render_fence)
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
        self.projected_text, self.exclusions = project_management_fields(self.text)
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


def inline_images(chapter, diagnostics, resource_registry):
    soup = chapter.soup
    for image in soup.find_all("img"):
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
            image.decompose()
            continue
        digest = sha256_file(path)
        key = str(path)
        if key not in resource_registry:
            mime = mimetypes.guess_type(str(path))[0]
            if not mime:
                diagnostics.append(
                    {
                        "severity": "fail",
                        "code": "unknown-image-type",
                        "message": "无法识别图片类型：%s" % path.name,
                        "input": str(chapter.path),
                        "line": line,
                    }
                )
                image.decompose()
                continue
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
            resource_registry[key] = {
                "path": str(path),
                "sha256": digest,
                "bytes": path.stat().st_size,
                "mime": mime,
                "data_uri": "data:%s;base64,%s" % (mime, payload),
            }
        record = resource_registry[key]
        image["src"] = record["data_uri"]
        chapter.images.append(
            {k: record[k] for k in ("path", "sha256", "bytes")}
            | {"src": src, "source_line": line}
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


def file_uri(path):
    return Path(path).as_uri()


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
<link rel="stylesheet" href="%s">
<link rel="stylesheet" href="%s">
<style>
%s
</style>
</head>
<body>
%s
<script src="%s"></script>
<script>%s</script>
</body>
</html>
""" % (
        escape(title),
        file_uri(katex_dir / "katex.min.css"),
        file_uri(ASSETS_DIR / "style.css"),
        pygments_css,
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


def export(paths, output, work_dir, unlink_targets=(), images_display_paths=(),
           toc_sections=False):
    work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = []
    report = {"diagnostics": diagnostics}

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

    resource_registry = {}
    # 显示尺寸映射先于渲染读取：命中条目在图片内联后注入受限宽度。
    bindings, display_map_paths = load_display_maps(
        chapters, list(images_display_paths), diagnostics
    )
    # 先完成全部章节解析，再做链接消解：跨章文件链接与片段链接都依赖
    # 所有章节的目标映射就绪。
    for chapter in chapters:
        parse_chapter(chapter)
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

    for chapter in chapters:
        collect_chapter_facts(chapter)
    display_records = {}
    natural_fallback = {}
    for chapter in chapters:
        resolve_links(chapter, chapters, diagnostics, unlink_targets)
        inline_images(chapter, diagnostics, resource_registry)
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

    title = chapters[0].headings[0]["text"] if chapters[0].headings else chapters[0].path.stem
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
    fonts = browser_checks.get("fonts", {}) if browser_checks else {}
    # 正文与代码的 CJK 回退族必须至少一项可用，否则中文会退到不可控字体。
    cjk_font_ok = any(fonts.get(f, False) for f in ("STFangsong", "STHeiti"))
    machine_ok = (
        not hard_failures
        and browser_checks
        and not browser_checks.get("katex")
        and not browser_checks.get("images")
        and not browser_checks.get("overflow")
        and browser_checks.get("scrollWidth", 0) <= browser_checks.get("clientWidth", 0) + 1
        and cjk_font_ok
    )

    report.update(
        {
            "status": STATUS_MACHINE_PASS if machine_ok else STATUS_MACHINE_FAIL,
            "candidate": str(candidate),
            "pdf_sha256": sha256_file(candidate),
            "output_target": str(output),
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
    protected = {Path(item["path"]).resolve() for item in inputs}
    protected |= {Path(r["path"]).resolve() for r in resources}
    if output.resolve() in protected:
        print(
            "FAIL: 输出路径不得指向输入文件或原始资源：%s" % output, file=sys.stderr
        )
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, output)
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
        )
    except ExportError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
