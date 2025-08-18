"""
Model command implementation.

This module provides a domain command for setting the model name.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class ModelCommand(BaseCommand):
    """Command for setting the model name."""

    name = "model"
    format = "model([name=model-name])"
    description = "Change the active model for LLM requests"
    examples = [
        "!/model(name=gpt-4)",
        "!/model(name=gemini-pro)",
        "!/model(name=claude-3-opus)",
        "!/model(name=openrouter:gpt-4)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set or unset the model name.

        Args:
            args: Command arguments with model name. If name is None or missing, model is unset.
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        model_name = args.get("name")
        # If model_name is None or empty string, treat as unset request
        if model_name is None or (
            isinstance(model_name, str) and not model_name.strip()
        ):
            # Unset the model
            try:
                # Create new backend config with model unset
                backend_config = session.state.backend_config.with_model(None)

                # Create new session state with updated backend config
                updated_state: ISessionState
                if isinstance(session.state, SessionStateAdapter):
                    # SessionStateAdapter.with_backend_config expects IBackendConfig and returns ISessionState
                    updated_state = session.state.with_backend_config(backend_config)
                elif isinstance(session.state, SessionState):
                    # SessionState.with_backend_config expects BackendConfiguration and returns SessionState
                    new_state = session.state.with_backend_config(
                        cast(BackendConfiguration, backend_config)
                    )
                    updated_state = SessionStateAdapter(new_state)
                else:
                    # Fallback for other implementations
                    try:
                        updated_state = session.state.with_backend_config(
                            backend_config
                        )
                    except AttributeError:
                        updated_state = session.state

                return CommandResult(
                    name=self.name,
                    success=True,
                    message="Model unset",
                    new_state=updated_state,
                )
            except Exception as e:
                logger.error(f"Error unsetting model: {e}")
                return CommandResult(
                    success=False,
                    message=f"Error unsetting model: {e}",
                    name=self.name,
                )

        # Continue with normal model setting logic
        if not model_name:
            return CommandResult(
                success=False,
                message="Model name must be specified",
                name=self.name,
            )

        try:
            # Parse model name for backend:model format
            backend_type = None
            actual_model = model_name

            if ":" in model_name:
                backend_type, actual_model = model_name.split(":", 1)

            # Create new backend config with updated model name and optionally backend
            backend_config = session.state.backend_config.with_model(actual_model)
            if backend_type:
                backend_config = backend_config.with_backend(backend_type)

            # Create new session state with updated backend config
            if isinstance(session.state, SessionStateAdapter):
                # SessionStateAdapter.with_backend_config expects IBackendConfig and returns ISessionState
                updated_state = session.state.with_backend_config(backend_config)
            elif isinstance(session.state, SessionState):
                # SessionState.with_backend_config expects BackendConfiguration and returns SessionState
                new_state = session.state.with_backend_config(
                    cast(BackendConfiguration, backend_config)
                )
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                try:
                    updated_state = session.state.with_backend_config(backend_config)
                except AttributeError:
                    updated_state = session.state

            message_parts = []
            if backend_type:
                message_parts.append(f"Backend changed to {backend_type}")
            message_parts.append(f"Model changed to {actual_model}")

            return CommandResult(
                name=self.name,
                success=True,
                message="; ".join(message_parts),
                data={"model": actual_model, "backend": backend_type},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error setting model: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting model: {e}",
                name=self.name,
            )
