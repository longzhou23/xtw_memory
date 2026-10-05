"""Opt-in bounded research comparison with stronger RAG and shared evidence views.

This is not an ANN or lazy large-library implementation. It uses the complete
visible small graph so baselines can get the same identity/evidence context.
No answers/gold IDs are accepted. Candidate checks cannot alter propagation.
"""
import math
import numbers
import re
import time

from . import dynamics
from .contracts import Invalid, integer, number, text
from .index import SemanticIndex
from .recall import make_plan
from .store import digest


DEFAULT_DYNAMICS = {"flowFloor": .00005, "maxOutflow": .8, "gamma": 1.05,
                    "anchor": .04, "threshold": .004, "steps": 12}
ARMS = ("raw_retrieval", "raw_window_retrieval", "formed_retrieval",
        "formed_multiquery", "graph_expansion", "attention_diffusion")


def options(value):
    if not isinstance(value, dict) or set(value) - {"seedCount", "gatePower", "viewCharacters", "windowRadius", "includeQuerySeed", "normalizeCueSeeds", "querySeedWeight", "gateAffinity", "returnDiversity", "groundBySpeaker"}:
        raise Invalid("未知联想读取参数")
    result = {"seedCount": 3, "gatePower": 2., "viewCharacters": 512, "windowRadius": 2,
              "includeQuerySeed": False, "normalizeCueSeeds": False, "querySeedWeight": .5,
              "gateAffinity": "query", "returnDiversity": 0., "groundBySpeaker": False, **value}
    if result['gateAffinity'] not in ('query', 'maxCue'):
        raise Invalid('gateAffinity必须是query或maxCue')
    for key in ('includeQuerySeed', 'normalizeCueSeeds', 'groundBySpeaker'):
        if not isinstance(result[key], bool):
            raise Invalid(key+'必须是布尔值')
    integer(result["seedCount"], "seedCount", 1, 3)
    number(result['querySeedWeight'], 'querySeedWeight', 0, 1)
    number(result["gatePower"], "gatePower", 0, 8)
    number(result['returnDiversity'], 'returnDiversity', 0, 1)
    integer(result["viewCharacters"], "viewCharacters", 100, 1024)
    integer(result["windowRadius"], "windowRadius", 0, 4)
    return result


def fused_order(rankings, weights):
    """Weighted reciprocal-rank fusion, same query-only cues as graph grounding."""
    result = {}
    for ranking, weight in zip(rankings, weights):
        for rank, ident in enumerate(ranking, 1):
            result[ident] = result.get(ident, 0.) + weight / (60 + rank)
    return result


def gate_affinity(similarities, requests, mode):
    """A relevant aspect can open a path even when the whole query is diluted."""
    if mode == 'query':
        return similarities[0]
    active = [scores for scores, (_, weight) in zip(similarities, requests) if weight > 0]
    return {ident: max(scores[ident] for scores in active) for ident in similarities[0]}


def speaker_grounding(nodes, events, requests, windows):
    """Exact known speaker mentions only; aliases never imply identity equality."""
    known = set(event['speaker'] for event in events.values())
    actors = [{speaker for speaker in known if re.search(
        r'(?<![A-Za-z0-9_])'+re.escape(speaker)+r'(?![A-Za-z0-9_])', query)} for query, _ in requests]
    membership = {'node': {}, 'raw': {}, 'window': {}}
    for ident, node in nodes.items():
        speakers = {events[e['eventId']]['speaker'] for e in node['evidence'] if e['eventId'] in events}
        if node['type'] == 'PERSON' and node['label'] in known:
            speakers.add(node['label'])
        subject = nodes.get(node.get('subject'))
        if subject and subject['type'] == 'PERSON' and subject['label'] in known:
            speakers.add(subject['label'])
        membership['node'][ident] = speakers
    membership['raw'] = {ident: {event['speaker']} for ident, event in events.items()}
    membership['window'] = {ident: {events[i]['speaker'] for i in view['evidenceIds']} for ident, view in windows.items()}
    return actors, membership


