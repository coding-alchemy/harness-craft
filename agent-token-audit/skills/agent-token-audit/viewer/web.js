'use strict';
/* Local web UI behaviour: explicit actions only, one in-flight source operation per page. */
const TOKEN = (location.hash.match(/[#&]token=([^&]+)/) || [])[1] || null;
let seqCounter = 0;
let baselineVersion = 0;
// Selection epoch: bumped wherever the selection identity (harness/session) changes, so
// candidate listings whose response arrives after the selection moved on are dropped.
let selectionVersion = 0;
let inflight = false;
const state = { harness: null, session: null, selectedTurns: [], lastTurnIndex: -1, context: null,
                sessionsListing: [], sessionChecks: null, sessionsView: null, overview: null };

function $(id) { return document.getElementById(id); }
function setStatus(message, isError) {
  const node = $('status');
  node.textContent = message || '';
  node.classList.toggle('error', Boolean(isError));
}
function setBusy(busy) {
  for (const id of ('browse-sessions,browse-turns,browse-requests,run-report,clear-turns,run-overview').split(',')) {
    const needsSession = id !== 'browse-sessions' && id !== 'run-overview';
    const needsTurns = id === 'clear-turns' && state.selectedTurns.length === 0;
    $(id).disabled = busy || (needsSession && !state.session) || needsTurns;
  }
  for (const id of ('context-select,context-request-run').split(',')) {
    const node = $(id);
    if (!node.hidden) node.disabled = busy;
  }
}
function showFatal(message) {
  setStatus(message, true);
  $('browse-sessions').disabled = true;
  $('browse-turns').disabled = true;
  $('browse-requests').disabled = true;
  $('run-report').disabled = true;
  $('run-overview').disabled = true;
}

async function call(action, payload) {
  if (inflight) return { busy: true };
  if (!TOKEN) { showFatal('缺少启动凭据：请使用终端中显示的完整链接（含 #token=…）打开本页。'); return { fatal: true }; }
  inflight = true;
  setBusy(true);
  setStatus('正在' + ({ sessions: '浏览会话', turns: '浏览轮次', requests: '浏览请求候选', report: '统计', overview: '查询整体用量' }[action] || action) + '……');
  const id = ++seqCounter;
  const owner = baselineVersion;
  // Candidate listings belong to the selection identity; result actions carry their own
  // scope and stay governed by seq plus the file baseline version alone.
  const selection = (action === 'sessions' || action === 'turns' || action === 'requests') ? selectionVersion : null;
  const outdated = () => owner !== baselineVersion || (selection !== null && selection !== selectionVersion);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token-Audit-Token': TOKEN },
      body: JSON.stringify(Object.assign({ action: action, seq: id }, payload)),
      signal: controller.signal
    });
    if (outdated()) return { stale: true };
    if (response.status === 403) {
      showFatal('请求被拒绝（凭据缺失或不匹配）。服务重启后旧链接失效：请使用终端中显示的新链接重新打开本页。');
      return { fatal: true };
    }
    // Lossless parse keeps report integers as BigInt; native response.json() would lose precision.
    const data = LosslessJSON.parse(await response.text(), undefined, LosslessJSON.parseNumberAndBigInt);
    // BigInt never strictly equals a Number, so normalize echo fields before comparing.
    if (outdated() || (data.seq !== undefined && Number(data.seq) !== id)) return { stale: true };
    if (data.exit_code !== undefined) data.exit_code = Number(data.exit_code);
    return data;
  } catch (error) {
    if (outdated()) return { stale: true };
    const aborted = error && error.name === 'AbortError';
    return { ok: false, error: aborted ? '请求超时：本次结果未取得，可明确重试；已加载报告不受影响' : '服务不可达：' + (error && error.message ? error.message : String(error)) };
  } finally {
    clearTimeout(timeout);
    inflight = false;
    setBusy(false);
  }
}

