"""
Backend compatibility rules for session sanitization.

This module defines which backend types share infrastructure and can
reuse session data (like thought signatures) without sanitization.
"""

import logging

logger = logging.getLogger(__name__)

# Backend groups that share compatible infrastructure
# Backends within the same group can reuse thought signatures
_GEMINI_OAUTH_PERSONAL_GROUP: frozenset[str] = frozenset(
    {
        "gemini-oauth-free",
        "gemini-oauth-plan",
    }
)

_GEMINI_OAUTH_ANTIGRAVITY_GROUP: frozenset[str] = frozenset(
    {
        "gemini-oauth-antigravity",
    }
)

_GEMINI_CLOUD_GROUP: frozenset[str] = frozenset(
    {
        "gemini-cloud-project",
        "gemini",
    }
)

# All groups of Gemini backends that use thought signatures
_GEMINI_SIGNATURE_GROUPS: list[frozenset[str]] = [
    _GEMINI_OAUTH_PERSONAL_GROUP,
    _GEMINI_OAUTH_ANTIGRAVITY_GROUP,
    _GEMINI_CLOUD_GROUP,
]

# All Gemini backend types that use thought signatures
_GEMINI_BACKENDS_WITH_SIGNATURES: frozenset[str] = frozenset().union(
    *_GEMINI_SIGNATURE_GROUPS
)


def _get_backend_group(backend_type: str) -> frozenset[str] | None:
    """Get the infrastructure group for a backend type.

    Args:
        backend_type: The backend type identifier (e.g., "gemini-oauth-plan")

    Returns:
        The group frozenset if found, None if backend is not in any group
    """
    for group in _GEMINI_SIGNATURE_GROUPS:
        if backend_type in group:
            return group
    return None


def are_backends_compatible(backend_from: str | None, backend_to: str | None) -> bool:
    """Check if two backends share compatible infrastructure.

    Backends are compatible if:
    - Either is None (no previous backend or unknown)
    - They are the same backend type
    - They belong to the same infrastructure group

    Args:
        backend_from: The previous backend type
        backend_to: The new backend type

    Returns:
        True if backends are compatible (no sanitization needed)
    """
    if backend_from is None or backend_to is None:
        return True

    if backend_from == backend_to:
        return True

    group_from = _get_backend_group(backend_from)
    group_to = _get_backend_group(backend_to)

    # If both have groups and they're the same group, compatible
    if group_from is not None and group_to is not None:
        return group_from is group_to

    # If switching to/from a non-Gemini backend, signatures don't matter
    # (they won't be used or understood anyway)
    if backend_from not in _GEMINI_BACKENDS_WITH_SIGNATURES:
        return True

    # If switching to a non-Gemini backend, signatures don't matter
    return backend_to not in _GEMINI_BACKENDS_WITH_SIGNATURES


def requires_signature_cleanup(
    backend_from: str | None, backend_to: str | None
) -> bool:
    """Check if switching backends requires thought signature cleanup.

    This is the inverse of are_backends_compatible, with additional
    checks to ensure we only clean up when necessary.

    Args:
        backend_from: The previous backend type
        backend_to: The new backend type

    Returns:
        True if signature cleanup is required
    """
    if backend_from is None or backend_to is None:
        return False

    if backend_from == backend_to:
        return False

    # Only clean up if going TO a Gemini backend that uses signatures
    # (signatures from non-Gemini backends don't exist anyway)
    if backend_to not in _GEMINI_BACKENDS_WITH_SIGNATURES:
        return False

    # Only clean up if coming FROM a Gemini backend with signatures
    if backend_from not in _GEMINI_BACKENDS_WITH_SIGNATURES:
        return False

    # Check if they're in the same group
    return not are_backends_compatible(backend_from, backend_to)


def uses_thought_signatures(backend_type: str | None) -> bool:
    """Check if a backend type uses thought signatures.

    Args:
        backend_type: The backend type identifier

    Returns:
        True if the backend uses thought signatures
    """
    if backend_type is None:
        return False
    return backend_type in _GEMINI_BACKENDS_WITH_SIGNATURES


__all__ = [
    "are_backends_compatible",
    "requires_signature_cleanup",
    "uses_thought_signatures",
]
