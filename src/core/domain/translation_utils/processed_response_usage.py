"""Extract canonical usage from streaming ``ProcessedResponse`` chunks."""

from __future__ import annotations

from typing import Any, cast

from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse


def usage_summary_from_processed_response(
    chunk: ProcessedResponse,
) -> UsageSummary | None:
    """Return usage from ``chunk.usage`` or from an OpenAI-style ``content`` dict.

    HTTP responses streaming often attaches provider usage only on the serialized
    domain dict (``content["usage"]``) while ``chunk.usage`` is unset. Downstream
    accounting should treat both shapes equivalently.
    """
    if chunk.usage is not None:
        return chunk.usage
    content = chunk.content
    if not isinstance(content, dict):
        return None
    raw_usage = content.get("usage")
    if not isinstance(raw_usage, dict):
        return None
    return UsageSummary.from_dict(cast(dict[str, Any], raw_usage))
