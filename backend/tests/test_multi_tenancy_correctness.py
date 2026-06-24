import pytest
from unittest.mock import patch
from app.core.config import get_settings
from app.services.vector_store import FAISSBackend
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine
import app.services.query_engine as query_engine_module
from app.services.agent import AgentOrchestrator

@pytest.mark.asyncio
async def test_multi_tenancy_retrieval_isolation(tmp_path):
    """Verify that search results are strictly filtered by user_id to prevent data leakage."""
    settings = get_settings()
    
    with patch.object(settings, "vector_store_dir", tmp_path):
        vector_backend = FAISSBackend()
        bm25_backend = BM25Index(use_database=False)
        
        embedder = vector_backend._get_embedder()
        eff_dim = int(embedder.get_sentence_embedding_dimension())
        
        with patch.object(settings, "embedding_dim", eff_dim):
            # Tenant 1 adds document
            t1_chunks = [{"chunk_id": "t1-c1", "text": "Patient has community acquired pneumonia, treated with Ceftriaxone."}]
            vector_backend.add_documents(
                document_id="doc-t1",
                document_name="pneumonia.txt",
                text="",
                metadata={"user_id": "tenant-1"},
                chunks=t1_chunks
            )
            bm25_backend.add_document(t1_chunks, "doc-t1", "pneumonia.txt", user_id="tenant-1")
            
            # Tenant 2 adds document
            t2_chunks = [{"chunk_id": "t2-c1", "text": "Patient diagnosed with systemic lupus erythematosus, positive ANA."}]
            vector_backend.add_documents(
                document_id="doc-t2",
                document_name="lupus.txt",
                text="",
                metadata={"user_id": "tenant-2"},
                chunks=t2_chunks
            )
            bm25_backend.add_document(t2_chunks, "doc-t2", "lupus.txt", user_id="tenant-2")

            # Add a dummy third document to ensure N=3, so BM25 IDF is positive (>0) for single-occurrence terms
            dummy_chunks = [{"chunk_id": "dummy-c1", "text": "unrelated medical record text"}]
            vector_backend.add_documents(
                document_id="doc-dummy",
                document_name="dummy.txt",
                text="",
                metadata={"user_id": "dummy-tenant"},
                chunks=dummy_chunks
            )
            bm25_backend.add_document(dummy_chunks, "doc-dummy", "dummy.txt", user_id="dummy-tenant")
            
            # Verify total count is 3
            stats = vector_backend.get_stats()
            assert stats["total_chunks"] == 3
            
            # Query as Tenant 1
            t1_query = "pneumonia"
            t1_dense = vector_backend.search(t1_query, top_k=5, filters={"user_id": "tenant-1"})
            assert len(t1_dense) == 1
            assert t1_dense[0].chunk_id == "t1-c1"
            
            # Query as Tenant 1 for Tenant 2's content (should not return Tenant 2's document)
            t1_dense_leak = vector_backend.search("lupus", top_k=5, filters={"user_id": "tenant-1"})
            for r in t1_dense_leak:
                assert r.document_name != "lupus.txt"
            
            # BM25 isolation check
            t1_sparse = bm25_backend.search("pneumonia", top_k=5, user_id="tenant-1")
            assert len(t1_sparse) == 1
            assert t1_sparse[0]["chunk_id"] == "t1-c1"
            
            t1_sparse_leak = bm25_backend.search("lupus", top_k=5, user_id="tenant-1")
            assert len(t1_sparse_leak) == 0
            
            # Hybrid Query Engine isolation check
            with (
                patch.object(query_engine_module, "vector_store_service", vector_backend),
                patch.object(query_engine_module, "bm25_index", bm25_backend)
            ):
                engine = QueryEngine()
                
                # Run query for Tenant 1 (should not leak Tenant 2's document)
                res_t1 = await engine.query("lupus", top_k=5, user_id="tenant-1", use_reranking=False, expand_query=False)
                for r in res_t1.results:
                    assert r.get("document_name") != "lupus.txt"
                
                res_t2 = await engine.query("lupus", top_k=5, user_id="tenant-2", use_reranking=False, expand_query=False)
                assert len(res_t2.results) == 1
                assert res_t2.results[0]["chunk_id"] == "t2-c1"

def test_agent_parameter_injection_user_override():
    """Verify that agent orchestrator unconditionally overrides user_id and image_id parameters from the state context."""
    orchestrator = AgentOrchestrator()
    
    state = {
        "user_id": "tenant-secured",
        "image_id": "image-secured",
    }
    
    # 1. Test user_id override for document/graph search tools
    params_search = {
        "query": "What meds was the patient on?",
        "user_id": "tenant-malicious",
    }
    injected_search = orchestrator._inject_runtime_params(
        tool_name="search_documents",
        params=params_search,
        state=state
    )
    assert injected_search["user_id"] == "tenant-secured"
    
    # 2. Test image_id override for vision analysis tool
    params_vision = {
        "image_id": "image-malicious",
        "additional_context": "chest x-ray",
    }
    injected_vision = orchestrator._inject_runtime_params(
        tool_name="analyze_image",
        params=params_vision,
        state=state
    )
    assert injected_vision["image_id"] == "image-secured"
