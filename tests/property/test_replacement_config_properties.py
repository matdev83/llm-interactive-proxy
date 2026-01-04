"""Property-based tests for replacement configuration validation."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.replacement_config import ReplacementConfig


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
            backend_model="backend:model",
            turn_count=1,
        )
        assert config.probability == probability
    else:
        # If probability is invalid, it should raise ValueError
        with pytest.raises(ValueError, match="replacement_probability"):
            ReplacementConfig(
                enabled=True,
                probability=probability,
                backend_model="backend:model",
                turn_count=1,
            )


@given(st.text())
def test_backend_model_format_validation(backend_model: str) -> None:
    """Verify that backend_model must contain a colon when enabled.

    Property 2: Valid backend:model format
    """
    # If backend_model is valid (non-empty and contains colon), it should pass
    if backend_model and ":" in backend_model:
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            backend_model=backend_model,
            turn_count=1,
        )
        assert config.backend_model == backend_model
    else:
        # If backend_model is invalid, it should raise ValueError
        with pytest.raises(ValueError, match="replacement_backend_model"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                backend_model=backend_model,
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
            backend_model="backend:model",
            turn_count=turn_count,
        )
        assert config.turn_count == turn_count
    else:
        with pytest.raises(ValueError, match="replacement_turn_count"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                backend_model="backend:model",
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
        backend_model="backend:model",
        turn_count=1,
    )

    app_config = AppConfig(replacement=replacement)
    assert app_config.replacement == replacement
    assert app_config.replacement.probability == probability


@given(st.text(min_size=1), st.text(min_size=1))
def test_parse_backend_model(backend: str, model: str) -> None:
    """Verify parsing of backend:model string."""
    # Ensure backend doesn't contain colon to avoid ambiguity in split
    if ":" in backend:
        return

    backend_model = f"{backend}:{model}"
    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model=backend_model,
        turn_count=1,
    )

    parsed = config.parse_backend_model()
    assert parsed.backend == backend
    assert parsed.model == model
