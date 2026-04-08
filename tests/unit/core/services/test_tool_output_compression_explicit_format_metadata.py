"""Explicit-format flags surface deterministic diagnostics on compression records."""

from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    DynamicCompressionConfig,
)
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _messages_with_command(*, content: str, command: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-fmt",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-fmt", content=content),
    ]


@pytest.mark.asyncio
async def test_explicit_format_note_on_record_when_flags_present() -> None:
    service = ToolOutputCompressionService()
    payload = "line\n" * 2000
    command = "gh pr list --json number,title"
    messages = _messages_with_command(content=payload, command=command)
    config = DynamicCompressionConfig(enabled=True, min_bytes=0)

    result = await service.compress_messages(messages=messages, config=config)

    record = result.records[-1]
    assert record.identity.explicit_format_flags
    assert record.explicit_format_note is not None
    assert "--json" in record.explicit_format_note
    assert "path_decision=" in record.explicit_format_note


@pytest.mark.asyncio
async def test_no_explicit_format_note_without_flags() -> None:
    service = ToolOutputCompressionService()
    payload = "plain\n" * 2000
    messages = _messages_with_command(content=payload, command="git status")
    config = DynamicCompressionConfig(enabled=True, min_bytes=0)

    result = await service.compress_messages(messages=messages, config=config)

    record = result.records[-1]
    assert not record.identity.explicit_format_flags
    assert record.explicit_format_note is None
