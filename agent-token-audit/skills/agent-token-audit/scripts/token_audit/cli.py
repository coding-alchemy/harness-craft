"""CLI operations share a single report result."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import codex, zcode
from .core import aggregate, known, now, report, timestamp
from .relations import bind
from .formats import export, load_report, render


def read_input(harness, descriptor):
    if descriptor['kind'] == 'zcode_database':
        return bind(zcode.read_database(descriptor['paths'][0]))
    return bind((codex if harness == 'codex' else zcode).read(descriptor['paths']))


def main(argv=None):
    started = now()
    parser = argparse.ArgumentParser(description='按需读取本地 Harness 日志并统计 token；默认不写文件。')
    parser.add_argument('operation', choices=['sessions', 'turns', 'requests', 'report', 'show', 'recompute'])
    parser.add_argument('--harness', choices=['codex', 'zcode'])
    parser.add_argument('--source', action='append', help='日志文件或目录；可重复，默认发现本地日志')
    parser.add_argument('--session', help='来自 sessions 的逻辑会话标识')
    parser.add_argument('--label', help='所选任务的简短名称，保存在报告范围中')
    parser.add_argument('--current', action='store_true', help='仅用 Harness 提供的当前会话环境标识匹配；缺失则报错')
    parser.add_argument('--database', help='只读 ZCode 现有遥测数据库；不与 rollout 相加')
    parser.add_argument('--to', help='带时区截止点，左闭右开')
    parser.add_argument('--from', dest='since', help='带时区时间下界，含边界')
    parser.add_argument('--turn', action='append', help='稳定轮次 ID；可重复传入连续或不连续集合')
    parser.add_argument('--request-start', help='自然语言统计请求的可信起点；追加消息使用消息自身时间')
    parser.add_argument('--request-id', help='本次统计请求的消息/输入 ID；从可信源提取起点')
    agents=parser.add_mutually_exclusive_group()
    agents.add_argument('--main-only', action='store_true', default=None, help='仅主代理常规调用；排除已单列的内部辅助')
    agents.add_argument('--all-agents', dest='main_only', action='store_false', help='明确恢复默认完整代理范围')
    parser.add_argument('--detail', choices=['model','agent','turn'], help='独立明细视图，不重复加入合计')
    parser.add_argument('--format', choices=['table', 'markdown', 'json', 'csv'], default='table', help='标准输出格式；不写文件')
    parser.add_argument('--saved', help='已保存的 JSON 报告')
    parser.add_argument('--update', action='store_true', help='明确更新保存范围；未指定上界时更新到命令开始')
    parser.add_argument('--export', choices=['markdown','csv','json'], help='显式导出；同时提供 --output')
    parser.add_argument('--output', help='导出目标文件')
    args = parser.parse_args(argv)
    try:
        if bool(args.export) != bool(args.output):
            raise ValueError('--export 与 --output 必须同时提供')
        saved = None
        if args.operation in ('show','recompute'):
            if not args.saved:
                raise ValueError('展示或重算需要 --saved JSON 报告')
            saved = load_report(args.saved)
        elif args.saved or args.update:
            raise ValueError('--saved 和 --update 只用于展示或重算已保存报告')
        if args.operation == 'show':
            if any((args.source,args.database,args.turn,args.since,args.to,args.request_start,args.request_id,args.current,args.update,args.session,args.harness,args.label,args.detail)) or args.main_only is not None:
                raise ValueError('show 只展示原报告；修改范围请使用 recompute --update')
            if args.export:
                export(saved,args.export,args.output,[args.saved])
            print(render(saved,args.format),end='')
            return 0
        if sum(bool(v) for v in (args.to,args.request_start,args.request_id)) > 1:
            raise ValueError('--to、--request-start、--request-id 只能指定一个')
        cutoff = args.to or args.request_start or started
        timestamp(cutoff)
        cutoff_source='explicit' if args.to else 'request_start' if args.request_start else 'cli_start'
        harness = args.harness or (saved['harness'] if saved else 'codex')
        if saved:
            old=saved['scope']
            if args.harness and args.harness != saved['harness'] or args.session and args.session != old['session']:
                raise ValueError('原范围重算不能切换 Harness 或会话；请新建查询')
            if not args.update and (any((args.turn,args.since,args.to,args.request_start,args.request_id,args.label)) or args.main_only is not None):
                raise ValueError('改变保存范围必须显式指定 --update')
            args.session=old['session']
            args.turn=args.turn if args.turn is not None else old['turns']
            args.since=args.since or old['from']
            args.main_only=args.main_only if args.main_only is not None else old['main_only']
            args.label=args.label if args.label is not None else old.get('label')
            if not args.update:
                cutoff=old['to'];cutoff_source=old['cutoff_source']
        if args.database and (args.source or harness != 'zcode'):
            raise ValueError('--database 仅用于 ZCode，且不能与 --source 混合计量')
        if saved and not args.database and not args.source:
            descriptor=saved['input']
        elif harness == 'codex':
            sources = args.source or [str(Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'sessions')]
            descriptor={'kind':'jsonl','paths':sources}
        else:
            database = args.database or (str(Path.home()/'.zcode/cli/db/db.sqlite') if not args.source else None)
            if args.database or database and Path(database).expanduser().is_file():
                descriptor={'kind':'zcode_database','paths':[database]}
            else:
                descriptor={'kind':'jsonl','paths':args.source or [str(Path.home()/'.zcode/cli/rollout'),str(Path.home()/'.zcode/cli/log')]}
        descriptor=dict(descriptor,paths=[str(Path(p).expanduser().resolve()) for p in descriptor['paths']])
        if saved and not any(Path(p).exists() for p in descriptor['paths']):
            data={'harness':harness,'sessions':{},'records':[],'issues':[],'source_files':descriptor['paths']}
        else:
            data=read_input(harness,descriptor)
        if args.current:
            if saved or args.session:
                raise ValueError('--current 不与保存范围或显式会话混用')
            candidate=os.environ.get('CODEX_THREAD_ID') if harness == 'codex' else os.environ.get('ZCODE_SESSION_ID')
            if not candidate or candidate not in data['sessions']:
                raise ValueError('无法可靠匹配当前会话；请列出 sessions 候选，不能按最新文件猜选')
            args.session=candidate
        if saved and args.session not in data['sessions']:
            data['sessions'][args.session]={'paths':descriptor['paths'],'turns':{t:{'id':t,'start':None,'end':None,'status':'unknown'} for t in (args.turn or [])}}
            data['issues'].append({'reason':'当前来源缺失或已无该会话；未使用旧报告数值','session':args.session})
        if args.operation == 'sessions':
            counts = {}
            for record in data['records']:
                state = counts.setdefault(record['session'], {'usage_records': 0, 'known_calls': 0})
                state['usage_records'] += int(any(known(record['metrics'][k]) for k in ('input', 'output', 'cache_read')))
                state['known_calls'] += record.get('call_count') or 0
            candidates = []
            for item in data['sessions'].values():
                ends = [t['end'] for t in item['turns'].values() if t.get('end')]
                candidate = {k: item.get(k) for k in ('id', 'harness', 'start', 'version', 'paths', 'parent', 'forked_from')}
                evidence = counts.get(item['id'], {'usage_records': 0, 'known_calls': 0})
                candidate.update(turn_count=len(item['turns']), last_turn_end=max(ends) if ends else None,
                                 evidence=evidence, coverage='当前可用记录，完整覆盖未知')
                candidates.append(candidate)
            result = {'sessions': candidates, 'issues': data['issues']}
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if not args.session:
            raise ValueError('report 需要明确 --session；先用 sessions 查看候选')
        if args.operation == 'requests':
            items=[r for r in data.get('requests',[]) if r['session'] == args.session and r.get('eligible', True)]
            print(json.dumps(items,ensure_ascii=False,indent=2));return 0
        if args.operation == 'turns':
            if args.session not in data['sessions']:
                raise ValueError('会话不存在')
            print(json.dumps(list(data['sessions'][args.session]['turns'].values()), ensure_ascii=False, indent=2)); return 0
        if args.request_id:
            matches=[r for r in data.get('requests',[]) if r['session']==args.session and args.request_id in r.get('ids', [r['id']])]
            if len(matches) != 1:
                raise ValueError('统计请求身份缺失或存在多个来源候选；请明确可用截止点')
            if not matches[0].get('eligible', True):
                raise ValueError(matches[0].get('rejection_reason', '该请求 ID 已确认是合成或非用户消息，不能作为用户请求截止点'))
            times={r['time'] for r in matches}
            if len(times)!=1:
                raise ValueError('统计请求身份缺失或时间冲突；请明确可用截止点')
            cutoff=times.pop();timestamp(cutoff);cutoff_source=matches[0]['time_source']
        result = report(data, args.session, cutoff, main_only=bool(args.main_only), turns=args.turn, since=args.since,
                        cutoff_source=cutoff_source)
        result['input']=descriptor
        result['scope']['label']=args.label
        if args.detail:
            def detail_name(record):
                value=record.get('owner_turn') if args.detail=='turn' and record['session']!=args.session else record.get(args.detail)
                return value or '未知'
            names = sorted({detail_name(r) for r in result['records']})
            result['details'] = [dict(dimension=args.detail, name=name, **aggregate([r for r in result['records'] if detail_name(r) == name])) for name in names]
        if args.export:
            export(result,args.export,args.output,[args.saved] if args.saved else [])
        print(render(result,args.format),end='')
        return 3 if result['status'] == 'unstatisticable' else 0 if result['status'] == 'confirmed_zero' else 2
    except (ValueError, OSError) as exc:
        print('统计错误：' + str(exc), file=sys.stderr)
        return 4
