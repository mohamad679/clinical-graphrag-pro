"""
Audio upload validation, storage, and background transcription helpers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.persistence import AudioTranscript
from app.services.job_state import job_state_service
from app.services.storage import storage_service

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".webm", ".m4a", ".mp4"}


@dataclass(slots=True)
class ValidatedAudioUpload:
    normalized_filename: str
    detected_kind: str
    extension: str
    mime_type: str
    duration_seconds: float | None
    validation_metadata: dict[str, Any]


class AudioProcessingService:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.groq.com/openai/v1",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                timeout=settings.audio_transcription_timeout_seconds,
            )
        return self._client

    def validate_audio_upload(
        self,
        filename: str,
        claimed_content_type: str,
        content: bytes,
    ) -> ValidatedAudioUpload:
        normalized_filename = Path(filename).name or "recording.webm"
        extension = Path(normalized_filename).suffix.lower()
        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio type: {extension}. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
            )

        max_size_bytes = settings.audio_max_upload_size_mb * 1024 * 1024
        if len(content) > max_size_bytes:
            raise ValueError(
                f"Audio file too large: {len(content) / (1024 * 1024):.1f}MB. "
                f"Max: {settings.audio_max_upload_size_mb}MB"
            )

        detected_kind = self._detect_kind(content)
        if detected_kind is None:
            raise ValueError("Unable to verify audio file signature from magic bytes.")

        if extension not in self._allowed_extensions_for_kind(detected_kind):
            raise ValueError(
                f"File extension {extension} does not match detected audio type {detected_kind}."
            )

        duration_seconds = self._duration_seconds(content, detected_kind)
        if duration_seconds is not None and duration_seconds > settings.audio_max_duration_seconds:
            raise ValueError(
                f"Audio duration {duration_seconds:.1f}s exceeds the limit of "
                f"{settings.audio_max_duration_seconds}s."
            )

        return ValidatedAudioUpload(
            normalized_filename=normalized_filename,
            detected_kind=detected_kind,
            extension=extension,
            mime_type=self._mime_for_kind(detected_kind),
            duration_seconds=duration_seconds,
            validation_metadata={
                "magic_bytes_checked": True,
                "claimed_content_type": claimed_content_type,
                "detected_kind": detected_kind,
                "duration_seconds": duration_seconds,
                "duration_validation": "exact" if duration_seconds is not None else "unavailable",
            },
        )

    async def store_audio_upload(
        self,
        *,
        content: bytes,
        validated: ValidatedAudioUpload,
    ):
        return await storage_service.store_bytes(
            category="audio",
            filename=validated.normalized_filename,
            content=content,
            content_type=validated.mime_type,
        )

    async def transcribe_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured for audio transcription.")

        client = await self._get_client()
        data: dict[str, Any] = {
            "model": "whisper-large-v3",
            "response_format": "verbose_json",
        }
        if not settings.audio_allow_auto_language_detection and settings.audio_default_language:
            data["language"] = settings.audio_default_language

        files = {"file": (filename, content, mime_type)}
        response = await client.post("/audio/transcriptions", data=data, files=files)
        response.raise_for_status()
        payload = response.json()
        return {
            "text": (payload.get("text") or "").strip(),
            "language": payload.get("language") or settings.audio_default_language or None,
            "provider": "groq",
            "model": "whisper-large-v3",
            "raw_response": payload,
        }

    def _detect_kind(self, content: bytes) -> str | None:
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            return "wav"
        if content.startswith(b"OggS"):
            return "ogg"
        if content.startswith(b"\x1A\x45\xDF\xA3"):
            return "webm"
        if content.startswith(b"ID3") or (len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0):
            return "mp3"
        if len(content) >= 12 and content[4:8] == b"ftyp":
            brand = content[8:12]
            if brand in {b"M4A ", b"isom", b"mp42", b"mp41"}:
                return "m4a"
        return None

    def _allowed_extensions_for_kind(self, kind: str) -> set[str]:
        return {
            "wav": {".wav"},
            "ogg": {".ogg"},
            "webm": {".webm"},
            "mp3": {".mp3"},
            "m4a": {".m4a", ".mp4"},
        }[kind]

    def _mime_for_kind(self, kind: str) -> str:
        return {
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "webm": "audio/webm",
            "mp3": "audio/mpeg",
            "m4a": "audio/mp4",
        }[kind]

    def _duration_seconds(self, content: bytes, kind: str) -> float | None:
        if kind != "wav" or len(content) < 44:
            return None

        if content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            return None

        offset = 12
        byte_rate = None
        data_size = None
        while offset + 8 <= len(content):
            chunk_id = content[offset:offset + 4]
            chunk_size = int.from_bytes(content[offset + 4:offset + 8], "little")
            chunk_start = offset + 8
            chunk_end = chunk_start + chunk_size
            if chunk_end > len(content):
                break
            if chunk_id == b"fmt " and chunk_size >= 16:
                byte_rate = int.from_bytes(content[chunk_start + 8:chunk_start + 12], "little")
            elif chunk_id == b"data":
                data_size = chunk_size
            offset = chunk_end + (chunk_size % 2)

        if not byte_rate or not data_size:
            return None
        return round(data_size / byte_rate, 3)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def process_audio_transcription_async(transcript_id: str) -> dict[str, Any]:
    transcript_uuid = UUID(str(transcript_id))
    async with async_session_factory() as session:
        result = await session.execute(
            select(AudioTranscript)
            .options(selectinload(AudioTranscript.storage_asset))
            .where(AudioTranscript.id == transcript_uuid)
        )
        transcript = result.scalar_one_or_none()
        if transcript is None:
            raise ValueError(f"Audio transcript {transcript_id} not found")

        transcript.status = "processing"
        transcript.error_message = None
        if transcript.transcription_job_id:
            await job_state_service.update_job(
                session,
                transcript.transcription_job_id,
                progress=10,
                metadata={"transcript_status": "processing"},
            )
        await session.commit()

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(AudioTranscript)
                .options(selectinload(AudioTranscript.storage_asset))
                .where(AudioTranscript.id == transcript_uuid)
            )
            transcript = result.scalar_one_or_none()
            if transcript is None or transcript.storage_asset is None:
                raise ValueError(f"Audio transcript {transcript_id} is missing its stored asset")
            content = await storage_service.read_bytes(
                bucket=transcript.storage_asset.bucket,
                object_key=transcript.storage_asset.object_key,
                storage_metadata=transcript.storage_asset.storage_metadata,
            )
            provider_result = await audio_processing_service.transcribe_bytes(
                filename=transcript.original_filename,
                content=content,
                mime_type=transcript.mime_type,
            )

        async with async_session_factory() as session:
            transcript = await session.get(AudioTranscript, transcript_uuid)
            if transcript is None:
                raise ValueError(f"Audio transcript {transcript_id} not found")
            transcript.status = "completed"
            transcript.transcript_text = provider_result["text"]
            transcript.translated_text = provider_result["text"]
            transcript.language = provider_result.get("language")
            transcript.provider = provider_result["provider"]
            transcript.provider_model = provider_result["model"]
            transcript.completed_at = datetime.now(timezone.utc)
            if transcript.transcription_job_id:
                await job_state_service.update_job(
                    session,
                    transcript.transcription_job_id,
                    status="completed",
                    progress=100,
                    result=provider_result,
                    metadata={"transcript_status": "completed"},
                    completed=True,
                )
            await session.commit()
        return provider_result
    except Exception as exc:
        async with async_session_factory() as session:
            transcript = await session.get(AudioTranscript, transcript_uuid)
            if transcript is not None:
                transcript.status = "failed"
                transcript.error_message = str(exc)
                if transcript.transcription_job_id:
                    await job_state_service.update_job(
                        session,
                        transcript.transcription_job_id,
                        status="failed",
                        progress=100,
                        error_message=str(exc),
                        metadata={"transcript_status": "failed"},
                        completed=True,
                    )
                await session.commit()
        raise


audio_processing_service = AudioProcessingService()
