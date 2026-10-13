'use strict';
/* Shared report validation and presentation for the offline viewer and the local web UI. */
const METRICS = ['input', 'output', 'cache_read', 'cache_write', 'reasoning', 'non_cache_read', 'total'];
const GROUP_LABELS = { main: '主代理常规调用', child: '子代理常规调用', internal: '内部辅助调用', unknown: '未分类' };
const STATES = { partial: '已记录小计', count_only: '仅调用计数', tool_only: '仅工具报告', confirmed_zero: '确认零用量',
                 unstatisticable: '不可统计', active: '截至当前记录，未结束', ended: '已结束', unknown: '未知' };
const SUPPORT_LABELS = { retry_failure: '重试/失败', compaction_summary: '压缩/摘要', title_session_aux: '标题/会话辅助',
                         subagent_descendants: '子代理/后代', background_other: '后台/其他' };
const SUPPORT_STATES = { not_checked: '尚未核查', checked_available: '已核查：有可靠记录',
                         checked_absent: '已核查：来源未提供', checked_gap: '已核查：存在缺口' };
const GRANULARITY_LABELS = { model_call: '逐调用用量', reply_usage: '唯一回复关联用量',
                             cumulative_interval: '累计差分区间', logical_request: '逻辑请求结果', unknown: '用量记录，粒度未知' };
const TIME_KIND_LABELS = { usage_record_time: 'usage 记录时间（无调用起点）', reply_usage_time: '回复关联 usage 记录时间',
                           count_interval_time: '累计计数区间终点', completion_time: '完成时间', unknown: '时间语义未知' };
const GRANULARITIES = ['model_call', 'reply_usage', 'cumulative_interval', 'logical_request', 'unknown'];
const TIME_KINDS = ['usage_record_time', 'reply_usage_time', 'count_interval_time', 'completion_time', 'unknown'];
const DURATION_STATES = ['known', 'unknown', 'conflict'];
const COST_COMPONENT_LABELS = { input: '总输入', non_cache_read: '非缓存读取输入', cache_read: '缓存读取', other_input: '其他输入',
                                cache_write: '缓存写入', output: '输出', other_output: '其他输出', reasoning: '推理输出' };
const COST_STATUS_LABELS = { priced: '完整计价', partially_priced: '部分计价', unpriced: '未定价', rule_conflict: '规则冲突' };
const RULE_COMPONENTS = {
  total_input: [['input', 'price_per_million']],
  split_cache_read: [['non_cache_read', 'non_cache_read_per_million'], ['cache_read', 'cache_read_per_million']],
  split_cache_read_write: [['other_input', 'other_input_per_million'], ['cache_read', 'cache_read_per_million'], ['cache_write', 'cache_write_per_million']],
  total_output: [['output', 'price_per_million']],
  split_reasoning: [['other_output', 'other_output_per_million'], ['reasoning', 'reasoning_per_million']],
};
const INPUT_COMPONENTS = ['input', 'non_cache_read', 'cache_read', 'other_input', 'cache_write'];
const DECIMAL_TEXT = /^(0|[1-9]\d*)(\.\d+)?$/;
function scaledDecimal(text) {
  // Exact decimal parsing over BigInt; amounts and unit prices never go through floats.
  if (typeof text !== 'string' || !DECIMAL_TEXT.test(text)) throw new Error('金额/单价必须是非负有限十进制字符串：' + String(text));
  const parts = text.split('.');
  const frac = parts[1] || '';
  return { value: BigInt(parts[0] + frac), scale: frac.length };
}
function canonScaled(value, scale) {
  let digits = value.toString();
  if (digits.length <= scale) digits = digits.padStart(scale + 1, '0');
  const intPart = digits.slice(0, digits.length - scale) || '0';
  const frac = scale ? digits.slice(-scale).replace(/0+$/, '') : '';
  return frac ? intPart + '.' + frac : intPart;
}
function componentAmountText(tokens, priceText) {
  const price = scaledDecimal(priceText);
  return canonScaled(BigInt(tokens) * price.value, price.scale + 6);
}
function sumAmounts(texts) {
  const parts = texts.map(scaledDecimal);
  const scale = Math.max(0, ...parts.map(p => p.scale));
  const total = parts.reduce((sum, p) => sum + p.value * 10n ** BigInt(scale - p.scale), 0n);
  return canonScaled(total, scale);
}
function displayAmount(text) {
  // Display default: exactly two decimals, round half up; the saved value stays unrounded.
  const s = scaledDecimal(text);
  const scale = Math.max(s.scale, 3);
  const v = s.value * 10n ** BigInt(scale - s.scale);
  const unit = 10n ** BigInt(scale - 2);
  let cents = v / unit;
  if ((v % unit) * 2n >= unit) cents += 1n;
  const digits = cents.toString().padStart(3, '0');
  return digits.slice(0, -2) + '.' + digits.slice(-2);
}
function compareAmountTexts(a, b) {
  // Exact decimal comparison over BigInt; ranking never goes through floats.
  const sa = scaledDecimal(a), sb = scaledDecimal(b);
  const scale = Math.max(sa.scale, sb.scale);
  const va = sa.value * 10n ** BigInt(scale - sa.scale);
  const vb = sb.value * 10n ** BigInt(scale - sb.scale);
  return va === vb ? 0 : va < vb ? -1 : 1;
}
function ruleComponentPrices(rule) {
  const pairs = RULE_COMPONENTS[rule.input.kind].concat(RULE_COMPONENTS[rule.output.kind]);
  return pairs.map(([name, key]) => [name, (INPUT_COMPONENTS.includes(name) ? rule.input : rule.output)[key]]);
}

function componentTokens(name, metrics) {
  const valueOf = key => {
    const metric = metrics[key];
    return metric && ['reported', 'derived'].includes(metric.state) && metric.value !== null ? metric.value : null;
  };
  if (name === 'other_input' || name === 'other_output') {
    const keys = name === 'other_input' ? ['input', 'cache_read', 'cache_write'] : ['output', 'reasoning'];
    const values = keys.map(valueOf);
    if (values.some(v => v === null)) return null;
    const value = values.slice(1).reduce((total, part) => total - part, values[0]);
    return value < 0n ? null : value;
  }
  return valueOf(name);
}
const TURN_STATUS_LABELS = { running: '进行中', completed: '已完成', cancelled: '已取消', error: '失败', unknown: '未知' };
const PRIVATE_KEYS = new Set(['request', 'response', 'headers', 'authorization', 'cookie', 'prompt', 'text', 'content', 'api_key', 'password']);
const TIMEZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const TIME_PARTS = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:\d{2})$/;
function validTime(value) {
  return typeof value === 'string' && TIMEZONE.test(value) && !Number.isNaN(Date.parse(value));
}
function instantMicros(value) {
  // Whole seconds go through the engine (correct calendar and numeric-offset handling);
  // sub-millisecond digits that Date.parse drops are added back so microsecond bounds
  // compare exactly instead of collapsing onto the millisecond.
  const match = TIME_PARTS.exec(value);
  const fraction = match ? ((match[1].match(/\.(\d+)$/) || [])[1] || '') : '';
  const sub = parseInt((fraction + '000').slice(3, 6), 10) || 0;
  return BigInt(Date.parse(value)) * 1000n + BigInt(sub);
}

function capabilityMissing() {
  const missing = [];
  if (typeof BigInt !== 'function') missing.push('BigInt 精确整数');
  if (!window.File || !window.FileReader) missing.push('本地文件选择');
  if (typeof SVGElement !== 'function') missing.push('SVG');
  return missing;
}

function sameValue(a, b) {
  if (typeof a === 'bigint' || typeof b === 'bigint') return typeof a === typeof b && a === b;
  if (a === b) return true;
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const key of keys) { if (!sameValue(a[key], b[key])) return false; }
    return true;
  }
  return false;
}

function fail(message) {
  const report = document.getElementById('report');
  report.hidden = true;
  report.textContent = '';
  document.getElementById('empty').hidden = false;
  const empty = document.getElementById('empty');
  empty.classList.add('error');
  empty.firstElementChild.textContent = '加载失败：' + message + '。本次展示已清空，请重新选择文件。';
}

function requireString(value, what) {
  if (typeof value !== 'string') throw new Error(what + ' 缺失或不是字符串');
  return value;
}
function isIndex(value) {
  return typeof value === 'bigint' && value >= 0n;
}
function checkAggregateRow(row, what) {
  if (!row || typeof row !== 'object') throw new Error(what + ' 结构无效');
  const metrics = row.metrics;
  if (!metrics || typeof metrics !== 'object') throw new Error(what + ' 缺少指标');
  for (const name of METRICS) {
    const metric = metrics[name];
    if (!metric || typeof metric !== 'object') throw new Error(what + ' 缺少指标 ' + name);
    if (metric.value !== null && !isIndex(metric.value)) throw new Error(what + ' 的 token 必须为非负整数或 null');
    if (!['known', 'partial', 'unknown'].includes(metric.state)) throw new Error(what + ' 指标状态未知');
    if (!Array.isArray(metric.reasons) || metric.reasons.some(r => typeof r !== 'string')) throw new Error(what + ' 缺少指标原因');
  }
  const rate = row.cache_hit_rate;
  if (!rate || typeof rate !== 'object') throw new Error(what + ' 缺少缓存覆盖状态');
  if (rate.value !== null && !((typeof rate.value === 'number' || typeof rate.value === 'bigint')
      && rate.value >= 0 && rate.value <= 1)) {
    throw new Error(what + ' 缓存命中率必须为 0 到 1 的数值或 null');
  }
  if (!['known', 'partial', 'unknown', 'not_applicable'].includes(rate.state)) throw new Error(what + ' 缓存覆盖状态未知');
  for (const key of ['paired_records', 'input', 'cache_read']) {
    if (!isIndex(rate[key])) throw new Error(what + ' 缓存覆盖量无效');
  }
  if (row.call_count !== null && !isIndex(row.call_count)) throw new Error(what + ' 调用数无效');
}
function checkPrivateKeys(value) {
  if (Array.isArray(value)) { value.forEach(checkPrivateKeys); return; }
  if (value && typeof value === 'object') {
    for (const key of Object.keys(value)) {
      if (PRIVATE_KEYS.has(key.toLowerCase())) throw new Error('报告包含合同以外的正文或认证字段：' + key);
      checkPrivateKeys(value[key]);
    }
  }
}
function checkSourceLoc(loc, what) {
  if (!loc || typeof loc !== 'object' || typeof loc.path !== 'string') throw new Error('无效的' + what);
  if ('line' in loc && (typeof loc.line !== 'bigint' || loc.line < 1n)) throw new Error('无效的' + what + '行号');
  if ('table' in loc && typeof loc.table !== 'string') throw new Error('无效的' + what + '表名');
  if ('id' in loc && !(typeof loc.id === 'string' || typeof loc.id === 'bigint')) throw new Error('无效的' + what + '行 ID');
  if (typeof loc.id === 'string' && !loc.id) throw new Error('无效的' + what + '行 ID');
}
function checkRecordExplanation(exp, key) {
  if (!exp || typeof exp !== 'object'
      || !GRANULARITIES.includes(exp.granularity) || !TIME_KINDS.includes(exp.time_kind)) {
    throw new Error('记录解释扩展无效：' + key);
  }
  const status = exp.status;
  if (!status || typeof status.read !== 'string' || typeof status.at_cutoff !== 'string' || typeof status.reason !== 'string') {
    throw new Error('记录解释状态无效：' + key);
  }
  const duration = exp.duration;
  if (!duration || duration.unit !== 'ms' || !DURATION_STATES.includes(duration.state) || typeof duration.reason !== 'string'
      || (duration.value !== null && !isIndex(duration.value))) {
    throw new Error('记录解释耗时无效：' + key);
  }
  const evidence = exp.classification_evidence;
  if (!evidence || typeof evidence.rule !== 'string' || typeof evidence.group !== 'string') {
    throw new Error('记录分类依据无效：' + key);
  }
  checkSourceLoc(evidence.source, '分类依据来源');
  const ownership = exp.ownership_evidence;
  if (!ownership || typeof ownership.owner_session !== 'string' || typeof ownership.rule !== 'string'
      || !Array.isArray(ownership.sources)) {
    throw new Error('记录归属依据无效：' + key);
  }
  ownership.sources.forEach(loc => checkSourceLoc(loc));
}
function checkRecordsExplanation(records, key) {
  const flags = records.map(r => r && typeof r === 'object' && 'explanation' in r);
  if (flags.some(Boolean) && !flags.every(Boolean)) throw new Error('记录解释扩展不完整：' + key);
  const keys = records.map(r => r && r.key);
  if (new Set(keys).size !== keys.length) throw new Error('记录键重复：' + key);
  for (const record of records) {
    if (record && 'explanation' in record) checkRecordExplanation(record.explanation, record.key || key);
  }
}
const TURN_STATUSES = ['running', 'completed', 'cancelled', 'error', 'unknown'];
const CUTOFF_STATUSES = ['ended_before_cutoff', 'ended_after_cutoff', 'not_confirmed_ended_at_cutoff', 'unknown_at_cutoff'];
const SPAN_STATES = ['in_range', 'extends_before', 'extends_after', 'extends_both', 'conflict', 'unknown', 'interval'];
const DURATION_SUM_STATES = ['complete', 'known_subset', 'unknown'];
function numOf(value) { return typeof value === 'bigint' ? Number(value) : value; }
function checkTurnRow(row, meteredByKey, what) {
  if (!row || typeof row !== 'object' || !['turn', 'cumulative_interval'].includes(row.kind)
      || typeof row.session !== 'string' || !TURN_STATUSES.includes(row.status)
      || !CUTOFF_STATUSES.includes(row.cutoff_status)
      || !SPAN_STATES.includes(row.span_state) || typeof row.span_reason !== 'string') {
    throw new Error('无效的轮次解释行：' + what);
  }
  if (row.kind === 'turn') {
    if (typeof row.turn !== 'string') throw new Error('轮次解释行缺少稳定轮次身份：' + what);
  } else {
    if (!validTime(row.interval_start) || !validTime(row.interval_end)) throw new Error('累计区间行边界无效：' + what);
    if (!(instantMicros(row.interval_start) < instantMicros(row.interval_end))) throw new Error('累计区间行边界无效：' + what);
  }
  for (const field of ['start', 'end']) {
    if (row[field] !== null && row[field] !== undefined && !validTime(row[field])) throw new Error('轮次解释行时间无效：' + what);
  }
  for (const field of ['start_source', 'end_source']) {
    if (row[field] !== null && row[field] !== undefined && typeof row[field] !== 'string') throw new Error('轮次解释行时间字段无效：' + what);
  }
  const native = row.native_duration_ms;
  if (native !== null && native !== undefined) {
    if (!native || typeof native !== 'object' || native.unit !== 'ms'
        || !['known', 'conflict'].includes(native.state) || typeof native.reason !== 'string'
        || (native.value !== null && !isIndex(native.value))) {
      throw new Error('原生轮次耗时无效：' + what);
    }
  }
  if (!Array.isArray(row.record_keys) || row.record_keys.some(k => typeof k !== 'string')) {
    throw new Error('轮次解释行引用无效：' + what);
  }
  for (const key of row.record_keys) {
    const record = meteredByKey.get(key);
    if (!record) throw new Error('轮次解释行引用悬空或不属于本报告计量记录：' + what);
    if (row.kind === 'turn') {
      if (record.interval_start) throw new Error('普通轮次行引用了累计区间记录：' + what);
      if (record.session !== row.session || record.turn !== row.turn) {
        throw new Error('轮次解释行引用了其他会话/轮次的记录：' + what);
      }
    } else {
      if (record.session !== row.session) throw new Error('累计区间行引用了其他会话的记录：' + what);
      if (!record.interval_start || record.interval_start !== row.interval_start
          || record.time !== row.interval_end) {
        throw new Error('累计区间行引用与区间边界不一致：' + what);
      }
      const recTurns = record.interval_turns || [], rowTurns = row.interval_turns || [];
      if (recTurns.length !== rowTurns.length || recTurns.some((t, i) => t !== rowTurns[i])) {
        throw new Error('累计区间行引用与涵盖轮次不一致：' + what);
      }
    }
  }
  checkAggregateRow(row, '轮次解释行 ' + what);
}
function checkActivityBlock(activity) {
  if (!activity || typeof activity !== 'object' || typeof activity.note !== 'string') throw new Error('解释活动结构无效');
  function checkWall(wall) {
    const wallValue = wall && wall.value !== null && wall.value !== undefined ? numOf(wall.value) : null;
    if (!wall || typeof wall !== 'object' || wall.unit !== 's'
        || !['known', 'unknown', 'conflict'].includes(wall.state)
        || typeof wall.basis !== 'string' || typeof wall.reason !== 'string'
        || (wallValue !== null && (typeof wallValue !== 'number' || Number.isNaN(wallValue) || wallValue < 0))) {
      throw new Error('墙钟解释无效');
    }
  }
  if (activity.wall) checkWall(activity.wall);
  if (activity.sessions) {
    if (typeof activity.sessions !== 'object' || Array.isArray(activity.sessions)) throw new Error('按会话墙钟解释无效');
    for (const sid of Object.keys(activity.sessions)) checkWall(activity.sessions[sid]);
  }
  const durations = activity.durations;
  if (!durations || typeof durations !== 'object') throw new Error('耗时覆盖解释无效');
  for (const granularity of Object.keys(durations)) {
    const bucket = durations[granularity];
    if (!['model_call', 'logical_request'].includes(granularity)) throw new Error('耗时覆盖含未知粒度：' + granularity);
    if (!bucket || typeof bucket !== 'object' || typeof bucket.label !== 'string' || bucket.unit !== 'ms'
        || !DURATION_SUM_STATES.includes(bucket.state)
        || (bucket.total_ms !== null && !isIndex(bucket.total_ms))) {
      throw new Error('耗时覆盖桶无效：' + granularity);
    }
    for (const field of ['valid', 'missing', 'conflict', 'records']) {
      if (!Number.isInteger(numOf(bucket[field])) || numOf(bucket[field]) < 0) throw new Error('耗时覆盖计数无效：' + granularity);
    }
  }
}
function checkExplanationBlock(exp, obj) {
  if (!exp || typeof exp !== 'object' || Array.isArray(exp)) throw new Error('解释扩展结构无效');
  for (const key of Object.keys(exp)) {
    if (!['turns', 'internal', 'activity', 'relations', 'excluded'].includes(key)) throw new Error('解释扩展含未知内容：' + key);
  }
  const meteredByKey = new Map((obj.records || []).map(r => [r.key, r]));
  for (const name of ['turns', 'internal', 'relations', 'excluded']) {
    if (name in exp && !Array.isArray(exp[name])) throw new Error('解释扩展结构无效：' + name);
  }
  if (exp.turns) exp.turns.forEach((row, i) => checkTurnRow(row, meteredByKey, 'turns ' + i));
  if (exp.activity) checkActivityBlock(exp.activity);
  if (exp.internal) exp.internal.forEach((row, i) => {
    if (!row || typeof row !== 'object' || !['compaction', 'session_aux', 'other_internal', 'unknown'].includes(row.category)
        || typeof row.label !== 'string' || typeof row.basis !== 'string') {
      throw new Error('无效的内部分布行：internal ' + i);
    }
    if (!Array.isArray(row.record_keys) || row.record_keys.some(k => typeof k !== 'string' || !meteredByKey.has(k))) {
      throw new Error('内部分布行引用无效：internal ' + i);
    }
    for (const key of row.record_keys) {
      if (meteredByKey.get(key).group !== 'internal') throw new Error('内部分布行混入非内部记录：internal ' + i);
    }
    checkAggregateRow(row, '内部分布行 ' + i);
  });
  if (exp.relations) exp.relations.forEach((row, i) => {
    if (!row || typeof row !== 'object' || !['parent_child', 'fork', 'inherited_copy'].includes(row.kind)
        || typeof row.session !== 'string' || typeof row.rule !== 'string'
        || !Array.isArray(row.sources) || !row.sources.length) {
      throw new Error('无效的关系行：relations ' + i);
    }
    row.sources.forEach(loc => checkSourceLoc(loc, '关系来源'));
  });
  if (exp.excluded) exp.excluded.forEach((row, i) => {
    if (!row || typeof row !== 'object' || typeof row.reason !== 'string') throw new Error('无效的排除行：excluded ' + i);
    if ('metrics' in row || 'record_keys' in row) throw new Error('排除项不得携带计量小计或记录引用：excluded ' + i);
    if (row.source !== null && row.source !== undefined) checkSourceLoc(row.source, '排除项来源');
  });
}

