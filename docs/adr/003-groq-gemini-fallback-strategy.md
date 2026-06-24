# ADR-003: Groq-First Text Generation With Gemini Fallback

**Date:** 2026-04-01  
**Status:** Accepted  
**Deciders:** Solo developer  

## Context
Text generation is routed through `LLMService` in `backend/app/services/llm.py`. The current implementation in `generate_with_metadata()` attempts Groq first when `settings.groq_api_key` is present, then falls back to Gemini when `settings.google_api_key` is present and the Groq call fails. Both provider-specific branches normalize the result into the shared `LLMResponse` dataclass.

Medical image analysis uses a different service. `backend/app/services/vision.py` defines `VisionService`, and both `analyze_image()` and `analyze_with_question()` route through `_call_gemini_vision()`. In other words, text inference is dual-provider in the current code, while image inference is Gemini-only.

## Decision
Keep the current provider split:
- Groq-first, Gemini-fallback for text generation in `LLMService.generate_with_metadata()`.
- Gemini-only for vision and multimodal image analysis in `VisionService`.

This decision is reflected directly in the code:
- `LLMService._generate_groq()` sends text generation requests to `https://api.groq.com/openai/v1`.
- `LLMService._generate_gemini()` sends fallback requests to `https://generativelanguage.googleapis.com/v1beta`.
- `VisionService._call_gemini_vision()` is the only implemented image-analysis path.

## Consequences
**Positive:** Text generation has provider redundancy without changing the caller contract because both branches return the same `LLMResponse` shape. The image pipeline uses a single multimodal implementation path instead of forcing the document chat service to understand image prompts directly.  
**Negative:** The deployment needs credentials for two external providers if both text paths are to be available. The runtime also has to normalize two different response payload formats and token accounting formats into `LLMResponse`.  
**Risks:** The current text routing is credential-driven rather than `LLM_PROVIDER`-driven. In `backend/app/services/llm.py`, Groq is attempted first whenever a Groq key exists, even if the environment advertises a different preferred provider. There is also no secondary image-analysis provider in `VisionService`, so the multimodal path still has a single-provider dependency.

## Alternatives Considered
| Alternative | Why Rejected |
|-------------|--------------|
| Groq-only for all inference | `VisionService` does not implement a Groq vision path, so Groq-only would remove image analysis capability from the current codebase. |
| Gemini-only for all inference | The text service already implements Groq and Gemini branches with normalization through `LLMResponse`, so dropping Groq would remove a working fallback path. |
| Strictly honor `LLM_PROVIDER` and disable failover | The implemented behavior in `LLMService.generate_with_metadata()` is failover-oriented. A hard pin would reduce resilience and would require explicit routing changes. |
