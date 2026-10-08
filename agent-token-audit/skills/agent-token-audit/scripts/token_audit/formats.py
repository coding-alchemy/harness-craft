"""Report serialization and explicit export; loading never reads telemetry."""
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
from .core import INTERNAL_CATEGORIES, METRICS, aggregate, explanation_lines, markdown, timestamp


def check_source_loc(loc, what='来源定位'):
    if (not isinstance(loc, dict) or not isinstance(loc.get('path'), str)):
        raise ValueError('无效的' + what)
    if 'line' in loc and (type(loc['line']) is not int or loc['line'] < 1):
        raise ValueError('无效的' + what + '行号')
    if 'table' in loc and not isinstance(loc['table'], str):
        raise ValueError('无效的' + what + '表名')
    if 'id' in loc:
        ident = loc['id']
        if (isinstance(ident, bool) or not (isinstance(ident, str) or type(ident) is int)
                or (isinstance(ident, str) and not ident)):
            raise ValueError('无效的' + what + '行 ID')


def check_record_explanation(exp, key):
    """Record-level explanation contract; absence is legal only for old reports
    (all-or-none within one report's metered and unassigned record lists)."""
    if (not isinstance(exp, dict)
            or exp.get('granularity') not in ('model_call', 'reply_usage', 'cumulative_interval', 'logical_request', 'unknown')
            or exp.get('time_kind') not in ('usage_record_time', 'reply_usage_time', 'count_interval_time', 'completion_time', 'unknown')):
        raise ValueError('记录解释扩展无效：' + key)
    status = exp.get('status')
    if (not isinstance(status, dict) or not isinstance(status.get('read'), str)
            or not isinstance(status.get('at_cutoff'), str) or not isinstance(status.get('reason'), str)):
        raise ValueError('记录解释状态无效：' + key)
    duration = exp.get('duration')
    if (not isinstance(duration, dict) or duration.get('unit') != 'ms'
            or duration.get('state') not in ('known', 'unknown', 'conflict')
            or not isinstance(duration.get('reason'), str)
            or (duration.get('value') is not None
                and (type(duration['value']) is not int or isinstance(duration['value'], bool) or duration['value'] < 0))):
        raise ValueError('记录解释耗时无效：' + key)
    evidence = exp.get('classification_evidence')
    if (not isinstance(evidence, dict) or not isinstance(evidence.get('rule'), str)
            or not isinstance(evidence.get('group'), str)):
        raise ValueError('记录分类依据无效：' + key)
    check_source_loc(evidence.get('source'), '分类依据来源')
    ownership = exp.get('ownership_evidence')
    if (not isinstance(ownership, dict) or not isinstance(ownership.get('owner_session'), str)
            or not isinstance(ownership.get('rule'), str) or not isinstance(ownership.get('sources'), list)
            or not all(isinstance(s, dict) for s in ownership['sources'])):
        raise ValueError('记录归属依据无效：' + key)
    for loc in ownership['sources']:
        check_source_loc(loc)
    if 'conflicts' in exp and (not isinstance(exp['conflicts'], list)
                               or not all(isinstance(c, str) for c in exp['conflicts'])):
        raise ValueError('记录解释冲突说明无效：' + key)


