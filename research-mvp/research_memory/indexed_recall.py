"""Four-arm comparison backed by persistent vectors and exact lazy diffusion."""
import time

from . import dynamics
from .contracts import Invalid, integer, number, text
from .index import LazyAdjacency, SemanticIndex
from .recall import make_plan
from .store import digest


def compare_indexed(store, payload, model, planner=None):
    started = time.perf_counter()
    scope = text(payload.get("scope"), "scope", 200)
    episode = payload.get("episode")
    checks = integer(payload.get("checkBudget", 24), "checkBudget", 1, 200)
    limit = integer(payload.get("limit", 6), "limit", 1, 30)
    budget = integer(payload.get("characterBudget", 3000), "characterBudget", 100, 20000)
    minimum = number(payload.get("seedMinimum", .35), "seedMinimum")
    min_score = number(payload.get("minScore", model.min_score), "minScore", -30, 30)
    history = payload.get("includeHistory", False)
    if not isinstance(history, bool):
        raise Invalid("includeHistory必须为布尔值")
    query = text(payload.get("query"), "query", 2000)
    config = dynamics.parameters(payload.get("diffusion"))
    plan, plan_meta = make_plan(query, payload.get("plan"), planner)
    index = SemanticIndex(store, model)
    store.db.execute("BEGIN")
    try:
        if episode is not None:
            store._episode(scope, episode)
        row = store.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()
        if row is None:
            raise Invalid("scope不存在")
        revision = row[0]
        index_status = index.require_complete(scope)
        seeds, grounding = {}, []
        manual = payload.get("seeds")
        if manual is not None:
            if not isinstance(manual, dict) or not 1 <= len(manual) <= 4:
                raise Invalid("手工种子必须是1–4个节点的权重对象")
            if set(store.visible_nodes(scope, manual, episode, mentions=False)) != set(manual):
                raise Invalid("种子不在本次可见图内")
            for weight in manual.values():
                number(weight, "seed weight")
            seeds = dynamics.normalize(manual)
            grounding = [{"source": "manual-seeds"}]
        else:
            for cue in plan["cues"]:
                if cue["weight"] <= 0:
                    continue
                # SQLite NOCASE covers ASCII case; non-ASCII exact labels remain literal.
                exact = store.db.execute("SELECT id FROM nodes WHERE scope=? AND status='CURRENT' AND label=? COLLATE NOCASE AND (stage='LONG_TERM' OR (episode=? AND stage='TEMPORARY')) ORDER BY seq LIMIT 1", (scope, cue["text"], episode)).fetchone()
                if exact:
                    hit, diagnostics = {"id": exact[0], "score": 1., "truncated": False}, {"exactLabel": True}
                else:
                    hits, diagnostics = index.search(scope, cue["text"], limit=1, episode=episode)
                    hit = hits[0] if hits else None
                if hit:
                    grounding.append({"cue": cue, "nodeId": hit["id"], "similarity": hit["score"],
                                      "truncated": hit["truncated"], "accepted": hit["score"] >= minimum,
                                      "index": diagnostics})
                    if hit["score"] >= minimum:
                        seeds[hit["id"]] = seeds.get(hit["id"], 0)+cue["weight"]
            seeds = dynamics.normalize(seeds) if seeds else {}
        lazy = LazyAdjacency(store, scope, episode, plan, config, seeds,
                             payload.get("graphNodeBudget", 20000), payload.get("graphEdgeBudget", 100000))
        arms = {}
        for name in ["raw_retrieval", "formed_retrieval", "graph_expansion", "attention_diffusion"]:
            clock, before = time.perf_counter(), dict(model.counts)
            outcome = {"state": {}, "paths": {}, "history": [], "checkedArcs": 0, "visitedNodes": 0}
            retrieval_clips, search_diag = {}, {}
            if name.endswith("retrieval"):
                kind = "raw" if name == "raw_retrieval" else "node"
                hits, search_diag = index.search(scope, query, kind, checks, episode, memories_only=kind == "node", current_only=not history)
                ordering = {("event:" if kind == "raw" else "")+h["id"]: h["score"] for h in hits}
                retrieval_clips = {("event:" if kind == "raw" else "")+h["id"]: h["truncated"] for h in hits}
                if kind == "node":
                    collection = store.visible_nodes(scope, [h["id"] for h in hits], episode)
                else:
                    collection = {}
                    for h in hits:
                        event = dict(store.db.execute("SELECT * FROM events WHERE scope=? AND id=?", (scope, h["id"])).fetchone())
                        ident = "event:"+event["id"]
                        collection[ident] = {"id": ident, "label": event["text"], "type": "RAW_EVENT", "status": "RAW",
                            "speaker": event["speaker"], "time": event["time"], "replyTo": event["reply_to"],
                            "evidence": [{"eventId": event["id"], "quote": event["text"]}]}
                candidates = list(ordering)
            else:
                if seeds:
                    operation = dynamics.graph_expand if name == "graph_expansion" else dynamics.diffuse
                    outcome = operation({}, seeds, plan, config, adjacency=lazy)
                ordering = outcome["state"]
                eligible = [ident for ident in ordering if ident in lazy.nodes and lazy.nodes[ident]["type"] == "MEMORY"
                            and (history or lazy.nodes[ident]["status"] == "CURRENT")
                            and (name != "attention_diffusion" or ordering[ident] >= config["threshold"])]
                candidates = sorted(eligible, key=lambda ident: (-ordering[ident], ident))[:checks]
                collection = store.visible_nodes(scope, candidates, episode)
            scores, clips = model.rerank(query, [collection[i]["label"] for i in candidates])
            checked = [{"id": i, "selectionScore": ordering[i], "rerankScore": score,
                        "truncated": bool(clip or retrieval_clips.get(i, False)), "accepted": score >= min_score}
                       for i, score, clip in zip(candidates, scores, clips)]
            selected, remaining = [], budget
            for item in sorted(checked, key=lambda i: (-i["rerankScore"], i["id"])):
                node = collection[item["id"]]
                if not item["accepted"] or len(selected) >= limit or len(node["label"]) > remaining:
                    continue
                selected.append({**node, **item, "discoveryPath": outcome["paths"].get(item["id"], [])})
                remaining -= len(node["label"])
            arms[name] = {"memories": selected, "checked": checked, "trace": outcome, "characters": budget-remaining,
                          "diagnostics": {"candidateCount": len(candidates), "seconds": round(time.perf_counter()-clock, 4),
                                          "modelCalls": {k: v-before.get(k, 0) for k, v in model.counts.items()},
                                          "search": search_diag}}
        graph = lazy.snapshot()
        result = {"query": query, "scope": scope, "episode": episode, "scopeRevision": revision, "model": model.name,
                  "modelFingerprint": model.fingerprint, "plan": plan, "planMetadata": plan_meta,
                  "seeds": seeds, "grounding": grounding, "graphHash": digest(graph), "graphSnapshot": graph,
                  "index": index_status, "graphAccess": lazy.diagnostics(), "arms": arms,
                  "parameters": {"diffusion": config, "checkBudget": checks, "limit": limit, "characterBudget": budget,
                                 "minScore": min_score, "seedMinimum": minimum, "includeHistory": history},
                  "seconds": round(time.perf_counter()-started, 3),
                  "interpretation": "持久FP32向量分块精确搜索（非ANN）；图按实际扩展加载完整邻边。图快照仅含访问子图，不代表整库。四路检查/输出预算共享，图访问和顺序暖缓存不同。"}
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    result["recallId"] = store.save_recall(scope, result)
    return result
