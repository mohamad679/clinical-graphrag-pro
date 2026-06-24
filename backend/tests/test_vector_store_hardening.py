import pytest
import json
import pickle
import faiss
from unittest.mock import patch
from app.core.config import get_settings
from app.services.vector_store import FAISSBackend

def test_faiss_load_missing_metadata(tmp_path):
    """Loading index.faiss and chunks.pkl should fail if index_metadata.json is missing."""
    settings = get_settings()
    
    # Pre-populate index files
    index = faiss.IndexFlatIP(128)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    with open(tmp_path / "chunks.pkl", "wb") as f:
        pickle.dump([], f)
        
    with patch.object(settings, "vector_store_dir", tmp_path):
        backend = FAISSBackend()
        with pytest.raises(ValueError) as exc_info:
            backend._get_index()
        assert "metadata is missing" in str(exc_info.value)

def test_faiss_load_model_mismatch(tmp_path):
    """Loading should fail if the configured embedding model does not match the stored model."""
    settings = get_settings()
    
    # Pre-populate index files
    index = faiss.IndexFlatIP(128)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    with open(tmp_path / "chunks.pkl", "wb") as f:
        pickle.dump([], f)
    
    # Store metadata with mismatched model
    metadata = {
        "embedding_model": "old-model-name",
        "embedding_dimension": 128,
        "index_type": "FAISS_IndexFlatIP"
    }
    with open(tmp_path / "index_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f)
        
    with (
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_model", "new-model-name"),
        patch.object(settings, "embedding_dim", 128)
    ):
        backend = FAISSBackend()
        with pytest.raises(ValueError) as exc_info:
            backend._get_index()
        assert "Embedding model mismatch" in str(exc_info.value)

def test_faiss_load_dimension_mismatch(tmp_path):
    """Loading should fail if the configured embedding dim does not match the stored dim."""
    settings = get_settings()
    
    # Pre-populate index files
    index = faiss.IndexFlatIP(128)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    with open(tmp_path / "chunks.pkl", "wb") as f:
        pickle.dump([], f)
    
    # Store metadata with mismatched dimension
    metadata = {
        "embedding_model": "test-model",
        "embedding_dimension": 256, # stored mismatch
        "index_type": "FAISS_IndexFlatIP"
    }
    with open(tmp_path / "index_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f)
        
    with (
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_model", "test-model"),
        patch.object(settings, "embedding_dim", 128)
    ):
        backend = FAISSBackend()
        with pytest.raises(ValueError) as exc_info:
            backend._get_index()
        assert "Embedding dimension mismatch" in str(exc_info.value)

def test_faiss_load_internal_d_mismatch(tmp_path):
    """Loading should fail if the FAISS index internal dimension does not match settings."""
    settings = get_settings()
    
    # Pre-populate index with 256 dims
    index = faiss.IndexFlatIP(256)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    with open(tmp_path / "chunks.pkl", "wb") as f:
        pickle.dump([], f)
    
    # Store metadata matching 128 (but file is 256!)
    metadata = {
        "embedding_model": "test-model",
        "embedding_dimension": 128,
        "index_type": "FAISS_IndexFlatIP"
    }
    with open(tmp_path / "index_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f)
        
    with (
        patch.object(settings, "vector_store_dir", tmp_path),
        patch.object(settings, "embedding_model", "test-model"),
        patch.object(settings, "embedding_dim", 128)
    ):
        backend = FAISSBackend()
        with pytest.raises(ValueError) as exc_info:
            backend._get_index()
        assert "internal dimension" in str(exc_info.value)

def test_qdrant_backend_full_flow():
    """Test QdrantBackend with mocked client for all operations."""
    import sys
    import numpy as np
    from unittest.mock import MagicMock, patch
    
    # Pre-register mock qdrant_client
    mock_qdrant = MagicMock()
    mock_models = MagicMock()
    sys.modules["qdrant_client"] = mock_qdrant
    sys.modules["qdrant_client.models"] = mock_models

    from app.services.vector_store import QdrantBackend

    # Mock settings
    settings = get_settings()
    
    with (
        patch.object(settings, "vector_backend", "qdrant"),
        patch.object(settings, "qdrant_url", "http://localhost:6333"),
        patch.object(settings, "qdrant_api_key", "test-key"),
        patch.object(settings, "qdrant_collection", "test_coll"),
        patch.object(settings, "app_env", "testing"),
        patch.object(settings, "embedding_dim", 128)
    ):
        backend = QdrantBackend()
        
        # Mock client calls
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        backend._client = mock_client
        backend._models = mock_models
        backend._collection_ready = True
        
        # Test collection name
        assert backend._collection_name() == "test_coll_testing"
        
        # Mock embedder
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.zeros((1, 128), dtype=np.float32)
        
        with patch.object(backend, "_get_embedder", return_value=mock_embedder):
            # Test add_documents
            chunks = [{"chunk_id": "c1", "chunk_text": "text content", "chunk_index": 0}]
            res = backend.add_documents("doc-1", "doc1.txt", "text content", chunks=chunks)
            assert res == 1
            mock_client.upsert.assert_called_once()
            
            # Mock query points / search
            mock_point = MagicMock()
            mock_point.payload = {
                "chunk_id": "c1",
                "chunk_text": "text content",
                "chunk_index": 0,
                "document_id": "doc-1",
                "document_name": "doc1.txt"
            }
            mock_point.score = 0.95
            mock_client.query_points.return_value = [mock_point]
            
            # Test search
            results = backend.search("query", top_k=2)
            assert len(results) == 1
            assert results[0].chunk_text == "text content"
            assert results[0].score == 0.95
            
            # Mock scroll
            mock_record = MagicMock()
            mock_record.payload = mock_point.payload
            mock_client.scroll.return_value = ([mock_record], None)
            
            # Test get_all_chunks
            all_chunks = backend.get_all_chunks()
            assert len(all_chunks) == 1
            assert all_chunks[0]["chunk_id"] == "c1"
            
            # Test get_chunks_for_document
            doc_chunks = backend.get_chunks_for_document("doc-1")
            assert len(doc_chunks) == 1
            
            # Test delete_document
            del_count = backend.delete_document("doc-1")
            assert del_count == 1
            mock_client.delete.assert_called_once()
            
            # Mock collection stats
            mock_coll_detail = MagicMock()
            mock_coll_detail.vectors_count = 1
            mock_coll_detail.points_count = 1
            mock_client.get_collection.return_value = mock_coll_detail
            
            # Test get_stats
            stats = backend.get_stats()
            assert stats["backend"] == "qdrant"
            assert stats["total_vectors"] == 1
