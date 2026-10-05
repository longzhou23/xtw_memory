"""Persistent FP32 embeddings, exact blockwise search, and lazy complete adjacency.

No approximate nearest-neighbour recall claim: vectors are scanned, not re-embedded.
Graph edges are never Top-K pruned; resource exhaustion raises instead of truncating.
"""
import time

from . import dynamics
from .contracts import Invalid, integer
from .store import digest


class SemanticIndex:
    def __init__(self, store, model):
        if not hasattr(model, "vectors"):
            raise Invalid("持久语义索引需要向量模型；词面诊断不能冒充语义索引")
        import numpy as np
        self.np, self.store, self.model = np, store, model
        self.fingerprint = model.fingerprint
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS semantic_vectors(scope TEXT NOT NULL, kind TEXT NOT NULL,
          source_seq INTEGER NOT NULL, source_id TEXT NOT NULL, model TEXT NOT NULL, body_hash TEXT NOT NULL,
          dimension INTEGER NOT NULL, vector BLOB NOT NULL, truncated INTEGER NOT NULL,
          PRIMARY KEY(scope,kind,source_seq,model));
        CREATE TABLE IF NOT EXISTS semantic_heads(scope TEXT NOT NULL,kind TEXT NOT NULL,model TEXT NOT NULL,
          last_seq INTEGER NOT NULL, PRIMARY KEY(scope,kind,model));
        """)

    def head(self, scope, kind):
        row = self.store.db.execute("SELECT last_seq FROM semantic_heads WHERE scope=? AND kind=? AND model=?", (scope, kind, self.fingerprint)).fetchone()
        return row[0] if row else 0

    def status(self, scope):
        result = {"modelFingerprint": self.fingerprint, "scopes": scope, "search": "exact-blockwise-FP32 (not ANN)"}
        for kind, table in [("node", "nodes"), ("raw", "events")]:
            maximum = self.store.db.execute(f"SELECT COALESCE(MAX(seq),0) FROM {table} WHERE scope=?", (scope,)).fetchone()[0]
            count = self.store.db.execute("SELECT COUNT(*) FROM semantic_vectors WHERE scope=? AND kind=? AND model=?", (scope, kind, self.fingerprint)).fetchone()[0]
            result[kind] = {"lastSeq": self.head(scope, kind), "maxSeq": maximum, "vectors": count,
                            "complete": self.head(scope, kind) >= maximum}
        return result

    def sync(self, scope, kinds=("node", "raw"), max_items=None, batch_size=48):
        integer(batch_size, "embedding batch size", 1, 256)
        if max_items is not None:
            integer(max_items, "max index items", 1, 10**9)
        started, created = time.perf_counter(), 0
        for kind in kinds:
            if kind not in ["node", "raw"]:
                raise Invalid("索引类型只能是node/raw")
            table, field = ("nodes", "label") if kind == "node" else ("events", "text")
            while max_items is None or created < max_items:
                size = batch_size if max_items is None else min(batch_size, max_items-created)
                rows = list(self.store.db.execute(f"SELECT seq,id,{field} AS body FROM {table} WHERE scope=? AND seq>? ORDER BY seq LIMIT ?", (scope, self.head(scope, kind), size)))
                if not rows:
                    break
                vectors, clips = self.model.vectors([r["body"] for r in rows])
                vectors = self.np.asarray(vectors, dtype="<f4")
                if vectors.ndim != 2 or len(vectors) != len(rows) or len(clips) != len(rows) or not self.np.isfinite(vectors).all():
                    raise Invalid("索引模型返回了非法向量")
                norms = self.np.linalg.norm(vectors, axis=1)
                if (norms <= 0).any():
                    raise Invalid("不能索引零向量")
                vectors = vectors / norms[:, None]
                with self.store.db:
                    self.store.db.executemany("INSERT OR IGNORE INTO semantic_vectors VALUES(?,?,?,?,?,?,?,?,?)", [
                        (scope, kind, r["seq"], r["id"], self.fingerprint, digest(r["body"]), vectors.shape[1],
                         v.astype("<f4").tobytes(), bool(clip)) for r, v, clip in zip(rows, vectors, clips)])
                    self.store.db.execute("INSERT INTO semantic_heads VALUES(?,?,?,?) ON CONFLICT(scope,kind,model) DO UPDATE SET last_seq=MAX(last_seq,excluded.last_seq)", (scope, kind, self.fingerprint, rows[-1]["seq"]))
                created += len(rows)
        return {"created": created, "seconds": round(time.perf_counter()-started, 4), "status": self.status(scope)}

    def require_complete(self, scope, kinds=("node", "raw")):
        status = self.status(scope)
        if any(not status[k]["complete"] for k in kinds):
            raise Invalid("语义索引尚未完成或落后于写入；先运行index命令，可断点续建")
        return status

    def search(self, scope, query, kind="node", limit=24, episode=None, memories_only=False,
               current_only=True, block_size=2048, include_unresolved=False):
        integer(limit, "index result limit", 1, 200)
        integer(block_size, "index block size", 1, 8192)
        if kind not in ["node", "raw"]:
            raise Invalid("索引类型只能是node/raw")
        self.require_complete(scope, (kind,))
        q, qc = self.model.vectors([query], query=True)
        query_vector = self.np.asarray(q[0], dtype="<f4")
        norm = float(self.np.linalg.norm(query_vector))
        if norm <= 0 or not self.np.isfinite(query_vector).all():
            raise Invalid("查询向量不合法")
        query_vector /= norm
        if not isinstance(include_unresolved,bool):raise Invalid("未决检索开关必须是bool")
        if kind == "node":
            stages="n.stage IN ('LONG_TERM','UNRESOLVED')" if include_unresolved else "n.stage='LONG_TERM'"
            sql = f"""SELECT v.source_id,v.dimension,v.vector,v.truncated FROM semantic_vectors v
              JOIN nodes n ON n.seq=v.source_seq AND n.scope=v.scope
              WHERE v.scope=? AND v.kind='node' AND v.model=? AND ({stages} OR (n.episode=? AND n.stage='TEMPORARY'))"""
            if memories_only:
                sql += " AND n.type='MEMORY'"
            if current_only:
                sql += " AND n.status='CURRENT'"
        else:
            sql = """SELECT v.source_id,v.dimension,v.vector,v.truncated FROM semantic_vectors v
              JOIN events e ON e.seq=v.source_seq AND e.scope=v.scope
              JOIN episodes p ON p.scope=e.scope AND p.id=e.episode
              WHERE v.scope=? AND v.kind='raw' AND v.model=? AND (p.status IN ('CLOSED','CONSOLIDATED') OR e.episode=?)"""
        cursor = self.store.db.execute(sql + " ORDER BY v.source_seq", (scope, self.fingerprint, episode))
        best, scanned = [], 0
        while True:
            rows = cursor.fetchmany(block_size)
            if not rows:
                break
            if any(r["dimension"] != len(query_vector) or len(r["vector"]) != 4*len(query_vector) for r in rows):
                raise Invalid("向量维度或存储长度不匹配，拒绝使用索引")
            matrix = self.np.stack([self.np.frombuffer(r["vector"], dtype="<f4") for r in rows])
            scores = matrix @ query_vector
            if not self.np.isfinite(scores).all():
                raise Invalid("持久索引含非法向量")
            candidates = [{"id": r["source_id"], "score": float(score), "truncated": bool(r["truncated"]) or qc[0]}
                          for r, score in zip(rows, scores)]
            best = sorted(best+candidates, key=lambda item: (-item["score"], item["id"]))[:limit]
            scanned += len(rows)
        return best, {"vectorsScanned": scanned, "blockSize": block_size,
                      "indexFingerprint": self.fingerprint, "approximate": False}


class LazyAdjacency:
    """Load every visible outgoing arc of each actually expanded source on demand."""
    def __init__(self, store, scope, episode, plan, config, seeds, max_nodes=20000, max_edges=100000):
        integer(max_nodes, "graph node budget", 1, 10**6)
        integer(max_edges, "graph edge budget", 1, 10**7)
        self.store, self.scope, self.episode = store, scope, episode
        self.plan, self.config = plan, config
        self.nodes = store.visible_nodes(scope, seeds, episode, mentions=False)
        if set(self.nodes) != set(seeds):
            raise Invalid("种子不在本次可见图内")
        if len(self.nodes) > max_nodes:
            raise Invalid("种子数量超过图节点预算")
        self.edges, self.cache = {}, {}
        self.max_nodes, self.max_edges = max_nodes, max_edges
        self.raw_edge_reads = 0

    def get(self, source, default=None):
        if source not in self.cache:
            records = self.store.edges_from(self.scope, [source], record_budget=self.max_edges, episode=self.episode)
            self.raw_edge_reads += sum(len(e["recordIds"]) for e in records)
            candidate = []
            for edge in records:
                if self.plan["relations"].get(edge["relation"], 0) <= 0:
                    continue
                if edge["relation"] == "CAUSAL":
                    if source == edge["source"] and self.plan["direction"] == "reverse":
                        continue
                    if source == edge["target"] and self.plan["direction"] == "forward":
                        continue
                candidate.append(edge)
            ids = {i for e in candidate for i in [e["source"], e["target"]]}
            visible = self.store.visible_nodes(self.scope, ids, self.episode, mentions=False)
            accepted = [e for e in candidate if e["source"] in visible and e["target"] in visible]
            new_nodes = {i for e in accepted for i in [e["source"], e["target"]]}
            if len(set(self.nodes)|new_nodes) > self.max_nodes or len(set(self.edges)|{e["id"] for e in accepted}) > self.max_edges:
                raise Invalid("本次实际传播超过图访问预算；拒绝截断邻边，请降低传播步数或显式提高预算")
            self.nodes.update({i: visible[i] for i in new_nodes})
            self.edges.update({e["id"]: e for e in accepted})
            self.cache[source] = dynamics.arcs({"edges": accepted}, self.plan, self.config).get(source, [])
        return self.cache.get(source, default)

    def snapshot(self):
        return {"nodes": sorted(self.nodes.values(), key=lambda n: n["seq"]),
                "edges": sorted(self.edges.values(), key=lambda e: e["id"])}

    def diagnostics(self):
        return {"mode": "lazy-complete-outgoing; no Top-K edge truncation", "sourcesExpanded": len(self.cache),
                "nodesLoaded": len(self.nodes), "edgesLoaded": len(self.edges), "rawEdgeReads": self.raw_edge_reads,
                "nodeBudget": self.max_nodes, "edgeBudget": self.max_edges}
