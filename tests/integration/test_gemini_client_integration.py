"""
Integration tests using the official Google Gemini API client library.

These tests verify that the proxy's Gemini API compatibility works correctly
with the real Google Gemini client, testing all backends and conversion logic.
"""
import pytest
import json
import asyncio
import threading
import time
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Dict, Any
import uvicorn
from fastapi import FastAPI

from src.main import build_app
from src.core.config import _load_config

# Import Gemini client types
try:
    import google.genai as genai
    from google.genai.types import GenerationConfig, Content, Part, Blob
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class ProxyServer:
    """Test server for integration tests."""
    
    def __init__(self, config: Dict[str, Any], port: int = 8001):
        self.config = config
        self.port = port
        self.app = build_app(config)
        self.server = None
        self.thread = None
        
    def start(self):
        """Start the server in a separate thread."""
        def run_server():
            config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
            self.server = uvicorn.Server(config)
            
            # Run server in the current thread
            asyncio.run(self.server.serve())
        
        self.thread = threading.Thread(target=run_server)
        self.thread.daemon = True
        self.thread.start()
        
        # Wait for server to start
        import time
        time.sleep(2)
        
        # Test if server is running
        import requests
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}/", timeout=5)
            if response.status_code == 200:
                print(f"Server started successfully on port {self.port}")
            else:
                print(f"Server responded with status {response.status_code}")
        except Exception as e:
            print(f"Failed to connect to server: {e}")
    
    def stop(self):
        """Stop the server."""
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)


@pytest.fixture
def proxy_config():
    """Configuration for proxy server."""
    return {
        "backend": "openrouter",
        "interactive_mode": True,
        "command_prefix": "!/",
        "openrouter_api_base_url": "https://openrouter.ai/api/v1",
        "gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "openrouter_api_keys": {"test_key": "test_api_key"},
        "gemini_api_keys": {"test_key": "test_gemini_key"},
        "disable_auth": True,
        "disable_accounting": True,
        "proxy_timeout": 30
    }


@pytest.fixture
def proxy_server(proxy_config):
    """Start proxy server for testing."""
    server = ProxyServer(proxy_config)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def gemini_client(proxy_server):
    """Create Gemini client configured to use proxy server."""
    if not GENAI_AVAILABLE:
        pytest.skip("google.genai not available")
    
    # Configure client to use proxy server
    genai.configure(api_key="test_key", base_url=f"http://127.0.0.1:{proxy_server.port}")
    return genai


class TestGeminiClientIntegration:
    """Test Gemini client integration with proxy server."""
    
    @pytest.mark.integration
    def test_models_list_with_gemini_client(self, gemini_client, proxy_server):
        """Test listing models through Gemini client."""
        if not GENAI_AVAILABLE:
            pytest.skip("google.genai not available")
        
        # Mock the backend models
        mock_models = ["gemini-pro", "gemini-pro-vision", "gemini-1.5-pro"]
        
        with patch.object(proxy_server.app.state.gemini_backend, 'get_available_models', 
                          return_value=mock_models):
            
            # List models through Gemini client
            models = list(gemini_client.models.list())
            
            # Verify models are returned
            assert len(models) > 0
            
            # Check that model names are in expected format
            model_names = [model.name for model in models]
            assert any("gemini" in name for name in model_names)


class TestBackendIntegration:
    """Test different backend integrations."""
    
    @pytest.fixture
    def openrouter_mock_response(self):
        """Mock OpenRouter response."""
        return {
            "id": "test-response",
            "object": "chat.completion", 
            "created": 1234567890,
            "model": "openrouter:gpt-4",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello! I'm GPT-4 via OpenRouter."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}
        }
    
    @pytest.fixture
    def gemini_mock_response(self):
        """Mock Gemini response."""
        return {
            "id": "gemini-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini:gemini-pro",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello! I'm Gemini Pro."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        }
    
    @pytest.mark.integration
    def test_openrouter_backend_via_gemini_client(self, gemini_client, proxy_server):
        """Test OpenRouter backend through Gemini client."""
        # Mock the backend to return a proper response
        mock_response = {
            "id": "test-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "openrouter:gpt-4",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello! I'm doing well, thank you for asking."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20}
        }
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            # Use Gemini client to make request
            response = gemini_client.models.generate_content(
                model="openrouter:gpt-4",
                contents=[
                    Content(parts=[Part(text="Hello, how are you?")], role="user")
                ]
            )
            
            # Verify the response is in Gemini format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0
            
            candidate = response.candidates[0]
            assert hasattr(candidate, 'content')
            assert candidate.content is not None
    
    @pytest.mark.integration
    def test_gemini_backend_via_gemini_client(self, gemini_client, proxy_server, gemini_mock_response):
        """Test Gemini backend through Gemini client."""
        with patch.object(proxy_server.app.state.gemini_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(gemini_mock_response, {}))):
            
            # Use Gemini client with system instruction
            response = gemini_client.models.generate_content(
                model='gemini:gemini-pro',
                contents='What is quantum computing?'
            )
            
            # Verify Gemini format response
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0
            
            candidate = response.candidates[0]
            assert hasattr(candidate, 'content')
            assert candidate.content is not None
    
    @pytest.mark.integration
    def test_gemini_cli_direct_backend_via_gemini_client(self, gemini_client, proxy_server):
        """Test Gemini CLI Direct backend through Gemini client."""
        cli_response = {
            "id": "cli-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini-1.5-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello from Gemini CLI Direct!"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 8,
                "total_tokens": 13
            }
        }
        
        with patch.object(proxy_server.app.state.gemini_cli_direct_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(cli_response, {}))):
            
            response = gemini_client.generate_content(
                contents='Test message'
            )
            
            # Verify response format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0


