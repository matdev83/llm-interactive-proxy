import json
from datetime import datetime
from typing import Any, cast

import pytest
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
    FunctionCall,
    ToolCall,
)
from src.core.services.response_parser_service import ParsingError, ResponseParser


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
                '[{"id": "call_1", "type": "function", "function": {"name": "func", "arguments": "{}"}}]',
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
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
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
                    "created": datetime.utcfromtimestamp(1678886400).isoformat(
                        timespec="seconds"
                    ),
                },
            ),
            (
                {"model": "dict_model", "id": "dict_id", "created": 1678886400},
                {
                    "model": "dict_model",
                    "id": "dict_id",
                    "created": datetime.utcfromtimestamp(1678886400).isoformat(
                        timespec="seconds"
                    ),
                },
            ),
            ("string", {}),
            (
                {},
                {
                    "model": "unknown",
                    "id": "",
                    "created": datetime.utcfromtimestamp(0).isoformat(
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
                    "created": datetime.utcfromtimestamp(123).isoformat(
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
