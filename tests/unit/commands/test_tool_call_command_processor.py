from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from src.core.commands.models import Command, CommandResultWrapper
from src.core.commands.tool_call_command_processor import ToolCallCommandProcessor
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.interfaces.command_service_interface import ICommandService


@pytest.mark.asyncio
async def test_process_messages_detects_tool_calls() -> None:
    """Verify that the processor correctly identifies messages containing tool_calls."""
    mock_command_service = AsyncMock(spec=ICommandService)

    # The actual result is a CommandResultWrapper. We simulate the object it wraps.
    mock_command_service.execute_command.return_value = CommandResultWrapper(
        "shell", SimpleNamespace(success=True, message="tool output")
    )
    processor = ToolCallCommandProcessor(command_service=mock_command_service)
    messages: list[Any] = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_123",
                    function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
                )
            ],
        ),
    ]

    result = await processor.process_messages(messages, "session-123")

    assert result.command_executed is True
    assert len(result.command_results) == 1
    command_result_message = result.command_results[0]
    assert isinstance(command_result_message, ChatMessage)
    assert command_result_message.role == "tool"
    assert command_result_message.tool_call_id == "call_123"
    assert command_result_message.content == "tool output"
    assert result.modified_messages == messages
    mock_command_service.execute_command.assert_awaited_once_with(
        Command(name="shell", args={"command": "ls"}), "session-123"
    )


@pytest.mark.asyncio
async def test_process_messages_ignores_messages_without_tool_calls() -> None:
    """Verify that the processor ignores messages without tool_calls."""
    mock_command_service = AsyncMock(spec=ICommandService)
    processor = ToolCallCommandProcessor(command_service=mock_command_service)
    messages: list[Any] = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="How can I help?"),
    ]

    result = await processor.process_messages(messages, "session-123")

    assert result.command_executed is False
    assert result.modified_messages == messages
    mock_command_service.execute_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_messages_converts_textual_tool_result() -> None:
    """Ensure textual Cline-style tool results are converted into tool messages."""
    mock_command_service = AsyncMock(spec=ICommandService)
    processor = ToolCallCommandProcessor(command_service=mock_command_service)

    messages: list[Any] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "shell",
                        "arguments": '{"command": ["bash", "-lc", "ls"], "workdir": "/tmp"}',
                    },
                }
            ],
        },
        ChatMessage(
            role="user",
            content=(
                "[execute_command for 'bash -lc ls'] Result:\n"
                "Command executed in terminal  within working directory '/tmp'. Exit code: 0\n"
                "Output:\n\nfile_one\nfile_two\n"
            ),
        ),
    ]

    result = await processor.process_messages(messages, "session-999")

    assert result.command_executed is True
    assert result.command_results == []
    assert len(result.modified_messages) == len(messages)

    converted_message = result.modified_messages[1]
    assert isinstance(converted_message, ChatMessage)
    assert converted_message.role == "tool"
    assert converted_message.tool_call_id == "call_abc"
    assert converted_message.name == "shell"
    assert "file_one" in (converted_message.content or "")
    assert "file_two" in (converted_message.content or "")

    mock_command_service.execute_command.assert_not_awaited()
