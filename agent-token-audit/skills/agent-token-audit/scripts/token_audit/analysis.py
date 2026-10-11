"""Pricing config validation, rule matching and exact Decimal cost components.

No I/O here: entry points parse and submit the config, adapters bind provider/model
identity onto records, and this module only validates the config, matches rules and
computes per-record pricing plus the per-currency summary saved in the v2/v3
`analysis` report extension. The same module owns the deterministic performance
selection (TTFT and source-observed-interval throughput): candidates come from the
kernel with every source time event preserved, and this module judges each metric
independently, aggregates over one valid set as exact numerator/denominator, and
saves the per-model/session/day projections.
"""
import datetime as dt
import json
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from .core import known, timestamp, timezone_of

SCHEMA_VERSION = 1
PRICE_TEXT = re.compile(r'(0|[1-9]\d*)(\.\d+)?$')
COMPONENT_LABELS = {'input': '总输入', 'non_cache_read': '非缓存读取输入', 'cache_read': '缓存读取',
                    'other_input': '其他输入', 'cache_write': '缓存写入', 'output': '输出',
                    'other_output': '其他输出', 'reasoning': '推理输出'}
INPUT_KINDS = ('total_input', 'split_cache_read', 'split_cache_read_write')
OUTPUT_KINDS = ('total_output', 'split_reasoning')
# Components are mutually exclusive within one rule; non-cache-read input reuses the
# existing input-minus-cache-read semantics, never a second guess at the same tokens.
RULE_COMPONENTS = {'total_input': (('input', 'price_per_million'),),
                   'split_cache_read': (('non_cache_read', 'non_cache_read_per_million'),
                                        ('cache_read', 'cache_read_per_million')),
                   'split_cache_read_write': (('other_input', 'other_input_per_million'),
                                              ('cache_read', 'cache_read_per_million'),
                                              ('cache_write', 'cache_write_per_million')),
                   'total_output': (('output', 'price_per_million'),),
                   'split_reasoning': (('other_output', 'other_output_per_million'),
                                       ('reasoning', 'reasoning_per_million'))}
MISSING_MODEL = '模型未知'


def canon_decimal(value):
    """Canonical decimal string: no exponent, no trailing fraction zeros."""
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def exact_decimal_add(left, right):
    """Add finite nonnegative amounts without rounding to the ambient context.

    Align both fractional scales and reserve one integer carry digit. Applying this
    bound at every addition also covers an arbitrarily growing running total.
    """
    left, right = Decimal(left), Decimal(right)
    integer_digits = max(1, left.adjusted() + 1, right.adjusted() + 1)
    fractional_digits = max(0, -left.as_tuple().exponent, -right.as_tuple().exponent)
    with localcontext() as ctx:
        ctx.prec = max(28, integer_digits + fractional_digits + 1)
        return left + right


def component_amount(tokens, price_text):
    """Exact cost of one component: integer tokens x price per million, Decimal only."""
    with localcontext() as ctx:
        ctx.prec = max(80, len(str(tokens)) + len(price_text) + 20)
        return canon_decimal(Decimal(tokens) * Decimal(price_text) / Decimal(1000000))


