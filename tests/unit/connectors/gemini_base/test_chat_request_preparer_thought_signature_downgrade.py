"""Tests for tool call downgrade when thought_signature is missing.

Vertex Code Assist rejects requests that contain functionCall parts without a
`thought_signature`. This can happen when switching from a non-Gemini backend
mid-session (tool calls exist in history but cannot have Google signatures).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.connectors.gemini_base.chat_request_preparer import ChatRequestPreparer
from src.connectors.gemini_base.connector_context import (
    IConnectorContext,
    IMessageConverter,
    IPromptLimiter,
    IRequestBodyBuilder,
)
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    ToolCall,
)


class MockConnectorContext(IConnectorContext):
    def __init__(self) -> None:
        self._creds = {"access_token": "fake-token"}

    async def _refresh_token_if_needed(
        self, *, force_reload: bool = False, session_id: str | None = None
    ) -> bool:
        return True

    @property
    def _oauth_credentials(self):
        return self._creds

    def _get_session_headers(self):
        return {}

    async def _discover_project_id(self, auth_session):
        return "fake-project"


class MockMessageConverter(IMessageConverter):
    def _convert_system_messages_for_code_assist(self, gemini_request):
        return gemini_request.get("contents", [])

    def _build_code_assist_request(self, gemini_request, final_contents):
        return {"contents": final_contents}

    def _sanitize_code_assist_tools(self, canonical_request, code_assist_request):
        pass


class MockPromptLimiter(IPromptLimiter):
    def _estimate_prompt_tokens(self, code_assist_request):
        return 100

    def _enforce_prompt_limit(self, prompt_tokens, effective_model, *, request_id=None):
        pass


class MockRequestBodyBuilder(IRequestBodyBuilder):
    def _build_code_assist_request_body(
        self, effective_model, project_id, request_data, code_assist_request
    ):
        return {"request": code_assist_request}


@pytest.mark.asyncio
async def test_prepare_downgrades_tool_calls_without_thought_signature() -> None:
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()

    def capture(canonical_request: CanonicalChatRequest):
        # Tool calls should be stripped
        assert canonical_request.messages[1].role == "assistant"
        assert canonical_request.messages[1].tool_calls is None
        # Downgrade must not inject protocol-looking or loop-inducing transcript text.
        assistant_text = str(canonical_request.messages[1].content)
        assert "tool_call:" not in assistant_text
        assert "Downgraded tool call" not in assistant_text
        assert "TOOL INVOCATION" not in assistant_text
        # Tool message should be converted to user text
        assert canonical_request.messages[2].role == "user"
        assert "tool_call_id=t1" in str(canonical_request.messages[2].content)
        return {"contents": [{"parts": [{"text": "ok"}]}]}

    translation_service.from_domain_to_gemini_request = MagicMock(side_effect=capture)

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    request_data = CanonicalChatRequest(
        model="gemini-3-flash-preview",
        stream=True,
        session_id="s1",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="doing tool",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        type="function",
                        function=FunctionCall(name="list_files", arguments="{}"),
                    )
                ],
            ),
            ChatMessage(role="tool", tool_call_id="t1", content="result"),
        ],
    )

    await preparer.prepare(
        request_data=request_data, effective_model="gemini-3-flash-preview"
    )


@pytest.mark.asyncio
async def test_prepare_keeps_tool_calls_with_signatures_and_downgrades_only_missing() -> (
    None
):
    context = MockConnectorContext()
    converter = MockMessageConverter()
    limiter = MockPromptLimiter()
    builder = MockRequestBodyBuilder()

    translation_service = MagicMock()

    def capture(canonical_request: CanonicalChatRequest):
        roles = [m.role for m in canonical_request.messages]
        assert roles == ["user", "assistant", "assistant", "user", "tool"]

        # Descriptive content preserved as text-only assistant message.
        assert canonical_request.messages[1].tool_calls is None
        assert str(canonical_request.messages[1].content) == "doing tool"

        # Only the signed tool call remains.
        assert canonical_request.messages[2].tool_calls is not None
        assert len(canonical_request.messages[2].tool_calls) == 1
        assert canonical_request.messages[2].content is None
        assert canonical_request.messages[2].tool_calls[0].id == "t2"

        # Unsigned tool response is converted to user text.
        assert canonical_request.messages[3].role == "user"
        assert "tool_call_id=t1" in str(canonical_request.messages[3].content)

        # Signed tool response remains structured.
        assert canonical_request.messages[4].role == "tool"
        assert canonical_request.messages[4].tool_call_id == "t2"
        return {"contents": [{"parts": [{"text": "ok"}]}]}

    translation_service.from_domain_to_gemini_request = MagicMock(side_effect=capture)

    preparer = ChatRequestPreparer(
        connector_context=context,
        message_converter=converter,
        prompt_limiter=limiter,
        request_body_builder=builder,
        translation_service=translation_service,
    )

    request_data = CanonicalChatRequest(
        model="gemini-3-flash-preview",
        stream=True,
        session_id="s1",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="doing tool",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        type="function",
                        function=FunctionCall(name="list_files", arguments="{}"),
                    ),
                    ToolCall(
                        id="t2",
                        type="function",
                        function=FunctionCall(name="read", arguments="{}"),
                        extra_content={"google": {"thought_signature": "sig-1"}},
                    ),
                ],
            ),
            ChatMessage(role="tool", tool_call_id="t1", content="result-one"),
            ChatMessage(role="tool", tool_call_id="t2", content="result-two"),
        ],
    )

    await preparer.prepare(
        request_data=request_data, effective_model="gemini-3-flash-preview"
    )
