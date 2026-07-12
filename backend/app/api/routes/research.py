import uuid

from anyio import to_thread
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import research_signals_collection
from app.schemas.ai import VectorSearchRequest
from app.schemas.research import IngestResult, ResearchSignalOut

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/ideas", response_model=list[ResearchSignalOut])
async def ideas(
    limit: int = Query(30, ge=1, le=200),
    symbol: str | None = None,
    _current_user: dict = Depends(get_current_user),
):
    query: dict = {}
    if symbol:
        query["symbol"] = symbol.upper()
    cursor = research_signals_collection.find(query).sort("timestamp", -1).limit(limit)
    docs = []
    async for doc in cursor:
        docs.append(
            ResearchSignalOut(
                id=str(doc["_id"]),
                symbol=doc["symbol"],
                timeframe=doc["timeframe"],
                signal=doc["signal"],
                confidence=doc["confidence"],
                source=doc["source"],
                timestamp=doc["timestamp"].isoformat() if hasattr(doc["timestamp"], "isoformat") else doc["timestamp"],
                reasoning=doc["reasoning"],
                link=doc.get("link"),
            )
        )
    return docs


@router.post("/ingest", response_model=IngestResult)
async def ingest(_current_user: dict = Depends(get_current_user)):
    from research_service.ingest import ingest_all

    counts = await to_thread.run_sync(ingest_all)
    return IngestResult(counts=counts)


@router.get("/vector/status")
async def vector_status(_current_user: dict = Depends(get_current_user)):
    from vector_service import get_embedder

    _embedder, mode = get_embedder()
    return {"mode": mode}


@router.post("/vector/search")
async def vector_search(request: VectorSearchRequest, _current_user: dict = Depends(get_current_user)):
    from vector_service import VectorStore, get_embedder, search

    embedder, mode = get_embedder()
    store = VectorStore()
    hits = await search(store, embedder, request.collection, request.query, limit=request.limit)
    return {"mode": mode, "hits": hits}


@router.post("/vector/index-research")
async def vector_index_research(limit: int = Query(200, ge=1, le=1000), _current_user: dict = Depends(get_current_user)):
    from vector_service import VectorStore, get_embedder, index_documents

    embedder, mode = get_embedder()
    store = VectorStore()

    cursor = research_signals_collection.find({}).sort("timestamp", -1).limit(limit)
    ids, texts, payloads = [], [], []
    async for doc in cursor:
        # Qdrant point IDs must be an unsigned int or a UUID — Mongo ObjectId hex
        # strings are neither, so derive a stable UUID5 from the ObjectId instead.
        ids.append(str(uuid.uuid5(uuid.NAMESPACE_OID, str(doc["_id"]))))
        texts.append(doc["reasoning"])
        payloads.append({"mongo_id": str(doc["_id"]), "symbol": doc["symbol"], "source": doc["source"], "reasoning": doc["reasoning"]})

    if not ids:
        return {"status": "no_data", "message": "no research signals to index"}

    count = await index_documents(store, embedder, "research_signals", ids, texts, payloads)
    return {"mode": mode, "indexed": count}
