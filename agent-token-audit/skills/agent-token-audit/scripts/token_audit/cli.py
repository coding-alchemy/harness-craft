"""CLI entry: argument parsing, command start time, output and exit status."""
import argparse
import json
import os
from pathlib import Path
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
    parser.add_argument('operation', choices=['sessions', 'turns', 'requests', 'report', 'show', 'recompute', 'overview', 'pricing-update'])
    parser.add_argument('--harness', choices=['codex', 'zcode'])
    parser.add_argument('--source', action='append', help='日志文件或目录；可重复，默认发现本地日志')
    parser.add_argument('--session', action='append', help='来自 sessions 的逻辑会话标识；overview 与 v3 整体报告重算可重复指定集合')
    parser.add_argument('--label', help='所选任务的简短名称，保存在报告范围中')
    parser.add_argument('--current', action='store_true', help='仅用 Harness 提供的当前会话环境标识匹配；缺失则报错')
    parser.add_argument('--database', help='只读 ZCode 现有遥测数据库；不与 rollout 相加')
    parser.add_argument('--to', help='带时区截止点，左闭右开')
    parser.add_argument('--from', dest='since', help='带时区时间下界，含边界')
    parser.add_argument('--time-preset', choices=['today', 'week', 'month', 'last_1d', 'last_3d', 'last_7d', 'last_30d', 'all'],
                        help='整体查询快捷时间范围；按所选时区解析为绝对下界，仅用于独立 overview')
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
    pricing_group = parser.add_mutually_exclusive_group()
    pricing_group.add_argument('--pricing', help='自定义价格配置 JSON 文件；仅用于 report/overview/recompute 的明确费用查询')
    pricing_group.add_argument('--default-pricing', action='store_true', help='使用随包官网价格快照计价；仅用于 report/overview/recompute')
    pricing_group.add_argument('--no-pricing', action='store_true', help='仅统计 token 与性能，不加载价格；只用于独立的新查询')
    parser.add_argument('--update', action='store_true', help='明确更新保存范围；未指定上界时更新到命令开始')
    parser.add_argument('--candidate', help='pricing-update 专用：已读取固定官网形成的 schema v2 候选 JSON 文件')
    parser.add_argument('--export', choices=['markdown','csv','json'], help='显式导出；同时提供 --output')
    parser.add_argument('--output', help='导出目标文件')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'pricing-update':
            # The Skill update workflow reads the fixed official sources with its own web
            # capability and submits the read-formed candidate here; this action only
            # validates and writes, never fetches.
            if not args.candidate:
                raise ValueError('pricing-update 需要 --candidate <已读取形成的 v2 候选 JSON>')
            if args.saved or args.update or args.export or args.output or args.pricing \
                    or args.default_pricing or args.no_pricing:
                raise ValueError('pricing-update 不与保存报告、范围更新、导出或查询价格参数混用')
            from . import pricing as pricing_resources
            try:
                report = pricing_resources.update_from_candidate(Path(args.candidate).read_text(encoding='utf-8'))
            except json.JSONDecodeError as exc:
                raise ValueError('候选不是有效 JSON') from exc
            print('更新目标（实际加载的 Skill 资源副本）：' + report['target_root'])
            print('上一默认快照：' + (report['previous'] or '无'))
            print('候选快照：' + report['revision'])
            for source in report['sources']:
                print('  来源读取：%s（%s）' % (source['url'], source['fetched_at']))
            if report['rule_changes'] is not None:
                changes = report['rule_changes']
                print('规则变化：新增 %d、移除 %d、变更 %d%s'
                      % (len(changes['added']), len(changes['removed']), len(changes['changed']),
                         ('（' + '、'.join(changes['added'] + changes['removed'] + changes['changed']) + '）')
                         if changes['added'] or changes['removed'] or changes['changed'] else ''))
            if report['uncovered']:
                print('未覆盖项：' + '、'.join(report['uncovered']))
            if report['enabled']:
                print('更新成功：候选已保存为历史快照，默认引用已原子切换为 ' + report['revision'])
                return 0
            print('候选已保存为未启用快照（读取记录保留），默认保持 '
                  + (report['previous'] or '无') + '：目录未覆盖 '
                  + '、'.join(report['missing_targets'])
                  + '；固定目录每款模型须有本轮可核查规则或已核查无价原因')
            return 2
        if args.candidate:
            raise ValueError('--candidate 只用于 pricing-update')
        if bool(args.export) != bool(args.output):
            raise ValueError('--export 与 --output 必须同时提供')
        saved = None
        if args.operation in ('show','recompute'):
            if not args.saved:
                raise ValueError('展示或重算需要 --saved JSON 报告')
            saved = read_decoded(args.saved)
        elif args.saved or args.update:
            raise ValueError('--saved 和 --update 只用于展示或重算已保存报告')
        pricing = None
        pricing_mode = None
        if args.pricing:
            if args.operation not in ('report', 'overview', 'recompute'):
                raise ValueError('--pricing 仅用于 report/overview/recompute 的明确费用查询；候选列举与 show 不接受价格')
            try:
                pricing = json.loads(Path(args.pricing).read_text())
            except json.JSONDecodeError as exc:
                raise ValueError('价格配置不是有效 JSON') from exc
            if pricing is None:
                raise ValueError('价格配置为 null；未选择配置请省略 --pricing')
            pricing_mode = 'custom'
        elif args.default_pricing:
            if args.operation not in ('report', 'overview', 'recompute'):
                raise ValueError('--default-pricing 仅用于 report/overview/recompute；候选列举与 show 不接受价格')
            pricing_mode = 'default'
        elif args.no_pricing:
            if args.operation != 'report' and args.operation != 'overview' or args.saved:
                raise ValueError('--no-pricing 只用于独立的新 report/overview 查询；重算请沿用保存价格或明确换价')
            pricing_mode = 'none'
        # Baseline CLI saved-scope merge treated --from '' as omitted. New reports
        # keep the original empty string; HTTP explicit null remains CLEAR.
        since = None if saved is not None and args.since == '' else args.since
        if args.time_preset and args.operation != 'overview':
            raise ValueError('--time-preset 只用于独立的新整体查询（overview）')
        if args.time_preset and since:
            raise ValueError('--time-preset 与 --from 互斥；需要精确下界请使用自定义范围')
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
                            sessions=sessions, tz=args.tz, time_preset=args.time_preset,
                            label=args.label, use_current=args.current,
                            current_identities=current_identities() if args.current else None,
                            to=args.to, since=since, turns=args.turn,
                            request_start=args.request_start, request_id=args.request_id,
                            main_only=args.main_only, detail=args.detail, saved=saved,
                            update=args.update, pricing=pricing, pricing_mode=pricing_mode))
        if outcome['kind'] == 'listing':
            print(json.dumps(outcome['payload'], ensure_ascii=False, indent=2))
            return 0
        if args.export:
            protected = ([args.saved] if args.saved else []) + ([args.pricing] if args.pricing else [])
            export(outcome['report'],args.export,args.output,protected)
        print(render(outcome['report'],args.format),end='')
        return outcome['exit']
    except (ValueError, OSError) as exc:
        print('统计错误：' + str(exc), file=sys.stderr)
        return 4
