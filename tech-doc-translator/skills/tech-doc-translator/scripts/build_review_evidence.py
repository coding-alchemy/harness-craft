#!/usr/bin/env python3
"""当前逐包硬检查生成 pending；逐包登记主 Agent 的实际回源记录。"""
import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
import recover_work_packages as rwp
from _verification import image_occurrence_fails


def current(args):
    context = rwp.load_project_context(args.project_context, args.source)
    tokens, extra, adaptations, numeric, policy = rwp.check_options(context)
    payload, adaptation, project = (None, None, None)
    if adaptations:
        payload, adaptation, project = rwp._load_source_adaptation(
            adaptations, Path(args.source).read_text(encoding='utf-8'))
    scope = context['source_scope']
    orders = None if scope == 'all' else scope
    packages = rwp.current_packages(args.source, args.source_packages,
                                   args.strategy, orders, adaptation,args.project_context)
    facts = {}
    for exp in packages:
        target = exp['target']
        if not Path(target).is_file():
            raise ValueError('译文目标缺失: %s' % target)
        meta, body = rwp._frontmatter(target)
        if meta:
            for key in ('source_file', 'source_order', 'section_id', 'section_instance',
                        'fragment_index', 'fragment_digest', 'target_file'):
                if meta.get(key) != exp['meta'].get(key):
                    raise ValueError('译文 %s 错误目标/范围映射: %s' % (target, key))
        else:
            raise ValueError('译文缺少源包映射元数据: %s' % target)
        fails, warns = rwp._fragment_hard_checks(exp['body'], body, target,
                tokens, extra, adaptation, adaptation_payload=payload,
                pdf_view=context.get('_pdf_view'),source_range=(exp['char_start'],exp['char_end']))
        fails.extend(image_occurrence_fails(
            body, str(Path(target).parent), expected_digests=rwp._source_resource_digests(
                exp['body'], str(Path(args.source).resolve().parent)), label='译文包'))
        if fails:
            raise ValueError('%s 硬检查失败: %s' % (exp['name'], '；'.join(fails)))
        fact = rwp.package_facts(exp, body, target, args.source, tokens, extra,
                                project, numeric, policy, context)
        if any(d is None for field in ('resource_digests','source_resource_digests') for d in fact[field]):
            raise ValueError('%s 存在无法核验的两侧资源身份' % exp['name'])
        facts[exp['name']] = (fact, body, warns)
    return context, packages, facts


def protected(context, packages, args):
    paths = rwp.protected_inputs(context, packages, args.source)
    if args.review_record:
        paths.add(Path(args.review_record).resolve())
    return paths


def atomic_write(output, payload, guard):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
            dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        guard()
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare','register-review'])
    parser.add_argument('--source', required=True)
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--source-packages', required=True)
    parser.add_argument('--project-context', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--review-evidence')
    parser.add_argument('--package')
    parser.add_argument('--review-record')
    args = parser.parse_args(argv)
    try:
        context, packages, facts = current(args)
        output = Path(args.output).resolve()
        if output in protected(context, packages, args):
            raise ValueError('输出与只读输入/译文/依据路径冲突')
        old_path = Path(args.review_evidence).resolve() if args.review_evidence else None
        if args.action == 'prepare' and output == old_path:
            raise ValueError('prepare 不得覆盖旧有效证据，须指定新候选')
        if args.action == 'prepare' and output.exists():
            existing = json.loads(output.read_text(encoding='utf-8'))
            if not isinstance(existing,dict) or any(isinstance(e,dict) and e.get('review',{}).get('semantic') == 'done' for e in existing.values()):
                raise ValueError('prepare 不得覆盖现有有效记录，须新候选')
        old_bytes = old_path.read_bytes() if old_path else None
        output_bytes = output.read_bytes() if output.exists() else None
        old = rwp._load_evidence(str(old_path)) if old_path else {}
        result = copy.deepcopy(old) if args.action == 'register-review' else {}
        for name, (fact, body, warns) in facts.items():
            if not rwp.package_binding_problems(old.get(name),fact,body):
                result[name] = copy.deepcopy(old[name])
            else:
                result[name] = copy.deepcopy(fact)
                if 'numeric' in result[name]:
                    result[name]['numeric']['disposed'] = []
                result[name]['review'] = {'semantic':'pending', 'unresolved':
                    list(fact.get('numeric',{}).get('diff_ids',[])),
                    'note':'硬检查只产生待复核；须主 Agent 独立逐包回源', 'warnings':warns}
        record_bytes = None
        if args.action == 'register-review':
            if not old_path or not args.package or not args.review_record:
                raise ValueError('登记须指定候选、单一包及当前主 Agent 实际复核记录')
            name = args.package
            if name not in facts:
                raise ValueError('登记包不在当前明确范围')
            record_bytes = Path(args.review_record).read_bytes()
            review = json.loads(record_bytes)
            declared_facts = copy.deepcopy(review.get('facts'))
            if isinstance(declared_facts,dict) and isinstance(declared_facts.get('numeric'),dict):
                declared_facts['numeric'].pop('disposed',None)
            if declared_facts != facts[name][0]:
                raise ValueError('实际复核记录不绑定当前事实，不能换摘要沿用 done')
            for field in ('scope','basis','note','reviewed_at'):
                if not review.get(field):
                    raise ValueError('实际复核记录缺少 %s' % field)
            if review.get('package') != name or review.get('unresolved') != [] or not isinstance(review.get('items'),list):
                raise ValueError('记录包身份不符或未解决项/处置记录不完整')
            entry = copy.deepcopy(facts[name][0])
            if 'numeric' in entry:
                entry['numeric']['disposed'] = review.get('disposed',[])
            entry['review'] = {k:review[k] for k in ('scope','basis','note','reviewed_at','unresolved','items')}
            entry['review']['semantic'] = 'done'
            bad = rwp.package_binding_problems(entry,facts[name][0],facts[name][1])
            if bad:
                raise ValueError('不能登记完成: ' + '；'.join(bad))
            result[name] = entry
        def guard():
            new_context, new_packages, new_facts = current(args)
            if new_facts != facts or new_packages != packages or new_context != context:
                raise ValueError('发布前当前依赖变化，拒绝替换')
            if old_path and old_path.read_bytes() != old_bytes:
                raise ValueError('旧记录漂移，拒绝替换')
            if (output.read_bytes() if output.exists() else None) != output_bytes:
                raise ValueError('目标记录漂移，拒绝替换')
            if record_bytes is not None and Path(args.review_record).read_bytes() != record_bytes:
                raise ValueError('实际复核记录漂移，拒绝替换')
        if args.action == 'register-review' and output == old_path:
            # 同目录不可变历史副本，原引用不被改写；发布失败仍保留旧当前。
            history = output.with_name(output.stem+'.'+rwp._sha256(old_bytes.decode('utf-8'))[:16]+'.json')
            if history.exists() and history.read_bytes() != old_bytes:
                raise ValueError('历史引用内容冲突')
            if not history.exists():
                history.write_bytes(old_bytes)
        atomic_write(output, result, guard)
        print('%s: %d 包，硬检查不授予复核资格: %s' % (args.action,len(result),output))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, '拒绝: %s\n' % exc)


if __name__ == '__main__':
    main()
