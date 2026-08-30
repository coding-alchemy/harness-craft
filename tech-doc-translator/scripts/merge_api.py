#!/usr/bin/env python3
"""按页面清单顺序合并已翻译 API 页面。

用法：
    python3 merge_api.py <manifest.txt> <site_root> <out.md>

规则：
- 清单每行一个相对 HTML 路径。
- 每个页面对应 <site_root>/<dir>/trans_<basename>.md。
- 页面中的本地图片集中复制到 <out.md 同级>/images/，引用改为交付目录相对路径。
- 页面之间用单独一行的 `---` 分隔。
- 不做全局空白压缩，保留代码围栏内容。
"""
import filecmp
import os
import re
import shutil
import sys


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


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    manifest_path, site_root, out_path = sys.argv[1:]

    with open(manifest_path, encoding='utf-8') as f:
        pages = [line.strip() for line in f if line.strip()]

    bodies = []
    assets = {}
    for p in pages:
        tp = translated_path(site_root, p)
        if not os.path.exists(tp):
            sys.exit('translated file missing: %s' % tp)
        body = open(tp, encoding='utf-8').read().strip()
        try:
            body = _localize_images(body, site_root, p, assets)
        except ValueError as exc:
            sys.exit(str(exc))
        bodies.append(body)

    output_dir = os.path.dirname(os.path.abspath(out_path))
    for relative, source in assets.items():
        destination = os.path.join(output_dir, *relative.split('/'))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.abspath(source) != os.path.abspath(destination):
            shutil.copy2(source, destination)

    open(out_path, 'w', encoding='utf-8').write('\n\n---\n\n'.join(bodies) + '\n')
    print('merged %d pages, localized %d images -> %s' %
          (len(pages), len(assets), out_path))


if __name__ == '__main__':
    main()
