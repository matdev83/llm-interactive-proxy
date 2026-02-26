#!/usr/bin/env python3
"""Test script to verify if kiro-oauth-auto handles large contexts properly."""

import asyncio
import sys
from pathlib import Path

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


PROXY_URL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "kiro-oauth-auto:amazon/claude-sonnet-4.6"


async def test_context_size(token_count: int) -> tuple[int, bool, str]:
    """Test a specific context size.
    
    Args:
        token_count: Approximate token count to send
    
    Returns:
        (token_count, success, response_or_error)
    """
    # Generate a message with approximately token_count tokens
    # Rough estimate: 1 token ~= 4 characters for English text
    char_count = token_count * 4
    message_content = "x " * (char_count // 2)  # "x " is ~2 characters
    
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": message_content[:char_count]}],
        "max_tokens": 50,
        "stream": False,
    }
    
    print(f"  Payload size: ~{len(message_content[:char_count])} chars (~{token_count} tokens)")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(PROXY_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return (token_count, True, f"SUCCESS: Got response")
            else:
                error_text = response.text[:300]
                return (token_count, False, f"HTTP {response.status_code}: {error_text}")
    except Exception as e:
        return (token_count, False, f"EXCEPTION: {type(e).__name__}: {str(e)[:200]}")


async def main():
    """Run context size tests."""
    print(f"Testing large contexts with {MODEL}")
    print(f"Proxy: {PROXY_URL}")
    print("=" * 80)
    
    # Test progressively larger contexts
    # The Quality Verifier sent 50,523 tokens
    test_sizes = [
        1000,    # Small
        5000,    # Medium
        10000,   # Large
        25000,   # Very large
        50000,   # Quality Verifier size
        60000,   # Beyond QV
    ]
    
    results = []
    for size in test_sizes:
        print(f"\nTesting: ~{size} tokens")
        token_count, success, message = await test_context_size(size)
        results.append((token_count, success, message))
        print(f"  {message}")
        
        # Stop if we hit a failure
        if not success:
            print(f"\n  STOPPED: Found failure threshold at ~{size} tokens")
            break
    
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)
    
    max_working = 0
    for token_count, success, message in results:
        status = "[WORKS]" if success else "[FAILS]"
        print(f"{status}: ~{token_count} tokens")
        if success:
            max_working = max(max_working, token_count)
    
    print("\n" + "=" * 80)
    if max_working > 0:
        print(f"Maximum working context: ~{max_working} tokens")
        if max_working < 50000:
            print(f"NOTE: Quality Verifier tried to send 50,523 tokens")
            print(f"      This exceeds the working limit!")
    else:
        print("WARNING: Even small contexts are failing!")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
