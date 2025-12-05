"""Unit tests for the diagnostics controller."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from src.core.app.controllers.diagnostics_controller import (
    BackendInstanceInfo,
    DiagnosticResponse,
    GlobalActivityInfo,
    get_activity,
)
from src.core.domain.connection_activity import ConnectionType
from src.core.services.connection_activity_tracker import (
    ConnectionActivityTracker,
    reset_activity_tracker,
)


@pytest.fixture
def activity_tracker() -> ConnectionActivityTracker:
    """Create a fresh activity tracker for tests."""
    reset_activity_tracker()
    return ConnectionActivityTracker()


class TestDiagnosticsResponse:
    """Tests for the diagnostics response model."""

    def test_diagnostic_response_model(self) -> None:
        """Test DiagnosticResponse model structure."""
        response = DiagnosticResponse(
            timestamp=1234567890.0,
            instances=[
                BackendInstanceInfo(
                    name="openai.1",
                    connector_type="openai",
                    is_rate_limited=False,
                    is_functional=True,
                    validation_errors=[],
                    models=[],
                )
            ],
            global_activity=GlobalActivityInfo(
                total_active_connections=0,
                total_bytes_rx=0,
                total_bytes_tx=0,
            ),
        )
        assert response.timestamp == 1234567890.0
        assert len(response.instances) == 1
        assert response.instances[0].name == "openai.1"
        assert response.global_activity is not None


class TestActivityIntegration:
    """Tests for activity tracking integration."""

    def test_activity_tracker_integration(
        self, activity_tracker: ConnectionActivityTracker
    ) -> None:
        """Test activity tracker produces correct snapshots."""
        with activity_tracker.track_connection(
            session_id="test-session",
            backend_name="openai.1",
            connection_type=ConnectionType.STREAMING,
            model="gpt-4",
        ):
            activity_tracker.increment_rx("test-session", "openai.1", 100)
            activity_tracker.increment_tx("test-session", "openai.1", 50)

            snapshot = activity_tracker.get_global_snapshot()
            assert snapshot.total_active_connections == 1
            assert snapshot.total_bytes_rx == 100
            assert snapshot.total_bytes_tx == 50

            backend_snapshot = activity_tracker.get_backend_snapshot("openai.1")
            assert backend_snapshot.active_connections == 1
            assert len(backend_snapshot.connections) == 1
            assert backend_snapshot.connections[0].session_id == "test-session"
            assert backend_snapshot.connections[0].model == "gpt-4"

    def test_activity_tracker_multiple_backends(
        self, activity_tracker: ConnectionActivityTracker
    ) -> None:
        """Test activity tracking across multiple backends."""
        with (
            activity_tracker.track_connection(
                session_id="s1",
                backend_name="openai.1",
                connection_type=ConnectionType.STREAMING,
            ),
            activity_tracker.track_connection(
                session_id="s2",
                backend_name="anthropic.1",
                connection_type=ConnectionType.NON_STREAMING,
            ),
        ):
            activity_tracker.increment_rx("s1", "openai.1", 100)
            activity_tracker.increment_tx("s1", "openai.1", 50)
            activity_tracker.increment_rx("s2", "anthropic.1", 200)
            activity_tracker.increment_tx("s2", "anthropic.1", 100)

            snapshot = activity_tracker.get_global_snapshot()
            assert snapshot.total_active_connections == 2
            assert snapshot.total_bytes_rx == 300
            assert snapshot.total_bytes_tx == 150
            assert len(snapshot.backends) == 2

    def test_activity_connection_cleanup(
        self, activity_tracker: ConnectionActivityTracker
    ) -> None:
        """Test that connections are cleaned up after context exit."""
        with activity_tracker.track_connection(
            session_id="temp",
            backend_name="test",
            connection_type=ConnectionType.STREAMING,
        ):
            activity_tracker.increment_rx("temp", "test", 100)
            assert activity_tracker.get_connection_count() == 1

        # After context exit, connection should be removed
        assert activity_tracker.get_connection_count() == 0
        snapshot = activity_tracker.get_global_snapshot()
        assert snapshot.total_active_connections == 0


class TestActivityEndpointDirect:
    """Direct tests for the activity endpoint function."""

    @pytest.mark.asyncio
    async def test_get_activity_returns_global_summary(
        self, activity_tracker: ConnectionActivityTracker
    ) -> None:
        """Test get_activity returns correct summary."""
        with patch(
            "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
            return_value=activity_tracker,
        ):
            # Add activity
            with activity_tracker.track_connection(
                session_id="test",
                backend_name="backend",
                connection_type=ConnectionType.STREAMING,
            ):
                activity_tracker.increment_rx("test", "backend", 500)
                activity_tracker.increment_tx("test", "backend", 250)

                result = await get_activity()

            assert result.enabled is True
            assert result.total_active_connections == 1
            assert result.total_bytes_rx == 500
            assert result.total_bytes_tx == 250

    @pytest.mark.asyncio
    async def test_get_activity_empty(
        self, activity_tracker: ConnectionActivityTracker
    ) -> None:
        """Test get_activity with no connections."""
        with patch(
            "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
            return_value=activity_tracker,
        ):
            result = await get_activity()

            assert result.enabled is True
            assert result.total_active_connections == 0
            assert result.total_bytes_rx == 0
            assert result.total_bytes_tx == 0

    @pytest.mark.asyncio
    async def test_get_activity_disabled(self) -> None:
        """Test get_activity when tracking is disabled."""
        with patch(
            "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
            return_value=None,
        ):
            result = await get_activity()

            assert result.enabled is False
            assert result.total_active_connections == 0
            assert result.total_bytes_rx == 0
            assert result.total_bytes_tx == 0
