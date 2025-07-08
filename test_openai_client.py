#!/usr/bin/env python3
"""
Test script using OpenAI client library to test the LLM Interactive Proxy
"""

import os
from openai import OpenAI
import json

def test_proxy_with_openai_client():
    """Test the proxy using OpenAI client library"""
    
    # Configure client to use our proxy
    client = OpenAI(
        base_url="http://127.0.0.1:8001/v1",
        api_key="dummy-key"  # Our proxy has auth disabled
    )
    
    print("Testing LLM Interactive Proxy with OpenAI client...")
    print("=" * 50)
    
    try:
        # Test 1: Simple chat completion
        print("\n1. Testing simple chat completion:")
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[
                {"role": "user", "content": "Hello! Can you tell me what 2+2 equals?"}
            ],
            max_tokens=100
        )
        
        print(f"Response: {response.choices[0].message.content}")
        print(f"Usage: {response.usage}")
        print(f"Model: {response.model}")
        
        # Test 2: Streaming response
        print("\n2. Testing streaming response:")
        stream = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[
                {"role": "user", "content": "Count from 1 to 5 slowly"}
            ],
            stream=True,
            max_tokens=50
        )
        
        print("Streaming response:")
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                print(chunk.choices[0].delta.content, end="", flush=True)
        print()  # New line after streaming
        
        # Test 3: Different model (OpenRouter)
        print("\n3. Testing OpenRouter model:")
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "What's the capital of France?"}
            ],
            max_tokens=50
        )
        
        print(f"Response: {response.choices[0].message.content}")
        print(f"Usage: {response.usage}")
        
        # Test 4: Test with commands (if supported)
        print("\n4. Testing proxy commands:")
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[
                {"role": "user", "content": "/help"}
            ],
            max_tokens=200
        )
        
        print(f"Command response: {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"Error occurred: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()

def test_models_endpoint():
    """Test the models endpoint"""
    print("\n5. Testing models endpoint:")
    
    client = OpenAI(
        base_url="http://127.0.0.1:8001/v1",
        api_key="dummy-key"
    )
    
    try:
        models = client.models.list()
        print(f"Available models ({len(models.data)}):")
        for model in models.data[:10]:  # Show first 10 models
            print(f"  - {model.id}")
        if len(models.data) > 10:
            print(f"  ... and {len(models.data) - 10} more models")
            
    except Exception as e:
        print(f"Error getting models: {e}")

if __name__ == "__main__":
    print("Make sure the proxy server is running on http://127.0.0.1:8001")
    print("Start it with: python -m src.main --default-backend gemini-cli-direct --host 127.0.0.1 --port 8001 --disable-auth")
    print()
    
    test_models_endpoint()
    test_proxy_with_openai_client() 