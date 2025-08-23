"""Debug Anthropic payload builder."""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from unittest.mock import AsyncMock

from src.connectors.anthropic import AnthropicBackend
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ToolDefinition,
)


async def main():
    client = AsyncMock()
    backend = AnthropicBackend(client)
    tools = [
        ToolDefinition(
            type="function",
            function=FunctionDefinition(
                name="get_weather",
                description="desc",
                parameters={"type":"object","properties":{"location":{"type":"string"}},"required":["location"]},
            ),
        )
    ]
    req = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="What's the weather like?")],
        temperature=0.7,
        max_tokens=100,
        stream=False,
        tools=[t.model_dump() for t in tools],
        tool_choice="auto",
    )
    processed = [ChatMessage(role="user", content="What's the weather like?")]
    payload = backend._prepare_anthropic_payload(req, processed, "claude-3-haiku-20240307", None)
    print(payload)

import asyncio

asyncio.run(main())


