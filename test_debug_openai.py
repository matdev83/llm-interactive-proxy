#!/usr/bin/env python3
"""
Debug test script to get detailed error information
"""

from openai import OpenAI
import httpx
import json

def test_with_detailed_errors():
    """Test with detailed error information"""
    
    print("Testing with detailed error information...")
    print("=" * 50)
    
    # Test 1: Direct HTTP request to see raw response
    print("\n1. Testing with raw HTTP request:")
    try:
        with httpx.Client() as client:
            response = client.post(
                "http://127.0.0.1:8001/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer dummy-key"
                },
                json={
                    "model": "gemini-1.5-flash",
                    "messages": [
                        {"role": "user", "content": "Hello"}
                    ],
                    "max_tokens": 50
                }
            )
            print(f"Status Code: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"HTTP Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: OpenAI client with more error details
    print("\n2. Testing with OpenAI client (detailed errors):")
    try:
        client = OpenAI(
            base_url="http://127.0.0.1:8001/v1",
            api_key="dummy-key"
        )
        
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[
                {"role": "user", "content": "Hello"}
            ],
            max_tokens=50
        )
        
        print("✅ Success!")
        print(f"Response: {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"❌ OpenAI Client Error: {e}")
        print(f"Error type: {type(e).__name__}")
        
        # Try to get more details from the error
        if hasattr(e, 'response'):
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        
        import traceback
        traceback.print_exc()

def test_models_endpoint_debug():
    """Test models endpoint with debug info"""
    print("\n3. Testing models endpoint:")
    
    try:
        with httpx.Client() as client:
            response = client.get(
                "http://127.0.0.1:8001/v1/models",
                headers={
                    "Authorization": "Bearer dummy-key"
                }
            )
            print(f"Models endpoint status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"Found {len(data.get('data', []))} models")
            else:
                print(f"Models endpoint error: {response.text}")
                
    except Exception as e:
        print(f"Models endpoint error: {e}")

if __name__ == "__main__":
    test_models_endpoint_debug()
    test_with_detailed_errors() 