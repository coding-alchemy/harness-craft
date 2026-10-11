"""Report serialization and explicit export; loading never reads telemetry."""
import csv
import datetime as dt
import io
import json
import os
from decimal import Decimal
from pathlib import Path
import tempfile
from .analysis import canon_decimal, component_amount, display_amount, exact_decimal_add, rule_component_prices, validate_pricing_config, _component_tokens, PRICE_TEXT
from .core import GRANULARITIES, INTERNAL_CATEGORIES, METRICS, aggregate, explanation_lines, markdown, timestamp, timezone_of, _perf_ratio


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


def _cost_totals(entries):
    """Exact per-currency Decimal totals over one set of pricing entries (audit recompute)."""
    totals = {}
    for entry in entries:
        if not entry['components']:
            continue
        bucket = totals.setdefault(entry['currency'], {'amount': Decimal(0), 'components': {}})
        for component in entry['components']:
            cell = bucket['components'].setdefault(component['name'], {'tokens': 0, 'amount': Decimal(0)})
            cell['tokens'] += component['tokens']
            cell['amount'] = exact_decimal_add(cell['amount'], component['amount'])
            bucket['amount'] = exact_decimal_add(bucket['amount'], component['amount'])
    return totals


def _check_projection_currencies(saved, expected, what):
    """One saved projection member's currency map must equal the entry recompute exactly."""
    if not isinstance(saved, dict) or set(saved) != set(expected):
        raise ValueError('费用投影币种集合与逐记录计价不一致：' + what)
    for currency, bucket in saved.items():
        expected_bucket = expected[currency]
        if not isinstance(bucket, dict) or set(bucket) != {'amount', 'components'}:
            raise ValueError('费用投影币种结构无效：' + what)
        if bucket['amount'] != canon_decimal(expected_bucket['amount']):
            raise ValueError('费用投影金额与逐记录计价不一致：' + what)
        components = bucket['components']
        if not isinstance(components, dict) or set(components) != set(expected_bucket['components']):
            raise ValueError('费用投影分项集合不一致：' + what)
        for name, cell in components.items():
            expected_cell = expected_bucket['components'][name]
            if not isinstance(cell, dict) or set(cell) != {'tokens', 'amount'} \
                    or type(cell.get('tokens')) is not int or cell['tokens'] != expected_cell['tokens'] \
                    or cell.get('amount') != canon_decimal(expected_cell['amount']):
                raise ValueError('费用投影分项与逐记录计价不一致：' + what)


def check_cost_projections(obj, entries, projections):
    """v3 cost projections: members reference this report's own record keys and each
    currency bucket recomputes exactly from the same per-record priced components."""
    if not isinstance(projections, dict) or set(projections) != {'model', 'session', 'day', 'unbucketed'}:
        raise ValueError('费用投影结构无效')
    entry_by_key = {entry['record_key']: entry for entry in entries}
    session_of = {record['key']: record['session'] for record in obj['records']}
    priced = [entry for entry in entries if entry['components']]

    def check_member(member, keys, what):
        if not isinstance(member, dict) or 'currencies' not in member or 'record_keys' not in member:
            raise ValueError('费用投影成员结构无效：' + what)
        saved_keys = member['record_keys']
        if not isinstance(saved_keys, list) or not all(isinstance(k, str) for k in saved_keys):
            raise ValueError('费用投影成员记录引用无效：' + what)
        if len(set(saved_keys)) != len(saved_keys) or set(saved_keys) != set(keys):
            raise ValueError('费用投影成员记录集合不一致：' + what)
        subset = [entry_by_key[key] for key in saved_keys]
        _check_projection_currencies(member['currencies'], _cost_totals(subset), what)

    model_groups = {}
    for entry in priced:
        identity = entry['identity']
        model_groups.setdefault((identity['provider'], identity['model']), []).append(entry['record_key'])
    members = projections['model']
    if not isinstance(members, list) or len(members) != len(model_groups):
        raise ValueError('模型费用投影成员集合与逐记录计价不一致')
    seen = set()
    for i, member in enumerate(members):
        what = 'model ' + str(i)
        identity = member.get('identity') if isinstance(member, dict) else None
        if not isinstance(identity, dict) or set(identity) != {'provider', 'model'} \
                or not all(isinstance(identity[k], str) and identity[k] for k in ('provider', 'model')):
            raise ValueError('模型费用投影身份无效：' + what)
        key = (identity['provider'], identity['model'])
        if key in seen or key not in model_groups:
            raise ValueError('模型费用投影成员重复或身份无已计价记录：' + what)
        seen.add(key)
        check_member(member, model_groups[key], what)
    session_groups = {}
    for entry in priced:
        session_groups.setdefault(session_of[entry['record_key']], []).append(entry['record_key'])
    members = projections['session']
    if not isinstance(members, list) or len(members) != len(session_groups):
        raise ValueError('会话费用投影成员集合与逐记录计价不一致')
    seen = set()
    for i, member in enumerate(members):
        what = 'session ' + str(i)
        sid = member.get('session') if isinstance(member, dict) else None
        if not isinstance(sid, str) or sid in seen or sid not in session_groups:
            raise ValueError('会话费用投影成员重复或身份无已计价记录：' + what)
        seen.add(sid)
        check_member(member, session_groups[sid], what)
    days = projections['day']
    report_days = obj['days']
    if not isinstance(days, list) or len(days) != len(report_days):
        raise ValueError('日期费用投影与本报告日趋势不一致')
    for i, member in enumerate(days):
        what = 'day ' + str(i)
        date = member.get('date') if isinstance(member, dict) else None
        if date != report_days[i]['date'] or [m['date'] for m in days] != sorted(m['date'] for m in days):
            raise ValueError('日期费用投影日期与本报告日趋势不一致：' + what)
        check_member(member, report_days[i]['record_keys'], what)
    check_member(projections['unbucketed'], obj['unbucketed']['record_keys'], 'unbucketed')
    # The day members plus the unbucketed item partition every metered record, so the
    # projections reconcile against the per-currency summary instead of adding into it.
    partition = set(projections['unbucketed']['record_keys'])
    for member in days:
        partition |= set(member['record_keys'])
    if partition != {record['key'] for record in obj['records']}:
        raise ValueError('日期费用投影与无法归日项未覆盖本报告全部计量记录')


