"""
Unit tests for the vector store caching mechanism and its isolation safety gates.
"""

from unittest.mock import MagicMock, patch
from app.core.config import get_settings
from app.core.caching import CacheManager
from app.services.vector_store import VectorStoreService, SearchResult


def test_vector_search_cache_flow(tmp_path):
    """Test the complete cache flow: write on first search, hit on second, and namedtuple reconstruction."""
    settings = get_settings()
    
    with (
        patch.object(settings, "cache_enabled", True),
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_dim", 128)
    ):
        # Clear cache first
        CacheManager.clear()
        
        # Instantiate VectorStoreService
        service = VectorStoreService()
        
        # Mock the backend search method
        mock_results = [
            SearchResult(
                chunk_text="Patient has history of asthma",
                chunk_index=2,
                document_id="doc-123",
                document_name="history.pdf",
                score=0.98,
                chunk_id="chk-abc",
                page_start=1,
                page_end=2,
                source_offset_start=100,
                source_offset_end=200
            )
        ]
        
        mock_backend = MagicMock()
        mock_backend.search.return_value = mock_results
        
        with patch.object(service, "_get_backend", return_value=mock_backend):
            filters = {"patient_id": "pat-1", "tenant_id": "tenant-1"}
            
            # First search: should call backend search and cache the results
            results1 = service.search("asthma", top_k=5, filters=filters)
            assert len(results1) == 1
            assert results1[0].chunk_text == "Patient has history of asthma"
            assert results1[0].chunk_index == 2
            assert results1[0].document_id == "doc-123"
            assert results1[0].document_name == "history.pdf"
            assert results1[0].score == 0.98
            assert results1[0].chunk_id == "chk-abc"
            assert results1[0].page_start == 1
            assert results1[0].page_end == 2
            assert results1[0].source_offset_start == 100
            assert results1[0].source_offset_end == 200
            
            # Check backend was called once
            mock_backend.search.assert_called_once_with("asthma", 5, filters)
            
            # Reset call count on mock
            mock_backend.search.reset_mock()
            
            # Second search: should hit cache and NOT call backend
            results2 = service.search("asthma", top_k=5, filters=filters)
            assert len(results2) == 1
            assert results2[0].chunk_text == "Patient has history of asthma"
            assert results2[0].chunk_index == 2
            assert results2[0].document_id == "doc-123"
            assert results2[0].document_name == "history.pdf"
            assert results2[0].score == 0.98
            assert results2[0].chunk_id == "chk-abc"
            assert results2[0].page_start == 1
            assert results2[0].page_end == 2
            assert results2[0].source_offset_start == 100
            assert results2[0].source_offset_end == 200
            
            # Verify backend was NOT called
            mock_backend.search.assert_not_called()


def test_vector_search_cache_isolation(tmp_path):
    """Test that cache is partitioned and isolated by patient_id and tenant_id."""
    settings = get_settings()
    
    with (
        patch.object(settings, "cache_enabled", True),
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_dim", 128)
    ):
        CacheManager.clear()
        service = VectorStoreService()
        
        mock_backend = MagicMock()
        with patch.object(service, "_get_backend", return_value=mock_backend):
            # Query for Patient 1
            mock_backend.search.return_value = [
                SearchResult(
                    chunk_text="Patient 1 clinical note",
                    chunk_index=0,
                    document_id="doc-p1",
                    document_name="note1.txt",
                    score=0.9
                )
            ]
            
            filters_p1 = {"patient_id": "pat-1", "tenant_id": "tenant-A"}
            res1 = service.search("fever", top_k=1, filters=filters_p1)
            assert len(res1) == 1
            assert res1[0].chunk_text == "Patient 1 clinical note"
            
            # Verify backend called once
            mock_backend.search.assert_called_once()
            mock_backend.search.reset_mock()
            
            # Query for Patient 2 (different patient, same tenant)
            mock_backend.search.return_value = [
                SearchResult(
                    chunk_text="Patient 2 clinical note",
                    chunk_index=0,
                    document_id="doc-p2",
                    document_name="note2.txt",
                    score=0.85
                )
            ]
            
            filters_p2 = {"patient_id": "pat-2", "tenant_id": "tenant-A"}
            res2 = service.search("fever", top_k=1, filters=filters_p2)
            assert len(res2) == 1
            assert res2[0].chunk_text == "Patient 2 clinical note"
            
            # Verify backend is called again because of patient isolation
            mock_backend.search.assert_called_once()
            mock_backend.search.reset_mock()
            
            # Query for Patient 1 on different tenant
            mock_backend.search.return_value = [
                SearchResult(
                    chunk_text="Patient 1 tenant B note",
                    chunk_index=0,
                    document_id="doc-p1-tb",
                    document_name="note1b.txt",
                    score=0.87
                )
            ]
            
            filters_p1_tb = {"patient_id": "pat-1", "tenant_id": "tenant-B"}
            res3 = service.search("fever", top_k=1, filters=filters_p1_tb)
            assert len(res3) == 1
            assert res3[0].chunk_text == "Patient 1 tenant B note"
            
            # Verify backend is called again because of tenant isolation
            mock_backend.search.assert_called_once()


def test_vector_search_cache_bypass_on_missing_context(tmp_path):
    """Test that cache is bypassed gracefully if patient_id or tenant_id context is missing."""
    settings = get_settings()
    
    with (
        patch.object(settings, "cache_enabled", True),
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_dim", 128)
    ):
        CacheManager.clear()
        service = VectorStoreService()
        
        mock_backend = MagicMock()
        mock_backend.search.return_value = [
            SearchResult(
                chunk_text="Unfiltered search result",
                chunk_index=0,
                document_id="doc-global",
                document_name="global.txt",
                score=0.5
            )
        ]
        
        with patch.object(service, "_get_backend", return_value=mock_backend):
            # Search without filters/context
            res = service.search("fever", top_k=5, filters=None)
            assert len(res) == 1
            assert res[0].chunk_text == "Unfiltered search result"
            mock_backend.search.assert_called_once()
            mock_backend.search.reset_mock()
            
            # A second identical search should NOT hit cache because context was missing
            # (ValueError is caught, cache bypassed, and backend queried again)
            res2 = service.search("fever", top_k=5, filters=None)
            assert len(res2) == 1
            mock_backend.search.assert_called_once()
