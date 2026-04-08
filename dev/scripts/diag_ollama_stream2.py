import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream(
            "POST",
            "http://localhost:11434/v1/chat/completions",
            json={
                "model": "gemma4:31b-cloud",
                "messages": [{"role": "user", "content": "Say hi"}],
                "stream": True,
            },
            headers={"Content-Type": "application/json"},
        ) as resp:
            print("Status:", resp.status_code)
            count = 0
            async for line in resp.aiter_lines():
                count += 1
                if count <= 10:
                    print(f"  [{count}] {line[:200]}")
            print("Total lines:", count)


asyncio.run(main())