PERF_METRICS = ('ttft', 'throughput', 'tool_duration')
PERF_REQUIRED_METRICS = ('ttft', 'throughput')
PERF_EXCLUSION_KINDS = ('missing', 'conflict', 'unsupported', 'range')
PERF_SUPPORT_STATES = ('supported', 'source_not_provided', 'not_checked')
PERF_COMPLETION_STATES = ('ended_before_cutoff', 'ended_after_cutoff', 'no_end_evidence')
PERF_UNITS = {'ttft': {'numerator': 'ms', 'denominator': '样本', 'value': 'ms'},
              'throughput': {'numerator': 'token', 'denominator': 'ms', 'value': 'token/s'},
              'tool_duration': {'numerator': 'ns', 'denominator': '样本', 'value': 'ms'}}
TOOL_SAMPLE_STATES = ('completed', 'failed')
PERF_MS = dt.timedelta(milliseconds=1)


def _check_perf_display(display, what):
    if (not isinstance(display, dict) or set(display) != {'decimals', 'rounding', 'note'}
            or display.get('decimals') != 2 or display.get('rounding') != 'half_up'
            or not isinstance(display.get('note'), str)):
        raise ValueError('性能显示精度说明无效：' + what)


def _check_perf_sample(sample, name, records_by_key, what):
    if not isinstance(sample, dict):
        raise ValueError('性能样本结构无效：' + what)
    common = {'key', 'record_key', 'session', 'turn', 'owner_session', 'owner_turn', 'granularity',
              'provider', 'model', 'precision', 'source'}
    expected = common | ({'value', 'basis', 'started_at', 'first_token_at', 'native_ttft_ms',
                          'completed_at', 'completion'} if name == 'ttft'
                         else {'output', 'interval_ms', 'basis', 'first_token_at', 'completed_at'})
    if set(sample) != expected:
        raise ValueError('性能样本结构无效：' + what)
    if not isinstance(sample['key'], str):
        raise ValueError('性能样本缺少稳定样本键：' + what)
    record_key = sample['record_key']
    if record_key is not None and (not isinstance(record_key, str) or record_key not in records_by_key):
        raise ValueError('性能样本引用了本报告不存在的 token 记录（悬空引用）：' + what)
    if not isinstance(sample['session'], str) or not isinstance(sample['owner_session'], str):
        raise ValueError('性能样本会话/归属无效：' + what)
    for field in ('turn', 'owner_turn'):
        if sample[field] is not None and not isinstance(sample[field], str):
            raise ValueError('性能样本轮次/归属无效：' + what)
    if sample['granularity'] not in GRANULARITIES:
        raise ValueError('性能样本粒度未知：' + what)
    if sample['provider'] is not None and not isinstance(sample['provider'], str):
        raise ValueError('性能样本供应商无效：' + what)
    if not isinstance(sample['model'], str) or not sample['model']:
        raise ValueError('性能样本模型无效：' + what)
    if sample['precision'] != 'ms' or sample['basis'] not in ('native', 'derived'):
        raise ValueError('性能样本精度/依据无效：' + what)
    check_source_loc(sample['source'], '性能样本来源')

    def time_of(field, required=True):
        value = sample[field]
        if value is None:
            if required:
                raise ValueError('性能样本缺少事件时间 ' + field + '：' + what)
            return None
        if not isinstance(value, str):
            raise ValueError('性能样本事件时间无效：' + what)
        try:
            return timestamp(value)
        except ValueError:
            raise ValueError('性能样本事件时间无效：' + what) from None

    def nonneg_int(field, minimum=0):
        value = sample[field]
        if type(value) is not int or value < minimum:
            raise ValueError('性能样本数值无效（非有限或负数不入有效值）：' + what)
        return value

    first = time_of('first_token_at')
    time_of('completed_at', required=False)
    if name == 'ttft':
        began = time_of('started_at')
        value = nonneg_int('value')
        native = sample['native_ttft_ms']
        if native is not None and (type(native) is not int or native < 0):
            raise ValueError('性能样本原生 TTFT 无效：' + what)
        if value != (first - began) // PERF_MS:
            raise ValueError('性能样本 TTFT 与事件时间差矛盾（坏样本冲突）：' + what)
        if (native is None) != (sample['basis'] == 'derived') or native is not None and native != value:
            raise ValueError('性能样本原生 TTFT 与推导值/依据矛盾（坏样本冲突）：' + what)
        if sample['completion'] not in PERF_COMPLETION_STATES:
            raise ValueError('性能样本完成状态未知：' + what)
        return value, 1
    output = nonneg_int('output')
    interval = nonneg_int('interval_ms', 1)
    completed = time_of('completed_at')
    if interval != (completed - first) // PERF_MS:
        raise ValueError('性能样本观测区间与事件时间差矛盾（坏样本冲突）：' + what)
    return output, interval


def _tool_time(value, what, required=False):
    if value is None:
        if required:
            raise ValueError('工具样本缺少事件时间：' + what)
        return None
    if not isinstance(value, str):
        raise ValueError('工具样本事件时间无效：' + what)
    try:
        return timestamp(value)
    except ValueError:
        raise ValueError('工具样本事件时间无效：' + what) from None