function renderSessions(listing) {
  const host = $('sessions-table-host');
  host.textContent = '';
  const items = listing.sessions || [];
  state.sessionsListing = items;
  state.sessionChecks = Object.create(null);
  state.sessionsView = { filter: '', sort: 'last_end', page: 0 };
  const toolbar = el('div', 'sessions-toolbar');
  const filterLabel = el('label', null, '筛选：');
  const filterInput = document.createElement('input');
  filterInput.type = 'text';
  filterInput.placeholder = '按身份/时间包含匹配';
  filterInput.addEventListener('input', () => { state.sessionsView.filter = filterInput.value.trim().toLowerCase(); state.sessionsView.page = 0; drawSessionsTable(); });
  filterLabel.appendChild(filterInput);
  toolbar.appendChild(filterLabel);
  const sortLabel = el('label', null, '排序：');
  const sortGroup = el('span', 'sort-radios');
  const SORTS = [['last_end', '最近轮次结束（新→旧）'], ['start', '开始时间（新→旧）'],
                 ['usage', 'usage 记录数（多→少）'], ['calls', '已识别调用（多→少）'], ['id', '稳定身份']];
  for (const [value, text] of SORTS) {
    const radio = document.createElement('input');
    radio.type = 'radio'; radio.name = 'sessions-sort'; radio.value = value;
    radio.checked = value === 'last_end';
    radio.addEventListener('change', () => { state.sessionsView.sort = value; state.sessionsView.page = 0; drawSessionsTable(); });
    sortGroup.appendChild(radio);
    sortGroup.appendChild(document.createTextNode(text + ' '));
  }
  sortLabel.appendChild(sortGroup);
  toolbar.appendChild(sortLabel);
  const prevButton = el('button', null, '上一页');
  prevButton.type = 'button';
  prevButton.addEventListener('click', () => { if (state.sessionsView.page > 0) { state.sessionsView.page--; drawSessionsTable(); } });
  const nextButton = el('button', null, '下一页');
  nextButton.type = 'button';
  nextButton.addEventListener('click', () => { state.sessionsView.page++; drawSessionsTable(); });
  const pageInfo = el('span', 'hint-line', '');
  toolbar.appendChild(prevButton);
  toolbar.appendChild(nextButton);
  toolbar.appendChild(pageInfo);
  const checkedRun = el('button', null, '用所选会话集合查询整体');
  checkedRun.type = 'button';
  checkedRun.disabled = true;
  checkedRun.addEventListener('click', () => {
    const sessions = Object.keys(state.sessionChecks).filter(k => state.sessionChecks[k]).sort();
    if (!sessions.length) return;
    runOverviewQuery({ sessions });
  });
  toolbar.appendChild(checkedRun);
  const toolbarNote = el('p', 'hint-line', '筛选、排序与翻页只影响候选列表显示，不读取来源、不改变已生成结果；勾选集合可提交为整体查询的会话范围。');
  host.appendChild(toolbar);
  host.appendChild(toolbarNote);
  const tableHost = el('div');
  tableHost.id = 'sessions-table-body-host';
  host.appendChild(tableHost);
  drawSessionsTable();
  $('sessions-card').hidden = false;

  function drawSessionsTable() {
    const view = state.sessionsView;
    let rows = items.slice();
    if (view.filter) {
      rows = rows.filter(item => item.id.toLowerCase().includes(view.filter)
        || String(item.last_turn_end || '').toLowerCase().includes(view.filter)
        || String(item.start || '').toLowerCase().includes(view.filter));
    }
    const keyOf = {
      last_end: item => item.last_turn_end || '',
      start: item => item.start || '',
      usage: item => -((item.evidence || {}).usage_records || 0),
      calls: item => -((item.evidence || {}).known_calls || 0),
      id: item => item.id,
    }[view.sort];
    const numeric = view.sort === 'usage' || view.sort === 'calls';
    rows.sort((a, b) => {
      const ka = keyOf(a), kb = keyOf(b);
      if (ka === kb) return 0;
      // Lossless parsing carries BigInt; only < / > comparisons are type-safe here.
      if (numeric) return ka < kb ? -1 : 1;
      return ka < kb ? 1 : -1;
    });
    const pageSize = 20;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (view.page >= pages) view.page = pages - 1;
    const pageRows = rows.slice(view.page * pageSize, (view.page + 1) * pageSize);
    pageInfo.textContent = '第 ' + (view.page + 1) + '/' + pages + ' 页；候选 ' + rows.length + '/' + items.length + ' 个';
    prevButton.disabled = view.page === 0;
    nextButton.disabled = view.page >= pages - 1;

    tableHost.textContent = '';
    const table = document.createElement('table');
    table.className = 'sessions-table';
    const head = document.createElement('tr');
    ['计入整体', '稳定身份', '轮次数', '最近轮次结束', '版本', '关系', '有 usage 记录', '已识别调用', '缺口'].forEach(h => head.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(head); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    const listed = new Set(pageRows.map(s => s.id));
    const gaps = Object.create(null);
    const notes = [];
    const unmatched = [];
    for (const issue of listing.issues || []) {
      if (!issue.session) { notes.push('来源缺口：' + issue.reason); continue; }
      if (!listed.has(issue.session)) { unmatched.push('会话 ' + short(issue.session, 12) + '：' + issue.reason); continue; }
      (gaps[issue.session] = gaps[issue.session] || []).push(issue.reason);
    }
    for (const item of pageRows) {
      const tr = document.createElement('tr');
      if (state.session === item.id) tr.classList.add('selected');
      const checkCell = tr.appendChild(document.createElement('td'));
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = Boolean(state.sessionChecks[item.id]);
      checkbox.addEventListener('click', event => event.stopPropagation());
      checkbox.addEventListener('change', () => {
        state.sessionChecks[item.id] = checkbox.checked;
        const count = Object.keys(state.sessionChecks).filter(k => state.sessionChecks[k]).length;
        checkedRun.disabled = count === 0;
        checkedRun.textContent = count ? '用所选 ' + count + ' 个会话查询整体' : '用所选会话集合查询整体';
      });
      checkCell.appendChild(checkbox);
      tr.appendChild(el('td', 'path', short(item.id, 42)));
      tr.appendChild(el('td', null, String(item.turn_count)));
      tr.appendChild(el('td', null, short(item.last_turn_end, 26)));
      tr.appendChild(el('td', null, short(item.version, 14)));
      tr.appendChild(el('td', null, item.parent ? '后代（父 ' + short(item.parent, 12) + '）' : item.forked_from ? '分叉自 ' + short(item.forked_from, 12) : '独立会话'));
      tr.appendChild(el('td', null, String((item.evidence || {}).usage_records)));
      tr.appendChild(el('td', null, String((item.evidence || {}).known_calls)));
      tr.appendChild(el('td', null, [...new Set(gaps[item.id] || [])].join('；') || '—'));
      tr.addEventListener('click', () => {
        for (const row of tbody.children) row.classList.remove('selected');
        tr.classList.add('selected');
        selectSession(item.id, '已选择会话 ' + short(item.id, 24) + '；可浏览轮次/请求候选或发起统计。');
      });
      tbody.appendChild(tr);
    }
    tableHost.appendChild(table);
    if (notes.length || unmatched.length) {
      const ul = document.createElement('ul'); ul.className = 'notes';
      for (const note of notes.slice(0, 5)) ul.appendChild(el('li', null, note));
      for (const note of unmatched) ul.appendChild(el('li', null, note));
      tableHost.appendChild(ul);
    }
  }
}

function selectSession(sessionId, message) {
  state.pendingContext = false;
  if (state.session !== sessionId) {
    selectionVersion++;
    state.session = sessionId;
    state.selectedTurns = [];
    state.lastTurnIndex = -1;
    $('turns-card').hidden = true;
    $('requests-card').hidden = true;
    $('turns-table-host').textContent = '';
    $('requests-table-host').textContent = '';
  }
  $('run-card').hidden = false;
  setBusy(false);
  refreshScopeSummary();
  setStatus(message);
}

function renderTurns(listing, keepSelection) {
  const host = $('turns-table-host');
  host.textContent = '';
  const table = document.createElement('table');
  table.className = 'turns-table';
  const head = document.createElement('tr');
  ['已选', '稳定轮次 ID', '显示序号', '状态', '开始', '结束', '身份来源'].forEach(h => head.appendChild(el('th', null, h)));
  const thead = document.createElement('thead'); thead.appendChild(head); table.appendChild(thead);
  const tbody = document.createElement('tbody'); table.appendChild(tbody);
  if (!keepSelection) {
    state.selectedTurns = [];
    state.lastTurnIndex = -1;
  }
  const order = listing.map(turn => turn.id);
  state.selectedTurns = state.selectedTurns.filter(id => order.includes(id));
  listing.forEach((turn, index) => {
    const tr = document.createElement('tr');
    if (state.selectedTurns.includes(turn.id)) tr.classList.add('selected');
    tr.appendChild(el('td', null, state.selectedTurns.includes(turn.id) ? '✓' : ''));
    tr.appendChild(el('td', 'path', short(turn.id, 42)));
    tr.appendChild(el('td', null, turn.display_number === undefined || turn.display_number === null ? '未知' : String(turn.display_number)));
    tr.appendChild(el('td', null, STATES[turn.status] || turn.status || '未知'));
    tr.appendChild(el('td', null, short(turn.start, 26)));
    tr.appendChild(el('td', null, short(turn.end, 26)));
    tr.appendChild(el('td', null, (turn.identity_sources || []).join('、') || '未知'));
    tr.addEventListener('click', event => {
      if (event.shiftKey && state.lastTurnIndex >= 0) {
        // Expand the displayed span into a full stable-ID set; no boundary guessing beyond the list.
        const from = Math.min(state.lastTurnIndex, index), to = Math.max(state.lastTurnIndex, index);
        for (let i = from; i <= to; i++) {
          if (!state.selectedTurns.includes(order[i])) state.selectedTurns.push(order[i]);
        }
      } else {
        const position = state.selectedTurns.indexOf(turn.id);
        if (position >= 0) state.selectedTurns.splice(position, 1);
        else state.selectedTurns.push(turn.id);
        state.lastTurnIndex = index;
      }
      renderTurns(listing, true);
      refreshScopeSummary();
      setStatus('已选 ' + state.selectedTurns.length + ' 个轮次（按列表顺序提交完整集合）；留空则统计整个会话。');
    });
    tbody.appendChild(tr);
  });
  host.appendChild(table);
  $('turns-card').hidden = false;
}

function renderRequests(listing) {
  const host = $('requests-table-host');
  host.textContent = '';
  const table = document.createElement('table');
  const head = document.createElement('tr');
  ['请求 ID', '时间', '时间依据', '分类', '操作'].forEach(h => head.appendChild(el('th', null, h)));
  const thead = document.createElement('thead'); thead.appendChild(head); table.appendChild(thead);
  const tbody = document.createElement('tbody'); table.appendChild(tbody);
  const items = listing || [];
  for (const item of items) {
    const tr = document.createElement('tr');
    tr.appendChild(el('td', 'path', short(item.id, 36)));
    tr.appendChild(el('td', null, short(item.time, 26)));
    tr.appendChild(el('td', null, item.time_source || '未知'));
    tr.appendChild(el('td', null, item.classification || '未知'));
    const cell = tr.appendChild(document.createElement('td'));
    const button = el('button', null, '用此起点统计');
    button.type = 'button';
    button.addEventListener('click', () => runReport({ request_id: item.id }));
    cell.appendChild(button);
    tbody.appendChild(tr);
  }
  host.appendChild(table);
  if (!items.length) host.appendChild(el('p', 'hint-line', '该会话无可用的用户请求候选；请使用显式时间或截至现在。'));
  $('requests-card').hidden = false;
}

function timeValue(prefix) {
  const local = $(prefix + '-local').value;
  const offset = $(prefix + '-tz').value.trim();
  if (!local) return null;  // An empty date means the bound is not used, regardless of the pre-filled timezone.
  if (!/^[+-]\d{2}:\d{2}$/.test(offset)) throw new Error('时区必须是 ±HH:MM 形式；浏览器不会把无时区时间当作 UTC');
  return local + offset;
}

function cutoffValue() {
  return timeValue('cutoff');
}

function refreshScopeSummary() {
  const summary = $('scope-summary');
  $('clear-turns').hidden = state.selectedTurns.length === 0;
  if (!state.session) { summary.textContent = ''; return; }
  const parts = ['会话 ' + short(state.session, 24)];
  parts.push(state.selectedTurns.length ? '轮次集合（' + state.selectedTurns.length + ' 个，按列表顺序）' : '轮次：整个会话（turns=null）');
  try {
    const from = timeValue('from');
    const to = timeValue('cutoff');
    if (from) parts.push('时间下界 ' + from + '（含）');
    if (to) parts.push('截止点 ' + to + '（不含）');
    else parts.push('截止点：截至本次网页请求（服务入口固定）');
    summary.textContent = '将提交的范围：' + parts.join('；');
  } catch (error) {
    summary.textContent = error.message;
  }
}

async function runReport(overrides) {
  if (!state.session) { setStatus('请先选择会话。', true); return; }
  let payload;
  try {
    payload = { harness: state.harness, session: state.session,
                turns: state.selectedTurns.length ? state.selectedTurns : null,
                from: timeValue('from'), to: timeValue('cutoff'),
                main_only: document.querySelector('input[name=agents]:checked').value === 'main' };
  } catch (error) {
    setStatus(error.message, true);
    return;
  }
  Object.assign(payload, overrides || {});
  if (payload.use_context) payload.session = null;  // The startup association is the identity; an explicit session alongside it is rejected as混用.
  if (payload.to && payload.request_id) { setStatus('请求起点与显式截止点不能同时使用', true); return; }
  const data = await call('report', payload);
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { const message = data.error || '统计失败'; setStatus(message, true); failFresh(message); return; }
  showFreshResult(data.report, '网页统计结果（明确读取当前来源生成；format_version=2）。实际采用范围与截止点见“报告范围与状态”；已加载基准（如有）不受影响。');
  setStatus('统计完成；状态：' + (STATES[data.report.status] || data.report.status)
    + (data.exit_code === 2 ? '（有效部分结果，缺口如实显示）' : data.exit_code === 3 ? '（不可统计，缺口见报告）' : ''));
}

function resetSelection() {
  selectionVersion++;
  state.pendingContext = false;
  state.session = null;
  state.selectedTurns = [];
  state.lastTurnIndex = -1;
  state.sessionsListing = [];
  state.sessionChecks = Object.create(null);
  state.sessionsView = { filter: '', sort: 'last_end', page: 0 };
  $('sessions-card').hidden = true;
  $('turns-card').hidden = true;
  $('requests-card').hidden = true;
  $('run-card').hidden = true;
  $('sessions-table-host').textContent = '';
  $('turns-table-host').textContent = '';
  $('requests-table-host').textContent = '';
}

function applyContext(context) {
  if (!context || !context.session) return;
  // A late startup context is a selection change too: reuse the same cleanup so neither an
  // in-flight nor an already-rendered candidate list from another harness survives it.
  if (state.harness !== context.harness) resetSelection();
  state.context = context;
  const radio = document.querySelector('input[name=harness][value=' + context.harness + ']');
  if (radio) radio.checked = true;
  state.harness = context.harness;
  const note = $('context-note');
  note.textContent = '启动链提供：' + context.harness + ' 会话 ' + context.session
    + (context.request_id ? '；转交本次统计请求 ' + context.request_id + '（尚未执行）' : '。');
  $('context-request-run').hidden = !context.request_id;
  $('context-card').hidden = false;
}

async function loadCapabilities() {
  if (!TOKEN) { showFatal('缺少启动凭据：请使用终端中显示的完整链接（含 #token=…）打开本页。'); return; }
  try {
    const response = await fetch('/api/capabilities', { headers: { 'X-Token-Audit-Token': TOKEN } });
    if (response.status === 403) { showFatal('凭据不匹配：服务可能已重启，请使用终端中显示的新链接重新打开本页。'); return; }
    const data = await response.json();
    const info = $('source-info');
    info.textContent = '';
    for (const harness of ['codex', 'zcode']) {
      const descriptor = (data.sources || {})[harness];
      if (!descriptor) continue;
      info.appendChild(el('dt', null, harness));
      const dd = el('dd');
      dd.appendChild(el('span', 'path', (descriptor.kind === 'zcode_database' ? '数据库（含相邻 log/rollout、WAL/SHM 受限只读）：' : 'JSONL 来源：') + descriptor.paths.join('；')));
      info.appendChild(dd);
    }
    applyContext(data.context);
    setStatus('页面已就绪。选择 Harness 后点击“浏览会话”。');
  } catch (error) {
    showFatal('无法连接本地服务：' + (error && error.message ? error.message : String(error)));
  }
}

document.querySelectorAll('input[name=harness]').forEach(radio => {
  radio.addEventListener('change', () => {
    state.harness = radio.value;
    resetSelection();
    refreshScopeSummary();
    setStatus('已选择 ' + radio.value + '；点击“浏览会话”列出真实候选（该动作读取来源）。');
  });
});

$('browse-sessions').addEventListener('click', async () => {
  if (!state.harness) { setStatus('请先选择 Harness。', true); return; }
  resetSelection();
  const data = await call('sessions', { harness: state.harness });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '浏览会话失败', true); return; }
  renderSessions(data.listing);
  setStatus('已列出 ' + (data.listing.sessions || []).length + ' 个会话候选；点击行选择。');
});

