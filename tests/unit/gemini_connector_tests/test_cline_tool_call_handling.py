import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

from src.connectors.gemini_cli_batch import GeminiCliBatchConnector
import src.models as models

@pytest.mark.asyncio
async def test_cline_tool_call_conversion():
    """Test that Cline tool calls are properly converted for gemini-cli-batch backend"""
    
    # Create connector instance
    connector = GeminiCliBatchConnector()
    
    # Mock the parent class chat_completions method to return a response with Cline marker
    mock_response = ({
        "id": "test-response",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gemini-2.5-pro",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "__CLINE_TOOL_CALL_MARKER__File created successfully__END_CLINE_TOOL_CALL_MARKER__"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }, {"content-type": "application/json"})
    
    # Mock the parent class method
    with patch.object(connector, '_execute_gemini_cli', new=AsyncMock(return_value="__CLINE_TOOL_CALL_MARKER__File created successfully__END_CLINE_TOOL_CALL_MARKER__")):
        with patch('src.connectors.gemini_cli_direct.GeminiCliDirectConnector.chat_completions', return_value=mock_response):
            
            # Create a mock request
            request_data = models.ChatCompletionRequest(
                model="gemini-2.5-pro",
                messages=[models.ChatMessage(role="user", content="Create a file")],
                stream=False
            )
            
            # Test with Cline agent
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
                project="/tmp/test",
                agent="cline"
            )
            
            # Verify the result is converted to tool call format
            response_data, headers = result
            assert response_data["choices"][0]["message"]["content"] is None
            assert "tool_calls" in response_data["choices"][0]["message"]
            assert response_data["choices"][0]["finish_reason"] == "tool_calls"
            
            tool_calls = response_data["choices"][0]["message"]["tool_calls"]
            assert len(tool_calls) == 1
            assert tool_calls[0]["function"]["name"] == "attempt_completion"
            
            arguments = json.loads(tool_calls[0]["function"]["arguments"])
            assert "result" in arguments
            assert "File created successfully" in arguments["result"]

@pytest.mark.asyncio
async def test_non_cline_agent_unchanged():
    """Test that non-Cline agents are not affected by the conversion"""
    
    # Create connector instance
    connector = GeminiCliBatchConnector()
    
    # Mock response without Cline marker
    mock_response = ({
        "id": "test-response",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gemini-2.5-pro",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Regular response text"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }, {"content-type": "application/json"})
    
    with patch.object(connector, '_execute_gemini_cli', new=AsyncMock(return_value="Regular response text")):
        with patch('src.connectors.gemini_cli_direct.GeminiCliDirectConnector.chat_completions', return_value=mock_response):
            
            # Create a mock request
            request_data = models.ChatCompletionRequest(
                model="gemini-2.5-pro",
                messages=[models.ChatMessage(role="user", content="Tell me a joke")],
                stream=False
            )
            
            # Test with non-Cline agent
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
                project="/tmp/test",
                agent="other-agent"
            )
            
            # Verify the result is unchanged
            response_data, headers = result
            assert response_data["choices"][0]["message"]["content"] == "Regular response text"
            assert "tool_calls" not in response_data["choices"][0]["message"]
            assert response_data["choices"][0]["finish_reason"] == "stop"

@pytest.mark.asyncio
async def test_streaming_response_unchanged():
    """Test that streaming responses are not affected"""
    
    # Create connector instance
    connector = GeminiCliBatchConnector()
    
    # Create a mock streaming response
    mock_streaming_response = MagicMock()
    
    with patch.object(connector, '_execute_gemini_cli', new=AsyncMock(return_value="Streaming response")):
        with patch('src.connectors.gemini_cli_direct.GeminiCliDirectConnector.chat_completions', return_value=mock_streaming_response):
            
            # Create a mock request with streaming
            request_data = models.ChatCompletionRequest(
                model="gemini-2.5-pro",
                messages=[models.ChatMessage(role="user", content="Tell me a joke")],
                stream=True
            )
            
            # Test with Cline agent and streaming
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
                project="/tmp/test",
                agent="cline"
            )
            
            # Verify streaming response is returned as-is
            assert result == mock_streaming_response