"""Property-based tests for PlanningPhaseManager.

Validates:
- Property 10: Planning Phase Transition (Requirements 10.1, 10.3)
- Property 11: File Write Counting (Requirements 10.4)

Feature: backend-service-refactoring
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.planning_phase_config import (
    PlanningPhaseConfiguration,
)
from src.core.domain.session import Session, SessionState


# Strategies for generating test data
@st.composite
def planning_phase_config_strategy(draw: st.DrawFn) -> PlanningPhaseConfiguration:
    """Generate valid PlanningPhaseConfiguration instances."""
    return PlanningPhaseConfiguration(
        enabled=draw(st.booleans()),
        strong_model=draw(
            st.one_of(
                st.none(),
                st.text(min_size=1, max_size=50).filter(lambda x: ":" not in x),
            ).map(lambda m: f"openai:{m}" if m else None)
        ),
        max_turns=draw(st.integers(min_value=1, max_value=100)),
        max_file_writes=draw(st.integers(min_value=1, max_value=50)),
    )


@st.composite
def backend_config_strategy(draw: st.DrawFn) -> BackendConfiguration:
    """Generate valid BackendConfiguration instances."""
    backend_types = ["openai", "anthropic", "gemini", "azure"]
    models = ["gpt-4", "gpt-3.5-turbo", "claude-3-opus", "gemini-pro"]
    return BackendConfiguration(
        backend_type=draw(st.sampled_from(backend_types)),
        model=draw(st.sampled_from(models)),
    )


@st.composite
def session_state_strategy(draw: st.DrawFn) -> SessionState:
    """Generate valid SessionState instances with planning phase config."""
    planning_config = draw(planning_phase_config_strategy())
    backend_config = draw(backend_config_strategy())
    turn_count = draw(st.integers(min_value=0, max_value=100))
    file_write_count = draw(st.integers(min_value=0, max_value=50))

    return SessionState(
        backend_config=backend_config,
        planning_phase_config=planning_config,
        planning_phase_turn_count=turn_count,
        planning_phase_file_write_count=file_write_count,
    )


@st.composite
def session_strategy(draw: st.DrawFn) -> Session:
    """Generate valid Session instances."""
    state = draw(session_state_strategy())
    session_id = draw(st.text(min_size=5, max_size=36, alphabet="abcdef0123456789-"))
    return Session(session_id=session_id, state=state)


FILE_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "patch_file",
        "apply_diff",
        "search_replace",
        "str_replace_editor",
        "write_to_file",
        "create_file",
        "modify_file",
        "apply_patch",
        "edit_notebook",
    }
)

NON_FILE_WRITE_TOOLS = [
    "read_file",
    "list_files",
    "search_files",
    "run_command",
    "execute",
    "get_context",
    "think",
]


@st.composite
def tool_call_strategy(draw: st.DrawFn, is_file_write: bool = False) -> dict[str, Any]:
    """Generate a tool call dict."""
    if is_file_write:
        tool_name = draw(st.sampled_from(list(FILE_WRITE_TOOLS)))
    else:
        tool_name = draw(st.sampled_from(NON_FILE_WRITE_TOOLS))

    return {
        "id": draw(st.text(min_size=1, max_size=30)),
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": draw(st.text(min_size=0, max_size=100)),
        },
    }


@st.composite
def response_with_tool_calls_strategy(
    draw: st.DrawFn, num_file_writes: int = 0
) -> Mock:
    """Generate a mock response with tool calls."""
    response = Mock()
    tool_calls = []

    # Add file write tool calls
    for _ in range(num_file_writes):
        tool_calls.append(draw(tool_call_strategy(is_file_write=True)))

    # Add some non-file-write tool calls
    num_other = draw(st.integers(min_value=0, max_value=5))
    for _ in range(num_other):
        tool_calls.append(draw(tool_call_strategy(is_file_write=False)))

    # Shuffle to mix the order
    draw(st.randoms()).shuffle(tool_calls)

    response.metadata = {"tool_calls": tool_calls}
    return response


class TestPlanningPhaseTransitionProperty:
    """Property 10: Planning Phase Transition (Requirements 10.1, 10.3).

    For any session in planning phase that exceeds max_turns or max_file_writes,
    the manager SHALL restore the original route.
    """

    @given(
        max_turns=st.integers(min_value=1, max_value=20),
        max_file_writes=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_restore_triggered_when_turn_limit_reached(
        self, max_turns: int, max_file_writes: int
    ) -> None:
        """When turn_count >= max_turns, restoration should be triggered."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        original_backend = "anthropic"
        original_model = "claude-3-opus"

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=max_turns,
            max_file_writes=max_file_writes,
        )

        # Create session at or beyond max turns
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=max_turns,  # At limit
            planning_phase_file_write_count=0,
            planning_phase_original_backend=original_backend,
            planning_phase_original_model=original_model,
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "openai")

        # Session should be restored to original backend/model
        assert session.state.backend_config.backend_type == original_backend
        assert session.state.backend_config.model == original_model
        assert session.state.planning_phase_original_backend is None
        assert session.state.planning_phase_original_model is None

    @given(
        max_turns=st.integers(min_value=1, max_value=20),
        max_file_writes=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_restore_triggered_when_file_write_limit_reached(
        self, max_turns: int, max_file_writes: int
    ) -> None:
        """When file_write_count >= max_file_writes, restoration should be triggered."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        original_backend = "anthropic"
        original_model = "claude-3-opus"

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=max_turns,
            max_file_writes=max_file_writes,
        )

        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=0,
            planning_phase_file_write_count=max_file_writes,  # At limit
            planning_phase_original_backend=original_backend,
            planning_phase_original_model=original_model,
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "openai")

        # Session should be restored to original backend/model
        assert session.state.backend_config.backend_type == original_backend
        assert session.state.backend_config.model == original_model
        assert session.state.planning_phase_original_backend is None
        assert session.state.planning_phase_original_model is None

    @given(
        current_turn=st.integers(min_value=0, max_value=5),
        max_turns=st.integers(min_value=10, max_value=20),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_no_restore_when_below_limits(
        self, current_turn: int, max_turns: int
    ) -> None:
        """When below both limits, no restoration should occur."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=max_turns,
            max_file_writes=10,
        )

        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type="anthropic", model="claude-3-opus"
            ),
            planning_phase_config=planning_config,
            planning_phase_turn_count=current_turn,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "openai")

        # Model should be switched to strong model (gpt-4), not restored
        assert session.state.backend_config.model == "gpt-4"
        assert session.state.backend_config.backend_type == "openai"

    @pytest.mark.asyncio
    async def test_disabled_planning_phase_no_changes(self) -> None:
        """When planning phase is disabled, no changes should occur."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=False,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )

        original_model = "claude-3-opus"
        original_backend = "anthropic"

        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type=original_backend, model=original_model
            ),
            planning_phase_config=planning_config,
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "openai")

        # No changes should be made
        assert session.state.backend_config.model == original_model
        assert session.state.backend_config.backend_type == original_backend

    @pytest.mark.asyncio
    async def test_no_strong_model_no_changes(self) -> None:
        """When strong_model is None, no changes should occur."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model=None,
            max_turns=10,
            max_file_writes=5,
        )

        original_model = "claude-3-opus"
        original_backend = "anthropic"

        state = SessionState(
            backend_config=BackendConfiguration(
                backend_type=original_backend, model=original_model
            ),
            planning_phase_config=planning_config,
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "openai")

        # No changes should be made
        assert session.state.backend_config.model == original_model
        assert session.state.backend_config.backend_type == original_backend


