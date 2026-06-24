# ADR-002: FAISS Over Managed Vector Database

**Date:** 2026-04-01  
**Status:** Accepted  
**Deciders:** Solo developer  

## Context
The vector retrieval layer is implemented behind `VectorStoreService` in `backend/app/services/vector_store.py`. The service chooses its backend at runtime in `VectorStoreService._get_backend()`: `FAISSBackend` when `settings.vector_backend == "faiss"`, and `QdrantBackend` when `settings.vector_backend == "qdrant"`. `backend/app/core/config.py` sets the default `vector_backend` to `faiss`.

The FAISS implementation is fully local. `FAISSBackend._get_index()` creates or loads `index.faiss`, and `FAISSBackend._save_index()` persists the index plus `chunks.pkl` under `settings.vector_store_dir`. Embeddings come from `SentenceTransformer(settings.embedding_model)` in `_EmbeddingChunkingMixin._get_embedder()`, which means the vector index can be built entirely from packages declared in `backend/requirements.txt`.

## Decision
Use the local FAISS backend as the default vector store. The current implementation uses `faiss.IndexFlatIP(dim)` in `FAISSBackend._get_index()` and normalizes embeddings in both `FAISSBackend.add_documents()` and `FAISSBackend.search()`. This produces an exact inner-product search over normalized vectors without requiring any external service.

Keep Qdrant as an opt-in alternative rather than the default. The current code already supports that path through `QdrantBackend`, `settings.vector_backend`, `settings.qdrant_url`, and `settings.qdrant_api_key`, but it is not the baseline deployment mode.

## Consequences
**Positive:** The default stack stays self-contained. A local deployment can build and query the vector index without provisioning a managed service, and the on-disk artifacts are explicit: `index.faiss`, `chunks.pkl`, and `deleted_docs.json`. The repository also preserves a migration path because `VectorStoreService` already abstracts Qdrant behind the same interface.  
**Negative:** `IndexFlatIP` is an exact scan structure, so search cost grows linearly with the number of indexed vectors. Because FAISS lacks native metadata filtering in `IndexFlatIP`, filtering is implemented inside Python using an overfetching (retrieving `top_k * 4` candidates or the entire index when filters are active) and post-filtering technique. True native index-level filtering is only supported natively by the Qdrant backend.  
**Risks:** The index dimension is taken from `settings.embedding_dim` in `FAISSBackend._get_index()`, while the actual embedding dimension comes from the configured sentence-transformers model. If those values diverge, index creation and document insertion can fail. The backend also relies on local filesystem persistence, so deployments still need durable storage for `vector_store_dir`. Furthermore, FAISS has no built-in access control or encryption, meaning it is not HIPAA-certified or secure for raw PHI in production without external encryption-at-rest.

## Alternatives Considered
| Alternative | Why Rejected |
|-------------|--------------|
| Qdrant as the default backend | `QdrantBackend` is implemented, but it requires `QDRANT_URL` and introduces a network dependency that the default FAISS path does not have. |
| Managed vector database as the primary design | No managed vendor integration exists in the current codebase. Adopting one would add operational dependencies that the present local FAISS implementation avoids. |
| Remove backend abstraction and hard-code FAISS only | The repository already carries a viable Qdrant path, so removing the abstraction would make future migration harder without simplifying caller code much. |
