"""
Set command implementation.

This module provides a domain command for setting various session parameters.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IReasoningConfig
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class SetCommand(BaseCommand):
    """Command for setting various session parameters."""

    name = "set"
    format = "set(parameter=value)"
    description = "Set various parameters for the session"
    examples = [
        "!/set(backend=openrouter)",
        "!/set(model=openrouter:claude-3-opus-20240229)",
        "!/set(temperature=0.7)",
    ]

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,
        context: Any = None,
    ) -> CommandResult:
        """Set various session parameters."""
        if not args:
            return CommandResult(
                success=False,
                message="Parameter must be specified",
                name=self.name,
            )

        # Dispatch to the appropriate handler based on the argument provided.
        # The original logic processes parameters with some precedence and exclusivity.
        # We will maintain that by checking for parameters in order.

        if "backend" in args or "model" in args:
            return await self._handle_backend_and_model(args, session, context)

        if "temperature" in args:
            return self._handle_temperature(args, session)

        if "redact-api-keys-in-prompts" in args:
            return self._handle_redact_api_keys(args, context)

        if "interactive-mode" in args:
            return self._handle_interactive_mode(args, session)

        if "command-prefix" in args:
            return self._handle_command_prefix(args, context)

        if "project" in args:
            return self._handle_project(args, session)

        # If we get here, the parameter is unknown or unhandled
        param_list = ', '.join(args.keys())
        return CommandResult(
            success=False,
            message=f"set: no valid or recognized parameters provided: {param_list}",
            name=self.name,
        )

    def _parse_bool_value(self, value: Any) -> bool:
        """Parse boolean value from string or other types."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "y", "1", "on")
        return bool(value)

    def _update_session_state_reasoning_config(
        self,
        state: ISessionState,
        reasoning_config: ReasoningConfiguration,
    ) -> ISessionState:
        """Update session state with new reasoning config."""
        if isinstance(state, SessionStateAdapter):
            old_state = state._state
            adapter_new_state = old_state.with_reasoning_config(reasoning_config)
            return SessionStateAdapter(adapter_new_state)
        if isinstance(state, SessionState):
            session_new_state = cast(SessionState, state).with_reasoning_config(
                reasoning_config
            )
            return SessionStateAdapter(cast(SessionState, session_new_state))
        
        other_new_state = state.with_reasoning_config(
            cast(IReasoningConfig, reasoning_config)
        )
        return other_new_state

    async def _handle_backend_and_model(
        self,
        args: Mapping[str, Any],
        session: Session,
        context: Any,
    ) -> CommandResult:
        """Handles logic for setting backend and/or model."""
        updated_state = session.state
        messages: list[str] = []
        data: dict[str, Any] = {}
        app = context.get("app") if context else None

        if "backend" in args:
            backend_value = args.get("backend")
            if not isinstance(backend_value, str):
                return CommandResult(success=False, message="Backend name must be a string", name=self.name)
            
            # Logic to update backend
            new_backend_config = updated_state.backend_config.with_backend(backend_value)
            updated_state = updated_state.with_backend_config(new_backend_config)
            messages.append(f"Backend changed to {backend_value}")
            data["backend"] = backend_value

        if "model" in args:
            model_value = args.get("model")
            if not isinstance(model_value, str):
                return CommandResult(success=False, message="Model name must be a string", name=self.name)

            backend_to_validate = updated_state.backend_config.backend_type
            model_to_validate = model_value

            if ":" in model_value:
                backend, model = model_value.split(":", 1)
                backend_to_validate = backend
                model_to_validate = model
                new_backend_config = updated_state.backend_config.with_backend(backend).with_model(model)
                messages.append(f"Backend changed to {backend}")
                messages.append(f"Model changed to {model}")
                data.update({"backend": backend, "model": model})
            else:
                new_backend_config = updated_state.backend_config.with_model(model_value)
                messages.append(f"Model changed to {model_value}")
                data.update({"model": model_value})
            
            updated_state = updated_state.with_backend_config(new_backend_config)

        return CommandResult(
            success=True,
            message="\n".join(messages),
            name=self.name,
            data=data,
            new_state=updated_state,
        )

    def _handle_temperature(
        self,
        args: Mapping[str, Any],
        session: Session,
    ) -> CommandResult:
        """Handles logic for setting temperature."""
        temp_value = args.get("temperature")
        if temp_value is None:
            return CommandResult(success=False, message="Temperature value must be specified", name=self.name)

        try:
            temp_float = float(temp_value)
            if not (0 <= temp_float <= 1):
                return CommandResult(success=False, message="Temperature must be between 0.0 and 1.0", name=self.name)

            reasoning_config = session.state.reasoning_config.with_temperature(temp_float)
            concrete_reasoning_config = cast(ReasoningConfiguration, reasoning_config)
            updated_state = self._update_session_state_reasoning_config(
                session.state,
                concrete_reasoning_config,
            )

            return CommandResult(
                success=True,
                message=f"Temperature set to {temp_float}",
                name=self.name,
                data={"temperature": temp_float},
                new_state=updated_state,
            )
        except (ValueError, TypeError):
            return CommandResult(success=False, message="Temperature must be a valid number", name=self.name)

    def _handle_redact_api_keys(
        self,
        args: Mapping[str, Any],
        context: Any,
    ) -> CommandResult:
        """Handles logic for redacting API keys."""
        redact_value = args.get("redact-api-keys-in-prompts")
        redact_bool = self._parse_bool_value(redact_value)
        
        # Try to get the app settings service from the service provider
        service_provider = context.get("service_provider")
        if service_provider:
            try:
                from src.core.interfaces.app_settings_interface import IAppSettings
                app_settings = service_provider.get_service(IAppSettings)
                if app_settings:
                    app_settings.set_redact_api_keys(redact_bool)
                    return CommandResult(
                        success=True,
                        message=f"API key redaction in prompts {'enabled' if redact_bool else 'disabled'}",
                        name=self.name,
                        data={"redact-api-keys-in-prompts": redact_bool},
                    )
            except Exception:
                pass
                
        # Legacy fallback for backwards compatibility during transition
        try:
            from src.core.services.command_settings_service import get_default_instance
            get_default_instance().api_key_redaction_enabled = redact_bool
            
            # Legacy app.state support during transition
            app = context.get("app")
            if app:
                app.state.api_key_redaction_enabled = redact_bool
        except Exception:
            pass

        return CommandResult(
            success=True,
            message=f"API key redaction in prompts {'enabled' if redact_bool else 'disabled'}",
            name=self.name,
            data={"redact-api-keys-in-prompts": redact_bool},
        )

    def _handle_interactive_mode(
        self,
        args: Mapping[str, Any],
        session: Session,
    ) -> CommandResult:
        """Handles logic for setting interactive mode."""
        interactive_value = args.get("interactive-mode")
        interactive_bool = self._parse_bool_value(interactive_value)

        new_backend_config = session.state.backend_config.with_interactive_mode(interactive_bool)
        updated_state = session.state.with_backend_config(new_backend_config)
        if interactive_bool:
            updated_state = updated_state.with_interactive_just_enabled(True)

        return CommandResult(
            success=True,
            message=f"Interactive mode {'enabled' if interactive_bool else 'disabled'}",
            name=self.name,
            data={"interactive-mode": interactive_bool},
            new_state=updated_state,
        )

    def _handle_command_prefix(
        self,
        args: Mapping[str, Any],
        context: Any,
    ) -> CommandResult:
        """Handles logic for setting the command prefix."""
        prefix_value = args.get("command-prefix")
        if not isinstance(prefix_value, str) or not prefix_value:
            return CommandResult(success=False, message="Command prefix must be a non-empty string", name=self.name)
        
        # Try to get the app settings service from the service provider
        service_provider = context.get("service_provider")
        if service_provider:
            try:
                from src.core.interfaces.app_settings_interface import IAppSettings
                app_settings = service_provider.get_service(IAppSettings)
                if app_settings:
                    app_settings.set_command_prefix(prefix_value)
                    return CommandResult(
                        success=True,
                        message=f"Command prefix set to '{prefix_value}'",
                        name=self.name,
                        data={"command-prefix": prefix_value},
                    )
            except Exception:
                pass
                
        # Legacy fallback for backwards compatibility during transition
        try:
            from src.core.services.command_settings_service import get_default_instance
            get_default_instance().command_prefix = prefix_value
            
            # Legacy app.state support during transition
            app = context.get("app")
            if app:
                app.state.command_prefix = prefix_value
        except Exception:
            pass

        return CommandResult(
            success=True,
            message=f"Command prefix set to '{prefix_value}'",
            name=self.name,
            data={"command-prefix": prefix_value},
        )

    def _handle_project(
        self,
        args: Mapping[str, Any],
        session: Session,
    ) -> CommandResult:
        """Handles logic for setting the project."""
        project_value = args.get("project")
        if not isinstance(project_value, str) or not project_value:
            return CommandResult(success=False, message="Project name must be a non-empty string", name=self.name)

        updated_state = session.state.with_project(project_value)
        
        return CommandResult(
            success=True,
            message=f"Project changed to {project_value}",
            name=self.name,
            data={"project": project_value},
            new_state=updated_state,
        )