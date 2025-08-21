"""
Pytest configuration file for unit tests.

This file contains shared fixtures and configuration for the unit tests.
"""

from collections.abc import AsyncGenerator
from typing import Any

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
from unittest.mock import MagicMock
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.commands.unset_command import UnsetCommand
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

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

# Define custom mock classes
class MockSecureStateAccess(ISecureStateAccess):
    def __init__(self, proxy_state: SessionStateAdapter, mock_app_state: Any):
        self._proxy_state = proxy_state
        self._mock_app_state = mock_app_state

    def read_state_setting(self, key: str) -> Any:
        if key == "api_key_redaction_enabled":
            return self._mock_app_state.api_key_redaction_enabled
        elif key == "command_prefix":
            return self._mock_app_state.command_prefix
        return getattr(self._proxy_state, key, None)

class MockSecureStateModification(ISecureStateModification):
    def __init__(self, proxy_state: SessionStateAdapter, mock_app_state: Any):
        self._proxy_state = proxy_state
        self._mock_app_state = mock_app_state

    def update_state_setting(self, key: str, value: Any) -> None:
        if key == "api_key_redaction_enabled":
            self._mock_app_state.api_key_redaction_enabled = value
        elif key == "command_prefix":
            self._mock_app_state.command_prefix = value
        else:
            setattr(self._proxy_state, key, value)


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
    app = FastAPI()
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

    # Use custom mock classes instead of MagicMock with side_effect
    from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.di.container import ServiceCollection
from src.core.domain.session import SessionStateAdapter, SessionState
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_service_interface import ISessionService
from unittest.mock import MagicMock
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.commands.unset_command import UnsetCommand
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.domain.configuration import BackendConfiguration, ReasoningConfiguration, LoopDetectionConfiguration

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

# Define custom mock classes
class MockSecureStateAccess(ISecureStateAccess):
    def __init__(self, proxy_state: SessionStateAdapter, mock_app_state: Any):
        self._proxy_state = proxy_state
        self._mock_app_state = mock_app_state

    def get_command_prefix(self) -> str | None:
        return self._mock_app_state.command_prefix

    def get_api_key_redaction_enabled(self) -> bool:
        return self._mock_app_state.api_key_redaction_enabled

    def get_disable_interactive_commands(self) -> bool:
        return not self._proxy_state.interactive_just_enabled

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        return self._proxy_state.backend_config.failover_routes


class MockSecureStateModification(ISecureStateModification):
    def __init__(self, proxy_state: SessionStateAdapter, mock_app_state: Any):
        self._proxy_state = proxy_state
        self._mock_app_state = mock_app_state

    def update_command_prefix(self, prefix: str) -> None:
        self._mock_app_state.command_prefix = prefix

    def update_api_key_redaction(self, enabled: bool) -> None:
        self._mock_app_state.api_key_redaction_enabled = enabled

    def update_interactive_commands(self, disabled: bool) -> None:
        new_session_state = self._proxy_state._state.with_interactive_just_enabled(not disabled)
        self._proxy_state._state = new_session_state

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        new_backend_config = self._proxy_state.backend_config.model_copy(update={"failover_routes": routes})
        new_session_state = self._proxy_state._state.with_backend_config(new_backend_config)
        self._proxy_state._state = new_session_state


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
    app = FastAPI()
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

    # Use custom mock classes instead of MagicMock with side_effect
    state_reader_instance = MockSecureStateAccess(proxy_state, mock_app_for_parser.state)
    state_modifier_instance = MockSecureStateModification(proxy_state, mock_app_for_parser.state)

    set_cmd = SetCommand(state_reader=state_reader_instance, state_modifier=state_modifier_instance)
    unset_cmd = UnsetCommand(state_reader=state_reader_instance, state_modifier=state_modifier_instance)

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
