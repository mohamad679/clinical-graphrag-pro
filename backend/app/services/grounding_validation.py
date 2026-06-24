"""
Deterministic grounding checks for cited clinical claims.

These checks validate evidence support, not clinical truth. They are designed to
fail closed for high-risk clinical claims before any optional semantic model is
introduced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StructuredClaim:
    claim_id: str
    text: str
    citation_ids: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    patient_id: str | None = None


@dataclass(slots=True)
class EvidenceRecord:
    evidence_id: str
    text: str
    tenant_id: str | None = None
    patient_id: str | None = None
    source_document_id: str | None = None
    source_chunk_id: str | None = None
    fact_type: str | None = None
    status: str | None = None
    value: Any = None
    unit: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    reason_code: str
    severity: str
    evidence_id: str
    claim_id: str
    details: dict[str, Any] = field(default_factory=dict)


NEGATION_TERMS = ("not", "no", "denies", "denied", "without", "negative for")
ACTIVE_TERMS = ("active", "current", "currently", "taking", "takes", "prescribed", "continues")
INACTIVE_TERMS = ("discontinued", "stopped", "held", "inactive", "resolved", "ended", "not taking")
UNIT_ALIASES = {
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "g": "g",
    "mcg": "mcg",
    "ug": "mcg",
    "%": "%",
    "percent": "%",
    "mmol/l": "mmol/l",
    "mmol": "mmol/l",
    "mg/dl": "mg/dl",
}
HIGH_RISK_TERMS = (
    "dose",
    "dosage",
    "mg",
    "mcg",
    "mmol",
    "warfarin",
    "insulin",
    "allergy",
    "allergic",
    "critical",
    "diagnosis",
    "diagnosed",
    "treatment",
    "recommend",
    "increase",
    "decrease",
    "active",
    "discontinued",
    "stopped",
    "taking",
)


def _fail(reason_code: str, claim: StructuredClaim, evidence: EvidenceRecord, *, severity: str = "high", **details: Any) -> ValidationResult:
    return ValidationResult(False, reason_code, severity, evidence.evidence_id, claim.claim_id, details)


def _pass(claim: StructuredClaim, evidence: EvidenceRecord, **details: Any) -> ValidationResult:
    return ValidationResult(True, "supported", "info", evidence.evidence_id, claim.claim_id, details)


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    cleaned = unit.strip().lower().replace(" ", "")
    return UNIT_ALIASES.get(cleaned, cleaned or None)


def extract_measurements(text: str) -> list[tuple[float, str | None]]:
    measurements: list[tuple[float, str | None]] = []
    text = re.sub(r"\[(?:EVIDENCE_SUPPORT|CONFIDENCE):\s*[0-9]*\.?[0-9]+\]", "", text or "", flags=re.I)
    pattern = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(mg/dl|mmol/l|mg|mcg|ug|g|%|percent|mmol)?(?=$|[^\w/])", re.I)
    for match in pattern.finditer(text or ""):
        unit = normalize_unit(match.group(2))
        try:
            measurements.append((float(match.group(1)), unit))
        except ValueError:
            continue
    return measurements


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for term in terms:
        if " " in term:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered):
                return True
        elif re.search(rf"\b{re.escape(term)}\b", lowered):
            return True
    return False


def _clinical_terms(text: str) -> set[str]:
    tokens = re.findall(r"\b[a-z][a-z0-9-]{2,}\b", text.lower())
    stop = {
        "the", "and", "for", "with", "from", "patient", "has", "have", "was",
        "were", "are", "not", "currently", "taking", "active", "status",
        "source", "document", "chunk", "tenant", "subject", "predicate",
        "object", "value", "unit", "date", "verification",
    }
    return {token for token in tokens if token not in stop}


def _is_high_risk(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in HIGH_RISK_TERMS) or bool(extract_measurements(text))


def _negated(text: str) -> bool:
    return _contains_any(text, NEGATION_TERMS)


def _status(text: str, explicit_status: str | None = None) -> str | None:
    if explicit_status:
        normalized = explicit_status.lower()
        if normalized in {"resolved", "inactive", "discontinued", "stopped"}:
            return "inactive"
        if normalized in {"active", "current"}:
            return "active"
    lowered = text.lower()
    if _contains_any(lowered, INACTIVE_TERMS):
        return "inactive"
    if _contains_any(lowered, ACTIVE_TERMS):
        return "active"
    return None


def validate_claim_against_evidence(claim: StructuredClaim, evidence: EvidenceRecord) -> ValidationResult:
    if evidence.evidence_id not in claim.citation_ids:
        return _fail("missing_citation", claim, evidence)
    if not evidence.source_document_id or not evidence.source_chunk_id:
        return _fail("missing_provenance", claim, evidence)
    if claim.tenant_id is not None and evidence.tenant_id is not None and str(claim.tenant_id) != str(evidence.tenant_id):
        return _fail("tenant_mismatch", claim, evidence)
    if claim.patient_id is not None and evidence.patient_id is not None and str(claim.patient_id) != str(evidence.patient_id):
        return _fail("patient_mismatch", claim, evidence)

    claim_text = claim.text or ""
    evidence_text = evidence.text or ""
    high_risk = _is_high_risk(claim_text)

    claim_terms = _clinical_terms(claim_text)
    evidence_terms = _clinical_terms(evidence_text)
    if high_risk and claim_terms and not (claim_terms & evidence_terms):
        return _fail("unsupported_high_risk_claim", claim, evidence, claim_terms=sorted(claim_terms))

    claim_measurements = extract_measurements(claim_text)
    evidence_measurements = extract_measurements(evidence_text)
    if evidence.value is not None:
        try:
            evidence_measurements.append((float(evidence.value), normalize_unit(evidence.unit)))
        except (TypeError, ValueError):
            pass

    if claim_measurements and evidence_measurements:
        for claim_value, claim_unit in claim_measurements:
            compatible = False
            for evidence_value, evidence_unit in evidence_measurements:
                if abs(claim_value - evidence_value) > 1e-9:
                    continue
                if claim_unit and evidence_unit and claim_unit != evidence_unit:
                    return _fail(
                        "unit_mismatch",
                        claim,
                        evidence,
                        claim_unit=claim_unit,
                        evidence_unit=evidence_unit,
                    )
                compatible = True
            if not compatible:
                return _fail("numeric_mismatch", claim, evidence, claim_value=claim_value)

    claim_negated = _negated(claim_text)
    evidence_negated = _negated(evidence_text)
    if claim_negated != evidence_negated and high_risk:
        return _fail("negation_mismatch", claim, evidence)

    claim_status = _status(claim_text)
    evidence_status = _status(evidence_text, evidence.status)
    if claim_status and evidence_status and claim_status != evidence_status:
        return _fail("status_mismatch", claim, evidence, claim_status=claim_status, evidence_status=evidence_status)

    if evidence.end_date and claim_status == "active":
        return _fail("temporal_mismatch", claim, evidence, end_date=evidence.end_date)

    return _pass(claim, evidence, high_risk=high_risk)