function checkPricingConfig(config) {
  // The browser independently validates the saved pricing snapshot (structure, version,
  // rule ids, times or conditions, price formats); it never matches rules or recomputes
  // prices for display. Schema v2 adds the official-estimate contract: read sources with
  // fetch times, condition-keyed rules, mappings and uncovered identities.
  const what = '价格配置快照';
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error(what + '必须是对象');
  if (typeof config.schema_version !== 'bigint' || ![1n, 2n].includes(config.schema_version)) throw new Error(what + '版本不支持');
  const v2 = config.schema_version === 2n;
  let sourceUrls = null;
  const topKeys = v2 ? ['schema_version', 'revision', 'price_basis', 'sources', 'rules', 'mappings', 'uncovered']
    : ['schema_version', 'revision', 'rules', 'aliases'];
  for (const key of Object.keys(config)) {
    if (!topKeys.includes(key)) throw new Error(what + '含未知字段：' + key);
  }
  if (typeof config.revision !== 'string' || !config.revision.trim()) throw new Error(what + '缺少修订标识');
  if (v2) {
    if (config.price_basis !== 'current_official_estimate') throw new Error(what + '价格口径无效');
    if (!Array.isArray(config.sources) || !config.sources.length) throw new Error(what + '快照来源必须是非空数组');
    config.sources.forEach((source, i) => {
      const name = '来源 ' + i;
      if (!source || typeof source !== 'object'
          || Object.keys(source).some(k => !['url', 'fetched_at', 'digest', 'summary'].includes(k))
          || typeof source.url !== 'string' || !source.url.trim()
          || typeof source.summary !== 'string' || !source.summary.trim()) throw new Error(what + name + '结构无效');
      if (!validTime(source.fetched_at)) throw new Error(what + name + '读取时间无效');
    });
    // v2 reference integrity: rules and mappings may only cite sources this very
    // snapshot actually read; a whitelisted-but-unread URL proves nothing here.
    sourceUrls = new Set(config.sources.map(source => source.url));
    if (!Array.isArray(config.uncovered)) throw new Error(what + '未覆盖项必须是数组');
    config.uncovered.forEach((item, i) => {
      const name = '未覆盖项 ' + i;
      if (!item || typeof item !== 'object' || Object.keys(item).sort().join(',') !== 'model,provider,reason'
          || (item.provider !== null && typeof item.provider !== 'string')
          || typeof item.model !== 'string' || !item.model.trim()
          || typeof item.reason !== 'string' || !item.reason.trim()) throw new Error(what + name + '结构无效');
    });
  }
  if (!Array.isArray(config.rules) || (v2 && !config.rules.length)) throw new Error(what + '规则必须是非空数组');
  const textOf = (value, name, max) => {
    if (typeof value !== 'string' || !value.trim() || value.length > (max || 256)) throw new Error(what + name + '必须是非空字符串');
    return value;
  };
  const priceOf = (value, name) => {
    if (typeof value !== 'string' || !DECIMAL_TEXT.test(value)) throw new Error(what + name + '必须是十进制字符串');
    return value;
  };
  const sourceOf = (value, name) => {
    if (!value || typeof value !== 'object'
        || typeof value.reference !== 'string' || typeof value.version !== 'string') throw new Error(what + name + '来源须含引用与版本');
  };
  const partitionOf = (value, kinds, name) => {
    if (!value || typeof value !== 'object' || !kinds.includes(value.kind)) throw new Error(what + name + '分区类型未知');
    for (const [, priceKey] of RULE_COMPONENTS[value.kind]) priceOf(value[priceKey], name + '单价 ' + priceKey);
    if (['split_cache_read_write', 'split_reasoning'].includes(value.kind)) textOf(value.basis, name + '互斥/包含依据', 512);
  };
  const conditionsMatch = (conditions, tokens) => {
    if ('input_min' in conditions && (tokens < conditions.input_min
        || (tokens === conditions.input_min && !conditions.input_min_inclusive))) return false;
    if ('input_max' in conditions && (tokens > conditions.input_max
        || (tokens === conditions.input_max && !conditions.input_max_inclusive))) return false;
    return true;
  };
  const rules = new Map();
  const ruleKeys = v2 ? ['id', 'source', 'provider', 'model', 'currency', 'input', 'output', 'conditions',
                         'official_effective_from', 'official_effective_to']
    : ['id', 'source', 'provider', 'model', 'effective_from', 'effective_to', 'currency', 'input', 'output'];
  const byIdentity = new Map();
  config.rules.forEach((rule, i) => {
    const name = '规则 ' + i;
    if (!rule || typeof rule !== 'object') throw new Error(what + name + '结构无效');
    for (const key of Object.keys(rule)) {
      if (!ruleKeys.includes(key)) throw new Error(what + name + '含未知字段：' + key);
    }
    textOf(rule.id, name + ' 稳定 ID', 128);
    if (rules.has(rule.id)) throw new Error(what + '规则 ID 重复 ' + rule.id);
    sourceOf(rule.source, name);
    if (v2 && !sourceUrls.has(rule.source.reference)) {
      throw new Error(what + name + '来源引用不在本快照读取来源内：' + rule.source.reference);
    }
    textOf(rule.provider, name + ' 供应商', 128);
    textOf(rule.model, name + ' 完整模型身份');
    textOf(rule.currency, name + ' 币种', 32);
    if (v2) {
      const conditions = rule.conditions;
      if (!conditions || typeof conditions !== 'object'
          || Object.keys(conditions).some(k => !['service_tier', 'input_min', 'input_min_inclusive',
                                                 'input_max', 'input_max_inclusive', 'basis'].includes(k))
          || conditions.service_tier !== 'standard') throw new Error(what + name + '价格条件结构无效');
      for (const side of ['min', 'max']) {
        if (('input_' + side) in conditions) {
          if (typeof conditions['input_' + side] !== 'bigint' || conditions['input_' + side] <= 0n
              || typeof conditions['input_' + side + '_inclusive'] !== 'boolean') {
            throw new Error(what + name + '输入条件必须为正整数并明确等值点');
          }
        }
      }
      if ('input_min' in conditions && 'input_max' in conditions) {
        if (conditions.input_min > conditions.input_max
            || (conditions.input_min === conditions.input_max
                && !(conditions.input_min_inclusive && conditions.input_max_inclusive))) {
          throw new Error(what + name + '输入条件区间为空');
        }
      }
      textOf(conditions.basis, name + '档位条件依据', 512);
      if (rule.official_effective_from !== undefined && rule.official_effective_from !== null
          && !validTime(rule.official_effective_from)) throw new Error(what + name + ' 官网生效起点无效');
      if (rule.official_effective_to !== undefined && rule.official_effective_to !== null
          && !validTime(rule.official_effective_to)) throw new Error(what + name + ' 官网生效终点无效');
      const key = rule.provider + '\u0001' + rule.model;
      const peers = byIdentity.get(key) || [];
      for (const other of peers) {
        const lows = [other.conditions, conditions].filter(c => 'input_min' in c).map(c => c.input_min);
        const highs = [other.conditions, conditions].filter(c => 'input_max' in c).map(c => c.input_max);
        let overlap;
        if (!lows.length || !highs.length) overlap = true;
        else {
          const lower = lows.reduce((a, b) => a > b ? a : b), upper = highs.reduce((a, b) => a < b ? a : b);
          overlap = lower !== upper ? lower < upper
            : conditionsMatch(other.conditions, lower) && conditionsMatch(conditions, lower);
        }
        if (overlap) throw new Error(what + name + '与规则 ' + other.id + ' 在同一身份与档位下条件区间重叠');
      }
      peers.push(rule);
      byIdentity.set(key, peers);
    } else {
      if (!validTime(rule.effective_from)) throw new Error(what + name + ' 生效起点无效');
      if (rule.effective_to !== undefined && rule.effective_to !== null) {
        if (!validTime(rule.effective_to)) throw new Error(what + name + ' 生效终点无效');
        if (!(instantMicros(rule.effective_from) < instantMicros(rule.effective_to))) throw new Error(what + name + ' 生效区间无效');
      }
    }
    partitionOf(rule.input, ['total_input', 'split_cache_read', 'split_cache_read_write'], name + ' 输入');
    partitionOf(rule.output, ['total_output', 'split_reasoning'], name + ' 输出');
    rules.set(rule.id, rule);
  });
  const items = v2 ? config.mappings : (config.aliases || []);
  if (!Array.isArray(items)) throw new Error(what + (v2 ? '映射' : '别名') + '必须是数组');
  const links = new Map();
  const linkFrom = new Map();
  items.forEach((item, i) => {
    const name = (v2 ? '映射 ' : '别名 ') + i;
    if (!item || typeof item !== 'object'
        || !['id', 'source', 'from', 'to', 'basis'].every(k => k in item)
        || Object.keys(item).length !== 5) throw new Error(what + name + '结构未知');
    textOf(item.id, name + ' 稳定 ID', 128);
    sourceOf(item.source, name);
    if (v2 && !sourceUrls.has(item.source.reference)) {
      throw new Error(what + name + '来源引用不在本快照读取来源内：' + item.source.reference);
    }
    textOf(item.basis, name + ' 映射依据', 512);
    for (const endpoint of ['from', 'to']) {
      const point = item[endpoint];
      if (!point || typeof point !== 'object') throw new Error(what + name + ' ' + endpoint + ' 身份无效');
      textOf(point.provider, name + ' ' + endpoint + ' 供应商', 128);
      textOf(point.model, name + ' ' + endpoint + ' 完整模型身份');
    }
    if (item.from.provider === item.to.provider && item.from.model === item.to.model) {
      throw new Error(what + name + ' 源与目标身份相同（循环映射）');
    }
    const key = item.from.provider + '\u0001' + item.from.model;
    if (linkFrom.has(key)) throw new Error(what + name + ' 与其他' + (v2 ? '映射' : '别名') + '的源身份冲突');
    linkFrom.set(key, item);
    links.set(item.id, item);
  });
  for (const item of links.values()) {
    if (linkFrom.has(item.to.provider + '\u0001' + item.to.model)) {
      throw new Error(what + (v2 ? '映射' : '别名') + '只允许一次精确映射，不支持链式推断');
    }
  }
  return { rules, links, v2, conditionsMatch };
}

function costTotals(entries) {
  // Exact per-currency BigInt totals over one set of pricing entries (audit recompute).
  const totals = {};
  for (const entry of entries) {
    if (!entry.components.length) continue;
    const bucket = totals[entry.currency] = totals[entry.currency] || { amounts: [], components: {} };
    for (const component of entry.components) {
      const cell = bucket.components[component.name] = bucket.components[component.name] || { tokens: 0n, amounts: [] };
      cell.tokens += component.tokens;
      cell.amounts.push(component.amount);
      bucket.amounts.push(component.amount);
    }
  }
  return totals;
}

function checkProjectionCurrencies(saved, expected, what) {
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) throw new Error('费用投影币种无效：' + what);
  const names = Object.keys(expected).sort();
  if (Object.keys(saved).sort().join('') !== names.join('')) throw new Error('费用投影币种集合与逐记录计价不一致：' + what);
  for (const currency of names) {
    const bucket = saved[currency];
    if (!bucket || typeof bucket !== 'object'
        || Object.keys(bucket).sort().join(',') !== 'amount,components') throw new Error('费用投影币种结构无效：' + what);
    if (bucket.amount !== sumAmounts(expected[currency].amounts)) throw new Error('费用投影金额与逐记录计价不一致：' + what);
    const components = bucket.components;
    const expectedComponents = expected[currency].components;
    const componentNames = Object.keys(expectedComponents).sort();
    if (!components || typeof components !== 'object'
        || Object.keys(components).sort().join('') !== componentNames.join('')) throw new Error('费用投影分项集合不一致：' + what);
    for (const name of componentNames) {
      const cell = components[name];
      const expectedCell = expectedComponents[name];
      if (!cell || typeof cell !== 'object' || cell.tokens !== expectedCell.tokens
          || cell.amount !== sumAmounts(expectedCell.amounts)) throw new Error('费用投影分项与逐记录计价不一致：' + what);
    }
  }
}

function checkCostProjections(obj, entries, projections) {
  if (!projections || typeof projections !== 'object' || Array.isArray(projections)
      || Object.keys(projections).sort().join(',') !== 'day,model,session,unbucketed') throw new Error('费用投影结构无效');
  const entryByKey = new Map(entries.map(e => [e.record_key, e]));
  const sessionOf = new Map((obj.records || []).map(r => [r.key, r.session]));
  const priced = entries.filter(e => e.components.length);
  const checkMember = (member, keys, what) => {
    if (!member || typeof member !== 'object') throw new Error('费用投影成员结构无效：' + what);
    const savedKeys = member.record_keys;
    if (!Array.isArray(savedKeys) || savedKeys.some(k => typeof k !== 'string')) throw new Error('费用投影成员记录引用无效：' + what);
    // One Set per member replaces the per-key includes scan over the same list.
    const savedKeySet = new Set(savedKeys);
    if (savedKeySet.size !== savedKeys.length || savedKeys.length !== keys.length
        || keys.some(k => !savedKeySet.has(k))) throw new Error('费用投影成员记录集合不一致：' + what);
    checkProjectionCurrencies(member.currencies, costTotals(savedKeys.map(k => entryByKey.get(k))), what);
  };
  const modelGroups = new Map();
  for (const entry of priced) {
    const key = entry.identity.provider + '' + entry.identity.model;
    if (!modelGroups.has(key)) modelGroups.set(key, { identity: entry.identity, keys: [] });
    modelGroups.get(key).keys.push(entry.record_key);
  }
  if (!Array.isArray(projections.model) || projections.model.length !== modelGroups.size) {
    throw new Error('模型费用投影成员集合与逐记录计价不一致');
  }
  const seenModels = new Set();
  projections.model.forEach((member, i) => {
    const what = 'model ' + i;
    const identity = member && member.identity;
    if (!identity || typeof identity.provider !== 'string' || !identity.provider
        || typeof identity.model !== 'string' || !identity.model) throw new Error('模型费用投影身份无效：' + what);
    const key = identity.provider + '' + identity.model;
    if (seenModels.has(key) || !modelGroups.has(key)) throw new Error('模型费用投影成员重复或身份无已计价记录：' + what);
    seenModels.add(key);
    checkMember(member, modelGroups.get(key).keys, what);
  });
  const sessionGroups = new Map();
  for (const entry of priced) {
    const sid = sessionOf.get(entry.record_key);
    if (!sessionGroups.has(sid)) sessionGroups.set(sid, []);
    sessionGroups.get(sid).push(entry.record_key);
  }
  if (!Array.isArray(projections.session) || projections.session.length !== sessionGroups.size) {
    throw new Error('会话费用投影成员集合与逐记录计价不一致');
  }
  const seenSessions = new Set();
  projections.session.forEach((member, i) => {
    const what = 'session ' + i;
    if (typeof member.session !== 'string' || seenSessions.has(member.session) || !sessionGroups.has(member.session)) {
      throw new Error('会话费用投影成员重复或身份无已计价记录：' + what);
    }
    seenSessions.add(member.session);
    checkMember(member, sessionGroups.get(member.session), what);
  });
  const reportDays = obj.days || [];
  if (!Array.isArray(projections.day) || projections.day.length !== reportDays.length) {
    throw new Error('日期费用投影与本报告日趋势不一致');
  }
  const memberDates = projections.day.map(m => m.date);
  const sortedDates = memberDates.slice().sort();
  const partition = new Set();
  projections.day.forEach((member, i) => {
    if (member.date !== reportDays[i].date || memberDates[i] !== sortedDates[i]) {
      throw new Error('日期费用投影日期与本报告日趋势不一致：day ' + i);
    }
    checkMember(member, reportDays[i].record_keys, 'day ' + i);
    member.record_keys.forEach(k => partition.add(k));
  });
  checkMember(projections.unbucketed, (obj.unbucketed || {}).record_keys || [], 'unbucketed');
  projections.unbucketed.record_keys.forEach(k => partition.add(k));
  // Day members plus the unbucketed item partition every metered record: the projections
  // reconcile against the per-currency summary instead of adding into it.
  const metered = (obj.records || []).map(r => r.key);
  if (partition.size !== metered.length || metered.some(k => !partition.has(k))) {
    throw new Error('日期费用投影与无法归日项未覆盖本报告全部计量记录');
  }
}

const PERF_METRIC_NAMES = ['ttft', 'throughput'];
const PERF_ALL_METRICS = ['ttft', 'throughput', 'tool_duration'];
const PERF_EXCLUSION_KINDS = ['missing', 'conflict', 'unsupported', 'range'];
const PERF_SUPPORT_STATES = ['supported', 'source_not_provided', 'not_checked'];
const PERF_COMPLETION_STATES = ['ended_before_cutoff', 'ended_after_cutoff', 'no_end_evidence'];
const PERF_UNITS = { ttft: { numerator: 'ms', denominator: '样本', value: 'ms' },
                     throughput: { numerator: 'token', denominator: 'ms', value: 'token/s' },
                     tool_duration: { numerator: 'ns', denominator: '样本', value: 'ms' } };
