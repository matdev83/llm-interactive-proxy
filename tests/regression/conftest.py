"""
Fixtures for regression tests.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.config.app_config import load_config


@pytest.fixture
def test_client():
    """Create a test client with API key authentication disabled."""
    # Set environment variables to disable authentication
    os.environ["DISABLE_AUTH"] = "true"

    # Create a temporary config file
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        config_path = f.name

    # Build the app with authentication disabled
    app_config = load_config(config_path)
    app, _ = build_app(app_config)

    # Create a test client
    client = TestClient(app)

    yield client

    # Clean up
    os.unlink(config_path)
    if "DISABLE_AUTH" in os.environ:
        del os.environ["DISABLE_AUTH"]
