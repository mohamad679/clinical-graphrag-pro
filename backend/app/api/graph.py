"""
Knowledge graph API endpoints.
Stats from vector store + placeholder for graph features.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.vector_store import vector_store_service
from app.services.graph import temporal_graph_service

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


@router.get("/stats")
async def graph_stats():
    """Return knowledge base statistics."""
    vs_stats = vector_store_service.get_stats()
    
    # Calculate edge count for NetworkX MultiDiGraph
    edge_count = temporal_graph_service.graph.number_of_edges()
    node_count = temporal_graph_service.graph.number_of_nodes()
    
    return {
        "vector_store": vs_stats,
        "knowledge_graph": {
            "nodes": node_count,
            "edges": edge_count,
            "status": "active_temporal",
        },
    }

class SeedGraphRequest(BaseModel):
    patient_id: str = "Patient_A"

@router.post("/seed")
async def seed_temporal_graph(req: SeedGraphRequest):
    """Seed the temporal graph with chronological test data."""
    # Seed Patient
    temporal_graph_service.add_entity(req.patient_id, "Patient", {"age": 65, "gender": "M"})
    
    # Seed Drugs Data
    temporal_graph_service.add_entity("Lisinopril", "Drug")
    temporal_graph_service.add_entity("Ibuprofen", "Drug")
    
    # Seed Diseases
    temporal_graph_service.add_entity("Hypertension", "Disease")
    temporal_graph_service.add_entity("Chronic_Kidney_Disease", "Disease")
    
    # Add Temporal Edges (Chronology)
    # Patient had hypertension from 2020, still active
    temporal_graph_service.add_temporal_relation(
        req.patient_id, "Hypertension", "HAS_CONDITION", "2020-01-01"
    )
    # Patient took Lisinopril from 2021-06-01 to 2023-12-01 (stopped)
    temporal_graph_service.add_temporal_relation(
        req.patient_id, "Lisinopril", "PRESCRIBED", "2021-06-01", "2023-12-01"
    )
    # Patient started Ibuprofen recently
    temporal_graph_service.add_temporal_relation(
        req.patient_id, "Ibuprofen", "PRESCRIBED", "2024-01-15"
    )
    
    return {"message": "Temporal Graph seeded successfully", "nodes": temporal_graph_service.graph.number_of_nodes()}


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
