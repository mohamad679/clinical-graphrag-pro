"""
RAG pipeline service — orchestrates retrieval and generation.
Now uses the advanced QueryEngine for hybrid search, reranking, and query expansion.
"""

import logging
from typing import AsyncGenerator

from app.services.llm import llm_service
from app.services.query_engine import query_engine

logger = logging.getLogger(__name__)


class RAGService:
    """Retrieval-Augmented Generation pipeline with advanced retrieval."""

    def build_context(self, results: list[dict], max_tokens: int = 3000) -> str:
        """Build a context string from enriched search results."""
        if not results:
            return ""

        context_parts = []
        total_len = 0

        for r in results:
            doc_name = r.get("document_name", "Unknown")
            chunk_idx = r.get("chunk_index", 0)
            score = r.get("score", 0.0)
            text = r.get("chunk_text", "")

            header = f"[Source: {doc_name} | Chunk {chunk_idx} | Score: {score:.3f}]"
            section = f"{header}\n{text}\n"
            section_len = len(section.split())

            if total_len + section_len > max_tokens:
                break

            context_parts.append(section)
            total_len += section_len

        return "\n---\n".join(context_parts)

    async def query_stream(
        self,
        question: str,
        top_k: int = 5,
        chat_history: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Full RAG pipeline with streaming.
        Yields dicts with type: "reasoning" | "source" | "token" | "done" | "error"
        """

        # ── Step 1: Query Expansion ──────────────────────
        yield {
            "type": "reasoning",
            "step": 1,
            "title": "Expanding query",
            "description": "Generating alternative phrasings with medical synonyms...",
            "status": "running",
        }

        try:
            enriched = await query_engine.query(question, top_k=top_k)
        except Exception as e:
            logger.error(f"Query engine failed: {e}")
            yield {
                "type": "error",
                "content": f"Search failed: {str(e)}",
            }
            return

        expand_desc = f"Generated {len(enriched.expanded_queries)} query variants."
        if enriched.expanded_queries:
            expand_desc += f" Variants: {', '.join(enriched.expanded_queries[:2])}"

        yield {
            "type": "reasoning",
            "step": 1,
            "title": "Expanding query",
            "description": expand_desc,
            "status": "done",
        }

        results = enriched.results

        # ── Step 2: Hybrid Search + Reranking ────────────
        yield {
            "type": "reasoning",
            "step": 2,
            "title": "Searching & reranking",
            "description": (
                f"Hybrid {enriched.retrieval_method} search across {enriched.total_candidates} candidates. "
                f"{'Reranked with cross-encoder.' if enriched.reranked else 'No reranking.'}"
            ),
            "status": "done",
        }

        # ── Step 3: Yield sources ────────────────────────
        if results:
            yield {
                "type": "source",
                "sources": [
                    {
                        "document_name": r.get("document_name", ""),
                        "document_id": r.get("document_id", ""),
                        "chunk_index": r.get("chunk_index", 0),
                        "text": (
                            r.get("chunk_text", "")[:200] + "..."
                            if len(r.get("chunk_text", "")) > 200
                            else r.get("chunk_text", "")
                        ),
                        "relevance_score": r.get("score", 0.0),
                    }
                    for r in results
                ],
            }

        # ── Step 4: Build context ────────────────────────
        yield {
            "type": "reasoning",
            "step": 3,
            "title": "Building context",
            "description": "Assembling relevant passages for the LLM...",
            "status": "running",
        }

        context = self.build_context(results)

        yield {
            "type": "reasoning",
            "step": 3,
            "title": "Building context",
            "description": f"Context ready ({len(context.split())} words from {len(results)} sources).",
            "status": "done",
        }

        # ── Step 5: Generate answer ──────────────────────
        yield {
            "type": "reasoning",
            "step": 4,
            "title": "Generating answer",
            "description": "Streaming response from the language model...",
            "status": "running",
        }

        try:
            async for token in llm_service.generate_stream(
                user_message=question,
                context=context,
                chat_history=chat_history,
            ):
                yield {"type": "token", "content": token}
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            yield {"type": "error", "content": f"Generation failed: {str(e)}"}
            return

        yield {
            "type": "reasoning",
            "step": 4,
            "title": "Generating answer",
            "description": "Response complete.",
            "status": "done",
        }

        yield {"type": "done"}

    async def query(
        self,
        question: str,
        top_k: int = 5,
        chat_history: list[dict] | None = None,
    ) -> dict:
        """Non-streaming RAG query. Returns full response dict."""
        tokens = []
        sources = []

        async for chunk in self.query_stream(question, top_k, chat_history):
            if chunk["type"] == "token":
                tokens.append(chunk["content"])
            elif chunk["type"] == "source":
                sources = chunk["sources"]
            elif chunk["type"] == "error":
                return {"answer": chunk["content"], "sources": [], "error": True}

        return {
            "answer": "".join(tokens),
            "sources": sources,
            "error": False,
        }


# Module-level singleton
rag_service = RAGService()