def _check_tool_sample(sample, what):
    """One saved tool-duration sample: stable identity, finished status, exact ns value
    with its native/derived basis, and separately saved scheduling endpoints."""
    expected = {'key', 'record_key', 'session', 'turn', 'owner_session', 'owner_turn', 'category', 'status',
                'value', 'basis', 'precision', 'native_duration_ns',
                'exec_start', 'exec_end', 'dispatch_start', 'dispatch_end', 'completed_at', 'source'}
    if not isinstance(sample, dict) or set(sample) != expected:
        raise ValueError('工具样本结构无效：' + what)
    if not isinstance(sample['key'], str):
        raise ValueError('工具样本缺少稳定样本键：' + what)
    if sample['record_key'] is not None:
        raise ValueError('工具样本不得引用 token 记录（独立通道，不伪造引用）：' + what)
    if not isinstance(sample['session'], str) or not isinstance(sample['owner_session'], str):
        raise ValueError('工具样本会话/归属无效：' + what)
    for field in ('turn', 'owner_turn'):
        if sample[field] is not None and not isinstance(sample[field], str):
            raise ValueError('工具样本轮次/归属无效：' + what)
    if not isinstance(sample['category'], str) or not sample['category']:
        raise ValueError('工具样本类别无效：' + what)
    if sample['status'] not in TOOL_SAMPLE_STATES:
        raise ValueError('工具样本状态无效（仅已完成/已失败执行携带耗时）：' + what)
    value = sample['value']
    if type(value) is not int or value < 0:
        raise ValueError('工具样本耗时无效（非有限或负数不入有效值）：' + what)
    if sample['basis'] not in ('native', 'derived') or sample['precision'] not in ('ns', 'ms'):
        raise ValueError('工具样本依据/精度无效：' + what)
    native = sample['native_duration_ns']
    if sample['basis'] == 'native':
        if type(native) is not int or native != value:
            raise ValueError('工具样本原生耗时与有效值矛盾（坏样本冲突）：' + what)
    elif native is not None:
        raise ValueError('推导耗时样本不得携带原生值（坏样本冲突）：' + what)
    exec_start = _tool_time(sample['exec_start'], what + ' exec_start')
    exec_end = _tool_time(sample['exec_end'], what + ' exec_end')
    _tool_time(sample['completed_at'], what + ' completed_at', required=True)
    if (exec_start is None) != (exec_end is None):
        raise ValueError('工具样本执行起止必须成对出现：' + what)
    if exec_start is not None:
        span = (exec_end - exec_start) // PERF_MS
        if span < 0:
            raise ValueError('工具样本执行起止逆序：' + what)
        if sample['basis'] == 'derived' and value != span * 1000000:
            raise ValueError('工具样本推导耗时与执行起止跨度矛盾（坏样本冲突）：' + what)
    dispatch_start = _tool_time(sample['dispatch_start'], what + ' dispatch_start')
    dispatch_end = _tool_time(sample['dispatch_end'], what + ' dispatch_end')
    if (dispatch_start is None) != (dispatch_end is None):
        raise ValueError('工具样本调度起止必须成对出现：' + what)
    if dispatch_start is not None and dispatch_end < dispatch_start:
        raise ValueError('工具样本调度起止逆序：' + what)
    check_source_loc(sample['source'], '工具样本来源')
    return value


def _tool_wall_of(samples):
    """Recompute the saved span envelope from the samples themselves (audit rule)."""
    if not samples:
        return 'unknown', None
    begins, ends, missing = [], [], False
    for sample in samples:
        start_text = sample['dispatch_start'] or sample['exec_start']
        end_text = sample['dispatch_end'] or sample['exec_end']
        if start_text is None or end_text is None:
            missing = True
            continue
        if timestamp(end_text) < timestamp(start_text):
            return 'conflict', None
        begins.append(timestamp(start_text))
        ends.append(timestamp(end_text))
    if missing:
        return 'unknown', None
    return 'known', (max(ends) - min(begins)) // PERF_MS * 1000000


