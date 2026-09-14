"""External CLI contracts; synthetic log inputs and outputs live outside the repo."""
import json
import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / 'skills/agent-token-audit/scripts/audit.py'
T0 = '2026-09-01T00:00:00Z'
T1 = '2026-09-01T00:01:00Z'
END = '2026-09-02T00:00:00Z'


def meta(sid='s'):
    return {'type': 'session_meta', 'timestamp': T0, 'payload': {'id': sid, 'timestamp': T0, 'source': 'cli', 'cli_version': '0.153.4'}}


def usage(rid='r1', turn='t1', sid='s', inp=100, cache=90, output=10, time=T1):
    values = {'input_tokens': inp, 'output_tokens': output, 'total_tokens': inp + output,
              'reasoning_output_tokens': 3, 'cache_write_input_tokens': 0}
    if cache is not None:
        values['cached_input_tokens'] = cache
    return {'type': 'token_usage_record', 'timestamp': time, 'payload': {
        'response_id': rid, 'thread_id': sid, 'turn_id': turn, 'root_turn_id': turn, 'usage': values}}


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'rollout.jsonl'

    def write(self, rows):
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))

    def run_cli(self, *args, codes=(0, 2, 3)):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def report(self, *args):
        proc = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END, '--format', 'json', *args)
        return json.loads(proc.stdout)

    def test_weighted_cache_and_duplicates_readonly(self):
        one = usage(); two = usage('r2', inp=300, cache=0)
        counter = {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 400}}}}
        self.write([meta(), one, two, one, counter])
        before = self.log.read_bytes()
        result = self.report('--source', str(self.log))
        metrics = result['summary']['metrics']
        self.assertEqual([metrics[k]['value'] for k in ('input','cache_read','non_cache_read','output','total')], [400,90,310,20,420])
        self.assertEqual(result['summary']['cache_hit_rate']['value'], .225)
        self.assertEqual(result['summary']['call_count'], 2)
        self.assertEqual(before, self.log.read_bytes())
        self.assertEqual(list(self.root.iterdir()), [self.log])

    def test_missing_field_preserves_known_subset_and_zero(self):
        self.write([meta(), usage(), usage('r2', inp=300, cache=None)])
        result = self.report()
        self.assertEqual(result['summary']['cache_hit_rate']['value'], .9)
        self.assertEqual(result['summary']['cache_hit_rate']['state'], 'partial')
        self.assertEqual(result['summary']['metrics']['cache_read']['state'], 'partial')
        self.assertEqual(result['records'][0]['metrics']['cache_write']['value'], 0)
        self.assertEqual(result['records'][0]['metrics']['cache_write']['state'], 'unknown')

    def test_zero_denominator(self):
        self.write([meta(), usage(inp=0, cache=0, output=0)])
        result = self.report()
        self.assertEqual(result['summary']['metrics']['input']['value'], 0)
        self.assertEqual(result['summary']['cache_hit_rate']['state'], 'not_applicable')

    def test_truncation_and_no_records_are_not_zero(self):
        self.write([meta(), usage()])
        with self.log.open('a') as f:
            f.write('{"type": "token_usage_record"')
        result = self.report()
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertTrue(result['issues'])
        self.write([meta()])
        result = self.report()
        self.assertEqual(result['status'], 'unstatisticable')
        self.assertIsNone(result['summary']['metrics']['input']['value'])

    def test_conflicting_duplicate_retains_other_fields(self):
        duplicate = usage(inp=120)
        self.write([meta(), usage(), duplicate])
        result = self.report()
        self.assertIsNone(result['summary']['metrics']['input']['value'])
        self.assertEqual(result['summary']['metrics']['output']['value'], 10)

    def test_discovery_uses_metadata_and_output_does_not_copy_content(self):
        row = usage(); row['payload']['request'] = {'text': 'PRIVATE-PROMPT', 'headers': {'Authorization': 'PRIVATE-KEY'}}
        self.write([meta(), row])
        result = self.run_cli('sessions', '--source', str(self.log))
        self.assertEqual(json.loads(result.stdout)['sessions'][0]['id'], 's')
        result = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END)
        self.assertNotIn('PRIVATE-', result.stdout)
        self.assertIn('主代理常规调用', result.stdout)

    def test_zcode_duplicate_completion_attempt_and_redacted_gap(self):
        def raw(rid, attempt, inp):
            return {'requestId': rid, 'attempt': attempt, 'sessionId': 's', 'turnId': 't1',
                    'querySource': 'main_turn', 'completedAt': T1,
                    'model': {'providerId': 'builtin:bigmodel-coding-plan', 'modelId': 'GLM-5.3-Flash'},
                    'response': {'usage': {'inputTokens': inp, 'outputTokens': 10,
                                          'totalTokens': inp + 10, 'cacheReadTokens': 0}}}
        one = raw('r1', 1, 100)
        redacted = {'event': 'model.sdk.stream.completed', 'sessionId': 's', 'turnId': 't1', 'timestamp': T1,
                    'context': {'requestId': 'r3', 'attempt': 1, 'querySource': 'main_turn', 'usage': {'inputTokens': '[Redacted]'}}}
        mirrored = dict(redacted, context=dict(redacted['context'], requestId='r1'))
        self.write([one, one, raw('r1', 2, 200), redacted, mirrored])
        result = self.report('--harness', 'zcode')
        self.assertEqual(result['summary']['metrics']['input']['value'], 300)
        self.assertEqual(result['summary']['metrics']['input']['state'], 'partial')
        self.assertEqual(result['summary']['call_count'], 3)

    def test_zcode_only_counts_and_unknown_provider(self):
        self.write([{'event': 'model.sdk.stream.completed', 'sessionId': 's', 'timestamp': T1,
                     'context': {'requestId': 'r', 'attempt': 1, 'querySource': 'main_turn', 'usage': {'inputTokens': '[Redacted]'}}}])
        result = self.report('--harness', 'zcode')
        self.assertEqual(result['summary']['call_count'], 1)
        self.assertIsNone(result['summary']['metrics']['input']['value'])

    def test_bigmodel_start_plan_uses_verified_zcode_usage_contract(self):
        self.write([{'sessionId': 's', 'turnId': 't1', 'requestId': 'r', 'attempt': 1,
                     'querySource': 'main_turn', 'completedAt': T1,
                     'model': {'providerId': 'builtin:bigmodel-start-plan', 'modelId': 'GLM-5.3'},
                     'response': {'usage': {'inputTokens': 300, 'outputTokens': 20,
                                           'cacheReadTokens': 100, 'totalTokens': 320}}}])
        result = self.report('--harness', 'zcode')
        self.assertEqual(result['summary']['metrics']['input']['value'], 300)

    def test_noncontiguous_turns_and_duplicate_selection(self):
        self.write([meta(), usage(turn='t1'), usage('r2', turn='t2', inp=900), usage('r3', turn='t3', inp=300)])
        result = self.report('--turn','t1','--turn','t3','--turn','t1')
        self.assertEqual(result['summary']['metrics']['input']['value'], 400)
        self.assertEqual(result['scope']['turns'], ['t1','t3'])
        self.run_cli('report','--source',str(self.log),'--session','s','--turn','foreign',codes=(4,))

    def test_shared_turn_and_request_cutoff(self):
        self.write([meta(), {'type':'event_msg','timestamp':T0,'payload':{'type':'task_started','turn_id':'t1'}},
                    usage(), {'type':'response_item','timestamp':T1,'payload':{'role':'user','type':'message','content':'extra user message'}},
                    usage('r2',time='2026-09-01T00:02:00Z')])
        turns=json.loads(self.run_cli('turns','--source',str(self.log),'--session','s').stdout)
        self.assertEqual(len(turns),1)
        proc=self.run_cli('report','--source',str(self.log),'--session','s','--request-start','2026-09-01T00:02:00Z','--format','json')
        result=json.loads(proc.stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'],100)
        self.assertEqual(result['scope']['cutoff_source'],'request_start')

    def test_left_closed_right_open_timezone(self):
        self.write([meta(),usage(),usage('r2',time='2026-09-01T00:02:00Z')])
        result=self.report('--from','2026-09-01T08:02:00+08:00')
        self.assertEqual(result['summary']['call_count'],1)

    def test_cumulative_filter_after_difference_and_boundary_gaps(self):
        def context(turn):
            return {'type':'event_msg','timestamp':T0,'payload':{'type':'task_started','turn_id':turn}}
        def count(total, time):
            return {'type':'event_msg','timestamp':time,'payload':{'type':'token_count','info':{'total_token_usage':{
                'input_tokens':total,'output_tokens':0,'cached_input_tokens':0,'total_tokens':total}}}}
        self.write([meta(),context('t1'),count(0,T0),count(100,T1),context('t2'),count(1000,'2026-09-01T00:02:00Z'),
                    context('t3'),count(1300,'2026-09-01T00:03:00Z')])
        result=self.report('--turn','t1','--turn','t3')
        self.assertEqual(result['summary']['metrics']['input']['value'],400)
        self.assertIsNone(result['summary']['call_count'])
        self.write([meta(),context('t1'),count(0,T0),count(100,T1),context('t2'),context('t3'),count(1300,'2026-09-01T00:03:00Z')])
        result=self.report('--turn','t1','--turn','t3')
        self.assertEqual(result['summary']['metrics']['input']['value'],100)
        self.assertTrue(any('未选轮次' in i['reason'] for i in result['issues']))
        self.write([meta(),context('t1'),count(500,T0),count(100,T1)])
        result=self.report()
        self.assertIsNone(result['summary']['metrics']['input']['value'])
        self.assertTrue(any('回退' in i['reason'] for i in result['issues']))

    def test_codex_last_usage_has_unique_reply_and_no_duplicate_view(self):
        reply = {'type': 'response_item', 'timestamp': T1, 'payload': {
            'type': 'message', 'role': 'assistant', 'id': 'msg-completed'}}
        raw = usage()['payload']['usage']
        count = {'type': 'event_msg', 'timestamp': T1, 'payload': {
            'type': 'token_count', 'info': {'total_token_usage': raw, 'last_token_usage': raw}}}
        start = {'type': 'event_msg', 'timestamp': T0, 'payload': {'type': 'task_started', 'turn_id': 't1'}}
        self.write([meta(), start, {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer'}}, reply, count, count])
        result = self.report()
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['summary']['call_count'], 1)
        copied = self.root / 'copy.jsonl'; copied.write_bytes(self.log.read_bytes())
        self.assertEqual(self.report('--source', str(copied))['summary']['metrics']['input']['value'], 100)
        zero = {'type': 'event_msg', 'timestamp': T0, 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {k: 0 for k in raw}}}}
        self.write([meta(), start, zero, count, usage()])
        self.assertEqual(self.report()['summary']['metrics']['input']['value'], 100)
        self.write([meta(), start, reply, count, usage()])
        self.assertEqual(self.report()['summary']['metrics']['input']['value'], 100)
        self.write([meta(), start, usage(), reply, count])
        self.assertEqual(self.report()['summary']['metrics']['input']['value'], 100)
        other = {'type': 'response_item', 'timestamp': T1, 'payload': {
            'type': 'function_call', 'call_id': 'tool-call'}}
        self.write([meta(), start, other, reply, count])
        self.assertIsNone(self.report()['summary']['metrics']['input']['value'])
        self.write([meta(), start, count])
        self.assertIsNone(self.report()['summary']['metrics']['input']['value'])

    def make_database(self):
        path = self.root/'db.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
        db.execute('INSERT INTO session VALUES (?,?,?,?,?)',('s','0.16.5',None,1788220800000,'interactive'))
        for i,total in enumerate((100,900,300),1):
            db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)',('s',f't{i}',1788220800000,1788220860000,'completed',1))
            db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (f'r{i}',f'msg{i}',0,'s',f't{i}','main_turn','builtin:bigmodel-coding-plan','GLM-5.3',
                        'completed',1788220800000,1788220860000,60000,0,json.dumps({'inputTokens':total,'outputTokens':0,'cacheReadTokens':0,'totalTokens':total})))
        db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)',('s','t0',1788220800000,1788220860000,'completed',0))
        db.commit(); db.close()
        return path

    def make_current_zcode_database(self):
        path = self.root / 'current.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);
        CREATE TABLE session_input (id TEXT,session_id TEXT,kind TEXT,delivery TEXT,payload TEXT,admitted_sequence INTEGER,
        promoted_sequence INTEGER,promoted_message_id TEXT,status TEXT,status_reason TEXT,time_created INTEGER,time_updated INTEGER);
        CREATE TABLE message (id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT,sequence INTEGER);''')
        for sid in ('s', 'other'):
            db.execute('INSERT INTO session VALUES (?,?,?,?,?)', (sid, '0.16.5', None, 1788220800000, 'interactive'))
        db.commit()
        return path, db

    def insert_db_usage(self, db, rid, turn, total, completed, session='s'):
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid, rid, 0, session, turn, 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'running', completed - 60000, completed, 60000, 0,
                    json.dumps({'inputTokens': total, 'outputTokens': 0, 'cacheReadTokens': 0, 'totalTokens': total})))

    def insert_input(self, db, iid, created, message_id=None, kind='sendText'):
        db.execute('INSERT INTO session_input VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (iid, 's', kind, 'queue', '{}', 1, 2 if message_id else None, message_id,
                    'promoted' if message_id else 'admitted', None, created, created))

    def insert_message(self, db, mid, created, **data):
        payload = {'role': 'user', 'time': {'created': created}}
        payload.update(data)
        db.execute('INSERT INTO message VALUES (?,?,?,?,?,?)', (mid, 's', created, created, json.dumps(payload), 1))

    def test_zcode_database_ranges_and_proven_zero(self):
        path=self.make_database(); before=path.read_bytes()
        args=['report','--harness','zcode','--database',str(path),'--session','s','--to',END,'--format','json']
        result=json.loads(self.run_cli(*args,'--turn','t1','--turn','t3').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'],400)
        self.assertEqual(result['activity']['call_duration_ms'],120000)
        zero=json.loads(self.run_cli(*args,'--turn','t0').stdout)
        self.assertEqual(zero['status'],'confirmed_zero')
        self.assertEqual(zero['summary']['call_count'],0)
        self.assertEqual(path.read_bytes(),before)

    def test_zcode_model_usage_turn_candidates_merge_and_fixed_cutoff(self):
        path, db = self.make_current_zcode_database()
        self.insert_db_usage(db, 'call-before', 'turn-live', 100, 1788220860000)
        self.insert_db_usage(db, 'call-after', 'turn-live', 900, 1788220980000)
        self.insert_db_usage(db, 'foreign-call', 'turn-foreign', 700, 1788220860000, 'other')
        db.commit()
        args = ['--harness', 'zcode', '--database', str(path), '--session', 's']
        turns = json.loads(self.run_cli('turns', *args).stdout)
        live = next(item for item in turns if item['id'] == 'turn-live')
        self.assertEqual(live['identity_sources'], ['model_usage'])
        self.assertEqual(live['status'], 'unknown')
        self.assertIsNone(live['start'])
        self.assertIsNone(live['end'])
        result = json.loads(self.run_cli('report', *args, '--turn', 'turn-live',
                                         '--to', '2026-09-01T00:02:00Z', '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['activity']['status'], 'unknown')
        self.run_cli('report', *args, '--turn', 'turn-foreign', codes=(4,))
        db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)',
                   ('s', 'turn-live', 1788220800000, 1788221040000, 'completed', 2))
        db.commit(); db.close()
        turns = json.loads(self.run_cli('turns', *args).stdout)
        live = next(item for item in turns if item['id'] == 'turn-live')
        self.assertEqual(live['identity_sources'], ['model_usage', 'turn_usage'])
        self.assertEqual(live['status'], 'completed')
        self.assertEqual(live['start'], '2026-09-01T00:00:00+00:00')
        result = json.loads(self.run_cli('report', *args, '--turn', 'turn-live',
                                         '--to', '2026-09-01T00:02:00Z', '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)

    def test_zcode_turn_started_event_is_a_running_candidate_without_usage(self):
        path, db = self.make_current_zcode_database()
        db.commit(); db.close()
        log = path.parent / 'log'
        log.mkdir()
        (log / 'events.jsonl').write_text(json.dumps({
            'event': 'turn.started', 'sessionId': 's', 'turnId': 'turn-event', 'timestamp': T0,
            'context': {'turnNumber': 7}}) + '\n')
        args = ['--harness', 'zcode', '--database', str(path), '--session', 's']
        turns = json.loads(self.run_cli('turns', *args).stdout)
        candidate = next(item for item in turns if item['id'] == 'turn-event')
        self.assertEqual(candidate['identity_sources'], ['turn.started'])
        self.assertEqual(candidate['status'], 'running')
        self.assertEqual(candidate['start'], '2026-09-01T00:00:00Z')
        result = json.loads(self.run_cli('report', *args, '--turn', 'turn-event', '--format', 'json').stdout)
        self.assertEqual(result['activity']['status'], 'active')
        self.assertEqual(result['status'], 'unstatisticable')

    def test_zcode_request_sources_reject_synthetic_and_merge_only_explicit_links(self):
        path, db = self.make_current_zcode_database()
        self.insert_db_usage(db, 'before', 'turn-live', 100, 1788220830000)
        self.insert_db_usage(db, 'between', 'turn-live', 200, 1788220890000)
        self.insert_db_usage(db, 'appended', 'turn-live', 300, 1788221030000)
        self.insert_message(db, 'msg-reminder', 1788220920000, synthetic=True,
                            visibility='model-only', source='todo_reminder')
        self.insert_input(db, 'input-1', 1788220860000, 'msg-1')
        self.insert_message(db, 'msg-1', 1788220920000)
        self.insert_input(db, 'input-2', 1788221040000, 'msg-2')
        self.insert_message(db, 'msg-2', 1788221100000)
        self.insert_input(db, 'input-unlinked', 1788221160000)
        self.insert_message(db, 'msg-unlinked', 1788221170000)
        self.insert_input(db, 'input-background', 1788221180000, 'msg-background', 'backgroundNotification')
        self.insert_message(db, 'msg-background', 1788221190000)
        db.commit(); db.close()
        args = ['--harness', 'zcode', '--database', str(path), '--session', 's']
        requests = json.loads(self.run_cli('requests', *args).stdout)
        self.assertNotIn('msg-reminder', {item['id'] for item in requests})
        self.assertNotIn('input-background', {item['id'] for item in requests})
        self.assertNotIn('msg-background', {item['id'] for item in requests})
        first = next(item for item in requests if item['id'] == 'input-1')
        self.assertEqual(first['ids'], ['input-1', 'msg-1'])
        self.assertEqual(first['time'], '2026-09-01T00:01:00+00:00')
        self.assertEqual(first['time_source'], 'input_admission_time')
        self.assertEqual({source['table'] for source in first['sources']}, {'session_input', 'message'})
        unlinked = {item['id']: item for item in requests if item['id'] in ('input-unlinked', 'msg-unlinked')}
        self.assertEqual(set(unlinked), {'input-unlinked', 'msg-unlinked'})
        self.assertTrue(all(item['association'] == 'unverified' for item in unlinked.values()))
        self.assertEqual(next(item for item in requests if item['id'] == 'msg-unlinked')['classification'], 'unknown')
        rejected = self.run_cli('report', *args, '--request-id', 'msg-reminder', codes=(4,))
        self.assertIn('已确认是合成或非用户消息', rejected.stderr)
        rejected = self.run_cli('report', *args, '--request-id', 'msg-background', codes=(4,))
        self.assertIn('已确认不是用户输入', rejected.stderr)
        first_report = json.loads(self.run_cli('report', *args, '--request-id', 'msg-1', '--format', 'json').stdout)
        self.assertEqual(first_report['scope']['to'], '2026-09-01T00:01:00+00:00')
        self.assertEqual(first_report['summary']['metrics']['input']['value'], 100)
        appended = json.loads(self.run_cli('report', *args, '--request-id', 'msg-2', '--format', 'json').stdout)
        self.assertEqual(appended['scope']['to'], '2026-09-01T00:04:00+00:00')
        self.assertEqual(appended['summary']['metrics']['input']['value'], 600)

    def test_active_zcode_wal_append_preserves_readable_snapshot(self):
        path = self.make_database()
        writer = sqlite3.connect(path, check_same_thread=False)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE activity (value BLOB)')
        writer.execute('INSERT INTO activity VALUES (zeroblob(16000000))')
        writer.commit()
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        stop = threading.Event()
        def append():
            while not stop.is_set():
                writer.execute('INSERT INTO activity VALUES (zeroblob(1000))')
                writer.commit()
                time.sleep(.001)
        worker = threading.Thread(target=append)
        worker.start()
        try:
            result = json.loads(self.run_cli('report', '--harness', 'zcode', '--database', str(path),
                                            '--session', 's', '--turn', 't1', '--turn', 't3',
                                            '--to', END, '--format', 'json').stdout)
            self.assertEqual(result['summary']['metrics']['input']['value'], 400)
        finally:
            stop.set(); worker.join(); writer.close()

    def test_zcode_snapshot_preserves_source_records_and_missing_sidecars(self):
        path = self.make_database()
        writer = sqlite3.connect(path)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE marker (value INTEGER)')
        writer.commit()
        wal = Path(str(path) + '-wal')
        before = (path.read_bytes(), wal.read_bytes())
        files = set(self.root.iterdir())
        self.run_cli('report', '--harness', 'zcode', '--database', str(path), '--session', 's', '--to', END)
        self.assertEqual((path.read_bytes(), wal.read_bytes()), before)
        self.assertEqual(set(self.root.iterdir()), files)
        closed_dir = self.root / 'closed'; closed_dir.mkdir()
        closed = closed_dir / 'db.sqlite'
        closed.write_bytes(before[0]); Path(str(closed) + '-wal').write_bytes(before[1])
        writer.close()
        files = set(closed_dir.iterdir())
        result = json.loads(self.run_cli('report', '--harness', 'zcode', '--database', str(closed),
                                        '--session', 's', '--turn', 't1', '--to', END, '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(set(closed_dir.iterdir()), files)
        self.assertEqual((closed.read_bytes(), Path(str(closed) + '-wal').read_bytes()), before)

    def test_codex_descendants_have_origin_turn_and_unique_calls(self):
        parent=meta(); child=meta('child')
        child['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':'s'}}}
        child_usage=usage('cr',sid='child',turn='ct',inp=200)
        child_usage['payload']['root_turn_id']='t1'
        parent_log=self.root/'parent.jsonl'
        parent_log.write_text(''.join(json.dumps(r)+'\n' for r in [parent,usage(),usage('r2',turn='t2',inp=900)]))
        self.write([child,child_usage,child_usage])
        result=self.report('--source',str(parent_log),'--turn','t1')
        self.assertEqual(result['summary']['metrics']['input']['value'],300)
        self.assertEqual({r['group'] for r in result['rows']},{'main','child'})
        only=self.report('--source',str(parent_log),'--turn','t1','--main-only')
        self.assertEqual(only['summary']['metrics']['input']['value'],100)

    def test_zcode_groups_origin_tool_report_and_main_filter(self):
        def call(sid,rid,turn,query,inp,cache,out=0):
            return {'sessionId':sid,'requestId':rid,'attempt':1,'turnId':turn,'querySource':query,'completedAt':T1,
                    'model':{'providerId':'builtin:bigmodel-coding-plan','modelId':'GLM-5.3'},
                    'response':{'usage':{'inputTokens':inp,'outputTokens':out,'cacheReadTokens':cache,'totalTokens':inp+out}}}
        def event(name,sid,turn,**context):
            return {'event':name,'sessionId':sid,'turnId':turn,'timestamp':T1,'context':context}
        self.write([call('s','main','t1','main_turn',100000,80000),
                    call('c1','child1','ct1','subagent',200000,150000),call('c2','child2','ct2','subagent',300000,250000),
                    call('s','compact','t1','compact',50000,0),
                    event('subagent.spawned','s','t1',agentId='a1'),event('subagent.spawned','s','t1',agentId='a2'),
                    event('turn.completed','c1','ct1',agentId='a1',parentSessionId='s'),
                    event('turn.completed','c2','ct2',agentId='a2',parentSessionId='s'),
                    event('subagent.completed','s','t1',agentId='a1',totalTokens=200000)])
        result=self.report('--harness','zcode','--turn','t1','--detail','model')
        self.assertEqual(result['summary']['metrics']['total']['value'],650000)
        self.assertEqual(len(result['rows']),3)
        self.assertEqual(result['tool_reports'][0]['total'],200000)
        main=self.report('--harness','zcode','--turn','t1','--main-only')
        self.assertEqual(main['summary']['metrics']['total']['value'],100000)
        self.assertEqual(main['tool_reports'],[])
        self.write([event('subagent.completed','s','t1',agentId='a1',totalTokens=200000)])
        only=self.report('--harness','zcode')
        self.assertEqual(only['status'],'tool_only')
        self.assertIsNone(only['summary']['metrics']['total']['value'])

    def test_default_group_totals_and_independent_detail(self):
        rows=[]
        for rid,query,inp,out,cache in [('m','main_turn',100000,10000,90000),('c','subagent',200000,20000,150000),('i','compact',50000,5000,30000)]:
            rows.append({'sessionId':'s','requestId':rid,'attempt':1,'turnId':'t1','querySource':query,'completedAt':T1,
                         'model':{'providerId':'builtin:bigmodel-coding-plan','modelId':'GLM-5.3'},
                         'response':{'usage':{'inputTokens':inp,'outputTokens':out,'cacheReadTokens':cache,'totalTokens':inp+out}}})
        self.write(rows)
        result=self.report('--harness','zcode','--detail','model')
        self.assertEqual([r['metrics']['total']['value'] for r in result['rows']],[110000,220000,55000])
        self.assertEqual(result['summary']['metrics']['total']['value'],385000)
        self.assertAlmostEqual(result['summary']['cache_hit_rate']['value'],270000/350000)
        self.assertEqual(result['details'][0]['metrics']['total']['value'],385000)

    def test_fork_excludes_verified_copies_but_counts_new_context_call(self):
        parent=self.root/'parent.jsonl'
        parent.write_text(''.join(json.dumps(x)+'\n' for x in [meta('parent'),usage('old',sid='parent',inp=1000000,output=0)]))
        fork=meta();fork['payload']['forked_from_id']='parent'
        self.write([fork,usage('old',inp=1000000,output=0),usage('new',inp=200000,output=0)])
        result=self.report('--source',str(parent))
        self.assertEqual(result['summary']['metrics']['total']['value'],200000)
        self.assertEqual(len(result['inherited_records']),1)
        resumed=self.root/'resume.jsonl';resumed.write_bytes(self.log.read_bytes())
        result=self.report('--source',str(parent),'--source',str(resumed))
        self.assertEqual(result['summary']['metrics']['total']['value'],200000)

    def test_export_show_recompute_preserves_scope_and_reports_missing_source(self):
        self.write([meta(),usage(turn='t1'),usage('r3',turn='t3',inp=300),usage('r5',turn='t5',inp=500)])
        saved=self.root/'report.json'
        first=self.report('--turn','t1','--turn','t3','--turn','t5','--export','json','--output',str(saved))
        self.assertEqual(json.loads(saved.read_text()),first)
        self.write([meta(),usage(turn='t1'),usage('r3',turn='t3',inp=300),usage('r5',turn='t5',inp=500),usage('r6',turn='t6',inp=600)])
        old=json.loads(self.run_cli('show','--saved',str(saved),'--format','json').stdout)
        current=json.loads(self.run_cli('recompute','--saved',str(saved),'--format','json').stdout)
        self.assertEqual(old,first)
        self.assertEqual(current['scope'],first['scope'])
        self.assertEqual(current['summary']['metrics']['input']['value'],900)
        self.run_cli('recompute','--saved',str(saved),'--turn','t6',codes=(4,))
        updated=json.loads(self.run_cli('recompute','--saved',str(saved),'--update','--turn','t6','--to',END,'--format','json').stdout)
        self.assertEqual(updated['summary']['metrics']['input']['value'],600)
        self.log.unlink()
        self.assertEqual(json.loads(self.run_cli('show','--saved',str(saved),'--format','json').stdout),first)
        missing=json.loads(self.run_cli('recompute','--saved',str(saved),'--format','json').stdout)
        self.assertIsNone(missing['summary']['metrics']['input']['value'])
        self.assertEqual(missing['status'],'unstatisticable')

    def test_export_formats_and_source_collisions(self):
        self.write([meta(),usage(),usage('r2',inp=300,cache=None)])
        baseline=self.log.read_bytes()
        result=self.report()
        csv_path=self.root/'report.csv'
        self.report('--export','csv','--output',str(csv_path))
        summary=next(r for r in csv.DictReader(io.StringIO(csv_path.read_text())) if r['category']=='summary')
        self.assertEqual(summary['input'],str(result['summary']['metrics']['input']['value']))
        self.assertEqual(summary['cache_read_state'],'partial')
        for dest in [self.log,self.root/'alias.jsonl',self.root/'hardlink.jsonl']:
            if 'alias' in dest.name:dest.symlink_to(self.log)
            if 'hardlink' in dest.name:os.link(self.log,dest)
            self.run_cli('report','--source',str(self.log),'--session','s','--export','json','--output',str(dest),codes=(4,))
            self.assertEqual(self.log.read_bytes(),baseline)

    def test_invalid_saved_report_rejected(self):
        path=self.root/'bad.json'
        for value in ({'format_version':99},{'format_version':1,'scope':None}):
            path.write_text(json.dumps(value))
            self.run_cli('show','--saved',str(path),codes=(4,))

    def test_malformed_saved_rate_rejected_and_show_detail_not_silent(self):
        self.write([meta(), usage()])
        saved = self.root / 'saved.json'
        self.report('--export', 'json', '--output', str(saved))
        self.run_cli('show', '--saved', str(saved), '--detail', 'model', codes=(4,))
        data = json.loads(saved.read_text())
        data['summary']['cache_hit_rate']['value'] = {'invalid': True}
        saved.write_text(json.dumps(data))
        result = self.run_cli('show', '--saved', str(saved), codes=(4,))
        self.assertNotIn('Traceback', result.stderr)

    def test_current_identity_and_appended_request_time(self):
        request={'type':'response_item','timestamp':'2026-09-01T00:01:00.5Z','payload':{
            'type':'message','role':'user','id':'request-2','content':'统计本轮',
            'internal_chat_message_metadata_passthrough':{'turn_id':'t1','create_time':1788220860.5}}}
        self.write([meta(),usage(),request,usage('r2',time='2026-09-01T00:02:00Z')])
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s'}):
            items=json.loads(self.run_cli('requests','--source',str(self.log),'--current').stdout)
            self.assertEqual(items[0]['id'],'request-2')
            result=json.loads(self.run_cli('report','--source',str(self.log),'--current','--request-id','request-2','--format','json').stdout)
            self.assertEqual(result['summary']['metrics']['input']['value'],100)
            self.assertEqual(result['scope']['to'],'2026-09-01T00:01:00.500000+00:00')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'unrelated'}):
            self.run_cli('report','--source',str(self.log),'--current',codes=(4,))

    def test_codex_duplicate_request_log_is_one_request_candidate(self):
        request = {'type': 'response_item', 'timestamp': T1, 'payload': {
            'type': 'message', 'role': 'user', 'id': 'request-duplicate',
            'internal_chat_message_metadata_passthrough': {'create_time': 1788220860}}}
        self.write([meta(), usage(time='2026-09-01T00:00:30Z'), request])
        copied = self.root / 'rollout-copy.jsonl'
        copied.write_bytes(self.log.read_bytes())
        args = ['--source', str(self.log), '--source', str(copied), '--session', 's']
        requests = json.loads(self.run_cli('requests', *args).stdout)
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(requests[0]['sources']), 2)
        result = json.loads(self.run_cli('report', *args, '--request-id', 'request-duplicate', '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)

    def test_unknown_identity_schema_is_a_gap_without_copying_content(self):
        bad = usage('bad'); bad['payload']['response_id'] = {'secret': 'PRIVATE-VALUE'}
        self.write([meta(), usage(), bad])
        result = self.report('--detail', 'model')
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertTrue(result['issues'])
        self.assertNotIn('PRIVATE-VALUE', json.dumps(result))
        row = {'sessionId': 's', 'turnId': 't1', 'requestId': 'r', 'attempt': 1,
               'querySource': 'main_turn', 'completedAt': T1,
               'model': {'providerId': 'builtin:bigmodel-coding-plan', 'modelId': {'secret': 'PRIVATE-VALUE'}},
               'response': {'usage': {'inputTokens': 100, 'outputTokens': 1}}}
        self.write([row])
        result = self.report('--harness', 'zcode', '--detail', 'model')
        self.assertTrue(result['issues'])
        self.assertNotIn('PRIVATE-VALUE', json.dumps(result))

    def test_installation_standalone_and_existing_target_protected(self):
        installer=ENTRY.parents[3]/'install_skill.py'
        target=self.root/'installed'
        proc=subprocess.run([sys.executable,'-B',str(installer),'--target',str(target)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        standalone=target/'scripts/audit.py'
        self.write([meta(),usage()])
        proc=subprocess.run([sys.executable,'-B',str(standalone),'report','--source',str(self.log),'--session','s','--to',END,'--format','json'],capture_output=True,text=True,cwd=self.root)
        self.assertEqual(json.loads(proc.stdout)['summary']['metrics']['input']['value'],100)
        skill=target/'SKILL.md';skill.write_text('existing personal changes')
        proc=subprocess.run([sys.executable,'-B',str(installer),'--target',str(target)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,1)
        self.assertEqual(skill.read_text(),'existing personal changes')


if __name__ == '__main__':
    unittest.main()
