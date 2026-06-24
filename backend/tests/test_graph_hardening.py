import pytest

from app.models.persistence import GraphNode
from app.core.database import async_session_factory
from app.services.graph import temporal_graph_service, classify_temporal_status
from app.services.fhir_ingestion import fhir_ingestion_service
from app.services.rag import rag_service
from app.services.query_engine import query_engine

@pytest.mark.asyncio
async def test_fhir_patient_ingestion():
    # Test ingesting a single FHIR Patient
    patient_json = {
        "resourceType": "Patient",
        "id": "pat-test-1",
        "active": True,
        "name": [
            {
                "family": "Doe",
                "given": ["John"]
            }
        ],
        "gender": "male",
        "birthDate": "1990-01-01"
    }
    
    result = await fhir_ingestion_service.ingest_fhir_bundle(patient_json, tenant_id="test-tenant")
    assert result["nodes"] >= 1
    
    async with async_session_factory() as session:
        node = await session.get(GraphNode, "tenant:test-tenant:patient:pat-test-1")
        assert node is not None
        assert node.label == "Patient"
        assert node.properties["name"] == "John Doe"
        assert node.properties["birth_date"] == "1990-01-01"
        assert node.properties["extraction_method"] == "fhir"

@pytest.mark.asyncio
async def test_fhir_bundle_ingestion_and_provenance():
    # Test ingesting a Bundle with Patient, Encounter, Condition, Observation, MedicationRequest
    bundle_json = {
        "resourceType": "Bundle",
        "id": "bundle-test-2",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-test-2",
                    "name": [{"family": "Smith", "given": ["Alice"]}]
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-test-2",
                    "code": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "38341003",
                                "display": "Hypertension"
                            }
                        ]
                    },
                    "subject": {"reference": "Patient/pat-test-2"},
                    "onsetDateTime": "2023-01-01T00:00:00Z"
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-test-2",
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "laboratory"
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "2160-0",
                                "display": "Creatinine"
                            }
                        ]
                    },
                    "subject": {"reference": "Patient/pat-test-2"},
                    "effectiveDateTime": "2023-06-01T00:00:00Z",
                    "valueQuantity": {
                        "value": 1.1,
                        "unit": "mg/dL"
                    }
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-test-2",
                    "medicationCodeableConcept": {
                        "coding": [
                            {
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": "866514",
                                "display": "Lisinopril"
                            }
                        ]
                    },
                    "subject": {"reference": "Patient/pat-test-2"},
                    "authoredOn": "2023-02-01T00:00:00Z",
                    "dispenseRequest": {
                        "validityPeriod": {
                            "start": "2023-02-01T00:00:00Z",
                            "end": "2023-08-01T00:00:00Z"
                        }
                    }
                }
            }
        ]
    }
    
    result = await fhir_ingestion_service.ingest_fhir_bundle(bundle_json, tenant_id="test-tenant")
    assert result["nodes"] >= 4
    
    async with async_session_factory() as session:
        # Verify Condition Node
        cond_node = await session.get(GraphNode, "tenant:test-tenant:condition:cond-test-2")
        assert cond_node is not None
        assert cond_node.properties["name"] == "Hypertension"
        assert cond_node.properties["concept_id"] == "38341003"
        assert cond_node.properties["ontology"] == "http://snomed.info/sct"
        
        # Verify Observation Node (should be LabResult because of laboratory category)
        obs_node = await session.get(GraphNode, "tenant:test-tenant:labresult:obs-test-2")
        assert obs_node is not None
        assert obs_node.properties["value_numeric"] == 1.1
        assert obs_node.properties["unit"] == "mg/dL"
        
        # Verify MedicationRequest Node
        med_node = await session.get(GraphNode, "tenant:test-tenant:medication:med-test-2")
        assert med_node is not None
        assert med_node.properties["name"] == "Lisinopril"

@pytest.mark.asyncio
async def test_temporal_active_resolved_future_unknown():
    # Clean/setup for testing temporal
    tenant = "test-tenant"
    pat_id = "pat-temporal-1"
    
    # 1. Active condition (start: 2020-01-01, end: None, query: 2023-01-01)
    status_act, _ = classify_temporal_status("2020-01-01", None, "2023-01-01")
    assert status_act == "active"
    
    # 2. Resolved condition (start: 2020-01-01, end: 2022-01-01, query: 2023-01-01)
    status_res, _ = classify_temporal_status("2020-01-01", "2022-01-01", "2023-01-01")
    assert status_res == "resolved"
    
    # 3. Future condition (start: 2024-01-01, end: None, query: 2023-01-01)
    status_fut, _ = classify_temporal_status("2024-01-01", None, "2023-01-01")
    assert status_fut == "future"
    
    # 4. Unknown start date should not default to active
    status_unk, _ = classify_temporal_status(None, "2023-12-01", "2023-01-01")
    assert status_unk == "unknown"
    
    # 5. Invalid date formats
    status_inv, _ = classify_temporal_status("invalid-date", None, "2023-01-01")
    assert status_inv == "unknown"
    
    # Test query_temporal_state with current_only
    # Add a mock condition to graph
    await temporal_graph_service.add_temporal_relation(
        pat_id,
        f"tenant:{tenant}:condition:active-cond",
        "HAS_CONDITION",
        "2020-01-01",
        None,
        properties={"tenant_id": tenant, "patient_id": pat_id}
    )
    
    await temporal_graph_service.add_temporal_relation(
        pat_id,
        f"tenant:{tenant}:condition:resolved-cond",
        "HAS_CONDITION",
        "2020-01-01",
        "2022-01-01",
        properties={"tenant_id": tenant, "patient_id": pat_id}
    )
    
    # Query active relationships on 2023-01-01
    res_all = await temporal_graph_service.query_temporal_state(
        pat_id,
        "2023-01-01",
        tenant_id=tenant,
        patient_id=pat_id,
        current_only=False
    )
    # Should find both, but with status resolved and active
    assert res_all["total_active"] >= 2
    statuses = {r["target_entity"]: r["status"] for r in res_all["active_relationships"]}
    assert statuses[f"tenant:{tenant}:condition:active-cond"] == "active"
    assert statuses[f"tenant:{tenant}:condition:resolved-cond"] == "resolved"
    
    res_current = await temporal_graph_service.query_temporal_state(
        pat_id,
        "2023-01-01",
        tenant_id=tenant,
        patient_id=pat_id,
        current_only=True
    )
    # Should only find active one
    entities_current = [r["target_entity"] for r in res_current["active_relationships"]]
    assert f"tenant:{tenant}:condition:active-cond" in entities_current
    assert f"tenant:{tenant}:condition:resolved-cond" not in entities_current

