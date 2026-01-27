import asyncio
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path("c:/Users/Mateusz/source/repos/llm-interactive-proxy")
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.gemini_base.credential_providers.sqlite_provider import (
    AntigravitySQLiteCredentialProvider,
)


async def main():
    provider = AntigravitySQLiteCredentialProvider()
    creds = await provider.load()
    token = creds.get("access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
    }

    base_url = "https://cloudcode-pa.googleapis.com"

    async with httpx.AsyncClient() as client:
        # 1. Try with 'default' project
        project = "default"
        model = "gemini-flash-3-preview"
        print(f"\nProbing {model} on {base_url} with project: {project}")
        stream_url = f"{base_url}/v1internal:streamGenerateContent?alt=sse"
        request_body = {
            "project": project,
            "requestId": f"req_def_{int(__import__('time').time()*1000)}",
            "request": {"contents": [{"role": "user", "parts": [{"text": "OK"}]}]},
            "model": model,
            "userAgent": "antigravity",
            "requestType": "chat",
        }
        resp = await client.post(
            stream_url, headers=headers, json=request_body, timeout=10
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")


if __name__ == "__main__":
    asyncio.run(main())
