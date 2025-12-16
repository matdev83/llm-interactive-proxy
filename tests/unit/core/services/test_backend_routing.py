from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import ChatRequest
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService

# Skip entire module - tests depend on _refresh_instance_registry which is not yet implemented
pytestmark = pytest.mark.skip(
    reason="Multi-instance backend routing feature not yet implemented"
)


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
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
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
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
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
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
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

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_concurrency_limiting(
        self, backend_service, mock_config, mock_factory
    ):
        """Test that requests block when concurrency limit is reached for an instance."""
        # Setup: backend with no concurrent use allowed
        # Use the correct connector name so _refresh_instance_registry groups it properly
        mock_config.backends.__dict__.update(
            {
                "single_thread": BackendConfig(
                    api_key=["k"], connector="single_thread", allow_concurrent_use=False
                )
            }
        )
        backend_service._refresh_instance_registry()

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "single_thread"
        backend.get_retry_after_remaining.return_value = None

        # Mock chat_completions to be slow
        async def slow_chat(*args, **kwargs):
            import asyncio

            await asyncio.sleep(0.1)
            return MagicMock(metadata={})

        backend.chat_completions = AsyncMock(side_effect=slow_chat)
        mock_factory.ensure_backend.return_value = backend

        # Use "single_thread:model" format to explicitly target the "single_thread" backend
        req = ChatRequest(
            model="single_thread:test-model",
            messages=[{"role": "user", "content": "hi"}],
        )

        import asyncio
        import time

        start_time = time.time()
        # Launch 2 requests concurrently
        # Since allow_concurrent_use=False, the second one should wait for the first
        results = await asyncio.gather(
            backend_service.call_completion(req), backend_service.call_completion(req)
        )
        end_time = time.time()

        # If they ran in parallel, duration ~ 0.1s
        # If sequential, duration ~ 0.2s
        # Allow some margin
        assert (end_time - start_time) >= 0.2
        assert len(results) == 2