class TestFileWriteCountingProperty:
    """Property 11: File Write Counting (Requirements 10.4).

    For any response with tool calls, the manager SHALL correctly count
    file write operations.
    """

    @given(num_file_writes=st.integers(min_value=0, max_value=10))
    @settings(max_examples=100)
    def test_file_write_count_accuracy(self, num_file_writes: int) -> None:
        """count_file_writes should accurately count file write tool calls."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        # Build response with exact number of file write tools
        tool_calls = []

        # Add file write tools
        for i in range(num_file_writes):
            tool_name = list(FILE_WRITE_TOOLS)[i % len(FILE_WRITE_TOOLS)]
            tool_calls.append(
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }
            )

        # Add some non-file-write tools
        for i in range(3):
            tool_calls.append(
                {
                    "id": f"other_{i}",
                    "type": "function",
                    "function": {"name": NON_FILE_WRITE_TOOLS[i], "arguments": "{}"},
                }
            )

        response = Mock()
        response.metadata = {"tool_calls": tool_calls}

        count = manager.count_file_writes(response)
        assert count == num_file_writes

    @given(
        tool_names=st.lists(
            st.sampled_from(list(FILE_WRITE_TOOLS)), min_size=0, max_size=15
        )
    )
    @settings(max_examples=100)
    def test_all_file_write_tools_detected(self, tool_names: list[str]) -> None:
        """All recognized file write tools should be counted."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        tool_calls = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for i, name in enumerate(tool_names)
        ]

        response = Mock()
        response.metadata = {"tool_calls": tool_calls}

        count = manager.count_file_writes(response)
        assert count == len(tool_names)

    def test_empty_tool_calls_returns_zero(self) -> None:
        """Response with no tool calls should return 0."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        response = Mock()
        response.metadata = {"tool_calls": []}

        count = manager.count_file_writes(response)
        assert count == 0

    def test_no_metadata_returns_zero(self) -> None:
        """Response without metadata should return 0."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        response = Mock()
        response.metadata = None

        count = manager.count_file_writes(response)
        assert count == 0

    def test_openai_format_tool_calls(self) -> None:
        """Tool calls in OpenAI response.content format should be counted."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        response = Mock()
        # metadata must not have tool_calls key for fallback to content
        response.metadata = None
        response.content = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "write_file"}, "id": "1"},
                            {"function": {"name": "edit_file"}, "id": "2"},
                            {"function": {"name": "read_file"}, "id": "3"},
                        ]
                    }
                }
            ]
        }

        count = manager.count_file_writes(response)
        assert count == 2  # write_file and edit_file

    def test_case_insensitive_matching(self) -> None:
        """File write tool names should be matched case-insensitively."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        tool_calls = [
            {"function": {"name": "Write_File"}, "id": "1"},
            {"function": {"name": "EDIT_FILE"}, "id": "2"},
            {"function": {"name": "CREATE_FILE"}, "id": "3"},
        ]

        response = Mock()
        response.metadata = {"tool_calls": tool_calls}

        count = manager.count_file_writes(response)
        assert count == 3


