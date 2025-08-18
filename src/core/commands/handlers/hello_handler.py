"""
Hello command handler.

This handler implements the hello command, which displays a welcome banner.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    CommandHandlerResult,
    ICommandHandler,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.session import SessionState
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class HelloCommandHandler(ICommandHandler):
    """Handler for the hello command."""

    @property
    def name(self) -> str:
        """The name of the command."""
        return "hello"

    @property
    def aliases(self) -> list[str]:
        """Aliases for the command."""
        return []

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Return the interactive welcome banner"

    @property
    def usage(self) -> str:
        """Usage information for the command."""
        return "hello"

    @property
    def examples(self) -> list[str]:
        """Examples of command usage."""
        return ["!/hello"]

    def can_handle(self, command_name: str) -> bool:
        """Check if this handler can handle the given command.

        Args:
            command_name: The name of the command to check

        Returns:
            True if this handler can handle the command, False otherwise
        """
        command_lower = command_name.lower()
        return command_lower == self.name or command_lower in self.aliases

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle the hello command.

        Args:
            param_value: The value to set (ignored for this command)
            current_state: The current session state
            context: Optional command context

        Returns:
            Command execution result
        """
        # Handle case where state is None by creating a default state
        if current_state is None:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )
            from src.core.domain.configuration.loop_detection_config import (
                LoopDetectionConfiguration,
            )
            from src.core.domain.configuration.reasoning_config import (
                ReasoningConfiguration,
            )

            # Create a default session state
            new_state = SessionState(
                backend_config=BackendConfiguration(),
                reasoning_config=ReasoningConfiguration(),
                loop_config=LoopDetectionConfiguration(),
                project=None,
                project_dir=None,
                interactive_just_enabled=False,
                hello_requested=True,
                is_cline_agent=False,
            )
        else:
            # Create a new session state with hello_requested=True
            # Cast interface types to concrete types
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )
            from src.core.domain.configuration.loop_detection_config import (
                LoopDetectionConfiguration,
            )
            from src.core.domain.configuration.reasoning_config import (
                ReasoningConfiguration,
            )

            backend_config = (
                current_state.backend_config
                if isinstance(current_state.backend_config, BackendConfiguration)
                else BackendConfiguration(
                    backend_type=current_state.backend_config.backend_type,
                    model=current_state.backend_config.model,
                    api_url=current_state.backend_config.api_url,
                    interactive_mode=current_state.backend_config.interactive_mode,
                    openai_url=getattr(
                        current_state.backend_config, "openai_url", None
                    ),
                )
            )

            reasoning_config = (
                current_state.reasoning_config
                if isinstance(current_state.reasoning_config, ReasoningConfiguration)
                else ReasoningConfiguration(
                    reasoning_effort=current_state.reasoning_config.reasoning_effort,
                    thinking_budget=current_state.reasoning_config.thinking_budget,
                    temperature=current_state.reasoning_config.temperature,
                )
            )

            loop_config = (
                current_state.loop_config
                if isinstance(current_state.loop_config, LoopDetectionConfiguration)
                else LoopDetectionConfiguration(
                    loop_detection_enabled=current_state.loop_config.loop_detection_enabled,
                    tool_loop_detection_enabled=current_state.loop_config.tool_loop_detection_enabled,
                )
            )

            new_state = SessionState(
                backend_config=backend_config,
                reasoning_config=reasoning_config,
                loop_config=loop_config,
                project=current_state.project,
                project_dir=current_state.project_dir,
                interactive_just_enabled=current_state.interactive_just_enabled,
                hello_requested=True,
                is_cline_agent=current_state.is_cline_agent,
            )

        # Wrap the SessionState in a SessionStateAdapter to make it ISessionState
        from src.core.domain.session import SessionStateAdapter

        adapted_state = SessionStateAdapter(new_state)

        return CommandHandlerResult(
            success=True,
            message="Hello, this is llm-interactive-proxy v0.1.0. hello acknowledged",
            new_state=adapted_state,
        )
