"""Storage identifiers have equality semantics, not linguistic semantics."""
import copy
import unittest
import tests.test_frozen_router as fixtures
from xtw_router.frozen import make_questions


def rename(payload):
    p=copy.deepcopy(payload)
    message_ids={}
    speakers={}
    def mid(value):
        if value is None:return None
        return message_ids.setdefault(value, 'opaque-message-'+str(len(message_ids))+'z'*90)
    def speaker(value):
        return speakers.setdefault(value, 'arbitrary-speaker-'+str(len(speakers))+'q'*100)
    p['conversation_id']='opaque-conversation'
    p['request_id']='opaque-request'
    messages=[p['target']]+p['prior_context']
    for i,c in enumerate(p['candidates']):
        c['episode_id']='opaque-episode-'+str(i)
        c['member_message_ids']=[mid(v) for v in c['member_message_ids']]
        messages+=c['first_messages']+c['recent_messages']
    unique={id(m):m for m in messages}
    for m in unique.values():
        m['message_id']=mid(m['message_id']);m['participant_id']=speaker(m['participant_id'])
        if m.get('reply_to_message_id') is not None:m['reply_to_message_id']=mid(m['reply_to_message_id'])
    return p


class IdentityTests(unittest.TestCase):
    def test_all_identifier_renaming_leaves_model_input_and_orders_identical(self):
        p=fixtures.FrozenTests().payload();q=make_questions(p);other=make_questions(rename(p))
        self.assertEqual(q['boundary'],other['boundary'])
        self.assertEqual(q['ranking'],other['ranking'])
    def test_speaker_equality_reply_quote_and_current_text_survive(self):
        p=fixtures.FrozenTests().payload();p['target']['participant_id']='乙'
        q=make_questions(p)
        self.assertIn('P1: 手机预算',q['boundary']['state'])
        self.assertIn('P2: 三千',q['boundary']['state'])
        self.assertIn('[回复原文] P1: 手机预算',q['boundary']['state'])
        self.assertNotIn('(回复: e0)',q['boundary']['state'])
        self.assertTrue(q['boundary']['state'].endswith('[当前消息] P2: 三千'))
    def test_unseen_reply_is_preserved_without_invented_quote(self):
        p=fixtures.FrozenTests().payload();p['target']['reply_to_message_id']='missing'
        q=make_questions(p)
        self.assertIn('回复目标原文未呈现',q['boundary']['state'])
        self.assertNotIn('missing',q['boundary']['state'])
