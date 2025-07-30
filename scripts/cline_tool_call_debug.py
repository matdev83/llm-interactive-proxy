#!/usr/bin/env python3
"""
Debug script to test how Cline tool calls would work with gemini-cli-batch backend.
This script simulates Cline's tool calling behavior and tests it against our proxy.
"""

import json
import requests
import time
import uuid
from typing import Dict, Any

def create_cline_tool_call_message(content: str) -> Dict[str, Any]:
    """Create a message that mimics Cline's tool call format"""
    return {
        "role": "user",
        "content": f"__CLINE_TOOL_CALL_MARKER__{content}__END_CLINE_TOOL_CALL_MARKER__"
    }

def create_openai_tool_call(content: str) -> Dict[str, Any]:
    """Create an OpenAI-style tool call that Cline would generate"""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": "attempt_completion",
                    "arguments": json.dumps({"result": content})
                }
            }
        ]
    }

def create_gemini_function_call(content: str) -> Dict[str, Any]:
    """Create a Gemini-style function call"""
    return {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "name": "attempt_completion",
                    "args": {
                        "result": content
                    }
                }
            }
        ]
    }

def test_cline_tool_call_with_proxy(proxy_url: str = "http://localhost:8080", model: str = "google-cli-batch"):
    """Test Cline tool call with the proxy server"""
    
    print(f"Testing Cline tool call with proxy at {proxy_url}")
    print(f"Using model: {model}")
    print("=" * 50)
    
    # Test 1: Simple tool call simulation
    print("\n1. Testing simple tool call simulation...")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-key"  # Using test key for local testing
    }
    
    # Create a request that mimics what Cline would send
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Create a file called test.txt with content 'Hello World'"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_12345678",
                        "type": "function",
                        "function": {
                            "name": "create_file",
                            "arguments": json.dumps({
                                "path": "test.txt",
                                "content": "Hello World"
                            })
                        }
                    }
                ]
            },
            {
                "role": "tool",
                "tool_call_id": "call_12345678",
                "content": "File created successfully"
            }
        ],
        "stream": False
    }
    
    try:
        response = requests.post(
            f"{proxy_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        print(f"Response Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print("Response received successfully!")
            print(json.dumps(result, indent=2))
        else:
            print(f"Error response: {response.text}")
            
    except Exception as e:
        print(f"Error making request: {e}")
    
    # Test 2: Test with streaming
    print("\n2. Testing with streaming...")
    
    payload["stream"] = True
    
    try:
        response = requests.post(
            f"{proxy_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
            stream=True
        )
        
        print(f"Streaming Response Status: {response.status_code}")
        if response.status_code == 200:
            print("Streaming response received:")
            for line in response.iter_lines():
                if line:
                    print(line.decode('utf-8'))
        else:
            print(f"Error response: {response.text}")
            
    except Exception as e:
        print(f"Error making streaming request: {e}")

def test_direct_gemini_batch_call():
    """Test direct interaction with Gemini batch API to understand the format"""
    print("\n3. Testing direct Gemini batch format...")
    
    # This would be the format that Gemini batch API expects
    batch_request = {
        "requests": [
            {
                "contents": {
                    "role": "user",
                    "parts": [{"text": "What is 2+2?"}]
                }
            }
        ]
    }
    
    print("Gemini batch request format:")
    print(json.dumps(batch_request, indent=2))

def test_cline_marker_handling():
    """Test how the proxy handles Cline markers specifically"""
    print("\n4. Testing Cline marker handling...")
    
    # Test the marker format that the proxy should detect and convert
    test_content = "File created successfully at /path/to/file.txt"
    marker_content = f"__CLINE_TOOL_CALL_MARKER__{test_content}__END_CLINE_TOOL_CALL_MARKER__"
    
    print("Cline marker format:")
    print(marker_content)
    print("\nThis should be detected by the proxy and converted to appropriate tool call format")

if __name__ == "__main__":
    print("Cline Tool Call Debug Script")
    print("This script tests how Cline tool calls would work with gemini-cli-batch backend")
    print("=" * 60)
    
    # Run tests
    test_cline_marker_handling()
    test_direct_gemini_batch_call()
    
    print("\nTo test with actual proxy:")
    print("1. Start the proxy server: python src/main.py")
    print("2. Run this script again to test actual requests")
    print("3. The proxy should handle Cline markers and convert them appropriately")
    
    # Only test with proxy if it's running
    try:
        response = requests.get("http://localhost:8080", timeout=1)
        test_cline_tool_call_with_proxy()
    except:
        print("\nProxy not running - skipping live tests")
    
    print("\nDebug script completed!")