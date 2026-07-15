"""Unit tests for the diagnostics controller."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from src.core.app.controllers.diagnostics_controller import (
    BackendInstanceInfo,
    DiagnosticResponse,
    GlobalActivityInfo,
    get_activity,
    get_diagnostics,
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


class TestRoutingDiagnostics:
    @pytest.mark.asyncio
    async def test_get_diagnostics_includes_routing_eligibility_metadata(self) -> None:
        backend = MagicMock()
        backend.get_available_models.return_value = ["openai/gpt-4o"]
        backend.is_rate_limited.return_value = False
        backend.get_retry_after_remaining.return_value = None
        backend.is_backend_functional.return_value = True
        backend.get_validation_errors.return_value = []

        backend_service = MagicMock()
        backend_service.get_active_backends.return_value = {"openai.1": backend}

        routing_service = MagicMock()
        routing_service.get_model_capability_snapshot.return_value = SimpleNamespace(
            discovery_status_by_instance={
                "cursor-cli-acp.default": SimpleNamespace(
                    status="unavailable",
                    source="agent_list_models",
                    model_count=0,
                    error_code="model_discovery_failed",
                )
            }
        )
        routing_service.build_model_eligibility_diagnostics.return_value = {
            "default_preference_policy": "cost",
            "proxy_selection_scope": "proxy_instance_model_selection",
            "connector_scheduling_scope": "connector_internal_and_opaque",
            "truncation": {
                "model_limit": 200,
                "instances_per_model_limit": 20,
                "models_truncated": False,
                "models_omitted": 0,
            },
            "model_eligibility": [
                {
                    "model": "openai/gpt-4o",
                    "eligible_instances": ["openai.1", "openai.2"],
                    "eligible_instance_count": 2,
                    "instances_truncated": False,
                    "instances_omitted": 0,
                    "applied_preference_policy": "cost",
                    "equivalent_score_tie_sets": [["openai.1", "openai.2"]],
                }
            ],
        }

        state_manager = MagicMock()
        state_manager.get_all_instance_states.return_value = {
            "openai.1": {
                "status": "rate_limited",
                "cooldown_remaining": 7.5,
                "disabled_reason": None,
                "disabled_at": None,
            }
        }
        state_manager.get_all_model_states.return_value = {}
        resilience = MagicMock()
        resilience.state_manager = state_manager

        lifecycle = MagicMock()
        lifecycle.get_disabled_backends.return_value = {}

        with (
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_routing_service_if_available",
                return_value=routing_service,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_resilience_coordinator_if_available",
                return_value=resilience,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_lifecycle_manager_if_available",
                return_value=lifecycle,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
                return_value=None,
            ),
        ):
            result = await get_diagnostics(backend_service=backend_service)

        assert result.routing is not None
        assert result.routing.default_preference_policy == "cost"
        assert result.routing.model_eligibility[0].model == "openai/gpt-4o"
        assert result.routing.model_eligibility[0].equivalent_score_tie_sets == [
            ["openai.1", "openai.2"]
        ]
        assert result.instances[0].availability_status == "rate_limited"
        assert result.instances[0].cooldown_remaining_seconds == 7.5
        assert result.catalog_discovery[0].instance_name == "cursor-cli-acp.default"
        assert result.catalog_discovery[0].status == "unavailable"
        assert result.catalog_discovery[0].source == "agent_list_models"
        assert result.catalog_discovery[0].error_code == "model_discovery_failed"

    @pytest.mark.asyncio
    async def test_get_diagnostics_surfaces_disabled_instance_and_truncation(
        self,
    ) -> None:
        backend_service = MagicMock()
        backend_service.get_active_backends.return_value = {}

        routing_service = MagicMock()
        routing_service.build_model_eligibility_diagnostics.return_value = {
            "default_preference_policy": "round_robin",
            "proxy_selection_scope": "proxy_instance_model_selection",
            "connector_scheduling_scope": "connector_internal_and_opaque",
            "truncation": {
                "model_limit": 1,
                "instances_per_model_limit": 1,
                "models_truncated": True,
                "models_omitted": 2,
            },
            "model_eligibility": [],
        }

        disabled_info = SimpleNamespace(reason="auth failed", timestamp=1234.5)
        lifecycle = MagicMock()
        lifecycle.get_disabled_backends.return_value = {"openai.9": disabled_info}

        state_manager = MagicMock()
        state_manager.get_all_instance_states.return_value = {}
        state_manager.get_all_model_states.return_value = {}
        resilience = MagicMock()
        resilience.state_manager = state_manager

        with (
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_routing_service_if_available",
                return_value=routing_service,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_resilience_coordinator_if_available",
                return_value=resilience,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_lifecycle_manager_if_available",
                return_value=lifecycle,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
                return_value=None,
            ),
        ):
            result = await get_diagnostics(backend_service=backend_service)

        disabled = next(item for item in result.instances if item.name == "openai.9")
        assert disabled.availability_status == "disabled"
        assert disabled.validation_errors == ["auth failed"]
        assert result.routing is not None
        assert result.routing.truncation.models_truncated is True
        assert result.routing.truncation.models_omitted == 2

    @pytest.mark.asyncio
    async def test_get_diagnostics_reflects_reactivation_visibility_transition(
        self,
    ) -> None:
        backend = MagicMock()
        backend.get_available_models.return_value = ["openai/gpt-4o"]
        backend.is_rate_limited.return_value = False
        backend.get_retry_after_remaining.return_value = None
        backend.is_backend_functional.return_value = True
        backend.get_validation_errors.return_value = []

        backend_service = MagicMock()

        routing_service = MagicMock()
        routing_service.build_model_eligibility_diagnostics.return_value = {
            "default_preference_policy": "round_robin",
            "proxy_selection_scope": "proxy_instance_model_selection",
            "connector_scheduling_scope": "connector_internal_and_opaque",
            "truncation": {
                "model_limit": 200,
                "instances_per_model_limit": 20,
                "models_truncated": False,
                "models_omitted": 0,
            },
            "model_eligibility": [],
        }

        lifecycle = MagicMock()
        lifecycle.get_disabled_backends.side_effect = [
            {"openai.1": SimpleNamespace(reason="auth failed", timestamp=10.0)},
            {},
        ]

        state_manager = MagicMock()
        state_manager.get_all_instance_states.return_value = {}
        state_manager.get_all_model_states.return_value = {}
        resilience = MagicMock()
        resilience.state_manager = state_manager

        with (
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_routing_service_if_available",
                return_value=routing_service,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_resilience_coordinator_if_available",
                return_value=resilience,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_backend_lifecycle_manager_if_available",
                return_value=lifecycle,
            ),
            patch(
                "src.core.app.controllers.diagnostics_controller._get_activity_tracker_if_enabled",
                return_value=None,
            ),
        ):
            backend_service.get_active_backends.return_value = {}
            disabled_view = await get_diagnostics(backend_service=backend_service)

            backend_service.get_active_backends.return_value = {"openai.1": backend}
            active_view = await get_diagnostics(backend_service=backend_service)

        assert disabled_view.instances[0].availability_status == "disabled"
        assert active_view.instances[0].availability_status == "active"