$('browse-turns').addEventListener('click', async () => {
  if (!state.session) { setStatus('请先在会话列表中选择一个会话。', true); return; }
  const data = await call('turns', { harness: state.harness, session: state.session });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '浏览轮次失败', true); return; }
  renderTurns(data.listing, false);
  $('run-card').hidden = false;
  refreshScopeSummary();
  setStatus('已列出该会话的稳定轮次；点击行选择统计范围。');
});

$('browse-requests').addEventListener('click', async () => {
  if (!state.session) { setStatus('请先选择会话。', true); return; }
  const data = await call('requests', { harness: state.harness, session: state.session });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '浏览请求候选失败', true); return; }
  renderRequests(data.listing);
  setStatus('请求候选按身份/时间列出；点击“用此起点统计”以该请求自身时间执行。');
});

$('clear-turns').addEventListener('click', () => {
  state.selectedTurns = [];
  state.lastTurnIndex = -1;
  const rows = [...document.querySelectorAll('#turns-table-host tbody tr')];
  rows.forEach(row => { row.classList.remove('selected'); row.firstChild.textContent = ''; });
  refreshScopeSummary();
  setStatus('已清除轮次选择；将统计整个会话。');
});

function selectContext() {
  const context = state.context;
  if (!context) return;
  if (state.harness !== context.harness) resetSelection();
  state.harness = context.harness;
  document.querySelector('input[name=harness][value=' + context.harness + ']').checked = true;
  selectSession(context.session, '已选择本次启动关联会话；发起统计时验证身份与来源唯一匹配。');
  state.pendingContext = true;
}

