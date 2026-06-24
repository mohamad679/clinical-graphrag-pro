"""
Vector store abstraction with FAISS default and optional Qdrant backend.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pickle
import re
import threading
import time
import uuid
from typing import Callable, NamedTuple, Protocol, TypeVar, runtime_checkable

import numpy as np

from app.core.config import get_settings
from app.core.metrics import observe_vector_search, observe_dense_search, record_retrieved_chunks
from app.core.observability import trace_operation
from app.core.retrieval_scope import exact_scope_match

logger = logging.getLogger(__name__)
WriteOperationResult = TypeVar("WriteOperationResult")


class SearchResult(NamedTuple):
    """A single search result from the vector store."""

    chunk_text: str
    chunk_index: int
    document_id: str
    document_name: str
    score: float
    chunk_id: str = ""
    page_start: int | None = None
    page_end: int | None = None
    source_offset_start: int | None = None
    source_offset_end: int | None = None


@runtime_checkable
class VectorStoreBackend(Protocol):
    """Backend contract shared by FAISS and Qdrant implementations."""

    def add_documents(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: dict | None = None,
        chunks: list[dict] | None = None,
    ) -> int: ...

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[SearchResult]: ...

    def delete_document(self, document_id: str) -> int: ...

    def get_stats(self) -> dict: ...

    def get_all_chunks(self, filters: dict | None = None) -> list[dict]: ...

    def get_chunks_for_document(
        self,
        document_id: str,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[dict]: ...


class _EmbeddingChunkingMixin:
    """Shared embedding and chunking helpers."""

    def __init__(self):
        self._embedder = None

    @staticmethod
    def _deterministic_embed(texts: list[str], *, normalize_embeddings: bool = True, **_: object) -> np.ndarray:
        settings = get_settings()
        dim = max(int(settings.embedding_dim), 1)
        rows: list[np.ndarray] = []
        for text in texts:
            vector = np.zeros(dim, dtype=np.float32)
            tokens = re.findall(r"[a-zA-Z0-9_]+", str(text).lower())
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[index] += sign
            if normalize_embeddings:
                norm = float(np.linalg.norm(vector))
                if norm > 0:
                    vector /= norm
            rows.append(vector)
        return np.vstack(rows) if rows else np.empty((0, dim), dtype=np.float32)

    def _get_embedder(self):
        if hasattr(self, "_parent") and hasattr(self._parent, "_get_embedder"):
            parent_method = self._parent._get_embedder
            func = getattr(parent_method, "__func__", parent_method)
            if func is not getattr(VectorStoreService, "_get_embedder", None):
                return parent_method()
        if self._embedder is None:
            settings = get_settings()
            if settings.offline_demo_mode or settings.embedding_model in {"deterministic-local", "local-deterministic", "hash-embedding"}:
                logger.warning(
                    "OFFLINE_DEMO_MODE is active. Using hash-based embeddings. "
                    "These have NO semantic meaning. Do not run retrieval benchmarks "
                    "in this mode."
                )
                self._embedder = type(
                    "DeterministicLocalEmbedder",
                    (),
                    {"encode": staticmethod(self._deterministic_embed)},
                )()
                logger.info("Loaded deterministic local embedder (dim=%s)", settings.embedding_dim)
                return self._embedder

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - env dependent
                logger.warning(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
                raise exc

            self._embedder = SentenceTransformer(settings.embedding_model)
            logger.info("Loaded embedding model: %s", settings.embedding_model)
        return self._embedder

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        text = re.sub(
            r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|vs|etc|e\.g|i\.e)\.\s",
            r"\1<DOT> ",
            text,
        )
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s.replace("<DOT>", ".") for s in sentences]
        return [s.strip() for s in sentences if s.strip()]

    def chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        chunks: list[dict] = []
        current_words: list[str] = []
        current_sentences: list[str] = []

        for sentence in sentences:
            sentence_words = sentence.split()
            if current_words and len(current_words) + len(sentence_words) > chunk_size:
                chunks.append({"chunk_id": str(uuid.uuid4()), "text": " ".join(current_words)})

                overlap_words: list[str] = []
                overlap_sents: list[str] = []
                for previous in reversed(current_sentences):
                    previous_words = previous.split()
                    if len(overlap_words) + len(previous_words) > overlap:
                        break
                    overlap_words = previous_words + overlap_words
                    overlap_sents = [previous] + overlap_sents

                current_words = overlap_words
                current_sentences = overlap_sents

            current_words.extend(sentence_words)
            current_sentences.append(sentence)

        if current_words:
            chunks.append({"chunk_id": str(uuid.uuid4()), "text": " ".join(current_words)})

        return chunks


class FAISSBackend(_EmbeddingChunkingMixin):
    """FAISS-based vector backend persisted locally on disk."""

    def __init__(self):
        super().__init__()
        self._index = None
        self._write_lock: asyncio.Lock | None = None
        self._thread_write_lock = threading.RLock()
        self._chunks: list[dict] = []
        self._store_path = get_settings().vector_store_dir
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._deleted_docs_path = self._store_path / "deleted_docs.json"
        self._deleted_document_ids: set[str] = set()
        self._doc_chunk_lookup: dict[str, list[int]] = {}
        self._load_deleted_documents()

    def _get_index(self):
        if hasattr(self, "_parent") and hasattr(self._parent, "_get_index"):
            parent_method = self._parent._get_index
            func = getattr(parent_method, "__func__", parent_method)
            if func is not getattr(VectorStoreService, "_get_index", None):
                return parent_method()
        if self._index is None:
            try:
                import faiss
            except ImportError as exc:  # pragma: no cover - env dependent
                logger.warning("faiss-cpu not installed. Install with: pip install faiss-cpu")
                raise exc

            index_path = self._store_path / "index.faiss"
            meta_path = self._store_path / "chunks.pkl"
            metadata_path = self._store_path / "index_metadata.json"
            settings = get_settings()

            if index_path.exists() and meta_path.exists():
                if not metadata_path.exists():
                    logger.error("FAISS index files exist but index_metadata.json is missing.")
                    raise ValueError(
                        "Index files exist but metadata is missing, which could lead to inconsistent dimensions. "
                        "Please delete the existing index files or rebuild the index to start fresh."
                    )
                
                with open(metadata_path, "r", encoding="utf-8") as handle:
                    metadata = json.load(handle)
                
                stored_model = metadata.get("embedding_model")
                stored_dim = metadata.get("embedding_dimension")
                
                if stored_model != settings.embedding_model:
                    logger.error(
                        "Embedding model mismatch! Stored: %s, Configured: %s",
                        stored_model, settings.embedding_model
                    )
                    raise ValueError(
                        f"Embedding model mismatch. The stored index uses '{stored_model}' "
                        f"but the configured model is '{settings.embedding_model}'. "
                        "Please delete the index directory or rebuild the index."
                    )
                
                if stored_dim != settings.embedding_dim:
                    logger.error(
                        "Embedding dimension mismatch! Stored: %s, Configured: %s",
                        stored_dim, settings.embedding_dim
                    )
                    raise ValueError(
                        f"Embedding dimension mismatch. The stored index uses {stored_dim}-dimensional "
                        f"embeddings but the configured dimension is {settings.embedding_dim}. "
                        "Please delete the index directory or rebuild the index."
                    )

                self._index = faiss.read_index(str(index_path))
                
                if self._index.d != settings.embedding_dim:
                    logger.error(
                        "FAISS index internal dimension (%s) does not match settings (%s)",
                        self._index.d, settings.embedding_dim
                    )
                    raise ValueError(
                        f"FAISS index internal dimension ({self._index.d}) does not match "
                        f"configured settings.embedding_dim ({settings.embedding_dim})."
                    )

                with open(meta_path, "rb") as handle:
                    self._chunks = pickle.load(handle)
                logger.info("Loaded FAISS index with %s vectors", self._index.ntotal)
            else:
                dim = settings.embedding_dim
                self._index = faiss.IndexFlatIP(dim)
                logger.info("Created new FAISS index (dim=%s)", dim)
            self._rebuild_lookup()
        return self._index

    async def _run_with_async_write_lock(
        self,
        operation: Callable[[], WriteOperationResult],
    ) -> WriteOperationResult:
        if self._write_lock is None:
            with self._thread_write_lock:
                return operation()
        async with self._write_lock:
            with self._thread_write_lock:
                return operation()

    def _run_write_locked(
        self,
        operation: Callable[[], WriteOperationResult],
    ) -> WriteOperationResult:
        if self._write_lock is None:
            with self._thread_write_lock:
                return operation()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run_with_async_write_lock(operation))
        with self._thread_write_lock:
            return operation()

    def _save_index(self):
        def persist() -> None:
            import faiss
            from datetime import datetime, timezone

            faiss.write_index(self._index, str(self._store_path / "index.faiss"))
            with open(self._store_path / "chunks.pkl", "wb") as handle:
                pickle.dump(self._chunks, handle)
            
            settings = get_settings()
            metadata = {
                "embedding_model": settings.embedding_model,
                "embedding_dimension": settings.embedding_dim,
                "index_type": "FAISS_IndexFlatIP",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "chunking_strategy": "sentence-split"
            }
            with open(self._store_path / "index_metadata.json", "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)

        self._run_write_locked(persist)

    def _load_deleted_documents(self):
        if not self._deleted_docs_path.exists():
            self._deleted_document_ids = set()
            return

        try:
            raw = json.loads(self._deleted_docs_path.read_text(encoding="utf-8"))
            self._deleted_document_ids = {str(item) for item in raw} if isinstance(raw, list) else set()
        except Exception:
            logger.warning("Failed to load deleted_docs.json; starting with empty deleted set.")
            self._deleted_document_ids = set()

    def _save_deleted_documents(self):
        if hasattr(self, "_parent") and hasattr(self._parent, "_save_deleted_documents"):
            parent_method = self._parent._save_deleted_documents
            func = getattr(parent_method, "__func__", parent_method)
            if func is not getattr(VectorStoreService, "_save_deleted_documents", None):
                return parent_method()
        try:
            payload = sorted(self._deleted_document_ids)
            self._deleted_docs_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist deleted docs registry: %s", exc)

    def _rebuild_lookup(self):
        lookup: dict[str, list[int]] = {}
        for idx, chunk in enumerate(self._chunks):
            document_id = str(chunk.get("document_id", ""))
            if not document_id or document_id in self._deleted_document_ids:
                continue
            lookup.setdefault(document_id, []).append(idx)
        self._doc_chunk_lookup = lookup

    def add_documents(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: dict | None = None,
        chunks: list[dict] | None = None,
    ) -> int:
        document_id = str(document_id)
        with trace_operation(
            "vector.add_documents",
            component="vector_store",
            logger_=logger,
            backend="faiss",
            document_id=document_id,
        ):
            def add_chunks() -> int:
                embedder = self._get_embedder()
                index = self._get_index()

                if document_id in self._deleted_document_ids:
                    self._deleted_document_ids.discard(document_id)
                    self._save_deleted_documents()

                chunk_dicts = chunks or self.chunk_text(text, chunk_size, overlap)
                if not chunk_dicts:
                    return 0

                chunk_texts = [chunk.get("chunk_text") or chunk.get("text", "") for chunk in chunk_dicts]
                embeddings = embedder.encode(chunk_texts, normalize_embeddings=True, show_progress_bar=False)
                embeddings = np.array(embeddings, dtype=np.float32)
                index.add(embeddings)

                start_idx = len(self._chunks)
                for idx, chunk in enumerate(chunk_dicts):
                    chunk_text = chunk.get("chunk_text") or chunk.get("text", "")
                    self._chunks.append(
                        {
                            "chunk_id": chunk["chunk_id"],
                            "chunk_text": chunk_text,
                            "chunk_index": chunk.get("chunk_index", idx),
                            "document_id": document_id,
                            "document_name": document_name,
                            "page_start": chunk.get("page_start"),
                            "page_end": chunk.get("page_end"),
                            "source_offset_start": chunk.get("source_offset_start"),
                            "source_offset_end": chunk.get("source_offset_end"),
                            "embedding_version": chunk.get("embedding_version"),
                            **(metadata or {}),
                            **(chunk.get("metadata") or {}),
                        }
                    )
                self._doc_chunk_lookup.setdefault(document_id, []).extend(range(start_idx, len(self._chunks)))
                self._save_index()
                logger.info("Indexed %s chunks for document '%s'", len(chunk_dicts), document_name)
                return len(chunk_dicts)

            return self._run_write_locked(add_chunks)

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[SearchResult]:
        started = time.perf_counter()
        with trace_operation(
            "vector.search",
            component="vector_store",
            logger_=logger,
            backend="faiss",
            top_k=top_k,
        ):
            embedder = self._get_embedder()
            index = self._get_index()

            if index.ntotal == 0:
                return []

            query_embedding = embedder.encode([query], normalize_embeddings=True, show_progress_bar=False)
            query_embedding = np.array(query_embedding, dtype=np.float32)
            active_filters = {k: v for k, v in filters.items() if v is not None} if filters else {}
            if active_filters:
                initial_k = index.ntotal
            else:
                initial_k = min(max(top_k, 1) * 4, index.ntotal)
            initial_k = max(initial_k, 1)
            scores, indices = index.search(query_embedding, initial_k)

            results: list[SearchResult] = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._chunks):
                    continue
                meta = self._chunks[idx]
                if str(meta.get("document_id", "")) in self._deleted_document_ids:
                    continue
                if active_filters:
                    if not exact_scope_match(meta, active_filters):
                        continue
                results.append(
                    SearchResult(
                        chunk_text=meta["chunk_text"],
                        chunk_index=meta["chunk_index"],
                        document_id=meta["document_id"],
                        document_name=meta["document_name"],
                        score=float(score),
                        chunk_id=str(meta.get("chunk_id", "")),
                        page_start=meta.get("page_start"),
                        page_end=meta.get("page_end"),
                        source_offset_start=meta.get("source_offset_start"),
                        source_offset_end=meta.get("source_offset_end"),
                    )
                )
                if len(results) >= top_k:
                    break
        latency_ms = (time.perf_counter() - started) * 1000
        observe_dense_search(latency_ms)
        record_retrieved_chunks(len(results))
        observe_vector_search(time.perf_counter() - started, backend="faiss")
        return results

    def delete_document(self, document_id: str) -> int:
        document_id = str(document_id)
        try:
            self._get_index()
        except Exception:
            pass
        removed_count = len(self._doc_chunk_lookup.get(document_id, []))
        self._deleted_document_ids.add(document_id)
        self._save_deleted_documents()
        self._rebuild_lookup()
        return removed_count

    def get_all_chunks(self, filters: dict | None = None) -> list[dict]:
        try:
            self._get_index()
        except Exception:
            return []
        chunks = [
            chunk
            for chunk in self._chunks
            if str(chunk.get("document_id", "")) not in self._deleted_document_ids
        ]
        if filters:
            chunks = [chunk for chunk in chunks if all(chunk.get(key) == value for key, value in filters.items())]
        return chunks

    def get_chunks_for_document(
        self,
        document_id: str,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        document_id = str(document_id)
        try:
            self._get_index()
        except Exception:
            return []
        if document_id in self._deleted_document_ids:
            return []
        indices = self._doc_chunk_lookup.get(document_id, [])
        if limit is not None:
            indices = indices[: max(limit, 0)]
        chunks = [self._chunks[idx] for idx in indices if 0 <= idx < len(self._chunks)]
        if filters:
            chunks = [chunk for chunk in chunks if all(chunk.get(key) == value for key, value in filters.items())]
        return chunks

    def get_stats(self) -> dict:
        try:
            index = self._get_index()
            active_chunks = [
                chunk
                for chunk in self._chunks
                if str(chunk.get("document_id", "")) not in self._deleted_document_ids
            ]
            document_ids = {chunk["document_id"] for chunk in active_chunks}
            return {
                "backend": "faiss",
                "total_vectors": index.ntotal,
                "active_vectors": len(active_chunks),
                "deleted_vectors": max(index.ntotal - len(active_chunks), 0),
                "total_chunks": len(active_chunks),
                "total_documents": len(document_ids),
                "deleted_documents": len(self._deleted_document_ids),
            }
        except Exception as exc:
            return {
                "backend": "faiss",
                "total_vectors": 0,
                "total_chunks": 0,
                "total_documents": 0,
                "error": str(exc),
            }


class QdrantBackend(_EmbeddingChunkingMixin):
    """Qdrant-backed vector store for production deployments."""

    def __init__(self):
        super().__init__()
        self._client = None
        self._models = None
        self._collection_ready = False
        self._settings = get_settings()

    def _collection_name(self) -> str:
        base_name = self._settings.qdrant_collection
        app_env = self._settings.app_env.strip().lower()
        return f"{base_name}_{app_env}"

    def _load_qdrant(self):
        if self._client is not None and self._models is not None:
            return self._client, self._models

        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:  # pragma: no cover - env dependent
            raise RuntimeError(
                "qdrant-client is not installed. Install it to enable VECTOR_BACKEND=qdrant."
            ) from exc

        if not self._settings.qdrant_url:
            raise RuntimeError("QDRANT_URL must be configured when VECTOR_BACKEND=qdrant.")

        self._client = QdrantClient(
            url=self._settings.qdrant_url,
            api_key=self._settings.qdrant_api_key or None,
        )
        self._models = models
        return self._client, self._models

    def _ensure_collection(self):
        if self._collection_ready:
            return

        client, models = self._load_qdrant()
        collection_name = self._collection_name()
        collections = client.get_collections().collections
        if not any(item.name == collection_name for item in collections):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=self._settings.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            info = client.get_collection(collection_name)
            vector_size = info.config.params.vectors.size
            if vector_size != self._settings.embedding_dim:
                logger.error(
                    "Qdrant collection dimension mismatch! Stored: %s, Configured: %s",
                    vector_size, self._settings.embedding_dim
                )
                raise ValueError(
                    f"Qdrant collection '{collection_name}' has vector size {vector_size} "
                    f"but configured embedding_dim is {self._settings.embedding_dim}."
                )
        self._collection_ready = True

    def _scroll_points(self, scroll_filter=None, limit: int = 256) -> list[dict]:
        client, models = self._load_qdrant()
        self._ensure_collection()
        collection_name = self._collection_name()

        results: list[dict] = []
        offset = None
        while True:
            records, next_offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=scroll_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            results.extend(records)
            if next_offset is None:
                break
            offset = next_offset
        return results

    def add_documents(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: dict | None = None,
        chunks: list[dict] | None = None,
    ) -> int:
        with trace_operation(
            "vector.add_documents",
            component="vector_store",
            logger_=logger,
            backend="qdrant",
            document_id=str(document_id),
        ):
            client, models = self._load_qdrant()
            self._ensure_collection()
            collection_name = self._collection_name()

            chunk_dicts = chunks or self.chunk_text(text, chunk_size, overlap)
            if not chunk_dicts:
                return 0

            embedder = self._get_embedder()
            chunk_texts = [chunk.get("chunk_text") or chunk.get("text", "") for chunk in chunk_dicts]
            embeddings = embedder.encode(chunk_texts, normalize_embeddings=True, show_progress_bar=False)

            points = []
            for idx, (chunk, embedding) in enumerate(zip(chunk_dicts, embeddings)):
                chunk_text = chunk.get("chunk_text") or chunk.get("text", "")
                payload = {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_text": chunk_text,
                    "chunk_index": chunk.get("chunk_index", idx),
                    "document_id": str(document_id),
                    "document_name": document_name,
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "source_offset_start": chunk.get("source_offset_start"),
                    "source_offset_end": chunk.get("source_offset_end"),
                    "embedding_version": chunk.get("embedding_version"),
                    **(metadata or {}),
                    **(chunk.get("metadata") or {}),
                }
                points.append(
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=np.array(embedding, dtype=np.float32).tolist(),
                        payload=payload,
                    )
                )

            client.upsert(collection_name=collection_name, points=points, wait=True)
            logger.info("Indexed %s chunks in Qdrant for document '%s'", len(points), document_name)
            return len(points)

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[SearchResult]:
        started = time.perf_counter()
        with trace_operation(
            "vector.search",
            component="vector_store",
            logger_=logger,
            backend="qdrant",
            top_k=top_k,
        ):
            client, models = self._load_qdrant()
            self._ensure_collection()

            embedder = self._get_embedder()
            query_embedding = embedder.encode([query], normalize_embeddings=True, show_progress_bar=False)
            query_vector = np.array(query_embedding[0], dtype=np.float32).tolist()
            collection_name = self._collection_name()
            query_filter = None
            if filters:
                active_filters = {k: v for k, v in filters.items() if v is not None}
                must_conditions = []
                for key, val in active_filters.items():
                    must_conditions.append(
                        models.FieldCondition(key=key, match=models.MatchValue(value=val))
                    )
                if must_conditions:
                    query_filter = models.Filter(must=must_conditions)

            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    limit=max(top_k, 1),
                    with_payload=True,
                    query_filter=query_filter,
                )
                points = getattr(response, "points", response)
            else:  # pragma: no cover - compatibility path
                points = client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=max(top_k, 1),
                    with_payload=True,
                    query_filter=query_filter,
                )

            results: list[SearchResult] = []
            for point in points:
                payload = point.payload or {}
                results.append(
                    SearchResult(
                        chunk_text=str(payload.get("chunk_text", "")),
                        chunk_index=int(payload.get("chunk_index", 0)),
                        document_id=str(payload.get("document_id", "")),
                        document_name=str(payload.get("document_name", "")),
                        score=float(getattr(point, "score", 0.0)),
                        chunk_id=str(payload.get("chunk_id", "")),
                        page_start=payload.get("page_start"),
                        page_end=payload.get("page_end"),
                        source_offset_start=payload.get("source_offset_start"),
                        source_offset_end=payload.get("source_offset_end"),
                    )
                )
        latency_ms = (time.perf_counter() - started) * 1000
        observe_dense_search(latency_ms)
        record_retrieved_chunks(len(results))
        observe_vector_search(time.perf_counter() - started, backend="qdrant")
        return results

    def delete_document(self, document_id: str) -> int:
        client, models = self._load_qdrant()
        self._ensure_collection()
        filter_ = models.Filter(
            must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))]
        )
        existing = self._scroll_points(scroll_filter=filter_)
        if existing:
            client.delete(
                collection_name=self._collection_name(),
                points_selector=models.FilterSelector(filter=filter_),
                wait=True,
            )
        return len(existing)

    def get_all_chunks(self, filters: dict | None = None) -> list[dict]:
        scroll_filter = None
        if filters:
            _client, models = self._load_qdrant()
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                    for key, value in filters.items()
                ]
            )
        points = self._scroll_points(scroll_filter=scroll_filter)
        return [point.payload or {} for point in points]

    def get_chunks_for_document(
        self,
        document_id: str,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        client, models = self._load_qdrant()
        self._ensure_collection()
        must_conditions = [models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))]
        if filters:
            must_conditions.extend(
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filters.items()
            )
        filter_ = models.Filter(must=must_conditions)
        points = self._scroll_points(scroll_filter=filter_, limit=limit or 256)
        payloads = [point.payload or {} for point in points]
        if limit is not None:
            return payloads[: max(limit, 0)]
        return payloads

    def get_stats(self) -> dict:
        client, _models = self._load_qdrant()
        self._ensure_collection()
        collection = client.get_collection(self._collection_name())
        vectors_count = getattr(collection, "vectors_count", None)
        points_count = getattr(collection, "points_count", None)
        return {
            "backend": "qdrant",
            "total_vectors": vectors_count or points_count or 0,
            "total_chunks": points_count or vectors_count or 0,
            "total_documents": len({payload.get("document_id") for payload in self.get_all_chunks()}),
            "collection_name": self._collection_name(),
        }


class VectorStoreService:
    """Facade that preserves the legacy service API for callers."""

    def __init__(self):
        self._backend: VectorStoreBackend | None = None
        self._write_lock: asyncio.Lock = asyncio.Lock()

    def _get_backend(self) -> VectorStoreBackend:
        if self._backend is not None:
            return self._backend

        settings = get_settings()
        if settings.vector_backend == "qdrant":
            self._backend = QdrantBackend()
        else:
            self._backend = FAISSBackend()
            self._backend._write_lock = self._write_lock
        
        # Bind parent reference for test monkeypatching delegation
        object.__setattr__(self._backend, "_parent", self)
        return self._backend

    @property
    def _chunks(self):
        backend = self._get_backend()
        if hasattr(backend, "_chunks"):
            return backend._chunks
        return []

    @_chunks.setter
    def _chunks(self, value):
        backend = self._get_backend()
        if hasattr(backend, "_chunks"):
            backend._chunks = value

    @property
    def _deleted_document_ids(self):
        backend = self._get_backend()
        if hasattr(backend, "_deleted_document_ids"):
            return backend._deleted_document_ids
        return set()

    @_deleted_document_ids.setter
    def _deleted_document_ids(self, value):
        backend = self._get_backend()
        if hasattr(backend, "_deleted_document_ids"):
            backend._deleted_document_ids = value

    def _rebuild_lookup(self):
        backend = self._get_backend()
        if hasattr(backend, "_rebuild_lookup"):
            return backend._rebuild_lookup()

    @staticmethod
    def _chunking_backend() -> _EmbeddingChunkingMixin:
        return _EmbeddingChunkingMixin()

    def _split_sentences(self, text: str) -> list[str]:
        return self._chunking_backend()._split_sentences(text)

    def chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
        return self._chunking_backend().chunk_text(text, chunk_size, overlap)

    def add_documents(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: dict | None = None,
        chunks: list[dict] | None = None,
    ) -> int:
        count = self._get_backend().add_documents(
            document_id,
            document_name,
            text,
            chunk_size,
            overlap,
            metadata,
            chunks,
        )
        try:
            from app.core.caching import CacheManager, make_cache_prefix

            scope = metadata or {}
            tenant_id = scope.get("tenant_id")
            patient_id = scope.get("patient_id")
            if tenant_id and patient_id:
                CacheManager.invalidate_prefix(make_cache_prefix("retrieval", tenant_id=tenant_id, patient_id=patient_id))
        except Exception:
            logger.warning("Retrieval cache invalidation failed after vector indexing")
        return count

    def add_document(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
        metadata: dict | None = None,
        chunks: list[dict] | None = None,
    ) -> int:
        return self.add_documents(document_id, document_name, text, chunk_size, overlap, metadata, chunks)

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[SearchResult]:
        from app.core.caching import CacheManager, make_cache_key
        filters_clean = filters or {}
        patient_id = filters_clean.get("patient_id")
        tenant_id = filters_clean.get("tenant_id")

        try:
            cache_key = make_cache_key(
                namespace="retrieval",
                patient_id=patient_id,
                tenant_id=tenant_id,
                payload={"query": query, "top_k": top_k, "filters": filters_clean}
            )
            cached_res = CacheManager.get(cache_key)
            if cached_res is not None:
                return [
                    SearchResult(
                        chunk_text=item["chunk_text"],
                        chunk_index=item["chunk_index"],
                        document_id=item["document_id"],
                        document_name=item["document_name"],
                        score=item["score"],
                        chunk_id=item.get("chunk_id", ""),
                        page_start=item.get("page_start"),
                        page_end=item.get("page_end"),
                        source_offset_start=item.get("source_offset_start"),
                        source_offset_end=item.get("source_offset_end"),
                    )
                    for item in cached_res
                ]
            
            res = self._get_backend().search(query, top_k, filters)
            serializable = [
                {
                    "chunk_text": item.chunk_text,
                    "chunk_index": item.chunk_index,
                    "document_id": item.document_id,
                    "document_name": item.document_name,
                    "score": item.score,
                    "chunk_id": item.chunk_id,
                    "page_start": item.page_start,
                    "page_end": item.page_end,
                    "source_offset_start": item.source_offset_start,
                    "source_offset_end": item.source_offset_end,
                }
                for item in res
            ]
            CacheManager.set(cache_key, serializable)
            return res
        except ValueError:
            # Bypass cache on missing patient/tenant context parameter
            return self._get_backend().search(query, top_k, filters)


    def mark_document_deleted(self, document_id: str) -> int:
        count = self._get_backend().delete_document(document_id)
        try:
            from app.core.caching import CacheManager

            CacheManager.invalidate_prefix("cgrag:retrieval:")
        except Exception:
            logger.warning("Retrieval cache invalidation failed after document deletion")
        return count

    def delete_document(self, document_id: str) -> int:
        return self.mark_document_deleted(document_id)

    def get_all_chunks(self, filters: dict | None = None) -> list[dict]:
        return self._get_backend().get_all_chunks(filters)

    def get_chunks_for_document(
        self,
        document_id: str,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        return self._get_backend().get_chunks_for_document(document_id, limit, filters)

    def get_stats(self) -> dict:
        return self._get_backend().get_stats()

    def _get_index(self):
        backend = self._get_backend()
        if hasattr(backend, "_get_index"):
            return backend._get_index()
        return None

    def _get_embedder(self):
        backend = self._get_backend()
        if hasattr(backend, "_get_embedder"):
            return backend._get_embedder()
        return None

    def _save_deleted_documents(self):
        backend = self._get_backend()
        if hasattr(backend, "_save_deleted_documents"):
            return backend._save_deleted_documents()

    @staticmethod
    def compute_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


vector_store_service = VectorStoreService()
