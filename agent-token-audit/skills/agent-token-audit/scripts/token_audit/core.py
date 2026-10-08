"""Shared metric, provenance, deduplication and presentation contracts."""
import datetime as dt
import json
import os
from pathlib import Path
import zoneinfo

METRICS = ('input', 'output', 'cache_read', 'cache_write', 'reasoning', 'non_cache_read', 'total')
GROUPS = {'main': '主代理常规调用', 'child': '子代理常规调用', 'internal': '内部辅助调用', 'unknown': '未分类'}
STATES = {'partial':'已记录小计','count_only':'仅调用计数','tool_only':'仅工具报告','confirmed_zero':'确认零用量','unstatisticable':'不可统计',
          'active':'截至当前记录，未结束','ended':'已结束','unknown':'未知'}
GRANULARITIES = ('model_call', 'reply_usage', 'cumulative_interval', 'logical_request', 'unknown')
TIME_KINDS = ('usage_record_time', 'reply_usage_time', 'count_interval_time', 'completion_time', 'unknown')
GRANULARITY_LABELS = {'model_call': '逐调用用量', 'reply_usage': '唯一回复关联用量',
                      'cumulative_interval': '累计差分区间', 'logical_request': '逻辑请求结果', 'unknown': '用量记录，粒度未知'}
TIME_KIND_LABELS = {'usage_record_time': 'usage 记录时间（无调用起点）', 'reply_usage_time': '回复关联 usage 记录时间',
                    'count_interval_time': '累计计数区间终点', 'completion_time': '完成时间', 'unknown': '时间语义未知'}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('时间必须是带时区的 ISO 8601 字符串')
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return result.astimezone(dt.timezone.utc)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def cell(value=None, state='unknown', reason='源未报告', field=None):
    return {'value': value, 'state': state, 'reason': reason, 'field': field}


