"""
Tests for Inline Python Steering Handler.
"""

from __future__ import annotations

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.command_extraction_service import CommandExtractionService
from src.core.services.tool_call_handlers.inline_python_steering_handler import (
    InlinePythonSteeringHandler,
)


class TestInlinePythonSteeringHandler:
    """Tests for the inline python execution prevention."""

    @pytest.fixture
    def handler(self) -> InlinePythonSteeringHandler:
        return InlinePythonSteeringHandler(
            command_service=CommandExtractionService(), enabled=True
        )

    def _make_context(self, tool_name: str, arguments: dict | str) -> ToolCallContext:
        return ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=arguments if isinstance(arguments, dict) else {},
            calling_agent=None,
        )

    @pytest.mark.asyncio
    async def test_can_handle_python_c(
        self, handler: InlinePythonSteeringHandler
    ) -> None:
        """Should detect python -c commands."""
        # Simple case
        context = self._make_context("bash", {"command": 'python -c "print(1)"'})
        assert await handler.can_handle(context)

        # With extra args
        context = self._make_context("bash", {"command": 'python -u -c "print(1)"'})
        assert await handler.can_handle(context)

        # python3
        context = self._make_context("bash", {"command": 'python3 -c "print(1)"'})
        assert await handler.can_handle(context)

        # python.exe
        context = self._make_context("bash", {"command": 'python.exe -c "print(1)"'})
        assert await handler.can_handle(context)

    @pytest.mark.asyncio
    async def test_can_handle_nested_args(
        self, handler: InlinePythonSteeringHandler
    ) -> None:
        """Should detect nested command structures."""
        context = self._make_context("Execute", {"command": 'python -c "print(1)"'})
        assert await handler.can_handle(context)

    @pytest.mark.asyncio
    async def test_ignores_normal_python_execution(
        self, handler: InlinePythonSteeringHandler
    ) -> None:
        """Should ignore normal python file execution."""
        context = self._make_context("bash", {"command": "python script.py"})
        assert not await handler.can_handle(context)

        context = self._make_context("bash", {"command": "python3 -m pytest"})
        assert not await handler.can_handle(context)

    @pytest.mark.asyncio
    async def test_ignores_non_shell_tools(
        self, handler: InlinePythonSteeringHandler
    ) -> None:
        """Should ignore non-shell tools."""
        context = self._make_context("write_file", {"path": "python -c file.txt"})
        assert not await handler.can_handle(context)

    @pytest.mark.asyncio
    async def test_handle_returns_steering_message(
        self, handler: InlinePythonSteeringHandler
    ) -> None:
        """Should return the proper steering message."""
        context = self._make_context("bash", {"command": 'python -c "print(1)"'})
        result = await handler.handle(context)

        assert result.should_swallow is True
        assert "inline Python code" in result.replacement_response
        assert "create a temporary script" in result.replacement_response
        assert result.metadata["handler"] == "inline_python_steering_handler"

    @pytest.mark.asyncio
    async def test_custom_message(self) -> None:
        """Should support custom messages."""
        custom_msg = "No inline python!"
        handler = InlinePythonSteeringHandler(
            command_service=CommandExtractionService(), message=custom_msg
        )
        context = self._make_context("bash", {"command": 'python -c "print(1)"'})
        result = await handler.handle(context)

        assert result.replacement_response == custom_msg

    @pytest.mark.asyncio
    async def test_disabled(self) -> None:
        """Should do nothing if disabled."""
        handler = InlinePythonSteeringHandler(
            command_service=CommandExtractionService(), enabled=False
        )
        context = self._make_context("bash", {"command": 'python -c "print(1)"'})

        assert not await handler.can_handle(context)

        result = await handler.handle(context)
        assert result.should_swallow is False
