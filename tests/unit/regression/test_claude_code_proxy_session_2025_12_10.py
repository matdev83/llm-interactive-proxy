"""
Regression tests for bugs fixed during the Claude Code proxy debugging session (2025-12-10).

This file documents and tests for specific bugs that were discovered when Claude Code
(using Anthropic proxy front-end) connected to the proxy with antigravity-oauth
and cline backends. These bugs caused Claude Code to stall or receive malformed responses.

Bug Summary:
1. ResponseParser JSON-dumps entire response when choices is empty ([])
2. AttributeError when backend returns usage=None in response
3. Cline backend wraps responses in 'data' envelope for non-streaming requests
4. stop_reason is None when response has tool_calls but finish_reason is None

All bugs were related to cross-API translation issues when:
- Client: Claude Code (Anthropic-compatible frontend)
- Backend: Various (cline, antigravity-oauth)
- Mode: Non-streaming (stream=false)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from src.anthropic_converters import openai_to_anthropic_response
from src.core.config.app_config import AppConfig
from src.core.services.response_parser_service import ResponseParser
from src.core.services.translation_service import TranslationService


class TestBug1ResponseParserEmptyChoices:
    """
    Bug #1: ResponseParser JSON-dumps entire response when choices is empty ([]).

    Root Cause:
    -----------
    In ResponseParser.parse_response(), the condition:
        `if not content and not choices:`
    was True for empty choices array because:
    - `not content` is True (empty string is falsy)
    - `not choices` is True (empty list [] is falsy in Python)

    This caused the entire response dict to be JSON-serialized as content:
        `content = json.dumps(raw_response)`

    Impact:
    -------
    When Claude Code received responses with empty choices from the backend,
    the ResponseParser would return a malformed response where the "content"
    field contained a JSON string of the entire response, instead of being empty.
    This caused downstream processing to fail.

    Fix:
    ----
    Changed the condition from:
        `if not content and not choices:`
    to:
        `if not content and "choices" not in raw_response:`

    This ensures we only serialize non-chat-completion responses (like embeddings)
    that truly don't have a choices key, while properly handling empty choices arrays.

    File: src/core/services/response_parser_service.py
    """

    @pytest.fixture
    def parser(self) -> ResponseParser:
        return ResponseParser()

    def test_empty_choices_array_not_json_serialized(
        self, parser: ResponseParser
    ) -> None:
        """
        REGRESSION TEST: Empty choices array should NOT cause entire response to be serialized.

        This was the original bug behavior that caused Claude Code to stall.
        """
        raw_response = {
            "id": "chatcmpl-regression-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [],  # Empty choices - this triggered the bug
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        }

        parsed = parser.parse_response(raw_response)
        content = parser.extract_content(parsed)

        # CRITICAL: Content should be empty string, not a JSON dump
        assert (
            content == ""
        ), f"Empty choices should result in empty content, not: {content[:100]}..."

        # Verify the bug is fixed - content should NOT be the serialized response
        assert content != json.dumps(
            raw_response
        ), "Bug regression: Empty choices caused entire response to be JSON-serialized"

    def test_missing_choices_key_still_serializes_response(
        self, parser: ResponseParser
    ) -> None:
        """
        Verify that responses without 'choices' key are still JSON-serialized.

        This is correct behavior for non-chat-completion responses (embeddings, etc.)
        """
        embedding_response = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": "text-embedding-ada-002",
            # No 'choices' key - this is a different response type
        }

        parsed = parser.parse_response(embedding_response)
        content = parser.extract_content(parsed)

        # For non-chat responses, serialization IS correct
        assert content == json.dumps(embedding_response)

    def test_choices_with_content_works_normally(self, parser: ResponseParser) -> None:
        """Verify normal responses with choices and content still work correctly."""
        normal_response = {
            "id": "chatcmpl-normal",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

        parsed = parser.parse_response(normal_response)
        content = parser.extract_content(parsed)

        assert content == "Hello!"


class TestBug2NoneUsageAttributeError:
    """
    Bug #2: AttributeError when backend returns usage=None in response.

    Root Cause:
    -----------
    In openai_to_anthropic_response(), the code did:
        `usage = oai_dict.get("usage", {})`

    When `usage` key exists but has value `None`, `.get("usage", {})` returns `None`
    (not the default `{}`). Then calling `usage.get("prompt_tokens", 0)` raised:
        `AttributeError: 'NoneType' object has no attribute 'get'`

    Impact:
    -------
    Any backend response with `usage: None` caused an unhandled exception,
    crashing the request handling and leaving Claude Code hanging.

    Fix:
    ----
    Changed from:
        `usage = oai_dict.get("usage", {})`
    to:
        `usage = oai_dict.get("usage") or {}`

    The `or {}` ensures None values are converted to empty dict.

    File: src/anthropic_converters.py
    """

    def test_usage_none_does_not_raise_attribute_error(self) -> None:
        """
        REGRESSION TEST: usage=None should not cause AttributeError.

        This was the original bug that caused 112 errors in the log.
        """
        openai_response = {
            "id": "chatcmpl-none-usage",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "x-ai/grok-code-fast-1",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": None,  # This exact pattern caused the bug
        }

        # Should NOT raise: AttributeError: 'NoneType' object has no attribute 'get'
        try:
            result_model = openai_to_anthropic_response(openai_response)
            result = result_model.model_dump(exclude_none=True)

        except AttributeError as e:
            pytest.fail(
                f"Bug regression: usage=None caused AttributeError: {e}\n"
                "The fix should use `usage = oai_dict.get('usage') or {}`"
            )

        # Verify response is valid
        assert result["type"] == "message"
        assert result["content"][0]["text"] == "Hello!"
        # Usage should default to zeros
        assert result["usage"]["input_tokens"] == 0
        assert result["usage"]["output_tokens"] == 0

    def test_usage_none_with_empty_choices(self) -> None:
        """
        REGRESSION TEST: Combination of empty choices and None usage.

        This double-bug scenario was observed in actual Claude Code traffic.
        """
        openai_response = {
            "id": "chatcmpl-double-bug",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "unknown",
            "choices": [],  # Empty choices (Bug #1)
            "usage": None,  # None usage (Bug #2)
        }

        # Should handle both edge cases without crashing
        try:
            result_model = openai_to_anthropic_response(openai_response)
            result = result_model.model_dump(exclude_none=True)

        except AttributeError as e:
            pytest.fail(
                f"Bug regression: Combined empty choices + None usage failed: {e}"
            )

        assert result["type"] == "message"
        assert result["usage"]["input_tokens"] == 0

    def test_usage_missing_entirely_works(self) -> None:
        """Verify missing usage key is handled (default to empty dict)."""
        openai_response = {
            "id": "chatcmpl-no-usage-key",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "No usage"},
                    "finish_reason": "stop",
                }
            ],
            # 'usage' key is completely absent
        }

        result_model = openai_to_anthropic_response(openai_response)
        result = result_model.model_dump(exclude_none=True)

        assert result["content"][0]["text"] == "No usage"

        assert result["usage"]["input_tokens"] == 0


class TestBug3ClineDataEnvelopeWrapping:
    """
    Bug #3: Cline backend wraps responses in 'data' envelope for non-streaming requests.

    Root Cause:
    -----------
    The Cline API (api.cline.bot) returns non-streaming responses wrapped in a 'data' key:
        {"data": {"id": "...", "choices": [...], ...}}

    The proxy was not unwrapping this envelope, so the translation layer received:
    - No 'choices' at top level
    - Response structure didn't match expected OpenAI format

    Impact:
    -------
    Claude Code (which uses non-streaming by default for many operations) received
    malformed responses where content was either empty or incorrectly serialized.

    Fix:
    ----
    Added `_unwrap_cline_data_envelope()` method to ClineConnector that:
    1. Checks if response has 'data' key containing a dict
    2. Verifies inner dict looks like OpenAI response (has choices/id/model)
    3. Returns unwrapped inner dict if so, otherwise returns original

    The fix is in the connector layer (not translation) because this is
    Cline-specific behavior that shouldn't affect other backends.

    File: src/connectors/cline.py
    """

    @pytest.fixture
    def mock_http_client(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def config(self) -> AppConfig:
        return AppConfig()

    @pytest.fixture
    def translation_service(self) -> TranslationService:
        return TranslationService()

    def test_cline_data_envelope_is_unwrapped(
        self,
        mock_http_client: AsyncMock,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """
        REGRESSION TEST: Cline's 'data' envelope must be unwrapped.

        This was discovered when Claude Code used the cline backend with
        non-streaming requests (stream=false).
        """
        from src.connectors.cline import ClineConnector

        connector = ClineConnector(mock_http_client, config, translation_service)

        # Exact format returned by Cline API for non-streaming requests
        cline_wrapped_response = {
            "data": {
                "id": "chatcmpl-cline-wrapped",
                "object": "chat.completion",
                "created": 1765364399,
                "model": "x-ai/grok-code-fast-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Response from Cline backend",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            }
        }

        unwrapped = connector._unwrap_cline_data_envelope(cline_wrapped_response)

        # CRITICAL: 'data' wrapper should be removed
        assert (
            "data" not in unwrapped
        ), "Bug regression: Cline 'data' envelope was not unwrapped"

        # Verify all fields are now at top level
        assert unwrapped["id"] == "chatcmpl-cline-wrapped"
        assert unwrapped["model"] == "x-ai/grok-code-fast-1"
        assert len(unwrapped["choices"]) == 1
        assert (
            unwrapped["choices"][0]["message"]["content"]
            == "Response from Cline backend"
        )

    def test_standard_openai_response_not_modified(
        self,
        mock_http_client: AsyncMock,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """Verify standard responses (without 'data' wrapper) pass through unchanged."""
        from src.connectors.cline import ClineConnector

        connector = ClineConnector(mock_http_client, config, translation_service)

        standard_response = {
            "id": "chatcmpl-standard",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Standard"},
                    "finish_reason": "stop",
                }
            ],
        }

        result = connector._unwrap_cline_data_envelope(standard_response)

        # Should return the exact same object
        assert result is standard_response

    def test_data_key_with_non_openai_content_not_unwrapped(
        self,
        mock_http_client: AsyncMock,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """
        Verify that 'data' keys containing non-OpenAI data aren't mistakenly unwrapped.

        For example, embedding responses have 'data' key but it's not a wrapper.
        """
        from src.connectors.cline import ClineConnector

        connector = ClineConnector(mock_http_client, config, translation_service)

        # This has 'data' but it's an embedding response, not a wrapper
        embedding_response = {
            "data": [{"embedding": [0.1, 0.2], "index": 0}],  # List, not dict
            "model": "text-embedding-ada-002",
        }

        result = connector._unwrap_cline_data_envelope(embedding_response)

        # Should NOT be unwrapped - 'data' is a list, not a dict
        assert result is embedding_response
        assert "data" in result  # 'data' key should still be present


class TestBug4NoneFinishReasonWithToolCalls:
    """
    Bug #4: stop_reason is None when response has tool_calls but finish_reason is None.

    Root Cause:
    -----------
    Some backends (like Gemini via antigravity-oauth) return tool call responses
    with `finish_reason: None` in the OpenAI format. The Anthropic converter was mapping
    this to `stop_reason: None` instead of `stop_reason: "tool_use"`.

    Impact:
    -------
    Claude Code interprets `stop_reason: None` as an incomplete response and doesn't
    properly handle the tool calls, causing the session to stall after tool execution.

    Fix:
    ----
    Added inference logic in openai_to_anthropic_response() to detect tool_calls
    in the message and set `stop_reason: "tool_use"` when `finish_reason` is None.

    File: src/anthropic_converters.py
    """

    def test_tool_calls_with_none_finish_reason_gets_tool_use_stop_reason(self) -> None:
        """
        REGRESSION TEST: Tool call response with finish_reason=None must have stop_reason="tool_use".

        This was discovered when Claude Code stalled after receiving tool call responses
        from antigravity-oauth backend.
        """
        openai_response = {
            "id": "chatcmpl-tool-call",
            "object": "chat.completion",
            "created": 1765367614,
            "model": "antigravity-oauth",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,  # This is the bug trigger
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "Edit",
                                    "arguments": '{"file_path": "test.py", "content": "print(1)"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

        result_model = openai_to_anthropic_response(openai_response)
        result = result_model.model_dump(exclude_none=True)


        # CRITICAL: stop_reason must be "tool_use", NOT None
        assert result["stop_reason"] == "tool_use", (
            f"Bug regression: Tool call response has stop_reason={result['stop_reason']!r} "
            "instead of 'tool_use'. Claude Code will stall on this response."
        )

        # Verify tool call content is properly converted
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "tool_use"
        assert result["content"][0]["name"] == "Edit"

    def test_tool_calls_with_tool_calls_finish_reason_still_works(self) -> None:
        """Verify explicit finish_reason="tool_calls" still works correctly."""
        openai_response = {
            "id": "chatcmpl-explicit",
            "object": "chat.completion",
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",  # Explicit finish_reason
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_xyz789",
                                "type": "function",
                                "function": {
                                    "name": "Bash",
                                    "arguments": '{"command": "ls"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        result_model = openai_to_anthropic_response(openai_response)
        result = result_model.model_dump(exclude_none=True)


        assert result["stop_reason"] == "tool_use"

    def test_normal_response_with_none_finish_reason_remains_none(self) -> None:
        """Verify that non-tool-call responses with None finish_reason keep None stop_reason."""
        openai_response = {
            "id": "chatcmpl-normal",
            "object": "chat.completion",
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,  # Can happen during streaming
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                        # No tool_calls
                    },
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

        result = openai_to_anthropic_response(openai_response)

        # For non-tool responses, None finish_reason should remain None stop_reason
        assert result.stop_reason is None



class TestCombinedBugScenario:
    """
    Test the exact scenario that caused Claude Code to stall.

    The complete bug chain was:
    1. Claude Code sends non-streaming request (stream=false)
    2. Cline backend returns response wrapped in 'data' envelope
    3. Translation layer sees no 'choices' at top level
    4. Response with empty choices triggers JSON serialization bug
    5. Usage being None triggers AttributeError
    6. Claude Code receives malformed response and stalls

    These tests verify the entire chain is now fixed.
    """

    @pytest.fixture
    def parser(self) -> ResponseParser:
        return ResponseParser()

    def test_full_cline_to_anthropic_translation_chain(
        self, parser: ResponseParser
    ) -> None:
        """
        INTEGRATION TEST: Full translation chain from Cline response to Anthropic format.

        This simulates what happens when Claude Code receives a response from Cline backend.
        """
        # Step 1: Cline returns wrapped response (Bug #3)
        cline_raw_response = {
            "data": {
                "id": "chatcmpl-integration",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "x-ai/grok-code-fast-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Integration test"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        }

        # Step 2: ClineConnector unwraps (Fix for Bug #3)
        from unittest.mock import AsyncMock

        from src.connectors.cline import ClineConnector

        connector = ClineConnector(AsyncMock(), AppConfig(), TranslationService())
        unwrapped = connector._unwrap_cline_data_envelope(cline_raw_response)

        # Step 3: Translation to Anthropic format (could trigger Bug #2)
        anthropic_response_model = openai_to_anthropic_response(unwrapped)
        anthropic_response = anthropic_response_model.model_dump(exclude_none=True)

        # Verify complete success
        assert anthropic_response["type"] == "message"

        assert anthropic_response["content"][0]["text"] == "Integration test"
        assert anthropic_response["usage"]["input_tokens"] == 10
        assert anthropic_response["usage"]["output_tokens"] == 5

    def test_worst_case_scenario_handled(self, parser: ResponseParser) -> None:
        """
        Test absolute worst case: empty choices + None usage + would-be wrapped.

        This combination would have crashed the old code at multiple points.
        """
        # Simulating after unwrapping - a response with all the problem patterns
        problematic_response = {
            "id": "chatcmpl-worst-case",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "unknown",
            "choices": [],  # Bug #1 trigger
            "usage": None,  # Bug #2 trigger
        }

        # ResponseParser should handle empty choices
        parsed = parser.parse_response(problematic_response)
        content = parser.extract_content(parsed)
        assert content == ""  # Empty, not JSON dump

        # Anthropic converter should handle None usage
        try:
            result_model = openai_to_anthropic_response(problematic_response)
            result = result_model.model_dump(exclude_none=True)
            assert result["usage"]["input_tokens"] == 0

        except AttributeError:
            pytest.fail("Bug regression: None usage still causes AttributeError")
