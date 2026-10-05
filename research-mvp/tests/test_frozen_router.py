"""Frozen two-judge policy plumbing; inference mocked, no semantic claims."""
import copy
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'router_deploy'))
from xtw_router.frozen import FrozenTwoJudgeCPU

class FrozenTests(unittest.TestCase):
    def model(self,threshold=.5):
        model=FrozenTwoJudgeCPU.__new__(FrozenTwoJudgeCPU)
        model.threshold=threshold;model.requests=model.passes=0;model.inputs=[]
        model.max_requests=2;model.max_passes=4;model.active_seconds=0;model.max_seconds=600
        model.rss_stop_mib=12288;model.boundary='boundary';model.ranking='ranking'
        self.calls=[]
        def forward(agent,state,question,order):
            self.calls.append((agent,state,question,order));model.passes+=1
            probabilities=[.4,.6] if agent=='boundary' else [.2,.8]
            return [probabilities[i] for i in order],20
        model.forward=forward
        return model
    def payload(self):
        old={'message_id':'e0','participant_id':'甲','timestamp':'2026-10-05T10:00:00+08:00','text':'手机预算','sequence_index':0}
        return {'conversation_id':'s','target':{'message_id':'e1','participant_id':'甲','timestamp':'2026-10-05T10:00:01+08:00','text':'三千','sequence_index':1,'reply_to_message_id':'e0'},'prior_context':[old],'candidates':[{'episode_id':'a','member_message_ids':['e0'],'first_messages':[old],'recent_messages':[old]},{'episode_id':'b','member_message_ids':['other'],'first_messages':[{**old,'message_id':'other'}],'recent_messages':[],'summary':'笔记本'}]}
    def test_empty_has_no_encoder(self):
        model=self.model();p=self.payload();p['candidates']=[]
        self.assertEqual(model.route(p)['encoder_passes'],0);self.assertEqual(model.requests,0)
    def test_same_probabilities_threshold_only_changes_boundary(self):
        a=self.model(.5);b=self.model(.75);p=self.payload()
        self.assertEqual(a.route(p)['decision'],'NEW');result=b.route(p)
        self.assertEqual(result['decision'],'CONTINUE');self.assertEqual(result['episode_id'],'b')
        self.assertEqual(result['encoder_passes'],2);self.assertIn('[包含回复目标]',self.calls[1][1])
    def test_pre_inference_budgets_fail_without_calls(self):
        for name,value in [('requests',2),('passes',4),('active_seconds',600)]:
            model=self.model();setattr(model,name,value)
            with self.assertRaisesRegex(RuntimeError,'budget'):model.route(self.payload())
            self.assertEqual(self.calls,[])
    def test_invalid_before_request_or_encoder(self):
        model=self.model();p=self.payload();p['target']['gold']='a'
        with self.assertRaises(ValueError):model.route(p)
        self.assertEqual(model.requests,0)
    def test_forward_input_and_prediction_are_saved_by_value(self):
        model=self.model(.75);p=self.payload();result=model.route(p)
        p['target']['text']='变了';result['scores'].clear()
        self.assertEqual(model.inputs[0]['payload']['target']['text'],'三千')
        self.assertTrue(model.inputs[0]['result']['scores'])
        self.assertEqual(len(model.inputs[0]['formatted_inputs']),2)
    def test_service_budgets_explicitly_disabled_and_trace_bounded(self):
        model=self.model(.75)
        model.max_requests=model.max_passes=model.max_seconds=None
        model.trace_limit=2
        for _ in range(5):model.route(self.payload())
        self.assertEqual(model.requests,5);self.assertEqual(model.passes,10)
        self.assertEqual(len(model.inputs),2)
    def test_invalid_service_settings_before_model_loading(self):
        for kwargs in ({'max_requests':0},{'max_passes':True},{'max_seconds':-1},
                       {'trace_limit':-1},{'trace_limit':True},{'rss_stop_mib':None}):
            with self.assertRaises(ValueError):FrozenTwoJudgeCPU('/missing',**kwargs)
