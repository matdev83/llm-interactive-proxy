"""Unit tests for ClientTerminationReasonMapper."""

from __future__ import annotations

from src.core.domain.client_termination import ClientTerminationReason
from src.core.services.client_termination_reason_mapper import (
    ClientTerminationReasonMapper,
)


class TestClientTerminationReasonMapper:
    """Test suite for ClientTerminationReasonMapper."""

    def test_map_legacy_client_disconnect(self) -> None:
        """Test mapping legacy 'client_disconnect' marker."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_reason("client_disconnect")
        assert result == ClientTerminationReason.CLIENT_DISCONNECTED

    def test_map_legacy_stream_cancelled(self) -> None:
        """Test mapping legacy 'stream_cancelled' marker."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_reason("stream_cancelled")
        assert result == ClientTerminationReason.CLIENT_CANCELLED

    def test_map_legacy_user_cancelled(self) -> None:
        """Test mapping legacy 'user_cancelled' marker."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_reason("user_cancelled")
        assert result == ClientTerminationReason.CLIENT_CANCELLED

    def test_map_generator_exit_exception(self) -> None:
        """Test mapping GeneratorExit exception."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_exception(GeneratorExit())
        assert result == ClientTerminationReason.CLIENT_DISCONNECTED

    def test_map_cancelled_error_exception(self) -> None:
        """Test mapping asyncio.CancelledError exception."""
        mapper = ClientTerminationReasonMapper()
        import asyncio

        result = mapper.map_exception(asyncio.CancelledError())
        assert result == ClientTerminationReason.CLIENT_CANCELLED

    def test_map_unknown_marker(self) -> None:
        """Test mapping unknown marker returns UNKNOWN_CLIENT_TERMINATION."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_reason("unknown_marker")
        assert result == ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION

    def test_map_none_marker(self) -> None:
        """Test mapping None marker returns UNKNOWN_CLIENT_TERMINATION."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_reason(None)
        assert result == ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION

    def test_map_unknown_exception(self) -> None:
        """Test mapping unknown exception returns UNKNOWN_CLIENT_TERMINATION."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_exception(ValueError("test"))
        assert result == ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION

    def test_map_none_exception(self) -> None:
        """Test mapping None exception returns UNKNOWN_CLIENT_TERMINATION."""
        mapper = ClientTerminationReasonMapper()
        result = mapper.map_exception(None)
        assert result == ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION
