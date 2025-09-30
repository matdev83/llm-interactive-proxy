"""Unit tests for static_route functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig, BackendSettings
from src.core.domain.chat import ChatRequest
from src.core.services.backend_service import BackendService


class TestStaticRoute:
    """Test suite for static_route override functionality."""

    @pytest.fixture
    def mock_config_without_static_route(self):
        """Create a mock config without static_route set."""
        config = MagicMock(spec=AppConfig)
        config.backends = MagicMock(spec=BackendSettings)
        config.backends.default_backend = "openai"
        config.backends.static_route = None
        return config

    @pytest.fixture
    def mock_config_with_static_route(self):
        """Create a mock config with static_route set."""
        config = MagicMock(spec=AppConfig)
        config.backends = MagicMock(spec=BackendSettings)
        config.backends.default_backend = "openai"
        config.backends.static_route = "gemini-cli-oauth-personal:gemini-2.5-pro"
        return config

    @pytest.fixture
    def mock_session_service(self):
        """Create a mock session service."""
        service = AsyncMock()
        service.get_session = AsyncMock(return_value=None)
        return service

    @pytest.fixture
    def mock_backend_factory(self):
        """Create a mock backend factory."""
        factory = MagicMock()
        factory.get_backend = MagicMock()
        return factory

    @pytest.fixture
    def mock_wire_capture(self):
        """Create a mock wire capture service."""
        capture = AsyncMock()
        capture.enabled = MagicMock(return_value=False)
        return capture

    @pytest.fixture
    def mock_rate_limiter(self):
        """Create a mock rate limiter."""
        limiter = AsyncMock()
        return limiter

    @pytest.fixture
    def mock_app_state(self):
        """Create a mock application state."""
        state = MagicMock()
        return state

    @pytest.mark.asyncio
    async def test_no_static_route_uses_requested_model(
        self,
        mock_config_without_static_route,
        mock_session_service,
        mock_backend_factory,
        mock_wire_capture,
        mock_rate_limiter,
        mock_app_state,
    ):
        """Test that without static_route, the requested model is used."""
        service = BackendService(
            factory=mock_backend_factory,
            rate_limiter=mock_rate_limiter,
            config=mock_config_without_static_route,
            session_service=mock_session_service,
            app_state=mock_app_state,
            wire_capture=mock_wire_capture,
            failover_routes={},
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "test"}],
        )

        backend_type, effective_model = await service._resolve_backend_and_model(
            request
        )

        assert effective_model == "gpt-4"
        assert backend_type == "openai"

    @pytest.mark.asyncio
    async def test_static_route_overrides_both_backend_and_model(
        self,
        mock_config_with_static_route,
        mock_session_service,
        mock_backend_factory,
        mock_wire_capture,
        mock_rate_limiter,
        mock_app_state,
    ):
        """Test that static_route overrides both backend and model."""
        service = BackendService(
            factory=mock_backend_factory,
            rate_limiter=mock_rate_limiter,
            config=mock_config_with_static_route,
            session_service=mock_session_service,
            app_state=mock_app_state,
            wire_capture=mock_wire_capture,
            failover_routes={},
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "test"}],
        )

        backend_type, effective_model = await service._resolve_backend_and_model(
            request
        )

        assert backend_type == "gemini-cli-oauth-personal"
        assert effective_model == "gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_static_route_with_backend_prefix_in_request(
        self,
        mock_config_with_static_route,
        mock_session_service,
        mock_backend_factory,
        mock_wire_capture,
        mock_rate_limiter,
        mock_app_state,
    ):
        """Test that static_route works with backend:model prefix in request."""
        service = BackendService(
            factory=mock_backend_factory,
            rate_limiter=mock_rate_limiter,
            config=mock_config_with_static_route,
            session_service=mock_session_service,
            app_state=mock_app_state,
            wire_capture=mock_wire_capture,
            failover_routes={},
        )

        request = ChatRequest(
            model="openai:gpt-4-turbo",
            messages=[{"role": "user", "content": "test"}],
        )

        backend_type, effective_model = await service._resolve_backend_and_model(
            request
        )

        assert backend_type == "gemini-cli-oauth-personal"
        assert effective_model == "gemini-2.5-pro"


class TestStaticRouteCLI:
    """Test suite for static_route CLI argument parsing."""

    def test_cli_args_parsing_with_static_route(self):
        """Test that --static-route CLI argument is parsed correctly."""
        from src.core.cli import parse_cli_args

        args = parse_cli_args(
            ["--static-route", "gemini-cli-oauth-personal:gemini-2.5-pro"]
        )
        assert args.static_route == "gemini-cli-oauth-personal:gemini-2.5-pro"

    def test_cli_args_parsing_without_static_route(self):
        """Test that static_route is None when not specified."""
        from src.core.cli import parse_cli_args

        args = parse_cli_args([])
        assert getattr(args, "static_route", None) is None

    def test_cli_config_application(self):
        """Test that static_route is applied to config from CLI args."""
        import os
        from unittest.mock import patch

        from src.core.cli import apply_cli_args, parse_cli_args

        # Use patch.dict to completely isolate environment
        with patch.dict(os.environ, {}, clear=True):
            args = parse_cli_args(
                [
                    "--static-route",
                    "gemini-cli-oauth-personal:gemini-2.5-pro",
                    "--default-backend",
                    "openai",
                ]
            )
            config = apply_cli_args(args)

            assert (
                config.backends.static_route
                == "gemini-cli-oauth-personal:gemini-2.5-pro"
            )
            assert config.backends.default_backend == "openai"

    def test_cli_rejects_force_model(self):
        """Test that --force-model is rejected (removed parameter)."""
        from src.core.cli import parse_cli_args

        # Should raise SystemExit because --force-model is not a valid argument
        with pytest.raises(SystemExit):
            parse_cli_args(["--force-model", "gemini-2.5-pro"])
