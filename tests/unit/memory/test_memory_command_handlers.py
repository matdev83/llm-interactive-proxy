"""Unit tests for memory command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.commands.handlers.memory_command_handlers import (
    MemoryOffCommandHandler,
    MemoryOnCommandHandler,
    MemoryStatusCommandHandler,
)
from src.core.commands.models import Command
from src.core.domain.session import Session
from src.core.memory.service import SessionMemoryState


def create_mock_session(
    session_id: str = "sess-123",
    user_id: str = "user-1",
) -> Session:
    """Create a mock Session object."""
    session = MagicMock(spec=Session)
    session.session_id = session_id
    session.user_id = user_id
    session.client_agent = "test-client"
    session.tenant_id = None
    session.project_root = "/home/user/project"
    return session


def create_mock_command() -> Command:
    """Create a mock Command object."""
    return Command(name="memory-on", args={})


class TestMemoryOnCommandHandler:
    """Tests for MemoryOnCommandHandler."""

    @pytest.mark.asyncio
    async def test_enable_succeeds_when_available(self) -> None:
        """Test memory-on succeeds when memory is available."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.enable_for_session = AsyncMock(return_value=True)

        handler = MemoryOnCommandHandler(memory_service=memory_service)
        result = await handler.handle(create_mock_command(), create_mock_session())

        assert result.success is True
        assert "enabled" in result.message.lower()
        memory_service.enable_for_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_fails_when_unavailable(self) -> None:
        """Test memory-on fails when memory is globally unavailable."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = False

        handler = MemoryOnCommandHandler(memory_service=memory_service)
        result = await handler.handle(create_mock_command(), create_mock_session())

        assert result.success is False
        assert "not available" in result.message.lower()

    @pytest.mark.asyncio
    async def test_enable_fails_when_denied(self) -> None:
        """Test memory-on fails when user/client is denied."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.enable_for_session = AsyncMock(return_value=False)

        handler = MemoryOnCommandHandler(memory_service=memory_service)
        result = await handler.handle(create_mock_command(), create_mock_session())

        assert result.success is False
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_enable_fails_without_service(self) -> None:
        """Test memory-on fails when service not configured."""
        handler = MemoryOnCommandHandler(memory_service=None)
        result = await handler.handle(create_mock_command(), create_mock_session())

        assert result.success is False
        assert "not available" in result.message.lower()


class TestMemoryOffCommandHandler:
    """Tests for MemoryOffCommandHandler."""

    @pytest.mark.asyncio
    async def test_disable_succeeds(self) -> None:
        """Test memory-off always succeeds."""
        memory_service = MagicMock()
        memory_service.disable_for_session = AsyncMock()

        handler = MemoryOffCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-off", args={}), create_mock_session()
        )

        assert result.success is True
        assert "disabled" in result.message.lower()
        memory_service.disable_for_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_fails_without_service(self) -> None:
        """Test memory-off fails when service not configured."""
        handler = MemoryOffCommandHandler(memory_service=None)
        result = await handler.handle(
            Command(name="memory-off", args={}), create_mock_session()
        )

        assert result.success is False


class TestMemoryStatusCommandHandler:
    """Tests for MemoryStatusCommandHandler."""

    @pytest.mark.asyncio
    async def test_status_when_enabled(self) -> None:
        """Test memory-status shows enabled state."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.is_enabled_for_session = AsyncMock(return_value=True)
        memory_service.get_session_state = AsyncMock(
            return_value=SessionMemoryState(
                user_id="user-1",
                project_root="/home/user/project",
            )
        )

        handler = MemoryStatusCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "enabled" in result.message.lower()
        assert "user-1" in result.message

    @pytest.mark.asyncio
    async def test_status_when_disabled(self) -> None:
        """Test memory-status shows disabled state."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.is_enabled_for_session = AsyncMock(return_value=False)
        memory_service.get_session_state = AsyncMock(return_value=None)

        handler = MemoryStatusCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "not enabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_status_when_globally_disabled(self) -> None:
        """Test memory-status shows globally disabled."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = False

        handler = MemoryStatusCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "disabled globally" in result.message.lower()

    @pytest.mark.asyncio
    async def test_status_without_service(self) -> None:
        """Test memory-status when service not configured."""
        handler = MemoryStatusCommandHandler(memory_service=None)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "unavailable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_status_shows_project_root(self) -> None:
        """Test memory-status includes project root when present."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.is_enabled_for_session = AsyncMock(return_value=True)
        memory_service.get_session_state = AsyncMock(
            return_value=SessionMemoryState(
                user_id="user-1",
                project_root="/home/user/my-project",
            )
        )

        handler = MemoryStatusCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "/home/user/my-project" in result.message

    @pytest.mark.asyncio
    async def test_status_shows_queued_state(self) -> None:
        """Test memory-status shows queued for analysis state."""
        memory_service = MagicMock()
        memory_service.is_available.return_value = True
        memory_service.is_enabled_for_session = AsyncMock(return_value=True)
        memory_service.get_session_state = AsyncMock(
            return_value=SessionMemoryState(
                user_id="user-1",
                queued_for_analysis=True,
            )
        )

        handler = MemoryStatusCommandHandler(memory_service=memory_service)
        result = await handler.handle(
            Command(name="memory-status", args={}), create_mock_session()
        )

        assert result.success is True
        assert "queued" in result.message.lower()