def number(usage, key, zero_uncertain=False):
    value = usage.get(key)
    if value is None:
        return cell(field=key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return cell(state='conflict', reason='非非负整数或已脱敏', field=key)
    if value == 0 and zero_uncertain:
        return cell(0, 'unknown', '源报告 0，语义未确认', key)
    return cell(value, 'reported', '', key)


def known(metric):
    return metric['state'] in ('reported', 'derived') and metric['value'] is not None


def _precision_ms(value):
    """Comparison tolerance implied by a timestamp's own precision: whole-second
    endpoints only support second-level comparison, fractional ones millisecond."""
    clock = value.split('T', 1)[-1]
    clock = clock.split('+')[0].split('-')[0].rstrip('Z')
    return 1 if '.' in clock else 1000


def duration_explanation(record):
    """One record's own duration evidence: a finite non-negative direct field, or the
    record's own trustworthy start/end when no direct field exists. Invalid direct
    fields stay in conflict and are never laundered into valid values by endpoints;
    usage times, turn starts or read times are never borrowed as call endpoints."""
    raw = record.get('duration_ms')
    if raw is None:
        if record.get('interval_start'):
            return {'value': None, 'state': 'unknown', 'reason': '累计区间不推导调用耗时', 'unit': 'ms'}
        start, end = record.get('start'), record.get('time')
        if isinstance(start, str) and isinstance(end, str):
            try:
                span = (timestamp(end) - timestamp(start)).total_seconds() * 1000
                if span < 0:
                    return {'value': None, 'state': 'conflict', 'reason': '该条自身起止逆序，不能作为有效耗时', 'unit': 'ms'}
                return {'value': int(span), 'state': 'known', 'reason': '源未报告直接耗时，由该条自身可信起止推算', 'unit': 'ms'}
            except (ValueError, TypeError, OverflowError):
                pass
        return {'value': None, 'state': 'unknown', 'reason': '源未报告该次调用/请求的直接耗时，且无自身可信起止', 'unit': 'ms'}
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != raw or raw in (float('inf'), float('-inf')) or raw < 0:
        return {'value': None, 'state': 'conflict', 'reason': '源报告的耗时为负数、布尔值或非有限数，不能作为有效耗时', 'unit': 'ms'}
    value = int(raw)
    start, end = record.get('start'), record.get('time')
    if isinstance(start, str) and isinstance(end, str) and not record.get('interval_start'):
        try:
            span = (timestamp(end) - timestamp(start)).total_seconds() * 1000
            if span < 0:
                return {'value': None, 'state': 'conflict', 'reason': '该条自身起止逆序，不能作为有效耗时', 'unit': 'ms'}
            tolerance = max(_precision_ms(start), _precision_ms(end))
            if abs(span - value) > tolerance:
                return {'value': value, 'state': 'conflict',
                        'reason': '直接耗时字段与同条起止在可比精度下矛盾（起止跨度 %.3f ms）' % span, 'unit': 'ms'}
        except (ValueError, TypeError, OverflowError):
            pass
    return {'value': value, 'state': 'known', 'reason': '来源直接报告的该次调用/请求耗时', 'unit': 'ms'}


def classification_evidence(record):
    """Which explicit rule placed this record in its mutually exclusive metering group."""
    loc = record['sources'][0]
    if record.get('internal_kind') == 'compaction':
        return {'rule': 'compacted.compaction_response_id 与该调用 response_id 一致（明确身份关联）',
                'group': record['group'], 'source': loc}
    if record.get('internal_kind') == 'session_aux':
        return {'rule': "query_source='session_title'（来源明确标记的标题/会话辅助）",
                'group': record['group'], 'source': loc}
    if record.get('origin_kind') == 'workflow_child':
        return {'rule': "task_type='workflow_child' 且父子关系明确", 'group': record['group'], 'source': loc}
    if record['group'] == 'child':
        return {'rule': '父子会话关系绑定：后代常规调用归发起轮次', 'group': record['group'], 'source': loc}
    if record['group'] == 'internal':
        return {'rule': '来源明确内部 query_source 分类', 'group': record['group'], 'source': loc}
    return {'rule': '主代理常规调用（无内部标记）', 'group': record['group'], 'source': loc}


def ownership_evidence(record):
    """Original vs attributed execution identity and the relation basis, both locatable."""
    owner_session = record.get('owner_session', record['session'])
    owner_turn = record.get('owner_turn')
    evidence = {'owner_session': owner_session, 'owner_turn': owner_turn, 'sources': record['sources']}
    if owner_session == record['session']:
        evidence['rule'] = '原始会话执行；归属即原始身份'
    else:
        evidence['rule'] = '父子/发起轮次关系绑定；原始执行与归属贡献分开列示，不相加'
    return evidence


def record_status(record):
    """Source-read status stays separate from what is provable before the cutoff."""
    read = record.get('source_status') or 'unknown'
    return {'read': read, 'at_cutoff': 'recorded_before_cutoff',
            'reason': '记录时间早于报告截止点；usage 存在即该次调用在记录时间前已完成'}


CONFLICT_FIELD_REASONS = {'granularity': '同身份来源的粒度字段冲突，无法协调',
                          'time_kind': '同身份来源的时间语义冲突，无法协调',
                          'source_status': '同身份来源的状态冲突，无法协调',
                          'duration_ms': '同身份来源的耗时字段冲突，无法协调',
                          'start': '同身份来源的起点字段冲突，无法协调'}


def build_record_explanation(record):
    conflicts = record.pop('_field_conflicts', None) or set()
    explanation = {'granularity': record.get('granularity') or 'unknown',
                   'time_kind': record.get('time_kind') or 'unknown',
                   'status': record_status(record),
                   'duration': duration_explanation(record),
                   'classification_evidence': classification_evidence(record),
                   'ownership_evidence': ownership_evidence(record)}
    if conflicts:
        explanation['conflicts'] = sorted(CONFLICT_FIELD_REASONS[f] for f in conflicts if f in CONFLICT_FIELD_REASONS)
        if 'granularity' in conflicts:
            explanation['granularity'] = 'unknown'
        if 'time_kind' in conflicts:
            explanation['time_kind'] = 'unknown'
        if 'source_status' in conflicts:
            explanation['status']['read'] = 'conflict'
            explanation['status']['reason'] = CONFLICT_FIELD_REASONS['source_status']
        if 'duration_ms' in conflicts or 'start' in conflicts:
            explanation['duration'] = {'value': None, 'state': 'conflict',
                                       'reason': CONFLICT_FIELD_REASONS['duration_ms'], 'unit': 'ms'}
    return explanation


def explain_records(records):
    for record in records:
        record['explanation'] = build_record_explanation(record)


TURN_STATUSES = ('running', 'completed', 'cancelled', 'error', 'unknown')
CUTOFF_STATUSES = ('ended_before_cutoff', 'ended_after_cutoff', 'not_confirmed_ended_at_cutoff', 'unknown_at_cutoff')


def _turn_cutoff_status(candidate, end):
    start, finish = candidate.get('start'), candidate.get('end')
    try:
        if finish:
            return 'ended_before_cutoff' if timestamp(finish) < end else 'ended_after_cutoff'
        if start and timestamp(start) < end:
            return 'not_confirmed_ended_at_cutoff'
    except (ValueError, TypeError):
        pass
    return 'unknown_at_cutoff'


def _native_duration(candidate):
    raw = candidate.get('native_duration_ms')
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return {'value': None, 'unit': 'ms', 'source': candidate.get('native_duration_source'),
                'state': 'conflict', 'reason': '原生轮次耗时为负数、布尔值或非整数，不能作为有效耗时'}
    return {'value': raw, 'unit': 'ms', 'source': candidate.get('native_duration_source'),
            'state': 'known', 'reason': '来源事件直接报告的轮次耗时'}


def build_turn_explanations(data, session_id, family, available, chosen_ids, selected, end, start):
    """Timeline rows over ACTUAL session/turn execution; attribution stays a separate view.
    Main-session lifecycle turns enter by explicit choice, metered-record reference, or a
    lifecycle provably intersecting the window; descendant turns enter via their own
    metered records, never by borrowing the main session's originating turn. Filtered
    candidates whose own bounds cannot prove they lie outside the window are returned
    alongside as excluded capability rows (identity + reason, no token subtotals)."""
    rows = []
    members = {}
    intervals = []
    for record in selected:
        if record.get('interval_start'):
            intervals.append(record)
            continue
        actual = (record['session'], record['turn'])
        members.setdefault(actual, []).append(record)
    admitted = set(chosen_ids or [])
    admitted |= {turn for sid, turn in members if sid == session_id and turn}
    excluded = []
    for item in available.values():
        if item['id'] in admitted:
            continue
        if _turn_intersects(item, start, end):
            admitted.add(item['id'])
            continue
        reason = _unproven_turn_reason(item, start, end)
        if reason:
            excluded.append({'reason': reason, 'session': session_id, 'turn': item['id']})
    turn_rows = []
    for turn_id in sorted(admitted):
        candidate = available.get(turn_id)
        if candidate is None:
            continue
        turn_rows.append((session_id, turn_id, candidate))
    covered = {(sid, turn_id) for sid, turn_id, _ in turn_rows}
    for sid, turn in sorted(members, key=lambda k: (k[0], k[1] or '')):
        if (sid, turn) in covered or not turn:
            continue
        candidate = data['sessions'].get(sid, {}).get('turns', {}).get(turn)
        if candidate is None:
            candidate = {'id': turn, 'start': None, 'end': None, 'status': 'unknown'}
        turn_rows.append((sid, turn, candidate))
    for sid, turn_id, candidate in turn_rows:
        group = members.get((sid, turn_id), [])
        span_state, span_reason = _span_state(candidate, start, end)
        rows.append({'kind': 'turn', 'session': sid, 'turn': turn_id,
                     'start': candidate.get('start'), 'end': candidate.get('end'),
                     'start_source': candidate.get('start_source'), 'end_source': candidate.get('end_source'),
                     'status': candidate.get('status') or 'unknown',
                     'cutoff_status': _turn_cutoff_status(candidate, end),
                     'span_state': span_state, 'span_reason': span_reason,
                     'native_duration_ms': _native_duration(candidate),
                     'record_keys': [r['key'] for r in group],
                     **aggregate(group)})
    for record in intervals:
        rows.append({'kind': 'cumulative_interval', 'session': record['session'],
                     'interval_start': record['interval_start'], 'interval_end': record['time'],
                     'interval_turns': record.get('interval_turns') or [],
                     'status': 'unknown', 'cutoff_status': 'ended_before_cutoff',
                     'span_state': 'interval', 'span_reason': '累计计数区间，独立呈现，不复制到各轮',
                     'native_duration_ms': None,
                     'record_keys': [record['key']],
                     **aggregate([record])})
    return rows, excluded


def _turn_intersects(candidate, start, end):
    """A lifecycle turn enters the timeline only when its own bounds prove
    intersection with [start, end); a lone endpoint outside the window cannot
    prove where the turn began or ended, so unprovable candidates stay out."""
    try:
        t_start = timestamp(candidate['start']) if candidate.get('start') else None
        t_end = timestamp(candidate['end']) if candidate.get('end') else None
    except (ValueError, TypeError):
        return False
    if t_start is None and t_end is None:
        return False
    if t_start is not None and t_end is not None:
        return t_start < end and (start is None or t_end > start)
    if t_start is not None:
        # A start inside the window proves overlap; an earlier start cannot.
        return t_start < end and (start is None or t_start >= start)
    # End-only: an end inside (start, end] proves the turn reached the window;
    # an end at/after the cutoff says nothing about where the turn began.
    return t_end <= end and (start is None or t_end > start)


def _unproven_turn_reason(candidate, start, end):
    """Mirror of _turn_intersects for the candidates it filters out: None when the
    candidate's own trustworthy bounds prove it lies outside the window (normal
    filtering); otherwise the capability-limitation reason carried into excluded."""
    try:
        t_start = timestamp(candidate['start']) if candidate.get('start') else None
        t_end = timestamp(candidate['end']) if candidate.get('end') else None
    except (ValueError, TypeError):
        return '轮次起止时间不可信，无法证明与查询范围相交'
    if t_start is None and t_end is None:
        return '轮次缺少可信起止时间，无法证明与查询范围相交'
    if t_start is not None and t_end is not None:
        return None
    if t_start is not None:
        # Only an earlier start without end evidence cannot prove exclusion;
        # a start at/after the cutoff proves the turn began outside the window.
        if start is not None and t_start < start:
            return '轮次仅有早于查询下界的起点记录且无结束证据，无法证明与查询范围相交'
        return None
    # End-only: an end at/before the lower bound proves the turn finished before
    # the window; a later end without start evidence cannot prove exclusion.
    if start is not None and t_end <= start:
        return None
    return '轮次仅有结束记录且无起点证据，无法证明与查询范围相交'


def _span_state(candidate, start, end):
    """Lifecycle vs the query window: keep original bounds, mark out-of-window context."""
    try:
        t_start = timestamp(candidate['start']) if candidate.get('start') else None
        t_end = timestamp(candidate['end']) if candidate.get('end') else None
    except (ValueError, TypeError):
        return 'unknown', '起止时间不可信，无法判断与范围关系'
    if t_start and t_end and t_end < t_start:
        return 'conflict', '起止逆序，不能作为有效跨度'
    before = t_start is not None and start is not None and t_start < start
    after = t_end is not None and t_end > end
    if before and after:
        return 'extends_both', '生命周期跨出筛选范围；显示原始边界（范围外上下文）'
    if before:
        return 'extends_before', '开始早于筛选下界；显示原始起点（范围外上下文）'
    if after:
        return 'extends_after', '结束晚于截止点；显示原始终点（范围外上下文）'
    return 'in_range', '生命周期落在查询范围内'


def build_internal_breakdown(selected):
    """Mutually exclusive metering group 'internal' broken down by evidenced category."""
    labels = {'compaction': '压缩/摘要', 'session_aux': '标题/会话辅助',
              'other_internal': '其他有依据内部工作', 'unknown': '内部类别未知'}
    def category(record):
        if record.get('internal_kind') == 'compaction':
            return 'compaction'
        if record.get('internal_kind') == 'session_aux':
            return 'session_aux'
        if record.get('internal_kind'):
            return 'other_internal'
        return 'unknown'
    groups = {}
    for record in selected:
        if record['group'] != 'internal':
            continue
        groups.setdefault(category(record), []).append(record)
    return [{'category': c, 'label': labels[c], 'basis': '来源明确标记（internal_kind/query_source）' if c != 'unknown' else '来源内部分类，无更细标记',
             'record_keys': [r['key'] for r in groups[c]], **aggregate(groups[c])}
            for c in sorted(groups)]


def build_relation_rows(data, family, session_id):
    """Existing parent/child, origin-turn and fork identities with their evidence; no new joins."""
    rows = []
    for sid in sorted(family):
        item = data['sessions'].get(sid)
        if not item:
            continue
        sources = [{'path': p} for p in item.get('paths', [])]
        if item.get('parent'):
            rows.append({'kind': 'parent_child', 'session': sid, 'parent': item['parent'],
                         'origin_turn': item.get('origin_turn'),
                         'rule': '父子会话关系（来源明确 parent 关系；发起轮次经 subagent 事件或 turn_usage 证据）',
                         'sources': sources})
        elif item.get('forked_from'):
            rows.append({'kind': 'fork', 'session': sid, 'forked_from': item['forked_from'],
                         'rule': '分叉关系（来源 forked_from 字段）',
                         'sources': sources})
    for record in data.get('inherited', []):
        if record['session'] in family:
            rows.append({'kind': 'inherited_copy', 'session': record['session'], 'call_id': record['call_id'],
                         'rule': '分叉继承副本：原始调用身份已在祖先会话计量，不贡献新增量',
                         'sources': record['sources']})
    return rows


EXCLUDED_REASONS = ('调用跨截止点，整次调用未纳入且不能按比例切分',
                    '调用缺少可信时间，无法判断截止点',
                    '累计区间跨时间下界，无法精确切分',
                    '累计区间跨过未选轮次，无法精确归属',
                    '记录轮次无法归属；未摊入任务')


def build_excluded_rows(issues):
    """Necessary unmetered identities/times with reason; no token subtotals, no log copying."""
    rows = []
    for issue in issues:
        if issue.get('reason') not in EXCLUDED_REASONS:
            continue
        rows.append({'reason': issue['reason'], 'source': issue.get('source'),
                     'session': issue.get('session'), 'turn': issue.get('turn')})
    return rows


def _wall_entry(turns, end, basis):
    begins = [t['start'] for t in turns if t.get('start')]
    ends = [t['end'] for t in turns if t.get('end')]
    wall = {'value': None, 'state': 'unknown', 'unit': 's', 'basis': basis}
    if not turns:
        wall['reason'] = '范围内没有轮次生命周期证据'
        return wall
    else:
        missing = [t['id'] for t in turns if not t.get('start') or not t.get('end')]
        reversed_ = []
        for t in turns:
            try:
                if t.get('start') and t.get('end') and timestamp(t['end']) < timestamp(t['start']):
                    reversed_.append(t['id'])
            except (ValueError, TypeError):
                pass
        late = []
        for t in turns:
            try:
                if t.get('end') and timestamp(t['end']) >= end:
                    late.append(t['id'])
            except (ValueError, TypeError):
                pass
        if reversed_:
            wall['state'] = 'conflict'
            wall['reason'] = '轮次起止逆序：' + '、'.join(reversed_)
        elif missing:
            wall['reason'] = '缺起止证据的轮次：' + '、'.join(missing)
        elif late:
            wall['reason'] = '截止点前未确认结束的轮次：' + '、'.join(late)
        else:
            wall['value'] = (max(map(timestamp, ends)) - min(map(timestamp, begins))).total_seconds()
            wall['state'] = 'known'
            wall['reason'] = '全部所选轮次在截止点前有可信起止'
    return wall


def _duration_groups(selected):
    groups = {}
    for record in selected:
        granularity = record['explanation']['granularity']
        if granularity not in ('model_call', 'logical_request'):
            continue
        state = record['explanation']['duration']['state']
        bucket = groups.setdefault(granularity, {'valid': 0, 'missing': 0, 'conflict': 0, 'records': 0, 'total_ms': 0})
        bucket['records'] += 1
        if state == 'known':
            bucket['valid'] += 1
            bucket['total_ms'] += record['explanation']['duration']['value']
        elif state == 'conflict':
            bucket['conflict'] += 1
        else:
            bucket['missing'] += 1
    return groups


def _durations_payload(groups):
    durations = {}
    for granularity, bucket in groups.items():
        state = 'complete' if bucket['records'] and bucket['valid'] == bucket['records'] else 'known_subset' if bucket['valid'] else 'unknown'
        durations[granularity] = {'label': '逻辑请求耗时之和' if granularity == 'logical_request' else '模型调用耗时之和',
                                  'total_ms': bucket['total_ms'] if state != 'unknown' else None,
                                  'state': state, 'valid': bucket['valid'], 'missing': bucket['missing'],
                                  'conflict': bucket['conflict'], 'records': bucket['records'], 'unit': 'ms'}
    return durations


def build_activity_explanation(chosen_turns, selected, end):
    wall = _wall_entry(chosen_turns, end,
                       '主会话所选轮次最早可信起点至最晚可信终点；不扣除插入间隔；不含后代执行并集')
    return {'wall': wall, 'durations': _durations_payload(_duration_groups(selected)),
            'note': '调用/请求耗时之和允许并行重叠，不等于墙钟跨度；不同粒度分列不混合'}


def build_overview_turns(data, family, selected, end, start):
    # Overall timeline strictly split by actual session/turn; no mixed cross-session table.
    members = {}
    intervals = []
    for record in selected:
        if record.get('interval_start'):
            intervals.append(record)
            continue
        members.setdefault((record['session'], record['turn']), []).append(record)
    admitted = {(sid, turn) for sid, turn in members if turn}
    excluded = []
    for sid in sorted(family):
        for item in data['sessions'].get(sid, {}).get('turns', {}).values():
            if (sid, item['id']) in admitted:
                continue
            if _turn_intersects(item, start, end):
                admitted.add((sid, item['id']))
                continue
            reason = _unproven_turn_reason(item, start, end)
            if reason:
                excluded.append({'reason': reason, 'session': sid, 'turn': item['id']})
    rows = []
    for sid, turn_id in sorted(admitted):
        candidate = data['sessions'].get(sid, {}).get('turns', {}).get(turn_id)
        if candidate is None:
            candidate = {'id': turn_id, 'start': None, 'end': None, 'status': 'unknown'}
        group = members.get((sid, turn_id), [])
        span_state, span_reason = _span_state(candidate, start, end)
        rows.append({'kind': 'turn', 'session': sid, 'turn': turn_id,
                     'start': candidate.get('start'), 'end': candidate.get('end'),
                     'start_source': candidate.get('start_source'), 'end_source': candidate.get('end_source'),
                     'status': candidate.get('status') or 'unknown',
                     'cutoff_status': _turn_cutoff_status(candidate, end),
                     'span_state': span_state, 'span_reason': span_reason,
                     'native_duration_ms': _native_duration(candidate),
                     'record_keys': [r['key'] for r in group],
                     **aggregate(group)})
    for record in intervals:
        rows.append({'kind': 'cumulative_interval', 'session': record['session'],
                     'interval_start': record['interval_start'], 'interval_end': record['time'],
                     'interval_turns': record.get('interval_turns') or [],
                     'status': 'unknown', 'cutoff_status': 'ended_before_cutoff',
                     'span_state': 'interval', 'span_reason': '累计计数区间，独立呈现，不复制到各轮',
                     'native_duration_ms': None,
                     'record_keys': [record['key']],
                     **aggregate([record])})
    return rows, excluded


def build_overview_activity(turn_rows, selected, end, family):
    """Per-session wall clocks over the SAME admitted turn set the timeline used;
    no second scan of every source turn, no cross-session total."""
    sessions = {}
    for sid in sorted(family):
        mine = [{'id': r['turn'], 'start': r['start'], 'end': r['end'], 'status': r['status']}
                for r in turn_rows if r['kind'] == 'turn' and r['session'] == sid]
        sessions[sid] = _wall_entry(mine, end, '该会话自身轮次最早可信起点至最晚可信终点；不扣除间隔；不跨会话合并')
    return {'sessions': sessions, 'durations': _durations_payload(_duration_groups(selected)),
            'note': '墙钟按会话分列，不生成跨会话墙钟总量；调用/请求耗时之和允许并行重叠'}


def normalize(usage, mapping, cache_write_zero_uncertain=False):
    metrics = {name: number(usage, key, name == 'cache_write' and cache_write_zero_uncertain)
               for name, key in mapping.items()}
    for name in METRICS:
        metrics.setdefault(name, cell())
    inp, out, cache = (metrics[k] for k in ('input', 'output', 'cache_read'))
    if known(inp) and known(cache):
        if cache['value'] > inp['value']:
            metrics['cache_read'] = cell(state='conflict', reason='缓存读取超过总输入', field=cache['field'])
        else:
            metrics['non_cache_read'] = cell(inp['value'] - cache['value'], 'derived', '', 'input-cache_read')
    if known(inp) and known(out):
        total = inp['value'] + out['value']
        metrics['total'] = cell(total, 'derived', '', 'input+output')
        if 'total_tokens' in usage and usage['total_tokens'] != total:
            metrics['total'] = cell(state='conflict', reason='源总量与输入加输出冲突', field='total_tokens')
    return metrics


def source_lines(paths):
    """Read each finite file snapshot; never copy raw records into diagnostics."""
    for path in paths:
        path = Path(path).resolve()
        try:
            with path.open('rb') as stream:
                snapshot = stream.read(os.fstat(stream.fileno()).st_size)
        except OSError as exc:
            yield str(path), 0, None, '读取失败：' + type(exc).__name__
            continue
        for line_no, line in enumerate(snapshot.splitlines(keepends=True), 1):
            if not line.endswith(b'\n'):
                yield str(path), line_no, None, '末行未完成；未纳入'
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError()
                yield str(path), line_no, record, None
            except (ValueError, UnicodeError):
                yield str(path), line_no, None, '损坏或非对象记录；未纳入'


def _same_moment(old, new):
    try:
        return timestamp(old) == timestamp(new)
    except (ValueError, TypeError, OverflowError):
        return old == new


def _reconcile_field(field, old, new):
    """Field-semantics reconciliation at the single dedup entry. Python value
    equality is not domain equality: a bool is never a number even when
    False == 0, and equivalent timestamp spellings name the same moment. A
    missing value or 'unknown' (no evidence) yields to a known fact; truly
    opposite facts and invalid values stay in conflict with every source."""
    if field == 'duration_ms':
        def valid(value):
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and value == value and value not in (float('inf'), float('-inf'))
                    and value >= 0)
        if old is None and new is None:
            return None, False
        if old is None:
            return (new, False) if valid(new) else (old, True)
        if new is None:
            return (old, False) if valid(old) else (old, True)
        if valid(old) and valid(new):
            return (old, False) if old == new else (old, True)
        # A bool/negative/non-finite duration is invalid evidence: it can never
        # be reconciled with a different value, even one Python calls equal.
        return (old, False) if type(old) is type(new) and old == new else (old, True)
    if field == 'start':
        if old is None and new is not None:
            return new, False
        if new is None and old is not None:
            return old, False
        if old is None:
            return old, False
        return (old, False) if _same_moment(old, new) else (old, True)
    # granularity / time_kind / source_status: None or 'unknown' means no evidence.
    old_missing = old is None or old == 'unknown'
    new_missing = new is None or new == 'unknown'
    if old_missing and new_missing:
        return (old if old is not None else new), False
    if old_missing:
        return new, False
    if new_missing:
        return old, False
    return (old, False) if old == new else (old, True)


