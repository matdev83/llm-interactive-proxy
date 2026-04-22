"""Unit tests for ResponsesRequestNormalizer."""

import pytest
from src.core.common.exceptions import ResponsesValidationError
from src.core.domain.responses_request_normalizer import ResponsesRequestNormalizer


class TestResponsesRequestNormalizer:
    def test_valid_minimal(self) -> None:
        raw = {"model": "gpt-4.1"}
        req = ResponsesRequestNormalizer().normalize(raw)
        assert req.model == "gpt-4.1"
        assert req.input == []

    def test_valid_array_input_items_preserved(self) -> None:
        raw = {
            "model": "gpt-4.1",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                },
                {"type": "function_call_output", "call_id": "c1", "output": "{}"},
            ],
            "instructions": "sys",
            "stream": True,
            "temperature": 0.2,
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 2
        assert req.input[0].type == "message"
        assert req.input[0].role == "user"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content is not None
        assert req.input[0].content[0].type == "input_text"
        assert req.input[0].content[0].text == "hi"
        assert req.input[1].type == "function_call_output"
        assert req.input[1].call_id == "c1"
        assert req.instructions == "sys"
        assert req.stream is True
        assert req.temperature == 0.2

    def test_array_input_chat_message_shorthand_is_normalized(self) -> None:
        raw = {
            "model": "gpt-4.1",
            "input": [
                {"role": "developer", "content": "Follow repo rules."},
                {"role": "user", "content": "hi"},
            ],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 2
        assert req.input[0].type == "message"
        assert req.input[0].role == "developer"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content is not None
        assert req.input[0].content[0].type == "input_text"
        assert req.input[0].content[0].text == "Follow repo rules."
        assert req.input[1].type == "message"
        assert req.input[1].role == "user"

    def test_array_input_shorthand_dict_content_part_preserves_text(self) -> None:
        """Shorthand messages may send a single content part as an object; do not drop it."""
        raw = {
            "model": "gpt-4.1",
            "input": [
                {
                    "role": "user",
                    "content": {"type": "input_text", "text": "from-dict-part"},
                },
            ],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 1
        assert req.input[0].type == "message"
        assert req.input[0].role == "user"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content is not None
        assert req.input[0].content[0].type == "input_text"
        assert req.input[0].content[0].text == "from-dict-part"

    def test_single_dict_chat_message_shorthand_is_normalized(self) -> None:
        raw = {
            "model": "gpt-4.1",
            "input": {"role": "developer", "content": "Stay concise."},
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 1
        assert req.input[0].type == "message"
        assert req.input[0].role == "developer"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content is not None
        assert req.input[0].content[0].type == "input_text"
        assert req.input[0].content[0].text == "Stay concise."

    def test_string_input_shorthand(self) -> None:
        raw = {"model": "gpt-4.1", "input": "hello"}
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 1
        assert req.input[0].type == "message"
        assert req.input[0].role == "user"
        assert isinstance(req.input[0].content, list)
        assert req.input[0].content is not None
        assert req.input[0].content[0].type == "input_text"
        assert req.input[0].content[0].text == "hello"

    def test_missing_model(self) -> None:
        with pytest.raises(ResponsesValidationError) as exc_info:
            ResponsesRequestNormalizer().normalize({"input": "x"})
        assert exc_info.value.param == "model"
        assert exc_info.value.code == "missing_required_parameter"

    def test_empty_model(self) -> None:
        with pytest.raises(ResponsesValidationError) as exc_info:
            ResponsesRequestNormalizer().normalize({"model": "", "input": "x"})
        assert exc_info.value.param == "model"

    def test_previous_response_id_and_conversation_mutually_exclusive(self) -> None:
        raw = {
            "model": "m",
            "previous_response_id": "resp_1",
            "conversation": "conv_1",
        }
        with pytest.raises(ResponsesValidationError) as exc_info:
            ResponsesRequestNormalizer().normalize(raw)
        assert exc_info.value.param in {"previous_response_id", "conversation", None}

    def test_messages_and_input_both_provided(self) -> None:
        raw = {
            "model": "m",
            "messages": [{"role": "user", "content": "a"}],
            "input": [{"type": "message", "role": "user", "content": "b"}],
        }
        with pytest.raises(ResponsesValidationError) as exc_info:
            ResponsesRequestNormalizer().normalize(raw)
        assert (
            "messages" in exc_info.value.message.lower()
            or "input" in exc_info.value.message.lower()
        )
        assert exc_info.value.param == "input"
        assert exc_info.value.code == "invalid_request_error"

    def test_empty_messages_with_string_input_rejected(self) -> None:
        raw = {"model": "m", "messages": [], "input": "hello"}
        with pytest.raises(ResponsesValidationError) as exc_info:
            ResponsesRequestNormalizer().normalize(raw)
        assert exc_info.value.param == "input"
        assert exc_info.value.code == "invalid_request_error"

    def test_single_dict_input_wrapped_as_one_item(self) -> None:
        raw = {
            "model": "m",
            "input": {"type": "message", "role": "user", "content": "plain"},
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 1
        assert req.input[0].content == "plain"

    def test_invalid_input_type(self) -> None:
        raw = {"model": "m", "input": 123}
        with pytest.raises(ResponsesValidationError):
            ResponsesRequestNormalizer().normalize(raw)

    def test_does_not_mutate_raw_dict(self) -> None:
        raw: dict = {"model": "m", "input": "hello"}
        ResponsesRequestNormalizer().normalize(raw)
        assert raw["input"] == "hello"

    def test_stream_null_uses_default_false(self) -> None:
        raw = {"model": "m", "input": "hello", "stream": None}
        req = ResponsesRequestNormalizer().normalize(raw)
        assert req.stream is False