def check_tool_duration(obj, metric, zone):
    """Tool-execution-duration metric: independent channel (samples never reference token
    records), exact ns sums, the span envelope recomputed from samples, and unmerged
    supplements listed with reasons."""
    what = '性能指标 tool_duration'
    support = metric['support']
    samples = metric['samples']
    aggregate = metric['aggregate']
    projections = metric['projections']
    if not isinstance(projections, dict) or set(projections) != {'category', 'session', 'day'}:
        raise ValueError('工具指标投影结构无效：' + what)
    if (not isinstance(aggregate, dict)
            or set(aggregate) != {'candidates', 'valid', 'excluded', 'excluded_by_kind',
                                  'exclusion_reasons', 'numerator', 'denominator', 'no_token_record', 'display',
                                  'wall', 'supplements'}):
        raise ValueError('工具指标聚合结构无效：' + what)
    _check_perf_display(aggregate['display'], what)
    wall = aggregate['wall']
    if (not isinstance(wall, dict) or set(wall) != {'value', 'state', 'unit', 'basis', 'reason'}
            or wall['unit'] != 'ns' or wall['state'] not in ('known', 'unknown', 'conflict')
            or not isinstance(wall['basis'], str) or not wall['basis']
            or not isinstance(wall['reason'], str) or not wall['reason']
            or (wall['value'] is not None and (type(wall['value']) is not int or wall['value'] < 0))):
        raise ValueError('工具跨度包络无效：' + what)
    supplements = aggregate['supplements']
    if not isinstance(supplements, list):
        raise ValueError('工具补充项结构无效：' + what)
    for i, item in enumerate(supplements):
        if (not isinstance(item, dict) or set(item) != {'key', 'session', 'reason', 'source'}
                or not isinstance(item['key'], str) or not isinstance(item['session'], str)
                or not isinstance(item['reason'], str) or not item['reason']):
            raise ValueError('工具补充项结构无效：' + what + ' supplements ' + str(i))
        check_source_loc(item['source'], '工具补充项来源')
    if support['status'] != 'supported':
        if not support['reason'] or samples or any(projections[d] for d in ('category', 'session', 'day')):
            raise ValueError('不可用指标不得携带有效样本或投影：' + what)
        if aggregate['valid'] or aggregate['excluded'] or aggregate['numerator'] or aggregate['denominator'] \
                or aggregate['no_token_record'] or aggregate['exclusion_reasons'] \
                or any(aggregate['excluded_by_kind'].get(k) for k in PERF_EXCLUSION_KINDS):
            raise ValueError('不可用指标不得携带有效值：' + what)
        if type(aggregate['candidates']) is not int or aggregate['candidates'] < 0:
            raise ValueError('性能候选计数无效：' + what)
        if wall['value'] is not None or wall['state'] != 'unknown':
            raise ValueError('不可用指标不得携带跨度包络值：' + what)
        return
    keys = [s['key'] if isinstance(s, dict) else None for s in samples]
    if len(set(keys)) != len(keys):
        raise ValueError('工具样本键重复：' + what)
    if keys != sorted(keys):
        raise ValueError('工具样本顺序无效（须按键排序）：' + what)
    total = 0
    for i, sample in enumerate(samples):
        total += _check_tool_sample(sample, what + ' 样本 ' + str(i))
    counts = {'candidates': aggregate['candidates'], 'valid': aggregate['valid'],
              'excluded': aggregate['excluded'], 'numerator': aggregate['numerator'],
              'denominator': aggregate['denominator'], 'no_token_record': aggregate['no_token_record']}
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError('工具聚合计数无效：' + what)
    if counts['valid'] != len(samples) or counts['candidates'] != counts['valid'] + counts['excluded']:
        raise ValueError('工具候选/有效/排除计数不一致：' + what)
    if counts['numerator'] != total or counts['denominator'] != len(samples) \
            or counts['no_token_record'] != len(samples):
        raise ValueError('工具聚合分子/分母与样本重算不一致：' + what)
    kinds = aggregate['excluded_by_kind']
    if (not isinstance(kinds, dict) or set(kinds) != set(PERF_EXCLUSION_KINDS)
            or any(type(kinds[k]) is not int or kinds[k] < 0 for k in PERF_EXCLUSION_KINDS)
            or sum(kinds.values()) != counts['excluded']):
        raise ValueError('工具排除分类计数不一致：' + what)
    reasons = aggregate['exclusion_reasons']
    if (not isinstance(reasons, dict) or any(not isinstance(r, str) or type(c) is not int or c < 1
                                             for r, c in reasons.items())
            or sum(reasons.values()) != counts['excluded']):
        raise ValueError('工具排除原因计数不一致：' + what)
    state, value = _tool_wall_of(samples)
    if wall['state'] != state or wall['value'] != value:
        raise ValueError('工具跨度包络与样本重算不一致：' + what)

    def member_check(members, key_of, label_field, label_check, sorted_of):
        groups = {}
        for sample in samples:
            groups.setdefault(key_of(sample), []).append(sample['key'])
        if not isinstance(members, list) or len(members) != len(groups):
            raise ValueError('工具投影成员集合与样本重算不一致：' + what)
        seen = set()
        for member in members:
            if not isinstance(member, dict) or set(member) != {label_field, 'sample_keys', 'numerator', 'denominator'}:
                raise ValueError('工具投影成员结构无效：' + what)
            label = label_check(member[label_field])
            if label in seen or label not in groups:
                raise ValueError('工具投影成员重复或无对应样本：' + what)
            seen.add(label)
            if member['sample_keys'] != sorted(groups[label]):
                raise ValueError('工具投影成员样本集合与重算不一致：' + what)
            numerator = sum(s['value'] for s in samples if s['key'] in groups[label])
            if member['numerator'] != numerator or member['denominator'] != len(groups[label]) \
                    or type(member['numerator']) is not int or type(member['denominator']) is not int:
                raise ValueError('工具投影成员分子/分母与样本重算不一致：' + what)
        if [label_check(m[label_field]) for m in members] != sorted(seen, key=sorted_of):
            raise ValueError('工具投影成员顺序无效：' + what)

    def text_label(label):
        if not isinstance(label, str) or not label:
            raise ValueError('工具投影成员标签无效：' + what)
        return label

    member_check(projections['category'], lambda s: s['category'], 'category', text_label, lambda k: k)
    member_check(projections['session'], lambda s: s['session'], 'session', text_label, lambda k: k)
    member_check(projections['day'],
                 lambda s: timestamp(s['completed_at']).astimezone(zone).date().isoformat(),
                 'date', text_label, lambda k: k)