def check_records_explanation(records, key):
    """New reports carry the extension on every record; a half-present extension is damage."""
    flags = ['explanation' in r for r in records]
    if any(flags) and not all(flags):
        raise ValueError('记录解释扩展不完整：' + key)
    keys = [r.get('key') for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError('记录键重复：' + key)
    for record in records:
        if 'explanation' in record:
            check_record_explanation(record['explanation'], record.get('key', key))


TURN_STATUSES = ('running', 'completed', 'cancelled', 'error', 'unknown')
CUTOFF_STATUSES = ('ended_before_cutoff', 'ended_after_cutoff', 'not_confirmed_ended_at_cutoff', 'unknown_at_cutoff')
SPAN_STATES = ('in_range', 'extends_before', 'extends_after', 'extends_both', 'conflict', 'unknown', 'interval')
DURATION_SUM_STATES = ('complete', 'known_subset', 'unknown')


def check_turn_row(row, records_by_key, what):
    if (not isinstance(row, dict) or row.get('kind') not in ('turn', 'cumulative_interval')
            or not isinstance(row.get('session'), str) or row.get('status') not in TURN_STATUSES
            or row.get('cutoff_status') not in CUTOFF_STATUSES
            or row.get('span_state') not in SPAN_STATES or not isinstance(row.get('span_reason'), str)):
        raise ValueError('无效的轮次解释行：' + what)
    if row['kind'] == 'turn':
        if not isinstance(row.get('turn'), str):
            raise ValueError('轮次解释行缺少稳定轮次身份：' + what)
    else:
        for field in ('interval_start', 'interval_end'):
            if not isinstance(row.get(field), str):
                raise ValueError('累计区间行缺少边界：' + what)
            try:
                timestamp(row[field])
            except ValueError:
                raise ValueError('累计区间行边界无效：' + what) from None
        if timestamp(row['interval_start']) >= timestamp(row['interval_end']):
            raise ValueError('累计区间行边界无效：' + what)
    for field in ('start', 'end', 'start_source', 'end_source'):
        if field in row and row[field] is not None and not isinstance(row[field], str):
            raise ValueError('轮次解释行时间字段无效：' + what)
    for field in ('start', 'end'):
        if row.get(field) is not None:
            try:
                timestamp(row[field])
            except ValueError:
                raise ValueError('轮次解释行时间无效：' + what) from None
    native = row.get('native_duration_ms')
    if native is not None:
        if (not isinstance(native, dict) or native.get('unit') != 'ms'
                or native.get('state') not in ('known', 'conflict') or not isinstance(native.get('reason'), str)
                or (native.get('value') is not None
                    and (type(native['value']) is not int or isinstance(native['value'], bool) or native['value'] < 0))):
            raise ValueError('原生轮次耗时无效：' + what)
    keys = row.get('record_keys')
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise ValueError('轮次解释行引用无效：' + what)
    for key in keys:
        record = records_by_key.get(key)
        if record is None:
            raise ValueError('轮次解释行引用悬空或不属于本报告计量记录：' + what)
        if row['kind'] == 'turn':
            if record.get('interval_start'):
                raise ValueError('普通轮次行引用了累计区间记录：' + what)
            if record['session'] != row['session'] or record.get('turn') != row['turn']:
                raise ValueError('轮次解释行引用了其他会话/轮次的记录：' + what)
        else:
            if record['session'] != row['session']:
                raise ValueError('累计区间行引用了其他会话的记录：' + what)
            if not record.get('interval_start') or record['interval_start'] != row['interval_start'] \
                    or record.get('time') != row['interval_end']:
                raise ValueError('累计区间行引用与区间边界不一致：' + what)
            if (record.get('interval_turns') or []) != (row.get('interval_turns') or []):
                raise ValueError('累计区间行引用与涵盖轮次不一致：' + what)
    check_aggregate_row(row)


def check_wall_entry(wall):
    if (not isinstance(wall, dict) or wall.get('unit') != 's'
            or wall.get('state') not in ('known', 'unknown', 'conflict')
            or not isinstance(wall.get('basis'), str) or not isinstance(wall.get('reason'), str)
            or (wall.get('value') is not None
                and (type(wall['value']) not in (int, float) or isinstance(wall['value'], bool) or wall['value'] < 0))):
        raise ValueError('墙钟解释无效')


def check_activity(activity):
    if not isinstance(activity, dict) or not isinstance(activity.get('note'), str):
        raise ValueError('解释活动结构无效')
    if 'wall' in activity:
        check_wall_entry(activity['wall'])
    if 'sessions' in activity:
        if not isinstance(activity['sessions'], dict):
            raise ValueError('按会话墙钟解释无效')
        for sid, wall in activity['sessions'].items():
            if not isinstance(sid, str):
                raise ValueError('按会话墙钟解释无效')
            check_wall_entry(wall)
    durations = activity.get('durations')
    if not isinstance(durations, dict):
        raise ValueError('耗时覆盖解释无效')
    for granularity, bucket in durations.items():
        if granularity not in ('model_call', 'logical_request'):
            raise ValueError('耗时覆盖含未知粒度：' + str(granularity))
        if (not isinstance(bucket, dict) or not isinstance(bucket.get('label'), str)
                or bucket.get('unit') != 'ms' or bucket.get('state') not in DURATION_SUM_STATES
                or (bucket.get('total_ms') is not None
                    and (type(bucket['total_ms']) is not int or isinstance(bucket['total_ms'], bool) or bucket['total_ms'] < 0))):
            raise ValueError('耗时覆盖桶无效：' + granularity)
        for field in ('valid', 'missing', 'conflict', 'records'):
            if type(bucket.get(field)) is not int or bucket[field] < 0:
                raise ValueError('耗时覆盖计数无效：' + granularity)


def check_explanation(obj, scope):
    """Top-level explanation block (turns/internal/activity/relations/excluded)."""
    exp = obj['explanation']
    if not isinstance(exp, dict):
        raise ValueError('解释扩展结构无效')
    allowed = {'turns', 'internal', 'activity', 'relations', 'excluded'}
    if any(k not in allowed for k in exp):
        raise ValueError('解释扩展含未知内容')
    for name in ('turns', 'internal', 'relations', 'excluded'):
        if name in exp and not isinstance(exp[name], list):
            raise ValueError('解释扩展结构无效：' + name)
    if 'turns' in exp:
        metered_by_key = {r['key']: r for r in obj['records']}
        for i, row in enumerate(exp['turns']):
            check_turn_row(row, metered_by_key, 'turns ' + str(i))
    if 'activity' in exp:
        check_activity(exp['activity'])
    if 'internal' in exp:
        metered = {r['key']: r for r in obj['records']}
        for i, row in enumerate(exp['internal']):
            if (not isinstance(row, dict) or row.get('category') not in ('compaction', 'session_aux', 'other_internal', 'unknown')
                    or not isinstance(row.get('label'), str) or not isinstance(row.get('basis'), str)):
                raise ValueError('无效的内部分布行：internal ' + str(i))
            keys = row.get('record_keys')
            if (not isinstance(keys, list) or not all(isinstance(k, str) for k in keys)
                    or any(k not in metered for k in keys)):
                raise ValueError('内部分布行引用无效：internal ' + str(i))
            for key in keys:
                if metered[key]['group'] != 'internal':
                    raise ValueError('内部分布行混入非内部记录：internal ' + str(i))
            check_aggregate_row(row)
    if 'relations' in exp:
        for i, row in enumerate(exp['relations']):
            if (not isinstance(row, dict) or row.get('kind') not in ('parent_child', 'fork', 'inherited_copy')
                    or not isinstance(row.get('session'), str) or not isinstance(row.get('rule'), str)
                    or not isinstance(row.get('sources'), list) or not row['sources']):
                raise ValueError('无效的关系行：relations ' + str(i))
            for loc in row['sources']:
                check_source_loc(loc, '关系来源')
            if row['kind'] == 'parent_child' and not isinstance(row.get('parent'), str):
                raise ValueError('关系行缺少父会话：relations ' + str(i))
            if row['kind'] == 'fork' and not isinstance(row.get('forked_from'), str):
                raise ValueError('关系行缺少分叉来源：relations ' + str(i))
    if 'excluded' in exp:
        for i, row in enumerate(exp['excluded']):
            if not isinstance(row, dict) or not isinstance(row.get('reason'), str):
                raise ValueError('无效的排除行：excluded ' + str(i))
            if 'metrics' in row or 'record_keys' in row:
                raise ValueError('排除项不得携带计量小计或记录引用：excluded ' + str(i))
            if row.get('source') is not None:
                check_source_loc(row['source'], '排除项来源')


def check_aggregate_row(row):
    """Validate one aggregate payload (metrics, cache subset, call count) shared by all report rows."""
    for name in METRICS:
        metric = row['metrics'][name]
        if metric['value'] is not None and (type(metric['value']) is not int or metric['value'] < 0):
            raise ValueError('报告中的 token 必须为非负整数或 null')
        if metric['state'] not in ('known','partial','unknown'):
            raise ValueError('未知的指标状态')
        if not isinstance(metric['reasons'],list) or not all(isinstance(r, str) for r in metric['reasons']):
            raise ValueError('缺失指标原因')
    rate = row['cache_hit_rate']
    if not isinstance(rate, dict):
        raise ValueError('缺失缓存覆盖状态')
    if rate['value'] is not None and (type(rate['value']) not in (int, float) or not 0 <= rate['value'] <= 1):
        raise ValueError('缓存命中率必须为 0 到 1 的数值或 null')
    if rate['state'] not in ('known', 'partial', 'unknown', 'not_applicable'):
        raise ValueError('未知的缓存覆盖状态')
    if any(type(rate[k]) is not int or rate[k] < 0 for k in ('paired_records', 'input', 'cache_read')):
        raise ValueError('无效的缓存覆盖量')
    if row['call_count'] is not None and (type(row['call_count']) is not int or row['call_count'] < 0):
        raise ValueError('无效的调用数')


def check_localization(localization, scope):
    session = localization['session']
    if (not isinstance(session, dict) or not isinstance(session.get('id'), str) or session['id'] != scope['session']
            or not isinstance(session.get('confirmed_by'), str) or not isinstance(session.get('evidence'), str)):
        raise ValueError('定位证据缺少会话身份或与会话不一致')
    cutoff = localization['cutoff']
    if (not isinstance(cutoff, dict) or not isinstance(cutoff.get('source'), str)
            or cutoff.get('source') != scope['cutoff_source'] or cutoff.get('time') != scope['to']
            or not isinstance(cutoff.get('evidence'), str)):
        raise ValueError('定位证据缺少截止点或与截止点不一致')
    if not isinstance(localization.get('limits'), list) or not all(isinstance(x, str) for x in localization['limits']):
        raise ValueError('无效的定位限制')


def read_decoded(path):
    """Read a saved report file and decode it; validation stays in validate_report."""
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError('报告缺少必需结构或 JSON 无效') from exc


def check_support(support):
    if not isinstance(support, dict) or set(support) != set(INTERNAL_CATEGORIES):
        raise ValueError('缺失或多余的内部来源支持类别')
    for value in support.values():
        if (not isinstance(value, dict) or not isinstance(value.get('status'), str)
                or not isinstance(value.get('summary'), str) or not isinstance(value.get('evidence'), list)):
            raise ValueError('无效的内部来源支持说明')


def check_view_rows(view, dimension=None, records_by_key=None, session_id=None):
    if (not isinstance(view, dict) or type(view.get('available')) is not bool
            or not isinstance(view.get('reason'), str) or not isinstance(view['rows'], list)):
        raise ValueError('无效的展示视图')
    flags = ['record_keys' in row for row in view['rows']]
    if any(flags) and not all(flags):
        raise ValueError('视图行记录引用不完整：' + str(dimension))
    for row in view['rows']:
        if not isinstance(row.get('id'), str) or not isinstance(row.get('label'), str):
            raise ValueError('无效的视图行身份')
        check_aggregate_row(row)
        keys = row.get('record_keys')
        if keys is None:
            continue
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValueError('视图行记录引用无效：' + str(dimension))
        if records_by_key is None:
            continue
        for key in keys:
            record = records_by_key.get(key)
            if record is None:
                raise ValueError('视图行引用悬空记录：' + str(dimension))
            if dimension == 'model' and (record.get('model') or '模型未知') != row['id']:
                raise ValueError('视图行记录引用与维度不一致：' + str(dimension))
            if dimension == 'agent' and (record.get('agent') or '未知') != row['id']:
                raise ValueError('视图行记录引用与维度不一致：' + str(dimension))
            if dimension == 'turn' and _turn_identity_of(record, session_id) != row['id']:
                raise ValueError('视图行记录引用与维度不一致：' + str(dimension))
            if dimension == 'session' and record['session'] != row['id']:
                raise ValueError('视图行记录引用与维度不一致：' + str(dimension))


def _turn_identity_of(record, session_id):
    members = record.get('interval_turns')
    if members and len(set(members)) > 1:
        return '__multi_turn_interval__'
    if members:
        return members[0]
    owner = record['turn'] if record['session'] == session_id else record.get('owner_turn')
    return owner if owner else '__unknown__'


def check_views(views, obj=None):
    if not isinstance(views, dict) or set(views) != {'model', 'agent', 'turn'}:
        raise ValueError('缺失报告展示视图')
    records_by_key = None
    session_id = None
    if obj is not None:
        records_by_key = {r['key']: r for r in obj['records']}
        session_id = obj.get('scope', {}).get('session')
    for dimension, view in views.items():
        check_view_rows(view, dimension, records_by_key, session_id)


def check_alternates(alternates):
    for alt in alternates:
        if (not isinstance(alt, dict) or not isinstance(alt.get('kind'), str) or not isinstance(alt.get('path'), str)
                or not isinstance(alt.get('session'), str) or not isinstance(alt.get('note'), str)
                or type(alt.get('records')) is not int or alt['records'] < 0):
            raise ValueError('无效的补充来源说明')
        check_aggregate_row(alt)


def check_overview_scope(scope):
    if scope.get('kind') != 'overall':
        raise ValueError('整体报告缺少范围类型')
    sessions = scope.get('sessions')
    if not isinstance(sessions, list) or not all(isinstance(s, str) and s for s in sessions):
        raise ValueError('无效的整体会话集合')
    if not isinstance(scope.get('tz'), str) or not scope['tz']:
        raise ValueError('缺少显示时区')
    if scope.get('turns') is not None:
        raise ValueError('整体范围不支持轮次集合')


def check_overview_report(obj, scope):
    localization = obj['localization']
    sessions = localization['sessions']
    if (not isinstance(sessions, dict) or not isinstance(sessions.get('confirmed_by'), str)
            or not isinstance(sessions.get('evidence'), str) or type(sessions.get('count')) is not int
            or sessions['count'] != len(scope['sessions'])):
        raise ValueError('定位证据缺少会话集合或与会话集合不一致')
    cutoff = localization['cutoff']
    if (not isinstance(cutoff, dict) or not isinstance(cutoff.get('source'), str)
            or cutoff.get('source') != scope['cutoff_source'] or cutoff.get('time') != scope['to']
            or not isinstance(cutoff.get('evidence'), str)):
        raise ValueError('定位证据缺少截止点或与截止点不一致')
    if not isinstance(localization.get('limits'), list) or not all(isinstance(x, str) for x in localization['limits']):
        raise ValueError('无效的定位限制')
    for day in obj['days']:
        if not isinstance(day, dict) or not isinstance(day.get('date'), str):
            raise ValueError('无效的日趋势行')
        try:
            dt.date.fromisoformat(day['date'])
        except ValueError:
            raise ValueError('无效的日趋势日期')
        if type(day.get('sessions')) is not int or day['sessions'] < 0:
            raise ValueError('无效的日会话计数')
        for key in ('from', 'to'):
            value = day.get(key)
            if not isinstance(value, str):
                raise ValueError('日趋势行缺少交集范围')
            try:
                timestamp(value)
            except ValueError:
                raise ValueError('日趋势行交集范围无效') from None
        if timestamp(day['from']) >= timestamp(day['to']):
            raise ValueError('日趋势行交集范围无效')
        check_aggregate_row(day)
        allowed = {r['key'] for r in obj['records']}
        records_by_key = {r['key']: r for r in obj['records']}
        day_keys = day.get('record_keys')
        if day_keys is not None:
            if not isinstance(day_keys, list) or not all(isinstance(k, str) for k in day_keys):
                raise ValueError('日趋势行记录引用无效')
            if any(k not in allowed for k in day_keys):
                raise ValueError('日趋势行引用悬空记录')
        for key in ('by_model', 'by_session'):
            rows = day.get(key)
            if not isinstance(rows, list):
                raise ValueError('无效的日分布')
            member_union = set()
            for row in rows:
                if not isinstance(row.get('id'), str) or not isinstance(row.get('label'), str):
                    raise ValueError('无效的日分布行身份')
                check_aggregate_row(row)
                keys = row.get('record_keys')
                if keys is None:
                    continue
                if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                    raise ValueError('日分布行记录引用无效')
                if any(k not in allowed for k in keys):
                    raise ValueError('日分布行引用悬空记录')
                member_union |= set(keys)
                for rk in keys:
                    if key == 'by_session' and records_by_key[rk]['session'] != row['id']:
                        raise ValueError('日分布行引用与维度不一致')
                    if key == 'by_model' and (records_by_key[rk].get('model') or '模型未知') != row['id']:
                        raise ValueError('日分布行引用与维度不一致')
            if day_keys is not None and member_union != set(day_keys):
                raise ValueError('日分布成员与当日记录集合不一致')
    if not isinstance(obj.get('rankings'), dict) or set(obj['rankings']) != {'model', 'session'}:
        raise ValueError('缺失整体排行')
    allowed = {r['key']: r for r in obj['records']}
    for dimension, view in obj['rankings'].items():
        check_view_rows(view, dimension, allowed, None)
    index = obj.get('session_index')
    if not isinstance(index, list) or not all(isinstance(x, dict) and isinstance(x.get('id'), str) for x in index):
        raise ValueError('无效的会话索引')
    unbucketed = obj.get('unbucketed')
    if (not isinstance(unbucketed, dict) or type(unbucketed.get('records')) is not int
            or unbucketed['records'] < 0 or not isinstance(unbucketed.get('reasons'), list)
            or not all(isinstance(r, str) for r in unbucketed['reasons'])):
        raise ValueError('无效的无法归桶说明')
    ub_keys = unbucketed.get('record_keys')
    if ub_keys is not None and (not isinstance(ub_keys, list) or not all(isinstance(k, str) for k in ub_keys)
                                or any(k not in allowed for k in ub_keys)):
        raise ValueError('无法归桶记录引用无效')
    check_aggregate_row(unbucketed)


def validate_report(obj):
    """Validate one decoded report object against the shared v1/v2/v3 contract."""
    try:
        version = obj.get('format_version') if isinstance(obj, dict) else None
        if type(version) is not int or version not in (1, 2, 3):
            raise ValueError('不支持的报告格式版本')
        scope = obj['scope']
        if obj['harness'] not in ('codex','zcode'):
            raise ValueError('无效的 Harness 或会话')
        if version == 3:
            check_overview_scope(scope)
        elif not isinstance(scope['session'],str):
            raise ValueError('无效的 Harness 或会话')
        timestamp(scope['to'])
        if scope['from']:
            timestamp(scope['from'])
        if version != 3 and scope['turns'] is not None and (not isinstance(scope['turns'],list) or not all(isinstance(t,str) for t in scope['turns'])):
            raise ValueError('无效的轮次集合')
        if type(scope['main_only']) is not bool or type(scope['include_children']) is not bool or scope['main_only'] == scope['include_children']:
            raise ValueError('不一致的子代理策略')
        for row in obj['rows'] + [obj['summary']] + obj.get('details', []):
            check_aggregate_row(row)
        if version == 2:
            check_localization(obj['localization'], scope)
            check_support(obj['internal_support'])
            check_views(obj['views'], obj)
            for detail in obj.get('details', []):
                matches = [row for row in obj['views'][detail['dimension']]['rows'] if row['label'] == detail['name']]
                if len(matches) != 1 or any(matches[0][key] != detail[key] for key in ('metrics','cache_hit_rate','call_count')):
                    raise ValueError('明细与保存视图投影不一致')
            check_alternates(obj.get('alternate_sources', []))
        if version == 3:
            check_overview_report(obj, scope)
            check_support(obj['internal_support'])
            check_views(obj['views'], obj)
            check_alternates(obj.get('alternate_sources', []))
        for key in ('records','source_files','issues','tool_reports'):
            if not isinstance(obj[key],list):
                raise ValueError('缺失报告结构：' + key)
        records_by_key = {r['key']: r for r in obj['records']}
        for row in obj.get('rows', []):
            keys = row.get('record_keys')
            if keys is None:
                continue
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise ValueError('分组行记录引用无效')
            for key in keys:
                if key not in records_by_key:
                    raise ValueError('分组行引用悬空记录')
                if records_by_key[key]['group'] != row['group']:
                    raise ValueError('分组行记录引用与互斥分组不一致')
        if version == 1 and ('explanation' in obj
                             or any('explanation' in r for r in obj.get('records', []))
                             or any('explanation' in r for r in obj.get('unassigned_records', []))):
            raise ValueError('v1 报告不含解释扩展')
        check_records_explanation(obj['records'], 'records')
        check_records_explanation(obj.get('unassigned_records', []), 'unassigned_records')
        if 'explanation' in obj:
            check_explanation(obj, scope)
        for key in ('read_at','status','coverage'):
            if not isinstance(obj[key],str):
                raise ValueError('缺失报告元数据：' + key)
        descriptor = obj['input']
        if descriptor['kind'] not in ('jsonl','zcode_database') or not isinstance(descriptor['paths'],list) or not descriptor['paths'] or not all(isinstance(p,str) for p in descriptor['paths']):
            raise ValueError('无效的来源描述')
        if not isinstance(scope.get('cutoff_source'),str):
            raise ValueError('缺少截止点来源')
        def check_private_keys(value):
            if isinstance(value,dict):
                if any(k.lower() in ('request','response','headers','authorization','cookie','prompt','text','content','api_key','password') for k in value):
                    raise ValueError('报告包含合同以外的正文或认证字段')
                for child in value.values():
                    check_private_keys(child)
            elif isinstance(value,list):
                for child in value:
                    check_private_keys(child)
        check_private_keys(obj)
        # Ignore unrelated top-level additions: only the report contract is exported.
        allowed = {'format_version','harness','scope','input','read_at','status','scope_note','rows','summary','records',
                   'unassigned_records','inherited_records','issues','source_files','coverage','coverage_state','tool_reports','activity','details'}
        if version in (2, 3):
            allowed |= {'localization','internal_support','views','alternate_sources','explanation'}
        if version == 3:
            allowed |= {'days','rankings','session_index','unbucketed'}
        return {k:v for k,v in obj.items() if k in allowed}
    except (KeyError,TypeError) as exc:
        raise ValueError('报告缺少必需结构或 JSON 无效') from exc


def load_report(path):
    return validate_report(read_decoded(path))


def csv_text(result):
    rows = [dict(category='group',label=r['group'],**r) for r in result['rows']]
    rows.append(dict(category='summary',label='已记录小计',**result['summary']))
    rows += [dict(category='detail',label=r['name'],**r) for r in result.get('details',[])]
    if result.get('unassigned_records'):
        rows.append(dict(category='unassigned',label='会话辅助/未归属',**aggregate(result['unassigned_records'])))
    rows += [dict(category='alternate_source',label=f"{alt['kind']}:{alt['session']}",**alt)
             for alt in result.get('alternate_sources', [])]
    if result.get('scope', {}).get('kind') == 'overall':
        for day in result['days']:
            entry = dict(day)
            entry.update(category='day', label=day['date'])
            rows.append(entry)
        entry = dict(result['unbucketed'])
        entry.update(category='unbucketed', label='无法归桶')
        rows.append(entry)
        for dimension in ('model', 'session'):
            for row in result['rankings'][dimension]['rows']:
                entry = dict(row)
                entry['category'] = 'ranking_' + dimension
                rows.append(entry)
    for kind, label, count in explanation_lines(result):
        entry = aggregate([])
        entry.update(category='explanation_' + kind, label=label, call_count=count)
        rows.append(entry)
    columns = ['category','label','scope','status','read_at','sources','issues','call_count',
               'cache_hit_rate','cache_rate_state','paired_records','paired_input','paired_cache_read','tool_report_total']
    for m in METRICS:
        columns += [m,m+'_state',m+'_known_records',m+'_records',m+'_reasons']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    common = {'scope': json.dumps(result['scope'],ensure_ascii=False), 'status': result['status'], 'read_at':result['read_at'],
              'sources':json.dumps([s for r in result['records'] for s in r['sources']],ensure_ascii=False),
              'issues':json.dumps(result['issues'],ensure_ascii=False)}
    for row in rows:
        rate = row['cache_hit_rate']
        flat = dict(common,category=row['category'],label=row['label'],call_count=row['call_count'],
                    cache_hit_rate=rate['value'],cache_rate_state=rate['state'],paired_records=rate['paired_records'],
                    paired_input=rate['input'],paired_cache_read=rate['cache_read'])
        for name,metric in row['metrics'].items():
            flat[name]=metric['value']
            for suffix in ('state','known_records','records'):
                flat[name+'_'+suffix]=metric[suffix]
            flat[name+'_reasons']=json.dumps(metric['reasons'],ensure_ascii=False)
        writer.writerow(flat)
    for row in result['tool_reports']:
        writer.writerow(dict(common,category='tool_report',label=row['agent'],tool_report_total=row['total'],sources=json.dumps(row['source'],ensure_ascii=False)))
    return output.getvalue()


def render(result, format_name):
    if format_name == 'json':
        return json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if format_name == 'csv':
        return csv_text(result)
    return markdown(result)


def export(result, format_name, destination, extra_sources=()):
    target=Path(destination).expanduser().resolve()
    sources=set(result['source_files']) | set(extra_sources) | set(result.get('input',{}).get('paths',[]))
    for name in sources:
        source=Path(name).expanduser().resolve()
        if target == source or target.exists() and source.exists() and os.path.samefile(target,source):
            raise ValueError('导出目标与输入来源冲突；源文件保持不变')
    content=render(result,format_name)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.token-audit-',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:
            stream.write(content)
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
