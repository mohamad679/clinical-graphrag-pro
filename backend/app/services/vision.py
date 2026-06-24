"""
Vision-Language Model (VLM) service.
Analyzes medical images using Gemini (primary) or Claude fallback.
Returns structured findings, recommendations, and annotation suggestions.
"""

import base64
import asyncio
import json
import logging
from datetime import datetime, timezone
from io import BytesIO

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
GEMINI_RATE_LIMIT_RETRY_DELAYS = (8.0, 20.0)
GEMINI_TRANSPORT_RETRY_DELAYS = (3.0, 8.0)
GEMINI_VISION_MAX_DIMENSION = 1280
GEMINI_VISION_MAX_BYTES = 1_500_000
GEMINI_VISION_FALLBACK_MODELS = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)

# ── Medical image analysis prompt ────────────────────────

MEDICAL_IMAGE_PROMPT = """You are an expert medical image analyst AI.
Analyze the provided medical image and return a structured JSON response.

IMPORTANT RULES:
1. Only describe what you can actually observe in the image.
2. Never fabricate findings.
3. Provide confidence scores (0-1) for each finding.
4. Suggest bounding box regions for notable findings (normalized 0-1 coordinates).
5. Use precise medical terminology.

Return your analysis as valid JSON with this exact structure:
{
  "summary": "Brief 1-2 sentence overview of the image",
  "modality_detected": "X-ray | CT | MRI | Ultrasound | Pathology | Other",
  "body_part_detected": "e.g., Chest | Brain | Knee | Abdomen",
  "findings": [
    {
      "description": "Clear description of the finding",
      "location": "Anatomical location",
      "severity": "normal | mild | moderate | severe",
      "confidence": 0.85,
      "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    }
  ],
  "recommendations": [
    "Recommendation string 1",
    "Recommendation string 2"
  ],
  "differential_diagnosis": [
    {"condition": "Condition name", "probability": 0.7}
  ]
}

ONLY return the JSON object. No markdown, no explanation outside the JSON."""

MULTIMODAL_CHAT_PROMPT = """You are Clinical GraphRAG Pro, an advanced medical AI assistant.
The user has shared a medical image along with their question.
Analyze the image in the context of their question and any provided document context.

RULES:
1. Describe relevant findings in the image.
2. Relate findings to the user's question and any document context.
3. Use precise medical terminology but explain complex terms.
4. Cite sources from documents when available.
5. Never fabricate findings.
6. Format the answer in clean Markdown with short sections such as "Summary", "Visual Findings", "Clinical Context", "Recommendations", and "Limitations" when helpful.
7. Use Markdown tables for multiple findings or comparisons, and use **bold** for key labels or clinically important terms.
8. Keep paragraphs short and do not wrap the full answer in a code block.
"""


