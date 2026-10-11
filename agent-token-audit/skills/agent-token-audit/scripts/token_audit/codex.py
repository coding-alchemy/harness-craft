"""Codex rollout adapter; payload identity wins over filename or cwd."""
from pathlib import Path
import datetime as dt
import json
from .core import deduplicate, iso_ms, normalize, source_lines, timestamp

MAPPING = {'input': 'input_tokens', 'output': 'output_tokens', 'cache_read': 'cached_input_tokens',
           'cache_write': 'cache_write_input_tokens', 'reasoning': 'reasoning_output_tokens'}


def discover(roots, guard=None):
    """Find candidate files; an optional guard rejects resolved paths outside the allowed set."""
    paths = set()
    for root in roots:
        root = Path(root).expanduser()
        if root.is_file():
            candidate = root.resolve()
            if guard:
                guard(candidate)
            paths.add(candidate)
        elif root.is_dir():
            for entry in root.rglob('*.jsonl'):
                candidate = entry.resolve()
                if guard:
                    guard(candidate)
                paths.add(candidate)
    return sorted(paths)


def read(roots, guard=None):
    paths = discover(roots, guard)
    sessions, records, issues, contexts, requests, compactions = {}, [], [], {}, [], []
    tool_events = []
    for path, line, obj, error in source_lines(paths):
        loc = {'path': path, 'line': line}
        if error:
            issues.append({'reason': error, 'source': loc})
            continue
        typ = obj.get('type'); payload = obj.get('payload', {})
        if not isinstance(payload, dict):
            continue
        ctx = contexts.setdefault(path, {'session': None, 'turn': None, 'model': None, 'provider': None,
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
            # The session-declared source provider identity is kept for pricing; it is
            # never rewritten (e.g. openai_http stays openai_http).
            if isinstance(payload.get('model_provider'), str):
                ctx['provider'] = payload['model_provider']
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
            if isinstance(payload.get('model_provider_id'), str):
                ctx['provider'] = payload['model_provider_id']
        elif typ == 'thread_settings_applied':
            # Explicit applied settings bind provider/model identity to their scope only.
            settings = payload.get('thread_settings', {})
            if isinstance(settings, dict):
                if isinstance(settings.get('model_provider_id'), str):
                    ctx['provider'] = settings['model_provider_id']
                if isinstance(settings.get('model'), str):
                    ctx['model'] = settings['model']
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
            kinds = metadata.get('content_item_kinds')
            if isinstance(kinds, list) and all(isinstance(k, str) for k in kinds):
                # The harness tags each content item; only user.text is a user-originated request.
                classification = 'user_message' if 'user.text' in kinds else 'non_user_input'
            else:
                classification = 'unknown'
            created=metadata.get('create_time')
            at=dt.datetime.fromtimestamp(created,dt.timezone.utc).isoformat() if isinstance(created,(int,float)) else obj.get('timestamp')
            item={'id':payload.get('id'),'session':ctx['session'],'turn':metadata.get('turn_id') or ctx['turn'],
                  'time':at,'source':loc,'sources':[loc],
                  'time_source':'message_create_time' if isinstance(created,(int,float)) else 'message_log_time',
                  'classification':classification,'eligible':classification != 'non_user_input'}
            if not item['eligible']:
                item['rejection_reason'] = '该消息由系统注入（非用户输入），不能作为用户请求截止点'
            requests.append(item)
        elif typ == 'response_item':
            if payload.get('type') == 'message' and payload.get('role') == 'assistant':
                ctx['outputs'].append(payload.get('id'))
            elif payload.get('type') not in ('message', 'reasoning', 'function_call_output', 'custom_tool_call_output'):
                # Tool calls or unknown model outputs make a message-only association ambiguous.
                ctx['outputs'].append(None)
        elif typ == 'compacted':
            # The marker names the compaction call's own response; its usage record (if any)
            # is the metered evidence. latest_token_usage_record is a copy of the same call,
            # never an additional one.
            compactions.append((payload.get('compaction_response_id'), loc, ctx['session']))
        elif typ == 'event_msg' and payload.get('type') == 'item_completed':
            # Only these two item types prove an actual execution with structured identity,
            # status and a native duration; other item types and plain text output are not
            # tool-duration evidence. Command arguments and output bodies are never copied.
            item = payload.get('item')
            if not isinstance(item, dict) or item.get('type') not in ('CommandExecution', 'McpToolCall'):
                continue
            sid = payload.get('thread_id') or ctx['session']
            ident = item.get('id')
            if sid not in sessions:
                issues.append({'reason': '工具事件会话身份未匹配', 'source': loc, 'session': ctx['session']})
                continue
            if not isinstance(ident, str) or not ident:
                issues.append({'reason': '工具事件缺少真实 item 身份；未纳入', 'source': loc, 'session': sid})
                continue
            event = {'key': 'codex-tool:' + sid + ':' + ident, 'call_id': ident, 'session': sid,
                     'turn': payload.get('turn_id') or ctx['turn'], 'root_turn': None,
                     'category': item['type'], 'group': 'main',
                     'status': item.get('status') if isinstance(item.get('status'), str) else 'unknown',
                     'completed_at': obj.get('timestamp'), 'sources': [loc],
                     'duration_ns': None, 'duration_precision': 'ms', 'zero_unconfirmed': False,
                     'exec_start': None, 'exec_end': None, 'dispatch_start': None, 'dispatch_end': None,
                     'conflict': None}
            duration = item.get('duration')
            if duration is not None:
                secs, nanos = duration.get('secs'), duration.get('nanos') if isinstance(duration, dict) else (None, None)
                valid = (isinstance(duration, dict)
                         and all(type(v) is int and v >= 0 for v in (secs, nanos)) and nanos < 1000000000)
                if valid:
                    # secs/nanos convert exactly; never truncated to whole milliseconds.
                    event['duration_ns'] = secs * 1000000000 + nanos
                    event['duration_precision'] = 'ns'
                else:
                    event['conflict'] = '原生 duration 的 secs/nanos 为负数、布尔值或非整数，不能作为有效耗时'
            start, finish = item.get('start'), item.get('end')
            for value in (start, finish):
                if value is not None and (type(value) is not int or value < 0):
                    event['conflict'] = event['conflict'] or '工具起止毫秒时间为负数、布尔值或非整数'
            if type(start) is int and type(finish) is int and start >= 0 and finish >= 0:
                if finish < start:
                    event['conflict'] = event['conflict'] or '工具起止逆序，不能作为有效跨度'
                else:
                    # Execution endpoints in epoch ms; the ms span and the native ns
                    # duration are different granularities, saved separately, no conflict.
                    event['exec_start'], event['exec_end'] = iso_ms(start), iso_ms(finish)
            tool_events.append(event)
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
                if payload['type'] == 'task_complete' and payload.get('duration_ms') is not None:
                    item['native_duration_ms'] = payload.get('duration_ms')
                    item['native_duration_source'] = 'event_msg.task_complete.duration_ms'
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
                            'group': 'main', 'model': ctx['model'] or '模型未知', 'provider': ctx['provider'],
                            'time': obj.get('timestamp'), 'sources': [loc],
                            'granularity': 'model_call', 'time_kind': 'usage_record_time', 'source_status': 'unknown',
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
                                'group': 'main', 'model': ctx['model'] or '模型未知', 'provider': ctx['provider'],
                                'time': obj.get('timestamp'), 'sources': [loc],
                                'granularity': 'reply_usage', 'time_kind': 'reply_usage_time', 'source_status': 'unknown',
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
                                    'group': 'main', 'model': '模型未知', 'provider': None, 'time': obj.get('timestamp'), 'sources': [loc],
                                    'granularity': 'cumulative_interval', 'time_kind': 'count_interval_time',
                                    'source_status': 'unknown',
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
    # A compaction marker reclassifies its referenced call as internal auxiliary; it never adds usage.
    for crid, loc, sid in compactions:
        if not isinstance(crid, str):
            issues.append({'reason': '发生上下文压缩，未提供可关联的压缩调用身份；用量可能已计或缺失',
                           'source': loc, 'session': sid})
            continue
        matched = [r for r in records if r.get('call_id') == crid]
        if matched:
            for record in matched:
                record['group'] = 'internal'
                record['internal_kind'] = 'compaction'
        else:
            issues.append({'reason': '发生上下文压缩，未找到可关联的压缩调用 usage；可能已计或缺失',
                           'source': loc, 'session': sid})
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
    # The same session can span several rollout files (resume copies): merge repeated tool
    # identities once; conflicting copies stay in conflict instead of double counting.
    unique_tools = {}
    for event in tool_events:
        old = unique_tools.get(event['key'])
        if old is None:
            unique_tools[event['key']] = event
            continue
        old['sources'] += [s for s in event['sources'] if s not in old['sources']]
        for field in ('status', 'completed_at', 'exec_start', 'exec_end'):
            new = event[field]
            if new is None:
                continue
            if old[field] is None:
                old[field] = new
                continue
            if old[field] == new:
                continue
            same = False
            if field != 'status':
                try:
                    same = timestamp(old[field]) == timestamp(new)
                except (ValueError, TypeError):
                    same = False
            if not same:
                old['conflict'] = old['conflict'] or '同一工具身份的来源副本在 ' + field + ' 上冲突'
        if event['duration_ns'] is not None:
            if old['duration_ns'] is None:
                old['duration_ns'] = event['duration_ns']
                old['duration_precision'] = event['duration_precision']
            elif old['duration_ns'] != event['duration_ns']:
                old['conflict'] = old['conflict'] or '同一工具身份的来源副本耗时冲突'
        if event['conflict']:
            old['conflict'] = old['conflict'] or event['conflict']
    return {'harness': 'codex', 'sessions': sessions, 'records': deduplicate(records, issues),
            'issues': issues, 'source_files': [str(p) for p in paths], 'requests': list(unique_requests.values()) + unkeyed_requests,
            'tool_events': list(unique_tools.values())}
