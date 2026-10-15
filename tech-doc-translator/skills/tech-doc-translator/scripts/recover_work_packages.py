#!/usr/bin/env python3
"""依据当前源与复核证据恢复工作包状态（文件事实，无中央状态库）。

用法：
    python3 recover_work_packages.py <source.md> <wps_dir> [trans_dir] [strategy]
        [--review-evidence <evidence.json>] [--strong-token <token>]...
        [--approved-extra-math <表达式>]...
        [--source-adaptation <依据.json> [--source-adaptation <依据.json> ...]]
        [--numeric-review] [--numeric-policy <UTF-8 项目约定文件>]

--numeric-review 显式启用包级数字与单位复核核对（R5/§4.7）：证据须含
numeric 块（口径/实现身份/本次差异 ID）且 disposed 逐项覆盖本次差异；
未处置项进入 review.unresolved，不授予复用资格。脚本只核对覆盖与当前
绑定，不解析说明、不写 closed。

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
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_work_packages as swp
from _verification import (
    compare_code_fences,
    compare_headings,
    compare_math_spans,
    extract_approved_extra_math,
    extract_numeric_review_options,
    extract_strong_tokens,
    extract_source_adaptation,
    file_sha256,
    footnote_diffs,
    heading_entries,
    image_marker_refs,
    image_occurrence_count,
    image_references,
    local_resource_digest,
    math_issue_fails,
    scan_code_fences,
    scan_math,
    strong_token_report,
)

import _numeric_review as numeric_review_mod

_SKILL_DIR = Path(__file__).resolve().parent.parent
_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)
_RESIDUAL_MARKERS = ['[DEF-LIST]', '[FOOTNOTE-LIST]', '[TABLE]', '[IMG:',
                     'ADMONITION', '¶', '\uf0c1']


def _frontmatter(path):
    import _pdf_math
    text = _pdf_math.read_document(path)
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
                          approved_extra_math, source_adaptation=None,
                          adaptation_payload=None, pdf_view=None, source_range=None):
    """片段范围的硬检查；返回 (fails, warns)。

    source_adaptation 提供时公式按来源依据精确核对（逐字表达式与已确认
    类型），绑定失败即拒绝。多快照（F7/§7.5）时 adaptation_payload 传入
    整文视图 payload（切片校验与准入由 _load_source_adaptation 完成）。
    """
    fails = []
    warns = []
    if pdf_view:
        import _pdf_math
        try:
            _pdf_math.check_fragment(pdf_view,*source_range,trans_body,approved_extra_math)
        except (ValueError,KeyError,IndexError,TypeError) as exc:
            fails.append('PDF确认数学片段核验: '+str(exc))

    code_src,code_doc=src_body,trans_body
    if pdf_view:
        scan_context=_pdf_math.context(pdf_view['checklist'])
        code_src=_pdf_math.footnote_view(src_body,scan_context)[0]
        code_doc=_pdf_math.footnote_view(trans_body,scan_context)[0]
    src_fences = scan_code_fences(code_src)
    doc_fences = scan_code_fences(code_doc)
    if not doc_fences.balanced:
        fails.append('代码围栏不成对: 第 %d 行开启的代码块未闭合'
                     % doc_fences.unclosed_line)
    for diff in compare_code_fences(src_fences.blocks, doc_fences.blocks,
                                    '源片段', '译文'):
        fails.append('代码逐块核对: %s' % diff)

    if pdf_view:
        math_warns=[]  # 同一精确核验已执行，不再套用普通数学归一口径。
    elif source_adaptation:
        import _latexml_source as latexml
        payload = adaptation_payload
        if payload is None:
            payload = latexml.load_adaptation(source_adaptation)
        # 宿主（脚注定义等）内字面公式源侧按 bound_math_spans 逐字进入比较，
        # 译侧同口径保留（两侧对称，与 verify_reference_translation 一致）：
        # 脚注公式损伤由本比较发现，不预先丢弃
        doc_scan = scan_math(
            trans_body,
            source_context=latexml.scan_context_from_payload(payload))
        src_spans, bind_problems = latexml.precise_math_spans(
            src_body, source_adaptation, full=False, label='源片段',
            payload=payload)
        fails.extend('公式来源绑定: %s' % p for p in bind_problems)
        math_warns = []
        if not bind_problems:
            # 绑定失败即拒绝：精确比较口径已不成立，不再制造误导噪音
            math_diffs, math_warns = compare_math_spans(
                src_spans, doc_scan.spans, '源片段', '译文',
                approved_extra_exprs=approved_extra_math, doc_text=trans_body,
                precise=True)
            fails.extend('公式逐项核对: %s' % d for d in math_diffs)
            fails.extend(math_issue_fails(doc_scan.issues, '译文'))
    else:
        doc_scan = scan_math(trans_body)
        src_scan = scan_math(src_body)
        math_diffs, math_warns = compare_math_spans(
            src_scan.spans, doc_scan.spans,
            '源片段', '译文', approved_extra_exprs=approved_extra_math,
            doc_text=trans_body)
        fails.extend('公式逐项核对: %s' % d for d in math_diffs)
        fails.extend(math_issue_fails(src_scan.issues, '源片段'))
        fails.extend(math_issue_fails(doc_scan.issues, '译文'))
    warns.extend(math_warns)

    for diff in compare_headings(heading_entries(src_body),
                                 heading_entries(trans_body),
                                 '源片段', '译文'):
        fails.append('标题核对: %s' % diff)

    fn_diffs, fn_warns = ([],[]) if pdf_view else footnote_diffs(src_body, trans_body, '源片段', '译文')
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
    if pdf_view:
        # 原布局断行中的年份等可匹配旧行正则；资格采用现行实际块。
        for text, counts in ((src_body, src_counts), (trans_body, doc_counts)):
            blocks, _ = _pdf_math.markdown_blocks(
                text, _pdf_math.context(pdf_view['checklist']))
            counts['list_items'] = sum(bool(b.get('list_path')) for b in blocks)
            counts['tables'] = sum(b['role'] == 'table_region' for b in blocks)
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
        # LaTeXML 来源适配/合同实现（D4）：适配器身份变化使旧复核失效
        '_latexml_source.py': file_sha256(os.path.join(base, '_latexml_source.py')),
        'build_review_evidence.py': file_sha256(os.path.join(base, 'build_review_evidence.py')),
        '_pdf_math.py': file_sha256(os.path.join(base, '_pdf_math.py')),
    }


def _load_source_adaptation(path, source_text):
    """恢复/合并共用的当前源预检：独立重读来源依据并核对源全文绑定。

    path 为单路径（旧行为）或有序路径列表（多快照 F7/§7.5：按序切片，
    行数/sha 证明无缝未漂移——覆盖不完整/漂移如实拒绝，不以数学定界等
    错误原因失败；逐片完整对账后合并整文视图 payload）。单元素列表与
    单路径同义（单个 --source-adaptation 用法行为不变）。返回
    (payload, adaptation_abs, check_policy 投影函数)；单依据时
    adaptation_abs 为绝对路径字符串，多依据为绝对路径列表；绑定失败或
    未解决项非空即以 ValueError 拒绝（不降级为普通来源）。
    """
    import _latexml_source as latexml
    paths = [path] if isinstance(path, str) else list(path)
    abs_paths = [os.path.abspath(p) for p in paths]
    single = len(abs_paths) == 1
    adaptation_abs = abs_paths[0] if single else abs_paths
    if single:
        payload = latexml.load_adaptation(adaptation_abs)
        md_problems = latexml.recorded_markdown_problems(
            source_text, payload, label='来源依据 %s' % adaptation_abs)
        if md_problems:
            raise ValueError('；'.join(md_problems))
        if payload.get('unresolved'):
            raise ValueError('来源依据含未解决项 %s（无分派/复用资格）'
                             % [u.get('node') for u in payload['unresolved']][:5])
        _spans, problems = latexml.bound_math_spans(
            source_text, payload, full=True, label='当前源')
        if problems:
            raise ValueError('当前源与来源依据不符: %s' % '；'.join(problems[:5]))
        # 准入追加完整原始源对账（与拆包同一 helper，不降级、不抽查）：
        # 普通正文被替换只在独立对账下可定位，恢复/合并预检同口径拒绝
        admission_diffs = swp.full_source_reconcile_admission(payload, source_text)
        if admission_diffs:
            raise ValueError('当前源与原始快照完整对账失败（不降级）: %s'
                             % '；'.join(admission_diffs[:5]))
    else:
        payloads = [latexml.load_adaptation(p) for p in abs_paths]
        if any(p.get('unresolved') for p in payloads):
            bad = next(p for p in payloads if p.get('unresolved'))
            raise ValueError('来源依据含未解决项 %s（无分派/复用资格）'
                             % [u.get('node') for u in bad['unresolved']][:5])
        _pieces, payload = latexml.multi_admission_view(
            source_text, payloads, abs_paths)
        _spans, problems = latexml.bound_math_spans(
            source_text, payload, full=True, label='当前源')
        if problems:
            raise ValueError('当前源与来源依据整文视图不符: %s'
                             % '；'.join(problems[:5]))

    def project(char_start, char_end):
        return latexml.check_policy_projection(payload, char_start, char_end,
                                               adaptation_abs
                                               if single else abs_paths[0])
    return payload, adaptation_abs, project


def evidence_binding_problems(entry, source_digest, trans_body, resources,
                              script_id, strong_tokens, source_resources,
                              check_policy=None, numeric_expected=None):
    """核对一条复核证据是否仍与当前源资源/文件/资源/口径/脚本身份绑定。

    返回失效原因列表；空列表表示证据有效。证据缺少源资源摘要字段同样
    视为失效（待复核），不因字段缺失放行。任一资源摘要无法核验（缺失、
    外链或不可读）即待复核：两侧同为空或同为 None 不构成匹配依据。
    check_policy 为 D4 最小包口径投影（本包实际涉及的适配事实）：证据
    的 check_policy 块与当前投影不符即失效；无关包事实变化不改变本包
    投影，该包仍可复验复用。
    numeric_expected 为启用 --numeric-review 时的本次包数字绑定投影
    （口径/实现身份/差异 ID 多重集）：证据 numeric 块须与投影一致且
    disposed 逐项覆盖本次差异 ID；未处置项进入 review.unresolved，
    历史/其他目标 ID 与只改说明都不能闭合。脚本不解析 note 推断正确性。
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
    if not isinstance(entry.get('strong_tokens'), list) or \
            sorted(set(entry['strong_tokens'])) != sorted(set(strong_tokens)):
        # 呈现保留首次顺序，资格只比较同一有效集合。
        bad.append('强 token 口径变化，需重新复核')
    if entry.get('check_policy') != check_policy:
        bad.append('check_policy（来源适配投影）与当前依据/适配器不符')
    if numeric_expected is not None:
        declared = entry.get('numeric')
        if not isinstance(declared, dict):
            bad.append('数字辅助已启用，但证据缺少 numeric 块（须逐项'
                       '回源复核并登记本次差异 ID）')
        else:
            for key in ('enabled', 'scope', 'policy', 'checker', 'diff_ids'):
                if declared.get(key) != numeric_expected[key]:
                    bad.append('数字复核绑定失效（%s 与当前口径/输入/'
                               '检查器不符）' % key)
                    break
            else:
                current = Counter(numeric_expected['diff_ids'])
                disposed = declared.get('disposed')
                if not isinstance(disposed, list) or not all(
                        isinstance(item, str) for item in disposed):
                    bad.append('numeric.disposed 必须是差异 ID 字符串列表')
                else:
                    disposed_counts = Counter(disposed)
                    stale = sorted((disposed_counts - current).elements())
                    if stale:
                        bad.append('登记的数字差异 ID 不在本次差异中'
                                   '（历史/其他目标 ID 无效）: %s'
                                   % '；'.join(stale[:3]))
                    unresolved = sorted((current - disposed_counts).elements())
                    if unresolved:
                        bad.append('存在未处置数字差异项（进入 '
                                   'review.unresolved，不授予完成）: %s'
                                   % '；'.join(unresolved[:3]))
    review = entry.get('review') or {}
    if review.get('semantic') != 'done' or review.get('unresolved'):
        bad.append('复核结论未完成或存在未解决项')
    return bad


