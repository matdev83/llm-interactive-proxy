"""
FastAPI transport adapters.

This module re-exports core adapter helpers for use in the FastAPI layer.
Keeping the logic in `src.core.adapters.api_adapters` ensures a single
domain-centric source of truth, with transports importing from here.
"""

from __future__ import annotations

from src.core.adapters.api_adapters import (
    dict_to_domain_chat_request,
    openai_to_domain_chat_request,
)

__all__ = [
    "dict_to_domain_chat_request",
    "openai_to_domain_chat_request",
]
