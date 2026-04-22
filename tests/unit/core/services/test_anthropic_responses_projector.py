"""Unit tests for Anthropic Responses backend projector."""

from __future__ import annotations

import pytest
from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)
from src.core.services.anthropic_responses_projector import AnthropicResponsesProjector


class TestAnthropicResponsesProjectorMessages:
    def test_projects_message_items_to_messages_and_system(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            instructions="You are helpful.",
            input=[
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[
                        ResponsesContentPart(type="input_text", text="hello"),
                    ],
                ),
            ],
            temperature=0.2,
            stream=True,
        )
        payload, flags = AnthropicResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["system"] == "You are helpful."
        assert payload["temperature"] == 0.2
        assert payload["stream"] is True
        assert payload["messages"] == [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            }
        ]
        assert "input" not in payload
        assert "instructions" not in payload

    def test_preserves_tool_call_linkage(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[ResponsesContentPart(type="input_text", text="run tool")],
                ),
                ResponsesInputItem(
                    type="function_call",
                    call_id="toolu_01",
                    name="do_thing",
                    arguments='{"a": 1}',
                ),
                ResponsesInputItem(
                    type="function_call_output",
                    call_id="toolu_01",
                    output='{"ok": true}',
                ),
            ],
        )
        payload, flags = AnthropicResponsesProjector().project(req, prior_items=None)
        assert flags == []
        msgs = payload["messages"]
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "do_thing",
                "input": {"a": 1},
            }
        ]
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_01",
                "content": '{"ok": true}',
            }
        ]

    def test_injects_prior_output_items_before_current_input(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[ResponsesContentPart(type="input_text", text="next")],
                ),
            ],
        )
        prior = [
            ResponsesOutputItem(
                id="out_1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponsesContentPart(type="output_text", text="prior reply"),
                ],
            ),
        ]
        payload, flags = AnthropicResponsesProjector().project(req, prior_items=prior)
        assert flags == []
        assert payload["messages"][0] == {
            "role": "assistant",
            "content": [{"type": "text", "text": "prior reply"}],
        }
        assert payload["messages"][1]["role"] == "user"
        assert payload["messages"][1]["content"][0]["text"] == "next"

    def test_prior_function_call_maps_to_tool_use(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[],
        )
        prior = [
            ResponsesOutputItem(
                id="fc_1",
                type="function_call",
                status="completed",
                call_id="call_abc",
                name="fn",
                arguments="{}",
            ),
        ]
        payload, _ = AnthropicResponsesProjector().project(req, prior_items=prior)
        assert payload["messages"] == [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_abc",
                        "name": "fn",
                        "input": {},
                    }
                ],
            }
        ]

    def test_maps_max_output_tokens_to_max_tokens(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[],
            max_output_tokens=900,
        )
        payload, flags = AnthropicResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert payload["max_tokens"] == 900
        assert "max_output_tokens" not in payload

    def test_converts_openai_tools_to_anthropic_tool_defs(self) -> None:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Weather tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ]
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[],
            tools=tools,
        )
        payload, flags = AnthropicResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert payload["tools"] == [
            {
                "name": "get_weather",
                "description": "Weather tool",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            }
        ]


class TestAnthropicResponsesProjectorUnsupported:
    def test_conversation_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            conversation={"id": "conv_1"},
            input=[],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            AnthropicResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "conversation"

    def test_include_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[],
            include=["reasoning.encrypted_content"],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            AnthropicResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "include"

    def test_unknown_input_item_type_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="claude-3-5-sonnet-20241022",
            input=[
                ResponsesInputItem(type="reasoning", role="assistant", content=None),
            ],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            AnthropicResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "input_item.reasoning"

    def test_pydantic_extra_field_raises(self) -> None:
        req = ResponsesDomainRequest.model_validate(
            {
                "model": "claude-3-5-sonnet-20241022",
                "input": [],
                "unknown_future_field": {"a": 1},
            }
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            AnthropicResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "unknown_future_field"
