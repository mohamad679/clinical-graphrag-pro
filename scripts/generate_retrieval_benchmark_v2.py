#!/usr/bin/env python3
"""Generate synthetic_retrieval_benchmark_v2.

This dataset is a deterministic synthetic retrieval regression suite. It is
not clinical validation and must not be reported as clinical performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "backend" / "data" / "synthetic_retrieval_benchmark_v2.json"
DEFAULT_MANIFEST = REPO_ROOT / "backend" / "data" / "synthetic_retrieval_benchmark_v2_manifest.json"
DATASET_VERSION = "synthetic_retrieval_benchmark_v2"
GENERATOR_VERSION = "2026-06-07.1"
DEFAULT_SEED = 20260607

CATEGORY_COUNTS = {
    "lexical_exact": 15,
    "semantic_paraphrase": 15,
    "hard_negative": 20,
    "temporal_question": 15,
    "negation": 10,
    "contradiction": 10,
    "medication_dosage_unit": 10,
    "graph_dependent": 10,
    "abstention": 15,
    "cross_tenant_leakage_attempt": 15,
}

PATIENTS = [
    ("tenant-alpha", "pat-a01", "user-alpha", "Mira Lane", "type 2 diabetes", "metformin", "500 mg BID", "HbA1c", "8.1%", "7.0%"),
    ("tenant-alpha", "pat-a02", "user-alpha", "Jon Reed", "atrial fibrillation", "apixaban", "5 mg BID", "INR", "1.1", "1.0"),
    ("tenant-beta", "pat-b01", "user-beta", "Nia Shah", "heart failure", "furosemide", "40 mg daily", "BNP", "820 pg/mL", "430 pg/mL"),
    ("tenant-beta", "pat-b02", "user-beta", "Owen Vale", "hypertension", "lisinopril", "10 mg daily", "potassium", "4.2 mmol/L", "4.8 mmol/L"),
    ("tenant-gamma", "pat-g01", "user-gamma", "Iris Cole", "COPD", "tiotropium", "18 mcg daily", "FEV1", "58%", "62%"),
    ("tenant-gamma", "pat-g02", "user-gamma", "Luis Hart", "migraine", "topiramate", "50 mg qHS", "bicarbonate", "24 mmol/L", "20 mmol/L"),
    ("tenant-delta", "pat-d01", "user-delta", "Ari Moss", "coronary artery disease", "atorvastatin", "80 mg nightly", "LDL", "142 mg/dL", "76 mg/dL"),
    ("tenant-delta", "pat-d02", "user-delta", "Eva Lin", "ulcerative colitis", "mesalamine", "2.4 g daily", "CRP", "12 mg/L", "34 mg/L"),
]


def _normal_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


def _scope(patient: tuple[str, str, str, str, str, str, str, str, str, str]) -> dict:
    tenant_id, patient_id, user_id, *_ = patient
    return {"tenant_id": tenant_id, "patient_id": patient_id, "user_id": user_id}


def _chunk(
    corpus: list[dict],
    *,
    category: str,
    idx: int,
    patient: tuple[str, str, str, str, str, str, str, str, str, str],
    text: str,
    kind: str,
) -> str:
    tenant_id, patient_id, user_id, *_ = patient
    chunk_id = f"rtv2-{category}-{idx:03d}-{kind}"
    indexed_text = f"Synthetic encounter {chunk_id}. {text}"
    corpus.append(
        {
            "chunk_id": chunk_id,
            "chunk_index": 0,
            "document_id": f"doc-{chunk_id}",
            "document_name": f"{chunk_id}.txt",
            "text": indexed_text,
            "metadata": {
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "user_id": user_id,
                "category": category,
                "source_type": kind,
            },
        }
    )
    return chunk_id


def _query(
    queries: list[dict],
    *,
    category: str,
    idx: int,
    patient: tuple[str, str, str, str, str, str, str, str, str, str],
    text: str,
    expected: list[str],
    abstain: bool = False,
) -> None:
    tenant_id, patient_id, user_id, *_ = patient
    queries.append(
        {
            "query_id": f"q-{category}-{idx:03d}",
            "category": category,
            "query_text": text,
            "expected_evidence_ids": expected,
            "abstention_expected": abstain,
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "user_id": user_id,
        }
    )


def build_dataset(seed: int) -> dict:
    rng = random.Random(seed)
    corpus: list[dict] = []
    queries: list[dict] = []
    patient_cycle = [PATIENTS[i % len(PATIENTS)] for i in range(sum(CATEGORY_COUNTS.values()) + 20)]
    cursor = 0

    def next_patient():
        nonlocal cursor
        patient = patient_cycle[cursor]
        cursor += 1
        return patient

    for i in range(CATEGORY_COUNTS["lexical_exact"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, lab, early, _late = patient
        cid = _chunk(
            corpus,
            category="lexical_exact",
            idx=i,
            patient=patient,
            kind="med",
            text=f"Medication reconciliation for {name}: active {condition}; continue {med} {dose}. {lab} was {early}.",
        )
        _query(queries, category="lexical_exact", idx=i, patient=patient, text=f"Which exact medication dose is continued for {condition}?", expected=[cid])

    for i in range(CATEGORY_COUNTS["semantic_paraphrase"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, _lab, _early, _late = patient
        cid = _chunk(
            corpus,
            category="semantic_paraphrase",
            idx=i,
            patient=patient,
            kind="assessment",
            text=f"Follow-up assessment for {name}: symptoms are stable and the current long-term therapy remains {med} at {dose} for {condition}.",
        )
        _query(queries, category="semantic_paraphrase", idx=i, patient=patient, text="What ongoing treatment should stay unchanged for the chronic diagnosis?", expected=[cid])

    for i in range(CATEGORY_COUNTS["hard_negative"]):
        patient = next_patient()
        wrong = PATIENTS[(i + 3) % len(PATIENTS)]
        _, _, _, name, condition, med, dose, _lab, _early, _late = patient
        cid = _chunk(corpus, category="hard_negative", idx=i, patient=patient, kind="target", text=f"{name} has {condition}. The active plan is {med} {dose}; do not substitute the similarly documented alternate therapy.")
        _chunk(corpus, category="hard_negative", idx=i, patient=wrong, kind="distractor", text=f"Hard negative note: {wrong[3]} takes {wrong[5]} {wrong[6]} for {wrong[4]}, not for {name}.")
        _query(queries, category="hard_negative", idx=i, patient=patient, text=f"For {name}, what therapy is active, avoiding the similarly worded alternate patient note?", expected=[cid])

    for i in range(CATEGORY_COUNTS["temporal_question"]):
        patient = next_patient()
        _, _, _, name, _condition, _med, _dose, lab, early, late = patient
        early_cid = _chunk(corpus, category="temporal_question", idx=i, patient=patient, kind="early", text=f"2026-01-{(i % 27) + 1:02d}: {name}'s {lab} was {early}.")
        late_cid = _chunk(corpus, category="temporal_question", idx=i, patient=patient, kind="late", text=f"2026-05-{(i % 27) + 1:02d}: repeat {lab} for {name} was {late}, after medication review.")
        _query(queries, category="temporal_question", idx=i, patient=patient, text=f"What were the earlier and later {lab} values in date order?", expected=[early_cid, late_cid])

    for i in range(CATEGORY_COUNTS["negation"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, _lab, _early, _late = patient
        cid = _chunk(corpus, category="negation", idx=i, patient=patient, kind="negated", text=f"Visit note for {name}: {condition} is listed, but the patient is not taking {med}; {dose} was discontinued.")
        _query(queries, category="negation", idx=i, patient=patient, text=f"Is {med} currently being taken for this patient?", expected=[cid])

    for i in range(CATEGORY_COUNTS["contradiction"]):
        patient = next_patient()
        _, _, _, name, _condition, med, dose, _lab, _early, _late = patient
        cid1 = _chunk(corpus, category="contradiction", idx=i, patient=patient, kind="allergy", text=f"Intake note for {name}: allergy list says {med} caused hives.")
        cid2 = _chunk(corpus, category="contradiction", idx=i, patient=patient, kind="reconcile", text=f"Discharge note for {name}: medication reconciliation lists {med} {dose} as active with no allergy warning.")
        _query(queries, category="contradiction", idx=i, patient=patient, text=f"Can the record confidently say {med} is safe?", expected=[cid1, cid2], abstain=True)

    for i in range(CATEGORY_COUNTS["medication_dosage_unit"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, lab, _early, late = patient
        cid = _chunk(corpus, category="medication_dosage_unit", idx=i, patient=patient, kind="dose", text=f"Dosing note for {name}: {med} remains {dose}; monitoring includes {lab} {late} and Na+ 136 mmol/L.")
        _query(queries, category="medication_dosage_unit", idx=i, patient=patient, text=f"What dose and monitoring unit are documented for {med}?", expected=[cid])

    for i in range(CATEGORY_COUNTS["graph_dependent"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, lab, _early, late = patient
        cid = _chunk(corpus, category="graph_dependent", idx=i, patient=patient, kind="graph_fact", text=f"Graph fact: {name} HAS_CONDITION {condition}; {condition} TREATED_BY {med} {dose}; latest {lab} equals {late}.")
        _query(queries, category="graph_dependent", idx=i, patient=patient, text="Using the condition-to-treatment relation, which therapy is linked to the condition node?", expected=[cid])

    for i in range(CATEGORY_COUNTS["abstention"]):
        patient = next_patient()
        _, _, _, name, condition, med, dose, _lab, _early, _late = patient
        _chunk(corpus, category="abstention", idx=i, patient=patient, kind="scope", text=f"Scoped note for {name}: {condition} and {med} {dose} are documented. No pathology staging is present.")
        _query(queries, category="abstention", idx=i, patient=patient, text="What was the final tumor pathology stage?", expected=[], abstain=True)

    for i in range(CATEGORY_COUNTS["cross_tenant_leakage_attempt"]):
        patient = PATIENTS[i % 2]
        other = ("tenant-omega", patient[1], "user-omega", patient[3], patient[4], "warfarin", "3 mg daily", patient[7], patient[8], patient[9])
        cid = _chunk(corpus, category="cross_tenant_leakage_attempt", idx=i, patient=patient, kind="authorized", text=f"Authorized tenant note: {patient[3]} receives {patient[5]} {patient[6]} for {patient[4]}.")
        _chunk(corpus, category="cross_tenant_leakage_attempt", idx=i, patient=other, kind="blocked", text=f"Other tenant note with same patient id: {other[3]} receives {other[5]} {other[6]}. This chunk must not leak.")
        _query(queries, category="cross_tenant_leakage_attempt", idx=i, patient=patient, text="For this scoped patient, which medication is authorized?", expected=[cid])

    rng.shuffle(queries)
    duplicates = Counter(_normal_hash(chunk["text"]) for chunk in corpus)
    duplicate_count = sum(count - 1 for count in duplicates.values() if count > 1)
    summary = {
        "query_count": len(queries),
        "corpus_chunk_count": len(corpus),
        "category_counts": dict(Counter(query["category"] for query in queries)),
        "duplicate_chunk_count": duplicate_count,
        "duplicate_ratio": duplicate_count / len(corpus) if corpus else 0.0,
        "seed": seed,
    }
    if summary["duplicate_ratio"] > 0.05:
        raise RuntimeError(f"Duplicate ratio exceeds 5%: {summary['duplicate_ratio']:.4f}")
    return {
        "dataset_version": DATASET_VERSION,
        "generator_version": GENERATOR_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": seed,
        "clinical_validation": "not_clinically_validated",
        "corpus": corpus,
        "queries": queries,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic retrieval benchmark v2.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    dataset = build_dataset(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    manifest = {
        "dataset_version": dataset["dataset_version"],
        "generator_version": dataset["generator_version"],
        "created_at": dataset["created_at"],
        "seed": dataset["seed"],
        "path": str(args.output),
        "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        **dataset["summary"],
    }
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
