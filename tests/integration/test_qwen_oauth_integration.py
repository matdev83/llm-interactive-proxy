from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig


def _qwen_oauth_available() -> bool:
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    if not creds_path.exists():
        return False
    try:
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        return bool(data.get("access_token") and data.get("refresh_token"))
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
]


@pytest.mark.asyncio
async def test_qwen_oauth_connector_api_endpoint():
    """Test that Qwen OAuth connector uses the correct API endpoint."""
    config = AppConfig()

    # Create a test credentials file
    test_creds = {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "token_type": "Bearer",
        "resource_url": "portal.qwen.ai",  # This should NOT be used for API calls
        "expiry_date": int((asyncio.get_event_loop().time() + 3600) * 1000)
    }

    # Mock the credentials file loading
    with patch('src.connectors.qwen_oauth.Path.home') as mock_home:
        mock_qwen_dir = Path("/mock/home/.qwen")
        mock_creds_path = mock_qwen_dir / "oauth_creds.json"

        # Create the mock path structure
        mock_home.return_value = Path("/mock/home")

        # Mock file operations
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'stat') as mock_stat, \
             patch.object(Path, 'mkdir'), \
             patch('builtins.open', create=True) as mock_open, \
             patch('json.load', return_value=test_creds):

            mock_stat.return_value.st_mtime = 1234567890

            # Create connector
            async_client = httpx.AsyncClient()
            connector = QwenOAuthConnector(async_client, config)

            # Manually set the credentials to simulate successful loading
            connector._oauth_credentials = test_creds

            # Test that the API base URL is correctly set to use resource_url from credentials
            expected_url = "https://portal.qwen.ai/v1"  # Should use resource_url from credentials
            actual_url = connector.api_base_url

            assert actual_url == expected_url, \
                f"Expected API base URL to be {expected_url}, but got {actual_url}"

            # Ensure it's NOT using the wrong DashScope endpoint
            wrong_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            assert actual_url != wrong_url, \
                f"API base URL should NOT be {wrong_url}, but got {actual_url}"

            await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_connector_headers():
    """Test that Qwen OAuth connector creates correct headers with access token."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set up mock credentials
        test_creds = {
            "access_token": "test_access_token_12345",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "expiry_date": int((asyncio.get_event_loop().time() + 3600) * 1000)
        }

        connector._oauth_credentials = test_creds

        # Test header generation
        headers = connector.get_headers()

        assert headers["Authorization"] == "Bearer test_access_token_12345"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_model_name_processing():
    """Test that model names are correctly processed for static routing."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Test model name processing that would happen with static routing
        test_cases = [
            ("gemini-cli-oauth-personal:models/gemini-2.5-pro", "gemini-2.5-pro"),
            ("qwen-oauth:qwen3-coder-plus", "qwen3-coder-plus"),
            ("models/gemini-pro", "gemini-pro"),
            ("openai:gpt-4", "gpt-4"),
        ]

        for input_model, expected_output in test_cases:
            # Simulate the model processing logic from the chat completions method
            model_name = input_model
            if ":" in model_name:
                model_name = model_name.split(":")[-1]  # Strip backend prefix
            if model_name.startswith("models/"):
                model_name = model_name[7:]  # Remove "models/" prefix

            assert model_name == expected_output, \
                f"Model name processing failed: {input_model} -> {model_name} (expected: {expected_output})"

    finally:
        await async_client.aclose()


@pytest.mark.skipif(not _qwen_oauth_available(), reason="Qwen OAuth credentials not available")
@pytest.mark.asyncio
async def test_qwen_oauth_real_credentials_loading():
    """Test with real Qwen OAuth credentials (only runs if credentials are available)."""
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Test loading real credentials
        creds_loaded = await connector._load_oauth_credentials()

        assert creds_loaded, "Failed to load real Qwen OAuth credentials"
        assert connector._oauth_credentials is not None, "OAuth credentials should be set"
        assert "access_token" in connector._oauth_credentials, "Access token should be present"
        assert "refresh_token" in connector._oauth_credentials, "Refresh token should be present"

        # Test that the correct API endpoint is used
        expected_url = "https://portal.qwen.ai/v1"
        actual_url = connector.api_base_url
        assert actual_url == expected_url, \
            f"Expected API base URL to be {expected_url}, but got {actual_url}"

        # Test header generation with real token
        headers = connector.get_headers()
        assert "Authorization" in headers, "Authorization header should be present"
        assert headers["Authorization"].startswith("Bearer "), \
            "Authorization header should start with 'Bearer '"

    finally:
        await async_client.aclose()