def check_options(context):
    argv = list(context.get('check_args', []))
    argv, tokens = extract_strong_tokens(argv, base_dir=context['_root'])
    argv, extra = extract_approved_extra_math(argv)
    argv, adaptations = extract_source_adaptation(argv)
    argv, numeric, policy = extract_numeric_review_options(argv)
    if argv:
        raise ValueError('未知包检查参数: %s' % argv)
    root = Path(context['_root'])
    return tokens, extra, [str((root/p).resolve()) for p in adaptations], numeric, str((root/policy).resolve()) if policy else None


def effective_options(context, strong_tokens, extra_math, adaptation, numeric, policy):
    if not context:
        return strong_tokens, extra_math, adaptation, numeric, policy
    tokens, extra, sources, enabled, selected_policy = check_options(context)
    for explicit, configured, label in (
            (strong_tokens, tokens, 'strong_tokens'),
            (extra_math, extra, 'approved_extra_math')):
        if explicit and set(explicit) != set(configured):
            raise ValueError('实际 %s 与项目配置不一致' % label)
    if adaptation:
        given = [adaptation] if isinstance(adaptation,str) else adaptation
        if {os.path.realpath(p) for p in given} != set(sources):
            raise ValueError('实际 source_adaptation 与项目配置不一致')
    if numeric and not enabled or policy and os.path.realpath(policy) != selected_policy:
        raise ValueError('实际数字口径与项目配置不一致')
    return tokens, extra, sources or None, enabled, selected_policy


