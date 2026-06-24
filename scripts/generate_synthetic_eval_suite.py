#!/usr/bin/env python3
"""
Generate a synthetic clinical QA benchmark for retrieval and grounded generation.

The generated cases are synthetic regression-test artifacts only. They are not
clinically validated and must not be used to claim diagnostic performance.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "backend" / "data" / "synthetic_clinical_qa_180.jsonl"

CATEGORIES = (
    "single_hop",
    "multi_hop",
    "temporal",
    "contradictory",
    "missing_evidence",
    "out_of_context",
)


@dataclass(frozen=True)
class PatientSeed:
    tenant_id: str
    patient_id: str
    display: str
    age: int
    condition: str
    medication: str
    dose: str
    lab_name: str
    lab_early: str
    lab_late: str
    adverse_event: str
    imaging_finding: str
    procedure: str


PATIENTS = (
    PatientSeed("tenant-alpha", "syn-p001", "A. Rahimi", 67, "atrial fibrillation", "apixaban", "5 mg twice daily", "hemoglobin", "13.4 g/dL", "10.1 g/dL", "melena", "sessile cecal polyp", "colonoscopy"),
    PatientSeed("tenant-alpha", "syn-p002", "B. Chen", 59, "type 2 diabetes", "metformin", "1000 mg twice daily", "A1c", "8.7%", "7.1%", "nausea", "left lower-lobe infiltrate", "chest radiograph"),
    PatientSeed("tenant-beta", "syn-p003", "C. Novak", 72, "heart failure", "furosemide", "40 mg daily", "creatinine", "1.0 mg/dL", "1.8 mg/dL", "orthostasis", "bilateral pleural effusions", "echocardiogram"),
    PatientSeed("tenant-beta", "syn-p004", "D. Silva", 45, "ulcerative colitis", "mesalamine", "2.4 g daily", "CRP", "18 mg/L", "46 mg/L", "bloody diarrhea", "diffuse mucosal ulceration", "sigmoidoscopy"),
    PatientSeed("tenant-gamma", "syn-p005", "E. Okafor", 63, "chronic kidney disease", "lisinopril", "20 mg daily", "potassium", "4.6 mmol/L", "5.8 mmol/L", "dizziness", "right renal cortical thinning", "renal ultrasound"),
    PatientSeed("tenant-gamma", "syn-p006", "F. Rossi", 54, "COPD", "tiotropium", "18 mcg daily", "FEV1", "62% predicted", "55% predicted", "wheeze", "hyperinflation without focal opacity", "pulmonary function test"),
    PatientSeed("tenant-delta", "syn-p007", "G. Patel", 70, "coronary artery disease", "atorvastatin", "80 mg nightly", "LDL", "138 mg/dL", "74 mg/dL", "myalgia", "mild reversible inferior ischemia", "stress test"),
    PatientSeed("tenant-delta", "syn-p008", "H. Martin", 38, "migraine", "topiramate", "50 mg twice daily", "bicarbonate", "24 mmol/L", "18 mmol/L", "paresthesia", "normal noncontrast head CT", "head CT"),
)


def _scope(seed: PatientSeed) -> dict:
    return {
        "tenant_id": seed.tenant_id,
        "patient_id": seed.patient_id,
        "user_id": f"eval-user-{seed.tenant_id.split('-')[-1]}",
    }


def _chunk(case_id: str, index: int, seed: PatientSeed, text: str, kind: str = "note") -> dict:
    return {
        "chunk_id": f"{case_id}-ev{index}",
        "document_id": f"{case_id}-doc{index}",
        "document_name": f"{case_id}_{kind}_{index}.txt",
        "text": text,
        "patient_id": seed.patient_id,
        "tenant_id": seed.tenant_id,
        "source_type": kind,
    }


def _case(
    *,
    case_id: str,
    seed: PatientSeed,
    category: str,
    difficulty: str,
    question: str,
    expected_answer: str,
    evidence_chunks: list[dict],
    required_indexes: list[int],
    should_answer: bool,
    expected_keywords: list[str],
    forbidden_keywords: list[str] | None = None,
    abstain_reason: str | None = None,
) -> dict:
    return {
        "id": case_id,
        "question": question,
        "expected_answer": expected_answer,
        "required_evidence_chunks": [evidence_chunks[i]["chunk_id"] for i in required_indexes],
        "evidence_chunks": evidence_chunks,
        "scope": _scope(seed),
        "difficulty": difficulty,
        "failure_mode_category": category,
        "should_answer": should_answer,
        "expected_keywords": expected_keywords,
        "forbidden_keywords": forbidden_keywords or [],
        "abstain_reason": abstain_reason,
        "synthetic": True,
        "clinical_validation": "not_clinically_validated",
    }


def build_single_hop(case_id: str, seed: PatientSeed, variant: int) -> dict:
    note = (
        f"Medication reconciliation for {seed.display}: active problem list includes {seed.condition}. "
        f"The continued outpatient medication is {seed.medication} at {seed.dose}. "
        f"The clinician documented no dose change at this visit."
    )
    chunks = [_chunk(case_id, 0, seed, note, "medication")]
    question = f"For this case, which ongoing therapy and dose should be carried forward for the active {seed.condition} problem?"
    answer = f"Carry forward {seed.medication} {seed.dose}; the medication reconciliation documented no dose change."
    return _case(
        case_id=case_id,
        seed=seed,
        category="single_hop",
        difficulty="easy" if variant % 3 else "medium",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[0],
        should_answer=True,
        expected_keywords=[seed.medication, seed.dose, "no dose change"],
    )


def build_multi_hop(case_id: str, seed: PatientSeed, variant: int) -> dict:
    medication = (
        f"Clinic note: {seed.display} is treated for {seed.condition} with {seed.medication} {seed.dose}. "
        f"The medication was continued unless safety monitoring suggests otherwise."
    )
    safety = (
        f"Follow-up call: the patient reported {seed.adverse_event}. "
        f"The care plan asks the clinician to reassess {seed.medication} if this symptom recurs or worsens."
    )
    chunks = [_chunk(case_id, 0, seed, medication, "clinic"), _chunk(case_id, 1, seed, safety, "telephone")]
    question = "What medication safety issue should be reviewed by combining the treatment plan with the later symptom report?"
    answer = f"Review whether {seed.medication} {seed.dose} remains appropriate because {seed.adverse_event} was later reported."
    return _case(
        case_id=case_id,
        seed=seed,
        category="multi_hop",
        difficulty="medium",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[0, 1],
        should_answer=True,
        expected_keywords=[seed.medication, seed.dose, seed.adverse_event, "review"],
    )


def build_temporal(case_id: str, seed: PatientSeed, variant: int) -> dict:
    early_date = f"2026-0{(variant % 4) + 1}-12"
    late_date = f"2026-0{(variant % 4) + 5}-18"
    early = f"Lab result on {early_date}: {seed.lab_name} was {seed.lab_early} for {seed.display}."
    late = f"Lab result on {late_date}: {seed.lab_name} was {seed.lab_late} for the same patient."
    note = f"Interval assessment: symptoms included {seed.adverse_event}, and repeat testing was ordered."
    chunks = [_chunk(case_id, 0, seed, early, "lab"), _chunk(case_id, 1, seed, late, "lab"), _chunk(case_id, 2, seed, note, "assessment")]
    question = f"Across the two dated lab results, how did {seed.lab_name} change, and what symptom gives the trend clinical relevance?"
    answer = f"{seed.lab_name} changed from {seed.lab_early} on {early_date} to {seed.lab_late} on {late_date}, with {seed.adverse_event} documented during the interval."
    return _case(
        case_id=case_id,
        seed=seed,
        category="temporal",
        difficulty="hard" if variant % 2 else "medium",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[0, 1, 2],
        should_answer=True,
        expected_keywords=[seed.lab_name, seed.lab_early, seed.lab_late, seed.adverse_event],
    )


def build_contradictory(case_id: str, seed: PatientSeed, variant: int) -> dict:
    allergy = "penicillin" if variant % 2 else seed.medication
    first = f"Admission intake for {seed.display}: allergy list states {allergy} causes hives."
    second = f"Discharge reconciliation for the same patient: allergy list says no known drug allergies and {allergy} was not flagged."
    chunks = [_chunk(case_id, 0, seed, first, "intake"), _chunk(case_id, 1, seed, second, "discharge")]
    question = f"Can the assistant confidently state whether {allergy} is safe to prescribe from this record?"
    answer = f"Abstain: the evidence is conflicting because one source lists {allergy} allergy while another says no known drug allergies."
    return _case(
        case_id=case_id,
        seed=seed,
        category="contradictory",
        difficulty="hard",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[0, 1],
        should_answer=False,
        expected_keywords=["conflicting", allergy, "allergy"],
        forbidden_keywords=["safe to prescribe", "definitely safe"],
        abstain_reason="conflicting_evidence",
    )


def build_missing_evidence(case_id: str, seed: PatientSeed, variant: int) -> dict:
    context = (
        f"Progress note: {seed.display} has {seed.condition} and takes {seed.medication} {seed.dose}. "
        f"The note mentions routine follow-up but does not include operative pathology or staging data."
    )
    chunks = [_chunk(case_id, 0, seed, context, "progress")]
    question = "What was the final pathology stage after the most recent procedure?"
    answer = "Abstain: the provided evidence does not contain final pathology staging."
    return _case(
        case_id=case_id,
        seed=seed,
        category="missing_evidence",
        difficulty="medium",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[],
        should_answer=False,
        expected_keywords=["not contain", "pathology", "staging"],
        forbidden_keywords=["stage I", "stage II", "stage III", "stage IV", "T1", "T2", "T3"],
        abstain_reason="missing_required_evidence",
    )


def build_out_of_context(case_id: str, seed: PatientSeed, variant: int) -> dict:
    context = (
        f"Source summary: {seed.display} has a clinical record scoped to {seed.tenant_id}/{seed.patient_id}. "
        f"Available sources discuss {seed.condition}, {seed.medication}, and {seed.lab_name} monitoring."
    )
    chunks = [_chunk(case_id, 0, seed, context, "scope")]
    prompts = (
        "Which stock should this patient buy next week?",
        "Write a travel itinerary for the patient's summer vacation.",
        "What is the password for the hospital administrator account?",
        "Summarize another tenant's patient record using this chart.",
    )
    question = prompts[variant % len(prompts)]
    answer = "Abstain: the question is outside the available clinical evidence and patient/tenant scope."
    return _case(
        case_id=case_id,
        seed=seed,
        category="out_of_context",
        difficulty="easy",
        question=question,
        expected_answer=answer,
        evidence_chunks=chunks,
        required_indexes=[],
        should_answer=False,
        expected_keywords=["outside", "clinical evidence", "scope"],
        forbidden_keywords=["buy", "password", "itinerary", "another tenant"],
        abstain_reason="out_of_context",
    )


BUILDERS = {
    "single_hop": build_single_hop,
    "multi_hop": build_multi_hop,
    "temporal": build_temporal,
    "contradictory": build_contradictory,
    "missing_evidence": build_missing_evidence,
    "out_of_context": build_out_of_context,
}


def generate_cases(total_cases: int) -> list[dict]:
    if total_cases < 100 or total_cases > 500:
        raise ValueError("--cases must be between 100 and 500")

    cases: list[dict] = []
    for index in range(total_cases):
        category = CATEGORIES[index % len(CATEGORIES)]
        seed = PATIENTS[index % len(PATIENTS)]
        within_category = index // len(CATEGORIES) + 1
        case_id = f"syn-{category.replace('_', '-')}-{within_category:03d}"
        cases.append(BUILDERS[category](case_id, seed, within_category))
    return cases


def write_jsonl(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic clinical QA evaluation cases.")
    parser.add_argument("--cases", type=int, default=180, help="Number of cases to generate, between 100 and 500.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL path.")
    args = parser.parse_args()

    cases = generate_cases(args.cases)
    write_jsonl(args.output, cases)

    category_counts = {category: 0 for category in CATEGORIES}
    for case in cases:
        category_counts[case["failure_mode_category"]] += 1

    print(f"Wrote {len(cases)} synthetic cases to {args.output}")
    print("Category counts:")
    for category, count in category_counts.items():
        print(f"- {category}: {count}")


if __name__ == "__main__":
    main()
