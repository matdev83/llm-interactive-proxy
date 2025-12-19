"""Tests for HeaderSanitizer."""

from __future__ import annotations

from src.core.transport.fastapi.adapters.sanitization.header_sanitizer import (
    HeaderSanitizer,
)


class TestHeaderSanitizer:
    """Test HeaderSanitizer implementation."""

    def test_hop_by_hop_headers_removed(self):
        """Test that hop-by-hop headers are removed."""
        sanitizer = HeaderSanitizer()
        headers = {
            "content-encoding": "gzip",
            "transfer-encoding": "chunked",
            "connection": "keep-alive",
            "x-custom": "value",
        }
        result = sanitizer.sanitize(headers)
        assert "content-encoding" not in result
        assert "transfer-encoding" not in result
        assert "connection" not in result
        assert result["x-custom"] == "value"

    def test_allowed_prefix_filtering(self):
        """Test that only headers with allowed prefixes are kept."""
        sanitizer = HeaderSanitizer()
        headers = {
            "x-custom": "value1",
            "access-control-allow-origin": "*",
            "anthropic-version": "2023-06-01",
            "openai-version": "v1",
            "zenmux-request-id": "123",
            "content-type": "application/json",
            "authorization": "Bearer token",
        }
        result = sanitizer.sanitize(headers)
        assert "x-custom" in result
        assert "access-control-allow-origin" in result
        assert "anthropic-version" in result
        assert "openai-version" in result
        assert "zenmux-request-id" in result
        assert "content-type" not in result
        assert "authorization" not in result

    def test_none_input_handling(self):
        """Test that None input returns empty dict."""
        sanitizer = HeaderSanitizer()
        result = sanitizer.sanitize(None)
        assert result == {}

    def test_empty_dict_handling(self):
        """Test that empty dict returns empty dict."""
        sanitizer = HeaderSanitizer()
        result = sanitizer.sanitize({})
        assert result == {}

    def test_case_insensitivity(self):
        """Test that header filtering is case-insensitive."""
        sanitizer = HeaderSanitizer()
        headers = {
            "X-Custom": "value1",
            "Content-Encoding": "gzip",
            "ACCESS-CONTROL-ALLOW-ORIGIN": "*",
        }
        result = sanitizer.sanitize(headers)
        assert "X-Custom" in result
        assert "Content-Encoding" not in result
        assert "ACCESS-CONTROL-ALLOW-ORIGIN" in result

    def test_all_hop_by_hop_headers_removed(self):
        """Test that all RFC 2616 hop-by-hop headers are removed."""
        sanitizer = HeaderSanitizer()
        headers = {
            "content-encoding": "gzip",
            "transfer-encoding": "chunked",
            "content-length": "1234",
            "connection": "keep-alive",
            "keep-alive": "timeout=5",
            "proxy-authenticate": "Basic",
            "proxy-authorization": "Bearer token",
            "te": "trailers",
            "trailer": "Expires",
            "upgrade": "websocket",
            "x-custom": "value",
        }
        result = sanitizer.sanitize(headers)
        hop_by_hop_headers = {
            "content-encoding",
            "transfer-encoding",
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "upgrade",
        }
        for header in hop_by_hop_headers:
            assert header not in result, f"{header} should be removed"
        assert "x-custom" in result

    def test_protocol_constants(self):
        """Test that protocol constants are defined correctly."""
        sanitizer = HeaderSanitizer()
        assert hasattr(sanitizer, "ALLOWED_PREFIXES")
        assert isinstance(sanitizer.ALLOWED_PREFIXES, tuple)
        assert "x-" in sanitizer.ALLOWED_PREFIXES
        assert "access-control-" in sanitizer.ALLOWED_PREFIXES
        assert "anthropic-" in sanitizer.ALLOWED_PREFIXES
        assert "openai-" in sanitizer.ALLOWED_PREFIXES
        assert "zenmux-" in sanitizer.ALLOWED_PREFIXES

        assert hasattr(sanitizer, "HOP_BY_HOP_HEADERS")
        assert isinstance(sanitizer.HOP_BY_HOP_HEADERS, frozenset)
        assert "content-encoding" in sanitizer.HOP_BY_HOP_HEADERS
        assert "transfer-encoding" in sanitizer.HOP_BY_HOP_HEADERS
        assert "connection" in sanitizer.HOP_BY_HOP_HEADERS
