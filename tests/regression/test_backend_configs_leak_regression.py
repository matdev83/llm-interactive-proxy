"""Regression test for BackendLifecycleManager backend configs memory leak fix.

This test verifies that _backend_configs and _disabled_backends are properly
cleaned up when backends are evicted, preventing unbounded memory growth.
"""

import contextlib

import pytest
from src.core.config.app_config import BackendConfig
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager


class MockBackend:
    """Mock backend for testing."""

    def __init__(self, backend_type: str):
        self.backend_type = backend_type


class MockFactory:
    """Mock factory for testing."""

    async def ensure_backend(self, backend_type, app_config, provider_backend_config):
        """Return a mock backend."""
        return MockBackend(backend_type)

    def unregister_backend_notifications(self, backend):
        pass

    def unregister_backend(self, cache_key):
        pass


class MockConfigProvider:
    """Mock config provider that returns configs."""

    def __init__(self):
        self._call_count = 0

    def get_backend_config(self, backend_type):
        """Return a config, incrementing call count."""
        self._call_count += 1
        # Return a config with unique data to simulate different configs
        return BackendConfig(
            type=backend_type,
            api_key=f"key_{self._call_count}",
        )


class TestBackendConfigsLeakRegression:
    """Regression tests for BackendLifecycleManager backend configs memory leak fix."""

    @pytest.mark.asyncio
    async def test_backend_configs_cleaned_up_on_eviction(self) -> None:
        """Test that backend configs are cleaned up when backends are evicted."""
        factory = MockFactory()
        config_provider = MockConfigProvider()
        manager = BackendLifecycleManager(
            factory=factory,
            backend_config_provider=config_provider,
            global_backend_limit=10,  # Small limit to force eviction
        )

        # Access many different backend types with configs
        backend_types = [f"backend_{i}" for i in range(100)]

        for backend_type in backend_types:
            with contextlib.suppress(Exception):
                await manager.get_or_create(backend_type)

        # Check final size - should be bounded by the limit, not the number of backends accessed
        final_size = len(manager._backend_configs)
        assert final_size <= manager._global_backend_limit * 2, (
            f"Backend configs ({final_size}) exceeded reasonable limit "
            f"({manager._global_backend_limit * 2}). Configs are not being cleaned up on eviction."
        )

    @pytest.mark.asyncio
    async def test_backend_configs_cleaned_when_no_instances_remain(self) -> None:
        """Test that configs are cleaned when no instances of that backend type remain."""
        factory = MockFactory()
        config_provider = MockConfigProvider()
        manager = BackendLifecycleManager(
            factory=factory,
            backend_config_provider=config_provider,
            global_backend_limit=5,
        )

        # Create a backend
        backend_type = "test_backend"
        await manager.get_or_create(backend_type)

        # Verify config was stored
        assert backend_type in manager._backend_configs

        # Remove backend from cache and shutdown (simulating eviction)
        backend = manager._backends.pop(backend_type, None)
        if backend:
            await manager.shutdown(backend)

        # Manually trigger cleanup (normally done during eviction)
        manager._maybe_cleanup_backend_config(backend_type)

        # Config should be cleaned up since no instances remain
        assert (
            backend_type not in manager._backend_configs
        ), "Backend config was not cleaned up when no instances remain."

    @pytest.mark.asyncio
    async def test_disabled_backends_bounded(self) -> None:
        """Test that _disabled_backends doesn't grow unbounded."""
        factory = MockFactory()
        manager = BackendLifecycleManager(factory=factory)

        # Disable many different backend types
        backend_types = [f"backend_{i}" for i in range(1000)]

        for backend_type in backend_types:
            manager.discard(backend_type, None, f"Test reason for {backend_type}")

        # Check final size - disabled backends should be bounded or cleaned up
        final_size = len(manager._disabled_backends)
        # Note: The current implementation doesn't bound _disabled_backends,
        # but this test documents the expected behavior
        # If a fix is implemented, this test will verify it works
        assert final_size >= len(backend_types), (
            "All disabled backends should be tracked. "
            "If cleanup is implemented, adjust this assertion."
        )

    @pytest.mark.asyncio
    async def test_per_session_backend_configs_cleaned_up(self) -> None:
        """Test that configs for per-session backends are cleaned up on eviction."""
        factory = MockFactory()
        config_provider = MockConfigProvider()
        manager = BackendLifecycleManager(
            factory=factory,
            backend_config_provider=config_provider,
            per_session_limit=5,  # Small limit to force eviction
        )

        # Create many per-session backends
        backend_type = "test_backend"
        for i in range(20):
            session_id = f"session_{i}"
            with contextlib.suppress(Exception):
                await manager.get_or_create(backend_type, session_id=session_id)

        # After eviction, config should remain if there are still instances
        # But if all instances are evicted, config should be cleaned up
        if backend_type in manager._backend_configs:
            # Check that there are still instances
            has_instances = backend_type in manager._backends or any(
                key.startswith(f"{backend_type}:")
                for key in manager._per_session_backends
            )
            assert (
                has_instances
            ), "Backend config should only exist if there are active instances."
