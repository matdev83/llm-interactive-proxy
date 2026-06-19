"""Backward-compatible transport shim for session key resolver utilities."""

from src.core.common.session_key_resolver import (
    resolve_session_key_from_request_context,
)

__all__ = [
    "resolve_session_key_from_request_context",
]
