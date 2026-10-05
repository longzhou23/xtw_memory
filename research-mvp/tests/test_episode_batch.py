"""Real FIFO batching transactions and frozen policy; synthetic writer only."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from research_memory.store import Store
from research_memory.contracts import Invalid

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.s=Store(':memory:');self.addCleanup(self.s.close)
    def event(self,i):
        return {'id':f'e{i}','speaker':'p','time':f'2026-10-05T10:{i:02d}:00+08:00','text':f'事实{i}','role':'user','media':'text_only','displayName':'甲','replyTo':f'e{i-1}' if i else None}
    def episode(self,batch=3):self.s.create_episode('s','A','A',lifecycle='episode',capacity=6,eviction_batch=batch)
    def writer(self):
        class Writer:
            name='synthetic-batch'
            def __init__(self):self.inputs=[]
            def generate(self,prompt,payload,schema):
                self.inputs.append(copy.deepcopy(payload))
                return {'records':[{'localRecordId':e['id'],'kind':'supported_statement','subjectRefs':['p'],'text':e['content'],'directSourceEventIds':[e['id']],'usedMemoryIds':[],'supersedes':[]} for e in payload['sourceEvents']]},{}
        return Writer()
    def test_batch_eviction_and_causal_sources_reduce_calls(self):
        self.episode();model=self.writer()
        for i in range(10):self.s.advance_episode('s','A',self.event(i),model=model)
        state=self.s.episode_state('s','A')
        self.assertEqual(len(model.inputs),2)
        self.assertEqual([[e['id'] for e in p['sourceEvents']] for p in model.inputs],[['e0','e1','e2'],['e3','e4','e5']])
        self.assertEqual([e['id'] for e in state['workingContext']],['e6','e7','e8','e9'])
        self.assertEqual([r[0] for r in self.s.db.execute('select id from events where processed=1 order by seq')],['e0','e1','e2','e3','e4','e5'])
        self.assertTrue(all(e['id']!='e7' for e in model.inputs[0]['episodeContext']['localContext']))
        self.assertEqual(model.inputs[0]['sourceEvents'][1]['replyTo'],'e0')
        self.assertEqual(len(state['history']),6)
    def test_single_item_control_uses_same_capacity(self):
        self.episode(batch=1);model=self.writer()
        for i in range(10):self.s.advance_episode('s','A',self.event(i),model=model)
        self.assertEqual(len(model.inputs),4)
        self.assertEqual(len(self.s.episode_state('s','A')['workingContext']),6)
    def test_sql_failure_rolls_back_every_evicted_item(self):
        self.episode()
        for i in range(6):self.s.advance_episode('s','A',self.event(i))
        before=self.s.episode_state('s','A')
        self.s.db.execute("CREATE TEMP TRIGGER reject_last BEFORE INSERT ON episode_temporary WHEN NEW.id LIKE '%:e2' BEGIN SELECT RAISE(ABORT,'batch failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'batch failure'):self.s.advance_episode('s','A',self.event(6),model=self.writer())
        self.assertEqual(self.s.episode_state('s','A'),before)
        self.assertEqual(self.s.db.execute('select sum(processed) from events').fetchone()[0],0)
        self.assertEqual(self.s.db.execute('select status from writes').fetchone()[0],'FAILED')
        self.assertEqual(self.s.db.execute('select count(*) from episode_busy').fetchone()[0],0)
    def test_source_change_in_any_evicted_item_rejects_whole_write(self):
        self.episode()
        for i in range(6):self.s.advance_episode('s','A',self.event(i))
        s=self.s;fixed=self.writer()
        class Mutation:
            name='synthetic-mutator'
            def generate(self,*args):
                out=fixed.generate(*args)
                with s.db:s.db.execute("update events set text='变了' where id='e2'")
                return out
        with self.assertRaisesRegex(Invalid,'来源版本'):s.advance_episode('s','A',self.event(6),model=Mutation())
        self.assertEqual(s.db.execute('select count(*) from episode_temporary').fetchone()[0],0)
        self.assertEqual(s.db.execute('select count(*) from events').fetchone()[0],6)
    def test_policy_frozen_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'new.db'
            s=Store(p);s.create_episode('s','A','A',lifecycle='episode',capacity=6,eviction_batch=3);s.close()
            s=Store(p);self.addCleanup(s.close)
            self.assertEqual(s.episode_state('s','A')['evictionBatch'],3)
            with self.assertRaisesRegex(Invalid,'不可'):s.create_episode('s','A','A',lifecycle='episode',capacity=6,eviction_batch=1)
    def test_invalid_batch_rejected_before_episode_publication(self):
        for value in (0,7,True,1.5):
            with self.subTest(value=value),self.assertRaises(Invalid):self.episode(value)
        self.assertEqual(self.s.db.execute('select count(*) from episodes').fetchone()[0],0)
    def test_old_v1_database_rejected_without_migration(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.db';db=sqlite3.connect(p)
            db.execute('create table private(value text)');db.execute('pragma application_id=1129467223');db.execute('pragma user_version=1');db.commit();db.close()
            before=p.read_bytes()
            with self.assertRaisesRegex(Invalid,'schema'):Store(p)
            self.assertEqual(p.read_bytes(),before)
