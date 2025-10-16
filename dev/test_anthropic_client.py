from __future__ import annotations

import os

# This has to be set before the first import of anthropic
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-dummy-key-for-testing"

import anthropic
from anthropic.types import MessageParam, ToolParam

# --- Configuration ---
# This is the base URL for the proxy's Anthropic-compatible API.
# The proxy's Anthropic-compatible endpoint.
BASE_URL = "http://127.0.0.1:8000/anthropic/"
# This model name is what a typical Anthropic client would send.
# The proxy should ignore this when --static-route is used and route to the specified backend instead.
MODEL_NAME = "claude-3-opus-20240229"

# --- Client Initialization ---
# We initialize the Anthropic client, pointing it to our local proxy.
# A dummy API key is required by the client, but the proxy will ignore it
# because --disable-auth is used.
client = anthropic.Anthropic(
    base_url=BASE_URL,
)

print(f"--- Attempting to connect to proxy at: {BASE_URL} ---")
print(f"--- Sending request for model: {MODEL_NAME} ---")

try:
    # --- Tool Definition ---
    # We define a simple tool that the model can call.
    tools: list[ToolParam] = [
        {
            "name": "get_weather",
            "description": "Get the current weather in a given location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    }
                },
                "required": ["location"],
            },
        }
    ]

    # --- Message History ---
    # We'll build the conversation history in this list.
    messages: list[MessageParam] = [
        {
            "role": "user",
            "content": "What is the weather like in Boston?",
        }
    ]

    # --- First API Call (Trigger Tool) ---
    print("\n--- Attempting to trigger tool use... ---")
    response_message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=150,
        messages=messages,
        tools=tools,
    )

    print("\n--- Tool call request successful. Response: ---")
    print(response_message.model_dump_json(indent=2))

    # Add assistant's response to history
    messages.append({"role": response_message.role, "content": response_message.content})

    # --- Tool Call Handling ---
    # Find the tool call in the response and add the result to the history.
    tool_call = next(
        (block for block in response_message.content if block.type == "tool_use"), None
    )

    if tool_call:
        print("\n--- Tool call detected. Preparing tool result... ---")
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": "The weather in Boston is 72 degrees and sunny.",
                    }
                ],
            }
        )

        # --- Second API Call (Send Tool Result) ---
        # This is the step where our new log should be triggered in the proxy.
        print("\n--- Sending tool result back to the model... ---")
        final_message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=100,
            messages=messages,
            tools=tools,
        )
        response_to_print = final_message
    else:
        print("\n--- No tool call was detected in the response. ---")
        response_to_print = response_message

    # --- Response Handling ---
    print("\n--- Success! Proxy responded successfully. ---\n")
    print("Final Response Content:")
    print(response_to_print.model_dump_json(indent=2))


except anthropic.APIConnectionError as e:
    print("\n--- FAILED: Could not connect to the proxy. ---")
    print("This usually means the proxy server is not running or the URL is incorrect.")
    print(f"Error details: {e.__cause__}")

except anthropic.APIStatusError as e:
    print(f"\n--- FAILED: Proxy returned an error (Status Code: {e.status_code}). ---")
    print(
        "This often indicates a server-side problem, like a routing issue or a backend error."
    )
    print(f"Response details: {e.response.text}")

except Exception as e:
    print("\n--- FAILED: An unexpected error occurred. ---")
    print(f"Error type: {type(e).__name__}")
    print(f"Error details: {e}")
