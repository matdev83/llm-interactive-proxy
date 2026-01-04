"""Billing domain models."""

from __future__ import annotations

from pydantic.types import JsonValue

from src.core.domain.base import ValueObject
from src.core.domain.usage_summary import UsageSummary


class BillingInfo(ValueObject):
    """Canonical billing and usage information for an LLM request/response."""

    backend: str
    usage: UsageSummary
    provider_info: dict[str, JsonValue] = {}
    cost: float = 0.0
