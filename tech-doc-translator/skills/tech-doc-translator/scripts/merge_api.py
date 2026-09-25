#!/usr/bin/env python3
"""按页面清单顺序合并已翻译 API 页面。

用法：
    python3 merge_api.py <manifest.txt> <site_root> <out.md> [--display-src <dir>]

规则：
- 清单每行一个相对 HTML 路径。
- 每个页面对应 <site_root>/<dir>/trans_<basename>.md。
- 页面中的本地图片集中复制到 <out.md 同级>/images/，引用改为交付目录相对路径。
- 提供 --display-src 时读取解析期生成的 <页名>.images_display.json，
  按出现序号与资源身份绑定到交付路径，写出 <out.md 同级>/images_display.json；
  绑定不一致（出现序号错位、资源身份不符）直接失败，不按 basename 猜测。
- 页面之间用单独一行的 `---` 分隔。
- 不做全局空白压缩，保留代码围栏内容。
"""
import argparse
import filecmp
import json
import os
import re
import shutil
import sys

from _html_fidelity import DISPLAY_MAP_VERSION
from _image_binding import bind_page, load_parse_map
from _verification import fenced_line_numbers, in_code_span, line_code_spans


_IMAGE_RE = re.compile(r'(!\[[^\]]*\]\()([^)]+)(\))')


def _real_image_matches(body):
    """译文中的真实图片引用（内联语法匹配，按文档顺序）。

    返回 (绝对起点, 绝对终点, match)；代码围栏与行内代码跨度内的图片
    字面量是代码内容：不改写、不计数、不参与缺映射门禁（与共享图片
    枚举同一代码语义口径，03-S3）。
    """
    fenced = fenced_line_numbers(body)
    matches = []
    offset = 0
    for line_no, line in enumerate(body.split('\n'), start=1):
        if line_no not in fenced and '![' in line:
            code_spans = line_code_spans(line)
            matches.extend(
                (offset + m.start(), offset + m.end(), m)
                for m in _IMAGE_RE.finditer(line)
                if not in_code_span(code_spans, m.start(), m.end()))
        offset += len(line) + 1
    return matches


def translated_path(site_root, page_rel):
    dir_name = os.path.dirname(page_rel)
    base = os.path.basename(page_rel)
    name = 'trans_' + os.path.splitext(base)[0] + '.md'
    return os.path.join(site_root, dir_name, name)


def _source_image(site_root, page_rel, reference):
    """把页面相对图片引用解析为本地快照内的文件。"""
    clean = reference.split('#', 1)[0].split('?', 1)[0].strip()
    if not clean or re.match(r'^[a-z][a-z0-9+.-]*:', clean, re.I):
        raise ValueError('图片尚未本地化: %s' % reference)
    if os.path.isabs(clean):
        raise ValueError('图片必须使用相对路径: %s' % reference)

    root = os.path.abspath(site_root)
    source = os.path.abspath(os.path.normpath(
        os.path.join(root, os.path.dirname(page_rel), clean)))
    if os.path.commonpath([root, source]) != root:
        raise ValueError('图片路径越出本地快照: %s' % reference)
    if not os.path.isfile(source):
        raise ValueError('本地图片不存在: %s（页面 %s）' % (reference, page_rel))
    return source


def _localize_images(body, site_root, page_rel, assets):
    """集中图片到交付 images/；同名不同内容时拒绝静默覆盖。

    代码内的图片字面量不是真实出现：保持原文，不解析其目标文件。
    """
    def replace(match):
        reference = match.group(2).strip()
        source = _source_image(site_root, page_rel, reference)
        name = os.path.basename(source)
        delivered = 'images/' + name
        previous = assets.get(delivered)
        if previous and not filecmp.cmp(previous, source, shallow=False):
            raise ValueError(
                '图片文件名冲突且内容不同: %s（%s / %s）' %
                (delivered, previous, source))
        assets[delivered] = source
        return match.group(1) + delivered + match.group(3)

    parts = []
    cursor = 0
    for start, end, match in _real_image_matches(body):
        parts.append(body[cursor:start])
        parts.append(replace(match))
        cursor = end
    parts.append(body[cursor:])
    return ''.join(parts)


