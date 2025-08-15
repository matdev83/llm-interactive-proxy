"""
Pytest configuration for chat completions tests.

This file provides fixtures specific to chat completion tests.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_client: TestClient) -> TestClient:
    """Alias for test_client fixture to match test expectations."""
    return test_client


@pytest.fixture
def app(test_app):
    """Alias for test_app fixture to match test expectations."""
    return test_app