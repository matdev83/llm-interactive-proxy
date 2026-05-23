from __future__ import annotations

import json

import pytest
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.domain.translation import Translation


class TestTranslationEdgeCases:
    def test_malformed_json_in_tool_calls(self):
        """Malformed tool JSON should be sanitized to an empty object."""

        broken_arguments = "{'query': 'weather"  # unterminated string literal

        normalized = Translation.normalize_tool_arguments(broken_arguments)

        assert normalized == "{}"

    def test_invalid_image_urls(self):
        """Non-http/https image URLs should be rejected for Gemini payloads."""

        invalid_part = MessageContentPartImage(
            image_url=ImageURL(url="ftp://example.com/image.png", detail=None)
        )

        assert Translation.process_gemini_image_part(invalid_part) is None

    def test_missing_required_fields(self):
        """Responses payload entries missing a role should default to 'user'."""

        input_payload = [{"content": [{"type": "text", "text": "hello"}]}]

        normalized = Translation.normalize_responses_input_to_messages(input_payload)

        assert normalized == [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
                "content_parts": [{"type": "text", "text": "hello"}],
            }
        ]

    def test_codex_style_user_named_bash_without_content_gets_empty_string(self):
        """Codex/CLI can emit user items with name=bash and no body; downstream expects content."""

        input_payload = [{"role": "user", "name": "bash"}]

        normalized = Translation.normalize_responses_input_to_messages(input_payload)

        assert len(normalized) == 1
        assert normalized[0]["role"] == "user"
        assert normalized[0]["name"] == "bash"
        assert normalized[0]["content"] == ""

    def test_streaming_error_conditions(self):
        """Invalid Gemini streaming chunks should return an explicit error payload."""

        result = Translation.gemini_to_domain_stream_chunk("not a dict")

        assert result == {"error": "Invalid chunk format: expected a dictionary"}

    def test_from_domain_to_openai_request_serializes_multimodal_content(self):
        """Ensure OpenAI payloads include plain multimodal structures."""

        request = CanonicalChatRequest(
            model="gpt-4o-mini",
            messages=[
                ChatMessage(
                    role="user",
                    content=[
                        MessageContentPartText(text="Describe this image"),
                        MessageContentPartImage(
                            image_url=ImageURL(
                                url="https://example.com/cat.png", detail=None
                            )
                        ),
                    ],
                )
            ],
        )

        payload = Translation.from_domain_to_openai_request(request)

        assert payload["model"] == "gpt-4o-mini"
        assert len(payload["messages"]) == 1
        message_payload = payload["messages"][0]

        assert isinstance(message_payload["content"], list)
        assert message_payload["content"][0] == {
            "type": "text",
            "text": "Describe this image",
        }
        image_part = message_payload["content"][1]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"] == "https://example.com/cat.png"

    @pytest.mark.parametrize(
        "args_input, expected_output_str",
        [
            # This is the key case: a string that looks like JSON with single quotes
            # but contains a single quote inside a value. Now returns empty object instead of _raw.
            (
                "{'query': 'what's the weather?'}",
                "{}",
            ),
            # A valid JSON string that contains a single quote. Should be parsed and returned as is.
            ('{"query": "what\'s the weather?"}', '{"query": "what\'s the weather?"}'),
            # A string that looks like JSON with single quotes and is valid if quotes are replaced.
            ("{'query': 'weather'}", '{"query": "weather"}'),
            # A valid JSON string.
            ('{"location": "New York"}', '{"location": "New York"}'),
            # A non-JSON string. Now returns empty object instead of _raw.
            ("just a raw string", "{}"),
            # Empty string.
            ("", "{}"),
            # None input.
            (None, "{}"),
        ],
    )
    def test_normalize_tool_arguments_handles_quotes_correctly(
        self, args_input, expected_output_str
    ):
        """
        Tests that _normalize_tool_arguments correctly handles various string inputs,
        especially those containing single and double quotes, without corrupting the data.
        """
        normalized_args = Translation.normalize_tool_arguments(args_input)

        # We compare the parsed JSON objects to be sure of semantic equivalence.
        expected_output = json.loads(expected_output_str)
        actual_output = json.loads(normalized_args)

        assert actual_output == expected_output
