"""
Image processing service — handles upload, validation, storage, and thumbnails.
"""

import logging
import uuid
import shutil
from pathlib import Path
from io import BytesIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Allowed MIME types for medical images
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/tiff",
    "image/bmp",
    "application/dicom",  # DICOM files
}

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".dcm"}

# Max image size: 100 MB
MAX_IMAGE_SIZE = 100 * 1024 * 1024


class ImageProcessingService:
    """Handles image file operations: validate, store, create thumbnails."""

    def __init__(self):
        self.image_dir = settings.upload_dir / "images"
        self.thumbnail_dir = settings.upload_dir / "thumbnails"
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

    def validate_image(self, filename: str, content_type: str, file_size: int) -> str | None:
        """
        Validate an uploaded image file.
        Returns an error message string or None if valid.
        """
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Unsupported image type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

        if file_size > MAX_IMAGE_SIZE:
            return f"Image too large: {file_size / (1024*1024):.1f}MB. Max: {MAX_IMAGE_SIZE / (1024*1024):.0f}MB"

        return None

    async def save_image(self, file_content: bytes, original_filename: str) -> dict:
        """
        Save an uploaded image to disk.
        Returns metadata dict with file paths and dimensions.
        """
        ext = Path(original_filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = self.image_dir / unique_name

        # Write the file
        file_path.write_bytes(file_content)
        logger.info(f"Saved image: {file_path} ({len(file_content)} bytes)")

        # Try to get image dimensions
        width, height = self._get_dimensions(file_content, ext)

        # Generate thumbnail
        thumbnail_path = await self._create_thumbnail(file_content, unique_name, ext)

        return {
            "filename": unique_name,
            "file_path": str(file_path),
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            "file_size": len(file_content),
            "width": width,
            "height": height,
        }

    def _get_dimensions(self, content: bytes, ext: str) -> tuple[int | None, int | None]:
        """Get image dimensions. Returns (width, height) or (None, None)."""
        try:
            # Try PIL if available
            from PIL import Image
            img = Image.open(BytesIO(content))
            return img.size
        except ImportError:
            # PIL not installed — try reading PNG/JPEG headers manually
            return self._parse_dimensions_raw(content, ext)
        except Exception:
            return None, None

    def _parse_dimensions_raw(self, content: bytes, ext: str) -> tuple[int | None, int | None]:
        """Fallback dimension parsing without PIL."""
        try:
            if ext == ".png" and len(content) >= 24:
                # PNG: width at byte 16, height at byte 20 (4 bytes each, big-endian)
                w = int.from_bytes(content[16:20], "big")
                h = int.from_bytes(content[20:24], "big")
                return w, h
        except Exception:
            pass
        return None, None

    async def _create_thumbnail(
        self, content: bytes, filename: str, ext: str
    ) -> Path | None:
        """Create a 256px thumbnail. Returns the path or None."""
        try:
            from PIL import Image

            img = Image.open(BytesIO(content))
            img.thumbnail((256, 256))

            thumb_name = f"thumb_{Path(filename).stem}.webp"
            thumb_path = self.thumbnail_dir / thumb_name
            img.save(thumb_path, "WEBP", quality=80)
            logger.info(f"Created thumbnail: {thumb_path}")
            return thumb_path
        except ImportError:
            logger.debug("PIL not available — skipping thumbnail generation")
            return None
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return None

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

    def get_image_url(self, filename: str) -> str:
        """Return the API-served URL for an image."""
        return f"/api/images/files/{filename}"

    def get_thumbnail_url(self, filename: str) -> str | None:
        """Return the API-served URL for a thumbnail."""
        thumb_name = f"thumb_{Path(filename).stem}.webp"
        thumb_path = self.thumbnail_dir / thumb_name
        if thumb_path.exists():
            return f"/api/images/thumbnails/{thumb_name}"
        return None


# Module-level singleton
image_processing_service = ImageProcessingService()
