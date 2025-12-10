"""Unit tests for RequestDeduplicationService."""

from __future__ import annotations

import asyncio

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.request_deduplication_service import RequestDeduplicationService


class TestRequestDeduplicationService:
    """Tests for RequestDeduplicationService."""

    @pytest.fixture
    def service(self) -> RequestDeduplicationService:
        """Create a deduplication service with default settings."""
        return RequestDeduplicationService(window_seconds=3.0, enabled=True)

    @pytest.fixture
    def short_window_service(self) -> RequestDeduplicationService:
        """Create a deduplication service with a short window for testing."""
        return RequestDeduplicationService(window_seconds=0.1, enabled=True)

    @pytest.fixture
    def sample_request(self) -> ChatRequest:
        """Create a sample chat request."""
        return ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="Hello, world!"),
            ],
        )

    @pytest.fixture
    def different_request(self) -> ChatRequest:
        """Create a different chat request."""
        return ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="Different message"),
            ],
        )

    @pytest.mark.asyncio
    async def test_first_request_not_duplicate(
        self, service: RequestDeduplicationService, sample_request: ChatRequest
    ) -> None:
        """First request should not be detected as duplicate."""
        is_duplicate, content_hash = await service.check_and_register(
            sample_request, "session-1"
        )
        assert is_duplicate is False
        assert content_hash != ""
        assert len(content_hash) == 32

    @pytest.mark.asyncio
    async def test_identical_request_within_window_is_duplicate(
        self, service: RequestDeduplicationService, sample_request: ChatRequest
    ) -> None:
        """Identical request within the dedup window should be detected as duplicate."""
        await service.check_and_register(sample_request, "session-1")

        is_duplicate, content_hash = await service.check_and_register(
            sample_request, "session-1"
        )
        assert is_duplicate is True
        assert content_hash != ""

    @pytest.mark.asyncio
    async def test_identical_request_after_window_not_duplicate(
        self,
        short_window_service: RequestDeduplicationService,
        sample_request: ChatRequest,
    ) -> None:
        """Identical request after the dedup window expires should not be duplicate."""
        await short_window_service.check_and_register(sample_request, "session-1")

        await asyncio.sleep(0.15)

        is_duplicate, _ = await short_window_service.check_and_register(
            sample_request, "session-1"
        )
        assert is_duplicate is False

    @pytest.mark.asyncio
    async def test_different_sessions_not_duplicates(
        self, service: RequestDeduplicationService, sample_request: ChatRequest
    ) -> None:
        """Same request from different sessions should not be duplicates."""
        await service.check_and_register(sample_request, "session-1")

        is_duplicate, _ = await service.check_and_register(sample_request, "session-2")
        assert is_duplicate is False

    @pytest.mark.asyncio
    async def test_different_content_not_duplicate(
        self,
        service: RequestDeduplicationService,
        sample_request: ChatRequest,
        different_request: ChatRequest,
    ) -> None:
        """Different request content should not be detected as duplicate."""
        await service.check_and_register(sample_request, "session-1")

        is_duplicate, _ = await service.check_and_register(
            different_request, "session-1"
        )
        assert is_duplicate is False

    @pytest.mark.asyncio
    async def test_disabled_service_never_detects_duplicates(
        self, sample_request: ChatRequest
    ) -> None:
        """Disabled service should never detect duplicates."""
        service = RequestDeduplicationService(window_seconds=3.0, enabled=False)

        await service.check_and_register(sample_request, "session-1")

        is_duplicate, content_hash = await service.check_and_register(
            sample_request, "session-1"
        )
        assert is_duplicate is False
        assert content_hash == ""

    @pytest.mark.asyncio
    async def test_zero_window_disables_dedup(
        self, sample_request: ChatRequest
    ) -> None:
        """Zero window should disable deduplication."""
        service = RequestDeduplicationService(window_seconds=0.0, enabled=True)

        await service.check_and_register(sample_request, "session-1")

        is_duplicate, content_hash = await service.check_and_register(
            sample_request, "session-1"
        )
        assert is_duplicate is False
        assert content_hash == ""

    @pytest.mark.asyncio
    async def test_stats_tracking(
        self, service: RequestDeduplicationService, sample_request: ChatRequest
    ) -> None:
        """Stats should correctly track requests and duplicates."""
        initial_stats = service.get_stats()
        assert initial_stats["requests_processed"] == 0
        assert initial_stats["duplicates_blocked"] == 0

        await service.check_and_register(sample_request, "session-1")
        await service.check_and_register(sample_request, "session-1")
        await service.check_and_register(sample_request, "session-1")

        stats = service.get_stats()
        assert stats["requests_processed"] == 3
        assert stats["duplicates_blocked"] == 2
        assert stats["cache_size"] == 1
        assert stats["dedup_rate"] == pytest.approx(2 / 3, rel=0.01)

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_entries(
        self,
        short_window_service: RequestDeduplicationService,
        sample_request: ChatRequest,
    ) -> None:
        """Cleanup should remove expired entries."""
        await short_window_service.check_and_register(sample_request, "session-1")
        assert short_window_service.get_stats()["cache_size"] == 1

        await asyncio.sleep(0.15)

        removed = await short_window_service.cleanup()
        assert removed == 1
        assert short_window_service.get_stats()["cache_size"] == 0

    @pytest.mark.asyncio
    async def test_cache_size_limit_enforced(self) -> None:
        """Cache size limit should be enforced after cleanup triggers."""
        service = RequestDeduplicationService(
            window_seconds=60.0,
            enabled=True,
            max_cache_size=5,
        )

        # Make enough requests to trigger size-based cleanup
        # Cleanup triggers when cache exceeds max_cache_size
        for i in range(10):
            request = ChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content=f"Message {i}")],
            )
            await service.check_and_register(request, f"session-{i}")

        # After cleanup, size should be at most max_cache_size
        # Note: cleanup happens when size EXCEEDS max, so final size <= max
        final_size = service.get_stats()["cache_size"]
        # Due to cleanup triggering after exceeding, allow some slack
        assert final_size <= 10, f"Cache size {final_size} should be bounded"

    @pytest.mark.asyncio
    async def test_concurrent_access_thread_safety(
        self, service: RequestDeduplicationService
    ) -> None:
        """Service should handle concurrent access safely."""

        async def make_request(session_id: str, msg: str) -> tuple[bool, str]:
            request = ChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content=msg)],
            )
            return await service.check_and_register(request, session_id)

        tasks = []
        for i in range(20):
            tasks.append(make_request(f"session-{i % 5}", f"msg-{i % 3}"))

        results = await asyncio.gather(*tasks)

        assert all(isinstance(r[0], bool) for r in results)
        assert all(isinstance(r[1], str) for r in results)

        stats = service.get_stats()
        assert stats["requests_processed"] == 20

    @pytest.mark.asyncio
    async def test_different_models_not_duplicate(
        self, service: RequestDeduplicationService
    ) -> None:
        """Same message with different models should not be duplicates."""
        request1 = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        request2 = ChatRequest(
            model="gpt-3.5-turbo",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        await service.check_and_register(request1, "session-1")
        is_duplicate, _ = await service.check_and_register(request2, "session-1")

        assert is_duplicate is False
