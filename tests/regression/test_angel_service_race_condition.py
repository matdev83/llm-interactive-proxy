"""Regression tests for angel_service.py race condition fix."""

import threading
import pytest

from src.core.services.angel_service import (
    get_prompt_loader,
    AngelService,
)
from src.core.services.angel_prompt_loader import AngelPromptLoader


def test_get_prompt_loader_lock_exists():
    """Test that lock for protecting prompt loader exists."""
    from src.core.services import angel_service
    assert hasattr(angel_service, "_prompt_loader_lock")
    assert angel_service._prompt_loader_lock is not None


def test_get_prompt_loader_returns_same_instance():
    """Test that multiple calls return the same instance."""
    loader1 = get_prompt_loader()
    loader2 = get_prompt_loader()
    loader3 = get_prompt_loader()

    assert id(loader1) == id(loader2) == id(loader3)


def test_get_prompt_loader_thread_safety():
    """Test that get_prompt_loader is thread-safe."""
    results = []

    def call_get_loader(thread_id: int):
        loader = get_prompt_loader()
        results.append((thread_id, id(loader)))

    threads = []
    for i in range(50):
        t = threading.Thread(target=call_get_loader, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    loader_ids = [loader_id for _, loader_id in results]
    assert len(set(loader_ids)) == 1, "All threads should get the same loader instance"


def test_angel_service_uses_get_prompt_loader():
    """Test that AngelService correctly uses get_prompt_loader."""
    service = AngelService("test_model")
    assert hasattr(service, "build_verification_messages")
    assert hasattr(service, "build_steering_payload")

    loader = get_prompt_loader()
    assert loader is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
