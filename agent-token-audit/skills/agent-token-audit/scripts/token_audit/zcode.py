"""ZCode rollout/log adapter and read-only existing telemetry database reader."""
import contextlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from .codex import discover
from .core import aggregate, capture, captured_lines, cell, deduplicate, iso_ms, normalize

MAPPING = {'input': 'inputTokens', 'output': 'outputTokens', 'cache_read': 'cacheReadTokens',
           'cache_write': 'cacheWriteTokens', 'reasoning': 'reasoningTokens'}
COMPLETIONS = ('model.sdk.stream.completed', 'model.sdk.generate.completed')
# Usage is digested by one telemetry writer; provider names only select the billing plan of the
# same BigModel API. Field semantics verified on every row of real sources: all rows with usage
# satisfy input+output==totalTokens and cacheReadTokens<=inputTokens (2026-10-01, 5,211+ rows).
VERIFIED_PROVIDERS = ('builtin:bigmodel-coding-plan', 'builtin:bigmodel-start-plan',
                      'account:bigmodel-individual-coding-plan', 'account:bigmodel-start-plan')


def metrics(usage, provider):
    usage = dict(usage) if isinstance(usage, dict) else {}
    if 'totalTokens' in usage:
        usage['total_tokens'] = usage['totalTokens']
    result = normalize(usage, MAPPING, True)
    if provider not in VERIFIED_PROVIDERS:
        # No inference from arithmetical equality alone for unverified providers.
        for name in result:
            result[name] = cell(result[name]['value'], 'unknown', '供应商字段包含关系尚未验证', result[name]['field'])
    return result


def session(sid, at=None):
    return {'id': sid, 'harness': 'zcode', 'start': at, 'version': None, 'paths': [], 'turns': {}}


def turn_candidate(item, turn_id, source):
    """Merge evidence for one stable turn ID without deriving missing lifecycle facts."""
    candidate = item['turns'].setdefault(turn_id, {
        'id': turn_id, 'start': None, 'end': None, 'status': 'unknown', 'identity_sources': []})
    sources = candidate.setdefault('identity_sources', [])
    if source not in sources:
        sources.append(source)
    return candidate


def apply_turn_event(sessions, event):
    item = sessions.get(event.get('session'))
    turn_id = event.get('turn')
    if not item or not turn_id:
        return
    name = event.get('event')
    candidate = turn_candidate(item, turn_id, name)
    if name == 'turn.started':
        if candidate['start'] is None:
            candidate['start'] = event.get('time')
            candidate['start_source'] = 'turn.started'
        if candidate['status'] == 'unknown':
            candidate['status'] = 'running'
            candidate['status_source'] = 'turn.started'
    elif name in ('turn.completed', 'turn.failed'):
        if candidate['end'] is None:
            candidate['end'] = event.get('time')
            candidate['end_source'] = name
        if candidate['status'] in ('unknown', 'running'):
            candidate['status'] = 'completed' if name == 'turn.completed' else 'error'
            candidate['status_source'] = name


def classify(query):
    if query == 'main_turn':
        return 'main'
    if query in ('subagent', 'workflow_child'):
        return 'child'
    return 'internal' if query in ('compact', 'session_title', 'web_fetch_processing', 'web_search_tool') else 'unknown'


TOOL_EVENTS = ('tool.call.started', 'tool.call.completed', 'tool.call.failed')


def read(roots, guard=None):
    return read_captured(capture(discover(roots, guard)))


