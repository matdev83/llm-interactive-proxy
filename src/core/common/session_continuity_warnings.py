"""Shared warning messages for session continuity configuration.

Keep all operator-facing warnings centralized to avoid drift between:
- CLI startup checks
- config semantic validation
- runtime services
"""

from __future__ import annotations

TOPIC_SIMILARITY_CONFIG_KEY = (
    "session.session_continuity.enable_topic_similarity_matching"
)


def topic_similarity_enabled_warning() -> str:
    return (
        f"{TOPIC_SIMILARITY_CONFIG_KEY}=true: topic similarity session matching is ENABLED. "
        "This may increase the risk of cross-session merges for parallel conversations "
        "on the same codebase."
    )
