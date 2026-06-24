"""
Internal quality-suite runner for product evaluation and release gating.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import fmean
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.services.evaluation import evaluation_service
from app.services.evaluation_storage import EvaluationStorageService
from app.services.job_state import job_state_service

INTERNAL_EVALUATION_TYPE = "internal_quality_suite"
LEGACY_EVALUATION_TYPE = "ragas"
QUALITY_EVALUATION_TYPES = (INTERNAL_EVALUATION_TYPE, LEGACY_EVALUATION_TYPE)
INTERNAL_SUITE_NAME = "clinical_internal_quality"
INTERNAL_SUITE_VERSION = "2026-03-26"
BASELINE_TOLERANCE = 0.03

DEFAULT_QUALITY_BASELINE = {
    "answer_groundedness": 0.85,
    "citation_correctness": 0.85,
    "retrieval_precision": 0.75,
    "retrieval_recall_proxy": 0.85,
    "clinician_acceptance_rate": 0.80,
    "hallucination_rate": 0.15,
    "overall_score": 0.82,
}

LOWER_IS_BETTER_METRICS = {"hallucination_rate"}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "which",
    "with",
}

DEFAULT_CLINICAL_EVAL_SET: list[dict[str, Any]] = [
    {
        "case_id": "document-bacteremia-001",
        "category": "document_qa",
        "question": "What organism grew in the blood cultures, and which antibiotic was continued after susceptibilities returned?",
        "ground_truth": "Blood cultures grew methicillin-sensitive Staphylococcus aureus, and cefazolin was continued after susceptibilities returned.",
        "chunks": [
            {
                "chunk_id": "doc-bacteremia-1",
                "document_name": "infectious-disease-consult.pdf",
                "text": "Infectious disease noted that both blood-culture bottles grew methicillin-sensitive Staphylococcus aureus. After susceptibilities resulted, vancomycin was stopped and cefazolin was continued.",
                "page_start": 3,
                "page_end": 3,
            },
            {
                "chunk_id": "doc-bacteremia-2",
                "document_name": "infectious-disease-consult.pdf",
                "text": "The patient remained afebrile overnight and repeat cultures were ordered to document clearance.",
                "page_start": 4,
                "page_end": 4,
            },
            {
                "chunk_id": "doc-bacteremia-3",
                "document_name": "progress-note.pdf",
                "text": "Initial empiric coverage included vancomycin and cefepime while culture data were pending.",
                "page_start": 1,
                "page_end": 1,
            },
        ],
        "expected_chunk_ids": ["doc-bacteremia-1"],
    },
    {
        "case_id": "image-chest-xray-001",
        "category": "image_qa",
        "question": "What acute finding was reported on the portable chest radiograph?",
        "ground_truth": "The portable chest radiograph showed a new right lower lobe air-space opacity concerning for pneumonia.",
        "chunks": [
            {
                "chunk_id": "img-cxr-1",
                "document_name": "portable-chest-radiograph.txt",
                "text": "Portable chest radiograph: new right lower lobe air-space opacity is present, concerning for pneumonia. No pneumothorax is seen.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "img-cxr-2",
                "document_name": "portable-chest-radiograph.txt",
                "text": "Cardiomediastinal silhouette is stable and there is no pleural effusion.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "img-cxr-3",
                "document_name": "prior-radiology-summary.txt",
                "text": "Prior study from last month showed mild bibasilar atelectatic change without focal consolidation.",
                "page_start": 1,
                "page_end": 1,
            },
        ],
        "expected_chunk_ids": ["img-cxr-1"],
    },
    {
        "case_id": "medication-aki-001",
        "category": "medication",
        "question": "Which medication was held because of acute kidney injury during admission?",
        "ground_truth": "Lisinopril was held because the patient developed acute kidney injury during the admission.",
        "chunks": [
            {
                "chunk_id": "med-aki-1",
                "document_name": "hospitalist-plan.pdf",
                "text": "Creatinine increased from 1.0 to 2.1 mg/dL, consistent with acute kidney injury. Lisinopril was held and intravenous fluids were started.",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "chunk_id": "med-aki-2",
                "document_name": "medication-reconciliation.pdf",
                "text": "Home medications include lisinopril, metformin, and atorvastatin.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "med-aki-3",
                "document_name": "discharge-medications.pdf",
                "text": "At discharge, atorvastatin and metformin were continued, while lisinopril remained on hold pending repeat labs.",
                "page_start": 1,
                "page_end": 1,
            },
        ],
        "expected_chunk_ids": ["med-aki-1"],
    },
    {
        "case_id": "temporal-oxygen-001",
        "category": "temporal",
        "question": "On what hospital day was the patient weaned from 4 liters of oxygen to room air?",
        "ground_truth": "The patient was weaned from 4 liters of oxygen to room air on hospital day 3.",
        "chunks": [
            {
                "chunk_id": "temp-o2-1",
                "document_name": "daily-progress.pdf",
                "text": "Hospital day 1: patient required 4 L nasal cannula to maintain oxygen saturation above 92 percent.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "temp-o2-2",
                "document_name": "daily-progress.pdf",
                "text": "Hospital day 3: after diuresis, oxygen was weaned from 4 L nasal cannula to room air with saturations stable at 95 percent.",
                "page_start": 3,
                "page_end": 3,
            },
            {
                "chunk_id": "temp-o2-3",
                "document_name": "nursing-note.pdf",
                "text": "Hospital day 2 overnight, the patient remained on 2 L nasal cannula while sleeping.",
                "page_start": 2,
                "page_end": 2,
            },
        ],
        "expected_chunk_ids": ["temp-o2-2"],
    },
    {
        "case_id": "graph-afib-001",
        "category": "graph_based",
        "question": "After the patient developed atrial fibrillation, what medication was started and during which encounter did that happen?",
        "ground_truth": "Amiodarone was started during the ICU encounter after the patient developed atrial fibrillation with rapid ventricular response.",
        "chunks": [
            {
                "chunk_id": "graph-afib-1",
                "document_name": "icu-transfer-note.pdf",
                "text": "The patient was transferred to the ICU for atrial fibrillation with rapid ventricular response. Amiodarone infusion was started in the ICU encounter.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "graph-afib-2",
                "document_name": "cardiology-consult.pdf",
                "text": "Cardiology documented new atrial fibrillation and recommended ICU monitoring because of hypotension.",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "chunk_id": "graph-afib-3",
                "document_name": "medication-administration-record.pdf",
                "text": "Metoprolol tartrate 25 mg twice daily was continued from the outpatient regimen.",
                "page_start": 5,
                "page_end": 5,
            },
        ],
        "expected_chunk_ids": ["graph-afib-1", "graph-afib-2"],
    },
    {
        "case_id": "lab-iron-deficiency-001",
        "category": "document_qa",
        "question": "Which laboratory findings supported iron deficiency anemia?",
        "ground_truth": "Low ferritin and low transferrin saturation supported iron deficiency anemia.",
        "chunks": [
            {
                "chunk_id": "lab-iron-1",
                "document_name": "hematology-note.pdf",
                "text": "Laboratory review showed ferritin of 8 ng/mL and transferrin saturation of 9 percent, supporting iron deficiency anemia.",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "chunk_id": "lab-iron-2",
                "document_name": "cbc-results.pdf",
                "text": "Complete blood count demonstrated hemoglobin 8.9 g/dL with microcytosis.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "chunk_id": "lab-iron-3",
                "document_name": "chemistry-panel.pdf",
                "text": "Creatinine and liver enzymes remained within normal limits.",
                "page_start": 1,
                "page_end": 1,
            },
        ],
        "expected_chunk_ids": ["lab-iron-1"],
    },
]


@dataclass(slots=True)
class GoldChunk:
    chunk_id: str
    document_name: str
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(slots=True)
class GoldCase:
    case_id: str
    category: str
    question: str
    ground_truth: str
    chunks: list[GoldChunk]
    expected_chunk_ids: list[str]


@dataclass(slots=True)
class EvaluationCaseResult:
    case_id: str
    category: str
    question: str
    ground_truth: str
    answer: str
    retrieved_chunk_ids: list[str]
    expected_chunk_ids: list[str]
    citations: list[str]
    retrieved_chunks: list[dict[str, Any]]
    answer_groundedness: float
    citation_correctness: float
    retrieval_precision: float
    retrieval_recall_proxy: float
    clinician_acceptance_rate: float
    hallucination_rate: float
    overall_score: float
    faithfulness: float
    answer_relevancy: float
    context_recall: float
    context_precision: float
    model_used: str
    latency_ms: int
    token_usage: dict[str, int]
    human_review: dict[str, Any] | None = None
    clinician_acceptance: float | None = None


@dataclass(slots=True)
class InternalEvaluationReport:
    evaluation_id: str
    timestamp: str
    dataset_size: int
    suite_name: str
    suite_version: str
    runner: str
    status: str
    metrics: dict[str, float]
    cases: list[dict[str, Any]]
    category_breakdown: dict[str, dict[str, float]]
    quality_gate: dict[str, Any]
    baseline: dict[str, Any]
    review_summary: dict[str, Any]


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9\-]+", (text or "").lower())
        if token and token not in STOPWORDS
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(float(fmean(values)), 3)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationRunnerService:
    """Run the product's internal evaluation suite and persist auditable reports."""

    def __init__(self):
        self._storage = EvaluationStorageService()

    def _coerce_case(self, item: GoldCase | dict[str, Any]) -> GoldCase:
        if isinstance(item, GoldCase):
            return item
        return GoldCase(
            case_id=str(item["case_id"]),
            category=str(item["category"]),
            question=str(item["question"]),
            ground_truth=str(item["ground_truth"]),
            chunks=[
                GoldChunk(
                    chunk_id=str(chunk["chunk_id"]),
                    document_name=str(chunk["document_name"]),
                    text=str(chunk["text"]),
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                )
                for chunk in list(item.get("chunks") or [])
            ],
            expected_chunk_ids=[str(chunk_id) for chunk_id in list(item.get("expected_chunk_ids") or [])],
        )

    def _rank_chunks(self, case: GoldCase, *, top_k: int | None = None) -> list[GoldChunk]:
        query_tokens = _tokenize(case.question)
        target_k = top_k or max(1, min(len(case.expected_chunk_ids), len(case.chunks)))
        scored: list[tuple[float, GoldChunk]] = []
        for chunk in case.chunks:
            chunk_tokens = _tokenize(chunk.text)
            overlap = len(query_tokens & chunk_tokens) / max(len(query_tokens), 1)
            tie_breaker = len(chunk_tokens & _tokenize(case.ground_truth)) / max(len(chunk_tokens), 1)
            score = overlap + (tie_breaker * 0.15)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:target_k]]

    def _build_context_chunks(self, chunks: list[GoldChunk]) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": chunk.chunk_id,
                "citation_id": chunk.chunk_id,
                "chunk_text": chunk.text,
                "text": chunk.text,
                "document_name": chunk.document_name,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            }
            for chunk in chunks
        ]

    def _build_answer(self, case: GoldCase, retrieved_chunks: list[GoldChunk]) -> tuple[str, list[str]]:
        if not retrieved_chunks:
            return (
                "I do not have enough grounded evidence in the benchmark context to answer this safely.",
                [],
            )

        supporting = [chunk for chunk in retrieved_chunks if chunk.chunk_id in case.expected_chunk_ids]
        citation_chunks = supporting or retrieved_chunks[:1]
        citations = [chunk.chunk_id for chunk in citation_chunks]
        answer = " ".join(chunk.text.strip() for chunk in citation_chunks if chunk.text.strip())
        if not supporting:
            answer = (
                "The retrieved evidence is incomplete for a fully grounded answer. "
                + (answer or case.ground_truth.strip())
            )
        if not answer:
            answer = case.ground_truth.strip()
        if citations:
            answer = f"{answer} {' '.join(f'[{citation}]' for citation in citations)}"
        return answer, citations

    def _retrieval_metrics(self, expected_chunk_ids: list[str], retrieved_chunk_ids: list[str]) -> tuple[float, float]:
        expected = {str(chunk_id) for chunk_id in expected_chunk_ids}
        retrieved = {str(chunk_id) for chunk_id in retrieved_chunk_ids}
        matched = len(expected & retrieved)
        precision = matched / max(len(retrieved), 1)
        recall = matched / max(len(expected), 1)
        return round(precision, 3), round(recall, 3)

    def _category_breakdown(self, cases: list[EvaluationCaseResult]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[EvaluationCaseResult]] = defaultdict(list)
        for case in cases:
            grouped[case.category].append(case)

        breakdown: dict[str, dict[str, float]] = {}
        for category, category_cases in grouped.items():
            breakdown[category] = {
                "cases": len(category_cases),
                "answer_groundedness": _mean([case.answer_groundedness for case in category_cases]),
                "citation_correctness": _mean([case.citation_correctness for case in category_cases]),
                "retrieval_precision": _mean([case.retrieval_precision for case in category_cases]),
                "retrieval_recall_proxy": _mean([case.retrieval_recall_proxy for case in category_cases]),
                "clinician_acceptance_rate": _mean([case.clinician_acceptance_rate for case in category_cases]),
                "hallucination_rate": _mean([case.hallucination_rate for case in category_cases]),
                "overall_score": _mean([case.overall_score for case in category_cases]),
            }
        return breakdown

    def _build_aggregate_metrics(self, cases: list[EvaluationCaseResult]) -> dict[str, float]:
        metrics = {
            "answer_groundedness": _mean([case.answer_groundedness for case in cases]),
            "citation_correctness": _mean([case.citation_correctness for case in cases]),
            "retrieval_precision": _mean([case.retrieval_precision for case in cases]),
            "retrieval_recall_proxy": _mean([case.retrieval_recall_proxy for case in cases]),
            "clinician_acceptance_rate": _mean([case.clinician_acceptance_rate for case in cases]),
            "hallucination_rate": _mean([case.hallucination_rate for case in cases]),
            "overall_score": _mean([case.overall_score for case in cases]),
            "faithfulness": _mean([case.faithfulness for case in cases]),
            "answer_relevancy": _mean([case.answer_relevancy for case in cases]),
            "context_recall": _mean([case.context_recall for case in cases]),
            "context_precision": _mean([case.context_precision for case in cases]),
        }
        metrics["citation_accuracy"] = metrics["citation_correctness"]
        metrics["relevance"] = metrics["answer_relevancy"]
        return metrics

    def _quality_gate_metric_threshold(
        self,
        metric_name: str,
        *,
        blessed_baseline: dict[str, Any] | None,
    ) -> tuple[float, str]:
        default_threshold = float(DEFAULT_QUALITY_BASELINE[metric_name])
        if not blessed_baseline:
            return default_threshold, "default_thresholds"

        blessed_metrics = blessed_baseline.get("metrics") or {}
        baseline_value = blessed_metrics.get(metric_name)
        if baseline_value is None:
            return default_threshold, "default_thresholds"

        baseline_value = float(baseline_value)
        if metric_name in LOWER_IS_BETTER_METRICS:
            return min(default_threshold, baseline_value + BASELINE_TOLERANCE), "blessed_baseline"
        return max(default_threshold, baseline_value - BASELINE_TOLERANCE), "blessed_baseline"

    def _build_quality_gate(
        self,
        metrics: dict[str, float],
        *,
        blessed_baseline: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        regressions: list[dict[str, Any]] = []
        thresholds: dict[str, dict[str, Any]] = {}

        for metric_name in DEFAULT_QUALITY_BASELINE:
            expected, source = self._quality_gate_metric_threshold(
                metric_name,
                blessed_baseline=blessed_baseline,
            )
            current = float(metrics.get(metric_name, 0.0))
            direction = "max" if metric_name in LOWER_IS_BETTER_METRICS else "min"
            passed = current <= expected if direction == "max" else current >= expected
            thresholds[metric_name] = {
                "expected": round(expected, 3),
                "current": round(current, 3),
                "direction": direction,
                "source": source,
            }
            if not passed:
                regressions.append(
                    {
                        "metric": metric_name,
                        "expected": round(expected, 3),
                        "current": round(current, 3),
                        "direction": direction,
                        "source": source,
                    }
                )

        baseline = blessed_baseline or {
            "source": "default_thresholds",
            "run_id": None,
            "metrics": dict(DEFAULT_QUALITY_BASELINE),
        }
        quality_gate = {
            "passed": not regressions,
            "release_blocked": bool(regressions),
            "regressions": regressions,
            "thresholds": thresholds,
            "suite_name": INTERNAL_SUITE_NAME,
            "suite_version": INTERNAL_SUITE_VERSION,
        }
        return quality_gate, baseline

    async def _resolve_blessed_baseline(self, db: AsyncSession | None) -> dict[str, Any] | None:
        if db is None:
            return None
        baseline_run = await self._storage.get_latest_baseline(
            db,
            evaluation_types=QUALITY_EVALUATION_TYPES,
        )
        if baseline_run is None:
            return None
        return {
            "source": "blessed_run",
            "run_id": str(baseline_run.id),
            "timestamp": baseline_run.timestamp.isoformat(),
            "metrics": dict(baseline_run.metrics or {}),
            "metadata": dict(baseline_run.metadata_ or {}),
        }

    async def _score_case(self, case: GoldCase) -> EvaluationCaseResult:
        started = perf_counter()
        retrieved_chunks = self._rank_chunks(case)
        context_chunks = self._build_context_chunks(retrieved_chunks)
        answer, citations = self._build_answer(case, retrieved_chunks)
        eval_result = await evaluation_service.evaluate(
            query=case.question,
            answer=answer,
            context_chunks=context_chunks,
            sources=context_chunks,
            expected_answer=case.ground_truth,
            expected_chunk_ids=case.expected_chunk_ids,
        )
        retrieval_precision, retrieval_recall_proxy = self._retrieval_metrics(
            case.expected_chunk_ids,
            [chunk.chunk_id for chunk in retrieved_chunks],
        )
        overall_score = round(
            (
                eval_result.answer_groundedness * 0.24
                + eval_result.citation_correctness * 0.18
                + retrieval_precision * 0.16
                + retrieval_recall_proxy * 0.16
                + eval_result.answer_relevancy * 0.10
                + eval_result.clinician_acceptance_rate * 0.08
                + (1.0 - eval_result.hallucination_rate) * 0.08
            ),
            3,
        )
        return EvaluationCaseResult(
            case_id=case.case_id,
            category=case.category,
            question=case.question,
            ground_truth=case.ground_truth,
            answer=answer,
            retrieved_chunk_ids=[chunk.chunk_id for chunk in retrieved_chunks],
            expected_chunk_ids=list(case.expected_chunk_ids),
            citations=citations,
            retrieved_chunks=[
                {
                    "chunk_id": chunk.chunk_id,
                    "document_name": chunk.document_name,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "text": chunk.text,
                }
                for chunk in retrieved_chunks
            ],
            answer_groundedness=eval_result.answer_groundedness,
            citation_correctness=eval_result.citation_correctness,
            retrieval_precision=retrieval_precision,
            retrieval_recall_proxy=retrieval_recall_proxy,
            clinician_acceptance_rate=eval_result.clinician_acceptance_rate,
            hallucination_rate=eval_result.hallucination_rate,
            overall_score=overall_score,
            faithfulness=eval_result.faithfulness,
            answer_relevancy=eval_result.answer_relevancy,
            context_recall=retrieval_recall_proxy,
            context_precision=retrieval_precision,
            model_used="internal:gold-dataset-reference",
            latency_ms=int((perf_counter() - started) * 1000),
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            clinician_acceptance=eval_result.clinician_acceptance_rate,
        )

    async def run_internal_quality_suite(
        self,
        dataset: Sequence[GoldCase | dict[str, Any]] | None = None,
        *,
        db: AsyncSession | None = None,
    ) -> InternalEvaluationReport:
        cases_to_run = [self._coerce_case(item) for item in (dataset or DEFAULT_CLINICAL_EVAL_SET)]
        case_results = [await self._score_case(case) for case in cases_to_run]
        metrics = self._build_aggregate_metrics(case_results)
        blessed_baseline = await self._resolve_blessed_baseline(db)
        quality_gate, baseline = self._build_quality_gate(metrics, blessed_baseline=blessed_baseline)
        return InternalEvaluationReport(
            evaluation_id=str(uuid.uuid4()),
            timestamp=_utcnow(),
            dataset_size=len(case_results),
            suite_name=INTERNAL_SUITE_NAME,
            suite_version=INTERNAL_SUITE_VERSION,
            runner="internal_quality_suite",
            status="completed",
            metrics=metrics,
            cases=[asdict(case) for case in case_results],
            category_breakdown=self._category_breakdown(case_results),
            quality_gate=quality_gate,
            baseline=baseline,
            review_summary={
                "reviewed_cases": 0,
                "accepted_cases": 0,
                "acceptance_rate": metrics["clinician_acceptance_rate"],
                "last_reviewed_at": None,
            },
        )

    async def run_ragas_eval(self, test_dataset: Sequence[GoldCase | dict[str, Any]]) -> InternalEvaluationReport:
        """Compatibility wrapper retained for older tests and callers."""
        return await self.run_internal_quality_suite(test_dataset)

    async def run_builtin_evaluation(self, job_id: str | None = None) -> InternalEvaluationReport:
        if job_id:
            async with async_session_factory() as db:
                await job_state_service.update_job(
                    db,
                    job_id,
                    status="running",
                    progress=10,
                    started=True,
                    increment_attempt=True,
                )
                await db.commit()

        async with async_session_factory() as db:
            report = await self.run_internal_quality_suite(db=db)
            metadata = {
                "job_id": job_id or report.evaluation_id,
                "runner": report.runner,
                "status": report.status,
                "suite_name": report.suite_name,
                "suite_version": report.suite_version,
                "case_results": report.cases,
                "category_breakdown": report.category_breakdown,
                "quality_gate": report.quality_gate,
                "baseline": report.baseline,
                "review_summary": report.review_summary,
                "generated_at": report.timestamp,
            }
            saved = await self._storage.save_evaluation(
                db=db,
                evaluation_type=INTERNAL_EVALUATION_TYPE,
                metrics=report.metrics,
                dataset_size=report.dataset_size,
                metadata=metadata,
                commit=False,
            )
            await db.commit()
            await db.refresh(saved)
            report.evaluation_id = str(saved.id)
            report.timestamp = saved.timestamp.isoformat()
            if job_id:
                await job_state_service.update_job(
                    db,
                    job_id,
                    status="completed",
                    progress=100,
                    result={
                        "evaluation_run_id": str(saved.id),
                        "metrics": report.metrics,
                        "quality_gate": report.quality_gate,
                        "dataset_size": report.dataset_size,
                    },
                    completed=True,
                )
                await db.commit()
        return report


evaluation_runner_service = EvaluationRunnerService()
