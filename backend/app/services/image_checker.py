# app/services/image_checker.py
"""
Image validation pipeline for WhatsApp complaint claims.

Pipeline order (fail-fast):
  1. Download from Twilio with Basic Auth (SID + token)
  2. File size check  (< MAX_FILE_SIZE_MB)
  3. MIME type check  (JPEG / PNG / WEBP only)
  4. EXIF extraction  (gallery / screenshot detection)
  5. pHash compute    (perceptual fingerprint)
  6. Duplicate check  (Hamming distance < HASH_DISTANCE_THRESHOLD against DB)

On any failure → ImageCheckResult(valid=False, rejection_reason=<str>)
On success     → ImageCheckResult(valid=True, image_hash=<str>, image_meta=<dict>)

The caller (routes_webhook.py) maps rejection_reason to the correct error template.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, Optional

import httpx
import imagehash
import magic
from PIL import Image
from PIL.ExifTags import TAGS
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB        = 10
MAX_BYTES               = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_MIME_TYPES      = {"image/jpeg", "image/png", "image/webp"}
HASH_DISTANCE_THRESHOLD = 10   # Hamming distance; < 10 → near-duplicate


# ── Result model ──────────────────────────────────────────────────────────
class ImageCheckResult(BaseModel):
    valid:            bool
    image_hash:       Optional[str]       = None
    image_meta:       Dict[str, Any]      = {}
    risk_delta:       int                 = 0      # extra risk to add to fraud score
    rejection_reason: Optional[str]       = None   # "too_large" | "bad_format" | "no_exif" | "duplicate"


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_exif(image: Image.Image) -> Dict[str, Any]:
    """Return a flat dict of readable EXIF tags. Empty dict if none."""
    try:
        raw = image._getexif()  # type: ignore[attr-defined]
        if not raw:
            return {}
        return {TAGS.get(tag_id, str(tag_id)): str(val) for tag_id, val in raw.items()}
    except Exception:
        return {}


async def _is_duplicate(
    phash_str: str,
    user_id: str,
    db: AsyncSession,
) -> bool:
    """
    Return True if any previous claim by this user has an image whose
    perceptual hash is within HASH_DISTANCE_THRESHOLD of the new hash.

    Imports RefundClaim inline to avoid circular imports at module level.
    """
    try:
        from app.models.domain import RefundClaim  # local import to avoid circular
        result = await db.execute(
            select(RefundClaim.image_hash)
            .where(RefundClaim.user_id == user_id)
            .where(RefundClaim.image_hash.isnot(None))
        )
        existing_hashes = [row[0] for row in result.fetchall()]

        new_hash = imagehash.hex_to_hash(phash_str)
        for existing in existing_hashes:
            try:
                if new_hash - imagehash.hex_to_hash(existing) < HASH_DISTANCE_THRESHOLD:
                    logger.warning(
                        "Duplicate image detected for user_id=%s  new=%s  existing=%s",
                        user_id, phash_str, existing,
                    )
                    return True
            except Exception:
                continue
    except Exception as exc:
        logger.error("Duplicate check DB error: %s", exc)

    return False


# ── Main validator ────────────────────────────────────────────────────────

async def validate_image(
    media_url:    str,
    phone_number: str,
    db:           AsyncSession,
    user_id:      Optional[str] = None,
    *,
    twilio_account_sid:  str = "",
    twilio_auth_token:   str = "",
) -> ImageCheckResult:
    """
    Download the image from Twilio and run the full validation pipeline.

    Args:
        media_url:           Twilio MediaUrl0 value from the webhook form.
        phone_number:        Sender's phone number (used for logging only).
        db:                  Async SQLAlchemy session (for duplicate check).
        user_id:             DB user ID (for duplicate check). If None, skips duplicate check.
        twilio_account_sid:  Twilio Account SID for Basic Auth.
        twilio_auth_token:   Twilio Auth Token for Basic Auth.

    Returns:
        ImageCheckResult — see class definition above.
    """

    # ── Step 1: Download with Twilio Basic Auth ───────────────────────────
    try:
        auth = (twilio_account_sid, twilio_auth_token) if twilio_account_sid else None
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(media_url, auth=auth)
            response.raise_for_status()
            file_bytes = response.content
    except httpx.HTTPStatusError as exc:
        logger.error("Twilio media download HTTP error phone=%s: %s", phone_number, exc)
        # Fail open — don't block genuine users on Twilio infra issues
        return ImageCheckResult(valid=True, image_hash=None, image_meta={"error": "download_failed"})
    except Exception as exc:
        logger.error("Twilio media download error phone=%s: %s", phone_number, exc)
        return ImageCheckResult(valid=True, image_hash=None, image_meta={"error": str(exc)})

    # ── Step 2: File size check ───────────────────────────────────────────
    if len(file_bytes) > MAX_BYTES:
        logger.info("Image too large phone=%s size=%d", phone_number, len(file_bytes))
        return ImageCheckResult(valid=False, rejection_reason="too_large")

    # ── Step 3: MIME type check ───────────────────────────────────────────
    try:
        mime_type = magic.from_buffer(file_bytes, mime=True)
    except Exception:
        mime_type = "unknown"

    if mime_type not in ALLOWED_MIME_TYPES:
        logger.info("Bad MIME type phone=%s mime=%s", phone_number, mime_type)
        return ImageCheckResult(valid=False, rejection_reason="bad_format")

    # ── Step 4: Open image + EXIF extraction ─────────────────────────────
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()  # force decode to catch truncated images
    except Exception as exc:
        logger.error("PIL cannot open image phone=%s: %s", phone_number, exc)
        return ImageCheckResult(valid=False, rejection_reason="bad_format")

    exif_data       = _extract_exif(image)
    has_timestamp   = "DateTime" in exif_data or "DateTimeOriginal" in exif_data
    has_gps         = "GPSInfo" in exif_data
    is_png          = mime_type == "image/png"
    is_gallery_img  = is_png and not exif_data   # PNG from gallery / screenshot — no EXIF

    if is_gallery_img:
        logger.info("Gallery/screenshot image detected phone=%s", phone_number)
        return ImageCheckResult(valid=False, rejection_reason="no_exif", risk_delta=20)

    # ── Step 5: Compute pHash ─────────────────────────────────────────────
    try:
        phash_str = str(imagehash.phash(image))
    except Exception as exc:
        logger.error("pHash computation failed phone=%s: %s", phone_number, exc)
        phash_str = None

    # ── Step 6: Duplicate check against claim history ────────────────────
    if phash_str and user_id:
        if await _is_duplicate(phash_str, user_id, db):
            return ImageCheckResult(
                valid=False,
                rejection_reason="duplicate",
                image_hash=phash_str,
                risk_delta=18,
            )

    # ── Build metadata dict ───────────────────────────────────────────────
    metadata: Dict[str, Any] = {
        "format":          image.format or mime_type,
        "mode":            image.mode,
        "size":            list(image.size),
        "mime_type":       mime_type,
        "has_timestamp":   has_timestamp,
        "has_gps":         has_gps,
        "suspicious":      not has_timestamp,   # JPEG without timestamp is mildly suspicious
        "exif_keys":       list(exif_data.keys())[:10],  # first 10 EXIF tag names for AI prompt
    }

    logger.info(
        "Image valid phone=%s phash=%s has_ts=%s has_gps=%s",
        phone_number, phash_str, has_timestamp, has_gps,
    )

    return ImageCheckResult(
        valid=True,
        image_hash=phash_str,
        image_meta=metadata,
        risk_delta=0,
    )


# ── Legacy sync validator (web API uploads — Phase 1 REST endpoint) ───────

def validate_and_extract_image_data(file_bytes: bytes) -> dict:
    """
    Synchronous validator for standard multipart/form-data uploads
    (used by the web dashboard claim form, not WhatsApp).
    Does NOT run duplicate check — call the async version for that.
    """
    if len(file_bytes) > MAX_BYTES:
        return {"is_valid": False, "error": f"File exceeds {MAX_FILE_SIZE_MB} MB limit."}

    try:
        mime_type = magic.from_buffer(file_bytes, mime=True)
    except Exception:
        return {"is_valid": False, "error": "Could not determine file type."}

    if mime_type not in ALLOWED_MIME_TYPES:
        return {"is_valid": False, "error": "Only JPEG, PNG, or WebP images are accepted."}

    try:
        image   = Image.open(io.BytesIO(file_bytes))
        image.load()
        phash   = str(imagehash.phash(image))
        exif    = _extract_exif(image)
        return {
            "is_valid":    True,
            "image_hash":  phash,
            "metadata": {
                "format":        image.format,
                "mode":          image.mode,
                "size":          list(image.size),
                "has_exif":      bool(exif),
                "has_timestamp": "DateTime" in exif or "DateTimeOriginal" in exif,
                "suspicious":    not exif,
            },
        }
    except Exception as exc:
        return {"is_valid": False, "error": f"Image processing failed: {exc}"}