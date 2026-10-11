"""Web entry contracts over the local HTTP and guard seams; synthetic sources live outside the repo."""
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ENTRY = Path(__file__).resolve().parents[1] / 'skills/agent-token-audit/scripts/audit.py'
SCRIPTS = ENTRY.parent
sys.path.insert(0, str(SCRIPTS))
from token_audit import webapp  # noqa: E402

T0 = 1788220800000          # 2026-09-01T00:00:00Z
T1 = 1788220860000          # 2026-09-01T00:01:00Z
END = '2026-09-02T00:00:00Z'


def make_database(path, totals=(100, 900, 300)):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
    CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
    query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
    duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
    CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
    db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.5', None, T0, 'interactive'))
    for i, total in enumerate(totals, 1):
        db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('s', f't{i}', T0, T1, 'completed', 1))
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (f'r{i}', f'msg{i}', 0, 's', f't{i}', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'completed', T0, T1, 60000, 0,
                    json.dumps({'inputTokens': total, 'outputTokens': 0, 'cacheReadTokens': 0, 'totalTokens': total})))
    db.commit()
    db.close()
    return path


def make_perf_database(path):
    """ZCode DB with first-token evidence columns; two calls with (start, first, completed)
    relative seconds (0,1,2) and (0,2,11), 100 output tokens each."""
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
    CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
    query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,first_token_at INTEGER,completed_at INTEGER,
    duration_ms INTEGER,time_to_first_token_ms INTEGER,tool_call_count INTEGER,retry_count INTEGER,raw_usage_json TEXT);
    CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
    db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.9', None, T0, 'interactive'))
    db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('s', 't1', T0, T0 + 120000, 'completed', 1))
    for rid, first_off, end_off in (('a', 1000, 2000), ('b', 2000, 11000)):
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid, 'msg-' + rid, 0, 's', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'completed', T0, T0 + first_off, T0 + end_off, end_off, first_off, 0, 0,
                    json.dumps({'inputTokens': 1000, 'outputTokens': 100, 'cacheReadTokens': 0, 'totalTokens': 1100})))
    db.commit()
    db.close()
    return path


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-web-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_guard_allows_only_the_declared_database_and_its_sidecars(self):
        allowed = self.root / 'allowed.sqlite'
        make_database(allowed)
        (self.root / 'allowed.sqlite-wal').write_bytes(b'')
        sibling = self.root / 'allowed.sqlite-extra.sqlite'
        make_database(sibling)
        guard = webapp.guard_for([{'kind': 'zcode_database', 'paths': [str(allowed)]}])
        guard(allowed)
        guard(self.root / 'allowed.sqlite-wal')
        guard(self.root / 'allowed.sqlite-shm')  # deterministic sidecar, may appear after start
        with self.assertRaises(ValueError) as extra:
            guard(sibling)
        self.assertIn('越界', str(extra.exception))
        outside = self.root / 'other.sqlite'
        make_database(outside)
        with self.assertRaises(ValueError):
            guard(outside)
        link = self.root / 'link.sqlite'
        link.symlink_to(sibling)
        with self.assertRaises(ValueError):
            guard(link)

    def test_guard_keeps_directory_containment_and_symlink_boundary(self):
        logs = self.root / 'logs'
        logs.mkdir()
        (logs / 'a.jsonl').write_text('{}\n')
        outside = self.root / 'outside.jsonl'
        outside.write_text('{}\n')
        guard = webapp.guard_for([{'kind': 'jsonl', 'paths': [str(logs)]}])
        guard(logs / 'a.jsonl')
        guard(logs / 'not-yet-listed.jsonl')
        with self.assertRaises(ValueError):
            guard(outside)
        escape = logs / 'escape.jsonl'
        escape.symlink_to(outside)
        with self.assertRaises(ValueError):
            guard(escape)


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-web-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self, descriptor):
        app = webapp.WebApp({'zcode': descriptor})
        webapp.Handler.app = app
        from http.server import ThreadingHTTPServer
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), webapp.Handler)
        self.server.daemon_threads = True
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/api/action'
        self.headers = {'Content-Type': 'application/json', 'X-Token-Audit-Token': app.credential}
        return app

    def post(self, payload):
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode('utf-8'),
                                         headers=self.headers, method='POST')
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode('utf-8'))

    def cli(self, *args):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, (0, 2, 3), proc.stderr)
        return proc

    def test_recompute_rejects_sibling_database_before_reading(self):
        allowed = make_database(self.root / 'allowed.sqlite')
        sibling = make_database(self.root / 'allowed.sqlite-extra.sqlite', totals=(700,))
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(sibling), '--session', 's',
                 '--turn', 't1', '--to', END, '--format', 'json', '--export', 'json', '--output', str(saved))
        self.assertIn('allowed.sqlite-extra.sqlite', json.loads(saved.read_text())['input']['paths'][0])
        before = sibling.read_bytes()
        self.start({'kind': 'zcode_database', 'paths': [str(allowed)]})
        status, data = self.post({'action': 'recompute', 'seq': 1, 'report_text': saved.read_text()})
        self.assertEqual(status, 400)
        self.assertIn('越界', data['error'])
        self.assertEqual(data['seq'], 1)
        self.assertEqual(sibling.read_bytes(), before)  # rejected before any read

    def test_update_clears_turns_and_lower_bound_only_when_explicit(self):
        database = make_database(self.root / 'db.sqlite')
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--turn', 't1', '--from', '2026-09-01T00:00:00Z', '--to', END,
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        base = {'action': 'recompute', 'seq': 1, 'update': True, 'to': END, 'report_text': saved.read_text()}

        status, data = self.post(dict(base, seq=2))  # only the cutoff supplied: saved scope kept
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['turns'], ['t1'])
        self.assertEqual(data['report']['scope']['from'], '2026-09-01T00:00:00Z')
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 100)

        status, data = self.post({**base, 'seq': 3, 'turns': None, 'from': None})  # explicit clears: whole session
        self.assertTrue(data['ok'], data)
        self.assertIsNone(data['report']['scope']['turns'])
        self.assertIsNone(data['report']['scope']['from'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1300)

        status, data = self.post({**base, 'seq': 4, 'turns': ['t1', 't2']})  # from omitted: kept
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['turns'], ['t1', 't2'])
        self.assertEqual(data['report']['scope']['from'], '2026-09-01T00:00:00Z')
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1000)

    def test_update_keeps_fractional_lower_bound_and_combined_turns_until_cleared(self):
        database = make_database(self.root / 'db.sqlite')
        db = sqlite3.connect(database)
        for i, ms in enumerate((15100, 45500, 60000), 1):
            db.execute('UPDATE model_usage SET started_at=?, completed_at=? WHERE id=?',
                       (T0 + ms, T0 + ms, f'r{i}'))
        db.commit()
        db.close()
        saved = self.root / 'saved.json'
        lower = '2026-09-01T00:00:30.123456Z'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--from', lower, '--turn', 't2', '--turn', 't3', '--to', END,
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        source_before, saved_before = database.read_bytes(), saved.read_bytes()
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        base = {'action': 'recompute', 'seq': 1, 'update': True,
                'to': '2026-09-03T00:00:00Z', 'report_text': saved.read_text()}
        _, data = self.post(base)
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['from'], lower)
        self.assertEqual(data['report']['scope']['turns'], ['t2', 't3'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1200)
        _, data = self.post({**base, 'from': None})
        self.assertIsNone(data['report']['scope']['from'])
        self.assertEqual(data['report']['scope']['turns'], ['t2', 't3'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1200)
        _, data = self.post({**base, 'from': None, 'turns': None})
        self.assertIsNone(data['report']['scope']['from'])
        self.assertIsNone(data['report']['scope']['turns'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1300)
        self.assertEqual(database.read_bytes(), source_before)
        self.assertEqual(saved.read_bytes(), saved_before)

    def test_use_context_rejects_an_explicit_session(self):
        database = make_database(self.root / 'db.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        webapp.Handler.app.context = {'harness': 'zcode', 'session': 's'}
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's', 'use_context': True})
        self.assertEqual(status, 400)
        self.assertIn('混用', data['error'])
        status, data = self.post({'action': 'report', 'seq': 2, 'harness': 'zcode', 'use_context': True})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['session'], 's')
        self.assertEqual(data['report']['localization']['session']['confirmed_by'], 'current_env')

    def test_overview_action_and_v3_saved_update(self):
        database = self.root / 'db.sqlite'
        make_database(database)
        db = sqlite3.connect(database)
        db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('x', '0.16.5', None, T0, 'interactive'))
        db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('x', 't1', T0, T1, 'completed', 1))
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('rx', 'msgx', 0, 'x', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'completed', T0, T1, 60000, 0,
                    json.dumps({'inputTokens': 700, 'outputTokens': 0, 'cacheReadTokens': 0, 'totalTokens': 700})))
        db.commit(); db.close()
        before = database.read_bytes()
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})

        status, data = self.post({'action': 'overview', 'seq': 1, 'harness': 'zcode', 'to': END, 'tz': '+08:00'})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['format_version'], 3)
        self.assertEqual(data['report']['scope']['sessions'], ['s', 'x'])
        self.assertEqual(data['report']['scope']['tz'], '+08:00')
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 2000)
        self.assertEqual(data['exit_code'], 2)

        status, data = self.post({'action': 'overview', 'seq': 2, 'harness': 'zcode', 'to': END,
                                  'sessions': ['s'], 'main_only': True})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['sessions'], ['s'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1300)

        status, data = self.post({'action': 'overview', 'seq': 3, 'harness': 'zcode', 'to': END, 'sessions': []})
        self.assertEqual(status, 400)
        status, data = self.post({'action': 'overview', 'seq': 4, 'harness': 'zcode', 'to': END, 'tz': 7})
        self.assertEqual(status, 400)

        saved = self.root / 'overall.json'
        self.cli('overview', '--harness', 'zcode', '--database', str(database), '--to', END,
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        _, data = self.post({'action': 'recompute', 'seq': 5, 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['sessions'], ['s', 'x'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 2000)
        _, data = self.post({'action': 'recompute', 'seq': 6, 'update': True, 'to': END,
                             'sessions': ['x'], 'tz': '+00:00', 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['sessions'], ['x'])
        self.assertEqual(data['report']['scope']['tz'], '+00:00')
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 700)
        status, data = self.post({'action': 'recompute', 'seq': 7, 'update': True, 'sessions': None,
                                  'report_text': saved.read_text()})
        self.assertEqual(status, 400)
        self.assertEqual(database.read_bytes(), before)

    def test_overview_duplicate_sessions_normalize_and_day_ranges_saved(self):
        database = make_database(self.root / 'db.sqlite', totals=(100, 900))
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        # Duplicate IDs in the explicit set normalize to one set for scope and localization.
        status, data = self.post({'action': 'overview', 'seq': 1, 'harness': 'zcode', 'to': END,
                                  'sessions': ['s', 's'], 'tz': '+08:00'})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['sessions'], ['s'])
        self.assertEqual(data['report']['localization']['sessions']['count'], 1)
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1000)
        # Day rows carry the kernel-computed intersection in the display timezone.
        day = data['report']['days'][0]
        self.assertEqual(day['date'], '2026-09-01')
        self.assertEqual(day['from'], '2026-09-01T00:00:00+08:00')
        self.assertEqual(day['to'], '2026-09-02T00:00:00+08:00')
        # A v3 update set with duplicates normalizes the same way; a single-session saved
        # report still rejects a session set outright.
        saved = self.root / 'overall.json'
        self.cli('overview', '--harness', 'zcode', '--database', str(database), '--to', END,
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        status, data = self.post({'action': 'recompute', 'seq': 2, 'update': True, 'to': END,
                                  'sessions': ['s', 's'], 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['sessions'], ['s'])
        v2 = self.root / 'v2.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--format', 'json', '--export', 'json', '--output', str(v2))
        status, data = self.post({'action': 'recompute', 'seq': 3, 'update': True, 'sessions': ['s'],
                                  'report_text': v2.read_text()})
        self.assertEqual(status, 400)


class PricingActions(Actions):
    def pricing_cfg(self, price='10'):
        return json.dumps({'schema_version': 1, 'revision': 'web-rev-1', 'aliases': [], 'rules': [{
            'id': 'glm', 'source': {'reference': '测试价目', 'version': '2026-09'},
            'provider': 'builtin:bigmodel-coding-plan', 'model': 'GLM-5.3',
            'effective_from': '2026-01-01T00:00:00Z', 'currency': 'TST',
            'input': {'kind': 'total_input', 'price_per_million': price},
            'output': {'kind': 'total_output', 'price_per_million': '20'}}]})

    def start_db(self):
        database = make_database(self.root / 'db.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        return database

    def test_report_with_pricing_text_saves_analysis_extension(self):
        self.start_db()
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's',
                                  'to': END, 'pricing_text': self.pricing_cfg()})
        self.assertTrue(data['ok'], data)
        cost = data['report']['analysis']['cost']
        # (100+900+300) × 10 / 1e6 输入；输出 0 × 20：逐记录精确金额与币种小计。
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '0.013')
        self.assertEqual(cost['summary']['priced'], 3)
        self.assertEqual(cost['records'][0]['components'][0]['amount'], '0.001')
        self.assertEqual(cost['config']['rules'][0]['id'], 'glm')
        # 同范围不带价格：原 token 结果不变；分析扩展仍保存性能区（无费用区）。
        status, data = self.post({'action': 'report', 'seq': 2, 'harness': 'zcode', 'session': 's', 'to': END})
        self.assertTrue(data['ok'], data)
        self.assertIn('performance', data['report']['analysis'])
        self.assertNotIn('cost', data['report']['analysis'])
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 1300)

    def test_pricing_text_rejected_on_other_actions_and_bad_content(self):
        database = self.start_db()
        before = database.read_bytes()
        for payload in ({'action': 'sessions', 'seq': 1, 'harness': 'zcode', 'pricing_text': self.pricing_cfg()},
                        {'action': 'report', 'seq': 2, 'harness': 'zcode', 'session': 's', 'pricing_text': None},
                        {'action': 'report', 'seq': 3, 'harness': 'zcode', 'session': 's', 'pricing_text': ''},
                        {'action': 'report', 'seq': 4, 'harness': 'zcode', 'session': 's', 'pricing_text': 'null'},
                        {'action': 'report', 'seq': 5, 'harness': 'zcode', 'session': 's', 'pricing_text': '{'},
                        {'action': 'report', 'seq': 6, 'harness': 'zcode', 'session': 's',
                         'pricing_text': '{"schema_version": 2, "revision": "x", "rules": []}'}):
            status, data = self.post(payload)
            self.assertEqual(status, 400, payload)
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--format', 'json', '--export', 'json', '--output', str(saved))
        status, data = self.post({'action': 'export', 'seq': 7, 'format': 'json',
                                  'report_text': saved.read_text(), 'pricing_text': self.pricing_cfg()})
        self.assertEqual(status, 400)
        self.assertEqual(database.read_bytes(), before)

    def test_recompute_reuses_saved_pricing_and_explicit_text_reprices(self):
        database = self.start_db()
        (self.root / 'pricing.json').write_text(self.pricing_cfg())
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--pricing', str(self.root / 'pricing.json'),
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        (self.root / 'pricing.json').write_text(self.pricing_cfg())  # 本地文件改价不影响保存报告
        status, data = self.post({'action': 'recompute', 'seq': 1, 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['analysis']['cost']['summary']['currencies']['TST']['amount'], '0.013')
        self.assertEqual(data['report']['analysis']['cost']['config']['revision'], 'web-rev-1')
        (self.root / 'pricing.json').unlink()
        status, data = self.post({'action': 'recompute', 'seq': 2, 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertIn('analysis', data['report'])  # 价格文件已删除，保存快照仍可重算
        status, data = self.post({'action': 'recompute', 'seq': 3, 'report_text': saved.read_text(),
                                  'pricing_text': self.pricing_cfg(price='20')})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['analysis']['cost']['summary']['currencies']['TST']['amount'], '0.026')

    def test_recompute_null_or_empty_pricing_rejected_not_treated_as_omitted(self):
        database = self.start_db()
        (self.root / 'pricing.json').write_text(self.pricing_cfg())
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--pricing', str(self.root / 'pricing.json'),
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        before = database.read_bytes()
        for bad in (None, '', '   ', 'null', '{', '{"schema_version": 2, "revision": "x", "rules": []}'):
            status, data = self.post({'action': 'recompute', 'seq': 1, 'report_text': saved.read_text(),
                                      'pricing_text': bad})
            self.assertEqual(status, 400, repr(bad))  # 非法配置不能视作省略
        # 省略 pricing_text 才是沿用保存快照；以上拒绝均未读取来源。
        status, data = self.post({'action': 'recompute', 'seq': 2, 'report_text': saved.read_text()})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['analysis']['cost']['summary']['currencies']['TST']['amount'], '0.013')
        self.assertEqual(database.read_bytes(), before)

    def test_update_with_explicit_pricing_reprices_without_scope_surprises(self):
        database = make_database(self.root / 'db.sqlite')
        (self.root / 'pricing.json').write_text(self.pricing_cfg())
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--turn', 't1', '--to', END, '--pricing', str(self.root / 'pricing.json'),
                 '--format', 'json', '--export', 'json', '--output', str(saved))
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        # 明确更新＋明确新价：范围按 update 合同扩展，新价只决定计价。
        status, data = self.post({'action': 'recompute', 'seq': 1, 'update': True, 'to': END,
                                  'turns': ['t1', 't2'], 'report_text': saved.read_text(),
                                  'pricing_text': self.pricing_cfg(price='20')})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['turns'], ['t1', 't2'])
        # 独立手算：(100+900)×20/1e6 输入 + 0 输出 = 0.02 TST。
        self.assertEqual(data['report']['analysis']['cost']['summary']['currencies']['TST']['amount'], '0.02')
        # 换价本身不暗示 update：不带 update 提交新价保持保存范围。
        status, data = self.post({'action': 'recompute', 'seq': 2, 'report_text': saved.read_text(),
                                  'pricing_text': self.pricing_cfg(price='20')})
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['report']['scope']['turns'], ['t1'])
        self.assertEqual(data['report']['analysis']['cost']['summary']['currencies']['TST']['amount'], '0.002')

    def test_export_csv_markdown_project_saved_analysis_and_match_cli(self):
        database = make_perf_database(self.root / 'perf.sqlite')
        pricing = self.root / 'pricing.json'
        pricing.write_text(self.pricing_cfg())
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's',
                                  'to': END, 'pricing_text': self.pricing_cfg()})
        self.assertTrue(data['ok'], data)
        report_text = json.dumps(data['report'])
        status, data = self.post({'action': 'export', 'seq': 2, 'format': 'csv', 'report_text': report_text})
        self.assertTrue(data['ok'], data)
        by_category = {}
        for row in csv.DictReader(io.StringIO(data['content'])):
            by_category.setdefault(row['category'], []).append(row)
        # 独立手算：输入 2000×10/1e6 = 0.02，输出 200×20/1e6 = 0.004，合计 0.024 TST。
        self.assertEqual(by_category['cost_summary'][0]['cost_amount_exact'], '0.024')
        self.assertEqual(by_category['cost_summary'][0]['cost_amount_display'], '0.02')
        config_detail = json.loads(by_category['cost_config'][0]['cost_detail'])
        self.assertEqual(config_detail['rules'][0]['id'], 'glm')
        metric_rows = {row['perf_metric']: row for row in by_category['perf_metric']}
        self.assertEqual((metric_rows['ttft']['perf_numerator'], metric_rows['ttft']['perf_denominator']),
                         ('3000', '2'))
        self.assertEqual(metric_rows['ttft']['perf_display_value'], '1500.00')
        self.assertEqual(metric_rows['throughput']['perf_display_value'], '20.00')
        ttft_detail = json.loads(metric_rows['ttft']['perf_detail'])
        self.assertIn('首个可观察', ttft_detail['definition'])
        # 与 CLI 同一结果同值（附加证据）：read_at 是各自读取时间，逐列排除后其余完全一致。
        cli_csv = self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                           '--to', END, '--pricing', str(pricing), '--format', 'csv').stdout

        def rows_without_read_at(text):
            return [{k: v for k, v in row.items() if k != 'read_at'}
                    for row in csv.DictReader(io.StringIO(text))]

        self.assertEqual(rows_without_read_at(data['content']), rows_without_read_at(cli_csv))
        status, data = self.post({'action': 'export', 'seq': 3, 'format': 'markdown', 'report_text': report_text})
        self.assertTrue(data['ok'], data)
        self.assertIn('费用估算', data['content'])
        self.assertIn('首 token 延迟', data['content'])
        status, data = self.post({'action': 'export', 'seq': 4, 'format': 'json', 'report_text': report_text})
        self.assertEqual(json.loads(data['content'])['analysis']['cost']['summary']['currencies']['TST']['amount'],
                         '0.024')

    def overview_report(self, *extra):
        payload = {'action': 'overview', 'seq': 1, 'harness': 'zcode', 'to': END, 'tz': '+00:00'}
        payload.update(*extra)
        status, data = self.post(payload)
        self.assertTrue(data['ok'], data)
        return data['report']

    def test_overview_pricing_saves_v3_projections(self):
        self.start_db()
        report = self.overview_report({'pricing_text': self.pricing_cfg()})
        cost = report['analysis']['cost']
        # 独立手算：输入 (100+900+300)×10/1e6 = 0.013 TST；输出全 0 ×20 = 0。
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '0.013')
        projections = cost['projections']
        models = projections['model']
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]['identity'], {'provider': 'builtin:bigmodel-coding-plan', 'model': 'GLM-5.3'})
        self.assertEqual(models[0]['currencies']['TST']['amount'], '0.013')
        self.assertEqual(len(models[0]['record_keys']), 3)
        sessions = projections['session']
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['session'], 's')
        self.assertEqual(sessions[0]['currencies']['TST']['amount'], '0.013')
        days = projections['day']
        self.assertEqual([d['date'] for d in days], ['2026-09-01'])
        self.assertEqual(days[0]['currencies']['TST']['amount'], '0.013')
        self.assertEqual(projections['unbucketed'], {'currencies': {}, 'record_keys': []})

    def test_drill_report_reuses_parent_saved_pricing(self):
        self.start_db()
        parent = json.dumps(self.overview_report({'pricing_text': self.pricing_cfg()}))
        day = json.loads(parent)['days'][0]
        # 下钻语义：携带父报告本身，服务用其保存的价格快照计价，不上传新价格文本。
        status, data = self.post({'action': 'report', 'seq': 2, 'harness': 'zcode', 'session': 's',
                                  'from': day['from'], 'to': day['to'], 'parent_report_text': parent})
        self.assertTrue(data['ok'], data)
        cost = data['report']['analysis']['cost']
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '0.013')
        self.assertEqual(cost['config']['revision'], 'web-rev-1')
        self.assertNotIn('projections', cost)  # v2 不携带整体投影
        status, data = self.post({'action': 'report', 'seq': 3, 'harness': 'zcode', 'session': 's',
                                  'parent_report_text': parent, 'pricing_text': self.pricing_cfg()})
        self.assertEqual(status, 400)  # 两个价格来源冲突
        status, data = self.post({'action': 'overview', 'seq': 4, 'harness': 'zcode', 'parent_report_text': parent})
        self.assertEqual(status, 400)  # 非会话下钻操作不接受父报告
        v2 = self.root / 'v2.json'
        self.cli('report', '--harness', 'zcode', '--database', str(self.root / 'db.sqlite'), '--session', 's',
                 '--to', END, '--format', 'json', '--export', 'json', '--output', str(v2))
        status, data = self.post({'action': 'report', 'seq': 5, 'harness': 'zcode', 'session': 's',
                                  'parent_report_text': v2.read_text()})
        self.assertEqual(status, 400)  # 父报告必须是 v3 整体报告
        tampered = json.loads(parent)
        tampered['analysis']['cost']['projections']['day'][0]['currencies']['TST']['amount'] = '999'
        status, data = self.post({'action': 'report', 'seq': 6, 'harness': 'zcode', 'session': 's',
                                  'parent_report_text': json.dumps(tampered)})
        self.assertEqual(status, 400)  # 篡改的父报告明确拒绝，不回源补正

    def test_drill_with_unpriced_parent_stays_unpriced(self):
        self.start_db()
        parent = json.dumps(self.overview_report())
        day = json.loads(parent)['days'][0]
        status, data = self.post({'action': 'report', 'seq': 2, 'harness': 'zcode', 'session': 's',
                                  'from': day['from'], 'to': day['to'], 'parent_report_text': parent})
        self.assertTrue(data['ok'], data)
        self.assertNotIn('cost', data['report']['analysis'])  # 未配置价格的父报告：下钻保持未定价，性能区仍在


