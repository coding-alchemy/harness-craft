"""Operations shared by every entry point: source choice, localization, scope reuse and reports.

No argparse, HTTP, terminal rendering or subprocess here; entry points parse their own
inputs, pass a Query and decide how to present the returned outcome.
"""
import dataclasses
import os
from pathlib import Path
from . import codex, zcode
from .core import known, local_timezone_name, overview, report, timestamp
from .formats import validate_report
from .relations import bind

# An explicit "no constraint" marker for update merges: the entry point distinguishes a field
# the caller omitted (keep the saved constraint) from one the user explicitly cleared. Only
# entry points that receive tri-state input construct it; the CLI never does.
CLEAR = object()


def read_input(harness, descriptor, guard=None):
    if descriptor['kind'] == 'zcode_database':
        return bind(zcode.read_database(descriptor['paths'][0], guard))
    return bind((codex if harness == 'codex' else zcode).read(descriptor['paths'], guard))


def cutoff_evidence(source):
    if source == 'explicit':
        return '用户显式指定的 --to 截止时间'
    if source == 'request_start':
        return '调用方提供的可信请求起点；时间字符串本身未验证请求身份'
    if source == 'cli_start':
        return '独立 CLI 命令开始时间（默认截止点）'
    if source == 'web_request_start':
        return '本地服务收到本次网页统计请求、进入请求处理入口的时间'
    return '本次统计请求（--request-id）自身的创建/入队起点'


def localization_of(session, used_current, saved, harness, cutoff, cutoff_source):
    if saved:
        confirmed, evidence = 'saved_scope', '沿用已保存报告确定的会话范围'
    elif used_current:
        variable = 'CODEX_THREAD_ID' if harness == 'codex' else 'ZCODE_SESSION_ID'
        confirmed, evidence = 'current_env', '环境变量 ' + variable + ' 与记录会话唯一匹配'
    else:
        confirmed, evidence = 'explicit', '显式指定的 --session 会话标识'
    limits = []
    if cutoff_source == 'request_start':
        limits.append('截止时间为调用方提供；工具未验证请求身份')
    if cutoff_source == 'cli_start':
        limits.append('独立 CLI 不读取运行环境身份；截止点为命令开始时间')
    if cutoff_source == 'web_request_start':
        limits.append('截止点为本地服务收到本次网页请求的处理入口时间，不等于浏览器点击瞬间')
    if saved:
        limits.append('定位证据沿用已保存报告；本次重算未重新定位')
    return {'session': {'id': session, 'confirmed_by': confirmed, 'evidence': evidence},
            'cutoff': {'time': cutoff, 'source': cutoff_source, 'evidence': cutoff_evidence(cutoff_source)},
            'limits': limits}