def select_evidence(checked, collection, vectors, limit, characters, diversity, paths):
    """Shared budgeted MMR after unchanged acceptance; sigmoid is a scale, not truth."""
    pending = [item for item in checked if item['accepted']]
    selected, trace, remaining = [], [], characters
    while pending and len(selected) < limit:
        eligible = [item for item in pending if len(collection[item['id']]['label']) <= remaining]
        if not eligible:
            break
        def value(item):
            if not diversity:
                return item['rerankScore']
            vector = vectors[item['id']]
            norm = float(vector @ vector) ** .5
            redundancy = 0.
            for previous in selected:
                other = vectors[previous['id']]
                denominator = norm * float(other @ other) ** .5
                similarity = float(vector @ other)/denominator if denominator else 0.
                redundancy = max(redundancy, min(1., similarity))
            relevance = 1/(1+math.exp(-max(-30., min(30., item['rerankScore']))))
            return (1-diversity)*relevance-diversity*redundancy
        item = min(eligible, key=lambda row: (-value(row), row['id']))
        trace.append({'id': item['id'], 'returnSelectionScore': value(item)})
        selected.append({**collection[item['id']], **item, 'discoveryPath': paths.get(item['id'], [])})
        remaining -= len(collection[item['id']]['label'])
        pending.remove(item)
    return selected, characters-remaining, trace


class QueryAdjacency:
    """All arcs remain present; positive semantic gates never Top-K prune edges."""
    def __init__(self, graph, plan, config, affinity, power):
        self.adjacency = dynamics.arcs(graph, plan, config)
        self.nodes = {n["id"]: n for n in graph["nodes"]}
        self.affinity, self.power, self.sources = affinity, power, set()

    def get(self, source, default=None):
        self.sources.add(source)
        arcs = self.adjacency.get(source, [])
        if not self.power:
            return arcs
        result = []
        for arc in arcs:
            target = arc["target"]
            relevance = max(0., self.affinity.get(target, 0.))
            if self.nodes[target]["type"] != "MEMORY":
                # Do not destroy an alias/person bridge because the stable ID
                # alone has no lexical similarity to the natural query.
                relevance = max(relevance, self.affinity.get(source, 0.))
            gate = max(.02, min(1., .25 + relevance) ** self.power)
            result.append({**arc, "baseEffective": arc["effective"], "contextGate": gate,
                           "effective": arc["effective"] * gate})
        return result


