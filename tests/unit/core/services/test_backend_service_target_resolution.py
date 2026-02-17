"""
Characterization tests for BackendService target resolution behavior.

This module locks in the current behavior of backend/model resolution
to prevent regressions during refactoring.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.common.exceptions import ConfigurationError, RoutingError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.request_context import RequestContext
from src.core.domain.session import Session, SessionState
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.session_service_interface import ISessionService


@pytest.fixture
def mock_dependencies():
    """Create common mock dependencies for BackendService."""
    factory = Mock()
    rate_limiter = Mock()
    rate_limiter.check_limit = AsyncMock(return_value=Mock(is_limited=False))
    rate_limiter.record_usage = AsyncMock()

    config = Mock(spec=AppConfig)
    config.backends = Mock()
    config.backends.default_backend = "openai"
    config.backends.static_route = None
    config.backends.get = Mock(return_value=None)

    session_service = Mock(spec=ISessionService)
    session_service.get_session = AsyncMock(return_value=None)

    app_state = Mock(spec=IApplicationState)
    routing_service = Mock()
    routing_service.resolve_model_only_backend = Mock(
        side_effect=lambda model, excluded_backends=None: "openai"
    )
    routing_service.resolve_backend_instance = Mock(
        side_effect=lambda backend, model, excluded_backends=None: backend or "openai"
    )

    from tests.utils.failover_stub import StubFailoverCoordinator

    return {
        "factory": factory,
        "rate_limiter": rate_limiter,
        "config": config,
        "session_service": session_service,
        "app_state": app_state,
        "routing_service": routing_service,
        "failover_coordinator": StubFailoverCoordinator(),
    }


@pytest.fixture
def backend_service(mock_dependencies):
    """Create a BackendService instance for testing.

    This fixture creates BackendService with REAL service implementations
    for the components being tested (model resolver, alias resolver, etc.)
    and mocks for external dependencies.
    """
    from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
    from src.core.services.backend_model_resolver import BackendModelResolver
    from src.core.services.model_alias_resolver import ModelAliasResolver
    from src.core.services.planning_phase_manager import PlanningPhaseManager

    from tests.unit.fixtures.backend_service_builder import (
        create_backend_service_with_mocks,
    )

    # Use REAL services for components being tested
    model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
    planning_phase_manager = PlanningPhaseManager(
        session_service=mock_dependencies["session_service"]
    )
    backend_lifecycle_manager = BackendLifecycleManager(
        factory=mock_dependencies["factory"],
        config=mock_dependencies["config"],
        backend_config_provider=Mock(),
        per_session_limit=32,
    )

    # Create real BackendModelResolver with real dependencies
    backend_model_resolver = BackendModelResolver(
        session_service=mock_dependencies["session_service"],
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=mock_dependencies["config"],
        routing_service=mock_dependencies["routing_service"],
    )

    mock_dependencies["model_alias_resolver"] = model_alias_resolver
    mock_dependencies["planning_phase_manager"] = planning_phase_manager
    mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
    mock_dependencies["backend_model_resolver"] = backend_model_resolver

    return create_backend_service_with_mocks(**mock_dependencies)


class TestTargetResolutionOrdering:
    """Test the ordering of model alias resolution and backend parsing."""

    @pytest.mark.asyncio
    async def test_model_aliases_resolved_before_backend_parsing(self, backend_service):
        """Test that model aliases are resolved BEFORE backend prefix parsing."""
        # Create a request with an aliased model
        request = ChatRequest(
            model="my-alias",
            messages=[ChatMessage(role="user", content="test")],
        )

        # Mock the model alias resolver to return a model with backend prefix
        with patch.object(
            backend_service._model_alias_resolver,
            "resolve",
            return_value="anthropic:claude-3-5-sonnet",
        ):
            backend, model, uri_params = (
                await backend_service._resolve_backend_and_model(request)
            )

            # Should resolve to anthropic backend from the aliased result
            assert backend == "anthropic"
            assert model == "claude-3-5-sonnet"


class TestBackendPrefixParsing:
    """Test backend prefix parsing from model strings."""

    @pytest.mark.asyncio
    async def test_parse_backend_from_model_with_colon(self, backend_service):
        """Test parsing 'backend:model' format."""
        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        assert backend == "anthropic"
        assert model == "claude-3-5-sonnet"

    @pytest.mark.asyncio
    async def test_parse_model_without_backend_prefix(self, backend_service):
        """Test model without backend prefix uses default backend."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        # Should use default backend from config
        assert backend == "openai"
        assert model == "gpt-4"


