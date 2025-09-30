"""Quick test script to debug gemini-cli-oauth-personal backend"""
import asyncio
import httpx


async def test_backend():
    """Test a simple request to the backend"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            json={
                "model": "gemini-cli-oauth-personal:gemini-2.5-pro",
                "messages": [{"role": "user", "content": "Say 'Hello World'"}],
                "stream": False,
            },
            timeout=60.0,
        )
        print(f"Status code: {response.status_code}")
        print(f"Response headers: {response.headers}")
        print(f"Response content: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nParsed response: {data}")
            if "choices" in data and len(data["choices"]) > 0:
                print(f"Content: {data['choices'][0]['message']['content']}")
            else:
                print("ERROR: No choices in response!")
        else:
            print(f"ERROR: Request failed with status {response.status_code}")


if __name__ == "__main__":
    asyncio.run(test_backend())

