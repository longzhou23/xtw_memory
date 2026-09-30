#!/usr/bin/env python3
"""Deterministic, conservative per-memory Cognitive Unit cleaner.

This intentionally never reads another memory while cleaning the current one.
"""
import hashlib, json, re, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "iris_full_backup_2026-09-21.json"
OUT = ROOT / "cognitive_units_batches"

STATUS = ["CLEAN","SUBJECTLESS","UNRESOLVED_REFERENCE","AMBIGUOUS","MIXED_SPLIT","DUPLICATE_CANDIDATE","CONFLICT_CANDIDATE","REJECTED"]

def stable_id(mem_id, ordinal, text):
    h = hashlib.sha256(f"{mem_id}\0{ordinal}\0{text}".encode()).hexdigest()[:24]
    return "cu:" + h

def split_units(text):
    # Sentence boundaries first; only split conjunctions when each side has
    # an independently asserted clause.  Keep temporal/procedural relations.
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s: return []
    parts = [p.strip(" ，,；;。！？!?\t") for p in re.split(r"(?<=[。！？!?；;])\s*", s) if p.strip()]
    out = []
    for p in parts:
        # Do not split procedures, comparisons, causes, conditions, or relation intervals.
        if re.search(r"(先.+再|然后|之后|以前|因为.+所以|由于.+因此|如果.+就|与.+间隔|比.+更|像.+一样)", p):
            out.append(p); continue
        chunks = [p]
        for sep in [r"(?:，|,)?(?:并且|以及|同时|还|又)\s*", r"(?:，|,|、)\s*(?=[^，,。；;]{1,30}(?:喜欢|不喜欢|希望|想|计划|住在|在|是|有|玩|负责|使用|来自|位于|属于|购买|去了|做|看|认为|负责|分享|维护|开发|制作))"]:
            nxt=[]
            for c in chunks:
                q=[x.strip(" ，,；;") for x in re.split(sep,c) if x.strip(" ，,；;")]
                nxt.extend(q if len(q)>1 else [c])
            chunks=nxt
        out.extend(chunks)
    # If the source opens with an explicit subject and later clauses are
    # coordinated predicates, repeat that subject so each unit stands alone.
    sm = re.match(r"^([^，,。；;：:]{1,24}?)(?:是|喜欢|不喜欢|希望|想|住在|在|有|负责|玩|认为|觉得|购买|买了|去了)", s)
    if sm and len(out) > 1:
        subj = sm.group(1).strip()
        out = [x if re.match(r"^[^，,。；;：:]{1,24}?(?:是|喜欢|不喜欢|希望|想|住在|在|有|负责|玩|认为|觉得|购买|买了|去了)", x) else subj + x for x in out]
    return out or [s]

def classify(t):
    if re.search(r"(不喜欢|喜欢|爱|讨厌|偏好|重视)", t): return "PREFERENCE"
    if re.search(r"(希望|想要|想和|想在|计划|打算|准备|愿望)", t): return "GOAL"
    if re.search(r"(认为|觉得|看来|感觉|推测|猜测|听说)", t): return "OPINION"
    if re.search(r"(先.+再|然后|步骤|流程|通常.*顺序)", t): return "PROCEDURE"
    if re.search(r"(买了|购买|去了|参加|完成|发生|发布|创建|加入)", t): return "EVENT"
    if re.search(r"(是|叫|真名|昵称|账号|身份)", t) and re.search(r"(人|名|号|身份|作者|创作者|开发者|维护者)", t): return "IDENTITY_CLAIM"
    if re.search(r"(住在|位于|在.+工作|开学后|目前|现在|状态|没有|未)", t): return "STATE"
    if re.search(r"(与|和).+(间隔|相似|不同|关系|之间)", t): return "RELATION"
    return "FACT"

