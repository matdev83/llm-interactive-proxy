"""
Tests for Gemini API compatibility endpoints.
These tests verify that the proxy correctly handles Gemini API format requests
and converts them to/from the internal OpenAI format.
"""
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.main import build_app


class TestGeminiModelsEndpoint:
    """Test the Gemini models listing endpoint."""
    


    def test_list_models_gemini_format(self, client):
        """Test that /v1beta/models returns Gemini-formatted models."""
        # Mock the backend models
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        if not hasattr(client.app.state, 'gemini_backend'):
            from unittest.mock import Mock
            client.app.state.gemini_backend = Mock()
        if not hasattr(client.app.state, 'gemini_cli_direct_backend'):
            from unittest.mock import Mock
            client.app.state.gemini_cli_direct_backend = Mock()
            
        with patch.object(client.app.state, 'openrouter_backend') as mock_or, \
             patch.object(client.app.state, 'gemini_backend') as mock_gemini, \
             patch.object(client.app.state, 'gemini_cli_direct_backend') as mock_cli:
            
            mock_or.get_available_models.return_value = ["gpt-4", "gpt-3.5-turbo"]
            mock_gemini.get_available_models.return_value = ["gemini-pro", "gemini-pro-vision"]
            mock_cli.get_available_models.return_value = ["gemini-1.5-pro"]
            
            response = client.get("/v1beta/models")
            
            assert response.status_code == 200
            data = response.json()
            
            # Check Gemini format structure
            assert "models" in data
            assert isinstance(data["models"], list)
            assert len(data["models"]) > 0
            
            # Check individual model format
            model = data["models"][0]
            assert "name" in model
            assert "display_name" in model
            assert "description" in model
            assert "input_token_limit" in model
            assert "output_token_limit" in model
            assert "supported_generation_methods" in model
            
            # Verify supported methods include both generation types
            assert "generateContent" in model["supported_generation_methods"]
            assert "streamGenerateContent" in model["supported_generation_methods"]
    


    def test_models_endpoint_auth_disabled(self, client):
        """Test models endpoint works when auth is disabled."""
        response = client.get("/v1beta/models")
        assert response.status_code == 200


class TestGeminiGenerateContent:
    """Test the Gemini content generation endpoint."""
    


    def test_generate_content_basic(self, client):
        """Test basic content generation with Gemini format."""
        # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = True  # Disable interactive commands for clean testing
        client.app.state.command_prefix = '!/'
        client.app.state.force_set_project = False
        client.app.state.api_key_redaction_enabled = False
        from src.rate_limit import RateLimitRegistry
        client.app.state.rate_limits = RateLimitRegistry()
        if not hasattr(client.app.state, 'session_manager'):
            from src.session import SessionManager
            client.app.state.session_manager = SessionManager()
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            mock_backend = Mock()
            mock_backend.get_available_models.return_value = ["gpt-4", "gpt-3.5-turbo"]
            client.app.state.openrouter_backend = mock_backend
        if not hasattr(client.app.state, 'gemini_backend'):
            from unittest.mock import Mock
            mock_backend = Mock()
            mock_backend.get_available_models.return_value = ["gemini-pro", "gemini-pro-vision"]
            client.app.state.gemini_backend = mock_backend
        if not hasattr(client.app.state, 'gemini_cli_direct_backend'):
            from unittest.mock import Mock
            mock_backend = Mock()
            mock_backend.get_available_models.return_value = ["gemini-2.0-flash-001", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
            client.app.state.gemini_cli_direct_backend = mock_backend
        
        # Create a Gemini-format request
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Hello, how are you?"}],
                    "role": "user"
                }
            ],
            "generation_config": {
                "temperature": 0.7,
                "max_output_tokens": 100
            }
        }
        
        # Mock the backend response
        mock_response = {
            "id": "test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! I'm doing well, thank you for asking."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25
            }
        }
        
        # Mock the backend instead of non-existent module function
        mock_response = {
            "id": "test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        }
        
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        
        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            # Mock response already defined above
            
            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Check Gemini response format
            assert "candidates" in data
            assert isinstance(data["candidates"], list)
            assert len(data["candidates"]) == 1
            
            candidate = data["candidates"][0]
            assert "content" in candidate
            assert "finishReason" in candidate
            assert candidate["finishReason"] == "STOP"
            
            # Check content format
            content = candidate["content"]
            assert "parts" in content
            assert "role" in content
            assert content["role"] == "model"
            
            # Check usage metadata (camelCase as per official Gemini API)
            assert "usageMetadata" in data
            usage = data["usageMetadata"]
            assert "promptTokenCount" in usage
            assert "candidatesTokenCount" in usage
            assert "totalTokenCount" in usage
    


    def test_generate_content_with_system_instruction(self, client):
        """Test content generation with system instruction."""
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "What is 2+2?"}],
                    "role": "user"
                }
            ],
            "system_instruction": {
                "parts": [{"text": "You are a helpful math tutor."}],
                "role": "user"
            }
        }
        
        # Mock the backend response to match what the test expects
        mock_response = {
            "id": "test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "2+2 equals 4."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}
        }
        
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        
        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "candidates" in data
            assert data["candidates"][0]["content"]["parts"][0]["text"] == "2+2 equals 4."
    


    def test_generate_content_error_handling(self, client):
        """Test error handling in content generation."""
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Test message"}],
                    "role": "user"
                }
            ]
        }
        
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        
        # Mock the backend to raise an HTTPException to simulate an error
        from fastapi import HTTPException
        
        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Model not found"))):
            
            response = client.post(
                "/v1beta/models/invalid-model:generateContent",
                json=request_data
            )
            
            # Should return the error status
            assert response.status_code == 404
    