def display_amount(amount_text):
    """Display default: two decimals, round half up; the exact value stays untouched."""
    amount = Decimal(amount_text)
    with localcontext() as ctx:
        ctx.prec = max(28, amount.adjusted() + 4)  # Integer digits, two decimals and carry.
        return str(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def rule_component_prices(rule):
    """[(component name, price text)] for one validated rule; shared by compute and audit."""
    pairs = RULE_COMPONENTS[rule['input']['kind']] + RULE_COMPONENTS[rule['output']['kind']]
    return [(name, (rule['input'] if name in ('input', 'non_cache_read', 'cache_read', 'other_input', 'cache_write')
                    else rule['output'])[price_key])
            for name, price_key in pairs]


def _require_text(value, what, length=256):
    if not isinstance(value, str) or not value.strip() or len(value) > length:
        raise ValueError('价格配置无效：' + what + '必须是非空字符串')
    return value.strip()


def _require_price(value, what):
    if not isinstance(value, str) or not PRICE_TEXT.fullmatch(value.strip()):
        raise ValueError('价格配置无效：' + what + '必须是非负有限十进制字符串（每百万 token 单价）')
    return value.strip()


def _require_time(value, what):
    if not isinstance(value, str):
        raise ValueError('价格配置无效：' + what + '必须是带时区的时间字符串')
    try:
        return timestamp(value)
    except ValueError:
        raise ValueError('价格配置无效：' + what + '必须是带时区的有效时间') from None


def _check_source_ref(value, what):
    if not isinstance(value, dict) or set(value) != {'reference', 'version'}:
        raise ValueError('价格配置无效：' + what + '来源须含引用与版本（只作说明，不发起网络请求）')
    return {'reference': _require_text(value.get('reference'), what + '来源引用'),
            'version': _require_text(value.get('version'), what + '来源版本')}


def _check_partition(value, kinds, what):
    if not isinstance(value, dict) or value.get('kind') not in kinds:
        raise ValueError('价格配置无效：' + what + '分区类型未知')
    kind = value['kind']
    expected = {'kind'} | {price_key for _, price_key in RULE_COMPONENTS[kind]}
    if kind in ('split_cache_read_write', 'split_reasoning'):
        expected.add('basis')
    if set(value) != expected:
        raise ValueError('价格配置无效：' + what + '分区字段与类型不匹配')
    result = {'kind': kind}
    for _, price_key in RULE_COMPONENTS[kind]:
        result[price_key] = _require_price(value.get(price_key), what + '单价 ' + price_key)
    if 'basis' in expected:
        result['basis'] = _require_text(value.get('basis'), what + '互斥/包含关系依据', 512)
    return result


def validate_pricing_config(value):
    """Validate one pricing config (JSON text or decoded object) into canonical form.

    Any structural, type, version, rule-id, time or price-format problem is a config
    error raised before any source read; a missing partition price is not defaulted.
    """
    if isinstance(value, str):
        if not value.strip():
            raise ValueError('价格配置文本为空；未选择配置请省略该参数')
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError('价格配置不是有效 JSON') from None
    if not isinstance(value, dict):
        raise ValueError('价格配置必须是 JSON 对象')
    if value.get('schema_version') != SCHEMA_VERSION or isinstance(value.get('schema_version'), bool):
        raise ValueError('价格配置无效：不支持的价格配置 schema 版本')
    if set(value) - {'schema_version', 'revision', 'rules', 'aliases'}:
        raise ValueError('价格配置无效：含未知字段')
    if 'revision' not in value or 'rules' not in value:
        raise ValueError('价格配置无效：缺少修订标识或规则列表')
    config = {'schema_version': SCHEMA_VERSION,
              'revision': _require_text(value.get('revision'), '修订标识'),
              'rules': [], 'aliases': []}
    rules = value['rules']
    if not isinstance(rules, list):
        raise ValueError('价格配置无效：规则必须是数组')
    seen = set()
    for i, rule in enumerate(rules):
        what = '规则 ' + str(i)
        if not isinstance(rule, dict) or set(rule) - {'id', 'source', 'provider', 'model', 'effective_from',
                                                      'effective_to', 'currency', 'input', 'output'}:
            raise ValueError('价格配置无效：' + what + '结构未知')
        entry = {'id': _require_text(rule.get('id'), what + ' 稳定 ID', 128),
                 'source': _check_source_ref(rule.get('source'), what),
                 'provider': _require_text(rule.get('provider'), what + ' 供应商', 128),
                 'model': _require_text(rule.get('model'), what + ' 完整模型身份', 256)}
        if entry['id'] in seen:
            raise ValueError('价格配置无效：规则 ID 重复 ' + entry['id'])
        seen.add(entry['id'])
        start = _require_time(rule.get('effective_from'), what + ' 生效起点')
        entry['effective_from'] = rule['effective_from']
        if rule.get('effective_to') is not None:
            end = _require_time(rule.get('effective_to'), what + ' 生效终点')
            if end <= start:
                raise ValueError('价格配置无效：' + what + ' 生效区间必须满足 from < to')
            entry['effective_to'] = rule['effective_to']
        entry['currency'] = _require_text(rule.get('currency'), what + ' 币种', 32)
        for section, kinds, label in (('input', INPUT_KINDS, what + ' 输入'), ('output', OUTPUT_KINDS, what + ' 输出')):
            if section not in rule:
                raise ValueError('价格配置无效：' + label + '分区缺失')
            entry[section] = _check_partition(rule[section], kinds, label)
        config['rules'].append(entry)
    aliases = value.get('aliases', [])
    if not isinstance(aliases, list):
        raise ValueError('价格配置无效：别名必须是数组')
    sources = {}
    for i, alias in enumerate(aliases):
        what = '别名 ' + str(i)
        if not isinstance(alias, dict) or set(alias) != {'id', 'source', 'from', 'to', 'basis'}:
            raise ValueError('价格配置无效：' + what + '结构未知')
        entry = {'id': _require_text(alias.get('id'), what + ' 稳定 ID', 128),
                 'source': _check_source_ref(alias.get('source'), what),
                 'basis': _require_text(alias.get('basis'), what + ' 映射依据', 512)}
        for endpoint in ('from', 'to'):
            point = alias.get(endpoint)
            if not isinstance(point, dict) or set(point) != {'provider', 'model'}:
                raise ValueError('价格配置无效：' + what + ' ' + endpoint + ' 须含完整供应商与模型身份')
            entry[endpoint] = {'provider': _require_text(point.get('provider'), what + ' ' + endpoint + ' 供应商', 128),
                               'model': _require_text(point.get('model'), what + ' ' + endpoint + ' 完整模型身份', 256)}
        if entry['from'] == entry['to']:
            raise ValueError('价格配置无效：' + what + ' 源与目标身份相同（循环映射）')
        key = (entry['from']['provider'], entry['from']['model'])
        if key in sources:
            raise ValueError('价格配置无效：' + what + ' 与其他别名的源身份冲突')
        sources[key] = entry
        config['aliases'].append(entry)
    targets = {(a['to']['provider'], a['to']['model']) for a in config['aliases']}
    if targets & set(sources):
        raise ValueError('价格配置无效：别名只允许一次精确映射，不支持链式推断')
    return config


def _identity_of(record):
    provider = record.get('provider')
    model = record.get('model')
    if not isinstance(provider, str) or not provider:
        return None
    if not isinstance(model, str) or not model or model == MISSING_MODEL:
        return None
    return {'provider': provider, 'model': model}


def _component_tokens(name, metrics):
    """Known integer tokens for one component, or (None, reason) keeping other parts priced."""
    def metric_value(key):
        metric = metrics.get(key)
        if metric is not None and known(metric):
            return metric['value'], None
        reason = (metric or {}).get('reason') or (metric or {}).get('state') or '源未报告'
        return None, reason
    if name == 'input':
        return metric_value('input')
    if name == 'non_cache_read':
        return metric_value('non_cache_read')
    if name == 'cache_read':
        return metric_value('cache_read')
    if name == 'cache_write':
        return metric_value('cache_write')
    if name == 'output':
        return metric_value('output')
    if name == 'other_input':
        inp, r1 = metric_value('input')
        cache, r2 = metric_value('cache_read')
        write, r3 = metric_value('cache_write')
        missing = [r for r in (r1, r2, r3) if r is not None]
        if missing:
            return None, '输入/缓存读取/缓存写入不全已知（' + '；'.join(sorted(set(missing))) + '）'
        value = inp - cache - write
        if value < 0:
            return None, '按互斥分区拆分后其他输入为负，源数值不支持该分区'
        return value, None
    if name == 'other_output':
        out, r1 = metric_value('output')
        reasoning, r2 = metric_value('reasoning')
        missing = [r for r in (r1, r2) if r is not None]
        if missing:
            return None, '输出/推理不全已知（' + '；'.join(sorted(set(missing))) + '）'
        value = out - reasoning
        if value < 0:
            return None, '推理超过输出，源数值不支持该包含关系'
        return value, None
    if name == 'reasoning':
        return metric_value('reasoning')
    return None, '未知计价分项'


def price_records(records, config):
    """Per-record pricing + per-currency summary for the report `analysis` extension.

    Matching is exact on source provider + full model identity (one optional explicit
    alias hop) over the record's billing time; overlapping rules are a per-record
    conflict, never a silent pick, and other identities keep their priced results.
    """
    aliases = {(a['from']['provider'], a['from']['model']): a for a in config['aliases']}
    entries = []
    summary = {'records': 0, 'priced': 0, 'partially_priced': 0, 'unpriced': 0, 'rule_conflicts': 0,
               'currencies': {}, 'unpriced_reasons': {},
               'display': {'decimals': 2, 'rounding': 'half_up',
                           'note': '金额显示默认两位小数四舍五入；各 amount 字段保存未舍入的规范十进制值'}}
    for record in records:
        entry = {'record_key': record['key'], 'identity': None, 'status': 'unpriced',
                 'currency': None, 'matched': None, 'components': [], 'unpriced': []}
        entries.append(entry)
        identity = _identity_of(record)
        if identity is None:
            entry['unpriced'].append({'component': None, 'reason': '缺少有依据的供应商与完整模型身份，不按名称猜测'})
            continue
        entry['identity'] = identity
        at = record.get('time')
        try:
            billing = timestamp(at) if isinstance(at, str) else None
        except ValueError:
            billing = None
        if billing is None:
            entry['unpriced'].append({'component': None, 'reason': '记录缺少可信计价时间，不按当前时钟选价'})
            continue
        key = (identity['provider'], identity['model'])
        alias = aliases.get(key)
        if alias is not None:
            identity = {'provider': alias['to']['provider'], 'model': alias['to']['model']}
            key = (identity['provider'], identity['model'])
        matched = []
        for rule in config['rules']:
            if (rule['provider'], rule['model']) != key:
                continue
            if timestamp(rule['effective_from']) > billing:
                continue
            if rule.get('effective_to') is not None and timestamp(rule['effective_to']) <= billing:
                continue
            matched.append(rule)
        if len(matched) > 1:
            entry['status'] = 'rule_conflict'
            entry['conflicts'] = sorted(rule['id'] for rule in matched)
            entry['unpriced'].append({'component': None,
                                      'reason': '同一身份与时间命中多条价格规则（' + '、'.join(entry['conflicts'])
                                                + '），不按文件顺序/最新/币种静默选价'})
            continue
        if not matched:
            reason = '别名 ' + alias['id'] + ' 映射后无匹配价格规则' if alias is not None \
                else '无匹配的价格规则（供应商＋完整模型身份精确匹配，含生效区间）'
            entry['unpriced'].append({'component': None, 'reason': reason})
            continue
        rule = matched[0]
        entry['currency'] = rule['currency']
        entry['matched'] = {'rule_id': rule['id'], 'alias_id': alias['id'] if alias is not None else None}
        for name, price_text in rule_component_prices(rule):
            tokens, reason = _component_tokens(name, record.get('metrics') or {})
            if tokens is None:
                entry['unpriced'].append({'component': name,
                                          'reason': '分项 ' + COMPONENT_LABELS[name] + ' 缺少已知 token（' + reason + '）'})
                continue
            entry['components'].append({'name': name, 'tokens': tokens, 'price_per_million': price_text,
                                        'amount': component_amount(tokens, price_text)})
        total = len(rule_component_prices(rule))
        entry['status'] = 'priced' if len(entry['components']) == total else 'partially_priced' if entry['components'] else 'unpriced'
    for entry in entries:
        summary['records'] += 1
        summary[{'priced': 'priced', 'partially_priced': 'partially_priced',
                 'unpriced': 'unpriced', 'rule_conflict': 'rule_conflicts'}[entry['status']]] += 1
        for item in entry['unpriced']:
            summary['unpriced_reasons'][item['reason']] = summary['unpriced_reasons'].get(item['reason'], 0) + 1
        if not entry['components']:
            continue
        bucket = summary['currencies'].setdefault(entry['currency'], {
            'amount': '0', 'components': {}, 'priced_records': 0, 'partially_priced_records': 0})
        bucket[{'priced': 'priced_records', 'partially_priced': 'partially_priced_records'}[entry['status']]] += 1
        for component in entry['components']:
            cell = bucket['components'].setdefault(component['name'], {'tokens': 0, 'amount': '0'})
            cell['tokens'] += component['tokens']
            cell['amount'] = canon_decimal(exact_decimal_add(cell['amount'], component['amount']))
            bucket['amount'] = canon_decimal(exact_decimal_add(bucket['amount'], component['amount']))
    return {'config': config, 'records': entries, 'summary': summary}


def overview_projections(entries, records, buckets):
    """v3 cost projections: model/session/day members and the unbucketed item.

    Every member sums the same per-record priced components under a different grouping;
    the views are never added back into any total. Day members reuse the kernel's saved
    day buckets and unbucketed set (records without a reliable day are never spread across
    days, and their priced amounts reconcile against the per-currency summary only here).
    """
    by_key = {entry['record_key']: entry for entry in entries}
    session_of = {record['key']: record['session'] for record in records}

    def member(keys):
        subset = [by_key[key] for key in keys]
        currencies = {}
        for entry in subset:
            for component in entry['components']:
                bucket = currencies.setdefault(entry['currency'], {'amount': '0', 'components': {}})
                cell = bucket['components'].setdefault(component['name'], {'tokens': 0, 'amount': '0'})
                cell['tokens'] += component['tokens']
                cell['amount'] = canon_decimal(exact_decimal_add(cell['amount'], component['amount']))
                bucket['amount'] = canon_decimal(exact_decimal_add(bucket['amount'], component['amount']))
        return {'currencies': currencies, 'record_keys': list(keys)}

    priced = [entry for entry in entries if entry['components']]
    model_groups = {}
    for entry in priced:
        identity = entry['identity']
        model_groups.setdefault((identity['provider'], identity['model']), []).append(entry['record_key'])
    models = [dict(identity={'provider': provider, 'model': model}, **member(sorted(keys)))
              for (provider, model), keys in sorted(model_groups.items())]
    session_groups = {}
    for entry in priced:
        session_groups.setdefault(session_of[entry['record_key']], []).append(entry['record_key'])
    sessions = [dict(session=sid, **member(sorted(keys))) for sid, keys in sorted(session_groups.items())]
    days = [dict(date=day['date'], **member(day['record_keys'])) for day in buckets['days']]
    return {'model': models, 'session': sessions, 'day': days,
            'unbucketed': member(buckets['unbucketed'])}


def build_analysis(records, config=None, buckets=None, performance=None):
    """The v2/v3 report extension (internal schema version 1).

    The performance section is always saved for new reports (no pricing needed); the
    cost section only for a priced query. Overall (v3) queries pass the kernel's saved
    day buckets/unbucketed set so a priced extension also saves the model/session/day
    cost projections; single-session (v2) never carries cost projections.
    """
    ext = {'schema_version': SCHEMA_VERSION}
    if config is not None:
        cost = price_records(records, config)
        if buckets is not None:
            cost['projections'] = overview_projections(cost['records'], records, buckets)
        ext['cost'] = cost
    if performance is not None:
        ext['performance'] = performance
    return ext


MS = dt.timedelta(milliseconds=1)
PERF_METRICS = ('ttft', 'throughput', 'tool_duration')
PERF_EXCLUSION_KINDS = ('missing', 'conflict', 'unsupported', 'range')
PERF_SUPPORT_STATES = ('supported', 'source_not_provided', 'not_checked')
PERF_COMPLETION_STATES = ('ended_before_cutoff', 'ended_after_cutoff', 'no_end_evidence')
TOOL_FINISHED_STATES = ('completed', 'failed')
PERF_DISPLAY = {'decimals': 2, 'rounding': 'half_up',
                'note': '比值显示默认两位小数四舍五入；分子/分母保存精确整数，分组与日分布由成员分子/分母重新生成，不从舍入值推导'}
PERF_METRIC_DEFS = {
    'ttft': {'label': '首 token 延迟（TTFT）',
             'definition': '同一逻辑请求的首个可观察文本/推理 token 时间减去请求起点',
             'admission': '以首 token 事件判断是否落入 [from,to)；事件恰在截止点排除；跨下界的完整有效样本不裁时',
             'unit': 'ms', 'units': {'numerator': 'ms', 'denominator': '样本', 'value': 'ms'},
             'overhead': None},
    'throughput': {'label': '生成吞吐（来源观测区间）',
                   'definition': '同一逻辑请求的已知输出 token 除以首 token 至 completed_at 的来源观测区间',
                   'admission': '以观测区间终点判断是否落入 [from,to)；要求完成在截止前被证实',
                   'unit': 'token/s', 'units': {'numerator': 'token', 'denominator': 'ms', 'value': 'token/s'},
                   'overhead': '观测区间终点 completed_at 在完成事件处理后写入，含完成事件处理开销；不是服务端纯生成速率'},
    'tool_duration': {'label': '工具执行耗时',
                      'definition': '可信原生执行耗时，或无原生值时有明确实际执行起止求差；原生与推导同语义才互校；'
                                    '调度至完成的跨度独立保存，不加入执行耗时和',
                      'admission': '以可信完成事件判断是否落入 [from,to)；恰在截止点排除；跨下界的完整有效样本不裁时',
                      'unit': 'ms', 'units': {'numerator': 'ns', 'denominator': '样本', 'value': 'ms'},
                      'overhead': None}}


def _tool_span_ns(start_text, end_text):
    """Exact ns of a millisecond-precision endpoint pair; None when either side is missing."""
    began, finish = _parse_time(start_text), _parse_time(end_text)
    if began is None or finish is None:
        return None
    return (finish - began) // MS * 1000000


def _tool_wall(samples):
    """Scheduling/execution span envelope over the valid samples: parallel durations are
    NOT overlapped away, the envelope is not the duration sum, and it never touches the
    original turn wall clock. Known only when every valid sample has both endpoints."""
    if not samples:
        return {'value': None, 'state': 'unknown', 'unit': 'ns',
                'basis': '工具集合调度/执行跨度包络：各样本调度或实际执行起止的最早起点至最晚终点；'
                         '并行不扣除重叠，不等于执行耗时和，也不改变轮次墙钟',
                'reason': '无有效样本，不给包络（未知不画零）'}
    begins, ends, missing = [], [], 0
    for sample in samples:
        start_text = sample['dispatch_start'] or sample['exec_start']
        end_text = sample['dispatch_end'] or sample['exec_end']
        span = _tool_span_ns(start_text, end_text)
        if span is None:
            missing += 1
            continue
        if span < 0:
            return {'value': None, 'state': 'conflict', 'unit': 'ns',
                    'basis': '工具集合调度/执行跨度包络：各样本调度或实际执行起止的最早起点至最晚终点；'
                             '并行不扣除重叠，不等于执行耗时和，也不改变轮次墙钟',
                    'reason': '存在起止逆序的有效样本，包络不可信'}
        begins.append(_parse_time(start_text))
        ends.append(_parse_time(end_text))
    if missing:
        return {'value': None, 'state': 'unknown', 'unit': 'ns',
                'basis': '工具集合调度/执行跨度包络：各样本调度或实际执行起止的最早起点至最晚终点；'
                         '并行不扣除重叠，不等于执行耗时和，也不改变轮次墙钟',
                'reason': '%d 条有效样本缺少完整起止端点（如仅有原生耗时与完成事件），包络覆盖不全，不由耗时反推端点' % missing}
    value = (max(ends) - min(begins)) // MS * 1000000
    return {'value': value, 'state': 'known', 'unit': 'ns',
            'basis': '工具集合调度/执行跨度包络：各样本调度或实际执行起止的最早起点至最晚终点；'
                     '并行不扣除重叠，不等于执行耗时和，也不改变轮次墙钟',
            'reason': '全部有效样本有可信起止端点'}


def _tool_outcome(event, start, end):
    """One tool candidate judged for the execution-duration metric; status-only samples
    (unfinished) and every exclusion keep an explicit reason."""
    if event.get('_agent_excluded'):
        return 'unsupported', event['_agent_excluded'], None
    if event.get('_turn_excluded'):
        return 'range', event['_turn_excluded'], None
    if event.get('inherited_copy'):
        return 'unsupported', '分叉继承副本：完整工具身份已在祖先会话计量，不重复计入；新身份的重新执行照常计入', None
    if event.get('conflict'):
        return 'conflict', event['conflict'], None
    status = event['status']
    if status not in TOOL_FINISHED_STATES:
        return 'missing', '执行未结束（状态 %s）；只给状态，不给耗时' % status, None
    value, basis = None, None
    if event.get('zero_unconfirmed'):
        return 'missing', '原生耗时为 0，但写入器可能把缺失 duration 转为 0；无独立执行完成证据确认零，保持未知', None
    if event['duration_ns'] is not None:
        value, basis = event['duration_ns'], 'native'
    else:
        span = _tool_span_ns(event.get('exec_start'), event.get('exec_end'))
        if span is None:
            return 'missing', '缺少可信原生执行耗时且无明确实际执行起止；调度跨度不补造执行耗时', None
        if span < 0:
            return 'conflict', '执行起止逆序，不能作为有效耗时', None
        value, basis = span, 'derived'
    completed = _parse_time(event.get('completed_at'))
    if completed is None:
        return 'missing', '缺少可信完成事件，无法判断范围', None
    if completed >= end or (start is not None and completed < start):
        return 'range', '完成事件不在范围 [from,to) 内（恰在截止点或界外事件排除）', None
    sample = {'key': event['key'], 'record_key': None,
              'session': event['session'], 'turn': event.get('turn'),
              'owner_session': event.get('owner_session', event['session']), 'owner_turn': event.get('owner_turn'),
              'category': event['category'], 'status': status,
              'value': value, 'basis': basis, 'precision': event['duration_precision'],
              'native_duration_ns': event['duration_ns'] if basis == 'native' else None,
              'exec_start': event.get('exec_start'), 'exec_end': event.get('exec_end'),
              'dispatch_start': event.get('dispatch_start'), 'dispatch_end': event.get('dispatch_end'),
              'completed_at': event['completed_at'], 'source': event['sources'][0]}
    return None, None, sample


def _tool_projections(samples, zone):
    """Tool category/session/day members over the same valid set; every member keeps its own
    exact numerator (sum of sample durations, ns) and denominator (sample count)."""
    def build(key_of, label_of, sort_of):
        groups = {}
        for sample in samples:
            groups.setdefault(key_of(sample), []).append(sample)
        members = []
        for key in sorted(groups, key=sort_of):
            subset = groups[key]
            members.append(dict(label_of(key),
                                sample_keys=sorted(s['key'] for s in subset),
                                numerator=sum(s['value'] for s in subset),
                                denominator=len(subset)))
        return members

    categories = build(lambda s: s['category'], lambda key: {'category': key}, lambda key: key)
    sessions = build(lambda s: s['session'], lambda key: {'session': key}, lambda key: key)
    days = build(lambda s: timestamp(s['completed_at']).astimezone(zone).date().isoformat(),
                 lambda key: {'date': key}, lambda key: key)
    return {'category': categories, 'session': sessions, 'day': days}


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return timestamp(value)
    except ValueError:
        return None


def _source_unavailable(harness, source_kind, columns, metric):
    """Checked per-entry 'source does not provide' conclusions; never an all-unknown chart."""
    if source_kind == 'zcode_database':
        # Native TTFT is optional corroboration, not a required first-token event.
        missing = sorted(name for name in ('first_token_at', 'tool_call_count')
                         if (columns or {}).get(name) is False)
        if not missing:
            return None
        return ('数据库 model_usage 缺少 ' + '/'.join(missing) + ' 列（列结构已核查）；'
                '无法核查' + PERF_METRIC_DEFS[metric]['label'] + '所需首 token 或输出类型证据')
    if harness == 'codex':
        return ('已核查所存 Codex JSONL：未提供可与逐调用 usage 唯一配对的请求起点、首 token、生成终点三元组；'
                'task_complete.time_to_first_token_ms 是执行轮次口径（一轮可含多次调用），不代替调用 TTFT；'
                '消息时间也不补造首 token（来源未提供，已核查非尚未核查）')
    return ('已核查所核 ZCode rollout/log 记录：无首 token 事件，无法计算 TTFT 与吞吐；'
            'usage 记录时间与完成时间不冒充首 token（来源未提供，已核查非尚未核查）')


def _empty_metric(name, status, reason, candidates=0):
    return {'label': PERF_METRIC_DEFS[name]['label'], 'definition': PERF_METRIC_DEFS[name]['definition'],
            'admission': PERF_METRIC_DEFS[name]['admission'], 'unit': PERF_METRIC_DEFS[name]['unit'],
            'units': dict(PERF_METRIC_DEFS[name]['units']), 'overhead': PERF_METRIC_DEFS[name]['overhead'],
            'support': {'status': status, 'reason': reason},
            'samples': [],
            'aggregate': {'candidates': candidates, 'valid': 0, 'excluded': 0,
                          'excluded_by_kind': {kind: 0 for kind in PERF_EXCLUSION_KINDS},
                          'exclusion_reasons': {}, 'numerator': 0, 'denominator': 0,
                          'no_token_record': 0, 'display': dict(PERF_DISPLAY)},
            'projections': {'model': [], 'session': [], 'day': []}}


def _identity_fields(record, token_keys):
    return {'key': record['key'],
            'record_key': record['key'] if record['key'] in token_keys else None,
            'session': record['session'], 'turn': record.get('turn'),
            'owner_session': record.get('owner_session', record['session']), 'owner_turn': record.get('owner_turn'),
            'granularity': record.get('granularity') or 'unknown',
            'provider': record.get('provider'), 'model': record.get('model') or '模型未知',
            'precision': 'ms', 'source': record['sources'][0]}


def _completion_state(record, end):
    completed = _parse_time(record.get('time'))
    if completed is None:
        return 'no_end_evidence'
    return 'ended_before_cutoff' if completed < end else 'ended_after_cutoff'


def _tool_arg_exclusion(record):
    """Records with tool-argument output cannot prove the recorded first text/reasoning
    token is the earliest token; missing evidence cannot prove the stream was pure."""
    tool_calls = record.get('tool_call_count')
    if tool_calls is None:
        return ('missing', '缺少 tool_call_count 证据，无法证明首个可观察 token 之前没有工具参数输出')
    if tool_calls > 0:
        return ('unsupported', '该请求含工具参数输出，无法证明记录的首个文本/推理 token 为最早 token')
    return None


def _ttft_outcome(record, token_keys, start, end):
    sample = _identity_fields(record, token_keys)
    began = _parse_time(record.get('start'))
    first = _parse_time(record.get('first_token_at'))
    if began is None or first is None:
        return 'missing', '缺少可信请求起点或首 token 时间事件', None
    tool_exclusion = _tool_arg_exclusion(record)
    if tool_exclusion:
        return tool_exclusion[0], tool_exclusion[1], None
    diff = (first - began) // MS
    if diff < 0:
        return 'conflict', '首 token 早于请求起点（同语义时间冲突；负延迟不入样，不伪造零）', None
    native = record.get('native_ttft_ms')
    if native is not None:
        if isinstance(native, bool) or not isinstance(native, int) or native < 0:
            return 'conflict', '原生 time_to_first_token_ms 为负数、布尔值或非整数', None
        if native != diff:
            return 'conflict', '原生 time_to_first_token_ms 与首 token−起点时间差矛盾（同语义证据冲突）', None
    if first >= end or (start is not None and first < start):
        return 'range', '首 token 事件不在范围 [from,to) 内（恰在截止点或界外事件排除）', None
    sample.update(value=diff, basis='native' if native is not None else 'derived',
                  started_at=record['start'], first_token_at=record['first_token_at'],
                  native_ttft_ms=native, completed_at=record.get('time'),
                  completion=_completion_state(record, end))
    return None, None, sample


def _throughput_outcome(record, token_keys, start, end):
    sample = _identity_fields(record, token_keys)
    output = record['metrics']['output']
    if not known(output):
        return 'missing', '缺少已知输出 token（' + (output['reason'] or output['state'] or '源未报告') + '；输出口径未经供应商语义验证同样不入样）', None
    first = _parse_time(record.get('first_token_at'))
    completed = _parse_time(record.get('time'))
    if first is None:
        return 'missing', '缺少首 token 时间事件', None
    if completed is None:
        return 'missing', '缺少可信观测区间终点（执行未完成；不补造生成终点）', None
    retry = record.get('retry_count')
    if retry is None:
        return 'missing', '缺少 retry_count 证据，无法核查首 token 与最终输出的重试配对', None
    if retry != 0:
        return 'unsupported', '重试使首 token 与最终输出的配对不明（逻辑请求 retry_count>0）', None
    tool_exclusion = _tool_arg_exclusion(record)
    if tool_exclusion:
        return tool_exclusion[0], tool_exclusion[1], None
    interval = (completed - first) // MS
    if interval <= 0:
        return 'conflict', '零/负来源观测区间（不产生无穷吞吐）', None
    if completed >= end or (start is not None and completed < start):
        return 'range', '观测区间终点不在范围 [from,to) 内（完成未在截止前证实或界外事件排除）', None
    sample.update(output=output['value'], interval_ms=interval, basis='derived',
                  first_token_at=record['first_token_at'], completed_at=record['time'])
    return None, None, sample


def _perf_projections(samples, metric, zone):
    """Model/session/day members over the same valid set; every member keeps its own
    exact numerator/denominator so views are regenerated, never derived from rounded values."""
    def parts(sample):
        return (sample['value'], 1) if metric == 'ttft' else (sample['output'], sample['interval_ms'])

    def event_of(sample):
        return sample['first_token_at'] if metric == 'ttft' else sample['completed_at']

    def build(key_of, label_of, sort_of):
        groups = {}
        for sample in samples:
            groups.setdefault(key_of(sample), []).append(sample)
        members = []
        for key in sorted(groups, key=sort_of):
            subset = groups[key]
            members.append(dict(label_of(key, subset[0]),
                                sample_keys=sorted(s['key'] for s in subset),
                                numerator=sum(parts(s)[0] for s in subset),
                                denominator=sum(parts(s)[1] for s in subset)))
        return members

    models = build(lambda s: ((s['provider'], s['model'])),
                   lambda key, _: {'identity': {'provider': key[0], 'model': key[1]}},
                   lambda key: (key[0] or '', key[1]))
    sessions = build(lambda s: s['session'], lambda key, _: {'session': key}, lambda key: key)
    days = build(lambda s: timestamp(event_of(s)).astimezone(zone).date().isoformat(),
                 lambda key, _: {'date': key}, lambda key: key)
    return {'model': models, 'session': sessions, 'day': days}


def _tool_unavailable(harness, source_kind, tool_evidence):
    """Checked per-entry tool-support conclusions; supported unless the checked structure
    proves the source does not record tool executions."""
    if source_kind == 'zcode_database' and not tool_evidence:
        return ('数据库缺少 tool_usage 表或已核查列（结构已核查）；该结构来源未提供工具执行耗时证据，'
                '无法计算工具执行耗时')
    return None


def _empty_tool_metric(status, reason, candidates=0, supplements=None):
    metric = _empty_metric('tool_duration', status, reason, candidates)
    aggregate = metric['aggregate']
    aggregate['wall'] = {'value': None, 'state': 'unknown', 'unit': 'ns',
                         'basis': '工具集合调度/执行跨度包络：各样本调度或实际执行起止的最早起点至最晚终点；'
                                  '并行不扣除重叠，不等于执行耗时和，也不改变轮次墙钟',
                         'reason': '指标不可用，不给包络' if status != 'supported' else '无有效样本，不给包络（未知不画零）'}
    aggregate['supplements'] = supplements or []
    metric['projections'] = {'category': [], 'session': [], 'day': []}
    return metric


def build_performance(candidates, token_keys, harness, source_kind, since, cutoff, tz_name, tz_evidence,
                      columns=None, tool_candidates=None, tool_supplements=None, tool_evidence=None):
    """Performance section of the analysis extension: TTFT, source-observed-interval
    throughput and tool execution duration, each judged independently per metric.

    Candidates reuse the same sessions, turns/descendants, agent policy and source
    boundaries as the token selection but never enter it; admission is per metric by
    its own event ([from,to), event exactly at the cutoff excluded), and each metric
    aggregates over its own valid set only — throughput sums output over summed
    intervals, never averaging per-row rates. Tool candidates are an independent
    channel (no model usage required, never token records): the execution-duration
    sum keeps exact per-sample ns values, the scheduling span stays separate, and
    unmerged log supplements are listed, never double counted.
    """
    end = timestamp(cutoff)
    start = timestamp(since) if since else None
    zone = timezone_of(tz_name)
    section = {'harness': harness, 'source_kind': source_kind,
               'tz': {'name': tz_name, 'evidence': tz_evidence},
               'note': '性能候选复用相同会话、轮次/后代、代理策略与来源边界，独立判定，不进入 token 选集、不改变 token 合计；'
                       '有效集合与 token 集合的差异在各指标候选/有效计数与样本 record_key 引用中可见；'
                       '按相同 Harness、粒度与事件定义分别聚合，不做跨 Harness 效率比较',
               'metrics': {}}
    for name in ('ttft', 'throughput'):
        unavailable = _source_unavailable(harness, source_kind, columns, name)
        if unavailable is not None:
            section['metrics'][name] = _empty_metric(name, 'source_not_provided', unavailable, len(candidates))
            continue
        outcome = _ttft_outcome if name == 'ttft' else _throughput_outcome
        metric = _empty_metric(name, 'supported', '', len(candidates))
        aggregate = metric['aggregate']
        for record in candidates:
            kind, reason, sample = outcome(record, token_keys, start, end)
            if sample is None:
                aggregate['excluded'] += 1
                aggregate['excluded_by_kind'][kind] += 1
                aggregate['exclusion_reasons'][reason] = aggregate['exclusion_reasons'].get(reason, 0) + 1
                continue
            metric['samples'].append(sample)
        metric['samples'].sort(key=lambda s: s['key'])
        aggregate['valid'] = len(metric['samples'])
        if name == 'ttft':
            aggregate['numerator'] = sum(s['value'] for s in metric['samples'])
            aggregate['denominator'] = len(metric['samples'])
        else:
            aggregate['numerator'] = sum(s['output'] for s in metric['samples'])
            aggregate['denominator'] = sum(s['interval_ms'] for s in metric['samples'])
        aggregate['no_token_record'] = sum(1 for s in metric['samples'] if s['record_key'] is None)
        metric['projections'] = _perf_projections(metric['samples'], name, zone)
        section['metrics'][name] = metric
    tool_reason = _tool_unavailable(harness, source_kind, tool_evidence)
    if tool_reason is not None:
        section['metrics']['tool_duration'] = _empty_tool_metric('source_not_provided', tool_reason,
                                                                 len(tool_candidates or []), tool_supplements)
        return section
    metric = _empty_tool_metric('supported', '', len(tool_candidates or []), tool_supplements)
    aggregate = metric['aggregate']
    for event in tool_candidates or []:
        kind, reason, sample = _tool_outcome(event, start, end)
        if sample is None:
            aggregate['excluded'] += 1
            aggregate['excluded_by_kind'][kind] += 1
            aggregate['exclusion_reasons'][reason] = aggregate['exclusion_reasons'].get(reason, 0) + 1
            continue
        metric['samples'].append(sample)
    metric['samples'].sort(key=lambda s: s['key'])
    aggregate['valid'] = len(metric['samples'])
    aggregate['numerator'] = sum(s['value'] for s in metric['samples'])
    aggregate['denominator'] = len(metric['samples'])
    aggregate['no_token_record'] = len(metric['samples'])  # tools never reference token records
    aggregate['wall'] = _tool_wall(metric['samples'])
    metric['projections'] = _tool_projections(metric['samples'], zone)
    section['metrics']['tool_duration'] = metric
    return section
