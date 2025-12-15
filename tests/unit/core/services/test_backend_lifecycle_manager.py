"""Unit tests for BackendLifecycleManager service.

Tests the extracted BackendLifecycleManager service for equivalence with
BackendService lifecycle methods.

Feature: backend-service-refactoring
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager


class MockLLMBackend:
    """Mock backend for testing."""

    def __init__(self, backend_type: str) -> None:
        self.backend_type = backend_type
        self.shutdown_called = False

    async def shutdown(self) -> None:
        self.shutdown_called = True


class MockBackendFactory:
    """Mock factory for testing."""

    def __init__(self) -> None:
        self.created_backends: list[str] = []
        self.unregistered_backends: list[str] = []
        self.unregistered_notifications: list[Any] = []

    async def ensure_backend(
        self, backend_type: str, app_config: Any, backend_config: Any = None
    ) -> MockLLMBackend:
        self.created_backends.append(backend_type)
        return MockLLMBackend(backend_type)

    def unregister_backend_notifications(self, backend: Any) -> None:
        self.unregistered_notifications.append(backend)

    def unregister_backend(self, key: str) -> None:
        self.unregistered_backends.append(key)


class TestBackendLifecycleManagerGetOrCreate:
    """Tests for get_or_create method."""

    @pytest.mark.asyncio
    async def test_creates_new_backend(self) -> None:
        """Should create new backend when not in cache."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        backend = await manager.get_or_create("openai")

        assert backend.backend_type == "openai"
        assert "openai" in factory.created_backends

    @pytest.mark.asyncio
    async def test_returns_cached_backend(self) -> None:
        """Should return cached backend on subsequent calls."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        backend1 = await manager.get_or_create("openai")
        backend2 = await manager.get_or_create("openai")

        assert backend1 is backend2
        assert factory.created_backends.count("openai") == 1

    @pytest.mark.asyncio
    async def test_session_backends_are_isolated(self) -> None:
        """Different session IDs should get different backends."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        backend1 = await manager.get_or_create("openai", session_id="session-1")
        backend2 = await manager.get_or_create("openai", session_id="session-2")

        assert backend1 is not backend2

    @pytest.mark.asyncio
    async def test_disabled_backend_raises_error(self) -> None:
        """Should raise BackendError for disabled backends."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        manager.discard("openai", None, "auth failed")

        with pytest.raises(BackendError) as exc_info:
            await manager.get_or_create("openai")

        assert "permanently disabled" in str(exc_info.value)
        assert "auth failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_factory_raises_error(self) -> None:
        """Should raise BackendError when no factory is configured."""
        manager = BackendLifecycleManager()

        with pytest.raises(BackendError) as exc_info:
            await manager.get_or_create("openai")

        assert "no factory configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_gemini_cli_acp_uses_default_key(self) -> None:
        """gemini-cli-acp without session_id should use default key."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("gemini-cli-acp")

        assert "gemini-cli-acp:default" in manager._per_session_backends

    @pytest.mark.asyncio
    async def test_per_session_cache_lru_eviction(self) -> None:
        """Per-session cache should evict LRU backends."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=2)  # type: ignore

        backend1 = await manager.get_or_create("openai", session_id="session-1")
        await manager.get_or_create("openai", session_id="session-2")
        await manager.get_or_create("openai", session_id="session-3")

        assert len(manager._per_session_backends) == 2
        assert "openai:session-1" not in manager._per_session_backends
        assert backend1.shutdown_called  # type: ignore

    @pytest.mark.asyncio
    async def test_accessing_cached_moves_to_mru(self) -> None:
        """Accessing cached backend should move it to MRU position."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=3)  # type: ignore

        await manager.get_or_create("openai", session_id="session-1")
        await manager.get_or_create("openai", session_id="session-2")
        await manager.get_or_create("openai", session_id="session-3")

        # Access session-1 to move it to MRU
        await manager.get_or_create("openai", session_id="session-1")

        # Now add session-4, session-2 should be evicted (was LRU)
        await manager.get_or_create("openai", session_id="session-4")

        assert "openai:session-1" in manager._per_session_backends
        assert "openai:session-2" not in manager._per_session_backends