class TestGeminiStreamGenerateContent:
    """Test the Gemini streaming content generation endpoint."""
    


    def test_stream_generate_content(self, client):
        """Test streaming content generation with Gemini format."""
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Tell me a short story"}],
                    "role": "user"
                }
            ],
            "generation_config": {
                "temperature": 0.8
            }
        }
        
        # Mock streaming response
        async def mock_stream():
            chunks = [
                b'data: {"candidates":[{"content":{"parts":[{"text":"Once"}],"role":"model"},"index":0}]}\n\n',
                b'data: {"candidates":[{"content":{"parts":[{"text":" upon"}],"role":"model"},"index":0}]}\n\n',
                b'data: {"candidates":[{"content":{"parts":[{"text":" a time"}],"role":"model"},"index":0}]}\n\n',
                b'data: [DONE]\n\n'
            ]
            for chunk in chunks:
                yield chunk
        
        from fastapi.responses import StreamingResponse
        mock_streaming_response = StreamingResponse(mock_stream(), media_type="text/plain; charset=utf-8")
        
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        
        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=mock_streaming_response)):
            
            response = client.post(
                "/v1beta/models/test-model:streamGenerateContent",
                json=request_data
            )
            
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/plain; charset=utf-8"
            
            # Read the streaming content
            content = response.content.decode('utf-8')
            
            # Should contain Gemini-formatted streaming chunks
            assert "data: " in content
            assert "candidates" in content
    


class TestGeminiAuthentication:
    """Test Gemini API authentication."""
    


    def test_gemini_auth_with_api_key_header(self):
        """Test authentication using x-goog-api-key header."""
        # Create app with auth enabled
        config = {
            "disable_auth": False,
            "interactive_mode": False,
            "command_prefix": "/",
            "disable_interactive_commands": True,
            "proxy_timeout": 30.0,
            "openrouter_api_base_url": "https://openrouter.ai/api/v1",
            "gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        }
        
        app = build_app(config)
        app.state.client_api_key = "test-api-key"
        client = TestClient(app)
        
        # Test with correct API key in x-goog-api-key header
        response = client.get(
            "/v1beta/models",
            headers={"x-goog-api-key": "test-api-key"}
        )
        assert response.status_code == 200
        
        # Test with incorrect API key
        response = client.get(
            "/v1beta/models",
            headers={"x-goog-api-key": "wrong-key"}
        )
        assert response.status_code == 401
        
        # Test with no auth header
        response = client.get("/v1beta/models")
        assert response.status_code == 401
    


    def test_gemini_auth_fallback_to_bearer(self):
        """Test fallback to Bearer token authentication."""
        config = {
            "disable_auth": False,
            "interactive_mode": False,
            "command_prefix": "/",
            "disable_interactive_commands": True,
            "proxy_timeout": 30.0,
        }
        
        app = build_app(config)
        app.state.client_api_key = "test-api-key"
        client = TestClient(app)
        
        # Test with Bearer token (should work as fallback)
        response = client.get(
            "/v1beta/models",
            headers={"Authorization": "Bearer test-api-key"}
        )
        assert response.status_code == 200


class TestGeminiRequestConversion:
    """Test conversion between Gemini and OpenAI formats."""
    


    def test_complex_content_conversion(self, client):
        """Test conversion of complex content with multiple parts."""
        request_data = {
            "contents": [
                {
                    "parts": [
                        {"text": "Look at this image: "},
                        {"inline_data": {"mime_type": "image/jpeg", "data": "base64data"}},
                        {"text": " What do you see?"}
                    ],
                    "role": "user"
                }
            ]
        }
        
        # Mock the backend response
        mock_response = {
            "id": "test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "I see an image."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
        }
        
        # Ensure backends exist on app.state first
        if not hasattr(client.app.state, 'openrouter_backend'):
            from unittest.mock import Mock
            client.app.state.openrouter_backend = Mock()
        
        with patch.object(client.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))) as mock_backend:
            
            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "candidates" in data
            assert data["candidates"][0]["content"]["parts"][0]["text"] == "I see an image."
            
            # Verify the backend was called (conversion happened successfully)
            mock_backend.assert_called_once() 