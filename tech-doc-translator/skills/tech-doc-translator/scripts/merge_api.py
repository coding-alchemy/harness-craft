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
import hashlib
import json
import os
import re
import shutil
import sys

from _html_fidelity import DISPLAY_MAP_VERSION


_IMAGE_RE = re.compile(r'(!\[[^\]]*\]\()([^)]+)(\))')


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
    """集中图片到交付 images/；同名不同内容时拒绝静默覆盖。"""
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

    return _IMAGE_RE.sub(replace, body)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load_page_display_map(display_src, page_rel):
    """查找解析期为该页生成的显示尺寸映射；无则返回 None。"""
    stem = os.path.splitext(page_rel)[0]
    candidates = [
        os.path.join(display_src, stem + '.images_display.json'),
        os.path.join(display_src, os.path.basename(stem) + '.images_display.json'),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return json.load(open(candidate, encoding='utf-8'))
    return None


def _bind_display_entries(page_rel, page_map, translated_body, site_root):
    """把页面级显示尺寸映射绑定为交付条目（出现序号 + 资源身份校验）。"""
    entries = []
    if not page_map:
        return entries
    page_entries = list(page_map.get('entries', []))
    undetermined = list(page_map.get('undetermined', []))
    max_occurrence = max(
        [e.get('occurrence', 0) for e in page_entries + undetermined] or [0])
    refs = [m.group(2).strip() for m in _IMAGE_RE.finditer(translated_body)]
    if max_occurrence != len(refs):
        raise ValueError(
            '显示尺寸映射出现数 %d 与译文图片数 %d 不符（页面 %s）'
            % (max_occurrence, len(refs), page_rel))
    resolved = []
    for ref in refs:
        source = _source_image(site_root, page_rel, ref)
        resolved.append(('images/%s' % os.path.basename(source), source))
    by_occurrence = {entry['occurrence']: entry for entry in page_entries}
    for position, (delivered_ref, translated_source) in enumerate(
            resolved, start=1):
        entry = by_occurrence.get(position)
        if entry is None:
            continue  # 解析期未确定尺寸的出现：交付层不伪造条目
        # 资源身份校验：映射记录的源图片必须解析为译文中该次出现的同一资源。
        entry_source = _source_image(site_root, page_rel, entry['image'])
        if os.path.abspath(entry_source) != os.path.abspath(translated_source):
            raise ValueError(
                '显示尺寸映射第 %d 次出现与译文资源不符（页面 %s）：%s != %s'
                % (position, page_rel, entry['image'], delivered_ref))
        entries.append({
            'occurrence': position,
            'image': delivered_ref,
            'sha256': _sha256(translated_source),
            'width': entry['width'],
            'source': {
                'snapshot': page_map.get('snapshot'),
                'node': entry.get('source_node'),
            },
        })
    return entries


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

    bodies = []
    assets = {}
    page_display_batches = []  # [(该页绑定条目, 该页图片数)]，按清单顺序
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
                batch = _bind_display_entries(p, page_map, raw_body, site_root)
                page_display_batches.append(
                    (batch, len(_IMAGE_RE.findall(raw_body))))
        except ValueError as exc:
            sys.exit(str(exc))
        bodies.append(body)

    # 页内出现序号重编号为合并文档中的全局出现序号。
    display_entries = []
    occurrence_offset = 0
    for batch, image_count in page_display_batches:
        for entry in batch:
            entry['occurrence'] += occurrence_offset
            display_entries.append(entry)
        occurrence_offset += image_count

    output_dir = os.path.dirname(os.path.abspath(out_path))
    for relative, source in assets.items():
        destination = os.path.join(output_dir, *relative.split('/'))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.abspath(source) != os.path.abspath(destination):
            shutil.copy2(source, destination)

    open(out_path, 'w', encoding='utf-8').write('\n\n---\n\n'.join(bodies) + '\n')
    if args.display_src:
        display_path = os.path.join(output_dir, 'images_display.json')
        with open(display_path, 'w', encoding='utf-8') as handle:
            json.dump({'version': DISPLAY_MAP_VERSION,
                       'markdown': os.path.basename(out_path),
                       'entries': display_entries},
                      handle, ensure_ascii=False, indent=2)
        print('display map bound: %d entries -> %s' % (
            len(display_entries), display_path))
    print('merged %d pages, localized %d images -> %s' %
          (len(pages), len(assets), out_path))


if __name__ == '__main__':
    main()
