"""
Knowledge Graph API endpoints.
Production-safe graph ingestion, scoped queries, visualization, and dev-only seed data.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.auth import User, require_role
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.retrieval_scope import retrieval_scope_for_user
from app.models.persistence import GraphEdge, GraphNode
from app.services.graph import FORMAL_GRAPH_SCHEMA, temporal_graph_service
from app.services.vector_store import vector_store_service
from app.services.query_engine import query_engine

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])
logger = logging.getLogger(__name__)
graph_reader = require_role("physician")
graph_admin = require_role("admin")
PATIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _tenant_scope_for_user(user: User) -> str | None:
    return None if user.role == "admin" else user.id


def _scoped_graph_properties(
    properties: dict | None,
    *,
    tenant_id: str | None,
    patient_id: str | None,
) -> bool:
    props = properties or {}
    if tenant_id is not None and props.get("tenant_id") != tenant_id:
        return False
    if patient_id is not None and props.get("patient_id") != patient_id:
        return False
    return True


async def _build_patient_lab_trends_payload(
    patient_id: str,
    *,
    tenant_id: str | None,
    lab_name: str | None = None,
    limit: int = 100,
) -> dict | None:
    capped_limit = max(1, min(int(limit), 200))
    requested_lab = (lab_name or "").strip().lower()

    async with async_session_factory() as session:
        nodes = (await session.execute(select(GraphNode))).scalars().all()

        patient_node = None
        for node in nodes:
            if node.label != "Patient":
                continue
            if not _scoped_graph_properties(node.properties, tenant_id=tenant_id, patient_id=patient_id):
                continue
            props = node.properties or {}
            candidates = {
                node.node_id.lower(),
                str(props.get("name") or "").lower(),
                str(props.get("patient_id") or "").lower(),
            }
            if patient_id.lower() in candidates:
                patient_node = node
                break

        if patient_node is None:
            return None

        edge_rows = (
            await session.execute(
                select(GraphEdge).where(
                    GraphEdge.source_id == patient_node.node_id,
                    GraphEdge.relationship_type == "LAB_RESULT",
                )
            )
        ).scalars().all()

        lab_points: dict[str, list[dict]] = defaultdict(list)
        lab_labels: dict[str, str] = {}

        for edge in edge_rows:
            if not _scoped_graph_properties(edge.properties, tenant_id=tenant_id, patient_id=patient_id):
                continue
            target_node = await session.get(GraphNode, edge.target_id)
            if target_node is None or target_node.label != "Lab":
                continue

            target_props = target_node.properties or {}
            label = str(target_props.get("name") or edge.target_id)
            if requested_lab and requested_lab not in label.lower():
                continue

            edge_props = edge.properties or {}
            value = edge_props.get("value_numeric")
            if value is None:
                value = edge_props.get("value")

            point = {
                "date": edge.start_date,
                "value": value,
                "raw_value": edge_props.get("value"),
                "unit": edge_props.get("unit"),
                "reference_range": edge_props.get("reference_range"),
                "source_type": edge_props.get("source_type"),
                "source_id": edge_props.get("source_id"),
            }
            lab_points[label].append(point)
            lab_labels[label] = label

    labs = []
    for label in sorted(lab_labels):
        points = sorted(
            lab_points[label],
            key=lambda item: (item.get("date") or "", str(item.get("value") or "")),
        )[:capped_limit]
        latest = points[-1] if points else None
        labs.append(
            {
                "lab": label,
                "points": points,
                "latest": latest,
                "trend_count": len(points),
            }
        )

    return {
        "patient_id": patient_node.node_id,
        "labs": labs,
        "total_labs": len(labs),
        "source": "temporal_graph",
    }


@router.get("/stats")
async def graph_stats(user: User = Depends(graph_reader)):
    """Return graph statistics and the supported schema."""
    vs_stats = vector_store_service.get_stats()
    graph_stats_payload = await temporal_graph_service.get_stats()

    return {
        "vector_store": vs_stats,
        "knowledge_graph": graph_stats_payload,
        "schema": FORMAL_GRAPH_SCHEMA,
        "scope": "global" if user.role == "admin" else "tenant",
    }


@router.get("/visualize")
async def graph_visualize(
    limit: int = 100,
    patient_id: str | None = None,
    user: User = Depends(graph_reader),
):
    """Fetch a bounded graph representation using the configured backend."""
    return await temporal_graph_service.export_for_visualization(
        limit=limit,
        tenant_id=_tenant_scope_for_user(user),
        patient_id=patient_id,
    )


class SeedGraphRequest(BaseModel):
    patient_id: str = "Patient_A"


@router.post("/seed")
async def seed_temporal_graph(
    req: SeedGraphRequest,
    user: User = Depends(graph_admin),
):
    """Seed the graph with chronological dev/test data."""
    settings = get_settings()
    if settings.app_env == "production" or not settings.graph_seed_enabled:
        raise HTTPException(status_code=404, detail="Graph seed endpoint is disabled in this deployment")

    tenant_id = user.id
    await temporal_graph_service.add_entity(
        req.patient_id,
        "Patient",
        {"name": req.patient_id, "patient_id": req.patient_id, "tenant_id": tenant_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:medication:lisinopril",
        "Medication",
        {"name": "Lisinopril", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:medication:ibuprofen",
        "Medication",
        {"name": "Ibuprofen", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:condition:hypertension",
        "Condition",
        {"name": "Hypertension", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:condition:chronic-kidney-disease",
        "Condition",
        {"name": "Chronic Kidney Disease", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:lab:creatinine",
        "Lab",
        {"name": "Creatinine", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )
    await temporal_graph_service.add_entity(
        f"tenant:{tenant_id}:lab:potassium",
        "Lab",
        {"name": "Potassium", "tenant_id": tenant_id, "patient_id": req.patient_id},
    )

    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:condition:hypertension",
        "HAS_CONDITION",
        "2020-01-01",
        properties={"tenant_id": tenant_id, "patient_id": req.patient_id, "source_type": "seed", "source_id": req.patient_id},
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:medication:lisinopril",
        "TOOK_MEDICATION",
        "2021-06-01",
        "2023-12-01",
        properties={"tenant_id": tenant_id, "patient_id": req.patient_id, "source_type": "seed", "source_id": req.patient_id},
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:medication:ibuprofen",
        "TOOK_MEDICATION",
        "2024-01-15",
        properties={"tenant_id": tenant_id, "patient_id": req.patient_id, "source_type": "seed", "source_id": req.patient_id},
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:lab:creatinine",
        "LAB_RESULT",
        "2022-01-15",
        "2022-01-15",
        properties={
            "tenant_id": tenant_id,
            "patient_id": req.patient_id,
            "source_type": "seed",
            "source_id": req.patient_id,
            "value": "1.1 mg/dL",
            "value_numeric": 1.1,
            "unit": "mg/dL",
            "reference_range": "0.7-1.3 mg/dL",
        },
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:lab:creatinine",
        "LAB_RESULT",
        "2022-06-01",
        "2022-06-01",
        properties={
            "tenant_id": tenant_id,
            "patient_id": req.patient_id,
            "source_type": "seed",
            "source_id": req.patient_id,
            "value": "1.3 mg/dL",
            "value_numeric": 1.3,
            "unit": "mg/dL",
            "reference_range": "0.7-1.3 mg/dL",
        },
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:lab:potassium",
        "LAB_RESULT",
        "2022-01-15",
        "2022-01-15",
        properties={
            "tenant_id": tenant_id,
            "patient_id": req.patient_id,
            "source_type": "seed",
            "source_id": req.patient_id,
            "value": "4.3 mmol/L",
            "value_numeric": 4.3,
            "unit": "mmol/L",
            "reference_range": "3.5-5.1 mmol/L",
        },
    )
    await temporal_graph_service.add_temporal_relation(
        req.patient_id,
        f"tenant:{tenant_id}:lab:potassium",
        "LAB_RESULT",
        "2022-06-01",
        "2022-06-01",
        properties={
            "tenant_id": tenant_id,
            "patient_id": req.patient_id,
            "source_type": "seed",
            "source_id": req.patient_id,
            "value": "4.7 mmol/L",
            "value_numeric": 4.7,
            "unit": "mmol/L",
            "reference_range": "3.5-5.1 mmol/L",
        },
    )

    stats = await temporal_graph_service.get_stats()
    return {"message": "Clinical graph seeded successfully", "nodes": stats["nodes"]}


@router.get("/search")
async def graph_search(
    q: str = "",
    top_k: int = 5,
    user: User = Depends(graph_reader),
):
    """Semantic document search across the knowledge base."""
    if not q:
        return {"message": "Provide a query parameter ?q=..."}

    scope = retrieval_scope_for_user(user)
    if user.role == "admin":
        enriched = await query_engine.maintenance_unfiltered_query(
            q,
            top_k=top_k,
            admin_scope=scope,
            mode="hybrid_rerank",
        )
    else:
        enriched = await query_engine.query(
            q,
            top_k=top_k,
            scope=scope,
            mode="hybrid_rerank",
        )
    return {
        "query": q,
        "total": len(enriched.results),
        "results": [
            {
                "document_id": r["document_id"],
                "document_name": r["document_name"],
                "chunk_index": r["chunk_index"],
                "text": r["chunk_text"][:300],
                "score": r["score"],
            }
            for r in enriched.results
        ],
    }


@router.get("/temporal")
async def graph_temporal(
    entity: str,
    date: str,
    limit: int = 25,
    patient_id: str | None = None,
    current_only: bool = Query(False, description="Filter for current/active relationships only"),
    user: User = Depends(graph_reader),
):
    """Query active graph relationships for a specific entity/date within the caller scope."""
    result = await temporal_graph_service.query_temporal_state(
        entity,
        date,
        tenant_id=_tenant_scope_for_user(user),
        patient_id=patient_id,
        limit=limit,
        current_only=current_only,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/fhir/ingest")
async def ingest_fhir(
    bundle: dict,
    user: User = Depends(graph_reader),
):
    """Ingest a FHIR resource or Bundle into the knowledge graph."""
    from app.services.fhir_ingestion import fhir_ingestion_service
    tenant_id = _tenant_scope_for_user(user)
    try:
        stats = await fhir_ingestion_service.ingest_fhir_bundle(bundle, tenant_id=tenant_id)
        return {
            "message": "FHIR data ingested successfully",
            "nodes": stats["nodes"],
            "edges": stats["edges"]
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@router.get("/patients/{patient_id}/lab-trends")
async def get_lab_trends(
    patient_id: str,
    lab: str | None = Query(None, description="Filter by lab name (partial match)"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(graph_reader),
) -> dict:
    """
    Retrieve temporal lab value trends for a patient from the knowledge graph.
    Returns chronologically ordered lab findings extracted from clinical documents.
    """
    if not PATIENT_ID_PATTERN.fullmatch(patient_id):
        raise HTTPException(
            status_code=400,
            detail="patient_id must contain only letters, numbers, hyphens, or underscores.",
        )

    payload = await temporal_graph_service.get_lab_trends(
        patient_id,
        lab,
        tenant_id=_tenant_scope_for_user(user),
        limit=limit,
    )
    if not payload.get("data_points"):
        payload = {
            **payload,
            "message": "No lab data found for this patient. Upload clinical documents to populate the graph.",
        }
    return payload
