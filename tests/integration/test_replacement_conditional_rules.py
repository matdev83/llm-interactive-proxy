"""Integration tests for conditional replacement rules.

This module tests the new conditional replacement functionality with
multiple rules, pattern matching, and rule ordering.

Feature: random-model-replacement (conditional rules)
Validates: Pattern matching, rule ordering, multiple rules
"""

from unittest.mock import MagicMock

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.replacement_rule import ReplacementRule
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_context() -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )


def create_mock_registry_with_backends(*backend_names: str) -> BackendRegistry:
    """Create a mock backend registry with specified backends."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    for backend_name in backend_names:
        registry.register_backend(backend_name, mock_factory)

    return registry


@pytest.mark.asyncio
async def test_multiple_rules_exact_match_wins() -> None:
    """Test that exact match rule is selected before partial match."""
    registry = create_mock_registry_with_backends(
        "openai", "anthropic", "gemini-oauth-plan"
    )

    rules = [
        ReplacementRule(
            from_pattern="openai:gpt-4",
            to_backend="anthropic",
            to_model="claude-3-5-sonnet",
        ),
        ReplacementRule(
            from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
        ),
        ReplacementRule(
            from_pattern="gemini", to_backend="gemini-oauth-plan", to_model="gemini-3-pro"
        ),
    ]

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,  # Always replace for test
        replacement_rules=rules,
        turn_count=1,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"
    context = create_test_context()

    # Test exact match: openai:gpt-4 should match rule 0
    service.should_replace(session_id, context, "openai", "gpt-4")  # First turn skip
    assert service.should_replace(session_id, context, "openai", "gpt-4") is True
    await service.activate_replacement(session_id, "openai", "gpt-4")
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "openai", "gpt-4"
    )

    assert effective_backend == "anthropic"
    assert effective_model == "claude-3-5-sonnet"


@pytest.mark.asyncio
async def test_multiple_rules_partial_match_precedence() -> None:
    """Test rule ordering with multiple partial matches."""
    registry = create_mock_registry_with_backends(
        "openai", "anthropic", "gemini-oauth-plan"
    )

    rules = [
        ReplacementRule(
            from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
        ),
        ReplacementRule(
            from_pattern="claude", to_backend="anthropic", to_model="claude-3-haiku"
        ),
    ]

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        replacement_rules=rules,
        turn_count=1,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"
    context = create_test_context()

    # Test partial match: gpt-4-turbo should match rule 0 (contains "gpt-4")
    service.should_replace(session_id, context, "openai", "gpt-4-turbo")  # First turn skip
    assert service.should_replace(session_id, context, "openai", "gpt-4-turbo") is True
    await service.activate_replacement(session_id, "openai", "gpt-4-turbo")
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "openai", "gpt-4-turbo"
    )

    assert effective_backend == "openai"
    assert effective_model == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_gemini_flash_to_pro_replacement() -> None:
    """Test the specific use case: gemini-3-flash-preview -> gemini-3-pro-preview."""
    registry = create_mock_registry_with_backends(
        "gemini-oauth-free", "gemini-oauth-plan", "some-backend"
    )

    rules = [
        ReplacementRule(
            from_pattern="gemini-3-flash-preview",
            to_backend="gemini-oauth-plan",
            to_model="gemini-3-pro-preview",
        ),
    ]

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        replacement_rules=rules,
        turn_count=1,
    )

    service = ModelReplacementService(config, registry)
    context = create_test_context()

    # Test from different backends - should all match
    test_cases = [
        ("gemini-oauth-free", "gemini-3-flash-preview"),
        ("some-backend", "gemini-3-flash-preview"),
        ("gemini-oauth-plan", "gemini-3-flash-preview"),
    ]

    for i, (orig_backend, orig_model) in enumerate(test_cases):
        session_id = f"test-session-{i}"
        service.should_replace(session_id, context, orig_backend, orig_model)  # First turn skip
        assert (
            service.should_replace(session_id, context, orig_backend, orig_model)
            is True
        )
        await service.activate_replacement(session_id, orig_backend, orig_model)
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, orig_backend, orig_model
        )

        assert effective_backend == "gemini-oauth-plan"
        assert effective_model == "gemini-3-pro-preview"


@pytest.mark.asyncio
async def test_no_matching_rule_does_not_activate() -> None:
    """Test that replacement doesn't activate when no rule matches."""
    registry = create_mock_registry_with_backends("openai", "anthropic")

    rules = [
        ReplacementRule(
            from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
        ),
        ReplacementRule(
            from_pattern="claude", to_backend="anthropic", to_model="claude-3-haiku"
        ),
    ]

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,  # Always replace (if rule matches)
        replacement_rules=rules,
        turn_count=1,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"
    context = create_test_context()

    # Model doesn't match any rule
    assert (
        service.should_replace(
            session_id, context, "gemini-oauth-free", "gemini-3-flash-preview"
        )
        is False
    )

    # State should not be active
    state = service.get_state(session_id)
    assert state.active is False


