"""TradingAI RAG store wrapping Qdrant (roadmap Phase 6). See `embeddings.py` for the
honest semantic-vs-placeholder embedder status."""

from vector_service.embeddings import get_embedder
from vector_service.rag import index_documents, search
from vector_service.store import VectorStore

__all__ = ["VectorStore", "get_embedder", "index_documents", "search"]