def check_performance(obj, perf):
    """Performance section of the v2/v3 analysis extension: per-metric independent valid
    sets with exact numerator/denominator, regenerated model/session/day projections and
    exclusion accounting. Conflicting samples, dangling record references, non-finite or
    negative values in a valid set and aggregate inconsistencies are rejected outright."""
    if (not isinstance(perf, dict)
            or set(perf) != {'harness', 'source_kind', 'tz', 'note', 'metrics'}):
        raise ValueError('性能分析扩展结构无效')
    if perf['harness'] != obj['harness'] or perf['source_kind'] != obj['input']['kind']:
        raise ValueError('性能分析与本报告 Harness/来源入口不一致')
    tz = perf['tz']
    if (not isinstance(tz, dict) or set(tz) != {'name', 'evidence'}
            or not isinstance(tz.get('name'), str) or not tz['name']
            or not isinstance(tz.get('evidence'), str) or not tz['evidence']):
        raise ValueError('性能分析日分布时区说明无效')
    zone = timezone_of(tz['name'])
    if not isinstance(perf['note'], str) or not isinstance(perf['metrics'], dict) \
            or not set(PERF_REQUIRED_METRICS) <= set(perf['metrics']) \
            or not set(perf['metrics']) <= set(PERF_METRICS):
        raise ValueError('性能分析指标结构无效')
    records_by_key = {r['key']: r for r in obj['records']}
    for name in PERF_METRICS:
        if name not in perf['metrics']:
            # Reports saved before the tool metric stay legal; the missing section is
            # displayed as "not saved", never backfilled with zeros.
            continue
        what = '性能指标 ' + name
        metric = perf['metrics'][name]
        if not isinstance(metric, dict) or set(metric) != {'label', 'definition', 'admission', 'unit', 'units',
                                                           'overhead', 'support', 'samples', 'aggregate', 'projections'}:
            raise ValueError('性能指标结构无效：' + what)
        for field in ('label', 'definition', 'admission'):
            if not isinstance(metric[field], str) or not metric[field]:
                raise ValueError('性能指标事件定义无效：' + what)
        if metric['unit'] != PERF_UNITS[name]['value'] or metric['units'] != PERF_UNITS[name]:
            raise ValueError('性能指标单位无效：' + what)
        if name != 'throughput' and metric['overhead'] is not None \
                or name == 'throughput' and (not isinstance(metric['overhead'], str) or not metric['overhead']):
            raise ValueError('性能指标开销标注无效：' + what)
        support = metric['support']
        if (not isinstance(support, dict) or set(support) != {'status', 'reason'}
                or support['status'] not in PERF_SUPPORT_STATES or not isinstance(support['reason'], str)):
            raise ValueError('性能指标支持状态无效：' + what)
        if not isinstance(metric['samples'], list):
            raise ValueError('性能指标样本/投影结构无效：' + what)
        if name == 'tool_duration':
            check_tool_duration(obj, metric, zone)
            continue
        samples = metric['samples']
        aggregate = metric['aggregate']
        projections = metric['projections']
        if not isinstance(samples, list) or not isinstance(projections, dict) \
                or set(projections) != {'model', 'session', 'day'}:
            raise ValueError('性能指标样本/投影结构无效：' + what)
        if (not isinstance(aggregate, dict)
                or set(aggregate) != {'candidates', 'valid', 'excluded', 'excluded_by_kind',
                                      'exclusion_reasons', 'numerator', 'denominator', 'no_token_record', 'display'}):
            raise ValueError('性能聚合结构无效：' + what)
        _check_perf_display(aggregate['display'], what)
        if support['status'] != 'supported':
            if not support['reason'] or samples or any(projections[d] for d in ('model', 'session', 'day')):
                raise ValueError('不可用指标不得携带有效样本或投影：' + what)
            if aggregate['valid'] or aggregate['excluded'] or aggregate['numerator'] or aggregate['denominator'] \
                    or aggregate['no_token_record'] or aggregate['exclusion_reasons'] \
                    or any(aggregate['excluded_by_kind'].get(k) for k in PERF_EXCLUSION_KINDS):
                raise ValueError('不可用指标不得携带有效值：' + what)
            if type(aggregate['candidates']) is not int or aggregate['candidates'] < 0:
                raise ValueError('性能候选计数无效：' + what)
            continue
        keys = [s['key'] if isinstance(s, dict) else None for s in samples]
        if len(set(keys)) != len(keys):
            raise ValueError('性能样本键重复：' + what)
        if keys != sorted(keys):
            raise ValueError('性能样本顺序无效（须按键排序）：' + what)
        totals = {'numerator': 0, 'denominator': 0, 'no_token_record': 0}
        for i, sample in enumerate(samples):
            numerator, denominator = _check_perf_sample(sample, name, records_by_key, what + ' 样本 ' + str(i))
            totals['numerator'] += numerator
            totals['denominator'] += denominator
            totals['no_token_record'] += sample['record_key'] is None
        counts = {'candidates': aggregate['candidates'], 'valid': aggregate['valid'],
                  'excluded': aggregate['excluded'], 'numerator': aggregate['numerator'],
                  'denominator': aggregate['denominator'], 'no_token_record': aggregate['no_token_record']}
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise ValueError('性能聚合计数无效：' + what)
        if counts['valid'] != len(samples) or counts['candidates'] != counts['valid'] + counts['excluded']:
            raise ValueError('性能候选/有效/排除计数不一致：' + what)
        if counts['numerator'] != totals['numerator'] or counts['denominator'] != totals['denominator']:
            raise ValueError('性能聚合分子/分母与样本重算不一致：' + what)
        if counts['no_token_record'] != totals['no_token_record']:
            raise ValueError('性能无 token 记录样本计数不一致：' + what)
        kinds = aggregate['excluded_by_kind']
        if (not isinstance(kinds, dict) or set(kinds) != set(PERF_EXCLUSION_KINDS)
                or any(type(kinds[k]) is not int or kinds[k] < 0 for k in PERF_EXCLUSION_KINDS)
                or sum(kinds.values()) != counts['excluded']):
            raise ValueError('性能排除分类计数不一致：' + what)
        reasons = aggregate['exclusion_reasons']
        if (not isinstance(reasons, dict) or any(not isinstance(r, str) or type(c) is not int or c < 1
                                                 for r, c in reasons.items())
                or sum(reasons.values()) != counts['excluded']):
            raise ValueError('性能排除原因计数不一致：' + what)

        def member_check(members, key_of, label_of, label_field, sorted_of):
            groups = {}
            for sample in samples:
                groups.setdefault(key_of(sample), []).append(sample['key'])
            if not isinstance(members, list) or len(members) != len(groups):
                raise ValueError('性能投影成员集合与样本重算不一致：' + what)
            seen = set()
            for member in members:
                if not isinstance(member, dict) or set(member) != {label_field, 'sample_keys', 'numerator', 'denominator'}:
                    raise ValueError('性能投影成员结构无效：' + what)
                label = member[label_field]
                if label_field == 'identity':
                    if not isinstance(label, dict) or set(label) != {'provider', 'model'} \
                            or (label['provider'] is not None and not isinstance(label['provider'], str)) \
                            or not isinstance(label['model'], str) or not label['model']:
                        raise ValueError('性能投影模型身份无效：' + what)
                elif not isinstance(label, str) or not label:
                    raise ValueError('性能投影成员标签无效：' + what)
                key = label_of(label)
                if key in seen or key not in groups:
                    raise ValueError('性能投影成员重复或无对应样本：' + what)
                seen.add(key)
                subset = sorted(groups[key])
                if member['sample_keys'] != subset:
                    raise ValueError('性能投影成员样本集合与重算不一致：' + what)
                numerator = denominator = 0
                for sample in samples:
                    if sample['key'] in groups[key]:
                        part = (sample['value'], 1) if name == 'ttft' else (sample['output'], sample['interval_ms'])
                        numerator += part[0]
                        denominator += part[1]
                if member['numerator'] != numerator or member['denominator'] != denominator \
                        or type(member['numerator']) is not int or type(member['denominator']) is not int:
                    raise ValueError('性能投影成员分子/分母与样本重算不一致：' + what)
            if [label_of(m[label_field]) for m in members] != sorted(seen, key=sorted_of):
                raise ValueError('性能投影成员顺序无效：' + what)

        member_check(projections['model'], lambda s: (s['provider'], s['model']),
                     lambda label: (label['provider'], label['model']), 'identity', lambda k: (k[0] or '', k[1]))
        member_check(projections['session'], lambda s: s['session'], lambda label: label, 'session', lambda k: k)
        event_of = (lambda s: s['first_token_at']) if name == 'ttft' else (lambda s: s['completed_at'])
        member_check(projections['day'],
                     lambda s: timestamp(event_of(s)).astimezone(zone).date().isoformat(),
                     lambda label: label, 'date', lambda k: k)