class VisionService:
    """Analyzes medical images using vision-language models."""

    def __init__(self):
        self._gemini_client: httpx.AsyncClient | None = None

    async def _get_gemini_client(self) -> httpx.AsyncClient:
        if self._gemini_client is None:
            self._gemini_client = httpx.AsyncClient(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                timeout=httpx.Timeout(connect=15.0, read=180.0, write=45.0, pool=15.0),
            )
        return self._gemini_client

    async def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/png",
        additional_context: str = "",
    ) -> dict:
        """
        Full structured analysis of a medical image.
        Returns parsed JSON with findings, recommendations, etc.
        """
        capability = self.get_analysis_capability()
        if not capability["available"]:
            return {
                "error": capability["reason"],
                "findings": [],
                "recommendations": [],
                "summary": "Image analysis is unavailable on this deployment.",
            }

        prompt = MEDICAL_IMAGE_PROMPT
        if additional_context:
            prompt += f"\n\nAdditional context from documents:\n{additional_context}"

        try:
            result, model_used = await self._call_gemini_vision(image_data, mime_type, prompt)
            parsed = self._parse_analysis_result(result)
            parsed["model_used"] = model_used
            parsed["review_status"] = "ai_generated"
            parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
            return parsed
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            friendly_error = self._friendly_error_message(e)
            return {
                "error": friendly_error,
                "findings": [],
                "recommendations": [],
                "summary": "Analysis failed",
                "review_status": "failed",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    async def analyze_with_question(
        self,
        image_data: bytes,
        mime_type: str,
        user_question: str,
        document_context: str = "",
    ) -> str:
        """
        Chat-style analysis: user asks a question about an image.
        Returns free-text markdown response (not structured JSON).
        """
        capability = self.get_analysis_capability()
        if not capability["available"]:
            return f"⚠️ {capability['reason']}"

        prompt = MULTIMODAL_CHAT_PROMPT + f"\n\nUser question: {user_question}"
        if document_context:
            prompt += f"\n\nRelevant document context:\n{document_context}"

        try:
            response_text, _model_used = await self._call_gemini_vision(image_data, mime_type, prompt)
            return response_text
        except Exception as e:
            logger.error(f"Multimodal chat failed: {e}")
            return f"⚠️ {self._friendly_error_message(e)}"

    async def _call_gemini_vision(
        self,
        image_data: bytes,
        mime_type: str,
        prompt: str,
    ) -> tuple[str, str]:
        """Send image + prompt to Gemini and return the text response."""
        prepared_image, prepared_mime_type = self._prepare_image_for_gemini(image_data, mime_type)
        b64_image = base64.b64encode(prepared_image).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": prepared_mime_type,
                                "data": b64_image,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        }

        models = self._vision_model_candidates()
        last_response: httpx.Response | None = None
        retryable_statuses = {404, 410, 429, 500, 502, 503, 504}
        for model_index, model_name in enumerate(models):
            response = await self._post_gemini_vision(model_name, payload)
            last_response = response
            if response.status_code in retryable_statuses and model_index < len(models) - 1:
                logger.warning(
                    "Gemini vision model %s returned HTTP %s; trying fallback model %s",
                    model_name,
                    response.status_code,
                    models[model_index + 1],
                )
                continue
            response.raise_for_status()

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("No response from Gemini vision model")

            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts), model_name

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("No response from Gemini vision model")

    async def _post_gemini_vision(self, model_name: str, payload: dict) -> httpx.Response:
        url = f"/models/{model_name}:generateContent?key={settings.google_api_key}"
        response: httpx.Response | None = None
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=45.0, pool=15.0)
        transport_attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    base_url="https://generativelanguage.googleapis.com/v1beta",
                    timeout=timeout,
                ) as client:
                    for attempt in range(len(GEMINI_RATE_LIMIT_RETRY_DELAYS) + 1):
                        response = await client.post(url, json=payload)
                        if response.status_code != 429 or attempt == len(GEMINI_RATE_LIMIT_RETRY_DELAYS):
                            break

                        retry_after = self._retry_after_seconds(response)
                        delay = retry_after if retry_after is not None else GEMINI_RATE_LIMIT_RETRY_DELAYS[attempt]
                        logger.warning(
                            "Gemini vision rate limit reached; retrying after %.1f seconds",
                            delay,
                        )
                        await asyncio.sleep(delay)
                break
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if transport_attempt >= len(GEMINI_TRANSPORT_RETRY_DELAYS):
                    raise
                delay = GEMINI_TRANSPORT_RETRY_DELAYS[transport_attempt]
                transport_attempt += 1
                logger.warning(
                    "Gemini vision transport failure; retrying after %.1f seconds: %s",
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

        if response is None:  # pragma: no cover - defensive guard
            raise RuntimeError("No response from Gemini vision model")
        return response

    @staticmethod
    def _vision_model_candidates() -> list[str]:
        candidates = [settings.gemini_model, *GEMINI_VISION_FALLBACK_MODELS]
        deduped: list[str] = []
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @staticmethod
    def _prepare_image_for_gemini(image_data: bytes, mime_type: str) -> tuple[bytes, str]:
        """Bound Gemini payload size to avoid HF/Gemini transport closures."""
        normalized_mime_type = mime_type.lower()

        try:
            from PIL import Image, ImageOps

            with Image.open(BytesIO(image_data)) as image:
                image = ImageOps.exif_transpose(image)
                if (
                    len(image_data) <= GEMINI_VISION_MAX_BYTES
                    and max(image.size) <= GEMINI_VISION_MAX_DIMENSION
                    and normalized_mime_type in {"image/jpeg", "image/png", "image/webp"}
                ):
                    return image_data, mime_type

                if image.mode not in {"RGB", "L"}:
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    if "A" in image.getbands():
                        background.paste(image, mask=image.getchannel("A"))
                    else:
                        background.paste(image)
                    image = background
                elif image.mode == "L":
                    image = image.convert("RGB")

                image.thumbnail(
                    (GEMINI_VISION_MAX_DIMENSION, GEMINI_VISION_MAX_DIMENSION),
                    Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                image.save(output, "JPEG", quality=82, optimize=True, progressive=True)
                prepared = output.getvalue()
                logger.info(
                    "Prepared image for Gemini vision: original=%d bytes prepared=%d bytes size=%sx%s",
                    len(image_data),
                    len(prepared),
                    image.width,
                    image.height,
                )
                return prepared, "image/jpeg"
        except Exception as exc:
            logger.warning("Failed to prepare image for Gemini; using original payload: %s", exc)
            return image_data, mime_type

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        if not value:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        if seconds <= 0:
            return None
        return min(seconds, 45.0)

    def _parse_analysis_result(self, raw_text: str) -> dict:
        """Parse the VLM's JSON output, handling markdown code fences."""
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse VLM output as JSON, returning raw text")
            return {
                "summary": raw_text[:500],
                "findings": [],
                "recommendations": [],
                "parse_error": True,
            }

    def _friendly_error_message(self, error: Exception) -> str:
        raw = str(error)
        lowered = raw.lower()
        transport_markers = (
            "tcptransport",
            "handler is closed",
            "connection closed",
            "remote protocol",
            "readerror",
            "connecterror",
            "timeout",
        )
        if isinstance(error, httpx.TimeoutException):
            return "The vision provider did not respond before the request timeout. Try a smaller image or try again."
        if any(marker in lowered for marker in transport_markers):
            return (
                "The vision model connection closed before analysis completed. "
                "The app has retried the request; try again with the optimized image pipeline."
            )
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status in {401, 403}:
                return "The vision provider rejected the request. Check the configured API key and permissions."
            if status == 429:
                return (
                    "Gemini quota is exhausted for this Google project. "
                    "The app tried the configured model and fallback Flash models; wait for quota reset or use a key from a billed project."
                )
            if status >= 500:
                return "The vision provider is temporarily unavailable. Try analysis again."
        return "Image analysis failed. Try again or verify the configured vision provider."

    def extract_annotations_from_analysis(self, analysis: dict) -> list[dict]:
        """
        Convert analysis findings with bboxes into annotation objects
        suitable for the ImageAnnotation model.
        """
        annotations = []
        for finding in analysis.get("findings", []):
            bbox = finding.get("bbox")
            if not bbox:
                continue

            annotations.append({
                "annotation_type": "bbox",
                "label": finding.get("description", "Finding")[:200],
                "description": finding.get("location", ""),
                "confidence": finding.get("confidence"),
                "color": self._severity_color(finding.get("severity", "normal")),
                "geometry": bbox,
                "source": "ai",
            })

        return annotations

    def _severity_color(self, severity: str) -> str:
        """Map severity to a display color."""
        return {
            "normal": "#10b981",    # green
            "mild": "#f59e0b",      # amber
            "moderate": "#f97316",  # orange
            "severe": "#ef4444",    # red
        }.get(severity, "#6366f1")

    def get_analysis_capability(self) -> dict[str, str | bool]:
        if settings.llm_provider.lower() == "retrieval-only":
            return {
                "available": False,
                "provider": "retrieval-only",
                "reason": "Image analysis is disabled in retrieval-only local mode.",
            }

        if settings.google_api_key:
            return {
                "available": True,
                "provider": "gemini",
                "reason": "",
            }

        return {
            "available": False,
            "provider": "gemini",
            "reason": "Image analysis is not configured on this deployment. Set GOOGLE_API_KEY to enable vision analysis.",
        }

    async def close(self):
        if self._gemini_client:
            await self._gemini_client.aclose()


# Module-level singleton
vision_service = VisionService()
