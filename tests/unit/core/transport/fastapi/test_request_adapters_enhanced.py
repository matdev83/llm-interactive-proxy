"""Tests for enhanced FastAPI request adapters."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import Request
from src.core.transport.fastapi.request_adapters import fastapi_to_domain_request_context


class TestFastapiToDomainRequestContextEnhanced:
    """Tests for fastapi_to_domain_request_context with enhanced request_id resolution."""

    def test_extracts_request_id_from_header(self) -> None:
        """Test that request_id is extracted from X-Request-ID header."""
        request = MagicMock(spec=Request)
        request.headers = {"x-request-id": "header-req-123"}
        request.cookies = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = MagicMock()
        request.state = MagicMock()
        request.state.request_state = {}

        context = fastapi_to_domain_request_context(request)

        assert context.request_id == "header-req-123"

    def test_extracts_request_id_from_correlation_header(self) -> None:
        """Test that request_id is extracted from X-Correlation-ID header."""
        request = MagicMock(spec=Request)
        request.headers = {"x-correlation-id": "corr-req-456"}
        request.cookies = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = MagicMock()
        request.state = MagicMock()
        request.state.request_state = {}

        context = fastapi_to_domain_request_context(request)

        assert context.request_id == "corr-req-456"

    def test_extracts_request_id_from_state(self) -> None:
        """Test that request_id is extracted from request.state."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.cookies = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = MagicMock()
        request.state = MagicMock()
        request.state.request_id = "state-req-789"
        request.state.request_state = {}

        context = fastapi_to_domain_request_context(request)

        assert context.request_id == "state-req-789"

    def test_generates_request_id_when_missing(self) -> None:
        """Test that a request_id is generated when missing from headers and state."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.cookies = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = MagicMock()
        request.state = MagicMock()
        request.state.request_id = None
        request.state.request_state = {}

        context = fastapi_to_domain_request_context(request)

        assert context.request_id is not None
        assert context.request_id.startswith("req-")
        assert len(context.request_id) > 4
