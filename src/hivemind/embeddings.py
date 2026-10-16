"""Text embeddings for semantic recall.

Default is a local ONNX model (BAAI/bge-small-en-v1.5 via fastembed): no API
key, ~15 ms per text, 384 dimensions. A deterministic hashing embedder with
the same dimension is used for tests, benchmarks and fully offline setups."""

from __future__ import annotations

import hashlib
import math
import re
import threading

DIM = 384


class HashEmbedder:
    """Feature-hashed bag of words + character trigrams. Deterministic and fast."""

    name = "hash"
    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = re.findall(r"[a-z0-9_]+", text.lower())
        feats = words + [w[i:i + 3] for w in words for i in range(max(1, len(w) - 2))]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            vec[h % self.dim] += 1.0 if (h >> 63) == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FastEmbedder:
    name = "fastembed"
    dim = DIM
    model_name = "BAAI/bge-small-en-v1.5"

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(self.model_name, cache_dir=self.cache_dir)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        out = []
        for v in model.embed(texts):
            norm = float(math.sqrt(float((v * v).sum()))) or 1.0
            out.append([float(x) / norm for x in v])
        return out


def make_embedder(kind: str, cache_dir: str):
    if kind == "hash":
        return HashEmbedder()
    return FastEmbedder(cache_dir)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