def extract_project_context(argv):
    if '--project-context' not in argv:
        return argv, None
    i = argv.index('--project-context')
    if i + 1 >= len(argv):
        raise SystemExit('--project-context 需要 JSON 路径')
    return argv[:i] + argv[i+2:], argv[i+1]


def load_project_context(path, source_path):
    if not path:
        return None
    context = json.loads(Path(path).read_text(encoding='utf-8'))
    root = Path(context['project_root']).resolve()
    context['_root'] = str(root)
    context['_path'] = str(Path(path).resolve())
    import verify_delivery as delivery
    record_path = root / context['source_record']
    record = delivery.load_record(record_path)
    problems = []
    entries = delivery.check_source_chains(record['delivery_root'], record, problems, source_only=True)
    delivery.run_source_reconcile(record['delivery_root'], record, entries, problems)
    if problems:
        raise ValueError('当前来源准入/独立对账拒绝: ' + '；'.join(problems))
    if not any(os.path.realpath(e.get('_parsed_abs', '')) == os.path.realpath(source_path)
               for e in entries):
        raise ValueError('source_record 未覆盖当前源')
    review = context.get('source_review')
    if not isinstance(review, dict) or not review.get('basis') or not review.get('scope'):
        raise ValueError('缺少主 Agent 当前来源/范围裁决依据')
    if not context.get('source_scope'):
        raise ValueError('source_scope 必须显式确认，不由实收包反推')
    if review['scope'] != context['source_scope']:
        raise ValueError('来源人工裁决范围与当前声明不符')
    matching = next(e for e in entries if os.path.realpath(e.get('_parsed_abs','')) == os.path.realpath(source_path))
    source_binding = {k: matching[k] for k in ('parsed_sha256','source_version','snapshots')}
    pdf_view=None
    if matching['family']=='pdf-source':
        import _pdf_math
        pdf_view=_pdf_math.source_view(matching,record['delivery_root'],source_path)
        if pdf_view:
            source_binding['pdf_source']=delivery._source_identity(matching,
                lambda rel:str(Path(record['delivery_root'])/rel))
    if review.get('binding') != source_binding:
        raise ValueError('主 Agent 来源裁决未绑定当前源/版本/快照及确认事实；历史 PASS 不授予资格')
    context['_source_version'] = matching['source_version']
    if pdf_view:
        context['_pdf_view']=pdf_view
    return context


