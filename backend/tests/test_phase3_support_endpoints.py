"""
Phase 3 support tests for frontend-facing backend helpers.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import graph
from app.core.auth import User
from app.api.images import _extract_normalized_entities


@pytest.mark.anyio
async def test_graph_temporal_endpoint_returns_temporal_payload(monkeypatch):
    async_app = FastAPI()
    async_app.include_router(graph.router, prefix="/api")
    async_app.dependency_overrides[graph.graph_reader] = lambda: User(
        id="demo-physician-001",
        email="physician@clinicalgraph.ai",
        name="Dr. Physician",
        role="physician",
        created_at="2026-03-26T00:00:00+00:00",
        session_id="graph-test-session",
    )

    async def fake_temporal_state(entity, date, **_kwargs):
        return {
            "entity": entity,
            "target_date": date,
            "active_relationships": [
                {
                    "relationship": "HAS_CONDITION",
                    "target_entity": "Hypertension",
                    "target_label": "Disease",
                    "start_date": "2020-01-01",
                    "end_date": None,
                }
            ],
            "total_active": 1,
        }

    monkeypatch.setattr(graph.temporal_graph_service, "query_temporal_state", fake_temporal_state)

    transport = ASGITransport(app=async_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/graph/temporal", params={"entity": "Patient_A", "date": "2024-01-01"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity"] == "Patient_A"
    assert payload["total_active"] == 1
    assert payload["active_relationships"][0]["target_entity"] == "Hypertension"


@pytest.mark.anyio
async def test_graph_patient_lab_trends_endpoint_returns_flat_data_points(monkeypatch):
    async_app = FastAPI()
    async_app.include_router(graph.router, prefix="/api")
    async_app.dependency_overrides[graph.graph_reader] = lambda: User(
        id="demo-physician-001",
        email="physician@clinicalgraph.ai",
        name="Dr. Physician",
        role="physician",
        created_at="2026-03-26T00:00:00+00:00",
        session_id="graph-test-session",
    )

    async def fake_lab_trends(patient_id, lab_name=None, **_kwargs):
        return {
            "patient_id": patient_id,
            "lab_name_filter": lab_name,
            "data_points": [
                {
                    "date": "2022-01-15",
                    "lab": "Creatinine",
                    "value": 1.1,
                    "value_unit": "mg/dL",
                    "node_id": "tenant:demo:lab:creatinine",
                    "source_type": "seed",
                    "source_id": "Patient_A",
                },
                {
                    "date": "2022-06-01",
                    "lab": "Creatinine",
                    "value": 1.3,
                    "value_unit": "mg/dL",
                    "node_id": "tenant:demo:lab:creatinine",
                    "source_type": "seed",
                    "source_id": "Patient_A",
                },
            ],
            "total": 2,
            "date_range": {"earliest": "2022-01-15", "latest": "2022-06-01"},
            "available_labs": ["Creatinine"],
        }

    monkeypatch.setattr(graph.temporal_graph_service, "get_lab_trends", fake_lab_trends)

    transport = ASGITransport(app=async_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/graph/patients/Patient_A/lab-trends")

    assert response.status_code == 200
    payload = response.json()
    assert payload["patient_id"] == "Patient_A"
    assert payload["total"] == 2
    assert payload["available_labs"] == ["Creatinine"]
    assert payload["data_points"][0]["lab"] == "Creatinine"
    assert payload["data_points"][1]["value"] == 1.3


def test_extract_normalized_entities_returns_grounded_snomed_labels():
    analysis = {
        "summary": "Chest image concerning for pneumonia in a patient with hypertension.",
        "findings": [
            {"description": "Pneumonia", "location": "Right lower lobe"},
            {"description": "Hypertension", "location": ""},
        ],
        "differential_diagnosis": [{"condition": "Pneumonia", "probability": 0.78}],
    }

    entities = _extract_normalized_entities(analysis)

    assert any(entity["canonical_label"] == "Pneumonia" for entity in entities)
    assert any(entity["canonical_label"] == "Hypertension" for entity in entities)
    assert all(entity["concept_id"].startswith("SCTID:") for entity in entities)
