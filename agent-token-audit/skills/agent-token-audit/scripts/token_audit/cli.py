"""CLI entry: argument parsing, command start time, output and exit status."""
import argparse
import json
import os
import sys
from .core import now
from .formats import export, read_decoded, render
from .operations import Query, run


def current_identities():
    return {harness: os.environ.get('CODEX_THREAD_ID' if harness == 'codex' else 'ZCODE_SESSION_ID')
            for harness in ('codex', 'zcode')}


def main(argv=None):
    started = now()
    parser = argparse.ArgumentParser(description='按需读取本地 Harness 日志并统计 token；默认不写文件。')
    parser.add_argument('operation', choices=['sessions', 'turns', 'requests', 'report', 'show', 'recompute', 'overview'])
    parser.add_argument('--harness', choices=['codex', 'zcode'])
    parser.add_argument('--source', action='append', help='日志文件或目录；可重复，默认发现本地日志')
    parser.add_argument('--session', action='append', help='来自 sessions 的逻辑会话标识；overview 与 v3 整体报告重算可重复指定集合')
    parser.add_argument('--label', help='所选任务的简短名称，保存在报告范围中')
    parser.add_argument('--current', action='store_true', help='仅用 Harness 提供的当前会话环境标识匹配；缺失则报错')
    parser.add_argument('--database', help='只读 ZCode 现有遥测数据库；不与 rollout 相加')
    parser.add_argument('--to', help='带时区截止点，左闭右开')
    parser.add_argument('--from', dest='since', help='带时区时间下界，含边界')
    parser.add_argument('--tz', help='整体趋势的显示时区（IANA 名称或 ±HH:MM；默认系统本地）')
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
            saved = read_decoded(args.saved)
        elif args.saved or args.update:
            raise ValueError('--saved 和 --update 只用于展示或重算已保存报告')
        # Baseline CLI saved-scope merge treated --from '' as omitted. New reports
        # keep the original empty string; HTTP explicit null remains CLEAR.
        since = None if saved is not None and args.since == '' else args.since
        # Repeated --session is a set only for overall queries; a v1/v2 saved report keeps
        # its single-session identity check, so there --session stays one value.
        set_session_op = args.operation == 'overview' or args.operation == 'recompute' \
            and isinstance(saved, dict) and saved.get('format_version') == 3
        sessions = args.session if set_session_op else None
        session = None
        if not set_session_op:
            if args.session and len(args.session) > 1:
                raise ValueError('--session 仅接受单个值；overview 与整体报告重算可重复指定会话集合')
            session = args.session[-1] if args.session else None
        outcome = run(Query(operation=args.operation, started=started, harness=args.harness,
                            sources=args.source, database=args.database, session=session,
                            sessions=sessions, tz=args.tz,
                            label=args.label, use_current=args.current,
                            current_identities=current_identities() if args.current else None,
                            to=args.to, since=since, turns=args.turn,
                            request_start=args.request_start, request_id=args.request_id,
                            main_only=args.main_only, detail=args.detail, saved=saved,
                            update=args.update))
        if outcome['kind'] == 'listing':
            print(json.dumps(outcome['payload'], ensure_ascii=False, indent=2))
            return 0
        if args.export:
            export(outcome['report'],args.export,args.output,[args.saved] if args.saved else [])
        print(render(outcome['report'],args.format),end='')
        return outcome['exit']
    except (ValueError, OSError) as exc:
        print('统计错误：' + str(exc), file=sys.stderr)
        return 4