def make_unit(mem, text, ordinal):
    mid = str(mem.get("id", "")); t=text.strip()
    explicit_subject = bool(re.match(r"^([^，,。；;：:]{1,24}?)(?:是|喜欢|不喜欢|希望|想|住在|在|有|负责|玩|认为|觉得|购买|买了|去了)", t))
    subjectless = (bool(mem.get("metadata",{}).get("subjectless")) and not explicit_subject) or bool(re.match(r"^(她|他|它|这|那|后来|目前|然后)", t))
    status = "SUBJECTLESS" if subjectless else "CLEAN"
    if re.match(r"^(她|他|它|这|那|后来)\b", t) and not subjectless: status="UNRESOLVED_REFERENCE"
    if len(t) < 2: status="REJECTED"
    polarity = "negative" if re.search(r"(不|没|没有|未|无|并非|不是)", t) else "positive"
    modality = "asserted"
    if re.search(r"(可能|也许|希望|想|计划|打算|认为|觉得|听说|猜测)", t): modality="modal"
    subjects=[]
    # Only record explicit local subject-like spans; never infer from other memories.
    m=re.match(r"^([^，,。；;：:]{1,24}?)(?:是|喜欢|不喜欢|希望|想|住在|在|有|负责|玩|认为|觉得|购买|买了|去了)", t)
    if m: subjects=[{"text":m.group(1).strip()}]
    return {"id":stable_id(mid,ordinal,t),"type":classify(t),"text":t,
            "subjects":subjects,"mentions":[],
            "semantic":{"predicate":None,"polarity":polarity,"modality":modality,"temporal":None},
            "provenance":{"sourceMemoryIds":[mid],"sourceTexts":[str(mem.get("content", ""))],"sourceSpan":None},
            "cleaning":{"status":status,"confidence":0.78 if status=="CLEAN" else 0.62,"notes":"deterministic conservative per-memory extraction"}}

def main():
    with RAW.open(encoding="utf-8") as f: data=json.load(f)
    entries=data["l2_memory"]["entries"]
    OUT.mkdir(exist_ok=True)
    all_stats=[]; all_units=[]
    for bi,start in enumerate(range(0,len(entries),100),1):
        batch=entries[start:start+100]
        units=[]; per=[]
        for mem in batch:
            texts=split_units(mem.get("content",""))
            us=[make_unit(mem,t,i) for i,t in enumerate(texts)]
            units.extend(us); all_units.extend(us)
            per.append({"memoryId":mem.get("id"),"unitCount":len(us),"statuses":{s:sum(u["cleaning"]["status"]==s for u in us) for s in STATUS}})
        stats={"batch":f"{bi:02d}","entryStart":start+1,"entryEnd":start+len(batch),"rawMemoryCount":len(batch),"derivedUnitCount":len(units),"statusCounts":{s:sum(u["cleaning"]["status"]==s for u in units) for s in STATUS},"needsReviewCount":sum(u["cleaning"]["status"]!="CLEAN" for u in units)}
        payload={"version":"0.1.0","schema":"iris-cognitive-unit-store/v0.1","source":"iris_full_backup_2026-09-21.json","rules":"IRIS_Memory_Cognitive_Unit_清洗规范_v0.1.md","batch":stats,"units":units,"perMemory":per}
        (OUT/f"batch_{bi:02d}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        all_stats.append(stats)
    counts=[len([u for u in all_units if u["provenance"]["sourceMemoryIds"][0]==m.get("id")]) for m in entries]
    summary={"version":"0.1.0","schema":"iris-cognitive-unit-store/v0.1","sourceRaw":"iris_full_backup_2026-09-21.json","rawMemoryCount":len(entries),"derivedCognitiveUnitCount":len(all_units),"unitsPerMemory":{"mean":statistics.mean(counts),"median":statistics.median(counts),"p90":sorted(counts)[int(.9*len(counts))-1],"max":max(counts)},"statusCounts":{s:sum(u["cleaning"]["status"]==s for u in all_units) for s in STATUS},"exactSemanticDedupCount":0,"duplicateCandidateCount":0,"conflictCandidateCount":0,"duplicateConflictAnalysis":"not performed; units remain provenance-preserving and unmerged","rejectedCount":sum(u["cleaning"]["status"]=="REJECTED" for u in all_units),"needsReviewCount":sum(u["cleaning"]["status"]!="CLEAN" for u in all_units),"batches":all_stats}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"batch_stats.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in all_stats),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