def context_refs(context, field, name):
    """明确引用/选区及包选择，无任意条件解释。"""
    result = []
    if field not in context:
        raise ValueError('项目上下文未声明 %s（空清单也须明确）' % field)
    for ref in context[field]:
        if isinstance(ref, str):
            ref = {'path': ref}
        selected = ref.get('packages')
        if selected is not None and name not in selected:
            continue
        path = Path(context['_root'], ref['path']).resolve()
        text = path.read_text(encoding='utf-8')
        lines = text.splitlines(keepends=True)
        start, end = ref.get('start_line', 1), ref.get('end_line', len(lines))
        if not (isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(lines)):
            raise ValueError('不可定位的 %s 选区: %s' % (field, path))
        content = ''.join(lines[start-1:end])
        result.append({'path': str(path), 'start_line': start, 'end_line': end,
                       'sha256': _sha256(content), 'content': content})
    return result


def context_policy(context, name, source_body, target_body):
    result = {'source_version': context['_source_version']}
    if context.get('_pdf_view'):
        result.pop('source_version')  # 全源准入在前；局部资格不绑定无关源版本。
    for field in ('instructions', 'rules', 'glossary', 'output_contract'):
        refs = context_refs(context, field, name)
        result[field] = [{k: v for k, v in ref.items() if k != 'content'} for ref in refs]
    # 具体转换须有两侧可定位文字及批准依据，不免除硬检查。
    conversions = []
    for item in context.get('structural_conversions', []):
        if item.get('package') != name:
            continue
        if not item.get('basis') or not item.get('source') or not item.get('target'):
            raise ValueError('结构转换缺少具体两侧内容/批准依据')
        if item['source'] not in source_body or item['target'] not in target_body:
            raise ValueError('结构转换与当前包不对应')
        conversions.append(item)
    if conversions:
        result['structural_conversions'] = conversions
    return result


