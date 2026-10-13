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
from fractions import Fraction
from datetime import datetime, timedelta
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / 'skills/agent-token-audit/scripts/audit.py'
T0 = '2026-09-01T00:00:00Z'
T1 = '2026-09-01T00:01:00Z'
END = '2026-09-02T00:00:00Z'


def meta(sid='s'):
    return {'type': 'session_meta', 'timestamp': T0, 'payload': {'id': sid, 'timestamp': T0, 'source': 'cli', 'cli_version': '0.153.4'}}


def pmeta(sid='s', provider='openai_http'):
    item = meta(sid)
    item['payload']['model_provider'] = provider
    return item


def tctx(turn='t1', model='gpt-6.1-sol'):
    return {'type': 'turn_context', 'timestamp': T0, 'payload': {'turn_id': turn, 'model': model}}


def pricing_cfg(rules, aliases=None, revision='test-rev-1'):
    return {'schema_version': 1, 'revision': revision, 'rules': rules, 'aliases': aliases or []}


def pricing_rule(rid, provider='openai_http', model='gpt-6.1-sol', currency='TST',
                 from_='2026-01-01T00:00:00Z', to=None, input_=None, output=None):
    rule = {'id': rid, 'source': {'reference': '测试价目', 'version': '2026-09'},
            'provider': provider, 'model': model, 'effective_from': from_, 'currency': currency,
            'input': input_ or {'kind': 'split_cache_read', 'non_cache_read_per_million': '10', 'cache_read_per_million': '2'},
            'output': output or {'kind': 'total_output', 'price_per_million': '20'}}
    if to:
        rule['effective_to'] = to
    return rule


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
               if k not in ('localization', 'internal_support', 'views', 'explanation', 'analysis')}
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
               if k not in ('localization', 'internal_support', 'views', 'explanation', 'analysis')}
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


class PricingCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-pricing-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'rollout.jsonl'

    def write(self, rows):
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))

    def write_pricing(self, cfg):
        path = self.root / 'pricing.json'
        path.write_text(json.dumps(cfg) if not isinstance(cfg, str) else cfg)
        return path

    def run_cli(self, *args, codes=(0, 2, 3)):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def priced(self, cfg, *args):
        pricing = self.write_pricing(cfg)
        proc = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                            '--pricing', str(pricing), '--format', 'json', *args)
        return json.loads(proc.stdout)

    def test_p3_a1_sample_priced_exactly_and_reasoning_not_double_charged(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        result = self.priced(pricing_cfg([pricing_rule('rule-a1')]))
        cost = result['analysis']['cost']
        entry = cost['records'][0]
        self.assertEqual(entry['status'], 'priced')
        self.assertEqual(entry['identity'], {'provider': 'openai_http', 'model': 'gpt-6.1-sol'})
        self.assertEqual(entry['matched'], {'rule_id': 'rule-a1', 'alias_id': None})
        components = {c['name']: c for c in entry['components']}
        self.assertEqual(components['non_cache_read'], {'name': 'non_cache_read', 'tokens': 600000,
                                                        'price_per_million': '10', 'amount': '6'})
        self.assertEqual(components['cache_read']['amount'], '0.8')
        self.assertEqual(components['output']['amount'], '2')
        # 30,000 reasoning tokens are already inside output: priced once, no second charge.
        self.assertNotIn('reasoning', components)
        bucket = cost['summary']['currencies']['TST']
        self.assertEqual(bucket['amount'], '8.8')
        self.assertEqual(bucket['components']['non_cache_read'], {'tokens': 600000, 'amount': '6'})
        self.assertEqual(cost['summary']['priced'], 1)
        table = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                             '--pricing', str(self.root / 'pricing.json'))
        self.assertIn('| TST | 8.8 | 8.80 |', table.stdout)

    def test_high_precision_cost_survives_export_reload_and_rejects_rounded_summary(self):
        inputs = [106968, 119931, 136711, 139978]
        self.write([pmeta(), tctx()] + [usage('r' + str(i), inp=n, cache=0, output=0)
                                      for i, n in enumerate(inputs)])
        price = '0.12345678901234567890123456789'
        cfg = pricing_cfg([pricing_rule('precise', input_={'kind': 'total_input', 'price_per_million': price},
                                        output={'kind': 'total_output', 'price_per_million': '0'})])
        saved = self.root / 'precise.json'
        result = self.priced(cfg, '--export', 'json', '--output', str(saved))
        amount = result['analysis']['cost']['summary']['currencies']['TST']['amount']
        self.assertEqual(Fraction(amount), sum(inputs) * Fraction(price) / 1000000)
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, result)
        # The formerly rounded summary must fail independent validation, not be accepted
        # because both the producer and validator used the same default Decimal context.
        result['analysis']['cost']['summary']['currencies']['TST']['amount'] = '0.06217135746514913574651491357'
        saved.write_text(json.dumps(result))
        self.run_cli('show', '--saved', str(saved), '--format', 'json', codes=(4,))

    def test_large_cost_display_and_csv_do_not_round_saved_amount(self):
        tokens = 10**40 + 7
        self.write([pmeta(), tctx(), usage(inp=tokens, cache=0, output=0)])
        cfg = pricing_cfg([pricing_rule('large', input_={'kind': 'total_input', 'price_per_million': '10'},
                                        output={'kind': 'total_output', 'price_per_million': '0'})])
        saved = self.root / 'large.json'
        result = self.priced(cfg, '--export', 'json', '--output', str(saved))
        amount = result['analysis']['cost']['summary']['currencies']['TST']['amount']
        self.assertEqual(Fraction(amount), Fraction(tokens, 100000))
        displayed = '1' + '0' * 35 + '.00'
        self.assertIn(displayed, self.run_cli('show', '--saved', str(saved)).stdout)
        exported = self.root / 'large.csv'
        self.run_cli('show', '--saved', str(saved), '--export', 'csv', '--output', str(exported))
        row = next(r for r in csv.DictReader(io.StringIO(exported.read_text())) if r['category'] == 'cost_summary')
        self.assertEqual(row['cost_amount_exact'], amount)
        self.assertEqual(row['cost_amount_display'], displayed)

    def test_pricing_saved_reload_recompute_reuse_and_explicit_reprice(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        saved = self.root / 'saved.json'
        first = self.priced(pricing_cfg([pricing_rule('rule-a1'),
                                         pricing_rule('rule-unused', model='other-model')]),
                            '--export', 'json', '--output', str(saved))
        # The snapshot keeps every rule, including ones no record hit.
        self.assertEqual([r['id'] for r in first['analysis']['cost']['config']['rules']], ['rule-a1', 'rule-unused'])
        self.assertEqual(json.loads(saved.read_text()), first)
        before = saved.read_bytes()
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, first)
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(recomputed['analysis']['cost']['summary']['currencies']['TST']['amount'], '8.8')
        self.assertEqual(recomputed['analysis']['cost']['config']['revision'], 'test-rev-1')
        repriced_cfg = pricing_cfg([pricing_rule('rule-a1', output={'kind': 'total_output', 'price_per_million': '40'})],
                                   revision='test-rev-2')
        repriced = json.loads(self.run_cli('recompute', '--saved', str(saved), '--pricing',
                                           str(self.write_pricing(repriced_cfg)), '--format', 'json').stdout)
        self.assertEqual(repriced['analysis']['cost']['summary']['currencies']['TST']['amount'], '10.8')
        self.assertEqual(repriced['analysis']['cost']['config']['revision'], 'test-rev-2')
        self.assertEqual(saved.read_bytes(), before)

    def test_invalid_pricing_rejected_before_source_read(self):
        self.write([pmeta(), tctx(), usage()])
        cases = {'null': 'null', 'empty': '', 'version': '{"schema_version": 2, "revision": "x", "rules": []}',
                 'price': json.dumps(pricing_cfg([pricing_rule('r', output={'kind': 'total_output',
                                                                            'price_per_million': '1.5.2'})])),
                 'window': json.dumps(pricing_cfg([pricing_rule('r', from_='2026-02-01T00:00:00Z',
                                                                to='2026-01-01T00:00:00Z')])),
                 'revision': json.dumps({'schema_version': 1, 'rules': []}),
                 'chain': json.dumps(pricing_cfg([], aliases=[
                     {'id': 'a1', 'source': {'reference': 'x', 'version': '1'}, 'basis': 'b',
                      'from': {'provider': 'p1', 'model': 'm1'}, 'to': {'provider': 'p2', 'model': 'm2'}},
                     {'id': 'a2', 'source': {'reference': 'x', 'version': '1'}, 'basis': 'b',
                      'from': {'provider': 'p2', 'model': 'm2'}, 'to': {'provider': 'p3', 'model': 'm3'}}]))}
        self.log.rename(self.root / 'moved.jsonl')  # any source error would mask pre-source rejection
        for name, text in cases.items():
            with self.subTest(name=name):
                path = self.write_pricing(text)
                proc = self.run_cli('report', '--source', str(self.log), '--session', 's',
                                    '--pricing', str(path), codes=(4,))
                self.assertIn('价格配置', proc.stderr)
        (self.root / 'moved.jsonl').rename(self.log)

    def test_pricing_rejected_on_listings_show_and_export_target(self):
        self.write([pmeta(), tctx(), usage()])
        pricing = self.write_pricing(pricing_cfg([pricing_rule('rule-a1')]))
        for operation in ('sessions', 'turns', 'requests'):
            self.run_cli(operation, '--source', str(self.log), '--session', 's',
                         '--pricing', str(pricing), codes=(4,))
        saved = self.root / 'saved.json'
        self.priced(pricing_cfg([pricing_rule('rule-a1')]), '--export', 'json', '--output', str(saved))
        self.run_cli('show', '--saved', str(saved), '--pricing', str(pricing), codes=(4,))
        before = pricing.read_bytes()
        proc = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                            '--pricing', str(pricing), '--export', 'json', '--output', str(pricing), codes=(4,))
        self.assertIn('冲突', proc.stderr)
        self.assertEqual(pricing.read_bytes(), before)

    def test_same_model_different_provider_and_no_suffix_matching(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        # Same model name under another provider, or a truncated model identity, never matches.
        cfg = pricing_cfg([pricing_rule('other-provider', provider='openai'),
                           pricing_rule('truncated', model='gpt-6.1')])
        result = self.priced(cfg)
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'unpriced')
        self.assertTrue(any('无匹配' in item['reason'] for item in entry['unpriced']))
        self.assertEqual(result['analysis']['cost']['summary']['currencies'], {})

    def test_effective_windows_match_record_time_not_current_clock(self):
        self.write([pmeta(), tctx(), usage('r1', inp=1000000, cache=0, output=0, time='2026-09-01T00:01:00Z'),
                    usage('r2', inp=1000000, cache=0, output=0, time='2026-10-01T00:01:00Z'),
                    usage('r3', inp=1000000, cache=0, output=0, time='2026-11-01T00:01:00Z')])
        old = pricing_rule('old-price', to='2026-10-01T00:00:00Z',
                           input_={'kind': 'total_input', 'price_per_million': '10'})
        new = pricing_rule('new-price', from_='2026-10-01T00:00:00Z', to='2026-11-01T00:00:00Z',
                           input_={'kind': 'total_input', 'price_per_million': '20'})
        result = self.priced(pricing_cfg([old, new]), '--to', '2026-12-01T00:00:00Z')
        entries = {e['record_key']: e for e in result['analysis']['cost']['records']}
        self.assertEqual(entries['codex:s:r1']['matched']['rule_id'], 'old-price')
        self.assertEqual(entries['codex:s:r1']['components'][0]['amount'], '10')
        self.assertEqual(entries['codex:s:r2']['matched']['rule_id'], 'new-price')
        self.assertEqual(entries['codex:s:r2']['components'][0]['amount'], '20')
        self.assertEqual(entries['codex:s:r3']['status'], 'unpriced')

    def test_overlapping_rules_conflict_but_other_identity_stays_priced(self):
        self.write([pmeta(), tctx(), usage('r1', inp=1000000, cache=0, output=0),
                    tctx(turn='t2', model='other-model'),
                    usage('r2', turn='t2', inp=1000000, cache=0, output=0, time='2026-09-01T00:02:00Z')])
        cfg = pricing_cfg([pricing_rule('overlap-1'), pricing_rule('overlap-2'),
                           pricing_rule('distinct', model='other-model')])
        result = self.priced(cfg)
        entries = {e['record_key']: e for e in result['analysis']['cost']['records']}
        conflict = entries['codex:s:r1']
        self.assertEqual(conflict['status'], 'rule_conflict')
        self.assertEqual(conflict['conflicts'], ['overlap-1', 'overlap-2'])
        self.assertIsNone(conflict['matched'])
        self.assertEqual(entries['codex:s:r2']['status'], 'priced')
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['TST']['amount'], '10')
        self.assertEqual(result['analysis']['cost']['summary']['rule_conflicts'], 1)

    def test_currencies_subtotaled_separately(self):
        self.write([pmeta(), tctx(), usage('r1', inp=1000000, cache=0, output=0),
                    tctx(turn='t2', model='other-model'),
                    usage('r2', turn='t2', inp=1000000, cache=0, output=0, time='2026-09-01T00:02:00Z')])
        cfg = pricing_cfg([pricing_rule('tst', currency='TST'),
                           pricing_rule('usd', model='other-model', currency='USD')])
        result = self.priced(cfg)
        currencies = result['analysis']['cost']['summary']['currencies']
        self.assertEqual(currencies['TST']['amount'], '10')
        self.assertEqual(currencies['USD']['amount'], '10')

    def test_partial_pricing_keeps_priced_components(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=None, output=100000)])
        result = self.priced(pricing_cfg([pricing_rule('rule-a1')]))
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'partially_priced')
        self.assertEqual([c['name'] for c in entry['components']], ['output'])
        self.assertEqual({item['component'] for item in entry['unpriced']}, {'non_cache_read', 'cache_read'})
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['TST']['amount'], '2')

    def test_zero_price_zero_usage_missing_price_and_no_records_distinguishable(self):
        zero_price = pricing_rule('zero-price', input_={'kind': 'total_input', 'price_per_million': '0'},
                                  output={'kind': 'total_output', 'price_per_million': '0'})
        self.write([pmeta(), tctx(), usage('r1', inp=1000000, cache=0, output=100000),
                    tctx(turn='t2', model='other-model'),
                    usage('r2', turn='t2', inp=0, cache=0, output=0, time='2026-09-01T00:02:00Z'),
                    tctx(turn='t3', model='unpriced-model'),
                    usage('r3', turn='t3', inp=1000000, cache=0, output=0, time='2026-09-01T00:03:00Z')])
        cfg = pricing_cfg([zero_price, pricing_rule('zero-usage', model='other-model')])
        result = self.priced(cfg)
        entries = {e['record_key']: e for e in result['analysis']['cost']['records']}
        self.assertEqual(entries['codex:s:r1']['status'], 'priced')
        # 确认零价格（单价 0，金额 0）与确认零用量（token 全 0，金额 0）都是已计价零，与缺价可辨。
        self.assertTrue(all(c['amount'] == '0' for c in entries['codex:s:r1']['components']))
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['TST']['amount'], '0')
        priced_zero = entries['codex:s:r2']
        self.assertEqual(priced_zero['status'], 'priced')
        self.assertTrue(all(c['amount'] == '0' for c in priced_zero['components']))
        self.assertEqual(entries['codex:s:r3']['status'], 'unpriced')

    def test_split_partitions_and_uncertain_cache_write_zero(self):
        write_split = {'kind': 'split_cache_read_write', 'other_input_per_million': '10',
                       'cache_read_per_million': '2', 'cache_write_per_million': '30',
                       'basis': '来源证据：三者互斥（测试构造）'}
        reasoning_split = {'kind': 'split_reasoning', 'other_output_per_million': '20',
                           'reasoning_per_million': '20', 'basis': '来源证据：推理包含于输出（测试构造）'}
        rich = usage('r1', inp=1000000, cache=400000, output=100000)
        rich['payload']['usage']['reasoning_output_tokens'] = 30000
        self.write([pmeta(), tctx(), rich])
        # codex 的 cache_write=0 语义未确认：互斥三分区缺已知 token，其他分项保留计价。
        result = self.priced(pricing_cfg([pricing_rule('w', input_=write_split, output=reasoning_split)]))
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'partially_priced')
        self.assertEqual({c['name'] for c in entry['components']}, {'cache_read', 'other_output', 'reasoning'})
        amounts = {c['name']: c['amount'] for c in entry['components']}
        self.assertEqual(amounts['other_output'], '1.4')
        self.assertEqual(amounts['reasoning'], '0.6')
        # 明确非零缓存写入时，其他输入 = 输入 − 缓存读取 − 缓存写入。
        row = usage('r2', inp=1000000, cache=400000, output=0)
        row['payload']['usage']['cache_write_input_tokens'] = 100000
        self.write([pmeta(), tctx(), row])
        result = self.priced(pricing_cfg([pricing_rule('w', input_=write_split)]))
        amounts = {c['name']: c['amount'] for c in result['analysis']['cost']['records'][0]['components']}
        self.assertEqual(amounts, {'other_input': '5', 'cache_read': '0.8', 'cache_write': '3', 'output': '0'})

    def test_alias_maps_once_with_basis(self):
        self.write([pmeta(), tctx(model='legacy-name'), usage(inp=1000000, cache=0, output=0)])
        alias = {'id': 'alias-1', 'source': {'reference': '供应商文档', 'version': '2026-08'},
                 'from': {'provider': 'openai_http', 'model': 'legacy-name'},
                 'to': {'provider': 'openai_http', 'model': 'gpt-6.1-sol'}, 'basis': '供应商更名单（测试构造）'}
        result = self.priced(pricing_cfg([pricing_rule('rule-a1')], aliases=[alias]))
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'priced')
        self.assertEqual(entry['matched'], {'rule_id': 'rule-a1', 'alias_id': 'alias-1'})

    def test_missing_identity_and_unverified_provider_stay_unpriced(self):
        # 累计区间记录无明确身份绑定；ZCode 未验证供应商的 usage 语义未知，均不猜价。
        def count(total, time):
            return {'type': 'event_msg', 'timestamp': time, 'payload': {'type': 'token_count', 'info': {
                'total_token_usage': {'input_tokens': total, 'output_tokens': 0, 'cached_input_tokens': 0,
                                      'total_tokens': total}}}}
        self.write([pmeta(), count(0, T0), count(1000000, T1)])
        result = self.priced(pricing_cfg([pricing_rule('rule-a1')]))
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'unpriced')
        self.assertTrue(any('身份' in item['reason'] for item in entry['unpriced']))
        self.write([{'sessionId': 's', 'requestId': 'r', 'attempt': 1, 'turnId': 't1', 'querySource': 'main_turn',
                     'completedAt': T1, 'model': {'providerId': 'bigmodel', 'modelId': 'GLM-5.3'},
                     'response': {'usage': {'inputTokens': 100, 'outputTokens': 10, 'cacheReadTokens': 90,
                                            'totalTokens': 110}}}])
        result = self.priced(pricing_cfg([pricing_rule('glm', provider='bigmodel', model='GLM-5.3')]),
                             '--harness', 'zcode')
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['status'], 'unpriced')
        self.assertTrue(any('尚未验证' in item['reason'] for item in entry['unpriced']))

    def test_saved_pricing_identity_and_alias_references_must_agree(self):
        for use_alias in (False, True):
            model = 'legacy-name' if use_alias else 'gpt-6.1-sol'
            self.write([pmeta(), tctx(model=model), usage()])
            alias = {'id': 'alias-1', 'source': {'reference': '测试更名依据', 'version': '1'},
                     'from': {'provider': 'openai_http', 'model': 'legacy-name'},
                     'to': {'provider': 'openai_http', 'model': 'gpt-6.1-sol'}, 'basis': '明确更名'}
            other_alias = json.loads(json.dumps(alias))
            other_alias['from']['model'] = 'unused-name'
            base = self.priced(pricing_cfg([pricing_rule('rule-a1')],
                                          aliases=[alias, other_alias] if use_alias else []))
            saved = self.root / 'identity.json'
            saved.write_text(json.dumps(base))
            self.run_cli('show', '--saved', str(saved))
            mutations = [
                ('rule-provider', lambda c: c['config']['rules'][0].__setitem__('provider', 'different-provider')),
                ('rule-model', lambda c: c['config']['rules'][0].__setitem__('model', 'different-model')),
                ('record-identity', lambda c: c['records'][0]['identity'].__setitem__('provider', 'different-provider')),
            ]
            if use_alias:
                mutations.extend([
                    ('alias-from', lambda c: c['config']['aliases'][0]['from'].__setitem__('model', 'different-model')),
                    ('alias-to', lambda c: c['config']['aliases'][0]['to'].__setitem__('model', 'different-model')),
                    ('alias-omitted', lambda c: c['records'][0]['matched'].__setitem__('alias_id', None)),
                ])
            for name, mutate in mutations:
                with self.subTest(alias=use_alias, mutation=name):
                    bad = json.loads(json.dumps(base))
                    mutate(bad['analysis']['cost'])
                    saved.write_text(json.dumps(bad))
                    rejected = self.run_cli('show', '--saved', str(saved), codes=(4,))
                    self.assertIn('身份', rejected.stderr)

    def test_tampered_analysis_and_v1_extension_rejected(self):
        self.write([pmeta(), tctx(), usage()])
        saved = self.root / 'saved.json'
        self.priced(pricing_cfg([pricing_rule('rule-a1')]), '--export', 'json', '--output', str(saved))
        base = json.loads(saved.read_text())
        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            path = self.root / ('bad-' + name + '.json')
            path.write_text(json.dumps(data))
            self.run_cli('show', '--saved', str(path), codes=(4,))
        reject(lambda d: d['analysis']['cost']['summary']['currencies']['TST'].__setitem__('amount', '999'), 'amount')
        reject(lambda d: d['analysis']['cost']['records'][0]['components'][0].__setitem__('tokens', 5), 'tokens')
        reject(lambda d: d['analysis']['cost']['records'][0].__setitem__('matched', {'rule_id': 'ghost', 'alias_id': None}), 'rule')
        reject(lambda d: d['analysis']['cost']['records'].pop(), 'coverage')
        reject(lambda d: d['analysis'].__setitem__('schema_version', 2), 'extversion')
        old = {k: v for k, v in base.items() if k not in ('localization', 'internal_support', 'views', 'explanation')}
        for collection in ('records', 'unassigned_records'):
            for record in old.get(collection, []):
                record.pop('explanation', None)
        old['format_version'] = 1
        v1 = self.root / 'v1.json'
        v1.write_text(json.dumps(old))
        self.run_cli('show', '--saved', str(v1), codes=(4,))

    def test_consistent_cost_tampering_cannot_change_metered_partition(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        result = self.priced(pricing_cfg([pricing_rule('rule-a1')]))
        cost = result['analysis']['cost']
        component = cost['records'][0]['components'][0]
        component['tokens'] += 1000000
        component['amount'] = '16'
        bucket = cost['summary']['currencies']['TST']
        bucket['amount'] = '18.8'
        bucket['components']['non_cache_read'] = {'tokens': 1600000, 'amount': '16'}
        saved = self.root / 'consistent-tampering.json'
        saved.write_text(json.dumps(result))
        proc = self.run_cli('show', '--saved', str(saved), codes=(4,))
        self.assertIn('计价分区', proc.stderr)

    def test_overview_accepts_pricing_and_saves_v3_extension(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        pricing = self.write_pricing(pricing_cfg([pricing_rule('rule-a1')]))
        proc = self.run_cli('overview', '--source', str(self.log), '--to', END,
                            '--pricing', str(pricing), '--format', 'json')
        result = json.loads(proc.stdout)
        self.assertEqual(result['format_version'], 3)
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['TST']['amount'], '8.8')
        saved = self.root / 'overall.json'
        self.run_cli('overview', '--source', str(self.log), '--to', END,
                     '--pricing', str(pricing), '--export', 'json', '--output', str(saved))
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown['analysis']['cost']['summary']['currencies']['TST']['amount'], '8.8')

    def test_zcode_database_pricing_uses_db_provider_and_model_identity(self):
        path = self.root / 'db.sqlite'
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
                    json.dumps({'inputTokens': 1000000, 'outputTokens': 100000, 'cacheReadTokens': 400000,
                                'totalTokens': 1100000})))
        db.commit(); db.close()
        cfg = pricing_cfg([pricing_rule('glm', provider='builtin:bigmodel-coding-plan', model='GLM-5.3')])
        pricing = self.write_pricing(cfg)
        proc = self.run_cli('report', '--harness', 'zcode', '--database', str(path), '--session', 's',
                            '--to', END, '--pricing', str(pricing), '--format', 'json')
        result = json.loads(proc.stdout)
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['identity'], {'provider': 'builtin:bigmodel-coding-plan', 'model': 'GLM-5.3'})
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['TST']['amount'], '8.8')


