"""Freeze model-blind HNR source windows from clean corpus, never raw exports.

This script only reads the frozen weak TRAIN and Judgment DEV/TEST splits. It
deliberately does not open Judgment HOLDOUT or load any model/teacher output.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "memory/clean/v0.1.0/messages.jsonl"
WEAK = ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-20k.jsonl"
JUDGMENT = ROOT / "memory/judgment/v0.1.0/splits"
OUTPUT = ROOT / "memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1"
DIAGNOSTIC_FILE_ID = "group_🌸🍐2026华理天文：迎新舞台✨_455497949_20260921_114745379.json"
BRACKET = re.compile(r"^\[\d+\]$")
PREFIXES = ("[图片:", "[视频:", "[文件:", "[语音:")


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ids_sha256(ids: list[str]) -> str:
    return sha256("".join(mid + "\n" for mid in ids).encode()).hexdigest()


def main() -> None:
    # The clean source is authoritative; raw file indices only identify the
    # known diagnostic exclusion via clean-record provenance, not sampling.
    weak_targets: set[str] = set()
    weak_inputs: set[str] = set()
    with WEAK.open() as stream:
        for line in stream:
            case = json.loads(line)
            weak_targets.add(case["target_message_id"])
            weak_inputs.update(case.get("source", {}).get("context_message_ids", []))
            for candidate in case.get("candidate_episodes", []):
                weak_inputs.update(m["message_id"] for m in candidate.get("messages", []))

    judgment_targets: set[str] = set()
    judgment_inputs: set[str] = set()
    for name in ("dev", "test"):
        with (JUDGMENT / f"{name}.jsonl").open() as stream:
            for line in stream:
                case = json.loads(line)
                judgment_targets.add(case["target_message_id"])
                judgment_inputs.update(case.get("source", {}).get("context_message_ids", []))
                for candidate in case.get("candidate_episodes", []):
                    judgment_inputs.update(m["message_id"] for m in candidate.get("messages", []))

    used = weak_targets | weak_inputs | judgment_targets | judgment_inputs
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    windows = {key: {"ids": [], "eligible_ids": [], "first_timestamp": None, "last_timestamp": None}
               for key in ("TRAIN", "DEV", "HOLDOUT")}
    clean_total = 0
    diagnostic_count = 0
    with DATA.open() as stream:
        for line in stream:
            message = json.loads(line)
            clean_total += 1
            mid = message["message_id"]
            source = message["source"]
            if source["file_id"] == DIAGNOSTIC_FILE_ID and 10000 <= source["record_index"] <= 10749:
                diagnostic_count += 1
                used.add(mid)
            # Exclude the entire Judgment HOLDOUT time block without ever
            # reading the Judgment HOLDOUT artifact. Windows are c_000001 only.
            if message["conversation_id"] != "c_000001":
                counts["other_conversation"] += 1
                continue
            month = message["timestamp"][:7]
            if "2026-01" <= month <= "2026-03":
                window = "TRAIN"
            elif month == "2026-04":
                window = "DEV"
            elif month == "2026-05":
                window = "HOLDOUT"
            else:
                counts["outside_frozen_windows"] += 1
                continue
            bucket = windows[window]
            bucket["ids"].append(mid)
            bucket["first_timestamp"] = bucket["first_timestamp"] or message["timestamp"]
            bucket["last_timestamp"] = message["timestamp"]
            if mid in used:
                reasons[f"{window}_previously_used"] += 1
                continue
            text = message.get("text", "").strip()
            if ("system_generated" in message.get("flags", []) or len(text) < 2
                    or BRACKET.match(text) or text.startswith(PREFIXES)):
                reasons[f"{window}_non_case_message"] += 1
                continue
            bucket["eligible_ids"].append(mid)

    result = {
        "goal_id": "laya_322m_hard_negative_ranking_training_p0",
        "previous_blocker": "WRONG_SOURCE_LAYER",
        "status": "SOURCE_WINDOWS_FROZEN_REVIEW_PENDING",
        "frozen_before_model_scoring": True,
        "selection_rule": "c_000001 whole chronological clean-corpus months: TRAIN 2026-01..03, DEV 2026-04, HOLDOUT 2026-05; exclude historical input and target IDs; no model-result selection",
        "source": {"path": str(DATA.relative_to(ROOT)), "sha256": file_sha256(DATA), "clean_corpus_total": clean_total},
        "exclusions": {
            "weak_train_target_ids": len(weak_targets),
            "weak_train_context_and_candidate_ids": len(weak_inputs),
            "judgment_dev_test_target_ids": len(judgment_targets),
            "judgment_dev_test_context_and_candidate_ids": len(judgment_inputs),
            "diagnostic_provenance_ids": diagnostic_count,
            "union_historical_ids": len(used),
            "judgment_holdout_artifact_read": False,
            "per_window_reasons": dict(sorted(reasons.items())),
            "outside_windows": dict(sorted(counts.items())),
        },
        "windows": {},
        "case_minima": {"train_true_continue": 800, "train_true_new": 500, "dev": 300, "holdout": 400},
        "high_confidence_count_verified": False,
        "model_scoring_started": False,
        "semantic_review_started": False,
        "training_started": False,
    }
    for name, bucket in windows.items():
        ids, eligible = bucket["ids"], bucket["eligible_ids"]
        result["windows"][name] = {
            "conversation_id": "c_000001",
            "first_timestamp": bucket["first_timestamp"],
            "last_timestamp": bucket["last_timestamp"],
            "messages": len(ids),
            "source_message_id_sha256": ids_sha256(ids),
            "fresh_eligible_message_count_upper_bound": len(eligible),
            "fresh_eligible_message_id_sha256": ids_sha256(eligible),
        }
    assert diagnostic_count == 750, "Known diagnostic source mapping changed"
    assert len(weak_targets) == 20000, "Weak TRAIN fingerprint/count changed"
    assert result["windows"]["TRAIN"]["fresh_eligible_message_count_upper_bound"] >= 1300
    assert result["windows"]["DEV"]["fresh_eligible_message_count_upper_bound"] >= 300
    assert result["windows"]["HOLDOUT"]["fresh_eligible_message_count_upper_bound"] >= 400
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "window-manifest.json"
    if path.exists():
        assert json.loads(path.read_text()) == result, "Frozen window manifest differs; do not overwrite"
    else:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": str(path), "sha256": file_sha256(path),
                      "source_total": clean_total,
                      "eligible_upper_bounds": {k: v["fresh_eligible_message_count_upper_bound"]
                                                for k, v in result["windows"].items()}}, indent=2))


if __name__ == "__main__":
    main()