def read_captured(captured):
    """Parse one guarded capture() snapshot; the plain path and the parse cache share it."""
    sessions, records, issues, counts, events = {}, [], [], {}, []
    tool_by_key = {}
    for path, line, obj, error in captured_lines(captured):
        loc = {'path': path, 'line': line}
        if error:
            issues.append({'reason': error, 'source': loc}); continue
        sid = obj.get('sessionId')
        if not isinstance(sid, str):
            if obj.get('event') in TOOL_EVENTS:
                # No trace/time-based attribution for tool events without a session identity.
                issues.append({'reason': '工具事件无会话身份，不按 trace 或时间猜归属；未纳入', 'source': loc})
            continue
        item = sessions.setdefault(sid, session(sid, obj.get('startedAt') or obj.get('timestamp')))
        if path not in item['paths']:
            item['paths'].append(path)
        event = obj.get('event')
        ctx = obj.get('context', {}) if event else obj
        if not isinstance(ctx, dict):
            continue
        identity_values = [obj.get('turnId')] + [ctx.get(k) for k in ('requestId', 'agentId', 'parentSessionId', 'parentToolCallId', 'querySource')]
        if any(v is not None and not isinstance(v, str) for v in identity_values):
            issues.append({'reason': '未知身份字段格式；该记录未纳入', 'source': loc, 'session': sid})
            continue
        # Keep only association metadata, never message/context bodies.
        if event:
            events.append({'event': event, 'session': sid, 'turn': obj.get('turnId'),
                           'time': obj.get('timestamp'), 'source': loc,
                           **{k: ctx[k] for k in ('agentId','parentSessionId','parentToolCallId','turnNumber','totalTokens') if k in ctx}})
            apply_turn_event(sessions, events[-1])
            turn = obj.get('turnId')
            if turn and ctx.get('turnNumber') is not None:
                turn_candidate(item, turn, event)['display_number'] = ctx.get('turnNumber')
        rid, attempt = ctx.get('requestId'), ctx.get('attempt')
        if event in TOOL_EVENTS:
            # Stable identity = full session + real tool_call_id; started copies merge with
            # the completion copy into ONE event. Command arguments and output are never read.
            cid = obj.get('toolCallId')
            if not isinstance(cid, str) or not cid:
                issues.append({'reason': '工具事件缺少真实 tool_call_id；未纳入', 'source': loc, 'session': sid})
                continue
            key = 'zcode-tool:' + sid + ':' + cid
            existing = tool_by_key.get(key)
            if existing is None:
                existing = {'key': key, 'call_id': cid, 'session': sid, 'turn': obj.get('turnId'),
                            'root_turn': None,
                            'category': ctx.get('toolName') if isinstance(ctx.get('toolName'), str) and ctx.get('toolName') else '工具类别未知',
                            'group': classify(ctx.get('querySource')),
                            'status': 'running', 'completed_at': None, 'sources': [loc],
                            'duration_ns': None, 'duration_precision': 'ms', 'zero_unconfirmed': False,
                            'exec_start': None, 'exec_end': None, 'dispatch_start': None, 'dispatch_end': None,
                            'conflict': None}
                tool_by_key[key] = existing
            else:
                if loc not in existing['sources']:
                    existing['sources'].append(loc)
            if event == 'tool.call.started':
                # The executor's own start event is the actual execution start; copies merge.
                if existing['exec_start'] is None:
                    existing['exec_start'] = obj.get('timestamp')
                elif existing['exec_start'] != obj.get('timestamp'):
                    existing['conflict'] = '同一工具身份的多个开始事件时间冲突'
                continue
            # Completion/failure copies must agree on time, duration and status to count once.
            finished = 'completed' if event == 'tool.call.completed' else 'failed'
            raw = obj.get('durationMs')
            if raw is not None and (type(raw) is not int or raw < 0):
                existing['conflict'] = '原生 durationMs 为负数、布尔值或非整数，不能作为有效耗时'
                raw = None
            if existing['completed_at'] is None:
                existing['completed_at'] = obj.get('timestamp')
                existing['exec_end'] = obj.get('timestamp')
                existing['status'] = finished
                existing['duration_ns'] = raw * 1000000 if raw is not None else None
            elif (existing['completed_at'] != obj.get('timestamp') or existing['status'] != finished
                  or (raw is not None and existing['duration_ns'] is not None and existing['duration_ns'] != raw * 1000000)):
                existing['conflict'] = '同一工具身份的完成副本在时间、状态或耗时上冲突，不能只计一次'
            continue
        if not rid or not isinstance(attempt, int):
            continue
        key = f'zcode:{sid}:{rid}:{attempt}'
        if event not in COMPLETIONS + ('model.sdk.stream.failed', 'model.request.failed') and event is not None:
            continue
        at = obj.get('completedAt') or obj.get('timestamp')
        if event in ('model.sdk.stream.failed', 'model.request.failed'):
            read_status = 'failed'
        elif event in COMPLETIONS:
            read_status = 'completed'
        else:
            read_status = 'unknown'
        base = {'key': key, 'call_id': f'{rid}:{attempt}', 'session': sid, 'agent': sid, 'turn': obj.get('turnId'),
                'root_turn': None, 'time': at, 'start': obj.get('startedAt'), 'sources': [loc],
                'duration_ms': obj.get('durationMs'), 'group': classify(ctx.get('querySource')), 'call_count': 1,
                'granularity': 'model_call', 'time_kind': 'completion_time', 'source_status': read_status}
        if ctx.get('querySource') == 'compact':
            base['internal_kind'] = 'compaction'
        elif ctx.get('querySource') == 'session_title':
            base['internal_kind'] = 'session_aux'
        elif ctx.get('querySource') == 'workflow_child':
            base['origin_kind'] = 'workflow_child'
        if ctx.get('querySource') == 'session_title':
            base['turn'] = None
        if base['turn']:
            turn_candidate(item, base['turn'], 'rollout_usage')
        counts.setdefault(key, dict(base))
        response = obj.get('response', {}) if not event else ctx
        usage = response.get('usage') if isinstance(response, dict) else None
        model = obj.get('model', {}) if not event else ctx
        if not isinstance(model, dict):
            model = {}
        provider = model.get('providerId')
        model_id = model.get('modelId')
        if model_id is not None and not isinstance(model_id, str):
            issues.append({'reason': '未知模型字段格式；模型归为未知', 'source': loc, 'session': sid})
            model_id = None
        base['model'] = model_id or '模型未知'
        base['provider'] = provider if isinstance(provider, str) else None
        if isinstance(usage, dict) and any(isinstance(v, int) and not isinstance(v, bool) for v in usage.values()):
            base['metrics'] = metrics(usage, provider)
            if obj.get('usage') is not None and obj['usage'] != usage:
                base['metrics'] = {k: cell(state='conflict', reason='顶层与 response.usage 冲突') for k in base['metrics']}
            records.append(base)
        elif not event and isinstance(obj.get('usage'), dict):
            base['metrics'] = metrics(obj['usage'], provider)
            records.append(base)
    records = deduplicate(records, issues)
    keys = {r['key'] for r in records}
    for key, value in counts.items():
        if key not in keys:
            # Count-only attempts carry identity but no usage evidence: granularity
            # stays unknown rather than inferred from call_count.
            records.append(dict(value, model='模型未知', granularity='unknown',
                                metrics=metrics({}, 'builtin:bigmodel-coding-plan')))
    return {'harness': 'zcode', 'sessions': sessions, 'records': records, 'issues': issues,
            'source_files': [item[0] for item in captured], 'events': events,
            'tool_events': list(tool_by_key.values())}


