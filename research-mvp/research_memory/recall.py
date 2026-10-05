"""Write/read attribution: raw retrieval vs formed retrieval vs graph vs diffusion."""
import time

from . import dynamics
from .contracts import Invalid, integer, number, text, validate_plan, PLAN_SCHEMA
from .providers import PLAN_PROMPT
from .store import digest


def make_plan(query, supplied=None, planner=None):
    if supplied is not None:
        return validate_plan(supplied), {"source": "explicit-plan"}
    if planner is not None:
        plan, metrics = planner.generate(PLAN_PROMPT, {"query": query}, PLAN_SCHEMA)
        return validate_plan(plan), {"source": "model-query-only", "promptHash": digest(PLAN_PROMPT),
                                     "schemaHash": digest(PLAN_SCHEMA), **metrics}
    plan = {"cues": [{"text": query, "weight": 1.0}],
            "relations": {"CAUSAL": 0, "SIMILARITY": 1, "OPPOSITION": 0}, "direction": "both"}
    return plan, {"source": "explicit-similarity-only-default (no relation inference)"}


def ground(graph, plan, model, manual=None, minimum=.35):
    nodes = {node["id"]: node for node in graph["nodes"]}
    if manual is not None:
        if not isinstance(manual, dict) or not manual or len(manual) > 4:
            raise Invalid("手工种子必须是1–4个节点的权重对象")
        for ident, weight in manual.items():
            if ident not in nodes:
                raise Invalid("种子不在本次可见图内")
            number(weight, "seed weight")
        return dynamics.normalize(manual), [{"source": "manual-seeds"}]
    seeds, trace = {}, []
    eligible = [node for node in nodes.values() if node["status"] == "CURRENT"]
    for cue in plan["cues"]:
        if cue["weight"] <= 0 or not eligible:
            continue
        exact = [node for node in eligible if node["label"].casefold() == cue["text"].casefold()]
        if exact:
            selected, score, clipped = exact[0], 1.0, False
        else:
            scores, flags = model.similarity(cue["text"], [node["label"] for node in eligible])
            index = max(range(len(eligible)), key=lambda i: (scores[i], eligible[i]["id"]))
            selected, score, clipped = eligible[index], scores[index], flags[index]
        trace.append({"cue": cue, "nodeId": selected["id"], "similarity": score, "truncated": clipped, "accepted": score >= minimum})
        if score >= minimum:
            seeds[selected["id"]] = seeds.get(selected["id"], 0) + cue["weight"]
    return dynamics.normalize(seeds) if seeds else {}, trace


