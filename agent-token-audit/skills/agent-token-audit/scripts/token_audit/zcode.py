"""ZCode rollout/log adapter and read-only existing telemetry database reader."""
import datetime as dt
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from .codex import discover
from .core import cell, deduplicate, normalize, source_lines

MAPPING = {'input': 'inputTokens', 'output': 'outputTokens', 'cache_read': 'cacheReadTokens',
           'cache_write': 'cacheWriteTokens', 'reasoning': 'reasoningTokens'}
COMPLETIONS = ('model.sdk.stream.completed', 'model.sdk.generate.completed')


def metrics(usage, provider):
    usage = dict(usage) if isinstance(usage, dict) else {}
    if 'totalTokens' in usage:
        usage['total_tokens'] = usage['totalTokens']
    result = normalize(usage, MAPPING, True)
    if provider not in ('builtin:bigmodel-coding-plan', 'builtin:bigmodel-start-plan'):
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
    if query == 'subagent':
        return 'child'
    return 'internal' if query in ('compact', 'session_title', 'web_fetch_processing', 'web_search_tool') else 'unknown'


def read(roots):
    paths = discover(roots)
    sessions, records, issues, counts, events = {}, [], [], {}, []
    for path, line, obj, error in source_lines(paths):
        loc = {'path': path, 'line': line}
        if error:
            issues.append({'reason': error, 'source': loc}); continue
        sid = obj.get('sessionId')
        if not isinstance(sid, str):
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
        if not rid or not isinstance(attempt, int):
            continue
        key = f'zcode:{sid}:{rid}:{attempt}'
        if event not in COMPLETIONS + ('model.sdk.stream.failed', 'model.request.failed') and event is not None:
            continue
        at = obj.get('completedAt') or obj.get('timestamp')
        base = {'key': key, 'call_id': f'{rid}:{attempt}', 'session': sid, 'agent': sid, 'turn': obj.get('turnId'),
                'root_turn': None, 'time': at, 'start': obj.get('startedAt'), 'sources': [loc],
                'duration_ms': obj.get('durationMs'), 'group': classify(ctx.get('querySource')), 'call_count': 1}
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
            records.append(dict(value, model='模型未知', metrics=metrics({}, 'builtin:bigmodel-coding-plan')))
    return {'harness': 'zcode', 'sessions': sessions, 'records': records, 'issues': issues,
            'source_files': [str(p) for p in paths], 'events': events}


def iso_ms(value):
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).isoformat() if value is not None else None


def read_database(path):
    """Read a disposable consistent snapshot; source DB/WAL records remain read-only."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError('ZCode 遥测数据库不存在')
    paths = [source, Path(str(source) + '-wal')]
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
        db = sqlite3.connect(str(target))
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            sessions, requests = {}, []
            for row in db.execute('SELECT id,version,parent_id,time_created,task_type FROM session'):
                sid = row['id']
                sessions[sid] = dict(session(sid, iso_ms(row['time_created'])), version=row['version'],
                                     parent=row['parent_id'] if row['task_type'] == 'subagent_child' else None,
                                     forked_from=row['parent_id'] if row['task_type'] != 'subagent_child' else None,
                                     paths=[str(source)])
            records, issues = [], []
            fields = 'id,logical_request_id,attempt_index,session_id,turn_id,query_source,provider_id,model_id,status,started_at,completed_at,duration_ms,retry_count,raw_usage_json'
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
                                'group': classify(row['query_source']), 'model': row['model_id'],
                                'start': iso_ms(row['started_at']), 'time': iso_ms(row['completed_at']),
                                'duration_ms': row['duration_ms'], 'sources': [loc],
                                'metrics': metrics(usage, row['provider_id']),
                                'call_count': 1 if usage and not row['retry_count'] else None})
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
    relation_logs = source.parent.parent / 'log' if source.parent.name == 'db' else source.parent / 'log'
    log_data = read([relation_logs]) if relation_logs.is_dir() else {'events': [], 'source_files': []}
    for event in log_data['events']:
        apply_turn_event(sessions, event)
    return {'harness': 'zcode', 'sessions': sessions, 'records': records, 'issues': issues,
            'source_files': [str(source)] + [str(p) for p in (paths[1],Path(str(source)+'-shm')) if p.exists()] + log_data['source_files'], 'events': log_data['events'],
            'ledger': 'model_usage；不叠加身份无法对应的 rollout 或消息副本', 'requests':requests}
