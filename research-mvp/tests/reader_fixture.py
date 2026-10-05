"""Synthetic, explicitly reviewed demo; never represented as learned writing."""
import uuid


def event(ident, speaker, body, minute, reply=None):
    result = {"id": ident, "speaker": speaker, "text": body, "time": f"2026-10-01T10:{minute:02d}:00+08:00"}
    if reply:
        result["replyTo"] = reply
    return result


BATCHES = [
    [event("e1", "林宁", "把这次观测叫作白鹭计划。周五19:00在南门集合。", 0),
     event("e2", "阿澈", "大家叫我海风就行，我负责带望远镜。", 1),
     event("e3", "林宁", "白鹭计划观测地点是旧码头。", 2),
     event("e4", "林宁", "那里路灯少，适合看暗星。", 3, "e3"),
     event("e5", "阿澈", "哈哈，今天的云像棉花糖。", 4)],
    [event("e6", "林宁", "预报周五暴雨。", 5),
     event("e7", "林宁", "因此白鹭计划改到周六19:00，集合地点仍是南门。", 6, "e1"),
     event("e8", "阿澈", "白鹭计划参加者不要独自离队。", 7)],
]


def ev(ident, quote):
    return {"eventId": ident, "quote": quote}


def entity(key, kind, label, evidence):
    return {'speakerId':None,"key": key, "type": kind, "label": label, "evidence": evidence}


def memory(key, body, subject, evidence, used=(), supersedes=()):
    return {"key": key, "kind": "EPISODIC", "text": body, "subject": subject,
            "evidence": evidence, "usedMemoryIds": list(used), "supersedes": list(supersedes)}


def edge(source, target, relation, evidence, rationale, strength=.8):
    return {"source": source, "target": target, "relation": relation, "strength": strength,
            "evidence": evidence, "rationale": rationale}


def first_draft():
    e1, e2, e3, e4 = [ev(batch["id"], batch["text"]) for batch in BATCHES[0][:4]]
    entities = [entity("activity", "ACTIVITY", "白鹭计划", [e1]), entity("person", "PERSON", "阿澈", [e2]),
                entity("alias", "ALIAS", "海风", [e2]), entity("location", "LOCATION", "旧码头", [e3]),
                entity("telescope", "OBJECT", "望远镜", [e2])]
    memories = [memory("schedule", "白鹭计划原定周五19:00在南门集合。", "activity", [e1]),
                memory("equipment", "阿澈自称海风，将为白鹭计划携带望远镜。", "person", [e1, e2]),
                memory("place", "白鹭计划在旧码头观测；该处路灯少，适合看暗星。", "activity", [e3, e4])]
    edges = [edge("activity", "schedule", "SIMILARITY", [e1], "活动与其计划"),
             edge("alias", "person", "SIMILARITY", [e2], "明确自称"),
             edge("person", "equipment", "SIMILARITY", [e2], "人物与承担事项"),
             edge("telescope", "equipment", "SIMILARITY", [e2], "器材线索"),
             edge("activity", "equipment", "SIMILARITY", [e1, e2], "同一经历中的承担事项"),
             edge("activity", "place", "SIMILARITY", [e3], "活动与地点"),
             edge("location", "place", "SIMILARITY", [e3, e4], "地点与完整观测记忆")]
    return {"entities": entities, "memories": memories, "associations": edges,
            "skipped": [{"eventId": "e5", "reason": "即时闲聊，没有需固化的独立信息"}]}


def second_draft(mapping):
    e6, e7, e8 = [ev(batch["id"], batch["text"]) for batch in BATCHES[1]]
    activity, old = mapping["activity"], mapping["schedule"]
    memories = [memory("weather", "预报白鹭计划原定的周五会有暴雨。", activity, [e6, e7], [old]),
                memory("new_schedule", "因预报周五暴雨，白鹭计划改到周六19:00，仍在南门集合。", activity, [e6, e7], [old], [old]),
                memory("safety", "白鹭计划要求参加者不要独自离队。", activity, [e8])]
    edges = [edge("weather", "new_schedule", "CAUSAL", [e6, e7], "明确以因此连接预报与改期"),
             edge(old, "new_schedule", "OPPOSITION", [e7], "同一活动的两个时间版本；旧版本被明确替代"),
             *[edge(activity, m["key"], "SIMILARITY", m["evidence"], "同一活动的事实线索") for m in memories]]
    return {"entities": [], "memories": memories, "associations": edges, "skipped": []}


def load_demo(store, scope=None, model=None):
    scope = scope or "demo-" + uuid.uuid4().hex[:8]
    if store.db.execute("SELECT 1 FROM scopes WHERE id=?", (scope,)).fetchone():
        from research_memory.contracts import Invalid
        raise Invalid("演示scope已存在，请使用新名字")
    store.create_episode(scope, "observation", "白鹭计划：两次记忆形成")
    results = []
    for index, batch in enumerate(BATCHES):
        store.ingest(scope, "observation", batch)
        draft = None if model else (first_draft() if index == 0 else second_draft(results[0]["mapping"]))
        result = store.checkpoint(scope, "observation", model=model, draft=draft)
        results.append(result)
    store.close_episode(scope, "observation")
    return {"scope": scope, "episode": "observation", "writing": "REAL_MODEL" if model else "REVIEWED_SYNTHETIC_DRAFTS",
            "writes": results, "exampleQueries": ["白鹭计划什么时候、在哪里集合？", "白鹭计划为什么改期？", "海风负责带什么？"]}
