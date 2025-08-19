"""
Unset command implementation.

This module provides a domain command for unsetting (clearing) various session parameters.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class UnsetCommand(BaseCommand):
    """Command for unsetting (clearing) various session parameters."""

    name = "unset"
    format = "unset(parameter)"
    description = "Unset (clear) various parameters for the session"
    examples = ["!/unset(model)", "!/unset(temperature)"]

    def __init__(self) -> None:
        super().__init__()
        self.param_handlers = {
            "backend": self._unset_backend,
            "model": self._unset_model,
            "temperature": self._unset_temperature,
            "interactive-mode": self._unset_interactive_mode,
            "interactive": self._unset_interactive_mode,  # Alias
            "redact-api-keys-in-prompts": self._unset_redact_api_keys,
            "command-prefix": self._unset_command_prefix,
            "project": self._unset_project,
        }

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Unset various session parameters."""
        if not args or all(not v for v in args.values()):
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        parameters_to_unset = [p for p, v in args.items() if v]
        if not parameters_to_unset:
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        updated_state = session.state
        messages: list[str] = []
        data: dict[str, Any] = {}
        success_count = 0

        for param in parameters_to_unset:
            handler = self.param_handlers.get(param)
            if handler:
                result, new_state = handler(updated_state, context)
                updated_state = new_state
                messages.append(result.message)
                if result.data:
                    data.update(result.data)
                success_count += 1
            else:
                messages.append(f"Unknown parameter: {param}")

        if success_count == 0:
            return CommandResult(
                success=False, message="unset: nothing to do", name=self.name
            )

        return CommandResult(
            success=True,
            message="\n".join(messages),
            name=self.name,
            data=data,
            new_state=updated_state,
        )

    def _unset_backend(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.without_override()
        updated_state = state.with_backend_config(new_backend_config)
        result = CommandResult(
            success=True, message="Backend reset to default", data={"backend": None}
        )
        return result, updated_state

    def _unset_model(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.with_model(None)
        updated_state = state.with_backend_config(new_backend_config)
        result = CommandResult(
            success=True, message="Model reset to default", data={"model": None}
        )
        return result, updated_state

    def _unset_temperature(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        default_temp = ReasoningConfiguration().temperature
        reasoning_config = state.reasoning_config.with_temperature(default_temp)
        updated_state = state.with_reasoning_config(reasoning_config)
        result = CommandResult(
            success=True,
            message=f"Temperature reset to default ({default_temp})",
            data={"temperature": default_temp},
        )
        return result, updated_state

    def _unset_interactive_mode(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.with_interactive_mode(True)
        updated_state = state.with_backend_config(
            new_backend_config
        ).with_interactive_just_enabled(False)
        result = CommandResult(
            success=True,
            message="Interactive mode reset to default (enabled)",
            data={"interactive-mode": True},
        )
        return result, updated_state

    def _unset_redact_api_keys(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        # Try to get the app settings service from the service provider
        service_provider = context.get("service_provider")
        if service_provider:
            try:
                from src.core.interfaces.app_settings_interface import IAppSettings

                app_settings = service_provider.get_service(IAppSettings)
                if app_settings:
                    app_settings.set_redact_api_keys(True)
                    result = CommandResult(
                        success=True,
                        message="API key redaction reset to default (enabled)",
                        data={"redact-api-keys-in-prompts": True},
                    )
                    return result, state  # No state change in session
            except Exception:
                pass

        # Legacy fallback for backwards compatibility during transition
        try:
            from src.core.services.command_settings_service import get_default_instance

            get_default_instance().api_key_redaction_enabled = True

            # Legacy app.state support during transition
            app = context.get("app")
            if app:
                app.state.api_key_redaction_enabled = True
        except Exception:
            pass

        result = CommandResult(
            success=True,
            message="API key redaction reset to default (enabled)",
            data={"redact-api-keys-in-prompts": True},
        )
        return result, state  # No state change in session

    def _unset_command_prefix(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        # Try to get the app settings service from the service provider
        service_provider = context.get("service_provider")
        if service_provider:
            try:
                from src.core.interfaces.app_settings_interface import IAppSettings

                app_settings = service_provider.get_service(IAppSettings)
                if app_settings:
                    app_settings.set_command_prefix("!/")
                    result = CommandResult(
                        success=True,
                        message="Command prefix reset to default (!/)",
                        data={"command-prefix": "!/"},
                    )
                    return result, state  # No state change in session
            except Exception:
                pass

        # Legacy fallback for backwards compatibility during transition
        try:
            from src.core.services.command_settings_service import get_default_instance

            get_default_instance().command_prefix = "!/"

            # Legacy app.state support during transition
            app = context.get("app")
            if app:
                app.state.command_prefix = "!/"
        except Exception:
            pass

        result = CommandResult(
            success=True,
            message="Command prefix reset to default (!/)",
            data={"command-prefix": "!/"},
        )
        return result, state  # No state change in session

    def _unset_project(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        updated_state = state.with_project(None)
        result = CommandResult(
            success=True, message="Project reset to default", data={"project": None}
        )
        return result, updated_state
