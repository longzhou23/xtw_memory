"""Test suite for Laya Episode Routing Training & Checkpoint Verification."""

import hashlib
import json
from pathlib import Path
import pytest
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / "benchmark-results" / "laya-episode-routing-weak-silver-v0.1"
SPLITS_DIR = BASE_DIR / "judgment" / "v0.1.0" / "splits"

LAYA_PKG_PATH = "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ"
if LAYA_PKG_PATH not in sys.path:
    sys.path.insert(0, LAYA_PKG_PATH)


def test_holdout_fingerprint_sealed():
    """Verify HOLDOUT was never touched or modified."""
    holdout_path = SPLITS_DIR / "holdout.jsonl"
    assert holdout_path.exists()
    h = hashlib.sha256()
    with open(holdout_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    assert h.hexdigest() == "400caf54e3efff7832df1707341aaefe207af28d03533948b9f3f53b37def474"


def test_nested_subsets():
    """Verify train-1k ⊂ train-2k ⊂ train-2800."""
    subsets_dir = RESULTS_DIR / "data-subsets"
    with open(subsets_dir / "train-1k.jsonl") as f:
        ids_1k = {json.loads(line)["case_id"] for line in f}
    with open(subsets_dir / "train-2k.jsonl") as f:
        ids_2k = {json.loads(line)["case_id"] for line in f}
    with open(subsets_dir / "train-2800.jsonl") as f:
        ids_2800 = {json.loads(line)["case_id"] for line in f}

    assert len(ids_1k) == 1000
    assert len(ids_2k) == 2000
    assert len(ids_2800) == 2800
    assert ids_1k.issubset(ids_2k)
    assert ids_2k.issubset(ids_2800)


def test_checkpoint_reloading():
    """Verify best-dev checkpoint can be reloaded by laya.load using python 3.12 venv."""
    import subprocess
    ckpt_path = RESULTS_DIR / "runs" / "322m-2800" / "best-dev"
    assert ckpt_path.exists()

    verify_script = f"""
import sys
sys.path.insert(0, {repr(LAYA_PKG_PATH)})
import laya

agent = laya.load({repr(str(ckpt_path))}, device='cpu')
q = {{
    'route': {{
        'type': 'choice',
        'instructions': '判断当前目标消息属于哪个 Episode？',
        'criteria': {{
            'cand_1': '话题线程: 迎新活动',
            'NEW': '新话题',
            'UNKNOWN': '信息不足'
        }}
    }}
}}
res = agent.predict('当前消息: 请问迎新几点结束？', q)
assert 'answers' in res and 'route' in res['answers']
assert res['answers']['route']['choice'] in ('cand_1', 'NEW', 'UNKNOWN')
print('VERIFY_SUCCESS')
"""
    res = subprocess.run(
        ["/tmp/opencode/qwen-alt/venv/bin/python", "-c", verify_script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "VERIFY_SUCCESS" in res.stdout, f"Reload failed: {res.stderr}"


def test_data_scaling_monotonicity():
    """Verify DEV Macro F1 improves monotonically with training data scale (Phase I)."""
    manifest_path = RESULTS_DIR / "manifest.json"
    with open(manifest_path) as f:
        m = json.load(f)

    f1_1k = m["completed_runs"]["322m-1k"]["best_dev_macro_f1"]
    f1_2k = m["completed_runs"]["322m-2k"]["best_dev_macro_f1"]
    f1_2800 = m["completed_runs"]["322m-2800"]["best_dev_macro_f1"]

    assert f1_1k > 0.40, f"1k F1 too low: {f1_1k}"
    assert f1_2k > f1_1k, f"Scaling regression from 1k to 2k: {f1_1k} >= {f1_2k}"
    assert f1_2800 > f1_2k, f"Scaling regression from 2k to 2.8k: {f1_2k} >= {f1_2800}"


def test_phase2_nested_subsets_and_monotonicity():
    """Verify Phase II nested subsets 2.8k ⊂ 5k ⊂ 10k ⊂ 20k and scaling monotonicity."""
    p2_dir = BASE_DIR / "benchmark-results" / "laya-episode-routing-weak-silver-scaling-v0.2"
    assert p2_dir.exists(), "Phase II directory missing"

    with open(p2_dir / "data" / "subset-manifest.json") as f:
        sm = json.load(f)

    assert sm["subsets"]["train-2800"]["sha256"] == "ed079c9558bea1b7d6bf1ba313d4b6f678df7200d1a8e279333f31c39ad4904a"

    with open(p2_dir / "manifest.json") as f:
        m2 = json.load(f)

    f1_28k = 0.5786
    f1_5k = m2["completed_runs"]["322m-5k"]["best_dev_macro_f1"]
    f1_10k = m2["completed_runs"]["322m-10k"]["best_dev_macro_f1"]
    f1_20k = m2["completed_runs"]["322m-20k"]["best_dev_macro_f1"]

    assert f1_5k > f1_28k, f"Scaling regression 2.8k -> 5k: {f1_28k} >= {f1_5k}"
    assert f1_10k > f1_5k, f"Scaling regression 5k -> 10k: {f1_5k} >= {f1_10k}"
    assert f1_20k > f1_10k, f"Scaling regression 10k -> 20k: {f1_10k} >= {f1_20k}"


def test_20k_checkpoint_reloading():
    """Verify 20k checkpoint can be cleanly reloaded and predict."""
    import subprocess
    p2_dir = BASE_DIR / "benchmark-results" / "laya-episode-routing-weak-silver-scaling-v0.2"
    ckpt_20k = p2_dir / "runs" / "322m-20k" / "best-dev"
    assert ckpt_20k.exists()

    verify_script = f"""
import sys
sys.path.insert(0, {repr(LAYA_PKG_PATH)})
import laya

agent = laya.load({repr(str(ckpt_20k))}, device='cpu')
q = {{
    'route': {{
        'type': 'choice',
        'instructions': '当前目标消息属于哪个 Episode？',
        'criteria': {{
            'cand_1': '话题: 迎新活动',
            'NEW': '新话题',
            'UNKNOWN': '信息不足'
        }}
    }}
}}
res = agent.predict('当前消息: 迎新什么时候开始？', q)
assert 'answers' in res and 'route' in res['answers']
assert res['answers']['route']['choice'] in ('cand_1', 'NEW', 'UNKNOWN')
print('VERIFY_20K_SUCCESS')
"""
    res = subprocess.run(
        ["/tmp/opencode/qwen-alt/venv/bin/python", "-c", verify_script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "VERIFY_20K_SUCCESS" in res.stdout, f"20k Reload failed: {res.stderr}"
