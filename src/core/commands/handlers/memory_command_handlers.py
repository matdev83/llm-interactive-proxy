"""Memory command handlers for ProxyMem feature.

Implements interactive commands for memory control:
- memory-on: Enable memory capture for a session
- memory-off: Disable memory capture for a session
- memory-status: Query current memory state
- memory-requeue: Requeue summary generation for a session
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService
    from src.core.memory.service import MemoryService


@command("memory-on")
class MemoryOnCommandHandler(ICommandHandler):
    """Command handler to enable memory capture for a session."""

    def __init__(
        self,
        command_service: ICommandService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        super().__init__(command_service)
        self._memory_service = memory_service

    @property
    def command_name(self) -> str:
        return "memory-on"

    @property
    def description(self) -> str:
        return "Enable memory capture for this session."

    @property
    def format(self) -> str:
        return "memory-on"

    @property
    def examples(self) -> list[str]:
        return ["!/memory-on"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Enable memory capture for the session."""
        if self._memory_service is None:
            return CommandResult(
                success=False,
                message="Memory service not available.",
            )

        if not self._memory_service.is_available():
            return CommandResult(
                success=False,
                message="Memory feature is not available. Check configuration.",
            )

        user_id = getattr(session, "user_id", None) or ""
        client_id = getattr(session, "client_agent", None)
        tenant_id = getattr(session, "tenant_id", None)
        project_root = getattr(session, "project_root", None)

        result = await self._memory_service.enable_for_session(
            session.session_id,
            user_id,
            client_id=client_id,
            tenant_id=tenant_id,
            project_root=project_root,
        )

        if result:
            return CommandResult(
                success=True,
                message="Memory capture enabled for this session.",
            )
        else:
            return CommandResult(
                success=False,
                message="Failed to enable memory. Check user/client permissions.",
            )


@command("memory-off")
class MemoryOffCommandHandler(ICommandHandler):
    """Command handler to disable memory capture for a session."""

    def __init__(
        self,
        command_service: ICommandService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        super().__init__(command_service)
        self._memory_service = memory_service

    @property
    def command_name(self) -> str:
        return "memory-off"

    @property
    def description(self) -> str:
        return "Disable memory capture for this session."

    @property
    def format(self) -> str:
        return "memory-off"

    @property
    def examples(self) -> list[str]:
        return ["!/memory-off"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Disable memory capture for the session."""
        if self._memory_service is None:
            return CommandResult(
                success=False,
                message="Memory service not available.",
            )

        await self._memory_service.disable_for_session(session.session_id)

        return CommandResult(
            success=True,
            message="Memory capture disabled for this session.",
        )


@command("memory-status")
class MemoryStatusCommandHandler(ICommandHandler):
    """Command handler to query memory status for a session."""

    def __init__(
        self,
        command_service: ICommandService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        super().__init__(command_service)
        self._memory_service = memory_service

    @property
    def command_name(self) -> str:
        return "memory-status"

    @property
    def description(self) -> str:
        return "Show current memory capture status for this session."

    @property
    def format(self) -> str:
        return "memory-status"

    @property
    def examples(self) -> list[str]:
        return ["!/memory-status"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Query and return memory status for the session."""
        if self._memory_service is None:
            return CommandResult(
                success=True,
                message="Memory: unavailable (service not configured)",
            )

        if not self._memory_service.is_available():
            return CommandResult(
                success=True,
                message="Memory: disabled globally",
            )

        is_enabled = await self._memory_service.is_enabled_for_session(
            session.session_id
        )
        state = await self._memory_service.get_session_state(session.session_id)

        if is_enabled and state:
            parts = [
                "Memory: enabled",
                f"  User: {state.user_id}",
            ]
            if state.project_root:
                parts.append(f"  Project: {state.project_root}")
            if state.tenant_id:
                parts.append(f"  Tenant: {state.tenant_id}")
            if state.queued_for_analysis:
                parts.append("  Status: queued for analysis")

            return CommandResult(success=True, message="\n".join(parts))
        else:
            return CommandResult(
                success=True,
                message="Memory: not enabled for this session",
            )


@command("memory-requeue")
class MemoryRequeueCommandHandler(ICommandHandler):
    """Command handler to requeue summary generation for a session."""

    def __init__(
        self,
        command_service: ICommandService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        super().__init__(command_service)
        self._memory_service = memory_service

    @property
    def command_name(self) -> str:
        return "memory-requeue"

    @property
    def description(self) -> str:
        return "Requeue summary generation for this session."

    @property
    def format(self) -> str:
        return "memory-requeue"

    @property
    def examples(self) -> list[str]:
        return ["!/memory-requeue"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Requeue summary generation for the session."""
        if self._memory_service is None:
            return CommandResult(
                success=False,
                message="Memory service not available.",
            )

        success, message = await self._memory_service.requeue_session_summary(
            session.session_id
        )
        return CommandResult(success=success, message=message)
