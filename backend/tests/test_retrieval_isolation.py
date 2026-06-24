import pytest
from unittest.mock import patch, AsyncMock
from app.core.config import get_settings
from app.services.vector_store import FAISSBackend
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine
import app.services.query_engine as query_engine_module
from app.services.tool_registry import tool_search_documents

@pytest.mark.asyncio
async def test_retrieval_isolation_scenarios(tmp_path):
    """Test all isolation, fail-closed, and overfetch behaviors for multi-tenancy."""
    settings = get_settings()
    
    with patch.object(settings, "vector_store_dir", tmp_path):
        # 1. Setup mock indices
        vector_backend = FAISSBackend()
        bm25_backend = BM25Index(use_database=False)
        
        embedder = vector_backend._get_embedder()
        eff_dim = int(embedder.get_sentence_embedding_dimension())
        
        with patch.object(settings, "embedding_dim", eff_dim):
            # Tenant 1, Patient A document
            t1_pa_chunks = [{"chunk_id": "c-t1-pa", "text": "Patient Alpha has type 2 diabetes and hypertension."}]
            vector_backend.add_documents(
                document_id="doc-t1-pa",
                document_name="t1_alpha.txt",
                text="",
                metadata={
                    "user_id": "user-1",
                    "tenant_id": "tenant-1",
                    "patient_id": "patient-a",
                    "organization_id": "org-1",
                    "owner": "user-1"
                },
                chunks=t1_pa_chunks
            )
            bm25_backend.add_document(
                t1_pa_chunks,
                "doc-t1-pa",
                "t1_alpha.txt",
                user_id="user-1",
                metadata={
                    "tenant_id": "tenant-1",
                    "patient_id": "patient-a",
                    "organization_id": "org-1",
                    "owner": "user-1",
                },
            )

            # Tenant 1, Patient B document
            t1_pb_chunks = [{"chunk_id": "c-t1-pb", "text": "Patient Beta has asthma and uses an albuterol inhaler."}]
            vector_backend.add_documents(
                document_id="doc-t1-pb",
                document_name="t1_beta.txt",
                text="",
                metadata={
                    "user_id": "user-1",
                    "tenant_id": "tenant-1",
                    "patient_id": "patient-b",
                    "organization_id": "org-1",
                    "owner": "user-1"
                },
                chunks=t1_pb_chunks
            )
            bm25_backend.add_document(
                t1_pb_chunks,
                "doc-t1-pb",
                "t1_beta.txt",
                user_id="user-1",
                metadata={
                    "tenant_id": "tenant-1",
                    "patient_id": "patient-b",
                    "organization_id": "org-1",
                    "owner": "user-1",
                },
            )

            # Tenant 2, Patient C document (cross-tenant)
            t2_pc_chunks = [{"chunk_id": "c-t2-pc", "text": "Patient Gamma has chronic kidney disease stage 3."}]
            vector_backend.add_documents(
                document_id="doc-t2-pc",
                document_name="t2_gamma.txt",
                text="",
                metadata={
                    "user_id": "user-2",
                    "tenant_id": "tenant-2",
                    "patient_id": "patient-c",
                    "organization_id": "org-2",
                    "owner": "user-2"
                },
                chunks=t2_pc_chunks
            )
            bm25_backend.add_document(
                t2_pc_chunks,
                "doc-t2-pc",
                "t2_gamma.txt",
                user_id="user-2",
                metadata={
                    "tenant_id": "tenant-2",
                    "patient_id": "patient-c",
                    "organization_id": "org-2",
                    "owner": "user-2",
                },
            )

            # Verify size
            assert vector_backend.get_stats()["total_chunks"] == 3

            # Mock in QueryEngine
            mock_generate = AsyncMock(return_value="alternative 1\nalternative 2")
            
            def mock_rerank_fn(query, candidates, top_k=5, **kwargs):
                from app.services.reranker import RankedResult, RerankResult
                return RerankResult(
                    items=[
                        RankedResult(
                            chunk_text=c["chunk_text"],
                            chunk_index=c["chunk_index"],
                            document_id=c["document_id"],
                            document_name=c["document_name"],
                            original_score=c.get("score", 0.0),
                            rerank_score=c.get("score", 0.0) + 0.8,
                            chunk_id=c.get("chunk_id", ""),
                            page_start=c.get("page_start"),
                            page_end=c.get("page_end"),
                            source_offset_start=c.get("source_offset_start"),
                            source_offset_end=c.get("source_offset_end"),
                        )
                        for c in candidates[:top_k]
                    ],
                    applied=True,
                    model_loaded=True,
                    fallback_reason=None,
                    latency_ms=1.0,
                )

            with (
                patch.object(query_engine_module, "vector_store_service", vector_backend),
                patch.object(query_engine_module, "bm25_index", bm25_backend),
                patch("app.services.query_engine.reranker_service.rerank_with_metadata", side_effect=mock_rerank_fn),
                patch("app.services.query_engine.llm_service.generate", mock_generate),
            ):
                engine = QueryEngine()

                # A. Fail-Closed behavior if no context is provided
                with pytest.raises(ValueError) as exc:
                    await engine.query("asthma", allow_unfiltered=False)
                assert "Access isolation context missing" in str(exc.value)

                # B. Dense-only retrieval respects filters (semantic search retrieves closest tenant-1 matches, none of tenant-2)
                res_dense = await engine.query(
                    "kidney",
                    mode="dense",
                    tenant_id="tenant-1",
                    allow_unfiltered=False
                )
                assert len(res_dense.results) == 2
                for r in res_dense.results:
                    assert r["chunk_id"] in {"c-t1-pa", "c-t1-pb"}
                    assert r["chunk_id"] != "c-t2-pc"

                # C. Sparse-only retrieval respects filters (keyword exact, returns only matching tenant-2)
                res_sparse = await engine.query(
                    "kidney",
                    mode="sparse",
                    tenant_id="tenant-2",
                    allow_unfiltered=False
                )
                assert len(res_sparse.results) == 1
                assert res_sparse.results[0]["chunk_id"] == "c-t2-pc"

                # D. Hybrid retrieval respects filters
                res_hybrid = await engine.query(
                    "diabetes",
                    mode="hybrid",
                    user_id="user-1",
                    allow_unfiltered=False
                )
                # Should find both tenant-1 documents since top_k=5 and both match user_id filter, but diabetes is top rank
                assert len(res_hybrid.results) == 2
                assert res_hybrid.results[0]["chunk_id"] == "c-t1-pa"

                # E. No cross-tenant leakage: Querying for Tenant 2's content as Tenant 1
                res_leak_tenant = await engine.query(
                    "kidney",
                    mode="hybrid",
                    tenant_id="tenant-1",
                    allow_unfiltered=False
                )
                # Should not leak PC
                for r in res_leak_tenant.results:
                    assert r["chunk_id"] != "c-t2-pc"

                # F. No cross-patient leakage: Querying for Patient B's content as Patient A (same tenant)
                res_leak_patient = await engine.query(
                    "asthma",
                    mode="hybrid",
                    tenant_id="tenant-1",
                    patient_id="patient-a",
                    allow_unfiltered=False
                )
                # Should not return patient-b doc c-t1-pb
                for r in res_leak_patient.results:
                    assert r["chunk_id"] != "c-t1-pb"

                # Patient B query finds Beta's doc
                res_correct_patient = await engine.query(
                    "asthma",
                    mode="hybrid",
                    tenant_id="tenant-1",
                    patient_id="patient-b",
                    allow_unfiltered=False
                )
                assert len(res_correct_patient.results) == 1
                assert res_correct_patient.results[0]["chunk_id"] == "c-t1-pb"

                # G. Adaptive overfetch check:
                # We have 3 chunks in FAISS.
                # If we filter by tenant-2, FAISS should search index.ntotal, retrieve and match only the t2 doc.
                res_overfetch = vector_backend.search("asthma", top_k=2, filters={"tenant_id": "tenant-2"})
                for r in res_overfetch:
                    assert r.document_name == "t2_gamma.txt"

                # H. Agent retrieval tool uses the same rules
                with patch("app.services.tool_registry.query_engine", engine):
                    tool_res = await tool_search_documents(
                        query="kidney",
                        tenant_id="tenant-1",
                        user_id="user-1",
                    )
                    for r in tool_res["results"]:
                        assert r["source"] != "t2_gamma.txt"

                    tool_res_correct = await tool_search_documents(
                        query="kidney",
                        tenant_id="tenant-2",
                        user_id="user-2",
                    )
                    assert len(tool_res_correct["results"]) == 1
