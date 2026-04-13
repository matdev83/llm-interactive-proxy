"""Local fixtures for chat_completions_tests (narrower scope than root conftest)."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def test_client() -> Generator[TestClient, None, None]:
    """Single app/client for the module — avoids repeated full build_test_app() setup."""
    from src.core.app.test_builder import build_test_app

    previous = os.environ.get("DISABLE_AUTH")
    os.environ["DISABLE_AUTH"] = "true"
    app = build_test_app()
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        yield client
    if previous is None:
        os.environ.pop("DISABLE_AUTH", None)
    else:
        os.environ["DISABLE_AUTH"] = previous
