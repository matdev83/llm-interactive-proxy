"""
Unit tests for Anthropic front-end router.
Tests the FastAPI endpoints for /anthropic/v1/messages and /anthropic/v1/models.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.anthropic_converters import AnthropicMessage, AnthropicMessagesRequest
from src.anthropic_router import (
    anthropic_messages,
    anthropic_models,
    router,
)


class TestAnthropicRouter:
    """Test suite for Anthropic front-end router."""

    def setup_method(self):
        """Set up test fixtures."""
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_router_prefix(self):
        """Test that router has correct prefix."""
        assert router.prefix == "/anthropic"
        assert "anthropic" in list(router.tags)

    def test_health_endpoint(self):
        """Test health check endpoint."""
        response = self.client.get("/anthropic/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "anthropic-proxy"

    def test_info_endpoint(self):
        """Test info endpoint."""
        response = self.client.get("/anthropic/v1/info")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "anthropic-proxy"
        assert data["version"] == "1.0.0"
        assert "supported_endpoints" in data
        assert "supported_models" in data
        assert "/v1/messages" in data["supported_endpoints"]
        assert "/v1/models" in data["supported_endpoints"]
        assert "claude-3-5-sonnet-20241022" in data["supported_models"]

    def test_models_endpoint(self):
        """Test models listing endpoint."""
        response = self.client.get("/anthropic/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert "data" in data
        assert len(data["data"]) > 0

        # Check model structure
        first_model = data["data"][0]
        assert "id" in first_model
        assert "object" in first_model
        assert "owned_by" in first_model
        assert first_model["owned_by"] == "anthropic"

    @pytest.mark.asyncio
    async def test_anthropic_models_function(self):
        """Test the anthropic_models function directly."""
        result = await anthropic_models()

        assert result["object"] == "list"
        assert len(result["data"]) > 0

    def test_messages_endpoint_not_implemented(self):
        """Test that messages endpoint returns 501 (not implemented yet)."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Currently returns 501 as noted in implementation
        assert response.status_code == 501
        assert "not yet fully integrated" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_anthropic_messages_function_validation(self):
        """Test the anthropic_messages function with valid input."""
        mock_request = Mock()
        mock_request.app = Mock()

        # Mock the service_provider and its get_required_service method
        mock_service_provider = Mock()
        mock_request.app.state.service_provider = mock_service_provider

        # Create an AsyncMock for the request_processor
        mock_request_processor = AsyncMock()
        mock_service_provider.get_required_service.return_value = mock_request_processor

        # Configure the mock_request_processor.process_request to return a mock response
        # This mock response should be a dictionary, as the router expects it.
        mock_request_processor.process_request.return_value = {
            "choices": [{"message": {"content": "mocked response"}}]
        }

        request_body = AnthropicMessagesRequest(
            model="claude-3-sonnet-20240229",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=100,
        )

        # The original test expected 501, but with a mocked backend, it should now succeed
        # unless there's another reason for 501. Let's assume it should succeed for now.
        response = await anthropic_messages(request_body, mock_request)

        # Assert that process_request was called
        mock_request_processor.process_request.assert_called_once()

        # Assert the response is as expected from the mock
        assert response["choices"][0]["message"]["content"] == "mocked response"

    def test_messages_endpoint_validation_errors(self):
        """Test validation errors for messages endpoint."""
        # Missing required fields
        response = self.client.post("/anthropic/v1/messages", json={})
        assert response.status_code == 422  # Validation error

        # Invalid model type
        response = self.client.post(
            "/anthropic/v1/messages",
            json={
                "model": 123,  # Should be string
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
        )
        assert response.status_code == 422

        # Invalid message format
        response = self.client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3-sonnet-20240229",
                "messages": [{"role": "invalid_role", "content": "Hello"}],
                "max_tokens": 100,
            },
        )
        assert response.status_code == 422

        # Missing max_tokens
        response = self.client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3-sonnet-20240229",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 422

    def test_messages_endpoint_optional_parameters(self):
        """Test messages endpoint with optional parameters."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "system": "You are helpful",
            "stop_sequences": ["STOP"],
            "stream": False,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Still 501 but validates the request structure
        assert response.status_code == 501

    def test_messages_endpoint_streaming_request(self):
        """Test messages endpoint with streaming enabled."""
        request_data = {
            "model": "claude-3-haiku-20240307",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 50,
            "stream": True,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Still 501 but validates streaming parameter
        assert response.status_code == 501

    def test_invalid_endpoints(self):
        """Test invalid endpoints return 404."""
        response = self.client.get("/anthropic/invalid")
        assert response.status_code == 404

        response = self.client.post("/anthropic/v1/invalid")
        assert response.status_code == 404

        response = self.client.get("/anthropic/v2/models")
        assert response.status_code == 404

    def test_wrong_http_methods(self):
        """Test wrong HTTP methods return 405."""
        # GET on messages endpoint (should be POST)
        response = self.client.get("/anthropic/v1/messages")
        assert response.status_code == 405

        # POST on models endpoint (should be GET)
        response = self.client.post("/anthropic/v1/models")
        assert response.status_code == 405

    def test_large_request_handling(self):
        """Test handling of large requests."""
        # Large message content
        large_content = "x" * 10000
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": large_content}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Should still validate and return 501
        assert response.status_code == 501

    def test_unicode_content_handling(self):
        """Test handling of Unicode content."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Hello 世界 🌍 émojis"}],
            "max_tokens": 100,
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)

        # Should handle Unicode properly
        assert response.status_code == 501

    def test_edge_case_parameters(self):
        """Test edge case parameter values."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Test"}],
            "max_tokens": 1,  # Minimum
            "temperature": 0.0,  # Minimum
            "top_p": 1.0,  # Maximum
            "stop_sequences": [],  # Empty list
        }

        response = self.client.post("/anthropic/v1/messages", json=request_data)
        assert response.status_code == 501

    @patch("src.anthropic_router.get_anthropic_models")
    def test_models_endpoint_error_handling(self, mock_get_models):
        """Test error handling in models endpoint."""
        mock_get_models.side_effect = Exception("Database error")

        response = self.client.get("/anthropic/v1/models")
        assert response.status_code == 500

    def test_cors_headers(self):
        """Test that appropriate headers are set for CORS if needed."""
        response = self.client.get("/anthropic/v1/models")

        # Basic response should succeed
        assert response.status_code == 200

        # Could add CORS header checks here if implemented

    def test_content_type_headers(self):
        """Test content type headers."""
        response = self.client.get("/anthropic/v1/models")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    def test_router_tags_and_metadata(self):
        """Test router metadata."""
        assert router.prefix == "/anthropic"
        assert "anthropic" in router.tags

        # Check that routes are properly registered
        route_paths = [route.path for route in router.routes]
        assert "/anthropic/v1/messages" in route_paths
        assert "/anthropic/v1/models" in route_paths
        assert "/anthropic/health" in route_paths
        assert "/anthropic/v1/info" in route_paths
