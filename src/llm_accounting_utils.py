from __future__ import annotations

from typing import Any

from src import anthropic_converters


def extract_billing_info_from_headers(
    headers: dict[str, str] | None, backend: str
) -> dict[str, Any]:
    headers = headers or {}
    backend_key = backend.lower()

    provider_info: dict[str, Any] = {}
    if backend_key == "anthropic":
        provider_info["note"] = "Anthropic backend - usage info in response only"

    billing = {
        "backend": backend_key,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "provider_info": provider_info,
        "cost": 0.0,
    }
    return billing


def extract_billing_info_from_response(response: Any, backend: str) -> dict[str, Any]:
    backend_key = backend.lower()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if backend_key == "anthropic":
        extracted = anthropic_converters.extract_anthropic_usage(response)
        usage = {
            "prompt_tokens": int(extracted.get("input_tokens", 0) or 0),
            "completion_tokens": int(extracted.get("output_tokens", 0) or 0),
            "total_tokens": int(extracted.get("total_tokens", 0) or 0),
        }

    billing = {
        "backend": backend_key,
        "usage": usage,
        "provider_info": {},
        "cost": 0.0,
    }
    return billing


def is_accounting_disabled() -> bool:
    """Compatibility flag for disabling accounting."""
    return False
