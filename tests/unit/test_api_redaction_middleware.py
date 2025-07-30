"""
Unit tests for the API key redaction middleware system.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.responses import StreamingResponse

from src.request_middleware import (
    RedactionProcessor,
    RequestContext,
    RequestMiddleware,
    configure_redaction_middleware,
    get_request_middleware,
)
from src.response_middleware import (
    RequestContext as ResponseContext,
    ResponseMiddleware,
    ResponseProcessor,
    configure_loop_detection_middleware,
    get_response_middleware,
)
from src.security import APIKeyRedactor, ProxyCommandFilter


class TestRequestRedactionMiddleware:
    """Test the request redaction middleware."""
    
    def test_middleware_initialization(self):
        """Test that middleware initializes correctly."""
        middleware = RequestMiddleware()
        assert len(middleware.middleware_stack) == 0
    
    def test_add_processor(self):
        """Test adding processors to middleware."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        
        middleware.add_processor(processor)
        assert len(middleware.middleware_stack) == 1
        assert middleware.middleware_stack[0] is processor
    
    def test_remove_processor(self):
        """Test removing processors by type."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        
        middleware.add_processor(processor)
        assert len(middleware.middleware_stack) == 1
        
        middleware.remove_processor(RedactionProcessor)
        assert len(middleware.middleware_stack) == 0
    
    @pytest.mark.asyncio
    async def test_process_request_no_processors(self):
        """Test processing request with no processors."""
        middleware = RequestMiddleware()
        context = RequestContext("test-session", "openrouter", "gpt-4")
        messages = [{"role": "user", "content": "test message"}]
        
        result = await middleware.process_request(messages, context)
        assert result == messages
    
    @pytest.mark.asyncio
    async def test_process_request_with_redaction_disabled(self):
        """Test processing request when redaction is disabled."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=False,
            api_key_redactor=APIKeyRedactor(["SECRET"])
        )
        messages = [{"role": "user", "content": "test SECRET message"}]
        
        result = await middleware.process_request(messages, context)
        # Should not redact when disabled
        assert result[0]["content"] == "test SECRET message"
    
    @pytest.mark.asyncio
    async def test_process_request_with_redaction_enabled(self):
        """Test processing request with API key redaction."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=True,
            api_key_redactor=APIKeyRedactor(["SECRET"])
        )
        messages = [{"role": "user", "content": "test SECRET message"}]
        
        result = await middleware.process_request(messages, context)
        # Should redact API key
        assert result[0]["content"] == "test (API_KEY_HAS_BEEN_REDACTED) message"
    
    @pytest.mark.asyncio
    async def test_process_request_with_command_filtering(self):
        """Test processing request with command filtering."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=True,
            command_filter=ProxyCommandFilter("!/")
        )
        messages = [{"role": "user", "content": "test !/help message"}]
        
        result = await middleware.process_request(messages, context)
        # Should filter commands
        assert result[0]["content"] == "test message"
    
    @pytest.mark.asyncio
    async def test_process_request_with_both_redaction_and_filtering(self):
        """Test processing request with both API key redaction and command filtering."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=True,
            api_key_redactor=APIKeyRedactor(["SECRET"]),
            command_filter=ProxyCommandFilter("!/")
        )
        messages = [{"role": "user", "content": "test !/help SECRET message"}]
        
        result = await middleware.process_request(messages, context)
        # Should apply both redaction and filtering
        # Command filtering happens first, then API key redaction
        assert result[0]["content"] == "test (API_KEY_HAS_BEEN_REDACTED) message"
    
    @pytest.mark.asyncio
    async def test_process_request_with_multiple_messages(self):
        """Test processing multiple messages."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=True,
            api_key_redactor=APIKeyRedactor(["SECRET1", "SECRET2"])
        )
        messages = [
            {"role": "user", "content": "test SECRET1 message"},
            {"role": "assistant", "content": "response SECRET2 message"},
            {"role": "user", "content": "another message"}
        ]
        
        result = await middleware.process_request(messages, context)
        # Should redact API keys in all messages
        assert result[0]["content"] == "test (API_KEY_HAS_BEEN_REDACTED) message"
        assert result[1]["content"] == "response (API_KEY_HAS_BEEN_REDACTED) message"
        assert result[2]["content"] == "another message"
    
    @pytest.mark.asyncio
    async def test_process_request_with_message_parts(self):
        """Test processing messages with content parts."""
        middleware = RequestMiddleware()
        processor = RedactionProcessor()
        middleware.add_processor(processor)
        
        context = RequestContext(
            "test-session", 
            "openrouter", 
            "gpt-4",
            redaction_enabled=True,
            api_key_redactor=APIKeyRedactor(["SECRET"])
        )
        messages = [{
            "role": "user", 
            "content": [
                {"type": "text", "text": "test SECRET message"},
                {"type": "image_url", "image_url": {"url": "http://example.com/image.jpg"}}
            ]
        }]
        
        result = await middleware.process_request(messages, context)
        # Should redact API key in text parts
        assert result[0]["content"][0]["text"] == "test (API_KEY_HAS_BEEN_REDACTED) message"
        # Should not modify non-text parts
        assert result[0]["content"][1]["image_url"]["url"] == "http://example.com/image.jpg"


