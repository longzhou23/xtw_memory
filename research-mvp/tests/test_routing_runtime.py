"""Durable autonomous Router -> actual FIFO/Final, no real model calls."""
import copy
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'router_deploy'))
from research_memory.store import Store
from research_memory.contracts import Invalid
from research_memory.routing import RouterRuntime

class Scorer:
    def __init__(self,answers=()):self.answers=list(answers);self.inputs=[]
    def route(self,payload):
        self.inputs.append(copy.deepcopy(payload))
        if self.answers:
            result=self.answers.pop(0)
            if isinstance(result,BaseException):raise result
            return result(payload) if callable(result) else result
        return {'decision':'CONTINUE','episode_id':payload['candidates'][0]['episode_id']}
class Writer:
    name='synthetic-routing-writer'
    def __init__(self):self.inputs=[];self.fail=False
    def generate(self,prompt,payload,schema):
        self.inputs.append(copy.deepcopy(payload))
        if self.fail:raise RuntimeError('writer failure')
        if 'sourceEvents' in payload:return {'records':[]},{}
        return {'write':{'entities':[],'memories':[],'associations':[],'skipped':[{'eventId':e['id'],'reason':'synthetic empty'} for e in payload['events']]},'temporaryDecisions':[{'memoryId':i,'action':'ARCHIVE','reason':'synthetic empty'} for i in payload['temporaryMemoryIds']]},{}

