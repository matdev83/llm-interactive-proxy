"""Client compatibility policy resolution.

This module provides a small, explicit contract for client capabilities.
Core streaming logic should consume these resolved policies rather than
hard-coding behavior based on specific client names.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.core.config.models.session import ClientCompatibilityConfig, ReasoningMode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientReasoningPolicy:
    reasoning_mode: ReasoningMode
    reasoning_counts_as_meaningful: bool


def _get_header_value(headers: Any, header_name: str) -> str | None:
    if not headers or not header_name:
        return None
    if not isinstance(headers, Mapping):
        return None

    # Be lenient with capitalization.
    direct = headers.get(header_name)
    if isinstance(direct, str):
        return direct
    lower = headers.get(header_name.lower())
    if isinstance(lower, str):
        return lower
    # Common canonicalization.
    for k, v in headers.items():
        if (
            isinstance(k, str)
            and k.lower() == header_name.lower()
            and isinstance(v, str)
        ):
            return v
    return None


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_reasoning_mode(value: str | None) -> ReasoningMode | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"passthrough", "pass", "keep"}:
        return "passthrough"
    if v in {"coerce_to_content", "coerce", "mirror_to_content", "strict"}:
        return "coerce_to_content"
    if v in {"drop", "strip"}:
        return "drop"
    return None


def resolve_client_reasoning_policy(
    *,
    headers: Any,
    client_config: ClientCompatibilityConfig | None,
    user_agent: str | None = None,
) -> ClientReasoningPolicy:
    """Resolve reasoning policy based on headers and optional UA rules.

    Precedence:
    1) Explicit request headers
    2) UA rules from config (if provided)
    3) Defaults: passthrough, but reasoning does not count as meaningful
       (so reasoning-only streams can still trigger empty-stream retry).
    """

    cfg = client_config or ClientCompatibilityConfig()

    mode_header = _get_header_value(headers, cfg.reasoning_mode_header)
    mode = _parse_reasoning_mode(mode_header)

    meaningful_header = _get_header_value(headers, cfg.reasoning_meaningful_header)
    meaningful_override = _parse_bool(meaningful_header)

    if mode is not None:
        if meaningful_override is not None:
            meaningful = meaningful_override
        else:
            meaningful = mode in {"passthrough", "coerce_to_content"}
        return ClientReasoningPolicy(
            reasoning_mode=mode,
            reasoning_counts_as_meaningful=meaningful,
        )

    # UA-based fallbacks (config-driven)
    ua = user_agent
    if ua and cfg.user_agent_rules:
        for rule in cfg.user_agent_rules:
            if not getattr(rule, "enabled", True):
                continue
            try:
                if re.search(rule.user_agent_regex, ua, flags=re.IGNORECASE):
                    return ClientReasoningPolicy(
                        reasoning_mode=rule.reasoning_mode,
                        reasoning_counts_as_meaningful=rule.reasoning_counts_as_meaningful,
                    )
            except re.error:
                # Rule regex is validated by pydantic, but keep best-effort.
                continue

    return ClientReasoningPolicy(
        reasoning_mode="passthrough",
        reasoning_counts_as_meaningful=False,
    )
