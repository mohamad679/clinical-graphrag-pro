import pytest
from uuid import uuid4
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.bm25_index import BM25Index
from app.models.persistence import DocumentChunk

@pytest.fixture
def phase1_env():
    """Dummy fixture to prevent conftest.py reset_test_db from reloading modules."""
    return None

@pytest.mark.asyncio
async def test_bm25_memory_naive_fallback(phase1_env):
    """Test memory fallback if rank-bm25 is missing or disabled."""
    # Temporarily hide rank_bm25 from sys.modules
    with patch.dict("sys.modules", {"rank_bm25": None}):
        idx = BM25Index(use_database=False)
        idx.add_document([{"text": "heart disease risk", "chunk_id": "c1"}], "doc-1", "doc1.txt")
        # search
        res = idx.search("heart", top_k=2)
        assert len(res) == 1
        assert res[0]["chunk_id"] == "c1"

@pytest.mark.asyncio
async def test_bm25_memory_search_filters(phase1_env):
    idx = BM25Index(use_database=False)
    idx.add_document(
        [{"text": "pneumonia lung infection", "chunk_id": "c1"}],
        "doc-1",
        "doc1.txt",
        user_id="u1",
        metadata={"tenant_id": "tenant-1", "patient_id": "patient-a"},
    )
    idx.add_document(
        [{"text": "lupus systemic disease", "chunk_id": "c2"}],
        "doc-2",
        "doc2.txt",
        user_id="u2",
        metadata={"tenant_id": "tenant-2", "patient_id": "patient-b"},
    )
    idx.add_document([{"text": "completely unrelated medical text", "chunk_id": "c3"}], "doc-3", "doc3.txt", user_id="u3")
    
    # query u1
    res1 = idx.search("infection", user_id="u1")
    assert len(res1) == 1
    assert res1[0]["chunk_id"] == "c1"
    
    # query u2
    res2 = idx.search("infection", user_id="u2")
    assert len(res2) == 0

    scoped = idx.search("infection", filters={"tenant_id": "tenant-1", "patient_id": "patient-a", "user_id": "u1"})
    assert len(scoped) == 1
    assert scoped[0]["chunk_id"] == "c1"

    wrong_patient = idx.search("infection", filters={"tenant_id": "tenant-1", "patient_id": "patient-b", "user_id": "u1"})
    assert wrong_patient == []


def test_bm25_tokenization_preserves_clinical_terms(phase1_env):
    tokens = BM25Index._tokenize("Type 2 diabetes, HbA1c 7.2%, Na+ 132 mmol/L, beta-blocker 5mg qHS.")
    assert "2" in tokens
    assert "hba1c" in tokens
    assert "7.2" in tokens
    assert "na+" in tokens
    assert "mmol/l" in tokens
    assert "mmol" in tokens
    assert "beta-blocker" in tokens
    assert "beta" in tokens
    assert "blocker" in tokens
    assert "5mg" in tokens

@pytest.mark.asyncio
async def test_bm25_database_sqlite_backend(phase1_env):
    # Mock database flow with use_database=True
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    
    chunk1 = DocumentChunk(
        document_id=uuid4(),
        user_id="u1",
        chunk_id="c1",
        chunk_text="coronary artery disease",
        normalized_text="coronary artery disease",
        metadata_={"document_name": "doc1.txt"}
    )
    
    mock_scalar = MagicMock()
    mock_scalar.scalars.return_value.all.return_value = [chunk1]
    mock_session.execute.return_value = mock_scalar
    
    with (
        patch("app.services.bm25_index.async_session_factory", mock_factory),
        patch("app.services.bm25_index.get_settings") as mock_settings
    ):
        mock_settings.return_value.database_url = "sqlite+aiosqlite:///test.db"
        idx = BM25Index(use_database=True)
        
        # Test add document
        res_add = await idx.add_document_async([{"text": "coronary artery disease", "chunk_id": "c1"}], str(chunk1.document_id), "doc1.txt", user_id="u1")
        assert res_add == 1
        
        # Test search async
        res_search = await idx.search_async("coronary", top_k=5, user_id="u1")
        assert len(res_search) == 1
        assert res_search[0]["chunk_id"] == "c1"
        assert res_search[0]["score"] > 0
        
        # Test stats
        mock_scalar_stats = MagicMock()
        mock_scalar_stats.scalar.side_effect = [10, 2, 0, 55] # chunks, documents, empty chunks, tokens
        mock_session.execute.return_value = mock_scalar_stats
        
        stats = await idx.get_stats_async()
        assert stats["total_documents"] == 10
        assert stats["active_documents"] == 2
        assert stats["empty_document_count"] == 0
        assert stats["token_count"] == 55
        
        # Test mark deleted
        mock_scalar_del = MagicMock()
        mock_scalar_del.scalar.return_value = 2
        mock_session.execute.return_value = mock_scalar_del
        
        deleted = await idx.mark_document_deleted_async(str(chunk1.document_id))
        assert deleted == 2

@pytest.mark.asyncio
async def test_bm25_database_postgresql_backend(phase1_env):
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    
    chunk_row = MagicMock()
    chunk_row.DocumentChunk = MagicMock(
        document_id=uuid4(),
        chunk_id="c1",
        chunk_text="chronic heart failure",
        chunk_index=0,
        page_start=1,
        page_end=2,
        source_offset_start=0,
        source_offset_end=10,
        metadata_={"document_name": "doc1.txt"}
    )
    chunk_row.score = 0.85
    
    mock_result = MagicMock()
    mock_result.all.return_value = [chunk_row]
    mock_session.execute.return_value = mock_result
    
    with (
        patch("app.services.bm25_index.async_session_factory", mock_factory),
        patch("app.services.bm25_index.get_settings") as mock_settings
    ):
        mock_settings.return_value.database_url = "postgresql+asyncpg://user:pass@host/db"
        mock_settings.return_value.postgres_fts_config = "english"
        
        idx = BM25Index(use_database=True)
        res = await idx.search_async("heart", top_k=2, user_id="u1")
        assert len(res) == 1
        assert res[0]["chunk_id"] == "c1"
        assert res[0]["score"] == 0.85

def test_bm25_sync_wrappers_handling_runtime_error(phase1_env):
    idx = BM25Index(use_database=True)
    
    mock_add = AsyncMock(return_value=5)
    mock_search = AsyncMock(return_value=[])
    mock_del = AsyncMock(return_value=3)
    mock_stats = AsyncMock(return_value={"total_documents": 5})
    
    with (
        patch.object(idx, "add_document_async", mock_add),
        patch.object(idx, "search_async", mock_search),
        patch.object(idx, "mark_document_deleted_async", mock_del),
        patch.object(idx, "get_stats_async", mock_stats)
    ):
        res_add = idx.add_document([], "doc-1", "doc1.txt")
        assert res_add == 5
        
        res_search = idx.search("heart")
        assert res_search == []
        
        res_del = idx.mark_document_deleted("doc-1")
        assert res_del == 3
        
        stats = idx.get_stats()
        assert stats["total_documents"] == 5
