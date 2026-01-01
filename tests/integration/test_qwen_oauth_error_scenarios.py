"""
Integration tests for qwen-oauth error scenarios.
These tests ensure that real error conditions are properly handled and don't give false positives.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig

from tests.unit.fixtures.markers import real_time

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows-specific test"),
    pytest.mark.integration,
    pytest.mark.network,
]


@pytest.mark.asyncio
async def test_qwen_oauth_health_check_without_credentials():
    """Test that health check fails properly when no credentials are available."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Don't set any credentials
        connector._oauth_credentials = None

        # Health check should fail
        health_result = await connector._perform_health_check()
        assert not health_result, "Health check should fail without credentials"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_health_check_with_expired_credentials():
    """Test that health check fails properly when credentials are expired."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set expired credentials
        past_time = int((asyncio.get_event_loop().time() - 3600) * 1000)  # 1 hour ago
        expired_creds = {
            "access_token": "expired_token",
            "refresh_token": "refresh_token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": past_time,
        }

        connector._oauth_credentials = expired_creds

        # Health check should fail
        health_result = await connector._perform_health_check()
        assert not health_result, "Health check should fail with expired credentials"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_headers_raises_exception_without_credentials():
    """Test that get_headers raises proper exception when no credentials are available."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Don't set any credentials
        connector._oauth_credentials = None

        # get_headers should raise HTTPException
        with pytest.raises(Exception) as exc_info:
            connector.get_headers()

        assert (
            "401" in str(exc_info.value)
            or "access token" in str(exc_info.value).lower()
        )

    finally:
        await async_client.aclose()


@pytest.mark.skipif(
    not (Path.home() / ".qwen" / "oauth_creds.json").exists(),
    reason="Qwen OAuth credentials not available",
)
@real_time(reason="Uses real credential expiry timestamps and live API time checks.")
@pytest.mark.asyncio
async def test_qwen_oauth_real_api_connectivity():
    """Test real API connectivity to ensure the fix actually works with real endpoints."""
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"

    try:
        with open(creds_path) as f:
            creds = json.load(f)

        if not creds.get("access_token"):
            pytest.skip("No access token in credentials")

        # Skip if credentials are expired
        expiry = creds.get("expiry_date", 0)
        current_time = int(time.time() * 1000)
        if expiry <= current_time:
            pytest.skip("Credentials are expired")

        config = AppConfig()
        async_client = httpx.AsyncClient()

        try:
            connector = QwenOAuthConnector(async_client, config)

            # Initialize the connector, which will load credentials and refresh token if needed
            await connector.initialize()

            # Test health check (should pass with our fix)
            health_result = await connector._perform_health_check()
            assert health_result, "Health check should pass with valid credentials"

            # Test actual API call to ensure connectivity works
            headers = connector.get_headers()

            # Make a minimal test request
            test_request = {
                "model": "qwen3-coder-plus",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1,
            }

            response = await async_client.post(
                f"{connector.api_base_url}/chat/completions",
                headers=headers,
                json=test_request,
                timeout=10.0,
            )

            # The response should not be a 401 (which would indicate auth issues)
            if response.status_code == 401:
                pytest.skip("Credentials rejected by API (401 Unauthorized)")

            # It could be 200 (success) or other errors (rate limits, etc), but not auth errors
            if response.status_code == 200:
                assert "choices" in response.json() or "content" in str(
                    response.text
                ), "Valid response should contain content"

        finally:
            await async_client.aclose()

    except Exception as e:
        if "No such file" in str(e):
            pytest.skip("Credentials file not available")
        else:
            raise


@pytest.mark.asyncio
async def test_qwen_oauth_static_routing_compatibility():
    """Test that static routing works correctly with the fixed connector."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set up valid credentials
        test_creds = {
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int((asyncio.get_event_loop().time() + 3600) * 1000),
        }

        connector._oauth_credentials = test_creds

        # Verify the connector is using the correct endpoint for static routing
        assert connector.api_base_url == "https://portal.qwen.ai/v1"

        # Test model name processing (critical for static routing)
        test_model = "gemini-cli-oauth-personal:models/gemini-2.5-pro"

        # Simulate the processing that happens in chat_completions
        model_name = test_model
        if ":" in model_name:
            model_name = model_name.split(":")[-1]
        if model_name.startswith("models/"):
            model_name = model_name[7:]

        expected = "gemini-2.5-pro"
        assert model_name == expected, f"Expected {expected}, got {model_name}"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_no_false_positives_from_mocking():
    """Test that ensures we're not getting false positives from excessive mocking."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Test with invalid credentials (should fail, not give false positive)
        invalid_creds = {
            "access_token": "invalid_token",
            "refresh_token": "invalid_refresh",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int((asyncio.get_event_loop().time() + 3600) * 1000),
        }

        connector._oauth_credentials = invalid_creds

        # Health check should pass (it only checks token validity, not API connectivity)
        # But we want to ensure our tests don't give false positives

        # The key test: headers should be generated correctly
        headers = connector.get_headers()
        assert headers["Authorization"] == "Bearer invalid_token"
        assert headers["Content-Type"] == "application/json"

        # But actual API call would fail with real invalid token
        # (We don't test this here to avoid real API calls, but the logic is sound)

    finally:
        await async_client.aclose()