def check_analysis(obj):
    """v2/v3 optional `analysis` extension (internal schema version 1): an always-saved
    performance section plus, for priced queries, the config snapshot, per-record pricing
    and per-currency summary, all cross-checked against this report's own metered records.
    Unknown versions or damaged/conflicting structures are rejected outright; amounts and
    unit prices are validated from their decimal strings."""
    ext = obj['analysis']
    if not isinstance(ext, dict) or type(ext.get('schema_version')) is not int or ext['schema_version'] != 1 \
            or not set(ext) <= {'schema_version', 'cost', 'performance'} \
            or not {'cost', 'performance'} & set(ext):
        raise ValueError('未知的分析扩展版本或结构')
    if 'cost' in ext:
        check_cost(obj, ext['cost'])
    if 'performance' in ext:
        check_performance(obj, ext['performance'])


def check_cost(obj, cost):
    overall = obj['format_version'] == 3
    # Projections are required on overall (v3) reports and forbidden on single-session ones.
    expected_cost_keys = {'config', 'records', 'summary', 'projections'} if overall \
        else {'config', 'records', 'summary'}
    if not isinstance(cost, dict) or set(cost) != expected_cost_keys:
        raise ValueError('费用分析扩展结构无效')
    config = validate_pricing_config(cost['config'])
    rules = {rule['id']: rule for rule in config['rules']}
    aliases = {alias['id'] for alias in config['aliases']}
    entries = cost['records']
    if not isinstance(entries, list):
        raise ValueError('费用分析逐记录计价必须是数组')
    metered_by_key = {r['key']: r for r in obj['records']}
    keys = []
    for i, entry in enumerate(entries):
        what = 'analysis.records ' + str(i)
        if not isinstance(entry, dict) \
                or set(entry) - {'record_key', 'identity', 'status', 'currency', 'matched', 'components', 'unpriced', 'conflicts'}:
            raise ValueError('逐记录计价结构无效：' + what)
        key = entry.get('record_key')
        if not isinstance(key, str):
            raise ValueError('逐记录计价缺少记录引用：' + what)
        keys.append(key)
        status = entry.get('status')
        if status not in ('priced', 'partially_priced', 'unpriced', 'rule_conflict'):
            raise ValueError('逐记录计价状态未知：' + what)
        identity = entry.get('identity')
        if identity is not None and (not isinstance(identity, dict) or set(identity) != {'provider', 'model'}
                                     or not all(isinstance(identity[k], str) and identity[k] for k in ('provider', 'model'))):
            raise ValueError('逐记录计价身份无效：' + what)
        matched = entry.get('matched')
        rule = None
        if matched is not None:
            if not isinstance(matched, dict) or set(matched) != {'rule_id', 'alias_id'}:
                raise ValueError('逐记录计价命中结构无效：' + what)
            rule = rules.get(matched['rule_id'])
            if rule is None:
                raise ValueError('逐记录计价引用了配置中不存在的规则：' + what)
            if matched['alias_id'] is not None and matched['alias_id'] not in aliases:
                raise ValueError('逐记录计价引用了配置中不存在的别名：' + what)
            record = metered_by_key.get(key)
            if identity is None or record is None \
                    or identity != {'provider': record.get('provider'), 'model': record.get('model')}:
                raise ValueError('计价身份与引用计量记录不一致：' + what)
            rule_identity = identity
            if matched['alias_id'] is not None:
                alias = next((a for a in config['aliases']
                              if a['id'] == matched['alias_id'] and a['from'] == identity), None)
                if alias is None:
                    raise ValueError('计价别名来源身份与引用计量记录不一致：' + what)
                rule_identity = alias['to']
            if rule_identity != {'provider': rule['provider'], 'model': rule['model']}:
                raise ValueError('命中价格规则身份与引用计量记录或别名目标不一致：' + what)
            if entry.get('currency') != rule['currency']:
                raise ValueError('逐记录计价币种与命中规则不一致：' + what)
        components = entry.get('components')
        if not isinstance(components, list):
            raise ValueError('逐记录计价分项无效：' + what)
        expected = dict(rule_component_prices(rule)) if rule is not None else {}
        seen = set()
        for component in components:
            if not isinstance(component, dict) or set(component) != {'name', 'tokens', 'price_per_million', 'amount'}:
                raise ValueError('计价分项结构无效：' + what)
            name = component['name']
            if name not in expected or name in seen:
                raise ValueError('计价分项不属于命中规则或重复：' + what)
            seen.add(name)
            tokens = component['tokens']
            if type(tokens) is not int or tokens < 0:
                raise ValueError('计价分项 token 必须为非负整数：' + what)
            record = metered_by_key.get(key)
            partition, reason = _component_tokens(name, record['metrics']) if record is not None else (None, '引用悬空')
            if reason is not None or tokens != partition:
                raise ValueError('计价分区 token 与引用计量记录不一致：' + what)
            if component['price_per_million'] != expected[name]:
                raise ValueError('计价分项单价与命中规则不一致：' + what)
            amount = component['amount']
            if not isinstance(amount, str) or not PRICE_TEXT.fullmatch(amount) \
                    or amount != component_amount(tokens, component['price_per_million']):
                raise ValueError('计价分项金额与精确 token×单价 不一致：' + what)
        unpriced = entry.get('unpriced')
        if not isinstance(unpriced, list):
            raise ValueError('逐记录未定价原因无效：' + what)
        for item in unpriced:
            if not isinstance(item, dict) or set(item) != {'component', 'reason'} \
                    or (item['component'] is not None and not isinstance(item['component'], str)) \
                    or not isinstance(item['reason'], str):
                raise ValueError('逐记录未定价原因无效：' + what)
        total = len(expected)
        if status == 'priced' and (rule is None or len(components) != total):
            raise ValueError('计价状态与分项不一致：' + what)
        if status == 'partially_priced' and not (rule is not None and 0 < len(components) < total):
            raise ValueError('计价状态与分项不一致：' + what)
        if status in ('unpriced', 'rule_conflict') and components:
            raise ValueError('计价状态与分项不一致：' + what)
        if status == 'rule_conflict':
            conflicts = entry.get('conflicts')
            if matched is not None or not isinstance(conflicts, list) or len(conflicts) < 2 \
                    or any(not isinstance(c, str) or c not in rules for c in conflicts):
                raise ValueError('规则冲突记录须列出配置中存在的冲突规则：' + what)
        elif 'conflicts' in entry:
            raise ValueError('非冲突记录不得携带冲突规则列表：' + what)
    if len(set(keys)) != len(keys):
        raise ValueError('逐记录计价记录引用重复')
    if set(keys) != {r['key'] for r in obj['records']}:
        raise ValueError('逐记录计价未覆盖本报告全部计量记录或引用悬空')
    summary = cost['summary']
    if not isinstance(summary, dict) or set(summary) != {'records', 'priced', 'partially_priced', 'unpriced',
                                                         'rule_conflicts', 'currencies', 'unpriced_reasons', 'display'}:
        raise ValueError('费用摘要结构无效')
    counts = {'records': len(entries), 'priced': 0, 'partially_priced': 0, 'unpriced': 0, 'rule_conflicts': 0}
    reasons = {}
    record_counts = {}
    for entry in entries:
        counts[{'priced': 'priced', 'partially_priced': 'partially_priced',
                 'unpriced': 'unpriced', 'rule_conflict': 'rule_conflicts'}[entry['status']]] += 1
        for item in entry['unpriced']:
            reasons[item['reason']] = reasons.get(item['reason'], 0) + 1
        if not entry['components']:
            continue
        bucket = record_counts.setdefault(entry['currency'], {'priced_records': 0, 'partially_priced_records': 0})
        bucket[{'priced': 'priced_records', 'partially_priced': 'partially_priced_records'}[entry['status']]] += 1
    totals = _cost_totals(entries)
    for field, expected_count in counts.items():
        if type(summary.get(field)) is not int or summary[field] != expected_count:
            raise ValueError('费用摘要计数与逐记录计价不一致')
    currencies = summary['currencies']
    if not isinstance(currencies, dict) or set(currencies) != set(totals):
        raise ValueError('费用摘要币种集合与逐记录计价不一致')
    for currency, bucket in currencies.items():
        if not isinstance(bucket, dict) or set(bucket) != {'amount', 'components', 'priced_records', 'partially_priced_records'}:
            raise ValueError('币种费用摘要结构无效：' + str(currency))
        expected_bucket = totals[currency]
        if bucket['amount'] != canon_decimal(expected_bucket['amount']):
            raise ValueError('币种费用摘要金额与逐记录计价不一致：' + str(currency))
        for field in ('priced_records', 'partially_priced_records'):
            if type(bucket.get(field)) is not int or bucket[field] != record_counts[currency][field]:
                raise ValueError('币种费用摘要计数不一致：' + str(currency))
        components = bucket['components']
        if not isinstance(components, dict) or set(components) != set(expected_bucket['components']):
            raise ValueError('币种费用摘要分项集合不一致：' + str(currency))
        for name, cell in components.items():
            expected_cell = expected_bucket['components'][name]
            if not isinstance(cell, dict) or set(cell) != {'tokens', 'amount'} \
                    or type(cell.get('tokens')) is not int or cell['tokens'] != expected_cell['tokens'] \
                    or cell.get('amount') != canon_decimal(expected_cell['amount']):
                raise ValueError('币种费用摘要分项与逐记录计价不一致：' + str(currency))
    if summary['unpriced_reasons'] != reasons:
        raise ValueError('费用摘要未定价原因与逐记录计价不一致')
    display = summary['display']
    if not isinstance(display, dict) or set(display) != {'decimals', 'rounding', 'note'} \
            or display.get('decimals') != 2 or display.get('rounding') != 'half_up' \
            or not isinstance(display.get('note'), str):
        raise ValueError('费用摘要显示精度说明无效')
    if overall:
        check_cost_projections(obj, entries, cost['projections'])


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
        if version == 1 and ('explanation' in obj or 'analysis' in obj
                             or any('explanation' in r for r in obj.get('records', []))
                             or any('explanation' in r for r in obj.get('unassigned_records', []))):
            raise ValueError('v1 报告不含解释或分析扩展')
        check_records_explanation(obj['records'], 'records')
        check_records_explanation(obj.get('unassigned_records', []), 'unassigned_records')
        if 'explanation' in obj:
            check_explanation(obj, scope)
        if 'analysis' in obj:
            check_analysis(obj)
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
            allowed |= {'localization','internal_support','views','alternate_sources','explanation','analysis'}
        if version == 3:
            allowed |= {'days','rankings','session_index','unbucketed'}
        return {k:v for k,v in obj.items() if k in allowed}
    except (KeyError,TypeError) as exc:
        raise ValueError('报告缺少必需结构或 JSON 无效') from exc


