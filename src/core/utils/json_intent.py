from __future__ import annotations

from typing import Any


def set_expected_json(metadata: dict[str, Any], value: bool = True) -> dict[str, Any]:
    """Set the expected_json flag in response metadata.

    Returns the same dict for chaining.
    """
    metadata["expected_json"] = bool(value)
    return metadata


def is_json_content_type(metadata: dict[str, Any]) -> bool:
    headers_raw = metadata.get("headers")
    headers: dict[str, Any] = headers_raw if isinstance(headers_raw, dict) else {}
    ct_raw = metadata.get("content_type")
    content_type = (
        ct_raw
        if isinstance(ct_raw, str)
        else headers.get("Content-Type") or headers.get("content-type")
    )
    return isinstance(content_type, str) and "application/json" in content_type.lower()


def is_json_like(content: str | None) -> bool:
    if not content or not isinstance(content, str):
        return False
    s = content.strip()
    if not s:
        return False
    return (s.startswith("{") and s.endswith("}")) or (
        s.startswith("[") and s.endswith("]")
    )


def infer_expected_json(metadata: dict[str, Any], content: str | None) -> bool:
    """Infer expected_json flag based on content-type or simple content heuristic."""
    if is_json_content_type(metadata):
        return True
    return is_json_like(content)
