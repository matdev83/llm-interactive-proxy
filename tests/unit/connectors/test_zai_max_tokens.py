"""Tests for ZAI connectors max_tokens handling."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import ChatRequest


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock()


@pytest.fixture
def mock_translation_service():
    """Create a mock translation service."""
    return MagicMock()


@pytest.fixture
async def zai_coding_plan_backend(mock_client, mock_translation_service):
    """Create a ZaiCodingPlanBackend instance."""
    mock_translation_service.from_domain_request.side_effect = (
        lambda request, *_args, **_kwargs: {
            "model": getattr(request, "model", None),
            "messages": getattr(request, "messages", []),
            "stream": getattr(request, "stream", False),
        }
    )
    model_response = MagicMock()
    model_response.json.return_value = {
        "data": [
            {
                "id": "claude-sonnet-4-20250514",
                "name": "claude-sonnet-4-20250514",
            }
        ]
    }
    model_response.raise_for_status = MagicMock()
    mock_client.get.return_value = model_response
    backend = ZaiCodingPlanBackend(
        client=mock_client,
        config=MagicMock(),
        translation_service=mock_translation_service,
    )
    await backend.initialize(api_key="test-key")
    return backend


class TestZaiCodingPlanMaxTokens:
    """Test max_tokens handling in ZaiCodingPlanBackend."""

    async def test_default_max_tokens_is_200k(self, zai_coding_plan_backend):
        """When no max_tokens is specified, should default to 200K."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=None,  # No explicit value
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert "max_tokens" not in payload  # provider default

    async def test_zero_max_tokens_uses_default(self, zai_coding_plan_backend):
        """When max_tokens is 0, should use default 200K."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=0,
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert payload["max_tokens"] == 8192  # fallback default

    async def test_negative_max_tokens_uses_default(self, zai_coding_plan_backend):
        """When max_tokens is negative, should use default 200K."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=-100,
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert payload["max_tokens"] == 8192  # fallback default

    async def test_explicit_valid_max_tokens_is_preserved(
        self, zai_coding_plan_backend
    ):
        """When max_tokens is explicitly set to a valid value, it should be preserved."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=4096,
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert payload["max_tokens"] == 4096

    async def test_max_tokens_below_minimum_is_clamped(self, zai_coding_plan_backend):
        """When max_tokens is below 1K, should be clamped to 1K."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=512,
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert payload["max_tokens"] == 1024  # Minimum 1K

    async def test_max_tokens_above_maximum_is_clamped(self, zai_coding_plan_backend):
        """When max_tokens exceeds 200K, should be clamped to 200K."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=200000,
        )

        payload = await zai_coding_plan_backend._prepare_payload(request)

        assert payload["max_tokens"] == 200000  # Maximum 200K

    async def test_max_tokens_at_boundaries(self, zai_coding_plan_backend):
        """Test max_tokens at exact boundary values."""
        # Test at minimum boundary
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=1024,
        )
        payload = await zai_coding_plan_backend._prepare_payload(request)
        assert payload["max_tokens"] == 1024

        # Test at maximum boundary
        request = ChatRequest(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=200000,
        )
        payload = await zai_coding_plan_backend._prepare_payload(request)
        assert payload["max_tokens"] == 200000
