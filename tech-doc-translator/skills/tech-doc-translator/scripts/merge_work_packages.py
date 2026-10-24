#!/usr/bin/env python3
"""按独立全量范围合并工作包译文（R3 / 已批准 D3）。

表格代码：--finalize-table-code 在已核验中间包上转为可读格位说明；不改原包。

用法：
    python3 merge_work_packages.py <out.md> <trans_wp_001.md> [<trans_wp_002.md> ...]
        --source <source.md> --strategy <h2|chars:N> --source-packages <wps_dir>
        --review-evidence <evidence.json>
        [--scope <order_csv>]
        [--strong-token <token>]... [--approved-extra-math <表达式>]...
        [--image-map <map.json>] [--delivery-root <dir>]
        [--source-adaptation <依据.json> [--source-adaptation <依据.json> ...]]
        [--numeric-review] [--numeric-policy <UTF-8 项目约定文件>]

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
      图片/强 token），暂存文件独立重读复验后原子替换；失败保持原成品，
      首次失败不留下声称有效的成品。
"""
import glob as _glob
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recover_work_packages as rwp
from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_image_options,
    extract_numeric_review_options,
    extract_strong_tokens,
    footnote_diffs,
    heading_entries,
    image_occurrence_count,
    image_occurrence_fails,
    image_references,
    load_image_digests,
    math_issue_fails,
    source_occurrence_digests,
    strong_token_report,
    scan_code_fences,
    scan_math,
)

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)


