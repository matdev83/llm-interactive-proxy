"""
Integration tests using the official Google Gemini API client library.

These tests verify that the proxy's Gemini API compatibility works correctly
with the real Google Gemini client, testing all backends and conversion logic.
"""
import pytest

pytestmark = pytest.mark.integration
import asyncio
import time
from typing import Optional, Dict, Any
from unittest.mock import patch, AsyncMock, MagicMock
import threading
import uvicorn
from fastapi.testclient import TestClient

# Official Google Gemini client
import google.genai as genai
from google.genai.types import GenerationConfig, Content, Part, Blob, HttpOptions

from src.main import build_app


class ProxyServer:
    """Helper class to run the proxy server in a separate thread for testing."""
    
    def __init__(self, config: Dict[str, Any], port: int = 8001):
        self.config = config
        self.port = port
        self.app = None
        self.server = None
        self.thread = None
        self.running = False
    
    def start(self):
        """Start the proxy server in a separate thread."""
        self.app = build_app(self.config)
        
        def run_server():
            if self.app is None:
                raise RuntimeError("FastAPI app failed to build.")
            config = uvicorn.Config(
                app=self.app, # Explicitly cast to FastAPI to help type checker
                host="127.0.0.1",
                port=self.port,
                log_level="warning"
            )
            self.server = uvicorn.Server(config)
            self.running = True
            asyncio.run(self.server.serve())
        
        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        
        # Wait for server to start
        import time
        for _ in range(50):  # Wait up to 5 seconds
            try:
                import requests
                response = requests.get(f"http://127.0.0.1:{self.port}/")
                if response.status_code == 200:
                    break
            except:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Server failed to start")
    
    def stop(self):
        """Stop the proxy server."""
        if self.server:
            self.server.should_exit = True
        self.running = False


@pytest.fixture
def proxy_config():
    """Test configuration for the proxy."""
    return {
        "disable_auth": True,
        "interactive_mode": False,
        "command_prefix": "/",
        "disable_interactive_commands": True,
        "proxy_timeout": 30.0,
        "openrouter_api_base_url": "https://openrouter.ai/api/v1",
        "gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "openrouter_api_keys": {"test": "test-openrouter-key"},
        "gemini_api_keys": {"test": "test-gemini-key"},
        "backend": "openrouter", # Add a default backend for testing
    }


@pytest.fixture
def proxy_server(proxy_config):
    """Start a proxy server for testing."""
    server = ProxyServer(proxy_config, port=8001)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def gemini_client(proxy_server):
    """Create a Gemini client pointing to our proxy."""
    # Use the new google.genai Client API
    from google.genai.types import HttpOptions
    client = genai.Client(
        api_key="test-api-key",
        http_options=HttpOptions(base_url=f"http://127.0.0.1:{proxy_server.port}")
    )
    return client


class TestGeminiClientIntegration:
    """Test the proxy using the official Gemini client library."""
    
    
    
    def test_models_list_with_gemini_client(self, gemini_client, proxy_server):
        """Test listing models using the official Gemini client."""
        # Mock the backend models
        with patch.object(proxy_server.app.state, 'openrouter_backend') as mock_or, \
             patch.object(proxy_server.app.state, 'gemini_backend') as mock_gemini, \
             patch.object(proxy_server.app.state, 'gemini_cli_direct_backend') as mock_cli:
            
            mock_or.get_available_models.return_value = ["gpt-4o", "gpt-4.1"]
            mock_gemini.get_available_models.return_value = ["gemini-2.5-pro", "gemini-2.5-flash"]
            mock_cli.get_available_models.return_value = ["gemini-2.5-pro"]
            
            # Use the official Gemini client to list models
            models_pager = gemini_client.models.list()
            models_list = list(models_pager)
            
            # Verify we get models in Gemini format
            assert len(models_list) > 0
            
            # Check the first model has Gemini format structure
            model = models_list[0]
            assert hasattr(model, 'name')
            assert hasattr(model, 'description')
            assert hasattr(model, 'version')
            # The proxy converts models to Gemini format, so basic structure should be present
            # Note: The actual model object may not have all expected attributes depending on conversion


