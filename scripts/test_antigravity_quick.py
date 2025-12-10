#!/usr/bin/env python
"""Quick test to verify Antigravity backend is working through the proxy."""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    """Test Antigravity backend through proxy."""
    from openai import AsyncOpenAI

    # Connect to local proxy
    client = AsyncOpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",
    )

    print("Testing Antigravity backend through proxy...")
    print("=" * 60)

    try:
        response = await client.chat.completions.create(
            model="gemini-oauth-antigravity:google/gemini-3-pro-high",
            messages=[
                {
                    "role": "user",
                    "content": "Say 'Hello from Antigravity!' and nothing else.",
                }
            ],
            stream=True,
        )

        print("Response (streaming):")
        full_text = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                full_text += content

        print("\n" + "=" * 60)
        print(f"Full response: {full_text}")
        print("SUCCESS!")
        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