def evidence_views(graph, events, characters):
    """Same finite, source/identity-only checking view for every memory arm."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    aliases = {}
    for edge in graph["edges"]:
        if edge["relation"] != "SIMILARITY":
            continue
        for entity, alias in [(edge["source"], edge["target"]), (edge["target"], edge["source"])]:
            if nodes[entity]["type"] == "PERSON" and nodes[alias]["type"] == "ALIAS":
                quotes = " / ".join(e["quote"] for e in edge["evidence"])
                aliases.setdefault(entity, []).append((nodes[alias]["seq"], nodes[alias]["label"], quotes))
    result = {}
    for ident, node in nodes.items():
        if node["type"] != "MEMORY":
            continue
        parts = [node["label"]]
        # An association is a context record, not an identity equality assertion.
        for _, label, quote in sorted(set(aliases.get(node["subject"], []))):
            parts.append("别名关联线索（不自动认定身份）：" + label + "；原话：" + quote)
        for citation in node["evidence"]:
            event = events[citation["eventId"]]
            parts.append(event["speaker"] + " 原话：" + citation["quote"])
        complete = "\n".join(parts)
        result[ident] = {"id": ident, "label": complete[:characters], "type": "MEMORY",
                         "kind": node["kind"], "status": node["status"], "stage": node["stage"],
                         "evidenceIds": sorted({e["eventId"] for e in node["evidence"]}),
                         "viewCharacterClipped": len(complete) > characters,
                         "sourceNodeId": ident}
    return result


def raw_views(rows, characters, radius=0):
    events = {r["id"]: r for r in rows}
    result = {}
    for position, row in enumerate(rows):
        # Anchor first prevents a long predecessor from erasing the indexed event.
        chosen = [row]
        reply = events.get(row["reply_to"])
        if radius and reply and reply["id"] != row["id"]:
            chosen.append(reply)
        if radius:
            chosen.extend(rows[max(0, position-radius):position+radius+1])
        unique = list({r["id"]: r for r in chosen}.values())
        label = "\n".join(r["speaker"] + " " + r["time"] + "：" + r["text"] for r in unique)
        ident = ("window:" if radius else "event:") + row["id"]
        result[ident] = {"id": ident, "label": label[:characters], "type": "RAW_WINDOW" if radius else "RAW_EVENT",
                         "status": "RAW", "anchorSeq": row["seq"], "evidenceIds": [r["id"] for r in unique],
                         "viewCharacterClipped": len(label) > characters}
    return result


def matrix_from_index(store, model, scope, kind, ids):
    rows = [r for r in store.db.execute("SELECT source_id,dimension,vector,truncated FROM semantic_vectors WHERE scope=? AND kind=? AND model=? ORDER BY source_seq",
                                       (scope, kind, model.fingerprint)) if r["source_id"] in ids]
    if len(rows) != len(ids):
        raise Invalid("读取向量与本次可见快照不一致")
    if not rows:
        return [], model.np.empty((0, 0), dtype=model.np.float32), {}
    if len({r["dimension"] for r in rows}) != 1 or any(len(r["vector"]) != 4*r["dimension"] for r in rows):
        raise Invalid("持久向量尺寸非法")
    matrix = model.np.stack([model.np.frombuffer(r["vector"], dtype='<f4') for r in rows])
    if not model.np.isfinite(matrix).all():
        raise Invalid("持久向量含非有限数值")
    return [r["source_id"] for r in rows], matrix, {r["source_id"]: bool(r["truncated"]) for r in rows}


def window_matrix(store, model, scope, views, recipe):
    store.db.execute("""CREATE TABLE IF NOT EXISTS associative_window_vectors(
      scope TEXT NOT NULL,anchor_seq INTEGER NOT NULL,model TEXT NOT NULL,recipe TEXT NOT NULL,
      body_hash TEXT NOT NULL,vector BLOB NOT NULL,truncated INTEGER NOT NULL,
      PRIMARY KEY(scope,anchor_seq,model,recipe,body_hash))""")
    cached = {(r["anchor_seq"], r["body_hash"]): r for r in store.db.execute(
        "SELECT * FROM associative_window_vectors WHERE scope=? AND model=? AND recipe=?", (scope, model.fingerprint, recipe))}
    vectors, clips, created = [], {}, 0
    with store.db:
        for ident, view in views.items():
            key = (view["anchorSeq"], digest(view["label"]))
            if key in cached:
                row = cached[key]
                vector, clipped = model.np.frombuffer(row["vector"], dtype='<f4'), bool(row["truncated"])
            else:
                array, flags = model.vectors([view["label"]])
                vector, clipped = model.np.asarray(array[0], dtype='<f4'), bool(flags[0])
                store.db.execute("INSERT INTO associative_window_vectors VALUES(?,?,?,?,?,?,?)",
                    (scope, view["anchorSeq"], model.fingerprint, recipe, key[1], vector.tobytes(), clipped))
                created += 1
            vectors.append(vector)
            clips[ident] = clipped
    return list(views), model.np.stack(vectors) if vectors else model.np.empty((0, 0)), clips, created


def compare_associative(store, payload, model, planner=None, check_cache=None, persist=True):
    started = time.perf_counter()
    settings = options(payload.get("associative", {}))
    requested = payload.get('arms', list(ARMS))
    if (not isinstance(requested, list) or not requested
            or any(not isinstance(name, str) or name not in ARMS for name in requested)
            or len(set(requested)) != len(requested)):
        raise Invalid("arms必须是无重复的已知比较系统数组")
    if 'seeds' in payload:
        raise Invalid("此比较只使用query-only种子，不接受手工节点id")
    history = payload.get('includeHistory', False)
    if not isinstance(history, bool) or history:
        raise Invalid("联想研究比较当前只支持includeHistory=false；历史对照使用原reader")
    scope = text(payload.get("scope"), "scope", 200)
    query = text(payload.get("query"), "query", 2000)
    episode = payload.get("episode")
    checks = integer(payload.get("checkBudget", 12), "checkBudget", 1, 200)
    limit = integer(payload.get("limit", 4), "limit", 1, 30)
    characters = integer(payload.get("characterBudget", 1600), "characterBudget", 100, 20000)
    min_score = number(payload.get("minScore", model.min_score), "minScore", -30, 30)
    acceptance = payload.get('acceptancePolicy', 'threshold')
    if acceptance not in ('threshold', 'rank-only'):
        raise Invalid('acceptancePolicy必须是threshold或rank-only')
    if type(persist) is not bool:
        raise Invalid('persist必须是显式布尔值')
    minimum = number(payload.get("seedMinimum", .35), "seedMinimum")
    supplied = payload.get('diffusion')
    if supplied is not None and not isinstance(supplied, dict):
        raise Invalid("diffusion必须是参数对象")
    config = dynamics.parameters({**DEFAULT_DYNAMICS, **(supplied or {})})
    plan, plan_meta = make_plan(query, payload.get("plan"), planner)
    index = SemanticIndex(store, model)
    index.require_complete(scope)
    store.db.execute("BEGIN")
    try:
        graph = store.graph(scope, episode)
        rows = [dict(r) for r in store.db.execute("""SELECT e.* FROM events e JOIN episodes p ON p.scope=e.scope AND p.id=e.episode
          WHERE e.scope=? AND (p.status IN ('CLOSED','CONSOLIDATED') OR e.episode=?) ORDER BY e.seq LIMIT 10001""", (scope, episode))]
        if len(rows) > 10000:
            raise Invalid("联想研究对照的上下文窗口上限10000事件；不代表大库实现")
        # A kept durable memory can originate in a still-SEALED episode with
        # other deferred memories. Fetch only its cited provenance; never make
        # that episode's remaining raw events eligible retrieval candidates.
        evidence_events = {r['id']: r for r in rows}
        citations = {e['eventId'] for n in graph['nodes'] if n['type'] == 'MEMORY' for e in n['evidence']}
        missing_sources = sorted(citations - set(evidence_events))
        if len(missing_sources) > 10000:
            raise Invalid('可见记忆的额外来源超过10000事件预算；不静默截断')
        for start in range(0, len(missing_sources), 200):
            chunk = missing_sources[start:start+200]
            placeholders = ','.join('?' for _ in chunk)
            for row in store.db.execute(f'SELECT * FROM events WHERE scope=? AND id IN ({placeholders})', (scope, *chunk)):
                evidence_events[row['id']] = dict(row)
        if citations - set(evidence_events):
            raise Invalid('可见记忆引用了缺失或跨scope原文；拒绝无来源读取')
        revision = store.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()
        if revision is None:
            raise Invalid("scope不存在")
        node_ids, node_matrix, node_clips = matrix_from_index(store, model, scope, 'node', {n['id'] for n in graph['nodes']})
        raw_ids, raw_matrix, raw_clips = matrix_from_index(store, model, scope, 'raw', {r['id'] for r in rows})
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    events, nodes = evidence_events, {n['id']: n for n in graph['nodes']}
    memory_views = evidence_views(graph, events, settings['viewCharacters'])
    memory_views = {i: v for i, v in memory_views.items() if v['status'] == 'CURRENT'}
    raw = raw_views(rows, settings['viewCharacters'])
    windows = raw_views(rows, settings['viewCharacters'], settings['windowRadius'])
    if 'raw_window_retrieval' in requested:
        window_ids, windows_matrix, window_clips, built = window_matrix(store, model, scope, windows,
            digest({'radius': settings['windowRadius'], 'characters': settings['viewCharacters'], 'recipe': 'anchor-first/reply/contiguous-v1'}))
    else:
        window_ids, windows_matrix, window_clips, built = [], model.np.empty((0, 0)), {}, 0
    requests = [(query, .5)] + [(c['text'], .5*c['weight']) for c in plan['cues'] if c['weight'] > 0]
    query_vectors, query_clips = model.vectors([q for q, _ in requests], query=True)
    query_vectors = model.np.asarray(query_vectors, dtype=model.np.float32)
    if (query_vectors.ndim != 2 or len(query_vectors) != len(requests)
            or len(query_clips) != len(requests) or not model.np.isfinite(query_vectors).all()
            or any(type(flag) is not bool for flag in query_clips)
            or (model.np.linalg.norm(query_vectors, axis=1) <= 0).any()
            or (node_ids and query_vectors.shape[1] != node_matrix.shape[1])
            or (raw_ids and query_vectors.shape[1] != raw_matrix.shape[1])
            or (window_ids and query_vectors.shape[1] != windows_matrix.shape[1])):
        raise Invalid("查询向量尺寸、数量或数值非法")
    rankings, similarities = {}, {}
    for name, ids, matrix in [('node', node_ids, node_matrix), ('raw', raw_ids, raw_matrix), ('window', window_ids, windows_matrix)]:
        values = [dict(zip(ids, [float(v) for v in matrix @ q])) if ids else {} for q in query_vectors]
        similarities[name] = values
        rankings[name] = [sorted(v, key=lambda i: (-v[i], i)) for v in values]
    speaker_trace = []
    if settings['groundBySpeaker']:
        actors, membership = speaker_grounding(nodes, events, requests, windows)
        for position, speakers in enumerate(actors):
            speaker_trace.append({'query': requests[position][0], 'explicitSpeakers': sorted(speakers)})
            if speakers:
                for kind in rankings:
                    rankings[kind][position] = [i for i in rankings[kind][position] if membership[kind][i] & speakers]
    seeds, grounding = {}, []
    seed_requests = list(enumerate([c for c in plan['cues'] if c['weight'] > 0], 1))
    if settings['includeQuerySeed']:
        # Defaults match the original-query / cue share available to multiquery
        # retrieval; explicit shares are recorded. Keep details lost in paraphrases.
        query_weight = settings['querySeedWeight']
        seed_requests = [(0, {'text': query, 'weight': query_weight})] + [
            (position, {**cue, 'weight': (1-query_weight)*cue['weight']}) for position, cue in seed_requests]
    for position, cue in seed_requests:
        if cue['weight'] <= 0:
            continue
        cue_seeds = {}
        exact = [i for i in node_ids if nodes[i]['status'] == 'CURRENT' and nodes[i]['label'].casefold() == cue['text'].casefold()
                 and (not settings['groundBySpeaker'] or i in rankings['node'][position])]
        eligible = exact[:1] if exact else [i for i in rankings['node'][position] if nodes[i]['status'] == 'CURRENT'][:settings['seedCount']]
        for ident in eligible:
            score = 1. if exact else similarities['node'][position][ident]
            accepted = score >= minimum
            grounding.append({'cue': cue, 'nodeId': ident, 'similarity': score, 'accepted': accepted,
                              'truncated': bool(node_clips.get(ident) or query_clips[position])})
            if accepted:
                cue_seeds[ident] = max(1e-6, score-minimum)**2
        if settings['normalizeCueSeeds'] and cue_seeds:
            # Plan weights allocate attention between questions/aspects. Cosine
            # confidence distributes a cue's own share rather than starving a
            # different aspect whose embeddings have lower absolute scores.
            cue_seeds = dynamics.normalize(cue_seeds)
        for ident, strength in cue_seeds.items():
            seeds[ident] = seeds.get(ident, 0.) + cue['weight']*strength
    seeds = dynamics.normalize(seeds) if seeds else {}
    weights = [w for _, w in requests]
    fused_node = fused_order([[i for i in ranking if i in memory_views] for ranking in rankings['node']], weights)
    fused_window = fused_order(rankings['window'], weights)
    cache = {} if check_cache is None else check_cache
    arms = {}
    graph_sources = set()
    for name in requested:
        clock, before = time.perf_counter(), dict(model.counts)
        outcome = {'state': {}, 'paths': {}, 'history': [], 'checkedArcs': 0, 'visitedNodes': 0}
        if name == 'raw_retrieval':
            collection = raw
            ordering = {'event:'+i: similarities['raw'][0][i] for i in rankings['raw'][0]}
            retrieval_clips = {'event:'+i: clipped or query_clips[0] for i, clipped in raw_clips.items()}
        elif name == 'raw_window_retrieval':
            collection, ordering = windows, fused_window
            retrieval_clips = {i: clipped or any(query_clips) for i, clipped in window_clips.items()}
        elif name == 'formed_retrieval':
            collection = memory_views
            ordering = {i: similarities['node'][0][i] for i in rankings['node'][0] if i in memory_views}
            retrieval_clips = {i: clipped or query_clips[0] for i, clipped in node_clips.items()}
        elif name == 'formed_multiquery':
            collection, ordering = memory_views, fused_node
            retrieval_clips = {i: clipped or any(query_clips) for i, clipped in node_clips.items()}
        else:
            retrieval_clips = {i: clipped or any(query_clips) for i, clipped in node_clips.items()}
            collection = memory_views
            affinity = gate_affinity(similarities['node'], requests, settings['gateAffinity'])
            adjacency = QueryAdjacency(graph, plan, config, affinity, settings['gatePower'])
            if seeds:
                operation = dynamics.diffuse if name == 'attention_diffusion' else dynamics.graph_expand
                outcome = operation({}, seeds, plan, config, adjacency=adjacency)
            graph_sources.update(adjacency.sources)
            ordering = {i: score for i, score in outcome['state'].items() if i in collection and
                        (name != 'attention_diffusion' or score >= config['threshold'])}
        candidates = sorted(ordering, key=lambda i: (-ordering[i], i))[:checks]
        missing = [i for i in candidates if (model.fingerprint, query, collection[i]['label']) not in cache]
        scores, flags = model.rerank(query, [collection[i]['label'] for i in missing])
        if len(scores)!=len(missing) or len(flags)!=len(missing):
            raise Invalid('联想检查返回数量与实际候选不一致')
        if any(isinstance(score,bool) or not isinstance(score,numbers.Real) or not math.isfinite(float(score)) for score in scores):
            raise Invalid('联想检查分数必须为有限数值')
        if any(type(flag) is not bool for flag in flags):
            raise Invalid('联想检查截断标记必须为布尔值')
        for ident, score, clipped in zip(missing, scores, flags):
            cache[(model.fingerprint, query, collection[ident]['label'])] = (score, clipped)
        checked = []
        for ident in candidates:
            score, clipped = cache[(model.fingerprint, query, collection[ident]['label'])]
            if (isinstance(score,bool) or not isinstance(score,numbers.Real)
                    or not math.isfinite(float(score)) or type(clipped) is not bool):
                raise Invalid('联想检查缓存含非法分数或截断标记')
            checked.append({'id': ident, 'selectionScore': ordering[ident], 'rerankScore': score,
                'truncated': bool(clipped or collection[ident]['viewCharacterClipped'] or retrieval_clips.get(ident)),
                'accepted': acceptance=='rank-only' or score >= min_score})
        if name == 'raw_retrieval':
            vectors = {'event:'+i: vector for i, vector in zip(raw_ids, raw_matrix)}
        elif name == 'raw_window_retrieval':
            vectors = dict(zip(window_ids, windows_matrix))
        else:
            vectors = dict(zip(node_ids, node_matrix))
        selected, used_characters, return_trace = select_evidence(checked, collection, vectors, limit,
            characters, settings['returnDiversity'], outcome['paths'])
        arms[name] = {'memories': selected, 'checked': checked, 'trace': outcome, 'characters': used_characters,
            'returnSelection': {'diversity': settings['returnDiversity'], 'trace': return_trace},
            'diagnostics': {'candidateCount': len(candidates), 'logicalChecks': len(candidates), 'physicalChecks': len(missing),
                'seconds': round(time.perf_counter()-clock, 4), 'modelCalls': {k: v-before.get(k, 0) for k, v in model.counts.items()}}}
    result = {'scope': scope, 'episode': episode, 'scopeRevision': revision[0], 'query': query,
        'model': model.name, 'modelFingerprint': model.fingerprint, 'plan': plan, 'planMetadata': plan_meta,
        'seeds': seeds, 'grounding': grounding, 'speakerGrounding': speaker_trace,
        'arms': arms, 'graphHash': digest(graph), 'graphSnapshot': graph,
        'parameters': {'associative': settings, 'diffusion': config, 'checkBudget': checks, 'limit': limit,
                        'characterBudget': characters, 'minScore': min_score, 'seedMinimum': minimum,
                        'acceptancePolicy': acceptance,
                       'arms': requested},
        'sharedWork': {'nodeVectorScores': len(node_ids)*len(requests), 'rawVectorScores': len(raw_ids)*len(requests),
                       'windowVectorScores': len(window_ids)*len(requests), 'newWindowVectors': built,
                       'graphNodesPrefetched': len(nodes), 'graphEdgesPrefetched': len(graph['edges']),
                        'sourcesExpanded': len(graph_sources), 'additionalCitationEvents': len(missing_sources)},
        'seconds': round(time.perf_counter()-started, 3),
        'interpretation': 'Opt-in complete-small-graph research: six arms share query-only cues and finite evidence views. Window RAG is the strong raw baseline. Positive semantic gates retain all arcs; checks never rescue non-emerged candidates. Shared caches/graph prefetch are disclosed; not a large-library or independent cold-latency claim.'}
    if persist:
        result['recallId'] = store.save_recall(scope, result)
    return result