class TestBackendLifecycleManagerShutdown:
    """Tests for shutdown method."""

    @pytest.mark.asyncio
    async def test_calls_async_shutdown(self) -> None:
        """Should call async shutdown method on backend."""
        manager = BackendLifecycleManager()
        backend = MockLLMBackend("openai")

        await manager.shutdown(backend)  # type: ignore[arg-type]

        assert backend.shutdown_called

    @pytest.mark.asyncio
    async def test_calls_sync_shutdown(self) -> None:
        """Should call sync shutdown method on backend."""
        manager = BackendLifecycleManager()

        class SyncShutdownBackend:
            backend_type = "test"
            shutdown_called = False

            def shutdown(self) -> None:
                self.shutdown_called = True

        backend = SyncShutdownBackend()
        await manager.shutdown(backend)  # type: ignore

        assert backend.shutdown_called

    @pytest.mark.asyncio
    async def test_handles_missing_shutdown(self) -> None:
        """Should handle backends without shutdown method."""
        manager = BackendLifecycleManager()

        class NoShutdownBackend:
            backend_type = "test"

        backend = NoShutdownBackend()

        # Should not raise
        await manager.shutdown(backend)  # type: ignore

    @pytest.mark.asyncio
    async def test_handles_shutdown_error(self) -> None:
        """Should log but not raise on shutdown error."""
        manager = BackendLifecycleManager()

        class ErrorShutdownBackend:
            backend_type = "test"

            async def shutdown(self) -> None:
                raise ValueError("Shutdown error")

        backend = ErrorShutdownBackend()

        # Should not raise
        await manager.shutdown(backend)  # type: ignore


class TestBackendLifecycleManagerDiscard:
    """Tests for discard method."""

    @pytest.mark.asyncio
    async def test_marks_backend_disabled(self) -> None:
        """Discard should mark backend as disabled."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        manager.discard("openai", None, "test reason")

        assert manager.is_disabled("openai")
        assert manager._disabled_backends["openai"]["reason"] == "test reason"

    @pytest.mark.asyncio
    async def test_removes_from_global_cache(self) -> None:
        """Discard should remove backend from global cache."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai")
        assert "openai" in manager._backends

        manager.discard("openai", None, "test")

        assert "openai" not in manager._backends

    @pytest.mark.asyncio
    async def test_removes_all_per_session_variants(self) -> None:
        """Discard without session_id should remove all per-session variants."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=10)  # type: ignore

        await manager.get_or_create("openai", session_id="s1")
        await manager.get_or_create("openai", session_id="s2")
        await manager.get_or_create("openai", session_id="s3")

        manager.discard("openai", None, "test")

        assert len(manager._per_session_backends) == 0

    @pytest.mark.asyncio
    async def test_discard_with_session_id_purges_all_variants(self) -> None:
        """Discard with session_id should still purge global and all per-session variants."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=10)  # type: ignore

        global_backend = await manager.get_or_create("openai")
        session_backend_1 = await manager.get_or_create("openai", session_id="s1")
        session_backend_2 = await manager.get_or_create("openai", session_id="s2")

        manager.discard("openai", "s1", "test")

        assert "openai" not in manager._backends
        assert (
            len([k for k in manager._per_session_backends if k.startswith("openai:")])
            == 0
        )
        assert {"openai", "openai:s1", "openai:s2"}.issubset(
            set(factory.unregistered_backends)
        )

        await asyncio.sleep(0)
        assert global_backend.shutdown_called  # type: ignore[attr-defined]
        assert session_backend_1.shutdown_called  # type: ignore[attr-defined]
        assert session_backend_2.shutdown_called  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_unregisters_from_factory(self) -> None:
        """Discard should unregister backend from factory."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        backend = await manager.get_or_create("openai")
        manager.discard("openai", None, "test")

        assert backend in factory.unregistered_notifications
        assert "openai" in factory.unregistered_backends


class TestBackendLifecycleManagerIsDisabled:
    """Tests for is_disabled method."""

    def test_returns_false_for_enabled(self) -> None:
        """Should return False for enabled backends."""
        manager = BackendLifecycleManager()

        assert not manager.is_disabled("openai")

    def test_returns_true_for_disabled(self) -> None:
        """Should return True for disabled backends."""
        manager = BackendLifecycleManager()
        manager.discard("openai", None, "test")

        assert manager.is_disabled("openai")


class TestBackendLifecycleManagerGetActiveBackends:
    """Tests for get_active_backends method."""

    @pytest.mark.asyncio
    async def test_returns_empty_initially(self) -> None:
        """Should return empty dict when no backends created."""
        manager = BackendLifecycleManager()

        assert manager.get_active_backends() == {}

    @pytest.mark.asyncio
    async def test_includes_global_backends(self) -> None:
        """Should include global backends."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai")
        await manager.get_or_create("anthropic")

        active = manager.get_active_backends()

        assert "openai" in active
        assert "anthropic" in active

    @pytest.mark.asyncio
    async def test_includes_per_session_backends(self) -> None:
        """Should include per-session backends."""
        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai", session_id="s1")
        await manager.get_or_create("openai", session_id="s2")

        active = manager.get_active_backends()

        assert "openai:s1" in active
        assert "openai:s2" in active


