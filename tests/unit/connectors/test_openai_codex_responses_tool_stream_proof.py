"""End-to-end proof: Codex (OpenAI) connector + Responses SSE tool calls.

Mocks upstream bytes only; exercises TranslationService, Responses streaming
translator, argument accumulation by call_id, and ProcessedResponse parsing.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.domain.translators.responses.streaming import (
    reset_active_responses_stream_context,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture(autouse=True)
def _reset_responses_stream_context() -> Generator[None, None, None]:
    reset_active_responses_stream_context()
    yield
    reset_active_responses_stream_context()


def _collect_tool_argument_strings(metadata: dict) -> list[str]:
    out: list[str] = []
    tcs = metadata.get("tool_calls")
    if not isinstance(tcs, list):
        return out
    for tc in tcs:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if isinstance(fn, dict):
            args = fn.get("arguments", "")
            if isinstance(args, str) and args.strip():
                out.append(args)
    return out


@pytest.mark.asyncio
async def test_openai_codex_handle_streaming_merges_tool_arguments_end_to_end(
    openai_codex_backend,
) -> None:
    """Prove connector streaming path yields non-empty tool args after delta + done."""
    resp_id = "resp_0proofcodexstreamtoolargs01"
    call_id = "fc_proof_merge_by_call_id_01"
    full_args = json.dumps({"command": ["bash", "-lc", "git log -1 --oneline"]})
    mid = max(1, len(full_args) // 2)
    part_a, part_b = full_args[:mid], full_args[mid:]

    events = [
        (
            "response.created",
            {"type": "response.created", "response": {"id": resp_id, "model": "gpt-5"}},
        ),
        (
            "response.function_call_arguments.delta",
            {"item_id": call_id, "output_index": 1, "delta": part_a},
        ),
        (
            "response.function_call_arguments.delta",
            {"item_id": call_id, "output_index": 1, "delta": part_b},
        ),
        (
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": call_id,
                    "name": "shell",
                    "arguments": "{}",
                },
            },
        ),
        (
            "response.completed",
            {"type": "response.completed", "response": {"id": resp_id}},
        ),
    ]

    sse_body = "".join(
        f"event: {ev}\ndata: {json.dumps(payload)}\n\n" for ev, payload in events
    ).encode("utf-8")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    async def _one_shot_bytes():
        yield sse_body

    mock_response.aiter_bytes = MagicMock(return_value=_one_shot_bytes())
    mock_response.aclose = AsyncMock()

    openai_codex_backend.client.build_request = MagicMock(return_value=MagicMock())
    openai_codex_backend.client.send = AsyncMock(return_value=mock_response)

    url = f"{openai_codex_backend.api_base_url.rstrip('/')}/responses"
    with patch.object(
        openai_codex_backend, "_validate_runtime_credentials", return_value=True
    ):
        handle = await openai_codex_backend._handle_streaming_response(
            url=url,
            payload={"stream": True},
            headers={"Authorization": "Bearer chatgpt_token"},
            session_id="sess-proof-tool-stream",
            stream_format="responses",
        )

    merged_args_seen: list[str] = []
    pydantic_chunks = 0
    dump_with_git: list[str] = []

    async for pr in handle.iterator:
        assert isinstance(pr, ProcessedResponse)
        md_fn = getattr(pr.content, "model_dump", None)
        if callable(md_fn) and not isinstance(pr.content, dict):
            pydantic_chunks += 1
            dumped = md_fn(exclude_none=True)
            if isinstance(dumped, dict):
                for ch in dumped.get("choices") or []:
                    if not isinstance(ch, dict):
                        continue
                    delta = ch.get("delta") or {}
                    if not isinstance(delta, dict):
                        continue
                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function")
                        if isinstance(fn, dict):
                            a = fn.get("arguments", "")
                            if isinstance(a, str) and "git log" in a:
                                dump_with_git.append(a)
        sc = StreamingContent.from_raw(pr)
        merged_args_seen.extend(_collect_tool_argument_strings(sc.metadata))

    assert (
        pydantic_chunks >= 1
    ), "expected CanonicalStreamChunk (Pydantic) from translation"
    assert dump_with_git, "model_dump choices.delta should include merged arguments"
    joined = "".join(merged_args_seen)
    assert (
        "git log" in joined
    ), f"merged tool arguments missing payload, got {merged_args_seen!r}"
    merged = json.loads(joined)
    assert "git log" in merged["command"]
    assert merged.get("description") == ""
