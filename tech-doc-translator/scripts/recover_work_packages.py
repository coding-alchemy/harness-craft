#!/usr/bin/env python3
"""从文件事实恢复工作包完成状态。

用法：
    python3 recover_work_packages.py <source.md> <wps_dir> [trans_dir] [strategy]

行为：
    - 根据源文件重新 split 得到期望工作包列表。
    - 检查译文目标（默认与 wps_dir 相同，或由 frontmatter target_file 指定）
      是否存在、非空、且通过结构与内容块计数校验。
    - 校验失败、无法独立验证或计数不符的工作包一律判为需重做，不降级复用。
    - 不依赖中央状态 JSON/数据库，只从文件事实恢复。
"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_work_packages as swp


_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)
_RESIDUAL_MARKERS = ['[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:', 'ADMONITION', '¶', '\uf0c1']


def _frontmatter(path):
    text = open(path, encoding='utf-8').read()
    m = _FRONTMATTER_RE.search(text)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    else:
        body = text
    return meta, body


def _int_field(meta, key):
    try:
        return int(meta.get(key, ''))
    except ValueError:
        return None


def _count_blocks(text):
    headings = 0
    list_items = 0
    code_fences = 0
    in_code = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('```'):
            in_code = not in_code
            if in_code:
                code_fences += 1
            continue
        if in_code:
            continue
        if re.match(r'^#{1,6}\s+', s):
            headings += 1
        elif re.match(r'^(?:[*+-]\s+|\d+\.\s+)', s):
            list_items += 1
    return headings, list_items, code_fences


def _verify_translation_body(body):
    if not body.strip():
        return False, '正文为空'
    if body.count('```') % 2 != 0:
        return False, '代码围栏不成对'
    for mk in _RESIDUAL_MARKERS:
        if mk in body:
            return False, '残留解析标记: %s' % mk
    for m in re.finditer(r'^\[([A-Z][A-Z0-9_-]*)\]\s', body, re.M):
        return False, '残留块级占位符: [%s]' % m.group(1)
    for num in sorted(set(re.findall(r'\[\^(\d+)\]', body))):
        refs = len(re.findall(r'\[\^%s\](?!:)' % num, body))
        defs = len(re.findall(r'^\[\^%s\]:' % num, body, re.M))
        if not (refs and defs):
            return False, '脚注 [^%s] 引用/定义不成对' % num
    return True, None


def recover(source_path, wps_dir, trans_dir, strategy):
    """返回 (reusable, missing, failed)。reusable/failed 元素含 name/order/reason。"""
    import tempfile
    import shutil
    tmp_dir = tempfile.mkdtemp(prefix='hpc_expected_wps_')
    try:
        expected_paths = swp.split(source_path, tmp_dir, trans_dir, strategy)
        expected = []
        for p in expected_paths:
            meta, body = _frontmatter(p)
            expected.append({
                'name': os.path.basename(p),
                'order': _int_field(meta, 'source_order'),
                'target_file': meta.get('target_file'),
                'headings': _int_field(meta, 'headings'),
                'list_items': _int_field(meta, 'list_items'),
                'code_fences': _int_field(meta, 'code_fences'),
            })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    reusable = []
    missing = []
    failed = []

    for exp in expected:
        name = exp['name']
        # 译文位置：frontmatter 指定的 target_file 优先，否则 trans_dir/name
        wp_path = os.path.join(wps_dir, name)
        target = None
        if os.path.isfile(wp_path):
            meta, _ = _frontmatter(wp_path)
            target = meta.get('target_file') or None
        if not target or not os.path.isfile(target):
            target = os.path.join(trans_dir, name)

        if not os.path.isfile(target):
            missing.append({'name': name, 'order': exp['order']})
            continue
        if os.path.getsize(target) == 0:
            failed.append({'name': name, 'order': exp['order'], 'reason': '译文文件为空'})
            continue

        _, body = _frontmatter(target)
        ok, reason = _verify_translation_body(body)
        if not ok:
            failed.append({'name': name, 'order': exp['order'], 'reason': reason})
            continue

        # 内容块计数对照：译文标题/围栏/列表项不得少于源工作包声明的数量
        th, tl, tf = _count_blocks(body)
        if exp['headings'] is not None and th < exp['headings']:
            failed.append({'name': name, 'order': exp['order'],
                           'reason': '标题数不足: 期望 %d / 实际 %d' % (exp['headings'], th)})
            continue
        if exp['code_fences'] is not None and tf != exp['code_fences']:
            failed.append({'name': name, 'order': exp['order'],
                           'reason': '代码围栏数不符: 期望 %d / 实际 %d' % (exp['code_fences'], tf)})
            continue
        if exp['list_items'] is not None and tl < exp['list_items']:
            failed.append({'name': name, 'order': exp['order'],
                           'reason': '列表项不足: 期望 %d / 实际 %d' % (exp['list_items'], tl)})
            continue

        reusable.append({'name': name, 'order': exp['order']})

    return reusable, missing, failed


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 5:
        sys.exit(__doc__)
    source_path = sys.argv[1]
    wps_dir = sys.argv[2]
    trans_dir = sys.argv[3] if len(sys.argv) > 3 else wps_dir
    strategy = sys.argv[4] if len(sys.argv) > 4 else 'h2'

    if not os.path.isfile(source_path):
        sys.exit('源文件不存在: %s' % source_path)
    if not os.path.isdir(wps_dir):
        sys.exit('工作包目录不存在: %s' % wps_dir)

    reusable, missing, failed = recover(source_path, wps_dir, trans_dir, strategy)

    print('\n=== 中断恢复报告 ===')
    print('可复用 (%d):' % len(reusable))
    for r in sorted(reusable, key=lambda x: x['order']):
        print('  [OK] %s (order=%d)' % (r['name'], r['order']))
    print('缺失需重做 (%d):' % len(missing))
    for m in sorted(missing, key=lambda x: x['order']):
        print('  [MISSING] %s (order=%d)' % (m['name'], m['order']))
    print('校验失败需重做 (%d):' % len(failed))
    for f in sorted(failed, key=lambda x: x['order']):
        print('  [FAIL] %s: %s' % (f['name'], f['reason']))

    total = len(reusable) + len(missing) + len(failed)
    print('总计: %d 个工作包' % total)

    if missing or failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