def protected_inputs(context, packages, source_path):
    """发布辅助产物不得覆盖来源、当前目标、依据或实际资源依赖。"""
    import verify_delivery as delivery
    from _verification import resource_identity_digest, _clean_reference_target
    paths = {Path(source_path).resolve(), Path(context['_path'])}
    record_path = Path(context['_root'], context['source_record']).resolve()
    paths.add(record_path)
    record = delivery.load_record(record_path)
    root = Path(record['delivery_root'])
    paths.update((root / p).resolve() for p in record.get('files', {}))
    paths.update((root / p).resolve() for p in record.get('inputs', []))
    paths.update((root / p['path']).resolve() for p in record.get('outputs', []))
    for field in ('images_display', 'view_declaration'):
        if record.get(field):
            paths.add((root / record[field]).resolve())
    problems = []
    entries = delivery.check_source_chains(record['delivery_root'], record,
                                           problems, source_only=True)
    if problems:
        raise ValueError('来源保护范围不能核验: ' + '；'.join(problems))
    bodies = []
    paths.update(delivery.source_dependency_paths(root, record, problems, entries=entries))
    if problems:
        raise ValueError('来源保护范围不能核验: ' + '；'.join(problems))
    argv = context.get('check_args', [])
    for i, flag in enumerate(argv[:-1]):
        if flag in ('--strong-token-file', '--numeric-policy', '--source-adaptation'):
            paths.add(Path(context['_root'], argv[i+1]).resolve())
    # 资格范围不缩小输入保护；全量映射已由 current_packages 核对。
    all_packages = []
    for path in Path(packages[0]['path']).parent.glob('*.md'):
        meta, body = _frontmatter(path)
        all_packages.append({'path': str(path), 'target': meta['target_file'],
                             'name': path.name, 'body': body})
    for package in all_packages:
        paths.update((Path(package['path']), Path(package['target'])))
        for field in ('instructions', 'rules', 'glossary', 'output_contract', 'examples'):
            if field in context:
                paths.update(Path(ref['path']) for ref in context_refs(context, field, package['name']))
        bodies.append((package['body'], Path(source_path).resolve().parent))
        if Path(package['target']).is_file():
            bodies.append((_frontmatter(package['target'])[1], Path(package['target']).parent))
    for body, base in bodies:
        refs = image_references(body) + image_marker_refs(body)
        for _, ref in refs:
            resource = _clean_reference_target(ref, str(base))
            if resource:
                memo = {}
                resource_identity_digest(resource, _memo=memo)
                paths.add(Path(resource).resolve())
                paths.update(Path(path) for path in memo)
    return {path.resolve() for path in paths}