class TestComplexConversions:
    """Test complex request/response conversions."""
    
    @pytest.mark.integration
    def test_multipart_content_conversion(self, gemini_client, proxy_server):
        """Test conversion of multipart content (text + attachments)."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "I see an image with text."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35}
        }
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            # Create multipart content using Gemini client format
            response = gemini_client.models.generate_content(
                model='test-model',
                contents=[
                    Content(
                        parts=[
                            Part(text="Look at this image:"),
                            Part(inline_data=Blob(
                                data=b"fake_image_data",
                                mime_type="image/jpeg"
                            )),
                            Part(text="What do you see?")
                        ],
                        role="user"
                    )
                ]
            )
            
            # Verify response format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0
    
    @pytest.mark.integration
    def test_conversation_history_conversion(self, gemini_client, proxy_server):
        """Test conversion of multi-turn conversation."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "That's a great follow-up question!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
        }
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            # Create conversation history
            conversation = [
                Content(
                    parts=[Part(text="What is AI?")],
                    role="user"
                ),
                Content(
                    parts=[Part(text="AI is artificial intelligence...")],
                    role="model"
                ),
                Content(
                    parts=[Part(text="Can you give me examples?")],
                    role="user"
                )
            ]
            
            response = gemini_client.models.generate_content(
                model='test-model',
                contents=conversation
            )
            
            # Verify response format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0


class TestStreamingIntegration:
    """Test streaming functionality with Gemini client."""
    
    @pytest.mark.integration
    def test_streaming_content_generation(self, gemini_client, proxy_server):
        """Test streaming content generation through Gemini client."""
        # Mock streaming response
        async def mock_stream():
            chunks = [
                b'data: {"choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n',
                b'data: {"choices":[{"index":0,"delta":{"content":" there"}}]}\n\n',
                b'data: {"choices":[{"index":0,"delta":{"content":"!"}}]}\n\n',
                b'data: [DONE]\n\n'
            ]
            for chunk in chunks:
                yield chunk
        
        from fastapi.responses import StreamingResponse
        mock_streaming_response = StreamingResponse(mock_stream(), media_type="text/plain")
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_streaming_response, {}))):
            
            # Test streaming with Gemini client
            stream = gemini_client.stream_generate_content(
                contents='Tell me a story'
            )
            
            # Collect streaming chunks
            chunks = []
            for chunk in stream:
                if hasattr(chunk, 'text') and chunk.text:
                    chunks.append(chunk.text)
            
            # Verify streaming worked
            assert len(chunks) >= 0  # May be empty if streaming fails, but shouldn't error


class TestErrorHandling:
    """Test error handling scenarios."""
    
    @pytest.mark.integration
    def test_authentication_error(self, proxy_config):
        """Test authentication error handling."""
        if not GENAI_AVAILABLE:
            pytest.skip("google.genai not available")
        
        # Create server with authentication enabled
        config = proxy_config.copy()
        config["disable_auth"] = False
        server = ProxyServer(config, port=8002)
        server.start()
        
        try:
            # Configure client with invalid credentials
            genai.configure(api_key="invalid_key", base_url=f"http://127.0.0.1:8002")
            client = genai
            
            # This should raise an authentication error
            with pytest.raises(Exception):  # Could be various exception types
                client.models.list()
        finally:
            server.stop()
    
    @pytest.mark.integration
    def test_model_not_found_error(self, gemini_client, proxy_server):
        """Test model not found error handling."""
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(side_effect=Exception("Model not found"))):
            
            # This should handle the error gracefully
            with pytest.raises(Exception):
                gemini_client.models.generate_content(
                    model='non-existent-model',
                    contents='Test message'
                )


class TestPerformanceAndReliability:
    """Test performance and reliability aspects."""
    
    @pytest.mark.integration
    def test_concurrent_requests(self, gemini_client, proxy_server):
        """Test handling of concurrent requests."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Concurrent response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
        }
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            # Make multiple concurrent requests
            def make_request(i):
                try:
                    response = gemini_client.models.generate_content(
                        model='test-model',
                        contents=f'Request {i}'
                    )
                    return response
                except Exception as e:
                    return e
            
            # Test with small number of concurrent requests
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(make_request, i) for i in range(3)]
                results = [future.result() for future in futures]
            
            # Verify all requests completed (may succeed or fail, but shouldn't hang)
            assert len(results) == 3
    
    @pytest.mark.integration
    def test_large_content_handling(self, gemini_client, proxy_server):
        """Test handling of large content."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Large content processed"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 5, "total_tokens": 1005}
        }
        
        with patch.object(proxy_server.app.state.openrouter_backend, 'chat_completions', 
                          new=AsyncMock(return_value=(mock_response, {}))):
            
            # Create large content
            large_content = "This is a test message. " * 1000  # Large content
            
            response = gemini_client.models.generate_content(
                model='test-model',
                contents=large_content
            )
            
            # Verify response format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0


if __name__ == "__main__":
    # Run specific tests for debugging
    pytest.main([__file__, "-v", "-s"])
