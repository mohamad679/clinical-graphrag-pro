"""
Background document processing pipeline with explicit stages and durable metadata.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from PyPDF2 import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.metrics import observe_document_processing
from app.core.observability import trace_operation, update_observability_context
from app.models.document import Document
from app.models.persistence import DocumentContent
from app.services.bm25_index import bm25_index
from app.services.document_pipeline import (
    coarse_status_for_stage,
    deindex_document_artifacts,
    pipeline_trace,
    progress_for_stage,
    record_pipeline_stage,
)
from app.services.entity_normalization import entity_normalization_service
from app.services.graph import temporal_graph_service
from app.services.job_state import job_state_service
from app.services.storage import storage_service
from app.services.vector_store import vector_store_service

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ExtractionResult:
    text: str
    page_count: int | None
    extraction_method: str
    page_texts: list[str]
    page_metadata: list[dict]
    scanned_pdf_detected: bool
    ocr_status: str


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _embedding_version() -> str:
    return settings.document_embedding_version or settings.embedding_model


def _split_page_sentences(page_text: str) -> list[tuple[str, int, int]]:
    sentences = vector_store_service._split_sentences(page_text)
    records: list[tuple[str, int, int]] = []
    cursor = 0
    for sentence in sentences:
        start = page_text.find(sentence, cursor)
        if start < 0:
            start = cursor
        end = start + len(sentence)
        cursor = end
        records.append((sentence, start, end))
    return records


def _extract_pdf_pypdf2(content: bytes) -> ExtractionResult:
    reader = PdfReader(io.BytesIO(content))
    page_texts: list[str] = []
    page_metadata: list[dict] = []
    total_chars = 0

    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_texts.append(text)
        char_count = len(text.strip())
        total_chars += char_count
        page_metadata.append(
            {
                "page_number": idx,
                "extractor": "pypdf2",
                "char_count": char_count,
                "has_text": bool(char_count),
            }
        )

    page_count = len(reader.pages)
    threshold = settings.document_scanned_pdf_min_chars_per_page * max(page_count, 1)
    scanned_pdf_detected = total_chars < threshold
    return ExtractionResult(
        text="\n\n".join(page_texts),
        page_count=page_count,
        extraction_method="pypdf2",
        page_texts=page_texts,
        page_metadata=page_metadata,
        scanned_pdf_detected=scanned_pdf_detected,
        ocr_status="not_requested",
    )


def _extract_pdf_pymupdf(content: bytes) -> ExtractionResult | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return None

    document = fitz.open(stream=content, filetype="pdf")
    page_texts: list[str] = []
    page_metadata: list[dict] = []
    total_chars = 0
    try:
        for idx, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            page_texts.append(text)
            char_count = len(text.strip())
            total_chars += char_count
            page_metadata.append(
                {
                    "page_number": idx,
                    "extractor": "pymupdf",
                    "char_count": char_count,
                    "has_text": bool(char_count),
                }
            )
    finally:
        document.close()

    page_count = len(page_texts)
    threshold = settings.document_scanned_pdf_min_chars_per_page * max(page_count, 1)
    scanned_pdf_detected = total_chars < threshold
    return ExtractionResult(
        text="\n\n".join(page_texts),
        page_count=page_count,
        extraction_method="pymupdf",
        page_texts=page_texts,
        page_metadata=page_metadata,
        scanned_pdf_detected=scanned_pdf_detected,
        ocr_status="not_requested",
    )


def extract_document_text(content: bytes, suffix: str) -> ExtractionResult:
    """Extract text with fallback logic and scanned-PDF detection."""
    if suffix != ".pdf":
        text = content.decode("utf-8", errors="replace")
        return ExtractionResult(
            text=text,
            page_count=None,
            extraction_method="text_decode",
            page_texts=[text],
            page_metadata=[],
            scanned_pdf_detected=False,
            ocr_status="not_requested",
        )

    primary = _extract_pdf_pypdf2(content)
    fallback = None
    if settings.document_enable_pdf_fallback and len(primary.text.strip()) < 100:
        fallback = _extract_pdf_pymupdf(content)

    if fallback and len(fallback.text.strip()) > len(primary.text.strip()):
        result = fallback
    else:
        result = primary

    if result.scanned_pdf_detected and settings.document_enable_ocr:
        result.ocr_status = "requested_but_unavailable"
    elif result.scanned_pdf_detected:
        result.ocr_status = "not_enabled"
    return result


def build_chunk_records(
    *,
    document_id: str,
    text: str,
    page_metadata: list[dict],
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    page_texts = [entry for entry in page_metadata if entry.get("text")]
    if not page_texts:
        page_texts = [{"page_number": 1, "text": text}]

    sentence_records: list[dict] = []
    global_offset = 0
    for page_idx, page in enumerate(page_texts, start=1):
        page_number = int(page.get("page_number") or page_idx)
        page_text = str(page.get("text") or "")
        sentence_offsets = _split_page_sentences(page_text)
        for sentence, local_start, local_end in sentence_offsets:
            sentence_records.append(
                {
                    "text": sentence,
                    "page_number": page_number,
                    "start": global_offset + local_start,
                    "end": global_offset + local_end,
                    "token_count": len(sentence.split()),
                }
            )
        global_offset += len(page_text) + 2

    if not sentence_records:
        normalized = _normalize_text(text)
        return [
            {
                "chunk_id": f"{document_id}-0",
                "chunk_index": 0,
                "chunk_text": normalized,
                "page_start": 1 if page_texts else None,
                "page_end": 1 if page_texts else None,
                "source_offset_start": 0,
                "source_offset_end": len(normalized),
                "embedding_version": _embedding_version(),
                "metadata": {
                    "page_range": [1, 1] if page_texts else None,
                    "source_offset": {"start": 0, "end": len(normalized)},
                },
            }
        ]

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_words = 0

    for sentence in sentence_records:
        next_words = current_words + sentence["token_count"]
        if current and next_words > chunk_size:
            chunks.append(current)
            overlap_sentences: list[dict] = []
            overlap_words = 0
            for previous in reversed(current):
                if overlap_words + previous["token_count"] > overlap:
                    break
                overlap_words += previous["token_count"]
                overlap_sentences.insert(0, previous)
            current = overlap_sentences
            current_words = sum(item["token_count"] for item in current)
        current.append(sentence)
        current_words += sentence["token_count"]

    if current:
        chunks.append(current)

    chunk_records: list[dict] = []
    for idx, sentences in enumerate(chunks):
        chunk_text = " ".join(item["text"] for item in sentences).strip()
        page_start = min(item["page_number"] for item in sentences)
        page_end = max(item["page_number"] for item in sentences)
        source_start = min(item["start"] for item in sentences)
        source_end = max(item["end"] for item in sentences)
        token_count = sum(item["token_count"] for item in sentences)
        chunk_records.append(
            {
                "chunk_id": f"{document_id}-{idx}-{source_start}-{source_end}",
                "chunk_index": idx,
                "chunk_text": chunk_text,
                "page_start": page_start,
                "page_end": page_end,
                "source_offset_start": source_start,
                "source_offset_end": source_end,
                "embedding_version": _embedding_version(),
                "metadata": {
                    "page_range": [page_start, page_end],
                    "source_offset": {"start": source_start, "end": source_end},
                    "token_count": token_count,
                },
            }
        )
    return chunk_records


async def _persist_stage(
    document_id: UUID,
    stage: str,
    *,
    state: str,
    details: dict | None = None,
    error: str | None = None,
    job_state: str | None = None,
    increment_attempt: bool = False,
    completed: bool = False,
) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return

        document.processing_stage = stage
        document.processing_progress = progress_for_stage(stage, state)
        document.status = coarse_status_for_stage(stage, state)
        if error:
            document.error_message = error
        elif state == "running":
            document.error_message = None
        document.metadata_ = record_pipeline_stage(
            document.metadata_,
            stage,
            state=state,
            details=details,
            error=error,
        )

        if document.processing_job_id:
            await job_state_service.update_job(
                session,
                document.processing_job_id,
                status=job_state or (
                    "failed" if document.status == "error" else
                    "completed" if document.status == "ready" else
                    "running"
                ),
                progress=document.processing_progress,
                error_message=error,
                metadata={
                    "current_stage": document.processing_stage,
                    "pipeline_trace": pipeline_trace(document.metadata_),
                },
                started=state == "running",
                completed=completed,
                increment_attempt=increment_attempt,
            )

        await session.commit()


async def _reconcile_previous_versions(session, document: Document) -> list[str]:
    if not document.version_group_id:
        return []

    result = await session.execute(
        select(Document)
        .options(selectinload(Document.storage_asset))
        .where(
            Document.version_group_id == document.version_group_id,
            Document.user_id == document.user_id,
            Document.id != document.id,
        )
    )
    superseded = result.scalars().all()
    superseded_ids: list[str] = []
    for previous in superseded:
        previous.is_latest_version = False
        previous.superseded_at = datetime.now(timezone.utc)
        superseded_ids.append(str(previous.id))
        await deindex_document_artifacts(str(previous.id))
    return superseded_ids


async def process_document_async(document_id: str) -> dict:
    """Process a document end-to-end and update DB status as progress advances."""
    started = time.perf_counter()
    document_uuid = UUID(str(document_id))
    await _persist_stage(
        document_uuid,
        "validated",
        state="running",
        details={"retryable": True},
        increment_attempt=True,
    )

    async with async_session_factory() as session:
        result = await session.execute(
            select(Document)
            .options(selectinload(Document.storage_asset), selectinload(Document.content))
            .where(Document.id == document_uuid)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"Document {document_id} not found")

    current_failed_stage = "validated"
    try:
        update_observability_context(document_id=str(document_uuid))
        with trace_operation(
            "document.process",
            component="document_pipeline",
            logger_=logger,
            document_id=str(document_uuid),
        ):
            suffix = ((document.metadata_ or {}).get("original_suffix")) or f".{document.file_type}"
            if suffix.lower() not in {".pdf", ".txt", ".md", ".csv"}:
                raise ValueError(f"Unsupported document type for processing: {suffix}")
            if document.storage_asset is None:
                raise FileNotFoundError("Document storage asset is missing.")
            await _persist_stage(
                document_uuid,
                "validated",
                state="completed",
                details={"suffix": suffix, "content_type": document.content_type},
            )

            current_failed_stage = "extracted"
            await _persist_stage(document_uuid, "extracted", state="running")
            content_bytes = await storage_service.read_bytes(
                bucket=document.storage_asset.bucket,
                object_key=document.storage_asset.object_key,
                storage_metadata=document.storage_asset.storage_metadata,
            )
            extraction = extract_document_text(content_bytes, suffix)
            if not extraction.text.strip():
                raise ValueError("Could not extract text from document.")
            normalized_text = _normalize_text(extraction.text)
            page_metadata = list(extraction.page_metadata)
            page_entries = [
                {
                    **item,
                    "text": extraction.page_texts[idx] if idx < len(extraction.page_texts) else "",
                }
                for idx, item in enumerate(page_metadata)
            ]
            if not page_entries:
                page_entries = [{"page_number": 1, "text": extraction.text, "char_count": len(extraction.text)}]
            await _persist_stage(
                document_uuid,
                "extracted",
                state="completed",
                details={
                    "page_count": extraction.page_count,
                    "method": extraction.extraction_method,
                    "scanned_pdf_detected": extraction.scanned_pdf_detected,
                    "ocr_status": extraction.ocr_status,
                },
            )

        current_failed_stage = "chunked"
        await _persist_stage(document_uuid, "chunked", state="running")
        chunk_records = build_chunk_records(
            document_id=document_id,
            text=normalized_text,
            page_metadata=page_entries,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        if not chunk_records:
            raise ValueError("No chunks could be built from the extracted text.")
        await _persist_stage(
            document_uuid,
            "chunked",
            state="completed",
            details={
                "chunk_count": len(chunk_records),
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "embedding_version": _embedding_version(),
            },
        )

        await deindex_document_artifacts(document_id)

        current_failed_stage = "embedded"
        await _persist_stage(document_uuid, "embedded", state="running")
        retrieval_metadata = {
            "user_id": document.user_id,
            "tenant_id": document.user_id,
            "patient_id": (document.metadata_ or {}).get("patient_id"),
            "organization_id": (document.metadata_ or {}).get("organization_id"),
            "owner": document.user_id,
            "app_env": settings.app_env,
            "version_group_id": document.version_group_id,
            "version_number": document.version_number,
        }

        chunk_count = vector_store_service.add_document(
            document_id=document_id,
            document_name=document.filename,
            text=normalized_text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
            metadata=retrieval_metadata,
            chunks=chunk_records,
        )
        await _persist_stage(
            document_uuid,
            "embedded",
            state="completed",
            details={"chunk_count": chunk_count},
        )

        current_failed_stage = "indexed_lexical"
        await _persist_stage(document_uuid, "indexed_lexical", state="running")
        bm25_add = bm25_index.add_document(
            chunks=chunk_records,
            document_id=document_id,
            document_name=document.filename,
            user_id=document.user_id,
            metadata=retrieval_metadata,
        )
        if hasattr(bm25_add, "__await__"):
            await bm25_add
        await _persist_stage(
            document_uuid,
            "indexed_lexical",
            state="completed",
            details={"chunk_count": len(chunk_records)},
        )

        current_failed_stage = "entities_extracted"
        await _persist_stage(document_uuid, "entities_extracted", state="running")
        all_chunk_entities: list[dict] = []
        seen_doc = set()
        unique_entities: list[dict] = []
        for chunk in chunk_records:
            chunk_entities = entity_normalization_service.normalize_with_fallback(chunk["chunk_text"])
            for entity in chunk_entities[:10]:
                if not entity or entity.is_ungrounded:
                    continue
                start_in_chunk = chunk["chunk_text"].find(entity.surface_form)
                if start_in_chunk >= 0:
                    start_offset = chunk["source_offset_start"] + start_in_chunk
                    end_offset = start_offset + len(entity.surface_form)
                else:
                    start_offset = chunk["source_offset_start"]
                    end_offset = chunk["source_offset_end"]
                entity_dict = entity.model_dump()
                entity_dict.update({
                    "source_chunk_id": chunk["chunk_id"],
                    "source_document_id": document_id,
                    "source_text_span": {"start": start_offset, "end": end_offset},
                    "extraction_method": "scispacy" if entity.confidence in ("High", "Medium") else "curated",
                    "confidence": entity.confidence or "High",
                })
                all_chunk_entities.append(entity_dict)
                doc_key = (entity.canonical_label, entity.concept_id)
                if doc_key not in seen_doc:
                    seen_doc.add(doc_key)
                    if len(unique_entities) < 30:
                        unique_entities.append(entity_dict)
        await _persist_stage(
            document_uuid,
            "entities_extracted",
            state="completed",
            details={"entity_count": len(unique_entities)},
        )

        current_failed_stage = "graph_ingested"
        await _persist_stage(document_uuid, "graph_ingested", state="running")
        graph_result = await temporal_graph_service.ingest_document_entities(
            document_id=document_id,
            tenant_id=document.user_id,
            document_name=document.filename,
            entities=all_chunk_entities,
            uploaded_at=document.uploaded_at,
            patient_id=(document.metadata_ or {}).get("patient_id"),
            chunks=chunk_records,
        )
        await _persist_stage(
            document_uuid,
            "graph_ingested",
            state="completed",
            details={
                "ingested": True,
                "nodes": graph_result["nodes"],
                "edges": graph_result["edges"],
            },
        )

        async with async_session_factory() as session:
            result = await session.execute(
                select(Document)
                .options(selectinload(Document.content))
                .where(Document.id == document_uuid)
            )
            db_document = result.scalar_one_or_none()
            if not db_document:
                raise ValueError(f"Document {document_id} disappeared during processing")

            metadata = dict(db_document.metadata_ or {})
            metadata["text_length"] = len(extraction.text)
            metadata["processed_with"] = "celery"

            db_document.chunk_count = chunk_count
            db_document.status = "ready"
            db_document.processing_stage = "ready"
            db_document.processing_progress = 100
            db_document.processed_at = datetime.now(timezone.utc)
            db_document.metadata_ = record_pipeline_stage(
                metadata,
                "ready",
                state="completed",
                details={"chunks": chunk_count, "text_length": len(extraction.text)},
            )
            db_document.extracted_entities = unique_entities

            content_record = db_document.content
            if content_record is None:
                content_record = DocumentContent(document_id=db_document.id)
                session.add(content_record)
            content_record.raw_text = extraction.text
            content_record.normalized_text = normalized_text
            content_record.extraction_status = "completed"
            content_record.extraction_method = extraction.extraction_method
            content_record.page_count = extraction.page_count
            content_record.page_metadata = extraction.page_metadata
            content_record.scanned_pdf_detected = extraction.scanned_pdf_detected
            content_record.ocr_status = extraction.ocr_status

            superseded_ids = await _reconcile_previous_versions(session, db_document)
            if superseded_ids:
                db_document.metadata_ = record_pipeline_stage(
                    db_document.metadata_,
                    "ready",
                    state="completed",
                    details={"superseded_version_ids": superseded_ids},
                )

            if db_document.processing_job_id:
                await job_state_service.update_job(
                    session,
                    db_document.processing_job_id,
                    status="completed",
                    progress=100,
                    result={"chunks": chunk_count, "text_length": len(extraction.text)},
                    metadata={
                        "current_stage": "ready",
                        "pipeline_trace": pipeline_trace(db_document.metadata_),
                    },
                    completed=True,
                )
            await session.commit()

        observe_document_processing(time.perf_counter() - started, success=True)
        logger.info("Processed document %s into %s chunks", document_id, chunk_count)
        return {"status": "completed", "progress": 100, "chunks": chunk_count}
    except Exception as exc:
        observe_document_processing(time.perf_counter() - started, success=False)
        logger.error("Document processing failed for %s: %s", document_id, exc, exc_info=True)
        async with async_session_factory() as session:
            result = await session.execute(select(Document).where(Document.id == document_uuid))
            db_document = result.scalar_one_or_none()
            if db_document:
                db_document.status = "error"
                db_document.processing_stage = "failed"
                db_document.processing_progress = 100
                db_document.error_message = str(exc)
                db_document.metadata_ = record_pipeline_stage(
                    db_document.metadata_,
                    "failed",
                    state="failed",
                    details={"failed_stage": current_failed_stage},
                    error=str(exc),
                )
                if db_document.previous_version_id:
                    previous = await session.get(Document, db_document.previous_version_id)
                    if previous is not None:
                        previous.is_latest_version = True
                        previous.superseded_at = None
                        db_document.is_latest_version = False
                if db_document.processing_job_id:
                    await job_state_service.update_job(
                        session,
                        db_document.processing_job_id,
                        status="failed",
                        progress=100,
                        error_message=str(exc),
                        metadata={
                            "current_stage": "failed",
                            "pipeline_trace": pipeline_trace(db_document.metadata_),
                        },
                        completed=True,
                    )
                await session.commit()
        raise
