import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.kimi_code import KimiCodeConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.translation_utils.content_utils import _coerce_reasoning_text


class AsyncMockIterable:
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        self.iter = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def connector():
    client = AsyncMock()
    config = MagicMock()
    translation_service = MagicMock()
    # KimiCodeConnector requires DI objects in constructor
    c = KimiCodeConnector(
        client=client, config=config, translation_service=translation_service
    )
    c.api_key = "test-key"
    c._prepare_payload = AsyncMock(
        return_value={"model": "kimi-for-coding", "messages": []}
    )
    return c


@pytest.mark.asyncio
async def test_regression_kimi_reasoning_delta_conversion_all_aliases(connector):
    """
    REGRESSION TEST: Ensures ALL reasoning aliases are converted from accumulated to deltas.
    If this fails, clients may see duplicated text or inconsistent state.
    """
    # Simulate Kimi sending multiple reasoning fields, all accumulated
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "The",
                        "reasoning": "The",
                        "thinking": "The",
                        "thought": "The",
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "The user",
                        "reasoning": "The user",
                        "thinking": "The user",
                        "thought": "The user",
                    }
                }
            ]
        },
    ]

    events = [f"data: {json.dumps(c)}\n\n".encode() for c in chunks]
    events.append(b"data: [DONE]\n\n")

    response = AsyncMock()
    response.aiter_bytes = MagicMock(return_value=AsyncMockIterable(events))
    response.status_code = 200
    connector.client.send = AsyncMock(return_value=response)

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding", messages=[ChatMessage(role="user", content="hi")]
    )

    # Track what the proxy sends back to the client
    collected_deltas = []
    async for chunk in connector.stream_completion(request):
        chunk_str = chunk.decode("utf-8")
        if chunk_str.startswith("data: ") and not chunk_str.strip().endswith("[DONE]"):
            data = json.loads(chunk_str[6:])
            collected_deltas.append(data["choices"][0]["delta"])

    # First chunk should have "The"
    assert collected_deltas[0]["reasoning_content"] == "The"
    assert collected_deltas[0]["thinking"] == "The"

    # Second chunk MUST have " user" (the delta), NOT "The user" (the accumulated)
    # If the fix is reverted, these will be "The user"
    assert collected_deltas[1]["reasoning_content"] == " user"
    assert collected_deltas[1]["reasoning"] == " user"
    assert collected_deltas[1]["thinking"] == " user"
    assert collected_deltas[1]["thought"] == " user"


def test_regression_coerce_reasoning_preserves_whitespace_tokens():
    """
    REGRESSION TEST: Ensures _coerce_reasoning_text does NOT strip whitespace.
    Stripping whitespace in streaming tokens causes "word word" -> "wordword" bug.
    """
    # Leading space token
    assert _coerce_reasoning_text(" user") == " user"

    # Newline token
    assert _coerce_reasoning_text("\n2.") == "\n2."

    # Nested structure with whitespace (common in Gemini/DeepSeek)
    payload = {"thinking": " Step 1"}
    assert _coerce_reasoning_text(payload) == " Step 1"


@pytest.mark.asyncio
async def test_regression_accumulation_processor_preserves_whitespace():
    """
    REGRESSION TEST: Ensures ContentAccumulationProcessor does not strip chunks.
    """
    from src.core.domain.streaming.streaming_content import StreamingContent
    from src.core.services.streaming.content_accumulation_processor import (
        ContentAccumulationProcessor,
    )

    processor = ContentAccumulationProcessor()

    # Sending two chunks that should concatenate with a space
    chunk1 = StreamingContent(
        content={"choices": [{"delta": {"reasoning_content": "Line"}}]},
        stream_id="test",
    )
    chunk2 = StreamingContent(
        content={"choices": [{"delta": {"reasoning_content": " 1"}}]},
        stream_id="test",
        is_done=True,
    )

    await processor.process(chunk1)
    result = await processor.process(chunk2)

    # If it strips, it will be "Line1"
    assert result.metadata["accumulated_reasoning"] == "Line 1"


@pytest.mark.asyncio
async def test_regression_drop_leading_whitespace_only_reasoning(connector):
    """
    REGRESSION TEST: Leading whitespace-only reasoning deltas should be dropped
    to avoid empty thinking sections in clients.
    """
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": " ",
                        "reasoning": " ",
                        "thinking": " ",
                        "thought": " ",
                        "content": "",
                    }
                }
            ]
        },
        {"choices": [{"delta": {"content": "Hello"}}]},
    ]

    events = [f"data: {json.dumps(c)}\n\n".encode() for c in chunks]
    events.append(b"data: [DONE]\n\n")

    response = AsyncMock()
    response.aiter_bytes = MagicMock(return_value=AsyncMockIterable(events))
    response.status_code = 200
    connector.client.send = AsyncMock(return_value=response)

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding", messages=[ChatMessage(role="user", content="hi")]
    )

    collected_deltas = []
    async for chunk in connector.stream_completion(request):
        chunk_str = chunk.decode("utf-8")
        if chunk_str.startswith("data: ") and not chunk_str.strip().endswith("[DONE]"):
            data = json.loads(chunk_str[6:])
            collected_deltas.append(data["choices"][0]["delta"])

    assert collected_deltas, "Expected at least one delta event"
    first_delta = collected_deltas[0]
    assert "reasoning_content" not in first_delta
    assert "reasoning" not in first_delta
    assert "thinking" not in first_delta
    assert "thought" not in first_delta