def _load_page_display_map(display_src, page_rel):
    """查找解析期为该页生成的显示尺寸映射；无则返回 None。

    找到的映射装载后立即按 validate_parse_map 校验：文件存在但为空壳
    或非法结构（如 ``{}``、未知版本）与缺失同样失败——空对象没有可
    核对的独立来源事实，不能作为合法缺省以空映射覆盖既有交付映射
    （F4）；无图页面无映射文件仍合法免映射。
    """
    stem = os.path.splitext(page_rel)[0]
    candidates = [
        os.path.join(display_src, stem + '.images_display.json'),
        os.path.join(display_src, os.path.basename(stem) + '.images_display.json'),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return load_parse_map(candidate)
    return None


def _bind_display_entries(page_rel, page_map, translated_body, site_root,
                          markdown_label):
    """把页面级显示尺寸映射绑定为交付条目（出现序号 + 资源身份校验）。

    绑定核心与通用回补共用（_image_binding.bind_page）：逐次出现核对
    独立来源资源身份，解析期记录 resource_sha256 的新映射做字节级比对，
    旧映射回退到快照路径一致性；确定项与未确定项都保留并重编号。
    """
    if not page_map:
        return [], []
    page_entries = list(page_map.get('entries', []))
    page_undetermined = list(page_map.get('undetermined', []))
    max_occurrence = max(
        [e.get('occurrence', 0) for e in page_entries + page_undetermined] or [0])
    refs = [m.group(2).strip() for _s, _e, m in _real_image_matches(
        translated_body)]
    if max_occurrence != len(refs):
        raise ValueError(
            '显示尺寸映射出现数 %d 与译文图片数 %d 不符（页面 %s）'
            % (max_occurrence, len(refs), page_rel))
    occurrences = []
    legacy_path_checks = []
    for ref in refs:
        source = _source_image(site_root, page_rel, ref)
        occurrences.append(('images/%s' % os.path.basename(source),
                            source, source))
        # 旧映射没有解析期资源身份记录：回退到路径一致性核对
        legacy_path_checks.append(source)
    by_occurrence = {}
    for entry in page_entries:
        by_occurrence[entry['occurrence']] = entry
    for entry in page_undetermined:
        by_occurrence[entry['occurrence']] = entry
    # 路径一致性核对始终执行：映射 image 必须解析为译文该次出现的
    # 同一资源（防止映射字段被改指其他文件）；字节级身份由绑定核心的
    # resource_sha256 比对承担。
    for position, entry in by_occurrence.items():
        if position < 1 or position > len(legacy_path_checks):
            continue
        entry_source = _source_image(site_root, page_rel, entry['image'])
        if os.path.abspath(entry_source) != os.path.abspath(
                legacy_path_checks[position - 1]):
            raise ValueError(
                '显示尺寸映射第 %d 次出现与译文资源不符（页面 %s）'
                % (position, page_rel))
    return bind_page(markdown_label, page_map, occurrences)


def main():
    parser = argparse.ArgumentParser(description='按页面清单顺序合并已翻译 API 页面')
    parser.add_argument('manifest')
    parser.add_argument('site_root')
    parser.add_argument('out')
    parser.add_argument(
        '--display-src',
        help='解析期 <页名>.images_display.json 所在目录；提供后才关联显示尺寸')
    args = parser.parse_args()

    manifest_path, site_root, out_path = args.manifest, args.site_root, args.out

    with open(manifest_path, encoding='utf-8') as f:
        pages = [line.strip() for line in f if line.strip()]

    output_dir = os.path.dirname(os.path.abspath(out_path))
    bodies = []
    assets = {}
    page_display_batches = []  # [(确定条目, 未确定条目, 该页图片数)]，按清单顺序
    for p in pages:
        tp = translated_path(site_root, p)
        if not os.path.exists(tp):
            sys.exit('translated file missing: %s' % tp)
        raw_body = open(tp, encoding='utf-8').read()
        body = raw_body.strip()
        try:
            body = _localize_images(body, site_root, p, assets)
            if args.display_src:
                page_map = _load_page_display_map(args.display_src, p)
                if page_map is None and _real_image_matches(raw_body):
                    sys.exit(
                        '解析期显示尺寸映射缺失（页面有图）: %s —— '
                        '--display-src 目录中未找到对应 .images_display.json；'
                        '有图页面不能以空映射合并并覆盖既有交付映射' % p)
                # 交付映射固定写入 export/：条目 markdown 以映射目录为
                # 基准的完整相对路径登记（../book.md），避免同名歧义。
                map_dir = os.path.join(output_dir, 'export')
                batch = _bind_display_entries(
                    p, page_map, raw_body, site_root,
                    markdown_label=os.path.relpath(
                        os.path.abspath(out_path),
                        os.path.abspath(map_dir)))
                page_display_batches.append(
                    (batch, len(_real_image_matches(raw_body))))
        except ValueError as exc:
            sys.exit(str(exc))
        bodies.append(body)

    # 页内出现序号重编号为合并文档中的全局出现序号；未确定项同序保留。
    display_entries = []
    display_undetermined = []
    occurrence_offset = 0
    for (batch_entries, batch_undetermined), image_count in page_display_batches:
        for entry in batch_entries + batch_undetermined:
            entry['occurrence'] += occurrence_offset
            if entry.get('image'):
                entry['image'] = os.path.join('..', entry['image'])
            (display_entries if 'width' in entry else display_undetermined)\
                .append(entry)
        occurrence_offset += image_count

    output_dir = os.path.dirname(os.path.abspath(out_path))
    for relative, source in assets.items():
        destination = os.path.join(output_dir, *relative.split('/'))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.abspath(source) != os.path.abspath(destination):
            shutil.copy2(source, destination)

    open(out_path, 'w', encoding='utf-8').write('\n\n---\n\n'.join(bodies) + '\n')
    if args.display_src:
        # 新交付布局：交付级映射固定写入 export/ 子目录，条目引用相对
        # 映射目录解析（../images/...），不再写根目录副本。
        export_dir = os.path.join(output_dir, 'export')
        display_path = os.path.join(export_dir, 'images_display.json')
        os.makedirs(export_dir, exist_ok=True)
        with open(display_path, 'w', encoding='utf-8') as handle:
            json.dump({'version': DISPLAY_MAP_VERSION,
                       'markdown': os.path.basename(out_path),
                       'entries': display_entries,
                       'undetermined': display_undetermined},
                      handle, ensure_ascii=False, indent=2)
        print('display map bound: %d entries, %d undetermined -> %s' % (
            len(display_entries), len(display_undetermined), display_path))
    print('merged %d pages, localized %d images -> %s' %
          (len(pages), len(assets), out_path))


if __name__ == '__main__':
    main()