def expected_packages(source_path, strategy, trans_dir, adaptation=None, project_context=None):
    with tempfile.TemporaryDirectory(prefix='package_expected_') as tmp:
        paths = swp.split(source_path, os.path.join(tmp, 'wps'), trans_dir,
                          strategy, adaptation, project_context)
        result = []
        for path in paths:
            meta, body = _frontmatter(path)
            result.append({'name': os.path.basename(path), 'meta': meta,
                'order': int(meta['source_order']), 'body': body,
                'section_id': meta['section_id'].strip('"'),
                'instance': meta['section_instance'], 'fragment': meta['fragment_index'],
                'target_file': meta['target_file'], 'digest': meta['fragment_digest'],
                'char_start': int(meta['source_char_start']), 'char_end': int(meta['source_char_end'])})
        return result


def current_packages(source_path, wps_dir, strategy, scope=None, adaptation=None, project_context=None):
    """独立拆包预期与只读源包映射核对；不从实收译文推断范围。"""
    expected = {p['name']: (p['meta'], p['body']) for p in
                expected_packages(source_path, strategy, str(Path(wps_dir).parent/'expected-trans'), adaptation,project_context)}
    actual = {p.name: p for p in Path(wps_dir).glob('*.md')}
    if set(actual) != set(expected):
        raise ValueError('源包范围不符：缺少 %s；额外 %s' %
                         (sorted(set(expected)-set(actual)), sorted(set(actual)-set(expected))))
    packages, targets = [], set()
    for name, (current, body) in expected.items():
        meta, old_body = _frontmatter(actual[name])
        for key in ('source_order', 'section_id', 'section_instance', 'fragment_index',
                    'source_char_start', 'source_char_end', 'fragment_digest'):
            if meta.get(key) != current.get(key):
                raise ValueError('%s 的 %s 与当前源预期不符' % (name, key))
        if old_body != body or os.path.realpath(meta.get('source_file', '')) != os.path.realpath(source_path):
            raise ValueError('异源/损伤源包: %s' % name)
        target = os.path.realpath(meta.get('target_file', ''))
        if not meta.get('target_file') or target in targets or target == os.path.realpath(source_path):
            raise ValueError('错误/复用目标: %s' % name)
        targets.add(target)
        if scope is not None and int(meta['source_order']) not in scope:
            continue
        packages.append({'name': name, 'order': int(meta['source_order']),
                         'digest': meta['fragment_digest'], 'body': body,
                         'char_start': int(meta['source_char_start']),
                         'char_end': int(meta['source_char_end']), 'meta': meta,
                         'path': str(actual[name].resolve()), 'target': target})
    if scope is not None and set(scope) != {p['order'] for p in packages}:
        raise ValueError('明确局部范围包含未知顺序')
    return packages



def package_facts(exp, trans_body, target, source_path, strong_tokens=(),
                  approved_extra_math=(), project=None, numeric_review=False,
                  numeric_policy=None, context=None):
    """当前包事实唯一构造；源与候选各自取事实，不授予复核资格。"""
    policy = (project(exp['char_start'], exp['char_end'])
              if project is not None else None)
    policy = dict(policy or {})
    # 只绑定实际适用的获准额外公式；目标摘要仍独立覆盖全部正文。
    applicable = sorted(set(approved_extra_math).intersection(
        span.expr for span in scan_math(trans_body).spans))
    if applicable:
        policy['approved_extra_math'] = applicable
    if context:
        policy.update(context_policy(context, exp['name'], exp['body'], trans_body))
        if context.get('_pdf_view'):
            import _pdf_math
            policy.update(_pdf_math.policy(context['_pdf_view'],exp['char_start'],exp['char_end']))
    numeric = None
    if numeric_review:
        numeric = numeric_review_mod.numeric_binding(
            exp['body'], trans_body, 'package', numeric_policy)
        policy['numeric'] = numeric_review_mod.numeric_check_policy_block(numeric_policy)
    facts = {
        'source_digest': exp['digest'], 'target_digest': _sha256(trans_body),
        'resource_digests': _resource_digests(trans_body, os.path.dirname(os.path.abspath(target))),
        'source_resource_digests': _source_resource_digests(exp['body'], os.path.dirname(os.path.abspath(source_path))),
        'checker': _script_identity(), 'strong_tokens': sorted(set(strong_tokens)),
    }
    if policy:
        facts['check_policy'] = policy
    if numeric is not None:
        facts['numeric'] = numeric
    return facts


