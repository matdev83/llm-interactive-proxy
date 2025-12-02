"""
Virtual Tool Calling (VTC) client detection utilities.

VTC is a mode used by Cline-like clients that embed tool calls as XML
within message content rather than using native tool_calls format.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def detect_vtc_client(agent: str | None, patterns: list[str]) -> bool:
    """Detect if the agent matches any VTC client pattern (case-insensitive).

    This function checks if the User-Agent string contains any of the
    configured VTC client patterns using case-insensitive substring matching.

    Args:
        agent: The User-Agent string from the request headers (may be None).
        patterns: List of patterns to match against (e.g., ["cline", "kilo", "roo"]).

    Returns:
        True if the agent matches any pattern, False otherwise.

    Examples:
        >>> detect_vtc_client("Cline/1.0", ["cline", "kilo", "roo"])
        True
        >>> detect_vtc_client("KiloCode-Agent/2.1.0", ["cline", "kilo", "roo"])
        True
        >>> detect_vtc_client("RooCode/0.5", ["cline", "kilo", "roo"])
        True
        >>> detect_vtc_client("cursor/1.0", ["cline", "kilo", "roo"])
        False
        >>> detect_vtc_client(None, ["cline", "kilo", "roo"])
        False
    """
    # Guard against non-string agents (e.g., mock objects from tests)
    if not agent or not isinstance(agent, str):
        return False

    if not patterns or not isinstance(patterns, list):
        return False

    agent_lower = agent.lower()
    for pattern in patterns:
        if pattern.lower() in agent_lower:
            logger.debug(
                "VTC client detected: agent=%r matches pattern=%r",
                agent,
                pattern,
            )
            return True

    return False