@pytest.mark.asyncio
async def test_multiple_rules_from_yaml_config() -> None:
    """Test loading multiple rules from YAML-like dict (without wildcard)."""
    registry = create_mock_registry_with_backends(
        "openai", "anthropic", "gemini-oauth-plan"
    )

    # Simulate YAML-loaded config
    config_dict = {
        "enabled": True,
        "probability": 0.5,
        "replacement_rules": [
            {
                "from_pattern": "openai:gpt-4",
                "to_backend": "anthropic",
                "to_model": "claude-3-5-sonnet",
            },
            {
                "from_pattern": "gpt-4",
                "to_backend": "openai",
                "to_model": "gpt-3.5-turbo",
            },
            {
                "from_pattern": "gemini-3-flash-preview",
                "to_backend": "gemini-oauth-plan",
                "to_model": "gemini-3-pro-preview",
            },
        ],
        "turn_count": 3,
    }

    config = ReplacementConfig.model_validate(config_dict)
    service = ModelReplacementService(config, registry)
    context = create_test_context()

    # Test each rule matches correctly
    test_cases = [
        ("openai", "gpt-4", "anthropic", "claude-3-5-sonnet"),  # Exact match
        ("openai", "gpt-4-turbo", "openai", "gpt-3.5-turbo"),  # Partial match
        (
            "some-backend",
            "gemini-3-flash-preview",
            "gemini-oauth-plan",
            "gemini-3-pro-preview",
        ),  # Partial match
    ]

    for i, (orig_backend, orig_model, expected_backend, expected_model) in enumerate(
        test_cases
    ):
        session_id = f"test-session-{i}"

        # Force replacement with probability = 1.0
        mock_random = MagicMock(return_value=0.0)
        service._random_generator = mock_random

        service.should_replace(session_id, context, orig_backend, orig_model)  # First turn skip
        assert (
            service.should_replace(session_id, context, orig_backend, orig_model)
            is True
        )
        await service.activate_replacement(session_id, orig_backend, orig_model)
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, orig_backend, orig_model
        )

        assert effective_backend == expected_backend, (
            f"Expected backend {expected_backend}, got {effective_backend} "
            f"for {orig_backend}:{orig_model}"
        )
        assert effective_model == expected_model, (
            f"Expected model {expected_model}, got {effective_model} "
            f"for {orig_backend}:{orig_model}"
        )


@pytest.mark.asyncio
async def test_rule_ordering_matters() -> None:
    """Test that rule order matters - first match wins."""
    registry = create_mock_registry_with_backends("openai", "anthropic", "gemini-oauth-plan")

    # Put more specific rule first, then less specific
    rules = [
        ReplacementRule(
            from_pattern="openai:gpt-4", to_backend="anthropic", to_model="claude-3-5-sonnet"
        ),
        ReplacementRule(
            from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
        ),
    ]

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        replacement_rules=rules,
        turn_count=1,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"
    context = create_test_context()

    # Exact match should win over partial match
    service.should_replace(session_id, context, "openai", "gpt-4")  # First turn skip
    assert service.should_replace(session_id, context, "openai", "gpt-4") is True
    await service.activate_replacement(session_id, "openai", "gpt-4")
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "openai", "gpt-4"
    )

    # Should match exact rule (rule 0), not partial rule (rule 1)
    assert effective_backend == "anthropic"
    assert effective_model == "claude-3-5-sonnet"
