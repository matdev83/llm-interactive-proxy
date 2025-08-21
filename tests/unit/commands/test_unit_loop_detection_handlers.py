from unittest.mock import Mock

import pytest
from src.core.constants import (
    LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE,
    LOOP_DETECTION_DISABLED_MESSAGE,
    LOOP_DETECTION_ENABLED_MESSAGE,
    LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE,
    TOOL_LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE,
    TOOL_LOOP_DETECTION_DISABLED_MESSAGE,
    TOOL_LOOP_DETECTION_ENABLED_MESSAGE,
    TOOL_LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_AT_LEAST_TWO_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_REQUIRED_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_SET_MESSAGE,
    TOOL_LOOP_MODE_INVALID_MESSAGE,
    TOOL_LOOP_MODE_REQUIRED_MESSAGE,
    TOOL_LOOP_MODE_SET_MESSAGE,
    TOOL_LOOP_TTL_AT_LEAST_ONE_MESSAGE,
    TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE,
    TOOL_LOOP_TTL_REQUIRED_MESSAGE,
    TOOL_LOOP_TTL_SET_MESSAGE,
)
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
    ToolLoopDetectionHandler,
    ToolLoopMaxRepeatsHandler,
    ToolLoopModeHandler,
    ToolLoopTTLHandler,
)
from src.core.domain.session import LoopDetectionConfiguration, Session, SessionState
from src.tool_call_loop.config import ToolLoopMode


@pytest.fixture
def loop_detection_handler() -> LoopDetectionHandler:
    return LoopDetectionHandler()


@pytest.fixture
def tool_loop_detection_handler() -> ToolLoopDetectionHandler:
    return ToolLoopDetectionHandler()


@pytest.fixture
def tool_loop_max_repeats_handler() -> ToolLoopMaxRepeatsHandler:
    return ToolLoopMaxRepeatsHandler()


@pytest.fixture
def tool_loop_ttl_handler() -> ToolLoopTTLHandler:
    return ToolLoopTTLHandler()


@pytest.fixture
def tool_loop_mode_handler() -> ToolLoopModeHandler:
    return ToolLoopModeHandler()


@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(
        loop_config=LoopDetectionConfiguration(loop_detection_enabled=False)
    )
    return mock


