from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import ChatRequest
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService


class TestBackendRouting:

    @pytest.fixture
    def mock_factory(self):
        factory = MagicMock(spec=BackendFactory)
        factory.ensure_backend = AsyncMock()
        # Mock factory.create_backend to return a dummy backend
        factory.create_backend = MagicMock()
        return factory

    @pytest.fixture
    def mock_rate_limiter(self):
        limiter = MagicMock()
        # Default to not limited
        limiter.check_limit = AsyncMock(return_value=MagicMock(is_limited=False))
        limiter.record_usage = AsyncMock()
        limiter.apply_cooldown = AsyncMock()
        return limiter

    @pytest.fixture
    def mock_config(self):
        config = MagicMock(spec=AppConfig)

        # Use a dummy class for backends to avoid MagicMock __dict__ issues
        class DummyBackendSettings:
            def __init__(self):
                self.__dict__ = {}
                self.default_backend = "openai"
                self.static_route = None  # Ensure static_route exists

            def get(self, k):
                return self.__dict__.get(k)

        config.backends = DummyBackendSettings()
        # Mock identity on config
        config.identity = "mock-identity"
        return config

    @pytest.fixture
    def backend_service(self, mock_factory, mock_rate_limiter, mock_config):
        # We need to mock other dependencies
        mock_provider = MagicMock()
        
        def get_config(backend_name):
             return mock_config.backends.__dict__.get(backend_name)
             
        mock_provider.get_backend_config.side_effect = get_config

        service = BackendService(
            factory=mock_factory,
            rate_limiter=mock_rate_limiter,
            config=mock_config,
            session_service=MagicMock(),
            app_state=MagicMock(),
            backend_config_provider=mock_provider,
        )
        # Add mock methods that we plan to implement if not already present
        # service._is_instance_available = MagicMock(return_value=True)
        return service

    @pytest.mark.asyncio
    async def test_round_robin_load_balancing(
        self, backend_service, mock_config, mock_factory
    ):
        """Test that requests for a generic backend rotate across available instances."""
        # Setup: 2 instances for 'openrouter'
        mock_config.backends.__dict__.update(
            {
                "openrouter.1": BackendConfig(api_key=["k1"], connector="openrouter"),
                "openrouter.2": BackendConfig(api_key=["k2"], connector="openrouter"),
            }
        )

        # Manually trigger refresh because we injected config after init
        backend_service._refresh_instance_registry()

        # Mock ensure_backend to return mock backends
        backend1 = MagicMock()
        backend1.is_backend_functional.return_value = True
        backend1.backend_type = "openrouter.1"
        backend1.get_retry_after_remaining.return_value = None  # Not rate limited
        backend1.chat_completions = AsyncMock()

        backend2 = MagicMock()
        backend2.is_backend_functional.return_value = True
        backend2.backend_type = "openrouter.2"
        backend2.get_retry_after_remaining.return_value = None  # Not rate limited
        backend2.chat_completions = AsyncMock()

        mock_factory.ensure_backend.side_effect = [
            backend1,
            backend2,
            backend1,
            backend2,
        ]

        # Request 1 for 'openrouter'
        req = ChatRequest(
            model="openrouter:gpt-4o", messages=[{"role": "user", "content": "hi"}]
        )
        await backend_service.call_completion(req)

        # Request 2
        await backend_service.call_completion(req)

        # Verify factory was called with different instance names
        calls = mock_factory.ensure_backend.call_args_list
        assert len(calls) >= 2

        # Extract the backend_type arg from calls
        # We need to verify that we are calling with different backend types
        called_backends = [c[0][0] for c in calls]
        assert "openrouter.1" in called_backends
        assert "openrouter.2" in called_backends

    @pytest.mark.asyncio
    async def test_model_centric_routing(
        self, backend_service, mock_config, mock_factory
    ):
        """Test routing based on model name without backend prefix."""
        # Setup: gemini.1 supports 'gemini-1.5-pro'
        mock_config.backends.__dict__.update(
            {"gemini.1": BackendConfig(api_key=["k"], connector="gemini")}
        )

        # Trigger refresh
        backend_service._refresh_instance_registry()

        backend_gemini = MagicMock()
        backend_gemini.is_backend_functional.return_value = True
        backend_gemini.get_available_models.return_value = ["gemini-1.5-pro"]
        backend_gemini.get_retry_after_remaining.return_value = None  # Not rate limited
        backend_gemini.chat_completions = AsyncMock()

        mock_factory.ensure_backend.return_value = backend_gemini

        # Pre-populate the routing table
        if not hasattr(backend_service, "_model_routing_table"):
            backend_service._model_routing_table = {}
        backend_service._model_routing_table["gemini-1.5-pro"] = ["gemini.1"]

        # Request with JUST model name
        req = ChatRequest(
            model="gemini-1.5-pro", messages=[{"role": "user", "content": "hi"}]
        )

        await backend_service.call_completion(req)

        # Verify ensure_backend call
        # We only check the first argument (backend_type) and third argument (BackendConfig)
        # Because config arg might be weirdly matched
        args, _ = mock_factory.ensure_backend.call_args
        assert args[0] == "gemini.1"
        assert isinstance(args[2], BackendConfig)

    @pytest.mark.asyncio
    async def test_granular_rate_limiting_skip(self, backend_service, mock_config):
        """Test that rate-limited instances are skipped."""
        mock_config.backends.__dict__.update(
            {
                "openrouter.1": BackendConfig(api_key=["k1"], connector="openrouter"),
                "openrouter.2": BackendConfig(api_key=["k2"], connector="openrouter"),
            }
        )

        # Trigger refresh
        backend_service._refresh_instance_registry()

        # Mock _is_instance_available to return False for openrouter.1
        # We assume _is_instance_available is implemented now.
        with patch.object(
            backend_service,
            "_is_instance_available",
            side_effect=lambda name, model: name == "openrouter.2",
        ):
            # We need to ensure ensure_backend is called for the backend we pick
            backend2 = MagicMock()
            backend2.is_backend_functional.return_value = True
            backend2.backend_type = "openrouter.2"
            backend2.get_retry_after_remaining.return_value = None  # Not rate limited
            backend2.chat_completions = AsyncMock()

            backend_service._factory.ensure_backend.return_value = backend2

            req = ChatRequest(
                model="openrouter:gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )
            # Should pick .2
            await backend_service.call_completion(req)

            # Verify ensure_backend call
            args, _ = backend_service._factory.ensure_backend.call_args
            assert args[0] == "openrouter.2"
            assert isinstance(args[2], BackendConfig)
