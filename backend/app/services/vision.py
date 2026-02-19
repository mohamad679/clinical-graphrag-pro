"""
Vision-Language Model (VLM) service.
Analyzes medical images using Gemini (primary) or Claude fallback.
Returns structured findings, recommendations, and annotation suggestions.
"""

import base64
import json
import logging
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

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
"""


class VisionService:
    """Analyzes medical images using vision-language models."""

    def __init__(self):
        self._gemini_client: httpx.AsyncClient | None = None

    async def _get_gemini_client(self) -> httpx.AsyncClient:
        if self._gemini_client is None:
            self._gemini_client = httpx.AsyncClient(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                timeout=120.0,  # vision takes longer
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
        if not settings.google_api_key:
            return {
                "error": "No Google API key configured. Set GOOGLE_API_KEY in .env",
                "findings": [],
                "recommendations": [],
            }

        prompt = MEDICAL_IMAGE_PROMPT
        if additional_context:
            prompt += f"\n\nAdditional context from documents:\n{additional_context}"

        try:
            result = await self._call_gemini_vision(image_data, mime_type, prompt)
            parsed = self._parse_analysis_result(result)
            parsed["model_used"] = settings.gemini_model
            return parsed
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return {
                "error": str(e),
                "findings": [],
                "recommendations": [],
                "summary": "Analysis failed",
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
        if not settings.google_api_key:
            return "⚠️ No Google API key configured. Set GOOGLE_API_KEY in .env."

        prompt = MULTIMODAL_CHAT_PROMPT + f"\n\nUser question: {user_question}"
        if document_context:
            prompt += f"\n\nRelevant document context:\n{document_context}"

        try:
            return await self._call_gemini_vision(image_data, mime_type, prompt)
        except Exception as e:
            logger.error(f"Multimodal chat failed: {e}")
            return f"⚠️ Image analysis error: {e}"

    async def _call_gemini_vision(
        self,
        image_data: bytes,
        mime_type: str,
        prompt: str,
    ) -> str:
        """Send image + prompt to Gemini and return the text response."""
        client = await self._get_gemini_client()

        # Base64-encode the image
        b64_image = base64.b64encode(image_data).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
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

        url = f"/models/{settings.gemini_model}:generateContent?key={settings.google_api_key}"
        response = await client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No response from Gemini vision model")

        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def _parse_analysis_result(self, raw_text: str) -> dict:
        """Parse the VLM's JSON output, handling markdown code fences."""
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse VLM output as JSON, returning raw text")
            return {
                "summary": raw_text[:500],
                "findings": [],
                "recommendations": [],
                "parse_error": True,
            }

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

    async def close(self):
        if self._gemini_client:
            await self._gemini_client.aclose()


# Module-level singleton
vision_service = VisionService()
