from __future__ import annotations

import logging
import mimetypes
from typing import Any

logger = logging.getLogger(__name__)


def _detect_image_mime_type(url: str) -> str:
    """Detect the MIME type for an image URL or data URI."""
    if url.startswith("data:"):
        header = url.split(",", 1)[0]
        header = header.split(";", 1)[0]
        if ":" in header:
            candidate = header.split(":", 1)[1]
            if candidate:
                return candidate
        return "image/jpeg"

    clean_url = url.split("?", 1)[0].split("#", 1)[0]
    if "." in clean_url:
        extension = clean_url.rsplit(".", 1)[-1].lower()
        if extension:
            mime_type = mimetypes.types_map.get(f".{extension}")
            if mime_type and mime_type.startswith("image/"):
                return mime_type
            if extension == "jpg":
                return "image/jpeg"
    return "image/jpeg"


def _process_gemini_image_part(part: Any) -> dict[str, Any] | None:
    """Convert a multimodal image part to Gemini format."""
    from src.core.domain.chat import MessageContentPartImage

    if not isinstance(part, MessageContentPartImage) or not part.image_url:
        return None

    url_str = str(part.image_url.url or "").strip()
    if not url_str:
        return None

    if url_str.startswith("data:"):
        mime_type = _detect_image_mime_type(url_str)
        try:
            _, base64_data = url_str.split(",", 1)
        except ValueError:
            base64_data = ""
        return {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64_data,
            }
        }

    try:
        from urllib.parse import urlparse

        scheme = (urlparse(url_str).scheme or "").lower()
    except (ValueError, TypeError) as e:
        logger.debug(
            "Failed to parse URL scheme from %s: %s (type=%s)",
            url_str,
            str(e),
            type(e).__name__,
            exc_info=True,
        )
        scheme = ""

    allowed_schemes = {"http", "https"}
    if scheme not in allowed_schemes:
        return None

    mime_type = _detect_image_mime_type(url_str)
    return {
        "file_data": {
            "mime_type": mime_type,
            "file_uri": url_str,
        }
    }