class TestResponseRedactionMiddleware:
    """Test the response redaction middleware."""
    
    def test_response_middleware_initialization(self):
        """Test that response middleware initializes correctly."""
        middleware = ResponseMiddleware()
        assert len(middleware.middleware_stack) == 0
    
    @pytest.mark.asyncio
    async def test_process_response_no_processors(self):
        """Test processing response with no processors."""
        middleware = ResponseMiddleware()
        context = ResponseContext("test-session", "openrouter", "gpt-4", False)
        response = {"test": "response"}
        
        result = await middleware.process_response(response, context)
        assert result == response
    
    @pytest.mark.asyncio
    async def test_process_non_streaming_response_with_redaction(self):
        """Test processing non-streaming response with API key redaction."""
        middleware = ResponseMiddleware()
        
        # Create API key redaction processor
        class APIKeyRedactionProcessor(ResponseProcessor):
            def __init__(self, api_key_redactor: APIKeyRedactor):
                self.api_key_redactor = api_key_redactor
            
            def should_process(self, response, context):
                return self.api_key_redactor is not None
            
            async def process(self, response, context):
                if isinstance(response, dict):
                    # Process non-streaming responses
                    for choice in response.get("choices", []):
                        if "message" in choice and "content" in choice["message"]:
                            content = choice["message"]["content"]
                            if content:
                                choice["message"]["content"] = self.api_key_redactor.redact(content)
                return response
        
        # Add processor to middleware
        redactor = APIKeyRedactor(["SECRET_RESPONSE"])
        processor = APIKeyRedactionProcessor(redactor)
        middleware.add_processor(processor)
        
        context = ResponseContext("test-session", "openrouter", "gpt-4", False)
        response = {
            "choices": [{
                "message": {
                    "content": "This is a response with SECRET_RESPONSE key"
                }
            }]
        }
        
        result = await middleware.process_response(response, context)
        # Should redact API key in response
        assert result["choices"][0]["message"]["content"] == "This is a response with (API_KEY_HAS_BEEN_REDACTED) key"
    
    @pytest.mark.asyncio
    async def test_process_streaming_response_with_redaction(self):
        """Test processing streaming response with API key redaction."""
        middleware = ResponseMiddleware()
        
        # Create API key redaction processor for streaming
        class APIKeyRedactionProcessor(ResponseProcessor):
            def __init__(self, api_key_redactor: APIKeyRedactor):
                self.api_key_redactor = api_key_redactor
            
            def should_process(self, response, context):
                return self.api_key_redactor is not None
            
            async def process(self, response, context):
                if isinstance(response, StreamingResponse):
                    # For streaming responses, we would wrap the stream to redact content
                    # This is a simplified version - in practice, we'd need to wrap the stream generator
                    pass
                return response
        
        # Add processor to middleware
        redactor = APIKeyRedactor(["SECRET_STREAM"])
        processor = APIKeyRedactionProcessor(redactor)
        middleware.add_processor(processor)
        
        context = ResponseContext("test-session", "openrouter", "gpt-4", True)
        
        # Create a mock streaming response
        async def mock_stream():
            yield b'data: {"choices": [{"delta": {"content": "stream SECRET_STREAM content"}}]}\n\n'
            yield b'data: [DONE]\n\n'
        
        response = StreamingResponse(mock_stream(), media_type="text/event-stream")
        
        result = await middleware.process_response(response, context)
        # Should return the same streaming response (stream wrapping would happen in the processor)
        assert isinstance(result, StreamingResponse)


class TestGlobalMiddlewareConfiguration:
    """Test global middleware configuration."""
    
    def test_configure_redaction_middleware(self):
        """Test configuring redaction middleware."""
        # Configure middleware
        configure_redaction_middleware()
        
        # Check that processor was added
        middleware = get_request_middleware()
        assert len(middleware.middleware_stack) > 0
        
        # Find redaction processor
        redaction_processors = [p for p in middleware.middleware_stack if isinstance(p, RedactionProcessor)]
        assert len(redaction_processors) == 1
    
    def test_reconfigure_redaction_middleware(self):
        """Test reconfiguring redaction middleware removes old processors."""
        # First configuration
        configure_redaction_middleware()
        
        middleware = get_request_middleware()
        initial_count = len(middleware.middleware_stack)
        
        # Second configuration should replace the first
        configure_redaction_middleware()
        
        # Should have same number of processors (old one replaced)
        assert len(middleware.middleware_stack) == initial_count
        
        # Should still have redaction processor
        redaction_processors = [p for p in middleware.middleware_stack if isinstance(p, RedactionProcessor)]
        assert len(redaction_processors) == 1


if __name__ == "__main__":
    pytest.main([__file__])