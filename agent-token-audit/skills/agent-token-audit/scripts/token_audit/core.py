"""Shared metric, provenance, deduplication and presentation contracts."""
import datetime as dt
import json
import os
from pathlib import Path

METRICS = ('input', 'output', 'cache_read', 'cache_write', 'reasoning', 'non_cache_read', 'total')
GROUPS = {'main': '主代理常规调用', 'child': '子代理常规调用', 'internal': '内部辅助调用', 'unknown': '未分类'}
STATES = {'partial':'已记录小计','count_only':'仅调用计数','tool_only':'仅工具报告','confirmed_zero':'确认零用量','unstatisticable':'不可统计',
          'active':'截至当前记录，未结束','ended':'已结束','unknown':'未知'}


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


def deduplicate(records, issues):
    unique = {}
    for record in records:
        key = record['key']
        if key not in unique:
            unique[key] = record
            continue
        old = unique[key]
        old['sources'].extend(s for s in record['sources'] if s not in old['sources'])
        for name in METRICS:
            if old['metrics'][name] != record['metrics'][name]:
                old['metrics'][name] = cell(state='conflict', reason='同一调用的来源数值冲突')
        if old['time'] != record['time'] or old['turn'] != record['turn']:
            issues.append({'reason': '同一调用的时间或轮次冲突', 'source': record['sources'][0]})
            old['time'] = None
            old['turn'] = None
    return list(unique.values())


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


def build_views(selected, session_id):
    """Three independent views over the same selected records; the only such computation."""
    def turn_identity(record):
        members = record.get('interval_turns')
        if members and len(set(members)) > 1:
            return '__multi_turn_interval__', '多轮区间，无法拆分'
        if members:
            return members[0], members[0]
        owner = record['turn'] if record['session'] == session_id else record.get('owner_turn')
        return (owner, owner) if owner else ('__unknown__', '未知')

    views = {}
    for dimension, identity_of in (
            ('model', lambda r: (r.get('model') or '模型未知', r.get('model') or '模型未知')),
            ('agent', lambda r: (r.get('agent') or '未知', r.get('agent') or '未知')),
            ('turn', turn_identity)):
        groups = {}
        for record in selected:
            identity, label = identity_of(record)
            groups.setdefault(identity, (label, []))[1].append(record)
        views[dimension] = {'available': True, 'reason': '', 'rows': [
            dict(id=identity, label=groups[identity][0], **aggregate(groups[identity][1]))
            for identity in sorted(groups)]}
    return views


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
    begins = [t['start'] for t in chosen_turns if t.get('start')]
    ends = [t['end'] for t in chosen_turns if t.get('end')]
    ended = bool(chosen_turns) and len(ends) == len(chosen_turns) and all(timestamp(x) < end for x in ends)
    wall = (max(map(timestamp, ends)) - min(map(timestamp, begins))).total_seconds() if ended and len(begins) == len(chosen_turns) else None
    duration = sum(r['duration_ms'] for r in selected) if selected and all(isinstance(r.get('duration_ms'), (float,int)) for r in selected) else None
    rows = [dict(group=g, **aggregate([r for r in selected if r['group'] == g])) for g in GROUPS if any(r['group'] == g for r in selected)]
    views = build_views(selected, session_id)
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
    alternates = [alt for alt in data.get('alternate_sources', []) if alt['session'] in family]
    if alternates:
        result['alternate_sources'] = alternates
    return result


def display_value(metric):
    if metric['value'] is None:
        return '未知'
    return f"{metric['value']:,}" + ('（部分）' if metric['state'] != 'known' else '')


def markdown(result):
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