class PerformanceActions(Actions):
    """Ticket 03: performance section over the HTTP action entry, no pricing needed."""

    def test_report_saves_performance_samples_without_pricing(self):
        database = make_perf_database(self.root / 'perf.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's', 'to': END})
        self.assertTrue(data['ok'], data)
        analysis = data['report']['analysis']
        self.assertNotIn('cost', analysis)  # 未配置价格也有性能区
        perf = analysis['performance']
        self.assertEqual(perf['source_kind'], 'zcode_database')
        ttft = perf['metrics']['ttft']
        self.assertEqual(ttft['support']['status'], 'supported')
        self.assertEqual([s['value'] for s in ttft['samples']], [1000, 2000])
        self.assertEqual((ttft['aggregate']['numerator'], ttft['aggregate']['denominator']), (3000, 2))
        throughput = perf['metrics']['throughput']
        self.assertEqual((throughput['aggregate']['numerator'], throughput['aggregate']['denominator']), (200, 10000))
        self.assertIn('完成事件处理开销', throughput['overhead'])
        self.assertEqual(data['report']['summary']['metrics']['output']['value'], 200)  # token 合计不变

    def test_old_schema_reports_checked_unavailable(self):
        database = make_database(self.root / 'db.sqlite')  # 旧结构无首 token 列
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's', 'to': END})
        self.assertTrue(data['ok'], data)
        metric = data['report']['analysis']['performance']['metrics']['ttft']
        self.assertEqual(metric['support']['status'], 'source_not_provided')
        self.assertIn('first_token_at', metric['support']['reason'])
        self.assertEqual(metric['samples'], [])

    def test_tampered_performance_extension_rejected(self):
        database = make_perf_database(self.root / 'perf.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--format', 'json', '--export', 'json', '--output', str(saved))
        base = json.loads(saved.read_text())

        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            status, resp = self.post({'action': 'recompute', 'seq': 9, 'report_text': json.dumps(data)})
            self.assertEqual(status, 400, name)

        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'][0].__setitem__('value', 999), 'conflict')
        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'][0].__setitem__('record_key', 'zcode-db:ghost'), 'dangling')
        reject(lambda d: d['analysis']['performance']['metrics']['throughput']['aggregate'].__setitem__('numerator', 201), 'aggregate')
        reject(lambda d: d['analysis']['performance']['metrics']['throughput'].__setitem__('overhead', None), 'overhead')
        reject(lambda d: d['analysis'].__setitem__('schema_version', 2), 'extversion')