const TOOL_SAMPLE_STATES = ['completed', 'failed'];
function sameUnits(a, b) {
  return a && typeof a === 'object' && !Array.isArray(a)
    && Object.keys(b).every(k => a[k] === b[k]) && Object.keys(a).length === Object.keys(b).length;
}
function perfDayOf(isoTime, tzName) {
  // Local calendar date of an event in the saved timezone; day buckets are never
  // recomputed by ad-hoc browser rules, this mirrors the kernel day-boundary rule.
  const ms = Number(instantMicros(isoTime) / 1000n);
  const offset = /^([+-])(\d{2}):(\d{2})$/.exec(tzName);
  if (offset) {
    const minutes = (parseInt(offset[2], 10) * 60 + parseInt(offset[3], 10)) * (offset[1] === '+' ? 1 : -1);
    return new Date(ms + minutes * 60000).toISOString().slice(0, 10);
  }
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: tzName, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date(ms));
  const get = type => parts.find(p => p.type === type).value;
  return get('year') + '-' + get('month') + '-' + get('day');
}
function checkPerfSample(sample, name, recordsByKey, what) {
  if (!sample || typeof sample !== 'object' || Array.isArray(sample)) throw new Error('性能样本结构无效：' + what);
  const common = ['key', 'record_key', 'session', 'turn', 'owner_session', 'owner_turn', 'granularity',
                  'provider', 'model', 'precision', 'source'];
  const expected = name === 'ttft'
    ? common.concat(['value', 'basis', 'started_at', 'first_token_at', 'native_ttft_ms', 'completed_at', 'completion'])
    : common.concat(['output', 'interval_ms', 'basis', 'first_token_at', 'completed_at']);
  const keys = Object.keys(sample);
  if (keys.length !== expected.length || expected.some(k => !(k in sample))) throw new Error('性能样本结构无效：' + what);
  if (typeof sample.key !== 'string') throw new Error('性能样本缺少稳定样本键：' + what);
  if (sample.record_key !== null && (typeof sample.record_key !== 'string' || !recordsByKey.has(sample.record_key))) {
    throw new Error('性能样本引用了本报告不存在的 token 记录（悬空引用）：' + what);
  }
  if (typeof sample.session !== 'string' || typeof sample.owner_session !== 'string') throw new Error('性能样本会话/归属无效：' + what);
  for (const field of ['turn', 'owner_turn']) {
    if (sample[field] !== null && typeof sample[field] !== 'string') throw new Error('性能样本轮次/归属无效：' + what);
  }
  if (!GRANULARITIES.includes(sample.granularity)) throw new Error('性能样本粒度未知：' + what);
  if (sample.provider !== null && typeof sample.provider !== 'string') throw new Error('性能样本供应商无效：' + what);
  if (typeof sample.model !== 'string' || !sample.model) throw new Error('性能样本模型无效：' + what);
  if (sample.precision !== 'ms' || !['native', 'derived'].includes(sample.basis)) throw new Error('性能样本精度/依据无效：' + what);
  checkSourceLoc(sample.source, '性能样本来源');
  const timeOf = (field, required) => {
    const value = sample[field];
    if (value === null) {
      if (required) throw new Error('性能样本缺少事件时间 ' + field + '：' + what);
      return null;
    }
    if (!validTime(value)) throw new Error('性能样本事件时间无效：' + what);
    return value;
  };
  const nonneg = (field, minimum) => {
    const value = sample[field];
    if (typeof value !== 'bigint' || value < minimum) throw new Error('性能样本数值无效（非有限或负数不入有效值）：' + what);
    return value;
  };
  const first = timeOf('first_token_at', true);
  timeOf('completed_at', false);
  if (name === 'ttft') {
    const began = timeOf('started_at', true);
    const value = nonneg('value', 0n);
    const native = sample.native_ttft_ms;
    if (native !== null && (typeof native !== 'bigint' || native < 0n)) throw new Error('性能样本原生 TTFT 无效：' + what);
    if (value !== (instantMicros(first) - instantMicros(began)) / 1000n) {
      throw new Error('性能样本 TTFT 与事件时间差矛盾（坏样本冲突）：' + what);
    }
    if ((native === null) !== (sample.basis === 'derived') || (native !== null && native !== value)) {
      throw new Error('性能样本原生 TTFT 与推导值/依据矛盾（坏样本冲突）：' + what);
    }
    if (!PERF_COMPLETION_STATES.includes(sample.completion)) throw new Error('性能样本完成状态未知：' + what);
    return [value, 1n];
  }
  const output = nonneg('output', 0n);
  const interval = nonneg('interval_ms', 1n);
  const completed = timeOf('completed_at', true);
  if (interval !== (instantMicros(completed) - instantMicros(first)) / 1000n) {
    throw new Error('性能样本观测区间与事件时间差矛盾（坏样本冲突）：' + what);
  }
  return [output, interval];
}
function checkToolSample(sample, what) {
  // One saved tool-duration sample: stable identity, finished status, exact ns value with
  // its native/derived basis, and separately saved scheduling endpoints.
  const expected = ['basis', 'category', 'completed_at', 'dispatch_end', 'dispatch_start', 'exec_end', 'exec_start',
                    'key', 'native_duration_ns', 'owner_session', 'owner_turn', 'precision', 'record_key',
                    'session', 'source', 'status', 'turn', 'value'];
  if (!sample || typeof sample !== 'object' || Array.isArray(sample)
      || Object.keys(sample).sort().join(',') !== expected.join(',')) throw new Error('工具样本结构无效：' + what);
  if (typeof sample.key !== 'string') throw new Error('工具样本缺少稳定样本键：' + what);
  if (sample.record_key !== null) throw new Error('工具样本不得引用 token 记录（独立通道，不伪造引用）：' + what);
  if (typeof sample.session !== 'string' || typeof sample.owner_session !== 'string') throw new Error('工具样本会话/归属无效：' + what);
  for (const field of ['turn', 'owner_turn']) {
    if (sample[field] !== null && typeof sample[field] !== 'string') throw new Error('工具样本轮次/归属无效：' + what);
  }
  if (typeof sample.category !== 'string' || !sample.category) throw new Error('工具样本类别无效：' + what);
  if (!TOOL_SAMPLE_STATES.includes(sample.status)) throw new Error('工具样本状态无效（仅已完成/已失败执行携带耗时）：' + what);
  if (typeof sample.value !== 'bigint' || sample.value < 0n) throw new Error('工具样本耗时无效（非有限或负数不入有效值）：' + what);
  if (!['native', 'derived'].includes(sample.basis) || !['ns', 'ms'].includes(sample.precision)) {
    throw new Error('工具样本依据/精度无效：' + what);
  }
  const native = sample.native_duration_ns;
  if (sample.basis === 'native') {
    if (typeof native !== 'bigint' || native !== sample.value) throw new Error('工具样本原生耗时与有效值矛盾（坏样本冲突）：' + what);
  } else if (native !== null) {
    throw new Error('推导耗时样本不得携带原生值（坏样本冲突）：' + what);
  }
  const timeOf = (field, required) => {
    const value = sample[field];
    if (value === null) {
      if (required) throw new Error('工具样本缺少事件时间：' + what);
      return null;
    }
    if (!validTime(value)) throw new Error('工具样本事件时间无效：' + what);
    return value;
  };
  const execStart = timeOf('exec_start', false);
  const execEnd = timeOf('exec_end', false);
  timeOf('completed_at', true);
  if ((execStart === null) !== (execEnd === null)) throw new Error('工具样本执行起止必须成对出现：' + what);
  if (execStart !== null) {
    const span = (instantMicros(execEnd) - instantMicros(execStart)) / 1000n;
    if (span < 0n) throw new Error('工具样本执行起止逆序：' + what);
    if (sample.basis === 'derived' && sample.value !== span * 1000000n) {
      throw new Error('工具样本推导耗时与执行起止跨度矛盾（坏样本冲突）：' + what);
    }
  }
  const dispatchStart = timeOf('dispatch_start', false);
  const dispatchEnd = timeOf('dispatch_end', false);
  if ((dispatchStart === null) !== (dispatchEnd === null)) throw new Error('工具样本调度起止必须成对出现：' + what);
  if (dispatchStart !== null && instantMicros(dispatchEnd) < instantMicros(dispatchStart)) {
    throw new Error('工具样本调度起止逆序：' + what);
  }
  checkSourceLoc(sample.source, '工具样本来源');
  return sample.value;
}
function toolWallOf(samples) {
  // Recompute the saved span envelope from the samples themselves (audit rule).
  if (!samples.length) return ['unknown', null];
  const begins = [], ends = [];
  let missing = false;
  for (const sample of samples) {
    const start = sample.dispatch_start || sample.exec_start;
    const end = sample.dispatch_end || sample.exec_end;
    if (start === null || end === null) { missing = true; continue; }
    if (instantMicros(end) < instantMicros(start)) return ['conflict', null];
    begins.push(instantMicros(start));
    ends.push(instantMicros(end));
  }
  if (missing) return ['unknown', null];
  const min = begins.reduce((a, b) => a < b ? a : b);
  const max = ends.reduce((a, b) => a > b ? a : b);
  return ['known', (max - min) / 1000n * 1000000n];
}
function checkToolDurationBlock(obj, metric, tzName) {
  // Tool-execution-duration metric: independent channel (samples never reference token
  // records), exact ns sums, the span envelope recomputed from samples, and unmerged
  // supplements listed with reasons.
  const what = '性能指标 tool_duration';
  const support = metric.support;
  const samples = metric.samples, aggregate = metric.aggregate, projections = metric.projections;
  if (!projections || typeof projections !== 'object' || Array.isArray(projections)
      || Object.keys(projections).sort().join(',') !== 'category,day,session') {
    throw new Error('工具指标投影结构无效：' + what);
  }
  if (!aggregate || typeof aggregate !== 'object'
      || Object.keys(aggregate).sort().join(',')
         !== 'candidates,denominator,display,excluded,excluded_by_kind,exclusion_reasons,no_token_record,numerator,supplements,valid,wall') {
    throw new Error('工具指标聚合结构无效：' + what);
  }
  const display = aggregate.display;
  if (!display || typeof display !== 'object' || display.decimals !== 2n
      || display.rounding !== 'half_up' || typeof display.note !== 'string') throw new Error('性能显示精度说明无效：' + what);
  const wall = aggregate.wall;
  if (!wall || typeof wall !== 'object'
      || Object.keys(wall).sort().join(',') !== 'basis,reason,state,unit,value'
      || wall.unit !== 'ns' || !['known', 'unknown', 'conflict'].includes(wall.state)
      || typeof wall.basis !== 'string' || !wall.basis || typeof wall.reason !== 'string' || !wall.reason
      || (wall.value !== null && (typeof wall.value !== 'bigint' || wall.value < 0n))) {
    throw new Error('工具跨度包络无效：' + what);
  }
  const supplements = aggregate.supplements;
  if (!Array.isArray(supplements)) throw new Error('工具补充项结构无效：' + what);
  supplements.forEach((item, i) => {
    if (!item || typeof item !== 'object'
        || Object.keys(item).sort().join(',') !== 'key,reason,session,source'
        || typeof item.key !== 'string' || typeof item.session !== 'string'
        || typeof item.reason !== 'string' || !item.reason) throw new Error('工具补充项结构无效：' + what + ' supplements ' + i);
    checkSourceLoc(item.source, '工具补充项来源');
  });
  const nonnegCount = value => typeof value === 'bigint' && value >= 0n;
  if (support.status !== 'supported') {
    if (!support.reason || samples.length || projections.category.length || projections.session.length || projections.day.length) {
      throw new Error('不可用指标不得携带有效样本或投影：' + what);
    }
    if (aggregate.valid !== 0n || aggregate.excluded !== 0n || aggregate.numerator !== 0n || aggregate.denominator !== 0n
        || aggregate.no_token_record !== 0n || Object.keys(aggregate.exclusion_reasons).length
        || PERF_EXCLUSION_KINDS.some(k => aggregate.excluded_by_kind[k] !== 0n)) {
      throw new Error('不可用指标不得携带有效值：' + what);
    }
    if (!nonnegCount(aggregate.candidates)) throw new Error('性能候选计数无效：' + what);
    if (wall.value !== null || wall.state !== 'unknown') throw new Error('不可用指标不得携带跨度包络值：' + what);
    return;
  }
  const keys = samples.map(s => s && s.key);
  if (new Set(keys).size !== keys.length) throw new Error('工具样本键重复：' + what);
  if (keys.some((k, i) => i && keys[i - 1] >= k)) throw new Error('工具样本顺序无效（须按键排序）：' + what);
  let total = 0n;
  samples.forEach((sample, i) => { total += checkToolSample(sample, what + ' 样本 ' + i); });
  for (const field of ['candidates', 'valid', 'excluded', 'numerator', 'denominator', 'no_token_record']) {
    if (!nonnegCount(aggregate[field])) throw new Error('工具聚合计数无效：' + what);
  }
  if (aggregate.valid !== BigInt(samples.length) || aggregate.candidates !== aggregate.valid + aggregate.excluded) {
    throw new Error('工具候选/有效/排除计数不一致：' + what);
  }
  if (aggregate.numerator !== total || aggregate.denominator !== BigInt(samples.length)
      || aggregate.no_token_record !== BigInt(samples.length)) {
    throw new Error('工具聚合分子/分母与样本重算不一致：' + what);
  }
  const kinds = aggregate.excluded_by_kind;
  if (!kinds || typeof kinds !== 'object' || Object.keys(kinds).sort().join(',') !== PERF_EXCLUSION_KINDS.slice().sort().join(',')
      || PERF_EXCLUSION_KINDS.some(k => !nonnegCount(kinds[k]))
      || PERF_EXCLUSION_KINDS.reduce((sum, k) => sum + kinds[k], 0n) !== aggregate.excluded) {
    throw new Error('工具排除分类计数不一致：' + what);
  }
  const reasons = aggregate.exclusion_reasons;
  if (!reasons || typeof reasons !== 'object' || Array.isArray(reasons)
      || Object.keys(reasons).some(r => typeof reasons[r] !== 'bigint' || reasons[r] < 1n)
      || Object.keys(reasons).reduce((sum, r) => sum + reasons[r], 0n) !== aggregate.excluded) {
    throw new Error('工具排除原因计数不一致：' + what);
  }
  const wallParts = toolWallOf(samples);
  if (wall.state !== wallParts[0] || wall.value !== wallParts[1]) throw new Error('工具跨度包络与样本重算不一致：' + what);
  const memberCheck = (members, keyOf, labelField) => {
    const groups = new Map();
    for (const sample of samples) {
      const key = keyOf(sample);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(sample.key);
    }
    // Per-label sample-key Sets let the numerator re-sum stay O(samples) per member
    // check instead of scanning the whole sample list per label.
    const groupSets = new Map([...groups].map(([label, keys]) => [label, new Set(keys)]));
    if (!Array.isArray(members) || members.length !== groups.size) throw new Error('工具投影成员集合与样本重算不一致：' + what);
    const seen = new Set();
    members.forEach(member => {
      if (!member || typeof member !== 'object'
          || Object.keys(member).sort().join(',') !== [labelField, 'denominator', 'numerator', 'sample_keys'].sort().join(',')) {
        throw new Error('工具投影成员结构无效：' + what);
      }
      const label = member[labelField];
      if (typeof label !== 'string' || !label) throw new Error('工具投影成员标签无效：' + what);
      if (seen.has(label) || !groups.has(label)) throw new Error('工具投影成员重复或无对应样本：' + what);
      seen.add(label);
      const expectedKeys = groups.get(label).slice().sort();
      if (!Array.isArray(member.sample_keys) || member.sample_keys.length !== expectedKeys.length
          || expectedKeys.some((k, i) => member.sample_keys[i] !== k)) {
        throw new Error('工具投影成员样本集合与重算不一致：' + what);
      }
      let numerator = 0n;
      for (const sample of samples) if (groupSets.get(label).has(sample.key)) numerator += sample.value;
      if (member.numerator !== numerator || member.denominator !== BigInt(groups.get(label).length)) {
        throw new Error('工具投影成员分子/分母与样本重算不一致：' + what);
      }
    });
    const sortedKeys = [...seen].sort();
    if (members.some((m, i) => m[labelField] !== sortedKeys[i])) throw new Error('工具投影成员顺序无效：' + what);
  };
  memberCheck(projections.category, s => s.category, 'category');
  memberCheck(projections.session, s => s.session, 'session');
  memberCheck(projections.day, s => perfDayOf(s.completed_at, tzName), 'date');
}
function checkPerformanceBlock(obj, perf) {
  // Independent per-metric valid sets with exact numerator/denominator; conflicting
  // samples, dangling record references, negative/non-finite valid values and aggregate
  // inconsistencies are rejected, never silently dropped.
  if (!perf || typeof perf !== 'object' || Array.isArray(perf)
      || Object.keys(perf).sort().join(',') !== 'harness,metrics,note,source_kind,tz') {
    throw new Error('性能分析扩展结构无效');
  }
  if (perf.harness !== obj.harness || perf.source_kind !== obj.input.kind) {
    throw new Error('性能分析与本报告 Harness/来源入口不一致');
  }
  const tz = perf.tz;
  if (!tz || typeof tz !== 'object' || Object.keys(tz).sort().join(',') !== 'evidence,name'
      || typeof tz.name !== 'string' || !tz.name || typeof tz.evidence !== 'string' || !tz.evidence) {
    throw new Error('性能分析日分布时区说明无效');
  }
  if (typeof perf.note !== 'string' || !perf.metrics || typeof perf.metrics !== 'object' || Array.isArray(perf.metrics)
      || !perf.metrics.ttft || !perf.metrics.throughput
      || Object.keys(perf.metrics).some(k => !PERF_ALL_METRICS.includes(k))) throw new Error('性能分析指标结构无效');
  const recordsByKey = new Map((obj.records || []).map(r => [r.key, r]));
  for (const name of PERF_ALL_METRICS) {
    if (!(name in perf.metrics)) continue;  // reports saved before the tool metric stay legal
    const what = '性能指标 ' + name;
    const metric = perf.metrics[name];
    if (!metric || typeof metric !== 'object'
        || Object.keys(metric).sort().join(',') !== 'admission,aggregate,definition,label,overhead,projections,samples,support,unit,units') {
      throw new Error('性能指标结构无效：' + what);
    }
    for (const field of ['label', 'definition', 'admission']) {
      if (typeof metric[field] !== 'string' || !metric[field]) throw new Error('性能指标事件定义无效：' + what);
    }
    if (metric.unit !== PERF_UNITS[name].value || !sameUnits(metric.units, PERF_UNITS[name])) throw new Error('性能指标单位无效：' + what);
    if ((name !== 'throughput' && metric.overhead !== null)
        || (name === 'throughput' && (typeof metric.overhead !== 'string' || !metric.overhead))) {
      throw new Error('性能指标开销标注无效：' + what);
    }
    const support = metric.support;
    if (!support || typeof support !== 'object' || Object.keys(support).sort().join(',') !== 'reason,status'
        || !PERF_SUPPORT_STATES.includes(support.status) || typeof support.reason !== 'string') {
      throw new Error('性能指标支持状态无效：' + what);
    }
    if (!Array.isArray(metric.samples)) throw new Error('性能指标样本/投影结构无效：' + what);
    if (name === 'tool_duration') {
      checkToolDurationBlock(obj, metric, perf.tz.name);
      continue;
    }
    const samples = metric.samples, aggregate = metric.aggregate, projections = metric.projections;
    if (!Array.isArray(samples) || !projections || typeof projections !== 'object'
        || Object.keys(projections).sort().join(',') !== 'day,model,session') throw new Error('性能指标样本/投影结构无效：' + what);
    if (!aggregate || typeof aggregate !== 'object'
        || Object.keys(aggregate).sort().join(',') !== 'candidates,denominator,display,excluded,excluded_by_kind,exclusion_reasons,no_token_record,numerator,valid') {
      throw new Error('性能聚合结构无效：' + what);
    }
    const display = aggregate.display;
    if (!display || typeof display !== 'object' || display.decimals !== 2n
        || display.rounding !== 'half_up' || typeof display.note !== 'string') throw new Error('性能显示精度说明无效：' + what);
    const nonnegCount = value => typeof value === 'bigint' && value >= 0n;
    if (support.status !== 'supported') {
      if (!support.reason || samples.length || projections.model.length || projections.session.length || projections.day.length) {
        throw new Error('不可用指标不得携带有效样本或投影：' + what);
      }
      if (aggregate.valid !== 0n || aggregate.excluded !== 0n || aggregate.numerator !== 0n || aggregate.denominator !== 0n
          || aggregate.no_token_record !== 0n || Object.keys(aggregate.exclusion_reasons).length
          || PERF_EXCLUSION_KINDS.some(k => aggregate.excluded_by_kind[k] !== 0n)) {
        throw new Error('不可用指标不得携带有效值：' + what);
      }
      if (!nonnegCount(aggregate.candidates)) throw new Error('性能候选计数无效：' + what);
      continue;
    }
    const keys = samples.map(s => s && s.key);
    if (new Set(keys).size !== keys.length) throw new Error('性能样本键重复：' + what);
    if (keys.some((k, i) => i && keys[i - 1] >= k)) throw new Error('性能样本顺序无效（须按键排序）：' + what);
    let numerator = 0n, denominator = 0n, noToken = 0n;
    samples.forEach((sample, i) => {
      const parts = checkPerfSample(sample, name, recordsByKey, what + ' 样本 ' + i);
      numerator += parts[0];
      denominator += parts[1];
      if (sample.record_key === null) noToken += 1n;
    });
    for (const field of ['candidates', 'valid', 'excluded', 'numerator', 'denominator', 'no_token_record']) {
      if (!nonnegCount(aggregate[field])) throw new Error('性能聚合计数无效：' + what);
    }
    if (aggregate.valid !== BigInt(samples.length) || aggregate.candidates !== aggregate.valid + aggregate.excluded) {
      throw new Error('性能候选/有效/排除计数不一致：' + what);
    }
    if (aggregate.numerator !== numerator || aggregate.denominator !== denominator) {
      throw new Error('性能聚合分子/分母与样本重算不一致：' + what);
    }
    if (aggregate.no_token_record !== noToken) throw new Error('性能无 token 记录样本计数不一致：' + what);
    const kinds = aggregate.excluded_by_kind;
    if (!kinds || typeof kinds !== 'object' || Object.keys(kinds).sort().join(',') !== PERF_EXCLUSION_KINDS.slice().sort().join(',')
        || PERF_EXCLUSION_KINDS.some(k => !nonnegCount(kinds[k]))
        || PERF_EXCLUSION_KINDS.reduce((sum, k) => sum + kinds[k], 0n) !== aggregate.excluded) {
      throw new Error('性能排除分类计数不一致：' + what);
    }
    const reasons = aggregate.exclusion_reasons;
    if (!reasons || typeof reasons !== 'object' || Array.isArray(reasons)
        || Object.keys(reasons).some(r => typeof reasons[r] !== 'bigint' || reasons[r] < 1n)
        || Object.keys(reasons).reduce((sum, r) => sum + reasons[r], 0n) !== aggregate.excluded) {
      throw new Error('性能排除原因计数不一致：' + what);
    }
    const partOf = sample => name === 'ttft' ? [sample.value, 1n] : [sample.output, sample.interval_ms];
    const eventOf = sample => name === 'ttft' ? sample.first_token_at : sample.completed_at;
    const memberCheck = (members, keyOf, labelField, labelOf, labelCheck) => {
      const groups = new Map();
      for (const sample of samples) {
        const key = keyOf(sample);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(sample.key);
      }
      // Per-label key Sets keep the numerator/denominator re-sum linear in samples.
      const groupSets = new Map([...groups].map(([key, keys]) => [key, new Set(keys)]));
      if (!Array.isArray(members) || members.length !== groups.size) throw new Error('性能投影成员集合与样本重算不一致：' + what);
      const seen = new Set();
      members.forEach(member => {
        if (!member || typeof member !== 'object'
            || Object.keys(member).sort().join(',') !== [labelField, 'denominator', 'numerator', 'sample_keys'].sort().join(',')) {
          throw new Error('性能投影成员结构无效：' + what);
        }
        const key = labelOf(labelCheck(member[labelField]));
        if (seen.has(key) || !groups.has(key)) throw new Error('性能投影成员重复或无对应样本：' + what);
        seen.add(key);
        const expectedKeys = groups.get(key).slice().sort();
        if (!Array.isArray(member.sample_keys) || member.sample_keys.length !== expectedKeys.length
            || expectedKeys.some((k, i) => member.sample_keys[i] !== k)) {
          throw new Error('性能投影成员样本集合与重算不一致：' + what);
        }
        let n = 0n, d = 0n;
        for (const sample of samples) {
          if (!groupSets.get(key).has(sample.key)) continue;
          const parts = partOf(sample);
          n += parts[0];
          d += parts[1];
        }
        if (member.numerator !== n || member.denominator !== d) throw new Error('性能投影成员分子/分母与样本重算不一致：' + what);
      });
      const sortedKeys = [...seen].sort();
      if (members.some((m, i) => labelOf(labelCheck(m[labelField])) !== sortedKeys[i])) {
        throw new Error('性能投影成员顺序无效：' + what);
      }
    };
    memberCheck(projections.model,
      s => (s.provider === null ? '' : s.provider) + '' + s.model, 'identity',
      label => (label.provider === null ? '' : label.provider) + '' + label.model,
      label => {
        if (!label || typeof label !== 'object' || Object.keys(label).sort().join(',') !== 'model,provider'
            || (label.provider !== null && typeof label.provider !== 'string')
            || typeof label.model !== 'string' || !label.model) throw new Error('性能投影模型身份无效：' + what);
        return label;
      });
    memberCheck(projections.session, s => s.session, 'session', label => label, label => {
      if (typeof label !== 'string' || !label) throw new Error('性能投影成员标签无效：' + what);
      return label;
    });
    memberCheck(projections.day, s => perfDayOf(eventOf(s), tz.name), 'date', label => label, label => {
      if (typeof label !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(label)) throw new Error('性能投影成员标签无效：' + what);
      return label;
    });
  }
}
function checkAnalysisBlock(obj) {
  const ext = obj.analysis;
  if (!ext || typeof ext !== 'object' || Array.isArray(ext)) throw new Error('未知的分析扩展版本或结构');
  const extKeys = Object.keys(ext);
  if (typeof ext.schema_version !== 'bigint' || ![1n, 2n].includes(ext.schema_version)
      || extKeys.some(k => !['schema_version', 'cost', 'performance'].includes(k))
      || (!ext.cost && !ext.performance)) throw new Error('未知的分析扩展版本或结构');
  if (ext.schema_version === 2n && !ext.cost) throw new Error('分析扩展版本 2 必须携带 v2 价格快照费用区');
  if (ext.cost) checkCostBlock(obj, ext.cost, ext.schema_version);
  if (ext.performance) checkPerformanceBlock(obj, ext.performance);
}

function checkCostBlock(obj, cost, extSchema) {
  const overall = (typeof obj.format_version === 'bigint' ? Number(obj.format_version) : obj.format_version) === 3;
  // Projections are required on overall (v3) reports and forbidden on single-session ones.
  const expectedCostKeys = overall ? 'config,projections,records,summary' : 'config,records,summary';
  if (typeof cost !== 'object' || Array.isArray(cost)
      || Object.keys(cost).sort().join(',') !== expectedCostKeys) throw new Error('费用分析扩展结构无效');
  const { rules, v2, conditionsMatch } = checkPricingConfig(cost.config);
  if (v2 !== (extSchema === 2n)) throw new Error('分析扩展版本与价格快照版本不一致');
  const linkField = v2 ? 'mapping_id' : 'alias_id';
  // Link ids are not guaranteed unique in saved configs (the writer only enforces unique
  // source identities), so lookups search the list instead of an id-keyed map.
  const linkItems = v2 ? cost.config.mappings : (cost.config.aliases || []);
  if (!Array.isArray(cost.records)) throw new Error('费用分析逐记录计价必须是数组');
  const meteredByKey = new Map((obj.records || []).map(record => [record.key, record]));
  const keys = [];
  cost.records.forEach((entry, i) => {
    const what = 'analysis.records ' + i;
    if (!entry || typeof entry !== 'object') throw new Error('逐记录计价结构无效：' + what);
    for (const key of Object.keys(entry)) {
      if (!['record_key', 'identity', 'status', 'currency', 'matched', 'components', 'unpriced', 'conflicts'].includes(key)) {
        throw new Error('逐记录计价结构无效：' + what);
      }
    }
    if (typeof entry.record_key !== 'string') throw new Error('逐记录计价缺少记录引用：' + what);
    keys.push(entry.record_key);
    if (!['priced', 'partially_priced', 'unpriced', 'rule_conflict'].includes(entry.status)) {
      throw new Error('逐记录计价状态未知：' + what);
    }
    if (entry.identity !== null && entry.identity !== undefined) {
      const identity = entry.identity;
      if (typeof identity !== 'object' || typeof identity.provider !== 'string' || !identity.provider
          || typeof identity.model !== 'string' || !identity.model) throw new Error('逐记录计价身份无效：' + what);
    }
    let rule = null;
    if (entry.matched !== null && entry.matched !== undefined) {
      const matched = entry.matched;
      if (typeof matched !== 'object' || typeof matched.rule_id !== 'string') throw new Error('逐记录计价命中结构无效：' + what);
      rule = rules.get(matched.rule_id);
      if (!rule) throw new Error('逐记录计价引用了配置中不存在的规则：' + what);
      if (matched[linkField] !== null && matched[linkField] !== undefined
          && !linkItems.some(l => l.id === matched[linkField])) {
        throw new Error('逐记录计价引用了配置中不存在的映射：' + what);
      }
      const record = meteredByKey.get(entry.record_key), identity = entry.identity;
      if (!identity || !record || identity.provider !== record.provider || identity.model !== record.model) {
        throw new Error('计价身份与引用计量记录不一致：' + what);
      }
      let ruleIdentity = identity;
      if (matched[linkField] !== null && matched[linkField] !== undefined) {
        const link = linkItems.find(l => l.id === matched[linkField]
          && l.from.provider === identity.provider && l.from.model === identity.model);
        if (!link) {
          throw new Error('计价映射来源身份与引用计量记录不一致：' + what);
        }
        ruleIdentity = link.to;
      }
      if (ruleIdentity.provider !== rule.provider || ruleIdentity.model !== rule.model) {
        throw new Error('命中价格规则身份与引用计量记录或映射目标不一致：' + what);
      }
      if (entry.currency !== rule.currency) throw new Error('逐记录计价币种与命中规则不一致：' + what);
      if (v2) {
        // v2 matched evidence carries the judged tier conditions; the browser re-checks
        // them against the record's own granularity and input without pricing anything.
        const conditions = rule.conditions;
        const bounded = 'input_min' in conditions || 'input_max' in conditions;
        const allowed = ['rule_id', linkField, 'input_tokens', 'condition_basis'];
        const granularity = (record.explanation || {}).granularity;
        if (bounded && granularity === 'logical_request') allowed.push('retry_count');
        for (const key of Object.keys(matched)) {
          if (!allowed.includes(key)) throw new Error('逐记录计价命中结构无效：' + what);
        }
        if (matched.condition_basis !== conditions.basis) throw new Error('计价命中条件依据与规则不一致：' + what);
        if (bounded) {
          if (typeof matched.input_tokens !== 'bigint' || matched.input_tokens < 0n
              || !conditionsMatch(conditions, matched.input_tokens)) {
            throw new Error('计价命中的单请求输入量不满足规则输入条件：' + what);
          }
          const metric = (record.metrics || {}).input;
          if (!metric || metric.value !== matched.input_tokens) {
            throw new Error('计价命中的单请求输入量与记录输入不一致：' + what);
          }
          if (granularity === 'logical_request') {
            if (matched.retry_count !== 0n) throw new Error('逻辑请求档位判定须携带 retry_count=0 证据：' + what);
          } else if (!['model_call', 'reply_usage'].includes(granularity)) {
            throw new Error('该记录粒度不能证明完整单请求输入量，档位判定证据不足：' + what);
          }
        } else if (matched.input_tokens !== null && matched.input_tokens !== undefined) {
          throw new Error('规则无输入条件时命中证据不得携带输入量：' + what);
        }
      }
    }
    if (!Array.isArray(entry.components)) throw new Error('逐记录计价分项无效：' + what);
    const expected = rule ? new Map(ruleComponentPrices(rule)) : new Map();
    const seen = new Set();
    for (const component of entry.components) {
      if (!component || typeof component !== 'object') throw new Error('计价分项结构无效：' + what);
      if (!expected.has(component.name) || seen.has(component.name)) throw new Error('计价分项不属于命中规则或重复：' + what);
      seen.add(component.name);
      if (!isIndex(component.tokens)) throw new Error('计价分项 token 必须为非负整数：' + what);
      const record = meteredByKey.get(entry.record_key);
      const partition = record ? componentTokens(component.name, record.metrics) : null;
      if (partition === null || component.tokens !== partition) throw new Error('计价分区 token 与引用计量记录不一致：' + what);
      if (component.price_per_million !== expected.get(component.name)) throw new Error('计价分项单价与命中规则不一致：' + what);
      if (componentAmountText(component.tokens, component.price_per_million) !== component.amount) {
        throw new Error('计价分项金额与精确 token×单价 不一致：' + what);
      }
    }
    if (!Array.isArray(entry.unpriced)) throw new Error('逐记录未定价原因无效：' + what);
    for (const item of entry.unpriced) {
      if (!item || typeof item !== 'object'
          || (item.component !== null && typeof item.component !== 'string')
          || typeof item.reason !== 'string') throw new Error('逐记录未定价原因无效：' + what);
    }
    const total = expected.size;
    if (entry.status === 'priced' && (!rule || entry.components.length !== total)) throw new Error('计价状态与分项不一致：' + what);
    if (entry.status === 'partially_priced' && !(rule && entry.components.length > 0 && entry.components.length < total)) {
      throw new Error('计价状态与分项不一致：' + what);
    }
    if (['unpriced', 'rule_conflict'].includes(entry.status) && entry.components.length) {
      throw new Error('计价状态与分项不一致：' + what);
    }
    if (entry.status === 'rule_conflict') {
      if (entry.matched !== null && entry.matched !== undefined) throw new Error('规则冲突记录不得携带命中规则：' + what);
      if (!Array.isArray(entry.conflicts) || entry.conflicts.length < 2
          || entry.conflicts.some(c => typeof c !== 'string' || !rules.has(c))) {
        throw new Error('规则冲突记录须列出配置中存在的冲突规则：' + what);
      }
    } else if ('conflicts' in entry) {
      throw new Error('非冲突记录不得携带冲突规则列表：' + what);
    }
  });
  if (new Set(keys).size !== keys.length) throw new Error('逐记录计价记录引用重复');
  const metered = new Set((obj.records || []).map(r => r.key));
  if (keys.length !== metered.size || keys.some(k => !metered.has(k))) {
    throw new Error('逐记录计价未覆盖本报告全部计量记录或引用悬空');
  }
  const summary = cost.summary;
  if (!summary || typeof summary !== 'object'
      || Object.keys(summary).sort().join(',') !== 'currencies,display,partially_priced,priced,records,rule_conflicts,unpriced,unpriced_reasons') {
    throw new Error('费用摘要结构无效');
  }
  const counts = { records: 0n, priced: 0n, partially_priced: 0n, unpriced: 0n, rule_conflicts: 0n };
  const reasons = {};
  const recordCounts = {};
  for (const entry of cost.records) {
    counts.records += 1n;
    counts[{ priced: 'priced', partially_priced: 'partially_priced', unpriced: 'unpriced', rule_conflict: 'rule_conflicts' }[entry.status]] += 1n;
    for (const item of entry.unpriced) reasons[item.reason] = (reasons[item.reason] || 0n) + 1n;
    if (!entry.components.length) continue;
    const countsBucket = recordCounts[entry.currency] = recordCounts[entry.currency] || { priced_records: 0n, partially_priced_records: 0n };
    countsBucket[{ priced: 'priced_records', partially_priced: 'partially_priced_records' }[entry.status]] += 1n;
  }
  const totals = costTotals(cost.records);
  for (const field of ['records', 'priced', 'partially_priced', 'unpriced', 'rule_conflicts']) {
    if (summary[field] !== counts[field]) throw new Error('费用摘要计数与逐记录计价不一致');
  }
  const currencies = summary.currencies;
  if (!currencies || typeof currencies !== 'object' || Array.isArray(currencies)) throw new Error('费用摘要币种无效');
  const expectedCurrencies = Object.keys(totals).sort();
  if (Object.keys(currencies).sort().join('') !== expectedCurrencies.join('')) throw new Error('费用摘要币种集合与逐记录计价不一致');
  for (const currency of expectedCurrencies) {
    const bucket = currencies[currency];
    const expected = totals[currency];
    if (!bucket || typeof bucket !== 'object'
        || Object.keys(bucket).sort().join(',') !== 'amount,components,partially_priced_records,priced_records') {
      throw new Error('币种费用摘要结构无效：' + currency);
    }
    if (bucket.amount !== sumAmounts(expected.amounts)) throw new Error('币种费用摘要金额与逐记录计价不一致：' + currency);
    if (bucket.priced_records !== recordCounts[currency].priced_records
        || bucket.partially_priced_records !== recordCounts[currency].partially_priced_records) {
      throw new Error('币种费用摘要计数不一致：' + currency);
    }
    const names = Object.keys(expected.components).sort();
    if (!bucket.components || typeof bucket.components !== 'object'
        || Object.keys(bucket.components).sort().join('') !== names.join('')) throw new Error('币种费用摘要分项集合不一致：' + currency);
    for (const name of names) {
      const cell = bucket.components[name];
      const expectedCell = expected.components[name];
      if (!cell || typeof cell !== 'object' || cell.tokens !== expectedCell.tokens
          || cell.amount !== sumAmounts(expectedCell.amounts)) {
        throw new Error('币种费用摘要分项与逐记录计价不一致：' + currency);
      }
    }
  }
  const summaryReasons = summary.unpriced_reasons;
  if (!summaryReasons || typeof summaryReasons !== 'object' || Array.isArray(summaryReasons)) throw new Error('费用摘要未定价原因无效');
  const reasonKeys = Object.keys(reasons);
  if (Object.keys(summaryReasons).length !== reasonKeys.length
      || reasonKeys.some(k => summaryReasons[k] !== reasons[k])) throw new Error('费用摘要未定价原因与逐记录计价不一致');
  const display = summary.display;
  if (!display || typeof display !== 'object' || display.decimals !== 2n
      || display.rounding !== 'half_up' || typeof display.note !== 'string') throw new Error('费用摘要显示精度说明无效');
  if (overall) checkCostProjections(obj, cost.records, cost.projections);
}

