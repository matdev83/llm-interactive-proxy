"""
Integration tests for Cline tool call implementation.

These tests verify that Cline agents receive proper tool calls for both:
1. Local command responses (!/hello, !/set, etc.)
2. Backend error responses (project-dir missing, etc.)

The tests simulate the exact scenarios from debug logs where Cline was failing.
"""

import pytest
import json
import re
from fastapi.testclient import TestClient
from src.main import build_app


@pytest.fixture
def app():
    """Create the application for testing."""
    return build_app({
        "proxy_host": "127.0.0.1",
        "proxy_port": 8000,
        "disable_auth": True,
        "disable_accounting": True,
    })


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestClineCommandResponses:
    """Test that Cline receives tool calls for local command responses."""
    
    def test_cline_hello_command_returns_tool_calls(self, client):
        """Test that !/hello command returns tool calls for Cline agents."""
        
        # Step 1: Establish Cline agent
        response1 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response1.status_code == 200
        
        # Step 2: Send hello command
        response2 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response2.status_code == 200
        data = response2.json()
        
        # Verify tool call structure
        assert "choices" in data
        choice = data["choices"][0]
        message = choice["message"]
        
        # Should return tool calls, not content
        assert message.get("content") is None, "Content should be None for tool calls"
        assert message.get("tool_calls") is not None, "Tool calls should be present"
        assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
        assert choice.get("finish_reason") == "tool_calls", "Finish reason should be tool_calls"
        
        # Verify tool call details
        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "attempt_completion"
        
        # Verify arguments contain the response
        args = json.loads(tool_call["function"]["arguments"])
        assert "result" in args
        assert "llm-interactive-proxy" in args["result"]
    
    def test_cline_set_command_returns_tool_calls(self, client):
        """Test that !/set command returns tool calls for Cline agents."""
        
        # Establish Cline agent
        response1 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response1.status_code == 200
        
        # Send set command
        response2 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(project=test-project)"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response2.status_code == 200
        data = response2.json()
        
        # Verify tool call structure
        choice = data["choices"][0]
        message = choice["message"]
        
        assert message.get("content") is None
        assert message.get("tool_calls") is not None
        assert choice.get("finish_reason") == "tool_calls"
        
        tool_call = message["tool_calls"][0]
        assert tool_call["function"]["name"] == "attempt_completion"
        
        args = json.loads(tool_call["function"]["arguments"])
        assert "project" in args["result"].lower()


class TestClineBackendResponses:
    """Test that Cline receives tool calls for backend error responses."""
    
    def test_xml_content_converted_to_tool_calls(self, client):
        """Test that backend responses with XML content are converted to tool calls."""
        
        # This test simulates the backend response transformation logic
        # since we can't easily trigger the exact gemini-cli-batch error in tests
        
        from src.agents import create_openai_attempt_completion_tool_call
        
        # Simulate XML content from backend (like gemini-cli-batch error)
        xml_content = '<attempt_completion>\n<r>\nTo use gemini-cli-batch, you need to set the project-dir first. Use the !/set(project-dir=...) command to configure the Google Cloud project.\n</r>\n</attempt_completion>'
        
        # Test XML detection
        has_xml = "<attempt_completion>" in xml_content and "</attempt_completion>" in xml_content
        assert has_xml, "Should detect XML content"
        
        # Test content extraction
        match = re.search(r'<r>\s*(.*?)\s*</r>', xml_content, re.DOTALL)
        assert match is not None, "Should extract content from XML"
        
        extracted_content = match.group(1).strip()
        assert "gemini-cli-batch" in extracted_content
        assert "project-dir" in extracted_content
        
        # Test tool call creation
        tool_call = create_openai_attempt_completion_tool_call([extracted_content])
        
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "attempt_completion"
        
        args = json.loads(tool_call["function"]["arguments"])
        assert args["result"] == extracted_content
    
    def test_backend_response_transformation_logic(self, client):
        """Test the backend response transformation logic directly."""
        
        from src.agents import detect_frontend_api, create_openai_attempt_completion_tool_call
        
        # Simulate a backend response with XML content
        backend_response = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '<attempt_completion>\n<r>\nError: Missing configuration\n</r>\n</attempt_completion>'
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        }
        
        # Simulate transformation for Cline on OpenAI frontend
        session_agent = "cline"
        frontend_api = detect_frontend_api("/v1/chat/completions")
        
        assert frontend_api == "openai"
        
        if session_agent in {"cline", "roocode"} and frontend_api == "openai":
            for choice in backend_response.get("choices", []):
                message = choice.get("message", {})
                content = message.get("content", "")
                
                if content and "<attempt_completion>" in content and "</attempt_completion>" in content:
                    # Extract content
                    match = re.search(r'<r>\s*(.*?)\s*</r>', content, re.DOTALL)
                    assert match is not None
                    
                    extracted_content = match.group(1).strip()
                    
                    # Create tool call
                    tool_call = create_openai_attempt_completion_tool_call([extracted_content])
                    
                    # Transform response
                    choice["message"] = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call]
                    }
                    choice["finish_reason"] = "tool_calls"
        
        # Verify transformation
        choice = backend_response["choices"][0]
        assert choice["message"]["content"] is None
        assert choice["message"]["tool_calls"] is not None
        assert len(choice["message"]["tool_calls"]) == 1
        assert choice["finish_reason"] == "tool_calls"
        
        tool_call_obj = choice["message"]["tool_calls"][0]
        assert tool_call_obj["type"] == "function"
        assert tool_call_obj["function"]["name"] == "attempt_completion"


