"""Independent software gate; synthetic fixtures, not memory usefulness evidence."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import numpy as np

from research_memory.associative_recall import compare_associative
from research_memory.context_recall import (
    CONTEXT_PLAN_PROMPT, compare_context, context_plan, normalize_state, state_text,
)
from research_memory.contracts import Invalid, PLAN_SCHEMA
from tests.reader_fixture import load_demo
from research_memory.index import SemanticIndex
from research_memory.store import Store, digest
from tests.test_associative import FixtureVectors, PLAN


def current_state():
    return {'messages': [
        {'id': 'now1', 'speaker': 'actor_01', 'time': '2026-10-02T10:00:00+08:00',
         'text': '  我这个夜猫子笑话又来了：今天聊白鹭计划。\n不是问题。  ', 'replyTo': None},
        {'id': 'now2', 'speaker': 'actor_02', 'time': '2026-10-02T02:01:00Z',
         'text': '@actor_010 引用“海风”：今晚继续聊。', 'replyTo': 'now1'},
    ], 'focusSpeakerId': 'actor_01'}


class NativeStateTests(unittest.TestCase):
    def test_literal_nonquestion_and_actor_are_preserved_without_hidden_ask(self):
        original = current_state()
        state = normalize_state(original)
        self.assertEqual(state, original)
        self.assertIsNot(state['messages'][0], original['messages'][0])
        plan, meta = context_plan(state)
        self.assertEqual(plan['cues'], [
            {'text': 'actor_01', 'weight': .35},
            {'text': original['messages'][-1]['text'], 'weight': .65}])
        self.assertAlmostEqual(sum(c['weight'] for c in plan['cues']), 1)
        self.assertEqual(meta['modelCalls'], 0)
        self.assertIn('no learned', meta['source'])
        self.assertIn('今晚继续聊', state_text(state))
        self.assertNotIn('以前说过什么', state_text(state))
        self.assertNotIn('偏好', json.dumps(plan, ensure_ascii=False))
        single = {'messages': [original['messages'][0]], 'focusSpeakerId': 'actor_01'}
        self.assertEqual(context_plan(normalize_state(single))[0]['cues'][1]['text'],
                         original['messages'][0]['text'])

    def test_invalid_state_fields_ids_times_order_focus_and_budget(self):
        cases = [None, [], {}, {**current_state(), 'query': 'hidden'}]
        for field, value in [('messages', []), ('messages', current_state()['messages'] * 5),
                             ('focusSpeakerId', 'actor_010'), ('focusSpeakerId', '海风'),
                             ('focusSpeakerId', True)]:
            cases.append({**current_state(), field: value})
        for field, value in [('id', ''), ('id', True), ('speaker', None), ('text', 1),
                             ('replyTo', False), ('time', 'yesterday'),
                             ('time', '2026-10-02T10:00:00'),
                             ('time', '2026-99-02T10:00:00Z')]:
            state = current_state(); state['messages'][0][field] = value; cases.append(state)
        state = current_state(); state['messages'][1]['id'] = 'now1'; cases.append(state)
        state = current_state(); state['messages'].reverse(); cases.append(state)
        state = current_state(); state['messages'][0]['targetIds'] = ['gold']; cases.append(state)
        state = current_state(); del state['messages'][0]['replyTo']; cases.append(state)
        state = current_state()
        for row in state['messages']: row['text'] = '长' * 1100
        cases.append(state)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(Invalid):
                normalize_state(value)

    def test_one_to_eight_messages_and_zoned_absolute_order(self):
        state = current_state()
        state['messages'] = [{**state['messages'][0], 'id': str(i)} for i in range(8)]
        self.assertEqual(len(normalize_state(state)['messages']), 8)
        self.assertEqual(normalize_state(current_state()), current_state())

    def test_planner_sees_only_state_and_authoritative_hashes_ignore_metrics(self):
        state = normalize_state(current_state()); before = copy.deepcopy(state)
        fake = {'source': 'forged', 'modelCalls': 999, 'inputHash': 'forged',
                'schemaHash': 'forged', 'promptHash': 'forged'}
        planner = Mock()
        planner.generate.return_value = (copy.deepcopy(PLAN), fake)
        plan, meta = context_plan(state, planner=planner)
        prompt, payload, schema = planner.generate.call_args.args
        self.assertEqual(prompt, CONTEXT_PLAN_PROMPT)
        self.assertEqual(payload, {'currentState': before})
        self.assertEqual(schema, PLAN_SCHEMA)
        self.assertIsNot(payload['currentState'], state)
        self.assertIsNot(schema, PLAN_SCHEMA)
        self.assertEqual(state, before)
        self.assertEqual(meta['inputHash'], digest({'currentState': state}))
        self.assertEqual(meta['schemaHash'], digest(PLAN_SCHEMA))
        self.assertEqual(meta['promptHash'], digest(CONTEXT_PLAN_PROMPT))
        self.assertEqual(meta['modelCalls'], 1)
        self.assertEqual(meta['source'], 'model-current-state-only')
        self.assertEqual(meta['modelMetrics'], fake)
        plan['cues'][0]['text'] = 'changed'
        self.assertEqual(planner.generate.return_value[0], PLAN)

    def test_planner_payload_and_schema_mutations_rejected(self):
        state = normalize_state(current_state())
        for target in ('payload', 'schema'):
            def generate(prompt, payload, schema):
                if target == 'payload': payload['currentState']['messages'][0]['text'] = 'tampered'
                else: schema['additionalProperties'] = True
                return copy.deepcopy(PLAN), {}
            with self.subTest(target=target), self.assertRaises(Invalid):
                context_plan(state, planner=Mock(generate=generate))
        self.assertEqual(state, current_state())
        with self.assertRaises(Invalid):
            context_plan(state, supplied=PLAN, planner=Mock())

    def test_plan_contract_length_finite_types_and_positive_totals(self):
        state = normalize_state(current_state())
        for count in (1, 2, 3):
            plan = {**copy.deepcopy(PLAN), 'cues': [{'text': '当前话题', 'weight': 1/count}] * count}
            accepted, _ = context_plan(state, supplied=plan)
            self.assertAlmostEqual(sum(c['weight'] for c in accepted['cues']), 1)
        bad = []
        for count in (0, 4):
            bad.append({**copy.deepcopy(PLAN), 'cues': [{'text': '当前话题', 'weight': .25}] * count})
        for weight in (True, '1', None, float('nan'), float('inf'), -1, 2, 0):
            plan = copy.deepcopy(PLAN); plan['cues'][0]['weight'] = weight; bad.append(plan)
        for weight in (True, float('nan'), float('inf'), -1):
            plan = copy.deepcopy(PLAN); plan['relations']['CAUSAL'] = weight; bad.append(plan)
        plan = copy.deepcopy(PLAN); plan['relations'] = dict.fromkeys(plan['relations'], 0); bad.append(plan)
        for plan in bad:
            with self.subTest(plan=plan), self.assertRaises(Invalid):
                context_plan(state, supplied=plan)

    def test_cue_budget_is_validated_not_silently_normalized(self):
        state = normalize_state(current_state())
        for total in (.5, 1.000002, .999998):
            plan = {**copy.deepcopy(PLAN), 'cues': [
                {'text': '当前参与者', 'weight': total / 2},
                {'text': '当前话题', 'weight': total / 2}]}
            for model_generated in (False, True):
                with self.subTest(total=total, model_generated=model_generated), self.assertRaises(Invalid):
                    if model_generated:
                        planner = Mock(); planner.generate.return_value = (plan, {})
                        context_plan(state, planner=planner)
                    else:
                        context_plan(state, supplied=plan)
        for total in (1., .9999995, 1.0000005):
            plan = {**copy.deepcopy(PLAN), 'cues': [
                {'text': '当前参与者', 'weight': total / 2},
                {'text': '当前话题', 'weight': total / 2}]}
            accepted, _ = context_plan(state, supplied=plan)
            self.assertEqual(accepted, plan)


class ContextStorageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:'); self.addCleanup(self.store.close)
        self.model = FixtureVectors()
        load_demo(self.store, 'a')
        SemanticIndex(self.store, self.model).sync('a')
        self.payload = {'scope': 'a', 'currentState': current_state(), 'seedMinimum': 0}

    def recalls(self):
        return list(self.store.db.execute('SELECT * FROM recalls'))

    def test_one_persisted_recall_has_current_state_metadata_and_detached_input(self):
        before = copy.deepcopy(self.payload)
        with patch('research_memory.context_recall.compare_associative', wraps=compare_associative) as compare:
            result = compare_context(self.store, self.payload, self.model)
        self.assertIs(compare.call_args.kwargs['persist'], False)
        self.assertEqual(len(self.recalls()), 1)
        saved = json.loads(self.recalls()[0]['result'])
        self.assertEqual(saved['currentState'], before['currentState'])
        self.assertEqual(saved['triggerMode'], 'current-state')
        self.assertEqual(result['parameters']['acceptancePolicy'], 'rank-only')
        self.assertEqual(saved['workingContext'], {arm:[] for arm in result['arms']})
        self.assertFalse(saved['automaticInjectionAuthorized'])
        self.assertEqual(saved['workingContextStatus'],'PENDING_SIGNIFICANCE')
        self.assertEqual(self.payload, before)
        self.payload['currentState']['messages'][0]['text'] = 'caller mutation'
        self.assertEqual(result['currentState'], before['currentState'])

    def test_unknown_controls_and_hidden_gold_manual_seeds_are_rejected(self):
        for key in ('query', 'gold', 'seeds', 'targetIds', 'history', 'episode', 'unknown'):
            with self.subTest(key=key), self.assertRaises(Invalid):
                compare_context(self.store, {**self.payload, key: []}, self.model)
        self.assertEqual(self.recalls(), [])

    def test_empty_candidates_need_no_current_usefulness_claim(self):
        with patch('research_memory.context_recall.compare_associative',return_value={
                'arms':{'attention_diffusion':{'memories':[]}}}):
            result=compare_context(self.store,self.payload,self.model)
        self.assertEqual(result['workingContextStatus'],'EMPTY_NO_CANDIDATES')
        self.assertEqual(result['workingContext'],{'attention_diffusion':[]})
        self.assertFalse(result['automaticInjectionAuthorized'])

    def test_all_raw_scope_past_gate_precedes_graph_planner_and_model(self):
        # A private/open episode is deliberately not eligible for raw retrieval,
        # but still must fail the all-scope gate before any historical read.
        self.store.create_episode('a', 'private', 'private')
        for stamp in ('2026-10-02T02:00:00Z', '2026-10-02T02:00:30Z', '2027-01-01T00:00:00Z'):
            self.store.ingest('a', 'private', [{'id': 'future' + stamp, 'speaker': 'x',
                'time': stamp, 'text': 'not eligible', 'replyTo': None}])
            planner = Mock(); before = dict(self.model.counts)
            with patch.object(self.store, 'graph') as graph, \
                 patch('research_memory.context_recall.compare_associative') as comparison:
                with self.subTest(stamp=stamp), self.assertRaises(Invalid):
                    compare_context(self.store, self.payload, self.model, planner=planner)
                graph.assert_not_called(); comparison.assert_not_called()
            planner.generate.assert_not_called()
            self.assertEqual(dict(self.model.counts), before)
        self.assertEqual(self.recalls(), [])

    def test_old_associative_default_threshold_and_persistence_compatibility(self):
        payload = {'scope': 'a', 'query': '白鹭计划', 'plan': copy.deepcopy(PLAN),
                   'arms': ['formed_multiquery']}
        default = compare_associative(self.store, payload, self.model)
        explicit = compare_associative(self.store, {**payload, 'acceptancePolicy': 'threshold'},
                                       self.model, persist=False)
        self.assertEqual(default['parameters']['acceptancePolicy'], 'threshold')
        self.assertIn('recallId', default); self.assertNotIn('recallId', explicit)
        self.assertEqual(len(self.recalls()), 1)
        for field in ('checked', 'memories', 'trace', 'characters'):
            self.assertEqual(default['arms']['formed_multiquery'][field],
                             explicit['arms']['formed_multiquery'][field])

    def test_native_requested_arms_are_only_nonempty_unique_memory_arms(self):
        valid = ['formed_multiquery', 'graph_expansion', 'attention_diffusion']
        for arms in ([name] for name in valid):
            result = compare_context(self.store, {**self.payload, 'arms': arms}, self.model)
            self.assertEqual(list(result['arms']), arms)
        baseline = len(self.recalls())
        for arms in (None, [], (), 'formed_multiquery', ['raw_retrieval'],
                     ['formed_retrieval'], ['raw_window_retrieval'], [True], [[]],
                     ['formed_multiquery', 'formed_multiquery']):
            with self.subTest(arms=arms), self.assertRaises(Invalid):
                compare_context(self.store, {**self.payload, 'arms': arms}, self.model)
        self.assertEqual(len(self.recalls()), baseline)

    def test_query_truncation_flags_require_plain_python_bool(self):
        original = self.model.vectors
        for flag in (0, 1, None, 'false', float('nan'), np.bool_(False)):
            def vectors(texts, query=False):
                matrix, flags = original(texts, query=query)
                return matrix, [flag] * len(texts) if query else flags
            with patch.object(self.model, 'vectors', side_effect=vectors):
                with self.subTest(flag=flag), self.assertRaises(Invalid):
                    compare_context(self.store, self.payload, self.model)
            self.assertEqual(self.recalls(), [])

    def test_cached_invalid_scores_flags_and_malformed_entries_fail_closed(self):
        payload = {'scope': 'a', 'query': '白鹭计划', 'plan': copy.deepcopy(PLAN),
                   'arms': ['formed_multiquery'], 'acceptancePolicy': 'rank-only'}
        cache = {}
        result = compare_associative(self.store, payload, self.model, check_cache=cache, persist=False)
        self.assertTrue(result['arms']['formed_multiquery']['checked'])
        self.assertTrue(cache)
        for entry in ((float('nan'), False), (float('inf'), False), (True, False),
                      ('1', False), (1., float('nan')), (1., 0), (1., np.bool_(False))):
            poisoned = dict.fromkeys(cache, entry)
            with self.subTest(entry=entry), self.assertRaises(Invalid):
                compare_associative(self.store, payload, self.model, check_cache=poisoned)
            self.assertEqual(self.recalls(), [])
        # Malformed cache entries must fail closed; no stronger error-class
        # contract is assumed for invalid internal cache tuple structure.
        for entry in ((), (1.,), (1., False, 'extra'), None):
            poisoned = dict.fromkeys(cache, entry)
            with self.subTest(entry=entry), self.assertRaises((Invalid, ValueError, TypeError)):
                compare_associative(self.store, payload, self.model, check_cache=poisoned)
            self.assertEqual(self.recalls(), [])
        warm = compare_associative(self.store, payload, self.model, check_cache=cache, persist=False)
        self.assertEqual(warm['arms']['formed_multiquery']['diagnostics']['physicalChecks'], 0)

    def test_finite_negative_scores_respect_both_acceptance_policies(self):
        payload = {'scope': 'a', 'query': '白鹭计划', 'plan': copy.deepcopy(PLAN),
                   'arms': ['formed_multiquery'], 'minScore': 0}
        with patch.object(self.model, 'rerank', side_effect=lambda q, texts: ([-2.] * len(texts), [False] * len(texts))):
            for policy in ('threshold', 'rank-only'):
                result = compare_associative(self.store, {**payload, 'acceptancePolicy': policy}, self.model, persist=False)
                arm = result['arms']['formed_multiquery']
                self.assertTrue(arm['checked'])
                self.assertTrue(all(c['accepted'] == (policy == 'rank-only') for c in arm['checked']))
                self.assertEqual(bool(arm['memories']), policy == 'rank-only')
        self.assertEqual(self.recalls(), [])

    def test_bad_reranker_counts_scores_and_flags_reject_without_false_output(self):
        payload = {'scope': 'a', 'query': '白鹭计划', 'plan': copy.deepcopy(PLAN),
                   'arms': ['formed_multiquery'], 'acceptancePolicy': 'rank-only'}
        cases = [lambda n: ([], [False] * n), lambda n: ([1.] * n, []),
                 *[lambda n, v=v: ([v] * n, [False] * n)
                   for v in (float('nan'), float('inf'), True, '1')],
                 *[lambda n, v=v: ([1.] * n, [v] * n)
                   for v in (float('nan'), 0, 1, None, 'false', np.bool_(False))]]
        for bad in cases:
            with patch.object(self.model, 'rerank', side_effect=lambda q, texts: bad(len(texts))):
                with self.subTest(output=bad(1)), self.assertRaises(Invalid):
                    compare_associative(self.store, payload, self.model)
            self.assertEqual(self.recalls(), [])


if __name__ == '__main__':
    unittest.main()