@contextlib.contextmanager
def database_snapshot(path, guard=None):
    """Guard-check the source, then yield a disposable consistent snapshot.

    Yields ``(source, target)`` where target is the copied/BACKUP'd sqlite file
    inside a temp directory this context manager owns. Source DB/WAL records
    remain read-only throughout; the adjacent companion files are discovered,
    guarded and captured separately by the caller (see companion_captures).
    """
    source = Path(path).expanduser().resolve()
    if guard:
        guard(source)
    if not source.is_file():
        raise ValueError('ZCode 遥测数据库不存在')
    paths = [source, Path(str(source) + '-wal')]
    if guard:
        for sidecar in (paths[1], Path(str(source) + '-shm')):
            if sidecar.exists():
                guard(sidecar)
    def stamps():
        return [(p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in paths]
    with tempfile.TemporaryDirectory(prefix='token-audit-snapshot-') as tmp:
        target = Path(tmp) / 'db.sqlite'
        if paths[1].exists() and Path(str(source) + '-shm').exists():
            # Use SQLite's WAL read transaction when the live writer already owns
            # the shared-memory files. mode=ro never writes DB/WAL record contents.
            reader = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)
            snapshot = sqlite3.connect(target)
            try:
                reader.execute('PRAGMA query_only=ON')
                reader.execute('BEGIN')
                reader.execute('SELECT count(*) FROM sqlite_master').fetchone()
                reader.backup(snapshot, pages=1024)
            except sqlite3.Error as exc:
                raise ValueError('无法取得 ZCode 只读事务快照：' + type(exc).__name__) from exc
            finally:
                snapshot.close()
                reader.close()
        else:
            # A closed WAL database can lack -shm. Work on a copy rather than
            # letting SQLite create any missing sidecar in the source directory.
            for _ in range(3):
                before = stamps()
                for old, dest in zip(paths, (target, Path(str(target) + '-wal'))):
                    if old.exists():
                        shutil.copyfile(old, dest)
                    elif dest.exists():
                        dest.unlink()
                if stamps() == before:
                    break
            else:
                raise ValueError('源数据库持续变化，未取得一致读取快照，请稍后重试')
        yield source, target


