"""
RAG Evaluation Framework.
Computes quality metrics for retrieval-augmented generation.

Metrics:
- Faithfulness: Is the answer grounded in retrieved context?
- Relevance: Is the answer relevant to the query?
- Citation Accuracy: Are claims mapped to valid sources?
- Context Precision: How much retrieved context is actually used?
"""

import logging
import re
from dataclasses import dataclass

import numpy as np

from app.services.llm import llm_service

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of evaluating a single query-answer pair."""
    query: str
    answer: str
    faithfulness: float        # 0-1
    relevance: float           # 0-1
    citation_accuracy: float   # 0-1
    context_precision: float   # 0-1
    overall_score: float       # weighted average
    details: dict              # per-metric explanations


class EvaluationService:
    """
    Evaluate RAG quality using LLM-as-judge and heuristic methods.
    """

    async def evaluate(
        self,
        query: str,
        answer: str,
        context_chunks: list[dict],
        sources: list[dict] | None = None,
    ) -> EvalResult:
        """
        Evaluate a query-answer pair against retrieved context.

        Args:
            query: The original user question
            answer: The generated answer
            context_chunks: Retrieved passages (list of dicts with 'chunk_text', 'document_name')
            sources: Optional list of cited sources
        """
        details = {}

        # ── 1. Faithfulness (LLM-as-judge) ───────────────
        faithfulness = await self._eval_faithfulness(answer, context_chunks)
        details["faithfulness"] = faithfulness

        # ── 2. Relevance (embedding similarity) ──────────
        relevance = await self._eval_relevance(query, answer)
        details["relevance"] = relevance

        # ── 3. Citation Accuracy (heuristic) ─────────────
        citation_accuracy = self._eval_citation_accuracy(answer, context_chunks, sources)
        details["citation_accuracy"] = citation_accuracy

        # ── 4. Context Precision (heuristic) ─────────────
        context_precision = self._eval_context_precision(answer, context_chunks)
        details["context_precision"] = context_precision

        # ── Weighted overall ─────────────────────────────
        overall = (
            faithfulness["score"] * 0.35
            + relevance["score"] * 0.25
            + citation_accuracy["score"] * 0.20
            + context_precision["score"] * 0.20
        )

        return EvalResult(
            query=query,
            answer=answer,
            faithfulness=faithfulness["score"],
            relevance=relevance["score"],
            citation_accuracy=citation_accuracy["score"],
            context_precision=context_precision["score"],
            overall_score=round(overall, 3),
            details=details,
        )

    async def _eval_faithfulness(self, answer: str, context_chunks: list[dict]) -> dict:
        """
        LLM judges whether the answer is fully supported by context.
        Returns score 0-1 and explanation.
        """
        if not context_chunks:
            return {"score": 0.0, "explanation": "No context provided."}

        context_text = "\n\n".join(
            c.get("chunk_text", c.get("text", ""))[:500]
            for c in context_chunks[:5]
        )

        prompt = (
            "You are an expert evaluator for RAG systems.\n\n"
            "Given the following CONTEXT and ANSWER, score how well the answer "
            "is supported by (faithful to) the context.\n\n"
            f"CONTEXT:\n{context_text}\n\n"
            f"ANSWER:\n{answer[:1000]}\n\n"
            "Respond with ONLY a JSON object like:\n"
            '{"score": 0.85, "explanation": "brief reason"}\n\n'
            "Score 1.0 = fully supported, 0.0 = completely made up."
        )

        try:
            response = await llm_service.generate(user_message=prompt, context="")
            return self._parse_json_score(response, "faithfulness")
        except Exception as e:
            logger.warning(f"Faithfulness eval failed: {e}")
            return {"score": 0.5, "explanation": f"Evaluation failed: {e}"}

    async def _eval_relevance(self, query: str, answer: str) -> dict:
        """
        LLM judges whether the answer is relevant to the query.
        """
        prompt = (
            "You are an expert evaluator.\n\n"
            "Score how relevant and helpful this answer is to the query.\n\n"
            f"QUERY: {query}\n\n"
            f"ANSWER:\n{answer[:1000]}\n\n"
            "Respond with ONLY a JSON object like:\n"
            '{"score": 0.9, "explanation": "brief reason"}\n\n'
            "Score 1.0 = perfectly relevant, 0.0 = completely irrelevant."
        )

        try:
            response = await llm_service.generate(user_message=prompt, context="")
            return self._parse_json_score(response, "relevance")
        except Exception as e:
            logger.warning(f"Relevance eval failed: {e}")
            return {"score": 0.5, "explanation": f"Evaluation failed: {e}"}

    def _eval_citation_accuracy(
        self, answer: str, context_chunks: list[dict], sources: list[dict] | None
    ) -> dict:
        """
        Heuristic: checks what fraction of source references in the answer
        can be matched to actual retrieved chunks.
        """
        if not sources and not context_chunks:
            return {"score": 0.0, "explanation": "No sources available."}

        # Extract source references from the answer (patterns like [Source: ...])
        cited = re.findall(r'\[(?:Source|Ref|Citation)[:\s]*([^\]]+)\]', answer, re.IGNORECASE)

        if not cited:
            # Check if answer contains any document names
            doc_names = set(
                c.get("document_name", "")
                for c in context_chunks
                if c.get("document_name")
            )
            mentions = sum(1 for name in doc_names if name.lower() in answer.lower())

            if doc_names and mentions > 0:
                score = min(mentions / len(doc_names), 1.0)
                return {
                    "score": round(score, 3),
                    "explanation": f"Found {mentions}/{len(doc_names)} source mentions in answer."
                }

            # No explicit citations — give partial credit if context was used
            if context_chunks and len(answer) > 50:
                return {"score": 0.3, "explanation": "No explicit citations, but answer appears substantive."}
            return {"score": 0.0, "explanation": "No citations found in answer."}

        # Match cited sources to actual chunks
        doc_names = set(
            c.get("document_name", "").lower()
            for c in context_chunks
            if c.get("document_name")
        )

        matched = sum(
            1 for c in cited
            if any(name in c.lower() for name in doc_names)
        )

        score = matched / len(cited) if cited else 0.0
        return {
            "score": round(score, 3),
            "explanation": f"Matched {matched}/{len(cited)} citations to sources."
        }

    def _eval_context_precision(self, answer: str, context_chunks: list[dict]) -> dict:
        """
        Heuristic: measures what fraction of retrieved chunks are actually
        reflected in the answer (checking term overlap).
        """
        if not context_chunks or not answer:
            return {"score": 0.0, "explanation": "No data to evaluate."}

        answer_words = set(answer.lower().split())
        used_chunks = 0

        for chunk in context_chunks:
            chunk_text = chunk.get("chunk_text", chunk.get("text", ""))
            chunk_words = set(chunk_text.lower().split())

            # Significant word overlap indicates the chunk was used
            overlap = len(answer_words & chunk_words)
            chunk_unique = len(chunk_words - {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or"})

            if chunk_unique > 0 and overlap / chunk_unique > 0.15:
                used_chunks += 1

        score = used_chunks / len(context_chunks)
        return {
            "score": round(score, 3),
            "explanation": f"{used_chunks}/{len(context_chunks)} chunks reflected in answer."
        }

    @staticmethod
    def _parse_json_score(response: str, metric_name: str) -> dict:
        """Parse a JSON score from LLM response."""
        import json

        # Try to extract JSON from response
        json_match = re.search(r'\{[^}]+\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                score = float(data.get("score", 0.5))
                score = max(0.0, min(1.0, score))
                return {
                    "score": round(score, 3),
                    "explanation": data.get("explanation", f"Score: {score}")
                }
            except (json.JSONDecodeError, ValueError):
                pass

        # Fallback: try to extract a number
        nums = re.findall(r'(\d+\.?\d*)', response)
        if nums:
            score = float(nums[0])
            if score > 1:
                score = score / 100  # handle percentage
            score = max(0.0, min(1.0, score))
            return {"score": round(score, 3), "explanation": f"Parsed {metric_name} score."}

        return {"score": 0.5, "explanation": f"Could not parse {metric_name} score."}


# Module-level singleton
evaluation_service = EvaluationService()