class OverviewPricingCLI(unittest.TestCase):
    """v3 overall cost projections: model/session/day members and the unbucketed item."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-ovpricing-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'rollout.jsonl'
        # Two sessions keep the same model name under different providers (full pricing
        # identity); a third session contributes a cross-day cumulative interval with no
        # identity binding: unpriced, and its priced amounts can only live in 无法归日.
        rows = [pmeta('s1'), tctx(), usage('r1', sid='s1', inp=1000000, cache=400000, output=100000,
                                           time='2026-09-01T00:01:00Z'),
                pmeta('s2', provider='openai'), tctx(),
                usage('r2', sid='s2', inp=1000000, cache=0, output=0, time='2026-09-02T00:01:00Z'),
                meta('s3'),
                {'type': 'event_msg', 'timestamp': '2026-09-01T00:00:00Z', 'payload': {'type': 'token_count',
                 'info': {'total_token_usage': {'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0,
                                                'total_tokens': 0}}}},
                {'type': 'event_msg', 'timestamp': '2026-09-02T00:00:30Z', 'payload': {'type': 'token_count',
                 'info': {'total_token_usage': {'input_tokens': 500000, 'output_tokens': 0, 'cached_input_tokens': 0,
                                                'total_tokens': 500000}}}}]
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))
        # Independent hand computation from the raw integers above (no product aggregation):
        # r1: 600000×10/1e6 + 400000×2/1e6 + 100000×20/1e6 = 6 + 0.8 + 2 = 8.8 TST；
        # r2: 1000000×5/1e6 + 0×0 = 5 USD；区间记录缺身份未定价。
        usd_output = {'kind': 'total_output', 'price_per_million': '0'}
        self.cfg = pricing_cfg([pricing_rule('tst-rule'),
                                pricing_rule('usd-rule', provider='openai', currency='USD',
                                             input_={'kind': 'total_input', 'price_per_million': '5'},
                                             output=usd_output)])
        self.pricing = self.root / 'pricing.json'
        self.pricing.write_text(json.dumps(self.cfg))

    def run_cli(self, *args, codes=(0, 2, 3)):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def overview(self, *args):
        proc = self.run_cli('overview', '--source', str(self.log), '--to', '2026-09-03T00:00:00Z',
                            '--tz', '+00:00', '--pricing', str(self.pricing), '--format', 'json', *args)
        return json.loads(proc.stdout)

    def test_high_precision_cost_projections_and_independent_reload(self):
        inputs = [19999, 29999]
        rows = []
        for i, tokens in enumerate(inputs, 1):
            sid = 's' + str(i)
            rows += [pmeta(sid), tctx(), usage('r' + str(i), sid=sid, inp=tokens, cache=0, output=0,
                                            time='2026-09-0%dT00:01:00Z' % i)]
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))
        price = '0.12345678901234567890123456789'
        self.pricing.write_text(json.dumps(pricing_cfg([
            pricing_rule('precise', input_={'kind': 'total_input', 'price_per_million': price},
                         output={'kind': 'total_output', 'price_per_million': '0'})])))
        saved = self.root / 'precise-overview.json'
        result = self.overview('--export', 'json', '--output', str(saved))
        cost = result['analysis']['cost']
        expected = sum(inputs) * Fraction(price) / 1000000
        self.assertEqual(Fraction(cost['summary']['currencies']['TST']['amount']), expected)
        self.assertEqual(Fraction(cost['projections']['model'][0]['currencies']['TST']['amount']), expected)
        for dimension in ('session', 'day'):
            members = cost['projections'][dimension]
            self.assertEqual([Fraction(m['currencies']['TST']['amount']) for m in members],
                             [n * Fraction(price) / 1000000 for n in inputs])
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, result)
        cost['projections']['model'][0]['currencies']['TST']['amount'] = '0'
        saved.write_text(json.dumps(result))
        self.run_cli('show', '--saved', str(saved), '--format', 'json', codes=(4,))

    def test_overview_projections_by_currency_model_session_and_day(self):
        result = self.overview()
        self.assertEqual(result['format_version'], 3)
        cost = result['analysis']['cost']
        currencies = cost['summary']['currencies']
        self.assertEqual(currencies['TST']['amount'], '8.8')
        self.assertEqual(currencies['USD']['amount'], '5')
        self.assertEqual((cost['summary']['records'], cost['summary']['priced'], cost['summary']['unpriced']), (3, 2, 1))
        projections = cost['projections']
        models = {(m['identity']['provider'], m['identity']['model']): m for m in projections['model']}
        # Same model name under two providers stays two full pricing identities.
        self.assertEqual(set(models), {('openai_http', 'gpt-6.1-sol'), ('openai', 'gpt-6.1-sol')})
        self.assertEqual(models[('openai_http', 'gpt-6.1-sol')]['currencies']['TST']['amount'], '8.8')
        self.assertEqual(models[('openai_http', 'gpt-6.1-sol')]['record_keys'], ['codex:s1:r1'])
        self.assertEqual(models[('openai', 'gpt-6.1-sol')]['currencies']['USD']['amount'], '5')
        sessions = {m['session']: m for m in projections['session']}
        self.assertEqual(set(sessions), {'s1', 's2'})
        self.assertEqual(sessions['s1']['currencies']['TST']['amount'], '8.8')
        self.assertEqual(sessions['s2']['currencies']['USD']['amount'], '5')
        days = {m['date']: m for m in projections['day']}
        self.assertEqual(set(days), {'2026-09-01', '2026-09-02'})
        self.assertEqual(days['2026-09-01']['currencies']['TST']['amount'], '8.8')
        self.assertEqual(days['2026-09-01']['record_keys'], ['codex:s1:r1'])
        self.assertEqual(days['2026-09-02']['currencies']['USD']['amount'], '5')
        # 跨日累计区间无法归日：未定价、金额不分摊、不与日期视图相加。
        unbucketed = projections['unbucketed']
        self.assertEqual(len(unbucketed['record_keys']), 1)
        self.assertTrue(unbucketed['record_keys'][0].startswith('codex-interval:s3:'))
        self.assertEqual(unbucketed['currencies'], {})
        self.assertEqual(result['unbucketed']['record_keys'], unbucketed['record_keys'])
        interval = [e for e in cost['records'] if e['record_key'].startswith('codex-interval:')][0]
        self.assertEqual(interval['status'], 'unpriced')
        self.assertTrue(any('身份' in item['reason'] for item in interval['unpriced']))
        # 投影不再加出总金额：各投影成员之和只与币种小计对账。
        text = self.run_cli('overview', '--source', str(self.log), '--to', '2026-09-03T00:00:00Z',
                            '--tz', '+00:00', '--pricing', str(self.pricing)).stdout
        self.assertIn('费用投影', text)
        self.assertIn('无法归日：1 条', text)

    def test_overview_pricing_saved_reload_and_recompute_keep_projections(self):
        saved = self.root / 'overall.json'
        first = self.overview('--export', 'json', '--output', str(saved))
        self.assertEqual(json.loads(saved.read_text()), first)
        before = saved.read_bytes()
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, first)
        (self.root / 'pricing.json').write_text(json.dumps(pricing_cfg(
            [pricing_rule('tst-rule', output={'kind': 'total_output', 'price_per_million': '40'})],
            revision='test-rev-changed')))
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        # 本地改价不影响保存快照：重算沿用原规则，投影不变。
        projections = recomputed['analysis']['cost']['projections']
        days = {m['date']: m for m in projections['day']}
        self.assertEqual(days['2026-09-01']['currencies']['TST']['amount'], '8.8')
        self.assertEqual(days['2026-09-02']['currencies']['USD']['amount'], '5')
        self.assertEqual(recomputed['analysis']['cost']['config']['revision'], 'test-rev-1')
        self.assertEqual(saved.read_bytes(), before)

    def test_tampered_v3_projections_rejected(self):
        saved = self.root / 'overall.json'
        self.overview('--export', 'json', '--output', str(saved))
        base = json.loads(saved.read_text())

        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            path = self.root / ('bad-' + name + '.json')
            path.write_text(json.dumps(data))
            self.run_cli('show', '--saved', str(path), codes=(4,))

        reject(lambda d: d['analysis']['cost'].pop('projections'), 'missing')
        reject(lambda d: d['analysis']['cost']['projections']['model'][1]['currencies']['TST']
               .__setitem__('amount', '999'), 'modelamount')
        reject(lambda d: d['analysis']['cost']['projections']['day'].pop(), 'daymissing')
        reject(lambda d: d['analysis']['cost']['projections']['day'][0]
               .__setitem__('record_keys', ['codex:s1:ghost']), 'daykeys')
        reject(lambda d: d['analysis']['cost']['projections']['unbucketed']['currencies']
               .__setitem__('TST', {'amount': '1', 'components': {}}), 'unbucketed')
        reject(lambda d: d['analysis']['cost']['projections']['session'][0]
               .__setitem__('session', 's-ghost'), 'sessionid')
        reject(lambda d: d['analysis']['cost']['projections']['model'][0]
               .__setitem__('record_keys', ['codex:s1:r1', 'codex:s1:r1']), 'dupkeys')
        # v2 报告携带整体投影同样拒绝。
        v2 = self.root / 'v2.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's1', '--to', '2026-09-03T00:00:00Z',
                     '--pricing', str(self.pricing), '--export', 'json', '--output', str(v2))
        v2base = json.loads(v2.read_text())
        v2base['analysis']['cost']['projections'] = json.loads(json.dumps(base['analysis']['cost']['projections']))
        bad_v2 = self.root / 'bad-v2.json'
        bad_v2.write_text(json.dumps(v2base))
        self.run_cli('show', '--saved', str(bad_v2), codes=(4,))


PERF_T0 = 1788220800000  # 2026-09-01T00:00:00Z（毫秒）


def perf_usage(inp=1000, output=100):
    usage = {'inputTokens': inp, 'cacheReadTokens': 0}
    if output is not None:
        usage['outputTokens'] = output
        usage['totalTokens'] = inp + output
    return usage


def perf_database(path, rows):
    """ZCode DB with the first-token evidence columns (started/first/completed relative ms)."""
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
    CREATE TABLE model_usage (id TEXT,logical_request_id TEXT,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
    query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,first_token_at INTEGER,completed_at INTEGER,
    duration_ms INTEGER,time_to_first_token_ms INTEGER,tool_call_count INTEGER,retry_count INTEGER,raw_usage_json TEXT);
    CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);''')
    db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.9', None, PERF_T0, 'interactive'))
    db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('s', 't1', PERF_T0, PERF_T0 + 120000, 'completed', 1))
    for rid, status, started, first, completed, native, tools, retry, usage in rows:
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid, 'msg-' + rid, 0, 's', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    status, started, first, completed,
                    (completed - started) if completed is not None else None, native, tools, retry,
                    json.dumps(usage) if usage is not None else None))
    db.commit()
    db.close()
    return path


# 需求 P3-A4 样例：两条已完成调用（请求起点、首 token、区间终点）相对秒 (0,1,2) 与 (0,2,11)，输出各 100。
P34_ROWS = [('a', 'completed', PERF_T0, PERF_T0 + 1000, PERF_T0 + 2000, 1000, 0, 0, perf_usage()),
            ('b', 'completed', PERF_T0, PERF_T0 + 2000, PERF_T0 + 11000, 2000, 0, 0, perf_usage())]


class PerformanceCLI(unittest.TestCase):
    """Ticket 03: TTFT and source-observed-interval throughput over the ZCode DB entry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-perf-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = perf_database(self.root / 'db.sqlite', P34_ROWS)

    def run_cli(self, *args, codes=(0, 2, 3)):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def report(self, *args):
        proc = self.run_cli('report', '--harness', 'zcode', '--database', str(self.db), '--session', 's',
                            '--to', END, '--format', 'json', *args)
        return json.loads(proc.stdout)

    def test_native_ttft_column_is_optional_cross_check(self):
        with sqlite3.connect(self.db) as db:
            db.execute('ALTER TABLE model_usage DROP COLUMN time_to_first_token_ms')
        perf = self.report()['analysis']['performance']['metrics']
        self.assertEqual(perf['ttft']['support']['status'], 'supported')
        self.assertEqual((perf['ttft']['aggregate']['numerator'], perf['ttft']['aggregate']['denominator']), (3000, 2))
        self.assertEqual([s['basis'] for s in perf['ttft']['samples']], ['derived', 'derived'])
        self.assertEqual((perf['throughput']['aggregate']['numerator'], perf['throughput']['aggregate']['denominator']), (200, 10000))

    def test_p3_a4_ttft_and_aggregate_throughput(self):
        result = self.report('--no-pricing')
        # 独立预期（手算）：TTFT 1 秒、2 秒；聚合吞吐 200 ÷ (1000+9000) = 20 token/秒（不平均逐行速率）。
        perf = result['analysis']['performance']
        self.assertNotIn('cost', result['analysis'])  # 仅 token 模式不加载价格也可计算性能
        self.assertEqual(perf['harness'], 'zcode')
        self.assertEqual(perf['source_kind'], 'zcode_database')
        ttft = perf['metrics']['ttft']
        self.assertEqual(ttft['support']['status'], 'supported')
        self.assertEqual(ttft['aggregate']['candidates'], 2)
        self.assertEqual([s['value'] for s in ttft['samples']], [1000, 2000])
        self.assertEqual([s['basis'] for s in ttft['samples']], ['native', 'native'])
        self.assertEqual([s['record_key'] for s in ttft['samples']], ['zcode-db:a', 'zcode-db:b'])
        self.assertEqual((ttft['aggregate']['numerator'], ttft['aggregate']['denominator']), (3000, 2))
        throughput = perf['metrics']['throughput']
        self.assertIn('完成事件处理开销', throughput['overhead'])
        self.assertEqual([(s['output'], s['interval_ms']) for s in throughput['samples']], [(100, 1000), (100, 9000)])
        self.assertEqual((throughput['aggregate']['numerator'], throughput['aggregate']['denominator']), (200, 10000))
        # 分组/日分布由成员分子/分母重新生成；token 合计不受性能影响。
        self.assertEqual(throughput['projections']['model'][0]['numerator'], 200)
        self.assertEqual(throughput['projections']['model'][0]['denominator'], 10000)
        self.assertEqual(throughput['projections']['session'][0]['session'], 's')
        self.assertEqual(len(throughput['projections']['day']), 1)
        self.assertEqual(throughput['projections']['day'][0]['sample_keys'], ['zcode-db:a', 'zcode-db:b'])
        self.assertEqual(result['summary']['metrics']['input']['value'], 2000)
        self.assertEqual(result['summary']['metrics']['output']['value'], 200)
        table = self.run_cli('report', '--harness', 'zcode', '--database', str(self.db), '--session', 's', '--to', END)
        self.assertIn('模型性能', table.stdout)
        self.assertIn('有效样本均值 1500.00 ms', table.stdout)
        self.assertIn('聚合吞吐 20.00 token/秒', table.stdout)
        self.assertIn('含完成事件处理开销', table.stdout)

    def test_independent_sampling_exclusions_and_confirmed_zeros(self):
        rows = [('c', 'completed', PERF_T0 + 20000, PERF_T0 + 21000, PERF_T0 + 25000, 1000, 0, 0, perf_usage(output=None)),
                ('d', 'running', PERF_T0 + 30000, PERF_T0 + 31000, None, 1000, 0, 0, perf_usage(output=50)),
                ('e', 'completed', PERF_T0 + 40000, PERF_T0 + 41000, PERF_T0 + 42000, 999, 0, 0, perf_usage(output=10)),
                ('f', 'completed', PERF_T0 + 50000, PERF_T0 + 51000, PERF_T0 + 51000, 1000, 0, 0, perf_usage(output=10)),
                ('g', 'completed', PERF_T0 + 60000, PERF_T0 + 61000, PERF_T0 + 65000, 1000, 0, 1, perf_usage(output=10)),
                ('h', 'completed', PERF_T0 + 70000, PERF_T0 + 71000, PERF_T0 + 72000, 1000, 2, 0, perf_usage(output=10)),
                ('i', 'completed', PERF_T0 + 80000, PERF_T0 + 80000, PERF_T0 + 81000, 0, 0, 0, perf_usage(output=0)),
                ('l', 'completed', PERF_T0 + 90000, None, PERF_T0 + 95000, None, 0, 0, perf_usage(output=10))]
        self.db = perf_database(self.root / 'mixed.sqlite', rows)
        result = self.report()
        perf = result['analysis']['performance']
        ttft = perf['metrics']['ttft']
        # TTFT：c/d/f/g 有效（各 1000ms），i 确认零延迟保留；d 未完成但首 token 已在截止前，注明未完成。
        self.assertEqual({s['key']: s['value'] for s in ttft['samples']},
                         {'zcode-db:c': 1000, 'zcode-db:d': 1000, 'zcode-db:f': 1000, 'zcode-db:g': 1000, 'zcode-db:i': 0})
        self.assertEqual(next(s for s in ttft['samples'] if s['key'] == 'zcode-db:d')['completion'], 'no_end_evidence')
        self.assertIsNone(next(s for s in ttft['samples'] if s['key'] == 'zcode-db:d')['record_key'])  # 无对应 token 记录不伪造引用
        self.assertEqual((ttft['aggregate']['numerator'], ttft['aggregate']['denominator']), (4000, 5))
        self.assertEqual((ttft['aggregate']['valid'], ttft['aggregate']['excluded'], ttft['aggregate']['candidates']), (5, 3, 8))
        self.assertEqual(ttft['aggregate']['excluded_by_kind'], {'missing': 1, 'conflict': 1, 'unsupported': 1, 'range': 0})
        self.assertEqual(ttft['aggregate']['no_token_record'], 1)
        throughput = perf['metrics']['throughput']
        # 吞吐：e（原生 TTFT 冲突不影响吞吐，10÷1000）与 i（已知零输出、正区间得零吞吐）有效。
        self.assertEqual({s['key']: (s['output'], s['interval_ms']) for s in throughput['samples']},
                         {'zcode-db:e': (10, 1000), 'zcode-db:i': (0, 1000)})
        self.assertEqual((throughput['aggregate']['numerator'], throughput['aggregate']['denominator']), (10, 2000))
        self.assertEqual((throughput['aggregate']['valid'], throughput['aggregate']['excluded']), (2, 6))
        self.assertEqual(throughput['aggregate']['excluded_by_kind'], {'missing': 3, 'conflict': 1, 'unsupported': 2, 'range': 0})
        reasons = throughput['aggregate']['exclusion_reasons']
        self.assertTrue(any('输出 token' in r for r in reasons))       # c：缺 output 不影响其 TTFT
        self.assertTrue(any('区间终点' in r and '未完成' in r for r in reasons))  # d
        self.assertTrue(any('零/负' in r for r in reasons))            # f：不产生无穷吞吐
        self.assertTrue(any('重试' in r for r in reasons))             # g
        self.assertTrue(any('工具参数' in r for r in reasons))         # h
        self.assertTrue(any('首 token' in r for r in reasons))         # l

    def test_cutoff_edge_excluded_and_lower_bound_not_trimmed(self):
        # 首 token 恰在截止点：TTFT 排除；区间终点在截止后：吞吐排除（完成未在截止前证实）。
        result = self.report('--to', '2026-09-01T00:00:01Z')
        perf = result['analysis']['performance']
        self.assertEqual(perf['metrics']['ttft']['aggregate']['excluded_by_kind']['range'], 2)
        self.assertEqual(perf['metrics']['ttft']['aggregate']['valid'], 0)
        self.assertEqual(perf['metrics']['throughput']['aggregate']['excluded_by_kind']['range'], 2)
        self.assertEqual(perf['metrics']['throughput']['aggregate']['valid'], 0)
        # 跨下界：a 的首 token 早于下界按入样事件排除；b 保留完整 2000ms 不裁时；
        # 吞吐按区间终点纳入，a/b 的区间时长不比例裁（1000/9000 完整保留）。
        result = self.report('--from', '2026-09-01T00:00:01.500Z')
        perf = result['analysis']['performance']
        ttft = perf['metrics']['ttft']
        self.assertEqual([s['value'] for s in ttft['samples']], [2000])
        self.assertEqual(ttft['aggregate']['excluded_by_kind']['range'], 1)
        throughput = perf['metrics']['throughput']
        self.assertEqual((throughput['aggregate']['numerator'], throughput['aggregate']['denominator']), (200, 10000))

    def test_overview_saves_performance_day_projection_in_scope_tz(self):
        proc = self.run_cli('overview', '--harness', 'zcode', '--database', str(self.db), '--to', END,
                            '--tz', '+00:00', '--format', 'json')
        result = json.loads(proc.stdout)
        self.assertEqual(result['format_version'], 3)
        perf = result['analysis']['performance']
        self.assertEqual(perf['tz']['name'], '+00:00')
        day = perf['metrics']['ttft']['projections']['day']
        self.assertEqual([(d['date'], d['numerator'], d['denominator']) for d in day], [('2026-09-01', 3000, 2)])
        tday = perf['metrics']['throughput']['projections']['day']
        self.assertEqual([(d['date'], d['numerator'], d['denominator']) for d in tday], [('2026-09-01', 200, 10000)])

    def test_saved_show_recompute_and_tampered_performance_rejected(self):
        saved = self.root / 'saved.json'
        first = self.report('--no-pricing', '--export', 'json', '--output', str(saved))
        self.assertEqual(json.loads(saved.read_text()), first)
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, first)
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(recomputed['analysis']['performance']['metrics']['throughput']['aggregate']['numerator'], 200)
        base = json.loads(saved.read_text())

        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            path = self.root / ('bad-' + name + '.json')
            path.write_text(json.dumps(data))
            self.run_cli('show', '--saved', str(path), codes=(4,))

        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'][0].__setitem__('value', 999), 'conflict')
        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'][0].__setitem__('record_key', 'zcode-db:ghost'), 'dangling')
        reject(lambda d: d['analysis']['performance']['metrics']['throughput']['aggregate'].__setitem__('numerator', 201), 'aggregate')
        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'].append(
            dict(d['analysis']['performance']['metrics']['ttft']['samples'][0])), 'dupkey')
        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['samples'].pop(), 'counts')
        reject(lambda d: d['analysis']['performance']['tz'].__setitem__('name', 'Pacific/Midway'), 'daytz')
        reject(lambda d: d['analysis']['performance']['metrics']['ttft']['projections']['day'][0].__setitem__('numerator', 3001), 'daymember')
        reject(lambda d: d['analysis'].__setitem__('schema_version', 2), 'extversion')

    def test_session_recompute_preserves_saved_performance_timezone(self):
        saved = self.root / 'saved.json'
        with patch.dict(os.environ, TZ='Asia/Shanghai'):
            first = self.report('--export', 'json', '--output', str(saved))
        original = saved.read_bytes()
        self.assertEqual(first['analysis']['performance']['tz']['name'], '+08:00')
        with patch.dict(os.environ, TZ='America/Los_Angeles'):
            shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
            fresh = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, first)
        self.assertEqual(fresh['scope'], first['scope'])
        self.assertEqual(fresh['analysis']['performance'], first['analysis']['performance'])
        self.assertEqual(saved.read_bytes(), original)

        # A legal report without saved performance still uses the current local timezone.
        legacy = dict(first)
        legacy.pop('analysis')
        saved.write_text(json.dumps(legacy))
        with patch.dict(os.environ, TZ='America/Los_Angeles'):
            fresh = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(fresh['analysis']['performance']['tz']['name'], '-07:00')

    def test_jsonl_entries_report_checked_unavailable_reasons(self):
        # Codex：逐调用三元组不可配对（轮次 time_to_first_token_ms 不冒充 TTFT）；ZCode JSONL：无首 token 事件。
        self.log = self.root / 'rollout.jsonl'
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in [pmeta(), tctx(), usage()]))
        result = json.loads(self.run_cli('report', '--harness', 'codex', '--source', str(self.log),
                                         '--session', 's', '--to', END, '--format', 'json').stdout)
        perf = result['analysis']['performance']
        for name in ('ttft', 'throughput'):
            metric = perf['metrics'][name]
            self.assertEqual(metric['support']['status'], 'source_not_provided')
            self.assertEqual(metric['samples'], [])
            self.assertEqual(metric['aggregate']['valid'], 0)
        self.assertIn('三元组', perf['metrics']['ttft']['support']['reason'])
        self.assertIn('task_complete.time_to_first_token_ms', perf['metrics']['ttft']['support']['reason'])
        table = self.run_cli('report', '--harness', 'codex', '--source', str(self.log), '--session', 's', '--to', END)
        self.assertIn('不可用', table.stdout)
        self.assertIn('来源未提供', table.stdout)
        zrows = [{'sessionId': 's', 'requestId': 'r1', 'attempt': 1, 'turnId': 't1', 'querySource': 'main_turn',
                  'completedAt': '2026-09-01T00:01:00Z', 'model': {'providerId': 'builtin:bigmodel-coding-plan', 'modelId': 'GLM-5.3'},
                  'response': {'usage': {'inputTokens': 100, 'outputTokens': 10, 'cacheReadTokens': 0, 'totalTokens': 110}}}]
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in zrows))
        result = json.loads(self.run_cli('report', '--harness', 'zcode', '--source', str(self.log),
                                         '--session', 's', '--to', END, '--format', 'json').stdout)
        reason = result['analysis']['performance']['metrics']['ttft']['support']['reason']
        self.assertIn('无首 token 事件', reason)
        self.assertIn('来源未提供', reason)


