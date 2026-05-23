"""Integration tests for skipping replacement when models are identical.

This module tests that the replacement logic is skipped entirely when the
replacement model is the same as the original model, avoiding unnecessary
state management and processing.

Feature: random-model-replacement
Validates: Same model skip optimization
"""

from __future__ import annotations

import logging

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.replacement_rule import ReplacementRule
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_service(
    replacement_rules: list[ReplacementRule],
    probability: float = 1.0,
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register backends
    registry.register_backend("backend-a", mock_factory)
    registry.register_backend("backend-b", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        replacement_rules=replacement_rules,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


def create_test_context(headers: dict[str, str] | None = None) -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers=headers or {},
        cookies={},
        state=None,
        app_state=None,
    )


@pytest.mark.asyncio
async def test_should_replace_skips_when_same_model() -> None:
    """Test that should_replace returns False when replacement model is the same.

    When a replacement rule would replace a model with itself (same backend
    and model), should_replace() should return False to avoid unnecessary
    replacement activation and state management.
    """
    # Create rule that replaces backend-a:model-x with itself
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn (should be False - first turn is always original)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn (should be False - same model skip)
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert (
        not should_replace_second
    ), "Should skip replacement when replacement model is the same"

    # Verify effective model is still the original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "backend-a", "model-x"
    )
    assert effective_backend == "backend-a"
    assert effective_model == "model-x"

    # Verify no replacement is active
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be active"


@pytest.mark.asyncio
async def test_should_replace_allows_different_model() -> None:
    """Test that should_replace returns True when replacement model is different.

    For comparison, verify that when the replacement model is different,
    the replacement logic proceeds normally.
    """
    # Create rule that replaces backend-a:model-x with backend-b:model-y
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-b",
        to_model="model-y",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn (should be False - first turn is always original)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn (should be True - different model, probability=1.0)
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert should_replace_second, "Should allow replacement when model is different"


@pytest.mark.asyncio
async def test_activate_replacement_skips_when_same_model() -> None:
    """Test that activate_replacement returns early when replacement model is the same.

    When activate_replacement is called with a matching rule that would
    replace a model with itself, it should return early without activating
    replacement state.
    """
    # Create rule that replaces backend-a:model-x with itself
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"

    # Try to activate replacement
    await service.activate_replacement(session_id, "backend-a", "model-x")

    # Verify replacement is NOT active
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be activated for same model"

    # Verify effective model is still the original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "backend-a", "model-x"
    )
    assert effective_backend == "backend-a"
    assert effective_model == "model-x"


@pytest.mark.asyncio
async def test_activate_replacement_allows_different_model() -> None:
    """Test that activate_replacement works normally when replacement model is different.

    For comparison, verify that when the replacement model is different,
    activate_replacement activates the replacement state normally.
    """
    # Create rule that replaces backend-a:model-x with backend-b:model-y
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-b",
        to_model="model-y",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"

    # Activate replacement
    await service.activate_replacement(session_id, "backend-a", "model-x")

    # Verify replacement IS active
    state = service.get_state(session_id)
    assert state.active, "Replacement should be activated for different model"
    assert state.replacement_backend == "backend-b"
    assert state.replacement_model == "model-y"

    # Verify effective model is the replacement
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "backend-a", "model-x"
    )
    assert effective_backend == "backend-b"
    assert effective_model == "model-y"


