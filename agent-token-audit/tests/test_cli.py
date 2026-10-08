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

    def test_empty_from_preserves_new_report_and_saved_scope_cli_contracts(self):
        self.write([meta(), usage('r1', inp=100, time='2026-09-01T00:00:15.100Z'),
                    usage('r2', inp=900, time='2026-09-01T00:00:45.500Z'),
                    usage('r3', inp=300, time='2026-09-01T00:01:00Z')])
        source_before = self.log.read_bytes()
        unbounded = self.report('--from', '')
        self.assertEqual(unbounded['scope']['from'], '')
        self.assertEqual(unbounded['summary']['metrics']['input']['value'], 1300)
        bound = '2026-09-01T00:00:30.123456Z'
        saved = self.root / 'saved.json'
        original = self.report('--from', bound, '--export', 'json', '--output', str(saved))
        self.assertEqual(original['summary']['metrics']['input']['value'], 1200)
        saved_before = saved.read_bytes()
        for lower in ([], ['--from', '']):
            with self.subTest(lower=lower):
                proc = self.run_cli('recompute', '--saved', str(saved), '--update', '--to', END,
                                    '--format', 'json', *lower)
                result = json.loads(proc.stdout)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(result['scope']['from'], bound)
                self.assertEqual(result['summary']['metrics']['input']['value'], 1200)
                self.assertEqual(saved.read_bytes(), saved_before)
                self.assertEqual(self.log.read_bytes(), source_before)
                self.assertEqual(set(self.root.iterdir()), {self.log, saved})

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
            self.assertEqual(items[0]['classification'],'unknown')
            result=json.loads(self.run_cli('report','--source',str(self.log),'--current','--request-id','request-2','--format','json').stdout)
            self.assertEqual(result['summary']['metrics']['input']['value'],100)
            self.assertEqual(result['scope']['to'],'2026-09-01T00:01:00.500000+00:00')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'unrelated'}):
            self.run_cli('report','--source',str(self.log),'--current',codes=(4,))
        env = {k: v for k, v in os.environ.items() if k != 'CODEX_THREAD_ID'}
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), 'report', '--source', str(self.log), '--current'],
                              capture_output=True, text=True, cwd=self.root, env=env)
        self.assertEqual(proc.returncode, 4)
        self.assertIn('CODEX_THREAD_ID 缺失', proc.stderr)

    def test_codex_system_injected_messages_are_not_request_cutoffs(self):
        def message(mid, kinds, text):
            meta = {'turn_id': 't1', 'create_time': 1788220860.5}
            if kinds is not None:
                meta['content_item_kinds'] = kinds
            return {'type': 'response_item', 'timestamp': T1, 'payload': {
                'type': 'message', 'role': 'user', 'id': mid, 'content': [{'type': 'input_text', 'text': text}],
                'internal_chat_message_metadata_passthrough': meta}}
        system = message('msg-env', ['agents_md.instructions', 'environments.environment_context'], '<environment_context>')
        skill = message('msg-skill', ['skills.selected_skill_instructions'], '<skill>')
        apps = message('msg-apps', ['additional_content.codex_apps_open_page'], '<external_codex_apps_open_page>')
        real = message('msg-real', ['user.text'], '统计这个任务')
        reply = message('msg-reply', ['user.text'], '<send_user_message_question_reply>[{"answer":"同意"}]')
        legacy = {'type': 'response_item', 'timestamp': T1, 'payload': {
            'type': 'message', 'role': 'user', 'id': 'msg-legacy', 'content': [{'type': 'input_text', 'text': '旧格式消息'}]}}
        self.write([meta(), usage(), system, skill, apps, real, reply, legacy, usage('r2', time='2026-09-01T00:02:00Z')])
        args = ['--source', str(self.log), '--session', 's']
        items = json.loads(self.run_cli('requests', *args).stdout)
        listed = {item['id']: item for item in items}
        self.assertNotIn('msg-env', listed)
        self.assertNotIn('msg-skill', listed)
        self.assertNotIn('msg-apps', listed)
        self.assertEqual(listed['msg-real']['classification'], 'user_message')
        self.assertEqual(listed['msg-reply']['classification'], 'user_message')
        self.assertEqual(listed['msg-legacy']['classification'], 'unknown')
        for rejected in ('msg-env', 'msg-skill', 'msg-apps'):
            proc = self.run_cli('report', *args, '--request-id', rejected, codes=(4,))
            self.assertIn('系统注入', proc.stderr)
        result = json.loads(self.run_cli('report', *args, '--request-id', 'msg-real', '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['scope']['to'], '2026-09-01T00:01:00.500000+00:00')

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

    def test_v2_report_roundtrip_views_and_projection(self):
        def started(turn):
            return {'type': 'event_msg', 'timestamp': T0, 'payload': {'type': 'task_started', 'turn_id': turn}}
        def count(total, time):
            return {'type': 'event_msg', 'timestamp': time, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {
                'input_tokens': total, 'output_tokens': 0, 'cached_input_tokens': 0, 'total_tokens': total}}}}
        child = meta('child')
        child['payload']['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': 's'}}}
        child_usage = usage('cr', sid='child', turn='ct', inp=50, cache=0, output=0)
        child_usage['payload']['root_turn_id'] = 't1'
        parent_log = self.root / 'parent.jsonl'
        parent_log.write_text(''.join(json.dumps(x) + '\n' for x in [
            meta(), started('t1'), count(0, T0), usage(), count(100, T1),
            started('t2'), started('t3'), count(1300, '2026-09-01T00:03:00Z')]))
        self.write([child, child_usage])
        turns = ['--turn', 't1', '--turn', 't2', '--turn', 't3']
        result = self.report('--source', str(parent_log), *turns, '--detail', 'turn')
        self.assertEqual(result['format_version'], 2)
        self.assertEqual(result['localization']['session']['confirmed_by'], 'explicit')
        self.assertEqual(result['localization']['cutoff']['source'], 'explicit')
        turn_rows = {row['label']: row for row in result['views']['turn']['rows']}
        self.assertEqual(set(turn_rows), {'t1', '多轮区间，无法拆分'})
        self.assertEqual(turn_rows['t1']['metrics']['input']['value'], 150)
        self.assertEqual(turn_rows['多轮区间，无法拆分']['metrics']['input']['value'], 1200)
        agent_rows = {row['label']: row for row in result['views']['agent']['rows']}
        self.assertEqual(agent_rows['s']['metrics']['input']['value'], 1300)
        self.assertEqual(agent_rows['child']['metrics']['input']['value'], 50)
        model_total = sum(row['metrics']['input']['value'] for row in result['views']['model']['rows'])
        self.assertEqual(model_total, result['summary']['metrics']['input']['value'])
        self.assertEqual([d['name'] for d in result['details']],
                         [row['label'] for row in result['views']['turn']['rows']])
        self.assertEqual(result['details'][-1]['metrics'], turn_rows['t1']['metrics'])
        self.assertIn('定位证据', self.run_cli('report', '--source', str(parent_log), '--session', 's', *turns).stdout)
        saved = self.root / 'v2.json'
        self.report('--source', str(parent_log), *turns, '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, json.loads(saved.read_text()))
        self.run_cli('show', '--saved', str(saved), '--export', 'json', '--output', str(saved), codes=(4,))

    def test_v1_report_reads_without_new_dimensions_and_recompute_makes_v2(self):
        self.write([meta(), usage(), usage('r2', inp=300, cache=None)])
        saved = self.root / 'v2.json'
        self.report('--detail', 'model', '--export', 'json', '--output', str(saved))
        old = {k: v for k, v in json.loads(saved.read_text()).items()
               if k not in ('localization', 'internal_support', 'views', 'explanation')}
        for collection in ('records', 'unassigned_records'):
            for record in old.get(collection, []):
                record.pop('explanation', None)
        old['format_version'] = 1
        v1 = self.root / 'v1.json'
        v1.write_text(json.dumps(old))
        shown = json.loads(self.run_cli('show', '--saved', str(v1), '--format', 'json').stdout)
        self.assertEqual(shown['format_version'], 1)
        self.assertEqual(shown['summary'], old['summary'])
        self.assertEqual(shown['details'], old['details'])
        self.assertNotIn('views', shown)
        table = self.run_cli('show', '--saved', str(v1))
        self.assertIn('旧报告未保存', table.stdout)
        self.assertIn('明细（model', table.stdout)
        plain = {k: v for k, v in old.items() if k != 'details'}
        plain_path = self.root / 'v1-plain.json'
        plain_path.write_text(json.dumps(plain))
        plain_shown = json.loads(self.run_cli('show', '--saved', str(plain_path), '--format', 'json').stdout)
        self.assertEqual(plain_shown['summary'], plain['summary'])
        self.assertNotIn('details', plain_shown)
        recompute = json.loads(self.run_cli('recompute', '--saved', str(v1), '--format', 'json').stdout)
        self.assertEqual(recompute['format_version'], 2)
        self.assertEqual(recompute['scope'], old['scope'])
        self.assertEqual(recompute['summary']['metrics']['input']['value'], 400)

    def test_invalid_v2_reports_rejected(self):
        self.write([meta(), usage()])
        saved = self.root / 'v2.json'
        self.report('--detail', 'model', '--export', 'json', '--output', str(saved))
        base = json.loads(saved.read_text())
        def reject(mutate):
            data = json.loads(json.dumps(base))
            mutate(data)
            path = self.root / 'bad.json'
            path.write_text(json.dumps(data))
            self.run_cli('show', '--saved', str(path), codes=(4,))
        reject(lambda d: d['localization']['session'].__setitem__('id', 'other'))
        reject(lambda d: d['localization']['cutoff'].__setitem__('time', 'not-a-time'))
        reject(lambda d: d['views'].pop('agent'))
        reject(lambda d: d['views']['model']['rows'][0]['metrics']['input'].__setitem__('value', -5))
        reject(lambda d: d['views']['model']['rows'][0]['metrics']['input'].__setitem__('value', 1.5))
        reject(lambda d: d['details'][0]['metrics']['input'].__setitem__('value', 1))
        reject(lambda d: d['internal_support'].pop('retry_failure'))
        reject(lambda d: d['views']['model']['rows'][0].pop('id'))

    def test_large_integers_survive_roundtrip_exactly(self):
        big = 2 ** 53 + 3
        self.write([meta(), usage(inp=big, cache=0)])
        result = self.report()
        self.assertEqual(result['summary']['metrics']['input']['value'], big)
        self.assertEqual(result['views']['model']['rows'][0]['metrics']['input']['value'], big)
        saved = self.root / 'big.json'
        self.report('--export', 'json', '--output', str(saved))
        self.assertIn(str(big), saved.read_text())
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['summary']['metrics']['input']['value'], big)
        self.assertEqual(shown['views']['model']['rows'][0]['metrics']['input']['value'], big)

    def test_legal_full_cache_rate_and_all_status_reports_roundtrip(self):
        self.write([meta(), usage(inp=100, cache=100, output=0)])
        result = self.report()
        self.assertEqual(result['summary']['cache_hit_rate']['value'], 1.0)
        self.assertEqual(result['coverage_state'], 'unknown')
        saved = self.root / 'rate.json'
        self.report('--export', 'json', '--output', str(saved))
        self.assertEqual(json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)['summary']['cache_hit_rate']['value'], 1.0)
        self.write([{'event': 'model.sdk.stream.completed', 'sessionId': 's', 'timestamp': T1,
                     'context': {'requestId': 'r', 'attempt': 1, 'querySource': 'main_turn', 'usage': {'inputTokens': '[Redacted]'}}}])
        count_only = self.root / 'count.json'
        self.report('--harness', 'zcode', '--export', 'json', '--output', str(count_only))
        self.assertEqual(json.loads(self.run_cli('show', '--saved', str(count_only), '--format', 'json').stdout)['status'], 'count_only')
        self.write([{'event': 'subagent.completed', 'sessionId': 's', 'turnId': 't1', 'timestamp': T1, 'context': {'agentId': 'a1', 'totalTokens': 200000}}])
        tool_only = self.root / 'tool.json'
        self.report('--harness', 'zcode', '--export', 'json', '--output', str(tool_only))
        self.assertEqual(json.loads(self.run_cli('show', '--saved', str(tool_only), '--format', 'json').stdout)['status'], 'tool_only')
        self.write([meta()])
        unstatisticable = self.root / 'none.json'
        self.report('--export', 'json', '--output', str(unstatisticable))
        self.assertEqual(json.loads(self.run_cli('show', '--saved', str(unstatisticable), '--format', 'json').stdout)['status'], 'unstatisticable')
        path = self.make_database()
        zero = self.root / 'zero.json'
        self.run_cli('report', '--harness', 'zcode', '--database', str(path), '--session', 's', '--turn', 't0',
                     '--to', END, '--format', 'json', '--export', 'json', '--output', str(zero))
        self.assertEqual(json.loads(self.run_cli('show', '--saved', str(zero), '--format', 'json').stdout)['status'], 'confirmed_zero')

    def test_account_plan_provider_usage_metered_and_unverified_stays_unknown(self):
        rows = []
        for rid, provider in (('a', 'account:bigmodel-individual-coding-plan'), ('b', 'account:bigmodel-start-plan'), ('c', 'bigmodel')):
            rows.append({'sessionId': 's', 'requestId': rid, 'attempt': 1, 'turnId': 't1', 'querySource': 'main_turn',
                         'completedAt': T1, 'model': {'providerId': provider, 'modelId': 'GLM-5.3'},
                         'response': {'usage': {'inputTokens': 100, 'outputTokens': 10, 'cacheReadTokens': 90, 'totalTokens': 110}}})
        self.write(rows)
        result = self.report('--harness', 'zcode')
        self.assertEqual(result['summary']['metrics']['input']['value'], 200)
        self.assertEqual(result['summary']['metrics']['input']['known_records'], 2)
        self.assertEqual(result['summary']['metrics']['input']['records'], 3)
        self.assertTrue(any('尚未验证' in r['metrics']['input']['reason'] for r in result['records'] if r['call_id'] == 'c:1'))

    def test_database_alternate_rollout_shown_not_merged(self):
        root = self.root / 'layout'
        dbdir = root / 'db'
        dbdir.mkdir(parents=True)
        path = dbdir / 'db.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
        db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.5', None, 1788220800000, 'interactive'))
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('r1', 'msg1', 0, 's', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'completed', 1788220800000, 1788220860000, 60000, 0,
                    json.dumps({'inputTokens': 100, 'outputTokens': 0, 'cacheReadTokens': 0, 'totalTokens': 100})))
        db.commit(); db.close()
        rollout = root / 'rollout'
        rollout.mkdir()
        (rollout / 'model-io-s.jsonl').write_text(json.dumps({
            'requestId': 'uuid-1', 'attempt': 1, 'sessionId': 's', 'turnId': 't1', 'querySource': 'main_turn',
            'completedAt': T1, 'model': {'providerId': 'account:bigmodel-individual-coding-plan', 'modelId': 'GLM-5.3'},
            'response': {'usage': {'inputTokens': 400, 'outputTokens': 40, 'cacheReadTokens': 10, 'totalTokens': 440}}}) + '\n')
        args = ['--harness', 'zcode', '--database', str(path), '--session', 's']
        result = json.loads(self.run_cli('report', *args, '--to', END, '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(len(result['records']), 1)
        alt = result['alternate_sources'][0]
        self.assertEqual(alt['kind'], 'rollout')
        self.assertEqual(alt['session'], 's')
        self.assertEqual(alt['records'], 1)
        self.assertEqual(alt['metrics']['input']['value'], 400)
        self.assertIn('未并入小计', alt['note'])
        self.assertIn('未按报告范围筛选', alt['note'])
        self.assertIn('补充来源（rollout', self.run_cli('report', *args, '--to', END).stdout)
        saved = self.root / 'alt.json'
        self.run_cli('report', *args, '--to', END, '--format', 'json', '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['alternate_sources'][0]['metrics']['input']['value'], 400)
        csv_path = self.root / 'alt.csv'
        self.run_cli('report', *args, '--to', END, '--export', 'csv', '--output', str(csv_path))
        alt_row = next(r for r in csv.DictReader(io.StringIO(csv_path.read_text())) if r['category'] == 'alternate_source')
        self.assertEqual(alt_row['input'], '400')
        data = json.loads(saved.read_text())
        data['alternate_sources'][0]['metrics']['input']['value'] = -1
        saved.write_text(json.dumps(data))
        self.run_cli('show', '--saved', str(saved), codes=(4,))

    def test_codex_compaction_marker_reclassifies_referenced_call(self):
        started = {'type': 'event_msg', 'timestamp': T0, 'payload': {'type': 'task_started', 'turn_id': 't1'}}
        compaction = usage('resp-compact', inp=5000, cache=0, output=200)
        marker = {'type': 'compacted', 'timestamp': '2026-09-01T00:01:30Z', 'payload': {
            'compaction_response_id': 'resp-compact', 'message': 'summary',
            'latest_token_usage_record': {'response_id': 'resp-compact', 'thread_id': 's',
                                          'usage': dict(compaction['payload']['usage'])}}}
        unresolved = {'type': 'compacted', 'timestamp': '2026-09-01T00:03:00Z', 'payload': {}}
        self.write([meta(), started, usage(), compaction, marker, usage('r2', time='2026-09-01T00:02:00Z'), unresolved])
        result = self.report()
        groups = {row['group']: row['metrics']['input']['value'] for row in result['rows']}
        self.assertEqual(groups.get('main'), 200)
        self.assertEqual(groups.get('internal'), 5000)
        self.assertEqual(result['summary']['metrics']['input']['value'], 5200)
        compaction_records = [r for r in result['records'] if r.get('internal_kind') == 'compaction']
        self.assertEqual(len(compaction_records), 1)
        self.assertTrue(any('压缩调用' in i['reason'] and ('未找到' in i['reason'] or '未提供' in i['reason']) for i in result['issues']))
        self.assertEqual(result['internal_support']['compaction_summary']['status'], 'checked_available')
        self.assertEqual(result['internal_support']['title_session_aux']['status'], 'checked_absent')
        only = self.report('--main-only')
        self.assertEqual(only['summary']['metrics']['input']['value'], 200)

    def test_workflow_child_is_descendant_and_session_aux_is_separate(self):
        path = self.root / 'wf.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
        db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.9', None, 1788220800000, 'interactive'))
        db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('wf', '0.16.9', 's', 1788220801000, 'workflow_child'))
        def usage_row(rid, sid, turn, source, inp, completed):
            db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (rid, rid, 0, sid, turn, source, 'builtin:bigmodel-coding-plan', 'GLM-5.3', 'completed',
                        completed - 60000, completed, 60000, 0,
                        json.dumps({'inputTokens': inp, 'outputTokens': 1, 'cacheReadTokens': 0, 'totalTokens': inp + 1})))
        usage_row('main1', 's', 't1', 'main_turn', 1000, 1788220860000)
        usage_row('wfc1', 'wf', None, 'workflow_child', 5000, 1788220920000)
        usage_row('wfc2', 'wf', 'wfturn', 'workflow_child', 7000, 1788220980000)
        usage_row('title1', 's', 't1', 'session_title', 238, 1788220870000)
        db.commit(); db.close()
        args = ['--harness', 'zcode', '--database', str(path), '--session', 's']
        full = json.loads(self.run_cli('report', *args, '--to', END, '--format', 'json').stdout)
        groups = {row['group']: row['metrics']['input']['value'] for row in full['rows']}
        self.assertEqual(groups.get('main'), 1000)
        self.assertEqual(groups.get('child'), 12000)
        self.assertEqual(groups.get('internal'), 238)
        self.assertEqual(full['summary']['metrics']['input']['value'], 13238)
        self.assertEqual([r['origin_kind'] for r in full['records'] if r.get('origin_kind')], ['workflow_child'] * 2)
        self.assertEqual(full['internal_support']['background_other']['status'], 'checked_available')
        self.assertEqual(full['internal_support']['title_session_aux']['status'], 'checked_available')
        task = json.loads(self.run_cli('report', *args, '--turn', 't1', '--to', END, '--format', 'json').stdout)
        self.assertEqual(task['summary']['metrics']['input']['value'], 1000)
        unassigned = [r['call_id'] for r in task['unassigned_records']]
        self.assertIn('title1:0', unassigned)
        main_only = json.loads(self.run_cli('report', *args, '--to', END, '--main-only', '--format', 'json').stdout)
        self.assertEqual(main_only['summary']['metrics']['input']['value'], 1000)

    def test_descendant_cycle_keeps_records_with_reason(self):
        first = meta('a')
        first['payload']['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': 'b'}}}
        second = meta('b')
        second['payload']['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': 'a'}}}
        log_b = self.root / 'b.jsonl'
        log_b.write_text(json.dumps(second) + '\n')
        self.write([first, usage(sid='a', turn='t1')])
        result = json.loads(self.run_cli('report', '--source', str(self.log), '--source', str(log_b),
                                         '--session', 'a', '--to', END, '--format', 'json').stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertTrue(any('循环' in i['reason'] for i in result['issues']))

    def test_installation_standalone_and_existing_target_protected(self):
        installer=ENTRY.parents[3]/'install_skill.py'
        target=self.root/'installed'
        proc=subprocess.run([sys.executable,'-B',str(installer),'--target',str(target)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        standalone=target/'scripts/audit.py'
        self.write([meta(),usage()])
        proc=subprocess.run([sys.executable,'-B',str(standalone),'report','--source',str(self.log),'--session','s','--to',END,'--format','json'],capture_output=True,text=True,cwd=self.root)
        self.assertEqual(json.loads(proc.stdout)['summary']['metrics']['input']['value'],100)
        for viewer_file in ('viewer/index.html','viewer/lossless-json.umd.js','viewer/lossless-json.LICENSE.md'):
            self.assertTrue((target/viewer_file).is_file(), viewer_file)
        skill=target/'SKILL.md';skill.write_text('existing personal changes')
        proc=subprocess.run([sys.executable,'-B',str(installer),'--target',str(target)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,1)
        self.assertEqual(skill.read_text(),'existing personal changes')


class OverviewCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-overview-')
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

    def overview(self, *args, source=None):
        src = source or self.log
        base = ['overview', '--source', str(src), '--to', END, '--format', 'json']
        if args and '--database' in args:
            base = ['overview', '--to', END, '--format', 'json']
        proc = self.run_cli(*base, *args)
        return json.loads(proc.stdout)

    def test_default_all_sessions_dedup_rankings_and_big_integer(self):
        big = 2 ** 60 + 7
        self.write([meta('s1'), meta('s2'), usage('a', sid='s1', inp=big), usage('b', sid='s2', inp=200, cache=0),
                    usage('a', sid='s1', inp=big)])
        result = self.overview()
        self.assertEqual(result['format_version'], 3)
        self.assertEqual(result['scope']['sessions'], ['s1', 's2'])
        self.assertEqual(result['scope']['kind'], 'overall')
        self.assertEqual(result['summary']['metrics']['input']['value'], big + 200)
        self.assertEqual(result['summary']['call_count'], 2)
        ranked = {row['label']: row['metrics']['input']['value'] for row in result['rankings']['session']['rows']}
        self.assertEqual(ranked, {'s1': big, 's2': 200})
        self.assertEqual(result['days'][0]['date'], '2026-09-01')
        export = self.root / 'big.json'
        self.run_cli('overview', '--source', str(self.log), '--to', END, '--export', 'json', '--output', str(export))
        reloaded = json.loads(export.read_text())
        self.assertEqual(reloaded['summary']['metrics']['input']['value'], big + 200)

    def test_day_intersection_unbucketed_and_timezone(self):
        def count(total, time):
            return {'type': 'event_msg', 'timestamp': time,
                    'payload': {'type': 'token_count', 'info': {'total_token_usage': total}}}
        zero = {'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0}
        delta = {'input_tokens': 50, 'output_tokens': 2, 'cached_input_tokens': 10}
        self.write([meta('s1'),
                    usage('m', sid='s1', turn='t1', inp=100, cache=0, time='2026-09-01T09:00:00Z'),
                    usage('a', sid='s1', turn='t2', inp=200, cache=0, time='2026-09-01T15:00:00Z'),
                    usage('d', sid='s1', turn='t3', inp=400, cache=0, time='2026-09-02T12:00:00Z'),
                    count(zero, '2026-09-01T23:50:00Z'), count(delta, '2026-09-02T00:10:00Z')])
        result = self.overview('--from', '2026-09-01T12:00:00Z', '--to', '2026-09-03T00:00:00Z', '--tz', '+00:00')
        days = {day['date']: day['metrics']['input']['value'] for day in result['days']}
        self.assertEqual(days, {'2026-09-01': 200, '2026-09-02': 400})
        self.assertEqual(result['unbucketed']['records'], 1)
        self.assertEqual(result['unbucketed']['metrics']['input']['value'], 50)
        total = result['summary']['metrics']['input']['value']
        self.assertEqual(total, 650)
        self.assertEqual(sum(days.values()) + result['unbucketed']['metrics']['input']['value'], total)
        self.assertEqual(result['scope']['tz'], '+00:00')

    def test_missing_time_records_are_diagnosed_not_counted(self):
        missing = usage('m', turn='t2', inp=900)
        missing['timestamp'] = None
        self.write([meta(), usage(), missing])
        result = self.overview()
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertTrue(any('缺少可信时间' in i['reason'] for i in result['issues']))
        self.write([meta(), missing])
        proc = self.run_cli('overview', '--source', str(self.log), '--to', END, '--format', 'json', codes=(3,))
        empty = json.loads(proc.stdout)
        self.assertEqual(empty['status'], 'unstatisticable')
        self.assertIsNone(empty['summary']['metrics']['input']['value'])

    def test_explicit_set_main_only_and_descendant_closure(self):
        child = meta('c')
        child['payload']['source'] = {'subagent': {'thread_spawn': {'parent_thread_id': 's1'}}}
        self.write([meta('s1'), child, usage('a', sid='s1', inp=100), usage('c', sid='c', inp=200, cache=0)])
        result = self.overview()
        self.assertEqual(result['summary']['metrics']['input']['value'], 300)
        index = {row['id']: row for row in result['session_index']}
        self.assertEqual(index['c']['parent'], 's1')
        main_only = self.overview('--main-only')
        self.assertEqual(main_only['summary']['metrics']['input']['value'], 100)
        explicit = self.overview('--session', 's1')
        self.assertEqual(explicit['scope']['sessions'], ['s1'])
        self.assertEqual(explicit['summary']['metrics']['input']['value'], 300)
        self.assertEqual(explicit['localization']['sessions']['confirmed_by'], 'explicit_set')

    def test_v3_saved_show_recompute_update_and_source_protection(self):
        self.write([meta(), usage()])
        saved = self.root / 'saved.json'
        self.run_cli('overview', '--source', str(self.log), '--to', END, '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['summary']['metrics']['input']['value'], 100)
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(recomputed['scope']['sessions'], ['s'])
        self.assertEqual(recomputed['summary']['metrics']['input']['value'], 100)
        self.assertEqual(recomputed['localization']['sessions']['confirmed_by'], 'saved_scope')
        with self.log.open('a') as f:
            f.write(json.dumps(usage('r9', turn='t9', inp=200, cache=0, time='2026-09-01T02:00:00Z')) + '\n')
        updated = json.loads(self.run_cli('recompute', '--saved', str(saved), '--update', '--to', '2026-09-03T00:00:00Z',
                                          '--format', 'json').stdout)
        self.assertEqual(updated['summary']['metrics']['input']['value'], 300)
        self.assertEqual(updated['scope']['to'], '2026-09-03T00:00:00Z')
        self.run_cli('overview', '--source', str(self.log), '--to', END, '--export', 'json', '--output', str(self.log),
                     codes=(4,))
        broken = json.loads(saved.read_text())
        del broken['days']
        broken_path = self.root / 'broken.json'
        broken_path.write_text(json.dumps(broken))
        self.run_cli('show', '--saved', str(broken_path), codes=(4,))

    def test_overview_csv_markdown_and_v2_regression(self):
        self.write([meta(), usage()])
        csv_proc = self.run_cli('overview', '--source', str(self.log), '--to', END, '--format', 'csv')
        self.assertIn('ranking_session', csv_proc.stdout)
        self.assertIn('2026-09-01', csv_proc.stdout)
        md_proc = self.run_cli('overview', '--source', str(self.log), '--to', END, '--format', 'markdown')
        self.assertIn('模型排行', md_proc.stdout)
        v2 = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                                     '--format', 'json').stdout)
        self.assertEqual(v2['format_version'], 2)

    def test_zcode_database_overview_two_sessions(self):
        path = self.root / 'db.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
        for sid, total in (('s', 100), ('x', 250)):
            db.execute('INSERT INTO session VALUES (?,?,?,?,?)', (sid, '0.16.5', None, 1788220800000, 'interactive'))
            db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', (sid, 't1', 1788220800000, 1788220860000, 'completed', 1))
            db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (f'r-{sid}', f'msg-{sid}', 0, sid, 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                        'completed', 1788220800000, 1788220860000, 60000, 0,
                        json.dumps({'inputTokens': total, 'outputTokens': 0, 'cacheReadTokens': 0, 'totalTokens': total})))
        db.commit(); db.close()
        before = path.read_bytes()
        result = self.overview('--harness', 'zcode', '--database', str(path))
        self.assertEqual(result['summary']['metrics']['input']['value'], 350)
        self.assertEqual(result['scope']['sessions'], ['s', 'x'])
        self.assertEqual(path.read_bytes(), before)

    def test_overview_request_id_cutoff_and_invalid_rejected(self):
        import datetime as dt
        epoch_noon = dt.datetime(2026, 10, 5, 12, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        message = {'type': 'response_item', 'timestamp': '2026-10-05T00:00:30Z',
                   'payload': {'type': 'message', 'role': 'user', 'id': 'req-1', 'created_time': 0,
                               'internal_chat_message_metadata_passthrough': {'create_time': epoch_noon,
                                                                              'content_item_kinds': ['user.text']}}}
        self.write([meta('a'), usage('rAM', sid='a', turn='t', inp=100, time='2026-10-05T11:00:00Z'),
                    usage('rPM', sid='a', turn='t2', inp=900, time='2026-10-05T13:00:00Z'), message])
        proc = self.run_cli('overview', '--source', str(self.log), '--session', 'a', '--request-id', 'req-1',
                            '--format', 'json')
        result = json.loads(proc.stdout)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['scope']['cutoff_source'], 'message_create_time')
        self.run_cli('overview', '--source', str(self.log), '--session', 'a', '--request-id', 'nope',
                     '--format', 'json', codes=(4,))

    def test_v3_update_replaces_session_set_and_accepts_multiple(self):
        child = meta('b')
        self.write([meta('a'), child, usage('a', sid='a', inp=1000, cache=0),
                    usage('b', sid='b', inp=555, cache=0, time='2026-09-01T00:00:20Z')])
        saved = self.root / 'saved.json'
        self.run_cli('overview', '--source', str(self.log), '--session', 'a', '--to', END,
                     '--tz', 'UTC', '--export', 'json', '--output', str(saved))
        updated = json.loads(self.run_cli('recompute', '--saved', str(saved), '--update', '--session', 'b',
                                          '--to', END, '--format', 'json').stdout)
        self.assertEqual(updated['scope']['sessions'], ['b'])
        self.assertEqual(updated['summary']['metrics']['input']['value'], 555)
        both = json.loads(self.run_cli('recompute', '--saved', str(saved), '--update',
                                       '--session', 'a', '--session', 'b', '--to', END, '--format', 'json').stdout)
        self.assertEqual(both['scope']['sessions'], ['a', 'b'])
        self.assertEqual(both['summary']['metrics']['input']['value'], 1555)

    def test_v3_recompute_missing_session_keeps_reliable_partial(self):
        self.write([meta('a'), usage(sid='a', inp=100)])
        other = self.root / 'b.jsonl'
        other.write_text(json.dumps(meta('b')) + '\n'
                         + json.dumps(usage('b', sid='b', inp=555, cache=0, time='2026-09-01T00:00:20Z')) + '\n')
        saved = self.root / 'saved.json'
        self.run_cli('overview', '--source', str(self.log), '--source', str(other),
                     '--session', 'a', '--session', 'b', '--to', END, '--tz', 'UTC',
                     '--export', 'json', '--output', str(saved))
        other.unlink()
        result = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(result['scope']['sessions'], ['a', 'b'])
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertTrue(any('缺失' in i['reason'] for i in result['issues']))

    def test_overview_zero_requires_full_session_coverage(self):
        path = self.root / 'zero.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
        CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
        query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
        duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
        CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
        for sid in ('proven', 'unknown'):
            db.execute('INSERT INTO session VALUES (?,?,?,?,?)', (sid, '0.16.5', None, 1788220800000, 'interactive'))
        db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('proven', 't0', 1788220800000, 1788220860000, 'completed', 0))
        db.commit(); db.close()
        proc = self.run_cli('overview', '--harness', 'zcode', '--database', str(path), '--to', END,
                            '--format', 'json', codes=(3,))
        self.assertEqual(json.loads(proc.stdout)['status'], 'unstatisticable')
        proc = self.run_cli('overview', '--harness', 'zcode', '--database', str(path), '--session', 'proven',
                            '--to', END, '--format', 'json', codes=(0,))
        self.assertEqual(json.loads(proc.stdout)['status'], 'confirmed_zero')

    def test_overview_keeps_session_less_diagnostics_and_empty_set_reads(self):
        self.write([meta('a'), usage()])
        with self.log.open('a') as f:
            f.write('not JSON\n')
        result = self.overview()
        self.assertTrue(any('损坏' in i['reason'] for i in result['issues']))
        empty = dict(result)
        empty['scope'] = dict(empty['scope'], sessions=[])
        empty['localization'] = dict(empty['localization'],
                                     sessions=dict(empty['localization']['sessions'], count=0))
        empty_path = self.root / 'empty.json'
        empty_path.write_text(json.dumps(empty))
        shown = json.loads(self.run_cli('show', '--saved', str(empty_path), '--format', 'json').stdout)
        self.assertEqual(shown['scope']['sessions'], [])
    def test_v1_v2_recompute_session_identity_contract_restored(self):
        self.write([meta(), usage()])
        v2 = self.root / 'v2.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--format', 'json', '--export', 'json', '--output', str(v2))
        # The single-session report contract: restating the saved session stays legal for v2...
        same = json.loads(self.run_cli('recompute', '--saved', str(v2), '--session', 's',
                                       '--format', 'json').stdout)
        self.assertEqual(same['scope']['session'], 's')
        self.assertEqual(same['summary']['metrics']['input']['value'], 100)
        # ...and so it does for a legal v1 report.
        old = {k: v for k, v in json.loads(v2.read_text()).items()
               if k not in ('localization', 'internal_support', 'views', 'explanation')}
        for collection in ('records', 'unassigned_records'):
            for record in old.get(collection, []):
                record.pop('explanation', None)
        old['format_version'] = 1
        v1 = self.root / 'v1.json'
        v1.write_text(json.dumps(old))
        same_v1 = json.loads(self.run_cli('recompute', '--saved', str(v1), '--session', 's',
                                          '--format', 'json').stdout)
        self.assertEqual(same_v1['scope']['session'], 's')
        # A different session, or any cross-session set, is still explicitly rejected.
        self.run_cli('recompute', '--saved', str(v2), '--session', 'other', codes=(4,))
        self.run_cli('recompute', '--saved', str(v2), '--session', 's', '--session', 'other', codes=(4,))
        self.run_cli('recompute', '--saved', str(v1), '--session', 'other', codes=(4,))

    def test_overview_duplicate_session_ids_normalize_to_one_set(self):
        self.write([meta('a'), meta('b'), usage('r1', sid='a', inp=100),
                    usage('r2', sid='b', inp=200, cache=0, time='2026-09-01T00:00:20Z')])
        single = self.overview('--session', 'a')
        duplicate = self.overview('--session', 'a', '--session', 'a')
        self.assertEqual(duplicate['scope']['sessions'], ['a'])
        self.assertEqual(duplicate['localization']['sessions']['count'], 1)
        self.assertEqual(duplicate['localization']['sessions']['evidence'], '显式指定的会话集合（1 个会话）')
        self.assertEqual(duplicate['summary']['metrics']['input']['value'],
                         single['summary']['metrics']['input']['value'])
        both = self.overview('--session', 'a', '--session', 'b')
        repeated = self.overview('--session', 'a', '--session', 'b', '--session', 'a')
        self.assertEqual(repeated['scope']['sessions'], both['scope']['sessions'])
        self.assertEqual(repeated['summary']['metrics']['input']['value'], 300)
        # The exported JSON stays consistent for show/browser reload, and a v3 update set
        # containing duplicates normalizes the same way.
        saved = self.root / 'dup.json'
        self.run_cli('overview', '--source', str(self.log), '--session', 'a', '--session', 'a',
                     '--to', END, '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['scope']['sessions'], ['a'])
        self.assertEqual(shown['localization']['sessions']['count'], 1)
        updated = json.loads(self.run_cli('recompute', '--saved', str(saved), '--update',
                                          '--session', 'b', '--session', 'b', '--to', END,
                                          '--format', 'json').stdout)
        self.assertEqual(updated['scope']['sessions'], ['b'])
        self.assertEqual(updated['summary']['metrics']['input']['value'], 200)

    def test_duplicate_midnight_fold_buckets_to_the_calendar_day(self):
        # Cuba 2026-11-01 falls back: 04:10Z and 05:10Z are both local 00:10 (fold 0/1).
        def count(total, time):
            return {'type': 'event_msg', 'timestamp': time,
                    'payload': {'type': 'token_count', 'info': {'total_token_usage': total}}}
        zero = {'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0}
        delta = {'input_tokens': 100, 'output_tokens': 0, 'cached_input_tokens': 0}
        self.write([meta('s'), count(zero, '2026-11-01T04:10:00Z'), count(delta, '2026-11-01T05:10:00Z')])
        result = self.overview('--from', '2026-11-01T04:00:00Z', '--to', '2026-11-02T05:00:00Z',
                               '--tz', 'America/Havana')
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['unbucketed']['records'], 0)
        self.assertEqual([(d['date'], d['metrics']['input']['value']) for d in result['days']],
                         [('2026-11-01', 100)])
        day = result['days'][0]
        self.assertEqual(day['from'], '2026-11-01T04:00:00Z')
        self.assertEqual(day['to'], '2026-11-02T00:00:00-05:00')
        # A cumulative interval that passes the scope filter but crosses this day's lower
        # bound (ends in Nov 2 local, started before its midnight) stays unbucketed.
        self.write([meta('s'), count(zero, '2026-11-01T04:10:00Z'), count(delta, '2026-11-02T05:30:00Z')])
        result = self.overview('--from', '2026-11-01T04:00:00Z', '--to', '2026-11-03T05:00:00Z',
                               '--tz', 'America/Havana')
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(result['days'], [])
        self.assertEqual(result['unbucketed']['records'], 1)
        self.assertEqual(result['unbucketed']['metrics']['input']['value'], 100)

    def test_microsecond_bounds_survive_days_export_reopen_and_bad_order_rejected(self):
        self.write([meta('a'),
                    usage('r1', sid='a', turn='t', inp=100, cache=0, time='2026-03-08T12:00:00.400000Z'),
                    usage('r2', sid='a', turn='t', inp=900, cache=0, time='2026-03-08T12:00:00.500002Z')])
        args = ('--from', '2026-03-08T12:00:00.123456Z', '--to', '2026-03-08T12:00:00.500001Z', '--tz', 'UTC')
        result = self.overview(*args)
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)
        self.assertEqual(len(result['days']), 1)
        self.assertEqual(result['days'][0]['from'], '2026-03-08T12:00:00.123456Z')
        self.assertEqual(result['days'][0]['to'], '2026-03-08T12:00:00.500001Z')
        self.assertEqual(result['days'][0]['metrics']['input']['value'], 100)
        saved = self.root / 'micro.json'
        self.run_cli('overview', '--source', str(self.log), *args, '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['days'][0]['from'], '2026-03-08T12:00:00.123456Z')
        self.assertEqual(shown['days'][0]['to'], '2026-03-08T12:00:00.500001Z')
        # Equal scope bounds are rejected before any bucketing.
        self.run_cli('overview', '--source', str(self.log), '--from', '2026-03-08T12:00:00.123456Z',
                     '--to', '2026-03-08T12:00:00.123456Z', '--format', 'json', codes=(4,))
        # Day rows whose intersection range is equal or reversed fail validation on reopen,
        # including one instant spelled with two different numeric offsets.
        tampered_cases = ({'from': '2026-03-08T12:00:00.500001Z'},                    # equal
                          {'from': '2026-03-08T12:00:00.500002Z'},                    # reversed
                          {'from': '2026-03-08T13:00:00.500001+01:00'})               # equal, other offset
        for index, mutation in enumerate(tampered_cases):
            tampered = json.loads(saved.read_text())
            tampered['days'][0].update(mutation)
            tampered_path = self.root / ('tampered-%d.json' % index)
            tampered_path.write_text(json.dumps(tampered))
            self.run_cli('show', '--saved', str(tampered_path), codes=(4,))

    def test_day_row_ranges_cover_dst_transitions_and_intersections(self):
        # US DST start 2026-03-08: EST (-05:00) springs forward to EDT (-04:00) at 02:00 local.
        self.write([meta('s'),
                    usage('am', sid='s', inp=100, cache=0, time='2026-03-08T10:00:00-05:00'),
                    usage('next', sid='s', inp=900, cache=0, time='2026-03-09T00:30:00-04:00')])
        result = self.overview('--from', '2026-03-08T00:00:00-05:00', '--to', '2026-03-10T00:00:00-04:00',
                               '--tz', 'America/New_York')
        days = {day['date']: day for day in result['days']}
        self.assertEqual(days['2026-03-08']['metrics']['input']['value'], 100)
        self.assertEqual(days['2026-03-09']['metrics']['input']['value'], 900)
        # The next local midnight resolves its own offset (EDT -04:00), so the day-03-08
        # intersection cannot swallow the next-day 00:30 local record.
        self.assertEqual(days['2026-03-08']['from'], '2026-03-08T00:00:00-05:00')
        self.assertEqual(days['2026-03-08']['to'], '2026-03-09T00:00:00-04:00')
        self.assertEqual(days['2026-03-09']['from'], '2026-03-09T00:00:00-04:00')
        self.assertEqual(days['2026-03-09']['to'], '2026-03-10T00:00:00-04:00')
        # US DST end 2026-11-01: EDT (-04:00) falls back to EST (-05:00); the 25-hour day
        # keeps both midnights' own offsets.
        self.write([meta('s'),
                    usage('fall', sid='s', inp=50, cache=0, time='2026-11-01T12:00:00-04:00'),
                    usage('late', sid='s', inp=60, cache=0, time='2026-11-01T23:30:00-05:00')])
        result = self.overview('--from', '2026-11-01T00:00:00-04:00', '--to', '2026-11-03T00:00:00-05:00',
                               '--tz', 'America/New_York')
        day = result['days'][0]
        self.assertEqual(day['date'], '2026-11-01')
        self.assertEqual(day['metrics']['input']['value'], 110)
        self.assertEqual(day['from'], '2026-11-01T00:00:00-04:00')
        self.assertEqual(day['to'], '2026-11-02T00:00:00-05:00')
        # UTC: a midday lower bound is the intersection lower bound (original spelling kept),
        # and the following midnight is the upper bound.
        self.write([meta('s'), usage('m', sid='s', inp=100, cache=0, time='2026-09-01T09:00:00Z'),
                    usage('a', sid='s', inp=200, cache=0, time='2026-09-01T15:00:00Z')])
        result = self.overview('--from', '2026-09-01T12:00:00Z', '--to', '2026-09-02T00:00:00Z', '--tz', 'UTC')
        day = result['days'][0]
        self.assertEqual(day['metrics']['input']['value'], 200)
        self.assertEqual(day['from'], '2026-09-01T12:00:00Z')
        self.assertEqual(day['to'], '2026-09-02T00:00:00+00:00')
        # Fixed offset: local dates and midnights follow +08:00.
        result = self.overview('--from', '2026-09-01T12:00:00+08:00', '--to', '2026-09-02T00:00:00+08:00',
                               '--tz', '+08:00')
        day = result['days'][0]
        self.assertEqual(day['date'], '2026-09-01')
        self.assertEqual(day['metrics']['input']['value'], 300)
        self.assertEqual(day['from'], '2026-09-01T12:00:00+08:00')
        self.assertEqual(day['to'], '2026-09-02T00:00:00+08:00')
        # A cutoff inside the day is that day's upper bound, with its original spelling;
        # [from,to) stays left-closed right-open, so the 15:00Z record is excluded.
        result = self.overview('--from', '2026-09-01T00:00:00Z', '--to', '2026-09-01T15:00:00Z', '--tz', 'UTC')
        day = result['days'][0]
        self.assertEqual(day['to'], '2026-09-01T15:00:00Z')
        self.assertEqual(day['metrics']['input']['value'], 100)
        # The day ranges are part of the saved v3 contract and survive export/reload.
        saved = self.root / 'ranges.json'
        self.run_cli('overview', '--source', str(self.log), '--from', '2026-09-01T12:00:00Z',
                     '--to', '2026-09-02T00:00:00Z', '--tz', 'UTC',
                     '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['days'][0]['from'], '2026-09-01T12:00:00Z')
        self.assertEqual(shown['days'][0]['to'], '2026-09-02T00:00:00+00:00')
        broken = json.loads(saved.read_text())
        del broken['days'][0]['to']
        broken_path = self.root / 'broken.json'
        broken_path.write_text(json.dumps(broken))
        self.run_cli('show', '--saved', str(broken_path), codes=(4,))

    def test_overview_cache_rate_uses_paired_subset_denominator(self):
        # Total input 1000 (10 records); only one record pairs input with cache (100/50),
        # so the rate denominator is the paired input 100 — never the total input.
        rows = [meta('s')]
        for i in range(9):
            rows.append(usage(f'r{i}', sid='s', inp=100, cache=None, time=f'2026-09-01T00:{i:02d}:00Z'))
        rows.append(usage('p', sid='s', inp=100, cache=50, time='2026-09-01T00:10:00Z'))
        self.write(rows)
        result = self.overview()
        self.assertEqual(result['summary']['metrics']['input']['value'], 1000)
        rate = result['summary']['cache_hit_rate']
        self.assertEqual(rate['value'], 0.5)
        self.assertEqual(rate['paired_records'], 1)
        self.assertEqual(rate['input'], 100)
        self.assertEqual(rate['cache_read'], 50)
        self.assertEqual(rate['state'], 'partial')
        # The same paired-subset口径 carries the day bucket and ranking rows.
        day_rate = result['days'][0]['cache_hit_rate']
        self.assertEqual(day_rate['input'], 100)
        self.assertEqual(day_rate['paired_records'], 1)
        ranking_rate = result['rankings']['model']['rows'][0]['cache_hit_rate']
        self.assertEqual(ranking_rate['input'], 100)
        # Zero denominator and fully unknown subsets stay distinguishable from a rate of zero.
        self.write([meta('s'), usage('z', sid='s', inp=0, cache=0, output=0, time='2026-09-01T00:00:00Z')])
        zero = self.overview()
        self.assertEqual(zero['summary']['cache_hit_rate']['state'], 'not_applicable')
        self.assertIsNone(zero['summary']['cache_hit_rate']['value'])
        self.write([meta('s'), usage('u', sid='s', inp=100, cache=None, time='2026-09-01T00:00:00Z')])
        unknown = self.overview()
        self.assertEqual(unknown['summary']['cache_hit_rate']['state'], 'unknown')
        self.assertIsNone(unknown['summary']['cache_hit_rate']['value'])
        self.assertEqual(unknown['summary']['metrics']['cache_read']['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