$('context-select').addEventListener('click', selectContext);

$('context-request-run').addEventListener('click', async () => {
  const context = state.context;
  if (!context || !context.request_id) return;
  selectContext();
  const data = await call('report', { harness: context.harness, session: null, use_context: true,
                                      request_id: context.request_id,
                                      main_only: document.querySelector('input[name=agents]:checked').value === 'main' });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '转交请求统计失败', true); failFresh(data.error || '转交请求统计失败'); return; }
  showFreshResult(data.report, '转交请求统计结果（明确读取当前来源生成；format_version=2）。截止点为该请求自身的创建/入队时间；实际范围见“报告范围与状态”。');
  setStatus('转交请求统计完成；状态：' + (STATES[data.report.status] || data.report.status));
});

function refreshCutoffPreview() { refreshScopeSummary(); }

for (const id of ('from-local,from-tz,cutoff-local,cutoff-tz').split(',')) {
  $(id).addEventListener('input', refreshCutoffPreview);
}

function defaultOffset() {
  const minutes = -new Date().getTimezoneOffset();
  const sign = minutes >= 0 ? '+' : '-';
  const abs = Math.abs(minutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return sign + hh + ':' + mm;
}
$('cutoff-tz').value = defaultOffset();
$('from-tz').value = defaultOffset();
$('update-to-tz').value = defaultOffset();
$('ov-from-tz').value = defaultOffset();
$('ov-to-tz').value = defaultOffset();
$('ov-tz').value = defaultOffset();

function refreshOverviewSummary() {
  const parts = [];
  try {
    const from = timeValue('ov-from');
    const to = timeValue('ov-to');
    if (from) parts.push('时间下界 ' + from + '（含）');
    if (to) parts.push('截止点 ' + to + '（不含）');
    else parts.push('截止点：截至本次网页请求（服务入口固定）');
  } catch (error) {
    $('ov-scope-summary').textContent = error.message;
    return;
  }
  parts.push('显示时区 ' + ($('ov-tz').value.trim() || defaultOffset()));
  parts.push('会话集合：来源全部会话（可在后续版本按列表缩小）');
  parts.push('代理：' + (document.querySelector('input[name=ov-agents]:checked').value === 'main' ? '仅主代理常规调用' : '默认完整范围'));
  $('ov-scope-summary').textContent = '将提交的整体范围：' + parts.join('；');
}
for (const id of ('ov-from-local,ov-from-tz,ov-to-local,ov-to-tz,ov-tz').split(',')) {
  $(id).addEventListener('input', refreshOverviewSummary);
}
document.querySelectorAll('input[name=ov-agents]').forEach(radio => {
  radio.addEventListener('change', refreshOverviewSummary);
});
refreshOverviewSummary();

function showOverviewResult(reportObj) {
  const host = $('overview-result');
  host.hidden = false;
  try {
    validateReport(reportObj);
    renderOverviewReport(reportObj, '整体用量结果（format_version=3）。日趋势、模型/会话排行与总览来自同一次读取；点选日期只切换视图，不重新读取来源。', 'overview-result', onOverviewDayClick);
    refreshOverviewDrill();
    const actions = $('overview-actions');
    actions.hidden = false;
    $('overview-export').onclick = () => exportReport(losslessText(reportObj), '整体结果');
  } catch (error) {
    host.textContent = '';
    const card = el('section', 'card error');
    card.appendChild(el('h2', null, '整体结果未取得'));
    card.appendChild(el('p', null, '返回的报告未通过合同校验：' + (error && error.message ? error.message : String(error))));
    host.appendChild(card);
  }
}

function runOverviewQuery(overrides) {
  if (!state.harness) { setStatus('请先选择 Harness。', true); return Promise.resolve(); }
  let payload;
  try {
    payload = { harness: state.harness,
                from: timeValue('ov-from'), to: timeValue('ov-to'),
                tz: $('ov-tz').value.trim() || null,
                main_only: document.querySelector('input[name=ov-agents]:checked').value === 'main' };
  } catch (error) {
    setStatus(error.message, true);
    return Promise.resolve();
  }
  Object.assign(payload, overrides || {});
  return call('overview', payload).then(data => {
    if (data.busy || data.fatal || data.stale) return;
    if (!data.ok) { setStatus(data.error || '整体查询失败', true); return; }
    state.overview = { report: data.report, drill: { date: null } };
    showOverviewResult(data.report);
    setStatus('整体查询完成；状态：' + (STATES[data.report.status] || data.report.status)
      + (data.exit_code === 2 ? '（有效部分结果，缺口如实显示）' : data.exit_code === 3 ? '（不可统计，缺口见报告）' : ''));
  });
}

function onOverviewDayClick(day) {
  if (!state.overview) return;
  state.overview.drill = { date: day.date, session: null };
  refreshOverviewDrill();
  setStatus('已切换到日期 ' + day.date + ' 的分布视图（同一份结果，无来源读取）；返回请点击面包屑。');
}

function refreshOverviewDrill() {
  const old = $('overview-drill');
  if (old) old.remove();
  const report = state.overview && state.overview.report;
  if (!report) return;
  const drill = state.overview.drill || { date: null };
  const panel = el('section', 'card');
  panel.id = 'overview-drill';
  const crumb = (label, handler) => {
    const button = el('button', null, label);
    button.type = 'button';
    button.addEventListener('click', handler);
    return button;
  };
  const head = el('h2', null, '下钻：');
  panel.appendChild(head);
  panel.appendChild(crumb('整体总览', () => { state.overview.drill = { date: null }; refreshOverviewDrill(); }));
  if (drill.date) {
    panel.appendChild(document.createTextNode(' / '));
    panel.appendChild(crumb('日期 ' + drill.date, () => { state.overview.drill = { date: drill.date, session: null }; refreshOverviewDrill(); }));
  }
  panel.appendChild(el('p', 'hint-line', '返回不会丢弃整体结果、查询条件与固定截止点；每层显示实际范围。'));
  if (!drill.date) {
    panel.appendChild(el('p', null, '点选上方趋势图中的日期条形，查看该日（原范围与该日交集）的模型/会话分布。'));
    $('overview-result').appendChild(panel);
    return;
  }
  const day = (report.days || []).find(d => d.date === drill.date);
  if (!day) {
    panel.appendChild(el('p', 'unavailable', '该日无已归桶数据（未知不画零）。'));
    $('overview-result').appendChild(panel);
    return;
  }
  panel.appendChild(el('p', 'notes', '日期 ' + day.date + '：会话 ' + day.sessions + ' 个；调用数 '
    + (day.call_count === null ? '未知' : day.call_count.toString()) + '；日范围＝原范围与该日交集：'
    + (day.from && day.to ? day.from + ' ~ ' + day.to : '未保存')));
  const distTable = (title, rows, onRow) => {
    panel.appendChild(el('h3', null, title));
    if (!rows.length) { panel.appendChild(el('p', 'unavailable', '无可显示行。')); return; }
    const table = document.createElement('table');
    const headRow = document.createElement('tr');
    ['行', '输入', '输出', '缓存读取', '缓存命中率', '总量', '调用数', '操作'].forEach(h => headRow.appendChild(el('th', null, h)));
    const thead = document.createElement('thead'); thead.appendChild(headRow); table.appendChild(thead);
    const tbody = document.createElement('tbody'); table.appendChild(tbody);
    const ovLocate = state.overview && state.overview.locate;
    for (const row of rows) {
      const tr = document.createElement('tr');
      const labelCell = el('td', onRow ? 'expandable' : null, row.label);
      if (onRow) {
        labelCell.title = '点击进入该会话当日统计（既有单会话流程）';
        labelCell.addEventListener('click', () => onRow(row));
      }
      tr.appendChild(labelCell);
      for (const key of ['input', 'output', 'cache_read']) {
        metricCell(tr.appendChild(document.createElement('td')), row.metrics[key].value, row.metrics[key].state);
      }
      const rateCell = tr.appendChild(document.createElement('td'));
      const rate = percent(row.cache_hit_rate);
      rateCell.textContent = rate.text;
      if (rate.unknown) rateCell.classList.add('unknown');
      if (rate.partial) rateCell.classList.add('partial');
      metricCell(tr.appendChild(document.createElement('td')), row.metrics.total.value, row.metrics.total.state);
      tr.appendChild(el('td', null, row.call_count === null ? '未知' : row.call_count.toString()));
      const op = tr.appendChild(document.createElement('td'));
      if (row.record_keys && row.record_keys.length && ovLocate) {
        const btn = el('button', null, '定位');
        btn.type = 'button';
        btn.title = '定位该行对应的计量明细（只改变明细可见集合）';
        btn.addEventListener('click', () => ovLocate(row.record_keys));
        op.appendChild(btn);
      } else {
        op.appendChild(el('span', 'hint-line', '旧报告未保存行级引用'));
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    panel.appendChild(table);
  };
  distTable('当日模型分布', day.by_model || [], null);
  panel.appendChild(el('p', 'hint-line', '会话行为该会话自身记录的已记录小计；点击进入的既有单会话报告默认含可靠归属后代，口径不同，结果页会同时显示实际范围。'));
  distTable('当日会话分布', day.by_session || [], row => enterSessionFromDrill(row.id, drill.date));
  $('overview-result').appendChild(panel);
}

function enterSessionFromDrill(sessionId, date) {
  const report = state.overview && state.overview.report;
  if (!report) return;
  if (state.harness !== report.harness) {
    setStatus('当前 Harness 与该整体结果不同；请先切回 ' + report.harness + ' 再进入会话。', true);
    return;
  }
  const day = (report.days || []).find(d => d.date === date);
  if (!day || !day.from || !day.to) {
    setStatus('该日没有已保存的交集范围，无法进入会话统计。', true);
    return;
  }
  // The day row carries the kernel-computed intersection of the original scope with this
  // local day (both bounds keep their own precision and timezone spelling); backfilling the
  // existing time controls keeps later turn/task statistics on the same range until edited.
  selectSession(sessionId, '已从整体结果进入会话 ' + short(sessionId, 20) + '（日期 ' + date
    + '，范围 ' + day.from + ' ~ ' + day.to + '）；将按既有单会话流程统计。');
  applyBoundControls('from', day.from);
  applyBoundControls('cutoff', day.to);
  refreshScopeSummary();
  runReport({ session: sessionId, from: day.from, to: day.to });
}

function applyBoundControls(prefix, iso) {
  // Split an ISO bound into the local wall time and offset the existing controls use. 'Z'
  // spells UTC as +00:00 for the ±HH:MM timezone field; each bound keeps its own offset.
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:\d{2})$/.exec(iso);
  if (!match) return;
  $(prefix + '-local').value = match[1];
  $(prefix + '-tz').value = match[2] === 'Z' ? '+00:00' : match[2];
}

$('run-overview').addEventListener('click', () => {
  runOverviewQuery();
});

$('run-report').addEventListener('click', () => {
  const payload = {};
  if (state.pendingContext) { payload.use_context = true; state.pendingContext = false; }
  runReport(payload);
});

setBusy(false);
loadCapabilities();

/* ---- 04：保存报告复用、更新与导出 ---- */
const baseline = { text: null, obj: null, name: null };

function losslessText(obj) {
  // Lossless round-trip keeps report integers exact for export submission.
  return LosslessJSON.stringify(obj) + '\n';
}

function failFresh(message) {
  // A failed recompute/update must not leave a previous result looking like this attempt's success.
  const fresh = document.getElementById('fresh-report');
  fresh.hidden = false;
  fresh.textContent = '';
  const card = el('section', 'card error');
  card.appendChild(el('h2', null, '新结果未取得'));
  card.appendChild(el('p', null, message));
  fresh.appendChild(card);
  document.getElementById('fresh-actions').hidden = true;
}

function showFreshResult(reportObj, footerText) {
  document.getElementById('empty').hidden = true;  // The initial placeholder must not claim nothing has run.
  try {
    const version = validateReport(reportObj);
    if (version === 3) renderOverviewReport(reportObj, footerText, 'fresh-report');
    else renderReport(reportObj, version, footerText, 'fresh-report');
    const actions = $('fresh-actions');
    actions.hidden = false;
    const button = $('fresh-export');
    // Assignment (not addEventListener) so repeated results replace the handler.
    button.onclick = () => exportReport(losslessText(reportObj), '新结果');
  } catch (error) {
    failFresh('返回的报告未通过合同校验：' + (error && error.message ? error.message : String(error)));
  }
}

function clearBaseline() {
  // A failed load leaves no loaded report at all: previous baseline, fresh result and
  // every operation binding on them are cleared so nothing can masquerade or stay operable.
  baseline.text = null;
  baseline.obj = null;
  baseline.name = null;
  $('saved-name').textContent = '';
  $('baseline-card').hidden = true;
  $('update-form').hidden = true;
  const report = $('report');
  report.textContent = '';
  report.hidden = true;
  const fresh = $('fresh-report');
  fresh.textContent = '';
  fresh.hidden = true;
  $('fresh-actions').hidden = true;
  $('fresh-export').onclick = null;
}

function resetBaselineFailure(message) {
  clearBaseline();
  setStatus('加载失败：' + message + '。本次报告状态已清空（含此前基准与新结果），请重新选择文件。', true);
}

function describeScope(scope) {
  const parts = [];
  if (scope.kind === 'overall') {
    parts.push('会话集合 ' + (scope.sessions || []).length + ' 个');
  } else {
    parts.push('会话 ' + short(scope.session, 20));
    parts.push(scope.turns === null ? '整个会话' : '轮次集合（' + scope.turns.length + ' 个）');
  }
  parts.push('时间下界 ' + (scope.from || '未指定'));
  parts.push('截止点 ' + scope.to + '（来源：' + scope.cutoff_source + '）');
  if (scope.tz) parts.push('显示时区 ' + scope.tz);
  parts.push(scope.main_only ? '仅主代理' : '默认完整范围');
  return parts.join('；');
}

function scopeDiff(oldScope, newScope) {
  const lines = [];
  const overall = oldScope.kind === 'overall';
  if (overall) {
    const added = (newScope.sessions || []).filter(s => !(oldScope.sessions || []).includes(s));
    const removed = (oldScope.sessions || []).filter(s => !(newScope.sessions || []).includes(s));
    if (added.length || removed.length) {
      lines.push('会话集合：新增 ' + added.length + (added.length ? '（' + added.map(s => short(s, 10)).join('、') + '）' : '')
        + '；移除 ' + removed.length + (removed.length ? '（' + removed.map(s => short(s, 10)).join('、') + '）' : '') + '（完整替换，非追加）');
    } else {
      lines.push('会话集合：保持不变');
    }
  } else if (oldScope.turns === null && newScope.turns === null) lines.push('轮次：保持整个会话');
  else if (oldScope.turns === null) lines.push('轮次：整个会话 → 显式集合（' + newScope.turns.length + ' 个，属替换非追加）');
  else if (newScope.turns === null) lines.push('轮次：集合 → 整个会话（在新截止点纳入符合范围的新调用）');
  else {
    const added = newScope.turns.filter(t => !oldScope.turns.includes(t));
    const removed = oldScope.turns.filter(t => !newScope.turns.includes(t));
    lines.push('轮次：新增 ' + added.length + (added.length ? '（' + added.map(t => short(t, 10)).join('、') + '）' : '')
      + '；移除 ' + removed.length + (removed.length ? '（' + removed.map(t => short(t, 10)).join('、') + '）' : ''));
  }
  if (oldScope.from !== newScope.from) lines.push('时间下界：' + (oldScope.from || '未指定') + ' → ' + (newScope.from || '未指定'));
  if (oldScope.to !== newScope.to) lines.push('截止点：' + oldScope.to + ' → ' + newScope.to);
  if (oldScope.tz !== undefined && newScope.tz !== undefined && oldScope.tz !== newScope.tz) {
    lines.push('显示时区：' + oldScope.tz + ' → ' + newScope.tz);
  }
  if (oldScope.main_only !== newScope.main_only) lines.push('代理策略：' + (oldScope.main_only ? '仅主代理→默认完整' : '默认完整→仅主代理'));
  return lines.join('；');
}

function updateFormValues() {
  const tz = defaultOffset();
  const pick = (localId, tzId) => {
    const local = $(localId).value;
    const offset = $(tzId).value.trim() || tz;
    return local ? local + offset : null;
  };
  const idList = id => {
    const raw = $(id).value.split(/[\n,，;；]+/).map(s => s.trim()).filter(Boolean);
    return raw.length ? raw : null;
  };
  return {
    from: $('update-from').value.trim() || null,
    to: pick('update-to', 'update-to-tz'),
    turns: idList('update-turns'),
    sessions: idList('update-sessions'),
    tz: $('update-tz').value.trim() || null
  };
}

function refreshUpdateDiff() {
  const diff = $('update-diff');
  if (!baseline.obj) { diff.textContent = ''; return; }
  const oldScope = baseline.obj.scope;
  const values = updateFormValues();
  const agents = document.querySelector('input[name=update-agents]:checked').value;
  const overall = oldScope.kind === 'overall';
  // The form is pre-filled with the saved constraints, so the submitted field IS the new
  // scope: a cleared textarea/field means the whole session / no lower bound (explicit
  // null), an untouched one carries the same value as the saved constraint.
  const newScope = {
    session: oldScope.session,
    sessions: overall ? (values.sessions || oldScope.sessions) : oldScope.sessions,
    kind: oldScope.kind,
    turns: overall ? null : values.turns,
    from: values.from,
    to: values.to,
    tz: overall ? (values.tz || oldScope.tz) : oldScope.tz,
    cutoff_source: values.to !== null ? 'explicit' : 'web_request_start',
    main_only: agents === 'keep' ? oldScope.main_only : agents === 'main'
  };
  diff.textContent = '原范围：' + describeScope(oldScope)
    + '\n新范围：' + describeScope(newScope)
    + '\n差异：' + scopeDiff(oldScope, newScope)
    + (values.to ? '' : '（截止点留空，将更新到本次网页请求入口时间）');
  diff.style.whiteSpace = 'pre-wrap';
}

function loadSavedFile(file) {
  if (!file) return;
  // Selecting a replacement (even an invalid file) invalidates every earlier response.
  const owner = ++baselineVersion;
  clearBaseline();
  setStatus('正在加载所选保存报告（未读取来源）……');
  const reader = new FileReader();
  reader.onerror = () => {
    if (owner === baselineVersion) resetBaselineFailure('无法读取所选文件');
  };
  reader.onload = () => {
    if (owner !== baselineVersion) return;
    try {
      const obj = LosslessJSON.parse(String(reader.result), undefined, LosslessJSON.parseNumberAndBigInt);
      const version = validateReport(obj);
      baseline.text = String(reader.result);
      baseline.obj = obj;
      baseline.name = file.name;
      $('saved-name').textContent = file.name;
      const footer = '保存结果（基准）：' + file.name + '（format_version=' + version + '）。浏览器本地展示，不读取来源。';
      if (version === 3) {
        document.getElementById('empty').hidden = true;
        renderOverviewReport(obj, footer, 'report');
      } else {
        renderReport(obj, version, footer, 'report');
      }
      $('baseline-scope').textContent = '保存范围：' + describeScope(obj.scope) + '；保存读取时间 ' + obj.read_at;
      $('baseline-card').hidden = false;
      $('update-form').hidden = true;
      setStatus('已加载保存报告（未读取来源）。可原范围重算、编辑新范围更新或导出。');
    } catch (error) {
      resetBaselineFailure(error && error.message ? error.message : String(error));
    }
  };
  reader.readAsText(file);
}

$('saved-file').addEventListener('change', event => {
  loadSavedFile(event.target.files[0]);
  event.target.value = '';
});

$('recompute-run').addEventListener('click', async () => {
  if (!baseline.text) return;
  const data = await call('recompute', { report_text: baseline.text });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '原范围重算失败', true); failFresh(data.error || '原范围重算失败'); return; }
  showFreshResult(data.report, '原范围重算结果（format_version=' + data.report.format_version + '）。保持保存的范围、代理策略与截止点，读取当前来源生成；基准仍可对照。');
  setStatus('原范围重算完成；状态：' + (STATES[data.report.status] || data.report.status)
    + (data.exit_code === 2 ? '（有效部分结果）' : data.exit_code === 3 ? '（不可统计）' : ''));
});

