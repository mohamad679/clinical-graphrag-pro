"""
LLM client service — Groq (primary) with Gemini fallback.
Supports both streaming and non-streaming generation.
"""

import json
import logging
from typing import AsyncGenerator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── System prompt for the medical assistant ──────────────

SYSTEM_PROMPT = """You are Clinical GraphRAG Pro, an advanced medical AI assistant.

RULES:
1. Answer ONLY based on the provided context from medical documents.
2. If the context doesn't contain enough information, say so clearly.
3. Always cite your sources by referencing the document name and chunk.
4. Use precise medical terminology but explain complex terms.
5. Structure your answers with clear sections.
6. Provide reasoning steps for complex medical questions.
7. Never fabricate medical information.

FORMAT:
- Use markdown formatting for readability.
- Put key findings in **bold**.
- Use bullet lists for multiple points.
"""


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
                timeout=60.0,
            )
        return self._gemini_client

    async def generate_stream(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from the LLM. Falls back to Gemini if Groq fails."""
        messages = self._build_messages(user_message, context, chat_history)

        groq_error = ""
        if settings.groq_api_key:
            try:
                async for token in self._stream_groq(messages):
                    yield token
                return
            except Exception as e:
                groq_error = str(e)
                logger.warning(f"Groq failed, falling back to Gemini: {groq_error}")

        if settings.google_api_key:
            try:
                async for token in self._stream_gemini(user_message, context):
                    yield token
                return
            except Exception as e:
                logger.error(f"Gemini also failed: {e}")

        # If we had a Groq key but it failed, it's likely a rate limit
        if groq_error and settings.groq_api_key:
            if "429" in groq_error or "rate limit" in groq_error.lower():
                yield f"⚠️ Groq Free Tier Rate Limit Exceeded (Too many tokens per minute). Please wait 60 seconds and try again!"
            else:
                yield f"⚠️ Groq API Error: {groq_error}"
        else:
            yield "⚠️ No LLM provider available. Please configure GROQ_API_KEY or GOOGLE_API_KEY in your .env file."

    async def generate(
        self,
        user_message: str,
        context: str = "",
        chat_history: list[dict] | None = None,
    ) -> str:
        """Non-streaming full response."""
        tokens = []
        async for token in self.generate_stream(user_message, context, chat_history):
            tokens.append(token)
        return "".join(tokens)

    # ── Private: Groq ────────────────────────────────────

    async def _stream_groq(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        client = await self._get_groq_client()
        payload = {
            "model": settings.groq_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.3,
            "max_tokens": 2048,
        }

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    # ── Private: Gemini ──────────────────────────────────

    async def _stream_gemini(
        self, user_message: str, context: str
    ) -> AsyncGenerator[str, None]:
        client = await self._get_gemini_client()

        prompt = f"""Context from medical documents:\n{context}\n\nUser question: {user_message}"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
            },
        }

        url = f"/models/{settings.gemini_model}:streamGenerateContent?key={settings.google_api_key}&alt=sse"

        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                    parts = chunk.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    # ── Private: Helpers ─────────────────────────────────

    def _build_messages(
        self,
        user_message: str,
        context: str,
        chat_history: list[dict] | None,
    ) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if chat_history:
            messages.extend(chat_history[-10:])  # last 10 messages

        augmented_message = user_message
        if context:
            augmented_message = (
                f"Context from medical documents:\n\n{context}\n\n"
                f"---\n\nUser question: {user_message}"
            )

        messages.append({"role": "user", "content": augmented_message})
        return messages

    async def close(self):
        """Cleanup HTTP clients."""
        if self._groq_client:
            await self._groq_client.aclose()
        if self._gemini_client:
            await self._gemini_client.aclose()


# Module-level singleton
llm_service = LLMService()