function validateReport(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) throw new Error('JSON 顶层必须是报告对象');
  // Lossless parsing turns integer literals into BigInt; normalize small contract integers.
  const asNumber = value => typeof value === 'bigint' ? Number(value) : value;
  const version = asNumber(obj.format_version);
  if (version !== 1 && version !== 2 && version !== 3) throw new Error('不支持的报告格式版本：' + String(version));
  const scope = obj.scope;
  if (!scope || typeof scope !== 'object') throw new Error('报告缺少范围结构');
  if (!['codex', 'zcode'].includes(obj.harness)) throw new Error('无效的 Harness');
  if (version === 3) {
    if (scope.kind !== 'overall') throw new Error('整体报告缺少范围类型');
    if (!Array.isArray(scope.sessions)
        || scope.sessions.some(s => typeof s !== 'string')) throw new Error('无效的整体会话集合');
    requireString(scope.tz, '显示时区');
  } else {
    requireString(scope.session, '会话标识');
  }
  if (!validTime(scope.to)) throw new Error('截止点必须是带时区的有效时间');
  if (scope.from !== null && !validTime(scope.from)) throw new Error('时间下界必须是带时区的有效时间');
  if (version !== 3 && scope.turns !== null && (!Array.isArray(scope.turns) || scope.turns.some(t => typeof t !== 'string'))) throw new Error('无效的轮次集合');
  if (typeof scope.main_only !== 'boolean' || typeof scope.include_children !== 'boolean' || scope.main_only === scope.include_children) {
    throw new Error('不一致的子代理策略');
  }
  requireString(scope.cutoff_source, '截止点来源');
  const aggregateRows = [...(obj.rows || []), obj.summary, ...(obj.details || [])];
  aggregateRows.forEach((row, i) => checkAggregateRow(row, '分组/汇总行 ' + i));
  const rowRecordsByKey = new Map((obj.records || []).map(r => [r.key, r]));
  for (const row of obj.rows || []) {
    const keys = row.record_keys;
    if (keys === undefined || keys === null) continue;
    if (!Array.isArray(keys) || keys.some(k => typeof k !== 'string')) throw new Error('分组行记录引用无效');
    for (const key of keys) {
      const record = rowRecordsByKey.get(key);
      if (!record) throw new Error('分组行引用悬空记录');
      if (record.group !== row.group) throw new Error('分组行记录引用与互斥分组不一致');
    }
  }
  if (version === 2 || version === 3) {
    const loc = obj.localization;
    if (!loc || typeof loc !== 'object') throw new Error('v' + version + ' 缺少定位证据');
    if (version === 3) {
      if (!loc.sessions || typeof loc.sessions.confirmed_by !== 'string' || typeof loc.sessions.evidence !== 'string'
          || asNumber(loc.sessions.count) !== scope.sessions.length) throw new Error('定位证据与会话集合不一致');
    } else {
      if (!loc.session || requireString(loc.session.id, '定位会话') !== scope.session) throw new Error('定位证据与会话不一致');
      requireString(loc.session.confirmed_by, '定位会话确认方式');
      requireString(loc.session.evidence, '定位会话证据');
    }
    if (!loc.cutoff || requireString(loc.cutoff.source, '定位截止点来源') !== scope.cutoff_source
        || requireString(loc.cutoff.time, '定位截止点') !== scope.to) throw new Error('定位证据与截止点不一致');
    requireString(loc.cutoff.evidence, '定位截止点证据');
    if (!Array.isArray(loc.limits) || loc.limits.some(x => typeof x !== 'string')) throw new Error('无效的定位限制');
    const support = obj.internal_support;
    const supportKeys = Object.keys(SUPPORT_LABELS);
    if (!support || typeof support !== 'object'
        || supportKeys.length !== Object.keys(support).length
        || !supportKeys.every(k => support[k])) throw new Error('缺失或多余的内部来源支持类别');
    for (const key of supportKeys) {
      const item = support[key];
      if (typeof item.status !== 'string' || typeof item.summary !== 'string' || !Array.isArray(item.evidence)) {
        throw new Error('无效的内部来源支持说明：' + key);
      }
    }
    const views = obj.views;
    if (!views || typeof views !== 'object' || !['model', 'agent', 'turn'].every(d => views[d])) throw new Error('缺失报告展示视图');
    const recordsByKey = new Map((obj.records || []).map(r => [r.key, r]));
    const sessionIdOf = scope.session;
    for (const dimension of ['model', 'agent', 'turn']) {
      const view = views[dimension];
      if (typeof view.available !== 'boolean' || typeof view.reason !== 'string' || !Array.isArray(view.rows)) {
        throw new Error('无效的展示视图：' + dimension);
      }
      if (version === 3 && dimension === 'turn' && view.available) throw new Error('整体报告的轮次视图必须标记不可用');
      checkViewRows(view, dimension, recordsByKey, sessionIdOf);
    }
    for (const detail of obj.details || []) {
      const matches = views[detail.dimension].rows.filter(row => row.label === detail.name);
      if (matches.length !== 1
          || !sameValue(matches[0].metrics, detail.metrics)
          || !sameValue(matches[0].cache_hit_rate, detail.cache_hit_rate)
          || !sameValue(matches[0].call_count, detail.call_count)) {
        throw new Error('明细与保存视图投影不一致');
      }
    }
    for (const alt of obj.alternate_sources || []) {
      if (!alt || typeof alt !== 'object') throw new Error('无效的补充来源说明');
      requireString(alt.kind, '补充来源类型');
      requireString(alt.path, '补充来源路径');
      requireString(alt.session, '补充来源会话');
      requireString(alt.note, '补充来源说明');
      if (!isIndex(alt.records)) throw new Error('补充来源记录数无效');
      checkAggregateRow(alt, '补充来源');
    }
  }
  if (version === 3) {
    const v3RecordsByKey = new Map((obj.records || []).map(r => [r.key, r]));
    for (const day of obj.days || []) {
      if (!day || typeof day.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day.date)) throw new Error('无效的日趋势日期');
      if (!Number.isInteger(asNumber(day.sessions)) || asNumber(day.sessions) < 0) throw new Error('无效的日会话计数');
      if (!validTime(day.from) || !validTime(day.to)) throw new Error('日趋势行缺少有效的交集范围');
      if (!(instantMicros(day.from) < instantMicros(day.to))) throw new Error('无效的日趋势交集范围');
      checkAggregateRow(day, '日趋势行 ' + day.date);
      if (day.record_keys !== undefined && day.record_keys !== null) {
        if (!Array.isArray(day.record_keys) || day.record_keys.some(k => typeof k !== 'string' || !v3RecordsByKey.has(k))) {
          throw new Error('日趋势行记录引用无效');
        }
      }
      for (const key of ['by_model', 'by_session']) {
        if (!Array.isArray(day[key])) throw new Error('无效的日分布：' + key);
        let memberUnion = new Set();
        day[key].forEach((row, i) => {
          if (typeof row.id !== 'string' || typeof row.label !== 'string') throw new Error('无效的日分布行身份：' + key + ' ' + i);
          checkAggregateRow(row, '日分布行 ' + key + ' ' + i);
          const keys = row.record_keys;
          if (keys === undefined || keys === null) return;
          if (!Array.isArray(keys) || keys.some(k => typeof k !== 'string' || !v3RecordsByKey.has(k))) {
            throw new Error('日分布行记录引用无效：' + key);
          }
          keys.forEach(k => memberUnion.add(k));
        });
        if (day.record_keys !== undefined && day.record_keys !== null
            && memberUnion.size !== new Set(day.record_keys).size) throw new Error('日分布成员与当日记录集合不一致');
      }
    }
    if (!Array.isArray(obj.days)) throw new Error('缺失日趋势');
    const rankings = obj.rankings;
    if (!rankings || typeof rankings !== 'object' || !['model', 'session'].every(d => rankings[d])) throw new Error('缺失整体排行');
    for (const dimension of ['model', 'session']) {
      const view = rankings[dimension];
      if (typeof view.available !== 'boolean' || typeof view.reason !== 'string' || !Array.isArray(view.rows)) {
        throw new Error('无效的整体排行：' + dimension);
      }
      view.rows.forEach((row, i) => {
        if (typeof row.id !== 'string' || typeof row.label !== 'string') throw new Error('无效的排行行身份：' + dimension + ' ' + i);
        checkAggregateRow(row, '排行行 ' + dimension + ' ' + i);
      });
    }
    if (!Array.isArray(obj.session_index) || obj.session_index.some(x => !x || typeof x.id !== 'string')) {
      throw new Error('无效的会话索引');
    }
    const unbucketed = obj.unbucketed;
    if (!unbucketed || typeof unbucketed !== 'object' || !isIndex(unbucketed.records)
        || !Array.isArray(unbucketed.reasons) || unbucketed.reasons.some(r => typeof r !== 'string')) {
      throw new Error('无效的无法归桶说明');
    }
    checkAggregateRow(unbucketed, '无法归桶');
  }
  for (const key of ['records', 'source_files', 'issues', 'tool_reports']) {
    if (!Array.isArray(obj[key])) throw new Error('缺失报告结构：' + key);
  }
  checkRecordsExplanation(obj.records || [], 'records');
  checkRecordsExplanation(obj.unassigned_records || [], 'unassigned_records');
  if ('explanation' in obj) {
    if (version === 1) throw new Error('v1 报告不含解释扩展');
    checkExplanationBlock(obj.explanation, obj);
  }
  if ('analysis' in obj) {
    if (version === 1) throw new Error('v1 报告不含分析扩展');
    checkAnalysisBlock(obj);
  }
  for (const key of ['read_at', 'status', 'coverage']) requireString(obj[key], '报告元数据 ' + key);
  const input = obj.input;
  if (!input || !['jsonl', 'zcode_database'].includes(input.kind)
      || !Array.isArray(input.paths) || input.paths.length === 0
      || input.paths.some(p => typeof p !== 'string')) throw new Error('无效的来源描述');
  checkPrivateKeys(obj);
  return version;
}

