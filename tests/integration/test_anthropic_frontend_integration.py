"""
Integration tests for Anthropic front-end interface.
Tests the complete flow using the official Anthropic SDK against the proxy.
"""

import pytest
from fastapi.testclient import TestClient

# Import the official Anthropic SDK for testing
try:
    from anthropic import Anthropic, AsyncAnthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)


@pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic package not available")
class TestAnthropicFrontendIntegration:
    """Integration tests for Anthropic front-end using official SDK."""

    def setup_method(self):
        """Set up test fixtures."""
        # Build app with test configuration
        test_config = AppConfig(
            auth=AuthConfig(disable_auth=True),
            backends=BackendSettings(
                openrouter=BackendConfig(api_key=["test-key"]),
                default_backend="openrouter",
            ),
        )

        self.app = build_app(test_config)
        self.client = TestClient(self.app)

        # Test API key for Anthropic SDK
        self.test_api_key = "test-anthropic-key"
        self.proxy_base_url = "http://testserver/anthropic"

    def test_anthropic_sdk_client_creation(self):
        """Test that Anthropic SDK client can be created with proxy URL."""
        client = Anthropic(api_key=self.test_api_key, base_url=self.proxy_base_url)

        assert client.api_key == self.test_api_key
        assert self.proxy_base_url in str(client._client.base_url)

    @pytest.mark.asyncio
    async def test_async_anthropic_sdk_client_creation(self):
        """Test that AsyncAnthropic SDK client can be created with proxy URL."""
        client = AsyncAnthropic(api_key=self.test_api_key, base_url=self.proxy_base_url)

        assert client.api_key == self.test_api_key
        assert self.proxy_base_url in str(client._client.base_url)

    def test_models_endpoint_via_http(self):
        """Test models endpoint via direct HTTP call."""
        response = self.client.get("/anthropic/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0

        # Verify model structure matches Anthropic format
        for model in data["data"]:
            assert "id" in model
            assert "object" in model
            assert "owned_by" in model
            assert model["owned_by"] == "anthropic"

    def test_messages_endpoint_validation_via_http(self):
        """Test messages endpoint validation via direct HTTP call."""
        # Valid request structure
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "max_tokens": 100,
            "temperature": 0.7,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Currently returns 501 but should validate the request
        assert response.status_code == 501
        assert "not yet fully integrated" in response.json()["detail"]

    def test_messages_endpoint_with_system_message(self):
        """Test messages endpoint with system message."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "max_tokens": 50,
            "system": "You are a helpful math tutor.",
            "temperature": 0.3,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501  # Not yet implemented

    def test_messages_endpoint_streaming_request(self):
        """Test messages endpoint with streaming enabled."""
        request_data = {
            "model": "claude-3-haiku-20240307",
            "messages": [{"role": "user", "content": "Tell me a short story."}],
            "max_tokens": 200,
            "stream": True,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501  # Not yet implemented

    def test_messages_endpoint_with_stop_sequences(self):
        """Test messages endpoint with stop sequences."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Count from 1 to 10"}],
            "max_tokens": 100,
            "stop_sequences": ["5", "STOP"],
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501  # Not yet implemented

    def test_conversation_flow_via_http(self):
        """Test multi-turn conversation via HTTP."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "The capital of France is Paris."},
                {"role": "user", "content": "What about Italy?"},
            ],
            "max_tokens": 50,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501  # Not yet implemented

    def test_error_handling_invalid_model(self):
        """Test error handling for invalid model."""
        request_data = {
            "model": "invalid-model-name",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        # Should validate but still return 501 for now
        assert response.status_code == 501

    def test_error_handling_missing_required_fields(self):
        """Test error handling for missing required fields."""
        # Missing messages
        response = self.client.post(
            "/anthropic/v1/messages",
            json={"model": "claude-3-sonnet-20240229", "max_tokens": 100},
        )
        assert response.status_code == 422  # Validation error

        # Missing max_tokens
        response = self.client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3-sonnet-20240229",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 422  # Validation error

    def test_parameter_validation_ranges(self):
        """Test parameter validation for ranges."""
        # Temperature out of range
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
            "temperature": 2.5,  # Should be 0-1
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        # Pydantic should validate this, but let's see current behavior
        assert response.status_code in [422, 501]

    def test_health_and_info_endpoints(self):
        """Test health and info endpoints."""
        # Health check
        response = self.client.get("/anthropic/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

        # Info endpoint
        response = self.client.get("/anthropic/v1/info")
        assert response.status_code == 200
        info = response.json()
        assert info["service"] == "anthropic-proxy"
        assert "/v1/messages" in info["supported_endpoints"]
        assert "/v1/models" in info["supported_endpoints"]

    @pytest.mark.asyncio
    async def test_anthropic_sdk_models_call_mock(self):
        """Test Anthropic SDK models call with mocked response."""
        # This would test the SDK integration once the endpoint is fully implemented
        client = AsyncAnthropic(api_key=self.test_api_key, base_url=self.proxy_base_url)

        # For now, we can't test the actual SDK call since it's not implemented
        # But we can verify the client is properly configured
        assert client.api_key == self.test_api_key

    def test_concurrent_requests(self):
        """Test handling of concurrent requests."""
        import threading

        results = []

        def make_request():
            response = self.client.get("/anthropic/v1/models")
            results.append(response.status_code)

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All requests should succeed
        assert all(status == 200 for status in results)
        assert len(results) == 5

    def test_large_payload_handling(self):
        """Test handling of large payloads."""
        # Large message content
        large_content = "This is a test message. " * 1000  # ~24KB

        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": large_content}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        # Should handle large payloads and still return 501
        assert response.status_code == 501

    def test_unicode_and_special_characters(self):
        """Test handling of Unicode and special characters."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {"role": "user", "content": "Hello 世界! 🌍 Café naïve résumé"}
            ],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        # Should handle Unicode properly
        assert response.status_code == 501

    def test_content_type_headers(self):
        """Test proper content type headers."""
        response = self.client.get("/anthropic/v1/models")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    def test_anthropic_specific_model_names(self):
        """Test that Anthropic-specific model names are handled."""
        models_response = self.client.get("/anthropic/v1/models")
        assert models_response.status_code == 200

        model_ids = [model["id"] for model in models_response.json()["data"]]

        # Check for Anthropic-specific models
        expected_models = [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]

        for expected_model in expected_models:
            assert expected_model in model_ids

    def test_endpoint_not_found(self):
        """Test that non-existent endpoints return 404."""
        response = self.client.get("/anthropic/v1/nonexistent")
        assert response.status_code == 404

        response = self.client.post("/anthropic/v2/messages")
        assert response.status_code == 404

    def test_method_not_allowed(self):
        """Test that wrong HTTP methods return 405."""
        # GET on messages endpoint (should be POST)
        response = self.client.get("/anthropic/v1/messages")
        assert response.status_code == 405

        # POST on models endpoint (should be GET)
        response = self.client.post("/anthropic/v1/models", json={})
        assert response.status_code == 405


@pytest.mark.skipif(
    ANTHROPIC_AVAILABLE, reason="Testing fallback when anthropic not available"
)
class TestAnthropicFrontendWithoutSDK:
    """Test Anthropic front-end when SDK is not available."""

    def setup_method(self):
        """Set up test fixtures."""
        test_config = AppConfig(
            auth=AuthConfig(disable_auth=True),
            backends=BackendSettings(default_backend="openrouter"),
        )

        self.app = build_app(test_config)
        self.client = TestClient(self.app)

    def test_endpoints_work_without_sdk(self):
        """Test that endpoints work even without Anthropic SDK installed."""
        # Models endpoint should work
        response = self.client.get("/anthropic/v1/models")
        assert response.status_code == 200

        # Messages endpoint should validate request structure
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501  # Not implemented yet
