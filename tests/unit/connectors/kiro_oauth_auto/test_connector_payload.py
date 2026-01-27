from __future__ import annotations

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.kiro_oauth_auto.connector import KiroOAuthAutoConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    MessageContentPartText,
    ToolCall,
)
from src.core.services.translation_service import TranslationService


def test_build_payload_includes_tools_and_tool_results() -> None:
    connector = KiroOAuthAutoConnector(
        client=None,  # type: ignore[arg-type]
        config=AppConfig({}),
        translation_service=TranslationService(),
    )

    messages = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(
            role="assistant",
            content="Hi",
            tool_calls=[
                ToolCall(
                    id="t1",
                    type="function",
                    function=FunctionCall(name="do_thing", arguments='{"x":1}'),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="t1", content="ok"),
        ChatMessage(role="user", content="Do thing"),
    ]

    canonical = CanonicalChatRequest(
        model="claude-sonnet-4.5",
        stream=True,
        session_id="s1",
        messages=messages,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "do_thing",
                    "description": "Do a thing",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                    },
                },
            }
        ],
        temperature=0.7,
        top_p=0.9,
        max_completion_tokens=123,
        system_prompt="SYS",
    )

    request = ConnectorChatCompletionsRequest(
        request=canonical,
        processed_messages=messages,
        effective_model="claude-sonnet-4.5",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )

    payload = connector._build_payload(request, effective_model="claude-sonnet-4.5")  # type: ignore[attr-defined]
    current = payload["conversationState"]["currentMessage"]["userInputMessage"]

    assert current["modelId"] == "claude-sonnet-4.5"
    ctx = current["userInputMessageContext"]
    assert len(ctx["tools"]) == 1
    assert ctx["tools"][0]["toolSpecification"]["name"] == "do_thing"
    assert len(ctx["toolResults"]) == 1
    assert ctx["toolResults"][0]["toolUseId"] == "t1"
    assert "assistant (tool_call): do_thing" in current["content"]
    assert payload["inferenceConfig"]["maxTokens"] == 123
    assert payload["inferenceConfig"]["temperature"] == 0.7
    assert payload["inferenceConfig"]["topP"] == 0.9


def test_build_payload_flattens_multimodal_text_parts() -> None:
    connector = KiroOAuthAutoConnector(
        client=None,  # type: ignore[arg-type]
        config=AppConfig({}),
        translation_service=TranslationService(),
    )

    messages = [
        ChatMessage(role="system", content=[MessageContentPartText(text="SYS")]),
        ChatMessage(role="user", content=[MessageContentPartText(text="Hello")]),
    ]

    canonical = CanonicalChatRequest(
        model="claude-sonnet-4.5",
        stream=True,
        session_id="s1",
        messages=messages,
        temperature=0.0,
    )

    request = ConnectorChatCompletionsRequest(
        request=canonical,
        processed_messages=messages,
        effective_model="claude-sonnet-4.5",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )

    payload = connector._build_payload(request, effective_model="claude-sonnet-4.5")  # type: ignore[attr-defined]
    current = payload["conversationState"]["currentMessage"]["userInputMessage"]
    assert isinstance(current["content"], str)
    assert "system: SYS" in current["content"]
    assert "user: Hello" in current["content"]
