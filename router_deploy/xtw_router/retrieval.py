"""Observable candidate retrieval, independent of semantic labels and model predictions."""
from collections import Counter
import copy
import math
import re
import xml.etree.ElementTree as ET


def semantic_text(text):
    if text.startswith("[合并转发: <?xml"):
        try:
            xml = text[text.index("<?xml"):].removesuffix("]")
            text = " ; ".join(t.text or "" for t in ET.fromstring(xml).iter("title"))
        except (ValueError, ET.ParseError): text = ""
    # Keep displayed markdown labels, exclude URL/encoded transport metadata.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[UNKNOWN_\d+消息\]", "", text)
    text = re.sub(r"\[回复 [^:\n]*:", "[引用:", text)
    return text.casefold()


def grams(text):
    text = semantic_text(text)
    return {text[i:i+2] for i in range(len(text)-1) if text[i:i+2].strip()}


def candidates_for(episodes, event):
    if not episodes: return []
    query = grams(event["text"]); reply = event.get("reply_to_message_id")
    views = {key: [grams(m["text"]) for m in messages[:1] + messages[-3:]] for key, messages in episodes.items()}
    document_frequency = Counter(g for pairs in views.values() for g in set().union(*pairs))
    weights = {g: math.log(1 + len(episodes) / (1 + document_frequency[g])) for g in query}
    total = sum(weights.values()) or 1
    scored = []
    for key, messages in episodes.items():
        overlap = max((sum(weights[g] for g in query & pair) / total for pair in views[key]), default=0)
        observed = messages[:1] + messages[-3:]
        author = .08 if any(m.get("participant_id") == event.get("participant_id") for m in observed) else 0
        score = (1000 if reply and any(m["message_id"] == reply for m in messages) else 0) + overlap + author
        scored.append((score, messages[-1]["sequence_index"], key))
    # Two immediate active threads prevent boilerplate-heavy bot replies from
    # displacing the request that just preceded them. This is candidate recall,
    # not an automatic continuation decision.
    by_recent = sorted(episodes, key=lambda k: (episodes[k][-1]["sequence_index"], k), reverse=True)
    chosen = [key for _, _, key in sorted(scored, reverse=True)[:6]]
    for key in by_recent[:2]:
        if key not in chosen: chosen.append(key)
    for _, _, key in sorted(scored, reverse=True):
        if len(chosen) >= 8: break
        if key not in chosen: chosen.append(key)
    return [{"runtime_episode_id": key, "all_episode_message_ids": [m["message_id"] for m in episodes[key]],
             "first_messages": copy.deepcopy(episodes[key][:1]), "recent_messages": copy.deepcopy(episodes[key][-2:]),
             "summary": " ; ".join(semantic_text(m["text"])[:40] for m in episodes[key][-2:])} for key in chosen]
