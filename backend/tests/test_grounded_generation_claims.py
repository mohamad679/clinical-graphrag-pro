from scripts.evaluate_grounded_generation import HeuristicClaimVerifier, score_case


def _case() -> dict:
    return {
        "id": "claim-test-001",
        "question": "What therapy should continue?",
        "expected_answer": "Continue apixaban 5 mg twice daily.",
        "required_evidence_chunks": ["ev-med"],
        "evidence_chunks": [
            {
                "chunk_id": "ev-med",
                "text": "Medication reconciliation states apixaban 5 mg twice daily is continued without dose change.",
                "tenant_id": "tenant-alpha",
                "patient_id": "syn-p001",
            },
            {
                "chunk_id": "ev-lab",
                "text": "Lab panel shows potassium 4.6 mmol/L and creatinine 1.0 mg/dL.",
                "tenant_id": "tenant-alpha",
                "patient_id": "syn-p001",
            },
        ],
        "scope": {"tenant_id": "tenant-alpha", "patient_id": "syn-p001", "user_id": "eval-user"},
        "difficulty": "medium",
        "failure_mode_category": "single_hop",
        "should_answer": True,
        "expected_keywords": ["apixaban", "5 mg twice daily"],
        "forbidden_keywords": ["warfarin", "pulmonary embolism"],
    }


def test_claim_verifier_catches_citation_laundering():
    case = _case()
    answer = "Continue warfarin 2 mg daily. [ev-med]"

    result = score_case(case, answer, verifier=HeuristicClaimVerifier())

    assert result["claims"][0]["status"] == "contradicted"
    assert result["citation_precision"] == 1.0
    assert result["unsupported_claim_rate"] == 1.0
    assert result["grounded_answer_accuracy"] is False


def test_claim_verifier_catches_fake_citation():
    case = _case()
    answer = "Continue apixaban 5 mg twice daily. [ev-fake]"

    result = score_case(case, answer, verifier=HeuristicClaimVerifier())

    assert result["unknown_citations"] == ["ev-fake"]
    assert result["claims"][0]["status"] == "unverifiable"
    assert result["citation_precision"] == 0.0
    assert result["claim_unverifiable_rate"] == 1.0


def test_claim_verifier_flags_unsupported_extra_claim():
    case = _case()
    answer = "Continue apixaban 5 mg twice daily. [ev-med] The patient also has pulmonary embolism. [ev-med]"

    result = score_case(case, answer, verifier=HeuristicClaimVerifier())
    statuses = [claim["status"] for claim in result["claims"]]

    assert statuses == ["supported", "contradicted"]
    assert result["claim_support_rate"] == 0.5
    assert result["unsupported_claim_rate"] == 0.5
    assert result["grounded_answer_accuracy"] is False


def test_claim_verifier_scores_partially_supported_answer():
    case = _case()
    answer = "Continue apixaban 5 mg twice daily. [ev-med] Creatinine is 2.5 mg/dL. [ev-lab]"

    result = score_case(case, answer, verifier=HeuristicClaimVerifier())
    statuses = [claim["status"] for claim in result["claims"]]

    assert statuses == ["supported", "unsupported"]
    assert result["claim_support_rate"] == 0.5
    assert result["unsupported_claim_rate"] == 0.5
    assert result["claims"][1]["mapped_evidence_chunks"][0]["chunk_id"] == "ev-lab"