class TestBackendIntegration:
    """Test integration with different backends through Gemini client."""
    
    @pytest.fixture
    def openrouter_mock_response(self):
        """Mock OpenRouter response."""
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! I'm GPT-4 via OpenRouter."
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
    
    @pytest.fixture
    def gemini_mock_response(self):
        """Mock Gemini backend response."""
        return {
            "id": "gemini-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! I'm Gemini Pro."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 12,
                "total_tokens": 20
            }
        }
    
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
                ],
                generation_config=GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=100,
                ),
            )
            
            # Verify the response is in Gemini format
            assert hasattr(response, 'candidates')
            assert len(response.candidates) > 0
            
            candidate = response.candidates[0]
            assert hasattr(candidate, 'content')
            assert candidate.content is not None
            assert response.prompt_feedback.block_reason is None
            
            # Verify content structure
            content = text_response
            assert isinstance(content, str)
            assert "Hello! I'm GPT-4 via OpenRouter." in content
            assert "Hello! I'm GPT-4 via OpenRouter." in content
            assert "Hello! I'm GPT-4 via OpenRouter." in content
            assert "Hello! I'm GPT-4 via OpenRouter." in content
            
            # Verify usage metadata
            assert response.usage_metadata is not None
            usage = response.usage_metadata
            assert usage.prompt_token_count == 10
            assert usage.candidates_token_count == 15
            assert usage.total_token_count == 25
            
            # Verify the mock was called with converted OpenAI format
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            
            # Check conversion to OpenAI format
            assert openai_request.model == 'openrouter:gpt-4'
            assert len(openai_request.messages) == 1
            assert openai_request.messages[0].role == "user"
            assert openai_request.messages[0].content == "Hello, how are you?"
            assert openai_request.temperature == 0.7
            assert openai_request.max_tokens == 100
    
    def test_gemini_backend_via_gemini_client(self, gemini_client, proxy_server, gemini_mock_response):
        """Test Gemini backend through Gemini client."""
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = gemini_mock_response
            
            # Use Gemini client with system instruction
            response = gemini_client.models.generate_content(
                model='gemini:gemini-pro',
                contents='What is quantum computing?',
                system_instruction='You are a physics expert.',
                generation_config=GenerationConfig(
                    temperature=0.5,
                    max_output_tokens=200
                )
            )
            
            # Verify Gemini format response
            assert response.text == "Hello! I'm Gemini Pro."
            assert response.prompt_feedback.block_reason is None
            
            # Verify the request was converted properly
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            
            # Check system instruction conversion
            assert len(openai_request.messages) == 2
            assert openai_request.messages[0].role == "system"
            assert openai_request.messages[0].content == "You are a physics expert."
            assert openai_request.messages[1].role == "user"
            assert openai_request.messages[1].content == "What is quantum computing?"
    
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
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = cli_response
            
            response = gemini_client.generate_content(
                contents='Test message'
            )
            
            # Verify response format
            assert response.text == "Hello from Gemini CLI Direct!"
            assert response.usage_metadata.total_token_count == 13


class TestComplexConversions:
    """Test complex request/response conversions."""
    
    def test_multipart_content_conversion(self, gemini_client, proxy_server):
        """Test conversion of multipart content (text + attachments)."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "I see an image with text."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35}
        }
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_response
            
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
            
            # Verify the request conversion handled multipart content
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            
            # Check that multipart content was converted to single message
            assert len(openai_request.messages) == 1
            message = openai_request.messages[0]
            assert message.role == "user"
            
            # Should contain text parts and attachment indicator
            content = message.content
            assert "Look at this image:" in content
            assert "[Attachment: image/jpeg]" in content
            assert "What do you see?" in content
    
    def test_conversation_history_conversion(self, gemini_client, proxy_server):
        """Test conversion of multi-turn conversation."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "That's a great follow-up question!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
        }
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_response
            
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
            
            # Verify conversation was converted properly
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            
            # Check message conversion
            assert len(openai_request.messages) == 3
            assert openai_request.messages[0].role == "user"
            assert openai_request.messages[0].content == "What is AI?"
            assert openai_request.messages[1].role == "assistant"
            assert openai_request.messages[1].content == "AI is artificial intelligence..."
            assert openai_request.messages[2].role == "user"
            assert openai_request.messages[2].content == "Can you give me examples?"


