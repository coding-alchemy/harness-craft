#!/usr/bin/env python3
"""按工作包头部上下文中的 source_order 排序合并译文。

用法：
    python3 merge_work_packages.py <out.md> <wp_001.md> [<wp_002.md> ...]
    python3 merge_work_packages.py <out.md> <wp_dir>

行为：
    - 读取每个工作包的 YAML frontmatter，按 source_order 排序。
    - 缺失、重复或不连续的 source_order / 小节分片映射直接失败。
    - 去除每个文件首尾空白后拼接；文件之间保留一个空行。
    - 不执行全局空白压缩，不修改代码围栏内容。
"""
import sys
import os
import re
import glob as _glob


_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)


def _read_frontmatter(path):
    text = open(path, encoding='utf-8').read()
    m = _FRONTMATTER_RE.search(text)
    if not m:
        raise ValueError('%s 缺少 YAML frontmatter' % path)

    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            meta[key.strip()] = value.strip().strip('"')

    for key in ('source_order', 'section_id', 'fragment_index'):
        if not meta.get(key):
            raise ValueError('%s 缺少 %s' % (path, key))
    try:
        order = int(meta['source_order'])
        fragment_index = int(meta['fragment_index'])
    except ValueError:
        raise ValueError('%s 的 source_order/fragment_index 必须为整数' % path)
    if order <= 0 or fragment_index < 0:
        raise ValueError('%s 的 source_order/fragment_index 超出范围' % path)

    return {
        'source_order': order,
        'section_id': meta['section_id'],
        'fragment_index': fragment_index,
    }, text[m.end():]


def _validate_mapping(packages):
    orders = [meta['source_order'] for meta, _, _ in packages]
    if len(set(orders)) != len(orders):
        raise ValueError('source_order 重复: %s' % orders)
    expected = list(range(1, len(packages) + 1))
    if sorted(orders) != expected:
        raise ValueError('source_order 必须连续为 %s，实际为 %s' %
                         (expected, sorted(orders)))

    fragments = {}
    for meta, path, _ in packages:
        key = (meta['section_id'], meta['fragment_index'])
        if key in fragments:
            raise ValueError(
                '小节分片映射重复: section_id=%s fragment_index=%d（%s / %s）' %
                (key[0], key[1], fragments[key], path))
        fragments[key] = path
    for section_id in sorted(set(key[0] for key in fragments)):
        indexes = sorted(key[1] for key in fragments if key[0] == section_id)
        if indexes != list(range(len(indexes))):
            raise ValueError('小节 %s 的 fragment_index 不连续: %s' %
                             (section_id, indexes))


def merge(out_path, inputs):
    packages = []
    for p in inputs:
        meta, body = _read_frontmatter(p)
        packages.append((meta, p, body))

    _validate_mapping(packages)
    packages.sort(key=lambda x: x[0]['source_order'])

    parts = []
    for meta, p, body in packages:
        body = body.strip('\n')
        if body:
            parts.append(body)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(parts))
        f.write('\n')

    return [p for _, p, _ in packages]


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_path = sys.argv[1]
    second = sys.argv[2]

    if len(sys.argv) == 3 and os.path.isdir(second):
        inputs = sorted(_glob.glob(os.path.join(second, 'wp_*.md')))
    else:
        inputs = sys.argv[2:]

    missing = [p for p in inputs if not os.path.isfile(p)]
    if missing:
        sys.exit('工作包不存在: %s' % ', '.join(missing))

    try:
        used = merge(out_path, inputs)
    except ValueError as exc:
        sys.exit('工作包映射无效: %s' % exc)
    print('已合并 %d 个工作包 -> %s' % (len(used), out_path))
    for p in used:
        print('  order=%d %s' % (_read_frontmatter(p)[0]['source_order'], p))


if __name__ == '__main__':
    main()
