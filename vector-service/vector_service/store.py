"""Thin wrapper over the Qdrant client already running via docker-compose (Phase 1) —
this is the first code that actually uses it. Collections are created on first use
with whatever vector dimension the active embedder reports."""

import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


class VectorStore:
    def __init__(self, url: str | None = None):
        self.client = QdrantClient(url=url or os.getenv("QDRANT_URL", "http://localhost:6333"))

    def ensure_collection(self, name: str, dim: int) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name, vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
            )

    def upsert(self, collection: str, dim: int, ids: list, vectors: list[list[float]], payloads: list[dict]) -> int:
        self.ensure_collection(collection, dim)
        points = [PointStruct(id=i, vector=v, payload=p) for i, v, p in zip(ids, vectors, payloads)]
        self.client.upsert(collection_name=collection, points=points)
        return len(points)

    def search(self, collection: str, dim: int, query_vector: list[float], limit: int = 5) -> list[dict]:
        self.ensure_collection(collection, dim)
        hits = self.client.query_points(collection_name=collection, query=query_vector, limit=limit).points
        return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]
