from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from src.core.common.exceptions import LLMProxyError, SessionCancelledError
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import RequestContext
from src.core.domain.session_key import SessionKey
from src.core.services.backend_work_guard import BackendWorkGuard
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)


def _request_context(*, request_id: str | None = None) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id=request_id,
    )


class TestBackendWorkGuard:
    def test_ensure_session_active_allows_active_scoped_session(self) -> None:
        coordinator = SessionCancellationCoordinator(ttl_seconds=3600)
        guard = BackendWorkGuard(cancellation_coordinator=coordinator)

        session_key = guard.ensure_session_active(
            context=_request_context(request_id="req-active"),
            purpose="primary_completion",
        )

        assert session_key is not None
        assert session_key.primary_id == "req-active"

    def test_ensure_session_active_raises_when_session_cancelled(self) -> None:
        coordinator = SessionCancellationCoordinator(ttl_seconds=3600)
        guard = BackendWorkGuard(cancellation_coordinator=coordinator)
        key = SessionKey(protocol="http", primary_id="req-cancelled")
        coordinator.cancel_session(key, ClientTerminationReason.CLIENT_DISCONNECTED)

        with pytest.raises(SessionCancelledError):
            guard.ensure_session_active(
                context=_request_context(request_id="req-cancelled"),
                purpose="primary_completion",
            )

    def test_ensure_session_active_enforces_scope_when_required(self) -> None:
        guard = BackendWorkGuard(cancellation_coordinator=None, strict_http_scope=True)

        with pytest.raises(LLMProxyError):
            guard.ensure_session_active(
                context=_request_context(request_id=None),
                purpose="quality_verifier",
                require_scope=True,
            )

    def test_ensure_session_active_allows_missing_scope_when_not_required(self) -> None:
        guard = BackendWorkGuard(cancellation_coordinator=None, strict_http_scope=True)

        session_key = guard.ensure_session_active(
            context=_request_context(request_id=None),
            purpose="quality_verifier",
            require_scope=False,
        )

        assert session_key is None

    @pytest.mark.asyncio
    async def test_wrap_stream_with_cancellation_stops_before_first_chunk(self) -> None:
        coordinator = SessionCancellationCoordinator(ttl_seconds=3600)
        guard = BackendWorkGuard(cancellation_coordinator=coordinator)
        session_key = SessionKey(protocol="http", primary_id="req-pre-cancel")
        coordinator.cancel_session(
            session_key, ClientTerminationReason.CLIENT_DISCONNECTED
        )

        async def _source() -> AsyncIterator[str]:
            yield "first"
            yield "second"

        wrapped = guard.wrap_stream_with_cancellation(
            stream=_source(),
            session_key=session_key,
            purpose="primary_completion",
        )

        items = [item async for item in wrapped]
        assert items == []

    @pytest.mark.asyncio
    async def test_wrap_stream_with_cancellation_stops_mid_stream(self) -> None:
        coordinator = SessionCancellationCoordinator(ttl_seconds=3600)
        guard = BackendWorkGuard(cancellation_coordinator=coordinator)
        session_key = SessionKey(protocol="http", primary_id="req-mid-cancel")

        async def _source() -> AsyncIterator[str]:
            yield "first"
            coordinator.cancel_session(
                session_key, ClientTerminationReason.CLIENT_DISCONNECTED
            )
            yield "second"

        wrapped = guard.wrap_stream_with_cancellation(
            stream=_source(),
            session_key=session_key,
            purpose="empty_stream_retry",
        )

        items = [item async for item in wrapped]
        assert items == ["first"]
