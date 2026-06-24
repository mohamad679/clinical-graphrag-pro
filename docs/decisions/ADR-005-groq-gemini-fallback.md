# ADR-005: Groq and Gemini Fallback

## Status
Accepted

## Context

The system depends on external LLM providers for answer generation, query expansion, and some normalization fallbacks. A single provider would make the application more brittle and would constrain model selection for text and multimodal tasks.

## Decision

We route text generation through `backend/app/services/llm.py` with Groq as the primary provider and Gemini as the fallback. The image-analysis path remains Gemini-centered through `backend/app/services/vision.py`.

## Alternatives Considered

- **Single-provider LLM stack**: rejected because provider outages or credential issues would disable too much of the application.
- **Provider-specific application code paths everywhere**: rejected because it would spread model-routing logic across the codebase.

## Consequences

**Positive:**
- The application can fail over between providers at runtime.
- Text and multimodal tasks can use different provider strengths without changing the calling code.
- Provider usage and latency are captured behind one service boundary.

**Negative:**
- Prompt behavior and output shape differ across providers and require normalization.
- Benchmark reproducibility depends on valid credentials for at least one provider.
- Multi-provider testing is harder than single-provider testing.

## Date
2026-03-24
