"""Unit tests for OpenAI native Responses backend projector."""

from __future__ import annotations

from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)
from src.core.services.openai_responses_projector import OpenAIResponsesProjector


class TestOpenAIResponsesProjector:
    def test_passes_input_instructions_ids_tools_without_flattening(self) -> None:
        items = [
            ResponsesInputItem(
                type="message",
                role="user",
                content=[
                    ResponsesContentPart(type="input_text", text="hi"),
                ],
            ),
            ResponsesInputItem(
                type="function_call_output",
                call_id="call_1",
                output="{}",
            ),
        ]
        tools = [{"type": "function", "name": "fn", "parameters": {"type": "object"}}]
        req = ResponsesDomainRequest(
            model="gpt-4.1",
            input=items,
            instructions="sys",
            previous_response_id="resp_prev",
            tools=tools,
            stream=True,
        )
        projector = OpenAIResponsesProjector()
        payload, capability_flags = projector.project(req, prior_items=None)

        assert capability_flags == []
        assert "messages" not in payload
        assert payload["model"] == "gpt-4.1"
        assert payload["instructions"] == "sys"
        assert payload["previous_response_id"] == "resp_prev"
        assert payload["stream"] is True
        inp = payload["input"]
        assert isinstance(inp, list)
        assert len(inp) == 2
        assert inp[0]["type"] == "message"
        assert inp[0]["role"] == "user"
        assert isinstance(inp[0]["content"], list)
        assert inp[0]["content"][0]["type"] == "input_text"
        assert inp[0]["content"][0]["text"] == "hi"
        assert inp[1]["type"] == "function_call_output"
        assert inp[1]["call_id"] == "call_1"
        assert inp[1]["output"] == "{}"
        assert payload["tools"] == tools

    def test_preserves_passthrough_and_extra_fields(self) -> None:
        req = ResponsesDomainRequest.model_validate(
            {
                "model": "gpt-4.1",
                "input": [],
                "include": ["reasoning.encrypted_content"],
                "max_tool_calls": 3,
                "prompt": {"id": "pmpt_1", "version": "2"},
                "prompt_cache_key": "k1",
                "prompt_cache_retention": "in_memory",
                "service_tier": "priority",
                "truncation": "auto",
                "store": False,
                "extra_body": {"metadata": {"a": "b"}, "safety_identifier": "sid"},
            }
        )
        projector = OpenAIResponsesProjector()
        payload, capability_flags = projector.project(req, prior_items=None)

        assert capability_flags == []
        assert payload["include"] == ["reasoning.encrypted_content"]
        assert payload["max_tool_calls"] == 3
        assert payload["prompt"] == {"id": "pmpt_1", "version": "2"}
        assert payload["prompt_cache_key"] == "k1"
        assert payload["prompt_cache_retention"] == "in_memory"
        assert payload["service_tier"] == "priority"
        assert payload["truncation"] == "auto"
        assert payload["store"] is False
        assert payload["metadata"] == {"a": "b"}
        assert payload["safety_identifier"] == "sid"
        assert "extra_body" not in payload

    def test_conversation_passes_through(self) -> None:
        req = ResponsesDomainRequest(
            model="gpt-4.1",
            conversation={"id": "conv_1"},
            input=[],
        )
        payload, capability_flags = OpenAIResponsesProjector().project(
            req, prior_items=None
        )
        assert capability_flags == []
        assert payload["conversation"] == {"id": "conv_1"}

    def test_prior_items_do_not_flatten_into_messages(self) -> None:
        req = ResponsesDomainRequest(
            model="gpt-4.1",
            input=[
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[ResponsesContentPart(type="input_text", text="x")],
                )
            ],
        )
        prior = [
            ResponsesOutputItem(
                id="out_1",
                type="message",
                status="completed",
                role="assistant",
                content=[ResponsesContentPart(type="output_text", text="prior")],
            )
        ]
        payload, _ = OpenAIResponsesProjector().project(req, prior_items=prior)
        assert "messages" not in payload
        assert len(payload["input"]) == 1
        assert payload["input"][0]["content"][0]["text"] == "x"
