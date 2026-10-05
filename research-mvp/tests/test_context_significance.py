"""Software contract checks only: fake judgments do not establish AI accuracy."""
import copy
import itertools
import unittest

from research_memory.contracts import Invalid
from research_memory import context_significance as significance


def fixture():
    # Ordinary conversation, not a question, urgent request, or stable-trait claim.
    state = {"messages": [
        {"id": "now-1", "speaker": "u_tea", "time": "2026-09-02T12:00:00Z",
         "text": "午后和大家一起去新开的茶馆坐坐。", "replyTo": None},
        {"id": "now-2", "speaker": "u_friend", "time": "2026-09-02T12:01:00Z",
         "text": "那家有不少饮品。", "replyTo": "now-1"}], "focusSpeakerId": "u_tea"}
    events = [
        {"id": "past-1", "speaker": "u_tea", "time": "2026-09-01T12:00:00Z",
         "text": "这周医生让我暂时避开咖啡因，和朋友出去也只能点无咖啡因的。",
         "reply_to": None, "episode": "temporary-constraint"},
        {"id": "past-2", "speaker": "u_tea", "time": "2026-09-01T13:00:00Z",
         "text": "刚把电脑桌上的文件归档了。", "reply_to": None, "episode": "desk"}]
    candidates = [
        {"id": "memory-constraint", "label": "u_tea 本周暂时需要避开咖啡因。",
         "sourceEventIds": ["past-1"]},
        {"id": "memory-desk", "label": "u_tea 昨天整理了电脑文件。",
         "sourceEventIds": ["past-2"]}]
    return state, candidates, events


def judgment(ident="memory-constraint", utility="USEFUL_CONTEXT",
             support="SUPPORTED", policy="INTERNAL_ONLY", anchors=None):
    return {"candidateId": ident, "utility": utility, "claimSupport": support,
            "mentionPolicy": policy, "currentAnchorIds": ["now-1"] if anchors is None else anchors,
            "rationale": "Synthetic provider output; checks mechanics, not semantic truth."}


class FakeProvider:
    def __init__(self, output, mutate=None, metrics=None):
        self.output = output
        self.mutate = mutate
        self.metrics = {} if metrics is None else metrics
        self.calls = []

    def generate(self, prompt, payload, schema):
        self.calls.append(copy.deepcopy((prompt, payload, schema)))
        if self.mutate:
            self.mutate(payload, schema)
        return self.output, self.metrics


