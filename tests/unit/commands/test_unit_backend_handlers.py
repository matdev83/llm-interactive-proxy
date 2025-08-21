from unittest.mock import Mock, patch

import pytest
from src.core.constants import (
    BACKEND_MUST_BE_STRING_MESSAGE,
    BACKEND_NOT_FUNCTIONAL_MESSAGE,
    BACKEND_NOT_SUPPORTED_MESSAGE,
    BACKEND_SET_MESSAGE,
    BACKEND_AND_MODEL_SET_MESSAGE,
    MODEL_MUST_BE_STRING_MESSAGE,
    MODEL_SET_MESSAGE,
    MODEL_UNSET_MESSAGE,
    MODEL_BACKEND_NOT_SUPPORTED_MESSAGE,
    OPENAI_URL_MUST_BE_STRING_MESSAGE,
    OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE,
    OPENAI_URL_SET_MESSAGE,
)
from src.core.commands.handlers.backend_handlers import (
    BackendHandler,
    ModelHandler,
    OpenAIUrlHandler,
)
from src.core.domain.session import BackendConfiguration, Session, SessionState


@pytest.fixture
def backend_handler() -> BackendHandler:
    return BackendHandler()


@pytest.fixture
def model_handler() -> ModelHandler:
    return ModelHandler()


@pytest.fixture
def openai_url_handler() -> OpenAIUrlHandler:
    return OpenAIUrlHandler()


@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(
        backend_config=BackendConfiguration(
            backend_type="test_backend", model="test_model"
        )
    )
    return mock


# BackendHandler tests
@pytest.mark.asyncio
async def test_backend_handler_set_success(backend_handler: BackendHandler, mock_session: Mock):
    # Arrange
    backend_value = "new_backend"

    # Act
    result = backend_handler.handle(backend_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == BACKEND_SET_MESSAGE.format(backend=backend_value)
    assert result.new_state is not None
    assert result.new_state.backend_config.backend_type == backend_value


@pytest.mark.asyncio
async def test_backend_handler_invalid_type(backend_handler: BackendHandler, mock_session: Mock):
    # Arrange
    backend_value = 123  # Not a string

    # Act
    result = backend_handler.handle(backend_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == BACKEND_MUST_BE_STRING_MESSAGE


@pytest.mark.asyncio
async def test_backend_handler_not_functional(backend_handler: BackendHandler, mock_session: Mock):
    # Arrange
    backend_handler.functional_backends = {"supported_backend"}
    backend_value = "unsupported_backend"

    # Act
    result = backend_handler.handle(backend_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == BACKEND_NOT_FUNCTIONAL_MESSAGE.format(backend=backend_value)
    assert result.new_state is not None
    assert result.new_state.backend_config.backend_type is None


# ModelHandler tests
@pytest.mark.asyncio
async def test_model_handler_set_success(model_handler: ModelHandler, mock_session: Mock):
    # Arrange
    model_value = "new_model"

    # Act
    result = model_handler.handle(model_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == MODEL_SET_MESSAGE.format(model=model_value)
    assert result.new_state is not None
    assert result.new_state.backend_config.model == model_value


@pytest.mark.asyncio
async def test_model_handler_unset(model_handler: ModelHandler, mock_session: Mock):
    # Act
    result = model_handler.handle(None, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == MODEL_UNSET_MESSAGE
    assert result.new_state is not None
    assert result.new_state.backend_config.model is None


@pytest.mark.asyncio
async def test_model_handler_invalid_type(model_handler: ModelHandler, mock_session: Mock):
    # Arrange
    model_value = 123  # Not a string

    # Act
    result = model_handler.handle(model_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == MODEL_MUST_BE_STRING_MESSAGE


@pytest.mark.asyncio
async def test_model_handler_with_backend_prefix(model_handler: ModelHandler, mock_session: Mock):
    # Arrange
    model_value = "new_backend:new_model"

    with patch("src.core.services.backend_registry.backend_registry") as mock_registry:
        mock_registry.get_registered_backends.return_value = {"new_backend"}
        
        # Act
        result = model_handler.handle(model_value, mock_session.state, context=Mock())

        # Assert
        assert result.success is True
        assert result.message == BACKEND_AND_MODEL_SET_MESSAGE.format(backend="new_backend", model="new_model")
        assert result.new_state is not None
        assert result.new_state.backend_config.backend_type == "new_backend"
        assert result.new_state.backend_config.model == "new_model"


@pytest.mark.asyncio
async def test_model_handler_with_unsupported_backend_prefix(model_handler: ModelHandler, mock_session: Mock):
    # Arrange
    model_value = "unsupported_backend:new_model"

    with patch("src.core.services.backend_registry.backend_registry") as mock_registry:
        mock_registry.get_registered_backends.return_value = {"supported_backend"}
        
        # Act
        result = model_handler.handle(model_value, mock_session.state, context=Mock())

        # Assert
        assert result.success is False
        assert result.message == MODEL_BACKEND_NOT_SUPPORTED_MESSAGE.format(backend="unsupported_backend", model=model_value)


# OpenAIUrlHandler tests
@pytest.mark.asyncio
async def test_openai_url_handler_set_success(openai_url_handler: OpenAIUrlHandler, mock_session: Mock):
    # Arrange
    url_value = "https://api.example.com/v1"

    # Act
    result = openai_url_handler.handle(url_value, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == OPENAI_URL_SET_MESSAGE.format(url=url_value)
    assert result.new_state is not None
    assert result.new_state.backend_config.openai_url == url_value


@pytest.mark.asyncio
async def test_openai_url_handler_invalid_type(openai_url_handler: OpenAIUrlHandler, mock_session: Mock):
    # Arrange
    url_value = 123  # Not a string

    # Act
    result = openai_url_handler.handle(url_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == OPENAI_URL_MUST_BE_STRING_MESSAGE


@pytest.mark.asyncio
async def test_openai_url_handler_invalid_format(openai_url_handler: OpenAIUrlHandler, mock_session: Mock):
    # Arrange
    url_value = "ftp://api.example.com/v1"  # Not http or https

    # Act
    result = openai_url_handler.handle(url_value, mock_session.state)

    # Assert
    assert result.success is False
    assert result.message == OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE