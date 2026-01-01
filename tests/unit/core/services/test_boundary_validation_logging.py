"""Unit tests for boundary validation logging utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.domain.request_context import RequestContext
from src.core.services.boundary_validation import (
    extract_correlation_ids,
    log_boundary_validation_failure,
)


class TestExtractCorrelationIds:
    """Test correlation identifier extraction."""

    def test_extract_from_request_context_with_ids(self):
        """Test extraction from RequestContext with both IDs."""
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-123",
            session_id="session-456",
        )

        result = extract_correlation_ids(context)

        assert result["request_id"] == "req-123"
        assert result["session_id"] == "session-456"

    def test_extract_from_request_context_partial(self):
        """Test extraction from RequestContext with partial IDs."""
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-123",
            session_id=None,
        )

        result = extract_correlation_ids(context)

        assert result["request_id"] == "req-123"
        assert result["session_id"] is None

    def test_extract_from_none(self):
        """Test extraction when context is None."""
        result = extract_correlation_ids(None)

        assert result["request_id"] is None
        assert result["session_id"] is None

    def test_extract_from_connector_request_context(self):
        """Test extraction from ConnectorRequestContext (duck typing)."""
        from src.connectors.contracts import ConnectorRequestContext

        context = ConnectorRequestContext(
            request_id="req-789",
            session_id="session-012",
            client_host=None,
        )

        result = extract_correlation_ids(context)

        assert result["request_id"] == "req-789"
        assert result["session_id"] == "session-012"

    def test_extract_from_object_without_ids(self):
        """Test extraction from object without correlation IDs."""
        class MockContext:
            pass

        context = MockContext()

        result = extract_correlation_ids(context)

        assert result["request_id"] is None
        assert result["session_id"] is None


class TestLogBoundaryValidationFailure:
    """Test boundary validation failure logging."""

    def test_log_with_request_context(self):
        """Test logging with RequestContext containing correlation IDs."""
        mock_logger = MagicMock()
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-123",
            session_id="session-456",
        )

        log_boundary_validation_failure(
            logger=mock_logger,
            message="Test validation failure",
            context=context,
            service="TestService",
            violation_type="test_violation",
            details={"key": "value"},
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args

        assert "Boundary validation failed: Test validation failure" in call_args[0][0]
        assert call_args[1]["extra"]["request_id"] == "req-123"
        assert call_args[1]["extra"]["session_id"] == "session-456"
        assert call_args[1]["extra"]["service"] == "TestService"
        assert call_args[1]["extra"]["violation_type"] == "test_violation"
        assert call_args[1]["extra"]["details"] == {"key": "value"}
        assert call_args[1]["exc_info"] is False

    def test_log_without_context(self):
        """Test logging without RequestContext."""
        mock_logger = MagicMock()
        log_boundary_validation_failure(
            logger=mock_logger,
            message="Test validation failure",
            context=None,
            service="TestService",
            violation_type="test_violation",
            details={"key": "value"},
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args

        assert "Boundary validation failed: Test validation failure" in call_args[0][0]
        assert call_args[1]["extra"]["request_id"] is None
        assert call_args[1]["extra"]["session_id"] is None
        assert call_args[1]["extra"]["service"] == "TestService"
        assert call_args[1]["exc_info"] is False

    def test_log_with_partial_correlation_ids(self):
        """Test logging with partial correlation IDs."""
        mock_logger = MagicMock()
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-123",
            session_id=None,
        )

        log_boundary_validation_failure(
            logger=mock_logger,
            message="Test validation failure",
            context=context,
            service="TestService",
            violation_type="test_violation",
            details={},
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args

        assert call_args[1]["extra"]["request_id"] == "req-123"
        assert call_args[1]["extra"]["session_id"] is None

    def test_log_uses_provided_logger(self):
        """Test that the provided logger instance is used."""
        custom_logger = MagicMock()
        custom_logger.setLevel = MagicMock()  # Mock setLevel if needed

        log_boundary_validation_failure(
            logger=custom_logger,
            message="Test",
            context=None,
            service="TestService",
            violation_type="test",
            details={},
        )

        custom_logger.warning.assert_called_once()
