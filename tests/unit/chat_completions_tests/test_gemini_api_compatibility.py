"""
Tests for Gemini API compatibility endpoints.
These tests verify that the proxy correctly handles Gemini API format requests
and converts them to/from the internal OpenAI format.
"""
import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.main import build_app
from src.gemini_models import GenerateContentRequest, Content, Part, GenerationConfig


@pytest.fixture
# Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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

    def test_config():
    """Test configuration with disabled auth for easier testing."""
    return {
        "disable_auth": True,
        "interactive_mode": False,
        "command_prefix": "/",
        "disable_interactive_commands": True,
        "proxy_timeout": 30.0,
        "openrouter_api_base_url": "https://openrouter.ai/api/v1",
        "gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "openrouter_api_keys": {"test": "test-key"},
        "gemini_api_keys": {"test": "test-gemini-key"},
    }


@pytest.fixture
def client(test_config):
    """FastAPI test client with test configuration."""
    app = build_app(test_config)
    return TestClient(app)


class TestGeminiModelsEndpoint:
    """Test the Gemini models listing endpoint."""
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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

    def test_models_endpoint_auth_disabled(self, client):
        """Test models endpoint works when auth is disabled."""
        response = client.get("/v1beta/models")
        assert response.status_code == 200


class TestGeminiGenerateContent:
    """Test the Gemini content generation endpoint."""
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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

    def test_generate_content_basic(self, client):
        """Test basic content generation with Gemini format."""
        # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
            assert "finish_reason" in candidate
            assert candidate["finishReason"] == "STOP"
            
            # Check content format
            content = candidate["content"]
            assert "parts" in content
            assert "role" in content
            assert content["role"] == "model"
            
            # Check usage metadata
            assert "usage_metadata" in data
            usage = data["usage_metadata"]
            assert "prompt_token_count" in usage
            assert "candidates_token_count" in usage
            assert "total_token_count" in usage
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
        
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "2+2 equals 4."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}
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
            assert "candidates" in data
            assert data["candidates"][0]["content"]["parts"][0]["text"] == "2+2 equals 4."
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
        
        # Mock an error response
        error_response = {
            "message": "Model not found",
            "error": "invalid_model"
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
            # Mock response already defined above = error_response
            
            response = client.post(
                "/v1beta/models/invalid-model:generateContent",
                json=request_data
            )
            
            # Should pass through error responses
            assert response.status_code == 200
            data = response.json()
            assert "message" in data
            assert "error" in data


class TestGeminiStreamGenerateContent:
    """Test the Gemini streaming content generation endpoint."""
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
                b'data: {"choices":[{"index":0,"delta":{"content":"Once"}}]}\n\n',
                b'data: {"choices":[{"index":0,"delta":{"content":" upon"}}]}\n\n',
                b'data: {"choices":[{"index":0,"delta":{"content":" a time"}}]}\n\n',
                b'data: [DONE]\n\n'
            ]
            for chunk in chunks:
                yield chunk
        
        from fastapi.responses import StreamingResponse
        mock_streaming_response = StreamingResponse(mock_stream(), media_type="text/plain")
        
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
            # Mock response already defined above = mock_streaming_response
            
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
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
    
    # Ensure app state is fully initialized
        client.app.state.backend_type = 'openrouter'
        client.app.state.disable_interactive_commands = False
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
        
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "I see an image."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
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
            
            # Verify the request was converted properly
            # The mock should have been called with an OpenAI-format request
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            
            # Check that the complex content was converted to a single message
            assert len(openai_request.messages) == 1
            message = openai_request.messages[0]
            assert message.role == "user"
            # Should contain text parts and attachment indicators
            assert "Look at this image:" in message.content
            assert "[Attachment: image/jpeg]" in message.content
            assert "What do you see?" in message.content 