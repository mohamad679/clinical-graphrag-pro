from __future__ import annotations

import pytest

from app.services.grounding_validation import (
    EvidenceRecord,
    StructuredClaim,
    validate_claim_against_evidence,
)
from app.services.graph import temporal_graph_service
from app.services.rag import ContextBundle, ContextItem, RAGService


@pytest.fixture
def phase1_env():
    return None


def _claim(text: str, *, evidence_id: str = "EV1", tenant_id: str = "tenant-A", patient_id: str = "patient-A") -> StructuredClaim:
    return StructuredClaim(
        claim_id="claim-1",
        text=text,
        citation_ids=[evidence_id],
        tenant_id=tenant_id,
        patient_id=patient_id,
    )


def _evidence(
    text: str,
    *,
    evidence_id: str = "EV1",
    tenant_id: str = "tenant-A",
    patient_id: str = "patient-A",
    source_document_id: str | None = "doc-1",
    source_chunk_id: str | None = "chunk-1",
    status: str | None = None,
    value=None,
    unit: str | None = None,
    end_date: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        text=text,
        tenant_id=tenant_id,
        patient_id=patient_id,
        source_document_id=source_document_id,
        source_chunk_id=source_chunk_id,
        status=status,
        value=value,
        unit=unit,
        end_date=end_date,
    )


@pytest.mark.parametrize(
    ("evidence", "claim", "reason"),
    [
        (_evidence("Patient is not taking warfarin."), _claim("Patient is taking warfarin [EV1]."), "negation_mismatch"),
        (_evidence("Warfarin dose: 5 mg."), _claim("Warfarin dose is 50 mg [EV1]."), "numeric_mismatch"),
        (_evidence("Medication discontinued.", status="resolved"), _claim("Medication is active [EV1]."), "status_mismatch"),
        (_evidence("HbA1c: 7.2%.", value=7.2, unit="%"), _claim("HbA1c is 7.2 mmol/L [EV1]."), "unit_mismatch"),
        (_evidence("Patient A note.", patient_id="patient-A"), _claim("Claim for patient B [EV1].", patient_id="patient-B"), "patient_mismatch"),
        (_evidence("Tenant A note.", tenant_id="tenant-A"), _claim("Claim for tenant B [EV1].", tenant_id="tenant-B"), "tenant_mismatch"),
        (_evidence("Graph fact without document.", source_document_id=None), _claim("Supported graph claim [EV1]."), "missing_provenance"),
        (_evidence("Warfarin was stopped.", status="resolved", end_date="2024-01-01"), _claim("Warfarin is currently active [EV1]."), "status_mismatch"),
    ],
)
def test_high_risk_structured_grounding_mismatches_fail_closed(evidence, claim, reason, phase1_env):
    result = validate_claim_against_evidence(claim, evidence)
    assert result.valid is False
    assert result.reason_code == reason
    assert result.severity == "high"


@pytest.mark.parametrize(
    ("evidence", "claim"),
    [
        (_evidence("Warfarin dose: 5 mg.", value=5, unit="mg"), _claim("Warfarin dose is 5 mg [EV1].")),
        (_evidence("HbA1c: 7.2%.", value=7.2, unit="%"), _claim("HbA1c is 7.2% [EV1].")),
        (_evidence("Patient is not taking warfarin."), _claim("Patient is not taking warfarin [EV1].")),
    ],
)
def test_structured_grounding_positive_cases_pass(evidence, claim, phase1_env):
    result = validate_claim_against_evidence(claim, evidence)
    assert result.valid is True
    assert result.reason_code == "supported"


@pytest.mark.asyncio
async def test_retrieval_only_requires_review_and_does_not_fake_perfect_confidence(monkeypatch, phase1_env):
    rag = RAGService()
    monkeypatch.setattr(rag._settings, "llm_provider", "retrieval-only")
    item = ContextItem(
        citation_id="SRC1",
        chunk_id="chunk-1",
        document_id="doc-1",
        document_name="note.txt",
        chunk_index=0,
        chunk_text="Warfarin dose is 5 mg.",
        retrieval_score=0.82,
    )
    bundle = ContextBundle(
        mode="retrieval",
        query="What is the warfarin dose?",
        expanded_queries=[],
        items=[item],
        context_text="[SRC1] Warfarin dose is 5 mg.",
        reasoning_steps=[],
        retrieval_method="test",
        total_candidates=1,
        retrieval_latency_ms=0.0,
        context_policy={},
    )

    result = await rag.generate_answer(question=bundle.query, bundle=bundle)

    assert result.clinician_review_required is True
    assert result.heuristic_evidence_support_score == 0.82
    assert result.confidence_score == result.heuristic_evidence_support_score
    assert result.trace["guardrails"]["clinician_review_required"] is True


