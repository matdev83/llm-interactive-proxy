"""
Pytest configuration file for unit tests.

This file contains shared fixtures and configuration for the unit tests.
"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.di.container import ServiceCollection
from src.core.domain.session import SessionStateAdapter
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_service_interface import ISessionService

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandService,
    MockLoopDetector,
    MockRateLimiter,
    MockResponseProcessor,
    MockSessionRepository,
    MockSessionService,
    MockSuccessCommand,
)


@pytest.fixture
def services() -> ServiceCollection:
    """Create a service collection with mock services."""
    services = ServiceCollection()

    # Register mock services
    services.add_singleton(
        IBackendService, implementation_factory=lambda _: MockBackendService()
    )  # type: ignore
    services.add_singleton(
        ISessionService, implementation_factory=lambda _: MockSessionService()
    )  # type: ignore
    services.add_singleton(
        ICommandService, implementation_factory=lambda _: MockCommandService()
    )  # type: ignore
    services.add_singleton(
        IRateLimiter, implementation_factory=lambda _: MockRateLimiter()
    )  # type: ignore
    services.add_singleton(
        ILoopDetector, implementation_factory=lambda _: MockLoopDetector()
    )  # type: ignore
    services.add_singleton(
        IResponseProcessor, implementation_factory=lambda _: MockResponseProcessor()
    )  # type: ignore
    services.add_singleton(
        ISessionRepository, implementation_factory=lambda _: MockSessionRepository()
    )  # type: ignore

    return services


@pytest.fixture
def service_provider(services: ServiceCollection) -> IServiceProvider:
    """Create a service provider from the service collection."""
    return services.build_provider()


@pytest.fixture
def mock_app_for_parser() -> FastAPI:
    class MockAppState:
            def __init__(self):
                self.functional_backends = {"openrouter", "gemini"}
                self.config_manager = None
                self.api_key_redaction_enabled = True # Make it a regular attribute
                self.default_api_key_redaction_enabled = True # Make it a regular attribute
                self.command_prefix = DEFAULT_COMMAND_PREFIX # Make it a regular attribute
        app.state = MockAppState()
        return app


@pytest.fixture
def proxy_state() -> SessionStateAdapter:
    from src.core.domain.session import SessionState

    session_state = SessionState()
    return SessionStateAdapter(session_state)


    # ... existing fixtures ...

@pytest.fixture(
    params=[True, False], ids=["preserve_unknown_True", "preserve_unknown_False"]
)
async def command_parser(
    request, mock_app_for_parser: FastAPI, proxy_state: SessionStateAdapter
) -> AsyncGenerator[CommandParser, None]:
    preserve_unknown_val = request.param
    parser_config = CommandParserConfig(
        proxy_state=proxy_state,
        app=mock_app_for_parser,
        preserve_unknown=preserve_unknown_val,
        functional_backends=mock_app_for_parser.state.functional_backends,
    )
    parser = CommandParser(parser_config, command_prefix=DEFAULT_COMMAND_PREFIX)
    parser.handlers.clear()

    # Create fresh mocks for each parametrization to avoid state leakage
    hello_cmd = MockSuccessCommand("hello", app=mock_app_for_parser)
    another_cmd = MockSuccessCommand("anothercmd", app=mock_app_for_parser)
    parser.register_command(hello_cmd)
    parser.register_command(another_cmd)

    # Mocks for SetCommand and UnsetCommand
    mock_state_reader = MagicMock(spec=ISecureStateAccess)
    mock_state_modifier = MagicMock(spec=ISecureStateModification)

    def mock_read_state_setting(key: str) -> Any:
        if key == "api_key_redaction_enabled":
            return mock_app_for_parser.state.api_key_redaction_enabled
        elif key == "command_prefix":
            return mock_app_for_parser.state.command_prefix
        # For other session state related settings, read from proxy_state
        # Note: proxy_state is a SessionStateAdapter, which wraps a SessionState object.
        # The attributes like backend_config, reasoning_config, project, interactive_just_enabled
        # are properties on SessionStateAdapter that delegate to the underlying SessionState.
        # So, direct attribute access on proxy_state is appropriate here.
        return getattr(proxy_state, key, None)

    def mock_update_state_setting(key: str, value: Any) -> None:
        if key == "api_key_redaction_enabled":
            mock_app_for_parser.state.api_key_redaction_enabled = value
        elif key == "command_prefix":
            mock_app_for_parser.state.command_prefix = value
        else:
            # For other session state related settings, update proxy_state
            setattr(proxy_state, key, value)

    mock_state_reader.read_state_setting.side_effect = mock_read_state_setting
    mock_state_modifier.update_state_setting.side_effect = mock_update_state_setting

    set_cmd = SetCommand(state_reader=mock_state_reader, state_modifier=mock_state_modifier)
    unset_cmd = UnsetCommand(state_reader=mock_state_reader, state_modifier=mock_state_modifier)

    parser.register_command(set_cmd)
    parser.register_command(unset_cmd)

    yield parser


@pytest.fixture
def mock_app(service_provider: IServiceProvider) -> object:
    """Create a mock FastAPI app with a service provider."""

    class MockApp:
        def __init__(self):
            self.state = self._get_mock_state()

        def _get_mock_state(self):
            class MockState:
                def __init__(self):
                    self.service_provider = service_provider
                    self.command_prefix = "!/"
                    self.api_key_redaction_enabled = True
                    self.default_api_key_redaction_enabled = True
                    self.functional_backends = ["openai", "openrouter", "gemini"]

            return MockState()

    return MockApp()
