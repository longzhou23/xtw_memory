"""Immutable events and memories, explicit revisions, atomic checkpoint commits."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .contracts import Invalid, integer, text, validate_write, WRITE_SCHEMA
from .providers import WRITE_PROMPT


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class RejectedWrite(Invalid):
    """Only structural/source validation failures are eligible for model correction."""
    def __init__(self, message, run_id, draft, revision):
        super().__init__(message)
        self.run_id, self.draft, self.revision = run_id, draft, revision


class Store:
    def __init__(self, path, limits=None):
        self.limits = {'global_working_bytes':360000,'per_input_bytes':180000,'per_output_bytes':64000}
        if limits is not None:
            if set(limits) != set(self.limits):
                raise Invalid('limits须完整声明global_working_bytes/per_input_bytes/per_output_bytes')
            self.limits = dict(limits)
        for key,value in self.limits.items():
            integer(value,key,1,100000000)
        self.path = str(path)
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        existing = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if existing:
            identity = self.db.execute("PRAGMA application_id").fetchone()[0]
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if identity != 1129467223 or version != 2:
                self.db.close()
                raise Invalid('未知数据库schema；只使用新CRMW实验库，不迁移旧库')
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS scopes(id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS episodes(scope TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'OPEN', lifecycle TEXT NOT NULL DEFAULT 'legacy', PRIMARY KEY(scope,id), FOREIGN KEY(scope) REFERENCES scopes(id));
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, scope TEXT NOT NULL, id TEXT NOT NULL,
          episode TEXT NOT NULL, speaker TEXT NOT NULL, time TEXT NOT NULL, text TEXT NOT NULL,
          reply_to TEXT, display_name TEXT, role TEXT NOT NULL DEFAULT 'unknown', media TEXT NOT NULL DEFAULT 'none', processed INTEGER NOT NULL DEFAULT 0, UNIQUE(scope,id),
          FOREIGN KEY(scope,episode) REFERENCES episodes(scope,id));
        CREATE TABLE IF NOT EXISTS nodes(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, scope TEXT NOT NULL,
          episode TEXT NOT NULL, stage TEXT NOT NULL, type TEXT NOT NULL, kind TEXT NOT NULL,
          label TEXT NOT NULL, subject TEXT, status TEXT NOT NULL, evidence TEXT NOT NULL,
          used TEXT NOT NULL, run_id TEXT NOT NULL, speaker_id TEXT, FOREIGN KEY(scope,episode) REFERENCES episodes(scope,id));
        CREATE TABLE IF NOT EXISTS edges(id TEXT PRIMARY KEY, scope TEXT NOT NULL, source TEXT NOT NULL,
          target TEXT NOT NULL, relation TEXT NOT NULL, strength REAL NOT NULL, evidence TEXT NOT NULL,
          rationale TEXT NOT NULL, run_id TEXT NOT NULL,
          FOREIGN KEY(source) REFERENCES nodes(id), FOREIGN KEY(target) REFERENCES nodes(id));
        CREATE TABLE IF NOT EXISTS revisions(old_id TEXT PRIMARY KEY, new_id TEXT NOT NULL, run_id TEXT NOT NULL,
          FOREIGN KEY(old_id) REFERENCES nodes(id), FOREIGN KEY(new_id) REFERENCES nodes(id));
        CREATE TABLE IF NOT EXISTS writes(id TEXT PRIMARY KEY, scope TEXT NOT NULL, episode TEXT NOT NULL,
          status TEXT NOT NULL, input TEXT NOT NULL, output TEXT, metadata TEXT NOT NULL, error TEXT);
        CREATE TABLE IF NOT EXISTS recalls(id TEXT PRIMARY KEY, scope TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entity_mentions(node_id TEXT NOT NULL, scope TEXT NOT NULL, episode TEXT NOT NULL,
          run_id TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(node_id,run_id),
          FOREIGN KEY(node_id) REFERENCES nodes(id), FOREIGN KEY(scope,episode) REFERENCES episodes(scope,id));
        CREATE TABLE IF NOT EXISTS consolidations(write_id TEXT PRIMARY KEY, scope TEXT NOT NULL,
          episode TEXT NOT NULL, status TEXT NOT NULL, decisions TEXT,
          FOREIGN KEY(write_id) REFERENCES writes(id));
        CREATE TABLE IF NOT EXISTS edge_publications(edge_id TEXT NOT NULL, write_id TEXT NOT NULL,
          PRIMARY KEY(edge_id,write_id), FOREIGN KEY(edge_id) REFERENCES edges(id),
          FOREIGN KEY(write_id) REFERENCES consolidations(write_id));
        CREATE INDEX IF NOT EXISTS event_scope ON events(scope,episode,processed,seq);
        CREATE INDEX IF NOT EXISTS node_scope ON nodes(scope,stage,episode,status);
        CREATE INDEX IF NOT EXISTS event_order ON events(scope,seq);
        CREATE INDEX IF NOT EXISTS edge_source ON edges(scope,source);
        CREATE INDEX IF NOT EXISTS edge_target ON edges(scope,target);
        CREATE INDEX IF NOT EXISTS mention_node ON entity_mentions(scope,node_id);
        """)
        self.db.execute("CREATE TABLE IF NOT EXISTS crmw_settings(id INTEGER PRIMARY KEY, limits TEXT NOT NULL)")
        settings = self.db.execute('SELECT limits FROM crmw_settings WHERE id=1').fetchone()
        if settings and settings[0] != encode(self.limits):
            self.db.close()
            raise Invalid('重启预算与新实验库冻结设置不一致')
        self.db.execute('INSERT OR IGNORE INTO crmw_settings VALUES(1,?)',(encode(self.limits),))
        self.db.execute("PRAGMA application_id=1129467223")
        self.db.execute("PRAGMA user_version=2")
        self.db.execute("CREATE TABLE IF NOT EXISTS episode_final_sources(node_id TEXT PRIMARY KEY, body TEXT NOT NULL, run_id TEXT NOT NULL, FOREIGN KEY(node_id) REFERENCES nodes(id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS episode_final_formed_with(source TEXT NOT NULL, target TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY(source,target), FOREIGN KEY(source) REFERENCES nodes(id))")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS node_speaker ON nodes(scope,speaker_id) WHERE speaker_id IS NOT NULL")
        from .episode_runtime import install
        install(self)
        self.db.commit()

    def check_context_budget(self, candidate_context=None, replacing=None, pending_input=None):
        working = 0
        for row in self.db.execute('SELECT scope,episode,context FROM episode_contexts'):
            if replacing == (row['scope'],row['episode']):
                continue
            status = self._episode(row['scope'],row['episode'])['status']
            if status == 'OPEN':
                working += len(row['context'].encode())
        if candidate_context is not None:
            working += len(encode(candidate_context).encode())
        working += sum(len(row[0].encode()) for row in self.db.execute("SELECT input FROM writes WHERE status='PENDING'"))
        if pending_input is not None:
            working += len(encode(pending_input).encode())
        if working > self.limits['global_working_bytes']:
            raise Invalid('跨Episode工作上下文及在途输入超过global_working_bytes；不静默挤出或截断')

    def close(self):
        self.db.close()

    def _episode(self, scope, episode):
        row = self.db.execute("SELECT * FROM episodes WHERE scope=? AND id=?", (scope, episode)).fetchone()
        if row is None:
            raise Invalid("话题不存在")
        return dict(row)

    def create_episode(self, scope, episode, title, lifecycle=None, capacity=None, eviction_batch=None):
        for key, value in [("scope", scope), ("episode", episode), ("title", title)]:
            text(value, key, 200)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO scopes(id) VALUES(?)", (scope,))
            prior = self.db.execute("SELECT title,lifecycle FROM episodes WHERE scope=? AND id=?", (scope, episode)).fetchone()
            if prior and prior[0] != title:
                raise Invalid("同一话题id已有不同标题")
            policy = lifecycle or (prior[1] if prior else 'legacy')
            if policy not in ('legacy', 'consolidate', 'episode') or (prior and prior[1] != policy):
                raise Invalid('话题生命周期不可改变；选择episode或旧实验legacy/consolidate')
            self.db.execute("INSERT OR IGNORE INTO episodes(scope,id,title,lifecycle) VALUES(?,?,?,?)", (scope, episode, title, policy))
            if policy == 'episode':
                from .episode_runtime import configure
                old_context = self.db.execute('SELECT capacity,eviction_batch FROM episode_contexts WHERE scope=? AND episode=?',(scope,episode)).fetchone()
                configure(self, scope, episode,
                          capacity if capacity is not None else (old_context[0] if old_context else 6),
                          eviction_batch if eviction_batch is not None else (old_context[1] if old_context else 1))
        return self._episode(scope, episode)

    def ingest(self, scope, episode, events):
        if not isinstance(events, list):
            raise Invalid("events 必须是事件数组")
        integer(len(events), "事件数", 1, 80)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            ep = self._episode(scope, episode)
            if ep['lifecycle'] == 'episode':
                raise Invalid('Episode-scoped接收请使用advance_episode，不能绕过独立FIFO直接批写')
            inserted = 0
            for event in events:
                if not isinstance(event, dict):
                    raise Invalid("事件必须是对象")
                values = [text(event.get(key), key, 12000 if key == "text" else 200) for key in ["id", "speaker", "time", "text"]]
                try:
                    timestamp = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        raise ValueError()
                except ValueError as error:
                    raise Invalid("time 必须是含时区的ISO时间") from error
                reply = event.get("replyTo")
                if reply is not None:
                    text(reply, "replyTo", 200)
                    if not self.db.execute("SELECT 1 FROM events WHERE scope=? AND id=?", (scope, reply)).fetchone():
                        raise Invalid("replyTo 必须指向同scope已接收事件")
                prior = self.db.execute("SELECT episode,id,speaker,time,text,reply_to FROM events WHERE scope=? AND id=?", (scope, event["id"])).fetchone()
                if prior:
                    if tuple(prior) != (episode, *values, reply):
                        raise Invalid("事件id已存在但内容不同")
                    continue
                if ep["status"] != "OPEN":
                    raise Invalid("话题已关闭")
                last = self.db.execute("SELECT time FROM events WHERE scope=? AND episode=? ORDER BY seq DESC LIMIT 1", (scope, episode)).fetchone()
                if last and timestamp < datetime.fromisoformat(last[0].replace("Z", "+00:00")):
                    raise Invalid("研究回放要求同话题按时间顺序写入")
                self.db.execute("INSERT INTO events(scope,episode,id,speaker,time,text,reply_to) VALUES(?,?,?,?,?,?,?)", (scope, episode, *values, reply))
                inserted += 1
            if inserted:
                self.db.execute("UPDATE scopes SET revision=revision+1 WHERE id=?", (scope,))
        return {"inserted": inserted, "duplicates": len(events) - inserted}

    def node(self, row):
        value = dict(row)
        value["evidence"] = json.loads(value["evidence"])
        value["usedMemoryIds"] = json.loads(value.pop("used"))
        value["speakerId"] = value.pop("speaker_id", None)
        provenance = self.db.execute('SELECT body FROM episode_final_sources WHERE node_id=?',(value['id'],)).fetchone()
        if provenance:
            value['provenance'] = json.loads(provenance[0])
        return value

    def visible_nodes(self, scope, ids, episode=None, mentions=True):
        """Targeted visibility/provenance reads; never enumerate the entire scope."""
        result = {}
        ids = sorted(set(ids))
        for start in range(0, len(ids), 200):
            chunk = ids[start:start+200]
            placeholders = ",".join("?" for _ in chunk)
            for row in self.db.execute(f"SELECT * FROM nodes WHERE scope=? AND id IN ({placeholders}) AND (stage='LONG_TERM' OR (episode=? AND stage='TEMPORARY'))", (scope, *chunk, episode)):
                result[row["id"]] = self.node(row)
            if mentions:
                for row in self.db.execute(f"""SELECT m.node_id,m.evidence FROM entity_mentions m
                  JOIN episodes ep ON ep.scope=m.scope AND ep.id=m.episode
                  WHERE m.scope=? AND m.node_id IN ({placeholders}) AND ((ep.lifecycle='legacy' AND ep.status='CLOSED') OR m.episode=?
                    OR m.run_id IN (SELECT write_id FROM consolidations WHERE status='COMMITTED'))""", (scope, *chunk, episode)):
                    if row["node_id"] in result:
                        node = result[row["node_id"]]
                        node["evidence"].extend(e for e in json.loads(row["evidence"]) if e not in node["evidence"])
        return result

    @staticmethod
    def combine_edges(rows):
        combined = {}
        for row in sorted(rows, key=lambda r: r["id"]):
            edge = dict(row)
            if isinstance(edge["evidence"], str):
                edge["evidence"] = json.loads(edge["evidence"])
            endpoints = (edge["source"], edge["target"])
            if edge["relation"] != "CAUSAL":
                endpoints = tuple(sorted(endpoints))
            key = (*endpoints, edge["relation"])
            if key not in combined:
                edge["recordIds"] = [edge["id"]]
                combined[key] = edge
            else:
                existing = combined[key]
                existing["strength"] = max(existing["strength"], edge["strength"])
                existing["recordIds"].append(edge["id"])
                existing["evidence"].extend(e for e in edge["evidence"] if e not in existing["evidence"])
        return list(combined.values())

    def edges_from(self, scope, ids, within=False, record_budget=None, episode=None):
        """Filter owning writes/episodes before merging duplicate association evidence."""
        seen = {}
        ids = sorted(set(ids))
        for start in range(0, len(ids), 100):
            chunk = ids[start:start+100]
            placeholders = ",".join("?" for _ in chunk)
            for column in ["source", "target"]:
                sql = f"""SELECT e.* FROM edges e
                  JOIN writes w ON w.id=e.run_id AND w.scope=e.scope
                  JOIN episodes p ON p.scope=w.scope AND p.id=w.episode
                  WHERE e.scope=? AND e.{column} IN ({placeholders})
                   AND w.status='COMMITTED' AND ((p.lifecycle='legacy' AND p.status='CLOSED') OR w.episode=?
                     OR w.id IN (SELECT write_id FROM consolidations WHERE status='COMMITTED')
                     OR e.id IN (SELECT pub.edge_id FROM edge_publications pub JOIN consolidations c
                       ON c.write_id=pub.write_id WHERE c.status='COMMITTED'))"""
                params = [scope, *chunk, episode]
                if within:
                    other = "target" if column == "source" else "source"
                    sql += f" AND e.{other} IN ({','.join('?' for _ in ids)})"
                    params.extend(ids)
                for row in self.db.execute(sql, params):
                    seen[row["id"]] = row
                    if record_budget is not None and len(seen) > record_budget:
                        raise Invalid("邻接记录读取超过预算，拒绝裁掉出边；请显式提高图预算")
        return self.combine_edges(seen.values())

    def graph(self, scope, episode=None):
        if episode is not None:
            self._episode(scope, episode)
        nodes = [self.node(row) for row in self.db.execute(
            "SELECT * FROM nodes WHERE scope=? AND (stage='LONG_TERM' OR (episode=? AND stage='TEMPORARY')) ORDER BY seq LIMIT 5001", (scope, episode))]
        if len(nodes) > 5000:
            raise Invalid("研究版限制5000个可见认知节点；不截断图，请缩小scope")
        ids = {node["id"] for node in nodes}
        by_id = {node["id"]: node for node in nodes}
        for row in self.db.execute("""SELECT m.node_id,m.evidence FROM entity_mentions m
          JOIN episodes ep ON ep.scope=m.scope AND ep.id=m.episode
           WHERE m.scope=? AND ((ep.lifecycle='legacy' AND ep.status='CLOSED') OR m.episode=?
             OR m.run_id IN (SELECT write_id FROM consolidations WHERE status='COMMITTED'))""", (scope, episode)):
            # Only visible mentions may augment provenance of a shared identity.
            if row["node_id"] in ids:
                node = by_id[row["node_id"]]
                node["evidence"].extend(e for e in json.loads(row["evidence"]) if e not in node["evidence"])
        edges = [e for e in self.edges_from(scope, ids, episode=episode) if e["source"] in ids and e["target"] in ids]
        return {"nodes": nodes, "edges": edges}

    def prepare(self, scope, episode, memory_ids=(), context_ids=()):
        ep = self._episode(scope, episode)
        if ep["status"] != "OPEN":
            raise Invalid("已关闭的话题不能生成检查点")
        pending = [dict(row) for row in self.db.execute("SELECT * FROM events WHERE scope=? AND episode=? AND processed=0 ORDER BY seq LIMIT 81", (scope, episode))]
        if not pending:
            raise Invalid("没有尚未整理的事件")
        integer(len(pending), "本批待整理事件", 1, 80)
        context = [dict(row) for row in self.db.execute("SELECT * FROM events WHERE scope=? AND episode=? AND processed=1 ORDER BY seq DESC LIMIT 6", (scope, episode))][::-1]
        if not isinstance(context_ids, (list, tuple)) or len(context_ids) > 6 or any(not isinstance(i, str) for i in context_ids) or len(set(context_ids)) != len(context_ids):
            raise Invalid("contextIds必须是至多6个无重复事件id")
        for ident in context_ids:
            row = self.db.execute("""SELECT e.* FROM events e JOIN episodes p ON p.scope=e.scope AND p.id=e.episode
              WHERE e.scope=? AND e.id=? AND e.processed=1 AND (p.status IN ('CLOSED','CONSOLIDATED') OR e.episode=?) AND e.seq<?""", (scope, ident, episode, pending[0]["seq"])).fetchone()
            if row is None:
                raise Invalid("contextIds只能注入已整理、已可见且早于本批的同scope事件")
            if ident not in {e["id"] for e in context}:
                context.append(dict(row))
        context = sorted(context, key=lambda e: e["seq"])[-6:]
        chosen = {row[0] for row in self.db.execute("SELECT id FROM nodes WHERE scope=? AND episode=? AND status='CURRENT' LIMIT 161", (scope, episode))}
        speakers = {event["speaker"] for event in pending + context}
        # Identity-only context, not automatic injection of all that person's memories.
        for speaker in speakers:
            chosen.update(row[0] for row in self.db.execute("SELECT id FROM nodes WHERE scope=? AND speaker_id=? AND (stage='LONG_TERM' OR episode=?)", (scope, speaker, episode)))
        if (not isinstance(memory_ids, (list, tuple)) or any(not isinstance(ident, str) for ident in memory_ids)
                or len(set(memory_ids)) != len(memory_ids)):
            raise Invalid("memoryIds 必须是无重复id的数组")
        available = self.visible_nodes(scope, memory_ids, episode, mentions=False)
        for ident in memory_ids:
            if ident not in available or available[ident]["type"] != "MEMORY":
                raise Invalid("只能注入当前scope可见的旧记忆")
            chosen.add(ident)
            chosen.add(available[ident]["subject"])
        if len(chosen) > 160:
            raise Invalid("当前检查点超过160个背景节点；请关闭话题，使用新话题和显式长期记忆注入")
        known = sorted(self.visible_nodes(scope, chosen, episode, mentions=False).values(), key=lambda n: n["seq"])
        bundle = {"episode": ep, "events": pending, "contextEvents": context,
                  "knownNodes": known, "knownAssociations": self.edges_from(scope, chosen, within=True, episode=episode),
                  "scopeRevision": self.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()[0]}
        if len(encode(bundle)) > 100000:
            raise Invalid("检查点输入超过100000字符，请减小事件批次")
        return bundle

    def checkpoint(self, scope, episode, model=None, draft=None, memory_ids=(), validation_retries=1, context_ids=()):
        if self._episode(scope,episode)['lifecycle'] == 'episode':
            raise Invalid('Episode临时检查点只在FIFO挤出时由advance_episode产生，不能手工批写')
        integer(validation_retries, "validation_retries", 0, 2)
        repair = None
        retries = validation_retries if draft is None and model is not None else 0
        for attempt in range(retries + 1):
            try:
                return self._checkpoint_once(scope, episode, model, draft, memory_ids, repair, context_ids)
            except RejectedWrite as error:
                if attempt == retries:
                    raise
                repair = error

    def _checkpoint_once(self, scope, episode, model, draft, memory_ids, repair, context_ids):
        # Snapshot reads must be mutually consistent; model work is outside the transaction.
        self.db.execute("BEGIN")
        try:
            bundle = self.prepare(scope, episode, memory_ids, context_ids)
            if repair:
                if bundle["scopeRevision"] != repair.revision:
                    raise Invalid("校验重试前scope已变化，停止自动修复；请重新生成检查点")
                bundle["validationRepair"] = {"previousWriteId": repair.run_id,
                                              "error": str(repair), "rejectedOutput": repair.draft}
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        run_id = "write_" + uuid.uuid4().hex
        metadata = {"provider": "reviewed-draft" if draft is not None else getattr(model, "name", "missing"),
                    "inputHash": digest(bundle), "promptHash": digest(WRITE_PROMPT), "schemaHash": digest(WRITE_SCHEMA)}
        with self.db:
            self.db.execute("INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)", (run_id, scope, episode, "PENDING", encode(bundle), None, encode(metadata), None))
        try:
            if draft is None:
                if model is None:
                    raise Invalid("请选择真实writer或显式提供人工草稿")
                draft, metrics = model.generate(WRITE_PROMPT, bundle, WRITE_SCHEMA)
                metadata.update(metrics)
            try:
                validate_write(draft, bundle)
                if bundle['episode'].get('lifecycle') == 'consolidate':
                    durable = {n['id'] for n in bundle['knownNodes'] if n['stage'] == 'LONG_TERM'}
                    if any(durable.intersection(m['supersedes']) for m in draft['memories']):
                        raise Invalid('临时检查点不能替代持久记忆；先记录带来源的新状态，巩固时再更正')
            except Invalid as error:
                raise RejectedWrite(str(error), run_id, draft, bundle["scopeRevision"]) from error
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                revision = self.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()[0]
                if revision != bundle["scopeRevision"] or self._episode(scope, episode)["status"] != "OPEN":
                    raise Invalid("模型调用期间scope已变化，拒绝过期检查点；请重试")
                mapping = {node["id"]: node["id"] for node in bundle["knownNodes"]}
                mapping.update({node["key"]: "node_" + digest([run_id, node["key"]])[:24] for node in draft["entities"] + draft["memories"]})
                reused = set()
                for node in draft["entities"]:
                    speaker = node.get("speakerId")
                    if speaker is None:
                        continue
                    prior = self.db.execute("SELECT id FROM nodes WHERE scope=? AND speaker_id=?", (scope, speaker)).fetchone()
                    if prior:
                        if prior[0] not in mapping:
                            raise Invalid("发言者实体仍位于另一未关闭话题；请先关闭该话题后重试，避免跨话题泄漏")
                        mapping[node["key"]] = prior[0]
                        reused.add(node["key"])
                for node in draft["entities"] + draft["memories"]:
                    memory = "kind" in node
                    if node["key"] in reused:
                        continue
                    self.db.execute("INSERT INTO nodes(id,scope,episode,stage,type,kind,label,subject,status,evidence,used,run_id,speaker_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (mapping[node["key"]], scope, episode, "TEMPORARY", "MEMORY" if memory else node["type"], node.get("kind", "ENTITY"),
                         node["text"] if memory else node["label"], mapping[node["subject"]] if memory else None, "CURRENT",
                          encode(node["evidence"]), encode(node.get("usedMemoryIds", [])), run_id, node.get("speakerId")))
                mentions = {}
                for node in draft["entities"] + draft["memories"]:
                    ident = mapping[node["subject"]] if "kind" in node else mapping[node["key"]]
                    # An attributed memory does not itself establish speaker identity;
                    # keep only evidence whose authoritative speaker matches the binding.
                    binding = self.db.execute("SELECT speaker_id FROM nodes WHERE id=?", (ident,)).fetchone()[0]
                    if binding:
                        event_speakers = {e["id"]: e["speaker"] for e in bundle["events"] + bundle["contextEvents"]}
                        mentions.setdefault(ident, []).extend(e for e in node["evidence"] if event_speakers[e["eventId"]] == binding)
                for ident, evidence in mentions.items():
                    if evidence:
                        unique = {encode(e): e for e in evidence}
                        self.db.execute("INSERT INTO entity_mentions VALUES(?,?,?,?,?)", (ident, scope, episode, run_id, encode(list(unique.values()))))
                for memory in draft["memories"]:
                    for old in memory["supersedes"]:
                        self.db.execute("UPDATE nodes SET status='SUPERSEDED' WHERE id=?", (old,))
                        self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (old, mapping[memory["key"]], run_id))
                for index, edge in enumerate(draft["associations"]):
                    self.db.execute("INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?)", (f"{run_id}:edge:{index}", scope,
                        mapping[edge["source"]], mapping[edge["target"]], edge["relation"], edge["strength"], encode(edge["evidence"]), edge["rationale"], run_id))
                self.db.executemany("UPDATE events SET processed=1 WHERE scope=? AND id=?", [(scope, e["id"]) for e in bundle["events"]])
                self.db.execute("UPDATE scopes SET revision=revision+1 WHERE id=?", (scope,))
                self.db.execute("UPDATE writes SET status='COMMITTED',output=?,metadata=? WHERE id=?", (encode(draft), encode(metadata), run_id))
            return {"writeId": run_id, "mapping": mapping, "memoriesCreated": len(draft["memories"]), "entitiesCreated": len(draft["entities"]) - len(reused), "entitiesReused": len(reused),
                    "edgesCreated": len(draft["associations"]), "skipped": draft["skipped"], "metadata": metadata}
        except Exception as error:
            with self.db:
                self.db.execute("UPDATE writes SET status='FAILED',output=?,metadata=?,error=? WHERE id=?",
                                (encode(draft) if draft is not None else None, encode(metadata), str(error), run_id))
            raise

    def close_episode(self, scope, episode):
        if self._episode(scope,episode)['lifecycle'] == 'episode':
            from .episode_runtime import close
            return close(self,scope,episode)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            ep = self._episode(scope, episode)
            if ep["status"] in ("CLOSED", "SEALED", "CONSOLIDATED"):
                return ep
            if self.db.execute("SELECT 1 FROM events WHERE scope=? AND episode=? AND processed=0", (scope, episode)).fetchone():
                raise Invalid("先为未整理事件生成检查点，再关闭话题")
            if ep['lifecycle'] == 'legacy':
                self.db.execute("UPDATE nodes SET stage='LONG_TERM' WHERE scope=? AND episode=?", (scope, episode))
            self.db.execute("UPDATE episodes SET status=? WHERE scope=? AND id=?", ('CLOSED' if ep['lifecycle'] == 'legacy' else 'SEALED', scope, episode))
            self.db.execute("UPDATE scopes SET revision=revision+1 WHERE id=?", (scope,))
        return self._episode(scope, episode)

    def consolidate(self, scope, episode, model=None, draft=None, memory_ids=(), temporary_ids=None):
        if self._episode(scope,episode)['lifecycle'] == 'episode':
            if temporary_ids is not None:
                raise Invalid('新流程整理整个CLOSED Episode快照，不按主体选临时子集')
            from .episode_final import finalize
            return finalize(self,scope,episode,model,draft,memory_ids)
        from .consolidation import consolidate
        return consolidate(self, scope, episode, model, draft, memory_ids, temporary_ids)

    def advance_episode(self, scope, episode, event, model=None, draft=None, memory_ids=()):
        from .episode_runtime import advance
        return advance(self,scope,episode,event,model,draft,memory_ids)

    def episode_state(self, scope, episode):
        from .episode_runtime import snapshot
        return snapshot(self,scope,episode)

    def reopen_episode(self, scope, episode):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            ep = self._episode(scope, episode)
            if ep['lifecycle'] != 'consolidate' or ep['status'] != 'SEALED':
                raise Invalid('仅待巩固/有暂存内容的SEALED话题可以恢复接收经历')
            self.db.execute("UPDATE episodes SET status='OPEN' WHERE scope=? AND id=?", (scope, episode))
            self.db.execute('UPDATE scopes SET revision=revision+1 WHERE id=?', (scope,))
        return self._episode(scope, episode)

    def state(self, scope):
        if self.db.execute("SELECT COUNT(*) FROM events WHERE scope=?", (scope,)).fetchone()[0] > 10000:
            raise Invalid("大scope请使用summary和分页读取，不导出整库到浏览器")
        result = {"scope": scope}
        revision = self.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()
        result["revision"] = revision[0] if revision else None
        for name in ["episodes", "events", "nodes", "edges", "writes"]:
            rows = list(self.db.execute(f"SELECT * FROM {name} WHERE scope=? ORDER BY rowid", (scope,)))
            result[name] = [self.node(row) if name == "nodes" else dict(row) for row in rows]
        for row in result["writes"]:
            for key in ["input", "output", "metadata"]:
                row[key] = json.loads(row[key]) if row[key] else None
        for row in result["edges"]:
            row["evidence"] = json.loads(row["evidence"])
        result["revisions"] = [dict(row) for row in self.db.execute("SELECT r.* FROM revisions r JOIN nodes n ON n.id=r.old_id WHERE n.scope=?", (scope,))]
        result["entityMentions"] = [{**dict(row), "evidence": json.loads(row["evidence"])} for row in self.db.execute("SELECT * FROM entity_mentions WHERE scope=? ORDER BY rowid", (scope,))]
        result['episodeCollections'] = [self.episode_state(scope,e['id']) for e in result['episodes'] if e['lifecycle']=='episode']
        result["experiments"] = [{"id": row["id"], "query": json.loads(row["result"])["query"]}
                                 for row in self.db.execute("SELECT id,result FROM recalls WHERE scope=? ORDER BY rowid DESC LIMIT 20", (scope,))]
        return result

    def summary(self, scope):
        result = {"scope": scope}
        for table in ["events", "nodes", "edges", "episodes", "writes", "recalls"]:
            result[table] = self.db.execute(f"SELECT COUNT(*) FROM {table} WHERE scope=?", (scope,)).fetchone()[0]
        result["pendingEvents"] = self.db.execute("SELECT COUNT(*) FROM events WHERE scope=? AND processed=0", (scope,)).fetchone()[0]
        result["revision"] = self.db.execute("SELECT revision FROM scopes WHERE id=?", (scope,)).fetchone()
        result["revision"] = result["revision"][0] if result["revision"] else None
        return result

    def page(self, scope, collection="nodes", after=0, limit=50):
        if collection not in ["nodes", "events", "writes"]:
            raise Invalid("分页collection只能是nodes/events/writes")
        integer(after, "after", 0, 10**12)
        integer(limit, "limit", 1, 200)
        rows = list(self.db.execute(f"SELECT rowid AS cursor,* FROM {collection} WHERE scope=? AND rowid>? ORDER BY rowid LIMIT ?", (scope, after, limit)))
        items = [self.node(row) if collection == "nodes" else dict(row) for row in rows]
        if collection == "writes":
            for item in items:
                for field in ["input", "output", "metadata"]:
                    item[field] = json.loads(item[field]) if item[field] else None
        return {"items": items, "next": rows[-1]["cursor"] if rows else None}

    def recall_record(self, scope, ident):
        row = self.db.execute("SELECT result FROM recalls WHERE scope=? AND id=?", (scope, ident)).fetchone()
        if row is None:
            raise Invalid("该scope中不存在此实验记录")
        return {**json.loads(row[0]), "recallId": ident}

    def save_recall(self, scope, result):
        ident = "recall_" + uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO recalls VALUES(?,?,?)", (ident, scope, encode(result)))
        return ident
