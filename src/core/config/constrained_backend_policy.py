"""Central constrained connector-family policy for routing and validation.

This module defines deterministic matching helpers reused by:
- configuration semantic validation
- runtime routing behavior
"""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from collections.abc import Iterable

# Constrained families are defined by naming contract rather than static catalog.
# Any oauth-style backend family (for example gemini-oauth-plan, qwen-oauth,
# anthropic-oauth) is constrained to a single configured proxy instance.
_CONSTRAINED_FAMILY_PATTERNS: tuple[str, ...] = (
    "*-oauth",
    "*-oauth-*",
)


def normalize_backend_family_name(raw_name: str) -> str:
    """Normalize backend/instance names into canonical family form."""
    normalized = raw_name.strip().lower().replace("_", "-")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    return normalized


def match_constrained_connector_family(backend_or_instance: str) -> str | None:
    """Return constrained family key for backend/instance, or None."""
    family = normalize_backend_family_name(backend_or_instance)
    if not family:
        return None

    if not any(
        fnmatch.fnmatch(family, pattern) for pattern in _CONSTRAINED_FAMILY_PATTERNS
    ):
        return None

    return family


def is_constrained_connector_family(backend_or_instance: str) -> bool:
    """Check whether backend/instance belongs to a constrained family."""
    return match_constrained_connector_family(backend_or_instance) is not None


def group_constrained_backend_instances(
    backend_instances: Iterable[str],
) -> dict[str, list[str]]:
    """Group backend instance names by constrained family key."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for backend in backend_instances:
        family = match_constrained_connector_family(backend)
        if family is None:
            continue
        grouped[family].append(backend)
    return {family: sorted(instances) for family, instances in sorted(grouped.items())}


def collapse_constrained_backend_candidates(candidates: list[str]) -> list[str]:
    """Collapse candidates so each constrained family contributes at most one instance.

    Selection is deterministic: lexicographically smallest instance in each constrained
    family is retained. Non-constrained candidates are preserved.
    """
    best_by_family: dict[str, str] = {}
    for candidate in candidates:
        family = match_constrained_connector_family(candidate)
        if family is None:
            continue
        previous = best_by_family.get(family)
        if previous is None or candidate < previous:
            best_by_family[family] = candidate

    collapsed: list[str] = []
    emitted_families: set[str] = set()
    for candidate in candidates:
        family = match_constrained_connector_family(candidate)
        if family is None:
            collapsed.append(candidate)
            continue
        if family in emitted_families:
            continue
        if best_by_family.get(family) == candidate:
            collapsed.append(candidate)
            emitted_families.add(family)

    return collapsed
