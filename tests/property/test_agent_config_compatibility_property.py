"""Property-based tests for agent configuration compatibility with model replacement.

Feature: random-model-replacement
Property: 30
Validates: Requirements 7.5
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


def create_test_service(
    probability: float,
    backend_model: str = "replacement-backend:replacement-model",
    turn_count: int = 1,
    random_generator: callable | None = None,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    backend_name = backend_model.split(":", 1)[0]
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend(backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry, random_generator)


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


# Strategy for generating agent configuration dictionaries
agent_config_strategy = st.dictionaries(
    keys=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "P")),
    ),
    values=st.one_of(
        st.text(min_size=0, max_size=50),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(
            min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        st.booleans(),
        st.lists(st.integers(min_value=0, max_value=100), min_size=0, max_size=5),
    ),
    min_size=0,
    max_size=10,
)


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    agent_config=agent_config_strategy,
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_30_agent_configuration_preservation(
    probability: float, turn_count: int, agent_config: dict
) -> None:
    """
    Property 30: Agent configuration preservation.

    For any session with agent configuration, the agent configuration must
    remain unchanged when routing to replacement models.

    Validates: Requirements 7.5
    """

    # Create service with deterministic random to control replacement
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create a deep copy of agent config to compare later
    agent_config_copy = copy.deepcopy(agent_config)

    # Create context with agent configuration
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn checks probability
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify agent configuration is preserved
    if agent_config:  # Only check if agent_config is not empty
        assert (
            context.state is not None
        ), "Context state should exist when agent config is present"
        assert (
            "agent_config" in context.state
        ), "Agent config should be in context state"
        assert context.state["agent_config"] == agent_config_copy, (
            f"Agent configuration should be preserved: expected {agent_config_copy}, "
            f"got {context.state.get('agent_config')}"
        )

    # Verify the effective backend is correct based on replacement state
    if should_replace:
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"
    else:
        assert effective_backend == "original-backend"
        assert effective_model == "original-model"


@given(
    turn_count=st.integers(min_value=1, max_value=4),  # Reduced from 5 for performance
    agent_config=agent_config_strategy,
)
@property_test_settings(
    max_examples=15, suppress_health_check=[HealthCheck.filter_too_much]
)  # Reduced from default 50 for performance
@pytest.mark.asyncio
async def test_agent_config_preserved_across_replacement_window(
    turn_count: int, agent_config: dict
) -> None:
    """
    Test that agent configuration persists throughout the replacement window.

    For any replacement window with multiple turns, agent configuration should
    remain unchanged across all turns.

    Validates: Requirements 7.5
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create a deep copy of agent config to compare later
    agent_config_copy = copy.deepcopy(agent_config)

    # Create context with agent configuration
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate all turns in the replacement window
    for turn in range(turn_count):
        # Verify agent configuration is preserved
        if agent_config:  # Only check if agent_config is not empty
            assert context.state is not None
            assert "agent_config" in context.state
            assert (
                context.state["agent_config"] == agent_config_copy
            ), f"Agent configuration should be preserved on turn {turn + 1}/{turn_count}"

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # During the window, replacement should be active
        if turn < turn_count - 1:
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, verify agent configuration is still preserved
    if agent_config:
        assert context.state is not None
        assert "agent_config" in context.state
        assert context.state["agent_config"] == agent_config_copy


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_no_agent_config_does_not_break_replacement(
    probability: float, turn_count: int
) -> None:
    """
    Test that replacement works when no agent configuration is present.

    For any request without agent configuration, replacement should work normally.

    Validates: Requirements 7.5
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context without agent configuration
    context = create_test_context_with_agent_config(agent_config=None)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Get effective backend:model - should work without errors
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify the effective backend is correct based on replacement state
    if should_replace:
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"
    else:
        assert effective_backend == "original-backend"
        assert effective_model == "original-model"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    agent_config=agent_config_strategy,
)
@property_test_settings(
    suppress_health_check=[HealthCheck.filter_too_much], max_examples=20
)
@pytest.mark.asyncio
async def test_agent_config_keys_not_modified(
    probability: float, turn_count: int, agent_config: dict
) -> None:
    """
    Test that replacement does not add or remove agent configuration keys.

    For any agent configuration, the set of keys should remain unchanged
    when using replacement models.

    Validates: Requirements 7.5
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Store original keys
    original_keys = set(agent_config.keys())

    # Create context with agent configuration
    context = create_test_context_with_agent_config(agent_config)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify agent configuration keys are unchanged
    if agent_config:  # Only check if agent_config is not empty
        assert context.state is not None
        assert "agent_config" in context.state
        current_keys = set(context.state["agent_config"].keys())
        assert current_keys == original_keys, (
            f"Agent configuration keys should not be modified: "
            f"original={original_keys}, current={current_keys}"
        )
