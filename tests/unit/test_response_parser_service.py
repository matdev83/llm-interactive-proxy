import json
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from src.core.common.exceptions import ParsingError
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
    FunctionCall,
    ToolCall,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.services.response_parser_service import ResponseParser


class TestResponseParser:
    @pytest.fixture
    def parser(self) -> ResponseParser:
        return ResponseParser()

    # Test cases for parse_response
    @pytest.mark.parametrize(
        "raw_response,expected_type",
        [
            (
                ChatResponse(
                    id="test",
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant", content="hello"
                            ),
                        )
                    ],
                    created=123,
                    model="gpt-4",
                ),
                dict,
            ),
            ({"choices": [{"message": {"content": "test"}}]}, dict),
            ("just a string", dict),
        ],
    )
    def test_parse_response_valid_types(
        self,
        parser: ResponseParser,
        raw_response: ChatResponse | dict | str,
        expected_type: type,
    ) -> None:
        parsed_data = parser.parse_response(raw_response)
        assert isinstance(parsed_data, expected_type)

    def test_parse_response_unsupported_type(self, parser: ResponseParser) -> None:
        class UnsupportedType:
            pass

        with pytest.raises(ParsingError, match="Unsupported response type"):
            parser.parse_response(cast(Any, UnsupportedType()))

    # Test cases for extract_content
    @pytest.mark.parametrize(
        "raw_response,expected_content",
        [
            (
                ChatResponse(
                    id="test",
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant", content="hello"
                            ),
                        )
                    ],
                    created=123,
                    model="gpt-4",
                ),
                "hello",
            ),
            ({"choices": [{"message": {"content": "test"}}]}, "test"),
            ("just a string", "just a string"),
            (
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "func", "arguments": "{}"},
                                    }
                                ]
                            }
                        }
                    ]
                },
                "",  # tool_calls are stored in metadata, not content; extract_content returns empty
            ),
            (
                {"error": "some error"},
                '{"error": "some error"}',
            ),  # Should convert non-chat dict to JSON string
            (None, ""),  # Handle None parsed data gracefully
            (
                ChatResponse(id="test", choices=[], created=123, model="gpt-4"),
                "",
            ),  # No choices
            (
                ChatResponse(
                    id="test",
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant", content=None
                            ),
                        )
                    ],
                    created=123,
                    model="gpt-4",
                ),
                "",
            ),  # None content
        ],
    )
    def test_extract_content(
        self,
        parser: ResponseParser,
        raw_response: ChatResponse | dict | str | None,
        expected_content: str,
    ) -> None:
        parsed_data = parser.parse_response(raw_response)
        content = parser.extract_content(parsed_data)
        assert content == expected_content

    # Test cases for extract_usage
    @pytest.mark.parametrize(
        "raw_response,expected_usage",
        [
            (
                ChatResponse(
                    id="test",
                    choices=[],
                    created=123,
                    model="gpt-4",
                    usage=UsageSummary.from_dict(
                        {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        }
                    ),
                ),
                {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            ),
            (
                {
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 10,
                        "total_tokens": 15,
                    }
                },
                {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            ),
            ("string", None),
            ({}, None),
            (
                ChatResponse(id="test", choices=[], created=123, model="gpt-4"),
                None,
            ),  # No usage
        ],
    )
    def test_extract_usage(
        self,
        parser: ResponseParser,
        raw_response: ChatResponse | dict | str | None,
        expected_usage: dict | None,
    ) -> None:
        parsed_data = parser.parse_response(raw_response)
        usage = parser.extract_usage(parsed_data)
        assert usage == expected_usage

    # Test cases for extract_metadata
    @pytest.mark.parametrize(
        "raw_response,expected_metadata",
        [
            (
                ChatResponse(
                    id="test_id", choices=[], created=1678886400, model="test_model"
                ),
                {
                    "model": "test_model",
                    "id": "test_id",
                    "created": datetime.fromtimestamp(
                        1678886400, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                },
            ),
            (
                {"model": "dict_model", "id": "dict_id", "created": 1678886400},
                {
                    "model": "dict_model",
                    "id": "dict_id",
                    "created": datetime.fromtimestamp(
                        1678886400, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                },
            ),
            ("string", {}),
            (
                {},
                {
                    "model": "unknown",
                    "id": "",
                    "created": datetime.fromtimestamp(0, tz=timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                },
            ),
            (
                ChatResponse(
                    id="test",
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant",
                                content="hello",
                                tool_calls=[
                                    ToolCall(
                                        id="call1",
                                        function=FunctionCall(
                                            name="func", arguments="{}"
                                        ),
                                    )
                                ],
                            ),
                        )
                    ],
                    created=123,
                    model="gpt-4",
                ),
                {
                    "model": "gpt-4",
                    "id": "test",
                    "created": datetime.fromtimestamp(123, tz=timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "tool_calls": [
                        {
                            "id": "call1",
                            "type": "function",
                            "function": {"name": "func", "arguments": "{}"},
                        }
                    ],
                },
            ),
        ],
    )
    def test_extract_metadata(
        self,
        parser: ResponseParser,
        raw_response: ChatResponse | dict | str,
        expected_metadata: dict,
    ) -> None:
        parsed_data: dict[str, Any] = parser.parse_response(raw_response)
        metadata = parser.extract_metadata(parsed_data)
        assert metadata is not None
        assert metadata == expected_metadata

    def test_extract_metadata_tool_calls_empty(self, parser: ResponseParser) -> None:
        raw_response = ChatResponse(
            id="test",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content="hello", tool_calls=[]
                    ),
                )
            ],
            created=123,
            model="gpt-4",
        )
        parsed_data = parser.parse_response(raw_response)
        metadata = parser.extract_metadata(parsed_data)
        assert metadata is not None and "tool_calls" not in metadata

    def test_extract_metadata_tool_calls_none(self, parser: ResponseParser) -> None:
        raw_response = ChatResponse(
            id="test",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content="hello", tool_calls=None
                    ),
                )
            ],
            created=123,
            model="gpt-4",
        )
        parsed_data = parser.parse_response(raw_response)
        metadata = parser.extract_metadata(parsed_data)
        assert metadata is not None and "tool_calls" not in metadata

    def test_extract_metadata_dict_tool_calls(self, parser: ResponseParser) -> None:
        raw_response = {
            "choices": [
                {"message": {"content": "test", "tool_calls": [{"id": "call_2"}]}}
            ]
        }
        parsed_data = parser.parse_response(raw_response)
        metadata = parser.extract_metadata(parsed_data)
        assert metadata is not None and metadata["tool_calls"] == [{"id": "call_2"}]

    def test_extract_content_json_string_from_dict(
        self, parser: ResponseParser
    ) -> None:
        data = {"key": "value", "number": 123}
        parsed_data = parser.parse_response(data)
        content = parser.extract_content(parsed_data)
        assert content == json.dumps(data)
        assert isinstance(content, str)

    def test_extract_content_json_string_from_list(
        self, parser: ResponseParser
    ) -> None:
        data = [{"item": 1}, {"item": 2}]
        # Convert the list to a JSON string, as parse_response expects str, dict, or ChatResponse
        raw_response_str = json.dumps(data)
        parsed_data = parser.parse_response(raw_response_str)
        content = parser.extract_content(parsed_data)
        assert content == raw_response_str
        assert isinstance(content, str)

    def test_empty_choices_array_not_serialized(self, parser: ResponseParser) -> None:
        """Test that empty choices array doesn't cause the entire response to be JSON-dumped.

        This tests a bug fix where responses with empty choices (choices: []) were
        incorrectly having their entire body serialized as the content string.
        Empty choices is a valid response indicating no output was generated.
        """
        raw_response = {
            "id": "chatcmpl-test123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [],  # Empty choices array
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        }
        parsed_data = parser.parse_response(raw_response)
        content = parser.extract_content(parsed_data)

        # Content should be empty string, NOT a JSON serialization of the response
        assert content == ""
        # Verify it's not the serialized response
        assert content != json.dumps(raw_response)

    def test_missing_choices_key_serializes_response(
        self, parser: ResponseParser
    ) -> None:
        """Test that responses without a 'choices' key are JSON-serialized.

        This ensures that non-chat-completion responses (like embeddings) are
        still handled by serializing the entire response.
        """
        raw_response = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": "text-embedding-ada-002",
        }
        parsed_data = parser.parse_response(raw_response)
        content = parser.extract_content(parsed_data)

        # When 'choices' key is missing, the entire response should be serialized
        assert content == json.dumps(raw_response)
