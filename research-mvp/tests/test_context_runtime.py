"""Software-only runtime gate: synthetic vectors, no provider or quality claim."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from research_memory import context_significance as significance
from research_memory.context_recall import compare_context, context_plan
from research_memory.contracts import Invalid, PLAN_SCHEMA
from tests.reader_fixture import load_demo
from research_memory.index import SemanticIndex
from research_memory.store import Store, digest
from tests.test_associative import FixtureVectors, PLAN
from tests.test_context_recall import current_state


def decision(candidate, **changes):
    return {'candidateId': candidate['id'], 'utility': 'USEFUL_CONTEXT',
            'claimSupport': 'SUPPORTED', 'currentAnchorIds': ['now1'],
            'mentionPolicy': 'INTERNAL_ONLY', 'rationale': 'synthetic gate', **changes}


def output(payload):
    return {'judgments': [decision(row) for row in payload['candidates']]}


def without_elapsed(value):
    """Compare discovery artifacts, excluding nondeterministic elapsed clocks only."""
    if isinstance(value, dict):
        return {k: without_elapsed(v) for k, v in value.items() if k != 'seconds'}
    if isinstance(value, list):
        return [without_elapsed(v) for v in value]
    return value


class RuntimeGateTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.model = FixtureVectors()
        load_demo(self.store, 'a')
        SemanticIndex(self.store, self.model).sync('a')
        self.payload = {'scope': 'a', 'currentState': current_state(), 'seedMinimum': 0}
        self.sources = [dict(row) for row in self.store.db.execute(
            'SELECT id,speaker,time,text,reply_to,episode FROM events WHERE scope=? ORDER BY seq', ('a',))]

    def recalls(self):
        return list(self.store.db.execute('SELECT * FROM recalls'))

    def candidates(self):
        return [{'id': 'candidate-' + str(i), 'label': 'synthetic ' + str(i),
                 'sourceEventIds': [row['id']]} for i, row in enumerate(self.sources[:3])]

    def native_result(self):
        return {'arms': {arm: {'memories': [
            {'id': c['id'], 'label': c['label'], 'evidenceIds': c['sourceEventIds'],
             'score': .5, 'trace': 'not provider input'}], 'trace': [arm]}
            for arm, c in zip(('formed_multiquery', 'graph_expansion', 'attention_diffusion'),
                              self.candidates())}}

    def test_actual_native_discovery_is_unchanged_with_opt_in_judgment(self):
        before = copy.deepcopy(self.payload)
        baseline = compare_context(self.store, self.payload, self.model)
        provider = Mock(generate=lambda p, data, s: (output(data), {'tokens': 7}))
        judged = compare_context(self.store, self.payload, self.model, judge_provider=provider)
        self.assertEqual(without_elapsed(baseline['arms']), without_elapsed(judged['arms']))
        self.assertEqual(baseline['plan'], judged['plan'])
        self.assertEqual(baseline['workingContextStatus'], 'PENDING_SIGNIFICANCE')
        self.assertEqual(baseline['workingContext'], {a: [] for a in baseline['arms']})
        self.assertNotIn('significance', baseline)
        self.assertEqual(judged['workingContextStatus'], 'JUDGED_INTERNAL_CONTEXT')
        self.assertFalse(judged['automaticInjectionAuthorized'])
        self.assertEqual(self.payload, before)
        self.assertEqual(len(self.recalls()), 2)

    def test_each_arm_has_only_its_actual_candidates_and_whole_referenced_sources(self):
        calls = []
        def generate(prompt, data, schema):
            self.assertEqual(self.recalls(), [])
            calls.append(copy.deepcopy((prompt, data, schema)))
            return output(data), {}
        native = self.native_result()
        with patch('research_memory.context_recall.compare_associative', return_value=native), \
             patch('research_memory.context_significance.judge', wraps=significance.judge) as adapter:
            result = compare_context(self.store, self.payload, self.model,
                                     judge_provider=Mock(generate=generate))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.recalls()), 1)
        saved = json.loads(self.recalls()[0]['result'])
        self.assertEqual(saved['workingContext'], result['workingContext'])
        for (arm, value), call, invocation in zip(native['arms'].items(), calls, adapter.call_args_list):
            prompt, data, schema = call
            candidates = [{'id': h['id'], 'label': h['label'], 'sourceEventIds': h['evidenceIds']}
                          for h in value['memories']]
            self.assertEqual(prompt.encode('utf-8'), significance.PROMPT.encode('utf-8'))
            self.assertEqual(set(data), {'currentState', 'candidates', 'sources'})
            self.assertEqual(data['currentState'], current_state())
            self.assertEqual(data['candidates'], candidates)
            self.assertEqual(invocation.args[2], self.sources)
            refs = {ref for c in candidates for ref in c['sourceEventIds']}
            self.assertEqual(data['sources'], sorted(
                [s for s in self.sources if s['id'] in refs], key=lambda s: s['id']))
            self.assertEqual(schema, significance.make_request(current_state(), candidates, self.sources)['schema'])
            self.assertEqual(result['workingContext'][arm], [{**c, 'mentionPolicy': 'INTERNAL_ONLY'} for c in candidates])
            self.assertFalse(result['significance'][arm]['judgments'][0]['externalDisclosureAuthorized'])

    def test_empty_actual_candidates_never_call_provider_even_with_other_arm_nonempty(self):
        for nonempty in (False, True):
            native = self.native_result()
            for i, value in enumerate(native['arms'].values()):
                if not nonempty or i != 1:
                    value['memories'] = []
            provider = Mock()
            provider.generate.side_effect = lambda p, data, s: (output(data), {})
            with patch('research_memory.context_recall.compare_associative', return_value=native):
                result = compare_context(self.store, self.payload, self.model, judge_provider=provider)
            self.assertEqual(provider.generate.call_count, int(nonempty))
            for arm, value in native['arms'].items():
                self.assertEqual(result['significance'][arm]['modelCalls'], int(bool(value['memories'])))
                if not value['memories']:
                    self.assertEqual(result['workingContext'][arm], [])
                    self.assertIsNone(result['significance'][arm]['modelMetrics'])

    def test_explicit_plan_and_native_cues_pass_unchanged_to_discovery(self):
        for supplied in (None, PLAN):
            payload = copy.deepcopy(self.payload)
            if supplied is not None:
                payload['plan'] = copy.deepcopy(supplied)
            before = copy.deepcopy(payload)
            with patch('research_memory.context_recall.compare_associative',
                       return_value={'arms': {'formed_multiquery': {'memories': []}}}) as reader:
                compare_context(self.store, payload, self.model, judge_provider=Mock())
            args = reader.call_args.args[1]
            expected, _ = context_plan(current_state(), supplied=supplied)
            self.assertEqual(args['plan'], expected)
            self.assertEqual(args['acceptancePolicy'], 'rank-only')
            self.assertIs(reader.call_args.kwargs['persist'], False)
            self.assertEqual(payload, before)

    def test_one_failed_arm_saves_nothing_and_stops_later_judgments(self):
        for failure in ('raise', 'missing', 'unknown-anchor'):
            calls = []
            def generate(prompt, data, schema):
                calls.append(data)
                self.assertEqual(self.recalls(), [])
                if len(calls) == 2:
                    if failure == 'raise':
                        raise RuntimeError('provider unavailable')
                    if failure == 'missing':
                        return {'judgments': []}, {}
                    return {'judgments': [decision(data['candidates'][0], currentAnchorIds=['future'])]}, {}
                return output(data), {}
            with patch('research_memory.context_recall.compare_associative', return_value=self.native_result()), \
                 patch.object(self.store, 'save_recall', wraps=self.store.save_recall) as save:
                with self.subTest(failure=failure), self.assertRaises((Invalid, RuntimeError)):
                    compare_context(self.store, self.payload, self.model, judge_provider=Mock(generate=generate))
                save.assert_not_called()
            self.assertEqual(len(calls), 2)
            self.assertEqual(self.recalls(), [])

    def test_semantic_writes_during_planning_reading_or_judgment_reject_before_save(self):
        for stage in ('planner', 'reranker', 'judge'):
            def write():
                self.store.create_episode('a', 'write-' + stage, 'synthetic concurrent write')
                self.store.ingest('a', 'write-' + stage, [{'id': 'write-' + stage, 'speaker': 'actor_01',
                    'time': '2027-01-01T00:00:00Z', 'text': 'future contamination', 'replyTo': None}])
            original_rerank = self.model.rerank
            def rerank(query, texts):
                write()
                return original_rerank(query, texts)
            def plan(prompt, data, schema):
                write()
                return copy.deepcopy(PLAN), {}
            def judge(prompt, data, schema):
                write()
                return output(data), {}
            planner = Mock(generate=plan) if stage == 'planner' else None
            provider = Mock()
            provider.generate.side_effect = judge if stage == 'judge' else lambda p, d, s: (output(d), {})
            # Each stage starts with a new independent past-only fixture.
            if stage != 'planner':
                self.store.close()
                self.store = Store(':memory:')
                self.addCleanup(self.store.close)
                load_demo(self.store, 'a')
                SemanticIndex(self.store, self.model).sync('a')
            with patch.object(self.model, 'rerank', side_effect=rerank if stage == 'reranker' else original_rerank), \
                 patch.object(self.store, 'save_recall', wraps=self.store.save_recall) as save:
                with self.subTest(stage=stage), self.assertRaisesRegex(Invalid, 'scope改变'):
                    compare_context(self.store, self.payload, self.model, planner=planner, judge_provider=provider)
                save.assert_not_called()
            self.assertEqual(self.recalls(), [])
            if stage in ('planner', 'reranker'):
                provider.generate.assert_not_called()

    def test_future_in_unreferenced_private_episode_blocks_all_providers_and_discovery(self):
        self.store.create_episode('a', 'private-future', 'private-future')
        self.store.ingest('a', 'private-future', [{'id': 'future', 'speaker': 'x',
            'time': current_state()['messages'][0]['time'], 'text': 'not a candidate', 'replyTo': None}])
        planner = Mock(); provider = Mock()
        with patch('research_memory.context_recall.compare_associative') as reader:
            with self.assertRaises(Invalid):
                compare_context(self.store, self.payload, self.model, planner=planner, judge_provider=provider)
            reader.assert_not_called()
        planner.generate.assert_not_called(); provider.generate.assert_not_called()
        self.assertEqual(self.recalls(), [])

    def test_metrics_are_nested_not_authoritative_and_inputs_are_detached(self):
        candidates = self.candidates()
        before = copy.deepcopy((self.payload['currentState'], candidates, self.sources, PLAN_SCHEMA))
        forged = {'modelCalls': 999, 'inputHash': 'forged', 'promptHash': 'forged', 'schemaHash': 'forged',
                  'workingContext': ['forged'], 'externalDisclosureAuthorized': True, 'seconds': -1}
        provider = Mock(generate=lambda p, d, s: (output(d), forged))
        result = significance.judge(self.payload['currentState'], candidates, self.sources, provider)
        request = significance.make_request(self.payload['currentState'], candidates, self.sources)
        self.assertEqual(result['modelCalls'], 1)
        for key in ('inputHash', 'promptHash', 'schemaHash'):
            self.assertEqual(result[key], request[key])
        self.assertGreaterEqual(result['seconds'], 0)
        self.assertEqual(result['modelMetrics'], forged)
        self.assertEqual(result['workingContext'], candidates)
        self.assertEqual((self.payload['currentState'], candidates, self.sources, PLAN_SCHEMA), before)
        forged['workingContext'].append('mutation')
        self.assertEqual(result['modelMetrics']['workingContext'], ['forged'])
        for target in ('payload', 'schema'):
            def mutate(prompt, data, schema):
                response = output(data)
                if target == 'payload': data['sources'][0]['text'] = 'tampered'
                else: schema['additionalProperties'] = True
                return response, {}
            with self.subTest(target=target), self.assertRaises(Invalid):
                significance.judge(self.payload['currentState'], candidates, self.sources, Mock(generate=mutate))
        self.assertEqual((self.payload['currentState'], candidates, self.sources, PLAN_SCHEMA), before)

if __name__ == '__main__':
    unittest.main()
