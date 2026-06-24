"""
LLM client service — Groq (primary) with Gemini fallback.
Supports both metadata-rich full generation and compatibility streaming helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

from app.core.config import get_settings
from app.core.metrics import observe_llm_call, observe_llm_latency, record_token_usage, record_provider_error
from app.core.observability import trace_operation

logger = logging.getLogger(__name__)
settings = get_settings()

# ── System prompt for the medical assistant ──────────────

SYSTEM_PROMPT = """You are Clinical GraphRAG Pro, an advanced medical AI assistant.

RULES:
1. Answer ONLY based on the provided context from medical documents or images.
2. If the context doesn't contain enough information, say so clearly.
3. Cite grounded evidence using the citation markers provided in the context.
4. Use precise medical terminology but explain complex terms.
5. Format responses in clean Markdown, not HTML.
6. Use short clinical sections with headings when helpful, such as "Summary", "Key Evidence", "Interpretation", and "Next Steps".
7. Use Markdown tables for comparisons, timelines, lab values, paper details, or multi-finding summaries when they make the answer easier to scan.
8. Use **bold** only for important labels or key terms, and keep paragraphs short.
9. Never wrap the full answer in a code block.
10. Never fabricate medical information.
11. End your response with a heuristic evidence-support score on a scale of 0.0 to 1.0, formatted exactly as:
[EVIDENCE_SUPPORT: 0.85]
This value is not calibrated clinical confidence.
"""


@dataclass(slots=True)
class LLMResponse:
    text: str
    provider: str
    model_used: str
    token_usage: dict[str, int]


class LLMService:
    """Unified LLM interface with provider fallback."""

    def __init__(self):
        self._groq_client: httpx.AsyncClient | None = None
        self._gemini_client: httpx.AsyncClient | None = None

    async def _get_groq_client(self) -> httpx.AsyncClient:
        if self._groq_client is None:
            self._groq_client = httpx.AsyncClient(
                base_url="https://api.groq.com/openai/v1",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        return self._groq_client

    async def _get_gemini_client(self) -> httpx.AsyncClient:
        if self._gemini_client is None:
            self._gemini_client = httpx.AsyncClient(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                headers={
                    "x-goog-api-key": settings.google_api_key,
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        return self._gemini_client

    async def generate_with_metadata(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
        system_prompt: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Return a full response plus provider/model/usage metadata."""
        messages = self._build_messages(user_message, context, chat_history, system_prompt=system_prompt)

        provider = settings.llm_provider.lower()
        if provider == "ollama":
            return await self._generate_ollama(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        elif provider == "llama_cpp":
            return await self._generate_llama_cpp(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        elif provider == "local_hf":
            return await self._generate_local_hf(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        elif provider == "gemini":
            if not settings.google_api_key:
                raise ValueError(
                    "Google Gemini API key is missing. Please configure GEMINI_API_KEY or GOOGLE_API_KEY."
                )
            return await self._generate_gemini(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        elif provider == "groq":
            if not settings.groq_api_key:
                raise ValueError(
                    "Groq API key is missing. Please configure GROQ_API_KEY."
                )
            return await self._generate_groq(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        elif provider == "retrieval-only":
            return LLMResponse(
                text="Retrieval-only mode: LLM generation is bypassed.",
                provider="retrieval-only",
                model_used="none",
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

        # Fallback path if llm_provider is not explicitly mapped
        groq_error = ""
        if settings.groq_api_key:
            try:
                return await self._generate_groq(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                groq_error = str(exc)
                logger.warning("Groq failed, falling back to Gemini: %s", groq_error)

        if settings.google_api_key:
            try:
                return await self._generate_gemini(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.error("Gemini also failed: %s", exc)
                if groq_error:
                    raise RuntimeError(f"Groq failed: {groq_error}; Gemini failed: {exc}") from exc
                raise

        warning = (
            "⚠️ No LLM provider available. Please configure GROQ_API_KEY or GOOGLE_API_KEY in your .env file."
        )
        return LLMResponse(
            text=warning,
            provider="none",
            model_used="unconfigured",
            token_usage=self._estimate_token_usage(messages, warning),
        )

    async def generate_stream(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
        system_prompt: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Compatibility streaming wrapper over the finalized response."""
        response = await self.generate_with_metadata(
            user_message,
            context=context,
            chat_history=chat_history,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.text
        if not text:
            return
        chunk_size = max(settings.chat_stream_chunk_size, 1)
        for start in range(0, len(text), chunk_size):
            yield text[start : start + chunk_size]

    async def stream_with_metadata(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """True token-level streaming. Yields text deltas as they arrive."""
        messages = self._build_messages(
            user_message, context, chat_history, system_prompt=system_prompt
        )
        provider = settings.llm_provider.lower()
        if provider == "groq":
            async for delta in self._stream_groq(messages):
                yield delta
        elif provider == "gemini":
            async for delta in self._stream_gemini(messages):
                yield delta
        else:
            # Fallback for providers that don't support streaming:
            # generate full response and yield in small chunks
            response = await self.generate_with_metadata(
                user_message, context, chat_history, system_prompt
            )
            chunk_size = 40
            for i in range(0, len(response.text), chunk_size):
                yield response.text[i:i + chunk_size]
                await asyncio.sleep(0)

    async def _stream_groq(
        self, messages: list[dict]
    ) -> AsyncGenerator[str, None]:
        client = await self._get_groq_client()
        payload = {
            "model": settings.groq_model,
            "messages": messages,
            "max_tokens": settings.llm_max_tokens,
            "temperature": settings.llm_temperature,
            "stream": True,
        }
        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def _stream_gemini(
        self, messages: list[dict]
    ) -> AsyncGenerator[str, None]:
        client = await self._get_gemini_client()
        # Convert OpenAI-style messages to Gemini format
        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            elif m["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": settings.llm_max_tokens,
                "temperature": settings.llm_temperature,
            },
        }
        model = settings.gemini_model
        url = f"/models/{model}:streamGenerateContent?alt=sse"
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                    text = (
                        chunk.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def generate(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
        system_prompt: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Non-streaming full response."""
        response = await self.generate_with_metadata(
            user_message,
            context=context,
            chat_history=chat_history,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.text

    async def _generate_groq(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = await self._get_groq_client()
        payload = {
            "model": settings.groq_model,
            "messages": messages,
            "stream": False,
            "temperature": 0.3 if temperature is None else temperature,
            "max_tokens": 2048 if max_tokens is None else max_tokens,
        }
        started = time.perf_counter()
        max_attempts = 3
        backoff_delay = 1.0
        for attempt in range(max_attempts):
            try:
                with trace_operation(
                    "llm.generate",
                    component="llm",
                    logger_=logger,
                    provider="groq",
                    model=settings.groq_model,
                ):
                    response = await client.post("/chat/completions", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                    usage = data.get("usage") or {}
                    token_usage = {
                        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or 0),
                        "total_tokens": int(usage.get("total_tokens") or 0),
                    }
                    if token_usage["total_tokens"] == 0:
                        token_usage = self._estimate_token_usage(messages, text)
                observe_llm_call("groq", time.perf_counter() - started, success=True)
                observe_llm_latency((time.perf_counter() - started) * 1000)
                record_token_usage(
                    token_usage.get("prompt_tokens") or 0,
                    token_usage.get("completion_tokens") or 0,
                    model=settings.groq_model,
                )
                return LLMResponse(
                    text=text,
                    provider="groq",
                    model_used=settings.groq_model,
                    token_usage=token_usage,
                )
            except Exception as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("groq", time.perf_counter() - started, success=False)
                    record_provider_error()
                    from app.core.logging_config import redact_secrets
                    cleaned_msg = redact_secrets(str(exc))
                    raise RuntimeError(cleaned_msg) from exc
                logger.warning(
                    "Groq API call failed (attempt %d/%d): %s. Retrying in %fs...",
                    attempt + 1,
                    max_attempts,
                    exc,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
        raise RuntimeError("Groq generation exhausted retries without returning a response.")

    async def _generate_gemini(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = await self._get_gemini_client()
        prompt = self._flatten_messages(messages)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3 if temperature is None else temperature,
                "maxOutputTokens": 2048 if max_tokens is None else max_tokens,
            },
        }
        url = f"/models/{settings.gemini_model}:generateContent"
        started = time.perf_counter()
        max_attempts = 3
        backoff_delay = 1.0
        for attempt in range(max_attempts):
            try:
                with trace_operation(
                    "llm.generate",
                    component="llm",
                    logger_=logger,
                    provider="gemini",
                    model=settings.gemini_model,
                ):
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise ValueError("No response from Gemini")
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = "".join(part.get("text", "") for part in parts)
                    usage = data.get("usageMetadata") or {}
                    token_usage = {
                        "prompt_tokens": int(usage.get("promptTokenCount") or 0),
                        "completion_tokens": int(usage.get("candidatesTokenCount") or 0),
                        "total_tokens": int(usage.get("totalTokenCount") or 0),
                    }
                    if token_usage["total_tokens"] == 0:
                        token_usage = self._estimate_token_usage(messages, text)
                observe_llm_call("gemini", time.perf_counter() - started, success=True)
                observe_llm_latency((time.perf_counter() - started) * 1000)
                record_token_usage(
                    token_usage.get("prompt_tokens") or 0,
                    token_usage.get("completion_tokens") or 0,
                    model=settings.gemini_model,
                )
                return LLMResponse(
                    text=text,
                    provider="gemini",
                    model_used=settings.gemini_model,
                    token_usage=token_usage,
                )
            except Exception as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("gemini", time.perf_counter() - started, success=False)
                    record_provider_error()
                    from app.core.logging_config import redact_secrets
                    cleaned_msg = redact_secrets(str(exc))
                    raise RuntimeError(cleaned_msg) from exc
                logger.warning(
                    "Gemini API call failed (attempt %d/%d): %s. Retrying in %fs...",
                    attempt + 1,
                    max_attempts,
                    exc,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
        raise RuntimeError("Gemini generation exhausted retries without returning a response.")

    async def _generate_ollama(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        started = time.perf_counter()
        url = f"{settings.ollama_url}/api/chat"
        max_attempts = 3
        backoff_delay = 1.0
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=settings.local_llm_timeout) as client:
                    payload = {
                        "model": settings.local_llm_model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.3 if temperature is None else temperature,
                        }
                    }
                    if max_tokens is not None:
                        payload["options"]["num_predict"] = max_tokens
                    
                    with trace_operation(
                        "llm.generate",
                        component="llm",
                        logger_=logger,
                        provider="ollama",
                        model=settings.local_llm_model,
                    ):
                        response = await client.post(url, json=payload)
                        if response.status_code == 404:
                            try:
                                err_data = response.json()
                                err_msg = err_data.get("error", "")
                            except Exception:
                                err_msg = ""
                            raise RuntimeError(
                                f"Ollama model '{settings.local_llm_model}' not found or endpoint not found. "
                                f"Please run 'ollama pull {settings.local_llm_model}' or verify settings. "
                                f"Details: {err_msg or response.text}"
                            )
                        response.raise_for_status()
                        data = response.json()
                        text = data.get("message", {}).get("content", "") or ""
                        token_usage = {
                            "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                            "completion_tokens": int(data.get("eval_count") or 0),
                            "total_tokens": int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0)
                        }
                        if token_usage["total_tokens"] == 0:
                            token_usage = self._estimate_token_usage(messages, text)
                observe_llm_call("ollama", time.perf_counter() - started, success=True)
                observe_llm_latency((time.perf_counter() - started) * 1000)
                record_token_usage(
                    token_usage.get("prompt_tokens") or 0,
                    token_usage.get("completion_tokens") or 0,
                    model=settings.local_llm_model,
                )
                return LLMResponse(
                    text=text,
                    provider="ollama",
                    model_used=settings.local_llm_model,
                    token_usage=token_usage,
                )
            except httpx.ConnectError as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("ollama", time.perf_counter() - started, success=False)
                    record_provider_error()
                    raise RuntimeError(
                        f"Could not connect to Ollama server at '{settings.ollama_url}'. "
                        "Is Ollama running? Start it via 'ollama serve' and try again."
                    ) from exc
                logger.warning("Ollama connection failed (attempt %d/%d). Retrying in %fs...", attempt + 1, max_attempts, backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
            except Exception as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("ollama", time.perf_counter() - started, success=False)
                    record_provider_error()
                    from app.core.logging_config import redact_secrets
                    cleaned_msg = redact_secrets(str(exc))
                    raise RuntimeError(cleaned_msg) from exc
                logger.warning("Ollama failed (attempt %d/%d): %s. Retrying in %fs...", attempt + 1, max_attempts, exc, backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
        raise RuntimeError("Ollama generation exhausted retries without returning a response.")

    async def _generate_llama_cpp(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        started = time.perf_counter()
        url = f"{settings.llama_cpp_url}/v1/chat/completions"
        max_attempts = 3
        backoff_delay = 1.0
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=settings.local_llm_timeout) as client:
                    payload = {
                        "model": settings.local_llm_model,
                        "messages": messages,
                        "stream": False,
                        "temperature": 0.3 if temperature is None else temperature,
                    }
                    if max_tokens is not None:
                        payload["max_tokens"] = max_tokens
                    
                    with trace_operation(
                        "llm.generate",
                        component="llm",
                        logger_=logger,
                        provider="llama_cpp",
                        model=settings.local_llm_model,
                    ):
                        response = await client.post(url, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        text = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                        usage = data.get("usage") or {}
                        token_usage = {
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                        }
                        if token_usage["total_tokens"] == 0:
                            token_usage = self._estimate_token_usage(messages, text)
                observe_llm_call("llama_cpp", time.perf_counter() - started, success=True)
                observe_llm_latency((time.perf_counter() - started) * 1000)
                record_token_usage(
                    token_usage.get("prompt_tokens") or 0,
                    token_usage.get("completion_tokens") or 0,
                    model=settings.local_llm_model,
                )
                return LLMResponse(
                    text=text,
                    provider="llama_cpp",
                    model_used=settings.local_llm_model,
                    token_usage=token_usage,
                )
            except httpx.ConnectError as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("llama_cpp", time.perf_counter() - started, success=False)
                    record_provider_error()
                    raise RuntimeError(
                        f"Could not connect to llama.cpp server at '{settings.llama_cpp_url}'. "
                        "Is llama.cpp running? Verify your server setup and try again."
                    ) from exc
                logger.warning("llama.cpp connection failed (attempt %d/%d). Retrying in %fs...", attempt + 1, max_attempts, backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
            except Exception as exc:
                if attempt == max_attempts - 1:
                    observe_llm_call("llama_cpp", time.perf_counter() - started, success=False)
                    record_provider_error()
                    from app.core.logging_config import redact_secrets
                    cleaned_msg = redact_secrets(str(exc))
                    raise RuntimeError(cleaned_msg) from exc
                logger.warning("llama.cpp failed (attempt %d/%d): %s. Retrying in %fs...", attempt + 1, max_attempts, exc, backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0
        raise RuntimeError("llama.cpp generation exhausted retries without returning a response.")

    async def _generate_local_hf(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise RuntimeError(
            "Local Hugging Face (local_hf) provider is not implemented. "
            "To run models locally, please use the 'ollama' or 'llama_cpp' providers. "
            "See docs/LOCAL_LLM.md for setup instructions."
        )


    def _build_messages(
        self,
        user_message: str,
        context: str,
        chat_history: list[dict] | None,
        *,
        system_prompt: str | None = None,
    ) -> list[dict]:
        resolved_system_prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt
        messages = [{"role": "system", "content": resolved_system_prompt}]

        if chat_history:
            messages.extend(chat_history[-settings.chat_history_message_limit :])

        augmented_message = user_message
        if context:
            augmented_message = (
                f"Context from grounded evidence:\n\n{context}\n\n"
                f"---\n\nUser question: {user_message}"
            )

        messages.append({"role": "user", "content": augmented_message})
        return messages

    @staticmethod
    def _flatten_messages(messages: list[dict]) -> str:
        lines = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = str(message.get("content", ""))
            lines.append(f"{role}:\n{content}")
        return "\n\n".join(lines)

    @staticmethod
    def _estimate_token_usage(messages: list[dict], answer: str) -> dict[str, int]:
        prompt_text = "\n".join(str(item.get("content", "")) for item in messages)
        prompt_tokens = LLMService.estimate_text_tokens(prompt_text)
        completion_tokens = LLMService.estimate_text_tokens(answer)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        return max(1, int(len(text.split()) * 1.3)) if text.strip() else 0

    async def close(self):
        """Cleanup HTTP clients."""
        if self._groq_client:
            await self._groq_client.aclose()
        if self._gemini_client:
            await self._gemini_client.aclose()

    async def health_check(self, timeout_seconds: float = 5.0) -> dict:
        """Lightweight provider health probe with a short timeout."""
        provider = settings.llm_provider.lower()
        try:
            if provider == "groq":
                if not settings.groq_api_key:
                    return {"status": "not_configured", "provider": "groq"}
                client = await self._get_groq_client()
                response = await client.get("/models", timeout=timeout_seconds)
                response.raise_for_status()
                return {"status": "healthy", "provider": "groq"}

            if provider == "gemini":
                if not settings.google_api_key:
                    return {"status": "not_configured", "provider": "gemini"}
                client = await self._get_gemini_client()
                response = await client.get(
                    "/models",
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                return {"status": "healthy", "provider": "gemini"}

            if provider == "retrieval-only":
                return {"status": "healthy", "provider": "retrieval-only", "info": "LLM generation bypassed"}

            if provider == "ollama":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(settings.ollama_url, timeout=timeout_seconds)
                    if resp.status_code in {200, 404}:
                        return {"status": "healthy", "provider": "ollama"}
                return {"status": "unhealthy", "provider": "ollama", "error": "Connection failed"}

            if provider == "llama_cpp":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{settings.llama_cpp_url}/v1/models", timeout=timeout_seconds)
                    if resp.status_code == 200:
                        return {"status": "healthy", "provider": "llama_cpp"}
                return {"status": "unhealthy", "provider": "llama_cpp", "error": "Connection failed"}

            if provider == "local_hf":
                return {"status": "healthy", "provider": "local_hf", "info": "Local HF simulation mode"}

            return {"status": "unhealthy", "provider": provider, "error": f"Unknown provider: {provider}"}
        except Exception as exc:
            return {"status": "unhealthy", "provider": provider, "error": str(exc)}



# Module-level singleton
llm_service = LLMService()
