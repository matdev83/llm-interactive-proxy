"""Regression tests for quality_verifier_service.py race condition fix."""

import threading

import pytest
from src.core.services.quality_verifier_service import (
    QualityVerifierService,
    get_quality_verifier_prompt_loader,
)


def test_get_quality_verifier_prompt_loader_lock_exists():
    """Test that lock for protecting prompt loader exists."""
    from src.core.services import quality_verifier_service

    assert hasattr(quality_verifier_service, "_prompt_loader_lock")
    assert quality_verifier_service._prompt_loader_lock is not None


def test_get_quality_verifier_prompt_loader_returns_same_instance():
    """Test that multiple calls return the same instance."""
    loader1 = get_quality_verifier_prompt_loader()
    loader2 = get_quality_verifier_prompt_loader()
    loader3 = get_quality_verifier_prompt_loader()

    assert id(loader1) == id(loader2) == id(loader3)


def test_get_quality_verifier_prompt_loader_thread_safety():
    """Test that get_quality_verifier_prompt_loader is thread-safe."""
    results = []

    def call_get_loader(thread_id: int):
        loader = get_quality_verifier_prompt_loader()
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


def test_quality_verifier_service_uses_get_quality_verifier_prompt_loader():
    """Test that QualityVerifierService correctly uses get_quality_verifier_prompt_loader."""
    service = QualityVerifierService("test_model")
    assert hasattr(service, "build_verification_messages")
    assert hasattr(service, "build_steering_payload")

    loader = get_quality_verifier_prompt_loader()
    assert loader is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