def deduplicate(records, issues):
    """The single dedup entry: merge whitelist explanation evidence and every source
    location. Irreconcilable facts (granularity/start/end/status/duration) only mark
    the affected explanation fields as conflict via '_field_conflicts'; no averaging,
    no first-wins rewriting, no extra metering record."""
    unique = {}
    for record in records:
        key = record['key']
        if key not in unique:
            unique[key] = record
            continue
        old = unique[key]
        old['sources'].extend(s for s in record['sources'] if s not in old['sources'])
        conflicts = old.setdefault('_field_conflicts', set())
        for field in ('granularity', 'time_kind', 'source_status', 'duration_ms', 'start'):
            merged, conflict = _reconcile_field(field, old.get(field), record.get(field))
            old[field] = merged
            if conflict:
                conflicts.add(field)
        for name in METRICS:
            if old['metrics'][name] != record['metrics'][name]:
                old['metrics'][name] = cell(state='conflict', reason='同一调用的来源数值冲突')
        if old['time'] != record['time'] or old['turn'] != record['turn']:
            issues.append({'reason': '同一调用的时间或轮次冲突', 'source': record['sources'][0]})
            old['time'] = None
            old['turn'] = None
    return list(unique.values())


def explanation_lines(result):
    """Granularity and duration-coverage facts shared by Markdown/CSV export."""
    records = result.get('records') or []
    exps = [r['explanation'] for r in records if 'explanation' in r]
    if not exps:
        return []
    counts = {}
    for exp in exps:
        counts[exp['granularity']] = counts.get(exp['granularity'], 0) + 1
    durs = {}
    for exp in exps:
        durs[exp['duration']['state']] = durs.get(exp['duration']['state'], 0) + 1
    return [('granularity', g, n) for g, n in sorted(counts.items())] \
        + [('duration_state', s, n) for s, n in sorted(durs.items())]


