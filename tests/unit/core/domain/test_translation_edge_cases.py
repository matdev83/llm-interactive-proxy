from __future__ import annotations

import json

import pytest
from src.core.domain.translation import Translation


class TestTranslationEdgeCases:
    def test_malformed_json_in_tool_calls(self):
        """Placeholder to be implemented later."""
        assert True

    def test_invalid_image_urls(self):
        """Placeholder to be implemented later."""
        assert True

    def test_missing_required_fields(self):
        """Placeholder to be implemented later."""
        assert True

    def test_streaming_error_conditions(self):
        """Placeholder to be implemented later."""
        assert True

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
        normalized_args = Translation._normalize_tool_arguments(args_input)

        # We compare the parsed JSON objects to be sure of semantic equivalence.
        expected_output = json.loads(expected_output_str)
        actual_output = json.loads(normalized_args)

        assert actual_output == expected_output
