
import asyncio

import httpx


async def check_redirects():
    url = "https://opencode.ai/zen/v1/models"
    print(f"Checking URL: {url}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, follow_redirects=False)
        print(f"Status: {resp.status_code}")
        if resp.is_redirect:
            print(f"Redirect location: {resp.headers.get('location')}")
        
        # Also check POST endpoint
        url_post = "https://opencode.ai/zen/v1/chat/completions"
        print(f"Checking POST URL: {url_post}")
        resp_post = await client.post(url_post, follow_redirects=False)
        print(f"Status: {resp_post.status_code}")
        if resp_post.is_redirect:
            print(f"Redirect location: {resp_post.headers.get('location')}")

if __name__ == "__main__":
    asyncio.run(check_redirects())