def discover_companions(source, guard=None):
    """Guard-checked discovery of EVERY adjacent file the database parser consumes.

    The relation-log set is recursive (the JSONL reader walks subdirectories) and
    the rollout set is the parser's top-level model-io entries; both are resolved
    and source-guarded here, before any content read, on hit and miss paths alike.
    A rollout entry keeps its own filename as the session association — the entry
    name, not a link target's name, is the identity the parser and the digest key
    on — while the content is read from the resolved real path only.
    """
    base = source.parent.parent if source.parent.name == 'db' else source.parent
    logs, rollouts = base / 'log', base / 'rollout'
    log_paths = sorted(entry.resolve() for entry in logs.rglob('*.jsonl')) if logs.is_dir() else []
    rollout_entries = sorted(rollouts.glob('model-io-*.jsonl')) if rollouts.is_dir() else []
    rollout_paths = [(entry, entry.resolve()) for entry in rollout_entries]
    if guard:
        for real in log_paths + [real for _, real in rollout_paths]:
            guard(real)
    return log_paths, rollout_paths


def companion_captures(source, guard=None):
    """One finite capture of the full companion set; digest and parse share these bytes.

    Rollout captures are labeled with the entry filename (the session association
    and the displayed supplement path); the bytes still come one-per-file from the
    resolved, guarded real path, so a root-internal link or rename can never
    re-associate a supplement or read through the entry itself."""
    log_paths, rollout_paths = discover_companions(source, guard)
    rollout_capture = [(str(entry), content, error)
                       for entry, real in rollout_paths
                       for _, content, error in capture([real])]
    return capture(log_paths), rollout_capture


def read_database(path, guard=None):
    """Read a disposable consistent snapshot; source DB/WAL records remain read-only."""
    with database_snapshot(path, guard) as (source, target):
        log_capture, rollout_capture = companion_captures(source, guard)
        return parse_database(source, target, log_capture, rollout_capture)


