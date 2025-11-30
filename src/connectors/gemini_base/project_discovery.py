"""
Project discovery helpers for Gemini OAuth connectors.

This module provides helper functions for project ID discovery,
including shared tier scoring logic and API call utilities.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_tier_id(tier: dict[str, Any]) -> str:
    """Extract tier ID from a tier dict.

    Args:
        tier: Tier dictionary from Code Assist API.

    Returns:
        Lowercase tier ID string.
    """
    raw_id = tier.get("id") or tier.get("tierId")
    return str(raw_id or "").lower()


def get_context_tokens(tier: dict[str, Any]) -> int:
    """Extract context token limit from a tier dict.

    Args:
        tier: Tier dictionary from Code Assist API.

    Returns:
        Context token limit, or 0 if not found.
    """
    for key in (
        "maxContextTokens",
        "contextTokenLimit",
        "contextWindowTokens",
        "tokenLimit",
        "maxContextWindow",
    ):
        value = tier.get(key)
        if isinstance(value, int | float):
            return int(value)
    return 0


def calculate_tier_score(tier: dict[str, Any]) -> tuple[int, int, int]:
    """Calculate a score for tier selection.

    Higher scores indicate better tiers. Score components:
    1. Is paid tier (highest priority)
    2. Context token limit
    3. Is default tier

    Args:
        tier: Tier dictionary from Code Assist API.

    Returns:
        Tuple of (is_paid, context_tokens, is_default) for sorting.
    """
    tier_id = get_tier_id(tier)
    is_paid = int(tier_id in {"paid-tier", "google-one-tier", "googleone-tier"})
    context_tokens = get_context_tokens(tier)
    if is_paid and context_tokens == 0:
        # Paid tier should always outrank tiers with unknown limits
        context_tokens = 1_000_000
    is_default = int(bool(tier.get("isDefault")))
    return (is_paid, context_tokens, is_default)


def select_best_tier(
    allowed_tiers: list[dict[str, Any]],
    current_tier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select the best tier from available options.

    Args:
        allowed_tiers: List of allowed tier dictionaries.
        current_tier: Optional current tier dictionary.

    Returns:
        The best tier dictionary, or {"id": "paid-tier"} if none found.
    """
    tiers = list(allowed_tiers)
    if current_tier:
        tiers.append(current_tier)

    if not tiers:
        return {"id": "paid-tier"}

    return max(tiers, key=calculate_tier_score)


def build_client_metadata(
    project_id: str | None = None,
    ide_type: str = "IDE_UNSPECIFIED",
    platform: str = "PLATFORM_UNSPECIFIED",
    plugin_type: str = "GEMINI",
) -> dict[str, str]:
    """Build standard client metadata for Code Assist API calls.

    Args:
        project_id: Optional project ID for duetProject field.
        ide_type: IDE type identifier.
        platform: Platform identifier.
        plugin_type: Plugin type identifier.

    Returns:
        Client metadata dictionary.
    """
    metadata = {
        "ideType": ide_type,
        "platform": platform,
        "pluginType": plugin_type,
    }
    if project_id:
        metadata["duetProject"] = project_id
    return metadata


def build_load_code_assist_request(
    project_id: str | None = None,
    client_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build request body for loadCodeAssist API call.

    Args:
        project_id: Optional project ID.
        client_metadata: Optional client metadata (will be generated if not provided).

    Returns:
        Request body dictionary.
    """
    if client_metadata is None:
        client_metadata = build_client_metadata(project_id)

    request: dict[str, Any] = {"metadata": client_metadata}
    if project_id:
        request["cloudaicompanionProject"] = project_id
    return request


def build_onboard_request(
    tier_id: str,
    project_id: str | None = None,
    client_metadata: dict[str, str] | None = None,
    include_project: bool = True,
) -> dict[str, Any]:
    """Build request body for onboardUser API call.

    Args:
        tier_id: The tier ID to onboard to.
        project_id: Optional project ID.
        client_metadata: Optional client metadata (will be generated if not provided).
        include_project: Whether to include cloudaicompanionProject field.

    Returns:
        Request body dictionary.
    """
    if client_metadata is None:
        client_metadata = build_client_metadata(project_id)

    request: dict[str, Any] = {
        "tierId": tier_id,
        "metadata": client_metadata,
    }

    if include_project and project_id:
        request["cloudaicompanionProject"] = project_id

    return request


def extract_project_id_from_response(
    response_data: dict[str, Any],
    fallback_id: str = "default",
) -> str:
    """Extract project ID from an API response.

    Args:
        response_data: The API response dictionary.
        fallback_id: Fallback ID if not found in response.

    Returns:
        The extracted project ID.
    """
    # Try direct cloudaicompanionProject field first
    if response_data.get("cloudaicompanionProject"):
        project = response_data["cloudaicompanionProject"]
        if isinstance(project, str):
            return project
        if isinstance(project, dict):
            return str(project.get("id", fallback_id))

    # Try nested response.cloudaicompanionProject
    nested_response = response_data.get("response", {})
    if nested_response.get("cloudaicompanionProject"):
        project = nested_response["cloudaicompanionProject"]
        if isinstance(project, str):
            return project
        if isinstance(project, dict):
            return str(project.get("id", fallback_id))

    return fallback_id


__all__ = [
    "build_client_metadata",
    "build_load_code_assist_request",
    "build_onboard_request",
    "calculate_tier_score",
    "extract_project_id_from_response",
    "get_context_tokens",
    "get_tier_id",
    "select_best_tier",
]