@pytest.mark.asyncio
async def test_graph_laundering_with_one_unsourced_fact_fails_closed(monkeypatch, phase1_env):
    rag = RAGService()
    sourced = ContextItem(
        citation_id="GRAPH-COND-001",
        chunk_id="graph-fact:GRAPH-COND-001",
        document_id="doc-1",
        document_name="Clinical Knowledge Graph Fact",
        chunk_index=0,
        chunk_text="Fact ID: GRAPH-COND-001\nObject: diabetes\nSource document ID: doc-1\nSource chunk ID: chunk-1\nVerification status: verified",
        retrieval_score=0.95,
        mode="graph_context",
        metadata={"tenant_id": "tenant-A", "patient_id": "patient-A", "source_document_id": "doc-1", "source_chunk_id": "chunk-1"},
    )
    unsourced = ContextItem(
        citation_id="GRAPH-MED-001",
        chunk_id="graph-fact:GRAPH-MED-001",
        document_id="graph-database",
        document_name="Clinical Knowledge Graph Fact",
        chunk_index=0,
        chunk_text="Fact ID: GRAPH-MED-001\nObject: increase medication dose\nVerification status: unverified",
        retrieval_score=0.95,
        mode="graph_context",
        metadata={"tenant_id": "tenant-A", "patient_id": "patient-A"},
    )
    bundle = ContextBundle(
        mode="retrieval",
        query="What does the graph show?",
        expanded_queries=[],
        items=[sourced, unsourced],
        context_text="",
        reasoning_steps=[],
        retrieval_method="graph",
        total_candidates=2,
        retrieval_latency_ms=0.0,
        context_policy={},
    )

    from app.services.llm import LLMResponse
    from unittest.mock import AsyncMock, patch

    response = LLMResponse(
        text="Patient has diabetes [GRAPH-COND-001]. Medication dose should be increased [GRAPH-MED-001]. [EVIDENCE_SUPPORT: 0.90]",
        provider="test",
        model_used="fake",
        token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    with patch("app.services.llm.llm_service.generate_with_metadata", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = response
        result = await rag.generate_answer(question=bundle.query, bundle=bundle)

    assert "not have enough evidence" in result.answer
    assert result.citations == []
    assert result.heuristic_evidence_support_score == 0.0


@pytest.mark.asyncio
async def test_latest_temporal_graph_fact_and_unique_citation():
    tenant_id = "tenant-grounding-latest"
    patient_id = "patient-grounding-latest"
    await temporal_graph_service.add_temporal_relation(
        patient_id,
        f"tenant:{tenant_id}:medication:warfarin",
        "TOOK_MEDICATION",
        "2020-01-01",
        None,
        properties={
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "source_document_id": "doc-old",
            "source_chunk_id": "chunk-old",
        },
    )
    await temporal_graph_service.add_temporal_relation(
        patient_id,
        f"tenant:{tenant_id}:medication:warfarin",
        "TOOK_MEDICATION",
        "2024-01-01",
        "2024-03-01",
        properties={
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "source_document_id": "doc-new",
            "source_chunk_id": "chunk-new",
        },
    )

    facts = await temporal_graph_service.get_evidence_facts(tenant_id=tenant_id, patient_id=patient_id)

    warfarin = [fact for fact in facts if "warfarin" in fact.normalized_object.lower()]
    assert len(warfarin) == 1
    assert warfarin[0].fact_id == "GRAPH-MED-001"
    assert warfarin[0].source_document_id == "doc-new"
    assert warfarin[0].source_chunk_id == "chunk-new"
    assert warfarin[0].temporal_status == "resolved"