class TestURIParameterParsing:
    """Test URI parameter extraction from model strings."""

    @pytest.mark.asyncio
    async def test_parse_uri_params_from_model(self, backend_service):
        """Test parsing URI parameters from model string."""
        request = ChatRequest(
            model="gpt-4?temperature=0.5&max_tokens=100",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        assert model == "gpt-4"
        assert "temperature" in uri_params
        assert "max_tokens" in uri_params

    @pytest.mark.asyncio
    async def test_uri_params_with_backend_prefix(self, backend_service):
        """Test URI parameters work with backend prefix."""
        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet?temperature=0.7",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        assert backend == "anthropic"
        assert model == "claude-3-5-sonnet"
        assert "temperature" in uri_params

    @pytest.mark.asyncio
    async def test_uri_params_with_backend_instance_prefix(self, backend_service):
        """Test URI parameters work with backend-instance prefix."""
        request = ChatRequest(
            model="openai.1:gpt-4o?temperature=0.6&top_p=0.9",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        assert backend == "openai.1"
        assert model == "gpt-4o"
        assert uri_params == {"temperature": "0.6", "top_p": "0.9"}


class TestStaticRouteOverride:
    """Test static route override behavior."""

    @pytest.mark.asyncio
    async def test_static_route_overrides_resolved_backend(
        self, mock_dependencies, backend_service
    ):
        """Test that static_route overrides the resolved backend and model."""
        # This test needs a fresh service instance with modified config
        mock_dependencies["config"].backends.static_route = "gemini:gemini-2.0-flash"

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        # Recreate real services with updated config
        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=mock_dependencies["routing_service"],
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await service._resolve_backend_and_model(request)

        # Static route should override everything
        assert backend == "gemini"
        assert model == "gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_static_route_query_params_are_parsed_and_merged(
        self, mock_dependencies
    ):
        """Static-route query params should be normalized into uri_params."""
        mock_dependencies["config"].backends.static_route = (
            "gemini:gemini-2.0-flash?temperature=0.2"
        )

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=mock_dependencies["routing_service"],
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet?temperature=0.7&top_p=0.8",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await service._resolve_backend_and_model(request)

        assert backend == "gemini"
        assert model == "gemini-2.0-flash"
        assert uri_params == {"temperature": "0.2", "top_p": "0.8"}

    @pytest.mark.asyncio
    async def test_static_route_model_only_is_rejected(self, mock_dependencies):
        """Model-only static_route must be rejected."""
        mock_dependencies["config"].backends.static_route = "gpt-4o"

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        # Recreate real services with updated config
        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=mock_dependencies["routing_service"],
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        with pytest.raises(ConfigurationError) as exc_info:
            await service._resolve_backend_and_model(request)
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("error_code") == "invalid_static_route_format"

    @pytest.mark.asyncio
    async def test_static_route_model_like_vendor_suffix_with_colon_is_rejected(
        self, mock_dependencies
    ):
        """Model-like `vendor/model:...` static_route without backend selector is rejected."""
        mock_dependencies["config"].backends.static_route = (
            "openrouter/anthropic/claude-3-haiku:free"
        )

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        # Recreate real services with updated config
        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=mock_dependencies["routing_service"],
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        with pytest.raises(ConfigurationError) as exc_info:
            await service._resolve_backend_and_model(request)
        assert exc_info.value.details is not None
        assert exc_info.value.details.get("error_code") == "invalid_static_route_format"

    @pytest.mark.asyncio
    async def test_static_route_can_be_skipped_with_context_flag(self, mock_dependencies):
        """Per-request context flag should bypass static_route overrides."""
        mock_dependencies["config"].backends.static_route = "gemini:gemini-2.0-flash"

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=mock_dependencies["routing_service"],
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="openrouter:nvidia/nemotron-3-nano-30b-a3b:free",
            messages=[ChatMessage(role="user", content="generate title")],
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-skip-static-route",
            session_id="aux-session",
        )
        context.extensions["skip_static_route"] = True

        target = await service._backend_model_resolver.resolve_target(
            request=request, context=context
        )

        assert target.backend == "openrouter"
        assert target.model == "nvidia/nemotron-3-nano-30b-a3b:free"


