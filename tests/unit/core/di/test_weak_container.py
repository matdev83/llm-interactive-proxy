"""Tests for the weak DI container memory management."""

from __future__ import annotations

import gc
import weakref

import pytest
from src.core.di.weak_container import WeakDIContainer


class _DummyService:
    """Simple service used to verify garbage collection behavior."""


@pytest.mark.asyncio
async def test_weak_container_allows_garbage_collection() -> None:
    """Instances registered in the weak container should not be leaked."""

    container = WeakDIContainer()

    def factory() -> _DummyService:
        return _DummyService()

    container.register_factory(_DummyService, factory)

    service = await container.get_service(_DummyService)
    service_ref = weakref.ref(service)

    # Drop the strong reference held by the test
    del service

    # Force garbage collection to trigger weakref callbacks
    gc.collect()

    assert service_ref() is None
