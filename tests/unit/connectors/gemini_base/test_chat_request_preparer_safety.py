"""
Tests for ChatRequestPreparer safety nets.

Tests ensure that:
- Empty tools/toolConfig are stripped from the final request body.
"""

from unittest.mock import AsyncMock, MagicMock

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
        self._get_session_headers = dict
        self._refresh_token_if_needed = AsyncMock(return_value=True)
        self._discover_project_id = AsyncMock(return_value="fake-project")

    @property
    def _oauth_credentials(self):
        return self._creds

class MockMessageConverter(IMessageConverter):
    def _convert_system_messages_for_code_assist(self, request):
        return request.get("contents", [])
    
    def _build_code_assist_request(self, gemini_request, contents):
        # Return a request that HAS empty tools to test stripping
        return {
            "contents": contents,
            "tools": {},
            "toolConfig": {}
        }
    
    def _sanitize_code_assist_tools(self, canonical, request):
        # Simulate sanitizer NOT removing them (worst case)
        pass

class MockPromptLimiter(IPromptLimiter):
    def _estimate_prompt_tokens(self, request):
        return 100
    
    def _enforce_prompt_limit(self, tokens, model, request_id=None):
        pass

class MockRequestBodyBuilder(IRequestBodyBuilder):
    def _build_code_assist_request_body(self, effective_model, project_id, request_data, code_assist_request):
        # Return the code_assist_request as part of the body
        return {
            "request": code_assist_request
        }

@pytest.mark.asyncio
async def test_prepare_strips_empty_tools_safety_net() -> None:
    """Test that build_request_body strips empty tools even if other components leave them."""
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()
    
    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=MagicMock(), # Mock translation service
    )
    
    # Mock translation service return
    preparer._translation_service.from_domain_to_gemini_request = MagicMock(return_value={
        "contents": [{"parts": [{"text": "test"}]}]
    })
    
    request_data = MagicMock()
    request_data.session_id = "test-session"
    
    prepared = await preparer.prepare(request_data, "gemini-2.5-flash")
    
    # Execute the build_request_body closure
    final_body = prepared.build_request_body()
    
    # Assert tools/toolConfig are GONE
    code_assist_req = final_body["request"]
    assert "tools" not in code_assist_req
    assert "toolConfig" not in code_assist_req