@pytest.mark.asyncio
async def test_same_model_skip_with_wildcard_rule() -> None:
    """Test same model skip works with wildcard rules.

    When a wildcard rule would replace all models with a specific model,
    and a request comes in for that specific model, replacement should
    be skipped.
    """
    # Create wildcard rule that replaces all models with backend-a:model-x
    rule = ReplacementRule(
        from_pattern="*",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn on backend-a:model-x (should skip - first turn)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn on backend-a:model-x (should skip - same model)
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert (
        not should_replace_second
    ), "Should skip replacement when wildcard rule points to same model"

    # Verify no replacement is active
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be active"


@pytest.mark.asyncio
async def test_same_model_skip_with_partial_match_rule() -> None:
    """Test same model skip works with partial match rules.

    When a partial match rule (matching on model name substring) would
    replace a model with itself, replacement should be skipped.
    """
    # Create partial match rule that replaces models containing "model" with backend-a:model-x
    rule = ReplacementRule(
        from_pattern="model",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn on backend-a:model-x (should skip - first turn)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn on backend-a:model-x (should skip - same model)
    # The rule matches because "model" is in "model-x", but replacement is same as original
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert (
        not should_replace_second
    ), "Should skip replacement when partial match rule points to same model"

    # Verify no replacement is active
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be active"


@pytest.mark.asyncio
async def test_same_model_skip_logs_debug_message(caplog) -> None:
    """Test that skipping same model replacement logs appropriate debug message.

    When replacement is skipped due to same model, a debug log message should
    be emitted for monitoring and troubleshooting.
    """
    # Create rule that replaces backend-a:model-x with itself
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # Enable DEBUG logging
    with caplog.at_level(
        logging.DEBUG, logger="src.core.services.model_replacement_service"
    ):
        # First turn (mark first turn complete)
        service.should_replace(session_id, context, "backend-a", "model-x")

        # Second turn (should skip with debug log)
        should_replace_second = service.should_replace(
            session_id, context, "backend-a", "model-x"
        )

    assert not should_replace_second, "Should skip replacement"

    # Verify debug log message
    debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
    assert any(
        "is the same as original model" in record.message for record in debug_logs
    ), "Should log debug message when skipping same model"


@pytest.mark.asyncio
async def test_same_backend_different_model_allows_replacement() -> None:
    """Test that replacement proceeds when only model differs on same backend.

    When the backend is the same but the model is different, replacement
    should proceed normally.
    """
    # Create rule that replaces backend-a:model-x with backend-a:model-y (same backend, different model)
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-y",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn (mark first turn complete)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn (should allow replacement - different model)
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert (
        should_replace_second
    ), "Should allow replacement when model is different (even if backend is same)"


@pytest.mark.asyncio
async def test_different_backend_same_model_allows_replacement() -> None:
    """Test that replacement proceeds when only backend differs with same model name.

    When the model name is the same but the backend is different, replacement
    should proceed normally (this is a valid use case for testing different
    backends with the same model).
    """
    # Create rule that replaces backend-a:model-x with backend-b:model-x (different backend, same model name)
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-b",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn (mark first turn complete)
    should_replace_first = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert not should_replace_first, "First turn should always use original model"

    # Second turn (should allow replacement - different backend)
    should_replace_second = service.should_replace(
        session_id, context, "backend-a", "model-x"
    )
    assert (
        should_replace_second
    ), "Should allow replacement when backend is different (even if model name is same)"


@pytest.mark.asyncio
async def test_activate_replacement_logs_debug_when_same_model(caplog) -> None:
    """Test that activate_replacement logs debug message when skipping same model.

    When activate_replacement is called with a rule that would replace a model
    with itself, it should log a debug message and return early.
    """
    # Create rule that replaces backend-a:model-x with itself
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"

    # Enable DEBUG logging
    with caplog.at_level(
        logging.DEBUG, logger="src.core.services.model_replacement_service"
    ):
        # Try to activate replacement
        await service.activate_replacement(session_id, "backend-a", "model-x")

    # Verify debug log message from activate_replacement
    debug_logs = [record for record in caplog.records if record.levelname == "DEBUG"]
    assert any(
        "Skipping replacement activation" in record.message
        and "is the same as original model" in record.message
        for record in debug_logs
    ), "Should log debug message when skipping activation for same model"

    # Verify replacement is NOT active
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be activated"


@pytest.mark.asyncio
async def test_multiple_rules_with_same_model_skip() -> None:
    """Test same model skip with multiple replacement rules.

    When multiple rules are configured, ensure that same-model skip works
    correctly for each rule independently.
    """
    # Create rules:
    # 1. backend-a:model-x -> backend-a:model-x (same, should skip)
    # 2. backend-a:model-y -> backend-b:model-z (different, should allow)
    rules = [
        ReplacementRule(
            from_pattern="backend-a:model-x",
            to_backend="backend-a",
            to_model="model-x",
        ),
        ReplacementRule(
            from_pattern="backend-a:model-y",
            to_backend="backend-b",
            to_model="model-z",
        ),
    ]

    service = create_test_service(
        replacement_rules=rules,
        probability=1.0,
        turn_count=3,
    )

    context = create_test_context()

    # Test rule 1 (same model - should skip)
    session_id_1 = "session-1"

    # First turn
    service.should_replace(session_id_1, context, "backend-a", "model-x")

    # Second turn (should skip - same model)
    should_replace_1 = service.should_replace(
        session_id_1, context, "backend-a", "model-x"
    )
    assert not should_replace_1, "Should skip for same model rule"

    # Test rule 2 (different model - should allow)
    session_id_2 = "session-2"

    # First turn
    service.should_replace(session_id_2, context, "backend-a", "model-y")

    # Second turn (should allow - different model)
    should_replace_2 = service.should_replace(
        session_id_2, context, "backend-a", "model-y"
    )
    assert should_replace_2, "Should allow for different model rule"


@pytest.mark.asyncio
async def test_same_model_skip_avoids_state_pollution() -> None:
    """Test that skipping same model doesn't pollute session state.

    When replacement is skipped due to same model, the session state
    should remain clean and inactive (no partial state, no stale data).
    """
    # Create rule that replaces backend-a:model-x with itself
    rule = ReplacementRule(
        from_pattern="backend-a:model-x",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn
    service.should_replace(session_id, context, "backend-a", "model-x")

    # Second turn (should skip - same model)
    service.should_replace(session_id, context, "backend-a", "model-x")

    # Try to activate (should return early)
    await service.activate_replacement(session_id, "backend-a", "model-x")

    # Get state and verify it's clean/inactive
    state = service.get_state(session_id)
    assert not state.active, "State should be inactive"
    assert state.turns_remaining == 0, "Turns remaining should be 0"
    assert state.original_backend == "", "Original backend should be empty"
    assert state.original_model == "", "Original model should be empty"
    assert state.replacement_backend == "", "Replacement backend should be empty"
    assert state.replacement_model == "", "Replacement model should be empty"


@pytest.mark.asyncio
async def test_same_model_skip_with_case_sensitivity() -> None:
    """Test that same model check is case-sensitive.

    Model names should be compared with exact case matching. Different
    cases should be treated as different models.
    """
    # Create rule that replaces backend-a:Model-X with backend-a:model-x (different case)
    rule = ReplacementRule(
        from_pattern="backend-a:Model-X",
        to_backend="backend-a",
        to_model="model-x",
    )

    service = create_test_service(
        replacement_rules=[rule],
        probability=1.0,
        turn_count=3,
    )

    session_id = "test-session"
    context = create_test_context()

    # First turn
    service.should_replace(session_id, context, "backend-a", "Model-X")

    # Second turn (should allow - different case)
    should_replace = service.should_replace(session_id, context, "backend-a", "Model-X")
    assert should_replace, "Should allow replacement when model names differ in case"
