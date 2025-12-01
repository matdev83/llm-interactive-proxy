"""
Tests for ToolCallRepairMiddleware.

These tests verify that the middleware correctly detects and repairs tool calls
while preserving the original content for clients like Kilo-Code that parse
tool calls from XML in the content field rather than from native tool_calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.app.middleware.tool_call_repair_middleware import ToolCallRepairMiddleware
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.services.tool_call_repair_service import ToolCallRepairService


@dataclass
class MockResponse:
    """Mock response object for testing."""

    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a mock AppConfig with tool_call_repair_enabled=True."""
    config = MagicMock(spec=AppConfig)
    config.session = MagicMock(spec=SessionConfig)
    config.session.tool_call_repair_enabled = True
    return config


@pytest.fixture
def repair_service() -> ToolCallRepairService:
    """Create a real ToolCallRepairService for testing."""
    return ToolCallRepairService()


@pytest.fixture
def middleware(
    mock_config: AppConfig, repair_service: ToolCallRepairService
) -> ToolCallRepairMiddleware:
    """Create the middleware under test."""
    return ToolCallRepairMiddleware(mock_config, repair_service)


class TestToolCallRepairMiddlewareContentPreservation:
    """
    CRITICAL REGRESSION TESTS: Content preservation for Kilo-Code compatibility.

    These tests ensure that when tool calls are detected in response content,
    the original content (XML) is NOT cleared. This is critical because:

    1. Kilo-Code explicitly IGNORES native tool_calls in the delta
    2. Kilo-Code parses XML tool calls directly from the content field
    3. If content is cleared, Kilo-Code cannot execute tool calls

    See: dev/thrdparty/kilocode/src/api/providers/openrouter.ts lines 280-286
    """

    @pytest.mark.asyncio
    async def test_xml_content_preserved_when_tool_call_detected(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """
        REGRESSION TEST: XML content must NOT be cleared when tool call is detected.

        This test prevents the bug where content was set to None after detecting
        a tool call, which broke Kilo-Code integration.
        """
        xml_content = (
            "<list_files>\n<path>.</path>\n<recursive>false</recursive>\n</list_files>"
        )
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        # CRITICAL: Content must be preserved (not set to None)
        assert result.content == xml_content, (
            "REGRESSION: Content was cleared when tool call detected! "
            "Kilo-Code requires XML to remain in content field."
        )

        # Tool calls should also be added to metadata
        assert "tool_calls" in result.metadata
        assert len(result.metadata["tool_calls"]) == 1
        assert result.metadata["tool_calls"][0]["function"]["name"] == "list_files"

    @pytest.mark.asyncio
    async def test_execute_command_xml_preserved(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that execute_command XML is preserved in content."""
        xml_content = "<execute_command>\n<command>ls -la</command>\n</execute_command>"
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        assert (
            result.content == xml_content
        ), "REGRESSION: execute_command XML was cleared!"
        assert "tool_calls" in result.metadata
        assert result.metadata["tool_calls"][0]["function"]["name"] == "execute_command"

    @pytest.mark.asyncio
    async def test_read_file_xml_preserved(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that read_file XML is preserved in content."""
        xml_content = "<read_file>\n<path>README.md</path>\n</read_file>"
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        assert result.content == xml_content, "REGRESSION: read_file XML was cleared!"
        assert "tool_calls" in result.metadata

    @pytest.mark.asyncio
    async def test_content_with_prefix_text_preserved(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that content with prefix text before XML is fully preserved."""
        xml_content = (
            "I'll list the files for you.\n\n"
            "<list_files>\n<path>.</path>\n</list_files>"
        )
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        # Full content including prefix text must be preserved
        assert (
            result.content == xml_content
        ), "REGRESSION: Content with prefix text was modified!"
        assert "tool_calls" in result.metadata

    @pytest.mark.asyncio
    async def test_finish_reason_set_to_tool_calls(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that finish_reason is set to 'tool_calls' when tool call detected."""
        xml_content = "<list_files>\n<path>.</path>\n</list_files>"
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        assert (
            result.metadata.get("finish_reason") == "tool_calls"
        ), "finish_reason should be set to 'tool_calls' when tool call is detected"

    @pytest.mark.asyncio
    async def test_existing_finish_reason_overridden(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that existing finish_reason='stop' is overridden to 'tool_calls'."""
        xml_content = "<list_files>\n<path>.</path>\n</list_files>"
        response = MockResponse(content=xml_content, metadata={"finish_reason": "stop"})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        assert (
            result.metadata.get("finish_reason") == "tool_calls"
        ), "finish_reason='stop' should be overridden to 'tool_calls'"

    @pytest.mark.asyncio
    async def test_no_tool_call_content_unchanged(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Test that content without tool calls is not modified."""
        content = "Here is some regular text without any tool calls."
        response = MockResponse(content=content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        assert result.content == content
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_disabled_middleware_passes_through(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that disabled middleware passes content through unchanged."""
        config = MagicMock(spec=AppConfig)
        config.session = MagicMock(spec=SessionConfig)
        config.session.tool_call_repair_enabled = False

        middleware = ToolCallRepairMiddleware(config, repair_service)
        xml_content = "<list_files>\n<path>.</path>\n</list_files>"
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        # Content should be unchanged, no tool_calls added
        assert result.content == xml_content
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_streaming_responses_skipped(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """
        CRITICAL REGRESSION TEST: Streaming responses must be skipped.

        Streaming responses are already processed by ToolCallRepairProcessor
        in the streaming pipeline. If this middleware also processes them,
        the same tool call would be detected twice, resulting in duplicate
        tool_calls with different IDs. This breaks clients that expect one
        tool call per action.

        Regression: KiloCode + Gemini OAuth backend showed duplicate tool calls
        where each had a different ID, causing tool_use_id errors on subsequent
        tool result submissions.
        """
        xml_content = (
            "<execute_command>\n<command>git status</command>\n</execute_command>"
        )
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=True,  # STREAMING - should be skipped
        )

        # No tool_calls should be added - streaming processor handles these
        assert "tool_calls" not in result.metadata, (
            "REGRESSION: Middleware processed streaming response! "
            "This causes duplicate tool calls when combined with ToolCallRepairProcessor."
        )
        # Content should be unchanged
        assert result.content == xml_content

    @pytest.mark.asyncio
    async def test_streaming_with_existing_tool_calls_preserved(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """
        Test that streaming responses with existing tool_calls are passed through.

        When ToolCallRepairProcessor has already added tool_calls to the metadata,
        this middleware should NOT add more (which would create duplicates).
        """
        xml_content = (
            "<execute_command>\n<command>git status</command>\n</execute_command>"
        )
        existing_call = {
            "id": "call_from_processor",
            "type": "function",
            "function": {
                "name": "execute_command",
                "arguments": '{"command": "git status"}',
            },
        }
        response = MockResponse(
            content=xml_content, metadata={"tool_calls": [existing_call]}
        )

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=True,
        )

        # Should still have exactly ONE tool call (no duplicates added)
        assert (
            len(result.metadata["tool_calls"]) == 1
        ), "REGRESSION: Middleware added duplicate tool call to streaming response!"
        assert result.metadata["tool_calls"][0]["id"] == "call_from_processor"