def load_report(path):
    return validate_report(read_decoded(path))


def _cost_csv_rows(ext):
    """CSV rows for the saved cost section: pricing basis (full snapshot incl. unmatched
    rules), per-currency exact and display amounts, coverage and v3 projection members."""
    cost = ext['cost']
    config = cost['config']
    summary = cost['summary']
    rows = [{'category': 'cost_config', 'label': '价格配置快照（含未命中规则，即价格依据）',
             'cost_detail': json.dumps({'schema_version': ext['schema_version'], 'revision': config['revision'],
                                        'rules': config['rules'], 'aliases': config['aliases']},
                                       ensure_ascii=False)}]
    for currency in sorted(summary['currencies']):
        bucket = summary['currencies'][currency]
        rows.append({'category': 'cost_summary', 'label': '币种小计', 'cost_currency': currency,
                     'cost_amount_exact': bucket['amount'], 'cost_amount_display': display_amount(bucket['amount']),
                     'cost_priced_records': bucket['priced_records'],
                     'cost_partially_priced_records': bucket['partially_priced_records'],
                     'cost_detail': json.dumps({'components': bucket['components'], 'display': summary['display']},
                                               ensure_ascii=False)})
    rows.append({'category': 'cost_coverage', 'label': '计价覆盖与未定价原因',
                 'cost_detail': json.dumps({'records': summary['records'], 'priced': summary['priced'],
                                            'partially_priced': summary['partially_priced'],
                                            'unpriced': summary['unpriced'],
                                            'rule_conflicts': summary['rule_conflicts'],
                                            'unpriced_reasons': summary['unpriced_reasons']},
                                           ensure_ascii=False)})

    def member_rows(dimension, label_of, members):
        for member in members:
            for currency in sorted(member['currencies']):
                bucket = member['currencies'][currency]
                rows.append({'category': 'cost_projection_' + dimension, 'label': label_of(member),
                             'cost_currency': currency, 'cost_amount_exact': bucket['amount'],
                             'cost_amount_display': display_amount(bucket['amount']),
                             'cost_detail': json.dumps({'records': len(member['record_keys']),
                                                        'components': bucket['components']}, ensure_ascii=False)})

    projections = cost.get('projections')
    if projections is not None:
        # v3 only: saved views of the same priced components; never added back into totals.
        member_rows('model', lambda m: m['identity']['provider'] + '/' + m['identity']['model'], projections['model'])
        member_rows('session', lambda m: m['session'], projections['session'])
        member_rows('day', lambda m: m['date'], projections['day'])
        member_rows('unbucketed', lambda m: '无法归日', [projections['unbucketed']])
    return rows


