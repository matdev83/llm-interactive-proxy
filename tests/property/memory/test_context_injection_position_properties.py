"""Property-based tests for context injection position.

Feature: proxy-mem
Property: 8
Validates: Requirements 11.2 - Context injection position
"""

from __future__ import annotations

from typing import cast

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.chat import ChatMessage
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.injection_middleware import ContextInjectionMiddleware
from tests.utils.hypothesis_config import property_test_settings


class _StubMemoryService:
    def is_available(self) -> bool:
        return True


class _StubContextInjector:
    pass


@given(
    system_count=st.integers(min_value=0, max_value=4),
    user_content=st.text(min_size=1, max_size=50),
    assistant_count=st.integers(min_value=0, max_value=3),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_8_context_injected_after_system_before_user(
    system_count: int,
    user_content: str,
    assistant_count: int,
) -> None:
    """Context is inserted after system messages and before first user."""
    messages: list[ChatMessage] = []
    for i in range(system_count):
        messages.append(ChatMessage(role="system", content=f"sys-{i}"))

    messages.append(ChatMessage(role="user", content=user_content))

    for i in range(assistant_count):
        messages.append(ChatMessage(role="assistant", content=f"asst-{i}"))

    middleware = ContextInjectionMiddleware(
        memory_service=cast(IMemoryService, _StubMemoryService()),
        context_injector=cast(ContextInjector, _StubContextInjector()),
        config=MemoryConfiguration(),
    )

    injected = middleware._inject_into_messages(messages, "context")

    inserted_index = next(
        i
        for i, msg in enumerate(injected)
        if isinstance(msg.content, str)
        and msg.content.startswith("[Prior Session Context]")
    )

    expected_index = system_count
    assert inserted_index == expected_index
    assert len(injected) == len(messages) + 1
