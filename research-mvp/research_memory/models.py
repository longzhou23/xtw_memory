"""Independent local BGE adapter. Model files can be shared with the first MVP."""
import collections
import hashlib
import json
import math
import os
import re
from pathlib import Path

from .contracts import Invalid

HASHES = {
    "embedding": {"model.onnx": "15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc",
                  "tokenizer.json": "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
                  "config.json": "d4193ead3a810fd694fa8a31d7fc72fbaebc0668b603e398734bf2f6538ff42f"},
    "reranker": {"model_fp32.onnx": "15b9a8c3da82eddf263df571281166e00e9308fe19d077084b642ebfcaf06d2b",
                 "tokenizer.json": "48564c5c7d3fa64d85d95e65414a542385f88b0f128fd8d4163fd7a57f2be05c",
                 "config.json": "b6575b9d5be20d6747417c8e20c5a0db1636356e0b6d422d7244c628423c4d4c"},
}
class LocalModels:
    name = "bge-small-zh-v1.5-int8-single-document + bge-reranker-base-fp32"
    embedding_recipe = "single-document-int8-v1"
    min_score = -1.0

    def __init__(self, directory=None):
        self.root = Path(directory or os.environ.get("XTW_RESEARCH_MODELS", Path(__file__).resolve().parents[2] / "models/semantic"))
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
            manifest = json.loads((self.root / "manifest.json").read_text())
            for name, files in HASHES.items():
                for filename, expected in files.items():
                    hasher = hashlib.sha256()
                    with (self.root / name / filename).open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            hasher.update(block)
                    if hasher.hexdigest() != expected:
                        raise ValueError("模型指纹不匹配")
            self.np, self.sessions, self.tokenizers = np, {}, {}
            for name in HASHES:
                path = self.root / name
                config = json.loads((path / "config.json").read_text())
                tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
                tokenizer.enable_truncation(max_length=256)
                pad = "[PAD]" if name == "embedding" else "<pad>"
                tokenizer.enable_padding(pad_id=config.get("pad_token_id", tokenizer.token_to_id(pad)), pad_token=pad)
                settings = ort.SessionOptions()
                settings.intra_op_num_threads = 2
                settings.inter_op_num_threads = 1
                self.sessions[name] = ort.InferenceSession(str(path / next(f for f in HASHES[name] if f.endswith(".onnx"))), settings, providers=["CPUExecutionProvider"])
                self.tokenizers[name] = tokenizer
            self.manifest_fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
            self.fingerprint = hashlib.sha256(json.dumps({"manifestFingerprint": self.manifest_fingerprint,
                "embeddingRecipe": self.embedding_recipe}, sort_keys=True).encode()).hexdigest()
        except (ImportError, OSError, ValueError, RuntimeError) as error:
            raise Invalid("本地BGE模型不可用：安装requirements.txt并设置XTW_RESEARCH_MODELS；不会静默改用词面评分") from error
        self.cache = collections.OrderedDict()
        self.counts = collections.Counter()

    def run(self, name, values):
        self.counts[name] += len(values)
        tokens = self.tokenizers[name].encode_batch(values)
        data = {"input_ids": self.np.asarray([t.ids for t in tokens], dtype=self.np.int64),
                "attention_mask": self.np.asarray([t.attention_mask for t in tokens], dtype=self.np.int64),
                "token_type_ids": self.np.asarray([t.type_ids for t in tokens], dtype=self.np.int64)}
        result = self.sessions[name].run(None, {k: data[k] for k in (i.name for i in self.sessions[name].get_inputs())})[0]
        if not self.np.isfinite(result).all():
            raise Invalid("模型返回非有限数值")
        return result, [bool(t.overflowing) for t in tokens]

    def vectors(self, texts, query=False):
        keys = [(query, body) for body in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in self.cache))
        # Dynamic INT8 activation scales depend on other documents in a batch.
        # Encode independently so cache state and index chunking cannot change a vector.
        for flag, body in missing:
            value = ("为这个句子生成表示以用于检索相关文章：" if flag else "") + body
            result, clips = self.run("embedding", [value])
            vector = result[0, 0, :].astype(self.np.float32)
            norm = self.np.linalg.norm(vector)
            if norm <= 0:
                raise Invalid("模型返回零范数向量")
            self.cache[(flag, body)] = (vector / norm, clips[0])
        selected = [self.cache[key] for key in keys]
        while len(self.cache) > 10000:
            self.cache.popitem(last=False)
        return self.np.asarray([v for v, _ in selected]), [c for _, c in selected]

    def similarity(self, query, texts):
        if not texts:
            return [], []
        q, qc = self.vectors([query], query=True)
        vectors, clips = self.vectors(texts)
        return [float(v) for v in vectors @ q[0]], [clip or qc[0] for clip in clips]

    def rerank(self, query, texts):
        scores, clips = [], []
        for start in range(0, len(texts), 8):
            result, flags = self.run("reranker", [(query, t) for t in texts[start:start + 8]])
            scores.extend(float(v) for v in result.reshape(-1))
            clips.extend(flags)
        return scores, clips


class LexicalDiagnostic:
    name = "lexical-diagnostic (NOT semantic retrieval)"
    fingerprint = "unicode-bigram-cosine-v1"
    min_score = .05

    def __init__(self):
        self.counts = collections.Counter()

    @staticmethod
    def vector(body):
        parts = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", body.lower())
        return collections.Counter(parts + [a + b for a, b in zip(parts, parts[1:])])

    def similarity(self, query, texts):
        self.counts["lexicalPairs"] += len(texts)
        q = self.vector(query)
        scores = []
        for body in texts:
            vector = self.vector(body)
            denominator = math.sqrt(sum(v*v for v in q.values()) * sum(v*v for v in vector.values()))
            scores.append(sum(v * vector[k] for k, v in q.items()) / denominator if denominator else 0)
        return scores, [False] * len(texts)

    def rerank(self, query, texts):
        self.counts["reranker"] += len(texts)
        return self.similarity(query, texts)


def model(name):
    if name == "local":
        return LocalModels()
    if name == "lexical":
        return LexicalDiagnostic()
    raise Invalid("reader 必须为 local 或 lexical")
