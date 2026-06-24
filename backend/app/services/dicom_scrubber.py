from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import numpy as np


PHI_TAGS = frozenset(
    {
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientSex",
        "PatientAge",
        "PatientAddress",
        "PatientTelephoneNumbers",
        "PatientMotherBirthName",
        "ReferringPhysicianName",
        "StudyID",
        "AccessionNumber",
        "StudyDescription",
        "RequestingPhysician",
        "PerformingPhysicianName",
        "InstitutionName",
        "InstitutionAddress",
        "StationName",
        "DeviceSerialNumber",
        "ContentDate",
        "StudyDate",
        "SeriesDate",
        "AcquisitionDate",
    }
)


@dataclass(slots=True)
class DicomScrubResult:
    pixel_array_bytes: bytes
    width: int
    height: int
    modality: str
    body_part: str
    tags_removed: list[str]
    scrub_timestamp: str
    burned_in_text_detection: str = "manual-review-only"
    manual_review_required: bool = True
    frames: int = 1


def _utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_pixel_array(dataset: Any) -> np.ndarray:
    pixel_array = np.asarray(dataset.pixel_array)
    if pixel_array.ndim == 3 and pixel_array.shape[0] in {3, 4} and pixel_array.shape[-1] not in {3, 4}:
        pixel_array = np.moveaxis(pixel_array, 0, -1)
    if pixel_array.ndim == 3 and pixel_array.shape[-1] == 1:
        pixel_array = pixel_array[..., 0]

    normalized = np.nan_to_num(pixel_array.astype(np.float32, copy=False))
    minimum = float(normalized.min())
    maximum = float(normalized.max())
    if maximum > minimum:
        normalized = (normalized - minimum) / (maximum - minimum)
    else:
        normalized = np.zeros_like(normalized, dtype=np.float32)

    normalized = (normalized * 255.0).clip(0, 255).astype(np.uint8)
    photometric = str(getattr(dataset, "PhotometricInterpretation", "") or "").upper()
    if photometric == "MONOCHROME1":
        normalized = 255 - normalized
    return normalized


def _pixel_array_to_png_bytes(dataset: Any) -> tuple[bytes, int, int]:
    from PIL import Image

    normalized = _normalize_pixel_array(dataset)
    if normalized.ndim == 2:
        image = Image.fromarray(normalized, mode="L")
    elif normalized.ndim == 3 and normalized.shape[-1] == 3:
        image = Image.fromarray(normalized, mode="RGB")
    elif normalized.ndim == 3 and normalized.shape[-1] == 4:
        image = Image.fromarray(normalized, mode="RGBA")
    else:
        raise ValueError("Not a valid DICOM file")

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), image.width, image.height


def _remove_phi_tags(dataset: Any) -> list[str]:
    from pydicom.datadict import tag_for_keyword

    removed: list[str] = []
    for keyword in sorted(PHI_TAGS):
        tag = tag_for_keyword(keyword)
        if tag is None or tag not in dataset:
            continue
        del dataset[tag]
        removed.append(keyword)
    return removed


def _coerce_positive_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        coerced = int(str(value))
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else default


def _validate_dicom_boundaries(dataset: Any, *, file_size_bytes: int) -> int:
    from app.core.config import get_settings

    settings = get_settings()
    max_bytes = settings.image_max_upload_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise ValueError(
            f"DICOM file too large: {file_size_bytes / (1024 * 1024):.1f}MB. "
            f"Max: {settings.image_max_upload_size_mb}MB"
        )

    frames = _coerce_positive_int(getattr(dataset, "NumberOfFrames", None), 1) or 1
    if frames > 1:
        raise ValueError("Multi-frame DICOM uploads are not supported; upload a single-frame image for review.")

    rows = _coerce_positive_int(getattr(dataset, "Rows", None))
    columns = _coerce_positive_int(getattr(dataset, "Columns", None))
    if rows and columns:
        if columns > settings.image_max_width or rows > settings.image_max_height:
            raise ValueError(
                f"DICOM dimensions exceed policy limits ({settings.image_max_width}x{settings.image_max_height})."
            )
        if rows * columns * frames > settings.image_max_pixels:
            raise ValueError("DICOM pixel count exceeds the configured safety limit.")
    return frames


def _scrub_dicom_impl(file_bytes: bytes) -> DicomScrubResult:
    import pydicom
    from pydicom.errors import InvalidDicomError

    try:
        metadata_dataset = pydicom.dcmread(BytesIO(file_bytes), stop_before_pixels=True)
        frames = _validate_dicom_boundaries(metadata_dataset, file_size_bytes=len(file_bytes))
        dataset = pydicom.dcmread(BytesIO(file_bytes))
        pixel_array_bytes, width, height = _pixel_array_to_png_bytes(dataset)
    except InvalidDicomError as exc:
        raise ValueError("Not a valid DICOM file") from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith("pydicom"):
            raise ValueError("Not a valid DICOM file") from exc
        raise

    tags_removed = _remove_phi_tags(dataset)
    return DicomScrubResult(
        pixel_array_bytes=pixel_array_bytes,
        width=width,
        height=height,
        modality=str(getattr(dataset, "Modality", "") or "UNKNOWN"),
        body_part=str(getattr(dataset, "BodyPartExamined", "") or "UNKNOWN"),
        tags_removed=tags_removed,
        scrub_timestamp=_utc_now_isoformat(),
        burned_in_text_detection="manual-review-only",
        manual_review_required=True,
        frames=frames,
    )


async def scrub_dicom(file_bytes: bytes) -> DicomScrubResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _scrub_dicom_impl, file_bytes)


def scrub_dicom_sync(file_bytes: bytes) -> DicomScrubResult:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return _scrub_dicom_impl(file_bytes)

    if loop.is_running():
        return _scrub_dicom_impl(file_bytes)
    return loop.run_until_complete(loop.run_in_executor(None, _scrub_dicom_impl, file_bytes))
