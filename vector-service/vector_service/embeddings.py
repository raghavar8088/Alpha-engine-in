"""Pluggable embedding backends. Anthropic has NO first-party embeddings API (confirmed
against the current Claude API docs while building this) — semantic embedding needs a
separate provider (Voyage AI is Anthropic's documented recommendation). None is
configured today, so this module's default is `PlaceholderHashEmbedder`: a deterministic
bag-of-words hash vector that proves the Qdrant plumbing (collection/upsert/search)
really works end-to-end, but is NOT semantic — it clusters by shared vocabulary, not
meaning. `get_embedder()` returns which mode is active so callers can show an honest
status rather than silently presenting placeholder results as real RAG."""

import hashlib
import os
import re
from typing import Protocol


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class PlaceholderHashEmbedder:
    """NOT semantic — a deterministic hashed bag-of-words vector (cosine similarity
    over shared words). Exists only to verify the vector-store plumbing without a real
    embedding provider key. Replace with a real embedder before trusting search
    relevance for anything user-facing."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_vector(t) for t in texts]

    def _hash_vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm > 0 else vec


def get_embedder() -> tuple[Embedder, str]:
    """Returns (embedder, mode) where mode is "semantic" once a real provider key is
    configured, else "placeholder". Only one real-provider check exists today
    (Voyage AI, Anthropic's documented embeddings partner) and it's a documented
    not-yet-implemented gap, not a silent fallback."""
    if os.getenv("VOYAGE_API_KEY"):
        raise NotImplementedError(
            "VOYAGE_API_KEY is set but no Voyage AI client is wired up yet — "
            "add a VoyageEmbedder implementation before relying on it"
        )
    return PlaceholderHashEmbedder(), "placeholder"
