#!/usr/bin/env python3
"""
Simple test script for quick debugging with OpenAI client
"""

from openai import OpenAI

def quick_test():
    """Quick test with minimal setup"""
    client = OpenAI(
        base_url="http://127.0.0.1:8001/v1",
        api_key="dummy-key"
    )
    
    print("Quick test - sending simple request...")
    
    try:
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=50
        )
        
        print("✅ Success!")
        print(f"Response: {response.choices[0].message.content}")
        if response.usage:
            print(f"Tokens: {response.usage}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"Error type: {type(e).__name__}")

if __name__ == "__main__":
    quick_test() 