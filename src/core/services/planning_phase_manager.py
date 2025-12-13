"""Planning phase manager implementation.

Manages planning phase model overrides and counter tracking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager

if TYPE_CHECKING:
    from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class PlanningPhaseManager(IPlanningPhaseManager):
    """Service for managing planning phase lifecycle."""

    def __init__(self, session_service: ISessionService | None = None) -> None:
        """Initialize the planning phase manager.

        Args:
            session_service: Service for session operations.
        """
        self._session_service = session_service

    async def apply_if_needed(self, session: Any, default_backend: str) -> None:
        """Apply planning phase model override if conditions are met.

        Enabled only when `session.state.planning_phase_config.enabled`
        and `strong_model` are set. Original route is persisted only once
        per planning phase.
        """
        if not session or not session.state:
            return

        planning_config = getattr(session.state, "planning_phase_config", None)
        if (
            not planning_config
            or not bool(getattr(planning_config, "enabled", False))
            or not getattr(planning_config, "strong_model", None)
        ):
            return

        # Safely extract counters with defaults
        try:
            turn_count = int(
                getattr(session.state, "planning_phase_turn_count", 0) or 0
            )
        except Exception:
            turn_count = 0
        try:
            file_write_count = int(
                getattr(session.state, "planning_phase_file_write_count", 0) or 0
            )
        except Exception:
            file_write_count = 0

        try:
            _max_turns = int(getattr(planning_config, "max_turns", 0) or 0)
        except Exception:
            _max_turns = 0
        try:
            _max_writes = int(getattr(planning_config, "max_file_writes", 0) or 0)
        except Exception:
            _max_writes = 0

        if (turn_count >= _max_turns) or (file_write_count >= _max_writes):
            await self._restore_planning_phase_route(session)
            return

        from src.core.domain.configuration.backend_config import BackendConfiguration
        from src.core.domain.model_utils import parse_model_backend
        from src.core.interfaces.configuration_interface import IBackendConfig

        requested_backend, requested_model = parse_model_backend(
            session.state.backend_config.model or "", default_backend
        )
        strong_backend, strong_model = parse_model_backend(
            planning_config.strong_model, default_backend
        )

        current_full_model = f"{requested_backend}:{requested_model}"
        strong_full_model = f"{strong_backend}:{strong_model}"

        if current_full_model == strong_full_model:
            return

        # Persist the original route so we can restore when planning phase ends
        try:
            has_original_backend = bool(
                getattr(session.state, "planning_phase_original_backend", None)
            )
            has_original_model = bool(
                getattr(session.state, "planning_phase_original_model", None)
            )
        except Exception:
            has_original_backend = False
            has_original_model = False

        if not (has_original_backend or has_original_model):
            new_state = session.state.with_planning_phase_original_route(
                requested_backend,
                requested_model,
            )
            session.update_state(new_state)
            if self._session_service:
                await self._session_service.update_session(session)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Planning phase active (turn {turn_count + 1}/{planning_config.max_turns}): "
                f"routing from {current_full_model} to {strong_full_model}"
            )

        new_backend_config = BackendConfiguration(
            backend_type=strong_backend,
            model=strong_model,
            interactive_mode=session.state.backend_config.interactive_mode,
        )

        new_state = session.state.with_backend_config(
            cast(IBackendConfig, new_backend_config)
        )
        session.update_state(new_state)
        if self._session_service:
            await self._session_service.update_session(session)

    async def update_counters(self, session_id: str, response: Any) -> None:
        """Update planning phase counters after a successful completion."""
        if not self._session_service:
            return

        try:
            session = await self._session_service.get_session(session_id)
            if not session or not session.state:
                return

            planning_config = session.state.planning_phase_config
            if not planning_config.enabled:
                return

            turn_count = session.state.planning_phase_turn_count
            file_write_count = session.state.planning_phase_file_write_count

            if (
                turn_count >= planning_config.max_turns
                or file_write_count >= planning_config.max_file_writes
            ):
                await self._restore_planning_phase_route(session)
                return

            new_turn_count = turn_count + 1
            new_file_write_count = file_write_count + self.count_file_writes(response)

            if new_turn_count != turn_count or new_file_write_count != file_write_count:
                new_state = session.state.with_multiple_updates(
                    planning_phase_turn_count=new_turn_count,
                    planning_phase_file_write_count=new_file_write_count,
                )

                session.update_state(new_state)
                await self._session_service.update_session(session)

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Updated session %s with planning_phase_turn_count=%d, "
                        "planning_phase_file_write_count=%d",
                        session_id,
                        new_turn_count,
                        new_file_write_count,
                    )

                if (
                    new_turn_count >= planning_config.max_turns
                    or new_file_write_count >= planning_config.max_file_writes
                ):
                    await self._restore_planning_phase_route(session)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to update planning phase counters: {e}", exc_info=True
                )

    def count_file_writes(self, response: Any) -> int:
        """Count file write tool calls in a response."""
        file_write_tools = {
            "write_file",
            "edit_file",
            "patch_file",
            "apply_diff",
            "search_replace",
            "str_replace_editor",
            "write_to_file",
            "create_file",
            "modify_file",
            "apply_patch",
            "edit_notebook",
        }

        count = 0
        tool_calls = []

        if hasattr(response, "metadata") and isinstance(response.metadata, dict):
            tool_calls = response.metadata.get("tool_calls", [])
        elif hasattr(response, "content") and isinstance(response.content, dict):
            choices = response.content.get("choices", [])
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message", {})
                if message and isinstance(message, dict):
                    tool_calls = message.get("tool_calls", [])

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("function", {}).get("name") or tool_call.get(
                    "name"
                )
                if tool_name and tool_name.lower() in file_write_tools:
                    count += 1

        return count

    async def _restore_planning_phase_route(self, session: Any) -> None:
        """Restore the original backend/model after planning phase concludes."""
        if not session or not session.state:
            return

        try:
            original_backend = getattr(
                session.state, "planning_phase_original_backend", None
            )
            original_model = getattr(
                session.state, "planning_phase_original_model", None
            )
        except Exception:
            return

        if original_backend is None and original_model is None:
            return

        from src.core.domain.configuration.backend_config import BackendConfiguration
        from src.core.interfaces.configuration_interface import IBackendConfig

        current_config = session.state.backend_config
        target_backend = original_backend or current_config.backend_type
        target_model = (
            original_model if original_model is not None else current_config.model
        )

        # Ensure not passing mock objects
        if hasattr(target_backend, "_extract_mock_name"):
            target_backend = str(target_backend)
        if hasattr(target_model, "_extract_mock_name"):
            target_model = str(target_model)

        restored_config = BackendConfiguration(
            backend_type=target_backend,
            model=target_model,
            interactive_mode=current_config.interactive_mode,
        )

        new_state = session.state.with_multiple_updates(
            backend_config=cast(IBackendConfig, restored_config),
            planning_phase_original_backend=None,
            planning_phase_original_model=None,
        )

        session.update_state(new_state)
        if self._session_service:
            await self._session_service.update_session(session)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Planning phase complete; restored session %s to backend=%s model=%s",
                getattr(session, "id", None),
                target_backend,
                target_model,
            )
