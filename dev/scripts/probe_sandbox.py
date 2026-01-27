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


async def probe():
    provider = AntigravitySQLiteCredentialProvider()
    creds = await provider.load()
    token = creds.get("access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
    }

    base_url = "https://daily-cloudcode-pa.sandbox.googleapis.com"

    async with httpx.AsyncClient() as client:
        # Load correct project
        load_url = f"{base_url}/v1internal:loadCodeAssist"
        load_payload = {
            "metadata": {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }
        }
        resp = await client.post(load_url, headers=headers, json=load_payload)
        project = resp.json().get("cloudaicompanionProject", "default")

        # Try gemini-flash-3-preview (User's specific suggestion)
        model = "gemini-flash-3-preview"
        print(
            f"\nCalling streamGenerateContent for model: {model} with project: {project}"
        )

        stream_url = f"{base_url}/v1internal:streamGenerateContent?alt=sse"

        request_body = {
            "project": project,
            "requestId": f"req_{int(__import__('time').time()*1000)}",
            "request": {
                "contents": [{"role": "user", "parts": [{"text": "Say 'OK'"}]}]
            },
            "model": model,
            "userAgent": "antigravity",
            "requestType": "agent",
        }

        resp = await client.post(stream_url, headers=headers, json=request_body)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")


if __name__ == "__main__":
    asyncio.run(probe())
