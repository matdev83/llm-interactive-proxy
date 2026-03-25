"""Shared steering text rendering for Quality Verifier (inline recall + transform pipeline)."""

from __future__ import annotations

from src.core.domain.chat import ChatMessage, ChatRequest


def render_quality_verifier_steering_system_content(steering_message: str) -> str:
    """Return system-role text for a steering note (template + fallback)."""
    msg = (steering_message or "").strip()
    if not msg:
        return ""

    try:
        from src.core.services.quality_verifier_service import (
            get_quality_verifier_prompt_loader,
        )

        template = get_quality_verifier_prompt_loader().steering_template
        return template.format(quality_verifier_steering_message=msg)
    except Exception:
        return "[SYSTEM MESSAGE: QUALITY VERIFIER STEERING]\n\n" + msg


def append_quality_verifier_steering_system_message(
    request: ChatRequest, steering_message: str
) -> ChatRequest:
    """Return a copy of ``request`` with steering appended as a final system message."""
    rendered = render_quality_verifier_steering_system_content(steering_message)
    if not rendered:
        return request
    steering_chat = ChatMessage(role="system", content=rendered)
    new_messages = [*list(request.messages or []), steering_chat]
    return request.model_copy(update={"messages": new_messages})