class TestOriginalRoutePreservation:
    """Test that original route is persisted only once per planning phase."""

    @pytest.mark.asyncio
    async def test_original_route_stored_on_first_apply(self) -> None:
        """First apply should store the original route."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

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
            # No original route set yet
        )
        session = Session(session_id="test-session", state=state)

        await manager.apply_if_needed(session, "anthropic")

        # Original route should be stored - the backend_config's backend_type was anthropic
        # But parse_model_backend uses backend_config.model, so original_backend comes from default_backend
        # Since model="claude-3-opus" has no ":", it uses default_backend which is "anthropic"
        assert session.state.planning_phase_original_backend == "anthropic"
        assert session.state.planning_phase_original_model == "claude-3-opus"
        # Current route should be switched to strong model
        assert session.state.backend_config.backend_type == "openai"
        assert session.state.backend_config.model == "gpt-4"

    @pytest.mark.asyncio
    async def test_original_route_not_overwritten(self) -> None:
        """Subsequent applies should not overwrite the original route."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=10,
            max_file_writes=5,
        )

        # Session already has original route stored
        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=1,
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test-session", state=state)

        # Apply again - should not overwrite original
        await manager.apply_if_needed(session, "openai")

        assert session.state.planning_phase_original_backend == "anthropic"
        assert session.state.planning_phase_original_model == "claude-3-opus"


class TestUpdateCounters:
    """Test counter update functionality."""

    @pytest.mark.asyncio
    async def test_counter_increments(self) -> None:
        """update_counters should increment turn count."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

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
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
        )
        session = Session(session_id="test-session", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {"tool_calls": []}

        await manager.update_counters("test-session", response)

        assert session.state.planning_phase_turn_count == 1

    @pytest.mark.asyncio
    async def test_file_write_count_increments(self) -> None:
        """update_counters should increment file write count based on response."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

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
            planning_phase_turn_count=0,
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test-session", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {
            "tool_calls": [
                {"function": {"name": "write_file"}, "id": "1"},
                {"function": {"name": "edit_file"}, "id": "2"},
            ]
        }

        await manager.update_counters("test-session", response)

        assert session.state.planning_phase_turn_count == 1
        assert session.state.planning_phase_file_write_count == 2

    @pytest.mark.asyncio
    async def test_restoration_on_limit_reached_via_update(self) -> None:
        """Reaching limit via update_counters should trigger restoration."""
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        session_service = AsyncMock()
        manager = PlanningPhaseManager(session_service=session_service)

        planning_config = PlanningPhaseConfiguration(
            enabled=True,
            strong_model="openai:gpt-4",
            max_turns=2,
            max_file_writes=5,
        )

        state = SessionState(
            backend_config=BackendConfiguration(backend_type="openai", model="gpt-4"),
            planning_phase_config=planning_config,
            planning_phase_turn_count=1,  # One more turn will hit the limit
            planning_phase_file_write_count=0,
            planning_phase_original_backend="anthropic",
            planning_phase_original_model="claude-3-opus",
        )
        session = Session(session_id="test-session", state=state)
        session_service.get_session.return_value = session

        response = Mock()
        response.metadata = {"tool_calls": []}

        await manager.update_counters("test-session", response)

        # Should be restored
        assert session.state.backend_config.backend_type == "anthropic"
        assert session.state.backend_config.model == "claude-3-opus"
        assert session.state.planning_phase_original_backend is None
        assert session.state.planning_phase_original_model is None
