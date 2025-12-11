"""
User prompt ID generation for Gemini Code Assist API.

This module handles generating unique identifiers for Code Assist requests.
"""

import uuid
from typing import Any


def generate_user_prompt_id(request_data: Any) -> str:
    """Generate a unique user_prompt_id for Code Assist requests.

    The ID is constructed from:
    - A base prefix "proxy"
    - Optional session hint from extra_body
    - A UUID suffix for uniqueness

    Args:
        request_data: The request data that may contain session hints

    Returns:
        A unique user_prompt_id string
    """
    session_hint: str | None = None
    extra_body = getattr(request_data, "extra_body", None)
    if isinstance(extra_body, dict):
        raw_session = extra_body.get("session_id") or extra_body.get("user_prompt_id")
        if raw_session is not None:
            session_hint = str(raw_session)

    base = "proxy"
    if session_hint:
        # Sanitize the session hint to contain only safe characters
        safe_session = "".join(
            c if c.isalnum() or c in "-._" else "-" for c in session_hint
        ).strip("-")
        if safe_session:
            base = f"{base}-{safe_session}"

    return f"{base}-{uuid.uuid4().hex}"
