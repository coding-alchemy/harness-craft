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
  if (rate.value !== null && (typeof rate.value !== 'number' || !(rate.value >= 0 && rate.value <= 1))) {
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
  const pct = (rate.value * 100);
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
function metricCell(tableCell, value, state) {
  const info = cellInt(value, state);
  tableCell.textContent = info.text;
  if (info.unknown) tableCell.classList.add('unknown');
  if (info.partial) { tableCell.classList.add('partial'); tableCell.appendChild(el('span', 'mark', '')); }
  return tableCell;
}
function addRow(tbody, name, aggregate, emphasize) {
  const tr = document.createElement('tr');
  if (emphasize) tr.style.fontWeight = '600';
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
    frag.appendChild(table);
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
    nodes = [el('h2', null, '调用明细'), toggle, host];

    locateRecordsByKeys = keys => {
      if (!keys.length) return;
      locatedKeys = keys.slice();
      if (host.hidden) { host.hidden = false; toggle.textContent = '收起调用明细'; }
      drawRecordsTable();
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
      const bar = el('p', 'hint-line', '');
      const table = document.createElement('table');
      table.className = 'records-table';
      const headRow = document.createElement('tr');
      ['操作', '分组', '模型', '代理/会话', '轮次', '时间', '输入', '输出', '缓存读取', '调用数', '性质'].forEach(h => headRow.appendChild(el('th', null, h)));
      const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
      const tbody = document.createElement('tbody'); table.appendChild(tbody);
      const records = located ? obj.records.filter(r => locatedKeys.includes(r.key)) : obj.records;
      for (const record of records) {
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
      }
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
      host.appendChild(table);
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
      const table = document.createElement('table');
      table.className = 'timeline-table';
      const headRow = document.createElement('tr');
      ['会话', '轮次/区间', '生命周期', '状态（来源所读/截止点）', '原生轮次耗时', '记录数', '输入', '总量', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
      const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
      const tbody = document.createElement('tbody'); table.appendChild(tbody);
      const spanLabels = { in_range: '范围内', extends_before: '起点早于下界（范围外上下文）', extends_after: '终点晚于截止点（范围外上下文）',
                           extends_both: '跨出筛选范围（范围外上下文）', conflict: '起止冲突', unknown: '时间未知', interval: '累计区间' };
      const cutoffLabels = { ended_before_cutoff: '截止点前已结束', ended_after_cutoff: '截止点后才结束',
                             not_confirmed_ended_at_cutoff: '截至该边界未确认结束', unknown_at_cutoff: '截止点状态未知' };
      for (const row of obj.explanation.turns) {
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
      }
      table.appendChild(tbody);
      frag.appendChild(table);
      if (!obj.explanation.turns.length) {
        frag.appendChild(el('p', 'unavailable', '本报告未保存轮次时间线行（旧报告或范围内无轮次证据）。'));
      }
      frag.appendChild(el('p', 'hint-line', '时间行“定位记录”只改变明细可见集合；范围、合计、分母与截止点不变，且不读取来源。'));
  }
  return frag;
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
    note.style.fontSize = '.85rem';
    const wrap = document.createDocumentFragment();
    wrap.appendChild(table);
    wrap.appendChild(note);
    return wrap;
  })());

  const localizationCard = (() => {
    const nodes = [el('h2', null, '定位证据')];
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
  card(...localizationCard);

  const supportCard = (() => {
    const nodes = [el('h2', null, '内部来源支持')];
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
  card(...supportCard);

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
          group.style.cursor = 'pointer';
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
    tableHost.appendChild(table);
    if (visible.length !== rows.length) {
      tableHost.appendChild(el('p', 'hint-line', '已按筛选隐藏 ' + (rows.length - visible.length) + ' 行；原范围、截止点、合计与占比分母保持不变。'));
    }
  }

  function percentText(value, denominator, presetRate) {
    const rate = presetRate !== undefined ? presetRate : Number(value * 10000n / denominator) / 10000;
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
    const sources = document.createElement('ul');
    sources.className = 'notes';
    for (const path of obj.source_files) {
      const li = el('li', null, '来源（仅展示路径，不自动读取）：');
      li.appendChild(el('span', 'path', path));
      sources.appendChild(li);
    }
    frag.appendChild(sources);
    if (obj.issues && obj.issues.length) {
      const grouped = {};
      for (const issue of obj.issues) grouped[issue.reason] = (grouped[issue.reason] || 0) + 1;
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const reason of Object.keys(grouped)) ul.appendChild(el('li', null, '缺口：' + reason + '（' + grouped[reason] + ' 处）'));
      frag.appendChild(el('p', null, '缺口说明：'));
      frag.appendChild(ul);
    } else {
      frag.appendChild(el('p', null, '无已记录缺口（不代表证明完整覆盖）。'));
    }
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
    card(el('h2', null, '独立证据（不并入小计）'), ul);
  }
  let locateRecordsByKeys = null;
  const recordsDetail = buildRecordsDetail(obj);
  if (recordsDetail) {
    card(...recordsDetail.nodes);
    locateRecordsByKeys = recordsDetail.locate;
    viewLocateHandler = recordsDetail.locate;
    viewClearHandler = recordsDetail.clear;
  }
  if (obj.explanation && Array.isArray(obj.explanation.turns)) {
    card(el('h2', null, '轮次时间线与已有耗时'), buildTimelineCard(obj, locateRecordsByKeys));
  }

  if (obj.explanation && (Array.isArray(obj.explanation.internal) && obj.explanation.internal.length
      || Array.isArray(obj.explanation.relations) && obj.explanation.relations.length
      || Array.isArray(obj.explanation.excluded) && obj.explanation.excluded.length)) {
    card(el('h2', null, '内部分布、后代关系与未计量证据'), buildInternalRelationsCard(obj, locateRecordsByKeys));
  }

  const loaded = el('p', null, footerText);
  loaded.style.fontSize = '.82rem';
  loaded.style.color = '#6b7280';
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

  card(el('h2', null, '整体范围与状态'), el('span', 'status-tag status-' + obj.status, STATES[obj.status] || obj.status), (() => {
    const dl = document.createElement('dl');
    dl.className = 'meta-grid';
    const add = (term, value) => {
      dl.appendChild(el('dt', null, term));
      const dd = el('dd');
      if (value instanceof Node) dd.appendChild(value); else dd.textContent = value === null || value === undefined ? '未指定' : value;
      dl.appendChild(dd);
    };
    add('Harness', obj.harness);
    add('会话集合', scope.sessions.length + ' 个（' + scope.sessions.slice(0, 5).map(s => short(s, 16)).join('、')
      + (scope.sessions.length > 5 ? ' …' : '') + '）');
    add('时间下界', scope.from || '未指定');
    add('截止点', scope.to + '（来源：' + scope.cutoff_source + '）');
    add('显示时区', scope.tz);
    add('代理策略', scope.main_only ? '仅主代理常规调用' : '含可靠归属的后代与内部调用');
    add('实际读取时间', obj.read_at);
    add('覆盖说明', obj.coverage);
    return dl;
  })());

  card(el('h2', null, '总览（与 CLI 同值）'), (() => {
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
    note.style.fontSize = '.85rem';
    const wrap = document.createDocumentFragment();
    wrap.appendChild(table);
    wrap.appendChild(note);
    return wrap;
  })());

  const trendSection = (() => {
    const nodes = [el('h2', null, '按日趋势（日范围＝原范围与本地日交集）')];
    const wrap = el('div');
    const metrics = [['input', '输入'], ['output', '输出'], ['cache_read', '缓存读取'], ['total', '总量']];
    const metricField = document.createElement('fieldset');
    metricField.appendChild(el('legend', null, '指标'));
    for (const [key, label] of metrics) {
      const l = el('label', null);
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = sectionId + ':trend-metric'; radio.value = key;
      radio.checked = key === 'total'; radio.id = sectionId + '-trend-' + key;
      l.appendChild(radio); l.appendChild(document.createTextNode(label));
      metricField.appendChild(l);
    }
    wrap.appendChild(metricField);
    const chartHost = el('div'); chartHost.id = sectionId + '-trend-chart-host'; chartHost.className = 'chart-host';
    wrap.appendChild(chartHost);
    nodes.push(wrap);
    return { nodes, render };
    function render() {
      const metricKey = document.querySelector('input[name="' + sectionId + ':trend-metric"]:checked').value;
      const metricLabel = { input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' }[metricKey];
      chartHost.textContent = '';
      const days = obj.days || [];
      const unbucketed = obj.unbucketed || { records: 0 };
      chartHost.appendChild(el('p', 'hint-line', '当前指标：' + metricLabel + '；共 ' + days.length + ' 天'
        + (unbucketed.records ? '；另有 ' + unbucketed.records.toString() + ' 条无法归桶（见下）' : '') + '。'));
      if (!days.length) {
        chartHost.appendChild(el('p', 'unavailable', '无可归桶的日期数据；未知不画零，缺口见“来源与缺口”。'));
        return;
      }
      const anyKnown = days.some(d => d.metrics[metricKey].value !== null);
      if (!anyKnown) {
        chartHost.appendChild(el('p', 'unavailable', '图表不可用：该指标无任何已记录数值。'));
        return;
      }
      const barHeight = 24, labelWidth = 110, valueWidth = 200, gap = 5;
      const width = Math.min(920, chartHost.clientWidth || 920);
      const valueMax = days.reduce((max, d) => d.metrics[metricKey].value > max ? d.metrics[metricKey].value : max, 0n);
      const trackWidth = Math.max(120, width - labelWidth - valueWidth - 16);
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', String(width));
      svg.setAttribute('height', String(days.length * (barHeight + gap) + 4));
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', '按日' + metricLabel + '条形图');
      days.forEach((day, i) => {
        const y = i * (barHeight + gap) + 2;
        const metric = day.metrics[metricKey];
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        if (onDayClick) {
          group.style.cursor = 'pointer';
          group.addEventListener('click', () => onDayClick(day));
        }
        const labelNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        labelNode.setAttribute('x', String(labelWidth - 6)); labelNode.setAttribute('y', String(y + 16));
        labelNode.setAttribute('text-anchor', 'end'); labelNode.setAttribute('class', 'bar-label');
        labelNode.textContent = day.date;
        group.appendChild(labelNode);
        const track = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        track.setAttribute('x', String(labelWidth)); track.setAttribute('y', String(y));
        track.setAttribute('width', String(trackWidth)); track.setAttribute('height', String(barHeight));
        track.setAttribute('class', 'bar-track');
        group.appendChild(track);
        if (metric.value !== null) {
          const scaled = valueMax === 0n ? 0 : Number(metric.value * 10000n / valueMax) / 10000;
          const fill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          fill.setAttribute('x', String(labelWidth)); fill.setAttribute('y', String(y));
          fill.setAttribute('width', String(Math.round(scaled * trackWidth))); fill.setAttribute('height', String(barHeight));
          fill.setAttribute('class', 'bar-fill' + (metric.state !== 'known' ? ' partial' : ''));
          group.appendChild(fill);
        }
        const valueNode = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        valueNode.setAttribute('x', String(labelWidth + trackWidth + 8)); valueNode.setAttribute('y', String(y + 16));
        valueNode.setAttribute('class', 'bar-value');
        valueNode.textContent = metric.value === null ? '未知（无数值条）'
          : metric.value.toLocaleString('en-US') + (metric.state !== 'known' ? '（部分）' : '');
        group.appendChild(valueNode);
        svg.appendChild(group);
      });
      chartHost.appendChild(svg);
      if (onDayClick) chartHost.appendChild(el('p', 'hint-line', '点选日期条形查看当日模型/会话分布（只切换视图，不重新读取来源）。'));
    }
  })();
  card(...trendSection.nodes);
  document.querySelectorAll('input[name="' + sectionId + ':trend-metric"]').forEach(radio => {
    radio.addEventListener('change', () => trendSection.render());
  });
  trendSection.render();

  card((() => {
    const unbucketed = obj.unbucketed || { records: 0 };
    if (!unbucketed.records) return el('p', null, '');
    const m = unbucketed.metrics || {};
    const known = ['input', 'output', 'cache_read', 'total'].filter(k => m[k] && m[k].value !== null)
      .map(k => ({ input: '输入', output: '输出', cache_read: '缓存读取', total: '总量' })[k]
        + ' ' + m[k].value.toLocaleString('en-US') + (m[k].state !== 'known' ? '（部分）' : ''));
    const p = el('p', null, '无法归桶：' + unbucketed.records.toString() + ' 条（已计入总览、未计入任何一天；'
      + (unbucketed.reasons || []).join('；') + '）。' + (known.length ? '已记录：' + known.join('、') + '。' : '无可记录量。'));
    p.className = 'notes';
    return p;
  })());

  const rankingSection = (() => {
    const nodes = [el('h2', null, '模型 / 会话排行（同一结果的独立视图，不加入合计；未知不归零；按所选指标降序）')];
    const metrics = [['input', '输入'], ['output', '输出'], ['cache_read', '缓存读取'], ['total', '总量']];
    const metricField = document.createElement('fieldset');
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
        frag.appendChild(el('h3', null, title + '（按' + metricLabel + '降序）'));
        if (!view.rows.length) {
          frag.appendChild(el('p', 'unavailable', '无可排行行。'));
          return frag;
        }
        const t = document.createElement('table');
        const headRow = document.createElement('tr');
        ['行', '输入', '输出', '缓存读取', '缓存命中率', '总量', '调用数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
        const thead = document.createElement('thead'); thead.appendChild(headRow); t.appendChild(thead);
        const tbody = document.createElement('tbody'); t.appendChild(tbody);
        // Bind each rendered row to its own saved identity at draw time; the sorted
        // order never re-indexes into the unsorted view rows.
        for (const row of byMetric(view.rows)) {
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
        }
        t.appendChild(tbody);
        frag.appendChild(t);
        return frag;
      };
      host.appendChild(table('模型排行', obj.rankings.model));
      host.appendChild(el('p', 'hint-line', '会话行为该会话自身记录的小计；单会话报告默认含可靠归属后代，口径不同。'));
      host.appendChild(table('会话排行', obj.rankings.session));
    }
  })();
  card(...rankingSection.nodes);
  document.querySelectorAll('input[name="' + sectionId + ':rank-metric"]').forEach(radio => {
    radio.addEventListener('change', () => rankingSection.render());
  });
  rankingSection.render();

  const ovRecords = buildRecordsDetail(obj);
  if (ovRecords) {
    card(...ovRecords.nodes);
    overviewLocate = ovRecords.locate;
    if (typeof state !== 'undefined' && state.overview && state.overview.report === obj) state.overview.locate = overviewLocate;
    rankingSection.render();  // rewire ranking locate buttons
  }
  if (obj.explanation && Array.isArray(obj.explanation.turns)) {
    card(el('h2', null, '整体轮次时间线与按会话耗时'), buildTimelineCard(obj, overviewLocate));
  }
  if (obj.explanation && ((Array.isArray(obj.explanation.internal) && obj.explanation.internal.length)
      || (Array.isArray(obj.explanation.relations) && obj.explanation.relations.length)
      || (Array.isArray(obj.explanation.excluded) && obj.explanation.excluded.length))) {
    card(el('h2', null, '内部分布、后代关系与未计量证据'), buildInternalRelationsCard(obj, overviewLocate));
  }

  if (Array.isArray(obj.session_index) && obj.session_index.length) {
    card(el('h2', null, '会话索引（范围内会话的白名单元数据）'), (() => {
      const table = document.createElement('table');
      const headRow = document.createElement('tr');
      ['会话', '开始', '最近轮次结束', '轮次数', 'usage 记录', '已识别调用', '关系'].forEach(h => headRow.appendChild(el('th', null, h)));
      const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
      const tbody = document.createElement('tbody'); table.appendChild(tbody);
      for (const item of obj.session_index) {
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
      }
      table.appendChild(tbody);
      return table;
    })());
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
    card(el('h2', null, '独立证据（不并入小计）'), ul);
  }

  card(el('h2', null, '定位证据'), (() => {
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
  })());

  card(el('h2', null, '内部来源支持'), (() => {
    if (!obj.internal_support) return el('p', null, '报告未保存内部来源支持说明。');
    const ul = document.createElement('ul');
    ul.className = 'notes';
    for (const key of Object.keys(SUPPORT_LABELS)) {
      const item = obj.internal_support[key];
      ul.appendChild(el('li', null, SUPPORT_LABELS[key] + '：' + (SUPPORT_STATES[item.status] || item.status) + '。' + item.summary));
    }
    return ul;
  })());

  card(el('h2', null, '来源与缺口'), (() => {
    const frag = document.createDocumentFragment();
    const sources = document.createElement('ul');
    sources.className = 'notes';
    for (const path of obj.source_files) {
      const li = el('li', null, '来源（仅展示路径，不自动读取）：');
      li.appendChild(el('span', 'path', path));
      sources.appendChild(li);
    }
    frag.appendChild(sources);
    if (obj.issues && obj.issues.length) {
      const grouped = {};
      for (const issue of obj.issues) grouped[issue.reason] = (grouped[issue.reason] || 0) + 1;
      const ul = document.createElement('ul');
      ul.className = 'notes';
      for (const reason of Object.keys(grouped)) ul.appendChild(el('li', null, '缺口：' + reason + '（' + grouped[reason] + ' 处）'));
      frag.appendChild(el('p', null, '缺口说明：'));
      frag.appendChild(ul);
    } else {
      frag.appendChild(el('p', null, '无已记录缺口（不代表证明完整覆盖）。'));
    }
    return frag;
  })());

  const loaded = el('p', null, footerText);
  loaded.style.fontSize = '.82rem';
  loaded.style.color = '#6b7280';
  report.appendChild(loaded);
}
