from __future__ import annotations

import os

# This has to be set before the first import of anthropic
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-dummy-key-for-testing"

import anthropic

# --- Configuration ---
# This is the base URL for the proxy's Anthropic-compatible API.
# It runs on the same port as the main proxy (8000) but uses a specific path.
BASE_URL = "http://127.0.0.1:8000/anthropic/v1"
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
    # --- API Call ---
    # We send a message to the /v1/messages endpoint.
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=100,
        messages=[
            {
                "role": "user",
                "content": "Hello, proxy! Please confirm you are working and tell me what 2+2 is.",
            }
        ],
    )

    # --- Response Handling ---
    print("\n--- Success! Proxy responded successfully. ---\n")
    print("Response Content:")
    # Use .model_dump_json for clean, indented output
    print(message.model_dump_json(indent=2))

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
