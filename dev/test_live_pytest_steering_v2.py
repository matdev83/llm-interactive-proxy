"""Improved live test with better response inspection.

Run with:
    .venv\Scripts\python.exe test_live_pytest_steering_v2.py
"""

import asyncio
import json
import sys

import httpx


PROXY_URL = "http://localhost:8000/v1/chat/completions"
# Using the requested model
MODEL = "gemini-oauth-plan:gemini-2.5-flash"
TIMEOUT = 120.0  # Increased timeout for potentially slower model


async def test_steering() -> None:
    """Test pytest full-suite steering with detailed response inspection."""
    
    print("=" * 80)
    print("PYTEST FULL-SUITE STEERING - DETAILED TEST")
    print("=" * 80)
    
    # Test 1: Full suite command
    print("\n[Test 1] Requesting to run 'pytest' (full suite)...")
    print("-" * 80)
    
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": "Please run pytest to verify all tests pass."
            }
        ],
        "tools": [
            {
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
        ],
        "temperature": 0.7,
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(PROXY_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP Error: {e.response.status_code} - {e.response.text}")
            return
        except Exception as e:
            print(f"❌ Error: {e}")
            return
    
    print("\n📋 RESPONSE ANALYSIS:")
    print("=" * 80)
    
    # Check response structure
    choices = data.get("choices", [])
    if not choices:
        print("❌ No choices in response!")
        print(json.dumps(data, indent=2))
        return
    
    choice = choices[0]
    message = choice.get("message", {})
    
    # Check for tool calls
    tool_calls = message.get("tool_calls", [])
    content = message.get("content")
    role = message.get("role")
    
    print(f"Role: {role}")
    print(f"Content: {content[:200] if content else 'None'}...")
    print(f"Tool calls: {len(tool_calls) if tool_calls else 0}")
    
    # Check metadata
    metadata = message.get("metadata", {})
    if metadata:
        print(f"\nMetadata keys: {list(metadata.keys())}")
        if "tool_call_swallowed" in metadata:
            print(f"  ✅ tool_call_swallowed: {metadata['tool_call_swallowed']}")
        if "steering_message" in metadata:
            print(f"  ✅ steering_message: {metadata['steering_message'][:100]}...")
        if "tool_call_reactor" in metadata:
            print(f"  ✅ tool_call_reactor: {metadata['tool_call_reactor']}")
        if "steering_retry_occurred" in metadata:
            print(f"  ✅ steering_retry_occurred: {metadata['steering_retry_occurred']}")
    
    # Analyze the result
    print("\n" + "=" * 80)
    print("VERDICT:")
    print("=" * 80)
    
    steering_retry = metadata.get("steering_retry_occurred")
    
    if steering_retry:
        print("✅ PASS: Steering retry occurred (verified via metadata).")
        if tool_calls:
            print("  Note: Response contains tool calls, meaning the model persisted after steering.")
            print("  This is acceptable behavior as per user requirements.")
    elif tool_calls:
        print("❌ FAIL: Response contains tool_calls and no steering retry was detected.")
        for i, tc in enumerate(tool_calls):
            func = tc.get("function", {})
            name = func.get("name")
            args = func.get("arguments", "{}")
            try:
                args_dict = json.loads(args) if isinstance(args, str) else args
            except:
                args_dict = {"raw": args}
            cmd = args_dict.get("command", "")
            print(f"  Tool Call #{i+1}: {name} - {cmd}")
    elif content and any(keyword in str(content).lower() for keyword in ["whole test suite", "entire test suite", "re-send", "consider running"]):
        print("✅ SUCCESS: Response contains steering message instead of tool call!")
        print(f"\nSteering message preview:")
        print("-" * 80)
        print(content[:500])
        print("-" * 80)
    elif role == "tool":
        print("✅ PARTIAL SUCCESS: Role is 'tool' (indicates swallowing)")
        print(f"Content: {content}")
    else:
        print("⚠️  UNCLEAR: Response doesn't match expected patterns")
        print(f"Content: {content}")
    
    # Print full response for debugging
    print("\n" + "=" * 80)
    print("FULL RESPONSE (for debugging):")
    print("=" * 80)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(test_steering())
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
