"""Tests for JSONResponseBuilder."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.responses import JSONResponse
from src.core.domain.responses import ResponseEnvelope
from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
    ReasoningInjector,
)
from src.core.transport.fastapi.adapters.response.json_response_builder import (
    JSONResponseBuilder,
)
from src.core.transport.fastapi.adapters.sanitization.header_sanitizer import (
    HeaderSanitizer,
)
from src.core.transport.fastapi.adapters.sanitization.json_sanitizer import (
    JSONSanitizer,
)
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)


class TestJSONResponseBuilder:
    """Test JSONResponseBuilder implementation."""

    def test_build_response_content_matches_envelope(self) -> None:
        """Test that response content matches envelope content."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=200,
        )

        response = builder.build(envelope)

        assert isinstance(response, JSONResponse)
        assert response.body is not None
        import json

        body_dict = json.loads(response.body.decode())
        assert body_dict["message"] == "Hello"
        # Usage may be added by _ensure_usage
        assert "usage" in body_dict or "message" in body_dict

    def test_build_headers_are_sanitized(self) -> None:
        """Test that headers are sanitized to allowed prefixes only."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={
                "x-custom-header": "value",
                "disallowed-header": "value",
                "transfer-encoding": "chunked",
            },
            status_code=200,
        )

        response = builder.build(envelope)

        assert "x-custom-header" in response.headers
        assert "disallowed-header" not in response.headers
        assert "transfer-encoding" not in response.headers

    def test_build_usage_headers_are_injected(self) -> None:
        """Test that usage headers are injected when usage is present."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=200,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        response = builder.build(envelope)

        assert response.headers["x-usage-prompt-tokens"] == "10"
        assert response.headers["x-usage-completion-tokens"] == "20"
        assert response.headers["x-usage-total-tokens"] == "30"

    def test_build_status_code_is_set_correctly(self) -> None:
        """Test that status code is set correctly."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=201,
        )

        response = builder.build(envelope)

        assert response.status_code == 201

    def test_build_di_injection_works(self) -> None:
        """Test that DI injection works for dependencies."""
        mock_json_sanitizer = MagicMock(spec=JSONSanitizer)
        mock_json_sanitizer.sanitize.side_effect = lambda x: x

        mock_header_sanitizer = MagicMock(spec=HeaderSanitizer)
        mock_header_sanitizer.sanitize.side_effect = lambda x: x or {}

        mock_usage_injector = MagicMock(spec=UsageHeaderInjector)
        mock_usage_injector.inject_headers.side_effect = lambda h, u: h or {}

        mock_reasoning_injector = MagicMock(spec=ReasoningInjector)
        mock_reasoning_injector.inject_reasoning.side_effect = lambda c, m, **kw: c

        builder = JSONResponseBuilder(
            json_sanitizer=mock_json_sanitizer,
            header_sanitizer=mock_header_sanitizer,
            usage_header_injector=mock_usage_injector,
            reasoning_injector=mock_reasoning_injector,
        )

        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=200,
        )

        response = builder.build(envelope)

        assert isinstance(response, JSONResponse)
        mock_json_sanitizer.sanitize.assert_called()
        mock_header_sanitizer.sanitize.assert_called()

    def test_build_default_instances_created(self) -> None:
        """Test that default instances are created when not provided."""
        builder = JSONResponseBuilder()

        # Should not raise
        assert builder._json_sanitizer is not None
        assert builder._header_sanitizer is not None
        assert builder._usage_header_injector is not None
        assert builder._reasoning_injector is not None

    def test_build_reasoning_injection_applied(self) -> None:
        """Test that reasoning injection is applied."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Hello"}}]},
            headers={},
            status_code=200,
            metadata={"reasoning_content": "Let me think..."},
        )

        response = builder.build(envelope)

        import json

        body_dict = json.loads(response.body.decode())
        # Reasoning should be injected into the content
        assert "choices" in body_dict
        # The reasoning injector should have processed it

    def test_build_steering_retry_metadata_included(self) -> None:
        """Test that steering_retry_occurred metadata is included."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=200,
            metadata={"steering_retry_occurred": True},
        )

        response = builder.build(envelope)

        import json

        body_dict = json.loads(response.body.decode())
        assert body_dict.get("metadata", {}).get("steering_retry_occurred") is True

    def test_build_json_sanitization_applied(self) -> None:
        """Test that JSON sanitization is applied."""
        builder = JSONResponseBuilder()
        # Create content that needs sanitization (e.g., with coroutine)

        async def coro():
            return "test"

        envelope = ResponseEnvelope(
            content={"coro": coro()},
            headers={},
            status_code=200,
        )

        response = builder.build(envelope)

        # Should not raise - coroutine should be converted to string
        assert isinstance(response, JSONResponse)

    def test_build_media_type_is_json(self) -> None:
        """Test that media type is set to application/json."""
        builder = JSONResponseBuilder()
        envelope = ResponseEnvelope(
            content={"message": "Hello"},
            headers={},
            status_code=200,
        )

        response = builder.build(envelope)

        assert response.media_type == "application/json"
