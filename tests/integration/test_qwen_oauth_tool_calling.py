"""
Integration tests for Qwen OAuth backend tool calling functionality.

These tests verify that the Qwen OAuth backend properly supports:
1. Tool/function calling requests
2. Tool call responses
3. Multi-turn tool conversations
4. Agent-specific tool call transformations

Run with: pytest -m "integration and network" tests/integration/test_qwen_oauth_tool_calling.py
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import build_app

# Mark all tests in this module as integration and network tests
pytestmark = [pytest.mark.integration, pytest.mark.network]

# Check if OAuth credentials are available
def _has_qwen_oauth_credentials() -> bool:
    """Check if Qwen OAuth credentials are available."""
    home_dir = Path.home()
    creds_path = home_dir / ".qwen" / "oauth_creds.json"
    
    if not creds_path.exists():
        return False
    
    try:
        with open(creds_path, encoding='utf-8') as f:
            creds = json.load(f)
        return bool(creds.get('access_token') and creds.get('refresh_token'))
    except Exception:
        return False

QWEN_OAUTH_AVAILABLE = _has_qwen_oauth_credentials()


class TestQwenOAuthToolCalling:
    """Test tool calling functionality with Qwen OAuth backend."""
    
    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch('src.core.config.load_dotenv'):
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
            
            app = build_app()
            yield app
    
    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_basic_tool_calling(self, qwen_oauth_client):
        """Test basic tool calling functionality with Qwen OAuth backend."""
        # Define a simple tool for the model to use
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA"
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "description": "The temperature unit"
                            }
                        },
                        "required": ["location"]
                    }
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "What's the weather like in San Francisco?"
                }
            ],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        if response.status_code != 200:
            print(f"Error response: {response.status_code}")
            print(f"Error detail: {response.text}")
        
        assert response.status_code == 200
        
        result = response.json()
        assert "choices" in result
        assert len(result["choices"]) > 0
        
        choice = result["choices"][0]
        message = choice["message"]
        
        # The model should either:
        # 1. Make a tool call (preferred)
        # 2. Respond with text if it doesn't support tool calling
        
        if choice.get("finish_reason") == "tool_calls":
            # Model made a tool call
            assert message.get("tool_calls") is not None
            assert len(message["tool_calls"]) > 0
            
            tool_call = message["tool_calls"][0]
            assert tool_call["type"] == "function"
            assert tool_call["function"]["name"] == "get_weather"
            
            # Verify arguments can be parsed as JSON
            args = json.loads(tool_call["function"]["arguments"])
            assert "location" in args
            assert "san francisco" in args["location"].lower()
            
        else:
            # Model responded with text (tool calling might not be supported)
            assert message.get("content") is not None
            assert isinstance(message["content"], str)
            assert len(message["content"]) > 0
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_multi_turn_tool_conversation(self, qwen_oauth_client):
        """Test multi-turn conversation with tool calls."""
        # Define a calculator tool
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform basic arithmetic calculations",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Mathematical expression to evaluate, e.g. '2 + 3'"
                            }
                        },
                        "required": ["expression"]
                    }
                }
            }
        ]
        
        # First turn: User asks for calculation
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "Calculate 15 * 7 for me"
                }
            ],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        assert response.status_code == 200
        
        result = response.json()
        first_choice = result["choices"][0]
        
        # If the model made a tool call, simulate the tool response
        if first_choice.get("finish_reason") == "tool_calls":
            tool_calls = first_choice["message"]["tool_calls"]
            
            # Simulate tool execution
            tool_responses = []
            for tool_call in tool_calls:
                if tool_call["function"]["name"] == "calculate":
                    args = json.loads(tool_call["function"]["arguments"])
                    # Simple calculation simulation
                    if "15" in args["expression"] and "7" in args["expression"]:
                        result_value = "105"
                    else:
                        result_value = "Calculation result"
                    
                    tool_responses.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result_value
                    })
            
            # Second turn: Include tool responses
            messages = [
                {"role": "user", "content": "Calculate 15 * 7 for me"},
                first_choice["message"],  # Assistant's tool call
                *tool_responses  # Tool responses
            ]
            
            request_payload_2 = {
                "model": "qwen-oauth:qwen3-coder-plus",
                "messages": messages,
                "tools": tools,
                "max_tokens": 100,
                "temperature": 0.1,
                "stream": False
            }
            
            response_2 = qwen_oauth_client.post("/v1/chat/completions", json=request_payload_2)
            assert response_2.status_code == 200
            
            result_2 = response_2.json()
            second_choice = result_2["choices"][0]
            
            # The model should now provide a final answer
            assert second_choice["message"].get("content") is not None
            content = second_choice["message"]["content"]
            assert isinstance(content, str)
            assert len(content) > 0
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_tool_calling_with_streaming(self, qwen_oauth_client):
        """Test tool calling with streaming responses."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the web for information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "Search for information about Python programming"
                }
            ],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": True
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        
        # Collect streaming chunks
        chunks = []
        tool_calls_found = False
        
        for line in response.iter_lines():
            if line:
                line_str = line if isinstance(line, str) else line.decode('utf-8')
                if line_str.startswith('data: '):
                    data_part = line_str[6:]
                    if data_part.strip() == '[DONE]':
                        break
                    try:
                        chunk_data = json.loads(data_part)
                        chunks.append(chunk_data)
                        
                        # Check for tool calls in streaming chunks
                        if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                            delta = chunk_data['choices'][0].get('delta', {})
                            if 'tool_calls' in delta:
                                tool_calls_found = True
                                
                    except json.JSONDecodeError:
                        continue
        
        assert len(chunks) > 0, "Should receive streaming chunks"
        
        # If tool calls were found in streaming, verify the structure
        if tool_calls_found:
            # Find chunks with tool call data
            tool_call_chunks = [
                chunk for chunk in chunks 
                if 'choices' in chunk and len(chunk['choices']) > 0 
                and 'tool_calls' in chunk['choices'][0].get('delta', {})
            ]
            assert len(tool_call_chunks) > 0
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_tool_choice_none(self, qwen_oauth_client):
        """Test that tool_choice='none' prevents tool calling."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current time",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "What time is it?"
                }
            ],
            "tools": tools,
            "tool_choice": "none",  # Explicitly disable tool calling
            "max_tokens": 50,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        assert response.status_code == 200
        
        result = response.json()
        choice = result["choices"][0]
        message = choice["message"]
        
        # Should not make tool calls when tool_choice is "none"
        assert choice.get("finish_reason") != "tool_calls"
        assert message.get("tool_calls") is None
        assert message.get("content") is not None
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_tool_choice_specific_function(self, qwen_oauth_client):
        """Test tool_choice with specific function selection."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        },
                        "required": ["location"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_news",
                    "description": "Get news information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"}
                        },
                        "required": ["topic"]
                    }
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "I want to know about the weather and news"
                }
            ],
            "tools": tools,
            "tool_choice": {
                "type": "function",
                "function": {"name": "get_weather"}
            },
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        assert response.status_code == 200
        
        result = response.json()
        choice = result["choices"][0]
        
        # If tool calling is supported and tool_choice is respected,
        # should call the specified function
        if choice.get("finish_reason") == "tool_calls":
            message = choice["message"]
            assert message.get("tool_calls") is not None
            
            tool_call = message["tool_calls"][0]
            assert tool_call["function"]["name"] == "get_weather"


