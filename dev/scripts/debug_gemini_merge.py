"""Debug script: reproduce Gemini generationConfig merge behavior.

Run from project root with the venv interpreter:
./.venv/Scripts/python.exe dev/scripts/debug_gemini_merge.py
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

# Ensure project root is on sys.path so `src` imports resolve when run as a script
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import ChatMessage, ChatRequest


async def main() -> None:
    client = AsyncMock()
    backend = GeminiBackend(client)

    req = ChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Test")],
        temperature=0.7,
        extra_body={"generationConfig": {"temperature": 0.3}},
    )

    processed = [ChatMessage(role="user", content="Test")]

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]
    }
    mock_response.headers = {}

    backend.client.post = AsyncMock(return_value=mock_response)

    # Call chat_completions which should build payload and call client.post
    await backend.chat_completions(
        request_data=req,
        processed_messages=processed,
        effective_model="gemini-2.5-pro",
        gemini_api_base_url="https://generativelanguage.googleapis.com",
        api_key="test-key",
    )

    # Inspect what was sent
    called = backend.client.post.call_args
    print("client.post.call_args:", called)
    payload = called[1]["json"]
    print("payload generationConfig:", payload.get("generationConfig"))


if __name__ == "__main__":
    asyncio.run(main())
