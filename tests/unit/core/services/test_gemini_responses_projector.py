"""Unit tests for Gemini Responses backend projector."""

from __future__ import annotations

import pytest
from src.core.common.exceptions import ResponsesProviderLimitationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)
from src.core.services.gemini_responses_projector import GeminiResponsesProjector


class TestGeminiResponsesProjectorContents:
    def test_projects_message_items_to_contents_and_system_instruction(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
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
        payload, flags = GeminiResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert payload["model"] == "gemini-2.0-flash"
        assert payload["systemInstruction"] == {
            "parts": [{"text": "You are helpful."}],
        }
        assert payload["generationConfig"]["temperature"] == 0.2
        assert "stream" not in payload
        assert payload["contents"] == [
            {"role": "user", "parts": [{"text": "hello"}]},
        ]
        assert "input" not in payload
        assert "instructions" not in payload

    def test_maps_function_call_and_output_parts(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            input=[
                ResponsesInputItem(
                    type="message",
                    role="user",
                    content=[ResponsesContentPart(type="input_text", text="run tool")],
                ),
                ResponsesInputItem(
                    type="function_call",
                    call_id="call_1",
                    name="do_thing",
                    arguments='{"a": 1}',
                ),
                ResponsesInputItem(
                    type="function_call_output",
                    call_id="call_1",
                    output='{"ok": true}',
                ),
            ],
        )
        payload, flags = GeminiResponsesProjector().project(req, prior_items=None)
        assert flags == []
        contents = payload["contents"]
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"
        assert contents[1]["parts"] == [
            {"functionCall": {"name": "do_thing", "args": {"a": 1}, "id": "call_1"}},
        ]
        assert contents[2]["role"] == "user"
        fr = contents[2]["parts"][0]["functionResponse"]
        assert fr["name"] == "do_thing"
        assert fr["id"] == "call_1"
        assert fr["response"] == {"ok": True}

    def test_injects_prior_output_items_before_current_input(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
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
        payload, flags = GeminiResponsesProjector().project(req, prior_items=prior)
        assert flags == []
        assert payload["contents"][0] == {
            "role": "model",
            "parts": [{"text": "prior reply"}],
        }
        assert payload["contents"][1]["role"] == "user"
        assert payload["contents"][1]["parts"][0]["text"] == "next"

    def test_prior_function_call_maps_to_function_call_part(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
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
        payload, _ = GeminiResponsesProjector().project(req, prior_items=prior)
        assert payload["contents"] == [
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "fn",
                            "args": {},
                            "id": "call_abc",
                        },
                    },
                ],
            },
        ]

    def test_maps_max_output_tokens_to_generation_config(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            input=[],
            max_output_tokens=900,
        )
        payload, flags = GeminiResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert payload["generationConfig"]["maxOutputTokens"] == 900

    def test_converts_openai_tools_to_gemini_function_declarations(self) -> None:
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
            model="gemini-2.0-flash",
            input=[],
            tools=tools,
        )
        payload, flags = GeminiResponsesProjector().project(req, prior_items=None)
        assert flags == []
        assert "tools" in payload
        decls = payload["tools"][0]["function_declarations"]
        assert decls[0]["name"] == "get_weather"
        assert decls[0]["description"] == "Weather tool"


class TestGeminiResponsesProjectorUnsupported:
    def test_conversation_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            conversation={"id": "conv_1"},
            input=[],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            GeminiResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "conversation"

    def test_include_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            input=[],
            include=["reasoning.encrypted_content"],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            GeminiResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "include"

    def test_unknown_input_item_type_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            input=[
                ResponsesInputItem(type="reasoning", role="assistant", content=None),
            ],
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            GeminiResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "input_item.reasoning"

    def test_pydantic_extra_field_raises(self) -> None:
        req = ResponsesDomainRequest.model_validate(
            {
                "model": "gemini-2.0-flash",
                "input": [],
                "unknown_future_field": {"a": 1},
            }
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            GeminiResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "unknown_future_field"

    def test_extra_body_unknown_key_raises(self) -> None:
        req = ResponsesDomainRequest(
            model="gemini-2.0-flash",
            input=[],
            extra_body={"not_a_gemini_key": True},
        )
        with pytest.raises(ResponsesProviderLimitationError) as exc:
            GeminiResponsesProjector().project(req, prior_items=None)
        assert exc.value.feature == "extra_body.not_a_gemini_key"
