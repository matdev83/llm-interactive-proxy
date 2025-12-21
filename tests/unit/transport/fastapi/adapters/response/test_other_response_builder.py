"""Tests for OtherResponseBuilder."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.responses import Response
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.transport.fastapi.adapters.response.other_response_builder import (
    OtherResponseBuilder,
)
from src.core.transport.fastapi.adapters.sanitization.header_sanitizer import (
    HeaderSanitizer,
)


class TestOtherResponseBuilder:
    """Test OtherResponseBuilder implementation."""

    def test_build_non_json_content_handling(self) -> None:
        """Test that non-JSON content is handled correctly."""
        builder = OtherResponseBuilder()
        envelope = ResponseEnvelope(
            content=b"Binary content",
            headers={},
            status_code=200,
            media_type="application/octet-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, Response)
        assert response.status_code == 200

    def test_build_header_sanitization_applied(self) -> None:
        """Test that header sanitization is applied."""
        builder = OtherResponseBuilder()
        envelope = ResponseEnvelope(
            content="Text content",
            headers={
                "x-custom-header": "value",
                "disallowed-header": "value",
                "transfer-encoding": "chunked",
            },
            status_code=200,
            media_type="text/plain",
        )

        response = builder.build(envelope)

        assert "x-custom-header" in response.headers
        assert "disallowed-header" not in response.headers
        assert "transfer-encoding" not in response.headers

    def test_build_correct_content_type_preserved(self) -> None:
        """Test that correct content-type is preserved."""
        builder = OtherResponseBuilder()
        envelope = ResponseEnvelope(
            content="Text content",
            headers={},
            status_code=200,
            media_type="text/plain",
        )

        response = builder.build(envelope)

        assert response.media_type == "text/plain"

    def test_build_di_injection_works(self) -> None:
        """Test that DI injection works for HeaderSanitizer."""
        mock_header_sanitizer = MagicMock(spec=HeaderSanitizer)
        mock_header_sanitizer.sanitize.side_effect = lambda x: x or {}

        builder = OtherResponseBuilder(header_sanitizer=mock_header_sanitizer)

        envelope = ResponseEnvelope(
            content="Content",
            headers={"x-header": "value"},
            status_code=200,
            media_type="text/plain",
        )

        response = builder.build(envelope)

        assert isinstance(response, Response)
        mock_header_sanitizer.sanitize.assert_called_once()

    def test_build_default_instance_created(self) -> None:
        """Test that default HeaderSanitizer instance is created."""
        builder = OtherResponseBuilder()

        # Should not raise
        assert builder._header_sanitizer is not None

    def test_build_status_code_preserved(self) -> None:
        """Test that status code is preserved."""
        builder = OtherResponseBuilder()
        envelope = ResponseEnvelope(
            content="Content",
            headers={},
            status_code=404,
            media_type="text/plain",
        )

        response = builder.build(envelope)

        assert response.status_code == 404

    def test_build_canonical_usage_headers_injected(self) -> None:
        """Test that canonical usage headers are injected (Requirement 5.5)."""
        builder = OtherResponseBuilder()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.05,
        )

        envelope = ResponseEnvelope(
            content=b"Binary content",
            headers={},
            status_code=200,
            media_type="application/octet-stream",
            canonical_usage=canonical_usage,
        )

        response = builder.build(envelope)

        assert isinstance(response, Response)
        # Headers should be derived from canonical usage
        assert response.headers["x-usage-prompt-tokens"] == "100"
        assert response.headers["x-usage-completion-tokens"] == "200"
        assert response.headers["x-usage-total-tokens"] == "300"
        assert response.headers["x-usage-cost"] == "0.05"

    def test_build_canonical_usage_headers_preserve_existing(self) -> None:
        """Test that existing headers are preserved when injecting canonical usage headers."""
        builder = OtherResponseBuilder()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
        )

        envelope = ResponseEnvelope(
            content="Text content",
            headers={"x-custom-header": "value"},
            status_code=200,
            media_type="text/plain",
            canonical_usage=canonical_usage,
        )

        response = builder.build(envelope)

        assert isinstance(response, Response)
        # Existing headers should be preserved
        assert response.headers["x-custom-header"] == "value"
        # Canonical usage headers should be added
        assert response.headers["x-usage-prompt-tokens"] == "100"
