"""Tests for failover route pruning using runtime state instead of config mutation."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, Mock

from src.core.config.app_config import AppConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.persistence import ConfigManager


def _make_mock_state(
    *, model_is_functional: Callable[[str], bool] = lambda x: True
) -> tuple[IApplicationState, AppConfig, Mock]:
    """Create a properly typed mock app state with a real AppConfig."""
    app_config = AppConfig(
        failover_routes={
            "route-a": {"policy": "k", "elements": ["openai:gpt-4"]},
            "route-b": {"policy": "k", "elements": ["gemini:gemini-pro"]},
        }
    )
    mock_state = MagicMock(spec=IApplicationState)
    mock_state.app_config = app_config
    set_failover_route_mock = Mock()
    mock_state.set_failover_route = set_failover_route_mock

    # Patch model_is_functional on the instance so _prune_unavailable_routes
    # does not depend on real backend API keys.
    app_config.model_is_functional = Mock(  # type: ignore[assignment]
        side_effect=model_is_functional
    )

    return mock_state, app_config, set_failover_route_mock


def test_prune_unavailable_routes_uses_runtime_state_not_config_mutation() -> None:
    """Pruning should store effective routes in runtime state, not mutate config."""
    mock_state, app_config, set_mock = _make_mock_state()
    manager = ConfigManager(app=Mock(), path=":memory:", app_state=mock_state)

    initial_routes = dict(app_config.failover_routes)

    manager._prune_unavailable_routes()

    # Config should NOT be mutated
    assert app_config.failover_routes == initial_routes

    # Runtime state SHOULD be updated via set_failover_route
    assert set_mock.call_count == 2  # type: ignore[attr-defined]


def test_prune_unavailable_routes_filters_unfunctional_backends() -> None:
    """Routes with non-functional backends should be excluded from effective routes."""
    mock_state, _, set_mock = _make_mock_state(
        model_is_functional=lambda x: x.startswith("openai:")
    )
    manager = ConfigManager(app=Mock(), path=":memory:", app_state=mock_state)

    manager._prune_unavailable_routes()

    # Only openai route should be set in runtime state
    calls = set_mock.call_args_list  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0][0][0] == "route-a"


def test_prune_unavailable_routes_handles_empty_elements() -> None:
    """Routes with empty elements should be excluded from effective routes."""
    mock_state, app_config, set_mock = _make_mock_state()
    app_config.failover_routes = {
        "empty-route": {"policy": "k", "elements": []},
        "valid-route": {"policy": "k", "elements": ["openai:gpt-4"]},
    }
    manager = ConfigManager(app=Mock(), path=":memory:", app_state=mock_state)

    manager._prune_unavailable_routes()

    # Only valid route should be set
    calls = set_mock.call_args_list  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0][0][0] == "valid-route"


def test_prune_unavailable_routes_skips_when_no_app_config() -> None:
    """Pruning should be a no-op when app_config is not available."""
    mock_state = MagicMock(spec=IApplicationState)
    mock_state.app_config = None

    manager = ConfigManager(app=Mock(), path=":memory:", app_state=mock_state)

    # Should not raise
    manager._prune_unavailable_routes()
