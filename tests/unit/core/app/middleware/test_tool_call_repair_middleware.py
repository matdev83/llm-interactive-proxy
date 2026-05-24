"""
Tests for ToolCallRepairMiddleware.

DESIGN DECISION: Virtual tool call detection has been DISABLED.
The middleware now passes content through unchanged.

These tests verify the pass-through behavior.
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


class TestToolCallRepairMiddlewarePassThrough:
    """
    Tests that middleware passes content through unchanged.

    Virtual tool call detection has been disabled. The middleware
    should not modify content or add tool_calls to metadata.
    """

    @pytest.mark.asyncio
    async def test_xml_content_passes_through_unchanged(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """XML content passes through without detection."""
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

        # Content unchanged
        assert result.content == xml_content
        # No tool_calls added (detection disabled)
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_regular_content_passes_through_unchanged(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Regular text content passes through unchanged."""
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
    async def test_streaming_responses_pass_through(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Streaming responses pass through unchanged."""
        xml_content = (
            "<execute_command>\n<command>git status</command>\n</execute_command>"
        )
        response = MockResponse(content=xml_content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=True,
        )

        # Content unchanged
        assert result.content == xml_content
        # No tool_calls added
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_native_tool_calls_preserved(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Native tool_calls in metadata are preserved."""
        existing_call = {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "execute_command",
                "arguments": '{"command": "git status"}',
            },
        }
        response = MockResponse(
            content="",
            metadata={"tool_calls": [existing_call], "finish_reason": "tool_calls"},
        )

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        # Native tool_calls preserved
        assert len(result.metadata["tool_calls"]) == 1
        assert result.metadata["tool_calls"][0]["id"] == "call_123"
        assert result.metadata["finish_reason"] == "tool_calls"

    @pytest.mark.asyncio
    async def test_client_specific_tags_pass_through(
        self, middleware: ToolCallRepairMiddleware
    ) -> None:
        """Client-specific tags like <brain_dump> pass through unchanged."""
        content = """I'll check the tests.<brain_dump>
The user wants to verify all tests pass.
</brain_dump>"""
        response = MockResponse(content=content, metadata={})

        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={},
            is_streaming=False,
        )

        # Content unchanged - including client-specific tags
        assert "<brain_dump>" in result.content
        assert "I'll check the tests." in result.content
        # No tool_calls added
        assert "tool_calls" not in result.metadata
