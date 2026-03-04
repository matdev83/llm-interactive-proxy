"""
Send a chat completion request to the proxy to reproduce the 400 error and print the raw backend error details.
"""

import asyncio
import json
import httpx

async def main():
    payload = {
        "model": "qwen-oauth:qwen/coder-model",
        "messages": [
            {"role": "user", "content": "Hi there. What this project is all about?"}
        ],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            print("Sending request to proxy...")
            response = await client.post(
                "http://127.0.0.1:8002/v1/chat/completions",
                json=payload
            )
            print(f"Status Code: {response.status_code}")
            print("Response Body:")
            print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error connecting to proxy: {e}")

if __name__ == "__main__":
    asyncio.run(main())
