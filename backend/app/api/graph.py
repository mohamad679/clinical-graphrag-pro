"""
Knowledge graph API endpoints.
Stats from vector store + placeholder for graph features.
"""

from fastapi import APIRouter, HTTPException
import os
from neo4j import AsyncGraphDatabase
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

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")

@router.get("/visualize")
async def graph_visualize(limit: int = 500):
    """
    Fetches a subgraph from Neo4j formatted as Nodes and Links for react-force-graph-3d.
    Limits the number of nodes to prevent overwhelming the browser.
    """
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    cypher_query = f"""
    MATCH (n)
    WITH n LIMIT {limit}
    OPTIONAL MATCH (n)-[r]->(m)
    WITH collect(DISTINCT n) + collect(DISTINCT m) AS all_nodes, collect(DISTINCT r) AS all_rels
    UNWIND all_nodes AS node
    WITH collect(DISTINCT node) AS nodes, all_rels
    UNWIND all_rels AS rel
    RETURN nodes, collect(DISTINCT rel) AS rels
    """
    
    try:
        async with driver.session() as session:
            result = await session.run(cypher_query)
            record = await result.single()
            
            if not record:
                 return {"nodes": [], "links": []}
                 
            nodes_data = record["nodes"]
            rels_data = record["rels"]
            
            nodes = []
            links = []
            
            for node in nodes_data:
                if node is None: continue
                properties = dict(node.items())
                node_id = properties.get("id", getattr(node, "element_id", id(node)))
                labels = list(node.labels) if hasattr(node, "labels") else ["Node"]
                label = labels[0] if labels else "Node"
                
                nodes.append({
                    "id": str(node_id),
                    "label": label,
                    "name": properties.get("name") or properties.get("title") or str(node_id),
                    "properties": properties
                })
                
            for rel in rels_data:
                if rel is None: continue
                properties = dict(rel.items())
                try:
                     start_node = rel.start_node
                     end_node = rel.end_node
                     start_id = dict(start_node.items()).get("id", start_node.element_id)
                     end_id = dict(end_node.items()).get("id", end_node.element_id)
                     
                     links.append({
                         "source": str(start_id),
                         "target": str(end_id),
                         "type": rel.type,
                         "properties": properties
                     })
                except AttributeError:
                     pass
                     
            return {"nodes": nodes, "links": links}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await driver.close()

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
