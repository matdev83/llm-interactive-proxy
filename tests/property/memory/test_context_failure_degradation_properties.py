"""Property-based tests for graceful context injection failure.

Feature: proxy-mem
Property: 10
Validates: Requirements 11.6 - Graceful degradation on context failure
"""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.injection_middleware import ContextInjectionMiddleware
from tests.utils.hypothesis_config import property_test_settings


class _StubMemoryService:
    def is_available(self) -> bool:
        return True

    async def is_enabled_for_session(self, session_id: str) -> bool:
        return True

    async def get_session_user_id(self, session_id: str) -> str | None:
        return "user-1"

    async def get_session_project_root(self, session_id: str) -> str | None:
        return "/project"

    async def get_session_state(self, session_id: str) -> object | None:
        return None


class _FailingContextInjector:
    async def get_context_for_session(
        self, *args: object, **kwargs: object
    ) -> str | None:
        raise RuntimeError("boom")

    def format_context_for_injection(self, context: str | None) -> str:
        return "unused"


@given(user_content=st.text(min_size=1, max_size=100))
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_10_context_failure_returns_original_request(
    user_content: str,
) -> None:
    """Context injection failures should not mutate the request."""
    request = ChatRequest(
        model="test",
        messages=[ChatMessage(role="user", content=user_content)],
    )
    middleware = ContextInjectionMiddleware(
        memory_service=cast(IMemoryService, _StubMemoryService()),
        context_injector=cast(ContextInjector, _FailingContextInjector()),
        config=MemoryConfiguration(require_project_discovery=False),
    )

    result = await middleware.maybe_inject_context("sess-1", request)
    assert result.messages == request.messages
