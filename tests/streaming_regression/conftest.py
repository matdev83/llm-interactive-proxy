"""Pytest configuration for streaming regression tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_emulator_state():
    """Reset emulator state between tests."""
    yield
    # Cleanup happens automatically as emulators are recreated per test


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "streaming_regression: marks tests as streaming regression tests"
    )


def count_sse_events(chunks: list[str]) -> int:
    """Count stream events (SSE or JSON) across aggregated chunk buffers."""
    event_count = 0
    for chunk in chunks:
        chunk_events = 0
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            payload = stripped[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            chunk_events += 1
        if chunk_events == 0 and chunk.strip():
            chunk_events = 1
        event_count += chunk_events
    return event_count
