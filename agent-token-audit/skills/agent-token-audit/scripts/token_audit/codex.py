"""Codex rollout adapter; payload identity wins over filename or cwd."""
from pathlib import Path
import datetime as dt
import json
from .core import deduplicate, normalize, source_lines

MAPPING = {'input': 'input_tokens', 'output': 'output_tokens', 'cache_read': 'cached_input_tokens',
           'cache_write': 'cache_write_input_tokens', 'reasoning': 'reasoning_output_tokens'}


def discover(roots):
    paths = set()
    for root in roots:
        root = Path(root).expanduser()
        if root.is_file():
            paths.add(root.resolve())
        elif root.is_dir():
            paths.update(p.resolve() for p in root.rglob('*.jsonl'))
    return sorted(paths)


def read(roots):
    paths = discover(roots)
    sessions, records, issues, contexts, requests = {}, [], [], {}, []
    for path, line, obj, error in source_lines(paths):
        loc = {'path': path, 'line': line}
        if error:
            issues.append({'reason': error, 'source': loc})
            continue
        typ = obj.get('type'); payload = obj.get('payload', {})
        if not isinstance(payload, dict):
            continue
        ctx = contexts.setdefault(path, {'session': None, 'turn': None, 'model': None,
                                         'counter': None, 'counter_time': None, 'pending_turns': set(), 'direct': [], 'outputs': []})
        identity_fields = ('id', 'thread_id', 'turn_id', 'root_turn_id', 'response_id', 'forked_from_id')
        if any(payload.get(k) is not None and not isinstance(payload[k], str) for k in identity_fields):
            issues.append({'reason': '未知身份字段格式；该记录未纳入', 'source': loc, 'session': ctx['session']})
            continue
        if typ == 'turn_context' and payload.get('model') is not None and not isinstance(payload['model'], str):
            issues.append({'reason': '未知模型字段格式；模型归为未知', 'source': loc, 'session': ctx['session']})
            payload = dict(payload, model=None)
        if typ == 'session_meta':
            sid = payload.get('id')
            if not isinstance(sid, str):
                issues.append({'reason': '会话身份缺失', 'source': loc})
                continue
            ctx['session'] = sid
            sessions.setdefault(sid, {'id': sid, 'harness': 'codex', 'start': payload.get('timestamp'),
                                     'version': payload.get('cli_version'), 'paths': [], 'turns': {},
                                     'source': payload.get('source'), 'forked_from': payload.get('forked_from_id')})
            source = payload.get('source')
            if isinstance(source, dict):
                spawn = source.get('subagent', {})
                spawn = spawn.get('thread_spawn', {}) if isinstance(spawn, dict) else {}
                if isinstance(spawn, dict) and isinstance(spawn.get('parent_thread_id'), str):
                    sessions[sid]['parent'] = spawn['parent_thread_id']
            if path not in sessions[sid]['paths']:
                sessions[sid]['paths'].append(path)
        elif typ == 'turn_context':
            ctx['turn'] = payload.get('turn_id'); ctx['model'] = payload.get('model')
        elif typ == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
            metadata = payload.get('internal_chat_message_metadata_passthrough', {})
            if isinstance(metadata,str):
                try:
                    metadata=json.loads(metadata)
                except ValueError:
                    metadata={}
            if not isinstance(metadata,dict):
                metadata={}
            if metadata.get('turn_id') is not None and not isinstance(metadata['turn_id'], str):
                metadata = dict(metadata, turn_id=None)
                issues.append({'reason': '请求轮次字段格式未知', 'source': loc, 'session': ctx['session']})
            created=metadata.get('create_time')
            at=dt.datetime.fromtimestamp(created,dt.timezone.utc).isoformat() if isinstance(created,(int,float)) else obj.get('timestamp')
            requests.append({'id':payload.get('id'),'session':ctx['session'],'turn':metadata.get('turn_id') or ctx['turn'],
                             'time':at,'source':loc,'sources':[loc],
                             'time_source':'message_create_time' if isinstance(created,(int,float)) else 'message_log_time'})
        elif typ == 'response_item':
            if payload.get('type') == 'message' and payload.get('role') == 'assistant':
                ctx['outputs'].append(payload.get('id'))
            elif payload.get('type') not in ('message', 'reasoning', 'function_call_output', 'custom_tool_call_output'):
                # Tool calls or unknown model outputs make a message-only association ambiguous.
                ctx['outputs'].append(None)
        elif typ == 'compacted':
            issues.append({'reason': '发生上下文压缩，源未提供可独立关联的压缩 usage', 'source': loc,
                           'session': ctx['session'], 'turn': ctx['turn']})
        elif typ == 'event_msg' and payload.get('type') in ('task_started','task_complete','turn_aborted'):
            sid = ctx['session']; turn = payload.get('turn_id') or ctx['turn']
            if sid not in sessions or not turn:
                continue
            ctx['turn'] = turn
            item = sessions[sid]['turns'].setdefault(turn, {'id': turn, 'start': None, 'end': None, 'status': 'unknown'})
            if payload['type'] == 'task_started':
                item['start'] = item['start'] or obj.get('timestamp')
                item['status'] = 'running'; ctx['pending_turns'].add(turn)
            else:
                item['end'] = obj.get('timestamp'); item['status'] = 'completed' if payload['type'] == 'task_complete' else 'cancelled'
        elif typ == 'token_usage_record':
            sid = payload.get('thread_id') or ctx['session']
            if sid not in sessions:
                issues.append({'reason': '调用会话身份未匹配', 'source': loc}); continue
            usage = payload.get('usage')
            if not isinstance(usage, dict):
                issues.append({'reason': '调用 usage 不可用', 'source': loc}); continue
            rid = payload.get('response_id')
            if not rid:
                issues.append({'reason': '缺少调用身份，不能可靠去重', 'source': loc})
                continue
            records.append({'key': 'codex:' + sid + ':' + str(rid), 'call_id': str(rid), 'session': sid,
                            'turn': payload.get('turn_id') or ctx['turn'],
                            'root_turn': payload.get('root_turn_id'), 'agent': sid,
                            'group': 'main', 'model': ctx['model'] or '模型未知',
                            'time': obj.get('timestamp'), 'sources': [loc],
                            'metrics': normalize(usage, MAPPING, True), 'call_count': 1})
            ctx['direct'].append(usage)
            turn = records[-1]['turn']
            if turn:
                sessions[sid]['turns'].setdefault(turn, {'id': turn, 'start': None, 'end': None, 'status': 'unknown'})
        elif typ == 'event_msg' and payload.get('type') == 'token_count':
            ctx['has_counter'] = True
            info = payload.get('info')
            totals = info.get('total_token_usage') if isinstance(info, dict) else None
            if not isinstance(totals, dict):
                continue
            sid = ctx['session']; prev = ctx['counter']
            valid = lambda x: isinstance(x, int) and not isinstance(x, bool) and x >= 0
            last = info.get('last_token_usage')
            reply = ctx['outputs'][0] if len(ctx['outputs']) == 1 else None
            core_fields = ('input_tokens', 'output_tokens', 'cached_input_tokens')
            unique_last = (isinstance(reply, str) and bool(reply) and isinstance(last, dict)
                           and all(valid(last.get(k)) for k in core_fields)
                           and (prev is None or all(valid(prev.get(k)) and valid(totals.get(k))
                               and totals[k] - prev[k] == last[k] for k in core_fields)))
            if ctx['direct']:
                # The matching notification is an alternative view, never an extra call.
                if prev:
                    for key in ('input_tokens','output_tokens','cached_input_tokens'):
                        if valid(prev.get(key)) and valid(totals.get(key)) and all(valid(u.get(key)) for u in ctx['direct']):
                            delta = totals[key] - prev[key]
                            if delta != sum(u[key] for u in ctx['direct']):
                                issues.append({'reason': '逐调用记录与累计快照不一致；不重复加总', 'source': loc, 'session': sid, 'turn': ctx['turn']})
            elif unique_last and sid in sessions:
                records.append({'key': f'codex-reply:{sid}:{reply}', 'call_id': reply,
                                'session': sid, 'agent': sid, 'turn': ctx['turn'], 'root_turn': None,
                                'group': 'main', 'model': ctx['model'] or '模型未知',
                                'time': obj.get('timestamp'), 'sources': [loc],
                                'metrics': normalize(last, MAPPING, True), 'call_count': 1,
                                'usage_source': 'unique_last_usage'})
                if prev is None and any(valid(totals.get(k)) and totals[k] != last[k] for k in core_fields):
                    issues.append({'reason': '已计入唯一回复的 last usage；更早累计用量缺少基线',
                                   'source': loc, 'session': sid, 'turn': ctx['turn']})
            elif prev and sid in sessions:
                differences = {k: v - prev[k] for k,v in totals.items() if valid(v) and valid(prev.get(k))}
                if any(v < 0 for v in differences.values()):
                    issues.append({'reason': '累计重置或回退；当前区间不可计量', 'source': loc, 'session': sid, 'turn': ctx['turn']})
                elif any(differences.values()):
                    turns = sorted(ctx['pending_turns'] | ({ctx['turn']} if ctx['turn'] else set()))
                    records.append({'key': f'codex-interval:{sid}:{ctx["counter_time"]}:{obj.get("timestamp")}',
                                    'session': sid, 'agent': sid, 'turn': turns[0] if len(turns) == 1 else None,
                                    'interval_turns': turns, 'interval_start': ctx['counter_time'], 'root_turn': None,
                                    'group': 'main', 'model': '模型未知', 'time': obj.get('timestamp'), 'sources': [loc],
                                    'metrics': normalize(differences, MAPPING, True), 'call_count': None})
            elif not ctx['direct'] and any(valid(v) and v for v in totals.values()):
                issues.append({'reason': '首个累计快照缺少零基线；不视为增量', 'source': loc, 'session': sid, 'turn': ctx['turn']})
            ctx['counter'] = totals; ctx['counter_time'] = obj.get('timestamp')
            ctx['pending_turns'] = set(); ctx['direct'] = []; ctx['outputs'] = []
    # Some versions write direct usage after its cumulative notification. Without a
    # shared response identity, do not add both representations of the same turn.
    direct_turns = {(r['session'], r['turn']) for r in records if r['key'].startswith('codex:')}
    kept = []
    for record in records:
        fallback = record.get('usage_source') == 'unique_last_usage' or record.get('interval_start') is not None
        covered_turns = record.get('interval_turns') or [record['turn']]
        if fallback and any((record['session'], t) in direct_turns for t in covered_turns):
            issues.append({'reason': '同轮存在逐调用记录；无法独立关联的累计或 last usage 视图不重复加总',
                           'source': record['sources'][0], 'session': record['session'], 'turn': record['turn']})
        else:
            kept.append(record)
    records = kept
    unique_requests, unkeyed_requests = {}, []
    for request in requests:
        request_id = request['id']
        if not isinstance(request_id, str):
            unkeyed_requests.append(request)
            continue
        key = (request['session'], request_id, request['time'])
        existing = unique_requests.setdefault(key, request)
        if existing is not request:
            for source in request['sources']:
                if source not in existing['sources']:
                    existing['sources'].append(source)
    return {'harness': 'codex', 'sessions': sessions, 'records': deduplicate(records, issues),
            'issues': issues, 'source_files': [str(p) for p in paths], 'requests': list(unique_requests.values()) + unkeyed_requests}