class TestBackendLifecycleManagerCacheKeyRules:
    """Test cache key generation rules."""

    def test_is_per_session_cache_key_with_session(self) -> None:
        """Cache key with session should be per-session."""
        assert BackendLifecycleManager._is_per_session_cache_key(
            "openai:session-1", "openai"
        )

    def test_is_per_session_cache_key_without_session(self) -> None:
        """Cache key without session should not be per-session."""
        assert not BackendLifecycleManager._is_per_session_cache_key("openai", "openai")


class TestBackendLifecycleManagerEquivalence:
    """Equivalence tests comparing to BackendService methods."""

    @pytest.mark.asyncio
    async def test_get_or_create_equivalence(self) -> None:
        """BackendLifecycleManager.get_or_create should behave like BackendService."""
        from src.core.config.app_config import AppConfig
        from src.core.services.backend_factory import BackendFactory
        from src.core.services.backend_service import BackendService

        # Create mock factory that returns mock backends
        mock_factory = Mock(spec=BackendFactory)
        mock_backend = MockLLMBackend("openai")
        mock_factory.ensure_backend = AsyncMock(return_value=mock_backend)

        # Create BackendService
        session_service = AsyncMock()
        app_config = AppConfig()
        backend_service = BackendService(
            factory=mock_factory,
            rate_limiter=Mock(),
            config=app_config,
            session_service=session_service,
            app_state=Mock(),
        )

        # Create BackendLifecycleManager
        lifecycle_manager = BackendLifecycleManager(
            factory=mock_factory,
            config=app_config,
        )

        # Both should get/create backends correctly
        bs_backend = await backend_service._get_or_create_backend("openai")
        lm_backend = await lifecycle_manager.get_or_create("openai")

        # Both should have the same backend type
        assert bs_backend.backend_type == lm_backend.backend_type

    def test_is_per_session_cache_key_equivalence(self) -> None:
        """_is_per_session_cache_key should match BackendService behavior."""
        from src.core.services.backend_service import BackendService

        test_cases = [
            ("openai", "openai"),
            ("openai:session-1", "openai"),
            ("anthropic:test", "anthropic"),
            ("gemini-cli-acp:default", "gemini-cli-acp"),
        ]

        for cache_key, backend_type in test_cases:
            bs_result = BackendService._is_per_session_cache_key(
                cache_key, backend_type
            )
            lm_result = BackendLifecycleManager._is_per_session_cache_key(
                cache_key, backend_type
            )
            assert bs_result == lm_result, f"Mismatch for {cache_key}, {backend_type}"
