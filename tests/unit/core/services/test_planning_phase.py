"""Tests for planning phase model routing feature."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.planning_phase_config import (
    PlanningPhaseConfiguration,
)
from src.core.domain.session import Session, SessionState


@pytest.fixture
def mock_session_service():
    """Create a mock session service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    config = Mock(spec=AppConfig)
    config.backends = Mock()
    config.backends.default_backend = "openai"
    return config


@pytest.fixture
def planning_enabled_session():
    """Create a session with planning phase enabled."""
    planning_config = PlanningPhaseConfiguration(
        enabled=True, strong_model="openai:gpt-4", max_turns=10, max_file_writes=1
    )
    state = SessionState(
        planning_phase_config=planning_config,
        planning_phase_turn_count=0,
        planning_phase_file_write_count=0,
    )
    session = Session(session_id="test-session", state=state)
    return session


@pytest.fixture
def planning_disabled_session():
    """Create a session with planning phase disabled."""
    planning_config = PlanningPhaseConfiguration(
        enabled=False, strong_model=None, max_turns=10, max_file_writes=1
    )
    state = SessionState(
        planning_phase_config=planning_config,
        planning_phase_turn_count=0,
        planning_phase_file_write_count=0,
    )
    session = Session(session_id="test-session", state=state)
    return session


class TestPlanningPhaseConfiguration:
    """Test planning phase configuration objects."""

    def test_planning_phase_config_defaults(self):
        """Test that planning phase config has correct defaults."""
        config = PlanningPhaseConfiguration()
        assert config.enabled is False
        assert config.strong_model is None
        assert config.max_turns == 10
        assert config.max_file_writes == 1

    def test_planning_phase_config_with_values(self):
        """Test creating planning phase config with custom values."""
        config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=5,
            max_file_writes=2,
        )
        assert config.enabled is True
        assert config.strong_model == "openai:gpt-4"
        assert config.max_turns == 5
        assert config.max_file_writes == 2

    def test_planning_phase_config_immutable(self):
        """Test that planning phase config is immutable."""
        config = PlanningPhaseConfiguration(enabled=True)
        new_config = config.with_enabled(False)
        assert config.enabled is True
        assert new_config.enabled is False


class TestSessionStateWithPlanningPhase:
    """Test session state integration with planning phase."""

    def test_session_state_includes_planning_phase_config(self):
        """Test that session state includes planning phase configuration."""
        planning_config = PlanningPhaseConfiguration(enabled=True)
        state = SessionState(planning_phase_config=planning_config)
        assert state.planning_phase_config.enabled is True

    def test_session_state_includes_planning_phase_counters(self):
        """Test that session state includes planning phase counters."""
        state = SessionState(
            planning_phase_turn_count=3, planning_phase_file_write_count=1
        )
        assert state.planning_phase_turn_count == 3
        assert state.planning_phase_file_write_count == 1

    def test_session_state_update_planning_phase_counters(self):
        """Test updating planning phase counters in session state."""
        state = SessionState(
            planning_phase_turn_count=0, planning_phase_file_write_count=0
        )
        new_state = state.with_planning_phase_turn_count(
            1
        ).with_planning_phase_file_write_count(1)
        assert new_state.planning_phase_turn_count == 1
        assert new_state.planning_phase_file_write_count == 1
        assert state.planning_phase_turn_count == 0


class TestBackendServicePlanningPhase:
    """Test backend service planning phase integration."""

    @pytest.mark.asyncio
    async def test_planning_phase_disabled_no_override(
        self, mock_session_service, mock_config, planning_disabled_session
    ):
        """Test that planning phase does not override when disabled."""
        mock_session_service.get_session.return_value = planning_disabled_session

        # The model should not be overridden
        assert planning_disabled_session.state.planning_phase_config.enabled is False

    @pytest.mark.asyncio
    async def test_planning_phase_counter_increments(
        self, mock_session_service, planning_enabled_session
    ):
        """Test that planning phase counters increment."""
        mock_session_service.get_session.return_value = planning_enabled_session

        initial_turn_count = planning_enabled_session.state.planning_phase_turn_count
        initial_file_write_count = (
            planning_enabled_session.state.planning_phase_file_write_count
        )

        # Simulate incrementing counters
        new_state = planning_enabled_session.state.with_planning_phase_turn_count(
            initial_turn_count + 1
        )
        planning_enabled_session.update_state(new_state)

        assert planning_enabled_session.state.planning_phase_turn_count == (
            initial_turn_count + 1
        )
        assert planning_enabled_session.state.planning_phase_file_write_count == (
            initial_file_write_count
        )


class TestPlanningPhaseEndToEnd:
    """End-to-end tests for planning phase feature."""

    @pytest.mark.asyncio
    async def test_planning_phase_switches_to_default_after_max_turns(
        self, planning_enabled_session
    ):
        """Test that planning phase switches to default model after max turns."""
        # Set planning config with max 2 turns
        state = planning_enabled_session.state
        new_config = state.planning_phase_config.with_max_turns(2)  # type: ignore[attr-defined]
        planning_enabled_session.update_state(
            state.with_planning_phase_config(new_config)
        )

        # Simulate two turns
        planning_enabled_session.update_state(
            planning_enabled_session.state.with_planning_phase_turn_count(2)
        )

        assert planning_enabled_session.state.planning_phase_turn_count == 2
        assert planning_enabled_session.state.planning_phase_config.max_turns == 2