def make_tool_database(path):
    """ZCode DB with tool_usage: native duration vs dispatch span, a verified zero and a failed run."""
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
    CREATE TABLE model_usage (id TEXT,logical_request_id INTEGER,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
    query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
    duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
    CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);
    CREATE TABLE tool_usage (id TEXT,session_id TEXT,turn_id TEXT,tool_call_id TEXT,tool_name TEXT,status TEXT,
    started_at INTEGER,completed_at INTEGER,duration_ms INTEGER);''')
    db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.9', None, T0, 'interactive'))
    db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('s', 't1', T0, T0 + 120000, 'completed', 1))
    db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               ('r1', 'msg1', 0, 's', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                'completed', T0, T0 + 60000, 60000, 0,
                json.dumps({'inputTokens': 100, 'outputTokens': 10, 'cacheReadTokens': 0, 'totalTokens': 110})))
    db.execute('INSERT INTO tool_usage VALUES (?,?,?,?,?,?,?,?,?)',
               ('usage_tool_s_call_a', 's', 't1', 'call_a', 'Bash', 'completed', T0, T0 + 103, 97))
    db.execute('INSERT INTO tool_usage VALUES (?,?,?,?,?,?,?,?,?)',
               ('usage_tool_s_call_b', 's', 't1', 'call_b', 'Read', 'error', T0 + 103, T0 + 153, 50))
    db.commit()
    db.close()
    return path


class ToolActions(Actions):
    """Ticket 04: tool-duration section over the HTTP action entry."""

    def test_report_saves_tool_duration_without_pricing(self):
        database = make_tool_database(self.root / 'db.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's', 'to': END})
        self.assertTrue(data['ok'], data)
        analysis = data['report']['analysis']
        self.assertNotIn('cost', analysis)  # 未配置价格也有工具耗时区
        metric = analysis['performance']['metrics']['tool_duration']
        self.assertEqual(metric['support']['status'], 'supported')
        aggregate = metric['aggregate']
        self.assertEqual((aggregate['candidates'], aggregate['valid']), (2, 2))
        self.assertEqual(aggregate['numerator'], 147000000)
        self.assertEqual(aggregate['no_token_record'], 2)
        samples = {s['key']: s for s in metric['samples']}
        self.assertEqual(samples['zcode-db-tool:s:call_a']['native_duration_ns'], 97000000)
        self.assertEqual(samples['zcode-db-tool:s:call_b']['status'], 'failed')
        self.assertEqual(aggregate['wall']['value'], 153000000)  # 调度跨度包络 0 → 153ms
        self.assertEqual(data['report']['summary']['metrics']['input']['value'], 100)  # token 合计不变

    def test_db_without_tool_usage_table_checked_unavailable(self):
        database = make_database(self.root / 'db.sqlite')  # 旧结构无 tool_usage 表
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        status, data = self.post({'action': 'report', 'seq': 1, 'harness': 'zcode', 'session': 's', 'to': END})
        self.assertTrue(data['ok'], data)
        metric = data['report']['analysis']['performance']['metrics']['tool_duration']
        self.assertEqual(metric['support']['status'], 'source_not_provided')
        self.assertIn('tool_usage', metric['support']['reason'])
        self.assertEqual(metric['samples'], [])
        self.assertEqual(metric['aggregate']['valid'], 0)

    def test_tampered_tool_extension_rejected(self):
        database = make_tool_database(self.root / 'db.sqlite')
        self.start({'kind': 'zcode_database', 'paths': [str(database)]})
        saved = self.root / 'saved.json'
        self.cli('report', '--harness', 'zcode', '--database', str(database), '--session', 's',
                 '--to', END, '--format', 'json', '--export', 'json', '--output', str(saved))
        base = json.loads(saved.read_text())

        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            status, resp = self.post({'action': 'recompute', 'seq': 9, 'report_text': json.dumps(data)})
            self.assertEqual(status, 400, name)

        tool = lambda d: d['analysis']['performance']['metrics']['tool_duration']
        reject(lambda d: tool(d)['samples'][0].__setitem__('value', 999), 'value')
        reject(lambda d: tool(d)['samples'][0].__setitem__('record_key', 'zcode-db:r1'), 'recordkey')
        reject(lambda d: tool(d)['aggregate'].__setitem__('numerator', 999), 'aggregate')
        reject(lambda d: tool(d)['aggregate']['wall'].__setitem__('state', 'unknown'), 'wall')
        reject(lambda d: tool(d)['projections']['category'][0].__setitem__('denominator', 9), 'category')
        # 03 前的两指标旧报告仍然合法（不补造工具区）：服务端校验通过，重算后新报告重新携带工具区
        del base['analysis']['performance']['metrics']['tool_duration']
        status, resp = self.post({'action': 'export', 'seq': 10, 'format': 'json', 'report_text': json.dumps(base)})
        self.assertTrue(resp['ok'], resp)
        self.assertNotIn('tool_duration', json.loads(resp['content'])['analysis']['performance']['metrics'])
        status, resp = self.post({'action': 'recompute', 'seq': 11, 'report_text': json.dumps(base)})
        self.assertTrue(resp['ok'], resp)
        self.assertIn('tool_duration', resp['report']['analysis']['performance']['metrics'])


if __name__ == '__main__':
    unittest.main()
