#!/usr/bin/env python3
"""
Test script with a commonly available OpenRouter model
"""

from openai import OpenAI

def test_with_available_model():
    """Test with a commonly available model"""
    
    client = OpenAI(
        base_url="http://127.0.0.1:8001/v1",
        api_key="dummy-key"
    )
    
    print("Testing with commonly available models...")
    print("=" * 50)
    
    # Try a few different models that are commonly available
    models_to_try = [
        "anthropic/claude-3-haiku",
        "meta-llama/llama-3.2-3b-instruct:free",
        "microsoft/phi-3-mini-128k-instruct:free",
        "google/gemma-2-9b-it:free"
    ]
    
    for model in models_to_try:
        print(f"\nTesting model: {model}")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": "Hello! What's 2+2?"}
                ],
                max_tokens=50
            )
            
            print("✅ Success!")
            print(f"Response: {response.choices[0].message.content}")
            print(f"Usage: {response.usage}")
            print(f"Model: {response.model}")
            break  # Stop after first successful model
            
        except Exception as e:
            print(f"❌ Error with {model}: {e}")
            continue
    
    else:
        print("\n❌ No models worked. This might be due to API key issues or rate limits.")

if __name__ == "__main__":
    test_with_available_model() 