"""
OpenAI URL handler for the set command.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.interfaces.domain_entities import ISessionState

logger = logging.getLogger(__name__)


class OpenAIURLHandler(BaseCommandHandler):
    """Handler for the openai_url parameter."""

    def __init__(self) -> None:
        super().__init__(name="openai-url", aliases=["openai_url"])

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter, False otherwise
        """
        normalized = param_name.lower().replace("_", "-")
        result = normalized == self.name.lower() or normalized in [
            a.lower() for a in self.aliases
        ]
        return result

    @property
    def description(self) -> str:
        return "Set the OpenAI API URL"

    @property
    def examples(self) -> list[str]:
        return ["!/set(openai_url=https://api.example.com/v1)"]

    def handle(
        self, param_value: Any, current_state: ISessionState, context: Any = None
    ) -> CommandHandlerResult:
        """Handle the openai_url parameter.

        Args:
            param_value: The parameter value
            current_state: The current session state
            context: Optional context

        Returns:
            Result of handling the parameter
        """
        url = str(param_value)

        # Validate URL
        if not url.startswith("http://") and not url.startswith("https://"):
            return CommandHandlerResult(
                success=False,
                message="OpenAI URL must start with http:// or https://",
                new_state=None,
            )

        # Update the state
        new_backend_config = current_state.backend_config.with_openai_url(url)
        updated_state = current_state.with_backend_config(new_backend_config)

        return CommandHandlerResult(
            success=True,
            message=f"OpenAI URL set to {url}",
            new_state=updated_state,
        )
