import os
import sys
import glob

# Add all required uv archives to sys.path
UV_BASE = "/home/longzhooou/.cache/uv/archive-v0"
for p in sorted(glob.glob(UV_BASE + "/*")):
    if p not in sys.path:
        sys.path.insert(0, p)

LAYA_PKG = "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ"
if LAYA_PKG not in sys.path:
    sys.path.insert(0, LAYA_PKG)

# Set up LD_LIBRARY_PATH for CUDA dynamic libraries
cuda_libs = glob.glob(UV_BASE + "/*/nvidia/*/lib")
current_ld = os.environ.get("LD_LIBRARY_PATH", "")
os.environ["LD_LIBRARY_PATH"] = ":".join(cuda_libs) + (":" + current_ld if current_ld else "")

# Monkeypatch torch native bmm outer product to avoid triton JIT compilation without Python.h
import torch
try:
    import torch._native.ops.bmm_outer_product.triton_kernels as tk
    tk.bmm_outer_product = lambda a, b: a * b
except Exception:
    pass

import laya
from laya.common import build_sequence, collate_items, DecisionModel

BASE_CHECKPOINT_DIR = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/runs/322m-20k/best-dev"
BASE_CHECKPOINT_SHA256 = "05688142b1501bb193253f1bbd5947f8fa7e91d9db2cdcf4ea3215d73d53fcfc"
RESULTS_DIR = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/router-v0.2-two-stage-smoke-v0.1"

TRAIN_DATA_PATH = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/dataset/semantic-hard-negative-silver-v0.1/train.jsonl"
DEV_DATA_PATH = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/dataset/semantic-hard-negative-silver-v0.1/dev.jsonl"
RAW_WINDOW_150_PATH = "/home/longzhooou/Documents/Programs/小天文设计素材/memory-demo/benchmark-results/real-episode-temporary-fabric-laya-20k-p0/raw-window.jsonl"
