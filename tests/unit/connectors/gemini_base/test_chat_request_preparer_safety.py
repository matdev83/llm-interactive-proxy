"""
Tests for ChatRequestPreparer safety nets.

Tests ensure that:
- Empty tools/toolConfig are stripped from the final request body.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.gemini_base.chat_request_preparer import ChatRequestPreparer
from src.connectors.gemini_base.connector_context import (
    IConnectorContext,
    IMessageConverter,
    IPromptLimiter,
    IRequestBodyBuilder,
)


class MockConnectorContext(IConnectorContext):
    def __init__(self):
        self._creds = {"access_token": "fake-token"}
        self._refresh_token_if_needed_mock = AsyncMock(return_value=True)

    @property
    def _oauth_credentials(self):
        return self._creds

    def _get_session_headers(self) -> dict[str, str]:
        return {}

    async def _discover_project_id(self, auth_session):
        return "fake-project"

    async def _refresh_token_if_needed(
        self, *, force_reload: bool = False, session_id: str | None = None
    ) -> bool:
        result = await self._refresh_token_if_needed_mock(
            force_reload=force_reload, session_id=session_id
        )
        return bool(result)


class MockMessageConverter(IMessageConverter):
    def _convert_system_messages_for_code_assist(self, gemini_request):
        return gemini_request.get("contents", [])

    def _build_code_assist_request(self, gemini_request, final_contents):
        # Return a request that HAS empty tools to test stripping
        return {"contents": final_contents, "tools": {}, "toolConfig": {}}

    def _sanitize_code_assist_tools(self, canonical_request, code_assist_request):
        # Simulate sanitizer NOT removing them (worst case)
        pass


class MockPromptLimiter(IPromptLimiter):
    def __init__(self):
        self.last_enforced_tokens: int | None = None

    def _estimate_prompt_tokens(self, code_assist_request):
        return 100

    def _enforce_prompt_limit(self, prompt_tokens, effective_model, *, request_id=None):
        self.last_enforced_tokens = prompt_tokens


class MockRequestBodyBuilder(IRequestBodyBuilder):
    def _build_code_assist_request_body(
        self, effective_model, project_id, request_data, code_assist_request
    ):
        # Return the code_assist_request as part of the body
        return {"request": code_assist_request}


@pytest.mark.asyncio
async def test_prepare_strips_empty_tools_safety_net() -> None:
    """Test that build_request_body strips empty tools even if other components leave them."""
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    # Mock translation service return
    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": [{"parts": [{"text": "test"}]}]}
    )

    request_data = MagicMock()
    request_data.session_id = "test-session"

    prepared = await preparer.prepare(request_data, "gemini-2.5-flash")

    # Execute the build_request_body closure
    final_body = prepared.build_request_body()

    # Assert tools/toolConfig are GONE
    code_assist_req = final_body["request"]
    assert "tools" not in code_assist_req
    assert "toolConfig" not in code_assist_req


@pytest.mark.asyncio
async def test_prepare_uses_higher_fallback_prompt_estimate() -> None:
    """Enforce prompt limit with the larger fallback estimate when needed."""
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()
    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    translation_service.from_domain_to_gemini_request = MagicMock(
        return_value={"contents": [{"parts": [{"text": "small"}]}]}
    )

    request_data = MagicMock()
    request_data.session_id = "test-session"

    with patch(
        "src.connectors.gemini_base.chat_request_preparer.calculate_outbound_tokens",
        return_value=4321,
    ):
        prepared = await preparer.prepare(request_data, "gemini-2.5-flash")

    assert prepared.prompt_tokens_estimate == 4321
    assert limiter.last_enforced_tokens == 4321