class TestQwenOAuthAgentToolCalling:
    """Test agent-specific tool calling behavior with Qwen OAuth backend."""
    
    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch('src.core.config.load_dotenv'):
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
            
            app = build_app()
            yield app
    
    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_cline_agent_tool_calls(self, qwen_oauth_client):
        """Test that Cline agent receives tool calls for command responses."""
        # Simulate Cline agent by setting User-Agent header
        headers = {"User-Agent": "Cline/1.0"}
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "!/hello"  # Proxy command that should return tool calls for Cline
                }
            ],
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post(
            "/v1/chat/completions", 
            json=request_payload,
            headers=headers
        )
        
        assert response.status_code == 200
        
        result = response.json()
        choice = result["choices"][0]
        message = choice["message"]
        
        # For Cline agents, command responses should be converted to tool calls
        if choice.get("finish_reason") == "tool_calls":
            assert message.get("content") is None
            assert message.get("tool_calls") is not None
            assert len(message["tool_calls"]) == 1
            
            tool_call = message["tool_calls"][0]
            assert tool_call["type"] == "function"
            assert tool_call["function"]["name"] == "attempt_completion"
            
            # Verify arguments contain the response
            args = json.loads(tool_call["function"]["arguments"])
            assert "result" in args
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_non_cline_agent_content_response(self, qwen_oauth_client):
        """Test that non-Cline agents receive content responses, not tool calls."""
        # Simulate non-Cline agent
        headers = {"User-Agent": "OpenAI-Python/1.0"}
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {
                    "role": "user", 
                    "content": "!/hello"  # Proxy command
                }
            ],
            "max_tokens": 100,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post(
            "/v1/chat/completions", 
            json=request_payload,
            headers=headers
        )
        
        assert response.status_code == 200
        
        result = response.json()
        choice = result["choices"][0]
        message = choice["message"]
        
        # For non-Cline agents, should receive content response
        assert message.get("content") is not None
        assert message.get("tool_calls") is None
        assert choice.get("finish_reason") == "stop"


class TestQwenOAuthToolCallingErrorHandling:
    """Test error handling in tool calling scenarios."""
    
    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch('src.core.config.load_dotenv'):
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
            
            app = build_app()
            yield app
    
    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_invalid_tool_definition(self, qwen_oauth_client):
        """Test handling of invalid tool definitions."""
        # Invalid tool definition (missing required fields)
        invalid_tools = [
            {
                "type": "function",
                "function": {
                    # Missing name and parameters
                    "description": "Invalid tool"
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {"role": "user", "content": "Use the tool"}
            ],
            "tools": invalid_tools,
            "max_tokens": 50,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        # Should either:
        # 1. Return 400 error for invalid tool definition
        # 2. Ignore invalid tools and proceed normally
        assert response.status_code in [200, 400, 422]
    
    @pytest.mark.skipif(not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available")
    def test_qwen_oauth_tool_calling_with_invalid_model(self, qwen_oauth_client):
        """Test tool calling with invalid model name."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_function",
                    "description": "Test function",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]
        
        request_payload = {
            "model": "qwen-oauth:invalid-model-name",
            "messages": [
                {"role": "user", "content": "Use the tool"}
            ],
            "tools": tools,
            "max_tokens": 50,
            "temperature": 0.1,
            "stream": False
        }
        
        response = qwen_oauth_client.post("/v1/chat/completions", json=request_payload)
        
        # Should return error for invalid model
        assert response.status_code in [400, 404, 422]


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-m", "integration and network"])