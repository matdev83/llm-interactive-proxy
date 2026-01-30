"""Regression tests for Opencode Zen model name handling and retry logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from src.connectors.opencode_zen import OpencodeZenConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest


@pytest.fixture
def http_client():
    """Mock HTTP client."""
    client = AsyncMock()
    return client


@pytest.fixture
def config():
    """App config."""
    return AppConfig()


@pytest.fixture
def connector(http_client, config):
    """OpencodeZenConnector instance."""
    conn = OpencodeZenConnector(http_client, config)
    conn._enable_opencode_zen_backend_debugging_override = True
    conn.is_functional = True
    conn._oauth_credentials = {"access": "valid_token", "type": "oauth", "expires": 9999999999}
    return conn


@pytest.mark.asyncio
async def test_denormalize_model_name_strips_vendor_prefix(connector):
    """Regression test for stripping vendor prefixes from model names."""
    # Test cases: (input_model, expected_output)
    test_cases = [
        ("kimi/kimi-k2.5-free", "kimi-k2.5-free"),
        ("anthropic/claude-3-opus", "claude-3-opus"),
        ("openai/gpt-4o", "gpt-4o"),
        ("google/gemini-1.5-pro", "gemini-1.5-pro"),
        ("custom/vendor/model", "model"),  # Should strip all but the last part
        ("no-prefix-model", "no-prefix-model"),
    ]

    for input_model, expected in test_cases:
        assert connector._denormalize_model_name(input_model) == expected


@pytest.mark.asyncio
async def test_chat_completions_retries_on_401(connector):
    """Regression test for retry logic on 401 Unauthorized in chat_completions."""
    # Mock chat_completions of parent OpenAIConnector
    # First call fails with 401, second succeeds
    with patch("src.connectors.openai.OpenAIConnector.chat_completions") as mock_parent_chat:
        mock_parent_chat.side_effect = [
            HTTPException(status_code=401, detail="Unauthorized"),
            MagicMock(spec=object)  # Mocked successful response
        ]

        # Mock credential reloading
        connector._load_oauth_credentials = AsyncMock(return_value=True)

        await connector.chat_completions(
            request_data={"model": "kimi/kimi-k2.5-free"},
            processed_messages=[],
            effective_model="opencode-zen/kimi/kimi-k2.5-free"
        )

        # Verify parent was called twice
        assert mock_parent_chat.call_count == 2
        # Verify credentials were reloaded
        assert connector._load_oauth_credentials.called
        # Verify model name was denormalized in the call to parent
        assert mock_parent_chat.call_args[1]["effective_model"] == "kimi-k2.5-free"


@pytest.mark.asyncio
async def test_stream_completion_retries_on_401(connector):
    """Regression test for retry logic on 401 Unauthorized in stream_completion."""
    
    # Mock stream_completion of parent OpenAIConnector
    # We need a generator that fails
    async def failing_stream(*args, **kwargs):
        raise HTTPException(status_code=401, detail="Unauthorized")
        yield  # Make it a generator

    async def successful_stream(*args, **kwargs):
        yield "chunk1"
        yield "chunk2"

    with patch("src.connectors.openai.OpenAIConnector.stream_completion") as mock_parent_stream:
        mock_parent_stream.side_effect = [failing_stream(), successful_stream()]

        # Mock credential reloading
        connector._load_oauth_credentials = AsyncMock(return_value=True)

        request = MagicMock(spec=CanonicalChatRequest)
        request.model = "kimi/kimi-k2.5-free"

        chunks = []
        async for chunk in connector.stream_completion(request):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]
        assert mock_parent_stream.call_count == 2
        assert connector._load_oauth_credentials.called


@pytest.mark.asyncio
async def test_regression_no_recursive_exception_on_retry_failure(connector):
    """Ensure that if retry also fails, we get the second failure without recursive mess."""
    with patch("src.connectors.openai.OpenAIConnector.chat_completions") as mock_parent_chat:
        # Both attempts fail with 401
        mock_parent_chat.side_effect = [
            HTTPException(status_code=401, detail="First Fail"),
            HTTPException(status_code=401, detail="Second Fail"),
        ]

        connector._load_oauth_credentials = AsyncMock(return_value=True)

        with pytest.raises(HTTPException) as excinfo:
            await connector.chat_completions(
                request_data={"model": "model"},
                processed_messages=[],
                effective_model="model"
            )
        
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Second Fail"
        assert mock_parent_chat.call_count == 2
