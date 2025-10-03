from unittest.mock import Mock

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.reasoning_aliases import (
    SetModeCommandHandler,
    SetProviderCommandHandler,
)
from src.core.domain.configuration.reasoning_aliases_config import ReasoningMode
from src.core.domain.session import Session


class TestSetProviderCommandHandler:
    @pytest.fixture
    def handler(self):
        return SetProviderCommandHandler()

    @pytest.fixture
    def session(self):
        return Mock(spec=Session)

    @pytest.mark.asyncio
    async def test_handle_success(self, handler, session):
        command = Command(name="provider", args={"provider_name": "anthropic"})
        session.set_provider = Mock()

        result = await handler.handle(command, session)

        assert result.success is True
        assert result.message == "Provider set to anthropic."
        session.set_provider.assert_called_once_with("anthropic")

    @pytest.mark.asyncio
    async def test_handle_missing_args(self, handler, session):
        command = Command(name="provider", args={})

        result = await handler.handle(command, session)

        assert result.success is False
        assert result.message == "Provider name is required."


class TestSetModeCommandHandler:
    @pytest.fixture
    def handler(self):
        return SetModeCommandHandler()

    @pytest.fixture
    def session(self):
        return Mock(spec=Session)

    @pytest.fixture
    def secure_state_access(self):
        mock = Mock()
        mock.get_config = Mock(return_value=Mock())
        return mock

    @pytest.mark.asyncio
    async def test_handle_success(self, handler, session, secure_state_access):
        command = Command(name="mode", args={"mode_name": "test"})
        session.get_model = Mock(return_value="claude-3-opus-20240229")
        session.set_reasoning_mode = Mock()

        # Mock the secure state access
        handler._secure_state_access = secure_state_access

        # Mock the config
        mock_config = Mock()
        mock_config.reasoning_aliases = Mock()
        mock_config.reasoning_aliases.reasoning_alias_settings = [
            Mock(
                model="claude-3-opus-20240229", modes={"test": Mock(spec=ReasoningMode)}
            )
        ]
        secure_state_access.get_config.return_value = mock_config

        result = await handler.handle(command, session)

        assert result.success is True
        assert result.message == "Reasoning mode set to test."
        session.set_reasoning_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_missing_args(self, handler, session, secure_state_access):
        command = Command(name="mode", args={})
        handler._secure_state_access = secure_state_access

        result = await handler.handle(command, session)

        assert result.success is False
        assert result.message == "Mode name is required."

    @pytest.mark.asyncio
    async def test_handle_no_config(self, handler, session, secure_state_access):
        command = Command(name="mode", args={"mode_name": "test"})
        handler._secure_state_access = secure_state_access
        secure_state_access.get_config.return_value = None

        result = await handler.handle(command, session)

        assert result.success is False
        assert result.message == "Reasoning aliases are not configured."

    @pytest.mark.asyncio
    async def test_handle_no_model(self, handler, session, secure_state_access):
        command = Command(name="mode", args={"mode_name": "test"})
        session.get_model = Mock(return_value=None)
        handler._secure_state_access = secure_state_access

        # Mock the config
        mock_config = Mock()
        mock_config.reasoning_aliases = Mock()
        secure_state_access.get_config.return_value = mock_config

        result = await handler.handle(command, session)

        assert result.success is False
        assert result.message == "No reasoning settings found for model None."
