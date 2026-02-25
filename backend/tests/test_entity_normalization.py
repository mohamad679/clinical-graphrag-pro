"""
Tests for the Medical Entity Normalization Service.
Run with: pytest tests/test_entity_normalization.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.entity_normalization import (
    EntityNormalizationService,
    CANONICAL_CONCEPTS,
    SYNONYM_MAP,
)
from app.schemas.entity_normalization import EntityInput


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def service():
    """Fresh service instance for unit tests."""
    return EntityNormalizationService()


# ── Curated Vocabulary Tests ─────────────────────────────


@pytest.mark.anyio
async def test_curated_disease_lookup(service):
    """Known diseases resolve with High confidence via curated vocabulary."""
    entities = [EntityInput(surface_form="Hypertension")]
    result = await service.normalize(entities)

    assert result.total == 1
    e = result.normalized_entities[0]
    assert e.canonical_label == "Hypertension"
    assert e.ontology == "SNOMED CT"
    assert e.concept_id == "SCTID:38341003"
    assert e.semantic_type == "Disease"
    assert e.confidence == "High"
    assert e.is_ungrounded is False


@pytest.mark.anyio
async def test_curated_drug_lookup(service):
    """Known drugs resolve with RxNorm and High confidence."""
    entities = [EntityInput(surface_form="Metformin")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Metformin"
    assert e.ontology == "RxNorm"
    assert e.concept_id == "RxCUI:6809"
    assert e.semantic_type == "Drug"
    assert e.confidence == "High"


@pytest.mark.anyio
async def test_curated_symptom_lookup(service):
    """Known symptoms resolve via curated vocabulary."""
    entities = [EntityInput(surface_form="Chest Pain")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Chest Pain"
    assert e.ontology == "SNOMED CT"
    assert e.semantic_type == "Symptom"
    assert e.confidence == "High"


@pytest.mark.anyio
async def test_curated_procedure_lookup(service):
    """Known procedures resolve via curated vocabulary."""
    entities = [EntityInput(surface_form="Colonoscopy")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Colonoscopy"
    assert e.semantic_type == "Procedure"
    assert e.confidence == "High"


# ── Synonym Resolution Tests ────────────────────────────


@pytest.mark.anyio
async def test_synonym_mi_maps_to_myocardial_infarction(service):
    """Abbreviation 'MI' maps to 'Myocardial Infarction'."""
    entities = [EntityInput(surface_form="MI")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Myocardial Infarction"
    assert e.concept_id == "SCTID:22298006"


@pytest.mark.anyio
async def test_synonym_heart_attack_maps_to_myocardial_infarction(service):
    """'heart attack' maps to same canonical concept as 'MI'."""
    entities = [EntityInput(surface_form="heart attack")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Myocardial Infarction"
    assert e.concept_id == "SCTID:22298006"


@pytest.mark.anyio
async def test_synonyms_produce_same_concept_id(service):
    """Multiple synonyms for the same concept all produce identical concept_id."""
    entities = [
        EntityInput(surface_form="MI"),
        EntityInput(surface_form="heart attack"),
        EntityInput(surface_form="Myocardial Infarction"),
    ]
    result = await service.normalize(entities)

    concept_ids = {e.concept_id for e in result.normalized_entities}
    canonical_labels = {e.canonical_label for e in result.normalized_entities}

    assert len(concept_ids) == 1, f"Expected 1 unique concept_id, got: {concept_ids}"
    assert len(canonical_labels) == 1, f"Expected 1 canonical label, got: {canonical_labels}"
    assert "SCTID:22298006" in concept_ids


@pytest.mark.anyio
async def test_drug_brand_name_maps_to_generic(service):
    """Brand names (Lipitor) map to generic drug name (Atorvastatin)."""
    entities = [EntityInput(surface_form="Lipitor")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Atorvastatin"
    assert e.ontology == "RxNorm"


@pytest.mark.anyio
async def test_abbreviation_copd(service):
    """'COPD' maps to full disease name."""
    entities = [EntityInput(surface_form="COPD")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Chronic Obstructive Pulmonary Disease"
    assert e.semantic_type == "Disease"


@pytest.mark.anyio
async def test_abbreviation_uti(service):
    """'UTI' maps to 'Urinary Tract Infection'."""
    entities = [EntityInput(surface_form="UTI")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Urinary Tract Infection"


@pytest.mark.anyio
async def test_abbreviation_cabg(service):
    """'CABG' maps to the full procedure term."""
    entities = [EntityInput(surface_form="CABG")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Coronary Artery Bypass Graft"
    assert e.semantic_type == "Procedure"


@pytest.mark.anyio
async def test_paracetamol_maps_to_acetaminophen(service):
    """International name 'paracetamol' maps to US generic 'Acetaminophen'."""
    entities = [EntityInput(surface_form="paracetamol")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.canonical_label == "Acetaminophen"
    assert e.ontology == "RxNorm"
    assert e.concept_id == "RxCUI:161"


# ── Ontology Preference Tests ───────────────────────────


@pytest.mark.anyio
async def test_disease_prefers_snomed(service):
    """Diseases should prefer SNOMED CT."""
    entities = [EntityInput(surface_form="Type 2 Diabetes Mellitus")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.ontology == "SNOMED CT"
    assert e.concept_id.startswith("SCTID:")


@pytest.mark.anyio
async def test_drug_prefers_rxnorm(service):
    """Drugs should prefer RxNorm."""
    entities = [EntityInput(surface_form="Warfarin")]
    result = await service.normalize(entities)

    e = result.normalized_entities[0]
    assert e.ontology == "RxNorm"
    assert e.concept_id.startswith("RxCUI:")


# ── Case Insensitivity Tests ────────────────────────────


@pytest.mark.anyio
async def test_case_insensitive_lookup(service):
    """Lookups should be case-insensitive."""
    entities = [
        EntityInput(surface_form="hypertension"),
        EntityInput(surface_form="HYPERTENSION"),
        EntityInput(surface_form="Hypertension"),
    ]
    result = await service.normalize(entities)

    for e in result.normalized_entities:
        assert e.canonical_label == "Hypertension"
        assert e.concept_id == "SCTID:38341003"


# ── Batch & Consistency Tests ───────────────────────────


@pytest.mark.anyio
async def test_batch_normalization(service):
    """Batch of mixed entity types all resolve correctly."""
    entities = [
        EntityInput(surface_form="Aspirin"),
        EntityInput(surface_form="Chest Pain"),
        EntityInput(surface_form="CABG"),
        EntityInput(surface_form="HTN"),
    ]
    result = await service.normalize(entities)

    assert result.total == 4
    by_label = {e.canonical_label: e for e in result.normalized_entities}

    assert by_label["Aspirin"].ontology == "RxNorm"
    assert by_label["Chest Pain"].semantic_type == "Symptom"
    assert by_label["Coronary Artery Bypass Graft"].semantic_type == "Procedure"
    assert by_label["Hypertension"].ontology == "SNOMED CT"


@pytest.mark.anyio
async def test_session_cache_consistency(service):
    """Same concept referenced twice in a batch always gets identical mapping."""
    entities = [
        EntityInput(surface_form="HTN"),
        EntityInput(surface_form="high blood pressure"),
        EntityInput(surface_form="Hypertension"),
    ]
    result = await service.normalize(entities)

    assert result.total == 3
    ids = [e.concept_id for e in result.normalized_entities]
    labels = [e.canonical_label for e in result.normalized_entities]

    assert len(set(ids)) == 1
    assert len(set(labels)) == 1


# ── API Endpoint Tests ──────────────────────────────────


@pytest.mark.anyio
async def test_api_normalize_endpoint(client):
    """POST /api/entity-normalization/normalize returns correct structure."""
    payload = {
        "entities": [
            {"surface_form": "MI"},
            {"surface_form": "Metformin"},
        ]
    }
    response = await client.post("/api/entity-normalization/normalize", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "normalized_entities" in data
    assert "total" in data
    assert data["total"] == 2

    by_label = {e["canonical_label"]: e for e in data["normalized_entities"]}
    assert "Myocardial Infarction" in by_label
    assert "Metformin" in by_label


@pytest.mark.anyio
async def test_api_ontologies_endpoint(client):
    """GET /api/entity-normalization/ontologies returns supported ontologies."""
    response = await client.get("/api/entity-normalization/ontologies")
    assert response.status_code == 200

    data = response.json()
    assert "ontologies" in data
    codes = {o["code"] for o in data["ontologies"]}
    assert "CUI" in codes
    assert "SCTID" in codes
    assert "RxCUI" in codes
    assert "ICD-10-CM" in codes


@pytest.mark.anyio
async def test_api_empty_entities_rejected(client):
    """Empty entities list is rejected by Pydantic validation."""
    response = await client.post(
        "/api/entity-normalization/normalize",
        json={"entities": []},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_api_empty_surface_form_rejected(client):
    """Empty surface_form is rejected by Pydantic validation."""
    response = await client.post(
        "/api/entity-normalization/normalize",
        json={"entities": [{"surface_form": ""}]},
    )
    assert response.status_code == 422


# ── Knowledge Base Integrity Tests ──────────────────────


def test_synonym_map_keys_are_lowercase():
    """All synonym map keys should be lowercase for case-insensitive matching."""
    for key in SYNONYM_MAP:
        assert key == key.lower(), f"Synonym key '{key}' is not lowercase"


def test_synonym_map_values_exist_in_canonical():
    """Every synonym must point to a valid canonical concept."""
    for synonym, canonical in SYNONYM_MAP.items():
        assert canonical in CANONICAL_CONCEPTS, (
            f"Synonym '{synonym}' -> '{canonical}' not found in CANONICAL_CONCEPTS"
        )


def test_all_canonical_concepts_have_required_fields():
    """Every curated concept must have ontology, concept_id, and semantic_type."""
    for label, data in CANONICAL_CONCEPTS.items():
        assert "ontology" in data, f"'{label}' missing 'ontology'"
        assert "concept_id" in data, f"'{label}' missing 'concept_id'"
        assert "semantic_type" in data, f"'{label}' missing 'semantic_type'"