class TestStreamingIntegration:
    """Test streaming functionality with Gemini client."""
    
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
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_streaming_response
            
            # Test streaming with Gemini client
            stream = gemini_client.stream_generate_content(
                contents='Tell me a story'
            )
            
            # Collect streaming chunks
            chunks = []
            for chunk in stream:
                if chunk.text:
                    chunks.append(chunk.text)
            
            # Verify streaming worked
            assert len(chunks) > 0
            full_text = ''.join(chunks)
            assert "Hello" in full_text and "there" in full_text
            
            # Verify the request was for streaming
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            assert openai_request.stream == True


class TestErrorHandling:
    """Test error handling with Gemini client."""
    
    def test_authentication_error(self, proxy_config):
        """Test authentication error handling."""
        # Create server with auth enabled
        auth_config = proxy_config.copy()
        auth_config["disable_auth"] = False
        
        server = ProxyServer(auth_config, port=8002)
        server.start()
        
        try:
            # Create client with wrong API key
            # The API key and endpoint are configured globally by the fixture
            # This client is just to trigger the API call
            client = genai.GenerativeModel('gemini-pro')
            
            # This should raise an authentication error
            with pytest.raises(Exception) as exc_info:
                list(genai.list_models())
            
            # Should be a 401 error
            assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)
        
        finally:
            server.stop()
    
    def test_model_not_found_error(self, gemini_client, proxy_server):
        """Test handling of model not found errors."""
        error_response = {
            "message": "Model not found",
            "error": "invalid_model"
        }
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = error_response
            
            # This should handle the error gracefully
            response = gemini_client.generate_content(
                contents='Test message'
            )
            
            # The error response should be passed through
            # (Note: Actual error handling may vary based on client implementation)
            assert response is not None


class TestPerformanceAndReliability:
    """Test performance and reliability aspects."""
    
    def test_concurrent_requests(self, gemini_client, proxy_server):
        """Test handling multiple concurrent requests."""
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Concurrent response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
        }
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_response
            
            # Make multiple concurrent requests
            import concurrent.futures
            import threading
            
            def make_request(i):
                return gemini_client.models.generate_content(
                    model='test-model',
                    contents=f'Request {i}'
                )
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_request, i) for i in range(5)]
                results = [future.result() for future in concurrent.futures.as_completed(futures)]
            
            # All requests should succeed
            assert len(results) == 5
            for result in results:
                assert result.text == "Concurrent response"
            
            # Verify all requests were processed
            assert mock_chat.call_count == 5
    
    def test_large_content_handling(self, gemini_client, proxy_server):
        """Test handling of large content."""
        large_content = "A" * 10000  # 10KB of text
        
        mock_response = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Processed large content"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2500, "completion_tokens": 10, "total_tokens": 2510}
        }
        
        with patch('src.main.chat_completions', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_response
            
            response = gemini_client.models.generate_content(
                model='test-model',
                contents=large_content
            )
            
            # Should handle large content without issues
            assert response.text == "Processed large content"
            
            # Verify the large content was passed through
            mock_chat.assert_called_once()
            call_args = mock_chat.call_args[0]
            openai_request = call_args[0]
            assert openai_request.messages[0].content == large_content


if __name__ == "__main__":
    # Run specific tests for debugging
    pytest.main([__file__, "-v", "-s"])
