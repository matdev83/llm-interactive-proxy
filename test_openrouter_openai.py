#!/usr/bin/env python3
"""
Test script using OpenRouter backend with OpenAI client
"""

from openai import OpenAI

def test_openrouter_backend():
    """Test the proxy using OpenRouter backend"""
    
    client = OpenAI(
        base_url="http://127.0.0.1:8001/v1",
        api_key="dummy-key"
    )
    
    print("Testing OpenRouter backend through proxy...")
    print("=" * 50)
    
    try:
        # Test with OpenRouter model
        print("\n1. Testing OpenRouter model:")
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "Hello! What's 2+2?"}
            ],
            max_tokens=100
        )
        
        print("✅ Success!")
        print(f"Response: {response.choices[0].message.content}")
        print(f"Usage: {response.usage}")
        print(f"Model: {response.model}")
        
        # Test streaming
        print("\n2. Testing streaming response:")
        stream = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "Count from 1 to 3"}
            ],
            stream=True,
            max_tokens=50
        )
        
        print("Streaming response:")
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                print(chunk.choices[0].delta.content, end="", flush=True)
        print()  # New line after streaming
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"Error type: {type(e).__name__}")
        
        # Try to get more details from the error
        if hasattr(e, 'response'):
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text}")

if __name__ == "__main__":
    test_openrouter_backend() 