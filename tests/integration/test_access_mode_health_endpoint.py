"""Integration tests for access mode in health endpoint.

Tests that the /internal/health endpoint includes the current access mode
in its response.

Requirements validated:
- 10.3: WHEN querying the health endpoint THEN the system SHALL include
  the access mode in the response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_builder import build_app_async
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.notification import NotificationConfig


@pytest.fixture
async def single_user_app():
    """Create FastAPI app with Single User Mode configuration."""
    cfg = AppConfig(
        host="127.0.0.1",
        port=8000,
        access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
        auth=AuthConfig(disable_auth=True),
        notifications=NotificationConfig(enabled=None),
    )
    app = await build_app_async(cfg)
    app.state.app_config = cfg
    return app


@pytest.fixture
async def multi_user_app():
    """Create FastAPI app with Multi User Mode configuration."""
    cfg = AppConfig(
        host="127.0.0.1",
        port=8000,
        access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
        auth=AuthConfig(disable_auth=True),
        notifications=NotificationConfig(enabled=None),
    )
    app = await build_app_async(cfg)
    app.state.app_config = cfg
    return app


@pytest.mark.asyncio
async def test_health_endpoint_includes_access_mode_single_user(single_user_app):
    """Test health endpoint includes access_mode field for Single User Mode.

    Requirement 10.3: WHEN querying the health endpoint THEN the system SHALL
    include the access mode in the response.
    """
    client = TestClient(single_user_app)
    response = client.get("/internal/health")

    assert response.status_code == 200
    data = response.json()

    # Assert access_mode field exists
    assert "access_mode" in data, "access_mode field missing from health response"

    # Assert value is correct
    assert (
        data["access_mode"] == "single_user"
    ), f"Expected 'single_user', got '{data.get('access_mode')}'"


@pytest.mark.asyncio
async def test_health_endpoint_includes_access_mode_multi_user(multi_user_app):
    """Test health endpoint includes access_mode field for Multi User Mode.

    Requirement 10.3: WHEN querying the health endpoint THEN the system SHALL
    include the access mode in the response.
    """
    client = TestClient(multi_user_app)
    response = client.get("/internal/health")

    assert response.status_code == 200
    data = response.json()

    # Assert access_mode field exists
    assert "access_mode" in data, "access_mode field missing from health response"

    # Assert value is correct
    assert (
        data["access_mode"] == "multi_user"
    ), f"Expected 'multi_user', got '{data.get('access_mode')}'"


@pytest.mark.asyncio
async def test_health_endpoint_default_access_mode():
    """Test health endpoint shows default access mode when not explicitly set.

    Requirement 1.1: WHEN the proxy starts without an explicit access mode flag
    THEN the system SHALL default to Single User Mode.
    Requirement 10.3: WHEN querying the health endpoint THEN the system SHALL
    include the access mode in the response.
    """
    # Create config without explicitly setting access_mode (should default to SINGLE_USER)
    cfg = AppConfig(
        host="127.0.0.1",
        port=8000,
        auth=AuthConfig(disable_auth=True),
        notifications=NotificationConfig(enabled=None),
    )
    app = await build_app_async(cfg)
    app.state.app_config = cfg

    client = TestClient(app)
    response = client.get("/internal/health")

    assert response.status_code == 200
    data = response.json()

    # Assert access_mode field exists
    assert "access_mode" in data, "access_mode field missing from health response"

    # Assert default value is single_user
    assert (
        data["access_mode"] == "single_user"
    ), f"Expected default 'single_user', got '{data.get('access_mode')}'"
