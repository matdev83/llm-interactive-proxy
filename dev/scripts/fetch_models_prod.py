import asyncio
import httpx
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Mateusz/source/repos/llm-interactive-proxy")
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.gemini_base.credential_providers.sqlite_provider import AntigravitySQLiteCredentialProvider

async def main():
    provider = AntigravitySQLiteCredentialProvider()
    creds = await provider.load()
    token = creds.get("access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64"
    }

    base_url = "https://cloudcode-pa.googleapis.com"
    
    async with httpx.AsyncClient() as client:
        print("\nCalling fetchAvailableModels on Production...")
        models_url = f"{base_url}/v1internal:fetchAvailableModels"
        resp = await client.get(models_url, headers=headers)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            models_data = resp.json()
            models = models_data.get("models", {})
            print(f"Found {len(models)} models.")
            for name in sorted(models.keys()):
                print(f"- {name}")
        else:
            print(f"Response: {resp.text}")

if __name__ == "__main__":
    asyncio.run(main())