function fmtInt(value, state) {
  if (value === null || value === undefined) return null;
  const text = value.toString();
  const grouped = text.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return state && state !== 'known' ? { text: grouped, partial: true } : { text: grouped, partial: false };
}
function cellInt(value, state) {
  const formatted = fmtInt(value, state);
  if (!formatted) return { text: '未知', unknown: true };
  return { text: formatted.text + (formatted.partial ? '（部分）' : ''), partial: formatted.partial };
}
function percent(rate) {
  if (!rate) return { text: '未知', unknown: true };
  // Coverage comes from the report's own paired subset: the denominator is the paired
  // input, never the total input; unknown and zero-denominator stay distinguishable.
  if (rate.value === null) {
    return { text: rate.state === 'not_applicable' ? '不适用（配对输入为 0）' : '未知', unknown: true };
  }
  const pct = (typeof rate.value === 'bigint' ? Number(rate.value) : rate.value) * 100;
  const text = (Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(3).replace(/0+$/, '')) + '%';
  if (rate.state === 'partial') {
    return { text: text + `（已知子集：${rate.paired_records.toString()} 条，配对输入 ${rate.input.toString()}）`, partial: true };
  }
  return { text };
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function tableScroll(table) {
  const wrap = el('div', 'table-scroll');
  wrap.appendChild(table);
  return wrap;
}
function evidenceCard(title, nodes) {
  const details = el('details', 'card evidence');
  const summary = document.createElement('summary');
  summary.textContent = title;
  details.appendChild(summary);
  const body = el('div', 'evidence-body');
  nodes.forEach(n => body.appendChild(n));
  details.appendChild(body);
  return details;
}

function lazyEvidenceCard(title, build) {
  // Same collapsed contract as evidenceCard, but the body is generated on the first
  // open only: long tables cost nothing until the user actually asks for them.
  const details = el('details', 'card evidence');
  const summary = document.createElement('summary');
  summary.textContent = title;
  details.appendChild(summary);
  const body = el('div', 'evidence-body');
  details.appendChild(body);
  details.addEventListener('toggle', () => {
    if (details.open && !body.firstChild) {
      try {
        build(body);
      } catch (error) {
        body.appendChild(el('p', 'unavailable', '本区生成失败：' + (error && error.message ? error.message : String(error))));
      }
    }
  });
  return details;
}

function pagedBody(headRow, rows, drawRow, opts) {
  // A table body that shows rows in pages of 20 with prev/next controls. Locate flows
  // narrow the visible row set itself, so the located targets are always on view.
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  let page = 0;
  const frag = document.createDocumentFragment();
  const table = document.createElement('table');
  if (opts && opts.className) table.className = opts.className;
  const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
  const tbody = document.createElement('tbody'); table.appendChild(tbody);
  const bar = el('p', 'hint-line pager');
  const draw = () => {
    tbody.textContent = '';
    const start = page * pageSize;
    for (const row of rows.slice(start, start + pageSize)) drawRow(row, tbody);
    bar.textContent = '';
    bar.appendChild(document.createTextNode(rows.length
      ? '第 ' + (page + 1) + ' / ' + pageCount + ' 页（' + (start + 1) + '–' + Math.min(start + pageSize, rows.length)
        + '，共 ' + rows.length + ' 行；完整数据在报告中，翻页只改变可见行）'
      : '共 0 行。'));
    if (pageCount > 1) {
      bar.appendChild(document.createTextNode(' '));
      const prev = el('button', null, '上一页');
      prev.type = 'button';
      prev.disabled = page === 0;
      prev.addEventListener('click', () => { page -= 1; draw(); });
      bar.appendChild(prev);
      bar.appendChild(document.createTextNode(' '));
      const next = el('button', null, '下一页');
      next.type = 'button';
      next.disabled = page >= pageCount - 1;
      next.addEventListener('click', () => { page += 1; draw(); });
      bar.appendChild(next);
    }
    if (opts && opts.note) bar.appendChild(document.createTextNode(' ' + opts.note));
  };
  frag.appendChild(tableScroll(table));
  frag.appendChild(bar);
  draw();
  return frag;
}
function metricCell(tableCell, value, state) {
  const info = cellInt(value, state);
  tableCell.textContent = info.text;
  if (info.unknown) tableCell.classList.add('unknown');
  if (info.partial) { tableCell.classList.add('partial'); tableCell.appendChild(el('span', 'mark', '')); }
  return tableCell;
}
function addRow(tbody, name, aggregate, emphasize) {
  const tr = document.createElement('tr');
  if (emphasize) tr.classList.add('emphasize');
  tr.appendChild(el('td', null, name));
  for (const key of ['input', 'output', 'cache_read']) {
    metricCell(tr.appendChild(document.createElement('td')), aggregate.metrics[key].value, aggregate.metrics[key].state);
  }
  const rateCell = tr.appendChild(document.createElement('td'));
  const rate = percent(aggregate.cache_hit_rate);
  rateCell.textContent = rate.text;
  if (rate.unknown) rateCell.classList.add('unknown');
  if (rate.partial) rateCell.classList.add('partial');
  metricCell(tr.appendChild(document.createElement('td')), aggregate.metrics.total.value, aggregate.metrics.total.state);
  tbody.appendChild(tr);
}

function turnIdentityOf(record, sessionId) {
  const members = record.interval_turns;
  if (Array.isArray(members) && new Set(members).size > 1) return '__multi_turn_interval__';
  if (Array.isArray(members) && members.length) return members[0];
  const owner = record.session === sessionId ? record.turn : record.owner_turn;
  return owner ? owner : '__unknown__';
}
function checkViewRows(view, dimension, recordsByKey, sessionId) {
  const flags = view.rows.map(row => row && 'record_keys' in row);
  if (flags.some(Boolean) && !flags.every(Boolean)) throw new Error('视图行记录引用不完整：' + dimension);
  view.rows.forEach((row, i) => {
    if (!row || typeof row.id !== 'string' || typeof row.label !== 'string') throw new Error('无效的视图行身份：' + dimension + ' ' + i);
    checkAggregateRow(row, '视图行 ' + dimension + ' ' + i);
    const keys = row.record_keys;
    if (keys === undefined || keys === null) return;
    if (!Array.isArray(keys) || keys.some(k => typeof k !== 'string')) throw new Error('视图行记录引用无效：' + dimension);
    if (!recordsByKey) return;
    for (const key of keys) {
      const record = recordsByKey.get(key);
      if (!record) throw new Error('视图行引用悬空记录：' + dimension);
      if (dimension === 'model' && (typeof record.model === 'string' ? record.model : '模型未知') !== row.id) {
        throw new Error('视图行记录引用与维度不一致：' + dimension);
      }
      if (dimension === 'agent' && (typeof record.agent === 'string' ? record.agent : '未知') !== row.id) {
        throw new Error('视图行记录引用与维度不一致：' + dimension);
      }
      if (dimension === 'turn' && turnIdentityOf(record, sessionId) !== row.id) {
        throw new Error('视图行记录引用与维度不一致：' + dimension);
      }
      if (dimension === 'session' && record.session !== row.id) {
        throw new Error('视图行记录引用与维度不一致：' + dimension);
      }
    }
  });
}

function buildInternalRelationsCard(obj, locate) {
  const frag = document.createDocumentFragment();
  const exp = obj.explanation;
  if (exp.internal && exp.internal.length) {
    frag.appendChild(el('h3', null, '内部辅助细分（互斥计量组内分类，同一记录只计一次）'));
    const table = document.createElement('table');
    table.className = 'internal-table';
    const headRow = document.createElement('tr');
    ['类别', '依据', '记录数', '输入', '总量', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    for (const row of exp.internal) {
      const tr = document.createElement('tr');
      tr.appendChild(el('td', null, row.label));
      tr.appendChild(el('td', null, row.basis));
      tr.appendChild(el('td', null, String(row.record_keys.length)));
      metricCell(tr.appendChild(document.createElement('td')), row.metrics.input.value, row.metrics.input.state);
      metricCell(tr.appendChild(document.createElement('td')), row.metrics.total.value, row.metrics.total.state);
      const op = tr.appendChild(document.createElement('td'));
      if (row.record_keys.length && locate) {
        const btn = el('button', null, '定位');
        btn.type = 'button';
        btn.addEventListener('click', () => locate(row.record_keys));
        op.appendChild(btn);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    frag.appendChild(tableScroll(table));
  }
  if (exp.relations && exp.relations.length) {
    frag.appendChild(el('h3', null, '会话关系（既有明确关系，不推断新关系）'));
    const ul = document.createElement('ul');
    ul.className = 'notes';
    for (const row of exp.relations) {
      const kind = row.kind === 'parent_child' ? '父子/后代' : row.kind === 'fork' ? '分叉' : '继承副本';
      ul.appendChild(el('li', null, kind + '：会话 ' + row.session
        + (row.parent ? '，父会话 ' + row.parent : '')
        + (row.forked_from ? '，分叉自 ' + row.forked_from : '')
        + (row.origin_turn ? '，发起轮次 ' + row.origin_turn : '')
        + (row.call_id ? '，调用 ' + row.call_id : '')
        + '。依据：' + row.rule
        + '；来源：' + row.sources.map(loc => String(loc.path)).join('；')));
    }
    frag.appendChild(ul);
  }
  if (exp.excluded && exp.excluded.length) {
    frag.appendChild(el('h3', null, '未计量证据（不并入任何合计，无 token 小计）'));
    const ul = document.createElement('ul');
    ul.className = 'notes';
    for (const row of exp.excluded) {
      ul.appendChild(el('li', null, row.reason
        + (row.session ? '；会话 ' + short(row.session, 16) : '')
        + (row.turn ? '；轮次 ' + short(row.turn, 12) : '')
        + (row.source && row.source.path ? '；来源：' + String(row.source.path)
           + (row.source.line ? '：第 ' + row.source.line + ' 行' : '') : '')));
    }
    frag.appendChild(ul);
  }
  frag.appendChild(el('p', 'hint-line', '内部五类支持状态仍是覆盖事实说明（见“内部来源支持”），不堆叠成 token 分组；后台工作流按后代属性归位，不再另计一份内部用量。'));
  return frag;
}

function buildRecordsDetail(obj) {
  if (!(Array.isArray(obj.records) && obj.records.length)) return null;
  let locateRecordsByKeys = null;
  let nodes = null;
  {
    const hasExplanation = !!obj.records[0].explanation;
    const toggle = el('button', null, '展开调用明细（' + obj.records.length + ' 条，白名单元数据）');
    toggle.type = 'button';
    const host = el('div');
    host.hidden = true;
    let locatedKeys = null;
    toggle.addEventListener('click', () => {
      host.hidden = !host.hidden;
      toggle.textContent = host.hidden
        ? '展开调用明细（' + obj.records.length + ' 条，白名单元数据）'
        : '收起调用明细';
      if (!host.firstChild) renderRecordsTable();
    });
    nodes = [toggle, host];

    locateRecordsByKeys = keys => {
      if (!keys.length) return;
      locatedKeys = keys.slice();
      if (host.hidden) { host.hidden = false; toggle.textContent = '收起调用明细'; }
      drawRecordsTable();
      let ancestor = host.parentElement;
      while (ancestor) {
        if (ancestor.tagName === 'DETAILS') ancestor.open = true;
        ancestor = ancestor.parentElement;
      }
      host.scrollIntoView({ block: 'nearest' });
    };

    function sourceLocText(loc) {
      if (!loc || typeof loc !== 'object') return '未知';
      let text = String(loc.path || '未知');
      if (loc.table !== undefined && loc.table !== null) text += '（表 ' + loc.table + (loc.id !== undefined && loc.id !== null ? '，行 ' + String(loc.id) : '') + '）';
      else if (loc.line !== undefined && loc.line !== null) text += '：第 ' + String(loc.line) + ' 行';
      return text;
    }

    function renderRecordsTable() {
      host.textContent = '';
      drawRecordsTable();
    }

    let escapeHandler = null;
    function drawRecordsTable() {
      host.textContent = '';
      if (escapeHandler) { document.removeEventListener('keydown', escapeHandler); escapeHandler = null; }
      const located = locatedKeys !== null;
      const locatedSet = located ? new Set(locatedKeys) : null;
      const records = located ? obj.records.filter(r => locatedSet.has(r.key)) : obj.records;
      const bar = el('p', 'hint-line', '');
      if (located) {
        escapeHandler = event => {
          if (event.key === 'Escape') { locatedKeys = null; drawRecordsTable(); }
        };
        document.addEventListener('keydown', escapeHandler);
        bar.textContent = '';
        const back = el('button', null, '返回全部明细');
        back.type = 'button';
        back.addEventListener('click', () => { locatedKeys = null; drawRecordsTable(); });
        bar.appendChild(back);
        bar.appendChild(document.createTextNode(' 已定位 ' + records.length + ' 条记录' + (records.length === 1 ? '：' + String(records[0].key) : '')
          + '。定位只改变可见明细，合计、分母、范围与截止点不变；按 Esc 也可返回。'));
      } else {
        bar.textContent = '共 ' + obj.records.length + ' 条。点击“定位”只看选中记录（Esc 或“返回全部明细”恢复）；点击“详情”或聚焦行后回车展开完整解释。'
          + (hasExplanation ? '' : '旧报告未保存记录级解释，仅展示已保存字段。');
      }
      host.appendChild(bar);
      const headRow = document.createElement('tr');
      ['操作', '分组', '模型', '代理/会话', '轮次', '时间', '输入', '输出', '缓存读取', '调用数', '性质'].forEach(h => headRow.appendChild(el('th', null, h)));
      host.appendChild(pagedBody(headRow, records, (record, tbody) => {
        const tr = document.createElement('tr');
        tr.tabIndex = 0;
        const opCell = tr.appendChild(document.createElement('td'));
        const locateBtn = el('button', null, '定位');
        locateBtn.type = 'button';
        locateBtn.title = '只显示这一条记录（键盘：Tab 到该按钮后回车）';
        locateBtn.addEventListener('click', () => { locatedKeys = [record.key]; drawRecordsTable(); });
        const detailBtn = el('button', null, '详情');
        detailBtn.type = 'button';
        detailBtn.addEventListener('click', () => { toggleDetail(record, tr, tbody); });
        opCell.appendChild(locateBtn);
        opCell.appendChild(document.createTextNode(' '));
        opCell.appendChild(detailBtn);
        tr.appendChild(el('td', null, GROUP_LABELS[record.group] || record.group || '未知'));
        tr.appendChild(el('td', null, typeof record.model === 'string' ? record.model : '未知'));
        tr.appendChild(el('td', 'path', short(record.agent || record.session, 20)));
        const turnCell = tr.appendChild(el('td', 'path', short(record.turn, 18)));
        if (Array.isArray(record.interval_turns) && record.interval_turns.length > 1) {
          turnCell.textContent = '多轮区间';
          turnCell.title = record.interval_turns.join('、');
        }
        tr.appendChild(el('td', null, short(record.time, 22)));
        for (const key of ['input', 'output', 'cache_read']) {
          const metric = (record.metrics || {})[key] || { value: null, state: 'unknown' };
          metricCell(tr.appendChild(document.createElement('td')), metric.value, metric.state);
        }
        const count = record.call_count;
        tr.appendChild(el('td', null, count === null || count === undefined ? '未知' : count.toString()));
        tr.appendChild(el('td', null, record.internal_kind === 'compaction' ? '压缩/摘要'
          : record.internal_kind === 'session_aux' ? '会话辅助'
          : record.origin_kind === 'workflow_child' ? '后台工作流'
          : record.group === 'child' ? '后代常规' : ''));
        tr.addEventListener('keydown', event => {
          if (event.key === 'Enter' && event.target === tr) { event.preventDefault(); toggleDetail(record, tr, tbody); }
          if (event.key === 'Escape' && locatedKeys !== null) { locatedKeys = null; drawRecordsTable(); }
        });
        tbody.appendChild(tr);
      }, { className: 'records-table' }));
      host.appendChild(el('p', 'hint-line', '明细只展示报告已保存的白名单元数据（身份、时间、指标状态与来源定位）；不在浏览器重新归属或计量，不读取来源文件。'));
    }

    function toggleDetail(record, tr, tbody) {
      const next = tr.nextSibling;
      if (next && next.className === 'record-detail') { next.remove(); return; }
      const detailRow = document.createElement('tr');
      detailRow.className = 'record-detail';
      const cell = detailRow.appendChild(document.createElement('td'));
      cell.colSpan = 11;
      const dl = document.createElement('dl');
      dl.className = 'meta-grid';
      const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
      add('完整键', String(record.key));
      add('会话 / 代理', String(record.session) + ' / ' + String(record.agent || record.session));
      add('原始轮次', record.turn === null || record.turn === undefined ? '未知' : String(record.turn));
      add('归属', (record.owner_session || record.session) + (record.owner_turn ? '，轮次 ' + record.owner_turn : ''));
      add('记录时间', record.time === null || record.time === undefined ? '未知' : String(record.time));
      add('调用起止', record.interval_start ? '累计区间边界见下'
        : (record.start ? String(record.start) + ' → ' + String(record.time || '未知') : '未知（来源未报告该次调用起点）'));
      if (record.interval_start) add('累计区间', String(record.interval_start) + ' ~ ' + String(record.time)
        + (Array.isArray(record.interval_turns) && record.interval_turns.length ? '；涵盖轮次：' + record.interval_turns.join('、') : ''));
      const exp = record.explanation;
      if (exp) {
        add('粒度', (GRANULARITY_LABELS[exp.granularity] || exp.granularity));
        add('时间语义', (TIME_KIND_LABELS[exp.time_kind] || exp.time_kind));
        add('状态', '来源所读：' + exp.status.read + '；截止点前：' + exp.status.at_cutoff + '（' + exp.status.reason + '）');
        add('直接耗时', exp.duration.value === null ? (exp.duration.state === 'conflict' ? '冲突：' : '未知：') + exp.duration.reason
          : exp.duration.value.toLocaleString('en-US') + ' ms（' + exp.duration.state + '：' + exp.duration.reason + '）');
        add('分类依据', exp.classification_evidence.rule + '；分组：' + exp.classification_evidence.group
          + '；来源：' + sourceLocText(exp.classification_evidence.source));
        add('归属依据', exp.ownership_evidence.rule + '；归属会话 ' + exp.ownership_evidence.owner_session
          + (exp.ownership_evidence.owner_turn ? '，归属轮次 ' + exp.ownership_evidence.owner_turn : ''));
        add('来源定位', exp.ownership_evidence.sources.map(sourceLocText).join('；'));
      } else {
        const source = (record.sources || [])[0] || {};
        add('来源定位', sourceLocText(source));
      }
      cell.appendChild(dl);
      tbody.insertBefore(detailRow, tr.nextSibling);
    }
    return { nodes: nodes, locate: locateRecordsByKeys, clear: () => { locatedKeys = null; drawRecordsTable(); } };
  }
}

function buildTimelineCard(obj, locate) {
  if (!(obj.explanation && Array.isArray(obj.explanation.turns))) return null;
  const frag = document.createDocumentFragment();
  {
      const activity = obj.explanation.activity || {};
      const wall = activity.wall;
      const dl = document.createElement('dl');
      dl.className = 'meta-grid';
      const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
      const wallText = w => (w.value === null || w.value === undefined)
        ? '未知（' + w.state + '：' + w.reason + '）'
        : (Number.isInteger(w.value) ? w.value.toLocaleString('en-US') : String(w.value)) + ' s（' + w.reason + '）';
      if (wall) {
        add('墙钟跨度', wallText(wall));
        add('墙钟口径', wall.basis);
      }
      if (activity.sessions) {
        for (const sid of Object.keys(activity.sessions)) {
          add('墙钟（会话 ' + short(sid, 18) + '）', wallText(activity.sessions[sid]));
        }
        if (activity.sessions && Object.keys(activity.sessions).length) {
          add('墙钟口径', activity.sessions[Object.keys(activity.sessions)[0]].basis || '');
        }
      }
      if (activity.durations && Object.keys(activity.durations).length) {
        for (const granularity of Object.keys(activity.durations)) {
          const bucket = activity.durations[granularity];
          add(bucket.label, (bucket.total_ms === null || bucket.total_ms === undefined)
            ? '未知（覆盖：有效 ' + bucket.valid + '、缺失 ' + bucket.missing + '、冲突 ' + bucket.conflict + '，共 ' + bucket.records + ' 条）'
            : bucket.total_ms.toLocaleString('en-US') + ' ms（' + bucket.state
              + '；覆盖：有效 ' + bucket.valid + '、缺失 ' + bucket.missing + '、冲突 ' + bucket.conflict + '，共 ' + bucket.records + ' 条）');
        }
      }
      frag.appendChild(dl);
      frag.appendChild(el('p', 'hint-line', (activity.note || '') + ' 时间线为实际执行轮次；归属贡献见分布视图，两者不相加。'));
      const headRow = document.createElement('tr');
      ['会话', '轮次/区间', '生命周期', '状态（来源所读/截止点）', '原生轮次耗时', '记录数', '输入', '总量', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
      const spanLabels = { in_range: '范围内', extends_before: '起点早于下界（范围外上下文）', extends_after: '终点晚于截止点（范围外上下文）',
                           extends_both: '跨出筛选范围（范围外上下文）', conflict: '起止冲突', unknown: '时间未知', interval: '累计区间' };
      const cutoffLabels = { ended_before_cutoff: '截止点前已结束', ended_after_cutoff: '截止点后才结束',
                             not_confirmed_ended_at_cutoff: '截至该边界未确认结束', unknown_at_cutoff: '截止点状态未知' };
      frag.appendChild(pagedBody(headRow, obj.explanation.turns, (row, tbody) => {
        const tr = document.createElement('tr');
        tr.appendChild(el('td', 'path', short(row.session, 18)));
        if (row.kind === 'turn') {
          tr.appendChild(el('td', null, short(row.turn, 18)));
          const lifeCell = el('td', null, (row.start ? short(row.start, 21) : '未知')
            + ' → ' + (row.end ? short(row.end, 21) : '未知')
            + (row.span_state && row.span_state !== 'in_range' ? '（' + (spanLabels[row.span_state] || row.span_state) + '）' : ''));
          lifeCell.title = '原始边界：' + (row.start || '未知') + ' → ' + (row.end || '未知');
          tr.appendChild(lifeCell);
        } else {
          tr.appendChild(el('td', null, '多轮累计区间'));
          tr.appendChild(el('td', null, short(row.interval_start, 21) + ' → ' + short(row.interval_end, 21)
            + (row.interval_turns && row.interval_turns.length ? '；涵盖：' + row.interval_turns.map(t => short(t, 10)).join('、') : '')));
        }
        const statusCell = tr.appendChild(el('td', null, (TURN_STATUS_LABELS[row.status] || row.status)
          + '；' + (cutoffLabels[row.cutoff_status] || row.cutoff_status)));
        statusCell.title = row.span_reason || '';
        const native = row.native_duration_ms;
        tr.appendChild(el('td', null, !native ? '未知/未报告'
          : native.value === null ? '冲突：' + native.reason
          : native.value.toLocaleString('en-US') + ' ms（' + (native.source ? short(native.source, 24) : '来源') + '）'));
        tr.appendChild(el('td', null, String(row.record_keys.length)));
        metricCell(tr.appendChild(document.createElement('td')), row.metrics.input.value, row.metrics.input.state);
        metricCell(tr.appendChild(document.createElement('td')), row.metrics.total.value, row.metrics.total.state);
        const opCell = tr.appendChild(document.createElement('td'));
        const locateBtn = el('button', null, '定位记录');
        locateBtn.type = 'button';
        if (row.record_keys.length && locate) {
          locateBtn.addEventListener('click', () => locate(row.record_keys));
        } else {
          locateBtn.disabled = true;
          locateBtn.title = '该轮次没有已计量记录引用；空引用不证明零调用';
        }
        opCell.appendChild(locateBtn);
        tbody.appendChild(tr);
      }, { className: 'timeline-table' }));
      if (!obj.explanation.turns.length) {
        frag.appendChild(el('p', 'unavailable', '本报告未保存轮次时间线行（旧报告或范围内无轮次证据）。'));
      }
      frag.appendChild(el('p', 'hint-line', '时间行“定位记录”只改变明细可见集合；范围、合计、分母与截止点不变，且不读取来源。'));
  }
  return frag;
}

function buildCostSection(obj) {
  // Cost display only consumes the saved analysis extension; the browser never matches
  // prices, recomputes amounts or re-aggregates beyond what the report saved.
  const nodes = [el('h2', null, '费用估算（按币种分别小计；不做汇率换算；已定价部分不是账单结论）')];
  const ext = obj.analysis;
  if (!ext || !ext.cost) {
    nodes.push(el('p', 'hint-line', ext
      ? '本次查询未配置价格，结果不含费用估算；token 与性能结果不受影响，明确带价格重算才生成费用。'
      : '本报告未保存费用分析（未配置价格的查询或旧报告）；token 结果不受影响，明确带价格重算才生成费用。'));
    return nodes;
  }
  const cost = ext.cost;
  const summary = cost.summary;
  const config = cost.config;
  if (config.schema_version === 2n) {
    nodes.push(el('p', 'hint-line', '价格快照：当前官网标准 API 价等价估算（schema v2，修订 ' + config.revision
      + '；规则 ' + config.rules.length + ' 条、映射 ' + config.mappings.length + ' 条、未覆盖 '
      + config.uncovered.length + ' 项）。不声称实际服务档、扣费或套餐额度已验证；各币种分别小计，不做汇率换算。'));
    for (const source of config.sources) {
      nodes.push(el('p', 'hint-line', '来源读取：' + source.url + '（' + source.fetched_at
        + (source.digest ? '；' + source.digest : '') + '）。' + source.summary));
    }
    for (const item of config.uncovered) {
      nodes.push(el('p', 'hint-line', '快照未覆盖：' + (item.provider ? item.provider + '/' : '') + item.model
        + ' — ' + item.reason));
    }
  } else {
    nodes.push(el('p', 'hint-line', '价格配置快照：schema v' + ext.schema_version.toString() + '，修订 ' + config.revision
      + '；规则 ' + config.rules.length + ' 条、别名 ' + config.aliases.length + ' 条（含未命中规则，依据见下方展开区）。'));
  }
  const currencies = Object.keys(summary.currencies).sort();
  if (currencies.length) {
    const table = document.createElement('table');
    const headRow = document.createElement('tr');
    ['币种', '已定价小计（两位小数四舍五入）', '精确未舍入值', '完整计价记录', '部分计价记录'].forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    for (const currency of currencies) {
      const bucket = summary.currencies[currency];
      const tr = document.createElement('tr');
      tr.appendChild(el('td', null, currency));
      tr.appendChild(el('td', null, displayAmount(bucket.amount)));
      tr.appendChild(el('td', null, bucket.amount));
      tr.appendChild(el('td', null, bucket.priced_records.toString()));
      tr.appendChild(el('td', null, bucket.partially_priced_records.toString()));
      tbody.appendChild(tr);
    }
    nodes.push(tableScroll(table));
    for (const currency of currencies) {
      const bucket = summary.currencies[currency];
      const parts = Object.keys(bucket.components).sort().map(name => {
        const cell = bucket.components[name];
        return (COST_COMPONENT_LABELS[name] || name) + ' ' + cell.tokens.toLocaleString('en-US') + '（金额 ' + cell.amount + '）';
      });
      nodes.push(el('p', 'hint-line', currency + ' 精确分项：' + parts.join('；') + '；各记录实际单价与命中规则见“逐记录计价”。'));
    }
  } else {
    nodes.push(el('p', 'unavailable', '无任何已定价金额（范围内无记录或未命中规则；未知不画零，这不等于费用为零）。'));
  }
  const projections = cost.projections;
  if (projections) {
    // v3 only: model/session/day members and the unbucketed item, all saved views of the
    // same priced components; they never add back into any total and never convert currency.
    nodes.push(el('h3', null, '费用投影（同一计价结果按模型/会话/日期的独立视图，不再加入合计；各币种分别排行，不换汇）'));
    const rankTables = (title, labelOf, members) => {
      const frag = document.createDocumentFragment();
      const memberCurrencies = [...new Set(members.flatMap(m => Object.keys(m.currencies)))].sort();
      if (!memberCurrencies.length) {
        frag.appendChild(el('p', 'unavailable', title + '：无已定价成员（未定价原因见上方摘要；未知不画零）。'));
        return frag;
      }
      for (const currency of memberCurrencies) {
        frag.appendChild(el('h3', null, title + '（' + currency + '，按精确金额降序）'));
        const ranked = members.filter(m => m.currencies[currency])
          .sort((a, b) => compareAmountTexts(b.currencies[currency].amount, a.currencies[currency].amount));
        const table = document.createElement('table');
        const headRow = document.createElement('tr');
        ['行', '已定价金额（两位小数四舍五入）', '精确未舍入值', '计价记录'].forEach(h => headRow.appendChild(el('th', null, h)));
        const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
        const tbody = document.createElement('tbody'); table.appendChild(tbody);
        for (const member of ranked) {
          const tr = document.createElement('tr');
          const labelCell = el('td', 'path', short(labelOf(member), 40));
          labelCell.title = labelOf(member);
          tr.appendChild(labelCell);
          tr.appendChild(el('td', null, displayAmount(member.currencies[currency].amount)));
          tr.appendChild(el('td', null, member.currencies[currency].amount));
          tr.appendChild(el('td', null, String(member.record_keys.length)));
          tbody.appendChild(tr);
        }
        frag.appendChild(tableScroll(table));
      }
      return frag;
    };
    nodes.push(rankTables('模型费用排行', m => m.identity.provider + ' / ' + m.identity.model, projections.model));
    nodes.push(rankTables('会话费用排行', m => m.session, projections.session));
    const dayCurrencies = [...new Set(projections.day.flatMap(d => Object.keys(d.currencies)))].sort();
    if (dayCurrencies.length) {
      for (const currency of dayCurrencies) {
        nodes.push(el('h3', null, '日期费用分布（' + currency + '；只含保存日桶，未知不画零桶）'));
        const table = document.createElement('table');
        const headRow = document.createElement('tr');
        ['日期', '已定价金额（两位小数四舍五入）', '精确未舍入值'].forEach(h => headRow.appendChild(el('th', null, h)));
        const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
        const tbody = document.createElement('tbody'); table.appendChild(tbody);
        for (const member of projections.day) {
          if (!member.currencies[currency]) continue;
          const tr = document.createElement('tr');
          tr.appendChild(el('td', null, member.date));
          tr.appendChild(el('td', null, displayAmount(member.currencies[currency].amount)));
          tr.appendChild(el('td', null, member.currencies[currency].amount));
          tbody.appendChild(tr);
        }
        nodes.push(tableScroll(table));
      }
    } else {
      nodes.push(el('p', 'unavailable', '日期费用分布：各保存日均无已定价金额（未知不画零桶）。'));
    }
    const unbucketedCurrencies = Object.keys(projections.unbucketed.currencies).sort();
    nodes.push(el('p', 'hint-line', '无法归日：' + String(projections.unbucketed.record_keys.length)
      + ' 条（累计区间跨日界等；已计入总览与对应币种小计，不分摊、不与日期视图再次相加）'
      + (unbucketedCurrencies.length
        ? '；已定价金额 ' + unbucketedCurrencies.map(c => c + ' ' + projections.unbucketed.currencies[c].amount).join('；')
        : '；无已定价金额') + '。'));
  }
  nodes.push(el('p', null, '计价覆盖：计量记录 ' + summary.records.toString() + ' 条，完整计价 ' + summary.priced.toString()
    + '、部分计价 ' + summary.partially_priced.toString() + '、未定价 ' + summary.unpriced.toString()
    + '、规则冲突 ' + summary.rule_conflicts.toString() + '；已定价小计只含已计价分项，未定价金额未知，不用占比表示缺口。'));
  const reasonKeys = Object.keys(summary.unpriced_reasons).sort();
  if (reasonKeys.length) {
    const ul = document.createElement('ul');
    ul.className = 'notes';
    for (const reason of reasonKeys) {
      ul.appendChild(el('li', null, '未定价：' + reason + '（' + summary.unpriced_reasons[reason].toString() + ' 条）'));
    }
    nodes.push(ul);
  }
  nodes.push(el('p', 'hint-line', '显示精度：' + summary.display.note + '。'));
  nodes.push(evidenceCard('价格配置与规则依据（本次完整快照）', [(() => {
    const frag = document.createDocumentFragment();
    const v2 = config.schema_version === 2n;
    const table = document.createElement('table');
    const headRow = document.createElement('tr');
    const columns = v2
      ? ['规则 ID', '供应商', '完整模型身份', '价格条件（标准档）', '币种', '输入分区', '输出分区', '来源']
      : ['规则 ID', '供应商', '完整模型身份', '生效区间（左闭右开）', '币种', '输入分区', '输出分区', '来源'];
    columns.forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    const partitionText = partition => {
      const pairs = RULE_COMPONENTS[partition.kind].map(([name, key]) => (COST_COMPONENT_LABELS[name] || name) + ' ' + partition[key] + '/百万');
      return pairs.join('；') + (partition.basis ? '（依据：' + partition.basis + '）' : '');
    };
    const conditionText = conditions => {
      const bounds = [];
      if ('input_min' in conditions) bounds.push((conditions.input_min_inclusive ? '≥ ' : '> ') + conditions.input_min.toString());
      if ('input_max' in conditions) bounds.push((conditions.input_max_inclusive ? '≤ ' : '< ') + conditions.input_max.toString());
      const span = bounds.length ? '单请求输入 ' + bounds.join(' 且 ') : '无输入档位条件';
      return span + '（依据：' + conditions.basis + '）';
    };
    for (const rule of config.rules) {
      const tr = document.createElement('tr');
      tr.appendChild(el('td', null, rule.id));
      tr.appendChild(el('td', null, rule.provider));
      tr.appendChild(el('td', null, rule.model));
      tr.appendChild(el('td', null, v2 ? conditionText(rule.conditions)
        : rule.effective_from + ' ~ ' + (rule.effective_to || '无上限')));
      tr.appendChild(el('td', null, rule.currency));
      tr.appendChild(el('td', null, partitionText(rule.input)));
      tr.appendChild(el('td', null, partitionText(rule.output)));
      tr.appendChild(el('td', null, rule.source.reference + '（' + rule.source.version + '）'));
      tbody.appendChild(tr);
    }
    if (!config.rules.length) frag.appendChild(el('p', 'unavailable', '配置不含任何规则；全部记录保持未定价。'));
    else frag.appendChild(tableScroll(table));
    const links = v2 ? config.mappings : (config.aliases || []);
    if (links.length) {
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const link of links) {
        ul.appendChild(el('li', null, (v2 ? '映射 ' : '别名 ') + link.id + '：' + link.from.provider + '/' + link.from.model
          + ' → ' + link.to.provider + '/' + link.to.model + '（一次精确映射；依据：' + link.basis
          + '；来源：' + link.source.reference + ' ' + link.source.version + '）'));
      }
      frag.appendChild(ul);
    }
    if (v2) {
      for (const item of config.uncovered) {
        frag.appendChild(el('p', 'hint-line', '快照未覆盖：' + (item.provider ? item.provider + '/' : '') + item.model
          + ' — ' + item.reason));
      }
    }
    return frag;
  })()]));
  nodes.push(lazyEvidenceCard('逐记录计价（引用本报告计量记录稳定键；' + cost.records.length + ' 条，按需生成并分页）', body => {
    if (!cost.records.length) { body.appendChild(el('p', 'unavailable', '范围内无计量记录；无记录不自动视为费用零。')); return; }
    const headRow = document.createElement('tr');
    ['记录', '价格身份（供应商/模型）', '状态', '命中规则', '计价分项（token × 单价/百万 = 金额）', '未定价原因'].forEach(h => headRow.appendChild(el('th', null, h)));
    body.appendChild(pagedBody(headRow, cost.records, (entry, tbody) => {
      const tr = document.createElement('tr');
      const keyCell = tr.appendChild(el('td', 'path', short(entry.record_key, 28)));
      keyCell.title = entry.record_key;
      tr.appendChild(el('td', null, entry.identity ? entry.identity.provider + ' / ' + entry.identity.model : '未知'));
      tr.appendChild(el('td', null, COST_STATUS_LABELS[entry.status] || entry.status));
      tr.appendChild(el('td', null, entry.matched
        ? entry.matched.rule_id
          + (entry.matched.mapping_id ? '（经映射 ' + entry.matched.mapping_id + '）' : '')
          + (entry.matched.alias_id ? '（经别名 ' + entry.matched.alias_id + '）' : '')
          + (entry.matched.input_tokens !== null && entry.matched.input_tokens !== undefined
            ? '（判定输入 ' + entry.matched.input_tokens.toLocaleString('en-US') + '）' : '')
        : entry.status === 'rule_conflict' ? '冲突：' + entry.conflicts.join('、') : '—'));
      tr.appendChild(el('td', null, entry.components.map(c => (COST_COMPONENT_LABELS[c.name] || c.name)
        + ' ' + c.tokens.toLocaleString('en-US') + ' × ' + c.price_per_million + ' = ' + c.amount).join('；') || '—'));
      tr.appendChild(el('td', null, entry.unpriced.map(item => (item.component ? (COST_COMPONENT_LABELS[item.component] || item.component) + '：' : '') + item.reason).join('；') || '—'));
      tbody.appendChild(tr);
    }));
  }));
  return nodes;
}

function perfRatioText(numerator, denominator, perSecond) {
  // Exact two-decimal half-up of an integer ratio saved as numerator/denominator;
  // perSecond rescales ms intervals to seconds. Never floats, never a fake zero.
  const scaled = perSecond ? numerator * 100000n : numerator * 100n;
  const rounded = (2n * scaled + denominator) / (2n * denominator);
  return (rounded / 100n).toString() + '.' + (rounded % 100n).toString().padStart(2, '0');
}

const PERF_KIND_LABELS = { missing: '缺失', conflict: '冲突', unsupported: '无法证明', range: '范围外' };
const PERF_COMPLETION_LABELS = { ended_before_cutoff: '截止前已完成', ended_after_cutoff: '截止点后结束', no_end_evidence: '无结束证据（未完成）' };
const PERF_SUPPORT_LABELS = { supported: '支持', source_not_provided: '来源未提供', not_checked: '尚未核查' };

function buildPerfMetricBlock(perf, name) {
  const metric = perf.metrics[name];
  // Display unit matches the CLI/Markdown wording; the saved contract unit stays 'token/s'.
  const displayUnit = name === 'throughput' ? 'token/秒' : metric.unit;
  const block = el('div', 'perf-metric');
  block.appendChild(el('h3', null, metric.label + '（' + metric.definition + '）'));
  block.appendChild(el('p', 'hint-line', '入样：' + metric.admission + '；单位：' + metric.unit
    + (metric.overhead ? '；' + metric.overhead : '') + '。'));
  const support = metric.support;
  if (support.status !== 'supported') {
    // A checked limitation replaces any chart: no all-unknown graph masquerading as support.
    block.appendChild(el('p', 'unavailable', '不可用（' + (PERF_SUPPORT_LABELS[support.status] || support.status)
      + '）：' + support.reason));
    return block;
  }
  const aggregate = metric.aggregate;
  const kindText = PERF_EXCLUSION_KINDS.map(k => PERF_KIND_LABELS[k] + ' ' + aggregate.excluded_by_kind[k].toString()).join('、');
  block.appendChild(el('p', null, '候选 ' + aggregate.candidates.toString() + '；有效 ' + aggregate.valid.toString()
    + '、排除 ' + aggregate.excluded.toString() + '（' + kindText + '）；无可靠候选分母时不给比例。'));
  if (aggregate.denominator > 0n) {
    const perSecond = name === 'throughput';
    const valueText = perfRatioText(aggregate.numerator, aggregate.denominator, perSecond) + ' ' + displayUnit;
    const detail = name === 'ttft'
      ? '精确分子 ' + aggregate.numerator.toString() + ' ms ÷ 分母 ' + aggregate.denominator.toString() + ' 个有效样本'
      : '同一有效集合输出 ' + aggregate.numerator.toString() + ' token ÷ 区间时长 ' + aggregate.denominator.toString() + ' ms 之和（不平均逐行速率）';
    block.appendChild(el('p', null, (name === 'ttft' ? '有效样本均值 ' : '聚合吞吐 ') + valueText
      + '（' + detail + '；显示两位小数四舍五入）；其中 ' + aggregate.no_token_record.toString()
      + ' 条有效样本无对应 token 记录引用（性能独立入样）。'));
  } else {
    block.appendChild(el('p', 'unavailable', '无有效样本；不给均值/聚合值（未知不画零，不产生伪零或无穷值）。'));
  }
  const reasonKeys = Object.keys(aggregate.exclusion_reasons).sort();
  if (reasonKeys.length) {
    const ul = el('ul', 'notes');
    for (const reason of reasonKeys) {
      ul.appendChild(el('li', null, '排除原因：' + reason + '（' + aggregate.exclusion_reasons[reason].toString() + ' 条）'));
    }
    block.appendChild(ul);
  }
  if (!metric.samples.length) return block;

  const perSecond = name === 'throughput';
  const memberValue = member => perfRatioText(member.numerator, member.denominator, perSecond);
  const memberGt = (a, b) => a.numerator * b.denominator > b.numerator * a.denominator;  // exact ratio compare

  // Samples host with locate-by-saved-key; locating only changes the visible sample set.
  const samplesHost = el('div');
  let locatedKeys = null;
  const drawSamples = () => {
    samplesHost.textContent = '';
    const located = locatedKeys !== null;
    const locatedSet = located ? new Set(locatedKeys) : null;
    const bar = el('p', 'hint-line', '');
    const headRow = document.createElement('tr');
    const valueHead = name === 'ttft' ? 'TTFT（ms）' : '输出 ÷ 区间（ms）';
    ['操作', '样本键', '会话', '轮次', '模型', '粒度', name === 'ttft' ? '完成状态' : '输出', valueHead, '依据', 'token 记录'].forEach(h => headRow.appendChild(el('th', null, h)));
    const shown = located ? metric.samples.filter(s => locatedSet.has(s.key)) : metric.samples;
    samplesHost.appendChild(pagedBody(headRow, shown, (sample, tbody) => {
      const tr = document.createElement('tr');
      tr.tabIndex = 0;
      const opCell = tr.appendChild(document.createElement('td'));
      const locateBtn = el('button', null, '定位');
      locateBtn.type = 'button';
      locateBtn.addEventListener('click', () => { locatedKeys = [sample.key]; drawSamples(); });
      const detailBtn = el('button', null, '详情');
      detailBtn.type = 'button';
      detailBtn.addEventListener('click', () => toggleSampleDetail(sample, tr, tbody));
      opCell.appendChild(locateBtn);
      opCell.appendChild(document.createTextNode(' '));
      opCell.appendChild(detailBtn);
      const keyCell = tr.appendChild(el('td', 'path', short(sample.key, 26)));
      keyCell.title = sample.key;
      tr.appendChild(el('td', 'path', short(sample.session, 14)));
      tr.appendChild(el('td', 'path', short(sample.turn, 12)));
      tr.appendChild(el('td', null, sample.model));
      tr.appendChild(el('td', null, GRANULARITY_LABELS[sample.granularity] || sample.granularity));
      if (name === 'ttft') {
        tr.appendChild(el('td', null, PERF_COMPLETION_LABELS[sample.completion] || sample.completion));
        tr.appendChild(el('td', null, sample.value.toLocaleString('en-US')));
      } else {
        tr.appendChild(el('td', null, sample.output.toLocaleString('en-US')));
        tr.appendChild(el('td', null, sample.interval_ms.toLocaleString('en-US')));
      }
      tr.appendChild(el('td', null, sample.basis === 'native' ? '原生' : '推导'));
      tr.appendChild(el('td', null, sample.record_key === null ? '无（不伪造引用）' : '有'));
      tr.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target === tr) { event.preventDefault(); toggleSampleDetail(sample, tr, tbody); }
        if (event.key === 'Escape' && locatedKeys !== null) { locatedKeys = null; drawSamples(); }
      });
      tbody.appendChild(tr);
    }));
    samplesHost.appendChild(bar);
    if (located) {
      const back = el('button', null, '返回全部样本');
      back.type = 'button';
      back.addEventListener('click', () => { locatedKeys = null; drawSamples(); });
      bar.appendChild(back);
      bar.appendChild(document.createTextNode(' 已定位 ' + shown.length + ' 条样本。定位只改变可见样本，候选/有效/排除计数、聚合分子/分母与范围不变；按 Esc 也可返回。'));
    } else {
      bar.textContent = '共 ' + metric.samples.length + ' 条有效样本。点击“定位”只看选中样本（Esc 或“返回全部样本”恢复）；点击“详情”或聚焦行后回车展开事件时间与来源定位。';
    }
  };
  const toggleSampleDetail = (sample, tr, tbody) => {
    const next = tr.nextSibling;
    if (next && next.className === 'record-detail') { next.remove(); return; }
    const detailRow = document.createElement('tr');
    detailRow.className = 'record-detail';
    const cell = detailRow.appendChild(document.createElement('td'));
    cell.colSpan = 10;
    const dl = document.createElement('dl');
    dl.className = 'meta-grid';
    const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
    add('完整样本键', sample.key);
    add('对应 token 记录', sample.record_key === null ? '无（候选无对应 token 计量记录；不伪造引用）' : sample.record_key);
    add('会话 / 轮次', sample.session + ' / ' + (sample.turn === null ? '未知' : sample.turn));
    add('归属', sample.owner_session + (sample.owner_turn ? '，轮次 ' + sample.owner_turn : ''));
    add('首 token 事件', sample.first_token_at);
    if (name === 'ttft') {
      add('请求起点', sample.started_at);
      add('原生 TTFT', sample.native_ttft_ms === null ? '未报告（推导值）' : sample.native_ttft_ms.toLocaleString('en-US') + ' ms（与时间差核对一致）');
      add('完成事件', sample.completed_at === null ? '无结束证据' : sample.completed_at);
      add('TTFT', sample.value.toLocaleString('en-US') + ' ms（' + (sample.basis === 'native' ? '原生' : '推导') + '；' + (PERF_COMPLETION_LABELS[sample.completion] || sample.completion) + '）');
    } else {
      add('区间终点', sample.completed_at);
      add('观测区间', sample.interval_ms.toLocaleString('en-US') + ' ms（首 token → completed_at；终点含完成事件处理开销，非服务端纯生成速率）');
      add('已知输出', sample.output.toLocaleString('en-US') + ' token');
    }
    add('精度', sample.precision + '（来源毫秒时间，保留原精度）');
    const loc = sample.source || {};
    add('来源定位', String(loc.path || '未知') + (loc.table ? '（表 ' + loc.table + (loc.id !== undefined && loc.id !== null ? '，行 ' + String(loc.id) : '') + ')' : loc.line ? '：第 ' + String(loc.line) + ' 行' : ''));
    cell.appendChild(dl);
    tbody.insertBefore(detailRow, tr.nextSibling);
  };
  const revealSamples = () => {
    let ancestor = samplesHost.parentElement;
    while (ancestor) {
      if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    samplesHost.scrollIntoView({ block: 'nearest' });
  };
  const locateSamples = keys => {
    locatedKeys = keys.slice();
    if (samplesHost.parentElement !== null) {
      drawSamples();
      revealSamples();
      return;
    }
    // First locate before the lazy sample card ever opened: opening it queues the
    // mount build (which draws the located subset); the reveal runs after that lands.
    samplesCard.open = true;
    setTimeout(revealSamples, 0);
  };

  const groupTable = (title, labelOf, members) => {
    const frag = document.createDocumentFragment();
    frag.appendChild(el('h3', null, title + '（成员值由该组精确分子/分母重新生成）'));
    const table = document.createElement('table');
    const headRow = document.createElement('tr');
    ['行', '值（' + displayUnit + '，两位小数）', '精确分子 ÷ 分母', '样本数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    for (const member of members) {
      const tr = document.createElement('tr');
      const labelCell = tr.appendChild(el('td', 'path', short(labelOf(member), 40)));
      labelCell.title = labelOf(member);
      tr.appendChild(el('td', null, memberValue(member)));
      tr.appendChild(el('td', null, member.numerator.toString() + ' ÷ ' + member.denominator.toString()));
      tr.appendChild(el('td', null, String(member.sample_keys.length)));
      const op = tr.appendChild(document.createElement('td'));
      const btn = el('button', null, '定位');
      btn.type = 'button';
      btn.title = '沿保存样本键定位该组成员样本（不改变范围与合计）';
      btn.addEventListener('click', () => locateSamples(member.sample_keys));
      op.appendChild(btn);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    frag.appendChild(tableScroll(table));
    return frag;
  };
  block.appendChild(groupTable('按模型分组（完整供应商＋模型身份）',
    m => (m.identity.provider === null ? '供应商未知' : m.identity.provider) + ' / ' + m.identity.model,
    metric.projections.model));
  // Session content renders on demand only: a count summary stays visible and the
  // member table is built (paged) when the entry is opened. Model groups stay eager.
  const sessionMembers = metric.projections.session;
  block.appendChild(el('p', 'hint-line', '按会话分组：共 ' + sessionMembers.length
    + ' 个会话；默认收起，展开后按 20 行分页（成员值由该组精确分子/分母重新生成，定位直达样本）。'));
  block.appendChild(lazyEvidenceCard('展开按会话分组（' + sessionMembers.length + ' 个会话）', body => {
    const headRow = document.createElement('tr');
    ['行', '值（' + displayUnit + '，两位小数）', '精确分子 ÷ 分母', '样本数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    body.appendChild(pagedBody(headRow, sessionMembers, (member, tbody) => {
      const tr = document.createElement('tr');
      const labelCell = tr.appendChild(el('td', 'path', short(member.session, 40)));
      labelCell.title = member.session;
      tr.appendChild(el('td', null, memberValue(member)));
      tr.appendChild(el('td', null, member.numerator.toString() + ' ÷ ' + member.denominator.toString()));
      tr.appendChild(el('td', null, String(member.sample_keys.length)));
      const op = tr.appendChild(document.createElement('td'));
      const btn = el('button', null, '定位');
      btn.type = 'button';
      btn.title = '沿保存样本键定位该组成员样本（不改变范围与合计）';
      btn.addEventListener('click', () => locateSamples(member.sample_keys));
      op.appendChild(btn);
      tbody.appendChild(tr);
    }));
  }));

  // Day chart: one bar per saved day member, scaled by exact ratio comparison.
  const days = metric.projections.day;
  block.appendChild(el('h3', null, '日分布（按各自入样事件与保存时区分日；未知不画零）'));
  if (days.length) {
    const maxMember = days.reduce((best, m) => memberGt(m, best) ? m : best, days[0]);
    const barHeight = 22, labelWidth = 110, valueWidth = 220, gap = 6, trackWidth = 320;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', String(labelWidth + trackWidth + valueWidth));
    svg.setAttribute('height', String(days.length * (barHeight + gap) + 4));
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', metric.label + '日分布条形图');
    days.forEach((member, i) => {
      const y = i * (barHeight + gap) + 2;
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('tabindex', '0');
      group.setAttribute('role', 'button');
      group.setAttribute('aria-label', '定位 ' + member.date + ' 的 ' + member.sample_keys.length + ' 条样本');
      group.addEventListener('click', () => locateSamples(member.sample_keys));
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); locateSamples(member.sample_keys); }
      });
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = member.date + '：' + memberValue(member) + ' ' + displayUnit + '（' + member.sample_keys.length + ' 条样本）';
      group.appendChild(title);
      const labelNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      labelNode.setAttribute('x', String(labelWidth - 6)); labelNode.setAttribute('y', String(y + 15));
      labelNode.setAttribute('text-anchor', 'end'); labelNode.setAttribute('class', 'bar-label');
      labelNode.textContent = member.date;
      group.appendChild(labelNode);
      const track = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      track.setAttribute('x', String(labelWidth)); track.setAttribute('y', String(y));
      track.setAttribute('width', String(trackWidth)); track.setAttribute('height', String(barHeight));
      track.setAttribute('class', 'bar-track');
      group.appendChild(track);
      const scaled = maxMember.numerator === 0n ? 0 : Number(member.numerator * 10000n * maxMember.denominator / (member.denominator * maxMember.numerator)) / 10000;
      const barWidth = Math.max(2, Math.round(scaled * trackWidth));
      const fill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      fill.setAttribute('x', String(labelWidth)); fill.setAttribute('y', String(y));
      fill.setAttribute('width', String(barWidth)); fill.setAttribute('height', String(barHeight));
      fill.setAttribute('class', 'bar-fill');
      group.appendChild(fill);
      const valueNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      valueNode.setAttribute('x', String(labelWidth + trackWidth + 8)); valueNode.setAttribute('y', String(y + 15));
      valueNode.setAttribute('class', 'bar-value');
      valueNode.textContent = memberValue(member) + ' ' + displayUnit + ' · ' + member.sample_keys.length + ' 条';
      group.appendChild(valueNode);
      svg.appendChild(group);
    });
    const chartHost = el('div', 'chart-host');
    chartHost.appendChild(svg);
    block.appendChild(chartHost);
    block.appendChild(el('p', 'hint-line', '点选日期条定位当日样本（键盘：Tab 聚焦后 Enter/空格；只切换视图，不改变计数与合计）。'));
  }
  const samplesCard = lazyEvidenceCard('有效样本明细（' + metric.samples.length + ' 条；稳定样本键＝完整会话＋源调用/逻辑请求身份——按需生成并分页）',
    body => {
      body.appendChild(samplesHost);
      drawSamples();
    });
  block.appendChild(samplesCard);
  return block;
}

