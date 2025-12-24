"""Mock MemoryService for testing."""

from typing import Any

from src.core.interfaces.memory_service_interface import IMemoryService


class MemoryServiceMock(IMemoryService):
    """Mock implementation of IMemoryService for testing."""

    def __init__(self) -> None:
        self._enabled_sessions: dict[str, bool] = {}
        self._captured_interactions: dict[str, list[Any]] = {}
        self._available: bool = True
        self._enable_call_counts: dict[str, int] = {}
        self._tool_events: dict[str, list[Any]] = {}

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    async def is_enabled_for_session(self, session_id: str) -> bool:
        return self._enabled_sessions.get(session_id, False)

    async def enable_for_session(
        self,
        session_id: str,
        user_id: str,
        *,
        client_id: str | None = None,
        tenant_id: str | None = None,
        project_root: str | None = None,
    ) -> bool:
        self._enable_call_counts[session_id] = (
            self._enable_call_counts.get(session_id, 0) + 1
        )
        self._enabled_sessions[session_id] = True
        return True

    def get_enable_call_count(self, session_id: str) -> int:
        return self._enable_call_counts.get(session_id, 0)

    async def disable_for_session(self, session_id: str) -> None:
        self._enabled_sessions.pop(session_id, None)

    async def capture_interaction(self, session_id: str, interaction: Any) -> bool:
        if session_id not in self._enabled_sessions:
            return False
        if session_id not in self._captured_interactions:
            self._captured_interactions[session_id] = []
        self._captured_interactions[session_id].append(interaction)
        return True

    async def record_tool_event(self, session_id: str, event: Any) -> bool:
        if session_id not in self._enabled_sessions:
            return False
        if session_id not in self._tool_events:
            self._tool_events[session_id] = []
        self._tool_events[session_id].append(event)
        return True

    async def mark_session_complete(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
        termination_reason: str | None = None,
    ) -> bool:
        return session_id in self._enabled_sessions

    async def get_captured_tool_events(self, session_id: str) -> Any:
        return self._tool_events.get(session_id, [])

    async def get_session_user_id(self, session_id: str) -> str | None:
        return None

    async def get_session_project_root(self, session_id: str) -> str | None:
        return None

    async def get_session_state(self, session_id: str) -> Any | None:
        return None
