"""Tests for secure state service utilities."""

from unittest.mock import MagicMock

import pytest
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.secure_state_service import SecureStateService, StateAccessProxy


class _DummyState:
    """Simple stand-in for FastAPI app.state."""


def test_state_access_proxy_allows_session_id_attribute() -> None:
    """Setting session_id should be allowed for middleware compatibility."""
    proxy = StateAccessProxy(_DummyState(), [])

    proxy.session_id = "abc123"

    assert proxy.session_id == "abc123"


def test_secure_state_service_limits_access_log_growth() -> None:
    """SecureStateService should cap its access log to prevent memory leaks."""

    app_state = MagicMock(spec=IApplicationState)
    app_state.get_command_prefix.return_value = "!/"
    app_state.get_api_key_redaction_enabled.return_value = True
    app_state.get_disable_interactive_commands.return_value = False
    app_state.get_failover_routes.return_value = []

    service = SecureStateService(app_state, max_access_log_entries=3)

    service.get_command_prefix()
    service.get_api_key_redaction_enabled()
    service.get_disable_interactive_commands()
    service.get_failover_routes()
    service.get_command_prefix()

    operations = [entry["operation"] for entry in service.get_access_log()]

    assert len(operations) == 3
    assert operations == [
        "get_disable_interactive_commands",
        "get_failover_routes",
        "get_command_prefix",
    ]


def test_secure_state_service_rejects_non_positive_access_log_limit() -> None:
    """Constructor should reject zero or negative log limits to avoid silent issues."""

    app_state = MagicMock(spec=IApplicationState)

    with pytest.raises(ValueError):
        SecureStateService(app_state, max_access_log_entries=0)