def default_descriptor(harness, sources, database):
    """Pick the telemetry descriptor from explicit sources or the local defaults."""
    if database and (sources or harness != 'zcode'):
        raise ValueError('--database 仅用于 ZCode，且不能与 --source 混合计量')
    if harness == 'codex':
        roots = sources or [str(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions')]
        return {'kind': 'jsonl', 'paths': roots}
    fallback = database or (str(Path.home() / '.zcode/cli/db/db.sqlite') if not sources else None)
    if database or fallback and Path(fallback).expanduser().is_file():
        return {'kind': 'zcode_database', 'paths': [fallback]}
    return {'kind': 'jsonl', 'paths': sources or [str(Path.home() / '.zcode/cli/rollout'), str(Path.home() / '.zcode/cli/log')]}


def resolve_current(data, harness, query):
    if query.saved or query.session:
        raise ValueError('--current 不与保存范围或显式会话混用')
    variable = 'CODEX_THREAD_ID' if harness == 'codex' else 'ZCODE_SESSION_ID'
    candidate = (query.current_identities or {}).get(harness)
    if not candidate:
        raise ValueError('当前环境未提供可信会话身份（' + variable + ' 缺失）；请运行 sessions 查看候选并明确选择，不能按最新文件猜选')
    if candidate not in data['sessions']:
        raise ValueError('环境提供的会话身份与记录不匹配；请运行 sessions 核对候选并明确选择')
    query.session = candidate


def listing_sessions(data):
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
    return {'sessions': candidates, 'issues': data['issues']}


def resolve_request_cutoff(data, session, request_id):
    matches = [r for r in data.get('requests', []) if r['session'] == session and request_id in r.get('ids', [r['id']])]
    if len(matches) != 1:
        raise ValueError('统计请求身份缺失或存在多个来源候选；请明确可用截止点')
    if not matches[0].get('eligible', True):
        raise ValueError(matches[0].get('rejection_reason', '该请求 ID 已确认是合成或非用户消息，不能作为用户请求截止点'))
    times = {r['time'] for r in matches}
    if len(times) != 1:
        raise ValueError('统计请求身份缺失或时间冲突；请明确可用截止点')
    cutoff = times.pop()
    timestamp(cutoff)
    return cutoff, matches[0]['time_source']


@dataclasses.dataclass
class Query:
    operation: str
    started: str
    started_source: str = 'cli_start'
    harness: str = None
    sources: list = None
    database: str = None
    session: str = None
    sessions: list = None
    tz: str = None
    label: str = None
    use_current: bool = False
    current_identities: dict = None
    to: str = None
    since: str = None
    turns: list = None
    request_start: str = None
    request_id: str = None
    main_only: bool = None
    detail: str = None
    saved: dict = None
    update: bool = False
    descriptor: dict = None
    guard: object = None


def resolve_overview_request_cutoff(data, request_id):
    """A request cutoff for an overall query must identify exactly one request source-wide."""
    matches = [r for r in data.get('requests', []) if request_id in r.get('ids', [r['id']])]
    if len(matches) != 1:
        raise ValueError('统计请求身份缺失或存在多个来源候选；请明确可用截止点')
    if not matches[0].get('eligible', True):
        raise ValueError(matches[0].get('rejection_reason', '该请求 ID 已确认是合成或非用户消息，不能作为用户请求截止点'))
    times = {r['time'] for r in matches}
    if len(times) != 1:
        raise ValueError('统计请求身份缺失或时间冲突；请明确可用截止点')
    cutoff = times.pop()
    timestamp(cutoff)
    return cutoff, matches[0]['time_source']


def run_overview(query, data, cutoff, cutoff_source, descriptor):
    explicit = query.sessions is not None
    if query.sessions is None:
        query.sessions = sorted(data['sessions'])
        if not query.sessions:
            data['issues'].append({'reason': '来源中未解析到任何会话'})
    else:
        # One canonical explicit set for scope, localization evidence and selection:
        # duplicates must not count twice or disagree with the deduplicated scope.
        query.sessions = sorted(set(query.sessions))
    query.tz = query.tz or local_timezone_name()
    if query.saved:
        confirmed, evidence = 'saved_scope', '沿用已保存报告确定的会话范围'
    elif explicit:
        confirmed, evidence = 'explicit_set', f'显式指定的会话集合（{len(query.sessions)} 个会话）'
    else:
        confirmed, evidence = 'all_source_sessions', f'未显式指定会话；纳入本次来源解析到的全部 {len(query.sessions)} 个会话'
    limits = ['整体查询无 --current；不猜当前会话']
    if cutoff_source == 'request_start':
        limits.append('截止时间为调用方提供；工具未验证请求身份')
    if cutoff_source == 'cli_start':
        limits.append('独立 CLI 不读取运行环境身份；截止点为命令开始时间')
    if cutoff_source == 'web_request_start':
        limits.append('截止点为本地服务收到本次网页请求的处理入口时间，不等于浏览器点击瞬间')
    localization = {'sessions': {'count': len(query.sessions), 'confirmed_by': confirmed, 'evidence': evidence},
                    'cutoff': {'time': cutoff, 'source': cutoff_source, 'evidence': cutoff_evidence(cutoff_source)},
                    'limits': limits}
    result = overview(data, query.sessions, cutoff, since=query.since, tz=query.tz,
                      main_only=bool(query.main_only), cutoff_source=cutoff_source,
                      localization=localization, missing_ok=bool(query.saved))
    result['input'] = descriptor
    exit_code = 3 if result['status'] == 'unstatisticable' else 0 if result['status'] == 'confirmed_zero' else 2
    return {'kind': 'report', 'report': result, 'exit': exit_code}


def run(query):
    saved = validate_report(query.saved) if query.saved is not None else None
    if query.operation == 'show':
        if any((query.sources, query.database, query.turns, query.since, query.to, query.request_start,
                query.request_id, query.use_current, query.update, query.session, query.harness,
                query.label, query.detail)) or query.main_only is not None:
            raise ValueError('show 只展示原报告；修改范围请使用 recompute --update')
        return {'kind': 'report', 'report': saved, 'exit': 0}
    if sum(bool(v) for v in (query.to, query.request_start, query.request_id)) > 1:
        raise ValueError('--to、--request-start、--request-id 只能指定一个')
    cutoff = query.to or query.request_start or query.started
    timestamp(cutoff)
    cutoff_source = 'explicit' if query.to else 'request_start' if query.request_start else query.started_source
    harness = query.harness or (saved['harness'] if saved else 'codex')
    saved_overall = bool(saved and saved.get('format_version') == 3)
    if saved and saved_overall:
        old = saved['scope']
        if query.harness and query.harness != saved['harness']:
            raise ValueError('原范围重算不能切换 Harness 或会话；请新建查询')
        if not query.update and (any((query.sessions, query.since, query.to, query.request_start,
                                      query.request_id, query.label, query.tz)) or query.main_only is not None):
            raise ValueError('改变保存范围必须显式指定 --update')
        if query.update:
            if query.sessions is None:
                query.sessions = list(old['sessions'])
            if query.since is CLEAR:
                query.since = None
            elif query.since is None:
                query.since = old['from']
            query.tz = query.tz or old['tz']
            query.main_only = query.main_only if query.main_only is not None else old['main_only']
        else:
            query.sessions = list(old['sessions'])
            query.since = old['from']
            query.tz = old['tz']
            query.main_only = old['main_only']
            cutoff = old['to']
            cutoff_source = old['cutoff_source']
    elif saved:
        old = saved['scope']
        if query.sessions:
            raise ValueError('保存的会话范围不支持会话集合；整体查询请使用 overview 或 v3 保存报告')
        if query.harness and query.harness != saved['harness'] or query.session and query.session != old['session']:
            raise ValueError('原范围重算不能切换 Harness 或会话；请新建查询')
        if not query.update and (any((query.turns, query.since, query.to, query.request_start, query.request_id, query.label)) or query.main_only is not None):
            raise ValueError('改变保存范围必须显式指定 --update')
        query.session = old['session']
        # Identity checks keep "field absent" (None) as "keep the saved constraint";
        # CLEAR means the user explicitly removed it.
        query.turns = None if query.turns is CLEAR else (query.turns if query.turns is not None else old['turns'])
        query.since = None if query.since is CLEAR else (query.since if query.since is not None else old['from'])
        query.main_only = query.main_only if query.main_only is not None else old['main_only']
        query.label = query.label if query.label is not None else old.get('label')
        if not query.update:
            cutoff = old['to']
            cutoff_source = old['cutoff_source']
    if query.sources or query.database:
        descriptor = default_descriptor(harness, query.sources, query.database)
    elif saved:
        # The saved report's recorded metering source wins for recompute; the guard still
        # verifies it belongs to what this entry point may read.
        descriptor = saved['input']
    else:
        descriptor = query.descriptor or default_descriptor(harness, None, None)
    descriptor = dict(descriptor, paths=[str(Path(p).expanduser().resolve()) for p in descriptor['paths']])
    if saved and not any(Path(p).exists() for p in descriptor['paths']):
        data = {'harness': harness, 'sessions': {}, 'records': [], 'issues': [], 'source_files': descriptor['paths']}
    else:
        data = read_input(harness, descriptor, query.guard)
    if saved and saved_overall and not any(Path(p).exists() for p in descriptor['paths']):
        for sid in query.sessions:
            data['sessions'][sid] = {'id': sid, 'harness': harness, 'start': None, 'version': None,
                                     'paths': descriptor['paths'], 'turns': {}, 'parent': None, 'forked_from': None}
        data['issues'].append({'reason': '当前来源缺失或已无该会话集合；未使用旧报告数值'})
    if query.use_current:
        resolve_current(data, harness, query)
    if saved and not saved_overall and query.session not in data['sessions']:
        data['sessions'][query.session] = {'paths': descriptor['paths'],
                                           'turns': {t: {'id': t, 'start': None, 'end': None, 'status': 'unknown'} for t in (query.turns or [])}}
        data['issues'].append({'reason': '当前来源缺失或已无该会话；未使用旧报告数值', 'session': query.session})
    if query.operation == 'sessions':
        return {'kind': 'listing', 'payload': listing_sessions(data)}
    if query.operation == 'overview' or saved_overall and query.operation == 'recompute':
        if query.request_id:
            cutoff, cutoff_source = resolve_overview_request_cutoff(data, query.request_id)
        return run_overview(query, data, cutoff, cutoff_source, descriptor)
    if not query.session:
        raise ValueError('report 需要明确 --session；先用 sessions 查看候选')
    if query.operation == 'requests':
        return {'kind': 'listing',
                'payload': [r for r in data.get('requests', []) if r['session'] == query.session and r.get('eligible', True)]}
    if query.operation == 'turns':
        if query.session not in data['sessions']:
            raise ValueError('会话不存在')
        return {'kind': 'listing', 'payload': list(data['sessions'][query.session]['turns'].values())}
    if query.request_id:
        cutoff, cutoff_source = resolve_request_cutoff(data, query.session, query.request_id)
    result = report(data, query.session, cutoff, main_only=bool(query.main_only), turns=query.turns, since=query.since,
                    cutoff_source=cutoff_source,
                    localization=localization_of(query.session, query.use_current, saved, harness, cutoff, cutoff_source))
    result['input'] = descriptor
    result['scope']['label'] = query.label
    if query.detail:
        result['details'] = [dict(dimension=query.detail, name=row['label'], metrics=row['metrics'],
                                  cache_hit_rate=row['cache_hit_rate'], call_count=row['call_count'],
                                  known_call_count=row['known_call_count'])
                             for row in result['views'][query.detail]['rows']]
    exit_code = 3 if result['status'] == 'unstatisticable' else 0 if result['status'] == 'confirmed_zero' else 2
    return {'kind': 'report', 'report': result, 'exit': exit_code}
