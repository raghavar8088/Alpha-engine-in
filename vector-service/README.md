# vector-service

Wraps the Qdrant container that's been running unused since Phase 1 (roadmap Phase 6).

## Honest embedding status

**Anthropic has no first-party embeddings API** (confirmed against the current Claude
API docs while building this — the Messages API has no embed endpoint). Semantic
embedding needs a separate provider; Voyage AI is Anthropic's documented recommendation,
but no key is configured yet. `embeddings.get_embedder()` returns `(embedder, mode)`:

- `mode == "placeholder"` today — `PlaceholderHashEmbedder`, a deterministic bag-of-
  words hash vector. It is **not semantic** (clusters by shared vocabulary, not
  meaning) and exists solely to prove the Qdrant plumbing works end-to-end without a
  real provider key.
- `mode == "semantic"` once a real embedder is wired in (e.g. set `VOYAGE_API_KEY` and
  implement `VoyageEmbedder` — currently raises `NotImplementedError` with that message
  rather than silently running in placeholder mode).

Every caller must read `mode` and surface it — never present placeholder-mode results
as semantic search.

## Verified live

Indexed 50 real `research_signals` documents (from research-service's live RSS
ingestion) into Qdrant and queried:

- `"Reliance Industries stock market selloff"` → top hit: the Reliance market-value
  article (score 0.336)
- `"FMCG healthcare consumer goods"` → top hit: the FMCG/healthcare-earnings article
  (score 0.533)

Both correct by shared vocabulary, exactly what the placeholder embedder promises — not
evidence of semantic understanding, but proof the store/upsert/search path is wired
correctly and ready for a real embedder to be dropped in.

## Usage

```python
from vector_service import VectorStore, get_embedder, index_documents, search

embedder, mode = get_embedder()  # mode: "placeholder" today
store = VectorStore()  # reads QDRANT_URL, defaults to http://localhost:6333

await index_documents(store, embedder, "research_signals", ids, texts, payloads)
hits = await search(store, embedder, "research_signals", "your query", limit=5)
```