@pytest.mark.asyncio
async def test_patient_scoped_leakage_prevention():
    tenant = "test-tenant"
    pat_a = "patient-alpha"
    pat_b = "patient-beta"
    
    # Ingest active condition for Patient Alpha
    await temporal_graph_service.add_temporal_relation(
        pat_a,
        f"tenant:{tenant}:condition:alpha-hypertension",
        "HAS_CONDITION",
        "2020-01-01",
        None,
        properties={"tenant_id": tenant, "patient_id": pat_a}
    )
    
    # Ingest active condition for Patient Beta
    await temporal_graph_service.add_temporal_relation(
        pat_b,
        f"tenant:{tenant}:condition:beta-diabetes",
        "HAS_CONDITION",
        "2020-01-01",
        None,
        properties={"tenant_id": tenant, "patient_id": pat_b}
    )
    
    # Query temporal state for Patient Alpha. Should NOT return Beta's data.
    res_a = await temporal_graph_service.query_temporal_state(
        pat_a,
        "2023-01-01",
        tenant_id=tenant,
        patient_id=pat_a
    )
    target_entities_a = [r["target_entity"] for r in res_a["active_relationships"]]
    assert f"tenant:{tenant}:condition:alpha-hypertension" in target_entities_a
    assert f"tenant:{tenant}:condition:beta-diabetes" not in target_entities_a
    
    # export graph for Patient Beta. Should NOT return Alpha's nodes.
    export_b = await temporal_graph_service.export_for_visualization(
        tenant_id=tenant,
        patient_id=pat_b
    )
    node_ids_b = [n["id"] for n in export_b["nodes"]]
    assert f"tenant:{tenant}:condition:beta-diabetes" in node_ids_b
    assert f"tenant:{tenant}:condition:alpha-hypertension" not in node_ids_b

@pytest.mark.asyncio
async def test_graph_enhanced_rag_integration(monkeypatch):
    # Test RAG context generation retrieves the structured graph context and formats it correctly
    tenant = "test-tenant"
    pat_id = "patient-rag-test"
    
    # Ingest a condition and medication for this patient
    await temporal_graph_service.add_temporal_relation(
        pat_id,
        f"tenant:{tenant}:condition:asthma",
        "HAS_CONDITION",
        "2018-05-10",
        None,
        properties={"tenant_id": tenant, "patient_id": pat_id, "source_document_id": "doc-99", "source_chunk_id": "chunk-asthma"}
    )
    await temporal_graph_service.add_temporal_relation(
        pat_id,
        f"tenant:{tenant}:medication:albuterol",
        "TOOK_MEDICATION",
        "2019-01-01",
        None,
        properties={"tenant_id": tenant, "patient_id": pat_id, "source_document_id": "doc-99", "source_chunk_id": "chunk-albuterol"}
    )
    
    # Mock query_engine.query to return empty result list (to isolate graph context)
    class FakeEnrichedResult:
        results = []
        retrieval_method = "vector"
        total_candidates = 0
        expanded_queries = []
        retrieval_latency_ms = 1.0
        
    async def mock_query(*args, **kwargs):
        return FakeEnrichedResult()
        
    monkeypatch.setattr(query_engine, "query", mock_query)
    
    # Call build_retrieval_bundle
    bundle = await rag_service.build_retrieval_bundle(
        "Does the patient have asthma?",
        tenant_id=tenant,
        patient_id=pat_id
    )
    
    # The bundle should contain a graph context item
    assert len(bundle.items) == 2
    graph_item = next(item for item in bundle.items if "asthma" in item.chunk_text.lower())
    assert graph_item.citation_id == "GRAPH-COND-001"
    assert graph_item.mode == "graph_context"
    assert "asthma" in graph_item.chunk_text.lower()
    assert "doc-99" in graph_item.chunk_text
    assert "chunk-asthma" in graph_item.chunk_text
