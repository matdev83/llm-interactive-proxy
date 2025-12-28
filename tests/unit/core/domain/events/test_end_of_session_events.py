"""Tests for End-of-Session domain events and signals."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)


class TestEndOfSessionSignalType:
    """Tests for EndOfSessionSignalType enum."""

    def test_enum_values(self) -> None:
        """Test that all expected enum values exist."""
        assert EndOfSessionSignalType.DONE_SENTINEL == "done_sentinel"
        assert EndOfSessionSignalType.FINISH_REASON == "finish_reason"
        assert EndOfSessionSignalType.RESPONSE_COMPLETED == "response_completed"
        assert EndOfSessionSignalType.TOOL_COMPLETION == "tool_completion"
        assert EndOfSessionSignalType.ERROR_TERMINATION == "error_termination"
        assert EndOfSessionSignalType.CLIENT_TERMINATION == "client_termination"

    def test_enum_is_string_based(self) -> None:
        """Test that enum values are strings."""
        assert isinstance(EndOfSessionSignalType.DONE_SENTINEL, str)

    @freeze_time("2024-01-01 12:00:00")
    def test_client_termination_signal_type(self) -> None:
        """Test that CLIENT_TERMINATION signal type can be used in signals."""
        signal = EndOfSessionSignal(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
            reason="client_disconnected",
        )

        assert signal.signal_type == EndOfSessionSignalType.CLIENT_TERMINATION
        assert signal.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert signal.reason == "client_disconnected"

    def test_client_termination_is_distinct_from_error_termination(self) -> None:
        """Test that CLIENT_TERMINATION is distinct from ERROR_TERMINATION (requirement 3.7)."""
        assert (
            EndOfSessionSignalType.CLIENT_TERMINATION
            != EndOfSessionSignalType.ERROR_TERMINATION
        )
        assert (
            EndOfSessionSignalType.CLIENT_TERMINATION.value
            != EndOfSessionSignalType.ERROR_TERMINATION.value
        )

    def test_client_termination_works_with_event(self) -> None:
        """Test that CLIENT_TERMINATION can be used in RemoteBackendConnectionEndOfSessionEvent."""
        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            reason="client_disconnected",
        )

        assert event.signal_type == EndOfSessionSignalType.CLIENT_TERMINATION
        assert event.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert event.reason == "client_disconnected"


class TestEndOfSessionTerminationCategory:
    """Tests for EndOfSessionTerminationCategory enum."""

    def test_enum_values(self) -> None:
        """Test that all expected enum values exist."""
        assert EndOfSessionTerminationCategory.NORMAL == "normal"
        assert EndOfSessionTerminationCategory.ERROR == "error"

    def test_enum_is_string_based(self) -> None:
        """Test that enum values are strings."""
        assert isinstance(EndOfSessionTerminationCategory.NORMAL, str)


class TestEndOfSessionErrorClassification:
    """Tests for EndOfSessionErrorClassification enum."""

    def test_enum_values(self) -> None:
        """Test that all expected enum values exist."""
        assert EndOfSessionErrorClassification.TRANSPORT_ERROR == "transport_error"
        assert EndOfSessionErrorClassification.HTTP_ERROR == "http_error"
        assert EndOfSessionErrorClassification.BACKEND_ERROR == "backend_error"
        assert EndOfSessionErrorClassification.UNKNOWN_ERROR == "unknown_error"

    def test_enum_is_string_based(self) -> None:
        """Test that enum values are strings."""
        assert isinstance(EndOfSessionErrorClassification.TRANSPORT_ERROR, str)


class TestEndOfSessionSignal:
    """Tests for EndOfSessionSignal dataclass."""

    @freeze_time("2024-01-01 12:00:00")
    def test_create_signal_with_required_fields(self) -> None:
        """Test creating a signal with required fields."""
        signal = EndOfSessionSignal(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
        )

        assert signal.session_id == "session-123"
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL
        assert signal.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert signal.reason is None
        assert signal.error_classification is None
        assert signal.error_status_code is None
        assert signal.protocol is None
        assert signal.request_id is None
        assert signal.backend is None

    @freeze_time("2024-01-01 12:00:00")
    def test_create_signal_with_all_fields(self) -> None:
        """Test creating a signal with all fields."""
        observed_at = datetime.now(timezone.utc)
        signal = EndOfSessionSignal(
            session_id="session-456",
            signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.ERROR,
            observed_at=observed_at,
            reason="Connection timeout",
            error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
            error_status_code=504,
            protocol="openai",
            request_id="req-789",
            backend="openai-gpt4",
        )

        assert signal.session_id == "session-456"
        assert signal.signal_type == EndOfSessionSignalType.ERROR_TERMINATION
        assert signal.termination_category == EndOfSessionTerminationCategory.ERROR
        assert signal.observed_at == observed_at
        assert signal.reason == "Connection timeout"
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )
        assert signal.error_status_code == 504
        assert signal.protocol == "openai"
        assert signal.request_id == "req-789"
        assert signal.backend == "openai-gpt4"

    @freeze_time("2024-01-01 12:00:00")
    def test_signal_is_immutable(self) -> None:
        """Test that signal is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        signal = EndOfSessionSignal(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
        )

        with pytest.raises(FrozenInstanceError):
            signal.session_id = "modified"  # type: ignore[misc]


