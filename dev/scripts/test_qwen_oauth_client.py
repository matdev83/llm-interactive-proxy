#!/usr/bin/env python3
"""Test client for qwen-oauth backend."""

import json
import sys
import time

import requests

# Unicode handling for Windows
def safe_print(msg: str):
    """Print message handling encoding issues on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        # Replace problematic characters
        msg = msg.replace("✓", "[OK]").replace("✗", "[FAIL]").replace("⚠", "[WARN]")
        print(msg)


def test_proxy_health(base_url: str = "http://127.0.0.1:8000"):
    """Test if the proxy is running."""
    safe_print("=" * 60)
    safe_print("Testing qwen-oauth backend via LLM Proxy")
    safe_print("=" * 60)
    
    # Test 1: Check if proxy is up (try /v1/models endpoint)
    safe_print("\n1. Checking proxy health...")
    try:
        response = requests.get(f"{base_url}/v1/models", timeout=5)
        safe_print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            safe_print("   [OK] Proxy is running")
            return True
        else:
            safe_print(f"   [FAIL] Proxy returned status {response.status_code}")
            safe_print(f"   Response: {response.text[:200]}")
            # Still return True if we got a response (proxy is up)
            return True
    except requests.exceptions.ConnectionError:
        safe_print("   [FAIL] Cannot connect to proxy on port 8000")
        safe_print("   Make sure the proxy is running:")
        safe_print("   ./.venv/Scripts/python.exe -m src.core.cli")
        return False
    except Exception as e:
        safe_print(f"   [FAIL] Error: {e}")
        return False
    
    return True


def test_available_models(base_url: str = "http://127.0.0.1:8000"):
    """Test getting available models."""
    safe_print("\n2. Checking available models...")
    try:
        response = requests.get(f"{base_url}/v1/models", timeout=10)
        safe_print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            models = data.get("data", [])
            safe_print(f"   Found {len(models)} models")
            
            # Check for qwen models
            qwen_models = [m for m in models if "qwen" in m.get("id", "").lower()]
            if qwen_models:
                safe_print(f"   [OK] Found {len(qwen_models)} Qwen model(s):")
                for model in qwen_models:
                    safe_print(f"     - {model.get('id')}")
            else:
                safe_print("   [WARN] No Qwen models found in model list")
                safe_print("   Available models:")
                for model in models[:5]:
                    safe_print(f"     - {model.get('id')}")
        else:
            safe_print(f"   [FAIL] Failed to get models: {response.text}")
    except Exception as e:
        safe_print(f"   [FAIL] Error: {e}")


def test_chat_completion(base_url: str = "http://127.0.0.1:8000", api_key: str = "test-key"):
    """Test chat completion with qwen-oauth backend."""
    safe_print("\n3. Testing chat completion (non-streaming)...")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": "qwen-oauth:qwen3-coder-plus",
        "messages": [
            {"role": "user", "content": "Say 'Hello from qwen-oauth test' and nothing else."}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    safe_print(f"   Request: POST {base_url}/v1/chat/completions")
    safe_print(f"   Model: {payload['model']}")
    first_message = payload['messages'][0]
    message_content = first_message['content']
    safe_print(f"   Message: {message_content[:50]}...")
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        elapsed = time.time() - start_time
        
        safe_print(f"   Status: {response.status_code}")
        safe_print(f"   Time: {elapsed:.2f}s")
        
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "") if isinstance(message, dict) else ""
                safe_print(f"   [OK] Response received:")
                safe_print(f"     {content[:200]}")
                return True
            else:
                safe_print(f"   [FAIL] No choices in response")
                safe_print(f"   Response: {json.dumps(data, indent=2)[:500]}")
        else:
            safe_print(f"   [FAIL] Request failed")
            try:
                error_data = response.json()
                safe_print(f"   Error: {json.dumps(error_data, indent=2)}")
            except:
                safe_print(f"   Response: {response.text[:500]}")
                
    except requests.exceptions.Timeout:
        safe_print("   [FAIL] Request timed out after 60s")
    except Exception as e:
        safe_print(f"   [FAIL] Error: {e}")
    
    return False


def test_streaming_chat(base_url: str = "http://127.0.0.1:8000", api_key: str = "test-key"):
    """Test streaming chat completion."""
    safe_print("\n4. Testing streaming chat completion...")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": "qwen-oauth:qwen3-coder-plus",
        "messages": [
            {"role": "user", "content": "Count from 1 to 3"}
        ],
        "max_tokens": 50,
        "stream": True
    }
    
    safe_print(f"   Request: POST {base_url}/v1/chat/completions (streaming)")
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            stream=True,
            timeout=60
        )
        
        safe_print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            content_chunks = []
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith('data: '):
                        data = line_text[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get('choices', [{}])[0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                content_chunks.append(content)
                        except json.JSONDecodeError:
                            pass
            
            elapsed = time.time() - start_time
            full_content = ''.join(content_chunks)
            safe_print(f"   [OK] Streaming completed in {elapsed:.2f}s")
            safe_print(f"   Content: {full_content[:200]}")
            return True
        else:
            safe_print(f"   [FAIL] Request failed: {response.text[:500]}")
            
    except requests.exceptions.Timeout:
        safe_print("   [FAIL] Request timed out after 60s")
    except Exception as e:
        safe_print(f"   [FAIL] Error: {e}")
    
    return False


def main():
    base_url = "http://127.0.0.1:8000"
    api_key = "test-key"  # Update this if your proxy requires a specific key
    
    # Check proxy health
    if not test_proxy_health(base_url):
        safe_print("\n" + "=" * 60)
        safe_print("FAILED: Proxy is not accessible")
        safe_print("=" * 60)
        sys.exit(1)
    
    # Check available models
    test_available_models(base_url)
    
    # Test chat completion
    success = test_chat_completion(base_url, api_key)
    
    # Test streaming (only if non-streaming worked)
    if success:
        test_streaming_chat(base_url, api_key)
    
    safe_print("\n" + "=" * 60)
    if success:
        safe_print("Test completed - qwen-oauth backend appears functional")
    else:
        safe_print("Test failed - qwen-oauth backend may be defunct")
    safe_print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