def compare(store, payload, model, planner=None):
    if payload.get("indexed") is True:
        from .indexed_recall import compare_indexed
        return compare_indexed(store, payload, model, planner)
    started = time.perf_counter()
    scope = text(payload.get("scope"), "scope", 200)
    episode = payload.get("episode")
    query = text(payload.get("query"), "query", 2000)
    checks = integer(payload.get("checkBudget", 24), "checkBudget", 1, 200)
    limit = integer(payload.get("limit", 6), "limit", 1, 30)
    budget = integer(payload.get("characterBudget", 3000), "characterBudget", 100, 20000)
    threshold = number(payload.get("minScore", model.min_score), "minScore", -30, 30)
    minimum = number(payload.get("seedMinimum", .35), "seedMinimum")
    history = payload.get("includeHistory", False)
    if not isinstance(history, bool):
        raise Invalid("includeHistory 必须为布尔值")
    config = dynamics.parameters(payload.get("diffusion"))
    store.db.execute("BEGIN")
    try:
        graph = store.graph(scope, episode)
        raw_rows = [dict(row) for row in store.db.execute("SELECT e.* FROM events e JOIN episodes p ON p.scope=e.scope AND p.id=e.episode WHERE e.scope=? AND (p.status IN ('CLOSED','CONSOLIDATED') OR e.episode=?) ORDER BY e.seq", (scope, episode))]
        revision = store.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()
        if revision is None:
            raise Invalid("scope不存在")
        revision = revision[0]
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    if len(raw_rows) > 10000:
        raise Invalid("研究版原始事件对照上限10000；请缩小scope")
    plan, plan_meta = make_plan(query, payload.get("plan"), planner)
    seeds, grounding = ground(graph, plan, model, payload.get("seeds"), minimum)
    all_nodes = {node["id"]: node for node in graph["nodes"]}
    memories = {ident: node for ident, node in all_nodes.items() if node["type"] == "MEMORY" and (history or node["status"] == "CURRENT")}
    raw = {"event:" + row["id"]: {"id": "event:" + row["id"], "label": row["text"], "type": "RAW_EVENT", "status": "RAW",
           "speaker": row["speaker"], "time": row["time"], "replyTo": row["reply_to"], "evidence": [{"eventId": row["id"], "quote": row["text"]}]} for row in raw_rows}
    arms = {}
    for name in ["raw_retrieval", "formed_retrieval", "graph_expansion", "attention_diffusion"]:
        arm_started = time.perf_counter()
        before = dict(model.counts)
        collection = raw if name == "raw_retrieval" else memories
        outcome = {"state": {}, "paths": {}, "history": [], "checkedArcs": 0, "visitedNodes": 0}
        if name.endswith("retrieval"):
            ids = list(collection)
            values, clips = model.similarity(query, [collection[ident]["label"] for ident in ids])
            ordering = dict(zip(ids, values))
            retrieval_clips = dict(zip(ids, clips))
            candidates = sorted(ids, key=lambda ident: (-ordering[ident], ident))[:checks]
        else:
            retrieval_clips = {}
            if seeds:
                operation = dynamics.diffuse if name == "attention_diffusion" else dynamics.graph_expand
                outcome = operation(graph, seeds, plan, config)
            ordering = outcome["state"]
            candidates = [ident for ident in ordering if ident in collection and
                          (name != "attention_diffusion" or ordering[ident] >= config["threshold"])]
            candidates = sorted(candidates, key=lambda ident: (-ordering[ident], ident))[:checks]
        scores, clipped = model.rerank(query, [collection[ident]["label"] for ident in candidates])
        checked = [{"id": ident, "selectionScore": ordering[ident], "rerankScore": score,
                    "truncated": clip or retrieval_clips.get(ident, False), "accepted": score >= threshold}
                   for ident, score, clip in zip(candidates, scores, clipped)]
        hits, remaining = [], budget
        for item in sorted(checked, key=lambda item: (-item["rerankScore"], item["id"])):
            node = collection[item["id"]]
            if not item["accepted"] or len(hits) >= limit or len(node["label"]) > remaining:
                continue
            hits.append({**node, **item, "discoveryPath": outcome["paths"].get(item["id"], [])})
            remaining -= len(node["label"])
        arms[name] = {"memories": hits, "checked": checked, "trace": outcome,
                      "characters": budget - remaining, "diagnostics": {"candidateCount": len(candidates),
                      "modelCalls": {key: value - before.get(key, 0) for key, value in model.counts.items()},
                      "seconds": round(time.perf_counter() - arm_started, 4)}}
    result = {"query": query, "scope": scope, "episode": episode, "scopeRevision": revision,
              "model": model.name, "modelFingerprint": model.fingerprint, "plan": plan, "planMetadata": plan_meta,
              "seeds": seeds, "grounding": grounding, "graphHash": digest(graph), "graphSnapshot": graph,
              "parameters": {"diffusion": config, "checkBudget": checks, "limit": limit, "characterBudget": budget,
                             "minScore": threshold, "seedMinimum": minimum, "includeHistory": history}, "arms": arms,
              "seconds": round(time.perf_counter() - started, 3),
              "interpretation": "原文与记忆直接检索用于观察写入影响；三种记忆读取共享图/记忆、检查与输出上限。图访问量不同，顺序执行共享暖缓存，耗时不是同质量速度结论。"}
    result["recallId"] = store.save_recall(scope, result)
    return result
