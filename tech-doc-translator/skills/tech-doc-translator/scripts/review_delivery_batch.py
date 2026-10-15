#!/usr/bin/env python3
"""显式批次复跑现有交付验收；不扫描、补签、重派或清理。"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import verify_delivery as delivery
from _verification import image_references, image_marker_refs, resource_identity_digest, _clean_reference_target


def protected_record_paths(record, problems=None):
    """只枚举本记录的实际依赖；沿用来源事实、真实 CLI 与资源遍历。"""
    problems = [] if problems is None else problems
    root=Path(record['delivery_root']).resolve()
    paths={(root/p).resolve() for p in record.get('files',{})}
    paths.add(Path(delivery.SCRIPTS_DIR,'verify_delivery.py'))
    if 'pdf' in record.get('mode',''):
        paths.add(Path(delivery.SCRIPTS_DIR).parent/'assets/pdf/style.css')
    if 'glossary' in record.get('files',{}).values():
        paths.update(Path(delivery.SCRIPTS_DIR,p) for p in delivery.GLOSSARY_SHARED_DEPS)
    documents={(root/p).resolve() for p in record.get('inputs',[])}
    paths.update((root/o['path']).resolve() for o in record.get('outputs',[]))
    for field in ('images_display','view_declaration'):
        if record.get(field):paths.add((root/record[field]).resolve())
    paths.update(delivery.source_dependency_paths(root, record, problems))
    paths.update(documents)
    for document in documents:
        if not document.is_file():continue
        try:
            text=document.read_text(encoding='utf-8')
        except (OSError,ValueError) as exc:
            problems.append('依赖正文不可读: %s（%s）' % (document,exc))
            continue
        for _,ref in image_references(text)+image_marker_refs(text):
            resource=_clean_reference_target(ref,str(document.parent))
            if resource:
                memo={};resource_identity_digest(resource,_memo=memo)
                paths.add(Path(resource).resolve());paths.update(Path(p) for p in memo)
    def file_paths(value):
        if isinstance(value,(tuple,list)):
            if len(value)==2 and isinstance(value[0],str):
                paths.add(Path(value[0]).resolve())
            else:
                for item in value:file_paths(item)
        elif isinstance(value,dict):
            for item in value.values():file_paths(item)
    for order,check in enumerate(record.get('checks',[]),1):
        tool=check.get('tool')
        if tool not in delivery.KNOWN_TOOLS:continue
        paths.add(Path(delivery.SCRIPTS_DIR,delivery.KNOWN_TOOLS[tool]))
        paths.update(Path(delivery.SCRIPTS_DIR,p) for p in delivery.CHECK_SHARED_DEPS[tool])
        facts,_=delivery._check_facts(str(root),tool,list(check.get('args') or []),order)
        if facts:file_paths(facts['files'])
    return paths


def current_identity(record_path):
    record=delivery.load_record(record_path)
    problems=[]
    entries=delivery.check_source_chains(record['delivery_root'],record,problems)
    if problems:
        raise ValueError('；'.join(problems))
    # 与既有 JSON 索引同形：资源 tuple 发布后为 list，不改变事实。
    return json.loads(json.dumps(delivery.compute_delivery_identity(
        record['delivery_root'],record,entries)))


def review(manifest_path, report_path, python=None, skill_dir=None):
    manifest_path, report_path=Path(manifest_path).resolve(),Path(report_path).resolve()
    raw=manifest_path.read_bytes();manifest=json.loads(raw)
    projects=manifest.get('projects')
    if not isinstance(projects,list) or not projects:
        raise ValueError('批次必须显式列出 projects')
    root=manifest_path.parent
    python=python or sys.executable
    skill_dir=Path(skill_dir or Path(__file__).resolve().parent.parent).resolve()
    executable=skill_dir/'scripts/verify_delivery.py'
    protected={manifest_path,executable}
    # 整份显式声明先检查；歧义/输出冲突不先执行其他项目。
    declaration_names, declaration_records = set(), set()
    dependency_problems = {}
    for item in projects:
        name=item['project'];rp=(root/item['record']).resolve()
        ep=(root/item['evidence_dir']).resolve()
        if not name or name in declaration_names or rp in declaration_records:
            raise ValueError('重复或歧义项目声明: '+str(name))
        declaration_names.add(name);declaration_records.add(rp)
        protected.add(rp)
        dependency_problems[name] = []
        if ep == report_path or ep in report_path.parents:
            raise ValueError('报告不得覆盖证据及历史引用')
        if rp.is_file():
            try:
                record=delivery.load_record(rp)
            except delivery.DeliveryError:
                # 记录缺口属于本项目；可解析的声明仍用于保护输入。
                try:
                    declared=json.loads(rp.read_bytes())
                    if isinstance(declared,dict) and isinstance(declared.get('delivery_root'),str):
                        protected.update(protected_record_paths(declared,dependency_problems[name]))
                except (OSError,ValueError,KeyError,TypeError,delivery.DeliveryError):
                    pass
                continue
            if record['mode']!=item['mode'] or record.get('inputs')!=item['scope']:
                raise ValueError('清单与实际记录模式/范围不符: '+str(name))
            protected.update(protected_record_paths(record,dependency_problems[name]))
    if report_path in protected:
        raise ValueError('报告与受保护输入/产物路径冲突')
    results=[]
    for item in projects:
        name=item['project'];record_path=(root/item['record']).resolve()
        evidence=(root/item['evidence_dir']).resolve()
        if report_path==evidence or evidence in report_path.parents:
            raise ValueError('报告不得覆盖证据及其历史引用')
        result={'project':name,'mode':item['mode'],'scope':item['scope'],
                'record':str(record_path),'status_note':item.get('status_note'),
                'status':'incomplete','diagnostics':list(dependency_problems[name]), 'call':None,'exit_code':None}
        results.append(result)
        try:
            record=delivery.load_record(record_path)
            if record['mode']!=item['mode'] or record.get('inputs')!=item['scope']:
                raise ValueError('清单与实际记录模式/范围不符')
            project_root=Path(record['delivery_root']).resolve()
            protected.update((project_root/p).resolve() for p in record.get('files',{}))
            actual=[(project_root/p).resolve() for p in record.get('inputs',[])]
            actual += [(project_root/o['path']).resolve() for o in record.get('outputs',[])]
            missing=[str(p) for p in actual if not p.is_file()]
            if missing:
                result['category']='missing-artifact' if any(p.is_file() for p in actual) else 'unknown'
                result['diagnostics'].append('缺产物: '+', '.join(missing))
                if result['category']=='unknown':result['status']='unknown'
            old_index=evidence/'delivery_index.json'
            old_identity=None
            if old_index.is_file():
                old_identity=json.loads(old_index.read_text(encoding='utf-8')).get('identity')
            result['record_sha256']=delivery.sha256_file(record_path)
            cmd=[str(python),str(executable),'--record',str(record_path),'--evidence-dir',str(evidence)]
            result['call']=cmd
            completed=subprocess.run(cmd,capture_output=True,text=True)
            result['exit_code']=completed.returncode
            result['stdout']=completed.stdout;result['stderr']=completed.stderr
            if completed.returncode:
                hard_failure='核验入口复验失败:' in completed.stderr
                result.setdefault('category','review-gap' if '复核' in completed.stderr and not hard_failure else 'current-verification-failed')
                result['diagnostics'].append(completed.stderr.strip() or completed.stdout.strip())
                if old_identity is not None:
                    try:
                        if current_identity(record_path)!=old_identity:
                            if result.get('category') not in ('missing-artifact','unknown'):
                                result['category']='expired'
                            result['diagnostics'].append('旧证据身份与当前输入不符')
                    except (ValueError,delivery.DeliveryError,OSError):
                        pass
            else:
                index=json.loads(old_index.read_text(encoding='utf-8'))
                result['status']='complete';result['category']='current-complete'
                result['evidence_index']=str(old_index)
                result['identity']=index['identity']
                result['evidence_sha256']=delivery.sha256_file(old_index)
            if item.get('status_note') and result['status']!='complete':
                result['diagnostics'].append('辅助状态与当前结果不一致或不足以确认；不推断分派/收件')
        except (OSError,ValueError,KeyError,TypeError,delivery.DeliveryError) as exc:
            result['diagnostics'].append(str(exc));result.setdefault('category','record-gap')
            if not record_path.is_file():
                result['status']='unknown';result['category']='unknown'
        if report_path in protected:
            raise ValueError('报告与受保护输入/产物路径冲突')
    # 报告发布前按当前交付身份独立复查引用，漂移只撤本项目当前资格。
    def recheck_references():
        changed=False
        for result in results:
            if result['status']!='complete':continue
            try:
                if (current_identity(result['record'])!=result['identity'] or
                    delivery.sha256_file(result['record'])!=result['record_sha256'] or
                    delivery.sha256_file(result['evidence_index'])!=result['evidence_sha256']):
                    raise ValueError('验收后、报告发布前输入/记录/索引漂移')
            except (OSError,ValueError,delivery.DeliveryError) as exc:
                result['status']='expired';result['category']='expired';result['diagnostics'].append(str(exc))
                changed=True
        return changed
    recheck_references()
    report={'reviewed_at':datetime.now(timezone.utc).isoformat(),
            'manifest':str(manifest_path),'projects':results,
            'complete':all(r['status']=='complete' for r in results)}
    if manifest_path.read_bytes()!=raw:
        raise ValueError('批次清单在报告发布前漂移，拒绝发布')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    old=report_path.read_bytes() if report_path.exists() else None
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=report_path.parent,delete=False) as handle:
        temp=Path(handle.name);json.dump(report,handle,ensure_ascii=False,indent=2)
    try:
        if recheck_references():
            report['complete']=all(r['status']=='complete' for r in results)
            temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if manifest_path.read_bytes()!=raw:
            raise ValueError('批次清单在报告写入期间漂移，拒绝发布')
        for result in results:
            if Path(result['record']).is_file():
                try:
                    record=json.loads(Path(result['record']).read_bytes())
                    if isinstance(record,dict) and isinstance(record.get('delivery_root'),str):
                        protected.update(protected_record_paths(record))
                except (OSError,ValueError,KeyError,TypeError,delivery.DeliveryError):
                    # 逐项诊断已保留；不可读记录不撤销其他独立结果。
                    pass
        if report_path in protected:
            raise ValueError('报告与当前受保护依赖路径冲突')
        if (report_path.read_bytes() if report_path.exists() else None)!=old:
            raise ValueError('报告目标在发布前漂移')
        os.replace(temp,report_path)
    finally:temp.unlink(missing_ok=True)
    return report['complete']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--python')
    parser.add_argument('--skill-dir')
    args=parser.parse_args()
    try:
        ok=review(args.manifest,args.output,args.python,args.skill_dir)
        print('批次当前完成' if ok else '批次仍有未完成/不明/过期项')
        return 0 if ok else 1
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(1,'批次拒绝: %s\n'%exc)


if __name__=='__main__':
    raise SystemExit(main())