def tool_completed(item_id, kind='CommandExecution', status='completed', secs=10, nanos=0,
                   start=None, end=None, time=T1, sid='s', turn='t1'):
    item = {'type': kind, 'id': item_id, 'status': status,
            'duration': None if secs is None else {'secs': secs, 'nanos': nanos}}
    if start is not None:
        item['start'] = start
        item['end'] = end
    if kind == 'CommandExecution':
        item['exit_code'] = 0 if status == 'completed' else 1
    return {'timestamp': time, 'type': 'event_msg',
            'payload': {'type': 'item_completed', 'thread_id': sid, 'turn_id': turn, 'item': item}}


def tool_log_event(sid, cid, event, time, duration=None, tool='Bash', query='main_turn', turn='turn_1'):
    obj = {'timestamp': time, 'level': 'info', 'event': event, 'sessionId': sid, 'turnId': turn,
           'toolCallId': cid, 'status': 'ok',
           'context': {'querySource': query, 'toolName': tool}}
    if duration is not None:
        obj['durationMs'] = duration
    return obj


def tool_database(path, rows, usage=True):
    """ZCode DB with tool_usage; rows: (call_id, tool, status, started, completed, duration)."""
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE session (id TEXT, version TEXT, parent_id TEXT, time_created INTEGER, task_type TEXT);
    CREATE TABLE model_usage (id TEXT,logical_request_id INTEGER,attempt_index INTEGER,session_id TEXT,turn_id TEXT,
    query_source TEXT,provider_id TEXT,model_id TEXT,status TEXT,started_at INTEGER,completed_at INTEGER,
    duration_ms INTEGER,retry_count INTEGER,raw_usage_json TEXT);
    CREATE TABLE turn_usage (session_id TEXT,turn_id TEXT,started_at INTEGER,completed_at INTEGER,status TEXT,model_request_count INTEGER);
    CREATE TABLE tool_usage (id TEXT,session_id TEXT,turn_id TEXT,tool_call_id TEXT,tool_name TEXT,status TEXT,
    started_at INTEGER,completed_at INTEGER,duration_ms INTEGER);''')
    db.execute('INSERT INTO session VALUES (?,?,?,?,?)', ('s', '0.16.9', None, PERF_T0, 'interactive'))
    db.execute('INSERT INTO turn_usage VALUES (?,?,?,?,?,?)', ('s', 't1', PERF_T0, PERF_T0 + 120000, 'completed', 1))
    if usage:
        db.execute('INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('r1', 'msg1', 0, 's', 't1', 'main_turn', 'builtin:bigmodel-coding-plan', 'GLM-5.3',
                    'completed', PERF_T0, PERF_T0 + 60000, 60000, 0,
                    json.dumps({'inputTokens': 100, 'outputTokens': 10, 'cacheReadTokens': 0, 'totalTokens': 110})))
    for cid, tool, status, started, completed, duration in rows:
        db.execute('INSERT INTO tool_usage VALUES (?,?,?,?,?,?,?,?,?)',
                   ('usage_tool_s_' + cid, 's', 't1', cid, tool, status, started, completed, duration))
    db.commit()
    db.close()
    return path


class ToolDurationCLI(unittest.TestCase):
    """Ticket 04: tool execution duration, span envelope and evidence location."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-tool-')
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

    def tool_metric(self, result):
        return result['analysis']['performance']['metrics']['tool_duration']

    def test_completed_only_native_tool_report_reloads(self):
        self.write([tool_log_event('s', 'alone', 'tool.call.completed', T1, duration=1000)])
        result = self.report('--harness', 'zcode', '--no-pricing')
        metric = self.tool_metric(result)
        sample = metric['samples'][0]
        self.assertEqual((sample['exec_start'], sample['exec_end']), (None, None))
        self.assertEqual((sample['value'], sample['native_duration_ns'], sample['basis']),
                         (1000000000, 1000000000, 'native'))
        self.assertEqual(sample['completed_at'], T1)
        self.assertEqual(metric['aggregate']['wall']['state'], 'unknown')
        saved = self.root / 'saved.json'
        saved.write_text(json.dumps(result))
        shown = self.run_cli('show', '--saved', str(saved), '--format', 'json')
        self.assertEqual(json.loads(shown.stdout), result)

    def test_tool_endpoint_pairs_preserve_independent_intervals(self):
        # Exercise the generation boundary for both native and derived paths.
        scripts = str(ENTRY.parent)
        with patch.object(sys, 'path', [scripts] + sys.path):
            from token_audit.analysis import _tool_outcome, _tool_wall, timestamp
        base = {'key': 'k', 'session': 's', 'category': 'shell', 'status': 'completed',
                'duration_ns': 1000000000, 'duration_precision': 'ms',
                'completed_at': T1, 'sources': [{'path': 'fixture.jsonl', 'line': 1}]}
        pairs = [(None, None), (T0, None), (None, T1), (T0, T1)]
        for execution in pairs:
            for dispatch in pairs:
                for native in (1000000000, None):
                    with self.subTest(execution=execution, dispatch=dispatch, native=native):
                        event = dict(base, exec_start=execution[0], exec_end=execution[1],
                                     dispatch_start=dispatch[0], dispatch_end=dispatch[1],
                                     duration_ns=native)
                        kind, _, sample = _tool_outcome(event, None, timestamp(END))
                        if native is None and execution != (T0, T1):
                            self.assertEqual(kind, 'missing')
                            self.assertIsNone(sample)
                            continue
                        self.assertIsNone(kind)
                        self.assertEqual((sample['exec_start'], sample['exec_end']),
                                         execution if all(execution) else (None, None))
                        self.assertEqual((sample['dispatch_start'], sample['dispatch_end']),
                                         dispatch if all(dispatch) else (None, None))
                        self.assertEqual(sample['value'], native if native is not None else 60000000000)
                        self.assertEqual(sample['basis'], 'native' if native is not None else 'derived')
                        wall = _tool_wall([sample])
                        self.assertEqual(wall['state'], 'known' if (all(execution) or all(dispatch)) else 'unknown')

    def test_p3_a4_serial_and_parallel_wall_vs_sum(self):
        # 需求 P3-A4 样例：两次各 10 秒工具；串行墙钟 20 秒、耗时和 20 秒；[0,10] 与 [5,15] 并行墙钟 15 秒、和 20 秒。
        t0 = 1788220800000  # 2026-09-01T00:00:00Z 毫秒
        base = [pmeta(), tctx(), usage()]
        serial = [tool_completed('exec-a', secs=10, start=t0, end=t0 + 10000, time='2026-09-01T00:00:10Z'),
                  tool_completed('exec-b', secs=10, start=t0 + 10000, end=t0 + 20000, time='2026-09-01T00:00:20Z')]
        self.write(base + serial)
        result = self.report()
        metric = self.tool_metric(result)
        aggregate = metric['aggregate']
        self.assertEqual(metric['support']['status'], 'supported')
        self.assertEqual((aggregate['candidates'], aggregate['valid'], aggregate['excluded']), (2, 2, 0))
        self.assertEqual(aggregate['numerator'], 20000000000)   # 耗时和 20 秒（精确 ns）
        self.assertEqual(aggregate['denominator'], 2)
        self.assertEqual(aggregate['wall']['value'], 20000000000)  # 串行包络 20 秒
        self.assertEqual(aggregate['wall']['state'], 'known')
        self.assertEqual(aggregate['no_token_record'], 2)       # 独立通道：无 token 记录引用
        self.assertEqual([s['record_key'] for s in metric['samples']], [None, None])
        self.assertEqual(result['summary']['metrics']['input']['value'], 100)  # 不进入 token 合计
        self.assertEqual(len(result['records']), 1)
        table = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END)
        self.assertIn('工具执行耗时', table.stdout)
        self.assertIn('执行耗时和 20000.00 ms', table.stdout)
        self.assertIn('跨度包络 20.00 s', table.stdout)
        # 并行 [0,10] 与 [5,15]：包络 15 秒，耗时和仍 20 秒（并行不扣重叠，不冒充墙钟）。
        parallel = [tool_completed('exec-a', secs=10, start=t0, end=t0 + 10000, time='2026-09-01T00:00:10Z'),
                    tool_completed('exec-b', secs=10, start=t0 + 5000, end=t0 + 15000, time='2026-09-01T00:00:15Z')]
        self.write(base + parallel)
        metric = self.tool_metric(self.report())
        self.assertEqual(metric['aggregate']['numerator'], 20000000000)
        self.assertEqual(metric['aggregate']['wall']['value'], 15000000000)
        table = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END)
        self.assertIn('跨度包络 15.00 s', table.stdout)

    def test_codex_identity_status_ns_precision_and_ignored_items(self):
        t0 = 1788220800000
        rows = [pmeta(), tctx(), usage(),
                # secs/nanos 精确换算：9s999999999ns，不截成 9999ms；失败完成保留真实耗时与失败状态
                tool_completed('call_mcp', kind='McpToolCall', status='failed', secs=9, nanos=999999999,
                               start=t0, end=t0 + 10000),
                tool_completed('exec_nodur', secs=None, start=t0 + 20000, end=t0 + 23000),  # 无原生值，起止求差 3000ms
                tool_completed('exec_running', status='in_progress', start=t0 + 30000, end=t0 + 31000),
                tool_completed('exec_baddur', secs=True, nanos=0),                         # 布尔耗时 → 冲突
                {'timestamp': T1, 'type': 'event_msg',
                 'payload': {'type': 'item_completed', 'thread_id': 's', 'turn_id': 't1',
                             'item': {'type': 'AgentMessage', 'id': 'msg_x', 'content': [{'text': '正文'}]}}}]
        self.write(rows)
        metric = self.tool_metric(self.report())
        samples = {s['key']: s for s in metric['samples']}
        self.assertEqual(set(samples), {'codex-tool:s:call_mcp', 'codex-tool:s:exec_nodur'})
        mcp = samples['codex-tool:s:call_mcp']
        self.assertEqual(mcp['value'], 9999999999)
        self.assertEqual(mcp['native_duration_ns'], 9999999999)
        self.assertEqual((mcp['basis'], mcp['precision'], mcp['status'], mcp['category']), ('native', 'ns', 'failed', 'McpToolCall'))
        derived = samples['codex-tool:s:exec_nodur']
        self.assertEqual((derived['value'], derived['basis'], derived['precision']), (3000000000, 'derived', 'ms'))
        self.assertIsNone(derived['native_duration_ns'])
        aggregate = metric['aggregate']
        self.assertEqual((aggregate['candidates'], aggregate['valid'], aggregate['excluded']), (4, 2, 2))
        self.assertEqual(aggregate['excluded_by_kind']['missing'], 1)   # 未结束只给状态
        self.assertEqual(aggregate['excluded_by_kind']['conflict'], 1)  # 布尔耗时
        reasons = aggregate['exclusion_reasons']
        self.assertTrue(any('未结束' in r for r in reasons))
        self.assertTrue(any('布尔值' in r for r in reasons))
        # 包络：两条有效样本都有起止端点，0 → 23000ms
        self.assertEqual(aggregate['wall']['value'], 23000000000)
        # 导出不含命令参数、输出正文或其他 item 内容
        text = json.dumps(self.report(), ensure_ascii=False)
        self.assertNotIn('正文', text)

    def test_cutoff_edge_and_lower_bound_not_trimmed(self):
        t0 = 1788220800000
        rows = [pmeta(), tctx(), usage(),
                tool_completed('exec-at-cutoff', secs=10, start=t0, end=t0 + 10000, time='2026-09-02T00:00:00Z'),
                tool_completed('exec-cross', secs=10, start=t0 - 5000, end=t0 + 5000, time='2026-09-01T00:00:05Z')]
        self.write(rows)
        result = self.report('--from', '2026-09-01T00:00:01Z')
        metric = self.tool_metric(result)
        # 恰在 cutoff 的完成事件排除；跨下界完整样本保留完整 10 秒，不比例裁时。
        self.assertEqual([s['key'] for s in metric['samples']], ['codex-tool:s:exec-cross'])
        self.assertEqual(metric['samples'][0]['value'], 10000000000)
        self.assertEqual(metric['aggregate']['excluded_by_kind']['range'], 1)

    def test_inherited_copy_excluded_new_identity_counted(self):
        t0 = 1788220800000
        ancestor = dict(pmeta('s0'))
        fork = dict(pmeta('s'))
        fork['payload']['forked_from_id'] = 's0'
        other = self.root / 'ancestor.jsonl'
        other.write_text(json.dumps(ancestor) + '\n'
                         + json.dumps(tool_completed('exec-same', sid='s0', secs=4, time=T1)) + '\n')
        self.write([fork, tctx(), usage(),
                    tool_completed('exec-same', secs=4, time=T1),   # 完整身份与祖先一致 → 继承副本
                    tool_completed('exec-new', secs=6, time=T1)])   # 新身份同命令重执行 → 照常计入
        metric = self.tool_metric(self.report('--source', str(other)))
        self.assertEqual([s['key'] for s in metric['samples']], ['codex-tool:s:exec-new'])
        self.assertEqual(metric['aggregate']['excluded_by_kind']['unsupported'], 1)
        self.assertTrue(any('继承副本' in r for r in metric['aggregate']['exclusion_reasons']))

    def test_zcode_database_merge_span_zero_and_supplements(self):
        t0 = PERF_T0
        db = tool_database(self.root / 'db.sqlite', [
            ('call_a', 'Bash', 'completed', t0, t0 + 103, 97),          # 原生 97ms ≠ 调度跨度 103ms：分列不判冲突
            ('call_b', 'Read', 'error', t0 + 103, t0 + 153, 50),        # 失败完成保留耗时与状态
            ('call_c', 'Write', 'completed', t0 + 153, t0 + 163, 0),    # 无日志证据的零：保持未知
            ('call_d', 'Edit', 'completed', t0 + 163, t0 + 173, 0),     # 日志 durationMs=0 独立证实零
            ('call_e', 'TodoWrite', 'running', t0 + 173, None, None),   # 未完成只给状态
            ('call_f', 'Bash', 'completed', t0 + 183, t0 + 243, 60)])   # 日志 durationMs=61：同语义冲突
        logdir = self.root / 'log'
        logdir.mkdir()
        (logdir / 'zcode-2026-09-01.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in [
            tool_log_event('s', 'call_a', 'tool.call.started', '2026-09-01T00:00:00.005Z'),
            tool_log_event('s', 'call_a', 'tool.call.completed', '2026-09-01T00:00:00.102Z', duration=97),
            tool_log_event('s', 'call_d', 'tool.call.started', '2026-09-01T00:00:00.164Z'),
            tool_log_event('s', 'call_d', 'tool.call.completed', '2026-09-01T00:00:00.164Z', duration=0),
            tool_log_event('s', 'call_f', 'tool.call.started', '2026-09-01T00:00:00.184Z'),
            tool_log_event('s', 'call_f', 'tool.call.completed', '2026-09-01T00:00:00.245Z', duration=61),
            tool_log_event('s', 'call_x', 'tool.call.started', '2026-09-01T00:00:01.000Z'),
            tool_log_event('s', 'call_x', 'tool.call.completed', '2026-09-01T00:00:01.100Z', duration=100)]))
        proc = self.run_cli('report', '--harness', 'zcode', '--database', str(db), '--session', 's',
                            '--to', END, '--format', 'json')
        metric = self.tool_metric(json.loads(proc.stdout))
        aggregate = metric['aggregate']
        self.assertEqual((aggregate['candidates'], aggregate['valid'], aggregate['excluded']), (6, 3, 3))
        samples = {s['key']: s for s in metric['samples']}
        a = samples['zcode-db-tool:s:call_a']
        self.assertEqual((a['value'], a['native_duration_ns'], a['basis']), (97000000, 97000000, 'native'))
        self.assertEqual(a['exec_start'], '2026-09-01T00:00:00.005Z')           # 日志补足真实执行起点（保留原拼写）
        self.assertEqual((a['dispatch_start'], a['dispatch_end']),             # 调度跨度分列
                         ('2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00.103000+00:00'))
        self.assertEqual(samples['zcode-db-tool:s:call_b']['status'], 'failed')
        self.assertEqual(samples['zcode-db-tool:s:call_b']['value'], 50000000)
        d = samples['zcode-db-tool:s:call_d']
        self.assertEqual((d['value'], d['basis']), (0, 'native'))              # 确认零可显示
        self.assertEqual(aggregate['numerator'], 147000000)
        self.assertEqual(aggregate['excluded_by_kind'], {'missing': 2, 'conflict': 1, 'unsupported': 0, 'range': 0})
        reasons = aggregate['exclusion_reasons']
        self.assertTrue(any('转为 0' in r and '未知' in r for r in reasons))   # call_c：零值未知
        self.assertTrue(any('未结束' in r for r in reasons))                   # call_e
        self.assertTrue(any('同语义证据冲突' in r for r in reasons))           # call_f
        self.assertEqual(len(aggregate['supplements']), 1)                     # call_x：关联不明单列
        self.assertEqual(aggregate['supplements'][0]['key'], 'zcode-tool:s:call_x')
        # 包络按调度跨度：有效样本 a/b/d，0 → 173ms
        self.assertEqual(aggregate['wall']['value'], 173000000)
        self.assertEqual(aggregate['wall']['state'], 'known')
        table = self.run_cli('report', '--harness', 'zcode', '--database', str(db), '--session', 's', '--to', END)
        self.assertIn('执行耗时和 147.00 ms', table.stdout)
        self.assertIn('补充项（单列不计入）', table.stdout)

    def test_zcode_jsonl_started_completed_merge_and_duplicates(self):
        rows = [
            tool_log_event('s', 'c1', 'tool.call.started', '2026-09-01T00:00:00Z'),
            tool_log_event('s', 'c1', 'tool.call.completed', '2026-09-01T00:00:10Z', duration=10000),
            tool_log_event('s', 'c1', 'tool.call.completed', '2026-09-01T00:00:10Z', duration=10000),  # 完成副本只计一次
            tool_log_event('s', 'c2', 'tool.call.started', '2026-09-01T00:00:10Z'),
            tool_log_event('s', 'c2', 'tool.call.completed', '2026-09-01T00:00:20Z'),                  # 缺原生 durationMs：起止求差
            tool_log_event('s', 'c3', 'tool.call.started', '2026-09-01T00:00:20Z'),                    # 只有开始：未完成
            tool_log_event('s', 'c4', 'tool.call.completed', '2026-09-01T00:00:30Z', duration=5000),
            tool_log_event('s', 'c4', 'tool.call.completed', '2026-09-01T00:00:31Z', duration=5000),   # 完成副本时间冲突
            tool_log_event(None, 'c5', 'tool.call.completed', '2026-09-01T00:00:40Z', duration=1000)]  # 无会话身份不猜归属
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))
        result = self.report('--harness', 'zcode')
        metric = self.tool_metric(result)
        samples = {s['key']: s for s in metric['samples']}
        self.assertEqual(set(samples), {'zcode-tool:s:c1', 'zcode-tool:s:c2'})
        self.assertEqual((samples['zcode-tool:s:c1']['value'], samples['zcode-tool:s:c1']['basis']), (10000000000, 'native'))
        self.assertEqual((samples['zcode-tool:s:c2']['value'], samples['zcode-tool:s:c2']['basis']), (10000000000, 'derived'))
        aggregate = metric['aggregate']
        self.assertEqual((aggregate['candidates'], aggregate['valid'], aggregate['excluded']), (4, 2, 2))
        self.assertEqual(aggregate['excluded_by_kind']['missing'], 1)
        self.assertEqual(aggregate['excluded_by_kind']['conflict'], 1)
        self.assertTrue(any('无会话身份' in i['reason'] for i in result['issues']))
        # 包络：c1 [0,10s] 与 c2 [10,20s] → 20 秒；耗时和 20 秒
        self.assertEqual(aggregate['wall']['value'], 20000000000)
        self.assertEqual(aggregate['numerator'], 20000000000)

    def test_main_only_excludes_unclassified_with_reason(self):
        db = tool_database(self.root / 'db.sqlite', [('call_a', 'Bash', 'completed', PERF_T0, PERF_T0 + 100, 97)])
        proc = self.run_cli('report', '--harness', 'zcode', '--database', str(db), '--session', 's',
                            '--to', END, '--main-only', '--format', 'json')
        metric = self.tool_metric(json.loads(proc.stdout))
        # tool_usage 无 query_source：分类未知，main-only 不纳入并说明原因，不补造内部分类
        self.assertEqual(metric['aggregate']['valid'], 0)
        self.assertEqual(metric['aggregate']['excluded_by_kind']['unsupported'], 1)
        self.assertTrue(any('分类、关系未知' in r for r in metric['aggregate']['exclusion_reasons']))
        proc = self.run_cli('report', '--harness', 'zcode', '--database', str(db), '--session', 's',
                            '--to', END, '--format', 'json')
        self.assertEqual(self.tool_metric(json.loads(proc.stdout))['aggregate']['valid'], 1)

    def test_resume_copy_merges_once_conflicting_copy_conflicts(self):
        t0 = 1788220800000
        copy = self.root / 'resume-copy.jsonl'
        copy.write_text(json.dumps(pmeta()) + '\n'
                        + json.dumps(tool_completed('exec-a', secs=10, start=t0, end=t0 + 10000, time='2026-09-01T00:00:10Z')) + '\n'
                        + json.dumps(tool_completed('exec-b', secs=5, time=T1)) + '\n'
                        + json.dumps(tool_completed('exec-b', secs=7, time=T1)) + '\n')
        self.write([pmeta(), tctx(), usage(),
                    tool_completed('exec-a', secs=10, start=t0, end=t0 + 10000, time='2026-09-01T00:00:10Z')])
        # 同会话跨文件（恢复副本）：一致副本只计一次；耗时冲突的副本冲突排除，不双计。
        metric = self.tool_metric(self.report('--source', str(copy)))
        self.assertEqual([s['key'] for s in metric['samples']], ['codex-tool:s:exec-a'])
        self.assertEqual(metric['samples'][0]['value'], 10000000000)
        self.assertEqual(len(metric['samples'][0]['source']['path']) > 0, True)
        self.assertEqual(metric['aggregate']['excluded_by_kind']['conflict'], 1)
        self.assertTrue(any('副本耗时冲突' in r for r in metric['aggregate']['exclusion_reasons']))

    def test_saved_show_recompute_and_tampered_tool_rejected(self):
        t0 = 1788220800000
        self.write([pmeta(), tctx(), usage(),
                    tool_completed('exec-a', secs=10, start=t0, end=t0 + 10000, time='2026-09-01T00:00:10Z')])
        saved = self.root / 'saved.json'
        first = self.report('--export', 'json', '--output', str(saved))
        self.assertEqual(json.loads(saved.read_text()), first)
        shown = json.loads(self.run_cli('show', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(shown, first)
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(recomputed['analysis']['performance']['metrics']['tool_duration']['aggregate']['numerator'], 10000000000)
        base = json.loads(saved.read_text())

        def reject(mutate, name):
            data = json.loads(json.dumps(base))
            mutate(data)
            path = self.root / ('bad-' + name + '.json')
            path.write_text(json.dumps(data))
            self.run_cli('show', '--saved', str(path), codes=(4,))

        tool = lambda d: d['analysis']['performance']['metrics']['tool_duration']
        reject(lambda d: tool(d)['samples'][0].__setitem__('value', 999), 'value')
        reject(lambda d: tool(d)['samples'][0].__setitem__('record_key', 'codex:s:r1'), 'recordkey')
        reject(lambda d: tool(d)['aggregate'].__setitem__('numerator', 999), 'aggregate')
        reject(lambda d: tool(d)['aggregate']['wall'].__setitem__('value', 999), 'wall')
        reject(lambda d: tool(d)['aggregate']['supplements'].append({'key': 'k', 'session': 's', 'reason': '', 'source': {'path': 'p'}}), 'supplement')
        reject(lambda d: tool(d)['projections']['category'][0].__setitem__('numerator', 999), 'category')
        reject(lambda d: tool(d)['samples'].append(dict(tool(d)['samples'][0])), 'dupkey')
        reject(lambda d: tool(d)['samples'][0].__setitem__('exec_end', None), 'spanpair')
        # 03 前保存的两指标报告仍合法展示（不补造工具区）
        del base['analysis']['performance']['metrics']['tool_duration']
        old = self.root / 'old-two-metric.json'
        old.write_text(json.dumps(base))
        proc = self.run_cli('show', '--saved', str(old), '--format', 'json')
        self.assertNotIn('tool_duration', json.loads(proc.stdout)['analysis']['performance']['metrics'])
        table = self.run_cli('show', '--saved', str(old))
        self.assertIn('未保存工具耗时分析', table.stdout)


class SavedReuseCLI(unittest.TestCase):
    """Ticket 05: saved-snapshot recompute, explicit reprice separation and CSV parity."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-reuse-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'rollout.jsonl'

    def write(self, rows):
        self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))

    def write_pricing(self, cfg, name='pricing.json'):
        path = self.root / name
        path.write_text(json.dumps(cfg) if not isinstance(cfg, str) else cfg)
        return path

    def run_cli(self, *args, codes=(0, 2, 3)):
        proc = subprocess.run([sys.executable, '-B', str(ENTRY), *args], capture_output=True, text=True,
                              cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def save_priced(self):
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        saved = self.root / 'saved.json'
        pricing = self.write_pricing(pricing_cfg([pricing_rule('rule-a1'),
                                                  pricing_rule('rule-unused', model='other-model')]))
        first = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                                        '--pricing', str(pricing), '--format', 'json',
                                        '--export', 'json', '--output', str(saved)).stdout)
        return saved, pricing, first

    def test_recompute_reuses_saved_snapshot_after_pricing_file_removed(self):
        saved, pricing, first = self.save_priced()
        before = saved.read_bytes()
        pricing.unlink()  # 本地价格文件移除后，重算仍沿用保存快照（含未命中规则）
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        cost = recomputed['analysis']['cost']
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '8.8')
        self.assertEqual([r['id'] for r in cost['config']['rules']], ['rule-a1', 'rule-unused'])
        # 范围、来源、截止点与代理策略沿用保存值；性能不因价格机制缺失或改价而改变。
        self.assertEqual(recomputed['scope'], first['scope'])
        self.assertEqual(recomputed['input'], first['input'])
        self.assertEqual(recomputed['analysis']['performance'], first['analysis']['performance'])
        self.assertEqual(saved.read_bytes(), before)  # 原文件不改写

    def test_appended_records_priced_by_saved_rules_new_model_unpriced(self):
        saved, pricing, first = self.save_priced()
        pricing.unlink()
        # 固定范围后补记录：同模型按保存的旧规则计价，后补新模型无规则保持未定价。
        with self.log.open('a') as stream:
            stream.write(json.dumps(usage('r2', inp=1000000, cache=400000, output=100000,
                                          time='2026-09-01T00:02:00Z')) + '\n')
            stream.write(json.dumps(tctx(turn='t2', model='gpt-7-ultra')) + '\n')
            stream.write(json.dumps(usage('r3', turn='t2', inp=500000, cache=0, output=0,
                                          time='2026-09-01T00:03:00Z')) + '\n')
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        cost = recomputed['analysis']['cost']
        # 独立手算：两条旧模型记录各 8.8；新模型记录无规则未定价，不默用当前文件。
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '17.6')
        self.assertEqual(cost['config']['revision'], 'test-rev-1')
        entries = {e['record_key']: e for e in cost['records']}
        self.assertEqual(entries['codex:s:r3']['status'], 'unpriced')
        self.assertTrue(any('无匹配' in item['reason'] for item in entries['codex:s:r3']['unpriced']))
        self.assertEqual((cost['summary']['priced'], cost['summary']['unpriced']), (2, 1))
        # 截止点仍为保存值，后补记录只因其时间在原范围内才计入。
        self.assertEqual(recomputed['scope']['to'], first['scope']['to'])

    def test_explicit_reprice_keeps_scope_cutoff_and_performance(self):
        saved, pricing, first = self.save_priced()
        before = saved.read_bytes()
        new_cfg = pricing_cfg([pricing_rule('rule-a1', output={'kind': 'total_output',
                                                               'price_per_million': '40'})],
                              revision='test-rev-2')
        repriced = json.loads(self.run_cli('recompute', '--saved', str(saved),
                                           '--pricing', str(self.write_pricing(new_cfg, 'new.json')),
                                           '--format', 'json').stdout)
        # 独立手算：600000×10/1e6 + 400000×2/1e6 + 100000×40/1e6 = 6 + 0.8 + 4 = 10.8。
        self.assertEqual(repriced['analysis']['cost']['summary']['currencies']['TST']['amount'], '10.8')
        self.assertEqual(repriced['analysis']['cost']['config']['revision'], 'test-rev-2')
        # 换价不设置 update：范围、截止点与代理策略不变，相同来源记录下性能不变。
        self.assertEqual(repriced['scope'], first['scope'])
        self.assertEqual(repriced['analysis']['performance'], first['analysis']['performance'])
        self.assertEqual(saved.read_bytes(), before)

    def test_update_without_pricing_uses_saved_snapshot(self):
        saved, pricing, first = self.save_priced()
        pricing.unlink()
        with self.log.open('a') as stream:
            stream.write(json.dumps(tctx(turn='t2', model='gpt-7-ultra')) + '\n')
            stream.write(json.dumps(usage('r3', turn='t2', inp=500000, cache=0, output=0,
                                          time='2026-09-03T00:03:00Z')) + '\n')
        updated = json.loads(self.run_cli('recompute', '--saved', str(saved), '--update',
                                          '--to', '2026-09-04T00:00:00Z', '--format', 'json').stdout)
        cost = updated['analysis']['cost']
        # 明确更新未选新价：沿用保存配置，范围内新增记录无规则则未定价。
        self.assertEqual(cost['config']['revision'], 'test-rev-1')
        self.assertEqual(cost['summary']['currencies']['TST']['amount'], '8.8')
        entries = {e['record_key']: e for e in cost['records']}
        self.assertEqual(entries['codex:s:r3']['status'], 'unpriced')
        self.assertEqual(updated['scope']['to'], '2026-09-04T00:00:00Z')

    def test_csv_projects_cost_and_performance_from_same_saved_result(self):
        database = perf_database(self.root / 'perf.sqlite', P34_ROWS)
        pricing = self.write_pricing(pricing_cfg(
            [pricing_rule('glm', provider='builtin:bigmodel-coding-plan', model='GLM-5.3',
                          input_={'kind': 'total_input', 'price_per_million': '10'},
                          output={'kind': 'total_output', 'price_per_million': '20'}),
             pricing_rule('glm-unused', provider='builtin:bigmodel-coding-plan', model='GLM-9.9')]))
        result = json.loads(self.run_cli('report', '--harness', 'zcode', '--database', str(database),
                                         '--session', 's', '--to', END, '--pricing', str(pricing),
                                         '--format', 'json').stdout)
        text = self.run_cli('report', '--harness', 'zcode', '--database', str(database),
                            '--session', 's', '--to', END, '--pricing', str(pricing),
                            '--format', 'csv').stdout
        rows = list(csv.DictReader(io.StringIO(text)))
        by_category = {}
        for row in rows:
            by_category.setdefault(row['category'], []).append(row)
        analysis = result['analysis']
        # 费用：与 JSON 同一保存结果同值（独立手算 2000×10/1e6 + 200×20/1e6 = 0.024 TST）。
        config_row = by_category['cost_config'][0]
        config_detail = json.loads(config_row['cost_detail'])
        self.assertEqual(config_detail['revision'], 'test-rev-1')
        self.assertEqual([r['id'] for r in config_detail['rules']], ['glm', 'glm-unused'])  # 含未命中规则
        summary_row = by_category['cost_summary'][0]
        self.assertEqual(summary_row['cost_currency'], 'TST')
        self.assertEqual(summary_row['cost_amount_exact'],
                         analysis['cost']['summary']['currencies']['TST']['amount'])
        self.assertEqual(summary_row['cost_amount_exact'], '0.024')
        self.assertEqual(summary_row['cost_amount_display'], '0.02')  # 两位小数四舍五入显示值
        coverage = json.loads(by_category['cost_coverage'][0]['cost_detail'])
        self.assertEqual(coverage['records'], analysis['cost']['summary']['records'])
        self.assertNotIn('cost_projection_model', by_category)  # v2 不携带整体投影
        # 性能：精确分子/分母、事件定义、覆盖与排除原因逐行与 JSON 相同。
        tz_row = by_category['perf_tz'][0]
        self.assertEqual(json.loads(tz_row['perf_detail'])['name'],
                         analysis['performance']['tz']['name'])
        metric_rows = {row['perf_metric']: row for row in by_category['perf_metric']}
        ttft = analysis['performance']['metrics']['ttft']
        self.assertEqual(metric_rows['ttft']['perf_numerator'], str(ttft['aggregate']['numerator']))
        self.assertEqual(metric_rows['ttft']['perf_denominator'], str(ttft['aggregate']['denominator']))
        self.assertEqual(metric_rows['ttft']['perf_display_value'], '1500.00')
        detail = json.loads(metric_rows['ttft']['perf_detail'])
        self.assertEqual(detail['definition'], ttft['definition'])
        self.assertEqual(detail['exclusion_reasons'], ttft['aggregate']['exclusion_reasons'])
        self.assertEqual(json.loads(metric_rows['ttft']['perf_units']), ttft['units'])
        throughput = analysis['performance']['metrics']['throughput']
        self.assertEqual(metric_rows['throughput']['perf_display_value'], '20.00')
        self.assertEqual(metric_rows['throughput']['perf_numerator'],
                         str(throughput['aggregate']['numerator']))
        member = [row for row in by_category['perf_projection_session'] if row['perf_metric'] == 'ttft'][0]
        self.assertEqual(member['label'], 's')
        self.assertEqual(member['perf_numerator'], str(ttft['projections']['session'][0]['numerator']))
        # 无 tool_usage 表的旧结构：工具指标不可用原因入 CSV，不补零。
        tool_detail = json.loads(metric_rows['tool_duration']['perf_detail'])
        self.assertEqual(tool_detail['support']['status'], 'source_not_provided')
        self.assertEqual(metric_rows['tool_duration']['perf_display_value'], '')

    def test_csv_note_rows_for_unpriced_query_and_v1_report(self):
        self.write([meta(), usage()])
        unpriced = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                                '--no-pricing', '--format', 'csv').stdout
        notes = [row['label'] for row in csv.DictReader(io.StringIO(unpriced))
                 if row['category'] == 'analysis_note']
        self.assertTrue(any('未配置价格' in note for note in notes))
        saved = self.root / 'v2.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--export', 'json', '--output', str(saved))
        old = {k: v for k, v in json.loads(saved.read_text()).items()
               if k not in ('localization', 'internal_support', 'views', 'explanation', 'analysis')}
        for record in old.get('records', []) + old.get('unassigned_records', []):
            record.pop('explanation', None)
        old['format_version'] = 1
        v1 = self.root / 'v1.json'
        v1.write_text(json.dumps(old))
        shown = self.run_cli('show', '--saved', str(v1), '--format', 'csv').stdout
        notes = [row['label'] for row in csv.DictReader(io.StringIO(shown))
                 if row['category'] == 'analysis_note']
        self.assertTrue(any('未保存费用/性能分析' in note for note in notes))
        # v1 再导出保持原版本；CSV 只是投影，不补零。
        out = self.root / 'v1-out.json'
        self.run_cli('show', '--saved', str(v1), '--export', 'json', '--output', str(out))
        self.assertEqual(json.loads(out.read_text())['format_version'], 1)
        # 无扩展旧报告明确重算生成新分析；未提交价格时不猜价（性能区保存，无费用区）。
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(v1), '--format', 'json').stdout)
        self.assertEqual(recomputed['format_version'], 2)
        self.assertIn('performance', recomputed['analysis'])
        self.assertNotIn('cost', recomputed['analysis'])


if __name__ == '__main__':
    unittest.main()


class DefaultPricingCLI(PricingCLI):
    """Ticket 01: bundled official default snapshot, token-only mode and flag guards."""

    def test_new_query_defaults_to_bundled_snapshot(self):
        # gpt-6.1-sol short tier with provable single-call input 100000:
        # (100K-40K)×$2 + 40K×$0.10 + 10K×$10 per 1M; the record has no cache-write tokens.
        self.write([pmeta(), tctx(), usage(inp=100000, cache=40000, output=10000)])
        result = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's',
                                         '--to', END, '--format', 'json').stdout)
        cost = result['analysis']['cost']
        self.assertEqual(result['analysis']['schema_version'], 2)
        self.assertEqual(cost['config']['schema_version'], 2)
        self.assertEqual(cost['config']['price_basis'], 'current_official_estimate')
        self.assertTrue(cost['config']['sources'])
        entry = cost['records'][0]
        self.assertEqual(entry['matched']['rule_id'], 'openai/gpt-6.1-sol/standard/short')
        self.assertEqual(entry['matched']['input_tokens'], 100000)
        self.assertEqual(entry['currency'], 'USD')
        # Without cache-write tokens both cache_write and the dependent other_input stay
        # unpriced; the priceable parts are 40000×0.1 + 10000×10 (per 1M) = 0.104 USD.
        self.assertEqual(cost['summary']['currencies']['USD']['amount'], '0.104')
        self.assertEqual({item['component'] for item in entry['unpriced']}, {'other_input', 'cache_write'})

    def test_long_tier_and_gap_use_bundled_conditions(self):
        # 1M input (> 278528 under either unit reading) is the long tier; its cache-write
        # tokens stay unknown so the amount keeps only the priced components.
        self.write([pmeta(), tctx(), usage(inp=1000000, cache=400000, output=100000)])
        result = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's',
                                         '--to', END, '--format', 'json').stdout)
        entry = result['analysis']['cost']['records'][0]
        self.assertEqual(entry['matched']['rule_id'], 'openai/gpt-6.1-sol/standard/long')
        # Cache-write tokens unknown: 400000×0.2 + 100000×15 (per 1M) = 1.58 USD priced.
        self.assertEqual(result['analysis']['cost']['summary']['currencies']['USD']['amount'], '1.58')
        # The unverified 272K integer band keeps its gap: no rule covers 275000.
        self.write([pmeta(), tctx(), usage(inp=275000, cache=0, output=1)])
        gap = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's',
                                      '--to', END, '--format', 'json').stdout)
        gap_entry = gap['analysis']['cost']['records'][0]
        self.assertEqual(gap_entry['status'], 'unpriced')
        self.assertIn('档位边界', gap_entry['unpriced'][0]['reason'])

    def test_no_pricing_and_flag_guards(self):
        self.write([pmeta(), tctx(), usage()])
        token_only = json.loads(self.run_cli('report', '--source', str(self.log), '--session', 's',
                                             '--to', END, '--no-pricing', '--format', 'json').stdout)
        self.assertEqual(token_only['analysis'].get('cost'), None)
        self.assertIn('performance', token_only['analysis'])
        saved = self.root / 'saved.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--export', 'json', '--output', str(saved))
        self.run_cli('recompute', '--saved', str(saved), '--no-pricing', codes=(4,))
        self.run_cli('sessions', '--source', str(self.log), '--default-pricing', codes=(4,))
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--pricing', str(self.write_pricing(pricing_cfg([pricing_rule('r')]))),
                     '--default-pricing', codes=(2,))
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--pricing', str(self.write_pricing(pricing_cfg([pricing_rule('r')]))),
                     '--no-pricing', codes=(2,))

    def test_recompute_reuses_saved_v2_snapshot_and_default_reprices(self):
        self.write([pmeta(), tctx(), usage()])
        saved = self.root / 'saved.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--export', 'json', '--output', str(saved))
        current_default = json.loads((ENTRY.parents[1] / 'pricing/default.json').read_text())['snapshot']
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        self.assertEqual(recomputed['analysis']['cost']['config']['revision'], current_default)
        # An explicitly unpriced saved report stays unpriced on recompute.
        unpriced = self.root / 'unpriced.json'
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--no-pricing', '--export', 'json', '--output', str(unpriced))
        again = json.loads(self.run_cli('recompute', '--saved', str(unpriced), '--format', 'json').stdout)
        self.assertNotIn('cost', again['analysis'])

    def test_v2_config_validation_rejects_bad_forms(self):
        snapshot = ENTRY.parents[1] / 'pricing' / 'snapshots' / 'official-20261011T0850Z.json'
        good = json.loads(snapshot.read_text())
        def bad(mutate):
            cfg = json.loads(json.dumps(good))
            mutate(cfg)
            proc = self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                                '--pricing', str(self.write_pricing(cfg)), '--format', 'json', codes=(4,))
            return proc.stderr
        self.assertIn('价格口径', bad(lambda c: c.__setitem__('price_basis', 'other')))
        self.assertIn('标准档', bad(lambda c: c['rules'][0]['conditions'].__setitem__('service_tier', 'flex')))
        self.assertIn('等值点', bad(lambda c: c['rules'][0]['conditions'].pop('input_max_inclusive')))
        self.assertIn('重叠', bad(lambda c: c['rules'][0]['conditions'].__setitem__('input_max', 400000)))
        self.assertIn('链式推断', bad(lambda c: c['mappings'].append(dict(
            id='chain', source=c['rules'][0]['source'],
            **{'from': {'provider': 'bigmodel', 'model': 'GLM-5.3'},
               'to': {'provider': 'other', 'model': 'GLM-5.3'}}, basis='链'))))
        self.assertIn('未覆盖项', bad(lambda c: c['uncovered'][0].pop('reason')))
        self.assertIn('来源', bad(lambda c: c['sources'][0].pop('fetched_at')))


class PricingUpdateCLI(unittest.TestCase):
    """Ticket 02: pricing-update candidate validation, history and atomic enablement."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='token-audit-update-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Run against an isolated copy so the shipped resource stays untouched.
        self.skill = self.root / 'skill'
        shutil_copy = __import__('shutil').copytree
        shutil_copy(Path(ENTRY).parents[1], self.skill)
        self.entry = self.entry_of(self.skill)
        self.base_candidate = json.loads((self.skill / 'pricing/default.json').read_text())
        self.base_candidate = json.loads((self.skill / 'pricing/snapshots' / (self.base_candidate['snapshot'] + '.json')).read_text())
        self.initial_default = self.base_candidate['revision']

    def entry_of(self, skill):
        return skill / 'scripts/audit.py'

    def run_update(self, *args, codes=(0, 2, 3, 4)):
        proc = subprocess.run([sys.executable, '-B', str(self.entry), 'pricing-update', *args],
                              capture_output=True, text=True, cwd=self.root,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertIn(proc.returncode, codes, proc.stderr)
        return proc

    def candidate(self, name, mutate=None):
        cfg = json.loads(json.dumps(self.base_candidate))
        cfg['revision'] = 'test-' + name
        if mutate:
            mutate(cfg)
        path = self.root / (name + '.json')
        path.write_text(json.dumps(cfg, ensure_ascii=False))
        return path

    def default_id(self):
        return json.loads((self.skill / 'pricing/default.json').read_text())['snapshot']

    def test_complete_candidate_enables_and_preserves_history(self):
        proc = self.run_update('--candidate', str(self.candidate('complete')))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('更新成功', proc.stdout)
        self.assertIn(self.initial_default, proc.stdout)  # 旧身份可核
        self.assertEqual(self.default_id(), 'test-complete')
        # History preserved; same-price re-read still gets a new identity and enables.
        proc2 = self.run_update('--candidate', str(self.candidate('reread')))
        self.assertEqual(proc2.returncode, 0)
        self.assertEqual(self.default_id(), 'test-reread')
        self.assertTrue((self.skill / 'pricing/snapshots/official-20261011T0850Z.json').exists())
        self.assertTrue((self.skill / 'pricing/snapshots/test-complete.json').exists())
        self.assertIn('规则变化：新增 0、移除 0、变更 0', proc2.stdout)

    def test_partial_candidate_saved_but_not_enabled(self):
        def drop_one_target(cfg):
            cfg['rules'] = [r for r in cfg['rules'] if r['id'] != 'bigmodel/GLM-5.2/standard']
        proc = self.run_update('--candidate', str(self.candidate('partial', drop_one_target)), codes=(2,))
        self.assertEqual(proc.returncode, 2)
        self.assertIn('未启用', proc.stdout)
        self.assertIn('bigmodel/GLM-5.2', proc.stdout)
        self.assertEqual(self.default_id(), self.initial_default)
        self.assertTrue((self.skill / 'pricing/snapshots/test-partial.json').exists())

    def test_unknown_source_and_identity_collision_rejected(self):
        def bad_source(cfg):
            old, new = cfg['sources'][0]['url'], 'https://example.com/pricing'
            cfg['sources'][0]['url'] = new
            # Keep the references tied to the (now unknown) source so this test still
            # exercises the whitelist rejection, not the dangling-reference check.
            for rule in cfg['rules'] + cfg['mappings']:
                if rule['source']['reference'] == old:
                    rule['source']['reference'] = new
        proc = self.run_update('--candidate', str(self.candidate('badsrc', bad_source)), codes=(4,))
        self.assertIn('白名单', proc.stderr)
        self.assertFalse((self.skill / 'pricing/snapshots/test-badsrc.json').exists())
        self.assertEqual(self.default_id(), self.initial_default)
        # Same identity, different content: rejected, default intact.
        first = self.candidate('clash')
        self.run_update('--candidate', str(first))
        clash = json.loads(first.read_text())
        clash['rules'][0]['currency'] = 'XXX'
        clash_path = self.root / 'clash2.json'
        clash_path.write_text(json.dumps(clash))
        proc = self.run_update('--candidate', str(clash_path), codes=(4,))
        self.assertIn('新身份', proc.stderr)

    def test_v1_candidate_and_misc_guards(self):
        v1 = {'schema_version': 1, 'revision': 'v1c', 'rules': [], 'aliases': []}
        path = self.root / 'v1.json'
        path.write_text(json.dumps(v1))
        proc = self.run_update('--candidate', str(path), codes=(4,))
        self.assertIn('schema v2', proc.stderr)
        proc = self.run_update(codes=(4,))
        self.assertIn('--candidate', proc.stderr)
        proc = self.run_update('--candidate', str(self.candidate('mix')), '--update', codes=(4,))
        self.assertIn('不与', proc.stderr)
        # Normal queries never trigger updates; candidate file only for pricing-update.
        proc = subprocess.run([sys.executable, '-B', str(self.entry), 'sessions', '--harness', 'codex',
                               '--source', str(self.root), '--candidate', str(self.candidate('x'))],
                              capture_output=True, text=True, cwd=self.root,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(proc.returncode, 4)
        self.assertIn('--candidate 只用于', proc.stderr)

    def test_snapshots_symlink_escape_rejected_and_default_kept(self):
        # Ticket 08 S06: a snapshots directory linked outside the resource root must be
        # rejected outright — the old default and every existing snapshot stay, nothing
        # lands outside, and restoring the real directory lets the update proceed.
        real = self.skill / 'pricing' / 'snapshots'
        aside = self.skill / 'pricing' / 'snapshots.real'
        real.rename(aside)
        external = self.root / 'outside-prices'
        external.mkdir()
        (self.skill / 'pricing' / 'snapshots').symlink_to(external, target_is_directory=True)
        proc = self.run_update('--candidate', str(self.candidate('escape')), codes=(4,))
        self.assertIn('越界', proc.stderr)
        self.assertEqual(self.default_id(), self.initial_default)
        self.assertEqual(list(external.iterdir()), [])
        self.assertTrue((aside / (self.initial_default + '.json')).exists())
        (self.skill / 'pricing' / 'snapshots').unlink()
        aside.rename(real)
        proc = self.run_update('--candidate', str(self.candidate('escape2')))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.default_id(), 'test-escape2')

    def test_default_pointer_and_snapshot_reads_reject_symlink_escape(self):
        # Ticket 08 S06 read side: the default pointer and one snapshot file linked
        # outside the resource root are rejected at load, before any pricing use.
        pointer = self.skill / 'pricing' / 'default.json'
        outside_pointer = self.root / 'outside-pointer.json'
        outside_pointer.write_text(pointer.read_text(encoding='utf-8'), encoding='utf-8')
        snapshot = self.skill / 'pricing' / 'snapshots' / (self.initial_default + '.json')
        outside_snapshot = self.root / 'outside-snapshot.json'
        outside_snapshot.write_text(snapshot.read_text(encoding='utf-8'), encoding='utf-8')
        snapshot.unlink()
        snapshot.symlink_to(outside_snapshot)
        pointer.unlink()
        pointer.symlink_to(outside_pointer)
        probe = ("import sys; sys.path.insert(0, %r)\n"
                 "from token_audit import pricing\n"
                 "results = []\n"
                 "try:\n"
                 "    pricing.load_default(); results.append('LOADED')\n"
                 "except ValueError as exc:\n"
                 "    results.append('REJECTED:' + str(exc))\n"
                 "try:\n"
                 "    pricing.read_snapshot(%r); results.append('READ')\n"
                 "except ValueError as exc:\n"
                 "    results.append('REJECTED:' + str(exc))\n"
                 "print('\\n'.join(results))") % (str(self.skill / 'scripts'), self.initial_default)
        proc = subprocess.run([sys.executable, '-B', '-c', probe], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('REJECTED:价格资源路径越界', proc.stdout)
        self.assertNotIn('LOADED', proc.stdout)
        self.assertNotIn('\nREAD', proc.stdout)

    def test_dangling_source_reference_rejected(self):
        # Ticket 08 S07: rules may only cite sources this very candidate read; dropping
        # the OpenAI reads while keeping OpenAI rules must fail naming the missing URL.
        def drop_openai_sources(cfg):
            cfg['sources'] = [s for s in cfg['sources'] if 'openai' not in s['url']]
        proc = self.run_update('--candidate', str(self.candidate('dangling', drop_openai_sources)), codes=(4,))
        self.assertIn('未读取的来源', proc.stderr)
        self.assertFalse((self.skill / 'pricing/snapshots/test-dangling.json').exists())
        self.assertEqual(self.default_id(), self.initial_default)


class TimePresetCLI(PricingCLI):
    """Ticket 04: quick time ranges resolve once against the request's fixed cutoff."""

    def setUp(self):
        super().setUp()
        self.write([pmeta(), tctx(), usage(time=T1)])

    def saved_scope(self, path):
        return json.loads(self.run_cli('overview', '--source', str(self.log), '--to', END,
                                       '--time-preset', 'last_7d', '--format', 'json').stdout)['scope']

    def test_preset_resolves_absolute_bounds_and_recompute_keeps_them(self):
        # END anchors the preset; last_7d = END - 168h.
        result = json.loads(self.run_cli('overview', '--source', str(self.log), '--to', END,
                                         '--time-preset', 'last_7d', '--tz', '+08:00', '--format', 'json').stdout)
        scope = result['scope']
        self.assertEqual(scope['to'], END)
        expected_from = (datetime.fromisoformat(END.replace('Z', '+00:00')) - timedelta(hours=168)).isoformat()
        self.assertEqual(scope['from'], expected_from)
        saved = self.root / 'ov.json'
        self.run_cli('overview', '--source', str(self.log), '--to', END,
                     '--time-preset', 'last_7d', '--export', 'json', '--output', str(saved))
        recomputed = json.loads(self.run_cli('recompute', '--saved', str(saved), '--format', 'json').stdout)
        # Recompute keeps the SAVED absolute bounds; it does not reinterpret the preset.
        self.assertEqual(recomputed['scope']['from'], expected_from)
        self.assertEqual(recomputed['scope']['to'], END)

    def test_natural_presets_follow_selected_timezone(self):
        # END is 2026-09-02T00:00:00Z, a Wednesday; +08 local is Wednesday 08:00, so the
        # week's Monday-00:00 local (2026-08-31 00:00+08) is 2026-08-30T16:00:00Z.
        result = json.loads(self.run_cli('overview', '--source', str(self.log), '--to', END,
                                         '--time-preset', 'week', '--tz', '+08:00', '--format', 'json').stdout)
        self.assertEqual(result['scope']['from'], '2026-08-30T16:00:00+00:00')
        result = json.loads(self.run_cli('overview', '--source', str(self.log), '--to', END,
                                         '--time-preset', 'today', '--tz=-05:00', '--format', 'json').stdout)
        self.assertEqual(result['scope']['from'], '2026-09-01T05:00:00+00:00')
        result = json.loads(self.run_cli('overview', '--source', str(self.log), '--to', END,
                                         '--time-preset', 'all', '--format', 'json').stdout)
        self.assertIsNone(result['scope']['from'])

    def test_preset_guards(self):
        self.run_cli('overview', '--source', str(self.log), '--to', END,
                     '--time-preset', 'last_7d', '--from', '2026-01-01T00:00:00+00:00', codes=(4,))
        self.run_cli('report', '--source', str(self.log), '--session', 's', '--to', END,
                     '--time-preset', 'today', codes=(4,))
        saved = self.root / 'ov.json'
        self.run_cli('overview', '--source', str(self.log), '--to', END, '--export', 'json', '--output', str(saved))
        self.run_cli('recompute', '--saved', str(saved), '--time-preset', 'today', codes=(4,))
        self.run_cli('overview', '--source', str(self.log), '--to', END, '--time-preset', 'bogus', codes=(2,))