def _perf_display(name, numerator, denominator):
    """Two-decimal display of one exact performance aggregate; empty when undefined."""
    if not denominator:
        return None
    if name == 'tool_duration':
        return _perf_ratio(numerator, 1000000)  # exact ns sum → ms
    return _perf_ratio(numerator, denominator, name == 'throughput')


def _perf_csv_rows(perf):
    """CSV rows for the saved performance section: per-metric exact numerator/denominator,
    units, event definitions, coverage and exclusion reasons, plus saved members."""
    rows = [{'category': 'perf_tz', 'label': '性能日分布时区',
             'perf_detail': json.dumps(perf['tz'], ensure_ascii=False)}]
    for name in PERF_METRICS:
        if name not in perf['metrics']:
            continue  # reports saved before the tool metric stay legal; never backfilled
        metric = perf['metrics'][name]
        aggregate = metric['aggregate']
        detail = {'definition': metric['definition'], 'admission': metric['admission'],
                  'overhead': metric['overhead'], 'support': metric['support'],
                  'candidates': aggregate['candidates'], 'valid': aggregate['valid'],
                  'excluded': aggregate['excluded'], 'excluded_by_kind': aggregate['excluded_by_kind'],
                  'exclusion_reasons': aggregate['exclusion_reasons'],
                  'no_token_record': aggregate['no_token_record'], 'display': aggregate['display']}
        if name == 'tool_duration':
            detail['wall'] = aggregate['wall']
            detail['supplements'] = aggregate['supplements']
        rows.append({'category': 'perf_metric', 'label': metric['label'], 'perf_metric': name,
                     'perf_numerator': aggregate['numerator'], 'perf_denominator': aggregate['denominator'],
                     'perf_units': json.dumps(metric['units'], ensure_ascii=False),
                     'perf_display_value': _perf_display(name, aggregate['numerator'], aggregate['denominator']),
                     'perf_detail': json.dumps(detail, ensure_ascii=False)})
        if metric['support']['status'] != 'supported':
            continue
        if name == 'tool_duration':
            dimensions = (('category', lambda m: m['category']), ('session', lambda m: m['session']),
                          ('day', lambda m: m['date']))
        else:
            dimensions = (('model', lambda m: m['identity']['provider'] + '/' + m['identity']['model']),
                          ('session', lambda m: m['session']), ('day', lambda m: m['date']))
        for dimension, label_of in dimensions:
            for member in metric['projections'][dimension]:
                rows.append({'category': 'perf_projection_' + dimension, 'label': label_of(member),
                             'perf_metric': name, 'perf_numerator': member['numerator'],
                             'perf_denominator': member['denominator'],
                             'perf_display_value': _perf_display(name, member['numerator'], member['denominator'])})
    return rows


def _analysis_csv_rows(result):
    """CSV projection of the same saved analysis extension; JSON stays the complete entry
    and neither CSV nor Markdown promises reconstruction."""
    ext = result.get('analysis')
    if not isinstance(ext, dict):
        return [{'category': 'analysis_note',
                 'label': '本报告未保存费用/性能分析（旧报告）；CSV 不补零，完整状态以 JSON 重载为准。'}]
    rows = []
    if 'cost' in ext:
        rows += _cost_csv_rows(ext)
    else:
        rows.append({'category': 'analysis_note',
                     'label': '本次查询未配置价格，结果不含费用估算；明确带价格重算才生成费用。'})
    if 'performance' in ext:
        rows += _perf_csv_rows(ext['performance'])
    else:
        rows.append({'category': 'analysis_note', 'label': '本报告未保存性能分析（旧报告）；token 结果不受影响。'})
    return rows


ANALYSIS_CSV_COLUMNS = ['cost_currency', 'cost_amount_exact', 'cost_amount_display',
                        'cost_priced_records', 'cost_partially_priced_records', 'cost_detail',
                        'perf_metric', 'perf_numerator', 'perf_denominator', 'perf_units',
                        'perf_display_value', 'perf_detail']


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
    analysis_rows = _analysis_csv_rows(result)
    columns = ['category','label','scope','status','read_at','sources','issues','call_count',
               'cache_hit_rate','cache_rate_state','paired_records','paired_input','paired_cache_read','tool_report_total']
    for m in METRICS:
        columns += [m,m+'_state',m+'_known_records',m+'_records',m+'_reasons']
    columns += ANALYSIS_CSV_COLUMNS
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
    for entry in analysis_rows:
        writer.writerow(dict(common, **entry))
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