def explanation_note(result):
    records = result.get('records') or []
    exps = [r['explanation'] for r in records if 'explanation' in r]
    if not exps:
        return '记录解释：旧报告未保存记录级解释，仅展示已保存字段。'
    counts = {}
    for exp in exps:
        counts[exp['granularity']] = counts.get(exp['granularity'], 0) + 1
    durs = {}
    for exp in exps:
        durs[exp['duration']['state']] = durs.get(exp['duration']['state'], 0) + 1
    return ('记录解释：粒度 ' + '、'.join(GRANULARITY_LABELS[g] + ' ' + str(n) + ' 条' for g, n in sorted(counts.items()))
            + '；直接耗时覆盖 ' + '、'.join(s + ' ' + str(n) + ' 条' for s, n in sorted(durs.items()))
            + '。')


def aggregate(records):
    metrics = {}
    for name in METRICS:
        values = [r['metrics'][name] for r in records]
        valid = [v for v in values if known(v)]
        metrics[name] = {'value': sum(v['value'] for v in valid) if valid else None,
                         'known_records': len(valid), 'records': len(values),
                         'state': 'known' if valid and len(valid) == len(values) else 'partial' if valid else 'unknown',
                         'reasons': sorted({v['reason'] for v in values if v['reason']})}
    paired = [r for r in records if known(r['metrics']['input']) and known(r['metrics']['cache_read'])]
    denom = sum(r['metrics']['input']['value'] for r in paired)
    numer = sum(r['metrics']['cache_read']['value'] for r in paired)
    return {'metrics': metrics, 'cache_hit_rate': {'value': numer / denom if denom else None,
            'paired_records': len(paired), 'input': denom, 'cache_read': numer,
            'state': 'not_applicable' if paired and not denom else 'known' if len(paired) == len(records) and paired else 'partial' if paired else 'unknown'},
            'call_count': sum(r.get('call_count', 1) for r in records) if records and all(r.get('call_count', 1) is not None for r in records) else None,
            'known_call_count': sum(r.get('call_count') or 0 for r in records)}


def build_views(selected, session_id, keys=False):
    """Three independent views over the same selected records; the only such computation.

    With keys=True each row also carries the metered record keys it was grouped from,
    so the browser can locate detail without regrouping."""
    def turn_identity(record):
        members = record.get('interval_turns')
        if members and len(set(members)) > 1:
            return '__multi_turn_interval__', '多轮区间，无法拆分'
        if members:
            return members[0], members[0]
        owner = record['turn'] if record['session'] == session_id else record.get('owner_turn')
        return (owner, owner) if owner else ('__unknown__', '未知')

    return {'model': dimension_view(selected, model_identity, keys),
            'agent': dimension_view(selected, agent_identity, keys),
            'turn': dimension_view(selected, turn_identity, keys)}


