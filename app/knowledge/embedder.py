"""Deterministic lexical feature hashing in the local Vector Database."""

from __future__ import annotations

import hashlib
import math
import re
from typing import List

DIMENSION = 256


def get_embedding(text: str, dim: int = DIMENSION) -> list[float]:
    """Generates a normalized lexical feature vector for a given text passage."""
    text = (text or "").lower().strip()
    if not text:
        return [0.0] * dim

    vec = [0.0] * dim
    words = re.findall(r"\b[a-z0-9_\-]{2,}\b", text)
    if not words:
        return [0.0] * dim

    # 1. Unigram feature weights
    for w in words:
        h = int(hashlib.sha256(w.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dim
        # Length-based weight (not inverse document frequency)
        weight = 1.0 + min(len(w) * 0.1, 1.5)
        vec[idx] += weight

    # 2. Bigram context weights
    for i in range(len(words) - 1):
        bg = f"{words[i]}_{words[i + 1]}"
        h = int(hashlib.sha256(bg.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dim
        vec[idx] += 2.0

    # 3. Subword character trigrams for morphological similarity (e.g. "impersonat" in "impersonation", "impersonating")
    for w in words:
        if len(w) >= 4:
            for j in range(len(w) - 2):
                tri = w[j : j + 3]
                h = int(hashlib.sha256(tri.encode("utf-8")).hexdigest()[:8], 16)
                idx = h % dim
                vec[idx] += 0.4

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


def get_embeddings_batch(texts: List[str], dim: int = DIMENSION) -> List[list[float]]:
    """Generates embeddings for a batch of text passages."""
    return [get_embedding(t, dim) for t in texts]


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculates cosine similarity between two normalized vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    return sum(a * b for a, b in zip(v1, v2))
