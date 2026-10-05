"""Model contracts. Evidence checks establish provenance, not entailment."""
import copy
import math


class Invalid(ValueError):
    pass


def text(value, name, maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Invalid(f"{name} 必须是 1–{maximum} 字符的非空文本")
    return value


def number(value, name, low=0, high=1):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise Invalid(f"{name} 必须在 {low}–{high} 内")
    return float(value)


def integer(value, name, low=1, high=100):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Invalid(f"{name} 必须是 {low}–{high} 的整数")
    return value


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array(items):
    return {"type": "array", "items": items}


STRING = {"type": "string"}
STRINGS = array(STRING)
EVIDENCE = array(obj({"eventId": STRING, "quote": STRING}))
WRITE_SCHEMA = obj({
    "entities": array(obj({"key": STRING, "type": {"type": "string", "enum": ["PERSON", "ALIAS", "CONCEPT", "OBJECT", "LOCATION", "ACTIVITY"]}, "label": STRING, "speakerId": {"type": ["string", "null"]}, "evidence": EVIDENCE})),
    "memories": array(obj({"key": STRING, "kind": {"type": "string", "enum": ["EPISODIC", "SEMANTIC", "PROCEDURAL", "GOAL"]}, "text": STRING, "subject": STRING, "evidence": EVIDENCE, "usedMemoryIds": STRINGS, "supersedes": STRINGS})),
    "associations": array(obj({"source": STRING, "target": STRING, "relation": {"type": "string", "enum": ["CAUSAL", "SIMILARITY", "OPPOSITION"]}, "strength": {"type": "number"}, "evidence": EVIDENCE, "rationale": STRING})),
    "skipped": array(obj({"eventId": STRING, "reason": STRING})),
})
PLAN_SCHEMA = obj({
    "cues": array(obj({"text": STRING, "weight": {"type": "number"}})),
    "relations": obj({name: {"type": "number"} for name in ["CAUSAL", "SIMILARITY", "OPPOSITION"]}),
    "direction": {"type": "string", "enum": ["forward", "reverse", "both"]},
})


def shape(value, schema, path="output"):
    kind = schema["type"]
    if isinstance(kind, list):
        if value is None and "null" in kind:
            return
        return shape(value, {**schema, "type": "string"}, path)
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise Invalid(f"{path} 字段不符合契约")
        for key, child in schema["properties"].items():
            shape(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list) or len(value) > 500:
            raise Invalid(f"{path} 不是合法数组（最多500项）")
        for item in value:
            shape(item, schema["items"], path + "[]")
    elif kind == "string":
        text(value, path)
        if "enum" in schema and value not in schema["enum"]:
            raise Invalid(f"{path} 枚举值不合法")
    elif kind == "number":
        number(value, path)


def validate_write(draft, bundle):
    shape(draft, WRITE_SCHEMA)
    pending = {event["id"] for event in bundle["events"]}
    events = {event["id"]: event for event in bundle["contextEvents"] + bundle["events"]}
    known = {node["id"]: node for node in bundle["knownNodes"]}
    keys, covered = set(known), set()

    def evidence(items, new=False):
        if not items:
            raise Invalid("每个节点和关联都必须引用证据")
        ids = set()
        for item in items:
            ident = item["eventId"]
            if ident not in events or item["quote"] not in events[ident]["text"]:
                raise Invalid(f"证据必须是本次输入事件的原文片段：eventId={ident}，请核对该id及其quote的对应关系")
            ids.add(ident)
        if new and not ids & pending:
            raise Invalid("新记忆必须包含本批新事件的证据")
        covered.update(ids & pending)

    for node in draft["entities"] + draft["memories"]:
        key = text(node["key"], "key", 100)
        if key in keys:
            raise Invalid("本地 key 重复或冒用了既有节点 id")
        keys.add(key)
        evidence(node["evidence"], new="kind" in node)
    entity_keys = {node["key"] for node in draft["entities"]} | {ident for ident, node in known.items() if node["type"] != "MEMORY"}
    bound = {}
    for node in draft["entities"]:
        speaker = node.get("speakerId")
        if speaker is None:
            continue
        if node["type"] != "PERSON" or node["label"] != speaker:
            raise Invalid("speakerId只用于发言者PERSON，label必须等于其原始speaker id；别名单独建点")
        if not any(events[e["eventId"]]["speaker"] == speaker for e in node["evidence"]):
            raise Invalid("speakerId必须由该发言者本人的输入事件元数据支持，不能从@文本推断")
        if speaker in bound:
            raise Invalid("同一输出不能重复声明同一个speakerId")
        bound[speaker] = node["key"]
    # Resolve identity before validating revisions and edges, including model redeclarations.
    existing = {n["speakerId"]: n["id"] for n in known.values() if n.get("speakerId")}
    canonical = {node["key"]: existing.get(node.get("speakerId"), node["key"]) for node in draft["entities"]}
    def resolve(ident):
        return canonical.get(ident, ident)
    replaced = set()
    for memory in draft["memories"]:
        if memory["subject"] not in entity_keys:
            raise Invalid("记忆 subject 必须引用可见实体节点")
        for field in ["usedMemoryIds", "supersedes"]:
            ids = memory[field]
            if len(ids) != len(set(ids)) or any(ident not in known or known[ident]["type"] != "MEMORY" for ident in ids):
                raise Invalid(f"{field} 只能引用已注入记忆的稳定 id")
        for ident in memory["supersedes"]:
            if ident in replaced or known[ident]["status"] != "CURRENT" or ident not in memory["usedMemoryIds"]:
                raise Invalid("替代必须使用尚未替代的旧记忆，且每条旧记忆只被替代一次")
            # Deliberately no fuzzy identity merge for revisions.
            if known[ident]["subject"] != resolve(memory["subject"]):
                raise Invalid("替代记忆必须保持相同主体 id")
            replaced.add(ident)
    edges = set()
    for edge in draft["associations"]:
        if edge["source"] not in keys or edge["target"] not in keys or resolve(edge["source"]) == resolve(edge["target"]):
            raise Invalid("关联端点不合法")
        endpoints = (resolve(edge["source"]), resolve(edge["target"]))
        if edge["relation"] != "CAUSAL":
            endpoints = tuple(sorted(endpoints))
        key = (*endpoints, edge["relation"])
        if key in edges:
            raise Invalid("重复关联；相似和对立只提交一次，运行时双向遍历")
        edges.add(key)
        number(edge["strength"], "strength", .01, 1)
        evidence(edge["evidence"], new=True)
    skipped = set()
    for item in draft["skipped"]:
        if item["eventId"] not in pending or item["eventId"] in skipped:
            raise Invalid("跳过记录不属于本批或重复")
        skipped.add(item["eventId"])
    if pending - covered - skipped:
        raise Invalid("每条新事件都必须有来源引用或明确的跳过理由")
    return draft


def validate_plan(plan):
    shape(plan, PLAN_SCHEMA)
    if not 1 <= len(plan["cues"]) <= 4 or sum(c["weight"] for c in plan["cues"]) <= 0:
        raise Invalid("需要1–4条线索，且总权重大于0")
    if sum(plan["relations"].values()) <= 0:
        raise Invalid("关系意图的总权重必须大于0")
    return plan
