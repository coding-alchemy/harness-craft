#!/usr/bin/env python3
"""按独立全量范围合并工作包译文（R3 / 已批准 D3）。

用法：
    python3 merge_work_packages.py <out.md> <trans_wp_001.md> [<trans_wp_002.md> ...]
        --source <source.md> --strategy <h2|chars:N> --source-packages <wps_dir>
        --review-evidence <evidence.json>
        [--scope <order_csv>]
        [--strong-token <token>]... [--approved-extra-math <表达式>]...
        [--image-map <map.json>] [--delivery-root <dir>]

行为（设计第 6 节）：
    - 从当前源、明确策略与源包映射在临时目录重建独立全量预期，不能从
      实收包数反推范围；缺少 --source/--strategy/--source-packages 或
      源包映射与当前源+策略不符时报告输入不足，不提供无依据的合并成功。
    - 收到的译文按 (section_id, section_instance, fragment_index) 与
      source_file 对应到预期包，并核对 source_order 与 target_file：
      target_file 必须等于源包映射中的权威目标，交换现存目标、指向无关
      现存文件、缺首/中/尾包、缺末片、重复、额外、异源、错误顺序或
      不存在的目标都以对应原因失败，已有有效成品不变。
    - --scope 显式声明局部范围（预期 source_order 列表，如 "1,3"）；
      未声明时要求全量范围。逆序实参按权威序号排序后装配。
    - --review-evidence 必需：范围内每个包都必须持有与当前源资源、当前
      文件绑定的有效复用资格（由任务 06 的恢复流程口径核对，含源资源
      摘要）；缺失、过期、不匹配或未完成即失败，不能因省略参数绕过。
    - 源译图片出现次数对账常开；完整通过必须建立每次出现的来源身份：
      --image-map 提供时按出现顺序核对，未提供时由可靠的当前源资源推导，
      两者都不可用而候选含图时报告“来源身份未核验”并失败。
    - 装配只拼接包正文（不把续片元数据变成正文，不改代码示例），候选
      先在最终目录语境通过对照当前源的全量硬检查（标题/代码/公式/脚注/
      图片/强 token），写出后再从实际路径复验；复验失败恢复原成品，
      首次失败不留下声称有效的成品。
"""
import glob as _glob
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recover_work_packages as rwp
import split_work_packages as swp
from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_strong_tokens,
    footnote_diffs,
    heading_entries,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
    load_image_digests,
    source_occurrence_digests,
    strong_token_report,
    scan_code_fences,
    scan_math_spans,
)

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

    for key in ('source_order', 'section_id', 'fragment_index',
                'section_instance', 'source_file'):
        if not meta.get(key):
            raise ValueError('%s 缺少 %s' % (path, key))
    try:
        order = int(meta['source_order'])
        fragment_index = int(meta['fragment_index'])
        instance = int(meta['section_instance'])
    except ValueError:
        raise ValueError('%s 的 source_order/section_instance/fragment_index '
                         '必须为整数' % path)
    if order <= 0 or fragment_index < 0 or instance <= 0:
        raise ValueError('%s 的映射字段超出范围' % path)

    body = text[m.end():]
    if not body.strip():
        raise ValueError('%s 正文为空' % path)
    return {
        'source_order': order,
        'section_id': meta['section_id'],
        'section_instance': instance,
        'fragment_index': fragment_index,
        'source_file': meta['source_file'],
        'target_file': meta.get('target_file', ''),
    }, body