function nsToScaledText(ns, unitNs) {
  // Exact two-decimal half-up display of a nanosecond value in ms or s; never floats.
  const rounded = (2n * ns * 100n + unitNs) / (2n * unitNs);
  return (rounded / 100n).toString() + '.' + (rounded % 100n).toString().padStart(2, '0');
}
function nsToMsText(ns) { return nsToScaledText(ns, 1000000n); }
function nsToSecText(ns) { return nsToScaledText(ns, 1000000000n); }

function buildToolMetricBlock(perf) {
  // Tool execution duration: same card/chart/locate mechanisms as the model metrics.
  // The execution-duration sum and the scheduling/execution span envelope stay separate;
  // unknown never draws a zero bar.
  const metric = perf.metrics.tool_duration;
  const block = el('div', 'perf-metric');
  block.appendChild(el('h3', null, metric.label + '（' + metric.definition + '）'));
  block.appendChild(el('p', 'hint-line', '入样：' + metric.admission + '；单位：ms（样本保存精确 ns 值；'
    + '调度至完成的跨度独立展示，不加入执行耗时和）。'));
  const support = metric.support;
  if (support.status !== 'supported') {
    block.appendChild(el('p', 'unavailable', '不可用（' + (PERF_SUPPORT_LABELS[support.status] || support.status)
      + '）：' + support.reason));
    return block;
  }
  const aggregate = metric.aggregate;
  const kindText = PERF_EXCLUSION_KINDS.map(k => PERF_KIND_LABELS[k] + ' ' + aggregate.excluded_by_kind[k].toString()).join('、');
  block.appendChild(el('p', null, '候选 ' + aggregate.candidates.toString() + '；有效 ' + aggregate.valid.toString()
    + '、排除 ' + aggregate.excluded.toString() + '（' + kindText + '）；独立工具通道，不要求模型 usage，不改变 token 合计；无可靠候选分母时不给比例。'));
  if (aggregate.denominator > 0n) {
    block.appendChild(el('p', null, '执行耗时和 ' + nsToMsText(aggregate.numerator) + ' ms（'
      + aggregate.denominator.toString() + ' 个有效样本精确耗时之和，共 ' + aggregate.numerator.toString()
      + ' ns；显示两位小数四舍五入）；已完成失败执行保留真实耗时与失败状态；全部样本无对应 token 记录引用（独立通道）。'));
  } else {
    block.appendChild(el('p', 'unavailable', '无有效样本；不给耗时和（未知不画零）。'));
  }
  const wall = aggregate.wall;
  block.appendChild(el('p', wall.state === 'known' ? null : 'unavailable',
    '调度/执行跨度包络：' + (wall.state === 'known' ? nsToSecText(wall.value) + ' s' : wall.state === 'conflict' ? '冲突' : '未知')
    + '（' + wall.basis + '；' + wall.reason + '）。'));
  const reasonKeys = Object.keys(aggregate.exclusion_reasons).sort();
  if (reasonKeys.length) {
    const ul = el('ul', 'notes');
    for (const reason of reasonKeys) {
      ul.appendChild(el('li', null, '排除原因：' + reason + '（' + aggregate.exclusion_reasons[reason].toString() + ' 条）'));
    }
    block.appendChild(ul);
  }
  if (aggregate.supplements.length) {
    const ul = el('ul', 'notes');
    for (const item of aggregate.supplements) {
      ul.appendChild(el('li', null, '补充项（单列不计入）：' + item.key + '——' + item.reason));
    }
    block.appendChild(ul);
  }
  if (!metric.samples.length) return block;

  const samplesHost = el('div');
  let locatedKeys = null;
  const drawSamples = () => {
    samplesHost.textContent = '';
    const located = locatedKeys !== null;
    const locatedSet = located ? new Set(locatedKeys) : null;
    const bar = el('p', 'hint-line', '');
    const headRow = document.createElement('tr');
    ['操作', '样本键', '会话', '轮次', '类别', '状态', '耗时（ms）', '依据', '精度'].forEach(h => headRow.appendChild(el('th', null, h)));
    const shown = located ? metric.samples.filter(s => locatedSet.has(s.key)) : metric.samples;
    samplesHost.appendChild(pagedBody(headRow, shown, (sample, tbody) => {
      const tr = document.createElement('tr');
      tr.tabIndex = 0;
      const opCell = tr.appendChild(document.createElement('td'));
      const locateBtn = el('button', null, '定位');
      locateBtn.type = 'button';
      locateBtn.addEventListener('click', () => { locatedKeys = [sample.key]; drawSamples(); });
      const detailBtn = el('button', null, '详情');
      detailBtn.type = 'button';
      detailBtn.addEventListener('click', () => toggleSampleDetail(sample, tr, tbody));
      opCell.appendChild(locateBtn);
      opCell.appendChild(document.createTextNode(' '));
      opCell.appendChild(detailBtn);
      const keyCell = tr.appendChild(el('td', 'path', short(sample.key, 26)));
      keyCell.title = sample.key;
      tr.appendChild(el('td', 'path', short(sample.session, 14)));
      tr.appendChild(el('td', 'path', short(sample.turn, 12)));
      tr.appendChild(el('td', null, sample.category));
      tr.appendChild(el('td', null, sample.status === 'failed' ? '已失败' : '已完成'));
      tr.appendChild(el('td', null, nsToMsText(sample.value)));
      tr.appendChild(el('td', null, sample.basis === 'native' ? '原生' : '推导'));
      tr.appendChild(el('td', null, sample.precision));
      tr.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target === tr) { event.preventDefault(); toggleSampleDetail(sample, tr, tbody); }
        if (event.key === 'Escape' && locatedKeys !== null) { locatedKeys = null; drawSamples(); }
      });
      tbody.appendChild(tr);
    }));
    samplesHost.appendChild(bar);
    if (located) {
      const back = el('button', null, '返回全部样本');
      back.type = 'button';
      back.addEventListener('click', () => { locatedKeys = null; drawSamples(); });
      bar.appendChild(back);
      bar.appendChild(document.createTextNode(' 已定位 ' + shown.length + ' 条样本。定位只改变可见样本，候选/有效/排除计数、耗时和与跨度包络不变；按 Esc 也可返回。'));
    } else {
      bar.textContent = '共 ' + metric.samples.length + ' 条有效样本。点击“定位”只看选中样本（Esc 或“返回全部样本”恢复）；点击“详情”或聚焦行后回车展开事件时间与来源定位。';
    }
  };
  const toggleSampleDetail = (sample, tr, tbody) => {
    const next = tr.nextSibling;
    if (next && next.className === 'record-detail') { next.remove(); return; }
    const detailRow = document.createElement('tr');
    detailRow.className = 'record-detail';
    const cell = detailRow.appendChild(document.createElement('td'));
    cell.colSpan = 9;
    const dl = document.createElement('dl');
    dl.className = 'meta-grid';
    const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
    add('完整样本键', sample.key);
    add('会话 / 轮次', sample.session + ' / ' + (sample.turn === null ? '未知' : sample.turn));
    add('归属', sample.owner_session + (sample.owner_turn ? '，轮次 ' + sample.owner_turn : ''));
    add('类别 / 状态', sample.category + ' / ' + (sample.status === 'failed' ? '已失败（保留真实耗时与失败状态）' : '已完成'));
    add('执行起止', sample.exec_start === null ? '无明确实际执行起止（不补造）' : sample.exec_start + ' → ' + sample.exec_end);
    add('调度跨度', sample.dispatch_start === null ? '无调度时间证据'
      : sample.dispatch_start + ' → ' + sample.dispatch_end + '（调度至完成；不加入执行耗时和）');
    add('完成事件', sample.completed_at);
    add('执行耗时', nsToMsText(sample.value) + ' ms（精确 ' + sample.value.toString() + ' ns；'
      + (sample.basis === 'native' ? '原生' : '推导（实际执行起止求差）') + '；精度 ' + sample.precision + '）');
    add('原生耗时', sample.native_duration_ns === null ? '无（推导样本）' : sample.native_duration_ns.toString() + ' ns');
    const loc = sample.source || {};
    add('来源定位', String(loc.path || '未知') + (loc.table ? '（表 ' + loc.table + (loc.id !== undefined && loc.id !== null ? '，行 ' + String(loc.id) : '') + ')' : loc.line ? '：第 ' + String(loc.line) + ' 行' : ''));
    cell.appendChild(dl);
    tbody.insertBefore(detailRow, tr.nextSibling);
  };
  const revealSamples = () => {
    let ancestor = samplesHost.parentElement;
    while (ancestor) {
      if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    samplesHost.scrollIntoView({ block: 'nearest' });
  };
  const locateSamples = keys => {
    locatedKeys = keys.slice();
    if (samplesHost.parentElement !== null) {
      drawSamples();
      revealSamples();
      return;
    }
    // First locate before the lazy sample card ever opened: opening it queues the
    // mount build (which draws the located subset); the reveal runs after that lands.
    samplesCard.open = true;
    setTimeout(revealSamples, 0);
  };

  const groupTable = (title, members) => {
    const frag = document.createDocumentFragment();
    frag.appendChild(el('h3', null, title + '（成员值由该组精确耗时之和重新生成）'));
    const table = document.createElement('table');
    const headRow = document.createElement('tr');
    ['行', '耗时和（ms，两位小数）', '精确耗时之和（ns）', '样本数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    for (const member of members) {
      const tr = document.createElement('tr');
      const labelCell = tr.appendChild(el('td', 'path', short(member.category !== undefined ? member.category : member.session, 40)));
      labelCell.title = member.category !== undefined ? member.category : member.session;
      tr.appendChild(el('td', null, nsToMsText(member.numerator)));
      tr.appendChild(el('td', null, member.numerator.toString()));
      tr.appendChild(el('td', null, member.denominator.toString()));
      const op = tr.appendChild(document.createElement('td'));
      const btn = el('button', null, '定位');
      btn.type = 'button';
      btn.title = '沿保存样本键定位该组成员样本（不改变范围与合计）';
      btn.addEventListener('click', () => locateSamples(member.sample_keys));
      op.appendChild(btn);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    frag.appendChild(tableScroll(table));
    return frag;
  };
  block.appendChild(groupTable('按工具类别分组', metric.projections.category));
  // Session content renders on demand only (same contract as the model metrics);
  // category groups stay eager.
  const sessionMembers = metric.projections.session;
  block.appendChild(el('p', 'hint-line', '按会话分组：共 ' + sessionMembers.length
    + ' 个会话；默认收起，展开后按 20 行分页（成员值由该组精确耗时之和重新生成，定位直达样本）。'));
  block.appendChild(lazyEvidenceCard('展开按会话分组（' + sessionMembers.length + ' 个会话）', body => {
    const headRow = document.createElement('tr');
    ['行', '耗时和（ms，两位小数）', '精确耗时之和（ns）', '样本数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    body.appendChild(pagedBody(headRow, sessionMembers, (member, tbody) => {
      const tr = document.createElement('tr');
      const labelCell = tr.appendChild(el('td', 'path', short(member.session, 40)));
      labelCell.title = member.session;
      tr.appendChild(el('td', null, nsToMsText(member.numerator)));
      tr.appendChild(el('td', null, member.numerator.toString()));
      tr.appendChild(el('td', null, String(member.sample_keys.length)));
      const op = tr.appendChild(document.createElement('td'));
      const btn = el('button', null, '定位');
      btn.type = 'button';
      btn.title = '沿保存样本键定位该组成员样本（不改变范围与合计）';
      btn.addEventListener('click', () => locateSamples(member.sample_keys));
      op.appendChild(btn);
      tbody.appendChild(tr);
    }));
  }));

  // Day chart: one bar per saved day member, scaled by exact integer comparison of sums.
  const days = metric.projections.day;
  block.appendChild(el('h3', null, '日分布（按完成事件与保存时区分日；未知不画零）'));
  if (days.length) {
    const maxMember = days.reduce((best, m) => m.numerator > best.numerator ? m : best, days[0]);
    const barHeight = 22, labelWidth = 110, valueWidth = 240, gap = 6, trackWidth = 320;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', String(labelWidth + trackWidth + valueWidth));
    svg.setAttribute('height', String(days.length * (barHeight + gap) + 4));
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', metric.label + '日分布条形图');
    days.forEach((member, i) => {
      const y = i * (barHeight + gap) + 2;
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('tabindex', '0');
      group.setAttribute('role', 'button');
      group.setAttribute('aria-label', '定位 ' + member.date + ' 的 ' + member.sample_keys.length + ' 条样本');
      group.addEventListener('click', () => locateSamples(member.sample_keys));
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); locateSamples(member.sample_keys); }
      });
      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = member.date + '：' + nsToMsText(member.numerator) + ' ms（' + member.sample_keys.length + ' 条样本）';
      group.appendChild(title);
      const labelNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      labelNode.setAttribute('x', String(labelWidth - 6)); labelNode.setAttribute('y', String(y + 15));
      labelNode.setAttribute('text-anchor', 'end'); labelNode.setAttribute('class', 'bar-label');
      labelNode.textContent = member.date;
      group.appendChild(labelNode);
      const track = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      track.setAttribute('x', String(labelWidth)); track.setAttribute('y', String(y));
      track.setAttribute('width', String(trackWidth)); track.setAttribute('height', String(barHeight));
      track.setAttribute('class', 'bar-track');
      group.appendChild(track);
      const scaled = maxMember.numerator === 0n ? 0 : Number(member.numerator * 10000n / maxMember.numerator) / 10000;
      const barWidth = Math.max(2, Math.round(scaled * trackWidth));
      const fill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      fill.setAttribute('x', String(labelWidth)); fill.setAttribute('y', String(y));
      fill.setAttribute('width', String(barWidth)); fill.setAttribute('height', String(barHeight));
      fill.setAttribute('class', 'bar-fill');
      group.appendChild(fill);
      const valueNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      valueNode.setAttribute('x', String(labelWidth + trackWidth + 8)); valueNode.setAttribute('y', String(y + 15));
      valueNode.setAttribute('class', 'bar-value');
      valueNode.textContent = nsToMsText(member.numerator) + ' ms · ' + member.sample_keys.length + ' 条';
      group.appendChild(valueNode);
      svg.appendChild(group);
    });
    const chartHost = el('div', 'chart-host');
    chartHost.appendChild(svg);
    block.appendChild(chartHost);
    block.appendChild(el('p', 'hint-line', '点选日期条定位当日样本（键盘：Tab 聚焦后 Enter/空格；只切换视图，不改变计数与合计）。'));
  }
  const samplesCard = lazyEvidenceCard('有效工具样本明细（' + metric.samples.length + ' 条；稳定样本键＝完整会话＋真实 item/tool_call_id——按需生成并分页）',
    body => {
      body.appendChild(samplesHost);
      drawSamples();
    });
  block.appendChild(samplesCard);
  return block;
}

