from __future__ import annotations

from typing import Any

from src import anthropic_converters
from src.core.domain.billing import BillingInfo
from src.core.domain.usage_summary import UsageSummary


def extract_billing_info_from_headers(
    headers: dict[str, str] | None, backend: str
) -> BillingInfo:
    headers = headers or {}
    backend_key = backend.lower()

    provider_info = {}
    if backend_key == "anthropic":
        provider_info["note"] = "Anthropic backend - usage info in response only"

    return BillingInfo(
        backend=backend_key,
        usage=UsageSummary(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        provider_info=provider_info,
        cost=0.0,
    )


def extract_billing_info_from_response(response: Any, backend: str) -> BillingInfo:
    backend_key = backend.lower()
    usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if backend_key == "anthropic":
        extracted = anthropic_converters.extract_anthropic_usage(response)
        usage_data = {
            "prompt_tokens": int(extracted.get("input_tokens", 0) or 0),
            "completion_tokens": int(extracted.get("output_tokens", 0) or 0),
            "total_tokens": int(extracted.get("total_tokens", 0) or 0),
        }

    return BillingInfo(
        backend=backend_key,
        usage=UsageSummary.from_dict(usage_data),
        provider_info={},
        cost=0.0,
    )


def is_accounting_disabled() -> bool:
    """Compatibility flag for disabling accounting."""
    return False