def _candidate_check_failures(candidate_text, source_text, out_dir,
                              delivery_root, image_digests, strong_tokens,
                              approved_extra_math, label, source_dir=None):
    """候选/成品在最终语境下对照当前源的全量硬检查；返回失败诊断列表。

    图片完整通过必须建立每次出现的来源身份对应：优先 --image-map，其次
    由可靠的当前源资源（source_dir 下可解析的引用与 [IMG: 标记）推导；
    两者都不可用时不得宣布完整通过。
    """
    fails = []
    for diff in compare_headings(heading_entries(source_text),
                                 heading_entries(candidate_text),
                                 '源文', label):
        fails.append('标题核对: %s' % diff)
    src_fences = scan_code_fences(source_text)
    doc_fences = scan_code_fences(candidate_text)
    if not doc_fences.balanced:
        fails.append('代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % doc_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    '源文', label):
        fails.append('代码逐块核对: %s' % diff)
    math_diffs, _ = compare_math_spans(
        scan_math_spans(source_text), scan_math_spans(candidate_text),
        '源文', label, approved_extra_exprs=approved_extra_math,
        doc_text=candidate_text)
    fails.extend('公式逐项核对: %s' % d for d in math_diffs)
    fn_diffs, _ = footnote_diffs(source_text, candidate_text, '源文', label)
    fails.extend(fn_diffs)
    src_count = image_occurrence_count(source_text)
    doc_count = len(image_references(candidate_text))
    if doc_count < src_count:
        fails.append('图片对账: 源出现 %d 次但候选仅 %d 次（漏图）'
                     % (src_count, doc_count))
    identity = image_digests
    if identity is None and source_dir:
        identity = source_occurrence_digests(source_text, source_dir)
    if identity is None and doc_count:
        fails.append('图片来源身份未核验: 无 --image-map 且源资源不可解析，'
                     '无法建立每次出现的身份对应，不判定完整通过')
    fails.extend(image_occurrence_fails(
        candidate_text, out_dir, delivery_root, expected_digests=identity,
        label=label))
    token_diffs, _ = strong_token_report(source_text, candidate_text,
                                         strong_tokens, '源文', label)
    if token_diffs:
        fails.extend(token_diffs)
    return fails


def merge(out_path, inputs, source_path, strategy, wps_dir, evidence_path=None,
          scope=None, strong_tokens=(), approved_extra_math=(),
          delivery_root=None, image_digests=None):
    source_abs = os.path.abspath(source_path)
    if not os.path.isfile(source_abs):
        sys.exit('输入不足: 当前源不存在: %s' % source_path)
    if not evidence_path:
        sys.exit('输入不足: 缺少必需的 --review-evidence 复核证据'
                 '（无复核资格的包不得进入交付合并）')
    if image_digests is not None and scope:
        sys.exit('输入不足: --scope 局部范围与 --image-map 全量出现身份不兼容')

    # 1) 临时目录重建独立全量预期；范围由当前源+策略产生，不由实收包数反推
    tmp_dir = tempfile.mkdtemp(prefix='merge_expected_')
    try:
        expected_paths = swp.split(source_abs, os.path.join(tmp_dir, 'wps'),
                                   os.path.join(tmp_dir, 'trans'), strategy)
        expected = {}
        orders = {}
        for p in expected_paths:
            meta, body = rwp._frontmatter(p)
            key = (meta.get('section_id', '').strip('"'),
                   meta.get('section_instance', '1'),
                   meta.get('fragment_index', '0'))
            expected[key] = {
                'name': os.path.basename(p),
                'order': int(meta.get('source_order', 0)),
                'digest': meta.get('fragment_digest', ''),
                'body': body,
            }
            orders[int(meta.get('source_order', 0))] = key

        # 2) 源包映射必须与当前源+策略的预期一致，否则依据不足；
        #    每包的权威 target_file 一并取自源包映射，不采信待验包自报路径
        old_keys = set()
        authoritative_targets = {}
        wps_abs = os.path.abspath(wps_dir)
        if not os.path.isdir(wps_abs):
            sys.exit('输入不足: 源包目录不存在: %s' % wps_dir)
        for name in os.listdir(wps_abs):
            if not name.endswith('.md'):
                continue
            meta, _ = rwp._frontmatter(os.path.join(wps_abs, name))
            key = (meta.get('section_id', '').strip('"'),
                   meta.get('section_instance', '1'),
                   meta.get('fragment_index', '0'))
            old_keys.add(key)
            authoritative_targets[key] = meta.get('target_file', '')
        if old_keys != set(expected):
            sys.exit('输入不足: 源包映射与当前源+策略的预期不一致'
                     '（预期 %d 包，源包目录 %d 包）；请先按当前源重新拆包'
                     % (len(expected), len(old_keys)))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    full_orders = sorted(orders)
    if scope:
        wanted = []
        for part in scope.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                sys.exit('输入不足: --scope 需为预期 source_order 列表（如 "1,3"）')
            if value not in orders:
                sys.exit('输入不足: --scope 中的 source_order %d 不在当前源预期范围 %s 中'
                         % (value, full_orders))
            wanted.append(value)
        in_scope = sorted(set(wanted))
    else:
        in_scope = full_orders
    scope_keys = {orders[value]: value for value in in_scope}

    # 3) 收到的译文按键对应，并核对独立预期映射（顺序、目标）；重复、
    #    额外、异源、错误顺序、错误目标一律失败
    received = {}
    received_paths = []
    seen_targets = {}
    for path in inputs:
        meta, body = _read_frontmatter(path)
        key = (meta['section_id'], str(meta['section_instance']),
               str(meta['fragment_index']))
        if key in received:
            raise ValueError('重复包: %s 与 %s 对应同一小节实例与片段'
                             % (received[key]['path'], path))
        if key not in expected:
            raise ValueError('额外包（当前源预期中不存在）: %s' % path)
        if meta['source_file'] != source_abs:
            raise ValueError('异源包: %s 的 source_file 为 %s，与当前源 %s 不符'
                             % (path, meta['source_file'], source_abs))
        if meta['source_order'] != expected[key]['order']:
            raise ValueError(
                '错误顺序映射: %s 自报 source_order=%d，预期映射为 %d'
                % (path, meta['source_order'], expected[key]['order']))
        target = meta['target_file']
        authoritative = authoritative_targets.get(key, '')
        if not authoritative:
            raise ValueError('错误目标映射: 源包权威映射缺少 %s 的 target_file'
                             % path)
        if target != authoritative:
            raise ValueError(
                '错误目标映射: %s 的 target_file %s 与源包权威映射 %s 不符'
                % (path, target or '（空）', authoritative))
        if not os.path.isfile(target):
            raise ValueError('错误目标映射: %s 的 target_file 不存在: %s'
                             % (path, target))
        if target in seen_targets:
            raise ValueError('错误目标映射: %s 与 %s 指向同一目标文件，目标不唯一'
                             % (path, seen_targets[target]))
        seen_targets[target] = path
        received[key] = {'path': path, 'meta': meta, 'body': body}
        received_paths.append(path)

    missing_keys = [key for key in scope_keys if key not in received]
    if missing_keys:
        detail = '、'.join('order=%d %s（片段 %s）' % (
            scope_keys[key], key[0], key[2]) for key in sorted(
            missing_keys, key=lambda k: scope_keys[k]))
        raise ValueError('缺少工作包（按当前源全量范围对照）: %s' % detail)
    extra_keys = [key for key in received if key not in scope_keys]
    if extra_keys:
        raise ValueError('额外包超出声明范围: %s' %
                         '、'.join(str(k) for k in extra_keys))

    # 缺末片检查：范围内每个小节的片段必须连续且从 0 开始
    fragments_by_section = {}
    for key in scope_keys:
        fragments_by_section.setdefault((key[0], key[1]), []).append(
            int(key[2]))
    for section, indexes in sorted(fragments_by_section.items()):
        if sorted(indexes) != list(range(len(indexes))):
            raise ValueError('小节 %s（实例 %s）的片段不连续（疑似缺末片）: %s'
                             % (section[0], section[1], sorted(indexes)))

    # 4) 复用资格（--review-evidence，必需）：范围内每包必须与当前源资源、
    #    当前文件绑定有效；缺失、过期、不匹配或未完成即拒绝
    evidence = rwp._load_evidence(evidence_path)
    script_id = rwp._script_identity()
    source_dir = os.path.dirname(source_abs)
    for key in ordered_keys_safe(scope_keys, orders):
        name = expected[key]['name']
        received_path = received[key]['path']
        _, trans_body = _read_frontmatter(received_path)
        resources = rwp._resource_digests(
            trans_body, os.path.dirname(os.path.abspath(received_path)))
        source_resources = rwp._source_resource_digests(
            expected[key]['body'], source_dir)
        bad = rwp.evidence_binding_problems(
            entry=entry_of(evidence, name), source_digest=expected[key]['digest'],
            trans_body=trans_body, resources=resources,
            script_id=script_id, strong_tokens=list(strong_tokens),
            source_resources=source_resources)
        if bad:
            raise ValueError('包 %s 无有效复用资格: %s'
                             % (name, '；'.join(bad)))

    # 5) 按权威序号装配候选（逆序实参不影响输出顺序）
    ordered_keys = sorted(scope_keys, key=lambda k: scope_keys[k])
    parts = []
    for key in ordered_keys:
        body = received[key]['body'].strip('\n')
        if body:
            parts.append(body)
    candidate = '\n\n'.join(parts) + '\n'

    # 6) 候选在最终目录语境下对照当前源（全量=整篇源；局部=范围内源切片）
    if scope:
        source_slice = '\n'.join(expected[key]['body'] for key in ordered_keys)
    else:
        source_slice = open(source_abs, encoding='utf-8').read()
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    fails = _candidate_check_failures(
        candidate, source_slice, out_dir, delivery_root, image_digests,
        strong_tokens, approved_extra_math, '候选', source_dir=source_dir)
    if fails:
        print('候选未通过最终目录语境检查，不写出成品：')
        for f in fails:
            print('  FAIL:', f)
        sys.exit(1)

    # 7) 写出后再从实际路径复验；失败恢复原成品，首次失败不留新成品
    previous = None
    if os.path.exists(out_abs):
        previous = open(out_abs, 'rb').read()
    with open(out_abs, 'w', encoding='utf-8') as f:
        f.write(candidate)
    written = open(out_abs, encoding='utf-8').read()
    fails = _candidate_check_failures(
        written, source_slice, out_dir, delivery_root, image_digests,
        strong_tokens, approved_extra_math, '实际成品', source_dir=source_dir)
    if fails:
        if previous is not None:
            with open(out_abs, 'wb') as f:
                f.write(previous)
            print('实际路径复验失败，已恢复原成品：')
        else:
            os.remove(out_abs)
            print('实际路径复验失败，不留下新成品：')
        for f in fails:
            print('  FAIL:', f)
        sys.exit(1)

    print('已合并 %d 个工作包 -> %s%s' % (
        len(ordered_keys), out_abs,
        '（局部范围 scope=%s）' % scope if scope else '（全量范围）'))
    for key in ordered_keys:
        print('  order=%d %s' % (scope_keys[key], received[key]['path']))
    return received_paths


def ordered_keys_safe(scope_keys, orders):
    return sorted(scope_keys, key=lambda k: scope_keys[k])


def entry_of(evidence, name):
    return evidence.get(name)


def main():
    argv, strong_tokens = extract_strong_tokens(sys.argv[1:])
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, image_map, delivery_root = extract_image_options(argv)

    def require_flag(name):
        if name not in argv:
            sys.exit('输入不足: 缺少必需的 %s 参数（旧的无依据合并已停用）' % name)
        idx = argv.index(name)
        if idx + 1 >= len(argv):
            sys.exit('输入不足: %s 需要参数值' % name)
        value = argv[idx + 1]
        del argv[idx:idx + 2]
        return value

    source_path = require_flag('--source')
    strategy = require_flag('--strategy')
    wps_dir = require_flag('--source-packages')
    evidence_path = require_flag('--review-evidence')
    scope = None
    if '--scope' in argv:
        idx = argv.index('--scope')
        if idx + 1 >= len(argv):
            sys.exit('输入不足: --scope 需要范围列表')
        scope = argv[idx + 1]
        del argv[idx:idx + 2]

    if len(argv) < 2:
        sys.exit(__doc__)
    out_path = argv[0]
    rest = argv[1:]
    if len(rest) == 1 and os.path.isdir(rest[0]):
        inputs = sorted(_glob.glob(os.path.join(rest[0], 'wp_*.md')))
        if not inputs:
            sys.exit('输入不足: 目录 %s 中没有 wp_*.md 译文' % rest[0])
    else:
        inputs = rest
    missing = [p for p in inputs if not os.path.isfile(p)]
    if missing:
        sys.exit('工作包译文不存在: %s' % ', '.join(missing))

    image_digests = load_image_digests(image_map) if image_map else None

    try:
        merge(out_path, inputs, source_path, strategy, wps_dir,
              evidence_path, scope, strong_tokens, approved_extra_math,
              delivery_root, image_digests)
    except ValueError as exc:
        sys.exit('合并拒绝: %s' % exc)


if __name__ == '__main__':
    main()