def new(payload=None):return {'decision':'NEW','episode_id':None}
def same(payload):return {'decision':'CONTINUE','episode_id':payload['candidates'][0]['episode_id']}
class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close);self.scorer=Scorer();self.writer=Writer()
        self.runtime=RouterRuntime(self.store,self.scorer,self.writer,ttl_seconds=900,max_span_seconds=3600)
    def event(self,i,**values):
        return {'id':f'e{i}','speaker':'p','time':(datetime.fromisoformat('2026-10-05T10:00:00+08:00')+timedelta(seconds=i)).isoformat(),'text':f'事实{i}','sequence':i,'replyTo':f'e{i-1}' if i else None,'displayName':'甲','role':'user','media':'text_only',**values}
    def test_no_candidate_new_zero_inference_and_raw_metadata_preserved(self):
        result=self.runtime.ingest('s',self.event(0))
        self.assertEqual(self.scorer.inputs,[])
        self.assertEqual(result['decision'],'NEW')
        state=self.store.episode_state('s',result['assigned_episode_id'])
        self.assertEqual(state['workingContext'][0]['displayName'],'甲')
        self.assertEqual(state['workingContext'][0]['media'],'text_only')
    def test_actual_wrong_group_forms_next_candidate_no_target_leak(self):
        first=self.runtime.ingest('s',self.event(0));self.runtime.ingest('s',self.event(1));self.runtime.ingest('s',self.event(2))
        payload=self.scorer.inputs[-1]
        self.assertEqual(payload['candidates'][0]['member_message_ids'],['e0','e1'])
        self.assertNotIn('e2',payload['candidates'][0]['member_message_ids'])
        self.assertEqual(first['assigned_episode_id'],payload['candidates'][0]['episode_id'])
    def test_actual_fifo_then_close_final_no_extra_route(self):
        for i in range(8):self.runtime.ingest('s',self.event(i))
        self.assertEqual(len(self.writer.inputs),1)
        self.assertEqual([e['id'] for e in self.writer.inputs[0]['sourceEvents']],['e0','e1','e2'])
        self.runtime.close_all('s')
        self.assertEqual(len(self.writer.inputs),2)
        self.assertEqual(len(self.writer.inputs[-1]['events']),8)
        self.runtime.close_all('s');self.assertEqual(len(self.writer.inputs),2)
        self.assertEqual(self.store.db.execute("select count(*) from routing_events where status='COMMITTED'").fetchone()[0],8)
    def test_duplicate_idempotent_conflict_rejected(self):
        first=self.runtime.ingest('s',self.event(0));again=self.runtime.ingest('s',self.event(0))
        self.assertEqual(first['assigned_episode_id'],again['assigned_episode_id']);self.assertTrue(again['duplicate'])
        with self.assertRaises(Invalid):self.runtime.ingest('s',self.event(0,text='变了'))
        self.assertEqual(self.scorer.inputs,[])
    def test_noncausal_and_gold_fields_rejected_before_inference(self):
        self.runtime.ingest('s',self.event(1))
        for event in [self.event(0),self.event(2,time='2026-10-04T00:00:00+08:00'),self.event(2,gold_episode='A')]:
            with self.assertRaises(Invalid):self.runtime.ingest('s',event)
        self.assertEqual(self.scorer.inputs,[])
    def test_router_failure_logged_and_never_new(self):
        self.runtime.ingest('s',self.event(0));self.scorer.answers=[RuntimeError('scorer failure')]
        with self.assertRaisesRegex(RuntimeError,'scorer failure'):self.runtime.ingest('s',self.event(1))
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],1)
        row=self.store.db.execute("select * from routing_events where event_id='e1'").fetchone()
        self.assertEqual(row['status'],'FAILED');self.assertIn('事实1',row['event'])
        with self.assertRaisesRegex(Invalid,'恢复'):self.runtime.ingest('s',self.event(2))
        self.runtime.resume('s','e1');self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],2)
    def test_candidate_outside_rejected_without_event_publication(self):
        self.runtime.ingest('s',self.event(0));self.scorer.answers=[{'decision':'CONTINUE','episode_id':'invented'}]
        with self.assertRaisesRegex(Invalid,'候选'):self.runtime.ingest('s',self.event(1))
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],1)
    def test_writer_failure_resume_keeps_decision_and_cursor(self):
        for i in range(6):self.runtime.ingest('s',self.event(i))
        self.writer.fail=True
        with self.assertRaisesRegex(RuntimeError,'writer failure'):self.runtime.ingest('s',self.event(6))
        calls=len(self.scorer.inputs)
        self.assertEqual(self.store.db.execute("select status from routing_events where event_id='e6'").fetchone()[0],'ROUTED')
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],6)
        self.writer.fail=False;self.runtime.resume('s','e6')
        self.assertEqual(len(self.scorer.inputs),calls)
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],7)
    def test_crash_after_writer_commit_resume_does_not_repeat_writer(self):
        for i in range(6):self.runtime.ingest('s',self.event(i))
        self.store.db.execute("CREATE TEMP TRIGGER stop_receipt BEFORE UPDATE ON routing_events WHEN NEW.status='COMMITTED' AND NEW.event_id='e6' BEGIN SELECT RAISE(ABORT,'receipt failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'receipt failure'):self.runtime.ingest('s',self.event(6))
        calls=len(self.writer.inputs);router_calls=len(self.scorer.inputs)
        self.store.db.execute('DROP TRIGGER stop_receipt');self.runtime.resume('s','e6')
        self.assertEqual(len(self.writer.inputs),calls);self.assertEqual(len(self.scorer.inputs),router_calls)
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],7)
    def test_ttl_closes_before_next_decision_closed_reply_not_reopened(self):
        first=self.runtime.ingest('s',self.event(0));later=self.event(1,time='2026-10-05T10:16:00+08:00',replyTo='e0')
        second=self.runtime.ingest('s',later)
        self.assertNotEqual(first['assigned_episode_id'],second['assigned_episode_id'])
        self.assertEqual(self.scorer.inputs,[])
        self.assertEqual(self.store.episode_state('s',first['assigned_episode_id'])['finalConsolidation'],'COMMITTED')
    def test_ttl_final_failure_retry_does_not_ignore_closed_unfinished(self):
        first=self.runtime.ingest('s',self.event(0));self.writer.fail=True
        with self.assertRaises(RuntimeError):self.runtime.ingest('s',self.event(1,time='2026-10-05T10:16:00+08:00'))
        self.writer.fail=False;self.runtime.resume('s','e1')
        self.assertEqual(self.store.episode_state('s',first['assigned_episode_id'])['finalConsolidation'],'COMMITTED')
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],2)
    def test_max_span_closes_despite_recent_activity(self):
        runtime=RouterRuntime(self.store,self.scorer,self.writer,ttl_seconds=900,max_span_seconds=100)
        first=runtime.ingest('s',self.event(0));runtime.ingest('s',self.event(1,time='2026-10-05T10:01:00+08:00'))
        later=runtime.ingest('s',self.event(2,time='2026-10-05T10:02:00+08:00'))
        self.assertNotEqual(first['assigned_episode_id'],later['assigned_episode_id'])
    def test_reentrant_same_scope_rejected_other_scope_allowed(self):
        self.runtime.ingest('s',self.event(0));runtime=self.runtime;test=self
        def nested(payload):
            with test.assertRaisesRegex(Invalid,'在途'):runtime.ingest('s',test.event(2))
            runtime.ingest('other',test.event(0))
            return same(payload)
        self.scorer.answers=[nested];self.runtime.ingest('s',self.event(1))
        self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],3)
    def test_restart_uses_committed_history_and_frozen_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'new.db';s=Store(path);a=RouterRuntime(s,self.scorer,self.writer)
            first=a.ingest('s',self.event(0));s.close()
            s=Store(path);self.addCleanup(s.close);b=RouterRuntime(s,self.scorer,self.writer)
            second=b.ingest('s',self.event(1))
            self.assertEqual(first['assigned_episode_id'],second['assigned_episode_id'])
            with self.assertRaisesRegex(Invalid,'设置'):RouterRuntime(s,self.scorer,self.writer,eviction_batch=1).ingest('s',self.event(2))
    def test_scope_context_never_contains_other_scope_events(self):
        self.runtime.ingest('other',self.event(0,text='别的群'))
        self.runtime.ingest('s',self.event(0));self.runtime.ingest('s',self.event(1))
        self.assertTrue(all(e['text']!='别的群' for e in self.scorer.inputs[-1]['prior_context']))
    def test_tick_refuses_time_backwards(self):
        self.runtime.ingest('s',self.event(1))
        with self.assertRaisesRegex(Invalid,'时间'):self.runtime.tick('s','2026-10-05T10:00:00+08:00')
    def test_changed_history_rejected_before_final_or_new_selection(self):
        self.runtime.ingest('s',self.event(0))
        self.store.db.execute("UPDATE events SET text='篡改' WHERE id='e0'");self.store.db.commit()
        with self.assertRaisesRegex(Invalid,'来源'):self.runtime.ingest('s',self.event(1,time='2026-10-05T10:16:00+08:00'))
        self.assertEqual(self.writer.inputs,[])
    def test_changed_history_after_route_failure_cannot_resume_stale_choice(self):
        for i in range(6):self.runtime.ingest('s',self.event(i))
        self.writer.fail=True
        with self.assertRaises(RuntimeError):self.runtime.ingest('s',self.event(6))
        self.writer.fail=False;self.store.db.execute("UPDATE events SET text='篡改' WHERE id='e0'");self.store.db.commit()
        with self.assertRaisesRegex(Invalid,'来源'):self.runtime.resume('s','e6')
    def test_count_limit_closes_before_next_event(self):
        runtime=RouterRuntime(self.store,self.scorer,self.writer,max_episode_events=2)
        first=runtime.ingest('s',self.event(0));runtime.ingest('s',self.event(1))
        third=runtime.ingest('s',self.event(2))
        self.assertNotEqual(first['assigned_episode_id'],third['assigned_episode_id'])
    def test_dead_lease_requires_explicit_resume_and_live_lease_blocks_it(self):
        import os
        self.runtime.ingest('s',self.event(0));self.scorer.answers=[RuntimeError('failed')]
        with self.assertRaises(RuntimeError):self.runtime.ingest('s',self.event(1))
        self.store.db.execute('UPDATE routing_scopes SET busy_pid=?,busy_token=? WHERE scope=?',(os.getpid(),'live','s'));self.store.db.commit()
        with self.assertRaisesRegex(Invalid,'在途'):self.runtime.resume('s','e1')
        self.store.db.execute('UPDATE routing_scopes SET busy_pid=2147483647 WHERE scope=?',('s',));self.store.db.commit()
        self.runtime.resume('s','e1')
    def test_pending_model_receipt_blocks_explicit_resume_without_retry(self):
        for i in range(6):self.runtime.ingest('s',self.event(i))
        self.writer.fail=True
        with self.assertRaises(RuntimeError):self.runtime.ingest('s',self.event(6))
        self.store.db.execute("UPDATE writes SET status='PENDING' WHERE scope='s'");self.store.db.commit()
        calls=len(self.writer.inputs)
        with self.assertRaisesRegex(Invalid,'PENDING'):self.runtime.resume('s','e6')
        self.assertEqual(len(self.writer.inputs),calls)