function buildPerformanceSection(obj) {
  // Performance display only consumes the saved extension; the browser never re-derives
  // admission, re-aggregates ratios beyond member numerator/denominator, or ranks harnesses.
  const nodes = [el('h2', null, '性能分析（模型 TTFT/来源观测区间吞吐与工具执行耗时；各指标独立入样，有效集合与 token 选集可能不同，不改变 token 合计）')];
  const ext = obj.analysis;
  if (!ext || !ext.performance) {
    nodes.push(el('p', 'hint-line', '本报告未保存性能分析（旧报告）；token 结果不受影响。'));
    return nodes;
  }
  const perf = ext.performance;
  nodes.push(el('p', 'hint-line', perf.note));
  nodes.push(el('p', 'hint-line', '性能日分布时区：' + perf.tz.name + '（' + perf.tz.evidence
    + '）；分组与日分布由各成员精确分子/分母重新生成，不从舍入后的上层值推导。'));
  for (const name of PERF_METRIC_NAMES) nodes.push(buildPerfMetricBlock(perf, name));
  if (perf.metrics.tool_duration) {
    nodes.push(buildToolMetricBlock(perf));
  } else {
    nodes.push(el('p', 'hint-line', '本报告未保存工具执行耗时分析（旧报告）；token 与其他性能结果不受影响，不补零。'));
  }
  return nodes;
}

function renderReport(obj, version, footerText, sectionId) {
  sectionId = sectionId || 'report';
  const report = document.getElementById(sectionId);
  const empty = document.getElementById(sectionId === 'report' ? 'empty' : sectionId + '-empty');
  report.textContent = '';
  empty.hidden = true;
  empty.classList.remove('error');
  empty.firstElementChild.textContent = '未加载报告。选择一个由 token 统计工具导出的 JSON 报告文件。';
  const scope = obj.scope;

  const card = (...nodes) => { const c = el('section', 'card'); nodes.forEach(n => c.appendChild(n)); report.appendChild(c); return c; };
  report.hidden = false;

  const statusTag = el('span', 'status-tag status-' + obj.status, STATES[obj.status] || obj.status);
  const head = el('h2', null, '报告范围与状态');
  card(head, statusTag, (() => {
    const dl = document.createElement('dl');
    dl.className = 'meta-grid';
    const add = (term, value) => { dl.appendChild(el('dt', null, term)); const dd = el('dd'); if (value instanceof Node) dd.appendChild(value); else dd.textContent = value === null || value === undefined ? '未指定' : value; dl.appendChild(dd); };
    add('任务', scope.label || '所选范围');
    add('Harness', obj.harness);
    add('会话', scope.session);
    add('轮次', scope.turns === null ? '整个会话' : scope.turns.join('、'));
    add('时间下界', scope.from || '未指定');
    add('截止点', scope.to + '（来源：' + scope.cutoff_source + '）');
    add('代理策略', scope.main_only ? '仅主代理常规调用' : '含可靠归属的后代与内部调用');
    add('实际读取时间', obj.read_at);
    add('覆盖说明', obj.coverage);
    if (obj.activity) add('活跃状态', (STATES[obj.activity.status] || '未知') + (obj.activity.wall_seconds !== null && obj.activity.wall_seconds !== undefined ? '；墙钟秒 ' + String(obj.activity.wall_seconds) : ''));
    return dl;
  })());

  card(el('h2', null, '分组用量（与 CLI 表格同值）'), (() => {
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['分组', '输入', '输出', '缓存读取', '缓存命中率', '总量'].forEach(h => headRow.appendChild(el('th', null, h)));
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const row of obj.rows) addRow(tbody, GROUP_LABELS[row.group] || row.group, row, false);
    addRow(tbody, '已记录小计', obj.summary, true);
    table.appendChild(tbody);
    const note = el('p', null, '输入包含缓存读取；缓存与已包含的推理输出不再相加。缓存命中率的分母是配对输入'
      + '（输入与缓存读取均已知的记录子集），不是总输入。调用数：'
      + (obj.summary.call_count === null ? '未知' : obj.summary.call_count.toString())
      + '；其中已识别 ' + (obj.summary.known_call_count === null ? '未知' : obj.summary.known_call_count.toString()) + ' 次。');
    note.className = 'hint-line';
    const wrap = document.createDocumentFragment();
    wrap.appendChild(tableScroll(table));
    wrap.appendChild(note);
    return wrap;
  })());

  card(...buildCostSection(obj));
  card(...buildPerformanceSection(obj));

  const localizationCard = (() => {
    const nodes = [];
    if (obj.localization) {
      const dl = document.createElement('dl');
      dl.className = 'meta-grid';
      const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
      add('会话确认方式', obj.localization.session.confirmed_by + '（' + obj.localization.session.evidence + '）');
      add('截止点', obj.localization.cutoff.source + '（' + obj.localization.cutoff.evidence + '）');
      nodes.push(dl);
      for (const limit of obj.localization.limits || []) nodes.push(el('p', 'notes', '定位限制：' + limit));
    } else {
      nodes.push(el('p', null, '旧报告未保存定位证据。'));
    }
    return nodes;
  })();
  report.appendChild(evidenceCard('定位证据', localizationCard));

  const supportCard = (() => {
    const nodes = [];
    if (obj.internal_support) {
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const key of Object.keys(SUPPORT_LABELS)) {
        const item = obj.internal_support[key];
        ul.appendChild(el('li', null, SUPPORT_LABELS[key] + '：' + (SUPPORT_STATES[item.status] || item.status) + '。' + item.summary));
      }
      nodes.push(ul);
    } else {
      nodes.push(el('p', null, '旧报告未保存内部来源支持说明。'));
    }
    return nodes;
  })();
  report.appendChild(evidenceCard('内部来源支持', supportCard));

  let viewLocateHandler = null;   // set by the records block once it exists
  let viewClearHandler = null;
  const viewsSection = (() => {
    const nodes = [el('h2', null, '消耗分布与明细视图')];
    const wrap = el('div');
    const hasViews = !!obj.views;
    const dimensions = [
      { key: 'group', label: '分组', available: true },
      { key: 'model', label: '模型', available: hasViews && obj.views.model.available },
      { key: 'agent', label: '代理', available: hasViews && obj.views.agent.available },
      { key: 'turn', label: '轮次', available: hasViews && obj.views.turn.available },
    ];
    const metrics = [['input', '输入'], ['output', '输出'], ['cache_read', '缓存读取'], ['total', '总量']];
    const controls = el('div'); controls.className = 'views-controls';
    const dimField = document.createElement('fieldset');
    dimField.appendChild(el('legend', null, '维度'));
    for (const dim of dimensions) {
      const label = el('label', null);
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = sectionId + ':dimension'; radio.value = dim.key;
      radio.checked = dim.key === 'group'; radio.disabled = !dim.available;
      radio.id = sectionId + '-dim-' + dim.key;
      label.appendChild(radio); label.appendChild(document.createTextNode(dim.label + (dim.available ? '' : '（不可用）')));
      dimField.appendChild(label);
    }
    controls.appendChild(dimField);
    const metricField = document.createElement('fieldset');
    metricField.appendChild(el('legend', null, '指标'));
    for (const [key, label] of metrics) {
      const l = el('label', null);
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = sectionId + ':metric'; radio.value = key;
      radio.checked = key === 'total'; radio.id = sectionId + '-metric-' + key;
      l.appendChild(radio); l.appendChild(document.createTextNode(label));
      metricField.appendChild(l);
    }
    controls.appendChild(metricField);
    const filterLabel = el('label', null, '行筛选：');
    const filterInput = document.createElement('input');
    filterInput.type = 'text'; filterInput.id = sectionId + '-row-filter'; filterInput.placeholder = '按标签筛选当前视图行';
    filterLabel.appendChild(filterInput);
    const clearButton = el('button', null, '清除筛选');
    clearButton.type = 'button'; clearButton.id = sectionId + '-clear-filter';
    filterLabel.appendChild(clearButton);
    controls.appendChild(filterLabel);
    wrap.appendChild(controls);
    const chartHost = el('div'); chartHost.id = sectionId + '-chart-host'; chartHost.className = 'chart-host';
    wrap.appendChild(chartHost);
    const tableHost = el('div'); tableHost.id = sectionId + '-view-table-host';
    wrap.appendChild(tableHost);
    const hint = el('p', 'hint-line', '图表与明细来自同一报告的保存视图；点选一行定位其计量明细（替换上次选择）；筛选只隐藏视图行，不改变定位集合、合计或占比分母。');
    wrap.appendChild(hint);
    if (!hasViews) {
      const note = el('p', 'unavailable', '模型/代理/轮次维度：旧报告未保存，不可用；不从旧记录推算。');
      note.id = sectionId + '-views-unavailable-note';
      wrap.appendChild(note);
    }
    nodes.push(wrap);
    return { nodes, render: () => renderViews(obj) };
  })();
  card(...viewsSection.nodes);

  function viewRowsOf(report, dimension) {
    if (dimension === 'group') {
      return (report.rows || []).map(row => ({ id: row.group, label: GROUP_LABELS[row.group] || row.group, aggregate: row }));
    }
    return report.views[dimension].rows.map(row => ({ id: row.id, label: row.label, aggregate: row }));
  }

  function renderViews(report) {
    const dimension = document.querySelector('input[name="' + sectionId + ':dimension"]:checked').value;
    const metricKey = document.querySelector('input[name="' + sectionId + ':metric"]:checked').value;
    const metricLabel = { input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' }[metricKey];
    const rows = viewRowsOf(report, dimension);
    const filter = (document.getElementById(sectionId + '-row-filter').value || '').trim().toLowerCase();
    const visible = filter ? rows.filter(r => r.label.toLowerCase().includes(filter) || r.id.toLowerCase().includes(filter)) : rows;
    const denominator = report.summary.metrics[metricKey].value;
    const denominatorText = denominator === null ? '未知（占比不适用）'
      : (report.summary.metrics[metricKey].state !== 'known' ? '原合计（部分）' : '原合计') + ' ' + denominator.toLocaleString('en-US');
    const anyKnown = visible.some(r => r.aggregate.metrics[metricKey].value !== null);
    const chartHost = document.getElementById(sectionId + '-chart-host');
    chartHost.textContent = '';
    const chartTitle = el('p', 'hint-line', '当前指标：' + metricLabel + '；占比分母：' + denominatorText
      + (filter ? '；已隐藏 ' + (rows.length - visible.length) + ' 行（筛选条件：' + filter + '）' : '') + '。');
    chartHost.appendChild(chartTitle);
    if (!anyKnown) {
      chartHost.appendChild(el('p', 'unavailable', '图表不可用：当前视图该指标无任何已记录数值；其他有效指标与证据仍可读。'));
    } else {
      const barHeight = 26, labelWidth = 260, valueWidth = 200, gap = 6;
      const width = Math.min(920, chartHost.clientWidth || 920);
      const valueMax = visible.reduce((max, r) => r.aggregate.metrics[metricKey].value > max ? r.aggregate.metrics[metricKey].value : max, 0n);
      const trackWidth = Math.max(120, width - labelWidth - valueWidth - 16);
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', String(width));
      svg.setAttribute('height', String(visible.length * (barHeight + gap) + 4));
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', metricLabel + '分布条形图');
      visible.forEach((row, i) => {
        const y = i * (barHeight + gap) + 2;
        const metric = row.aggregate.metrics[metricKey];
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        if (row.aggregate.record_keys && row.aggregate.record_keys.length && viewLocateHandler) {
          group.setAttribute('tabindex', '0');
          group.setAttribute('role', 'button');
          group.setAttribute('aria-label', '定位 ' + row.label + ' 的明细');
          group.addEventListener('click', () => viewLocateHandler(row.aggregate.record_keys));
          group.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); viewLocateHandler(row.aggregate.record_keys); }
          });
        }
        const labelNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        labelNode.setAttribute('x', String(labelWidth - 6)); labelNode.setAttribute('y', String(y + 17));
        labelNode.setAttribute('text-anchor', 'end'); labelNode.setAttribute('class', 'bar-label');
        labelNode.textContent = row.label;
        group.appendChild(labelNode);
        const track = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        track.setAttribute('x', String(labelWidth)); track.setAttribute('y', String(y));
        track.setAttribute('width', String(trackWidth)); track.setAttribute('height', String(barHeight));
        track.setAttribute('class', 'bar-track');
        group.appendChild(track);
        if (metric.value !== null) {
          const scaled = valueMax === 0n ? 0 : Number(metric.value * 10000n / valueMax) / 10000;
          const barWidth = Math.round(scaled * trackWidth);
          const fill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          fill.setAttribute('x', String(labelWidth)); fill.setAttribute('y', String(y));
          fill.setAttribute('width', String(barWidth)); fill.setAttribute('height', String(barHeight));
          fill.setAttribute('class', 'bar-fill' + (metric.state !== 'known' ? ' partial' : ''));
          group.appendChild(fill);
        }
        const valueNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        valueNode.setAttribute('x', String(labelWidth + trackWidth + 8)); valueNode.setAttribute('y', String(y + 17));
        valueNode.setAttribute('class', 'bar-value');
        let valueText;
        if (metric.value === null) valueText = '未知（无数值条）';
        else {
          valueText = metric.value.toLocaleString('en-US') + (metric.value === 0n ? '（零）' : '');
          if (metric.state !== 'known') valueText += '（部分）';
          if (denominator !== null && denominator !== 0n && metric.value !== 0n) {
            valueText += ' · ' + percentText(metric.value, denominator);
          }
        }
        valueNode.textContent = valueText;
        group.appendChild(valueNode);
        svg.appendChild(group);
      });
      chartHost.appendChild(svg);
    }
    const tableHost = document.getElementById(sectionId + '-view-table-host');
    tableHost.textContent = '';
    const table = document.createElement('table');
    table.className = 'view-table';
    const theadRow = document.createElement('tr');
    ['行', metricLabel, '占比（原分母）', '调用数', '操作'].forEach(h => theadRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(theadRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    for (const row of visible) {
      const tr = document.createElement('tr');
      const labelCell = tr.appendChild(el('td', 'expandable', row.label + ' '));
      const marker = el('span', 'mark', row.aggregate.metrics[metricKey].state !== 'known' && row.aggregate.metrics[metricKey].value !== null ? '（部分）' : '');
      if (marker.textContent) labelCell.appendChild(marker);
      const valueCell = tr.appendChild(document.createElement('td'));
      const metric = row.aggregate.metrics[metricKey];
      valueCell.textContent = metric.value === null ? '未知' : metric.value.toLocaleString('en-US') + (metric.value === 0n ? '（零）' : '');
      if (metric.value === null) valueCell.classList.add('unknown');
      const pctCell = tr.appendChild(document.createElement('td'));
      if (metric.value === null || denominator === null || denominator === 0n) pctCell.textContent = '不适用';
      else { pctCell.textContent = percentText(metric.value, denominator); }
      const countCell = tr.appendChild(document.createElement('td'));
      countCell.textContent = row.aggregate.call_count === null ? '未知' : row.aggregate.call_count.toLocaleString('en-US');
      let expanded = false;
      const opCell = tr.appendChild(document.createElement('td'));
      if (row.aggregate.record_keys && row.aggregate.record_keys.length && viewLocateHandler) {
        const locateBtn = el('button', null, '定位');
        locateBtn.type = 'button';
        locateBtn.title = '定位该行对应的 ' + row.aggregate.record_keys.length + ' 条计量明细';
        locateBtn.addEventListener('click', () => viewLocateHandler(row.aggregate.record_keys));
        opCell.appendChild(locateBtn);
      } else {
        opCell.appendChild(el('span', 'hint-line', '旧报告未保存行级引用'));
      }
      const detailRow = document.createElement('tr');
      detailRow.className = 'row-detail'; detailRow.hidden = true;
      const detailCell = detailRow.appendChild(document.createElement('td'));
      detailCell.colSpan = 5;
      labelCell.addEventListener('click', () => {
        expanded = !expanded;
        detailRow.hidden = !expanded;
        if (expanded) {
          detailCell.textContent = '';
          const dl = document.createElement('dl');
          const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
          for (const name of METRICS) {
            const m = row.aggregate.metrics[name];
            add(name, m.value === null ? '未知' : m.value.toLocaleString('en-US') + (m.state !== 'known' ? '（部分）' : ''));
          }
          const rate = row.aggregate.cache_hit_rate;
          add('缓存命中子集', rate.paired_records.toString() + ' 条；' + (rate.value === null ? '不适用/未知' : percentText(1n, 1n, rate.value)));
          add('调用数', row.aggregate.call_count === null ? '未知（部分行无调用计数）' : row.aggregate.call_count.toLocaleString('en-US'));
          add('行级记录', '该行对应的计量明细经“操作”列定位；旧报告未保存行级引用，报告级来源见“来源与缺口”');
          detailCell.appendChild(dl);
        }
      });
      tbody.appendChild(tr);
      tbody.appendChild(detailRow);
    }
    tableHost.appendChild(tableScroll(table));
    if (visible.length !== rows.length) {
      tableHost.appendChild(el('p', 'hint-line', '已按筛选隐藏 ' + (rows.length - visible.length) + ' 行；原范围、截止点、合计与占比分母保持不变。'));
    }
  }

  function percentText(value, denominator, presetRate) {
    const rate = presetRate !== undefined
      ? (typeof presetRate === 'bigint' ? Number(presetRate) : presetRate)
      : Number(value * 10000n / denominator) / 10000;
    const pct = rate * 100;
    const text = (Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(3).replace(/0+$/, '')) + '%';
    return text;
  }

  viewsSection.render();
  // Controls stay bound to this section's own report; another section rendering later
  // must never redirect them.
  document.querySelectorAll('input[name="' + sectionId + ':dimension"]').forEach(radio => {
    radio.addEventListener('change', () => { if (viewClearHandler) viewClearHandler(); renderViews(obj); });
  });
  document.querySelectorAll('input[name="' + sectionId + ':metric"]').forEach(radio => {
    radio.addEventListener('change', () => renderViews(obj));  // metric switch keeps the current location
  });
  document.getElementById(sectionId + '-row-filter').addEventListener('input', () => renderViews(obj));
  document.getElementById(sectionId + '-clear-filter').addEventListener('click', () => {
    document.getElementById(sectionId + '-row-filter').value = '';
    renderViews(obj);
  });

  card(el('h2', null, '来源与缺口'), (() => {
    const frag = document.createDocumentFragment();
    if (obj.issues && obj.issues.length) {
      const grouped = {};
      for (const issue of obj.issues) grouped[issue.reason] = (grouped[issue.reason] || 0) + 1;
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const reason of Object.keys(grouped)) ul.appendChild(el('li', null, '缺口：' + reason + '（' + grouped[reason] + ' 处）'));
      frag.appendChild(el('p', null, '缺口说明（始终可见，不折叠）：'));
      frag.appendChild(ul);
    } else {
      frag.appendChild(el('p', null, '无已记录缺口（不代表证明完整覆盖）。'));
    }
    const sourcesDetails = el('details', 'evidence-inner');
    sourcesDetails.appendChild(el('summary', null, '来源文件列表（' + obj.source_files.length + ' 个；仅展示路径，不自动读取）'));
    const sources = document.createElement('ul');
    sources.className = 'notes';
    for (const path of obj.source_files) {
      const li = el('li');
      li.appendChild(el('span', 'path', path));
      sources.appendChild(li);
    }
    sourcesDetails.appendChild(sources);
    frag.appendChild(sourcesDetails);
    return frag;
  })());

  const extra = [];
  for (const tool of obj.tool_reports || []) {
    extra.push('仅工具报告：' + tool.agent + '，累计 ' + tool.total.toString() + '；独立展示，不与 usage 相加。');
  }
  if (obj.unassigned_records && obj.unassigned_records.length) {
    const unassignedTotal = obj.unassigned_records.reduce((sum, r) => sum + (r.metrics.total.value || 0n), 0n);
    extra.push('会话辅助/未归属（未摊入所选任务）：' + obj.unassigned_records.length + ' 条，已记录总量 ' + unassignedTotal.toString() + '。');
  }
  if (obj.inherited_records && obj.inherited_records.length) {
    extra.push('已验证继承副本（不贡献本会话新增量）：' + obj.inherited_records.length + ' 条。');
  }
  for (const alt of obj.alternate_sources || []) {
    extra.push('补充来源（' + alt.kind + '，会话 ' + alt.session + '）：' + alt.records.toString() + ' 条，输入 '
      + (alt.metrics.input.value === null ? '未知' : alt.metrics.input.value.toString()) + '；' + alt.note + '。来源：' + alt.path);
  }
  if (extra.length) {
    const ul = document.createElement('ul');
    ul.className = 'notes';
    extra.forEach(x => ul.appendChild(el('li', null, x)));
    report.appendChild(evidenceCard('独立证据（不并入小计）', [ul]));
  }
  let locateRecordsByKeys = null;
  const recordsDetail = buildRecordsDetail(obj);
  if (recordsDetail) {
    report.appendChild(evidenceCard('调用明细', recordsDetail.nodes));
    locateRecordsByKeys = recordsDetail.locate;
    viewLocateHandler = recordsDetail.locate;
    viewClearHandler = recordsDetail.clear;
  }
  if (obj.explanation && Array.isArray(obj.explanation.turns)) {
    report.appendChild(evidenceCard('轮次时间线与已有耗时', [buildTimelineCard(obj, locateRecordsByKeys)]));
  }

  if (obj.explanation && (Array.isArray(obj.explanation.internal) && obj.explanation.internal.length
      || Array.isArray(obj.explanation.relations) && obj.explanation.relations.length
      || Array.isArray(obj.explanation.excluded) && obj.explanation.excluded.length)) {
    report.appendChild(evidenceCard('内部分布、后代关系与未计量证据', [buildInternalRelationsCard(obj, locateRecordsByKeys)]));
  }

  const loaded = el('p', 'hint-line', footerText);
  report.appendChild(loaded);
}

function short(text, max) {
  const value = String(text === null || text === undefined ? '未知' : text);
  return value.length > max ? value.slice(0, max - 1) + '…' : value;
}


