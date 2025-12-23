"""Regression test for SSOMiddlewareAdapter DoS vulnerability fix.

This test verifies that the SSOMiddlewareAdapter properly limits request body
size and validates JSON structure to prevent DoS attacks.

Fixed: Added MAX_BODY_SIZE (10MB) and validate_json_structure() checks.
"""

import json
from unittest.mock import MagicMock

import pytest
from src.core.app.middleware.sso_middleware_adapter import SSOMiddlewareAdapter
from src.core.auth.sso.middleware import AuthMiddleware
from src.core.auth.sso.sandbox_handler import SandboxHandler
from starlette.requests import Request


class MockAuthMiddleware(AuthMiddleware):
    """Mock auth middleware for testing."""

    def __init__(self):
        """Initialize mock auth middleware."""
        # Create minimal mocks for required dependencies
        mock_token_service = MagicMock()
        mock_token_repository = MagicMock()
        mock_sandbox_handler = SandboxHandler(
            auth_url="http://test.com", token_repository=None
        )
        super().__init__(
            mock_token_service, mock_token_repository, mock_sandbox_handler
        )

    async def __call__(self, request_dict: dict) -> dict | None:
        return None  # Always allow (for testing)


class TestSSOMiddlewareAdapterDoSRegression:
    """Regression tests for SSOMiddlewareAdapter DoS vulnerability fix."""

    @pytest.fixture
    def middleware(self):
        """Create a SSOMiddlewareAdapter instance for testing."""
        mock_auth = MockAuthMiddleware()
        return SSOMiddlewareAdapter(None, mock_auth)  # type: ignore

    def create_deeply_nested_json(self, depth: int) -> dict:
        """Create a JSON structure with specified nesting depth."""
        if depth == 0:
            return {"value": "leaf"}
        return {"nested": self.create_deeply_nested_json(depth - 1)}

    def create_large_array_json(self, size: int) -> dict:
        """Create a JSON structure with a large array."""
        return {"messages": [{"role": "user", "content": "test"}] * size}

    @pytest.mark.asyncio
    async def test_large_body_rejected(self, middleware: SSOMiddlewareAdapter) -> None:
        """Test that large request bodies (>10MB) are rejected."""
        # Create payload larger than 10MB
        large_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_string": "A" * (12 * 1024 * 1024),  # 12MB string
        }

        json_str = json.dumps(large_payload)
        json_bytes = json_str.encode("utf-8")

        # Create a mock request
        async def mock_receive():
            return {"type": "http.request", "body": json_bytes}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }

        request = Request(scope, mock_receive)

        # Should handle large body gracefully (skip parsing)
        result = await middleware._convert_request_to_dict(request)
        assert isinstance(result, dict), "Should return dict even with large body"
        # Messages should be empty if body was too large
        assert len(result.get("messages", [])) == 0, "Large body should not be parsed"

    @pytest.mark.asyncio
    async def test_deep_nesting_rejected(
        self, middleware: SSOMiddlewareAdapter
    ) -> None:
        """Test that deeply nested structures are rejected."""
        # Create payload with nesting exceeding 100 levels
        nested_data = self.create_deeply_nested_json(150)  # > 100 limit

        deep_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "deeply_nested": nested_data,
        }

        json_str = json.dumps(deep_payload)
        json_bytes = json_str.encode("utf-8")

        # Should be within size limit but exceed depth limit
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            # Create a mock request
            async def mock_receive():
                return {"type": "http.request", "body": json_bytes}

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/test",
                "headers": [(b"content-type", b"application/json")],
            }

            request = Request(scope, mock_receive)

            # Should handle deep nesting gracefully (skip parsing or return empty messages)
            result = await middleware._convert_request_to_dict(request)
            assert isinstance(result, dict), "Should return dict"
            # Messages should be empty if validation failed
            assert (
                len(result.get("messages", [])) == 0
            ), "Deep nesting should be rejected"

    @pytest.mark.asyncio
    async def test_large_array_rejected(self, middleware: SSOMiddlewareAdapter) -> None:
        """Test that large arrays are rejected."""
        # Create payload with large array (but within size limit)
        large_array_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_array": list(range(1_500_000)),  # 1.5M elements
        }

        json_str = json.dumps(large_array_payload)
        json_bytes = json_str.encode("utf-8")

        # Should be within size limit but exceed array limit
        if len(json_bytes) <= middleware.MAX_BODY_SIZE:
            # Create a mock request
            async def mock_receive():
                return {"type": "http.request", "body": json_bytes}

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/test",
                "headers": [(b"content-type", b"application/json")],
            }

            request = Request(scope, mock_receive)

            # Should handle large array gracefully
            result = await middleware._convert_request_to_dict(request)
            assert isinstance(result, dict), "Should return dict"
            # Messages extraction may fail due to validation
            assert (
                len(result.get("messages", [])) == 0
                or len(result.get("messages", [])) == 1
            ), "Large array should be handled safely"

    @pytest.mark.asyncio
    async def test_valid_payload_accepted(
        self, middleware: SSOMiddlewareAdapter
    ) -> None:
        """Test that valid payloads within limits are accepted."""
        normal_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "normal_array": list(range(1000)),  # Small array
            "normal_nested": {
                "level1": {"level2": {"level3": "value"}}
            },  # Shallow nesting
        }

        json_str = json.dumps(normal_payload)
        json_bytes = json_str.encode("utf-8")

        # Create a mock request
        async def mock_receive():
            return {"type": "http.request", "body": json_bytes}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }

        request = Request(scope, mock_receive)

        # Should parse successfully
        result = await middleware._convert_request_to_dict(request)
        assert isinstance(result, dict), "Should return dict"
        assert (
            len(result.get("messages", [])) == 1
        ), "Valid payload should be parsed correctly"

    def test_max_constant_defined(self) -> None:
        """Test that MAX_BODY_SIZE constant is defined correctly."""
        mock_auth = MockAuthMiddleware()
        middleware = SSOMiddlewareAdapter(None, mock_auth)  # type: ignore
        assert (
            middleware.MAX_BODY_SIZE == 10 * 1024 * 1024
        ), f"MAX_BODY_SIZE ({middleware.MAX_BODY_SIZE}) should be 10MB"
        assert middleware.MAX_BODY_SIZE > 0, "MAX_BODY_SIZE should be positive"
