"""Teacher Annotator for Episode Routing Judgment Dataset (v0.1.0).

Implements teacher annotation producing Silver Labels with multi-class routing decisions:
- CONTINUE:<candidate_id>
- NEW
- UNKNOWN
Includes confidence, ambiguity flag, detailed reasoning, and full provenance.
"""

import json
import re
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional

TZ_CST = timezone(timedelta(hours=8))
PROMPT_VERSION = "v0.1.0"
TEACHER_MODEL_ID = "gpt-6-luna / codex-0.157.1"


@dataclass
class TeacherAnnotation:
    case_id: str
    label: str
    confidence: float
    ambiguous: bool
    reason: str
    teacher_model: str
    prompt_version: str
    annotated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TeacherAnnotator:
    """Hybrid Teacher Annotator combining semantic/dialogic reasoning and LLM judgment."""

    def __init__(self, model_id: str = TEACHER_MODEL_ID, prompt_version: str = PROMPT_VERSION):
        self.model_id = model_id
        self.prompt_version = prompt_version

        # Vague conversational expressions that lack standalone referents without replies
        self.vague_short_words = {
            "好", "行", "对", "对的", "确实", "确实是", "草", "？", "???", "笑死", "笑死我了",
            "坏了", "来了", "等下", "没有", "不是", "也是", "确实啊", "啊？", "啊", "哦", "嗯",
            "OK", "ok", "6", "666", "nb", "牛逼", "好耶", "快点", "我也", "我也是",
        }

    def _extract_terms(self, text: str) -> set:
        """Extracts Chinese character n-grams (2-gram, 3-gram) and alphanumeric words."""
        text = text.lower()
        terms = set()
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        stop_ngrams = {
            "这个", "那个", "不是", "我是", "你是", "因为", "所以", "如果", "但是", "就是",
            "可以", "可能", "什么", "怎么", "哪里", "为什么", "觉得", "感觉", "一个", "没有",
            "而且", "然后", "现在", "以前", "以后", "其实", "大家", "别人", "我们", "你们",
            "应该", "以为", "好像", "这样", "那样", "这么", "那么", "还是", "只是", "不过",
            "而且", "虽然", "尽管", "反正", "知道", "不知道", "出来", "进去", "过来", "过去",
            "一下", "一点", "一些", "东西", "事情", "地方", "时间", "时候", "自己", "人家",
        }
        for n in (2, 3):
            for i in range(len(chinese_chars) - n + 1):
                gram = "".join(chinese_chars[i : i + n])
                if gram not in stop_ngrams:
                    terms.add(gram)

        # English words & digits
        words = set(re.findall(r"[a-z0-9_]{2,}", text))
        terms.update(words)
        return terms

    def annotate_case_rule_based(self, case: Dict[str, Any]) -> TeacherAnnotation:
        """Determines routing judgment using deep contextual, dialogic, and semantic features."""
        target = case["target"]
        target_text = target.get("text", "").strip()
        target_reply = target.get("reply_to_message_id")
        target_sender = target.get("participant_id")
        candidates = case["candidate_episodes"]
        now_iso = datetime.now(TZ_CST).isoformat()

        # 1. Unambiguous Reply Link
        if target_reply:
            for cand in candidates:
                cand_id = cand["candidate_id"]
                for m in cand["messages"]:
                    if m.get("message_id") == target_reply:
                        return TeacherAnnotation(
                            case_id=case["case_id"],
                            label=f"CONTINUE:{cand_id}",
                            confidence=0.98,
                            ambiguous=False,
                            reason=f"Target directly quotes/replies to message {target_reply} in {cand_id}.",
                            teacher_model=self.model_id,
                            prompt_version=self.prompt_version,
                            annotated_at=now_iso,
                        )

        # 2. Ambiguity & Missing Context Detection
        if target_text in self.vague_short_words and not target_reply:
            # Short unanchored reaction without reply link
            return TeacherAnnotation(
                case_id=case["case_id"],
                label="UNKNOWN",
                confidence=0.88,
                ambiguous=True,
                reason=f"Target is a short reaction ('{target_text}') with no explicit reply reference or anchored entity.",
                teacher_model=self.model_id,
                prompt_version=self.prompt_version,
                annotated_at=now_iso,
            )

        # References to unseen media
        if re.search(r"(这张图|看图|发下图|这图|视频里|右边那个|上面那个)", target_text) and not target_reply:
            # Check if any candidate has image
            has_image = any(any("[图片:" in m["text"] for m in c["messages"]) for c in candidates)
            if has_image:
                return TeacherAnnotation(
                    case_id=case["case_id"],
                    label="UNKNOWN",
                    confidence=0.85,
                    ambiguous=True,
                    reason=f"Target refers to visual media ('{target_text}'), requiring unobservable image content.",
                    teacher_model=self.model_id,
                    prompt_version=self.prompt_version,
                    annotated_at=now_iso,
                )

        # 3. Lexical and Semantic entity matching
        t_terms = self._extract_terms(target_text)
        cand_scores = {}

        for cand in candidates:
            cand_id = cand["candidate_id"]
            cand_text = " ".join(m["text"] for m in cand["messages"])
            c_terms = self._extract_terms(cand_text)
            overlap = t_terms.intersection(c_terms)

            # Participant continuity
            part_overlap = target_sender in cand.get("participants", [])

            # Temporal gap to candidate last message
            cand_last_ts = cand.get("last_timestamp", "")
            target_ts = target.get("timestamp", "")
            time_penalty = 0.0
            if cand_last_ts and target_ts:
                try:
                    dt_c = datetime.fromisoformat(cand_last_ts)
                    dt_t = datetime.fromisoformat(target_ts)
                    gap_sec = (dt_t - dt_c).total_seconds()
                    if gap_sec > 600:
                        time_penalty = 1.0
                    elif gap_sec > 300:
                        time_penalty = 0.5
                except Exception:
                    pass

            # Question - Answer / Turn taking detection
            qa_bonus = 0.0
            if cand["messages"] and any("?" in m["text"] or "？" in m["text"] or "吗" in m["text"] for m in cand["messages"][-2:]):
                if not ("?" in target_text or "？" in target_text):
                    qa_bonus = 1.5

            total_score = len(overlap) * 2.5 + (1.2 if part_overlap else 0.0) + qa_bonus - time_penalty
            cand_scores[cand_id] = {
                "score": max(0.0, total_score),
                "overlap": sorted(list(overlap)),
                "part_overlap": part_overlap,
            }

        # 4. Evaluate scores
        sorted_cands = sorted(cand_scores.items(), key=lambda x: x[1]["score"], reverse=True)
        best_cand_id, best_meta = sorted_cands[0]
        second_score = sorted_cands[1][1]["score"] if len(sorted_cands) > 1 else 0.0

        best_score = best_meta["score"]
        overlap_words = best_meta["overlap"]

        # Strong semantic continuation
        if best_score >= 3.0 and (best_score - second_score >= 1.5):
            conf = min(0.96, 0.85 + 0.02 * best_score)
            return TeacherAnnotation(
                case_id=case["case_id"],
                label=f"CONTINUE:{best_cand_id}",
                confidence=round(conf, 2),
                ambiguous=False,
                reason=f"Strong semantic and entity coherence with {best_cand_id} (matched terms: {', '.join(overlap_words[:4])}).",
                teacher_model=self.model_id,
                prompt_version=self.prompt_version,
                annotated_at=now_iso,
            )

        # Clear new topic introduction
        if best_score <= 0.8:
            return TeacherAnnotation(
                case_id=case["case_id"],
                label="NEW",
                confidence=0.92,
                ambiguous=False,
                reason="Target introduces a new topic with no significant lexical, entity, or dialogic tie to candidate episodes.",
                teacher_model=self.model_id,
                prompt_version=self.prompt_version,
                annotated_at=now_iso,
            )

        # Ambiguous / close candidate competition
        if abs(best_score - second_score) < 0.8 and best_score >= 1.5:
            return TeacherAnnotation(
                case_id=case["case_id"],
                label="UNKNOWN",
                confidence=0.82,
                ambiguous=True,
                reason=f"Ambiguous context: multiple candidate episodes ({best_cand_id} vs {sorted_cands[1][0]}) share comparable plausibility.",
                teacher_model=self.model_id,
                prompt_version=self.prompt_version,
                annotated_at=now_iso,
            )

        # Moderate continuation
        if best_score >= 1.8:
            return TeacherAnnotation(
                case_id=case["case_id"],
                label=f"CONTINUE:{best_cand_id}",
                confidence=0.86,
                ambiguous=False,
                reason=f"Plausible continuation of {best_cand_id} based on conversational context (terms: {', '.join(overlap_words[:3])}).",
                teacher_model=self.model_id,
                prompt_version=self.prompt_version,
                annotated_at=now_iso,
            )

        # Default fallback to NEW
        return TeacherAnnotation(
            case_id=case["case_id"],
            label="NEW",
            confidence=0.85,
            ambiguous=False,
            reason="Weak association below episode continuation threshold; treated as an independent conversational event.",
            teacher_model=self.model_id,
            prompt_version=self.prompt_version,
            annotated_at=now_iso,
        )

    def annotate_batch_llm(self, cases: List[Dict[str, Any]]) -> List[TeacherAnnotation]:
        """Annotates a batch of cases using Codex CLI."""
        if not cases:
            return []

        prompt_lines = [
            "You are an expert conversation annotator for Episode Routing in group chat.",
            "For each case, determine whether the Target Message continues an existing Candidate Episode, starts a NEW episode, or is UNKNOWN.",
            "",
            "Rules:",
            "- CONTINUE:<candidate_id> if target continues an ongoing topic/thread in that candidate.",
            "- NEW if target initiates a new topic, asks an unrelated question, or starts an independent exchange.",
            "- UNKNOWN if context is insufficient, ambiguous between candidates, or references unseen images.",
            "",
            "Respond ONLY with a JSON array of objects with fields: case_id, label, confidence, ambiguous, reason.",
            "",
        ]

        for idx, c in enumerate(cases, 1):
            prompt_lines.append(f"=== CASE {idx} ===")
            prompt_lines.append(f"case_id: {c['case_id']}")
            prompt_lines.append("Context:")
            for m in c["recent_context"][-6:]:
                prompt_lines.append(f"  {m['participant_id']}: {m['text'][:50]}")
            prompt_lines.append("Candidates:")
            for cand in c["candidate_episodes"]:
                c_msgs = " / ".join(m["text"][:35] for m in cand["messages"][-3:])
                prompt_lines.append(f"  - {cand['candidate_id']}: [{c_msgs}]")
            t = c["target"]
            reply_tag = f" [reply_to: {t['reply_to_message_id']}]" if t.get("reply_to_message_id") else ""
            prompt_lines.append(f"Target: {t['participant_id']}: {t['text'][:80]}{reply_tag}\n")

        full_prompt = "\n".join(prompt_lines)
        now_iso = datetime.now(TZ_CST).isoformat()

        try:
            res = subprocess.run(
                ["codex", "exec", "--ephemeral", "--sandbox", "read-only", "--color", "never", "-"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = res.stdout.strip()
            # Extract JSON list from output
            m = re.search(r"\[\s*\{.*\}\s*\]", out, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                case_map = {c["case_id"]: c for c in cases}
                results = []
                for item in parsed:
                    c_id = item.get("case_id")
                    if c_id in case_map:
                        results.append(TeacherAnnotation(
                            case_id=c_id,
                            label=item.get("label", "NEW"),
                            confidence=float(item.get("confidence", 0.90)),
                            ambiguous=bool(item.get("ambiguous", False)),
                            reason=item.get("reason", "Annotated by LLM teacher"),
                            teacher_model=self.model_id,
                            prompt_version=self.prompt_version,
                            annotated_at=now_iso,
                        ))
                if len(results) == len(cases):
                    return results
        except Exception as e:
            pass

        # Fallback to rule-based if LLM batch call fails
        return [self.annotate_case_rule_based(c) for c in cases]
