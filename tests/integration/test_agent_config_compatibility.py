"""Integration tests for agent configuration compatibility with model replacement.

This module tests that model replacement works correctly with agent configuration,
ensuring that agent settings are preserved when routing to replacement models.

Feature: random-model-replacement
Validates: Requirements 7.5
"""

from __future__ import annotations

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_service(
    probability: float = 1.0,
    backend_model: str = "replacement-backend:replacement-model",
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


def create_test_context_with_agent_config(
    agent_config: dict | None = None,
) -> RequestContext:
    """Helper to create a test request context with agent configuration."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add agent configuration to context state
    if agent_config is not None:
        if context.state is None:
            context.state = {}
        context.state["agent_config"] = agent_config

    return context


@pytest.mark.asyncio
async def test_agent_config_preserved_with_replacement() -> None:
    """Test that agent configuration is preserved when replacement is active.

    When replacement is active and agent configuration is present, the agent
    settings should remain unchanged when routing to the replacement backend.

    Validates: Requirements 7.5
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with agent configuration
    agent_config = {
        "agent_name": "test-agent",
        "temperature": 0.7,
        "max_tokens": 2000,
        "system_prompt": "You are a helpful assistant.",
        "tools": ["calculator", "search"],
    }
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should trigger with probability=1.0"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify agent configuration is preserved
    assert context.state is not None
    assert "agent_config" in context.state
    assert context.state["agent_config"] == agent_config
    assert context.state["agent_config"]["agent_name"] == "test-agent"
    assert context.state["agent_config"]["temperature"] == 0.7
    assert context.state["agent_config"]["max_tokens"] == 2000
    assert (
        context.state["agent_config"]["system_prompt"] == "You are a helpful assistant."
    )
    assert context.state["agent_config"]["tools"] == ["calculator", "search"]


@pytest.mark.asyncio
async def test_agent_config_preserved_across_turns() -> None:
    """Test that agent configuration persists across multiple replacement turns.

    When replacement is active for multiple turns, agent configuration should
    remain consistent throughout the replacement window.

    Validates: Requirements 7.5
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with agent configuration
    agent_config = {
        "agent_id": "agent-123",
        "capabilities": ["code_generation", "debugging"],
        "preferences": {"verbose": True, "explain_steps": True},
    }
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate 3 turns
    for turn in range(3):
        # Verify replacement is active
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        if turn < 2:  # First 2 turns should use replacement
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"

        # Verify agent configuration is still present and unchanged
        assert context.state is not None
        assert "agent_config" in context.state
        assert context.state["agent_config"] == agent_config
        assert context.state["agent_config"]["agent_id"] == "agent-123"
        assert context.state["agent_config"]["capabilities"] == [
            "code_generation",
            "debugging",
        ]
        assert context.state["agent_config"]["preferences"]["verbose"] is True

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, agent configuration should still be preserved
    assert context.state is not None
    assert "agent_config" in context.state
    assert context.state["agent_config"] == agent_config


@pytest.mark.asyncio
async def test_no_agent_config_with_replacement() -> None:
    """Test that replacement works when no agent configuration is present.

    When agent configuration is not present, replacement should work normally
    without requiring agent configuration data.

    Validates: Requirements 7.5
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context without agent configuration
    context = create_test_context_with_agent_config(agent_config=None)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"


@pytest.mark.asyncio
async def test_complex_agent_config_preserved() -> None:
    """Test that complex agent configuration structures are preserved.

    When agent configuration contains nested structures, all data should be
    preserved when using replacement models.

    Validates: Requirements 7.5
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with complex agent configuration
    agent_config = {
        "agent_metadata": {
            "id": "agent-456",
            "version": "2.0",
            "created_at": "2024-01-01T00:00:00Z",
        },
        "behavior": {
            "response_style": "concise",
            "code_style": {
                "language": "python",
                "formatting": "black",
                "max_line_length": 88,
            },
        },
        "constraints": {
            "max_iterations": 10,
            "timeout_seconds": 300,
            "allowed_operations": ["read", "write", "execute"],
        },
        "context": {
            "project_root": "/path/to/project",
            "files_in_scope": ["main.py", "utils.py"],
        },
    }
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify complex agent configuration is fully preserved
    assert context.state is not None
    assert "agent_config" in context.state
    assert context.state["agent_config"] == agent_config

    # Verify nested structures
    assert context.state["agent_config"]["agent_metadata"]["id"] == "agent-456"
    assert (
        context.state["agent_config"]["behavior"]["code_style"]["language"] == "python"
    )
    assert context.state["agent_config"]["constraints"]["max_iterations"] == 10
    assert (
        context.state["agent_config"]["context"]["project_root"] == "/path/to/project"
    )


@pytest.mark.asyncio
async def test_agent_config_not_modified_by_replacement() -> None:
    """Test that replacement does not modify agent configuration.

    When replacement is active, the replacement service should not add, remove,
    or modify any agent configuration values.

    Validates: Requirements 7.5
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=2)

    # Create context with agent configuration
    original_agent_config = {
        "setting1": "value1",
        "setting2": 42,
        "setting3": [1, 2, 3],
        "setting4": {"nested": "data"},
    }
    # Create a deep copy to compare later
    import copy

    agent_config_copy = copy.deepcopy(original_agent_config)

    context = create_test_context_with_agent_config(original_agent_config)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Process multiple turns
    for _ in range(2):
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )
        service.complete_turn(session_id)

    # Verify agent configuration was not modified
    assert context.state is not None
    assert "agent_config" in context.state
    assert context.state["agent_config"] == agent_config_copy

    # Verify no keys were added or removed
    assert set(context.state["agent_config"].keys()) == set(agent_config_copy.keys())

    # Verify all values remain unchanged
    for key in agent_config_copy:
        assert context.state["agent_config"][key] == agent_config_copy[key]
