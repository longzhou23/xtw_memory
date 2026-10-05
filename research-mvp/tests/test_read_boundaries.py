"""Synthetic regressions: batch-independent vectors and write-owned edge visibility."""
import collections
import hashlib
import inspect
import itertools
import json
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from research_memory import dynamics
from research_memory.contracts import Invalid
from research_memory.index import LazyAdjacency
from research_memory.models import LocalModels
from research_memory.store import Store, encode


QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def synthetic_models(zero=False):
    """No constructor/model files: deliberately emulate padding-dependent inference."""
    model = LocalModels.__new__(LocalModels)
    model.np = np
    model.cache = collections.OrderedDict()
    model.counts = collections.Counter()

    def run(name, values):
        model.counts[name] += len(values)
        # A document's second coordinate changes with the longest batch member.
        # Normalization does not erase this dependence (unlike scalar scaling).
        width = max(map(len, values))
        rows = [[0., 0., 0.] if zero else
                [len(value) + 1., width + 2., sum(map(ord, value)) % 31 + 1.]
                for value in values]
        return np.asarray(rows, dtype=np.float32)[:, None, :], [len(v) > 40 for v in values]

    model.run = Mock(side_effect=run)
    return model


class EmbeddingReadBoundaryTests(unittest.TestCase):
    def test_execution_recipe_fingerprint_cannot_alias_legacy_manifest(self):
        manifest = {"pad_token_id": 0}
        root = MagicMock()
        root.__truediv__.return_value = root
        root.read_text.return_value = json.dumps(manifest)
        stream = root.open.return_value.__enter__.return_value
        stream.read.side_effect = lambda size: b""
        empty_hash = hashlib.sha256(b"").hexdigest()
        files = {name: {"model.onnx": empty_hash} for name in ("embedding", "reranker")}
        ort = types.SimpleNamespace(SessionOptions=Mock(), InferenceSession=Mock())
        tokenizers = types.SimpleNamespace(Tokenizer=types.SimpleNamespace(from_file=Mock(return_value=Mock())))
        with patch("research_memory.models.Path", return_value=root), \
                patch("research_memory.models.HASHES", files), \
                patch.dict("sys.modules", {"onnxruntime": ort, "tokenizers": tokenizers}):
            model = LocalModels("synthetic-no-files")
            with patch.object(LocalModels, "embedding_recipe", "synthetic-other-recipe"):
                other = LocalModels("synthetic-no-files")
        legacy = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        expected = hashlib.sha256(json.dumps({"manifestFingerprint": legacy,
            "embeddingRecipe": "single-document-int8-v1"}, sort_keys=True).encode()).hexdigest()
        self.assertEqual(model.manifest_fingerprint, legacy)
        self.assertEqual(model.fingerprint, expected)
        self.assertNotEqual(model.fingerprint, legacy)
        self.assertEqual(other.manifest_fingerprint, legacy)
        self.assertNotEqual(other.fingerprint, model.fingerprint)

    def test_mixed_lengths_permutations_and_cold_warm_calls_are_identical(self):
        texts = ["短", "a medium document", "long " * 20]
        reference = {}
        for text in texts:
            reference[text] = synthetic_models().vectors([text])[0][0]
        for order in itertools.permutations(texts):
            for warm in (False, True):
                with self.subTest(order=order, warm=warm):
                    model = synthetic_models()
                    if warm:
                        model.vectors([order[0]])
                    vectors, clips = model.vectors(list(order))
                    for text, vector, clip in zip(order, vectors, clips):
                        np.testing.assert_array_equal(vector, reference[text])
                        self.assertEqual(clip, len(text) > 40)
                    self.assertEqual(model.counts["embedding"], len(texts))
                    self.assertTrue(all(len(call.args[1]) == 1 for call in model.run.call_args_list))
                    before = model.run.call_count
                    cached, cached_clips = model.vectors(list(reversed(order)))
                    np.testing.assert_array_equal(cached, vectors[::-1])
                    self.assertEqual(cached_clips, clips[::-1])
                    self.assertEqual(model.run.call_count, before)

    def test_duplicates_query_prefix_and_cache_keys(self):
        model = synthetic_models()
        texts = ["same", "different length", "same"]
        documents, _ = model.vectors(texts)
        self.assertEqual([call.args for call in model.run.call_args_list],
                         [("embedding", ["same"]), ("embedding", ["different length"])])
        queries, _ = model.vectors(texts, query=True)
        self.assertEqual([call.args for call in model.run.call_args_list[2:]],
                         [("embedding", [QUERY_PREFIX + "same"]),
                          ("embedding", [QUERY_PREFIX + "different length"])])
        np.testing.assert_array_equal(documents[0], documents[2])
        np.testing.assert_array_equal(queries[0], queries[2])
        self.assertFalse(np.array_equal(documents[0], queries[0]))
        self.assertEqual(set(model.cache), {(flag, text) for flag in (False, True) for text in texts})
        model.vectors(texts)
        model.vectors(texts, query=True)
        self.assertEqual(model.counts["embedding"], 4)

    def test_zero_norm_is_rejected_without_caching_invalid_vector(self):
        model = synthetic_models(zero=True)
        with self.assertRaisesRegex(Invalid, "零范数"):
            model.vectors(["zero"])
        self.assertNotIn((False, "zero"), model.cache)

    def test_truncation_flags_survive_duplicates_cache_and_query_prefix(self):
        model = synthetic_models()
        texts = ["short", "x" * 50, "short"]
        self.assertEqual(model.vectors(texts)[1], [False, True, False])
        self.assertEqual(model.vectors(texts)[1], [False, True, False])
        body = "q" * 25
        self.assertEqual(model.vectors([body])[1], [False])
        self.assertEqual(model.vectors([body], query=True)[1], [True])
        self.assertEqual(model.vectors([body], query=True)[1], [True])
        self.assertEqual(model.similarity(body, ["short", "x" * 50])[1], [True, True])


class EdgeReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        for episode in ("closed", "own", "foreign"):
            self.store.create_episode("s", episode, episode)
        self.closed_evidence = [{"eventId": "closed-event", "quote": "old evidence"}]
        self.open_evidence = [{"eventId": "open-event", "quote": "private evidence"}]
        with self.store.db:
            for episode, run in (("closed", "closed-write"), ("own", "open-write")):
                self.store.db.execute("INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)",
                                      (run, "s", episode, "COMMITTED", "{}", "{}", "{}", None))
            for ident in ("a", "b"):
                self.store.db.execute("""INSERT INTO nodes
                    (id,scope,episode,stage,type,kind,label,subject,status,evidence,used,run_id,speaker_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ident, "s", "closed", "TEMPORARY", "PERSON", "ENTITY", ident, None,
                     "CURRENT", encode(self.closed_evidence), "[]", "closed-write", ident))
            self.insert_edge("0-closed", "SIMILARITY", .2, self.closed_evidence, "closed-write")
        self.store.close_episode("s", "closed")
        # Capture the independent oracle before private duplicate/new records exist.
        self.closed_graph = self.store.graph("s")
        with self.store.db:
            self.insert_edge("1-open-duplicate", "SIMILARITY", .9, self.open_evidence, "open-write")
            self.insert_edge("2-open-causal", "CAUSAL", .7, self.open_evidence, "open-write")
        for episode in ("own", "foreign"):
            self.store.ingest("s", episode, [
                {"id": episode + "-" + speaker, "speaker": speaker,
                 "time": "2026-10-01T10:00:00+00:00", "text": "synthetic pending"}
                for speaker in ("a", "b")])

    def insert_edge(self, ident, relation, strength, evidence, run):
        self.store.db.execute("INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?)",
                              (ident, "s", "a", "b", relation, strength, encode(evidence), ident, run))

    def expected_edges(self, own=False):
        rows = [dict(e) for e in self.closed_graph["edges"]]
        if own:
            rows[0] = {**rows[0], "strength": .9,
                       "evidence": self.closed_evidence + self.open_evidence,
                       "recordIds": ["0-closed", "1-open-duplicate"]}
            rows.append({"id": "2-open-causal", "scope": "s", "source": "a", "target": "b",
                         "relation": "CAUSAL", "strength": .7, "evidence": self.open_evidence,
                         "rationale": "2-open-causal", "run_id": "open-write",
                         "recordIds": ["2-open-causal"]})
        return rows

    def edges_for(self, episode, **kwargs):
        # Fail as an explicit missing-contract assertion, not a TypeError/harness error.
        self.assertIn("episode", inspect.signature(self.store.edges_from).parameters,
                      "edges_from must accept caller episode as its last parameter")
        self.assertEqual(list(inspect.signature(self.store.edges_from).parameters)[-1], "episode")
        return self.store.edges_from("s", ["a", "b"], episode=episode, **kwargs)

    def close_own(self):
        with self.store.db:
            self.store.db.execute("UPDATE events SET processed=1 WHERE episode='own'")
        self.store.close_episode("s", "own")

    def test_default_and_foreign_graph_filter_before_duplicate_aggregation(self):
        for episode in (None, "closed", "foreign"):
            with self.subTest(episode=episode):
                self.assertEqual(self.store.graph("s", episode)["edges"], self.expected_edges())
        self.assertEqual(self.store.edges_from("s", ["a", "b"]), self.expected_edges())

    def test_direct_reads_own_visibility_and_close_transition(self):
        self.assertEqual(self.edges_for("foreign", within=True), self.expected_edges())
        self.assertEqual(self.edges_for("own", within=True), self.expected_edges(own=True))
        self.assertEqual(self.store.graph("s", "own")["edges"], self.expected_edges(own=True))
        self.close_own()
        for episode in (None, "own", "foreign"):
            self.assertEqual(self.store.graph("s", episode)["edges"], self.expected_edges(own=True))
            self.assertEqual(self.edges_for(episode), self.expected_edges(own=True))

    def test_prepare_filters_foreign_records_but_includes_own_and_closed(self):
        self.assertEqual(self.store.prepare("s", "foreign")["knownAssociations"], self.expected_edges())
        self.assertEqual(self.store.prepare("s", "own")["knownAssociations"], self.expected_edges(own=True))
        self.close_own()
        self.assertEqual(self.store.prepare("s", "foreign")["knownAssociations"], self.expected_edges(own=True))

    def test_uncommitted_owning_writes_never_contribute(self):
        with self.store.db:
            for status in ("PENDING", "FAILED"):
                run = status + "-write"
                self.store.db.execute("INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)",
                                      (run, "s", "closed", status, "{}", None, "{}", None))
                self.insert_edge(status, "OPPOSITION", 1., self.open_evidence, run)
        self.assertEqual(self.store.graph("s", "own")["edges"], self.expected_edges(own=True))

    def test_orphan_and_mismatched_write_scope_do_not_leak_or_use_budget(self):
        self.store.create_episode("other-scope", "closed", "foreign owner")
        self.store.close_episode("other-scope", "closed")
        with self.store.db:
            self.store.db.execute("INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)",
                ("foreign-owner", "other-scope", "closed", "COMMITTED", "{}", "{}", "{}", None))
            self.insert_edge("3-orphan", "SIMILARITY", 1., self.open_evidence, "missing-owner")
            self.insert_edge("4-scope-mismatch", "OPPOSITION", 1., self.open_evidence, "foreign-owner")
        for episode in (None, "closed", "foreign", "own"):
            own = episode == "own"
            with self.subTest(episode=episode):
                self.assertEqual(self.edges_for(episode, record_budget=3 if own else 1), self.expected_edges(own))
                self.assertEqual(self.store.graph("s", episode)["edges"], self.expected_edges(own))
        self.assertEqual(self.store.prepare("s", "foreign")["knownAssociations"], self.expected_edges())

    def test_full_and_lazy_propagation_match_visible_oracle_in_all_states(self):
        plan = {"cues": [{"text": "synthetic", "weight": 1}],
                "relations": {"SIMILARITY": .5, "CAUSAL": .5, "OPPOSITION": 0}, "direction": "forward"}
        config = dynamics.parameters({"steps": 3, "flowFloor": 0})
        for closed in (False, True):
            if closed:
                self.close_own()
            for episode in (None, "closed", "own", "foreign"):
                for propagate in (dynamics.diffuse, dynamics.graph_expand):
                    with self.subTest(closed=closed, episode=episode, method=propagate.__name__):
                        expected = {"nodes": self.closed_graph["nodes"],
                                    "edges": self.expected_edges(own=closed or episode == "own")}
                        oracle = propagate(expected, {"a": 1}, plan, config)
                        full = propagate(self.store.graph("s", episode), {"a": 1}, plan, config)
                        lazy = LazyAdjacency(self.store, "s", episode, plan, config, {"a": 1})
                        partial = propagate({}, {"a": 1}, plan, config, adjacency=lazy)
                        self.assertEqual(full, oracle)
                        self.assertEqual(partial, oracle)
                        self.assertEqual(lazy.snapshot()["edges"], expected["edges"])

    def test_raw_record_budget_counts_only_visible_records_before_combining(self):
        try:
            records = self.store.edges_from("s", ["a", "b"], record_budget=1)
        except Invalid as error:
            self.fail(f"Invisible open records exhausted the closed read budget: {error}")
        self.assertEqual(records, self.expected_edges())
        self.assertEqual(self.edges_for("foreign", record_budget=1), self.expected_edges())
        self.assertEqual(self.edges_for("own", record_budget=3), self.expected_edges(own=True))
        with self.assertRaisesRegex(Invalid, "预算"):
            self.edges_for("own", record_budget=2)
        plan = {"relations": {"SIMILARITY": 1, "CAUSAL": 0, "OPPOSITION": 0}, "direction": "forward"}
        lazy = LazyAdjacency(self.store, "s", "foreign", plan, dynamics.parameters(), {"a": 1}, max_edges=1)
        lazy.get("a")
        self.assertEqual(lazy.diagnostics()["rawEdgeReads"], 1)
        lazy.get("a")
        self.assertEqual(lazy.diagnostics()["rawEdgeReads"], 1)
        self.close_own()
        with self.assertRaisesRegex(Invalid, "预算"):
            self.store.edges_from("s", ["a", "b"], record_budget=2)


if __name__ == "__main__":
    unittest.main()
