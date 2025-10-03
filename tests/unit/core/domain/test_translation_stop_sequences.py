"""Regression tests for Gemini stop sequence handling."""

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.translation import Translation


def test_stop_sequence_string_is_wrapped_in_list() -> None:
    """Ensure Gemini translation wraps single stop strings in a list."""

    request = CanonicalChatRequest(
        model="gemini-1.5-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stop="FINISH",
    )

    gemini_request = Translation.from_domain_to_gemini_request(request)

    assert gemini_request["generationConfig"]["stopSequences"] == ["FINISH"]
