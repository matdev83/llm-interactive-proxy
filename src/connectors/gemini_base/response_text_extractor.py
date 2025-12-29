"""
Response text extraction utilities for Gemini Code Assist API.

This module handles parsing and extracting text content from
various response formats returned by the Gemini API.
"""

import json
import logging
from typing import Any

from src.core.common.exceptions import BackendError

logger = logging.getLogger(__name__)


class ResponseTextExtractor:
    """Extracts text content from Gemini Code Assist API responses.

    Handles various response formats including:
    - Standard candidates with text parts
    - Error payloads
    - Rate limit responses
    """

    @staticmethod
    def extract_generated_text(response_payload: Any) -> str:
        """Extract concatenated text content from a Gemini Code Assist response.

        Args:
            response_payload: Raw response from the API

        Returns:
            Concatenated text content from all candidates

        Raises:
            BackendError: If response contains errors or no valid content
        """
        candidate_dicts: list[dict[str, Any]] = []
        visited: set[int] = set()

        def _walk(node: Any) -> None:
            if isinstance(node, str | bytes | int | float | bool) or node is None:
                return

            node_id = id(node)
            if node_id in visited:
                return
            visited.add(node_id)

            if isinstance(node, dict):
                error_obj = node.get("error")
                if isinstance(error_obj, dict):
                    _log_anomaly("Gemini API returned error object", node)
                    _raise_error(
                        "Gemini API returned an error payload",
                        "gemini_error_payload",
                        {"error": error_obj},
                        payload=response_payload,
                    )

                maybe_candidates = node.get("candidates")
                if isinstance(maybe_candidates, list) and maybe_candidates:
                    candidate_dicts.extend(
                        candidate
                        for candidate in maybe_candidates
                        if isinstance(candidate, dict)
                    )

                for value in node.values():
                    _walk(value)

            elif isinstance(node, list | tuple):
                for item in node:
                    _walk(item)

        def _detect_rate_limit(details: dict[str, Any]) -> bool:
            error = details.get("error")
            if isinstance(error, dict):
                error_code = error.get("code")
                if isinstance(error_code, int) and error_code == 429:
                    return True
                message = error.get("message")
                if isinstance(message, str):
                    lower = message.lower()
                    if any(
                        phrase in lower
                        for phrase in (
                            "resource exhausted",
                            "rate limit",
                            "quota",
                            "too many requests",
                        )
                    ):
                        return True
            message = details.get("message")
            if isinstance(message, str):
                lower = message.lower()
                if any(
                    phrase in lower
                    for phrase in (
                        "resource exhausted",
                        "rate limit",
                        "quota",
                        "too many requests",
                    )
                ):
                    return True
            return False

        def _build_preview(payload: Any) -> str:
            try:
                text = json.dumps(payload, ensure_ascii=False)
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to serialize payload as JSON, using repr: %s",
                        e,
                        exc_info=True,
                    )
                text = repr(payload)
            if len(text) > 512:
                return text[:512] + "..."
            return text

        def _log_anomaly(message: str, payload: Any | None = None) -> None:
            if not logger.isEnabledFor(logging.WARNING):
                return
            extra: dict[str, Any] = {
                "event": "gemini_response_anomaly",
                "log_message": message,
            }
            formatted_message = message
            if payload is not None:
                preview = _build_preview(payload)
                extra["payload_preview"] = preview
                formatted_message = f"{message}; payload_preview={preview}"
            logger.warning(formatted_message, extra=extra)

        def _raise_error(
            message: str,
            code: str,
            details: dict[str, Any],
            *,
            default_status: int = 503,
            payload: Any | None = None,
        ) -> None:
            status_code = 429 if _detect_rate_limit(details) else default_status
            if payload is not None:
                details = {**details, "payload_preview": _build_preview(payload)}
            raise BackendError(
                message=message,
                code=code,
                details=details,
                status_code=status_code,
            )

        if isinstance(response_payload, dict | list | tuple):
            _walk(response_payload)
        else:
            _raise_error(
                f"Unexpected response format: {type(response_payload).__name__}",
                "unexpected_response_format",
                {"payload_type": type(response_payload).__name__},
                default_status=502,
                payload=response_payload,
            )

        if not candidate_dicts:
            payload_type = (
                type(response_payload).__name__
                if not isinstance(response_payload, list)
                else "list"
            )
            _log_anomaly(
                "Gemini response contained no candidates",
                response_payload,
            )
            _raise_error(
                "Gemini response did not include any candidates",
                "empty_response",
                {"payload_type": payload_type},
                default_status=502,
                payload=response_payload,
            )

        text_parts: list[str] = []
        for candidate in candidate_dicts:
            if not isinstance(candidate, dict):
                continue
            candidate_error = candidate.get("error")
            if isinstance(candidate_error, dict):
                _raise_error(
                    "Gemini candidate contained an error payload",
                    "gemini_error_payload",
                    {"error": candidate_error},
                )
            content = candidate.get("content", {})
            if not isinstance(content, dict):
                continue
            parts = content.get("parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text_value = part.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)

        if not text_parts or not any(part.strip() for part in text_parts):
            logger.warning(
                "List response from Gemini API contained no candidates. "
                "This may be due to safety settings or other content filters."
            )
            _log_anomaly(
                "Gemini response list contained no text parts",
                response_payload,
            )
            _raise_error(
                "Gemini response did not contain any text content",
                "empty_response",
                {"payload_type": type(response_payload).__name__},
                default_status=502,
                payload=response_payload,
            )

        return "".join(text_parts)


def extract_generated_text_from_response(response_payload: Any) -> str:
    """Extract concatenated text content from a Gemini Code Assist response.

    This is a convenience function that delegates to ResponseTextExtractor.

    Args:
        response_payload: Raw response from the API

    Returns:
        Concatenated text content from all candidates

    Raises:
        BackendError: If response contains errors or no valid content
    """
    return ResponseTextExtractor.extract_generated_text(response_payload)
