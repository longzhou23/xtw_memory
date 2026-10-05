import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import Mock
from research_memory.chat_gateway import Inbox, make_server
from research_memory.contracts import Invalid
STATE={'messages':[{'id':'now','speaker':'actor_01','time':'2026-10-05T10:00:00+08:00','text':'继续白鹭计划。','replyTo':None}],'focusSpeakerId':'actor_01'}
class ContextGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.inbox=Inbox(Path(self.tmp.name)/'test.sqlite3')
    def reader(self):
        from research_memory.context_gateway import ContextReader
        return ContextReader(self.inbox,'unused',model_factory=lambda _:Mock())
    def test_http_reader_receives_exact_body(self):
        reader=Mock(read=Mock(return_value={'contextText':'{}'}))
        server=make_server(self.inbox,'x'*32,0,reader=reader)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        data={'scope':'s','currentState':STATE}
        request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/context',json.dumps(data).encode(),{'Authorization':'Bearer '+'x'*32,'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status,200);self.assertEqual(json.load(response)['contextText'],'{}')
        reader.read.assert_called_once_with(data)
    def test_unknown_fields_invalid_mode_and_boolean_rejected(self):
        for body in [{'scope':'s','currentState':STATE,'query':'hidden'}, {'scope':'s','currentState':STATE,'mode':'raw_retrieval'}, {'scope':'s','currentState':STATE,'autoSignificance':'yes'}]:
            with self.assertRaises(Invalid):self.reader().read(body)
    def test_pending_jobs_rejected_before_reader_load(self):
        self.inbox.message('s',{'id':'old','speaker':'p','time':'2026-10-04T10:00:00+08:00','text':'旧事'})
        with self.assertRaisesRegex(Invalid,'未完成'):self.reader().read({'scope':'s','currentState':STATE})
    def test_budget_contains_no_unjudged_candidates_or_partial_records(self):
        from research_memory.context_gateway import pack_context
        result={'workingContext':{'attention_diffusion':[]}}
        context,memories=pack_context(STATE,result,'attention_diffusion',512)
        self.assertEqual(json.loads(context)['memories'],[]);self.assertLessEqual(len(context),512)
        result['workingContext']['attention_diffusion']=[{'id':'a','label':'长'*1000,'sourceEventIds':['past']}]
        context,memories=pack_context(STATE,result,'attention_diffusion',512)
        self.assertEqual(memories,[]);self.assertNotIn('长',context)
    def test_current_state_over_budget_rejected(self):
        from research_memory.context_gateway import pack_context
        state=copy.deepcopy(STATE);state['messages'][0]['text']='长'*600
        with self.assertRaises(Invalid):pack_context(state,{'workingContext':{'attention_diffusion':[]}},'attention_diffusion',512)
    def setup_history(self):
        from contextlib import closing
        from research_memory.store import Store
        from tests.reader_fixture import load_demo
        with closing(Store(self.inbox.path)) as store:load_demo(store,'s')
    def real_reader(self,provider=None):
        from research_memory.context_gateway import ContextReader
        from tests.test_associative import FixtureVectors
        return ContextReader(self.inbox,'unused',provider_factory=lambda:provider,model_factory=lambda _:FixtureVectors())
    def test_snapshot_recall_persists_audit_not_vectors_or_graph_changes(self):
        from contextlib import closing
        from research_memory.store import Store
        self.setup_history();reader=self.real_reader()
        with closing(Store(self.inbox.path)) as store:before=store.graph('s')
        for mode in ('formed_multiquery','graph_expansion','attention_diffusion'):
            result=reader.read({'scope':'s','currentState':STATE,'mode':mode})
            self.assertEqual(result['mode'],mode);self.assertEqual(result['selectedMemories'],[])
            self.assertEqual(json.loads(result['contextText'])['memories'],[])
        with closing(Store(self.inbox.path)) as store:
            self.assertEqual(store.graph('s'),before)
            self.assertEqual(store.db.execute('select count(*) from recalls').fetchone()[0],3)
            self.assertFalse(store.db.execute("select 1 from sqlite_master where name='semantic_vectors'").fetchone())
    def test_significance_and_revision_conflict_no_partial_audit(self):
        from contextlib import closing
        from research_memory.store import Store
        from research_memory.context_gateway import ReadUnavailable
        self.setup_history()
        def generate(prompt,payload,schema):
            return {'judgments':[{'candidateId':c['id'],'utility':'USEFUL_CONTEXT','claimSupport':'SUPPORTED','currentAnchorIds':['now'],'mentionPolicy':'INTERNAL_ONLY','rationale':'synthetic'} for c in payload['candidates']]},{}
        state=copy.deepcopy(STATE);state['messages'][0]['speaker']='阿澈';state['focusSpeakerId']='阿澈'
        reader=self.real_reader(Mock(generate=generate))
        result=reader.read({'scope':'s','currentState':state,'mode':'formed_multiquery','autoSignificance':True})
        self.assertEqual(result['workingContextStatus'],'JUDGED_INTERNAL_CONTEXT')
        self.assertTrue(result['selectedMemories']);self.assertLessEqual(len(result['contextText']),8000)
        def mutate(prompt,payload,schema):
            with closing(Store(self.inbox.path)) as store:
                store.db.execute("update scopes set revision=revision+1 where id='s'");store.db.commit()
            return generate(prompt,payload,schema)
        reader.provider_factory=lambda:Mock(generate=mutate)
        with self.assertRaises(ReadUnavailable):reader.read({'scope':'s','currentState':state,'mode':'formed_multiquery','autoSignificance':True})
        with closing(Store(self.inbox.path)) as store:self.assertEqual(store.db.execute('select count(*) from recalls').fetchone()[0],1)
    def test_current_or_future_library_rejected_before_model(self):
        self.setup_history();state=copy.deepcopy(STATE);state['messages'][0]['time']='2026-10-01T09:00:00+08:00'
        with self.assertRaisesRegex(Invalid,'未来'):self.real_reader().read({'scope':'s','currentState':state})
    def test_significance_failure_never_publishes_partial_audit(self):
        from contextlib import closing
        from research_memory.store import Store
        self.setup_history();state=copy.deepcopy(STATE);state['messages'][0]['speaker']='阿澈';state['focusSpeakerId']='阿澈'
        reader=self.real_reader(Mock(generate=Mock(side_effect=Invalid('provider failed'))))
        with self.assertRaises(Invalid):reader.read({'scope':'s','currentState':state,'mode':'formed_multiquery','autoSignificance':True})
        with closing(Store(self.inbox.path)) as store:self.assertEqual(store.db.execute('select count(*) from recalls').fetchone()[0],0)
