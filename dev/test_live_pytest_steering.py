"""Live integration test for pytest full-suite steering feature.

This script tests the feature against a running proxy server.

Prerequisites:
    - Proxy server must be running with --enable-pytest-full-suite-steering
    - Example: python -m src.core.cli --enable-pytest-full-suite-steering --default-backend gemini-oauth-plan:gemini-2.5-flash

Run with:
    .venv\Scripts\python.exe test_live_pytest_steering.py
"""

import asyncio
import json
import sys
from typing import Any

import httpx


PROXY_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "zenmux:google/gemini-2.5-pro-free"
TIMEOUT = 60.0


async def send_chat_request(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Send a chat completion request to the proxy."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
    }
    
    if tools:
        payload["tools"] = tools
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(PROXY_URL, json=payload)
        response.raise_for_status()
        return response.json()


def create_bash_tool() -> dict[str, Any]:
    """Create a bash tool definition."""
    return {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }


async def test_full_suite_steering() -> None:
    """Test the pytest full-suite steering feature."""
    
    print("=" * 80)
    print("LIVE PYTEST FULL-SUITE STEERING TEST")
    print("=" * 80)
    print(f"Proxy URL: {PROXY_URL}")
    print(f"Model: {MODEL}")
    print()
    
    # Test 1: Request to run full pytest suite
    print("[Test 1] Sending request to run 'pytest' (full suite)...")
    print("-" * 80)
    
    messages = [
        {
            "role": "user",
            "content": "Please run pytest to verify all tests pass."
        }
    ]
    
    tools = [create_bash_tool()]
    
    try:
        response1 = await send_chat_request(messages, tools)
        
        # Check if model tried to call bash tool
        choice = response1.get("choices", [{}])[0]
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls", [])
        
        if tool_calls:
            print("✓ Model attempted to call tool")
            for i, tool_call in enumerate(tool_calls):
                func = tool_call.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", "{}")
                
                # Parse arguments
                try:
                    args_dict = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    args_dict = {"raw": args}
                
                command = args_dict.get("command", args_dict.get("raw", ""))
                
                print(f"\n  Tool Call #{i+1}:")
                print(f"    Name: {name}")
                print(f"    Command: {command}")
                
                # Check if it's a full pytest suite command
                if "pytest" in command.lower() and not any(x in command for x in ["tests/", "test_", ".py", "-k", "--lf"]):
                    print(f"    ⚠️  DETECTED: Full suite pytest command!")
                    print(f"    Expected: Proxy should swallow this and return steering message")
                else:
                    print(f"    ℹ️  This appears to be a targeted test command")
        else:
            # No tool calls - check if there's a text response (steering message)
            content = message.get("content", "")
            if content:
                print("✓ Model returned text response instead of tool call")
                print(f"\nResponse content (first 500 chars):")
                print("-" * 80)
                print(content[:500])
                if len(content) > 500:
                    print("... (truncated)")
                print("-" * 80)
                
                # Check if it looks like a steering message
                steering_keywords = [
                    "whole test suite",
                    "entire test suite", 
                    "full suite",
                    "lengthy process",
                    "re-send",
                    "consider running",
                    "specific tests"
                ]
                
                if any(keyword.lower() in content.lower() for keyword in steering_keywords):
                    print("\n✅ SUCCESS: Response contains steering message keywords!")
                    print("   The pytest full-suite steering feature is WORKING!")
                else:
                    print("\n⚠️  WARNING: Response doesn't contain expected steering keywords")
                    print("   The feature might not be working as expected")
            else:
                print("❌ UNEXPECTED: No tool calls and no content in response")
        
        print("\n" + "=" * 80)
        print("Full Response:")
        print(json.dumps(response1, indent=2))
        print("=" * 80)
        
    except httpx.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"   Is the proxy server running with --enable-pytest-full-suite-steering?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Test 2: Request to run targeted test
    print("\n\n[Test 2] Sending request to run targeted test...")
    print("-" * 80)
    
    messages2 = [
        {
            "role": "user",
            "content": "Please run pytest tests/unit/test_cli.py to verify the CLI tests pass."
        }
    ]
    
    try:
        response2 = await send_chat_request(messages2, tools)
        
        choice = response2.get("choices", [{}])[0]
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls", [])
        
        if tool_calls:
            print("✓ Model attempted to call tool (expected for targeted test)")
            for i, tool_call in enumerate(tool_calls):
                func = tool_call.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", "{}")
                
                try:
                    args_dict = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    args_dict = {"raw": args}
                
                command = args_dict.get("command", args_dict.get("raw", ""))
                
                print(f"\n  Tool Call #{i+1}:")
                print(f"    Name: {name}")
                print(f"    Command: {command}")
                
                if "test_cli.py" in command or "tests/unit" in command:
                    print(f"    ✅ CORRECT: Targeted test command passed through!")
                else:
                    print(f"    ⚠️  Unexpected command format")
        else:
            content = message.get("content", "")
            print(f"⚠️  Model returned text instead of tool call:")
            print(f"    {content[:200]}...")
        
    except Exception as e:
        print(f"❌ Error in Test 2: {e}")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


async def main() -> None:
    """Main entry point."""
    try:
        await test_full_suite_steering()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
