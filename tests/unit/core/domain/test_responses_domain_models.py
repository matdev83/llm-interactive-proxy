"""Tests for Responses API domain models (typed input/output items)."""

import pytest
from pydantic import ValidationError
from src.core.domain.responses_domain import (
    ResponsesContentPart,
    ResponsesDomainRequest,
    ResponsesInputItem,
    ResponsesOutputItem,
)


class TestResponsesDomainRequest:
    def test_preserves_input_item_list_structure(self) -> None:
        items = [
            ResponsesInputItem(
                type="message",
                role="user",
                content=[
                    ResponsesContentPart(type="input_text", text="hello"),
                ],
            ),
            ResponsesInputItem(
                type="function_call_output",
                call_id="call_1",
                output='{"ok": true}',
            ),
        ]
        req = ResponsesDomainRequest(model="gpt-4.1", input=items)
        assert len(req.input) == 2
        assert req.input[0].type == "message"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content[0].text == "hello"
        assert req.input[1].type == "function_call_output"
        assert req.input[1].output == '{"ok": true}'

    def test_frozen_model_cannot_mutate(self) -> None:
        req = ResponsesDomainRequest(model="m")
        with pytest.raises(ValidationError):
            req.model = "x"  # type: ignore[misc]

    def test_conversation_mutually_exclusive_with_previous_response_id(self) -> None:
        with pytest.raises(ValidationError):
            ResponsesDomainRequest(
                model="m",
                previous_response_id="resp_1",
                conversation="conv_1",
            )

    def test_accepts_extra_standard_parameters(self) -> None:
        req = ResponsesDomainRequest.model_validate(
            {
                "model": "m",
                "input": [],
                "top_p": 0.9,
                "unknown_future_field": {"a": 1},
            }
        )
        assert req.top_p == 0.9
        extra = getattr(req, "__pydantic_extra__", None) or {}
        assert extra.get("unknown_future_field") == {"a": 1}


class TestResponsesOutputItem:
    def test_roundtrip_tool_fields(self) -> None:
        item = ResponsesOutputItem(
            id="item_1",
            type="function_call",
            status="completed",
            call_id="call_x",
            name="do_thing",
            arguments="{}",
        )
        assert item.call_id == "call_x"
        assert item.name == "do_thing"
