#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import os
from types import MethodType
from typing import Any, cast

import httpx
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.ports.streaming_integration import integrate_streaming_pipeline


def build_payload(model: str, payload_shape: str) -> dict[str, Any]:
    if payload_shape == "proxy-shape":
        tools = [
            {
                "type": "function",
                "function": {
                    "name": f"tool_{i}",
                    "description": f"Tool description number {i}",
                    "parameters": {
                        "type": "object",
                        "properties": {"param": {"type": "string"}},
                        "required": ["param"],
                    },
                },
            }
            for i in range(4)
        ]
        system_prompt = (
            "You are opencode, an interactive CLI tool that helps users with software "
            "engineering tasks. Use the instructions below and the tools available "
            "to you to assist the user. "
        ) * 8
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "What is 2+2?"},
        ]
        return {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": 512,
            "tools": tools,
            "tool_choice": "auto",
        }

    return {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "stream": True,
        "max_tokens": 64,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-5.1")
    parser.add_argument(
        "--payload-shape", choices=("minimal", "proxy-shape"), default="minimal"
    )
    parser.add_argument("--chunks", type=int, default=10)
    args = parser.parse_args()

    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        raise SystemExit("ZAI_API_KEY is not set")

    payload = build_payload(args.model, args.payload_shape)

    async with httpx.AsyncClient(timeout=60.0, http2=False) as client:
        backend = ZaiCodingPlanBackend(
            client=client,
            config=AppConfig(),
            translation_service=None,
        )
        backend_any = cast(Any, backend)
        backend.api_key = api_key
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend.available_models = [args.model]
        backend_any._provider_models = {args.model}

        async def fake_prepare_payload(
            self, request_data, processed_messages, effective_model, context=None
        ):
            return dict(payload)

        backend_any._prepare_payload = MethodType(fake_prepare_payload, backend)

        request = CanonicalChatRequest(
            model=args.model,
            messages=[ChatMessage(role="user", content="Say hello in one word.")],
            stream=True,
            max_tokens=payload.get("max_tokens"),
        )

        raw_stream = backend.stream_completion(request)
        envelope = await integrate_streaming_pipeline(
            raw_stream,
            provider="openai",
            stream_id=f"probe-{args.model}",
            enable_loop_detection=False,
            enable_tool_call_repair=False,
            enable_think_tags=True,
            model_name=args.model,
        )

        print(f"Envelope status: {envelope.status_code}")
        print(f"Media type: {envelope.media_type}")
        print("Chunks:")

        count = 0
        content_iter = envelope.content
        if content_iter is None:
            raise RuntimeError("Streaming envelope unexpectedly has no content")

        async for chunk in content_iter:
            count += 1
            content = chunk.content
            if isinstance(content, bytes):
                preview = content.decode("utf-8", errors="replace")[:500]
            else:
                preview = str(content)[:500]
            print(f"--- chunk {count} ---")
            print(preview)
            if count >= args.chunks:
                break

        print(f"Observed chunks: {count}")
        print(f"Payload keys: {sorted(payload.keys())}")
        print(f"Payload preview: {json.dumps(payload)[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
