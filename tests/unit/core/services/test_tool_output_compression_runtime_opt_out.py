"""Runtime opt-out controls: disable_tools, disable_command_prefixes, disable_methods."""

from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _shell_pair(*, content: str, command: str = "git status") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=content),
    ]


def _read_pair(*, content: str, path: str = "src/example.py") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name="read",
                        arguments=f'{{"path":"{path}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=content),
    ]


def _read_file_pair(*, content: str, path: str = "src/example.py") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name="read_file",
                        arguments=f'{{"path":"{path}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=content),
    ]


@pytest.mark.asyncio
async def test_disable_tools_bypasses_compression_and_markers() -> None:
    service = ToolOutputCompressionService()
    payload = "x" * 8000
    messages = _shell_pair(content=payload)
    base = DynamicCompressionConfig()
    config = base.model_copy(
        update={
            "enabled": True,
            "min_bytes": 0,
            "disable_tools": ["shell"],
        }
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    record = result.records[-1]
    assert record.applied is False
    assert record.marker_inserted is False


@pytest.mark.asyncio
async def test_disable_command_prefixes_bypasses_compression() -> None:
    service = ToolOutputCompressionService()
    payload = "y" * 8000
    messages = _shell_pair(content=payload, command="git status --porcelain")
    base = DynamicCompressionConfig()
    config = base.model_copy(
        update={
            "enabled": True,
            "min_bytes": 0,
            "disable_command_prefixes": ["git status"],
        }
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    assert result.records[-1].applied is False


@pytest.mark.asyncio
async def test_disable_command_prefixes_bypasses_compression_case_insensitively() -> (
    None
):
    service = ToolOutputCompressionService()
    payload = "k" * 8000
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        disable_command_prefixes=["GIT STATUS"],
    )

    for command in ("git status --porcelain", "GiT StAtUs --porcelain"):
        result = await service.compress_messages(
            messages=_shell_pair(content=payload, command=command),
            config=config,
        )
        assert result.messages[-1].content == payload
        assert result.records[-1].applied is False


@pytest.mark.asyncio
async def test_disable_methods_empty_pipeline_skips_compression() -> None:
    service = ToolOutputCompressionService()
    payload = "z" * 8000
    messages = _shell_pair(content=payload)
    base = DynamicCompressionConfig()
    rule = CompressionRule(
        name="line_only",
        priority=1,
        when=CompressionRulePredicate(tool_name="shell"),
        pipeline=["line_dedupe"],
    )
    config = base.model_copy(
        update={
            "enabled": True,
            "min_bytes": 0,
            "disable_methods": ["line_dedupe"],
            "rules": [rule],
        }
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    record = result.records[-1]
    assert record.applied is False
    assert record.marker_inserted is False


@pytest.mark.asyncio
async def test_disable_tools_wins_over_command_prefix_disable_mismatch() -> None:
    service = ToolOutputCompressionService()
    payload = "w" * 8000
    messages = _shell_pair(content=payload, command="npm test")
    base = DynamicCompressionConfig()
    config = base.model_copy(
        update={
            "enabled": True,
            "min_bytes": 0,
            "disable_tools": ["shell"],
            "disable_command_prefixes": ["git status"],
        }
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    assert result.records[-1].applied is False


@pytest.mark.asyncio
async def test_default_read_disable_tool_bypasses_compression_and_markers() -> None:
    service = ToolOutputCompressionService()
    payload = ("def alpha():\n" + "    value = 1\n" * 500).strip()
    messages = _read_pair(content=payload)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    record = result.records[-1]
    assert record.applied is False
    assert record.marker_inserted is False
    assert record.identity.tool_name == "read"


@pytest.mark.asyncio
async def test_default_read_file_disable_tool_bypasses_compression_and_markers() -> (
    None
):
    service = ToolOutputCompressionService()
    payload = ("def beta():\n" + "    value = 2\n" * 500).strip()
    messages = _read_file_pair(content=payload)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[-1].content == payload
    record = result.records[-1]
    assert record.applied is False
    assert record.marker_inserted is False
    assert record.identity.tool_name == "read_file"