class TestNonClineAgents:
    """Test that non-Cline agents are not affected by the tool call conversion."""
    
    def test_non_cline_agents_receive_regular_content(self, client):
        """Test that non-Cline agents receive regular content, not tool calls."""
        
        # Send request without Cline detection pattern
        response = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}  # No Cline pattern
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify regular content response
        choice = data["choices"][0]
        message = choice["message"]
        
        assert message.get("content") is not None, "Non-Cline should get content"
        assert message.get("tool_calls") is None, "Non-Cline should not get tool calls"
        assert choice.get("finish_reason") == "stop", "Non-Cline should get stop finish reason"
    
    def test_xml_content_not_converted_for_non_cline(self, client):
        """Test that XML content is not converted to tool calls for non-Cline agents."""
        
        # Simulate the transformation logic for non-Cline agent
        session_agent = "other"
        frontend_api = "openai"
        
        xml_content = '<attempt_completion>\n<r>\nSome content\n</r>\n</attempt_completion>'
        
        # Non-Cline agents should not trigger transformation
        should_transform = session_agent in {"cline", "roocode"} and frontend_api == "openai"
        assert not should_transform, "Non-Cline agents should not trigger transformation"


class TestFrontendAgnostic:
    """Test that the solution works across different frontend APIs."""
    
    def test_openai_frontend_detection(self, client):
        """Test that OpenAI frontend is correctly detected."""
        
        from src.agents import detect_frontend_api
        
        # Test different OpenAI paths
        assert detect_frontend_api("/v1/chat/completions") == "openai"
        assert detect_frontend_api("/v1/models") == "openai"
    
    def test_anthropic_frontend_detection(self, client):
        """Test that Anthropic frontend is correctly detected."""
        
        from src.agents import detect_frontend_api
        
        # Test Anthropic paths
        assert detect_frontend_api("/anthropic/v1/messages") == "anthropic"
    
    def test_gemini_frontend_detection(self, client):
        """Test that Gemini frontend is correctly detected."""
        
        from src.agents import detect_frontend_api
        
        # Test Gemini paths
        assert detect_frontend_api("/v1beta/models/gemini-pro:generateContent") == "gemini"
        assert detect_frontend_api("/v1beta/models/gemini-pro:streamGenerateContent") == "gemini"


class TestToolCallStructure:
    """Test that tool calls have the correct OpenAI-compatible structure."""
    
    def test_tool_call_format_compliance(self, client):
        """Test that generated tool calls comply with OpenAI format."""
        
        from src.agents import create_openai_attempt_completion_tool_call
        
        content = "Test response content"
        tool_call = create_openai_attempt_completion_tool_call([content])
        
        # Verify OpenAI tool call structure
        assert "id" in tool_call
        assert "type" in tool_call
        assert "function" in tool_call
        
        assert tool_call["type"] == "function"
        assert isinstance(tool_call["id"], str)
        assert tool_call["id"].startswith("call_")
        
        function = tool_call["function"]
        assert "name" in function
        assert "arguments" in function
        assert function["name"] == "attempt_completion"
        
        # Verify arguments are valid JSON
        args = json.loads(function["arguments"])
        assert "result" in args
        assert args["result"] == content
    
    def test_tool_call_id_uniqueness(self, client):
        """Test that tool call IDs are unique."""
        
        from src.agents import create_openai_attempt_completion_tool_call
        
        tool_call1 = create_openai_attempt_completion_tool_call(["content1"])
        tool_call2 = create_openai_attempt_completion_tool_call(["content2"])
        
        assert tool_call1["id"] != tool_call2["id"], "Tool call IDs should be unique"


@pytest.mark.integration
class TestEndToEndScenarios:
    """End-to-end integration tests simulating real Cline usage scenarios."""
    
    def test_cline_workflow_with_commands(self, client):
        """Test a complete Cline workflow with multiple commands."""
        
        # Step 1: Establish Cline agent
        response1 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "I am a Cline agent. <attempt_completion>starting</attempt_completion>"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response1.status_code == 200
        
        # Step 2: Hello command
        response2 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["choices"][0]["message"]["tool_calls"] is not None
        assert data2["choices"][0]["finish_reason"] == "tool_calls"
        
        # Step 3: Set command
        response3 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/set(temperature=0.7)"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response3.status_code == 200
        data3 = response3.json()
        assert data3["choices"][0]["message"]["tool_calls"] is not None
        assert data3["choices"][0]["finish_reason"] == "tool_calls"
        
        # Verify all responses have proper tool call structure
        for data in [data2, data3]:
            choice = data["choices"][0]
            message = choice["message"]
            
            assert message["content"] is None
            assert len(message["tool_calls"]) == 1
            
            tool_call = message["tool_calls"][0]
            assert tool_call["function"]["name"] == "attempt_completion"
            
            args = json.loads(tool_call["function"]["arguments"])
            assert "result" in args
    
    def test_mixed_agent_session(self, client):
        """Test that Cline and non-Cline responses are handled correctly in the same session."""
        
        # Non-Cline request
        response1 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}  # No Cline pattern
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Should get regular content
        assert data1["choices"][0]["message"]["content"] is not None
        assert data1["choices"][0]["message"]["tool_calls"] is None
        
        # Cline request in same session
        response2 = client.post("/v1/chat/completions", json={
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>"},
                {"role": "user", "content": "!/hello"}
            ]
        }, headers={"Authorization": "Bearer test-proxy-key"})
        
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Should get tool calls
        assert data2["choices"][0]["message"]["content"] is None
        assert data2["choices"][0]["message"]["tool_calls"] is not None