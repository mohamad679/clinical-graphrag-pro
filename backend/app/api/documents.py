"""
Document upload and management API endpoints.
Now backed by PostgreSQL instead of in-memory dict.
"""

import hashlib
import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.models.document import Document
from app.services.vector_store import vector_store_service
from app.schemas.document import DocumentUploadResponse, DocumentListResponse, DocumentResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])

settings = get_settings()

# Ensure upload directory exists
UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF or text document for RAG processing.
    Chunks the document, embeds it, and adds it to the vector store.
    Metadata is persisted in PostgreSQL.
    """
    # Validate file type
    allowed_types = {".pdf", ".txt", ".md", ".csv"}
    suffix = Path(file.filename or "unknown").suffix.lower()
    if suffix not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(allowed_types)}",
        )

    # Read file content
    content_bytes = await file.read()

    # Check size
    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(content_bytes) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.max_upload_size_mb}MB",
        )

    # Compute hash for deduplication
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Check if already exists in DB
    existing = await db.execute(
        select(Document).where(Document.content_hash == content_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Document already uploaded.")

    # Extract text based on file type
    text = ""
    if suffix == ".pdf":
        text = _extract_pdf_text(content_bytes)
    else:
        text = content_bytes.decode("utf-8", errors="replace")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from document.")

    # Save file to disk
    doc_id = str(uuid4())
    file_path = UPLOAD_DIR / f"{doc_id}{suffix}"
    file_path.write_bytes(content_bytes)

    # Index in vector store
    chunk_count = vector_store_service.add_document(
        document_id=doc_id,
        document_name=file.filename or "unknown",
        text=text,
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )

    # Persist to PostgreSQL
    doc = Document(
        id=doc_id,
        filename=file.filename or "unknown",
        content_hash=content_hash,
        file_size=len(content_bytes),
        file_type=suffix.lstrip("."),
        chunk_count=chunk_count,
        status="ready",
        processed_at=datetime.now(timezone.utc),
        metadata_={"original_suffix": suffix, "text_length": len(text)},
    )
    db.add(doc)
    # session.commit() handled by get_db dependency

    logger.info(f"Uploaded and indexed '{file.filename}' → {chunk_count} chunks")

    return DocumentUploadResponse(
        id=doc_id,
        filename=file.filename or "unknown",
        status="ready",
        chunk_count=chunk_count,
        message=f"Document processed successfully. {chunk_count} chunks indexed.",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all uploaded documents from PostgreSQL."""
    result = await db.execute(
        select(Document).order_by(Document.uploaded_at.desc())
    )
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                filename=d.filename,
                file_size=d.file_size,
                chunk_count=d.chunk_count,
                status=d.status,
                uploaded_at=d.uploaded_at,
                processed_at=d.processed_at,
                error_message=d.error_message,
            )
            for d in documents
        ],
        total=len(documents),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single document's metadata."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_size=doc.file_size,
        chunk_count=doc.chunk_count,
        status=doc.status,
        uploaded_at=doc.uploaded_at,
        processed_at=doc.processed_at,
        error_message=doc.error_message,
    )


@router.delete("/{document_id}")
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a document from DB and disk."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove file from disk
    for suffix in [".pdf", ".txt", ".md", ".csv"]:
        fp = UPLOAD_DIR / f"{document_id}{suffix}"
        if fp.exists():
            fp.unlink()
            break

    await db.delete(doc)
    return {"message": "Document deleted. Note: vector store entries remain until rebuild."}


def _extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF using PyPDF2."""
    try:
        import io
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("PyPDF2 not installed. Install with: pip install PyPDF2")
        return ""
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""
