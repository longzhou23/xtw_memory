"""Synthetic opt-in reader regressions; no corpus, provider, or quality claims."""
import collections
import copy
import hashlib
import math
import unittest
from unittest.mock import patch

import numpy as np

from research_memory import dynamics
from research_memory.associative_recall import (
    ARMS, QueryAdjacency, compare_associative, evidence_views, fused_order,
    options, raw_views, window_matrix, gate_affinity, select_evidence, speaker_grounding,
)
from research_memory.contracts import Invalid
from tests.reader_fixture import event, load_demo
from research_memory.index import SemanticIndex
from research_memory.recall import compare
from research_memory.store import Store


class FixtureVectors:
    name = "associative deterministic fixture (NOT semantic quality)"
    fingerprint = "associative-fixture-v1"
    min_score = -30
    np = np

    def __init__(self):
        self.counts = collections.Counter()
        self.checked_bodies = []

    def vectors(self, texts, query=False):
        self.counts["embedding"] += len(texts)
        rows = [np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8)
                .astype(np.float32) - 127 for t in texts]
        matrix = np.asarray(rows, dtype=np.float32).reshape((-1, 32))
        if len(rows):
            matrix /= np.linalg.norm(matrix, axis=1)[:, None]
        return matrix, [False] * len(texts)

    def similarity(self, query, texts):
        q, _ = self.vectors([query], query=True)
        matrix, flags = self.vectors(texts)
        return list(map(float, matrix @ q[0])), flags

    def rerank(self, query, texts):
        self.checked_bodies.extend(texts)
        self.counts["reranker"] += len(texts)
        return [1.] * len(texts), [False] * len(texts)


PLAN = {"cues": [{"text": "白鹭计划", "weight": 1}],
        "relations": {"CAUSAL": .3, "SIMILARITY": .4, "OPPOSITION": .3},
        "direction": "both"}


class AssociativeOptionsTests(unittest.TestCase):
    def test_defaults_and_all_range_endpoints(self):
        self.assertEqual(options({}), {"seedCount": 3, "gatePower": 2.,
                                     "viewCharacters": 512, "windowRadius": 2, "includeQuerySeed": False,
                                     "normalizeCueSeeds": False, "querySeedWeight": .5, "gateAffinity": "query",
                                     "returnDiversity": 0., "groundBySpeaker": False})
        for supplied in ({"seedCount": 1, "gatePower": 0, "viewCharacters": 100, "windowRadius": 0},
                         {"seedCount": 3, "gatePower": 8, "viewCharacters": 1024, "windowRadius": 4}):
            self.assertEqual(options(supplied), {**supplied, "includeQuerySeed": False,
                                                "normalizeCueSeeds": False, "querySeedWeight": .5, "gateAffinity": "query",
                                                "returnDiversity": 0., "groundBySpeaker": False})

    def test_bad_options_are_rejected(self):
        values = [None, [], {"unknown": 1}]
        for name, invalid in {
            "seedCount": [0, 4, True, 1.5], "gatePower": [-1, 9, True, float("nan"), float("inf")],
            "viewCharacters": [99, 1025, True, 100.5], "windowRadius": [-1, 5, True, .5],
            "includeQuerySeed": [0, 1, "true", None],
            "normalizeCueSeeds": [0, 1, "true", None],
            "querySeedWeight": [-.1, 1.1, True, float('nan')],
            "gateAffinity": [None, True, 'unknown', [], {}],
            "returnDiversity": [-.1, 1.1, True, float('inf')],
            "groundBySpeaker": [0, 1, None, 'true'],
        }.items():
            values.extend({name: value} for value in invalid)
        for value in values:
            with self.subTest(value=value), self.assertRaises(Invalid):
                options(value)

    def test_weighted_reciprocal_rank_fusion(self):
        scores = fused_order([["a", "b"], ["b", "c"], ["c"]], [.5, .25, 0])
        self.assertAlmostEqual(scores["a"], .5 / 61)
        self.assertAlmostEqual(scores["b"], .5 / 62 + .25 / 61)
        self.assertAlmostEqual(scores["c"], .25 / 62)
        self.assertEqual(fused_order([], []), {})
        self.assertGreater(scores["b"], scores["a"])


class AssociativeTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.model = FixtureVectors()
        self.fixture = load_demo(self.store, "a")
        SemanticIndex(self.store, self.model).sync("a")
        self.payload = {"scope": "a", "query": "白鹭计划", "plan": copy.deepcopy(PLAN),
                        "seedMinimum": .35}

    def run_compare(self, **updates):
        return compare_associative(self.store, {**self.payload, **updates}, self.model)

    def test_speaker_grounding_uses_attribution_not_alias_or_id_substrings(self):
        events = {'e1': {'speaker': 'p_01'}, 'e2': {'speaker': 'p_010'}}
        nodes = {'person': {'type': 'PERSON', 'label': 'p_01', 'evidence': []},
                 'quoted': {'type': 'MEMORY', 'label': 'p_01提到p_010', 'subject': 'person', 'evidence': [{'eventId': 'e1'}]},
                 'other': {'type': 'MEMORY', 'label': 'p_010', 'evidence': [{'eventId': 'e2'}]},
                 'alias': {'type': 'ALIAS', 'label': '夜风', 'evidence': [{'eventId': 'e1'}]}}
        actors, members = speaker_grounding(nodes, events, [('p_01的建议', 1), ('p_010做了什么', 1), ('夜风是谁', 1)],
                                            {'w1': {'evidenceIds': ['e1', 'e2']}})
        self.assertEqual(actors, [{'p_01'}, {'p_010'}, set()])
        self.assertEqual(members['node']['quoted'], {'p_01'})
        self.assertEqual(members['node']['other'], {'p_010'})
        self.assertEqual(members['window']['w1'], {'p_01', 'p_010'})

    def test_speaker_grounding_filters_direct_raw_checks_and_is_traced(self):
        result = self.run_compare(query='林宁说了什么', associative={'groundBySpeaker': True})
        by_id = {r['id']: r for r in self.store.db.execute("SELECT * FROM events WHERE scope='a'")}
        for checked in result['arms']['raw_retrieval']['checked']:
            self.assertEqual(by_id[checked['id'].removeprefix('event:')]['speaker'], '林宁')
        self.assertEqual(result['speakerGrounding'][0]['explicitSpeakers'], ['林宁'])

    def test_diverse_returns_do_not_rescue_rejected_or_exceed_budget(self):
        checked = [{'id': k, 'rerankScore': score, 'accepted': accepted} for k, score, accepted in
                   [('a', 4., True), ('b', 3.9, True), ('c', 2., True), ('d', 8., False)]]
        views = {k: {'label': k*50} for k in 'abcd'}
        vectors = {k: np.array(v, dtype=float) for k, v in
                   [('a', [1, 0]), ('b', [1, 0]), ('c', [0, 1]), ('d', [-1, 0])]}
        plain, size, _ = select_evidence(checked, views, vectors, 2, 100, 0, {})
        diverse, diverse_size, trace = select_evidence(checked, views, vectors, 2, 100, .35, {})
        self.assertEqual([x['id'] for x in plain], ['a', 'b'])
        self.assertEqual([x['id'] for x in diverse], ['a', 'c'])
        self.assertEqual((size, diverse_size, len(trace)), (100, 100, 2))
        self.assertEqual(len(checked), 4)
        views['a']['label'] *= 3
        fitting, size, _ = select_evidence(checked, views, vectors, 2, 100, 0, {})
        self.assertEqual([x['id'] for x in fitting], ['b', 'c'])
        self.assertEqual(size, 100)

    def test_cue_gate_retains_weak_whole_query_aspect_without_using_disabled_cue(self):
        scores = [{'detail': .1, 'theme': .7}, {'detail': .8, 'theme': .2}, {'detail': 1., 'theme': 1.}]
        requests = [('full', .5), ('aspect', .5), ('disabled', 0)]
        self.assertEqual(gate_affinity(scores, requests, 'query'), scores[0])
        self.assertEqual(gate_affinity(scores, requests, 'maxCue'), {'detail': .8, 'theme': .7})
        old = self.run_compare(associative={'gatePower': 0})
        new = self.run_compare(associative={'gatePower': 0, 'gateAffinity': 'maxCue'})
        self.assertEqual(old['arms']['attention_diffusion']['trace']['state'],
                         new['arms']['attention_diffusion']['trace']['state'])

    def test_complete_query_can_seed_detail_missing_from_paraphrased_cue(self):
        memories = [n for n in self.store.graph('a')['nodes'] if n['type'] == 'MEMORY' and n['status'] == 'CURRENT']
        cue, detail = memories[:2]
        plan = {**PLAN, 'cues': [{'text': cue['label'], 'weight': 1}]}
        payload = {'query': detail['label'], 'plan': plan,
                   'arms': ['formed_multiquery', 'attention_diffusion'],
                   'diffusion': {'maxOutflow': 0, 'gamma': 1, 'anchor': 0, 'steps': 1}}
        old = self.run_compare(**payload, associative={'seedCount': 1, 'gatePower': 0})
        new = self.run_compare(**payload, associative={'seedCount': 1, 'gatePower': 0, 'includeQuerySeed': True})
        self.assertEqual(old['seeds'], {cue['id']: 1})
        self.assertEqual(new['seeds'], {cue['id']: .5, detail['id']: .5})
        self.assertEqual(len(new['grounding']), 2)
        self.assertEqual(new['grounding'][0]['cue'], {'text': detail['label'], 'weight': .5})
        quarter = self.run_compare(**payload, associative={'seedCount': 1, 'gatePower': 0,
            'includeQuerySeed': True, 'querySeedWeight': .25})
        self.assertEqual(quarter['seeds'], {cue['id']: .75, detail['id']: .25})
        self.assertEqual([m['id'] for m in old['arms']['formed_multiquery']['memories']],
                         [m['id'] for m in new['arms']['formed_multiquery']['memories']])

    def test_each_cue_keeps_its_share_despite_different_absolute_cosines(self):
        plan = {**PLAN, 'cues': [{'text': '拆分线索乙', 'weight': 1}]}
        common = {'query': '完整问题甲', 'plan': plan, 'seedMinimum': 0,
                  'arms': ['attention_diffusion']}
        original = self.run_compare(**common, associative={'seedCount': 1, 'includeQuerySeed': True})
        balanced = self.run_compare(**common, associative={'seedCount': 1, 'includeQuerySeed': True,
                                                          'normalizeCueSeeds': True})
        self.assertEqual(len(balanced['seeds']), 2)
        self.assertEqual(sorted(balanced['seeds'].values()), [.5, .5])
        self.assertNotEqual(sorted(original['seeds'].values()), [.5, .5])

    def test_raw_windows_anchor_reply_context_dedup_and_clipping(self):
        rows = [{"id": str(i), "seq": i, "speaker": "speaker", "time": "time",
                 "text": "body" + str(i), "reply_to": "0" if i == 3 else None}
                for i in range(5)]
        view = raw_views(rows, 1024, 1)["window:3"]
        self.assertEqual(view["evidenceIds"], ["3", "0", "2", "4"])
        self.assertTrue(view["label"].startswith("speaker time：body3"))
        clipped = raw_views(rows, 15, 1)["window:3"]
        self.assertEqual(clipped["label"], view["label"][:15])
        self.assertTrue(clipped["viewCharacterClipped"])
        raw = raw_views(rows, 1024, 0)["event:3"]
        self.assertEqual(raw["evidenceIds"], ["3"])
        self.assertEqual(raw["type"], "RAW_EVENT")
        rows[3]["reply_to"] = "invisible"
        self.assertNotIn("invisible", raw_views(rows, 1024, 1)["window:3"]["evidenceIds"])

    def test_common_source_alias_views_do_not_assert_identity_equality(self):
        graph = self.store.graph("a")
        events = {r["id"]: dict(r) for r in self.store.db.execute("SELECT * FROM events WHERE scope='a'")}
        views = evidence_views(graph, events, 1024)
        equipment = self.fixture["writes"][0]["mapping"]["equipment"]
        body = views[equipment]["label"]
        self.assertIn("别名关联线索（不自动认定身份）：海风", body)
        self.assertIn("阿澈 原话：", body)
        self.assertIn("大家叫我海风就行", body)
        self.assertEqual(views[equipment]["evidenceIds"], ["e1", "e2"])
        self.assertEqual(views[equipment]["sourceNodeId"], equipment)
        clipped = evidence_views(graph, events, 10)[equipment]
        self.assertEqual(clipped["label"], body[:10])
        self.assertTrue(clipped["viewCharacterClipped"])
        result = self.run_compare(checkBudget=200, limit=30, characterBudget=20000,
                                  associative={"viewCharacters": 1024})
        for name in ARMS[2:]:
            selected = {v["id"]: v for v in result["arms"][name]["memories"]}
            self.assertIn(equipment, selected)
            self.assertEqual(selected[equipment]["label"], body)

    def test_zero_gate_power_matches_original_dynamics_exactly(self):
        graph = self.store.graph("a")
        seed = self.fixture["writes"][0]["mapping"]["activity"]
        config = dynamics.parameters({"steps": 5})
        for operation in (dynamics.diffuse, dynamics.graph_expand):
            adjacency = QueryAdjacency(graph, PLAN, config, {}, 0)
            self.assertEqual(operation(graph, {seed: 1}, PLAN, config),
                             operation({}, {seed: 1}, PLAN, config, adjacency=adjacency))

    def test_positive_gates_retain_every_arc_and_conserve_attention(self):
        graph = self.store.graph("a")
        seed = self.fixture["writes"][0]["mapping"]["activity"]
        config = dynamics.parameters({"steps": 12, "flowFloor": 0})
        original = dynamics.arcs(graph, PLAN, config)
        for power in (1, 2, 8):
            adjacency = QueryAdjacency(graph, PLAN, config, {seed: .9}, power)
            for source, arcs in original.items():
                gated = adjacency.get(source)
                self.assertEqual(len(gated), len(arcs))
                for before, after in zip(arcs, gated):
                    self.assertEqual({k: after[k] for k in before if k != "effective"},
                                     {k: v for k, v in before.items() if k != "effective"})
                    self.assertGreater(after["effective"], 0)
                    self.assertGreaterEqual(after["contextGate"], .02)
                    self.assertLessEqual(after["contextGate"], 1)
                    self.assertEqual(after["baseEffective"], before["effective"])
                    self.assertAlmostEqual(after["effective"], before["effective"] * after["contextGate"])
            outcome = dynamics.diffuse({}, {seed: 1}, PLAN, config, adjacency=adjacency)
            previous = {seed: 1}
            for step in outcome["history"]:
                self.assertAlmostEqual(math.fsum(step["raw"].values()), 1)
                self.assertAlmostEqual(step["total"], 1)
                for source, weight in previous.items():
                    sent = math.fsum(f["amount"] for f in step["flows"] if f["source"] == source)
                    self.assertLessEqual(sent, config["maxOutflow"] * weight + 1e-12)
                previous = step["state"]

    def test_current_only_candidates_with_shared_check_limit_char_view_budgets(self):
        result = self.run_compare(checkBudget=2, limit=1, characterBudget=100,
                                  associative={"viewCharacters": 100})
        old = self.fixture["writes"][0]["mapping"]["schedule"]
        self.assertEqual(tuple(result["arms"]), ARMS)
        for name, arm in result["arms"].items():
            self.assertLessEqual(len(arm["checked"]), 2)
            self.assertLessEqual(len(arm["memories"]), 1)
            self.assertLessEqual(arm["characters"], 100)
            self.assertEqual(arm["characters"], sum(len(v["label"]) for v in arm["memories"]))
            self.assertEqual(arm["diagnostics"]["logicalChecks"], len(arm["checked"]))
            self.assertLessEqual(arm["diagnostics"]["physicalChecks"], len(arm["checked"]))
            for view in arm["memories"]:
                self.assertLessEqual(len(view["label"]), 100)
                if name in ARMS[2:]:
                    self.assertEqual(view["status"], "CURRENT")
            if name in ARMS[2:]:
                self.assertNotIn(old, [v["id"] for v in arm["checked"]])
        self.assertTrue(all(len(body) <= 100 for body in self.model.checked_bodies))

    def test_checker_cannot_rescue_non_emerged_memories(self):
        result = self.run_compare(diffusion={"maxOutflow": 0}, checkBudget=200)
        self.assertTrue(result["seeds"])
        self.assertTrue(result["arms"]["formed_retrieval"]["checked"])
        self.assertEqual(result["arms"]["attention_diffusion"]["checked"], [])
        self.assertEqual(result["arms"]["attention_diffusion"]["memories"], [])
        # Best-path expansion deliberately has no outflow/competition control.
        expanded = result["arms"]["graph_expansion"]
        self.assertTrue(all(v["id"] in expanded["trace"]["state"] for v in expanded["checked"]))
        thresholded = self.run_compare(diffusion={"threshold": 1})["arms"]["attention_diffusion"]
        self.assertEqual(thresholded["checked"], [])
        self.assertEqual(thresholded["memories"], [])

    def test_logical_checks_remain_when_physical_cache_is_warm(self):
        cache = {}
        first = compare_associative(self.store, self.payload, self.model, check_cache=cache)
        before = self.model.counts["reranker"]
        second = compare_associative(self.store, self.payload, self.model, check_cache=cache)
        self.assertEqual(self.model.counts["reranker"], before)
        self.assertGreater(sum(a["diagnostics"]["physicalChecks"] for a in first["arms"].values()), 0)
        for name, arm in second["arms"].items():
            self.assertEqual(arm["diagnostics"]["physicalChecks"], 0)
            self.assertEqual(arm["checked"], first["arms"][name]["checked"])
            self.assertEqual(arm["memories"], first["arms"][name]["memories"])
        self.assertGreater(sum(a["diagnostics"]["logicalChecks"] for a in second["arms"].values()), 0)

    def test_window_cache_repeated_changed_body_recipe_scope_model(self):
        views = {"window:x": {"anchorSeq": 1, "label": "original body"}}
        first = window_matrix(self.store, self.model, "a", views, "recipe")
        before = self.model.counts["embedding"]
        repeated = window_matrix(self.store, self.model, "a", views, "recipe")
        self.assertEqual(first[3], 1)
        self.assertEqual(repeated[3], 0)
        self.assertEqual(self.model.counts["embedding"], before)
        np.testing.assert_array_equal(first[1], repeated[1])
        changed = window_matrix(self.store, self.model, "a",
                                {"window:x": {"anchorSeq": 1, "label": "changed body"}}, "recipe")
        self.assertEqual(changed[3], 1)
        self.assertFalse(np.array_equal(first[1], changed[1]))
        self.assertEqual(window_matrix(self.store, self.model, "b", views, "recipe")[3], 1)
        self.assertEqual(window_matrix(self.store, self.model, "a", views, "other recipe")[3], 1)
        other = FixtureVectors()
        other.fingerprint = "associative-fixture-v2"
        self.assertEqual(window_matrix(self.store, other, "a", views, "recipe")[3], 1)

    def test_compare_repeat_window_cache_adds_zero(self):
        first = self.run_compare()
        second = self.run_compare()
        self.assertEqual(first["sharedWork"]["newWindowVectors"], 8)
        self.assertEqual(second["sharedWork"]["newWindowVectors"], 0)

    def test_compare_raw_visibility_own_episode_and_cross_scope(self):
        load_demo(self.store, "b")
        self.store.create_episode("a", "hidden", "private")
        self.store.ingest("a", "hidden", [event("private", "x", "PRIVATE BODY", 9, "e1")])
        SemanticIndex(self.store, self.model).sync("a")
        SemanticIndex(self.store, self.model).sync("b")
        foreign_nodes = {n["id"] for n in self.store.graph("b")["nodes"]}
        closed = self.run_compare(checkBudget=200, limit=30, characterBudget=20000)
        own = self.run_compare(episode="hidden", checkBudget=200, limit=30, characterBudget=20000)
        for result, visible in ((closed, False), (own, True)):
            for name in ARMS[:2]:
                views = result["arms"][name]["memories"]
                evidence = {i for view in views for i in view["evidenceIds"]}
                self.assertEqual("private" in evidence, visible)
                if not visible:
                    self.assertTrue(all("PRIVATE BODY" not in view["label"] for view in views))
            self.assertTrue(foreign_nodes.isdisjoint(n["id"] for n in result["graphSnapshot"]["nodes"]))
            self.assertTrue(foreign_nodes.isdisjoint(result["seeds"]))
        other = self.run_compare(scope="b")
        self.assertTrue(set(other["seeds"]).issubset(foreign_nodes))

    def test_old_and_opt_in_comparisons_callable_with_same_model(self):
        original = compare(self.store, self.payload, self.model)
        associative = self.run_compare()
        self.assertEqual(set(original["arms"]), {"raw_retrieval", "formed_retrieval",
                                                 "graph_expansion", "attention_diffusion"})
        self.assertEqual(set(associative["arms"]), set(ARMS))
        again = compare(self.store, self.payload, self.model)
        for name in original["arms"]:
            self.assertEqual(original["arms"][name]["checked"], again["arms"][name]["checked"])

    def test_incomplete_index_and_invalid_shared_budgets_rejected(self):
        for field, value in (("checkBudget", 0), ("checkBudget", 201), ("limit", 0),
                             ("limit", 31), ("characterBudget", 99), ("characterBudget", 20001)):
            with self.subTest(field=field, value=value), self.assertRaises(Invalid):
                self.run_compare(**{field: value})
        self.store.create_episode("a", "new", "new")
        self.store.ingest("a", "new", [event("unindexed", "x", "pending", 10)])
        with self.assertRaisesRegex(Invalid, "索引"):
            self.run_compare()

    def test_manual_seeds_and_history_are_explicitly_rejected(self):
        for seeds in (None, {}, {"foreign": 1}):
            with self.subTest(seeds=seeds), self.assertRaises(Invalid):
                self.run_compare(seeds=seeds)
        for history in (True, None, 0, 1, "false", [], {}):
            with self.subTest(history=history), self.assertRaises(Invalid):
                self.run_compare(includeHistory=history)
        self.assertTrue(self.run_compare(includeHistory=False)["arms"])

    def test_diffusion_type_and_unknown_controls_rejected(self):
        for value in ([], "steps", 1, False, {"unknown": 1}):
            with self.subTest(value=value), self.assertRaises(Invalid):
                self.run_compare(diffusion=value)
        self.assertEqual(self.run_compare(diffusion=None)["parameters"]["diffusion"],
                         self.run_compare(diffusion={})["parameters"]["diffusion"])

    def test_invalid_requested_arms_rejected_before_model_work(self):
        bad = [None, (), "formed_retrieval", [], ["unknown"], [1], [None],
               [[]], [{}], ["formed_retrieval", "formed_retrieval"]]
        for arms in bad:
            before = dict(self.model.counts)
            with self.subTest(arms=arms), self.assertRaises(Invalid):
                self.run_compare(arms=arms)
            self.assertEqual(dict(self.model.counts), before)

    def test_standalone_arms_exact_requested_system_and_same_results(self):
        combined = self.run_compare()
        for name in ARMS:
            with self.subTest(name=name):
                standalone = self.run_compare(arms=[name])
                self.assertEqual(list(standalone["arms"]), [name])
                self.assertEqual(standalone["parameters"]["arms"], [name])
                arm = standalone["arms"][name]
                self.assertEqual(arm["checked"], combined["arms"][name]["checked"])
                self.assertEqual(arm["memories"], combined["arms"][name]["memories"])
                self.assertEqual(arm["trace"], combined["arms"][name]["trace"])
                self.assertEqual(arm["diagnostics"]["physicalChecks"], len(arm["checked"]))
        requested = ["attention_diffusion", "formed_multiquery"]
        self.assertEqual(list(self.run_compare(arms=requested)["arms"]), requested)

    def test_memory_only_never_builds_window_table_or_vectors(self):
        def has_table():
            return self.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='associative_window_vectors'").fetchone()
        self.assertIsNone(has_table())
        for name in ARMS[2:]:
            before = self.model.counts["embedding"]
            result = self.run_compare(arms=[name])
            self.assertIsNone(has_table())
            self.assertEqual(result["sharedWork"]["newWindowVectors"], 0)
            self.assertEqual(result["sharedWork"]["windowVectorScores"], 0)
            self.assertEqual(self.model.counts["embedding"] - before, 2)
            self.assertEqual(result["parameters"]["checkBudget"], 12)
            self.assertEqual(result["parameters"]["limit"], 4)
            self.assertEqual(result["parameters"]["characterBudget"], 1600)
            self.assertEqual(result["parameters"]["associative"], options({}))

    def test_missing_snapshot_vectors_reject_even_with_complete_head(self):
        for kind in ("node", "raw"):
            with self.subTest(kind=kind):
                self.store.db.execute("SAVEPOINT missing_vector")
                row = self.store.db.execute("SELECT source_seq FROM semantic_vectors WHERE kind=? LIMIT 1", (kind,)).fetchone()
                self.store.db.execute("DELETE FROM semantic_vectors WHERE kind=? AND source_seq=?", (kind, row[0]))
                # Commit the synthetic corruption; compare owns its transaction.
                self.store.db.execute("RELEASE missing_vector")
                self.assertTrue(SemanticIndex(self.store, self.model).status("a")[kind]["complete"])
                with self.assertRaisesRegex(Invalid, "快照"):
                    self.run_compare(arms=["formed_retrieval"])
                # Rebuild only the synthetic index for the next subcase.
                with self.store.db:
                    self.store.db.execute("DELETE FROM semantic_vectors WHERE scope='a'")
                    self.store.db.execute("DELETE FROM semantic_heads WHERE scope='a'")
                SemanticIndex(self.store, self.model).sync("a")

    def test_nonfinite_and_malformed_persisted_vectors_reject(self):
        row = dict(self.store.db.execute("SELECT * FROM semantic_vectors WHERE scope='a' AND kind='node' LIMIT 1").fetchone())
        cases = [b"bad", np.full(row["dimension"], np.nan, dtype='<f4').tobytes(),
                 np.full(row["dimension"], np.inf, dtype='<f4').tobytes()]
        for body in cases:
            with self.store.db:
                self.store.db.execute("UPDATE semantic_vectors SET vector=? WHERE scope='a' AND kind='node' AND source_seq=?",
                                      (body, row["source_seq"]))
            with self.subTest(body_length=len(body)), self.assertRaises(Invalid):
                self.run_compare(arms=["formed_retrieval"])
        with self.store.db:
            self.store.db.execute("UPDATE semantic_vectors SET vector=? WHERE scope='a' AND kind='node' AND source_seq=?",
                                  (row["vector"], row["source_seq"]))
        self.assertTrue(self.run_compare(arms=["formed_retrieval"])["arms"])

    def test_storage_and_cached_window_truncation_propagate(self):
        with self.store.db:
            self.store.db.execute("UPDATE semantic_vectors SET truncated=1 WHERE scope='a'")
        result = self.run_compare()
        self.assertTrue(all(g["truncated"] for g in result["grounding"]))
        for name in ("raw_retrieval", *ARMS[2:]):
            self.assertTrue(result["arms"][name]["checked"])
            self.assertTrue(all(c["truncated"] for c in result["arms"][name]["checked"]))
        with self.store.db:
            self.store.db.execute("UPDATE associative_window_vectors SET truncated=1")
        warm = self.run_compare(arms=["raw_window_retrieval"])
        self.assertEqual(warm["sharedWork"]["newWindowVectors"], 0)
        self.assertTrue(all(c["truncated"] for c in warm["arms"]["raw_window_retrieval"]["checked"]))

    def test_query_and_reranker_truncation_propagate(self):
        original = self.model.vectors
        def clipped_queries(texts, query=False):
            matrix, flags = original(texts, query=query)
            return matrix, [query] * len(texts)
        with patch.object(self.model, "vectors", side_effect=clipped_queries):
            result = self.run_compare()
        self.assertTrue(all(g["truncated"] for g in result["grounding"]))
        for arm in result["arms"].values():
            self.assertTrue(arm["checked"])
            self.assertTrue(all(c["truncated"] for c in arm["checked"]))
        with patch.object(self.model, "rerank", side_effect=lambda query, texts: ([1.] * len(texts), [True] * len(texts))):
            result = self.run_compare()
        self.assertTrue(all(c["truncated"] for arm in result["arms"].values() for c in arm["checked"]))

    def test_nonfinite_query_vectors_rejected(self):
        original = self.model.vectors
        def nonfinite_query(texts, query=False):
            matrix, flags = original(texts, query=query)
            if query:
                matrix[:] = np.nan
            return matrix, flags
        with patch.object(self.model, "vectors", side_effect=nonfinite_query):
            with self.assertRaises(Invalid):
                self.run_compare(arms=["formed_retrieval"])


if __name__ == "__main__":
    unittest.main()
