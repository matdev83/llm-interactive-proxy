#!/usr/bin/env python3
"""
Direct OpenRouter connection demo script.

This script connects directly to OpenRouter API (bypassing the proxy)
to verify that the API key and model "mistralai/devstral-2512:free" are working.

Prerequisites:
    - OPENROUTER_API_KEY environment variable must be set (or in .env file)
    - openai python package
    - python-dotenv package
"""

import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

def main():
    # Load environment variables from .env if present
    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY")
    
    if not api_key:
        print("Error: OPENROUTER_API_KEY environment variable is not set.")
        print("Please set it or add it to a .env file.")
        sys.exit(1)

    # Mask key for display
    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print(f"OPENROUTER_API_KEY found: {masked_key} (length: {len(api_key)})")

    base_url = "https://openrouter.ai/api/v1"
    model = "mistralai/devstral-2512:free"
    
    print(f"Connecting directly to {base_url}...")
    print(f"Requesting model: {model}")

    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        # OpenRouter specific headers (optional but recommended)
        extra_headers = {
            "HTTP-Referer": "http://localhost:8000", # Site URL for rankings
            "X-Title": "DirectDemoScript",           # App title for rankings
        }

        print("\nSending chat completion request...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Hello! Confirm you are receiving this message directly from the demo script. Be brief."}
            ],
            extra_headers=extra_headers,
            temperature=0.7,
            max_tokens=100
        )

        print("\nResponse received:")
        print("-" * 50)
        print(response.choices[0].message.content)
        print("-" * 50)
        print("\nSuccess! Direct connection to OpenRouter is working.")

    except Exception as e:
        print(f"\nError occurred: {e}")
        if "401" in str(e):
             print("\n[!] Authentication Failed: The API Key appears to be invalid or rejected by OpenRouter.")
        elif "404" in str(e):
             print("\n[!] Not Found: The model route might be incorrect or unavailable.")

if __name__ == "__main__":
    main()
