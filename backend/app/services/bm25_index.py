"""
Sparse retrieval service.

In application mode, chunk text is persisted in PostgreSQL and searched via
PostgreSQL full-text search when available, with a SQLite/test fallback scorer.
For isolated unit tests, the class can still operate in-memory.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from uuid import UUID

from sqlalchemy import delete, distinct, func, select, cast
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.retrieval_scope import exact_scope_match
from app.core.text_normalization import sparse_text_diagnostics, tokenize_sparse_text
from app.models.persistence import DocumentChunk

logger = logging.getLogger(__name__)


class BM25Index:
    """Sparse keyword search.

    In-memory evaluation mode uses rank_bm25.BM25Okapi when installed.
    Application database mode uses PostgreSQL full-text search, not BM25.
    """

    def __init__(self, *, use_database: bool = False):
        self._use_database = use_database
        self._index = None
        self._corpus: list[list[str]] = []
        self._metadata: list[dict] = []
        self._deleted_document_ids: set[str] = set()

    def _save_deleted_documents(self) -> None:
        return None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return tokenize_sparse_text(text)

    @staticmethod
    def _run_sync(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        raise RuntimeError("Use the async BM25 methods inside an active event loop.")

    # ── In-memory fallback ──────────────────────────────

    def _rebuild_index(self) -> None:
        if not self._corpus:
            self._index = None
            return
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 not installed; using naive token overlap for in-memory BM25.")
            self._index = None
            return
        self._index = BM25Okapi(self._corpus)

    def _add_document_memory(
        self,
        chunks: list[dict],
        document_id: str,
        document_name: str,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        base_metadata = dict(metadata or {})
        if user_id is not None:
            base_metadata.setdefault("user_id", user_id)
        base_metadata.setdefault("document_name", document_name)
        for chunk in chunks:
            text = chunk.get("chunk_text") or chunk.get("text", "")
            tokens = self._tokenize(text)
            chunk_metadata = {**base_metadata, **dict(chunk.get("metadata") or {})}
            self._corpus.append(tokens)
            self._metadata.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chunk_text": text,
                    "chunk_index": chunk.get("chunk_index", 0),
                    "document_id": str(document_id),
                    "document_name": document_name,
                    **chunk_metadata,
                }
            )
        self._rebuild_index()
        return len(chunks)

    def _search_memory(self, query: str, top_k: int = 10, user_id: str | None = None, filters: dict | None = None) -> list[dict]:
        tokens = self._tokenize(query)
        if not tokens or not self._metadata:
            return []

        active_filters = dict(filters) if filters else {}
        if user_id and "user_id" not in active_filters:
            active_filters["user_id"] = user_id
        active_filters = {k: v for k, v in active_filters.items() if v is not None}

        if self._index is not None:
            scores = self._index.get_scores(tokens)
            ranked_indices = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)
            results = []
            for idx in ranked_indices:
                if scores[idx] <= 0:
                    continue
                meta = self._metadata[idx]
                if str(meta.get("document_id", "")) in self._deleted_document_ids:
                    continue
                if active_filters:
                    if not exact_scope_match(meta, active_filters):
                        continue
                results.append(meta | {"score": float(scores[idx])})
                if len(results) >= top_k:
                    break
            return results

        query_counts = Counter(tokens)
        ranked: list[tuple[float, dict]] = []
        for meta, corpus_tokens in zip(self._metadata, self._corpus):
            if str(meta.get("document_id", "")) in self._deleted_document_ids:
                continue
            if active_filters:
                if not exact_scope_match(meta, active_filters):
                    continue
            corpus_counts = Counter(corpus_tokens)
            score = float(sum(min(query_counts[token], corpus_counts[token]) for token in query_counts))
            if score > 0:
                ranked.append((score, meta))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [meta | {"score": score} for score, meta in ranked[:top_k]]

    # ── Persistent PostgreSQL/SQLite mode ───────────────

    async def add_document_async(
        self,
        chunks: list[dict],
        document_id: str,
        document_name: str,
        *,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        if not self._use_database:
            return self._add_document_memory(chunks, document_id, document_name, user_id=user_id, metadata=metadata)

        base_metadata = dict(metadata or {})
        if user_id is not None:
            base_metadata.setdefault("user_id", user_id)
        base_metadata.setdefault("document_name", document_name)
        async with async_session_factory() as session:
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == UUID(str(document_id)))
            )
            for chunk in chunks:
                text = chunk.get("chunk_text") or chunk.get("text", "")
                tokens = self._tokenize(text)
                chunk_metadata = {**base_metadata, **dict(chunk.get("metadata") or {})}
                session.add(
                    DocumentChunk(
                        document_id=UUID(str(document_id)),
                        user_id=chunk_metadata.get("user_id") or user_id,
                        chunk_id=chunk.get("chunk_id", ""),
                        chunk_index=chunk.get("chunk_index", 0),
                        chunk_text=text,
                        normalized_text=" ".join(tokens),
                        token_count=len(tokens),
                        page_start=chunk.get("page_start"),
                        page_end=chunk.get("page_end"),
                        source_offset_start=chunk.get("source_offset_start"),
                        source_offset_end=chunk.get("source_offset_end"),
                        embedding_version=chunk.get("embedding_version"),
                        metadata_=chunk_metadata,
                    )
                )
            await session.commit()
        return len(chunks)

    async def search_async(
        self,
        query: str,
        top_k: int = 10,
        *,
        user_id: str | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        import time
        from app.core.metrics import observe_sparse_search
        started = time.perf_counter()
        try:
            if not self._use_database:
                return self._search_memory(query, top_k=top_k, user_id=user_id, filters=filters)

            tokens = self._tokenize(query)
            if not tokens:
                return []

            active_filters = dict(filters) if filters else {}
            if user_id and "user_id" not in active_filters:
                active_filters["user_id"] = user_id
            active_filters = {k: v for k, v in active_filters.items() if v is not None}

            db_backend = make_url(get_settings().database_url).get_backend_name()
            async with async_session_factory() as session:
                if db_backend == "postgresql":
                    from sqlalchemy.dialects.postgresql import JSONB
                    tsquery = func.websearch_to_tsquery(get_settings().postgres_fts_config, " ".join(tokens))
                    tsvector = DocumentChunk.search_vector
                    stmt = (
                        select(
                            DocumentChunk,
                            func.ts_rank_cd(tsvector, tsquery).label("score"),
                        )
                        .where(tsvector.op("@@")(tsquery))
                        .order_by(func.ts_rank_cd(tsvector, tsquery).desc(), DocumentChunk.chunk_index.asc())
                        .limit(max(top_k, 1))
                    )
                    for key, val in active_filters.items():
                        if key == "user_id":
                            stmt = stmt.where(DocumentChunk.user_id == val)
                        else:
                            stmt = stmt.where(cast(DocumentChunk.metadata_, JSONB)[key].astext == val)
                    result = await session.execute(stmt)
                    return [
                        {
                            "chunk_text": row.DocumentChunk.chunk_text,
                            "chunk_index": row.DocumentChunk.chunk_index,
                            "document_id": str(row.DocumentChunk.document_id),
                            "document_name": (row.DocumentChunk.metadata_ or {}).get("document_name", ""),
                            "chunk_id": row.DocumentChunk.chunk_id,
                            "page_start": row.DocumentChunk.page_start,
                            "page_end": row.DocumentChunk.page_end,
                            "source_offset_start": row.DocumentChunk.source_offset_start,
                            "source_offset_end": row.DocumentChunk.source_offset_end,
                            "score": float(row.score or 0.0),
                        }
                        for row in result.all()
                    ]

                stmt = select(DocumentChunk)
                if active_filters:
                    # For SQLite, filter on index column if possible
                    if "user_id" in active_filters:
                        stmt = stmt.where(DocumentChunk.user_id == active_filters["user_id"])
                result = await session.execute(stmt)
                chunks = result.scalars().all()

            ranked: list[tuple[float, DocumentChunk]] = []
            query_counts = Counter(tokens)
            for chunk in chunks:
                chunk_meta = chunk.metadata_ or {}
                if active_filters:
                    combined_meta = {"user_id": chunk.user_id, **chunk_meta}
                    if not exact_scope_match(combined_meta, active_filters):
                        continue

                corpus_tokens = chunk.normalized_text.split() if chunk.normalized_text else self._tokenize(chunk.chunk_text)
                corpus_counts = Counter(corpus_tokens)
                score = float(sum(min(query_counts[token], corpus_counts[token]) for token in query_counts))
                if score > 0:
                    ranked.append((score, chunk))
            ranked.sort(key=lambda item: item[0], reverse=True)
            return [
                {
                    "chunk_text": chunk.chunk_text,
                    "chunk_index": chunk.chunk_index,
                    "document_id": str(chunk.document_id),
                    "document_name": (chunk.metadata_ or {}).get("document_name", ""),
                    "chunk_id": chunk.chunk_id,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "source_offset_start": chunk.source_offset_start,
                    "source_offset_end": chunk.source_offset_end,
                    "score": score,
                }
                for score, chunk in ranked[: max(top_k, 1)]
            ]
        finally:
            observe_sparse_search((time.perf_counter() - started) * 1000)

    async def mark_document_deleted_async(self, document_id: str) -> int:
        if not self._use_database:
            removed = sum(1 for meta in self._metadata if str(meta.get("document_id", "")) == str(document_id))
            self._deleted_document_ids.add(str(document_id))
            self._save_deleted_documents()
            return removed

        async with async_session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == UUID(str(document_id)))
            )
            count = int(result.scalar() or 0)
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == UUID(str(document_id)))
            )
            await session.commit()
            return count

    async def get_stats_async(self) -> dict:
        if not self._use_database:
            document_ids = {meta["document_id"] for meta in self._metadata}
            diagnostics = sparse_text_diagnostics([meta.get("chunk_text", "") for meta in self._metadata])
            return {
                "total_documents": len(self._metadata),
                "active_documents": len(document_ids),
                "deleted_documents": 0,
                "index_loaded": self._index is not None,
                **diagnostics,
            }

        async with async_session_factory() as session:
            chunk_count_result = await session.execute(select(func.count()).select_from(DocumentChunk))
            doc_count_result = await session.execute(select(func.count(distinct(DocumentChunk.document_id))))
            empty_count_result = await session.execute(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.token_count <= 0)
            )
            token_count_result = await session.execute(select(func.coalesce(func.sum(DocumentChunk.token_count), 0)))
            return {
                "total_documents": int(chunk_count_result.scalar() or 0),
                "active_documents": int(doc_count_result.scalar() or 0),
                "deleted_documents": 0,
                "index_loaded": True,
                "empty_document_count": int(empty_count_result.scalar() or 0),
                "token_count": int(token_count_result.scalar() or 0),
            }

    # ── Compatibility sync methods ──────────────────────

    def add_document(
        self,
        chunks: list[dict],
        document_id: str,
        document_name: str,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        if not self._use_database:
            return self._add_document_memory(chunks, document_id, document_name, user_id=user_id, metadata=metadata)
        try:
            asyncio.get_running_loop()
            return self.add_document_async(
                chunks,
                document_id,
                document_name,
                user_id=user_id,
                metadata=metadata,
            )  # type: ignore[return-value]
        except RuntimeError:
            return self._run_sync(
            self.add_document_async(
                chunks,
                document_id,
                document_name,
                user_id=user_id,
                metadata=metadata,
            )
        )

    def search(self, query: str, top_k: int = 10, user_id: str | None = None, filters: dict | None = None) -> list[dict]:
        if not self._use_database:
            return self._search_memory(query, top_k=top_k, user_id=user_id, filters=filters)
        try:
            asyncio.get_running_loop()
            return self.search_async(query, top_k=top_k, user_id=user_id, filters=filters)  # type: ignore[return-value]
        except RuntimeError:
            return self._run_sync(self.search_async(query, top_k=top_k, user_id=user_id, filters=filters))

    def mark_document_deleted(self, document_id: str) -> int:
        if not self._use_database:
            return self._run_sync(self.mark_document_deleted_async(document_id))
        try:
            asyncio.get_running_loop()
            return self.mark_document_deleted_async(document_id)  # type: ignore[return-value]
        except RuntimeError:
            return self._run_sync(self.mark_document_deleted_async(document_id))

    def get_stats(self) -> dict:
        if not self._use_database:
            document_ids = {meta["document_id"] for meta in self._metadata}
            diagnostics = sparse_text_diagnostics([meta.get("chunk_text", "") for meta in self._metadata])
            return {
                "total_documents": len(self._metadata),
                "active_documents": len(document_ids),
                "deleted_documents": 0,
                "index_loaded": self._index is not None,
                **diagnostics,
            }
        return self._run_sync(self.get_stats_async())


bm25_index = BM25Index(use_database=True)