def model_identity(record):
    name = record.get('model') or '模型未知'
    return name, name


def agent_identity(record):
    name = record.get('agent') or '未知'
    return name, name


def session_identity(record):
    return record['session'], record['session']


def dimension_view(records, identity_of, keys=False):
    """One independent distribution view; the only grouping computation for a dimension."""
    groups = {}
    for record in records:
        identity, label = identity_of(record)
        groups.setdefault(identity, (label, []))[1].append(record)
    rows = []
    for identity in sorted(groups):
        label, members = groups[identity]
        row = dict(id=identity, label=label, **aggregate(members))
        if keys:
            row['record_keys'] = [r['key'] for r in members]
        rows.append(row)
    return {'available': True, 'reason': '', 'rows': rows}


def timezone_of(name):
    """Display timezone for day bucketing: IANA name or ±HH:MM offset."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError('时区必须是 IANA 名称或 ±HH:MM 偏移')
    text = name.strip()
    try:
        return zoneinfo.ZoneInfo(text)
    except Exception:
        pass
    if len(text) == 6 and text[0] in '+-' and text[3] == ':':
        hours, minutes = int(text[1:3]), int(text[4:6])
        delta = dt.timedelta(hours=hours, minutes=minutes)
        if text[0] == '-':
            delta = -delta
        return dt.timezone(delta)
    raise ValueError('无法识别的时区：' + name)


def local_timezone_name():
    offset = dt.datetime.now().astimezone().utcoffset()
    total = int(offset.total_seconds()) // 60
    sign = '+' if total >= 0 else '-'
    total = abs(total)
    return f'{sign}{total // 60:02d}:{total % 60:02d}'


def day_bounds(date_text, zone):
    """Local-day [start, end) for one ISO calendar date in the display zone.

    fold=0 local midnight to the next day's midnight; the single day-boundary rule
    shared by bucket filtering (effective lower bound) and saved day rows (from/to).
    """
    start_local = dt.datetime.fromisoformat(date_text + 'T00:00:00').replace(tzinfo=zone)
    end_local = start_local + dt.timedelta(days=1)
    return start_local, end_local, start_local.astimezone(dt.timezone.utc), end_local.astimezone(dt.timezone.utc)


INTERNAL_CATEGORIES = ('retry_failure', 'compaction_summary', 'title_session_aux', 'subagent_descendants', 'background_other')
INTERNAL_LABELS = {'retry_failure': '重试/失败', 'compaction_summary': '压缩/摘要', 'title_session_aux': '标题/会话辅助',
                   'subagent_descendants': '子代理/后代', 'background_other': '后台/其他'}
INTERNAL_STATES = {'not_checked': '尚未核查', 'checked_available': '已核查：有可靠记录', 'checked_absent': '已核查：来源未提供', 'checked_gap': '已核查：存在缺口'}


def internal_support(selected, issues, harness):
    """Record verified facts only; unchecked must stay distinguishable from source gaps."""
    def evidence(part):
        return [issue for issue in issues if part in issue.get('reason', '')]

    support = {}
    retry = evidence('重试')
    support['retry_failure'] = {'status': 'checked_gap' if retry else 'not_checked',
                                'summary': '数据库仅保留逻辑请求结果，独立重试调用总数及失败用量可能缺失' if retry
                                else '重试与失败调用尚未在本范围核查', 'evidence': retry}
    compact_marks = evidence('压缩')
    metered_compactions = [r for r in selected if r.get('internal_kind') == 'compaction']
    support['compaction_summary'] = {'status': 'checked_available' if metered_compactions else 'checked_gap' if compact_marks else 'not_checked',
                                     'summary': f'本范围包含 {len(metered_compactions)} 条经明确关联计量的压缩/摘要调用' if metered_compactions
                                     else '源存在压缩标记但无可关联 usage，可能已计或缺失' if compact_marks
                                     else '压缩与摘要调用尚未在本范围核查', 'evidence': compact_marks}
    aux = [r for r in selected if r.get('internal_kind') == 'session_aux']
    if aux:
        support['title_session_aux'] = {'status': 'checked_available',
                                        'summary': f'本范围包含 {len(aux)} 条会话辅助调用（标题等，不摊入任务轮次）', 'evidence': []}
    elif harness == 'codex':
        support['title_session_aux'] = {'status': 'checked_absent',
                                        'summary': '已核查近期真实样例记录类型，源未记录标题/会话辅助类模型调用', 'evidence': []}
    else:
        support['title_session_aux'] = {'status': 'not_checked',
                                        'summary': '标题与会话辅助尚未核查；无法归属记录在会话辅助/未归属单列', 'evidence': []}
    children = [r for r in selected if r['group'] == 'child']
    background = [r for r in selected if r.get('origin_kind') == 'workflow_child']
    support['subagent_descendants'] = {'status': 'checked_available' if children else 'not_checked',
                                       'summary': f'本范围包含 {len(children)} 条经明确关系归属的后代调用'
                                       + (f'（其中后台工作流 {len(background)} 条）' if background else '') if children
                                       else '后代与派生关系尚未在本范围核查', 'evidence': []}
    support['background_other'] = {'status': 'checked_available' if background else 'not_checked',
                                   'summary': f'本范围包含 {len(background)} 条后台工作流调用，按明确父子关系归入后代并遵守截止点' if background
                                   else '后台及其他内部工作尚未在本范围核查', 'evidence': []}
    return support


def report(data, session_id, cutoff, main_only=False, turns=None, since=None, cutoff_source='cli_start', localization=None):
    if session_id not in data['sessions']:
        raise ValueError('找不到指定会话；请先列出候选')
    available = data['sessions'][session_id]['turns']
    turns = sorted(set(turns)) if turns is not None else None
    if turns is not None and (not turns or any(t not in available for t in turns)):
        raise ValueError('轮次为空或不属于所选会话；请先列出稳定轮次 ID')
    end = timestamp(cutoff); start = timestamp(since) if since else None
    if start and start >= end:
        raise ValueError('时间范围必须满足 from < to')
    family = {session_id}
    if not main_only:
        while True:
            grown = family | {sid for sid,s in data['sessions'].items() if s.get('parent') in family}
            if grown == family:
                break
            family = grown
    paths = {p for sid in family for p in data['sessions'][sid]['paths']}
    issues = [i for i in data['issues'] if i.get('session', session_id) in family
              and (not turns or not i.get('turn') or i['turn'] in turns)
              and (i.get('session') or i.get('source', {}).get('path') in paths)]
    records = [r for r in data['records'] if r['session'] in family
               and (not main_only or (r['session'] == session_id and r['group'] == 'main'))]
    selected, unassigned = [], []
    for r in records:
        if turns is not None:
            members = r.get('interval_turns')
            if members:
                if not set(members).issubset(turns):
                    if set(members).intersection(turns):
                        issues.append({'reason': '累计区间跨过未选轮次，无法精确归属', 'source': r['sources'][0]})
                    continue
            elif (r.get('owner_turn') if r['session'] != session_id else r['turn']) not in turns:
                if not (r.get('owner_turn') if r['session'] != session_id else r['turn']):
                    issues.append({'reason': '记录轮次无法归属；未摊入任务', 'source': r['sources'][0]})
                    try:
                        if timestamp(r['time']) < end and (not start or timestamp(r['time']) >= start):
                            unassigned.append(r)
                    except (ValueError,TypeError):
                        pass
                continue
        try:
            at = timestamp(r['time'])
            if at >= end:
                if r.get('start') and timestamp(r['start']) < end:
                    issues.append({'reason': '调用跨截止点，整次调用未纳入且不能按比例切分', 'source': r['sources'][0]})
                continue
            if start and at < start:
                continue
            if start and r.get('interval_start') and timestamp(r['interval_start']) < start:
                issues.append({'reason': '累计区间跨时间下界，无法精确切分', 'source': r['sources'][0]})
                continue
            selected.append(r)
        except (ValueError, TypeError):
            issues.append({'reason': '调用缺少可信时间，无法判断截止点', 'source': r['sources'][0]})
    chosen_turns = [available[t] for t in (turns if turns is not None else available)]
    explain_records(selected)
    explain_records(unassigned)
    turn_rows, turn_excluded = build_turn_explanations(data, session_id, family, available,
                                                       turns if turns is not None else None,
                                                       selected, end, start)
    explanation = {'turns': turn_rows}
    begins = [t['start'] for t in chosen_turns if t.get('start')]
    ends = [t['end'] for t in chosen_turns if t.get('end')]
    ended = bool(chosen_turns) and len(ends) == len(chosen_turns) and all(timestamp(x) < end for x in ends)
    wall = (max(map(timestamp, ends)) - min(map(timestamp, begins))).total_seconds() if ended and len(begins) == len(chosen_turns) else None
    # The legacy field projects the SAME valid-duration evidence as explanation.activity:
    # a complete sum only when every included record carries a valid duration of one
    # granularity; negative/bool/non-finite values never enter the sum.
    durations = [r['explanation']['duration'] for r in selected] if selected else []
    duration = (sum(d['value'] for d in durations)
                if durations and all(d['state'] == 'known' for d in durations)
                and len({r['explanation']['granularity'] for r in selected}) == 1
                else None)
    rows = [dict(group=g, record_keys=[r['key'] for r in selected if r['group'] == g],
                 **aggregate([r for r in selected if r['group'] == g])) for g in GROUPS if any(r['group'] == g for r in selected)]
    views = build_views(selected, session_id, keys=True)
    view_rows = [row for view in views.values() for row in view['rows']]
    any_usage = any(known(r['metrics'][m]) for r in selected for m in ('input','output','cache_read'))
    any_count = any(r.get('call_count') is not None for r in selected)
    tools = []
    if not main_only:
        for item in data.get('tool_reports', []):
            if item['session'] == session_id and (turns is None or item['turn'] in turns):
                try:
                    if (not start or timestamp(item['time']) >= start) and timestamp(item['time']) < end:
                        tools.append(item)
                except (TypeError,ValueError):
                    issues.append({'reason':'工具报告缺少可信时间', 'source':item['source']})
    zero_proven = bool(chosen_turns) and ended and all(t.get('model_request_count') == 0 for t in chosen_turns) and not selected and not issues and not tools
    summary = aggregate(selected)
    if zero_proven:
        # A completed turn ledger explicitly reports no model requests. No inference from absence.
        for m in summary['metrics'].values():
            m.update(value=0, state='known', reasons=[])
        summary['call_count'] = 0
        summary['cache_hit_rate']['state'] = 'not_applicable'
    else:
        for row in rows + view_rows + [summary]:
            for metric in row['metrics'].values():
                if metric['value'] is not None:
                    metric['state']='partial'
            if row['cache_hit_rate']['state']=='known':
                row['cache_hit_rate']['state']='partial'
    result = {'format_version': 2, 'harness': data['harness'],
            'scope': {'session': session_id, 'turns': turns, 'from': since, 'to': cutoff,
                      'cutoff_source': cutoff_source, 'include_children': not main_only, 'main_only': main_only},
            'localization': localization or {'session': {'id': session_id, 'confirmed_by': 'explicit',
                                                         'evidence': '显式指定的会话标识'},
                                             'cutoff': {'time': cutoff, 'source': cutoff_source,
                                                        'evidence': '显式或默认截止点'},
                                             'limits': []},
            'internal_support': internal_support(selected, issues, data['harness']),
            'views': views,
            'read_at': now(), 'status': 'confirmed_zero' if zero_proven else 'partial' if any_usage else 'count_only' if any_count else 'tool_only' if tools else 'unstatisticable',
            'scope_note': '筛选：主代理常规调用' if main_only else '默认纳入有证据归属的后代与内部调用；重叠任务选集不能直接相加',
            'rows': rows, 'summary': summary, 'records': selected, 'unassigned_records': unassigned,
            'inherited_records': [r for r in data.get('inherited',[]) if r['session'] in family],
            'issues': issues, 'source_files': data['source_files'],
            'coverage': '当前可用记录；未证明完整调用覆盖，不能推断 100%',
            'coverage_state': 'proven_zero' if zero_proven else 'unknown',
            'activity': {'status': 'ended' if ended else 'active' if any(t.get('status') == 'running' for t in chosen_turns) else 'unknown',
                         'wall_seconds': wall, 'call_duration_ms': duration, 'note': '墙钟跨度不扣除插入任务；调用耗时之和不等于墙钟跨度'},
            'tool_reports': tools}
    explanation['activity'] = build_activity_explanation(chosen_turns, selected, end)
    explanation['internal'] = build_internal_breakdown(selected)
    explanation['relations'] = build_relation_rows(data, family, session_id)
    explanation['excluded'] = build_excluded_rows(issues) + turn_excluded
    result['explanation'] = explanation
    alternates = [alt for alt in data.get('alternate_sources', []) if alt['session'] in family]
    if alternates:
        result['alternate_sources'] = alternates
    return result


def overview(data, session_ids, cutoff, since=None, tz='UTC', main_only=False,
             cutoff_source='cli_start', localization=None, missing_ok=False):
    """Cross-session overall report: one selection over the deduplicated record set.

    With missing_ok (saved-scope recompute), ids absent from the current source are kept
    in the recorded scope but excluded from selection and reported as a gap; fresh
    explicit sets stay strict so typos fail loudly.
    """
    end = timestamp(cutoff)
    start = timestamp(since) if since else None
    if start and start >= end:
        raise ValueError('时间范围必须满足 from < to')
    zone = timezone_of(tz)
    roots_recorded = sorted(set(session_ids))
    unknown = sorted(sid for sid in roots_recorded if sid not in data['sessions'])
    if unknown and not missing_ok:
        raise ValueError('找不到指定会话：' + ', '.join(unknown) + '；请先运行 sessions 查看候选')
    scope_sessions = roots_recorded
    roots = [sid for sid in roots_recorded if sid not in unknown]
    family = set(roots)
    if not main_only:
        while True:
            grown = family | {sid for sid, s in data['sessions'].items() if s.get('parent') in family}
            if grown == family:
                break
            family = grown
    issues = [i for i in data['issues'] if i.get('session') in family or i.get('session') is None]
    for sid in unknown:
        issues.append({'reason': '保存的会话在当前来源缺失，未计入用量；未使用旧报告数值', 'session': sid})
    records = [r for r in data['records'] if r['session'] in family
               and (not main_only or (r['session'] in roots and r['group'] == 'main'))]
    selected = []
    for r in records:
        try:
            at = timestamp(r['time'])
            if at >= end:
                if r.get('start') and timestamp(r['start']) < end:
                    issues.append({'reason': '调用跨截止点，整次调用未纳入且不能按比例切分',
                                   'source': r['sources'][0], 'session': r['session']})
                continue
            if start and at < start:
                continue
            if start and r.get('interval_start') and timestamp(r['interval_start']) < start:
                issues.append({'reason': '累计区间跨时间下界，无法精确切分', 'source': r['sources'][0],
                               'session': r['session']})
                continue
            selected.append(r)
        except (ValueError, TypeError):
            issues.append({'reason': '调用缺少可信时间，无法判断截止点；未计入任何合计', 'source': r['sources'][0],
                           'session': r['session']})
    day_records, unbucketed = {}, []
    for r in selected:
        at = timestamp(r['time'])
        date = at.astimezone(zone).date().isoformat()
        day_start_utc = day_bounds(date, zone)[2]
        lower = max(day_start_utc, start) if start else day_start_utc
        interval_start = r.get('interval_start')
        if interval_start:
            try:
                if timestamp(interval_start) < lower:
                    unbucketed.append(r)
                    continue
            except (ValueError, TypeError):
                pass
        day_records.setdefault(date, []).append(r)
    days = []
    for date in sorted(day_records):
        group = day_records[date]
        row = {'date': date, 'sessions': len({r['session'] for r in group})}
        # Day range = intersection of the original scope with this local day. Saved on the
        # row so drill/display/recompute all consume this one kernel boundary rule; when the
        # scope bound itself is the intersection bound, keep its original spelling.
        day_start_local, day_end_local, day_start_utc, day_end_utc = day_bounds(date, zone)
        row['from'] = since if start and start >= day_start_utc else day_start_local.isoformat()
        row['to'] = cutoff if end < day_end_utc else day_end_local.isoformat()
        row['record_keys'] = [r['key'] for r in group]
        row.update(aggregate(group))
        row['by_model'] = dimension_view(group, model_identity, keys=True)['rows']
        row['by_session'] = dimension_view(group, session_identity, keys=True)['rows']
        days.append(row)
    unbucketed_payload = {'records': len(unbucketed),
                          'reasons': ['累计区间跨日桶下界，无法可靠分日；已计入总览，未计入任何一天'] if unbucketed else [],
                          'record_keys': [r['key'] for r in unbucketed],
                          **aggregate(unbucketed)}
    rankings = {'model': dimension_view(selected, model_identity, keys=True),
                'session': dimension_view(selected, session_identity, keys=True)}
    index = []
    for sid in sorted(family):
        item = data['sessions'][sid]
        ends = [t['end'] for t in item['turns'].values() if t.get('end')]
        mine = [r for r in selected if r['session'] == sid]
        index.append({'id': sid, 'start': item.get('start'), 'last_turn_end': max(ends) if ends else None,
                      'turn_count': len(item['turns']), 'parent': item.get('parent'),
                      'forked_from': item.get('forked_from'), 'usage_records': len(mine),
                      'known_calls': sum(r.get('call_count') or 0 for r in mine)})
    turns = [t for sid in family for t in data['sessions'][sid]['turns'].values()]
    ends = [t['end'] for t in turns if t.get('end')]
    ended = bool(turns) and len(ends) == len(turns) and all(timestamp(x) < end for x in ends)
    # Confirmed zero needs zero-call evidence for EVERY session in scope: one ledger-proven
    # zero session cannot speak for a session with no turn evidence at all.
    every_session_proven = bool(family) and all(data['sessions'][sid]['turns'] for sid in family)
    tools = []
    if not main_only:
        for item in data.get('tool_reports', []):
            if item['session'] in family:
                try:
                    if (not start or timestamp(item['time']) >= start) and timestamp(item['time']) < end:
                        tools.append(item)
                except (TypeError, ValueError):
                    issues.append({'reason': '工具报告缺少可信时间', 'source': item['source']})
    zero_proven = bool(turns) and every_session_proven and ended \
        and all(t.get('model_request_count') == 0 for t in turns) \
        and not selected and not issues and not tools
    rows = [dict(group=g, record_keys=[r['key'] for r in selected if r['group'] == g],
                 **aggregate([r for r in selected if r['group'] == g])) for g in GROUPS if any(r['group'] == g for r in selected)]
    views = {'model': dimension_view(selected, model_identity, keys=True),
             'agent': dimension_view(selected, agent_identity, keys=True),
             'turn': {'available': False, 'reason': '整体范围为跨会话视图，轮次维度不可用；请进入单会话流程查看轮次分布',
                      'rows': []}}
    any_usage = any(known(r['metrics'][m]) for r in selected for m in ('input', 'output', 'cache_read'))
    any_count = any(r.get('call_count') is not None for r in selected)
    summary = aggregate(selected)
    if zero_proven:
        for m in summary['metrics'].values():
            m.update(value=0, state='known', reasons=[])
        summary['call_count'] = 0
        summary['cache_hit_rate']['state'] = 'not_applicable'
    else:
        aggregate_rows = rows + rankings['model']['rows'] + rankings['session']['rows'] \
            + views['model']['rows'] + views['agent']['rows'] + [summary]
        for day in days:
            aggregate_rows += [day] + day['by_model'] + day['by_session']
        aggregate_rows.append(unbucketed_payload)
        for row in aggregate_rows:
            for metric in row['metrics'].values():
                if metric['value'] is not None:
                    metric['state'] = 'partial'
            if row['cache_hit_rate']['state'] == 'known':
                row['cache_hit_rate']['state'] = 'partial'
    result = {'format_version': 3, 'harness': data['harness'],
              'scope': {'kind': 'overall', 'sessions': scope_sessions, 'from': since, 'to': cutoff, 'tz': tz,
                        'cutoff_source': cutoff_source, 'include_children': not main_only, 'main_only': main_only},
              'localization': localization or {'sessions': {'confirmed_by': 'explicit_set', 'count': len(scope_sessions),
                                                            'evidence': '显式指定的会话集合'},
                                               'cutoff': {'time': cutoff, 'source': cutoff_source,
                                                          'evidence': '显式或默认截止点'},
                                               'limits': []},
              'internal_support': internal_support(selected, issues, data['harness']),
              'views': views, 'days': days, 'rankings': rankings, 'session_index': index,
              'unbucketed': unbucketed_payload,
              'read_at': now(), 'status': 'confirmed_zero' if zero_proven else 'partial' if any_usage
                          else 'count_only' if any_count else 'tool_only' if tools else 'unstatisticable',
              'scope_note': '整体范围：所选会话集合闭包，重叠选集不重复计量；重叠任务选集不能直接相加',
              'rows': rows, 'summary': summary, 'records': selected, 'unassigned_records': [],
              'inherited_records': [r for r in data.get('inherited', []) if r['session'] in family],
              'issues': issues, 'source_files': data['source_files'],
              'coverage': '当前可用记录；未证明完整调用覆盖，不能推断 100%',
              'coverage_state': 'proven_zero' if zero_proven else 'unknown',
              'tool_reports': tools}
    alternates = [alt for alt in data.get('alternate_sources', []) if alt['session'] in family]
    if alternates:
        result['alternate_sources'] = alternates
    explain_records(selected)
    turn_rows, turn_excluded = build_overview_turns(data, family, selected, end, start)
    result['explanation'] = {'turns': turn_rows,
                             'activity': build_overview_activity(turn_rows, selected, end, family),
                             'internal': build_internal_breakdown(selected),
                             'relations': build_relation_rows(data, family, None),
                             'excluded': build_excluded_rows(issues) + turn_excluded}
    return result


def display_value(metric):
    if metric['value'] is None:
        return '未知'
    return f"{metric['value']:,}" + ('（部分）' if metric['state'] != 'known' else '')


def markdown(result):
    if result.get('scope', {}).get('kind') == 'overall':
        return overview_markdown(result)
    def safe(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    scope = result['scope']
    lines = [f"任务：{safe(scope.get('label') or '所选范围')}；会话：{safe(scope['session'])}；截止：{safe(scope['to'])}",
             f"轮次：{safe(', '.join(scope['turns']) if scope['turns'] is not None else '整个会话')}；时间下界：{safe(scope['from'])}",
             result.get('scope_note', ''), f"覆盖：{result['coverage']}", '',
             '| 分组 | 输入 | 输出 | 缓存读取 | 缓存命中率 | 总量 |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in result['rows'] + [dict(group='summary', **result['summary'])]:
        metrics = row['metrics']; rate = row['cache_hit_rate']
        hit = f"{rate['value']:.2%}" if rate['value'] is not None else '不适用' if rate['state'] == 'not_applicable' else '未知'
        if rate['state'] == 'partial':
            hit += f"（已知子集：{rate['paired_records']} 条，输入 {rate['input']}）"
        name = '已记录小计' if row['group'] == 'summary' else GROUPS.get(row['group'], row['group'])
        lines.append('| ' + ' | '.join([safe(name), display_value(metrics['input']), display_value(metrics['output']), display_value(metrics['cache_read']), hit, display_value(metrics['total'])]) + ' |')
    lines += ['', '输入包含缓存读取；缓存与已包含的推理输出不再相加。',
              f"实际读取：{result['read_at']}；状态：{STATES.get(result['status'], result['status'])}"]
    localization = result.get('localization')
    if localization is None:
        lines.append('定位证据：旧报告未保存')
    else:
        session = localization['session']; cutoff = localization['cutoff']
        lines.append(f"定位证据：会话经{session['confirmed_by']}确认（{safe(session['evidence'])}）；"
                     f"截止点来源 {safe(cutoff['source'])}（{safe(cutoff['evidence'])}）")
        lines += [f"定位限制：{safe(limit)}" for limit in localization.get('limits', [])]
    support = result.get('internal_support')
    if support is None:
        lines.append('内部来源支持：旧报告未保存')
    else:
        lines.append('内部来源支持：' + '；'.join(
            f"{INTERNAL_LABELS.get(key, key)}={INTERNAL_STATES.get(value['status'], value['status'])}"
            for key, value in support.items()))
        lines += [f"内部支持说明（{INTERNAL_LABELS.get(key, key)}）：{safe(value['summary'])}"
                  for key, value in support.items() if value['status'] != 'not_checked']
    if result.get('views') is None:
        lines.append('明细视图（模型/代理/轮次）：旧报告未保存，不可用')
    lines.append(f"调用数：{result['summary']['call_count'] if result['summary']['call_count'] is not None else '未知'}；其中已识别 {result['summary'].get('known_call_count', 0)} 次")
    lines.append(explanation_note(result))
    activity = result.get('activity', {})
    lines.append(f"活跃状态：{STATES.get(activity.get('status'), '未知')}；墙钟秒：{activity.get('wall_seconds') if activity.get('wall_seconds') is not None else '未知'}；调用耗时毫秒之和：{activity.get('call_duration_ms') if activity.get('call_duration_ms') is not None else '未知'}")
    for name in ('cache_write', 'reasoning', 'non_cache_read'):
        metric = result['summary']['metrics'][name]
        label={'cache_write':'缓存写入','reasoning':'推理输出','non_cache_read':'非缓存读取输入'}[name]
        lines.append(f"{label}: {display_value(metric)}；{'；'.join(metric['reasons'])}")
    lines += [f"来源：{safe(p)}" for p in result['source_files']]
    issue_groups={}
    for issue in result['issues']:
        issue_groups.setdefault(issue['reason'],[]).append(issue.get('source',''))
    for reason,sources in issue_groups.items():
        lines.append(f"缺口：{safe(reason)}（{len(sources)} 处）；来源示例：{safe(sources[:3])}")
    lines += [f"仅工具报告：{safe(i['agent'])}，累计 {i['total']:,}；独立展示，不与 usage 相加；来源 {safe(i['source'])}" for i in result.get('tool_reports', [])]
    for alt in result.get('alternate_sources', []):
        metrics = alt['metrics']
        lines.append(f"补充来源（{safe(alt['kind'])}，会话 {safe(alt['session'])}）：{alt['records']} 条，"
                     f"输入 {display_value(metrics['input'])}、总量 {display_value(metrics['total'])}；"
                     f"{safe(alt['note'])}；来源 {safe(alt['path'])}")
    if result.get('unassigned_records'):
        separate = aggregate(result['unassigned_records'])
        lines.append(f"会话辅助/未归属（未摊入所选任务）：{len(result['unassigned_records'])} 条，已记录总量 {display_value(separate['metrics']['total'])}")
    for view in result.get('details', []):
        lines.append(f"明细（{view['dimension']}，独立视图，不再加入合计）：{safe(view['name'])}；输入 {display_value(view['metrics']['input'])}；总量 {display_value(view['metrics']['total'])}")
    return '\n'.join(lines) + '\n'


def _rate_text(rate):
    if rate['value'] is not None:
        text = f"{rate['value']:.2%}"
        if rate['state'] == 'partial':
            text += f"（已知子集：{rate['paired_records']} 条，输入 {rate['input']}）"
        return text
    return '不适用' if rate['state'] == 'not_applicable' else '未知'


def overview_markdown(result):
    def safe(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    scope = result['scope']
    shown = ', '.join(scope['sessions'][:5]) + (' …' if len(scope['sessions']) > 5 else '')
    lines = [f"整体用量：Harness {safe(result['harness'])}；会话集合 {len(scope['sessions'])} 个（{safe(shown)}）",
             f"区间：{safe(scope['from'])} ~ {safe(scope['to'])}；显示时区：{safe(scope['tz'])}；"
             f"代理：{'仅主代理常规调用' if scope['main_only'] else '默认含可靠归属后代与内部调用'}",
             result.get('scope_note', ''), f"覆盖：{result['coverage']}", '',
             '| 分组 | 输入 | 输出 | 缓存读取 | 缓存命中率 | 总量 |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in result['rows'] + [dict(group='summary', **result['summary'])]:
        metrics = row['metrics']
        name = '已记录小计' if row['group'] == 'summary' else GROUPS.get(row['group'], row['group'])
        lines.append('| ' + ' | '.join([safe(name), display_value(metrics['input']), display_value(metrics['output']),
                                        display_value(metrics['cache_read']), _rate_text(row['cache_hit_rate']),
                                        display_value(metrics['total'])]) + ' |')
    lines += ['', '| 日期 | 输入 | 输出 | 缓存读取 | 缓存命中率 | 总量 | 调用数 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for day in result['days']:
        metrics = day['metrics']
        lines.append('| ' + ' | '.join([day['date'], display_value(metrics['input']), display_value(metrics['output']),
                                        display_value(metrics['cache_read']), _rate_text(day['cache_hit_rate']),
                                        display_value(metrics['total']), str(day['call_count'])]) + ' |')
    unbucketed = result['unbucketed']
    if unbucketed['records']:
        lines.append(f"无法归桶：{unbucketed['records']} 条，已记录输入 {display_value(unbucketed['metrics']['input'])}、"
                     f"总量 {display_value(unbucketed['metrics']['total'])}；{safe('；'.join(unbucketed['reasons']))}")
    for dimension, title in (('model', '模型排行'), ('session', '会话排行')):
        lines += ['', f"| {title}（同一结果的独立视图，不加入合计） | 输入 | 输出 | 缓存读取 | 缓存命中率 | 总量 | 调用数 |",
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for row in result['rankings'][dimension]['rows']:
            metrics = row['metrics']
            lines.append('| ' + ' | '.join([safe(row['label']), display_value(metrics['input']),
                                            display_value(metrics['output']), display_value(metrics['cache_read']),
                                            _rate_text(row['cache_hit_rate']), display_value(metrics['total']),
                                            str(row['call_count'])]) + ' |')
    lines += ['', '输入包含缓存读取；缓存与已包含的推理输出不再相加。',
              f"实际读取：{result['read_at']}；状态：{STATES.get(result['status'], result['status'])}"]
    localization = result.get('localization')
    if localization is None:
        lines.append('定位证据：旧报告未保存')
    else:
        sessions = localization['sessions']; cutoff = localization['cutoff']
        lines.append(f"定位证据：会话集合经{sessions['confirmed_by']}确认（{safe(sessions['evidence'])}，{sessions['count']} 个）；"
                     f"截止点来源 {safe(cutoff['source'])}（{safe(cutoff['evidence'])}）")
        lines += [f"定位限制：{safe(limit)}" for limit in localization.get('limits', [])]
    support = result.get('internal_support')
    if support is None:
        lines.append('内部来源支持：旧报告未保存')
    else:
        lines.append('内部来源支持：' + '；'.join(
            f"{INTERNAL_LABELS.get(key, key)}={INTERNAL_STATES.get(value['status'], value['status'])}"
            for key, value in support.items()))
    lines.append(f"调用数：{result['summary']['call_count'] if result['summary']['call_count'] is not None else '未知'}"
                 f"；其中已识别 {result['summary'].get('known_call_count', 0)} 次")
    lines.append(explanation_note(result))
    lines += [f"来源：{safe(p)}" for p in result['source_files']]
    issue_groups = {}
    for issue in result['issues']:
        issue_groups.setdefault(issue['reason'], []).append(issue.get('source', ''))
    for reason, sources in issue_groups.items():
        lines.append(f"缺口：{safe(reason)}（{len(sources)} 处）；来源示例：{safe(sources[:3])}")
    for alt in result.get('alternate_sources', []):
        metrics = alt['metrics']
        lines.append(f"补充来源（{safe(alt['kind'])}，会话 {safe(alt['session'])}）：{alt['records']} 条，"
                     f"输入 {display_value(metrics['input'])}、总量 {display_value(metrics['total'])}；"
                     f"{safe(alt['note'])}；来源 {safe(alt['path'])}")
    return '\n'.join(lines) + '\n'
