#!/usr/bin/env python3
"""依据当前源与复核证据恢复工作包状态（文件事实，无中央状态库）。

用法：
    python3 recover_work_packages.py <source.md> <wps_dir> [trans_dir] [strategy]
        [--review-evidence <evidence.json>] [--strong-token <token>]...
        [--approved-extra-math <表达式>]...

判定顺序（需求 R2 / 设计第 5 节）：
1. 只读旧源包，从当前源与明确策略在临时目录重建预期；旧包在任何情况下
   不被覆盖或改写。
2. 按 (section_id, section_instance, fragment_index) 与源片段摘要把旧包
   对应到预期包；源摘要不一致即失效，无法唯一对应时不猜测复用。
3. 对存在且源一致的译文运行片段范围的硬检查（代码逐块、公式逐项、
   标题层级与官方原题、脚注、图片、强 token；仅剩标题而源含正文等
   确定损伤直接失败）。检查失败即不可复用。
4. 硬检查通过后：存在与当前文件绑定的有效复核证据才输出“可复用”；
   无证据或证据失效输出“待复核”，不自动重译，也不因缺记录拒绝补验。

复核证据是工作区外、逐包、可重建的 JSON 文件，由主 Agent 在独立回源
复核后人工产生；最少绑定源片段摘要、目标正文摘要、译文资源摘要、当前
源资源摘要、实际校验脚本身份、强 token 与复核结论。脚本只重新计算并核
对绑定，绝不因计数通过自动生成语义通过。源图片等资源被替换（字节变化、
不改动 Markdown）后旧记录同样失效，恢复时按当前源资源重新核验。
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_work_packages as swp
from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_strong_tokens,
    file_sha256,
    footnote_diffs,
    heading_entries,
    image_marker_refs,
    image_occurrence_count,
    image_references,
    local_resource_digest,
    scan_code_fences,
    scan_math_spans,
    strong_token_report,
)

_SKILL_DIR = Path(__file__).resolve().parent.parent
_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)
_RESIDUAL_MARKERS = ['[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:',
                     'ADMONITION', '¶', '\uf0c1']


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


def _sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _resource_digests(body, base_dir):
    """译文中实际图片引用的资源身份摘要（按出现顺序；不可解析记 None）。

    复用 _verification.local_resource_digest：引用清理、路径解析、依赖
    身份与不可读处理与源侧及各校验入口同一实现，不另行维护。
    """
    return [local_resource_digest(src, base_dir)
            for _, src in image_references(body)]


def _source_resource_digests(body, base_dir):
    """源片段中图片的当前资源身份摘要（按出现顺序）。

    覆盖 Markdown 图片引用（内联与引用式）与源家族的 `` [IMG:…] `` 标记
    （标记内为相对路径，代码围栏内的示例标记不计数）；摘要含 SVG/CSS
    依赖内容。用于把复核证据绑定到源资源内容：源图片或其依赖字节变化
    （不改 Markdown）后旧证据即失效。
    """
    digests = [local_resource_digest(src, base_dir)
               for _, src in image_references(body)]
    digests.extend(local_resource_digest(marker, base_dir)
                   for _, marker in image_marker_refs(body))
    return digests


def _fragment_hard_checks(src_body, trans_body, trans_path, strong_tokens,
                          approved_extra_math):
    """片段范围的硬检查；返回 (fails, warns)。"""
    fails = []
    warns = []

    src_fences = scan_code_fences(src_body)
    doc_fences = scan_code_fences(trans_body)
    if not doc_fences.balanced:
        fails.append('代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % doc_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    '源片段', '译文'):
        fails.append('代码逐块核对: %s' % diff)

    math_diffs, math_warns = compare_math_spans(
        scan_math_spans(src_body), scan_math_spans(trans_body),
        '源片段', '译文', approved_extra_exprs=approved_extra_math)
    fails.extend('公式逐项核对: %s' % d for d in math_diffs)
    warns.extend(math_warns)

    for diff in compare_headings(heading_entries(src_body),
                                 heading_entries(trans_body),
                                 '源片段', '译文'):
        fails.append('标题核对: %s' % diff)

    fn_diffs, fn_warns = footnote_diffs(src_body, trans_body, '源片段', '译文')
    fails.extend(fn_diffs)
    warns.extend(fn_warns)

    src_images = image_occurrence_count(src_body)
    trans_images = len(image_references(trans_body))
    if trans_images < src_images:
        fails.append('图片数量不足: 源 %d vs 译 %d' % (src_images, trans_images))

    token_diffs, token_warns = strong_token_report(
        src_body, trans_body, strong_tokens, '源片段', '译文')
    if token_diffs:
        fails.extend(token_diffs)
    warns.extend(token_warns)

    for marker in _RESIDUAL_MARKERS:
        if marker in trans_body:
            fails.append('残留解析标记: %s' % marker)

    # 仅剩标题而源含正文等确定损伤直接失败；列表/表格全部丢失属可证明截断
    src_body_lines = [l for l in src_body.splitlines()
                      if l.strip() and not l.strip().startswith('#')]
    trans_body_lines = [l for l in trans_body.splitlines()
                        if l.strip() and not l.strip().startswith('#')]
    if src_body_lines and not trans_body_lines:
        fails.append('确定损伤: 译文仅剩标题，源片段正文全部丢失')
    src_counts = swp._count_blocks(src_body)
    doc_counts = swp._count_blocks(trans_body)
    if src_counts['list_items'] and not doc_counts['list_items']:
        fails.append('可证明截断: 列表项全部丢失（源 %d 项）'
                     % src_counts['list_items'])
    if src_counts['tables'] and not doc_counts['tables']:
        fails.append('可证明截断: 表格全部丢失（源 %d 张）'
                     % src_counts['tables'])
    return fails, warns


def _load_evidence(path):
    if not path:
        return {}
    if not os.path.isfile(path):
        sys.exit('复核证据文件不存在: %s' % path)
    with open(path, encoding='utf-8') as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        sys.exit('复核证据格式无效: %s（需逐包 JSON 对象）' % path)
    return payload


def _script_identity():
    base = os.path.dirname(os.path.abspath(__file__))
    return {
        'recover_work_packages.py': file_sha256(os.path.abspath(__file__)),
        '_verification.py': file_sha256(os.path.join(base, '_verification.py')),
        'split_work_packages.py': file_sha256(os.path.join(base, 'split_work_packages.py')),
    }


def evidence_binding_problems(entry, source_digest, trans_body, resources,
                              script_id, strong_tokens, source_resources):
    """核对一条复核证据是否仍与当前源资源/文件/资源/口径/脚本身份绑定。

    返回失效原因列表；空列表表示证据有效。证据缺少源资源摘要字段同样
    视为失效（待复核），不因字段缺失放行。任一资源摘要无法核验（缺失、
    外链或不可读）即待复核：两侧同为空或同为 None 不构成匹配依据。
    """
    bad = []
    if not isinstance(entry, dict):
        return ['证据条目缺失或格式无效']
    if entry.get('source_digest') != source_digest:
        bad.append('源片段摘要与当前源不符')
    if entry.get('target_digest') != _sha256(trans_body):
        bad.append('目标正文摘要与当前译文不符')
    if entry.get('resource_digests') != resources:
        bad.append('资源摘要与当前文件不符')
    if entry.get('source_resource_digests') != source_resources:
        bad.append('源资源摘要与当前源资源不符')
    if any(d is None for d in resources) or \
            any(d is None for d in source_resources):
        bad.append('存在无法核验的资源摘要（缺失、外链或不可读），'
                   '不能授予复用资格')
    if entry.get('checker') != script_id:
        bad.append('校验脚本身份变化，需重新复核')
    if entry.get('strong_tokens') != list(strong_tokens):
        bad.append('强 token 口径变化，需重新复核')
    review = entry.get('review') or {}
    if review.get('semantic') != 'done' or review.get('unresolved'):
        bad.append('复核结论未完成或存在未解决项')
    return bad


def recover(source_path, wps_dir, trans_dir, strategy, evidence_path=None,
            strong_tokens=(), approved_extra_math=()):
    """返回 (reusable, missing, invalidated, pending, reports)。

    reusable/missing/invalidated/pending 元素含 name/order/reason。
    """
    evidence = _load_evidence(evidence_path)
    script_id = _script_identity()

    # 1) 只读重建预期：临时目录拆分，绝不触碰 wps_dir 与既有译文
    tmp_dir = tempfile.mkdtemp(prefix='recover_expected_')
    try:
        expected_paths = swp.split(source_path, tmp_dir, trans_dir, strategy)
        expected = []
        for p in expected_paths:
            meta, body = _frontmatter(p)
            expected.append({
                'name': os.path.basename(p),
                'order': int(meta.get('source_order', 0)),
                'section_id': meta.get('section_id', '').strip('"'),
                'instance': meta.get('section_instance', '1'),
                'fragment': meta.get('fragment_index', '0'),
                'target_file': meta.get('target_file'),
                'digest': meta.get('fragment_digest', ''),
                'body': body,
                'headings': meta.get('headings'),
                'list_items': meta.get('list_items'),
                'code_fences': meta.get('code_fences'),
            })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 2) 读取旧源包（只读），按键唯一对应
    old_packages = {}
    ambiguous = set()
    if os.path.isdir(wps_dir):
        for name in sorted(os.listdir(wps_dir)):
            if not name.endswith('.md'):
                continue
            meta, _ = _frontmatter(os.path.join(wps_dir, name))
            key = (meta.get('section_id', '').strip('"'),
                   meta.get('section_instance', ''),
                   meta.get('fragment_index', ''))
            if key in old_packages:
                ambiguous.add(key)
            old_packages[key] = {
                'name': name,
                'order': meta.get('source_order'),
                'target_file': meta.get('target_file'),
                'digest': meta.get('fragment_digest', ''),
            }

    reusable, missing, invalidated, pending = [], [], [], []
    reports = []

    for exp in expected:
        key = (exp['section_id'], exp['instance'], exp['fragment'])
        name = exp['name']
        reason_base = '%s (order=%s)' % (name, exp['order'])

        if key in ambiguous:
            pending.append({'name': name, 'order': exp['order'],
                            'reason': '旧源包按键无法唯一对应，不猜测复用'})
            continue
        old = old_packages.get(key)
        if old is None:
            missing.append({'name': name, 'order': exp['order'],
                            'reason': '无对应旧源包（首次拆分或旧包缺失）'})
            continue
        if old['digest'] != exp['digest']:
            invalidated.append({'name': name, 'order': exp['order'],
                                'reason': '源片段已变化（摘要不一致），译文需重做'})
            continue

        # 3) 译文目标：以旧源包 frontmatter 指向的唯一目标为准
        target = old['target_file']
        targets = [old['target_file'] for k, old in old_packages.items()
                   if k == key]
        if len(set(targets)) != 1 or not target:
            pending.append({'name': name, 'order': exp['order'],
                            'reason': '译文目标不唯一或缺失，不猜测复用'})
            continue
        if not os.path.isfile(target):
            missing.append({'name': name, 'order': exp['order'],
                            'reason': '译文目标缺失: %s' % target})
            continue
        _, trans_body = _frontmatter(target)
        if not trans_body.strip():
            invalidated.append({'name': name, 'order': exp['order'],
                                'reason': '译文文件为空'})
            continue

        # 片段范围硬检查
        fails, warns = _fragment_hard_checks(
            exp['body'], trans_body, target, strong_tokens,
            approved_extra_math)
        if fails:
            invalidated.append({'name': name, 'order': exp['order'],
                                'reason': '硬检查失败: ' + '；'.join(fails[:3])})
            continue
        for warn in warns:
            reports.append('%s: %s' % (reason_base, warn))

        # 4) 复核证据核对（证据必须与当前源资源/源片段/译文/资源/口径/脚本
        #    绑定；源资源在恢复时重新核验）
        entry = evidence.get(name)
        if not isinstance(entry, dict):
            pending.append({'name': name, 'order': exp['order'],
                            'reason': '硬检查通过但无复核证据，待回源复核'})
            continue
        resources = _resource_digests(
            trans_body, os.path.dirname(os.path.abspath(target)))
        source_resources = _source_resource_digests(
            exp['body'], os.path.dirname(os.path.abspath(source_path)))
        bad = evidence_binding_problems(entry, exp['digest'], trans_body,
                                        resources, script_id, strong_tokens,
                                        source_resources)
        if bad:
            pending.append({'name': name, 'order': exp['order'],
                            'reason': '证据失效待复核: ' + '；'.join(bad)})
            continue
        reusable.append({'name': name, 'order': exp['order'],
                         'target': target})

    return reusable, missing, invalidated, pending, reports


def main():
    argv, strong_tokens = extract_strong_tokens(sys.argv[1:])
    argv, approved_extra_math = extract_approved_extra_math(argv)
    evidence_path = None
    if '--review-evidence' in argv:
        idx = argv.index('--review-evidence')
        if idx + 1 >= len(argv):
            sys.exit('--review-evidence 需要证据文件路径')
        evidence_path = argv[idx + 1]
        argv = argv[:idx] + argv[idx + 2:]
    if len(argv) < 2 or len(argv) > 4:
        sys.exit(__doc__)
    source_path = argv[0]
    wps_dir = argv[1]
    trans_dir = argv[2] if len(argv) > 2 else wps_dir
    strategy = argv[3] if len(argv) > 3 else 'h2'

    if not os.path.isfile(source_path):
        sys.exit('源文件不存在: %s' % source_path)
    if not os.path.isdir(wps_dir):
        sys.exit('工作包目录不存在: %s' % wps_dir)

    reusable, missing, invalidated, pending, reports = recover(
        source_path, wps_dir, trans_dir, strategy, evidence_path,
        strong_tokens, approved_extra_math)

    print('\n=== 中断恢复报告 ===')
    print('可复用 (%d):' % len(reusable))
    for r in sorted(reusable, key=lambda x: x['order']):
        print('  [OK] %s (order=%s) -> %s' % (r['name'], r['order'], r.get('target')))
    print('缺失需处理 (%d):' % len(missing))
    for m in sorted(missing, key=lambda x: x['order']):
        print('  [MISSING] %s (order=%s): %s' % (m['name'], m['order'], m['reason']))
    print('已失效需重做 (%d):' % len(invalidated))
    for f in sorted(invalidated, key=lambda x: x['order']):
        print('  [FAIL] %s (order=%s): %s' % (f['name'], f['order'], f['reason']))
    print('待复核 (%d):' % len(pending))
    for p in sorted(pending, key=lambda x: x['order']):
        print('  [PENDING] %s (order=%s): %s' % (p['name'], p['order'], p['reason']))
    for line in reports:
        print('  [WARN] %s' % line)
    total = len(reusable) + len(missing) + len(invalidated) + len(pending)
    print('总计: %d 个工作包' % total)
    print('说明: 待复核包不计作完成，不进入可直接交付的合并；'
          '补齐独立复核证据后重新运行本脚本可升级为可复用。')

    if missing or invalidated or pending:
        sys.exit(1)


if __name__ == '__main__':
    main()