# LoopDetectionHandler tests
def test_loop_detection_handler_enable(loop_detection_handler: LoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = "true"

    # Act
    result = loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == LOOP_DETECTION_ENABLED_MESSAGE
    assert result.new_state is not None
    assert result.new_state.loop_config.loop_detection_enabled is True


def test_loop_detection_handler_disable(loop_detection_handler: LoopDetectionHandler, mock_session: Mock):
    # Arrange
    mock_session.state = SessionState(
        loop_config=LoopDetectionConfiguration(loop_detection_enabled=True)
    )
    param_value = "false"

    # Act
    result = loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == LOOP_DETECTION_DISABLED_MESSAGE
    assert result.new_state is not None
    assert result.new_state.loop_config.loop_detection_enabled is False


def test_loop_detection_handler_no_value(loop_detection_handler: LoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = None

    # Act
    result = loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE


def test_loop_detection_handler_invalid_value(loop_detection_handler: LoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = "invalid"

    # Act
    result = loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE.format(value=param_value)


# ToolLoopDetectionHandler tests
def test_tool_loop_detection_handler_enable(tool_loop_detection_handler: ToolLoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = "true"

    # Act
    result = tool_loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_DETECTION_ENABLED_MESSAGE
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_detection_enabled is True


def test_tool_loop_detection_handler_disable(tool_loop_detection_handler: ToolLoopDetectionHandler, mock_session: Mock):
    # Arrange
    mock_session.state = SessionState(
        loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=True)
    )
    param_value = "false"

    # Act
    result = tool_loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_DETECTION_DISABLED_MESSAGE
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_detection_enabled is False


def test_tool_loop_detection_handler_no_value(tool_loop_detection_handler: ToolLoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = None

    # Act
    result = tool_loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE


def test_tool_loop_detection_handler_invalid_value(tool_loop_detection_handler: ToolLoopDetectionHandler, mock_session: Mock):
    # Arrange
    param_value = "invalid"

    # Act
    result = tool_loop_detection_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE.format(value=param_value)


# ToolLoopMaxRepeatsHandler tests
def test_tool_loop_max_repeats_handler_success(tool_loop_max_repeats_handler: ToolLoopMaxRepeatsHandler, mock_session: Mock):
    # Arrange
    param_value = "5"

    # Act
    result = tool_loop_max_repeats_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_MAX_REPEATS_SET_MESSAGE.format(max_repeats=5)
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_max_repeats == 5


def test_tool_loop_max_repeats_handler_no_value(tool_loop_max_repeats_handler: ToolLoopMaxRepeatsHandler, mock_session: Mock):
    # Arrange
    param_value = None

    # Act
    result = tool_loop_max_repeats_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_MAX_REPEATS_REQUIRED_MESSAGE


def test_tool_loop_max_repeats_handler_invalid_value(tool_loop_max_repeats_handler: ToolLoopMaxRepeatsHandler, mock_session: Mock):
    # Arrange
    param_value = "invalid"

    # Act
    result = tool_loop_max_repeats_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE.format(value=param_value)


def test_tool_loop_max_repeats_handler_too_low(tool_loop_max_repeats_handler: ToolLoopMaxRepeatsHandler, mock_session: Mock):
    # Arrange
    param_value = "1"

    # Act
    result = tool_loop_max_repeats_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_MAX_REPEATS_AT_LEAST_TWO_MESSAGE


# ToolLoopTTLHandler tests
def test_tool_loop_ttl_handler_success(tool_loop_ttl_handler: ToolLoopTTLHandler, mock_session: Mock):
    # Arrange
    param_value = "60"

    # Act
    result = tool_loop_ttl_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_TTL_SET_MESSAGE.format(ttl=60)
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_ttl_seconds == 60


def test_tool_loop_ttl_handler_no_value(tool_loop_ttl_handler: ToolLoopTTLHandler, mock_session: Mock):
    # Arrange
    param_value = None

    # Act
    result = tool_loop_ttl_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_TTL_REQUIRED_MESSAGE


def test_tool_loop_ttl_handler_invalid_value(tool_loop_ttl_handler: ToolLoopTTLHandler, mock_session: Mock):
    # Arrange
    param_value = "invalid"

    # Act
    result = tool_loop_ttl_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE.format(value=param_value)


def test_tool_loop_ttl_handler_too_low(tool_loop_ttl_handler: ToolLoopTTLHandler, mock_session: Mock):
    # Arrange
    param_value = "0"

    # Act
    result = tool_loop_ttl_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_TTL_AT_LEAST_ONE_MESSAGE


# ToolLoopModeHandler tests
def test_tool_loop_mode_handler_success_break(tool_loop_mode_handler: ToolLoopModeHandler, mock_session: Mock):
    # Arrange
    param_value = "break"

    # Act
    result = tool_loop_mode_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_MODE_SET_MESSAGE.format(mode="break")
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_mode == ToolLoopMode.BREAK


def test_tool_loop_mode_handler_success_chance_then_break(tool_loop_mode_handler: ToolLoopModeHandler, mock_session: Mock):
    # Arrange
    param_value = "chance_then_break"

    # Act
    result = tool_loop_mode_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == TOOL_LOOP_MODE_SET_MESSAGE.format(mode="chance_then_break")
    assert result.new_state is not None
    assert result.new_state.loop_config.tool_loop_mode == ToolLoopMode.CHANCE_THEN_BREAK


def test_tool_loop_mode_handler_no_value(tool_loop_mode_handler: ToolLoopModeHandler, mock_session: Mock):
    # Arrange
    param_value = None

    # Act
    result = tool_loop_mode_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_MODE_REQUIRED_MESSAGE


def test_tool_loop_mode_handler_invalid_value(tool_loop_mode_handler: ToolLoopModeHandler, mock_session: Mock):
    # Arrange
    param_value = "invalid"

    # Act
    result = tool_loop_mode_handler.handle(param_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == TOOL_LOOP_MODE_INVALID_MESSAGE.format(value=param_value)