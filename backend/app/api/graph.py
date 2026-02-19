"""
Knowledge graph API endpoints.
Stats from vector store + placeholder for graph features.
"""

from fastapi import APIRouter

from app.services.vector_store import vector_store_service

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


@router.get("/stats")
async def graph_stats():
    """Return knowledge base statistics."""
    vs_stats = vector_store_service.get_stats()
    return {
        "vector_store": vs_stats,
        "knowledge_graph": {
            "nodes": 0,
            "edges": 0,
            "status": "coming_in_phase_4",
        },
    }


@router.get("/search")
async def graph_search(q: str = "", top_k: int = 5):
    """Semantic search across the knowledge base."""
    if not q:
        return {"message": "Provide a query parameter ?q=..."}

    results = vector_store_service.search(q, top_k=top_k)
    return {
        "query": q,
        "total": len(results),
        "results": [
            {
                "document_id": r.document_id,
                "document_name": r.document_name,
                "chunk_index": r.chunk_index,
                "text": r.chunk_text[:300],
                "score": r.score,
            }
            for r in results
        ],
    }
