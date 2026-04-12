"""Pytest fixtures shared by tests under ``tests/unit/core``."""

import pytest

from tests.unit.core.test_doubles import MockSessionService


@pytest.fixture
def session_service() -> MockSessionService:
    return MockSessionService()
