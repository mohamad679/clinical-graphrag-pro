"""
Image processing service — handles upload, validation, storage, thumbnails, and async analysis.
"""

from __future__ import annotations

import importlib.util
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.metrics import observe_image_analysis
from app.core.observability import trace_operation, update_observability_context
from app.models.medical_image import ImageAnnotation, MedicalImage
from app.services.dicom_scrubber import scrub_dicom
from app.services.entity_normalization import entity_normalization_service
from app.services.graph import temporal_graph_service
from app.services.job_state import job_state_service
from app.services.storage import storage_service
from app.services.vision import vision_service

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif", ".dcm"}
MAX_IMAGE_SIZE = settings.image_max_upload_size_mb * 1024 * 1024


@dataclass(slots=True)
class ValidatedImageUpload:
    normalized_filename: str
    detected_kind: str
    extension: str
    mime_type: str
    sanitized_content: bytes
    width: int | None
    height: int | None
    phi_scrubbed: bool
    manual_review_required: bool
    dicom_metadata: dict | None
    validation_metadata: dict


class ImageProcessingService:
    """Handles image file operations: validate, store, create thumbnails."""

    def __init__(self):
        self.image_dir = settings.upload_dir / "images"
        self.thumbnail_dir = settings.upload_dir / "thumbnails"
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

    async def validate_image_upload(
        self,
        filename: str,
        claimed_content_type: str,
        content: bytes,
    ) -> ValidatedImageUpload:
        normalized_filename = Path(filename).name or "image"
        extension = Path(normalized_filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported image type: {extension}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        if len(content) > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image too large: {len(content) / (1024 * 1024):.1f}MB. "
                f"Max: {settings.image_max_upload_size_mb}MB"
            )

        detected_kind = self._detect_kind(content)
        if detected_kind is None:
            raise ValueError("Unable to verify image file signature from magic bytes.")

        allowed_extensions = self._allowed_extensions_for_kind(detected_kind)
        if extension not in allowed_extensions:
            raise ValueError(
                f"File extension {extension} does not match detected file type {detected_kind}."
            )

        manual_review_required = False
        dicom_metadata = None
        phi_scrubbed = False
        sanitized_content = content
        width = None
        height = None

        if extension == ".dcm":
            if not settings.image_allow_dicom or settings.image_dicom_policy == "reject":
                raise ValueError("DICOM uploads are disabled by policy until sanitization support is configured.")
            scrub_result = await scrub_dicom(content)
            sanitized_content = scrub_result.pixel_array_bytes
            width = scrub_result.width
            height = scrub_result.height
            manual_review_required = True
            phi_scrubbed = True
            dicom_metadata = {
                "modality": scrub_result.modality,
                "body_part": scrub_result.body_part,
                "rows": scrub_result.height,
                "columns": scrub_result.width,
                "frames": scrub_result.frames,
                "scrub_timestamp": scrub_result.scrub_timestamp,
                "burned_in_text_detection": scrub_result.burned_in_text_detection,
                "deidentification_status": "metadata-scrubbed-pixel-text-manual-review-required",
            }
        else:
            width, height = self._get_dimensions(content, detected_kind)
        if detected_kind == "tiff" and settings.image_strip_metadata and extension != ".dcm":
            raise ValueError("TIFF uploads require metadata sanitization support and are currently rejected.")
        elif extension != ".dcm":
            sanitized_content, phi_scrubbed = self._strip_metadata(detected_kind, content)
            if detected_kind in {"gif", "bmp"}:
                phi_scrubbed = True

        self._validate_dimensions(width, height)
        if not phi_scrubbed and settings.image_strip_metadata:
            manual_review_required = True

        validation_metadata = {
            "magic_bytes_checked": True,
            "claimed_content_type": claimed_content_type,
            "detected_kind": detected_kind,
            "extension": extension,
            "metadata_stripped": phi_scrubbed,
            "manual_review_required": manual_review_required,
            "dicom_policy": settings.image_dicom_policy,
            "burned_in_text_detection": (
                dicom_metadata.get("burned_in_text_detection") if dicom_metadata else "unsupported"
            ),
        }
        if extension == ".dcm":
            validation_metadata["dicom_phi_tags_removed"] = scrub_result.tags_removed

        return ValidatedImageUpload(
            normalized_filename=normalized_filename,
            detected_kind=detected_kind,
            extension=extension,
            mime_type="image/png" if extension == ".dcm" else self._mime_for_kind(detected_kind),
            sanitized_content=sanitized_content,
            width=width,
            height=height,
            phi_scrubbed=phi_scrubbed,
            manual_review_required=manual_review_required,
            dicom_metadata=dicom_metadata,
            validation_metadata=validation_metadata,
        )

    async def save_image(
        self,
        file_content: bytes,
        original_filename: str,
        *,
        content_type: str | None = None,
    ) -> dict:
        """
        Save an uploaded image through the configured storage backend.
        Returns metadata dict with storage descriptors and dimensions.
        """
        ext = Path(original_filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"

        # Try to get image dimensions
        width, height = self._get_dimensions(file_content, self._kind_from_extension(ext) or ext.lstrip("."))

        # Generate thumbnail
        thumbnail_content = await self._create_thumbnail(file_content, unique_name, ext)

        file_asset = await storage_service.store_bytes(
            category="images",
            filename=unique_name,
            content=file_content,
            content_type=content_type,
        )
        thumbnail_asset = None
        if thumbnail_content is not None:
            thumbnail_asset = await storage_service.store_bytes(
                category="thumbnails",
                filename=f"thumb_{Path(unique_name).stem}.webp",
                content=thumbnail_content,
                content_type="image/webp",
            )

        return {
            "filename": unique_name,
            "file_asset": file_asset,
            "thumbnail_asset": thumbnail_asset,
            "file_path": self._asset_compat_path(file_asset),
            "thumbnail_path": self._asset_compat_path(thumbnail_asset) if thumbnail_asset else None,
            "file_size": len(file_content),
            "width": width,
            "height": height,
        }

    def _get_dimensions(self, content: bytes, kind: str) -> tuple[int | None, int | None]:
        """Get image dimensions. Returns (width, height) or (None, None)."""
        kind = kind.lower()
        try:
            if kind == "png" and len(content) >= 24:
                return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
            if kind == "gif" and len(content) >= 10:
                return int.from_bytes(content[6:8], "little"), int.from_bytes(content[8:10], "little")
            if kind == "bmp" and len(content) >= 26:
                return int.from_bytes(content[18:22], "little"), int.from_bytes(content[22:26], "little")
            if kind == "webp" and len(content) >= 30:
                return self._parse_webp_dimensions(content)
            if kind == "jpeg":
                return self._parse_jpeg_dimensions(content)
        except Exception:
            pass
        return None, None

    def _parse_webp_dimensions(self, content: bytes) -> tuple[int | None, int | None]:
        if content[12:16] != b"WEBP":
            return None, None
        chunk_type = content[12:16]
        if chunk_type == b"VP8 " and len(content) >= 30:
            return (
                int.from_bytes(content[26:28], "little") & 0x3FFF,
                int.from_bytes(content[28:30], "little") & 0x3FFF,
            )
        if chunk_type == b"VP8L" and len(content) >= 25:
            bits = int.from_bytes(content[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if chunk_type == b"VP8X" and len(content) >= 30:
            return (
                1 + int.from_bytes(content[24:27], "little"),
                1 + int.from_bytes(content[27:30], "little"),
            )
        return None, None

    def _parse_jpeg_dimensions(self, content: bytes) -> tuple[int | None, int | None]:
        offset = 2
        size = len(content)
        while offset + 9 < size:
            if content[offset] != 0xFF:
                offset += 1
                continue
            marker = content[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if marker == 0xDA:
                break
            if offset + 2 > size:
                break
            segment_length = int.from_bytes(content[offset:offset + 2], "big")
            if segment_length < 2 or offset + segment_length > size:
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3,
                0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB,
                0xCD, 0xCE, 0xCF,
            }:
                height = int.from_bytes(content[offset + 3:offset + 5], "big")
                width = int.from_bytes(content[offset + 5:offset + 7], "big")
                return width, height
            offset += segment_length
        return None, None

    async def _create_thumbnail(
        self, content: bytes, filename: str, ext: str
    ) -> bytes | None:
        """Create a 256px thumbnail. Returns bytes or None."""
        try:
            from PIL import Image
            from io import BytesIO as ThumbnailBuffer

            img = Image.open(BytesIO(content))
            img.thumbnail((256, 256))

            output = ThumbnailBuffer()
            img.save(output, "WEBP", quality=80)
            logger.info("Created thumbnail for %s", filename)
            return output.getvalue()
        except ImportError:
            logger.debug("PIL not available — skipping thumbnail generation")
            return None
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return None

    def _validate_dimensions(self, width: int | None, height: int | None) -> None:
        if width is None or height is None:
            return
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions are invalid.")
        if width > settings.image_max_width or height > settings.image_max_height:
            raise ValueError(
                f"Image dimensions exceed policy limits ({settings.image_max_width}x{settings.image_max_height})."
            )
        if width * height > settings.image_max_pixels:
            raise ValueError("Image pixel count exceeds the configured safety limit.")

    def _detect_kind(self, content: bytes) -> str | None:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if content.startswith(b"\xff\xd8\xff"):
            return "jpeg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "gif"
        if content.startswith(b"BM"):
            return "bmp"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "webp"
        if content.startswith((b"II*\x00", b"MM\x00*")):
            return "tiff"
        if len(content) >= 132 and content[128:132] == b"DICM":
            return "dicom"
        return None

    def _allowed_extensions_for_kind(self, kind: str) -> set[str]:
        return {
            "png": {".png"},
            "jpeg": {".jpg", ".jpeg"},
            "gif": {".gif"},
            "bmp": {".bmp"},
            "webp": {".webp"},
            "tiff": {".tif", ".tiff"},
            "dicom": {".dcm"},
        }.get(kind, set())

    def _kind_from_extension(self, extension: str) -> str | None:
        normalized = extension.lower()
        for kind, extensions in {
            "png": {".png"},
            "jpeg": {".jpg", ".jpeg"},
            "gif": {".gif"},
            "bmp": {".bmp"},
            "webp": {".webp"},
            "tiff": {".tif", ".tiff"},
            "dicom": {".dcm"},
        }.items():
            if normalized in extensions:
                return kind
        return None

    def _mime_for_kind(self, kind: str) -> str:
        return {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "tiff": "image/tiff",
            "dicom": "application/dicom",
        }[kind]

    def _strip_metadata(self, kind: str, content: bytes) -> tuple[bytes, bool]:
        if not settings.image_strip_metadata:
            return content, False
        if kind == "png":
            return self._strip_png_metadata(content), True
        if kind == "jpeg":
            return self._strip_jpeg_metadata(content), True
        if kind == "webp":
            return self._strip_webp_metadata(content), True
        return content, False

    def _strip_png_metadata(self, content: bytes) -> bytes:
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            return content
        output = bytearray(content[:8])
        offset = 8
        while offset + 12 <= len(content):
            length = int.from_bytes(content[offset:offset + 4], "big")
            chunk_type = content[offset + 4:offset + 8]
            chunk_end = offset + 12 + length
            if chunk_end > len(content):
                break
            if chunk_type not in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
                output.extend(content[offset:chunk_end])
            offset = chunk_end
            if chunk_type == b"IEND":
                break
        return bytes(output)

    def _strip_jpeg_metadata(self, content: bytes) -> bytes:
        if not content.startswith(b"\xff\xd8"):
            return content
        output = bytearray(content[:2])
        offset = 2
        size = len(content)
        while offset + 4 <= size:
            if content[offset] != 0xFF:
                break
            marker = content[offset + 1]
            if marker == 0xDA:
                output.extend(content[offset:])
                return bytes(output)
            if marker in {0xD8, 0xD9}:
                output.extend(content[offset:offset + 2])
                offset += 2
                continue
            segment_length = int.from_bytes(content[offset + 2:offset + 4], "big")
            if segment_length < 2 or offset + 2 + segment_length > size:
                break
            segment = content[offset:offset + 2 + segment_length]
            if marker not in {0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xFE}:
                output.extend(segment)
            offset += 2 + segment_length
        output.extend(content[offset:])
        return bytes(output)

    def _strip_webp_metadata(self, content: bytes) -> bytes:
        if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            return content
        payload = bytearray(b"WEBP")
        offset = 12
        while offset + 8 <= len(content):
            chunk_type = content[offset:offset + 4]
            chunk_size = int.from_bytes(content[offset + 4:offset + 8], "little")
            chunk_end = offset + 8 + chunk_size + (chunk_size % 2)
            if chunk_end > len(content):
                break
            if chunk_type not in {b"EXIF", b"XMP ", b"ICCP"}:
                payload.extend(content[offset:chunk_end])
            offset = chunk_end
        return b"RIFF" + len(payload).to_bytes(4, "little") + payload

    def _sanitize_dicom(self, content: bytes) -> tuple[bytes, dict]:
        if not importlib.util.find_spec("pydicom"):
            raise ValueError("DICOM sanitization requires the optional pydicom dependency.")
        import pydicom  # type: ignore[import-not-found]

        dataset = pydicom.dcmread(BytesIO(content), force=True)
        metadata = {
            "modality": str(getattr(dataset, "Modality", "") or ""),
            "study_instance_uid": str(getattr(dataset, "StudyInstanceUID", "") or ""),
            "rows": int(getattr(dataset, "Rows", 0) or 0) or None,
            "columns": int(getattr(dataset, "Columns", 0) or 0) or None,
        }
        for attribute in (
            "PatientName",
            "PatientID",
            "PatientBirthDate",
            "PatientSex",
            "InstitutionName",
            "ReferringPhysicianName",
            "AccessionNumber",
            "StudyID",
        ):
            if hasattr(dataset, attribute):
                delattr(dataset, attribute)
        dataset.remove_private_tags()
        output = BytesIO()
        dataset.save_as(output)
        return output.getvalue(), metadata

    @staticmethod
    def _asset_compat_path(asset) -> str:
        if asset is None:
            return ""
        local_path = asset.storage_metadata.get("local_path") if asset.storage_metadata else None
        if local_path:
            return str(local_path)
        return f"{asset.provider}://{asset.bucket}/{asset.object_key}"

    def delete_image(self, file_path: str, thumbnail_path: str | None = None):
        """Remove image (and thumbnail) from disk."""
        try:
            p = Path(file_path)
            if p.exists():
                p.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete image {file_path}: {e}")

        if thumbnail_path:
            try:
                t = Path(thumbnail_path)
                if t.exists():
                    t.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete thumbnail {thumbnail_path}: {e}")

    def get_image_url(self, image_id: str) -> str:
        """Return the DB-authorized API-served URL for an image."""
        return f"/api/images/{image_id}/file"

    def get_thumbnail_url(self, image_id: str) -> str | None:
        """Return the DB-authorized API-served URL for a thumbnail."""
        return f"/api/images/{image_id}/thumbnail"

    async def read_image_bytes(self, image: MedicalImage) -> bytes:
        if image.storage_asset is not None:
            return await storage_service.read_bytes(
                bucket=image.storage_asset.bucket,
                object_key=image.storage_asset.object_key,
                storage_metadata=image.storage_asset.storage_metadata,
            )

        path = Path(image.file_path)
        if ".." in path.parts:
            raise FileNotFoundError("Image file path is invalid.")
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image.file_path}")
        return path.read_bytes()

    async def read_thumbnail_bytes(self, image: MedicalImage) -> bytes | None:
        if image.thumbnail_asset is not None:
            return await storage_service.read_bytes(
                bucket=image.thumbnail_asset.bucket,
                object_key=image.thumbnail_asset.object_key,
                storage_metadata=image.thumbnail_asset.storage_metadata,
            )

        if not image.thumbnail_path:
            return None
        path = Path(image.thumbnail_path)
        if ".." in path.parts:
            return None
        if not path.exists():
            return None
        return path.read_bytes()


async def process_image_analysis_async(image_id: str, additional_context: str = "") -> dict:
    started = time.perf_counter()
    image_uuid = UUID(str(image_id))
    update_observability_context(image_id=str(image_uuid))
    async with async_session_factory() as session:
        result = await session.execute(
            select(MedicalImage)
            .options(selectinload(MedicalImage.storage_asset), selectinload(MedicalImage.annotations))
            .where(MedicalImage.id == image_uuid)
        )
        image = result.scalar_one_or_none()
        if image is None:
            raise ValueError(f"Image {image_id} not found")

        image.analysis_status = "analyzing"
        image.analysis_requested_at = datetime.now(timezone.utc)
        image.last_error = None
        if image.analysis_job_id:
            await job_state_service.update_job(
                session,
                image.analysis_job_id,
                progress=10,
                metadata={"analysis_status": "analyzing"},
            )
        await session.commit()

    try:
        with trace_operation(
            "image.analyze",
            component="vision",
            logger_=logger,
            image_id=str(image_uuid),
        ):
            async with async_session_factory() as session:
                result = await session.execute(
                    select(MedicalImage)
                    .options(selectinload(MedicalImage.storage_asset), selectinload(MedicalImage.annotations))
                    .where(MedicalImage.id == image_uuid)
                )
                image = result.scalar_one_or_none()
                if image is None:
                    raise ValueError(f"Image {image_id} not found")
                image_bytes = await image_processing_service.read_image_bytes(image)
                mime_type = image.mime_type

            analysis = await vision_service.analyze_image(image_bytes, mime_type, additional_context)

        success = "error" not in analysis
        if success:
            text_fragments = [analysis.get("summary", "")]
            for finding in analysis.get("findings", []):
                text_fragments.append(finding.get("description", ""))
                text_fragments.append(finding.get("location", ""))
            for item in analysis.get("differential_diagnosis", []):
                text_fragments.append(item.get("condition", ""))
            combined_text = ". ".join(fragment.strip() for fragment in text_fragments if fragment and fragment.strip())
            normalized_entities = entity_normalization_service.normalize_with_fallback(combined_text) if combined_text else []
            analysis["normalized_entities"] = [entity.model_dump() for entity in normalized_entities if not entity.is_ungrounded]
        else:
            analysis["normalized_entities"] = []

        async with async_session_factory() as session:
            result = await session.execute(
                select(MedicalImage)
                .options(selectinload(MedicalImage.annotations))
                .where(MedicalImage.id == image_uuid)
            )
            image = result.scalar_one_or_none()
            if image is None:
                raise ValueError(f"Image {image_id} not found")

            now = datetime.now(timezone.utc)
            image.analysis_result = analysis
            image.analysis_status = "ai_generated" if success else "failed"
            image.analyzed_at = now
            image.modality = analysis.get("modality_detected")
            image.body_part = analysis.get("body_part_detected")
            image.manual_review_required = bool(success)
            image.manual_review_status = "pending_review" if success else image.manual_review_status
            image.last_error = analysis.get("error") if isinstance(analysis, dict) else None

            for annotation in image.annotations:
                if annotation.source == "ai" and annotation.is_current and annotation.deleted_at is None:
                    annotation.is_current = False
                    annotation.deleted_at = now

            if success:
                for ann_data in vision_service.extract_annotations_from_analysis(analysis):
                    session.add(
                        ImageAnnotation(
                            image_id=image.id,
                            version_number=1,
                            is_current=True,
                            review_status="ai_generated",
                            metadata_={"generated_at": now.isoformat()},
                            **ann_data,
                        )
                    )

                graph_result = await temporal_graph_service.ingest_image_analysis(
                    image_id=str(image.id),
                    tenant_id=image.user_id,
                    image_name=image.original_filename,
                    analysis=analysis,
                    patient_id=image.patient_id,
                    study_date=image.study_date,
                    uploaded_at=image.uploaded_at,
                    modality=image.modality,
                    body_part=image.body_part,
                )
                analysis["graph_ingestion"] = graph_result

            if image.analysis_job_id:
                await job_state_service.update_job(
                    session,
                    image.analysis_job_id,
                    status="completed" if success else "failed",
                    progress=100,
                    result=analysis,
                    error_message=analysis.get("error") if isinstance(analysis, dict) else None,
                    metadata={"analysis_status": image.analysis_status},
                    completed=True,
                )
            await session.commit()
        observe_image_analysis(time.perf_counter() - started, success=success)
        return analysis
    except Exception as exc:
        observe_image_analysis(time.perf_counter() - started, success=False)
        async with async_session_factory() as session:
            image = await session.get(MedicalImage, image_uuid)
            if image is not None:
                image.analysis_status = "failed"
                image.last_error = str(exc)
                image.analyzed_at = datetime.now(timezone.utc)
                if image.analysis_job_id:
                    await job_state_service.update_job(
                        session,
                        image.analysis_job_id,
                        status="failed",
                        progress=100,
                        error_message=str(exc),
                        metadata={"analysis_status": "failed"},
                        completed=True,
                    )
                await session.commit()
        raise


# Module-level singleton
image_processing_service = ImageProcessingService()
