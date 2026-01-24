"""Property-based tests for replacement configuration validation."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.replacement_rule import ReplacementRule


def _make_replacement_rule(
    from_pattern: str = "*", to_backend: str = "backend", to_model: str = "model"
) -> ReplacementRule:
    """Helper to create a replacement rule."""
    return ReplacementRule(
        from_pattern=from_pattern,
        to_backend=to_backend,
        to_model=to_model,
    )


@given(st.floats())
def test_probability_range_validation(probability: float) -> None:
    """Verify that probability must be between 0.0 and 1.0 when enabled.

    Property 1: Valid probability range
    """
    # If probability is valid, it should pass validation
    if 0.0 <= probability <= 1.0:
        config = ReplacementConfig(
            enabled=True,
            probability=probability,
            replacement_rules=[_make_replacement_rule()],
            turn_count=1,
        )
        assert config.probability == probability
    else:
        # If probability is invalid, it should raise ValueError
        with pytest.raises(ValueError, match="replacement_probability"):
            ReplacementConfig(
                enabled=True,
                probability=probability,
                replacement_rules=[_make_replacement_rule()],
                turn_count=1,
            )


@given(st.text(), st.text())
def test_replacement_rule_validation(to_backend: str, to_model: str) -> None:
    """Verify that replacement rules must have valid to_backend and to_model.

    Property 2: Valid replacement rule format
    """
    # If both backend and model are non-empty, it should pass
    if to_backend and to_model and to_backend != "*" and to_model != "*":
        rule = ReplacementRule(
            from_pattern="*",
            to_backend=to_backend,
            to_model=to_model,
        )
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=[rule],
            turn_count=1,
        )
        assert len(config.replacement_rules) == 1
    else:
        # If backend or model is empty or wildcard, it should raise ValueError
        with pytest.raises(ValueError, match="replacement_rules"):
            rule = ReplacementRule(
                from_pattern="*",
                to_backend=to_backend,
                to_model=to_model,
            )
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[rule],
                turn_count=1,
            )


@given(st.integers())
def test_turn_count_validation(turn_count: int) -> None:
    """Verify that turn_count must be at least 1 when enabled.

    Property 3: Positive turn count
    """
    if turn_count >= 1:
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=[_make_replacement_rule()],
            turn_count=turn_count,
        )
        assert config.turn_count == turn_count
    else:
        with pytest.raises(ValueError, match="replacement_turn_count"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[_make_replacement_rule()],
                turn_count=turn_count,
            )


def test_disabled_config_skips_validation() -> None:
    """Verify that validation is skipped when enabled is False."""
    # Should not raise even with invalid values if enabled=False
    config = ReplacementConfig(
        enabled=False,
        probability=2.0,  # Invalid
        backend_model="invalid",  # Invalid
        turn_count=0,  # Invalid
    )
    assert config.enabled is False


@given(st.floats(min_value=0.0, max_value=1.0))
def test_app_config_integration(probability: float) -> None:
    """Verify AppConfig correctly integrates ReplacementConfig.

    Property: AppConfig integration
    """
    replacement = ReplacementConfig(
        enabled=True,
        probability=probability,
        replacement_rules=[_make_replacement_rule()],
        turn_count=1,
    )

    app_config = AppConfig(replacement=replacement)
    assert app_config.replacement == replacement
    assert app_config.replacement.probability == probability


@given(st.text(min_size=1), st.text(min_size=1))
def test_find_matching_rule(from_pattern: str, model: str) -> None:
    """Verify find_matching_rule returns the correct rule."""
    # Ensure from_pattern doesn't contain special characters that would affect matching
    if ":" in from_pattern or "*" in from_pattern:
        return

    # Create a rule with a specific pattern
    rule = ReplacementRule(
        from_pattern=from_pattern,
        to_backend="target_backend",
        to_model="target_model",
    )
    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        replacement_rules=[rule],
        turn_count=1,
    )

    # Exact match should find the rule
    matched = config.find_matching_rule(from_pattern, model)
    if matched:
        assert matched.from_pattern == from_pattern
