#!/usr/bin/env python3
"""
Demo script to verify OpenRouter backend functionality.

This script connects to the local LLM proxy and sends a request to the
OpenRouter backend using the 'mistralai/devstral-2512:free' model.

Prerequisites:
    - The LLM proxy server must be running on localhost:8000
    - The openai python package must be installed
"""

import os
from openai import OpenAI

def main():
    # Configuration
    # The proxy is running locally on port 8000
    base_url = "http://localhost:8000/v1"
    
    # We can use any non-empty string as the API key when talking to the proxy
    # The proxy will use its configured OpenRouter API key to talk to upstream
    api_key = os.getenv("OPENAI_API_KEY", "sk-proxy-demo-key")
    
    # The specific model requested for testing
    model = "openrouter:mistralai/devstral-2512:free"
    
    print(f"Connecting to proxy at {base_url}...")
    print(f"Requesting model: {model}")
    
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        
        print("\nSending chat completion request...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Hello! Please confirm you are receiving this message from OpenRouter. Be brief."}
            ],
            temperature=0.7,
            max_tokens=100
        )
        
        print("\nResponse received:")
        print("-" * 50)
        print(response.choices[0].message.content)
        print("-" * 50)
        print("\nSuccess! OpenRouter backend is functional.")
        
    except Exception as e:
        print(f"\nError occurred: {e}")
        if "User not found" in str(e):
             print("\n[!] Authentication Error: The proxy server is missing the OpenRouter API Key.")
             print("Please ensure the 'OPENROUTER_API_KEY' environment variable is set for the proxy server process.")
        else:
             print("\nPlease ensure the proxy server is running on localhost:8000")

if __name__ == "__main__":
    main()
