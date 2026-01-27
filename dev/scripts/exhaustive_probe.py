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


async def probe_model(client, base_url, headers, project, model, request_type="agent"):
    print(f"\nProbing {model} ({request_type}) on {base_url}...")
    stream_url = f"{base_url}/v1internal:streamGenerateContent?alt=sse"
    request_body = {
        "project": project,
        "requestId": f"probe_{int(__import__('time').time()*1000)}",
        "request": {"contents": [{"role": "user", "parts": [{"text": "OK"}]}]},
        "model": model,
        "userAgent": "antigravity",
        "requestType": request_type,
    }
    try:
        resp = await client.post(
            stream_url, headers=headers, json=request_body, timeout=10
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("SUCCESS!")
            return True
        else:
            print(f"Error: {resp.text}")
            return False
    except Exception as e:
        print(f"Exception: {e}")
        return False


async def main():
    provider = AntigravitySQLiteCredentialProvider()
    creds = await provider.load()
    token = creds.get("access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
    }

    prod_url = "https://cloudcode-pa.googleapis.com"
    sandbox_url = "https://daily-cloudcode-pa.sandbox.googleapis.com"

    async with httpx.AsyncClient() as client:
        # Get project from PROD
        resp = await client.post(
            f"{prod_url}/v1internal:loadCodeAssist",
            headers=headers,
            json={"metadata": {}},
        )
        project = resp.json().get("cloudaicompanionProject", "default")
        print(f"Project: {project}")

        models = [
            "gemini-flash-3-preview",
            "gemini-3-flash-preview",
            "gemini-3-flash",
            "gemini-flash-3",
        ]

        for model in models:
            for rtype in ["agent", "chat"]:
                await probe_model(client, prod_url, headers, project, model, rtype)
                await probe_model(client, sandbox_url, headers, project, model, rtype)


if __name__ == "__main__":
    asyncio.run(main())