class ContextSignificanceTests(unittest.TestCase):
    def setUp(self):
        self.state, self.candidates, self.events = fixture()
        self.request = significance.make_request(self.state, self.candidates, self.events)
        self.output = {"judgments": [judgment(), judgment("memory-desk", "ASSOCIATIVE_ONLY", anchors=[])]}

    def test_all_utility_support_policy_combinations(self):
        request = significance.make_request(self.state, self.candidates[:1], self.events)
        for utility, support, policy in itertools.product(
                significance.UTILITIES, ("SUPPORTED", "UNCERTAIN", "UNSUPPORTED"),
                ("INTERNAL_ONLY", "CONTEXTUAL_MENTION", "DO_NOT_USE")):
            with self.subTest(utility=utility, support=support, policy=policy):
                result = significance.apply(request, {"judgments": [judgment(
                    utility=utility, support=support, policy=policy)]})
                expected = utility in ("USEFUL_CONTEXT", "NECESSARY_CONTEXT") and support == "SUPPORTED" and policy != "DO_NOT_USE"
                self.assertIs(result["judgments"][0]["acceptedForInternalContext"], expected)
                self.assertIs(result["judgments"][0]["externalDisclosureAuthorized"], False)
                self.assertEqual(result["workingContext"], self.candidates[:1] if expected else [])

    def test_non_question_constraint_and_actor_only_control_mechanics(self):
        # Expected judgments are deliberately supplied, never asserted to be AI truth.
        provider = FakeProvider(self.output)
        result = significance.judge(self.state, self.candidates, self.events, provider)
        self.assertEqual(result["workingContext"], self.candidates[:1])
        self.assertEqual(result["candidates"], self.candidates)
        self.assertEqual(result["currentState"], self.state)
        self.assertEqual(result["modelCalls"], 1)
        self.assertEqual(provider.calls, [(self.request["prompt"], self.request["payload"], self.request["schema"])])

    def test_empty_candidates_never_call_provider(self):
        provider = FakeProvider(None, mutate=lambda *_: self.fail("provider called"))
        result = significance.judge(self.state, [], self.events, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["seconds"], 0)
        self.assertIsNone(result["modelMetrics"])
        self.assertEqual(result["judgments"], [])
        self.assertEqual(result["workingContext"], [])

    def test_sources_are_complete_past_rows_only_for_actual_candidates(self):
        request = significance.make_request(self.state, self.candidates[:1], self.events)
        self.assertEqual(request["payload"], {"currentState": self.state,
                         "candidates": self.candidates[:1], "sources": self.events[:1]})
        self.assertEqual(set(request["payload"]), {"currentState", "candidates", "sources"})

    def test_request_and_results_are_deep_copies(self):
        before = copy.deepcopy((self.request, self.output))
        result = significance.apply(self.request, self.output)
        result["currentState"]["messages"][0]["text"] = "changed"
        result["candidates"][0]["sourceEventIds"].append("changed")
        result["workingContext"][0]["label"] = "changed"
        result["judgments"][0]["currentAnchorIds"].append("changed")
        self.assertEqual((self.request, self.output), before)
        self.state["messages"][0]["text"] = "changed"
        self.candidates[0]["label"] = "changed"
        self.events[0]["text"] = "changed"
        self.assertEqual(self.request, before[0])

    def test_invalid_sources(self):
        cases = []
        for timestamp in ("2026-09-02T12:00:00Z", "2026-09-03T00:00:00Z",
                          "2026-09-02T14:00:00+02:00", "2026-09-01T12:00:00", "not-a-time"):
            events = copy.deepcopy(self.events)
            events[0]["time"] = timestamp
            cases.append(events)
        cases.append(self.events + [copy.deepcopy(self.events[0])])
        for field in ("id", "speaker", "time", "text", "reply_to", "episode"):
            events = copy.deepcopy(self.events)
            del events[0][field]
            cases.append(events)
        for field, value in (("text", ""), ("text", None), ("speaker", 4), ("reply_to", 4), ("query", "hidden")):
            events = copy.deepcopy(self.events)
            events[0][field] = value
            cases.append(events)
        cases.extend([None, {}, [None]])
        for events in cases:
            with self.subTest(events=events), self.assertRaises(Invalid):
                significance.make_request(self.state, self.candidates, events)

    def test_invalid_candidates_and_reference_counts(self):
        cases = [None, {}, [None], self.candidates + [copy.deepcopy(self.candidates[0])],
                 [{"id": str(i), "label": "body", "sourceEventIds": ["past-1"]} for i in range(31)]]
        for refs in ([], ["past-1", "past-1"], ["missing"], ["now-1"], [1], "past-1", None):
            candidate = copy.deepcopy(self.candidates[0])
            candidate["sourceEventIds"] = refs
            cases.append([candidate])
        for field in ("id", "label", "sourceEventIds"):
            candidate = copy.deepcopy(self.candidates[0])
            del candidate[field]
            cases.append([candidate])
        for field, value in (("label", ""), ("label", None), ("id", ""), ("method", "target"),
                             ("gold", True), ("accepted", True), ("query", "hidden")):
            candidate = copy.deepcopy(self.candidates[0])
            candidate[field] = value
            cases.append([candidate])
        for candidates in cases:
            with self.subTest(candidates=candidates), self.assertRaises(Invalid):
                significance.make_request(self.state, candidates, self.events)

    def test_state_rejects_hidden_controls_and_malformed_messages(self):
        for field in ("query", "gold", "targetMemoryIds", "method", "accepted"):
            state = copy.deepcopy(self.state)
            state[field] = "hidden"
            with self.subTest(field=field), self.assertRaises(Invalid):
                significance.make_request(state, self.candidates, self.events)
        for change in (lambda s: s.update(focusSpeakerId="unknown"),
                       lambda s: s.update(messages=[]),
                       lambda s: s["messages"][0].update(unknown=True),
                       lambda s: s["messages"][0].pop("text"),
                       lambda s: s["messages"][1].update(id="now-1"),
                       lambda s: s["messages"][1].update(time="2026-09-01T00:00:00Z")):
            state = copy.deepcopy(self.state)
            change(state)
            with self.subTest(state=state), self.assertRaises(Invalid):
                significance.make_request(state, self.candidates, self.events)

    def test_coverage_exactly_once_and_real_unique_anchors(self):
        cases = [{"judgments": []}, {"judgments": self.output["judgments"][:1]},
                 {"judgments": self.output["judgments"] + [judgment()]},
                 {"judgments": [judgment(), judgment("invented")]},
                 {"judgments": [judgment(), judgment()]}]
        for utility in ("USEFUL_CONTEXT", "NECESSARY_CONTEXT"):
            cases.append({"judgments": [judgment(utility=utility, anchors=[]), self.output["judgments"][1]]})
        for anchors in (["past-1"], ["invented"], ["now-1", "now-1"]):
            cases.append({"judgments": [judgment(anchors=anchors), self.output["judgments"][1]]})
        for output in cases:
            with self.subTest(output=output), self.assertRaises(Invalid):
                significance.apply(self.request, output)
        for utility in ("NONE", "ASSOCIATIVE_ONLY"):
            significance.apply(self.request, {"judgments": [judgment(utility=utility, anchors=[]), self.output["judgments"][1]]})

    def test_output_rejects_malformed_enums_types_and_forged_permissions(self):
        for field in judgment():
            output = copy.deepcopy(self.output)
            del output["judgments"][0][field]
            with self.subTest(missing=field), self.assertRaises(Invalid):
                significance.apply(self.request, output)
        for field, value in (("utility", "HIGH"), ("claimSupport", "TRUE"), ("mentionPolicy", "AUTHORIZED"),
                             ("candidateId", 1), ("rationale", ""), ("currentAnchorIds", "now-1"),
                             ("externalDisclosureAuthorized", True), ("acceptedForInternalContext", True),
                             ("inputHash", "forged"), ("gold", True)):
            output = copy.deepcopy(self.output)
            output["judgments"][0][field] = value
            with self.subTest(field=field), self.assertRaises(Invalid):
                significance.apply(self.request, output)
        for output in (None, [], {**self.output, "inputHash": "forged"}, {"judgments": {}}):
            with self.subTest(output=output), self.assertRaises(Invalid):
                significance.apply(self.request, output)

    def test_request_prompt_hash_schema_enum_and_payload_mutations_rejected(self):
        mutations = [lambda r: r.update(prompt="rewritten"),
                     lambda r: r.update(inputHash="forged"), lambda r: r.update(promptHash="forged"),
                     lambda r: r.update(schemaHash="forged"), lambda r: r.update(extra=True),
                     lambda r: r["payload"]["currentState"]["messages"][0].update(text="rewritten"),
                     lambda r: r["payload"]["candidates"][0].update(label="rewritten"),
                     lambda r: r["payload"]["sources"][0].update(text="rewritten"),
                     lambda r: r["schema"]["properties"]["judgments"]["items"]["properties"]["utility"]["enum"].append("FORGED")]
        for index, mutate in enumerate(mutations):
            request = copy.deepcopy(self.request)
            mutate(request)
            with self.subTest(mutation=index), self.assertRaises(Invalid):
                significance.apply(request, self.output)

    def test_provider_payload_and_schema_mutations_rejected_without_retry(self):
        for mutate in (lambda p, s: p["currentState"]["messages"][0].update(text="rewritten"),
                       lambda p, s: p["candidates"][0].update(label="rewritten"),
                       lambda p, s: p["sources"][0].update(text="rewritten"),
                       lambda p, s: s.update(additionalProperties=True),
                       lambda p, s: s["properties"]["judgments"]["items"]["properties"]["utility"]["enum"].append("FORGED")):
            provider = FakeProvider(self.output, mutate=mutate)
            before = copy.deepcopy((self.state, self.candidates, self.events))
            with self.assertRaises(Invalid):
                significance.judge(self.state, self.candidates, self.events, provider)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual((self.state, self.candidates, self.events), before)

    def test_metrics_forgery_cannot_override_authoritative_results(self):
        metrics = {"inputHash": "forged", "promptHash": "forged", "schemaHash": "forged",
                   "modelCalls": 99, "externalDisclosureAuthorized": True, "workingContext": ["invented"]}
        result = significance.judge(self.state, self.candidates, self.events, FakeProvider(self.output, metrics=metrics))
        for key in ("inputHash", "promptHash", "schemaHash"):
            self.assertEqual(result[key], self.request[key])
        self.assertEqual(result["modelCalls"], 1)
        self.assertEqual(result["workingContext"], self.candidates[:1])
        self.assertTrue(all(row["externalDisclosureAuthorized"] is False for row in result["judgments"]))
        self.assertEqual(result["modelMetrics"], metrics)
        metrics["workingContext"].append("changed")
        self.assertNotEqual(result["modelMetrics"], metrics)


if __name__ == "__main__":
    unittest.main()
