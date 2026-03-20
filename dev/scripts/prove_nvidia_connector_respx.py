#!/usr/bin/env python3
"""In-process proof of NvidiaConnector: ``list_models()`` + ``chat_completions()`` with mocked NVIDIA upstream.

Uses ``respx`` to stub ``https://integrate.api.nvidia.com/v1/models`` and
``.../chat/completions`` so this runs **without** a real ``NVIDIA_API_KEY`` and
exercises the same code paths as production (``OpenAIConnector.list_models``,
canonical chat, payload cleaning).

Run from repo root::

    ./.venv/Scripts/python.exe dev/scripts/prove_nvidia_connector_respx.py

For live wire proof with your account, use ``prove_nvidia_connector_live.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import respx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.nvidia import NvidiaConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

_BASE = "https://integrate.api.nvidia.com/v1"
# Matches NVIDIA Build default demo model (mock only; see prove_nvidia_connector_live.py).
_DEMO_MODEL = "stepfun-ai/step-3.5-flash"


def _models_json() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": _DEMO_MODEL,
                "object": "model",
                "created": 1,
                "owned_by": "stepfun-ai",
            },
            {
                "id": "meta/llama3-8b-instruct",
                "object": "model",
                "created": 2,
                "owned_by": "meta",
            },
        ],
    }


def _chat_json() -> dict:
    return {
        "id": "chatcmpl-demo",
        "object": "chat.completion",
        "created": 1700000000,
        "model": _DEMO_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "OK - Step-3.5-Flash via NvidiaConnector (mocked upstream)."
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30},
    }


async def _run() -> int:
    async with respx.mock(assert_all_called=False) as router:
        router.get(f"{_BASE}/models").mock(
            return_value=httpx.Response(200, json=_models_json())
        )
        router.post(f"{_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_json())
        )

        async with httpx.AsyncClient(timeout=30.0) as http:
            connector = NvidiaConnector(
                http, AppConfig(), translation_service=TranslationService()
            )
            await connector.initialize(api_key="respx-mock-nvidia-key")

            print("=== 1) NvidiaConnector.list_models() ===")
            listing = await connector.list_models()
            ids = [m.id for m in listing.data]
            print(json.dumps({"object": listing.object, "model_ids": ids}, indent=2))

            print("\n=== 2) get_available_models() (cached from init + list) ===")
            print(json.dumps(connector.get_available_models(), indent=2))

            print(f"\n=== 3) chat_completions (non-stream), model={_DEMO_MODEL!r} ===")
            domain = CanonicalChatRequest(
                model=_DEMO_MODEL,
                messages=[
                    ChatMessage(role="user", content="Say hi in one short sentence.")
                ],
                stream=False,
                max_completion_tokens=64,
            )
            req = ConnectorChatCompletionsRequest(
                request=domain,
                processed_messages=list(domain.messages),
                effective_model=_DEMO_MODEL,
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )
            env = await connector.chat_completions(req)
            if not isinstance(env, ResponseEnvelope):
                print(f"Unexpected return: {type(env)}", file=sys.stderr)
                return 2
            body = env.content
            if not isinstance(body, dict):
                print(f"Unexpected content: {type(body)}", file=sys.stderr)
                return 2
            msg = body["choices"][0]["message"]
            print("--- assistant content ---")
            print(msg["content"])
            print("--- usage ---")
            print(json.dumps(body.get("usage"), indent=2))

    print("\n(respx: upstream NVIDIA host was mocked; no real API key required.)")
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
