import os
from typing import Any

import pytest


def pytest_configure(config: Any) -> None:
    """Register the live marker."""
    config.addinivalue_line(
        "markers", "live: mark test as a live test requiring real API keys"
    )


def pytest_collection_modifyitems(config: Any, items: list[pytest.Item]) -> None:
    """Skip live tests if LIVE_TESTS_ENABLED is not set."""
    if os.getenv("LIVE_TESTS_ENABLED", "false").lower() != "true":
        skip_live = pytest.mark.skip(
            reason="LIVE_TESTS_ENABLED environment variable not set to true"
        )
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
            # Also skip if it's in the tests/live directory
            if "tests/live" in str(item.fspath).replace("\\", "/"):
                item.add_marker(skip_live)


@pytest.fixture(scope="session")
def live_openai_key() -> str | None:
    """Return OpenAI API key if available, else skip."""
    # Check base key first, then numbered variant
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        key = os.getenv("OPENAI_API_KEY_1")
    return key if key else None


@pytest.fixture(scope="session")
def live_anthropic_key() -> str | None:
    """Return Anthropic API key if available, else skip."""
    # Check base key first, then numbered variant
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        key = os.getenv("ANTHROPIC_API_KEY_1")
    return key if key else None


@pytest.fixture(scope="session")
def live_gemini_key() -> str | None:
    """Return Gemini API key if available, else skip."""
    # Check base key first, then numbered variant
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        key = os.getenv("GEMINI_API_KEY_1")
    return key if key else None


@pytest.fixture
def require_openai(live_openai_key: str | None) -> str:
    if not live_openai_key:
        pytest.skip("OPENAI_API_KEY or OPENAI_API_KEY_1 not set")
    return live_openai_key


@pytest.fixture
def require_anthropic(live_anthropic_key: str | None) -> str:
    if not live_anthropic_key:
        pytest.skip("ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_1 not set")
    return live_anthropic_key


@pytest.fixture
def require_gemini(live_gemini_key: str | None) -> str:
    if not live_gemini_key:
        pytest.skip("GEMINI_API_KEY or GEMINI_API_KEY_1 not set")
    return live_gemini_key