def _read_frontmatter(path):
    import _pdf_math
    text = _pdf_math.read_document(path)
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
                              approved_extra_math, label, source_dir=None,
                              source_adaptation=None, full=True,
                              adaptation_payload=None, pdf_view=None, source_ranges=None, header_cells=()):
    """候选/成品在最终语境下对照当前源的全量硬检查；返回 (失败, 告警)。

    图片完整通过必须建立每次出现的来源身份对应：优先 --image-map，其次
    由可靠的当前源资源（source_dir 下可解析的引用与 [IMG: 标记）推导；
    两者都不可用时不得宣布完整通过。强 token 的缺席/未配置告警随结果
    返回，不丢弃、不把空差异打印成所有配置项通过。
    source_adaptation 提供时公式按来源依据精确核对（full=完整源范围）。
    """
    fails = []
    warns = []
    for diff in compare_headings(heading_entries(source_text),
                                 heading_entries(candidate_text),
                                 '源文', label):
        fails.append('标题核对: %s' % diff)
    scan_context = None
    code_src,code_doc=source_text,candidate_text
    if pdf_view:
        import _pdf_math
        scan_context=_pdf_math.context(pdf_view['checklist'])
        code_src=_pdf_math.footnote_view(source_text,scan_context)[0]
        code_doc=_pdf_math.footnote_view(candidate_text,scan_context)[0]
    src_fences = scan_code_fences(code_src)
    doc_fences = scan_code_fences(code_doc)
    if not doc_fences.balanced:
        fails.append('代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % doc_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    '源文', label):
        fails.append('代码逐块核对: %s' % diff)
    if pdf_view:
        import _pdf_math
        try:
            with _pdf_math.load_fitz().open(pdf_view['pdf']) as doc:
                _pdf_math.verify(pdf_view['checklist'],doc,pdf_view['text'],
                                 pdf_view['mapping'],candidate_text,source_ranges,
                                 approved_extra_math)
        except (ValueError,KeyError,IndexError,TypeError) as exc:
            fails.append('PDF确认数学成品核验: '+str(exc))
    elif source_adaptation:
        import _latexml_source as latexml
        payload = adaptation_payload
        if payload is None:
            payload = latexml.load_adaptation(source_adaptation)
        # 宿主（脚注定义等）内字面公式源侧按 bound_math_spans 逐字进入比较，
        # 译侧同口径保留（两侧对称，与 verify_reference_translation 一致）：
        # 脚注公式损伤由本比较发现，不预先丢弃
        scan_context = latexml.scan_context_from_payload(payload)
        doc_scan = scan_math(candidate_text, source_context=scan_context)
        src_spans, bind_problems = latexml.precise_math_spans(
            source_text, source_adaptation, full=full, label='源文',
            payload=payload)
        fails.extend('公式来源绑定: %s' % p for p in bind_problems)
        if not bind_problems:
            # 绑定失败即拒绝：精确比较口径已不成立，不再制造误导噪音
            math_diffs, _ = compare_math_spans(
                src_spans, doc_scan.spans, '源文', label,
                approved_extra_exprs=approved_extra_math,
                doc_text=candidate_text, precise=True)
            fails.extend('公式逐项核对: %s' % d for d in math_diffs)
            fails.extend(math_issue_fails(doc_scan.issues, label))
    else:
        doc_scan = scan_math(candidate_text)
        src_scan = scan_math(source_text)
        math_diffs, _ = compare_math_spans(
            src_scan.spans, doc_scan.spans,
            '源文', label, approved_extra_exprs=approved_extra_math,
            doc_text=candidate_text, src_text=source_text)
        fails.extend('公式逐项核对: %s' % d for d in math_diffs)
        fails.extend(math_issue_fails(src_scan.issues, '源文'))
        fails.extend(math_issue_fails(doc_scan.issues, label))
    from _source_reconcile import compare_translation_tables, table_code_problems
    fails.extend(table_code_problems(candidate_text, source_context=scan_context))
    fails.extend(compare_translation_tables(source_text, candidate_text,
                                            source_context=scan_context, header_cells=header_cells))
    fn_diffs, _ = ([],[]) if pdf_view else footnote_diffs(source_text, candidate_text, '源文', label)
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
    token_diffs, token_warns = strong_token_report(
        source_text, candidate_text, strong_tokens, '源文', label)
    if token_diffs:
        fails.extend(token_diffs)
    warns.extend(token_warns)
    return fails, warns


def merge(out_path, inputs, source_path, strategy, wps_dir, evidence_path=None,
          scope=None, strong_tokens=(), approved_extra_math=(),
          delivery_root=None, image_digests=None, source_adaptation=None,
          numeric_review=False, numeric_policy=None, project_context=None,
          finalize_code=False):
    source_abs = os.path.abspath(source_path)
    if not os.path.isfile(source_abs):
        sys.exit('输入不足: 当前源不存在: %s' % source_path)
    if not evidence_path:
        sys.exit('输入不足: 缺少必需的 --review-evidence 复核证据'
                 '（无复核资格的包不得进入交付合并）')
    if image_digests is not None and scope:
        sys.exit('输入不足: --scope 局部范围与 --image-map 全量出现身份不兼容')

    context = rwp.load_project_context(project_context, source_abs)
    code_stage = rwp.table_code_stage(context, 'intermediate' if finalize_code else None)
    strong_tokens, approved_extra_math, source_adaptation, numeric_review, numeric_policy = rwp.effective_options(
        context, strong_tokens, approved_extra_math, source_adaptation, numeric_review, numeric_policy)
    import _pdf_math
    source_text = _pdf_math.read_document(source_abs)
    adaptation_abs = None
    adaptation_payload = None
    project = None
    if source_adaptation:
        try:
            adaptation_payload, adaptation_abs, project = \
                rwp._load_source_adaptation(source_adaptation, source_text)
        except ValueError as exc:
            sys.exit('来源预检拒绝: %s' % exc)
    numeric_policy_abs = None
    if numeric_policy:
        if not numeric_review:
            sys.exit('输入不足: 提供 --numeric-policy 但未启用 '
                     '--numeric-review（口径不生效，请显式启用或移除参数）')
        numeric_policy_abs = os.path.abspath(numeric_policy)

    # 1) 临时目录重建独立全量预期；范围由当前源+策略产生，不由实收包数反推
    tmp_dir = tempfile.mkdtemp(prefix='merge_expected_')
    try:
        expected = {}
        orders = {}
        for exp in rwp.expected_packages(source_abs, strategy,
                os.path.join(tmp_dir, 'trans'), adaptation_abs,project_context):
            key = (exp['section_id'], exp['instance'], exp['fragment'])
            expected[key] = exp
            orders[exp['order']] = key

        # 2) 源包映射必须与当前源+策略的预期一致，否则依据不足；
        #    每包的权威 target_file 一并取自源包映射，不采信待验包自报路径
        old_keys = set()
        authoritative_targets = {}
        declared_adaptations = set()
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
            declared = meta.get('source_adaptation')
            if declared:
                declared_adaptations.add(
                    os.path.realpath(declared.strip('"')))
            declared_multi = meta.get('source_adaptations')
            if declared_multi:
                # 多快照来源（F7/§7.5）：包以 JSON 列表登记全部依据引用
                try:
                    items = json.loads(declared_multi)
                except ValueError:
                    items = [declared_multi.strip('"')]
                for item in items:
                    if isinstance(item, str) and item:
                        declared_adaptations.add(os.path.realpath(item))
        if old_keys != set(expected):
            sys.exit('输入不足: 源包映射与当前源+策略的预期不一致'
                     '（预期 %d 包，源包目录 %d 包）；请先按当前源重新拆包'
                     % (len(expected), len(old_keys)))
        # 2b) 来源依据绑定一致性：声明了依据而缺参数/参数不符即拒绝合并
        #     （多快照按集合核对全部声明引用）
        if declared_adaptations and adaptation_abs is None:
            sys.exit('输入不足: 源包声明 source_adaptation %s，但缺少 '
                     '--source-adaptation 参数（不降级为普通来源合并）'
                     % sorted(declared_adaptations))
        if declared_adaptations:
            provided = ({adaptation_abs} if isinstance(adaptation_abs, str)
                        else set(adaptation_abs))
            provided = {os.path.realpath(p) for p in provided}
            if declared_adaptations != provided:
                sys.exit('输入不足: 源包声明的 source_adaptation %s 与本次 '
                         '参数 %s 不符（来源依据不一致，拒绝合并）'
                         % (sorted(declared_adaptations), sorted(provided)))
        if adaptation_abs is not None and not declared_adaptations:
            sys.exit('输入不足: 提供 --source-adaptation，但源包未登记来源'
                     '依据（请先按当前来源重新拆包）: %s' % wps_dir)
        # 公式对应不得跨工作包（02-5）：最终装配前按预期包范围核对；
        # 多快照用整文视图 payload（区间已按累计偏移平移到整文坐标）
        if project is not None:
            import _latexml_source as latexml
            payload = (latexml.load_adaptation(adaptation_abs)
                       if isinstance(adaptation_abs, str)
                       else adaptation_payload)
            cross = latexml.correspondence_package_problems(
                payload,
                [(entry['char_start'], entry['char_end'])
                 for entry in expected.values()])
            if cross:
                sys.exit('输入不足: %s' % '；'.join(cross))
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
    source_dir = os.path.dirname(source_abs)
    for key in ordered_keys_safe(scope_keys, orders):
        name = expected[key]['name']
        received_path = received[key]['path']
        _, trans_body = _read_frontmatter(received_path)
        if context and context.get('_pdf_view'):
            import _pdf_math
            _pdf_math.check_fragment(context['_pdf_view'],expected[key]['char_start'],
                                     expected[key]['char_end'],trans_body,
                                     approved_extra_math)
        facts = rwp.package_facts(
            expected[key], trans_body, received_path, source_abs,
            strong_tokens, approved_extra_math, project, numeric_review,
            numeric_policy_abs, context, code_stage)
        bad = rwp.package_binding_problems(entry_of(evidence, name), facts, trans_body)

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
    source_ranges=[(expected[key]['char_start'],expected[key]['char_end']) for key in ordered_keys] if scope else None
    header_cells = rwp.table_headers(context, source_ranges)
    if finalize_code:
        from _source_reconcile import finalize_table_code
        code_context = None
        if adaptation_payload:
            import _latexml_source as latexml
            code_context = latexml.scan_context_from_payload(adaptation_payload)
        candidate = finalize_table_code(candidate, code_context, header_cells)

    # 6) 候选在最终目录语境下对照当前源（全量=整篇源；局部=范围内源切片）
    if scope:
        source_slice = '\n'.join(expected[key]['body'] for key in ordered_keys)
    else:
        source_slice = _pdf_math.read_document(source_abs)
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    pdf_view=context.get('_pdf_view') if context else None
    fails, warns = _candidate_check_failures(
        candidate, source_slice, out_dir, delivery_root, image_digests,
        strong_tokens, approved_extra_math, '候选', source_dir=source_dir,
        source_adaptation=adaptation_abs, full=not scope,
        adaptation_payload=adaptation_payload,pdf_view=pdf_view,source_ranges=source_ranges,header_cells=header_cells)
    if fails:
        print('候选未通过最终目录语境检查，不写出成品：')
        for f in fails:
            print('  FAIL:', f)
        for w in warns:
            print('  WARN:', w)
        sys.exit(1)
    for w in warns:
        print('WARN:', w)

    # 7) 独立重读暂存文件并检查后原子发布；写入/检查/替换失败均不碰旧目标。
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                dir=out_dir, prefix='.merge-', suffix='.md', delete=False) as handle:
            staged = handle.name
            handle.write(candidate)
            handle.flush()
            os.fsync(handle.fileno())
        written = _pdf_math.read_document(staged, exact=bool(pdf_view))
        fails, warns = _candidate_check_failures(
            written, source_slice, out_dir, delivery_root, image_digests,
            strong_tokens, approved_extra_math, '暂存成品', source_dir=source_dir,
            source_adaptation=adaptation_abs, full=not scope,
            adaptation_payload=adaptation_payload, pdf_view=pdf_view,
            source_ranges=source_ranges,header_cells=header_cells)
        if fails:
            raise ValueError('暂存成品复验失败，旧成品保持：' + '；'.join(fails))
        for warning in warns:
            print('WARN:', warning)
        if os.path.exists(out_abs):
            os.chmod(staged, os.stat(out_abs).st_mode & 0o777)
        os.replace(staged, out_abs)
        staged = None
    finally:
        if staged is not None and os.path.exists(staged):
            os.unlink(staged)

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
    argv, project_context = rwp.extract_project_context(sys.argv[1:])
    finalize_code = '--finalize-table-code' in argv
    argv = [item for item in argv if item != '--finalize-table-code']
    argv, strong_tokens = extract_strong_tokens(argv)
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, image_map, delivery_root = extract_image_options(argv)
    argv, numeric_review, numeric_policy = extract_numeric_review_options(argv)

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
    source_adaptation = []
    rest = []
    index = 0
    while index < len(argv):
        if argv[index] == '--source-adaptation':
            if index + 1 >= len(argv):
                sys.exit('输入不足: --source-adaptation 需要依据文件路径')
            source_adaptation.append(argv[index + 1])
            index += 2
        else:
            rest.append(argv[index])
            index += 1
    argv = rest
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
              delivery_root, image_digests,
              source_adaptation or None,
              numeric_review, numeric_policy, project_context, finalize_code)
    except ValueError as exc:
        sys.exit('合并拒绝: %s' % exc)


if __name__ == '__main__':
    main()
