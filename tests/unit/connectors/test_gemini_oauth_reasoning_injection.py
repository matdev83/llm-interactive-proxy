"""Tests for reasoning prompt injection in ChatRequestPreparer."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.connectors.gemini_base.chat_request_preparer import ChatRequestPreparer


class _FakeBackendSettings:
    """Minimal stand-in for BackendSettings for testing."""

    def __init__(self, *, disable_reasoning_injection: bool = False) -> None:
        self.disable_gemini_oauth_reasoning_prompt_injection: bool = (
            disable_reasoning_injection
        )


class _FakeConfig:
    """Minimal AppConfig stand-in."""

    def __init__(self, *, disable_reasoning_injection: bool = False) -> None:
        self.backends: _FakeBackendSettings = _FakeBackendSettings(
            disable_reasoning_injection=disable_reasoning_injection
        )


def _make_connector_context(
    *, backend_type: str = "gemini-oauth-auto", disable_injection: bool = False
) -> MagicMock:
    """Create a mock connector context with the given backend_type and config."""
    ctx = MagicMock()
    ctx.backend_type = backend_type
    ctx.config = _FakeConfig(disable_reasoning_injection=disable_injection)
    return ctx


def _make_code_assist_request(
    contents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a minimal code_assist_request dict."""
    if contents is None:
        contents = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi there!"}]},
        ]
    return {"contents": contents, "generationConfig": {}}


class TestReasoningPromptInjection:
    """Test _inject_reasoning_prompt_if_applicable method."""

    def _make_preparer(
        self,
        *,
        backend_type: str = "gemini-oauth-auto",
        disable_injection: bool = False,
    ) -> ChatRequestPreparer:
        ctx = _make_connector_context(
            backend_type=backend_type, disable_injection=disable_injection
        )
        preparer = ChatRequestPreparer(
            connector_context=ctx,
            message_converter=MagicMock(),
            prompt_limiter=MagicMock(),
            request_body_builder=MagicMock(),
        )
        return preparer

    def test_injection_enabled_by_default(self) -> None:
        """Test that injection happens by default for gemini-oauth-auto."""
        preparer = self._make_preparer(backend_type="gemini-oauth-auto")
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count + 1
        injected = request["contents"][0]
        assert injected["role"] == "user"
        assert "<system-reminder>" in injected["parts"][0]["text"]
        assert "EFFORT LEVEL: 1.50" in injected["parts"][0]["text"]

    def test_injection_for_gemini_oauth_plan(self) -> None:
        """Test injection also works for gemini-oauth-plan backend type."""
        preparer = self._make_preparer(backend_type="gemini-oauth-plan")
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count + 1

    def test_injection_for_gemini_oauth_free(self) -> None:
        """Test injection also works for gemini-oauth-free backend type."""
        preparer = self._make_preparer(backend_type="gemini-oauth-free")
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count + 1

    def test_injection_disabled_via_config(self) -> None:
        """Test that injection is skipped when disabled via config."""
        preparer = self._make_preparer(
            backend_type="gemini-oauth-auto", disable_injection=True
        )
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count

    def test_no_injection_for_non_oauth_backend(self) -> None:
        """Test that injection is skipped for non-gemini-oauth backends."""
        preparer = self._make_preparer(backend_type="openai")
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count

    def test_no_injection_for_gemini_non_oauth(self) -> None:
        """Test that injection is skipped for gemini (non-oauth) backend."""
        preparer = self._make_preparer(backend_type="gemini")
        request: dict[str, Any] = _make_code_assist_request()
        original_count: int = len(request["contents"])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == original_count

    def test_injected_message_at_position_zero(self) -> None:
        """Test that the injected message is at position 0."""
        preparer = self._make_preparer(backend_type="gemini-oauth-auto")
        original_first_msg: dict[str, Any] = {
            "role": "user",
            "parts": [{"text": "System prompt as user"}],
        }
        request: dict[str, Any] = _make_code_assist_request(
            contents=[
                original_first_msg,
                {"role": "model", "parts": [{"text": "Response"}]},
            ]
        )

        preparer._inject_reasoning_prompt_if_applicable(request)

        # The reasoning prompt should be at index 0
        assert "<system-reminder>" in request["contents"][0]["parts"][0]["text"]
        # The original first message should be at index 1
        assert request["contents"][1] == original_first_msg

    def test_injection_with_empty_contents(self) -> None:
        """Test injection into an empty contents array."""
        preparer = self._make_preparer(backend_type="gemini-oauth-auto")
        request: dict[str, Any] = _make_code_assist_request(contents=[])

        preparer._inject_reasoning_prompt_if_applicable(request)

        assert len(request["contents"]) == 1
        assert "<system-reminder>" in request["contents"][0]["parts"][0]["text"]

    def test_no_config_attribute_still_injects(self) -> None:
        """Test that injection works when config has no backends attribute."""
        ctx = MagicMock()
        ctx.backend_type = "gemini-oauth-auto"
        ctx.config = None  # No config
        preparer = ChatRequestPreparer(
            connector_context=ctx,
            message_converter=MagicMock(),
            prompt_limiter=MagicMock(),
            request_body_builder=MagicMock(),
        )
        request: dict[str, Any] = _make_code_assist_request()

        preparer._inject_reasoning_prompt_if_applicable(request)

        # Should still inject because config=None means no explicit disable
        assert len(request["contents"]) == 3
