"""
Regression test for qwen-oauth static routing model name override.

This test specifically validates that static routing properly overrides model names
and prevents regression of the issue where the original model name was sent to the API
instead of the static route override.
"""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
]


@pytest.mark.asyncio
async def test_qwen_oauth_static_routing_model_override_regression():
    """
    Regression test to ensure static routing properly overrides model names.

    This test validates that when static routing is configured to override
    gemini-cli-oauth-personal:models/gemini-2.5-pro -> qwen-oauth:qwen3-coder-plus,
    the qwen-oauth connector sends 'qwen3-coder-plus' to the API, not the original model name.
    """
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set up valid credentials
        test_creds = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int((time.time() + 3600) * 1000),
        }

        connector._oauth_credentials = test_creds

        # Mock the parent OpenAIConnector.chat_completions method to capture the call
        with patch(
            "src.connectors.openai.OpenAIConnector.chat_completions",
            new_callable=AsyncMock,
        ) as mock_parent_chat:

            # Create mock response envelope
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Test response"
            mock_response.usage.total_tokens = 10

            from src.core.domain.responses import ResponseEnvelope

            mock_response_envelope = ResponseEnvelope(
                content="Test response", usage=MagicMock(total_tokens=10)
            )
            mock_parent_chat.return_value = mock_response_envelope

            # Create test request data that simulates a client request with original model
            test_request_data = {
                "model": "gemini-cli-oauth-personal:models/gemini-2.5-pro",
                "messages": [{"role": "user", "content": "test message"}],
                "max_tokens": 100,
            }

            # Processed messages (empty for this test)
            processed_messages = []

            # Simulate static routing by calling with the effective_model from static route
            # This is what the backend service does after applying static routing
            effective_model = "qwen3-coder-plus"  # This comes from static routing

            # Call the qwen-oauth connector
            await connector.chat_completions(
                request_data=test_request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
            )

            # Verify the parent method was called
            assert (
                mock_parent_chat.called
            ), "Parent OpenAIConnector.chat_completions should be called"

            # Get the call arguments
            call_args = mock_parent_chat.call_args
            call_kwargs = call_args.kwargs

            # CRITICAL: Verify that effective_model parameter was passed correctly
            assert (
                "effective_model" in call_kwargs
            ), "effective_model should be passed to parent method"
            assert (
                call_kwargs["effective_model"] == "qwen3-coder-plus"
            ), f"Expected effective_model to be 'qwen3-coder-plus', got '{call_kwargs['effective_model']}'"

            # Verify request_data was passed unchanged (not modified)
            assert (
                call_kwargs["request_data"] == test_request_data
            ), "request_data should be passed unchanged to parent method"

            # Verify processed_messages was passed
            assert (
                call_kwargs["processed_messages"] == processed_messages
            ), "processed_messages should be passed to parent method"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_model_name_processing_with_static_routes():
    """
    Test that model name processing works correctly with various static routing scenarios.

    This ensures that different static route patterns are handled correctly.
    """
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set up valid credentials
        test_creds = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int((time.time() + 3600) * 1000),
        }

        connector._oauth_credentials = test_creds

        # Mock the validation method
        with patch.object(
            connector, "_validate_runtime_credentials", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = True

            # Mock the parent OpenAIConnector.chat_completions method
            with patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                new_callable=AsyncMock,
            ) as mock_parent_chat:

                from src.core.domain.responses import ResponseEnvelope

                mock_response_envelope = ResponseEnvelope(
                    content="Test response", usage=MagicMock(total_tokens=10)
                )
                mock_parent_chat.return_value = mock_response_envelope

                # Test various static routing scenarios
                test_cases = [
                    {
                        "original_model": "gemini-cli-oauth-personal:models/gemini-2.5-pro",
                        "static_override": "qwen-oauth:qwen3-coder-plus",
                        "expected_effective_model": "qwen3-coder-plus",
                    },
                    {
                        "original_model": "openai:gpt-4",
                        "static_override": "qwen-oauth:qwen-turbo",
                        "expected_effective_model": "qwen-turbo",
                    },
                    {
                        "original_model": "models/claude-3-sonnet",
                        "static_override": "qwen-oauth:qwen-plus",
                        "expected_effective_model": "qwen-plus",
                    },
                    {
                        "original_model": "any-backend:any-model",
                        "static_override": "qwen-oauth:qwen-max",
                        "expected_effective_model": "qwen-max",
                    },
                ]

                for i, case in enumerate(test_cases):
                    # Reset the mock for each test case
                    mock_parent_chat.reset_mock()

                    test_request_data = ChatRequest(
                        model=case["original_model"],
                        messages=[
                            ChatMessage(role="user", content=f"test message {i}")
                        ],
                        max_tokens=100,
                    )

                    processed_messages = []

                    # Call with the static route override
                    effective_model = case["static_override"].split(":", 1)[
                        1
                    ]  # Extract model part

                    await connector.chat_completions(
                        request_data=test_request_data,
                        processed_messages=processed_messages,
                        effective_model=effective_model,
                    )

                    # Verify the call
                    assert (
                        mock_parent_chat.called
                    ), f"Parent method should be called for case {i}"

                    call_kwargs = mock_parent_chat.call_args.kwargs
                    assert (
                        call_kwargs["effective_model"]
                        == case["expected_effective_model"]
                    ), f"Case {i}: Expected effective_model to be '{case['expected_effective_model']}', got '{call_kwargs['effective_model']}'"

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_prevents_original_model_leakage():
    """
    Test that ensures the original model name from client request doesn't leak to the API.

    This is a critical security/functional test to prevent the regression where
    the original model name was being sent to the API instead of the static route.
    """
    config = AppConfig()
    async_client = httpx.AsyncClient()

    try:
        connector = QwenOAuthConnector(async_client, config)

        # Set up valid credentials
        test_creds = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int((time.time() + 3600) * 1000),
        }

        connector._oauth_credentials = test_creds

        # Mock the parent OpenAIConnector.chat_completions method
        with patch(
            "src.connectors.openai.OpenAIConnector.chat_completions",
            new_callable=AsyncMock,
        ) as mock_parent_chat:

            from src.core.domain.responses import ResponseEnvelope

            mock_response_envelope = ResponseEnvelope(
                content="Test response", usage=MagicMock(total_tokens=10)
            )
            mock_parent_chat.return_value = mock_response_envelope

            # Create a request with a completely different original model
            original_model = "some-other-backend:some-completely-different-model-name"
            static_override_model = "qwen3-coder-plus"

            test_request_data = {
                "model": original_model,
                "messages": [{"role": "user", "content": "test message"}],
                "max_tokens": 100,
            }

            # Call with static routing override
            await connector.chat_completions(
                request_data=test_request_data,
                processed_messages=[],
                effective_model=static_override_model,
            )

            # CRITICAL: Verify the original model doesn't leak through
            call_kwargs = mock_parent_chat.call_args.kwargs

            # The effective_model should be the static override, not the original
            assert (
                call_kwargs["effective_model"] == static_override_model
            ), f"Original model '{original_model}' leaked through! Expected '{static_override_model}'"

            # The request_data should still contain the original model (that's fine,
            # the parent method should override it with effective_model)
            assert call_kwargs["request_data"]["model"] == original_model

            # Most importantly: verify that if we were to inspect what the parent method
            # would send to the API, it would use the effective_model, not the original
            # (This is validated by the OpenAIConnector's _prepare_payload method)

    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_qwen_oauth_static_routing_with_real_credentials():
    """
    Test static routing with real credentials when available.

    This test runs only when real Qwen OAuth credentials are available and
    validates that static routing works with the actual authentication flow.
    """
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"

    if not creds_path.exists():
        pytest.skip("Qwen OAuth credentials not available")

    try:
        with open(creds_path) as f:
            creds = json.load(f)

        if not creds.get("access_token"):
            pytest.skip("No access token in credentials")

        config = AppConfig()
        async_client = httpx.AsyncClient()

        try:
            connector = QwenOAuthConnector(async_client, config)

            # Load real credentials
            creds_loaded = await connector._load_oauth_credentials()
            assert creds_loaded, "Should load real credentials"

            # Mock the HTTP client to capture the actual request
            with patch.object(
                async_client, "post", new_callable=AsyncMock
            ) as mock_post:
                # Mock successful response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Test response"}}],
                    "usage": {"total_tokens": 10},
                }
                mock_response.raise_for_status = MagicMock()
                mock_post.return_value = mock_response

                # Create test request with original model
                test_request_data = ChatRequest(
                    model="gemini-cli-oauth-personal:models/gemini-2.5-pro",
                    messages=[ChatMessage(role="user", content="test")],
                    max_tokens=1,
                )

                # Call with static routing override
                static_override_model = "qwen3-coder-plus"
                await connector.chat_completions(
                    request_data=test_request_data,
                    processed_messages=[],
                    effective_model=static_override_model,
                )

                # Verify the HTTP request was made
                assert mock_post.called, "HTTP POST should be called"

                # Get the request that would be sent to the API
                call_args = mock_post.call_args
                request_url = call_args[0][0]
                request_json = call_args[1]["json"]

                # Verify the URL is correct
                assert "portal.qwen.ai" in request_url, "Should call portal.qwen.ai"
                assert (
                    "/chat/completions" in request_url
                ), "Should call chat/completions endpoint"

                # CRITICAL: Verify the model in the JSON payload is the static override, not original
                assert (
                    request_json["model"] == static_override_model
                ), f"Expected model '{static_override_model}' in API request, got '{request_json['model']}'"

                # Verify the original model is NOT in the API request
                assert "gemini-cli-oauth-personal" not in str(
                    request_json
                ), "Original model should not appear in API request"

        finally:
            await async_client.aclose()

    except Exception as e:
        if "No such file" in str(e):
            pytest.skip("Credentials file not available")
        else:
            raise
