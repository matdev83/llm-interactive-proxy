"""Quick diagnostic: test Ollama /v1/chat/completions streaming response."""

import asyncio

import httpx


async def main() -> None:
    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "gemma4:31b-cloud",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "stream": True,
    }
    headers = {"Content-Type": "application/json"}

    print(f"POST {url}")
    print(f"Model: {payload['model']}")
    print(f"Stream: {payload['stream']}")
    print("---")

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            print(f"Status: {resp.status_code}")
            print(f"Headers: {dict(resp.headers)}")
            print("---")
            chunk_count = 0
            async for line in resp.aiter_lines():
                chunk_count += 1
                if chunk_count <= 20:
                    print(f"Chunk {chunk_count}: {line[:200]}")
            print(f"---\nTotal lines received: {chunk_count}")


asyncio.run(main())