def package_binding_problems(entry, facts, trans_body):
    return evidence_binding_problems(
        entry, facts['source_digest'], trans_body, facts['resource_digests'],
        facts['checker'], facts['strong_tokens'], facts['source_resource_digests'],
        facts.get('check_policy'), facts.get('numeric'))


def recover(source_path, wps_dir, trans_dir, strategy, evidence_path=None,
            strong_tokens=(), approved_extra_math=(), source_adaptation=None,
            numeric_review=False, numeric_policy=None, project_context=None):
    """返回 (reusable, missing, invalidated, pending, reports)。

    reusable/missing/invalidated/pending 元素含 name/order/reason。
    numeric_review 显式启用包级数字复核核对：证据 numeric 块与当前口径/
    输入/检查器绑定且 disposed 覆盖本次差异 ID 才具备复用资格。
    """
    import _pdf_math
    source_text = _pdf_math.read_document(source_path)
    context = load_project_context(project_context, source_path)
    strong_tokens, approved_extra_math, source_adaptation, numeric_review, numeric_policy = effective_options(
        context, strong_tokens, approved_extra_math, source_adaptation, numeric_review, numeric_policy)
    evidence = _load_evidence(evidence_path)
    numeric_policy_abs = None
    if numeric_policy:
        if not numeric_review:
            sys.exit('提供 --numeric-policy 但未启用 --numeric-review：'
                     '口径不生效，请显式启用或移除参数')
        numeric_policy_abs = os.path.abspath(numeric_policy)

    # 当前源预检与包口径投影（LaTeXML 来源显式绑定时；漏参数/不符拒绝，
    # 不降级为普通来源）。多快照（F7/§7.5）时 source_adaptation 为有序
    # 路径列表，payload 为切片校验+逐片对账后的整文视图。
    adaptation_abs = None
    adaptation_payload = None
    project = None
    if source_adaptation:
        try:
            adaptation_payload, adaptation_abs, project = \
                _load_source_adaptation(source_adaptation, source_text)
        except ValueError as exc:
            sys.exit('来源预检拒绝: %s' % exc)

    # 1) 只读重建预期：临时目录拆分，绝不触碰 wps_dir 与既有译文
    expected = expected_packages(source_path, strategy, trans_dir, adaptation_abs,project_context)

    # 2) 读取旧源包（只读），按键唯一对应
    old_packages = {}
    ambiguous = set()
    declared_adaptations = set()
    if os.path.isdir(wps_dir):
        for name in sorted(os.listdir(wps_dir)):
            if not name.endswith('.md'):
                continue
            meta, old_body = _frontmatter(os.path.join(wps_dir, name))
            key = (meta.get('section_id', '').strip('"'),
                   meta.get('section_instance', ''),
                   meta.get('fragment_index', ''))
            if key in old_packages:
                ambiguous.add(key)
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
            old_packages[key] = {
                'name': name,
                'body': old_body,
                'order': meta.get('source_order'),
                'target_file': meta.get('target_file'),
                'digest': meta.get('fragment_digest', ''),
            }

    # 2b) 来源依据绑定一致性：包声明了依据而缺参数/参数不符即整体拒绝
    #     （不降级为普通来源恢复）。多快照按集合核对全部声明引用。
    if declared_adaptations and adaptation_abs is None:
        sys.exit('旧源包声明了 source_adaptation %s，但缺少 --source-'
                 'adaptation 参数：拒绝恢复，不降级为普通来源'
                 % sorted(declared_adaptations))
    if declared_adaptations:
        provided = ({adaptation_abs} if isinstance(adaptation_abs, str)
                    else set(adaptation_abs))
        provided = {os.path.realpath(p) for p in provided}
        if declared_adaptations != provided:
            sys.exit('旧源包声明的 source_adaptation %s 与本次参数 %s 不符：'
                     '拒绝恢复（来源依据不一致，不降级）'
                     % (sorted(declared_adaptations), sorted(provided)))
    if adaptation_abs is not None and not declared_adaptations:
        sys.exit('本次提供 --source-adaptation，但旧源包未登记来源依据'
                 '（请先按当前来源重新拆包）: %s' % wps_dir)

    # 2c) 公式对应不得跨工作包（02-5）：先通过当前全源预检，再按预期
    #     包字符范围核对；跨两包即整体拒绝恢复，不按包截断。多快照用
    #     整文视图 payload（区间已按累计偏移平移到整文坐标）
    if project is not None:
        import _latexml_source as latexml
        payload = (latexml.load_adaptation(adaptation_abs)
                   if isinstance(adaptation_abs, str)
                   else adaptation_payload)
        cross = latexml.correspondence_package_problems(
            payload,
            [(exp['char_start'], exp['char_end']) for exp in expected])
        if cross:
            sys.exit('来源预检拒绝: %s' % '；'.join(cross))

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
        if (old['body'] != exp['body'] or
                str(old['order']) != str(exp['order'])):
            invalidated.append({'name': name, 'order': exp['order'],
                                'reason': '当前源正文/来源/顺序与旧包不符'})
            continue
        if old['digest'] != exp['digest']:
            invalidated.append({'name': name, 'order': exp['order'],
                                'reason': '源片段已变化（摘要不一致），译文需重做'})
            continue

        # 3) 译文目标：以旧源包 frontmatter 指向的唯一目标为准
        target = old['target_file']
        if not target or sum(os.path.realpath(p['target_file'] or '') == os.path.realpath(target)
                             for p in old_packages.values()) != 1:
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
            approved_extra_math, adaptation_abs,
            adaptation_payload=adaptation_payload,
            pdf_view=(context or {}).get('_pdf_view'),source_range=(exp['char_start'],exp['char_end']))
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
        facts = package_facts(exp, trans_body, target, source_path,
                              strong_tokens, approved_extra_math, project,
                              numeric_review, numeric_policy_abs, context)
        bad = package_binding_problems(entry, facts, trans_body)

        if bad:
            pending.append({'name': name, 'order': exp['order'],
                            'reason': '证据失效待复核: ' + '；'.join(bad)})
            continue
        reusable.append({'name': name, 'order': exp['order'],
                         'target': target})

    return reusable, missing, invalidated, pending, reports


def main():
    argv, project_context = extract_project_context(sys.argv[1:])
    argv, strong_tokens = extract_strong_tokens(argv)
    argv, approved_extra_math = extract_approved_extra_math(argv)
    argv, numeric_review, numeric_policy = extract_numeric_review_options(argv)
    evidence_path = None
    source_adaptation = []
    if '--review-evidence' in argv:
        idx = argv.index('--review-evidence')
        if idx + 1 >= len(argv):
            sys.exit('--review-evidence 需要证据文件路径')
        evidence_path = argv[idx + 1]
        argv = argv[:idx] + argv[idx + 2:]
    rest = []
    index = 0
    while index < len(argv):
        if argv[index] == '--source-adaptation':
            if index + 1 >= len(argv):
                sys.exit('--source-adaptation 需要依据文件路径')
            source_adaptation.append(argv[index + 1])
            index += 2
        else:
            rest.append(argv[index])
            index += 1
    argv = rest
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
        strong_tokens, approved_extra_math,
        source_adaptation or None,
        numeric_review, numeric_policy, project_context)

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
