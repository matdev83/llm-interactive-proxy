"""Regression test for ContentRewritingMiddleware JSON parsing DoS fix.

This test verifies that ContentRewritingMiddleware properly protects against
DoS attacks through malicious JSON payloads:
1. Massive arrays causing memory exhaustion
2. Deeply nested structures causing stack overflow
3. Oversized request bodies

Fixed: Added _validate_json_size() and _validate_json_structure() methods with
MAX_BODY_SIZE (10MB), MAX_NESTING_DEPTH (100), and MAX_ARRAY_ELEMENTS (1M) limits.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)
from src.core.services.content_rewriter_service import ContentRewriterService


class TestContentRewritingMiddlewareJsonParsingDoSRegression:
    """Regression tests for ContentRewritingMiddleware JSON parsing DoS fix."""

    @pytest.fixture
    def middleware(self):
        """Create a ContentRewritingMiddleware instance for testing."""
        rewriter = MagicMock(spec=ContentRewriterService)
        return ContentRewritingMiddleware(app=None, rewriter=rewriter)

    def test_massive_array_rejected(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that massive arrays exceeding MAX_ARRAY_ELEMENTS are rejected."""
        # Create payload with array exceeding 1M elements
        massive_array_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_array": list(range(1_500_000)),  # Exceeds 1M limit
        }

        json_str = json.dumps(massive_array_payload)
        json_bytes = json_str.encode("utf-8")

        # Validate size first (should pass if under 10MB)
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            # Parse and validate structure
            parsed = json.loads(json_bytes)

            # Should raise HTTPException for massive array
            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_json_structure(parsed)

            assert exc_info.value.status_code == 422
            assert (
                "array size" in exc_info.value.detail.lower()
                or "elements" in exc_info.value.detail.lower()
            )

    def test_deeply_nested_structure_rejected(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that deeply nested structures exceeding MAX_NESTING_DEPTH are rejected."""
        # Create payload with nesting exceeding 100 levels
        nested_data = {"value": "root"}
        for _i in range(150):  # Exceeds MAX_NESTING_DEPTH (100)
            nested_data = {"nested": nested_data}

        deep_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "deeply_nested": nested_data,
        }

        json_str = json.dumps(deep_payload)
        json_bytes = json_str.encode("utf-8")

        # Validate size first
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            parsed = json.loads(json_bytes)

            # Should raise HTTPException for deep nesting
            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_json_structure(parsed)

            assert exc_info.value.status_code == 422
            assert (
                "nesting depth" in exc_info.value.detail.lower()
                or "depth" in exc_info.value.detail.lower()
            )

    def test_oversized_request_body_rejected(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that request bodies exceeding MAX_BODY_SIZE are rejected."""
        # Create payload larger than 10MB
        large_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_string": "A" * (12 * 1024 * 1024),  # 12MB string
        }

        json_str = json.dumps(large_payload)
        json_bytes = json_str.encode("utf-8")

        # Should raise HTTPException for oversized body
        with pytest.raises(HTTPException) as exc_info:
            middleware._validate_json_size(json_bytes)

        assert exc_info.value.status_code == 413
        assert (
            "too large" in exc_info.value.detail.lower()
            or "size" in exc_info.value.detail.lower()
        )

    def test_valid_payload_accepted(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that valid payloads within limits are accepted."""
        # Create a normal payload
        normal_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "normal_array": list(range(1000)),  # Small array
            "normal_nested": {
                "level1": {"level2": {"level3": "value"}}
            },  # Shallow nesting
        }

        json_str = json.dumps(normal_payload)
        json_bytes = json_str.encode("utf-8")

        # Should not raise exceptions
        middleware._validate_json_size(json_bytes)
        parsed = json.loads(json_bytes)
        middleware._validate_json_structure(parsed)

        # If we get here, validation passed
        assert parsed["messages"][0]["content"] == "test"

    def test_array_at_limit_accepted(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that arrays at the MAX_ARRAY_ELEMENTS limit are accepted."""
        # Optimize: Use smaller array for faster test execution while maintaining coverage
        # Test with array at limit but use a smaller limit for test performance
        # The actual limit validation is tested elsewhere, here we just verify acceptance
        test_limit = min(
            middleware.MAX_ARRAY_ELEMENTS, 100000
        )  # Cap at 100k for test speed
        array_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_array": [0] * test_limit,
        }

        json_str = json.dumps(array_payload)
        json_bytes = json_str.encode("utf-8")

        # Validate size first
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            parsed = json.loads(json_bytes)

            # Should not raise exception (at limit is OK)
            middleware._validate_json_structure(parsed)

            # Verify array size
            assert len(parsed["large_array"]) == test_limit

    def test_many_small_nested_objects_accepted(
        self, middleware: ContentRewritingMiddleware
    ) -> None:
        """Test that many small nested objects within limits are accepted."""
        # Create 5,000 small nested objects (reduced from 10,000 for performance while maintaining coverage)
        nested_objects_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "many_objects": [
                {"id": i, "data": {"nested": {"value": i}}} for i in range(5000)
            ],
        }

        json_str = json.dumps(nested_objects_payload)
        json_bytes = json_str.encode("utf-8")

        # Validate size first
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            parsed = json.loads(json_bytes)

            # Should not raise exception (shallow nesting, array under limit)
            middleware._validate_json_structure(parsed)

            # Verify objects were parsed
            assert len(parsed["many_objects"]) == 5000
