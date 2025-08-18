"""
Tests for domain model classes.
"""

import pytest
from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.session import (
    SessionInteraction,
    SessionState,
    SessionStateAdapter,
)


def test_backend_config_immutability():
    """Test that BackendConfig is immutable and with_* methods work."""
    # Arrange
    config = BackendConfig(backend_type="openai", model="gpt-4")

    # Act & Assert - Pydantic raises ValidationError for frozen models
    with pytest.raises(Exception) as excinfo:
        config.backend_type = "anthropic"  # type: ignore

    # Check that it's a frozen instance error
    assert "frozen" in str(excinfo.value).lower()

    # Act - Test with_* methods
    new_config = config.with_backend("anthropic")

    # Assert
    # Use model_dump() to access the values directly
    assert config.model_dump()["backend_type"] == "openai"  # Original unchanged
    assert (
        new_config.model_dump()["backend_type"] == "anthropic"
    )  # New config has updated value
    # Note: model is cleared when changing backend, so we don't check it


def test_reasoning_config_immutability():
    """Test that ReasoningConfig is immutable and with_* methods work."""
    # Arrange
    config = ReasoningConfig(temperature=0.7)

    # Act & Assert - Pydantic raises ValidationError for frozen models
    with pytest.raises(Exception) as excinfo:
        config.temperature = 0.8  # type: ignore

    # Check that it's a frozen instance error
    assert "frozen" in str(excinfo.value).lower()

    # Act - Test with_* methods
    new_config = config.with_temperature(0.8)

    # Assert
    # Use model_dump() to access the values directly
    assert config.model_dump()["temperature"] == 0.7  # Original unchanged
    assert new_config.model_dump()["temperature"] == 0.8  # New config has updated value


def test_loop_detection_config_immutability():
    """Test that LoopDetectionConfig is immutable and with_* methods work."""
    # Arrange
    config = LoopDetectionConfig(loop_detection_enabled=True)

    # Act & Assert - Pydantic raises ValidationError for frozen models
    with pytest.raises(Exception) as excinfo:
        config.loop_detection_enabled = False  # type: ignore

    # Check that it's a frozen instance error
    assert "frozen" in str(excinfo.value).lower()

    # Act - Test with_* methods
    new_config = config.with_loop_detection_enabled(False)

    # Assert
    # Use model_dump() to access the values directly
    assert config.model_dump()["loop_detection_enabled"] is True  # Original unchanged
    assert (
        new_config.model_dump()["loop_detection_enabled"] is False
    )  # New config has updated value


def test_session_state_immutability():
    """Test that SessionState is immutable but its components can be updated."""
    # Arrange
    state = SessionState(
        backend_config=BackendConfig(backend_type="openai", model="gpt-4"),
        reasoning_config=ReasoningConfig(temperature=0.7),
        loop_config=LoopDetectionConfig(loop_detection_enabled=True),
    )

    # Act & Assert - Pydantic raises ValidationError for frozen models
    with pytest.raises(Exception) as excinfo:
        state.backend_config = BackendConfig()  # type: ignore

    # Check that it's a frozen instance error
    assert "frozen" in str(excinfo.value).lower()


def test_session_interaction_immutability():
    """Test that SessionInteraction is immutable."""
    # Arrange
    interaction = SessionInteraction(
        prompt="Hello",
        handler="backend",
        response="Hi there!",
        backend="openai",
        model="gpt-4",
    )

    # Act & Assert - Pydantic raises ValidationError for frozen models
    with pytest.raises(Exception) as excinfo:
        interaction.response = "New response"  # type: ignore

    # Check that it's a frozen instance error
    assert "frozen" in str(excinfo.value).lower()


def test_session_mutability():
    """Test that Session is mutable."""
    from src.core.domain.session import Session, SessionInteraction

    # Arrange
    session = Session(session_id="test-session")
    interaction = SessionInteraction(
        prompt="Hello", handler="proxy", response="Hi there!"
    )

    # Act - Test that session is mutable
    session.add_interaction(interaction)
    new_state = SessionState()
    session.update_state(SessionStateAdapter(new_state))

    # Assert
    assert len(session.history) == 1
    assert session.state._state == new_state