function renderOverviewReport(obj, footerText, sectionId, onDayClick) {
  sectionId = sectionId || 'overview-result';
  let overviewLocate = null;
  if (typeof state !== 'undefined' && state.overview) state.overview.locate = null;
  const report = document.getElementById(sectionId);
  report.textContent = '';
  report.hidden = false;
  const scope = obj.scope;
  const card = (...nodes) => { const c = el('section', 'card'); nodes.forEach(n => c.appendChild(n)); report.appendChild(c); return c; };

  // Result scope band: the identity/range THIS report actually used, visually apart from
  // the pending query form above it. A one-line summary keeps the first screen compact;
  // the full metadata stays one disclosure away.
  const band = el('section', 'card scope-band');
  const bandHead = el('div', 'band-head');
  bandHead.appendChild(el('h2', null, '结果范围与状态'));
  bandHead.appendChild(el('span', 'status-tag status-' + obj.status, STATES[obj.status] || obj.status));
  band.appendChild(bandHead);
  band.appendChild(el('p', 'band-summary', 'Harness（实际身份）：' + obj.harness + '；会话集合 ' + scope.sessions.length + ' 个；时间范围 '
    + (scope.from || '未指定') + '（含）→ ' + scope.to + '（不含）；显示时区 ' + scope.tz + '；'
    + (scope.main_only ? '仅主代理常规调用' : '含可靠归属的后代与内部调用')));
  const fullRange = el('details', 'inline-details');
  fullRange.appendChild(el('summary', null, '核对完整范围与元数据（截止点来源、代理策略、覆盖说明、读取时间与完整会话集合）'));
  const bandDl = document.createElement('dl');
  bandDl.className = 'meta-grid';
  const bandAdd = (term, value) => {
    bandDl.appendChild(el('dt', null, term));
    const dd = el('dd');
    if (value instanceof Node) dd.appendChild(value); else dd.textContent = value === null || value === undefined ? '未指定' : value;
    bandDl.appendChild(dd);
  };
  bandAdd('Harness（实际身份）', obj.harness);
  const sessionsSummary = document.createDocumentFragment();
  sessionsSummary.appendChild(document.createTextNode(scope.sessions.length + ' 个（' + scope.sessions.slice(0, 5).map(s => short(s, 16)).join('、')
    + (scope.sessions.length > 5 ? ' …' : '') + '）'));
  const fullSet = el('details', 'inline-details');
  fullSet.appendChild(el('summary', null, '核对完整会话集合（' + scope.sessions.length + ' 个稳定身份；按 20 行分页）'));
  // Session content builds on demand: nothing is constructed until this disclosure
  // is first opened, then the identities render through the shared pager.
  let fullSetBuilt = false;
  fullSet.addEventListener('toggle', () => {
    if (!fullSet.open || fullSetBuilt) return;
    fullSetBuilt = true;
    const headRow = document.createElement('tr');
    headRow.appendChild(el('th', null, '会话身份'));
    fullSet.appendChild(pagedBody(headRow, scope.sessions, (sid, tbody) => {
      const tr = document.createElement('tr');
      const cell = tr.appendChild(el('td', 'path', sid));
      cell.title = sid;
      tbody.appendChild(tr);
    }));
  });
  sessionsSummary.appendChild(fullSet);
  bandAdd('会话集合', sessionsSummary);
  bandAdd('时间范围', (scope.from || '未指定') + '（含）→ ' + scope.to + '（不含）');
  bandAdd('固定截止点', scope.to + '（来源：' + scope.cutoff_source + '）');
  bandAdd('显示时区', scope.tz);
  bandAdd('代理策略', scope.main_only ? '仅主代理常规调用' : '含可靠归属的后代与内部调用');
  bandAdd('覆盖说明', obj.coverage);
  bandAdd('实际读取时间', obj.read_at);
  fullRange.appendChild(bandDl);
  band.appendChild(fullRange);
  band.appendChild(el('p', 'hint-line', '本范围带是这份结果实际采用的身份、范围与状态，与待提交的查询表单分开；编辑表单不改变本报告。'));
  report.appendChild(band);

  // Four metric cards straight from report.summary; full integers, states and reasons kept.
  const metricCards = el('div', 'metric-cards');
  const confirmedZero = obj.status === 'confirmed_zero';
  const metricCard = (label, metric, note) => {
    const cardNode = el('div', 'metric-card');
    if (metric.state === 'partial') cardNode.classList.add('partial');
    if (metric.state === 'unknown' || metric.value === null) cardNode.classList.add('unknown');
    cardNode.appendChild(el('div', 'metric-label', label));
    const formatted = fmtInt(metric.value, metric.state);
    cardNode.appendChild(el('div', 'metric-value', formatted ? formatted.text : '未知'));
    const notes = [];
    if (metric.state === 'partial') notes.push('部分：仍缺完整覆盖证据');
    if (metric.state === 'unknown' || metric.value === null) notes.push('未知');
    if (metric.state !== 'known' && Array.isArray(metric.reasons) && metric.reasons.length) notes.push(metric.reasons.join('；'));
    if (confirmedZero && metric.value === 0n) notes.push('确认零：范围内各会话均有完整零调用账本');
    if (note) notes.push(note);
    cardNode.appendChild(el('div', 'metric-note', notes.length ? notes.join('；') : '已记录'));
    return cardNode;
  };
  metricCards.appendChild(metricCard('已记录总量', obj.summary.metrics.total, null));
  metricCards.appendChild(metricCard('输入（含缓存读取）', obj.summary.metrics.input, null));
  metricCards.appendChild(metricCard('输出', obj.summary.metrics.output, null));
  const rate = obj.summary.cache_hit_rate;
  const rateCard = el('div', 'metric-card');
  if (rate.state === 'partial') rateCard.classList.add('partial');
  if (rate.value === null) rateCard.classList.add('unknown');
  rateCard.appendChild(el('div', 'metric-label', '缓存命中率'));
  const pctValue = rate.value === null ? null : (typeof rate.value === 'bigint' ? Number(rate.value) : rate.value) * 100;
  rateCard.appendChild(el('div', 'metric-value', pctValue === null
    ? (rate.state === 'not_applicable' ? '不适用' : '未知')
    : (Number.isInteger(pctValue) ? pctValue.toFixed(0) : pctValue.toFixed(3).replace(/0+$/, '')) + '%'));
  const rateNotes = [];
  if (rate.value === null) rateNotes.push(rate.state === 'not_applicable' ? '配对输入为 0，命中率不适用（不是 0%）' : '未知：没有输入与缓存读取均已知配对记录');
  if (rate.state === 'partial') rateNotes.push('部分：仅已知配对子集');
  rateNotes.push('配对子集 ' + rate.paired_records.toString() + ' 条记录、配对输入 ' + rate.input.toLocaleString('en-US')
    + '；分母是配对输入（输入与缓存读取均已知的记录子集），不是总输入；缓存读取不重复相加');
  rateCard.appendChild(el('div', 'metric-note', rateNotes.join('；')));
  metricCards.appendChild(rateCard);
  report.appendChild(metricCards);

  const trendSection = (() => {
    const head = el('div', 'trend-head');
    head.appendChild(el('h2', null, '日趋势（每个保存日一根柱；日范围＝原范围与本地日交集）'));
    const wrap = el('div');
    const metrics = [['input', '输入'], ['output', '输出'], ['cache_read', '缓存读取'], ['total', '总量']];
    const metricField = document.createElement('fieldset');
    metricField.className = 'inline-radios';
    metricField.appendChild(el('legend', null, '指标'));
    for (const [key, label] of metrics) {
      const l = el('label', null);
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = sectionId + ':trend-metric'; radio.value = key;
      radio.checked = key === 'total'; radio.id = sectionId + '-trend-' + key;
      l.appendChild(radio); l.appendChild(document.createTextNode(label));
      metricField.appendChild(l);
    }
    head.appendChild(metricField);
    const chartHost = el('div'); chartHost.id = sectionId + '-trend-chart-host'; chartHost.className = 'chart-host';
    wrap.appendChild(chartHost);
    const nodes = [head, wrap];
    return { nodes, render };
    function render() {
      const metricKey = document.querySelector('input[name="' + sectionId + ':trend-metric"]:checked').value;
      const metricLabel = { input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' }[metricKey];
      chartHost.textContent = '';
      const days = obj.days || [];
      const unbucketed = obj.unbucketed || { records: 0 };
      // The metric/bucket summary sits under the chart so the plot itself starts higher.
      const trendHint = el('p', 'hint-line', '当前指标：' + metricLabel + '；共 ' + days.length + ' 个保存日桶（按时间排列，不聚合、不补零桶）；无法归桶 '
        + unbucketed.records.toString() + ' 条' + (unbucketed.records ? '（说明见下方常显卡片）' : '') + '。');
      if (!days.length) {
        chartHost.appendChild(trendHint);
        chartHost.appendChild(el('p', 'unavailable', '无可归桶的日期数据；未知不画零，缺口见“来源与缺口”。'));
        return;
      }
      const anyKnown = days.some(d => d.metrics[metricKey].value !== null);
      if (!anyKnown) {
        chartHost.appendChild(trendHint);
        chartHost.appendChild(el('p', 'unavailable', '图表不可用：该指标无任何已记录数值。'));
        return;
      }
      const SVGNS = 'http://www.w3.org/2000/svg';
      const slotW = 48, barW = 30, plotH = 220, topPad = 16, labelH = 64, leftPad = 70, rightPad = 12;
      const width = leftPad + days.length * slotW + rightPad;
      const height = topPad + plotH + labelH;  // stable height: long series grow width and scroll
      const valueMax = days.reduce((max, d) => d.metrics[metricKey].value > max ? d.metrics[metricKey].value : max, 0n);
      const baseline = topPad + plotH;
      const yFor = v => baseline - (valueMax === 0n ? 0 : Number(v * 10000n / valueMax) / 10000) * plotH;
      const svg = document.createElementNS(SVGNS, 'svg');
      svg.setAttribute('width', String(width));
      svg.setAttribute('height', String(height));
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', '按日' + metricLabel + '柱状图');
      [[0n, '0', 'trend-axis'], [valueMax / 2n, fmtInt(valueMax / 2n).text, 'trend-grid'], [valueMax, fmtInt(valueMax).text, 'trend-grid']].forEach(pair => {
        const y = yFor(pair[0]);
        const line = document.createElementNS(SVGNS, 'line');
        line.setAttribute('x1', String(leftPad)); line.setAttribute('x2', String(width - rightPad));
        line.setAttribute('y1', String(y)); line.setAttribute('y2', String(y));
        line.setAttribute('class', pair[2]);
        svg.appendChild(line);
        const gridLabel = document.createElementNS(SVGNS, 'text');
        gridLabel.setAttribute('x', String(leftPad - 6)); gridLabel.setAttribute('y', String(y + 3));
        gridLabel.setAttribute('text-anchor', 'end'); gridLabel.setAttribute('class', 'trend-grid-label');
        gridLabel.textContent = pair[1];
        svg.appendChild(gridLabel);
      });
      days.forEach((day, i) => {
        const x = leftPad + i * slotW;
        const metric = day.metrics[metricKey];
        const group = document.createElementNS(SVGNS, 'g');
        group.setAttribute('class', 'trend-day');
        const title = document.createElementNS(SVGNS, 'title');
        title.textContent = day.date + '：' + metricLabel + ' '
          + (metric.value === null ? '未知（' + ((metric.reasons || []).join('；') || '来源未报告') + '）'
             : metric.value.toLocaleString('en-US') + (metric.state !== 'known' ? '（部分）' : ''));
        group.appendChild(title);
        if (onDayClick) {
          group.setAttribute('tabindex', '0');
          group.setAttribute('role', 'button');
          group.setAttribute('aria-label', '日期 ' + day.date + '，' + metricLabel
            + (metric.value === null ? ' 未知' : ' ' + metric.value.toLocaleString('en-US')) + '；回车查看当日分布');
          group.addEventListener('click', () => onDayClick(day));
          group.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onDayClick(day); }
          });
        }
        const hit = document.createElementNS(SVGNS, 'rect');
        hit.setAttribute('x', String(x + 2)); hit.setAttribute('y', String(topPad));
        hit.setAttribute('width', String(slotW - 4)); hit.setAttribute('height', String(plotH));
        hit.setAttribute('class', 'trend-hit');
        group.appendChild(hit);
        if (metric.value !== null) {
          const columnHeight = metric.value === 0n ? 0 : Math.max(2, Math.round(baseline - yFor(metric.value)));
          if (columnHeight > 0) {
            const bar = document.createElementNS(SVGNS, 'rect');
            bar.setAttribute('x', String(x + (slotW - barW) / 2)); bar.setAttribute('y', String(baseline - columnHeight));
            bar.setAttribute('width', String(barW)); bar.setAttribute('height', String(columnHeight));
            bar.setAttribute('class', 'trend-bar' + (metric.state !== 'known' ? ' partial' : ''));
            group.appendChild(bar);
          }
          // Exact values stay on the per-day tooltip/title; inline labels would collide
          // at this slot width.
        } else {
          const unknown = document.createElementNS(SVGNS, 'text');
          unknown.setAttribute('x', String(x + slotW / 2)); unknown.setAttribute('y', String(baseline - 6));
          unknown.setAttribute('text-anchor', 'middle'); unknown.setAttribute('class', 'trend-unknown');
          unknown.textContent = '未知';
          group.appendChild(unknown);
        }
        const labelNode = document.createElementNS(SVGNS, 'text');
        const lx = x + slotW / 2, ly = baseline + 12;
        labelNode.setAttribute('x', String(lx)); labelNode.setAttribute('y', String(ly));
        labelNode.setAttribute('text-anchor', 'end'); labelNode.setAttribute('class', 'trend-label');
        labelNode.setAttribute('transform', 'rotate(-45 ' + lx + ' ' + ly + ')');
        labelNode.textContent = day.date;
        group.appendChild(labelNode);
        svg.appendChild(group);
      });
      const scroll = el('div', 'trend-scroll');
      scroll.appendChild(svg);
      chartHost.appendChild(scroll);
      chartHost.appendChild(trendHint);
      if (onDayClick) chartHost.appendChild(el('p', 'hint-line', '点选日期柱查看当日模型/会话分布（键盘：Tab 聚焦日期柱后 Enter/空格；只切换视图，不重新读取来源）。'));
    }
  })();
  const trendCard = card(...trendSection.nodes);
  trendCard.id = sectionId + '-trend-card';
  document.querySelectorAll('input[name="' + sectionId + ':trend-metric"]').forEach(radio => {
    radio.addEventListener('change', () => trendSection.render());
  });
  trendSection.render();

  (() => {
    const unbucketed = obj.unbucketed || { records: 0 };
    if (!unbucketed.records) return;  // zero case stays visible as a count in the trend summary line
    const m = unbucketed.metrics || {};
    const known = ['input', 'output', 'cache_read', 'total'].filter(k => m[k] && m[k].value !== null)
      .map(k => ({ input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' })[k]
        + ' ' + m[k].value.toLocaleString('en-US') + (m[k].state !== 'known' ? '（部分）' : ''));
    const p = el('p', null, '无法归桶：' + unbucketed.records.toString() + ' 条（已计入总览、未计入任何一天；'
      + (unbucketed.reasons || []).join('；') + '）。' + (known.length ? '已记录：' + known.join('、') + '。' : '无可记录量。'));
    p.className = 'notes';
    card(el('h2', null, '无法归桶量对账（常显）'), p);
  })();

  const rankingSection = (() => {
    const nodes = [el('h2', null, '模型 / 会话排行（同一结果的独立视图，不加入合计；未知不归零；按所选指标降序）')];
    const metrics = [['input', '输入'], ['output', '输出'], ['cache_read', '缓存读取'], ['total', '总量']];
    const metricField = document.createElement('fieldset');
    metricField.className = 'inline-radios';
    metricField.appendChild(el('legend', null, '排行指标与排序'));
    for (const [key, label] of metrics) {
      const l = el('label', null);
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = sectionId + ':rank-metric'; radio.value = key;
      radio.checked = key === 'input'; radio.id = sectionId + '-rank-' + key;
      l.appendChild(radio); l.appendChild(document.createTextNode(label + ' '));
      metricField.appendChild(l);
    }
    nodes.push(metricField);
    const host = el('div'); host.id = sectionId + '-ranking-host';
    nodes.push(host);
    return { nodes, render };
    function render() {
      const metricKey = document.querySelector('input[name="' + sectionId + ':rank-metric"]:checked').value;
      const metricLabel = { input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' }[metricKey];
      host.textContent = '';
      const byMetric = rows => rows.slice().sort((a, b) => {
        const va = a.metrics[metricKey].value, vb = b.metrics[metricKey].value;
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        return va === vb ? 0 : va > vb ? -1 : 1;
      });
      const table = (title, view) => {
        const frag = document.createDocumentFragment();
        const sorted = byMetric(view.rows);
        const unknownCount = sorted.filter(row => row.metrics[metricKey].value === null).length;
        frag.appendChild(el('h3', null, title + '（按' + metricLabel + '降序）'));
        if (!sorted.length) {
          frag.appendChild(el('p', 'unavailable', '无可排行行。'));
          return frag;
        }
        frag.appendChild(el('p', 'hint-line', '共 ' + sorted.length + ' 行，其中该指标未知 ' + unknownCount
          + ' 行（未知不归零、排序置底，缺口常显于此摘要；行内状态在展开页可见）——按 20 行分页展示。'));
        const headRow = document.createElement('tr');
        ['行', '输入', '输出', '缓存读取', '缓存命中率', '总量', '调用数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
        frag.appendChild(pagedBody(headRow, sorted, (row, tbody) => {
          // Bind each rendered row to its own saved identity at draw time; the sorted
          // order never re-indexes into the unsorted view rows.
          addRow(tbody, row.label, row, false);
          const tr = tbody.lastChild;
          const op = tr.appendChild(document.createElement('td'));
          const keys = row.record_keys;
          if (keys && keys.length && overviewLocate) {
            const btn = el('button', null, '定位');
            btn.type = 'button';
            btn.title = '定位 ' + row.label + ' 的 ' + keys.length + ' 条计量明细';
            btn.addEventListener('click', () => overviewLocate(keys));
            op.appendChild(btn);
          } else {
            op.appendChild(el('span', 'hint-line', '旧报告未保存行级引用'));
          }
        }));
        return frag;
      };
      const grid = el('div', 'ranking-grid');
      const modelBlock = el('div', 'ranking-block');
      modelBlock.appendChild(table('模型排行', obj.rankings.model));
      const sessionBlock = el('div', 'ranking-block');
      // Session content renders on demand only: the count summary stays visible and
      // the paged table is built when the entry is opened. Model ranking stays eager.
      const sortedSessions = byMetric(obj.rankings.session.rows);
      const unknownSessions = sortedSessions.filter(row => row.metrics[metricKey].value === null).length;
      sessionBlock.appendChild(el('p', 'hint-line', '会话排行：共 ' + sortedSessions.length + ' 个会话，该指标未知 '
        + unknownSessions + ' 个（未知不归零、排序置底）；默认收起，展开后按 20 行分页。'));
      sessionBlock.appendChild(lazyEvidenceCard('展开会话排行（按' + metricLabel + '降序）',
        body => body.appendChild(table('会话排行', obj.rankings.session))));
      sessionBlock.appendChild(el('p', 'hint-line', '会话行为该会话自身记录的小计；单会话报告默认含可靠归属后代，口径不同。'));
      grid.appendChild(modelBlock);
      grid.appendChild(sessionBlock);
      host.appendChild(grid);
    }
  })();
  card(...rankingSection.nodes);
  document.querySelectorAll('input[name="' + sectionId + ':rank-metric"]').forEach(radio => {
    radio.addEventListener('change', () => rankingSection.render());
  });
  rankingSection.render();

  report.appendChild(evidenceCard('分组用量（互斥分组，与 CLI 同值）', [(() => {
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['分组', '输入', '输出', '缓存读取', '缓存命中率', '总量'].forEach(h => headRow.appendChild(el('th', null, h)));
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const row of obj.rows) addRow(tbody, GROUP_LABELS[row.group] || row.group, row, false);
    addRow(tbody, '已记录小计', obj.summary, true);
    table.appendChild(tbody);
    const note = el('p', null, '输入包含缓存读取；缓存与已包含的推理输出不再相加。缓存命中率的分母是配对输入'
      + '（输入与缓存读取均已知的记录子集），不是总输入。调用数：'
      + (obj.summary.call_count === null ? '未知' : obj.summary.call_count.toString())
      + '；其中已识别 ' + (obj.summary.known_call_count === null ? '未知' : obj.summary.known_call_count.toString()) + ' 次。');
    note.className = 'hint-line';
    const wrap = document.createDocumentFragment();
    wrap.appendChild(tableScroll(table));
    wrap.appendChild(note);
    return wrap;
  })()]));

  card(...buildCostSection(obj));
  card(...buildPerformanceSection(obj));

  const ovRecords = buildRecordsDetail(obj);
  if (ovRecords) {
    report.appendChild(evidenceCard('调用明细', ovRecords.nodes));
    overviewLocate = ovRecords.locate;
    if (typeof state !== 'undefined' && state.overview && state.overview.report === obj) state.overview.locate = overviewLocate;
    rankingSection.render();  // rewire ranking locate buttons
  }
  if (obj.explanation && Array.isArray(obj.explanation.turns)) {
    report.appendChild(lazyEvidenceCard('整体轮次时间线与按会话耗时（' + obj.explanation.turns.length + ' 行，按需生成并分页）',
      body => body.appendChild(buildTimelineCard(obj, overviewLocate))));
  }
  if (obj.explanation && ((Array.isArray(obj.explanation.internal) && obj.explanation.internal.length)
      || (Array.isArray(obj.explanation.relations) && obj.explanation.relations.length)
      || (Array.isArray(obj.explanation.excluded) && obj.explanation.excluded.length))) {
    report.appendChild(lazyEvidenceCard('内部分布、后代关系与未计量证据（按需生成）',
      body => body.appendChild(buildInternalRelationsCard(obj, overviewLocate))));
  }

  if (Array.isArray(obj.session_index) && obj.session_index.length) {
    const withUsage = obj.session_index.filter(item => item.usage_records || item.known_calls).length;
    report.appendChild(lazyEvidenceCard('会话索引（范围内会话的白名单元数据；' + obj.session_index.length
      + ' 个会话，其中 ' + withUsage + ' 个有 usage 记录或已识别调用——按需生成并分页）', body => {
      const headRow = document.createElement('tr');
      ['会话', '开始', '最近轮次结束', '轮次数', 'usage 记录', '已识别调用', '关系'].forEach(h => headRow.appendChild(el('th', null, h)));
      body.appendChild(pagedBody(headRow, obj.session_index, (item, tbody) => {
        const tr = document.createElement('tr');
        tr.appendChild(el('td', 'path', short(item.id, 40)));
        tr.appendChild(el('td', null, short(item.start, 26)));
        tr.appendChild(el('td', null, short(item.last_turn_end, 26)));
        tr.appendChild(el('td', null, String(item.turn_count)));
        tr.appendChild(el('td', null, String(item.usage_records)));
        tr.appendChild(el('td', null, String(item.known_calls)));
        tr.appendChild(el('td', null, item.parent ? '后代（父 ' + short(item.parent, 12) + '）'
          : item.forked_from ? '分叉自 ' + short(item.forked_from, 12) : '独立会话'));
        tbody.appendChild(tr);
      }));
    }));
  }

  const extra = [];
  for (const tool of obj.tool_reports || []) {
    extra.push('仅工具报告：' + tool.agent + '，累计 ' + tool.total.toString() + '；独立展示，不与 usage 相加。');
  }
  if (obj.inherited_records && obj.inherited_records.length) {
    extra.push('已验证继承副本（不贡献本会话新增量）：' + obj.inherited_records.length + ' 条。');
  }
  for (const alt of obj.alternate_sources || []) {
    extra.push('补充来源（' + alt.kind + '，会话 ' + alt.session + '）：' + alt.records.toString() + ' 条，输入 '
      + (alt.metrics.input.value === null ? '未知' : alt.metrics.input.value.toString()) + '；' + alt.note + '。来源：' + alt.path);
  }
  if (extra.length) {
    const ul = document.createElement('ul');
    ul.className = 'notes';
    extra.forEach(x => ul.appendChild(el('li', null, x)));
    report.appendChild(evidenceCard('独立证据（不并入小计）', [ul]));
  }

  report.appendChild(evidenceCard('定位证据', [(() => {
    const frag = document.createDocumentFragment();
    if (obj.localization) {
      const dl = document.createElement('dl');
      dl.className = 'meta-grid';
      const add = (term, value) => { dl.appendChild(el('dt', null, term)); dl.appendChild(el('dd', null, value)); };
      add('会话集合确认方式', obj.localization.sessions.confirmed_by + '（' + obj.localization.sessions.evidence + '）');
      add('截止点', obj.localization.cutoff.source + '（' + obj.localization.cutoff.evidence + '）');
      frag.appendChild(dl);
      for (const limit of obj.localization.limits || []) frag.appendChild(el('p', 'notes', '定位限制：' + limit));
    } else {
      frag.appendChild(el('p', null, '旧报告未保存定位证据。'));
    }
    return frag;
  })()]));

  report.appendChild(evidenceCard('内部来源支持', [(() => {
    if (!obj.internal_support) return el('p', null, '报告未保存内部来源支持说明。');
    const ul = document.createElement('ul');
    ul.className = 'notes';
    for (const key of Object.keys(SUPPORT_LABELS)) {
      const item = obj.internal_support[key];
      ul.appendChild(el('li', null, SUPPORT_LABELS[key] + '：' + (SUPPORT_STATES[item.status] || item.status) + '。' + item.summary));
    }
    return ul;
  })()]));

  card(el('h2', null, '来源与缺口'), (() => {
    const frag = document.createDocumentFragment();
    if (obj.issues && obj.issues.length) {
      const grouped = {};
      for (const issue of obj.issues) grouped[issue.reason] = (grouped[issue.reason] || 0) + 1;
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const reason of Object.keys(grouped)) ul.appendChild(el('li', null, '缺口：' + reason + '（' + grouped[reason] + ' 处）'));
      frag.appendChild(el('p', null, '缺口说明（始终可见，不折叠）：'));
      frag.appendChild(ul);
    } else {
      frag.appendChild(el('p', null, '无已记录缺口（不代表证明完整覆盖）。'));
    }
    const sourcesDetails = el('details', 'evidence-inner');
    sourcesDetails.appendChild(el('summary', null, '来源文件列表（' + obj.source_files.length + ' 个；仅展示路径，不自动读取）'));
    const sources = document.createElement('ul');
    sources.className = 'notes';
    for (const path of obj.source_files) {
      const li = el('li');
      li.appendChild(el('span', 'path', path));
      sources.appendChild(li);
    }
    sourcesDetails.appendChild(sources);
    frag.appendChild(sourcesDetails);
    return frag;
  })());

  const loaded = el('p', 'hint-line', footerText);
  report.appendChild(loaded);
}