$('update-toggle').addEventListener('click', () => {
  const form = $('update-form');
  form.hidden = !form.hidden;
  if (!form.hidden) {
    const scope = baseline.obj.scope;
    const overall = scope.kind === 'overall';
    // Text preserves every saved second/fraction and its timezone spelling.
    $('update-from').value = scope.from || '';
    $('update-turns').value = scope.turns === null || scope.turns === undefined ? '' : scope.turns.join('\n');
    $('update-sessions').value = overall ? (scope.sessions || []).join('\n') : '';
    $('update-sessions-block').hidden = !overall;
    $('update-turns-block').hidden = overall;
    $('update-tz-block').hidden = !overall;
    $('update-tz').value = overall ? (scope.tz || '') : '';
    refreshUpdateDiff();
    setStatus('更新表单已展开：先核对原范围与新范围差异，提交完整集合后才读取来源。');
  }
});

for (const id of ('update-from,update-to,update-to-tz,update-turns,update-sessions,update-tz').split(',')) {
  $(id).addEventListener('input', refreshUpdateDiff);
}
document.querySelectorAll('input[name=update-agents]').forEach(radio => {
  radio.addEventListener('change', refreshUpdateDiff);
});

$('update-run').addEventListener('click', async () => {
  if (!baseline.text) return;
  const values = updateFormValues();
  const agents = document.querySelector('input[name=update-agents]:checked').value;
  const overall = baseline.obj.scope.kind === 'overall';
  const payload = { report_text: baseline.text, update: true, to: values.to };
  if (overall) {
    if (values.sessions) payload.sessions = values.sessions;
    if (values.tz) payload.tz = values.tz;
  } else {
    payload.turns = values.turns;
  }
  // Omit an untouched lower bound; explicit null remains the web CLEAR contract.
  if (values.from !== baseline.obj.scope.from) payload.from = values.from;
  if (agents !== 'keep') payload.main_only = agents === 'main';
  const data = await call('recompute', payload);
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '更新失败', true); failFresh(data.error || '更新失败'); return; }
  showFreshResult(data.report, '明确更新结果（format_version=' + data.report.format_version + '）。实际采用范围与截止点见上方；与保存基准的差异已在提交前显示。');
  setStatus('明确更新完成；状态：' + (STATES[data.report.status] || data.report.status));
});

async function exportReport(reportText, sourceLabel) {
  const choice = window.prompt('导出格式：输入 json、csv 或 markdown（内容由本地服务按同一结果生成，浏览器决定保存位置）。', 'json');
  if (!choice) return;
  const fmt = choice.trim().toLowerCase();
  const data = await call('export', { report_text: reportText, format: fmt });
  if (data.busy || data.fatal || data.stale) return;
  if (!data.ok) { setStatus(data.error || '导出失败', true); return; }
  const blob = new Blob([data.content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'token-audit-export.' + (fmt === 'markdown' ? 'md' : fmt);
  link.click();
  URL.revokeObjectURL(url);
  setStatus('已生成 ' + fmt + ' 导出（format_version=' + data.format_version + '）并交由浏览器下载：' + sourceLabel + '。服务未读来源、未写报告文件。');
}

$('baseline-export').addEventListener('click', () => {
  if (baseline.text) exportReport(baseline.text, baseline.name || '保存基准');
});
