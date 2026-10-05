"""Durable local ingress. Synthetic models verify delivery, never accuracy."""
import json
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'router_deploy'))
from research_memory.contracts import Invalid
from research_memory.store import Store
from tests.test_routing_runtime import Scorer, Writer
from research_memory.chat_gateway import Inbox, Worker, make_server, run_worker


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'chat.sqlite3'
        self.inbox=Inbox(self.path)
        self.scorer,self.writer=Scorer(),Writer()
        self.worker=Worker(self.inbox,self.scorer,self.writer)
        self.addCleanup(self.worker.close)
    def event(self,i,**kw):
        return {'id':f'e{i}','speaker':'甲','time':f'2026-10-05T10:00:{i:02}+08:00','text':f'事实{i}',**kw}
    def put(self,i,scope='群A',**kw):return self.inbox.message(scope,self.event(i,**kw))
    def drain(self):
        while self.worker.step():pass
    def test_receipt_durable_before_worker_and_duplicate_after_done(self):
        a=self.put(0);self.assertEqual(a['status'],'QUEUED')
        with closing(Store(self.path)) as s:self.assertEqual(s.db.execute('select count(*) from events').fetchone()[0],0)
        b=Inbox(self.path).message('群A',self.event(0));self.assertEqual(a['jobId'],b['jobId']);self.assertTrue(b['duplicate'])
        self.drain();self.assertEqual(self.inbox.get(a['jobId'])['status'],'DONE')
        self.put(0);self.assertEqual(len(self.scorer.inputs),0)
        with self.assertRaisesRegex(Invalid,'内容'):self.put(0,text='更改了')
    def test_fifo_temporary_final_and_idempotent_close(self):
        for i in range(14):self.put(i)
        self.drain();self.assertEqual(len(self.writer.inputs),1)
        close=self.inbox.close_scope('群A','finish');self.drain()
        self.assertEqual(self.inbox.get(close['jobId'])['status'],'DONE');self.assertEqual(len(self.writer.inputs),2)
        self.inbox.close_scope('群A','finish');self.drain();self.assertEqual(len(self.writer.inputs),2)
        self.assertEqual(len(self.writer.inputs[-1]['events']),14)
    def test_known_failure_blocks_scope_only_retry_uses_saved_choice(self):
        for i in range(13):self.put(i)
        for i in range(12):self.worker.step()
        self.writer.fail=True;self.worker.step();failed=self.inbox.list('群A')[-1]
        self.assertEqual(failed['status'],'FAILED')
        self.put(13);other=self.put(0,scope='群B');self.worker.step()
        self.assertEqual(self.inbox.get(other['jobId'])['status'],'DONE')
        calls=len(self.scorer.inputs);self.writer.fail=False;self.inbox.retry(failed['jobId']);self.worker.step()
        self.assertEqual(len(self.scorer.inputs),calls);self.drain()
        self.assertEqual(self.inbox.list('群A')[-1]['status'],'DONE')
    def test_restart_queued_and_committed_receipt_gap(self):
        a=self.put(0);self.worker.step()
        with closing(Store(self.path)) as s:s.db.execute("update chat_jobs set status='RUNNING' where id=?",(a['jobId'],));s.db.commit()
        self.worker.close();new=Worker(Inbox(self.path),self.scorer,self.writer);self.addCleanup(new.close)
        self.assertEqual(self.inbox.get(a['jobId'])['status'],'DONE')
        b=self.put(1);new.step();self.assertEqual(self.inbox.get(b['jobId'])['status'],'DONE')
    def test_restart_unknown_writer_pending_never_reissues(self):
        for i in range(13):self.put(i)
        for _ in range(12):self.worker.step()
        self.writer.fail=True;self.worker.step();job=self.inbox.list('群A')[-1]
        with closing(Store(self.path)) as s:
            s.db.execute("update chat_jobs set status='RUNNING' where id=?",(job['jobId'],))
            s.db.execute("update writes set status='PENDING' where scope='群A'");s.db.commit()
        self.worker.close();new=Worker(self.inbox,self.scorer,self.writer);self.addCleanup(new.close)
        calls=len(self.writer.inputs);self.assertEqual(self.inbox.get(job['jobId'])['status'],'REVIEW')
        with self.assertRaisesRegex(Invalid,'核查'):self.inbox.retry(job['jobId'])
        new.step();self.assertEqual(len(self.writer.inputs),calls)
    def test_late_long_and_unreadable_archived_without_time_or_text_change(self):
        self.put(1);self.worker.step()
        late=self.put(0);long=self.put(2,text='汉'*1025)
        media=self.put(3,text='',media='unreadable');self.drain()
        for job in (late,long,media):self.assertEqual(self.inbox.get(job['jobId'])['status'],'ARCHIVED')
        self.assertEqual(self.inbox.get(late['jobId'])['event']['time'],self.event(0)['time'])
        self.assertEqual(self.inbox.get(long['jobId'])['event']['text'],'汉'*1025)
        self.assertEqual(self.inbox.get(media['jobId'])['event']['text'],'')
        next_job=self.put(4);self.drain();self.assertEqual(self.inbox.get(next_job['jobId'])['status'],'DONE')
    def test_limits_backpressure_and_idempotence_at_capacity(self):
        self.worker.close();self.tmp.cleanup();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        inbox=Inbox(Path(self.tmp.name)/'limits.db',max_pending=1,max_rows=2,max_bytes=2000)
        first=inbox.message('s',self.event(0));self.assertTrue(inbox.message('s',self.event(0))['duplicate'])
        with self.assertRaisesRegex(Invalid,'容量'):inbox.message('s',self.event(1))
        self.assertEqual(len(inbox.list('s')),1)
    def test_reject_old_db_settings_change_and_second_worker(self):
        old=Path(self.tmp.name)/'old.db'
        with closing(Store(old)):pass
        with self.assertRaisesRegex(Invalid,'新库'):Inbox(old)
        with self.assertRaisesRegex(Invalid,'配置'):Inbox(self.path,max_pending=2)
        with self.assertRaisesRegex(Invalid,'工作'):Worker(self.inbox,self.scorer,self.writer)
    def test_idle_close_scheduler_and_no_tick_before_due(self):
        self.put(0);self.worker.step()
        self.assertEqual(self.worker.schedule_idle('2026-10-05T10:14:59+08:00'),0)
        self.assertEqual(self.worker.schedule_idle('2026-10-05T10:15:00+08:00'),1)
        self.assertEqual(self.worker.schedule_idle('2026-10-05T10:15:01+08:00'),0)
        self.drain();self.assertEqual(len(self.writer.inputs),1)
        self.assertEqual(self.inbox.list('群A')[-1]['kind'],'tick')
    def test_http_acceptance_is_independent_of_slow_worker_and_auth(self):
        server=make_server(self.inbox,'test-token',0);self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,data=None,token='test-token'):
            headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'}
            return urllib.request.urlopen(urllib.request.Request(base+path,json.dumps(data).encode() if data else None,headers),timeout=2)
        with self.assertRaises(urllib.error.HTTPError) as error:request('/api/jobs?scope=s',token='wrong')
        self.assertEqual(error.exception.code,401)
        error.exception.close()
        with request('/api/messages',{'scope':'s','event':self.event(0)}) as response:
            self.assertEqual(response.status,202);first=json.load(response)
        started=time.monotonic()
        with request('/api/messages',{'scope':'s','event':self.event(1)}) as response:self.assertEqual(response.status,202)
        self.assertLess(time.monotonic()-started,1)
        self.assertEqual(self.inbox.get(first['jobId'])['status'],'QUEUED')
        with request('/health') as response:self.assertEqual(json.load(response)['queued'],2)
        with request('/api/stop',{'confirm':True}) as response:self.assertEqual(response.status,202)
        thread.join(2);self.assertFalse(thread.is_alive())
    def test_unknown_call_requires_operator_confirmation_before_retry(self):
        for i in range(13):self.put(i)
        for _ in range(12):self.worker.step()
        self.writer.fail=True;self.worker.step();job=self.inbox.list('群A')[-1]
        with closing(Store(self.path)) as s:
            s.db.execute("update chat_jobs set status='REVIEW' where id=?",(job['jobId'],))
            s.db.execute("update writes set status='PENDING' where scope='群A'");s.db.commit()
        with self.assertRaisesRegex(Invalid,'确认'):self.inbox.confirm_ended(job['jobId'],False)
        self.inbox.confirm_ended(job['jobId'],True);self.writer.fail=False
        self.inbox.retry(job['jobId']);self.worker.step()
        self.assertEqual(self.inbox.get(job['jobId'])['status'],'DONE')
    def test_running_without_routing_receipt_recovers_before_model_call(self):
        a=self.put(0)
        with closing(Store(self.path)) as s:s.db.execute("update chat_jobs set status='RUNNING' where id=?",(a['jobId'],));s.db.commit()
        self.worker.close();new=Worker(self.inbox,self.scorer,self.writer);self.addCleanup(new.close)
        self.assertEqual(self.inbox.get(a['jobId'])['status'],'QUEUED')
        new.step();self.assertEqual(self.inbox.get(a['jobId'])['status'],'DONE')
    def test_final_failure_can_retry_and_raw_commits_remain(self):
        self.put(0);self.worker.step();job=self.inbox.close_scope('群A','close')
        self.writer.fail=True;self.worker.step();self.assertEqual(self.inbox.get(job['jobId'])['status'],'FAILED')
        self.assertEqual(self.inbox.list('群A')[0]['status'],'DONE')
        self.writer.fail=False;self.inbox.retry(job['jobId']);self.worker.step()
        self.assertEqual(self.inbox.get(job['jobId'])['status'],'DONE')
    def test_readable_caption_preserved_and_unknown_fields_rejected(self):
        job=self.put(0,text='这是待核实的图片说明',media='unreadable',replyTo='outside')
        self.drain();self.assertEqual(self.inbox.get(job['jobId'])['status'],'DONE')
        with self.assertRaises(Invalid):self.put(1,gold='topic')
        self.assertEqual(len(self.inbox.list('群A')),1)
    def test_source_times_with_different_offsets_idle_uses_event_order(self):
        self.put(0,time='2026-10-05T10:00:00+08:00');self.put(1,time='2026-10-05T02:10:00Z');self.drain()
        self.assertEqual(self.worker.schedule_idle('2026-10-05T02:15:00Z'),0)
        self.assertEqual(self.worker.schedule_idle('2026-10-05T02:25:00Z'),1)
    def test_http_receives_while_real_worker_thread_waits_on_writer(self):
        self.worker.close();entered=threading.Event();release=threading.Event();stop=threading.Event()
        original=self.writer.generate
        def slow(*args):entered.set();release.wait(3);return original(*args)
        self.writer.generate=slow
        def run():
            worker=Worker(self.inbox,self.scorer,self.writer)
            try:
                while not stop.is_set():
                    if not worker.step():stop.wait(.01)
            finally:worker.close()
        thread=threading.Thread(target=run);thread.start()
        self.addCleanup(lambda: (release.set(),stop.set(),thread.join(4)))
        for i in range(13):self.put(i)
        self.assertTrue(entered.wait(2))
        server=make_server(self.inbox,'test-token',0)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/messages',json.dumps({'scope':'群B','event':self.event(0)}).encode(),{'Authorization':'Bearer test-token','Content-Type':'application/json'})
        started=time.monotonic()
        with urllib.request.urlopen(req,timeout=1) as response:self.assertEqual(response.status,202)
        self.assertLess(time.monotonic()-started,1)
    def test_second_start_cannot_overwrite_live_worker_health(self):
        run_worker(self.inbox,self.scorer,self.writer,threading.Event())
        self.assertEqual(self.inbox.health()['worker'],'READY')
    def test_raw_archive_capacity_does_not_prevent_finalization(self):
        self.worker.close()
        inbox=Inbox(Path(self.tmp.name)/'small.db',max_rows=1)
        worker=Worker(inbox,self.scorer,self.writer);self.addCleanup(worker.close)
        inbox.message('s',self.event(0));worker.step()
        with self.assertRaisesRegex(Invalid,'容量'):inbox.message('s',self.event(1))
        close=inbox.close_scope('s','finish');worker.step()
        self.assertEqual(inbox.get(close['jobId'])['status'],'DONE')


if __name__=='__main__':unittest.main()
