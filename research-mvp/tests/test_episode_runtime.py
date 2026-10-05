"""Original Episode collection semantics, using explicit drafts, not quality claims."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from research_memory.contracts import Invalid
from research_memory.episode_final import prepare as final_input
from research_memory.store import Store


class EpisodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)

    def create(self, ident='A', capacity=1, scope='s'):
        return self.store.create_episode(scope,ident,ident,lifecycle='episode',capacity=capacity)

    def event(self, ident, minute=0, body=None, speaker='same-person'):
        return {'id':ident,'speaker':speaker,'time':f'2026-10-02T10:{minute:02d}:00+00:00','text':body or ident}

    def draft(self, body='Episode checkpoint', used=(), supersedes=()):
        return {'records':[{'localRecordId':'r','kind':'supported_statement','subjectRefs':['same-person'],'text':body,
                'directSourceEventIds':[], 'usedMemoryIds':list(used),'supersedes':list(supersedes)}]}

    def advance(self, ep, ident, minute=0, **kwargs):
        draft=kwargs.get('draft')
        if draft is not None:
            draft['records'][0]['directSourceEventIds']=[self.store.episode_state('s',ep)['workingContext'][0]['id']]
        return self.store.advance_episode('s',ep,self.event(ident,minute),**kwargs)

    def final(self, ep='A', used=None):
        state = self.store.episode_state('s',ep)
        events = [dict(e) for e in self.store.db.execute('SELECT * FROM events WHERE scope=? AND episode=? ORDER BY seq',('s',ep))]
        used = [m['id'] for m in state['history']] if used is None else list(used)
        evidence = [{'eventId':e['id'],'quote':e['text']} for e in events]
        return {'write':{'entities':[{'key':'p','type':'PERSON','label':'same-person','speakerId':'same-person','evidence':evidence[:1]}],
            'memories':[{'key':'m','kind':'EPISODIC','recordKind':'supported_statement','text':' / '.join(e['text'] for e in events),'subject':'p',
                         'evidence':evidence,'usedMemoryIds':used,'supersedes':[]}],
            'associations':[{'source':'p','target':'m','relation':'SIMILARITY','strength':.6,
                             'evidence':evidence[:1],'rationale':'source-backed subject link'}],'skipped':[]},
            'temporaryDecisions':[{'memoryId':m['id'],'action':'USED' if m['id'] in used else 'ARCHIVE','reason':'reviewed fixture decision'} for m in state['history']]}

    def test_default_fifo_six_is_distinct_from_collection_and_zero_call_before_spill(self):
        self.create(capacity=6)
        calls=[]
        test=self
        class Model:
            name='explicit-fixture'
            def generate(self,prompt,payload,schema):
                calls.append(copy.deepcopy(payload));draft=test.draft();draft['records'][0]['directSourceEventIds']=[payload['sourceEvents'][0]['id']];return draft,{}
        for i in range(6):
            result=self.advance('A',f'a{i}',i,model=Model())
            self.assertEqual(result['modelCalls'],0)
        self.assertEqual(calls,[])
        self.assertEqual(self.store.episode_state('s','A')['temporaryMemories'],[])
        result=self.advance('A','a6',6,model=Model())
        self.assertEqual(result['modelCalls'],1)
        self.assertEqual(result['records'][0]['sourceEventIds'],['a0'])
        self.assertEqual([e['id'] for e in calls[0]['episodeContext']['localContext']],[f'a{i}' for i in range(1,7)])
        self.assertEqual(calls[0]['injectedMemories'],[])
        self.assertEqual(self.store.graph('s'),{'nodes':[],'edges':[]})

    def test_interleaved_same_subject_has_multiple_separate_episode_collections(self):
        self.create('A');self.create('B')
        self.advance('A','a1');self.advance('B','b1')
        a=self.advance('A','a2',1,draft=self.draft('A first'))['records'][0]
        b=self.advance('B','b2',1,draft=self.draft('B first'))['records'][0]
        self.advance('A','a3',2,draft=self.draft('A other topic'))
        self.advance('B','b3',2,draft=self.draft('B other topic'))
        for ep,first,last in [('A',a,'a3'),('B',b,'b3')]:
            state=self.store.episode_state('s',ep)
            self.assertEqual(len(state['temporaryMemories']),2)
            self.assertEqual(state['workingContext'][0]['id'],last)
            self.assertEqual(state['history'][-1]['memoryWriteProvenance']['injectedMemoryIds'],[first['id']])
            self.assertEqual(state['formedWith'],[])

    def test_used_ids_not_membership_create_exact_formed_with_without_semantic_edge(self):
        self.create();self.advance('A','a1')
        first=self.advance('A','a2',1,draft=self.draft())['records'][0]['id']
        second=self.advance('A','a3',2,draft=self.draft(used=[first]))['records'][0]['id']
        state=self.store.episode_state('s','A')
        self.assertEqual([(e['sourceMemoryId'],e['targetMemoryId'],e['relationType'],e['associationStrength']) for e in state['formedWith']],[(second,first,'FORMED_WITH',1)])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM edges').fetchone()[0],0)

    def test_superseding_one_record_preserves_other_active_and_all_history(self):
        self.create();self.advance('A','a1')
        first=self.advance('A','a2',1,draft=self.draft('first'))['records'][0]['id']
        self.advance('A','a3',2,draft=self.draft('independent'))
        self.advance('A','a4',3,draft=self.draft('corrected',used=[first],supersedes=[first]))
        state=self.store.episode_state('s','A')
        self.assertEqual(len(state['temporaryMemories']),2)
        self.assertEqual([m['status'] for m in state['history']],['ARCHIVED','ACTIVE','ACTIVE'])
        self.assertEqual(state['history'][0]['text'],'first')

    def test_provider_failure_leaves_pending_event_and_context_uncommitted(self):
        self.create();self.advance('A','a1');before=self.store.episode_state('s','A')
        class Fail:
            name='fixture-failure'
            def generate(self,*args):raise RuntimeError('failed')
        with self.assertRaisesRegex(RuntimeError,'failed'):
            self.advance('A','a2',1,model=Fail())
        self.assertEqual(self.store.episode_state('s','A'),before)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertEqual(self.store.db.execute('SELECT status FROM writes').fetchone()[0],'FAILED')
        self.advance('A','a2',1,draft=self.draft())
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)

    def test_invalid_usage_and_foreign_temporary_in_long_term_channel_fail_closed(self):
        self.create('A');self.create('B');self.advance('A','a1');self.advance('B','b1')
        foreign=self.advance('B','b2',1,draft=self.draft())['records'][0]['id']
        before=self.store.episode_state('s','A')
        for draft in (self.draft(used=[foreign]),self.draft(used=['missing']),self.draft(supersedes=[foreign])):
            with self.assertRaises(Invalid):self.advance('A','a2',1,draft=draft)
            self.assertEqual(self.store.episode_state('s','A'),before)
        with self.assertRaises(Invalid):self.advance('A','a2',1,draft=self.draft(),memory_ids=[foreign])

    def test_close_archives_complete_collection_and_leaves_other_episode_unchanged(self):
        self.create('A');self.create('B');self.advance('A','a1');self.advance('B','b1')
        self.advance('A','a2',1,draft=self.draft());self.advance('B','b2',1,draft=self.draft())
        before=self.store.episode_state('s','A');other=self.store.episode_state('s','B')
        self.assertEqual(self.store.close_episode('s','A')['status'],'CLOSED')
        after=self.store.episode_state('s','A')
        self.assertEqual(after['temporaryMemories'],[])
        for old,new in zip(before['history'],after['history']):
            self.assertEqual({k:v for k,v in old.items() if k!='status'},{k:v for k,v in new.items() if k!='status'})
            self.assertEqual(new['status'],'ARCHIVED')
        self.assertEqual(self.store.episode_state('s','B'),other)
        self.assertEqual(after['workingContext'],before['workingContext'])
        self.assertEqual(self.store.graph('s'),{'nodes':[],'edges':[]})
        with self.assertRaises(Invalid):self.store.reopen_episode('s','A')
        with self.assertRaises(Invalid):self.advance('A','a3',2,draft=self.draft())
        self.store.close_episode('s','A')
        self.assertEqual(self.store.episode_state('s','A'),after)

    def test_short_episode_closes_without_checkpoint_and_final_uses_remaining_raw_events(self):
        self.create(capacity=6);self.advance('A','a1');self.advance('A','a2',1)
        self.store.close_episode('s','A')
        bundle=final_input(self.store,'s','A')
        self.assertEqual(bundle['temporaryMemoryIds'],[])
        self.assertEqual([e['id'] for e in bundle['events']],['a1','a2'])
        result=self.store.consolidate('s','A',draft=self.final())
        self.assertEqual(result['episode']['status'],'CLOSED')
        self.assertEqual(result['consolidationState'],'COMMITTED')

    def test_same_episode_inflight_rejected_other_episode_can_progress_without_staling_result(self):
        self.create('A');self.create('B');self.advance('A','a1');self.advance('B','b1')
        test=self
        class Model:
            name='fixture-interleaving'
            def generate(self,prompt,payload,schema):
                with test.assertRaisesRegex(Invalid,'在途'):test.advance('A','a3',2,draft=test.draft())
                test.advance('B','b2',1,draft=test.draft())
                draft=test.draft();draft['records'][0]['directSourceEventIds']=[payload['sourceEvents'][0]['id']];return draft,{}
        result=self.advance('A','a2',1,model=Model())
        self.assertEqual(result['records'][0]['status'],'ACTIVE')
        self.assertEqual(len(self.store.episode_state('s','B')['history']),1)

    def test_close_during_provider_call_invalidates_capture_without_append_or_partial_memory(self):
        self.create();self.advance('A','a1');test=self
        class Model:
            name='fixture-close'
            def generate(self,prompt,payload,schema):
                test.store.close_episode('s','A');draft=test.draft();draft['records'][0]['directSourceEventIds']=[payload['sourceEvents'][0]['id']];return draft,{}
        with self.assertRaisesRegex(Invalid,'过期'):self.advance('A','a2',1,model=Model())
        state=self.store.episode_state('s','A')
        self.assertEqual(state['episode']['status'],'CLOSED')
        self.assertEqual(state['history'],[])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)

    def test_working_context_collection_and_idempotency_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'runtime.sqlite3';a=Store(path)
            try:
                a.create_episode('s','A','A',lifecycle='episode',capacity=1)
                a.advance_episode('s','A',self.event('a1'))
                a.advance_episode('s','A',self.event('a2',1),draft={**self.draft(),'records':[{**self.draft()['records'][0],'directSourceEventIds':['a1']}]})
                before=a.episode_state('s','A')
            finally:a.close()
            b=Store(path)
            try:
                self.assertEqual(b.episode_state('s','A'),before)
                result=b.advance_episode('s','A',self.event('a1'))
                self.assertEqual((result['duplicates'],result['modelCalls']),(1,0))
                b.advance_episode('s','A',self.event('a3',2),draft={**self.draft(),'records':[{**self.draft()['records'][0],'directSourceEventIds':['a2']}]})
                self.assertEqual(len(b.episode_state('s','A')['history']),2)
                self.assertEqual(b.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:b.close()

    def test_final_failure_leaves_episode_closed_archives_unchanged_and_no_durable_graph(self):
        self.create();self.advance('A','a1');self.advance('A','a2',1,draft=self.draft())
        self.store.close_episode('s','A');before=self.store.episode_state('s','A')
        class Model:
            name='fixture-fail'
            def generate(self,*args):raise RuntimeError('failed final')
        with self.assertRaisesRegex(RuntimeError,'failed final'):self.store.consolidate('s','A',model=Model())
        after=self.store.episode_state('s','A')
        self.assertEqual(after['episode']['status'],'CLOSED')
        self.assertEqual(after['history'],before['history'])
        self.assertEqual(after['finalConsolidation'],'FAILED')
        self.assertEqual(self.store.graph('s'),{'nodes':[],'edges':[]})

    def test_final_keeps_archives_and_formed_with_separate_from_new_semantic_graph(self):
        self.create();self.advance('A','a1');first=self.advance('A','a2',1,draft=self.draft())['records'][0]['id']
        self.advance('A','a3',2,draft=self.draft(used=[first]));self.store.close_episode('s','A')
        before=self.store.episode_state('s','A')
        result=self.store.consolidate('s','A',draft=self.final())
        after=self.store.episode_state('s','A')
        self.assertEqual(after['history'],before['history']);self.assertEqual(after['formedWith'],before['formedWith'])
        self.assertEqual(after['episode']['status'],'CLOSED');self.assertEqual(after['temporaryMemories'],[])
        graph=self.store.graph('s');self.assertEqual(len(graph['nodes']),2)
        self.assertEqual([e['relation'] for e in graph['edges']],['SIMILARITY'])
        self.assertEqual(graph['nodes'][-1]['usedMemoryIds'],[m['id'] for m in before['history']])
        self.assertEqual(self.store.consolidate('s','A',draft=self.final())['writeId'], result['writeId'])
        self.assertEqual(result['metadata']['phase'],'EPISODE_FINAL')

    def test_same_speaker_final_identity_reuse_does_not_require_closing_other_open_episode(self):
        self.create('A');self.create('B');self.advance('A','a1');self.advance('B','b1')
        self.store.close_episode('s','A');a=self.store.consolidate('s','A',draft=self.final('A'))
        self.advance('B','b2',1,draft=self.draft());self.store.close_episode('s','B')
        b=self.store.consolidate('s','B',draft=self.final('B'))
        self.assertEqual(a['mapping']['p'],b['mapping']['p'])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM nodes WHERE speaker_id='same-person'").fetchone()[0],1)

    def test_invalid_final_usage_or_missing_decision_cannot_publish_partial_graph(self):
        self.create();self.advance('A','a1');self.advance('A','a2',1,draft=self.draft());self.store.close_episode('s','A')
        base=self.final();bad=copy.deepcopy(base);bad['temporaryDecisions']=[]
        wrong=copy.deepcopy(base);wrong['temporaryDecisions'][0]['action']='ARCHIVE'
        fake=copy.deepcopy(base);fake['write']['memories'][0]['evidence'][0]['quote']='not source text'
        for draft in (bad,wrong,fake):
            with self.assertRaises(Invalid):self.store.consolidate('s','A',draft=draft)
            self.assertEqual(self.store.graph('s'),{'nodes':[],'edges':[]})
            self.assertEqual(self.store.episode_state('s','A')['episode']['status'],'CLOSED')

    def test_old_bulk_checkpoint_and_scoped_final_cannot_bypass_episode_contract(self):
        self.create()
        with self.assertRaises(Invalid):self.store.ingest('s','A',[self.event('a1')])
        with self.assertRaises(Invalid):self.store.checkpoint('s','A',draft={})
        with self.assertRaises(Invalid):self.store.consolidate('s','A',draft={},temporary_ids=['fake'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM writes').fetchone()[0],0)


if __name__=='__main__':unittest.main()
