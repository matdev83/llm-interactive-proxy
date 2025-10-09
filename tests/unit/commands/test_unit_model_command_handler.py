import asyncio

from src.core.commands.command import Command
from src.core.commands.handlers.model_command_handler import ModelCommandHandler
from src.core.domain.session import Session


def test_model_command_handler_sets_model() -> None:
    handler = ModelCommandHandler()
    session = Session(session_id="test-session")
    command = Command(name="model", args={"name": "gpt-4-turbo"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert result.message == "Model changed to gpt-4-turbo"
    assert result.new_state is not None
    assert result.new_state.backend_config.model == "gpt-4-turbo"


def test_model_command_handler_sets_backend_and_model() -> None:
    handler = ModelCommandHandler()
    session = Session(session_id="test-session")
    command = Command(name="model", args={"name": "openrouter:claude-3-opus"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert (
        result.message
        == "Backend changed to openrouter; Model changed to claude-3-opus"
    )
    assert result.new_state is not None
    assert result.new_state.backend_config.backend_type == "openrouter"
    assert result.new_state.backend_config.model == "claude-3-opus"


def test_model_command_handler_unsets_model() -> None:
    handler = ModelCommandHandler()
    session = Session(session_id="test-session")
    command = Command(name="model", args={"name": ""})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert result.message == "Model unset"
    assert result.new_state is not None
    assert result.new_state.backend_config.model is None


def test_model_command_handler_preserves_message_with_service() -> None:
    handler = ModelCommandHandler(command_service=object())
    session = Session(session_id="test-session")
    command = Command(name="model", args={"name": "gpt-4-turbo"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert result.message == "Model changed to gpt-4-turbo"
    assert result.new_state is not None
    assert result.new_state.backend_config.model == "gpt-4-turbo"


def test_model_command_handler_updates_session_state_with_service() -> None:
    handler = ModelCommandHandler(command_service=object())
    session = Session(session_id="test-session")
    command = Command(name="model", args={"name": "gpt-4-turbo"})

    result = asyncio.run(handler.handle(command, session))

    assert result.success is True
    assert session.state.backend_config.model == "gpt-4-turbo"
    assert result.new_state is session.state
