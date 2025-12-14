"""Unit tests for PlanningPhaseManager service.

Tests the extracted PlanningPhaseManager service for equivalence with
BackendService planning phase methods.

Feature: backend-service-refactoring
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.planning_phase_config import (
    PlanningPhaseConfiguration,
)
from src.core.domain.session import Session, SessionState
from src.core.services.planning_phase_manager import PlanningPhaseManager


class TestPlanningPhaseManagerApplyIfNeeded:
    """Tests for apply_if_needed method."""

    @pytest.mark.asyncio
    async def test_no_session_does_nothing(self) -> None:
        """When session is None, no changes occur."""
        manager = PlanningPhaseManager(session_service=AsyncMock())
        await manager.apply_if_needed(None, "openai")
        # Should complete without error

    @pytest.mark.asyncio
    async def test_no_state_does_nothing(self) -> None:
        """When session.state is None, no changes occur."""
        manager = PlanningPhaseManager(session_service=AsyncMock())
        session = Mock()
        session.state = None
        await manager.apply_if_needed(session, "openai")
        # Should complete without error

    @pytest.mark.asyncio
    async def test_disabled_planning_does_nothing(self) -> None:
        """When planning phase is disabled, no model switch occurs."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=False,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="anthropic", model="claude-3-opus"
            ),
            planning_phase_config=planning_config,
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"

    @pytest.mark.asyncio
    async def test_no_strong_model_does_nothing(self) -> None:
        """When strong_model is None, no model switch occurs."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model=None,
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="anthropic", model="claude-3-opus"
            ),
            planning_phase_config=planning_config,
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"

    @pytest.mark.asyncio
    async def test_switches_to_strong_model(self) -> None:
        """When below limits, should switch to strong model."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="anthropic", model="claude-3-opus"
            ),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "anthropic")

        assert session.state.backend_config.model == "gpt-4"
        assert session.state.backend_config.backend_type == "openai"

    @pytest.mark.asyncio
    async def test_stores_original_route(self) -> None:
        """First apply should store original route for restoration."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="anthropic", model="claude-3-opus"
            ),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "anthropic")

        assert session.state.planning_phase_original_backend == "anthropic"
        assert session.state.planning_phase_original_model == "claude-3-opus"

    @pytest.mark.asyncio
    async def test_does_not_overwrite_original_route(self) -> None:
        """Subsequent applies should not overwrite original route."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=1,
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        # Original route should remain unchanged
        assert session.state.planning_phase_original_backend == "anthropic"
        assert session.state.planning_phase_original_model == "claude-3-opus"

    @pytest.mark.asyncio
    async def test_restores_when_turn_limit_reached(self) -> None:
        """When turn count >= max_turns, should restore original route."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=5,
            max_file_writes=10,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=5,  # At limit
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"
        assert session.state.planning_phase_original_backend is None
        assert session.state.planning_phase_original_model is None

    @pytest.mark.asyncio
    async def test_restores_when_file_write_limit_reached(self) -> None:
        """When file_write_count >= max_file_writes, should restore original route."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=3,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=2,
            planning_phase_file_write_count=3,  # At limit
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"
        assert session.state.planning_phase_original_backend is None
        assert session.state.planning_phase_original_model is None

    @pytest.mark.asyncio
    async def test_already_on_strong_model_does_nothing(self) -> None:
        """When already on strong model, no changes occur."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="openai", model="gpt-4"  # Already on strong model
            ),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test", state=state)

        await manager.apply_if_needed(session, "openai")

        # Model should remain the same
        assert session.state.backend_config.model == "gpt-4"
        assert session.state.backend_config.backend_type == "openai"


class TestPlanningPhaseManagerUpdateCounters:
    """Tests for update_counters method."""

    @pytest.mark.asyncio
    async def test_no_session_service_does_nothing(self) -> None:
        """When session_service is None, method returns early."""
        manager = PlanningPhaseManager(session_service=None)
        response = Mock()
        response.metadata = {}

        # Should not raise
        await manager.update_counters("test-session", response)

    @pytest.mark.asyncio
    async def test_session_not_found_does_nothing(self) -> None:
        """When session is not found, method returns early."""
        session_service = AsyncMock()
        session_service.get_session.return_value = None
        manager = PlanningPhaseManager(session_service=session_service)

        response = Mock()
        response.metadata = {}

        await manager.update_counters("nonexistent-session", response)
        # Should complete without error

    @pytest.mark.asyncio
    async def test_disabled_planning_does_nothing(self) -> None:
        """When planning phase is disabled, counters are not updated."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=False,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {}

        await manager.update_counters("test", response)

        assert session.state.planning_phase_turn_count == 0

    @pytest.mark.asyncio
    async def test_increments_turn_count(self) -> None:
        """Should increment turn count on update."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=3,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {"tool_calls": []}

        await manager.update_counters("test", response)

        assert session.state.planning_phase_turn_count == 4

    @pytest.mark.asyncio
    async def test_increments_file_write_count(self) -> None:
        """Should increment file write count based on tool calls."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=10,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=2,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3",
        )
        session = Session(session_id="test", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "write_file"}, "id": "1"},
                {"function": {"name": "edit_file"}, "id": "2"},
            ]
        }

        await manager.update_counters("test", response)

        assert session.state.planning_phase_file_write_count == 4
        assert session.state.planning_phase_turn_count == 1

    @pytest.mark.asyncio
    async def test_restores_when_limits_reached_after_update(self) -> None:
        """Should restore original route when limits reached after update."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=3,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=2,  # One more will hit limit
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {"tool_calls": []}

        await manager.update_counters("test", response)

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"
        assert session.state.planning_phase_original_backend is None

    @pytest.mark.asyncio
    async def test_already_at_limit_triggers_restore(self) -> None:
        """When already at limit on entry, should restore immediately."""
        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=5,
            max_file_writes=5,
        )
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=5,  # Already at limit
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {"tool_calls": []}

        await manager.update_counters("test", response)

        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.backend_config.backend_type == "anthropic"


class TestPlanningPhaseManagerCountFileWrites:
    """Tests for count_file_writes method."""

    def test_empty_tool_calls(self) -> None:
        """Should return 0 for empty tool_calls."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {"tool_calls": []}

        assert manager.count_file_writes(response) == 0

    def test_no_metadata(self) -> None:
        """Should return 0 when metadata is None."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = None

        assert manager.count_file_writes(response) == 0

    def test_no_tool_calls_key(self) -> None:
        """Should return 0 when tool_calls key is missing."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {"other_key": "value"}

        assert manager.count_file_writes(response) == 0

    def test_counts_write_file(self) -> None:
        """Should count write_file tool calls."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "write_file"}, "id": "1"},
            ]
        }

        assert manager.count_file_writes(response) == 1

    def test_counts_multiple_file_write_tools(self) -> None:
        """Should count all recognized file write tools."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "write_file"}, "id": "1"},
                {"function": {"name": "edit_file"}, "id": "2"},
                {"function": {"name": "patch_file"}, "id": "3"},
                {"function": {"name": "apply_diff"}, "id": "4"},
                {"function": {"name": "create_file"}, "id": "5"},
            ]
        }

        assert manager.count_file_writes(response) == 5

    def test_ignores_non_file_write_tools(self) -> None:
        """Should not count non-file-write tools."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "read_file"}, "id": "1"},
                {"function": {"name": "list_files"}, "id": "2"},
                {"function": {"name": "run_command"}, "id": "3"},
            ]
        }

        assert manager.count_file_writes(response) == 0

    def test_case_insensitive_matching(self) -> None:
        """Should match tool names case-insensitively."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "Write_File"}, "id": "1"},
                {"function": {"name": "EDIT_FILE"}, "id": "2"},
                {"function": {"name": "Create_File"}, "id": "3"},
            ]
        }

        assert manager.count_file_writes(response) == 3

    def test_openai_format_in_content(self) -> None:
        """Should count tool calls from OpenAI response.content format."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = None  # Force fallback to content
        response.content = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "write_file"}, "id": "1"},
                            {"function": {"name": "edit_file"}, "id": "2"},
                        ]
                    }
                }
            ]
        }

        assert manager.count_file_writes(response) == 2

    def test_mixed_file_write_and_other_tools(self) -> None:
        """Should only count file write tools in mixed list."""
        manager = PlanningPhaseManager()
        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "write_file"}, "id": "1"},
                {"function": {"name": "read_file"}, "id": "2"},
                {"function": {"name": "edit_file"}, "id": "3"},
                {"function": {"name": "list_files"}, "id": "4"},
            ]
        }

        assert manager.count_file_writes(response) == 2