class TestSessionBackendResolution:
    """Test backend resolution from session state."""

    @pytest.mark.asyncio
    async def test_backend_from_session_state(self, backend_service):
        """Test that backend is resolved from session state."""
        # Create a proper session with backend config
        backend_config = BackendConfiguration(backend_type="anthropic")
        session_state = SessionState(backend_config=backend_config)
        session = Session(session_id="test-session", state=session_state)

        backend_service._session_service.get_session = AsyncMock(return_value=session)

        # Mock planning phase manager to avoid state modifications
        backend_service._planning_phase_manager.apply_if_needed = AsyncMock()

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"session_id": "test-session"},
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        # Backend should come from session
        assert backend == "anthropic"
        assert model == "gpt-4"

    @pytest.mark.asyncio
    async def test_backend_from_extra_body(self, backend_service):
        """Test that backend can be specified in extra_body."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"backend_type": "gemini"},
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        assert backend == "gemini"
        assert model == "gpt-4"


class TestBackendDiscoveryAndRouting:
    """Test backend discovery and routing service integration."""

    @pytest.mark.asyncio
    async def test_routing_service_discovery(self, mock_dependencies):
        """Test backend discovery through routing service."""
        routing_service = Mock()
        routing_service.resolve_model_only_backend = Mock(return_value="gemini-oauth")
        routing_service.resolve_backend_instance = Mock(return_value="gemini-oauth")

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        mock_dependencies["routing_service"] = routing_service

        # Recreate real services with routing service
        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=routing_service,
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver

        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="gemini-2.0-flash",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await service._resolve_backend_and_model(request)

        # Should discover gemini-oauth backend
        assert backend == "gemini-oauth"
        routing_service.resolve_model_only_backend.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_only_unknown_raises_routing_error_before_dispatch(
        self, mock_dependencies
    ):
        """Unknown model-only identifiers raise RoutingError per Req 3.3."""
        routing_service = Mock()
        routing_service.resolve_model_only_backend = Mock(
            side_effect=RoutingError(
                message="Unknown model",
                details={"code": "unknown_model", "model": "unknown-model"},
            )
        )
        routing_service.resolve_backend_instance = Mock(return_value=None)

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=routing_service,
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver
        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="unknown-model",
            messages=[ChatMessage(role="user", content="test")],
        )

        with pytest.raises(RoutingError) as exc_info:
            await service._resolve_backend_and_model(request)

        assert exc_info.value.details is not None
        assert exc_info.value.details.get("code") == "unknown_model"
        routing_service.resolve_model_only_backend.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_only_resolution_requires_routing_service_contract(
        self, mock_dependencies
    ) -> None:
        """Model-only resolution must fail-fast when routing service contract is incomplete."""

        class _RoutingServiceWithoutModelOnly:
            def __init__(self) -> None:
                self.resolve_backend_instance = Mock(return_value=None)

        routing_service = _RoutingServiceWithoutModelOnly()

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=routing_service,  # type: ignore[arg-type]
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver
        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="unknown-model",
            messages=[ChatMessage(role="user", content="test")],
        )

        with pytest.raises(AttributeError):
            await service._resolve_backend_and_model(request)

    @pytest.mark.asyncio
    async def test_explicit_backend_without_available_instance_raises_routing_error(
        self, mock_dependencies
    ):
        routing_service = Mock()
        routing_service.resolve_backend_instance = Mock(return_value=None)
        routing_service.resolve_model_only_backend = Mock()

        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
        from src.core.services.backend_model_resolver import BackendModelResolver
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )

        model_alias_resolver = ModelAliasResolver(config=mock_dependencies["config"])
        planning_phase_manager = PlanningPhaseManager(
            session_service=mock_dependencies["session_service"]
        )
        backend_lifecycle_manager = BackendLifecycleManager(
            factory=mock_dependencies["factory"],
            config=mock_dependencies["config"],
            backend_config_provider=Mock(),
            per_session_limit=32,
        )
        backend_model_resolver = BackendModelResolver(
            session_service=mock_dependencies["session_service"],
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=mock_dependencies["config"],
            routing_service=routing_service,
        )
        mock_dependencies["model_alias_resolver"] = model_alias_resolver
        mock_dependencies["planning_phase_manager"] = planning_phase_manager
        mock_dependencies["backend_lifecycle_manager"] = backend_lifecycle_manager
        mock_dependencies["backend_model_resolver"] = backend_model_resolver
        service = create_backend_service_with_mocks(
            use_real_completion_flow=True, **mock_dependencies
        )

        request = ChatRequest(
            model="openai:gpt-4o",
            messages=[ChatMessage(role="user", content="test")],
        )

        with pytest.raises(RoutingError) as exc_info:
            await service._resolve_backend_and_model(request)

        assert exc_info.value.details is not None
        assert exc_info.value.details.get("code") == "temporarily_unavailable"


class TestRequestSynchronization:
    """Test request synchronization with resolved target."""

    def test_synchronize_updates_model_when_different(self, backend_service):
        """Test that synchronize updates model when it differs from effective model."""
        request = ChatRequest(
            model="gpt-3.5-turbo",
            messages=[ChatMessage(role="user", content="test")],
        )

        synced = backend_service._synchronize_request_with_target(
            request, "openai", "gpt-4"
        )

        assert synced.model == "gpt-4"

    def test_synchronize_preserves_backend_prefix_when_matches(self, backend_service):
        """Test that original model format is preserved when backend matches."""
        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        synced = backend_service._synchronize_request_with_target(
            request, "anthropic", "claude-3-5-sonnet"
        )

        # Should preserve original format
        assert synced.model == "anthropic:claude-3-5-sonnet"

    def test_synchronize_updates_model_when_backend_overridden(self, backend_service):
        """Test that model is updated when backend was overridden."""
        request = ChatRequest(
            model="anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="test")],
        )

        synced = backend_service._synchronize_request_with_target(
            request, "gemini", "gemini-2.0-flash"
        )

        # Backend was overridden, so update the model
        assert synced.model == "gemini-2.0-flash"

    def test_synchronize_updates_extra_body(self, backend_service):
        """Test that extra_body is updated with resolved backend and model."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            extra_body={"some_field": "value"},
        )

        synced = backend_service._synchronize_request_with_target(
            request, "anthropic", "claude-3-5-sonnet"
        )

        assert synced.extra_body["model"] == "claude-3-5-sonnet"
        assert synced.extra_body["backend_type"] == "anthropic"
        assert synced.extra_body["some_field"] == "value"  # Preserved

    @pytest.mark.asyncio
    async def test_synchronize_preserves_uri_params_for_follow_up_resolution(
        self, backend_service
    ) -> None:
        """Resolved URI params should remain available after request synchronization."""
        resolver = backend_service._backend_model_resolver
        request = ChatRequest(
            model="gpt-4?temperature=0.4&top_p=0.8",
            messages=[ChatMessage(role="user", content="test")],
        )

        initial_target = await resolver.resolve_target(request=request, context=None)
        synchronized = resolver.synchronize_request_with_target(request, initial_target)

        assert synchronized.extra_body is not None
        assert synchronized.extra_body.get("_resolved_uri_params") == {
            "temperature": "0.4",
            "top_p": "0.8",
        }

        failover_request = synchronized.model_copy(
            update={
                "extra_body": {
                    **(synchronized.extra_body or {}),
                    "backend_type": "anthropic",
                }
            }
        )

        failover_target = await resolver.resolve_target(
            request=failover_request,
            context=None,
        )

        assert failover_target.backend == "anthropic"
        assert failover_target.model == "gpt-4"
        assert failover_target.uri_params == {"temperature": "0.4", "top_p": "0.8"}


class TestEdgeCases:
    """Test edge cases in target resolution."""

    @pytest.mark.asyncio
    async def test_empty_model_string(self, backend_service):
        """Test behavior with empty model string."""
        request = ChatRequest(
            model="",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        # Should use default backend and empty model
        assert backend == "openai"
        assert model == ""

    @pytest.mark.asyncio
    async def test_multiple_colons_in_model(self, backend_service):
        """Test model string with multiple colons."""
        request = ChatRequest(
            model="backend:model:version",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend, model, uri_params = await backend_service._resolve_backend_and_model(
            request
        )

        # Should parse first colon as backend separator
        assert backend == "backend"
        assert model == "model:version"
