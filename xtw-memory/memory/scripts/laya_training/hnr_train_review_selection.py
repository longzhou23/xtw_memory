"""TRAIN-only weak-Teacher *proposals*, never semantic gold.

Preselect 1300 proposed NEW + 2000 proposed CONTINUE for blinded two-pass
review. If reviewed minima are not met, extend deterministically through the
remaining TRAIN packets; no teacher or model result is delivered to reviewers.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import hnr_source_preflight as source
from hnr_blind_packets import REVIEW_DIR, write_once, EXPECTED_WINDOW_MANIFEST_SHA256

from memory.scripts.judgment.teacher_annotator import TeacherAnnotator


def main() -> None:
    assert source.file_sha256(source.OUTPUT / "window-manifest.json") == EXPECTED_WINDOW_MANIFEST_SHA256
    input_path = REVIEW_DIR / "train-blind.jsonl"
    traces_path = source.OUTPUT / "dataset/baseline-candidate-capture/train-candidate-trace.jsonl"
    with input_path.open() as stream:
        packets = [json.loads(line) for line in stream]
    with traces_path.open() as stream:
        traces = {row["target_message_id"]: row for row in map(json.loads, stream)}
    assert len(traces) == len(packets) == 5014
    teacher = TeacherAnnotator()
    proposals = {}
    for packet in packets:
        trace = traces[packet["target_message_id"]]
        candidate_episodes = []
        for c in trace["candidates"]:
            recent = c["recent_messages"]
            candidate_episodes.append({
                "candidate_id": c["runtime_episode_id"],
                "messages": [{"message_id": m["message_id"], "text": m["text"]} for m in recent],
                "participants": [packet["target"]["participant_id"]] if c["same_speaker"] else [],
                "last_timestamp": recent[-1]["timestamp"] if recent else None,
            })
        proposal = teacher.annotate_case_rule_based({
            "case_id": packet["case_id"], "target": packet["target"],
            "candidate_episodes": candidate_episodes,
        })
        proposals[packet["case_id"]] = proposal.label.split(":", 1)[0]
    def priority(packet: dict) -> tuple:
        trace = traces[packet["target_message_id"]]
        scores = sorted((c["score"] for c in trace["candidates"]), reverse=True)
        close = int(len(scores) >= 2 and scores[0] - scores[1] <= 0.10)
        same_speaker = int(any(c["same_speaker"] for c in trace["candidates"]))
        return (-close, -same_speaker, packet["case_id"])
    new = sorted((p for p in packets if proposals[p["case_id"]] == "NEW"), key=priority)
    cont = sorted((p for p in packets if proposals[p["case_id"]] == "CONTINUE"), key=priority)
    assert len(new) >= 1300 and len(cont) >= 2000, "TRAIN proposed pool cannot supply initial review quota"
    # Mix the proposed classes by a fixed, content-independent hash so even
    # packet position cannot reveal the hidden Teacher proposal to reviewers.
    chosen = sorted(new[:1300] + cont[:2000],
                    key=lambda p: sha256(("hnr-review-v0.1:" + p["case_id"]).encode()).hexdigest())
    chosen_ids = {p["case_id"] for p in chosen}
    # If real semantic review misses a quota, only this fixed remainder order
    # may be reviewed next. Never overwrite first-pass results or reuse teacher
    # labels as truth.
    remainder = [p for p in packets if p["case_id"] not in chosen_ids]
    blind = REVIEW_DIR / "train-proposed-blind-3300.jsonl"
    remainder_path = REVIEW_DIR / "train-proposed-fallback-blind-1714.jsonl"
    digest = write_once(blind, chosen)
    fallback_digest = write_once(remainder_path, remainder)
    result = {
        "selection_rule": "TRAIN-only rule Teacher proposals + model-score closeness; NEVER truth. 1300 proposed NEW + 2000 proposed CONTINUE; deterministically hash-mix all selected packets to hide proposal class; if quotas fail, append fixed remainder in original chronological order",
        "reviewer_exposed_to_teacher_labels_or_model_scores": False,
        "proposals_not_gold": True,
        "window_manifest_sha256": EXPECTED_WINDOW_MANIFEST_SHA256,
        "baseline_trace_sha256": source.file_sha256(traces_path),
        "blind_parent_sha256": source.file_sha256(input_path),
        "proposal_distribution": dict(Counter(proposals.values())),
        "initial_selection": {"path": str(blind.relative_to(source.OUTPUT)), "count": len(chosen),
                              "sha256": digest, "proposed_new": 1300, "proposed_continue": 2000},
        "fallback": {"path": str(remainder_path.relative_to(source.OUTPUT)), "count": len(remainder),
                     "sha256": fallback_digest},
    }
    manifest = REVIEW_DIR / "train-selection-manifest.json"
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if manifest.exists():
        assert manifest.read_text() == payload
    else:
        manifest.write_text(payload)
    print(json.dumps({"selection_manifest_sha256": source.file_sha256(manifest),
                      "proposals": result["proposal_distribution"], "selected": len(chosen)}, indent=2))


if __name__ == "__main__":
    main()
