"""
OpenAI URL command implementation.

This module provides a domain command for setting the OpenAI API URL.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.constants import COMMAND_EXECUTION_ERROR
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatefulCommandBase
from src.core.domain.session import Session
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

logger = logging.getLogger(__name__)


class OpenAIUrlCommand(StatefulCommandBase, BaseCommand):
    """Command for setting the OpenAI API URL."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "openai-url"

    @property
    def format(self) -> str:
        return "openai-url(url=<api-url>)"

    @property
    def description(self) -> str:
        return "Set custom URL for OpenAI API calls"

    @property
    def examples(self) -> list[str]:
        return ["!/openai-url(url=https://api.example.com/v1)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set the OpenAI API URL.

        Args:
            args: Command arguments with URL
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        # Validate that this command was created through proper DI
        self._validate_di_usage()

        url = args.get("url")
        if not url:
            return CommandResult(
                success=False, message="OpenAI URL must be specified", name=self.name
            )

        try:
            # Validate URL format
            if not isinstance(url, str):
                return CommandResult(
                    success=False, message="OpenAI URL must be a string", name=self.name
                )

            url_val = url.strip()

            # Validate URL starts with http:// or https://
            if not url_val.startswith(("http://", "https://")):
                return CommandResult(
                    success=False,
                    message="OpenAI URL must start with http:// or https://",
                    name=self.name,
                )

            # Create new session state with updated OpenAI URL
            new_backend_config = session.state.backend_config.with_openai_url(url_val)
            updated_state = session.state.with_backend_config(new_backend_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"OpenAI URL set to {url_val}",
                data={"openai_url": url_val},
                new_state=updated_state,
            )
        except Exception as e:
            error_message = COMMAND_EXECUTION_ERROR.format(error=str(e))
            logger.error(error_message)
            return CommandResult(success=False, message=error_message, name=self.name)
