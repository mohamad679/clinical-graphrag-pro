"""
Internal response-quality evaluation utilities.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    "with",
}


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9\-]+", (text or "").lower())
        if token and token not in STOPWORDS
    }


def _extract_citation_tokens(answer: str) -> list[str]:
    return re.findall(r"\[([A-Za-z0-9:_\-]+)\]", answer or "")


@dataclass
class EvalResult:
    """Result of evaluating a single query-answer pair."""

    query: str
    answer: str
    answer_groundedness: float
    citation_correctness: float
    retrieval_precision: float
    retrieval_recall_proxy: float
    clinician_acceptance_rate: float
    hallucination_rate: float
    overall_score: float
    details: dict

    @property
    def faithfulness(self) -> float:
        return self.answer_groundedness

    @property
    def relevance(self) -> float:
        return self.details.get("answer_relevancy", {}).get("score", 0.0)

    @property
    def answer_relevancy(self) -> float:
        return self.relevance

    @property
    def citation_accuracy(self) -> float:
        return self.citation_correctness

    @property
    def context_precision(self) -> float:
        return self.retrieval_precision

    @property
    def context_recall(self) -> float:
        return self.retrieval_recall_proxy

    def metric_payload(self) -> dict[str, float]:
        return {
            "answer_groundedness": self.answer_groundedness,
            "citation_correctness": self.citation_correctness,
            "retrieval_precision": self.retrieval_precision,
            "retrieval_recall_proxy": self.retrieval_recall_proxy,
            "clinician_acceptance_rate": self.clinician_acceptance_rate,
            "hallucination_rate": self.hallucination_rate,
            "overall_score": self.overall_score,
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "citation_accuracy": self.citation_accuracy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "relevance": self.relevance,
        }


class EvaluationService:
    """Evaluate grounded response quality with deterministic internal metrics."""

    async def evaluate(
        self,
        query: str,
        answer: str,
        context_chunks: list[dict],
        sources: list[dict] | None = None,
        *,
        expected_answer: str | None = None,
        expected_chunk_ids: list[str] | None = None,
    ) -> EvalResult:
        details: dict[str, dict] = {}
        groundedness = self._eval_answer_groundedness(answer, context_chunks)
        details["answer_groundedness"] = groundedness
        details["faithfulness"] = groundedness

        answer_relevancy = self._eval_answer_relevancy(query, answer, expected_answer=expected_answer)
        details["answer_relevancy"] = answer_relevancy
        details["relevance"] = answer_relevancy

        citation_correctness = self._eval_citation_correctness(
            answer,
            context_chunks,
            sources=sources,
            expected_chunk_ids=expected_chunk_ids,
        )
        details["citation_correctness"] = citation_correctness
        details["citation_accuracy"] = citation_correctness

        retrieval_precision = self._eval_retrieval_precision(answer, context_chunks)
        details["retrieval_precision"] = retrieval_precision
        details["context_precision"] = retrieval_precision

        retrieval_recall_proxy = self._eval_retrieval_recall_proxy(
            answer,
            context_chunks,
            expected_answer=expected_answer,
            expected_chunk_ids=expected_chunk_ids,
        )
        details["retrieval_recall_proxy"] = retrieval_recall_proxy
        details["context_recall"] = retrieval_recall_proxy

        hallucination_rate = {
            "score": round(max(0.0, 1.0 - groundedness["score"]), 3),
            "explanation": "Complement of groundedness over the generated answer.",
        }
        details["hallucination_rate"] = hallucination_rate

        clinician_acceptance_rate = {
            "score": 1.0 if (
                groundedness["score"] >= 0.75
                and citation_correctness["score"] >= 0.6
                and hallucination_rate["score"] <= 0.25
            ) else 0.0,
            "explanation": "Automatic surrogate for clinician acceptance until a physician review is recorded.",
        }
        details["clinician_acceptance_rate"] = clinician_acceptance_rate

        overall = (
            groundedness["score"] * 0.24
            + citation_correctness["score"] * 0.16
            + retrieval_precision["score"] * 0.14
            + retrieval_recall_proxy["score"] * 0.14
            + answer_relevancy["score"] * 0.16
            + clinician_acceptance_rate["score"] * 0.08
            + (1.0 - hallucination_rate["score"]) * 0.08
        )

        return EvalResult(
            query=query,
            answer=answer,
            answer_groundedness=groundedness["score"],
            citation_correctness=citation_correctness["score"],
            retrieval_precision=retrieval_precision["score"],
            retrieval_recall_proxy=retrieval_recall_proxy["score"],
            clinician_acceptance_rate=clinician_acceptance_rate["score"],
            hallucination_rate=hallucination_rate["score"],
            overall_score=round(overall, 3),
            details=details,
        )

    def _eval_answer_groundedness(self, answer: str, context_chunks: list[dict]) -> dict:
        if not context_chunks:
            return {"score": 0.0, "explanation": "No context provided."}
        answer_tokens = _tokenize(answer)
        context_tokens = set()
        for chunk in context_chunks:
            context_tokens |= _tokenize(chunk.get("chunk_text", chunk.get("text", "")))
        if not answer_tokens:
            return {"score": 0.0, "explanation": "Empty answer."}
        supported = len(answer_tokens & context_tokens) / max(len(answer_tokens), 1)
        return {
            "score": round(supported, 3),
            "explanation": f"{len(answer_tokens & context_tokens)}/{len(answer_tokens)} answer tokens are grounded in retrieved context.",
        }

    def _eval_answer_relevancy(self, query: str, answer: str, *, expected_answer: str | None = None) -> dict:
        query_tokens = _tokenize(query)
        answer_tokens = _tokenize(answer)
        target_tokens = query_tokens | (_tokenize(expected_answer or ""))
        if not answer_tokens or not target_tokens:
            return {"score": 0.0, "explanation": "Missing query or answer tokens."}
        overlap = len(answer_tokens & target_tokens) / max(len(answer_tokens), 1)
        return {
            "score": round(overlap, 3),
            "explanation": "Measures how much of the answer aligns with the question and gold-answer vocabulary.",
        }

    def _eval_citation_correctness(
        self,
        answer: str,
        context_chunks: list[dict],
        *,
        sources: list[dict] | None,
        expected_chunk_ids: list[str] | None = None,
    ) -> dict:
        citations = _extract_citation_tokens(answer)
        if not citations:
            return {"score": 0.0, "explanation": "No citations found in answer."}

        valid_chunk_ids = {
            str(chunk.get("chunk_id") or chunk.get("citation_id") or "")
            for chunk in context_chunks
            if chunk.get("chunk_id") or chunk.get("citation_id")
        }
        if sources:
            for source in sources:
                if source.get("chunk_id"):
                    valid_chunk_ids.add(str(source["chunk_id"]))
                if source.get("citation_id"):
                    valid_chunk_ids.add(str(source["citation_id"]))

        expected = {str(item) for item in (expected_chunk_ids or [])}
        matched = 0
        for citation in citations:
            if citation in valid_chunk_ids or citation in expected:
                matched += 1
        score = matched / max(len(citations), 1)
        return {
            "score": round(score, 3),
            "explanation": f"Matched {matched}/{len(citations)} citations to retrieved or expected chunk ids.",
        }

    def _eval_retrieval_precision(self, answer: str, context_chunks: list[dict]) -> dict:
        if not context_chunks:
            return {"score": 0.0, "explanation": "No retrieved context available."}
        answer_tokens = _tokenize(answer)
        used_chunks = 0
        for chunk in context_chunks:
            chunk_tokens = _tokenize(chunk.get("chunk_text", chunk.get("text", "")))
            if chunk_tokens and len(answer_tokens & chunk_tokens) / max(len(chunk_tokens), 1) >= 0.15:
                used_chunks += 1
        score = used_chunks / max(len(context_chunks), 1)
        return {
            "score": round(score, 3),
            "explanation": f"{used_chunks}/{len(context_chunks)} retrieved chunks contributed meaningful vocabulary to the answer.",
        }

    def _eval_retrieval_recall_proxy(
        self,
        answer: str,
        context_chunks: list[dict],
        *,
        expected_answer: str | None = None,
        expected_chunk_ids: list[str] | None = None,
    ) -> dict:
        if not context_chunks:
            return {"score": 0.0, "explanation": "No retrieved context available."}

        if expected_chunk_ids:
            retrieved_ids = {
                str(chunk.get("chunk_id") or chunk.get("citation_id") or "")
                for chunk in context_chunks
            }
            expected = {str(item) for item in expected_chunk_ids}
            matched = len(retrieved_ids & expected)
            score = matched / max(len(expected), 1)
            return {
                "score": round(score, 3),
                "explanation": f"Retrieved {matched}/{len(expected)} expected evidence chunks.",
            }

        expected_tokens = _tokenize(expected_answer or "")
        context_tokens = set()
        for chunk in context_chunks:
            context_tokens |= _tokenize(chunk.get("chunk_text", chunk.get("text", "")))
        if not expected_tokens:
            expected_tokens = _tokenize(answer)
        matched = len(expected_tokens & context_tokens)
        score = matched / max(len(expected_tokens), 1)
        return {
            "score": round(score, 3),
            "explanation": "Proxy for evidence recall based on overlap between gold-answer vocabulary and retrieved context.",
        }


evaluation_service = EvaluationService()
