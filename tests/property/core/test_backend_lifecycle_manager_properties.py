"""Property-based tests for BackendLifecycleManager.

Validates:
- Property 12: Backend Cache LRU (Requirements 11.1)

Feature: backend-service-refactoring
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


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

    async def ensure_backend(
        self, backend_type: str, app_config: Any, backend_config: Any = None
    ) -> MockLLMBackend:
        self.created_backends.append(backend_type)
        return MockLLMBackend(backend_type)

    def unregister_backend_notifications(self, backend: Any) -> None:
        pass

    def unregister_backend(self, key: str) -> None:
        pass


class TestBackendCacheLRUProperty:
    """Property 12: Backend Cache LRU (Requirements 11.1).

    For any sequence of backend requests exceeding the cache limit,
    the lifecycle manager SHALL evict the least recently used backend.
    """

    @given(
        num_sessions=st.integers(min_value=5, max_value=20),
        cache_limit=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_lru_eviction_on_limit(
        self, num_sessions: int, cache_limit: int
    ) -> None:
        """When exceeding cache limit, LRU backend should be evicted."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(
            factory=factory,  # type: ignore
            per_session_limit=cache_limit,
        )

        # Create backends for multiple sessions
        created_backends: list[MockLLMBackend] = []
        for i in range(num_sessions):
            backend = await manager.get_or_create("openai", session_id=f"session-{i}")
            created_backends.append(backend)  # type: ignore

        # Cache should not exceed limit
        assert len(manager._per_session_backends) <= cache_limit

        # The most recent backends should be in cache
        expected_sessions = [f"openai:session-{i}" for i in range(num_sessions)]
        expected_in_cache = set(expected_sessions[-cache_limit:])
        actual_in_cache = set(manager._per_session_backends.keys())
        assert actual_in_cache == expected_in_cache

    @given(
        access_pattern=st.lists(
            st.integers(min_value=0, max_value=4), min_size=5, max_size=20
        )
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_lru_order_maintained_on_access(
        self, access_pattern: list[int]
    ) -> None:
        """Accessing a cached backend should move it to MRU position."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        cache_limit = 3
        manager = BackendLifecycleManager(
            factory=factory,  # type: ignore
            per_session_limit=cache_limit,
        )

        # Create initial backends
        for i in range(cache_limit):
            await manager.get_or_create("openai", session_id=f"session-{i}")

        # Access backends in given pattern
        for session_idx in access_pattern:
            session_id = f"session-{session_idx % cache_limit}"
            await manager.get_or_create("openai", session_id=session_id)

        # Cache should still be within limit
        assert len(manager._per_session_backends) <= cache_limit

    @pytest.mark.asyncio
    async def test_evicted_backends_are_shutdown(self) -> None:
        """Evicted backends should have their shutdown method called."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        cache_limit = 2
        manager = BackendLifecycleManager(
            factory=factory,  # type: ignore
            per_session_limit=cache_limit,
        )

        # Create backends that will be evicted
        backend1 = await manager.get_or_create("openai", session_id="session-1")
        backend2 = await manager.get_or_create("openai", session_id="session-2")

        # These should cause eviction
        await manager.get_or_create("openai", session_id="session-3")
        await manager.get_or_create("openai", session_id="session-4")

        # First backends should have been evicted and shutdown
        assert backend1.shutdown_called  # type: ignore
        assert backend2.shutdown_called  # type: ignore

    @pytest.mark.asyncio
    async def test_global_backends_not_subject_to_lru(self) -> None:
        """Global backends (no session_id) should not be evicted by LRU."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        cache_limit = 2
        manager = BackendLifecycleManager(
            factory=factory,  # type: ignore
            per_session_limit=cache_limit,
        )

        # Create global backends (no session_id)
        await manager.get_or_create("openai")
        await manager.get_or_create("anthropic")
        await manager.get_or_create("gemini")

        # Global backends should all be retained
        assert len(manager._backends) == 3

        # Create per-session backends to trigger LRU
        for i in range(5):
            await manager.get_or_create("openai", session_id=f"session-{i}")

        # Global backends should still be there
        assert len(manager._backends) == 3
        # Per-session backends should be limited
        assert len(manager._per_session_backends) <= cache_limit


class TestDisabledBackends:
    """Test that permanently disabled backends are tracked correctly."""

    @pytest.mark.asyncio
    async def test_disabled_backend_raises_error(self) -> None:
        """Attempting to get a disabled backend should raise BackendError."""
        from src.core.common.exceptions import BackendError
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        # Disable a backend
        manager.discard("openai", None, "auth failed")

        # Attempting to get it should raise
        with pytest.raises(BackendError) as exc_info:
            await manager.get_or_create("openai")

        assert "permanently disabled" in str(exc_info.value)
        assert "auth failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_is_disabled_returns_correct_status(self) -> None:
        """is_disabled should return correct status."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        assert not manager.is_disabled("openai")

        manager.discard("openai", None, "test reason")

        assert manager.is_disabled("openai")
        assert not manager.is_disabled("anthropic")


class TestCacheKeyRules:
    """Test cache key generation rules."""

    @pytest.mark.asyncio
    async def test_session_id_creates_per_session_key(self) -> None:
        """With session_id, backend should be in per-session cache."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai", session_id="test-session")

        assert "openai:test-session" in manager._per_session_backends
        assert "openai" not in manager._backends

    @pytest.mark.asyncio
    async def test_no_session_id_creates_global_key(self) -> None:
        """Without session_id, backend should be in global cache."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai")

        assert "openai" in manager._backends
        assert len(manager._per_session_backends) == 0

    @pytest.mark.asyncio
    async def test_gemini_cli_acp_special_case(self) -> None:
        """gemini-cli-acp without session_id should get default session key."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("gemini-cli-acp")

        assert "gemini-cli-acp:default" in manager._per_session_backends
        assert "gemini-cli-acp" not in manager._backends


class TestGetActiveBackends:
    """Test get_active_backends method."""

    @pytest.mark.asyncio
    async def test_returns_all_backends(self) -> None:
        """get_active_backends should return both global and per-session backends."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai")
        await manager.get_or_create("anthropic")
        await manager.get_or_create("openai", session_id="session-1")
        await manager.get_or_create("openai", session_id="session-2")

        active = manager.get_active_backends()

        assert len(active) == 4
        assert "openai" in active
        assert "anthropic" in active
        assert "openai:session-1" in active
        assert "openai:session-2" in active