class TestModelFormatRouting:
    """Tests for all three model format routing scenarios:
    1. <backend>.<instance>:<model> - specific instance
    2. <backend>:<model> - any instance of backend
    3. <model> - model-centric routing (includes vendor/model format)
    """

    @pytest.fixture
    def mock_factory(self):
        factory = MagicMock(spec=BackendFactory)
        factory.ensure_backend = AsyncMock()
        factory.create_backend = MagicMock()
        return factory

    @pytest.fixture
    def mock_rate_limiter(self):
        limiter = MagicMock()
        limiter.check_limit = AsyncMock(return_value=MagicMock(is_limited=False))
        limiter.record_usage = AsyncMock()
        limiter.apply_cooldown = AsyncMock()
        return limiter

    @pytest.fixture
    def mock_config(self):
        config = MagicMock(spec=AppConfig)

        class DummyBackendSettings:
            def __init__(self):
                self.__dict__ = {}
                self.default_backend = "openai"
                self.static_route = None

            def get(self, k):
                return self.__dict__.get(k)

        config.backends = DummyBackendSettings()
        config.identity = "mock-identity"
        return config

    @pytest.fixture
    def backend_service(self, mock_factory, mock_rate_limiter, mock_config):
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
        return service

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format1_specific_instance(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 1: <backend>.<instance>:<model> routes to specific instance."""
        mock_config.backends.__dict__.update(
            {
                "openai.1": BackendConfig(api_key=["k1"], connector="openai"),
                "openai.2": BackendConfig(api_key=["k2"], connector="openai"),
            }
        )
        backend_service._refresh_instance_registry()

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "openai.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with explicit instance: openai.1:gpt-4
        req = ChatRequest(
            model="openai.1:gpt-4", messages=[{"role": "user", "content": "hi"}]
        )
        await backend_service.call_completion(req)

        # Verify ensure_backend was called with the specific instance
        args, _ = mock_factory.ensure_backend.call_args
        assert args[0] == "openai.1"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format2_generic_backend(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 2: <backend>:<model> routes through round robin across instances."""
        mock_config.backends.__dict__.update(
            {
                "openai.1": BackendConfig(api_key=["k1"], connector="openai"),
                "openai.2": BackendConfig(api_key=["k2"], connector="openai"),
            }
        )
        backend_service._refresh_instance_registry()

        backend1 = MagicMock()
        backend1.is_backend_functional.return_value = True
        backend1.backend_type = "openai.1"
        backend1.get_retry_after_remaining.return_value = None
        backend1.chat_completions = AsyncMock()

        backend2 = MagicMock()
        backend2.is_backend_functional.return_value = True
        backend2.backend_type = "openai.2"
        backend2.get_retry_after_remaining.return_value = None
        backend2.chat_completions = AsyncMock()

        mock_factory.ensure_backend.side_effect = [backend1, backend2]

        # Request with generic backend: openai:gpt-4
        req = ChatRequest(
            model="openai:gpt-4", messages=[{"role": "user", "content": "hi"}]
        )

        # Make two requests to see round robin in action
        await backend_service.call_completion(req)
        await backend_service.call_completion(req)

        calls = mock_factory.ensure_backend.call_args_list
        called_backends = [c[0][0] for c in calls]
        # Should have called both instances via round robin
        assert "openai.1" in called_backends
        assert "openai.2" in called_backends

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format3_model_only_simple(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 3: <model> without backend prefix uses model routing table."""
        mock_config.backends.__dict__.update(
            {"gemini.1": BackendConfig(api_key=["k"], connector="gemini")}
        )
        backend_service._refresh_instance_registry()

        # Pre-populate model routing table
        backend_service._model_routing_table["gemini-2.0-flash"] = ["gemini.1"]

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "gemini.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with just model name (no backend prefix)
        req = ChatRequest(
            model="gemini-2.0-flash", messages=[{"role": "user", "content": "hi"}]
        )
        await backend_service.call_completion(req)

        args, _ = mock_factory.ensure_backend.call_args
        assert args[0] == "gemini.1"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format3_vendor_prefixed_model(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 3: <vendor>/<model> is treated as a model name, not vendor as backend."""
        mock_config.backends.__dict__.update(
            {"openrouter.1": BackendConfig(api_key=["k"], connector="openrouter")}
        )
        backend_service._refresh_instance_registry()

        # Pre-populate model routing table with vendor-prefixed model
        backend_service._model_routing_table["google/gemini-pro"] = ["openrouter.1"]

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "openrouter.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with vendor-prefixed model name
        # IMPORTANT: "google/gemini-pro" should NOT be parsed as backend=google, model=gemini-pro
        # It should be treated as a model name and routed via the model routing table
        req = ChatRequest(
            model="google/gemini-pro", messages=[{"role": "user", "content": "hi"}]
        )
        await backend_service.call_completion(req)

        args, _ = mock_factory.ensure_backend.call_args
        # Should route to openrouter.1 (from model routing table), not "google"
        assert args[0] == "openrouter.1"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format2_with_vendor_prefixed_model(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 2: <backend>:<vendor>/<model> correctly preserves vendor prefix in model."""
        mock_config.backends.__dict__.update(
            {"openrouter.1": BackendConfig(api_key=["k"], connector="openrouter")}
        )
        backend_service._refresh_instance_registry()

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "openrouter.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with explicit backend and vendor-prefixed model
        req = ChatRequest(
            model="openrouter:anthropic/claude-3-haiku",
            messages=[{"role": "user", "content": "hi"}],
        )
        await backend_service.call_completion(req)

        args, _ = mock_factory.ensure_backend.call_args
        # Backend should be openrouter.1 (resolved from openrouter)
        assert args[0] == "openrouter.1"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format3_unknown_vendor_falls_to_default(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 3: Unknown vendor/<model> without model routing falls to default backend."""
        mock_config.backends.__dict__.update(
            {"openai.1": BackendConfig(api_key=["k"], connector="openai")}
        )
        backend_service._refresh_instance_registry()

        # Model routing table does NOT have this model
        backend_service._model_routing_table = {}

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "openai.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with unknown vendor-prefixed model
        # "unknown_vendor/some-model" should NOT be parsed as backend=unknown_vendor
        # Since unknown_vendor is not a known connector, it should fall to default backend
        req = ChatRequest(
            model="unknown_vendor/some-model",
            messages=[{"role": "user", "content": "hi"}],
        )
        await backend_service.call_completion(req)

        args, _ = mock_factory.ensure_backend.call_args
        # Should use default backend (openai -> openai.1), not "unknown_vendor"
        assert args[0] == "openai.1"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
    )
    async def test_format2_model_with_colon_suffix(
        self, backend_service, mock_config, mock_factory
    ):
        """Format 2: Model names can contain colons (e.g., xai/grok-4.1-fast:free)."""
        mock_config.backends.__dict__.update(
            {"openrouter.1": BackendConfig(api_key=["k"], connector="openrouter")}
        )
        backend_service._refresh_instance_registry()

        backend = MagicMock()
        backend.is_backend_functional.return_value = True
        backend.backend_type = "openrouter.1"
        backend.get_retry_after_remaining.return_value = None
        backend.chat_completions = AsyncMock()
        mock_factory.ensure_backend.return_value = backend

        # Request with model containing colon suffix (e.g., :free, :beta)
        # "openrouter:xai/grok-4.1-fast:free" should parse as:
        # - backend: openrouter
        # - model: xai/grok-4.1-fast:free (including the :free suffix)
        req = ChatRequest(
            model="openrouter:xai/grok-4.1-fast:free",
            messages=[{"role": "user", "content": "hi"}],
        )
        await backend_service.call_completion(req)

        args, _ = mock_factory.ensure_backend.call_args
        # Should route to openrouter.1
        assert args[0] == "openrouter.1"

        # Verify the model name passed to the backend includes the :free suffix
        # The effective_model should be "xai/grok-4.1-fast:free"
        # We can check this by looking at the chat_completions call
        chat_call_args = backend.chat_completions.call_args
        assert chat_call_args is not None
        # The effective_model is passed as a keyword argument
        assert chat_call_args.kwargs.get("effective_model") == "xai/grok-4.1-fast:free"