class TestRemoteBackendConnectionEndOfSessionEvent:
    """Tests for RemoteBackendConnectionEndOfSessionEvent."""

    def test_event_type_constant(self) -> None:
        """Test that event_type is set correctly."""
        assert (
            RemoteBackendConnectionEndOfSessionEvent.event_type
            == "remote_backend_connection_end_of_session"
        )

    def test_create_event_with_required_fields(self) -> None:
        """Test creating an event with required fields."""
        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )

        assert event.session_id == "session-123"
        assert event.signal_type == EndOfSessionSignalType.DONE_SENTINEL
        assert event.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert event.reason is None
        assert event.error_classification is None
        assert event.error_status_code is None
        assert event.protocol is None
        assert event.request_id is None
        assert event.backend is None
        assert isinstance(event.timestamp, datetime)
        assert isinstance(event.event_id, str)

    def test_create_event_with_all_fields(self) -> None:
        """Test creating an event with all fields."""
        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-456",
            signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.ERROR,
            reason="Connection timeout",
            error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
            error_status_code=504,
            protocol="openai",
            request_id="req-789",
            backend="openai-gpt4",
        )

        assert event.session_id == "session-456"
        assert event.signal_type == EndOfSessionSignalType.ERROR_TERMINATION
        assert event.termination_category == EndOfSessionTerminationCategory.ERROR
        assert event.reason == "Connection timeout"
        assert (
            event.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )
        assert event.error_status_code == 504
        assert event.protocol == "openai"
        assert event.request_id == "req-789"
        assert event.backend == "openai-gpt4"
        assert isinstance(event.timestamp, datetime)
        assert isinstance(event.event_id, str)

    def test_event_is_immutable(self) -> None:
        """Test that event is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )

        with pytest.raises(FrozenInstanceError):
            event.session_id = "modified"  # type: ignore[misc]

    def test_event_inherits_from_domain_event(self) -> None:
        """Test that event inherits from DomainEvent."""
        from src.core.domain.events import DomainEvent

        event = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )

        assert isinstance(event, DomainEvent)
        assert isinstance(event, DomainEvent)

    def test_event_has_unique_event_id(self) -> None:
        """Test that each event gets a unique event_id."""
        event1 = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )
        event2 = RemoteBackendConnectionEndOfSessionEvent(
            session_id="session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )

        assert event1.event_id != event2.event_id

    def test_event_validates_session_id_required(self) -> None:
        """Test that event validates session_id is not empty."""
        with pytest.raises(ValueError, match="session_id is required"):
            RemoteBackendConnectionEndOfSessionEvent(
                session_id="",  # Empty session_id should raise
                signal_type=EndOfSessionSignalType.DONE_SENTINEL,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
            )
