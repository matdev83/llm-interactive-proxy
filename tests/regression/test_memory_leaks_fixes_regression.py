import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.session import Session, SessionState
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
from src.core.services.cbor_wire_capture_service import (
    CborWireCaptureService,
    _RequestTimingState,
)
from src.core.services.connection_activity_tracker import (
    ConnectionActivityTracker,
    ConnectionType,
)
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.model_catalog_updater import ModelCatalogUpdater


class TestMemoryLeaksFixesRegression:

    def test_connection_activity_tracker_max_connections(self):
        tracker = ConnectionActivityTracker()

        # Test max connections logic
        max_conns = 10000

        # Fill it exactly to the max
        for i in range(max_conns):
            activity = MagicMock()
            activity.started_at = time.time()
            tracker._connections[("test_backend", f"session_{i}")] = activity

        with tracker.track_connection(
            "session_new", "test_backend", ConnectionType.STREAMING
        ):
            pass

        # The new one was added, and the oldest one evicted, leaving the total at max_conns (or fewer if stale)
        assert len(tracker._connections) <= max_conns

    def test_endpoint_registry_prunes_health_states(self):
        registry = EndpointRegistry()
        registry.register_backend("backend1", "http://url1.com")

        assert "http://url1.com" in registry._health_states
        registry.unregister_backend("backend1")
        assert "http://url1.com" not in registry._health_states

    @pytest.mark.asyncio
    async def test_in_memory_session_repository_caps(self):
        repo = InMemorySessionRepository()

        user_id = "test_user"
        max_user_sessions = repo._max_sessions_per_user

        for i in range(max_user_sessions + 5):
            s = Session(session_id=f"session_{i}", state=SessionState())
            s.user_id = user_id
            await repo.add(s)

        assert len(repo._user_sessions[user_id]) <= max_user_sessions

    @pytest.mark.asyncio
    async def test_backend_lifecycle_manager_caching(self):
        factory = MagicMock()
        factory.ensure_backend = AsyncMock(return_value=MagicMock())
        manager = BackendLifecycleManager(factory=factory)

        b1 = await manager.get_or_create("backend1", session_id="session1")
        b2 = await manager.get_or_create("backend1", session_id="session1")

        assert b1 is b2
        assert factory.ensure_backend.call_count == 1

        b3 = await manager.get_or_create("backend1", session_id="session2")
        assert b3 is b1

    @pytest.mark.asyncio
    async def test_cbor_wire_capture_cleanup(self):
        config = MagicMock()
        service = CborWireCaptureService(config=config)
        service._enabled = True

        # Insert a stale entry
        old_time = time.time() - 600 - 10  # > _REQUEST_TIMING_TTL_SECONDS
        service._request_timings["old_req"] = _RequestTimingState(old_time)

        # Insert a new entry
        service._request_timings["new_req"] = _RequestTimingState(time.time())

        ctx = MagicMock()
        ctx.request_id = "new_req2"
        ctx.b2bua_identity = None

        with patch.object(service, "_buffer_entry", AsyncMock()):
            await service.capture_outbound_request(
                context=ctx,
                session_id="sess1",
                backend="b1",
                model="m1",
                key_name=None,
                request_payload={},
            )

        assert "old_req" not in service._request_timings
        assert "new_req" in service._request_timings
        assert "new_req2" in service._request_timings

    @pytest.mark.asyncio
    async def test_model_catalog_updater_close(self):
        config = MagicMock()
        catalog_service = MagicMock()
        updater = ModelCatalogUpdater(config=config, catalog_service=catalog_service)
        updater._http_client = AsyncMock()
        # Create a real task so it can be cleanly cancelled and awaited
        updater._task = asyncio.create_task(asyncio.sleep(10))
        await updater.stop()
        updater._http_client.aclose.assert_called_once()
