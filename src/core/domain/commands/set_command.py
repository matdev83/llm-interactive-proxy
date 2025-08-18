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
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.configuration import IBackendConfig

logger = logging.getLogger(__name__)


class SetCommand(BaseCommand):
    """Command for setting various session parameters."""

    name = "set"
    format = "set(parameter=value)"
    description = "Set various parameters for the session"
    examples = [
        "!/set(backend=openrouter)",
        "!/set(model=openrouter:claude-3-opus-20240229)",
        "!/set(redact-api-keys-in-prompts=true)",
        "!/set(interactive-mode=true)",
        "!/set(command-prefix=!)",
        "!/set(temperature=0.7)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set various session parameters.

        Args:
            args: Command arguments with parameter name and value
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        if not args:
            return CommandResult(
                success=False,
                message="Parameter must be specified",
                name=self.name,
            )

        # Handle backend parameter
        if "backend" in args:
            backend_value = args.get("backend")
            if not backend_value:
                return CommandResult(
                    success=False,
                    message="Backend name must be specified",
                    name=self.name,
                )
            
            # Check if backend is in functional backends
            app = context.get("app")
            if app and hasattr(app.state, "functional_backends"):
                if backend_value not in app.state.functional_backends:
                    return CommandResult(
                        success=False,
                        message=f"Backend {backend_value} not functional",
                        name=self.name,
                    )
            
            # Set backend in session state
            updated_state = self._update_session_state(session.state, "override_backend", backend_value)
            
            # Create command result
            cmd_result = CommandResult(
                success=True,
                message=f"Backend changed to {backend_value}",
                name=self.name,
                data={"backend": backend_value},
                new_state=updated_state,
            )
            
            # Store command result in session state for test access
            updated_state = self._update_session_state(updated_state, "_last_command_result", cmd_result)
            cmd_result.new_state = updated_state
            
            return cmd_result
            
        # Handle model parameter
        if "model" in args:
            model_value = args.get("model")
            if not model_value:
                return CommandResult(
                    success=False,
                    message="Model name must be specified",
                    name=self.name,
                )
                
            # Check if model contains backend prefix
            if ":" in model_value:
                backend, model = model_value.split(":", 1)
                # Set both backend and model
                updated_state = self._update_session_state(session.state, "override_backend", backend)
                updated_state = self._update_session_state(updated_state, "override_model", model)
                
                # Create command result
                cmd_result = CommandResult(
                    success=True,
                    message=f"Backend changed to {backend}\nModel changed to {model}",
                    name=self.name,
                    data={"backend": backend, "model": model},
                    new_state=updated_state,
                )
                
                # Store command result in session state for test access
                updated_state = self._update_session_state(updated_state, "_last_command_result", cmd_result)
                cmd_result.new_state = updated_state
                
                return cmd_result
            else:
                # Set only model
                updated_state = self._update_session_state(session.state, "override_model", model_value)
                
                # Create command result
                cmd_result = CommandResult(
                    success=True,
                    message=f"Model changed to {model_value}",
                    name=self.name,
                    data={"model": model_value},
                    new_state=updated_state,
                )
                
                # Store command result in session state for test access
                updated_state = self._update_session_state(updated_state, "_last_command_result", cmd_result)
                cmd_result.new_state = updated_state
                
                return cmd_result
                
        # Handle temperature parameter
        if "temperature" in args:
            temp_value = args.get("temperature")
            if not temp_value:
                return CommandResult(
                    success=False,
                    message="Temperature value must be specified",
                    name=self.name,
                )
                
            try:
                # Convert to float and validate range
                temp_float = float(temp_value)
                if temp_float < 0 or temp_float > 1:
                    return CommandResult(
                        success=False,
                        message="Temperature must be between 0.0 and 1.0",
                        name=self.name,
                    )
                
                # Create new reasoning config with updated temperature
                reasoning_config = session.state.reasoning_config.with_temperature(
                    temp_float
                )
                
                # Cast to concrete type
                concrete_reasoning_config = cast(ReasoningConfiguration, reasoning_config)
                
                # Create new session state with updated reasoning config
                updated_state = self._update_session_state_reasoning_config(
                    session.state, concrete_reasoning_config
                )
                
                return CommandResult(
                    success=True,
                    message=f"Temperature set to {temp_float}",
                    name=self.name,
                    data={"temperature": temp_float},
                    new_state=updated_state,
                )
            except ValueError:
                return CommandResult(
                    success=False,
                    message="Temperature must be a valid number",
                    name=self.name,
                )
            except Exception as e:
                logger.error(f"Error setting temperature: {e}")
                return CommandResult(
                    success=False,
                    message=f"Error setting temperature: {e}",
                    name=self.name,
                )
                
        # Handle redact-api-keys-in-prompts parameter
        if "redact-api-keys-in-prompts" in args:
            redact_value = args.get("redact-api-keys-in-prompts")
            if redact_value is None:
                return CommandResult(
                    success=False,
                    message="Value must be specified for redact-api-keys-in-prompts",
                    name=self.name,
                )
                
            # Convert to bool
            redact_bool = self._parse_bool_value(redact_value)
            
            # Update app state
            app = context.get("app")
            if app:
                app.state.api_key_redaction_enabled = redact_bool
                
            return CommandResult(
                success=True,
                message=f"API key redaction in prompts {'enabled' if redact_bool else 'disabled'}",
                name=self.name,
                data={"redact-api-keys-in-prompts": redact_bool},
            )
            
        # Handle interactive-mode parameter
        if "interactive-mode" in args:
            interactive_value = args.get("interactive-mode")
            if interactive_value is None:
                return CommandResult(
                    success=False,
                    message="Value must be specified for interactive-mode",
                    name=self.name,
                )
                
            # Convert to bool
            interactive_bool = self._parse_bool_value(interactive_value)
            
            # Update session state
            updated_state = self._update_session_state(session.state, "interactive_mode", interactive_bool)
            
            return CommandResult(
                success=True,
                message=f"Interactive mode {'enabled' if interactive_bool else 'disabled'}",
                name=self.name,
                data={"interactive-mode": interactive_bool},
                new_state=updated_state,
            )
            
        # Handle command-prefix parameter
        if "command-prefix" in args:
            prefix_value = args.get("command-prefix")
            if not prefix_value:
                return CommandResult(
                    success=False,
                    message="Value must be specified for command-prefix",
                    name=self.name,
                )
                
            # Update app state
            app = context.get("app")
            if app:
                app.state.command_prefix = prefix_value
                
            return CommandResult(
                success=True,
                message=f"Command prefix set to '{prefix_value}'",
                name=self.name,
                data={"command-prefix": prefix_value},
            )
        
        # If we get here, the parameter is unknown
        return CommandResult(
            success=False,
            message=f"Unknown parameter. Supported parameters: backend, model, temperature, redact-api-keys-in-prompts, interactive-mode, command-prefix",
            name=self.name,
        )
        
    def _parse_bool_value(self, value: Any) -> bool:
        """Parse boolean value from string or other types."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "y", "1", "on")
        return bool(value)
        
    def _update_session_state(self, state: ISessionState, attr_name: str, value: Any) -> ISessionState:
        """Update session state with new attribute value."""
        if isinstance(state, SessionStateAdapter):
            # Working with SessionStateAdapter - get the underlying state
            old_state = state._state
            # Create copy with updated attribute
            new_state_dict = old_state.__dict__.copy()
            new_state_dict[attr_name] = value
            # Create new instance with updated values
            new_state = type(old_state)(**new_state_dict)
            return SessionStateAdapter(new_state)
        elif isinstance(state, SessionState):
            # Working with SessionState directly
            new_state_dict = state.__dict__.copy()
            new_state_dict[attr_name] = value
            new_state = type(state)(**new_state_dict)
            return SessionStateAdapter(new_state)
        else:
            # Fallback for other implementations
            # Try to set attribute directly if supported
            try:
                setattr(state, attr_name, value)
            except (AttributeError, TypeError):
                logger.warning(f"Could not set {attr_name} on session state of type {type(state)}")
            return state
            
    def _update_session_state_reasoning_config(
        self, state: ISessionState, reasoning_config: ReasoningConfiguration
    ) -> ISessionState:
        """Update session state with new reasoning config."""
        if isinstance(state, SessionStateAdapter):
            # Working with SessionStateAdapter - get the underlying state
            old_state = state._state
            new_state = old_state.with_reasoning_config(reasoning_config)
            return SessionStateAdapter(new_state)
        elif isinstance(state, SessionState):
            # Working with SessionState directly
            new_state = state.with_reasoning_config(reasoning_config)
            return SessionStateAdapter(new_state)
        else:
            # Fallback for other implementations
            # Try to set attribute directly if supported
            try:
                state.reasoning_config = reasoning_config
            except (AttributeError, TypeError):
                logger.warning(f"Could not set reasoning_config on session state of type {type(state)}")
            return state
