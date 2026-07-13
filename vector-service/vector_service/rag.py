"""High-level RAG operations: index research signals / trade explanations, then search
by natural-language query. Everything here is embedder-agnostic — swap the embedder
returned by `embeddings.get_embedder()` for a real semantic one with no other changes."""

from vector_service.embeddings import Embedder
from vector_service.store import VectorStore

RESEARCH_COLLECTION = "research_signals"


async def index_documents(
    store: VectorStore, embedder: Embedder, collection: str, ids: list, texts: list[str], payloads: list[dict]
) -> dict:
    vectors = await embedder.embed(texts)
    count = store.upsert(collection, embedder.dim, ids, vectors, payloads)
    return {"indexed": count, "collection": collection}


async def search(store: VectorStore, embedder: Embedder, collection: str, query: str, limit: int = 5) -> list[dict]:
    vectors = await embedder.embed([query])
    return store.search(collection, embedder.dim, vectors[0], limit=limit)
