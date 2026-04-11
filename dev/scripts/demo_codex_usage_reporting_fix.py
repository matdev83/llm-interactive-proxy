#!/usr/bin/env python
"""Demo script proving OpenAI Codex usage reporting is non-zero.

This script creates a real OpenAICodexConnector instance, routes both
non-streaming and streaming chat flows through it, and prints/asserts usage.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi


class _FakeTransportWithProviderUsage:
    async def initiate_streaming_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        session_id: str,
    ) -> StreamingResponseHandle:
        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {"content": "Non-streaming Codex response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "input_tokens": 17,
                        "output_tokens": 9,
                        "total_tokens": 26,
                    },
                }
            )

        async def _cancel() -> None:
            return None

        return StreamingResponseHandle(
            iterator=_iterator(),
            headers={"x-demo": "codex-usage"},
            cancel_callback=_cancel,
        )


class _FakeTransportWithStreamingUsage:
    async def initiate_streaming_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        session_id: str,
    ) -> StreamingResponseHandle:
        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {"content": "Hello from Codex streaming. "},
                            "finish_reason": None,
                        }
                    ]
                }
            )
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {"content": "This carries token usage."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "input_tokens": 17,
                        "output_tokens": 9,
                        "total_tokens": 26,
                    },
                }
            )

        async def _cancel() -> None:
            return None

        return StreamingResponseHandle(
            iterator=_iterator(),
            headers={"x-demo": "codex-usage"},
            cancel_callback=_cancel,
        )


async def _run_demo() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        auth_dir = Path(tmp_dir)
        auth_payload = {"tokens": {"access_token": "chatgpt_token"}}
        (auth_dir / "auth.json").write_text(json.dumps(auth_payload), encoding="utf-8")

        async with httpx.AsyncClient() as client:
            cfg = AppConfig()
            ts = TranslationService()
            backend = OpenAICodexConnector(client, cfg, translation_service=ts)

            with (
                patch.object(
                    backend,
                    "_validate_credentials_file_exists",
                    return_value=(True, []),
                ),
                patch.object(
                    backend, "_validate_credentials_structure", return_value=(True, [])
                ),
                patch.object(backend, "_start_file_watching"),
            ):
                await backend.initialize(openai_codex_path=str(auth_dir))

            backend._credential_manager._managed_current_account = None  # type: ignore[attr-defined]

            try:
                with patch.object(
                    backend,
                    "_validate_runtime_credentials",
                    AsyncMock(return_value=True),
                ):
                    non_stream_request = ChatRequest(
                        model="openai-codex:gpt-5-codex",
                        messages=[ChatMessage(role="user", content="Count my tokens")],
                        stream=False,
                    )

                    response_executor = getattr(backend, "_response_executor", None)
                    if response_executor is None:
                        raise RuntimeError("Response executor is not initialized")
                    response_executor._transport = _FakeTransportWithProviderUsage()  # type: ignore[attr-defined]

                    non_stream_result = await backend.chat_completions(
                        request_data=non_stream_request,
                        processed_messages=list(non_stream_request.messages),
                        effective_model="gpt-5-codex",
                    )

                    if not isinstance(non_stream_result, ResponseEnvelope):
                        raise RuntimeError(
                            "Expected non-streaming call to return ResponseEnvelope"
                        )
                    if non_stream_result.usage is None:
                        raise RuntimeError("Non-streaming usage is missing")

                    non_stream_total = non_stream_result.usage.total_tokens or 0
                    print("[non-stream] usage:", non_stream_result.usage.model_dump())
                    if non_stream_total <= 0:
                        raise RuntimeError(
                            "Non-streaming total_tokens is zero; expected > 0"
                        )

                    legacy_fastapi_response = domain_response_to_fastapi(
                        non_stream_result
                    )
                    legacy_body = (
                        legacy_fastapi_response.body.tobytes()
                        if isinstance(legacy_fastapi_response.body, memoryview)
                        else legacy_fastapi_response.body
                    )
                    legacy_payload = json.loads(legacy_body.decode("utf-8"))
                    legacy_usage = legacy_payload.get("usage")
                    print("[legacy-non-stream] usage:", legacy_usage)
                    if not isinstance(legacy_usage, dict):
                        raise RuntimeError(
                            "Legacy OpenAI-compatible payload is missing usage"
                        )
                    if int(legacy_usage.get("total_tokens", 0)) <= 0:
                        raise RuntimeError(
                            "Legacy OpenAI-compatible total_tokens is zero; expected > 0"
                        )

                    streaming_request = ChatRequest(
                        model="openai-codex:gpt-5-codex",
                        messages=[
                            ChatMessage(
                                role="user",
                                content="Give me a short answer and report usage",
                            )
                        ],
                        stream=True,
                    )

                    response_executor._transport = _FakeTransportWithStreamingUsage()  # type: ignore[attr-defined]

                    stream_result = await backend.chat_completions(
                        request_data=streaming_request,
                        processed_messages=list(streaming_request.messages),
                        effective_model="gpt-5-codex",
                    )

                    if not isinstance(stream_result, StreamingResponseEnvelope):
                        raise RuntimeError(
                            "Expected streaming call to return StreamingResponseEnvelope"
                        )
                    stream_content_any = stream_result.content
                    if stream_content_any is None or not hasattr(
                        stream_content_any, "__aiter__"
                    ):
                        raise RuntimeError(
                            "Streaming response content iterator is missing"
                        )
                    stream_content: AsyncIterator[ProcessedResponse] = (
                        stream_content_any
                    )

                    usage_payloads: list[dict[str, Any]] = []
                    async for chunk in stream_content:
                        # Check explicit usage field
                        if chunk.usage is not None:
                            usage_payloads.append(chunk.usage.model_dump())
                        # Check metadata
                        usage_metadata = chunk.metadata.get("usage")
                        if isinstance(usage_metadata, dict):
                            usage_payloads.append(dict(usage_metadata))
                        # Check content dict (where Codex SSE would embed usage)
                        if isinstance(chunk.content, dict):
                            content_usage = chunk.content.get("usage")
                            if isinstance(content_usage, dict):
                                usage_payloads.append(dict(content_usage))

                    print("[stream] usage payloads:", usage_payloads)
                    if not usage_payloads:
                        raise RuntimeError(
                            "Streaming usage is missing; no chunks carried usage data"
                        )

                    max_total = max(
                        int(p.get("total_tokens", 0)) for p in usage_payloads
                    )
                    if max_total <= 0:
                        raise RuntimeError(
                            "Streaming total_tokens is zero; expected > 0"
                        )

                    print(
                        "SUCCESS: Codex usage reporting is non-zero for connector and legacy OpenAI frontend flows."
                    )
            finally:
                await backend.shutdown()


def main() -> None:
    asyncio.run(_run_demo())


if __name__ == "__main__":
    main()
