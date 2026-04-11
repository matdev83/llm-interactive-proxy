#!/usr/bin/env python
"""
DEMO: OpenAI Codex Usage Reporting Fix Verification

This script proves that the Codex connector now properly reports token usage
instead of always returning 0 tokens.

BEFORE THE FIX:
- Codex responses showed: {"usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
- This was because the executor used "openai" format translator instead of "openai-responses"
- The Responses API format (with input_tokens/output_tokens) wasn't being handled

AFTER THE FIX:
- Codex responses now show correct token counts
- Usage flows through: Connector → Translation → Legacy Frontend → Client
- Both streaming and non-streaming work correctly
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import Request

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.openai_codex import OpenAICodexConnector
from src.core.app.controllers.chat_controller import ChatController
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi


class _FakeCodexBackendWithUsage:
    """Simulates Codex backend returning Responses API format with usage."""

    async def initiate_streaming_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        session_id: str,
    ) -> StreamingResponseHandle:
        is_streaming = payload.get("stream", False)

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            if is_streaming:
                # Simulate streaming SSE chunks
                yield ProcessedResponse(
                    content={
                        "choices": [
                            {"delta": {"content": "Hello "}, "finish_reason": None}
                        ]
                    }
                )
                yield ProcessedResponse(
                    content={
                        "choices": [
                            {"delta": {"content": "world!"}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "input_tokens": 42,  # Prompt tokens
                            "output_tokens": 15,  # Completion tokens
                            "total_tokens": 57,
                        },
                    }
                )
            else:
                # Simulate non-streaming response
                yield ProcessedResponse(
                    content={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "Hello world!",
                                }
                            }
                        ],
                        "usage": {
                            "input_tokens": 42,
                            "output_tokens": 15,
                            "total_tokens": 57,
                        },
                    }
                )

        async def _cancel() -> None:
            return None

        return StreamingResponseHandle(
            iterator=_iterator(),
            headers={"content-type": "application/json"},
            cancel_callback=_cancel,
        )


class _FakeRequestProcessor(IRequestProcessor):
    def __init__(self, response: ResponseEnvelope) -> None:
        self._response = response

    async def process_request(
        self,
        context: RequestContext,
        request_data: ChatRequest,
    ) -> ResponseEnvelope:
        return self._response


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 70}")
    print(f" {title}")
    print(f"{'=' * 70}")


def print_test(name: str, passed: bool, details: str = "") -> None:
    """Print test result with checkmark or X."""
    status = "PASS" if passed else "FAIL"
    symbol = "[OK]" if passed else "[!!]"
    print(f"  {symbol} {name}: {status}")
    if details and not passed:
        print(f"    -> {details}")


async def run_demo() -> bool:
    """Run the full demo and return True if all tests pass."""
    all_passed = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        auth_dir = Path(tmp_dir)
        auth_payload = {"tokens": {"access_token": "chatgpt_token"}}
        (auth_dir / "auth.json").write_text(json.dumps(auth_payload), encoding="utf-8")

        async with httpx.AsyncClient() as client:
            cfg = AppConfig()
            ts = TranslationService()
            backend = OpenAICodexConnector(client, cfg, translation_service=ts)

            # Initialize backend with mocks
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
                    response_executor = getattr(backend, "_response_executor", None)
                    if response_executor is None:
                        raise RuntimeError("Response executor not initialized")
                    response_executor._transport = _FakeCodexBackendWithUsage()  # type: ignore[attr-defined]

                    # TEST 1: Non-streaming connector response
                    print_section("TEST 1: Non-Streaming Connector Response")
                    non_stream_request = ChatRequest(
                        model="openai-codex:gpt-5-codex",
                        messages=[ChatMessage(role="user", content="Hello")],
                        stream=False,
                    )

                    non_stream_result = await backend.chat_completions(
                        request_data=non_stream_request,
                        processed_messages=list(non_stream_request.messages),
                        effective_model="gpt-5-codex",
                    )

                    if isinstance(non_stream_result, ResponseEnvelope):
                        usage = non_stream_result.usage
                        if usage:
                            print(f"  Response usage: {usage.model_dump()}")
                            test1_pass = (
                                usage.prompt_tokens == 42
                                and usage.completion_tokens == 15
                                and usage.total_tokens == 57
                            )
                            print_test(
                                "Non-streaming usage correctly mapped from input/output_tokens",
                                test1_pass,
                            )
                            if not test1_pass:
                                all_passed = False
                        else:
                            print_test("Usage exists", False, "usage is None")
                            all_passed = False
                    else:
                        print_test("Response is ResponseEnvelope", False)
                        all_passed = False

                    # TEST 2: Legacy OpenAI-compatible frontend conversion
                    print_section("TEST 2: Legacy OpenAI-Compatible Frontend")
                    legacy_response = domain_response_to_fastapi(non_stream_result)
                    legacy_body = (
                        legacy_response.body.tobytes()
                        if isinstance(legacy_response.body, memoryview)
                        else legacy_response.body
                    )
                    legacy_payload = json.loads(legacy_body.decode("utf-8"))
                    legacy_usage = legacy_payload.get("usage", {})

                    # Type safety: ensure legacy_usage is dict for .get()
                    if not isinstance(legacy_usage, dict):
                        print_test(
                            "Legacy frontend receives correct usage",
                            False,
                            f"usage is not a dict: {type(legacy_usage)}",
                        )
                        all_passed = False
                        return all_passed

                    print(f"  Legacy response usage: {legacy_usage}")
                    test2_pass = (
                        legacy_usage.get("prompt_tokens") == 42
                        and legacy_usage.get("completion_tokens") == 15
                        and legacy_usage.get("total_tokens") == 57
                    )
                    print_test(
                        "Legacy frontend receives correct usage",
                        test2_pass,
                    )
                    if not test2_pass:
                        all_passed = False

                    # TEST 2B: Full ChatController legacy path with plain-text content
                    print_section("TEST 2B: ChatController Legacy Path")
                    plain_usage = (
                        non_stream_result.usage
                        if isinstance(non_stream_result, ResponseEnvelope)
                        else None
                    )
                    plain_text_envelope = ResponseEnvelope(
                        content="Hello from plain text fallback",
                        usage=plain_usage,
                        metadata={"model": "openai-codex:gpt-5-codex"},
                    )
                    controller = ChatController(
                        request_processor=_FakeRequestProcessor(plain_text_envelope),
                        translation_service=ts,
                        wire_capture=None,
                        metrics_initializer=None,
                    )

                    fake_request = SimpleNamespace(
                        body=AsyncMock(return_value=b"{}"),
                        method="POST",
                        url=SimpleNamespace(path="/v1/chat/completions"),
                        headers={},
                        cookies={},
                        state=SimpleNamespace(),
                        app=SimpleNamespace(
                            state=SimpleNamespace(service_provider=None)
                        ),
                    )

                    controller_response = await controller.handle_chat_completion(
                        cast(Request, fake_request),
                        ChatRequest(
                            model="openai-codex:gpt-5-codex",
                            messages=[ChatMessage(role="user", content="Hello")],
                            stream=False,
                        ),
                    )
                    controller_body = (
                        controller_response.body.tobytes()
                        if isinstance(controller_response.body, memoryview)
                        else controller_response.body
                    )
                    controller_payload = json.loads(controller_body.decode("utf-8"))
                    controller_usage = controller_payload.get("usage", {})
                    print(f"  Controller payload usage: {controller_usage}")
                    test2b_pass = (
                        isinstance(controller_usage, dict)
                        and controller_usage.get("prompt_tokens") == 42
                        and controller_usage.get("completion_tokens") == 15
                        and controller_usage.get("total_tokens") == 57
                    )
                    print_test(
                        "ChatController preserves usage for plain-text fallback",
                        test2b_pass,
                    )
                    if not test2b_pass:
                        all_passed = False

                    # TEST 3: Streaming response
                    print_section("TEST 3: Streaming Response")
                    streaming_request = ChatRequest(
                        model="openai-codex:gpt-5-codex",
                        messages=[ChatMessage(role="user", content="Hello")],
                        stream=True,
                    )

                    stream_result = await backend.chat_completions(
                        request_data=streaming_request,
                        processed_messages=list(streaming_request.messages),
                        effective_model="gpt-5-codex",
                    )

                    if isinstance(stream_result, StreamingResponseEnvelope):
                        stream_content = stream_result.content
                        if stream_content is None:
                            print_test(
                                "Stream content exists", False, "content is None"
                            )
                            all_passed = False
                            return all_passed

                        usage_found = False
                        usage_data = None

                        async for chunk in stream_content:
                            if isinstance(chunk.content, dict):
                                content_usage = chunk.content.get("usage")
                                if isinstance(content_usage, dict):
                                    usage_found = True
                                    usage_data = content_usage
                                    print(f"  Streaming chunk usage: {content_usage}")
                                    break

                        test3_pass = (
                            usage_found
                            and isinstance(usage_data, dict)
                            and usage_data.get("input_tokens") == 42
                            and usage_data.get("output_tokens") == 15
                        )
                        print_test(
                            "Streaming response contains usage data",
                            test3_pass,
                        )
                        if not test3_pass:
                            all_passed = False
                    else:
                        print_test("Response is StreamingResponseEnvelope", False)
                        all_passed = False

            finally:
                await backend.shutdown()

    return all_passed


def main() -> None:
    """Run demo and print final results."""
    print("\n" + "=" * 70)
    print(" OpenAI Codex Usage Reporting Fix - Verification Demo")
    print("=" * 70)
    print("\nThis demo proves that token usage is now properly reported")
    print("for the openai-codex connector (both streaming and non-streaming).")

    try:
        success = asyncio.run(run_demo())

        print("\n" + "=" * 70)
        if success:
            print(" [OK] ALL TESTS PASSED")
            print("=" * 70)
            print("\nThe fix is working correctly!")
            print(
                "- Non-streaming: Usage correctly extracted from Responses API format"
            )
            print("- Legacy frontend: Usage properly converted to OpenAI format")
            print("- Streaming: Usage present in final chunk")
            print("\nYour agents should now see correct token counts instead of 0.")
            sys.exit(0)
        else:
            print(" [!!] SOME TESTS FAILED")
            print("=" * 70)
            print("\nThe fix may not be complete. Check the output above.")
            sys.exit(1)

    except Exception as e:
        print(f"\n{'=' * 70}")
        print(" [!!] DEMO ERROR")
        print(f"{'=' * 70}")
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