def parse_database(source, target, log_capture=None, rollout_capture=None):
    """Parse one already-copied consistent snapshot (see database_snapshot) plus the
    captured companion bytes; it performs no further live source reads itself."""
    db = sqlite3.connect(str(target))
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        sessions, requests = {}, []
        for row in db.execute('SELECT id,version,parent_id,time_created,task_type FROM session'):
            sid = row['id']
            # task_type records the relation kind: child types are descendants, not forks.
            child = row['task_type'] in ('subagent_child', 'workflow_child')
            sessions[sid] = dict(session(sid, iso_ms(row['time_created'])), version=row['version'],
                                 parent=row['parent_id'] if child else None,
                                 forked_from=row['parent_id'] if row['parent_id'] and not child else None,
                                 paths=[str(source)])
        records, issues = [], []
        # First-token evidence columns exist only on newer writers; the column check is
        # the verified "source does not provide" conclusion for older schemas.
        usage_columns = {row['name'] for row in db.execute('PRAGMA table_info(model_usage)')}
        optional = [name for name in ('first_token_at', 'time_to_first_token_ms', 'tool_call_count')
                    if name in usage_columns]
        fields = 'id,logical_request_id,attempt_index,session_id,turn_id,query_source,provider_id,model_id,status,started_at,completed_at,duration_ms,retry_count,raw_usage_json'
        if optional:
            fields += ',' + ','.join(optional)
        for row in db.execute('SELECT ' + fields + ' FROM model_usage ORDER BY started_at,id'):
            loc = {'path': str(source), 'table': 'model_usage', 'id': row['id']}
            try:
                usage = json.loads(row['raw_usage_json']) if row['raw_usage_json'] else {}
            except ValueError:
                usage = {}
            turn_id = None if row['query_source'] == 'session_title' else row['turn_id']
            if turn_id and row['session_id'] in sessions:
                turn_candidate(sessions[row['session_id']], turn_id, 'model_usage')
            records.append({'key': 'zcode-db:' + row['id'], 'call_id': f"{row['logical_request_id']}:{row['attempt_index']}", 'session': row['session_id'],
                            'agent': row['session_id'], 'turn': turn_id, 'root_turn': None,
                            'group': classify(row['query_source']), 'model': row['model_id'], 'provider': row['provider_id'],
                            'start': iso_ms(row['started_at']), 'time': iso_ms(row['completed_at']),
                            'duration_ms': row['duration_ms'], 'sources': [loc],
                            'first_token_at': iso_ms(row['first_token_at']) if 'first_token_at' in optional else None,
                            'native_ttft_ms': row['time_to_first_token_ms'] if 'time_to_first_token_ms' in optional else None,
                            'tool_call_count': row['tool_call_count'] if 'tool_call_count' in optional else None,
                            'retry_count': row['retry_count'],
                            'granularity': 'logical_request', 'time_kind': 'completion_time',
                            'source_status': row['status'] or 'unknown',
                            'metrics': metrics(usage, row['provider_id']),
                            'call_count': 1 if usage and not row['retry_count'] else None,
                            **({'internal_kind': 'compaction'} if row['query_source'] == 'compact' else
                               {'internal_kind': 'session_aux'} if row['query_source'] == 'session_title' else
                               {'origin_kind': 'workflow_child'} if row['query_source'] == 'workflow_child' else {})})
            if row['retry_count']:
                issues.append({'reason': '数据库仅保留逻辑请求结果，重试调用总数及失败用量可能缺失', 'source': loc,
                               'session': row['session_id'], 'turn': row['turn_id']})
        for row in db.execute('SELECT session_id,turn_id,started_at,completed_at,status,model_request_count FROM turn_usage'):
            if row['session_id'] in sessions:
                candidate = turn_candidate(sessions[row['session_id']], row['turn_id'], 'turn_usage')
                candidate['status'] = row['status']
                candidate['status_source'] = 'turn_usage'
                candidate['model_request_count'] = row['model_request_count']
                if row['started_at'] is not None:
                    candidate['start'] = iso_ms(row['started_at'])
                    candidate['start_source'] = 'turn_usage'
                if row['completed_at'] is not None:
                    candidate['end'] = iso_ms(row['completed_at'])
                    candidate['end_source'] = 'turn_usage'
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tool_events = []
        # tool_usage carries session/turn, tool_call_id, status, a native duration and the
        # dispatch-to-completion times. The writer may default a missing duration to 0, so
        # a bare zero stays unconfirmed until an independent completion log verifies it.
        tool_required = {'id','session_id','turn_id','tool_call_id','tool_name','status','started_at','completed_at','duration_ms'}
        tool_table_ok = False
        if 'tool_usage' in tables:
            tool_columns = {row['name'] for row in db.execute('PRAGMA table_info(tool_usage)')}
            tool_table_ok = tool_required <= tool_columns
        if tool_table_ok:
            seen_tool_keys = {}
            for row in db.execute('SELECT id,session_id,turn_id,tool_call_id,tool_name,status,started_at,completed_at,duration_ms FROM tool_usage'):
                loc = {'path': str(source), 'table': 'tool_usage', 'id': row['id']}
                sid, cid = row['session_id'], row['tool_call_id']
                if not isinstance(sid, str) or not isinstance(cid, str) or not cid:
                    issues.append({'reason': '数据库工具行缺少完整会话/tool_call_id；未纳入', 'source': loc})
                    continue
                key = 'zcode-db-tool:' + sid + ':' + cid
                if key in seen_tool_keys:
                    seen_tool_keys[key]['conflict'] = '数据库同一会话内 tool_call_id 重复，无法唯一合并'
                    continue
                raw = row['duration_ms']
                duration_ns, zero_unconfirmed, conflict = None, False, None
                if raw is not None:
                    if type(raw) is not int or raw < 0:
                        conflict = '数据库原生 duration_ms 为负数、布尔值或非整数，不能作为有效耗时'
                    elif raw == 0:
                        zero_unconfirmed = True
                    else:
                        duration_ns = raw * 1000000
                status = {'completed': 'completed', 'error': 'failed'}.get(
                    row['status'], row['status'] if isinstance(row['status'], str) else 'unknown')
                seen_tool_keys[key] = {'key': key, 'call_id': cid, 'session': sid, 'turn': row['turn_id'],
                    'root_turn': None,
                    'category': row['tool_name'] if isinstance(row['tool_name'], str) and row['tool_name'] else '工具类别未知',
                    'group': 'unknown',  # tool_usage has no query_source; a merged log event may classify
                    'status': status, 'completed_at': iso_ms(row['completed_at']),
                    'sources': [loc], 'duration_ns': duration_ns, 'duration_precision': 'ms',
                    'zero_unconfirmed': zero_unconfirmed,
                    'exec_start': None, 'exec_end': None,
                    # Dispatch-to-completion span: different semantics from the native
                    # execution duration, saved separately, never judged as a conflict.
                    'dispatch_start': iso_ms(row['started_at']), 'dispatch_end': iso_ms(row['completed_at']),
                    'conflict': conflict}
            tool_events = list(seen_tool_keys.values())
        message_by_id = {}
        if 'message' in tables:
            fields = "id,session_id,coalesce(json_extract(data,'$.time.created'),time_created) AS created, json_extract(data,'$.synthetic') AS synthetic, json_extract(data,'$.visibility') AS visibility, json_extract(data,'$.source') AS message_source"
            for row in db.execute("SELECT " + fields + " FROM message WHERE json_valid(data) AND json_extract(data,'$.role')='user'"):
                synthetic = row['synthetic'] in (1, True, 'true')
                item = {'id': row['id'], 'ids': [row['id']], 'session': row['session_id'], 'turn': None,
                        'time': iso_ms(row['created']), 'time_source': 'user_message_time',
                        'classification': 'synthetic_system' if synthetic else 'unknown',
                        'eligible': not synthetic, 'association': 'unverified',
                        'sources': [{'path': str(source), 'table': 'message', 'id': row['id']}],
                        'synthetic_source': row['message_source'], 'visibility': row['visibility']}
                message_by_id[(row['session_id'], row['id'])] = item
        if 'session_input' in tables:
            columns = {row['name'] for row in db.execute('PRAGMA table_info(session_input)')}
            kind = 'kind' if 'kind' in columns else 'NULL'
            promoted = 'promoted_message_id' if 'promoted_message_id' in columns else 'NULL'
            for row in db.execute(f'SELECT id,session_id,delivery,time_created,{kind} AS kind,{promoted} AS promoted_message_id FROM session_input'):
                input_kind = row['kind']
                eligible = input_kind in (None, 'sendText')
                classification = 'confirmed_user_input' if input_kind == 'sendText' else 'unknown' if input_kind is None else 'non_user_input'
                item = {'id': row['id'], 'ids': [row['id']], 'session': row['session_id'], 'turn': None,
                        'time': iso_ms(row['time_created']), 'delivery': row['delivery'],
                        'time_source': 'input_admission_time', 'classification': classification,
                        'eligible': eligible, 'association': 'unverified',
                        'sources': [{'path': str(source), 'table': 'session_input', 'id': row['id']}]}
                linked = message_by_id.get((row['session_id'], row['promoted_message_id']))
                if linked:
                    item['ids'].append(linked['id'])
                    item['sources'].extend(linked['sources'])
                    item['association'] = 'promoted_message_id'
                    message_by_id.pop((row['session_id'], linked['id']))
                if linked and not eligible:
                    item['rejection_reason'] = '该入队记录已确认不是用户输入，不能作为用户请求截止点'
                elif linked and not linked['eligible']:
                    item['eligible'] = False
                    item['classification'] = 'ambiguous'
                    item['rejection_reason'] = '入队记录关联到已确认的合成消息，不能作为用户请求截止点'
                requests.append(item)
        requests.extend(message_by_id.values())
    except sqlite3.Error as exc:
        raise ValueError('不支持或损坏的 ZCode 遥测数据库结构：' + type(exc).__name__) from exc
    finally:
        db.close()
    log_data = read_captured(log_capture or [])
    for event in log_data['events']:
        apply_turn_event(sessions, event)
    # DB tool rows and adjacent logs merge ONLY on a complete, unique session/tool_call_id
    # match (fills the true execution start and verifies zeros); anything unmatched stays a
    # separately listed supplement and is never counted into tool durations.
    log_tools = {(e['session'], e['call_id']): e for e in log_data.get('tool_events', [])}
    tool_supplements = []
    if tool_table_ok:
        for event in tool_events:
            match = log_tools.pop((event['session'], event['call_id']), None)
            if match is None:
                continue
            event['sources'] += [s for s in match['sources'] if s not in event['sources']]
            event['exec_start'], event['exec_end'] = match['exec_start'], match['exec_end']
            if event['group'] == 'unknown' and match['group'] != 'unknown':
                event['group'] = match['group']
            if match['conflict']:
                event['conflict'] = event['conflict'] or match['conflict']
            log_ns = match['duration_ns']
            if event['conflict'] or log_ns is None:
                continue
            if event['zero_unconfirmed']:
                if log_ns == 0:
                    # An independent completion log with zero duration confirms the zero.
                    event['zero_unconfirmed'] = False
                    event['duration_ns'] = 0
                else:
                    event['conflict'] = '数据库 duration 为 0 与日志原生 durationMs 矛盾（同语义证据冲突）'
            elif event['duration_ns'] is None:
                event['duration_ns'] = log_ns
            elif event['duration_ns'] != log_ns:
                event['conflict'] = '数据库 duration_ms 与日志原生 durationMs 矛盾（同语义证据冲突）'
    supplement_reason = ('相邻日志工具事件与数据库 tool_usage 无完整会话/tool_call_id 唯一匹配；单列，不重复计入工具耗时'
                         if tool_table_ok else
                         '数据库缺少 tool_usage 表或已核查列；相邻日志工具事件无法唯一合并，单列不重复计入工具耗时')
    for leftover in log_tools.values():
        tool_supplements.append({'key': leftover['key'], 'session': leftover['session'],
                                 'reason': supplement_reason, 'source': leftover['sources'][0]})
    alternates = []
    # Filename gives a session-level association only; rollout requestIds live in another
    # identity space than database logical_request_id, so no call-level bridge exists and
    # readable values stay out of the metered subtotal.
    for path_text, blob, read_error in (rollout_capture or []):
        sid = Path(path_text).name[len('model-io-'):-len('.jsonl')]
        if sid not in sessions:
            continue
        rollout_records = [r for r in read_captured([(path_text, blob, read_error)])['records'] if r['session'] == sid]
        alternates.append(dict({'kind': 'rollout', 'path': path_text, 'session': sid,
                                'records': len(rollout_records),
                                'note': '跨源重叠未知，未并入小计；为该会话全量可读值，未按报告范围筛选'}, **aggregate(rollout_records)))
    return {'harness': 'zcode', 'sessions': sessions, 'records': records, 'issues': issues,
            'source_files': [str(source)] + [str(p) for p in (Path(str(source) + '-wal'), Path(str(source) + '-shm')) if p.exists()] + log_data['source_files'], 'events': log_data['events'],
            'alternate_sources': alternates,
            'performance_evidence': {'columns': {name: name in usage_columns
                                                 for name in ('first_token_at', 'time_to_first_token_ms', 'tool_call_count')},
                                     'tool_usage': tool_table_ok},
            'tool_events': tool_events, 'tool_supplements': tool_supplements,
            'ledger': 'model_usage 为计量来源；rollout 无调用级身份桥接，可读值独立展示不并入小计', 'requests':requests}
