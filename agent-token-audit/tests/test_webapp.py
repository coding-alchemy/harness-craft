"""Web entry contracts over the local HTTP and guard seams; synthetic sources live outside the repo."""
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


if __name__ == '__main__':
    unittest.main()