class TestBackendShutdown:
    """Test backend shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown_calls_backend_shutdown(self) -> None:
        """shutdown should call the backend's shutdown method."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        manager = BackendLifecycleManager()
        backend = MockLLMBackend("openai")

        await manager.shutdown(backend)  # type: ignore[arg-type]

        assert backend.shutdown_called

    @pytest.mark.asyncio
    async def test_shutdown_handles_missing_shutdown_method(self) -> None:
        """shutdown should handle backends without shutdown method."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        manager = BackendLifecycleManager()

        class BackendWithoutShutdown:
            backend_type = "test"

        backend = BackendWithoutShutdown()

        # Should not raise
        await manager.shutdown(backend)  # type: ignore

    @pytest.mark.asyncio
    async def test_shutdown_handles_sync_shutdown_method(self) -> None:
        """shutdown should handle backends with sync shutdown method."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        manager = BackendLifecycleManager()

        class BackendWithSyncShutdown:
            backend_type = "test"
            shutdown_called = False

            def shutdown(self) -> None:
                self.shutdown_called = True

        backend = BackendWithSyncShutdown()
        await manager.shutdown(backend)  # type: ignore

        assert backend.shutdown_called


class TestDiscardBackend:
    """Test discard method."""

    @pytest.mark.asyncio
    async def test_discard_removes_from_global_cache(self) -> None:
        """discard should remove backend from global cache."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory)  # type: ignore

        await manager.get_or_create("openai")
        assert "openai" in manager._backends

        manager.discard("openai", None, "test reason")

        assert "openai" not in manager._backends
        assert manager.is_disabled("openai")

    @pytest.mark.asyncio
    async def test_discard_removes_per_session_variants(self) -> None:
        """discard without session_id should remove all per-session variants."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=10)  # type: ignore

        await manager.get_or_create("openai", session_id="session-1")
        await manager.get_or_create("openai", session_id="session-2")
        await manager.get_or_create("openai", session_id="session-3")

        assert len(manager._per_session_backends) == 3

        manager.discard("openai", None, "test reason")

        assert len(manager._per_session_backends) == 0

    @pytest.mark.asyncio
    async def test_discard_with_session_id_purges_all_variants(self) -> None:
        """discard with session_id should still purge global and all per-session variants."""
        from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

        factory = MockBackendFactory()
        manager = BackendLifecycleManager(factory=factory, per_session_limit=10)  # type: ignore

        await manager.get_or_create("openai")
        await manager.get_or_create("openai", session_id="session-1")
        await manager.get_or_create("openai", session_id="session-2")

        manager.discard("openai", "session-1", "test reason")

        assert "openai" not in manager._backends
        assert len(manager._per_session_backends) == 0
