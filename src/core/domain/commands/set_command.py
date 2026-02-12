from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.core.commands.set_parameter_registry import build_set_parameter_handlers
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatefulCommandBase
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)
from src.core.domain.session import Session
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

if TYPE_CHECKING:
    from src.core.commands.handlers.base_handler import CommandHandlerResult
    from src.core.interfaces.command_policy_service_interface import (
        ICommandPolicyService,
    )

logger = logging.getLogger(__name__)


class SetCommand(StatefulCommandBase, BaseCommand):
    """Command for setting various session parameters."""

    _PARAMETER_ALIASES: dict[str, str] = {"interactive": "interactive-mode"}

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification,
        policy_service: ICommandPolicyService | None = None,
    ):
        """Initialize with required state services.

        Args:
            state_reader: Service for reading state
            state_modifier: Service for modifying state
        """
        StatefulCommandBase.__init__(
            self,
            state_reader,
            state_modifier,
            policy_service=policy_service,
        )
        self._policy_service = policy_service
        self._parameter_handlers = build_set_parameter_handlers()

    @property
    def name(self) -> str:
        return "set"

    @property
    def format(self) -> str:
        return "set(parameter=value, ...)"

    @property
    def description(self) -> str:
        return "Set various parameters for the session"

    @property
    def examples(self) -> list[str]:
        return [
            "!/set(backend=openrouter)",
            "!/set(model=openrouter:claude-3-opus-20240229, temperature=0.8)",
        ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set various session parameters."""
        # Validate that this command was created through proper DI
        self._validate_di_usage()

        if not args:
            return CommandResult(
                success=False, message="Parameter(s) must be specified", name=self.name
            )

        updated_state = session.state
        messages: list[str] = []
        data: dict[str, Any] = {}

        normalized_args: dict[str, Any] = {}
        for param, value in args.items():
            normalized = self._normalize_param_name(param)
            if normalized in normalized_args:
                return CommandResult(
                    success=False,
                    message=f"Duplicate parameter provided: {normalized}",
                    name=self.name,
                )
            normalized_args[normalized] = value

        if self._is_static_route_locked():
            blocked_params = [
                name for name in ("backend", "model") if name in normalized_args
            ]
            if blocked_params:
                return CommandResult(
                    success=False,
                    message=(
                        f"Cannot change {' and '.join(blocked_params)} when static routing is enabled via --static-route CLI parameter"
                    ),
                    name=self.name,
                )

        remaining_args = dict(normalized_args)
        handled_any = False

        if "backend" in remaining_args or "model" in remaining_args:
            result, updated_state = await self._handle_backend_and_model(
                remaining_args, updated_state, context
            )
            if not result.success:
                return result
            messages.append(result.message)
            if result.data:
                data.update(result.data)
            remaining_args.pop("backend", None)
            remaining_args.pop("model", None)
            handled_any = True

        for param, value in remaining_args.items():
            handler = getattr(self, f"_handle_{param.replace('-', '_')}", None)
            if handler is not None:
                command_result: CommandResult
                command_result, updated_state = await handler(
                    value, updated_state, context
                )
                if not command_result.success:
                    return command_result
                if command_result.message:
                    messages.append(command_result.message)
                if command_result.data:
                    data.update(command_result.data)
                handled_any = True
                continue

            parameter_handler = self._parameter_handlers.get(param)
            if parameter_handler is not None:
                parameter_result: CommandHandlerResult = parameter_handler.handle(
                    value, updated_state, context
                )
                if not parameter_result.success:
                    return CommandResult(
                        success=False,
                        message=parameter_result.message,
                        name=self.name,
                    )
                if parameter_result.new_state is not None:
                    updated_state = parameter_result.new_state
                if parameter_result.message:
                    messages.append(parameter_result.message)
                if parameter_result.additional_data:
                    data.update(parameter_result.additional_data)
                handled_any = True
                continue

            return CommandResult(
                success=False, message=f"Unknown parameter: {param}", name=self.name
            )

        if not handled_any:
            return CommandResult(
                success=False, message="No valid parameters provided.", name=self.name
            )

        return CommandResult(
            success=True,
            message="\n".join(m for m in messages if m) or "Settings updated",
            name=self.name,
            data=data,
            new_state=updated_state,
        )

    def _normalize_param_name(self, name: str) -> str:
        normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
        return self._PARAMETER_ALIASES.get(normalized, normalized)

    async def _handle_backend_and_model(
        self, args: dict[str, Any], state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        messages = []
        data = {}
        updated_state = state

        if "backend" in args:
            backend_value = args.get("backend")
            if not isinstance(backend_value, str):
                return (
                    CommandResult(
                        success=False, message="Backend name must be a string"
                    ),
                    state,
                )
            new_backend_config = updated_state.backend_config.with_backend(
                backend_value
            )
            updated_state = updated_state.with_backend_config(new_backend_config)
            messages.append(f"Backend changed to {backend_value}")
            data["backend"] = backend_value

        if "model" in args:
            model_value = args.get("model")
            if not isinstance(model_value, str):
                return (
                    CommandResult(success=False, message="Model name must be a string"),
                    state,
                )

            if has_explicit_backend_selector(model_value):
                parsed = parse_model_backend(model_value, "")
                backend = parsed.backend_type.strip()
                model = parsed.model_name.strip()
                if not backend or not model:
                    return (
                        CommandResult(
                            success=False,
                            message=(
                                "Invalid model selector. Use backend:model with non-empty backend and model."
                            ),
                        ),
                        state,
                    )
                new_backend_config = updated_state.backend_config.with_backend(
                    backend
                ).with_model(model)
                messages.append(f"Backend changed to {backend}")
                messages.append(f"Model changed to {model}")
                data.update({"backend": backend, "model": model})
            else:
                normalized_model = model_value.strip()
                if not normalized_model:
                    return (
                        CommandResult(
                            success=False,
                            message="Model name must be a non-empty string",
                        ),
                        state,
                    )
                new_backend_config = updated_state.backend_config.with_model(
                    normalized_model
                )
                messages.append(f"Model changed to {normalized_model}")
                data.update({"model": normalized_model})
            updated_state = updated_state.with_backend_config(new_backend_config)

        return (
            CommandResult(success=True, message="\n".join(messages), data=data),
            updated_state,
        )

    async def _handle_temperature(
        self, value: Any, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        if value is None:
            return (
                CommandResult(
                    success=False, message="Temperature value must be specified"
                ),
                state,
            )
        try:
            temp_float = float(value)
            if not (0 <= temp_float <= 1):
                return (
                    CommandResult(
                        success=False, message="Temperature must be between 0.0 and 1.0"
                    ),
                    state,
                )
            reasoning_config = state.reasoning_config.with_temperature(temp_float)
            updated_state = state.with_reasoning_config(reasoning_config)
            return (
                CommandResult(
                    success=True,
                    message=f"Temperature set to {temp_float}",
                    data={"temperature": temp_float},
                ),
                updated_state,
            )
        except (ValueError, TypeError):
            return (
                CommandResult(
                    success=False, message="Temperature must be a valid number"
                ),
                state,
            )

    async def _handle_project(
        self, value: Any, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        if not isinstance(value, str) or not value:
            return (
                CommandResult(
                    success=False, message="Project name must be a non-empty string"
                ),
                state,
            )
        updated_state = state.with_project(value)
        return (
            CommandResult(
                success=True,
                message=f"Project changed to {value}",
                data={"project": value},
            ),
            updated_state,
        )

    async def _handle_command_prefix(
        self, value: Any, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        if not isinstance(value, str):
            return (
                CommandResult(success=False, message="Command prefix must be a string"),
                state,
            )

        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            value = value[1:-1]

        from src.command_prefix import validate_command_prefix

        error = validate_command_prefix(value)
        if error:
            return (
                CommandResult(
                    success=False, message=f"Invalid command prefix: {error}"
                ),
                state,
            )

        updated_state = state.with_command_prefix_override(value)

        return (
            CommandResult(
                success=True,
                message=f"Command prefix changed to {value}",
                data={"command-prefix": value},
            ),
            updated_state,
        )

    async def _handle_interactive_mode(
        self, value: Any, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        """Handle setting interactive mode."""
        if isinstance(value, bool):
            enabled = value
        elif isinstance(value, str):
            value_upper = value.upper()
            if value_upper in ("ON", "TRUE", "YES", "1", "ENABLED", "ENABLE"):
                enabled = True
            elif value_upper in ("OFF", "FALSE", "NO", "0", "DISABLED", "DISABLE"):
                enabled = False
            else:
                return (
                    CommandResult(
                        success=False,
                        message=(
                            f"Invalid interactive mode value: {value}. Use ON/OFF, TRUE/FALSE, etc."
                        ),
                    ),
                    state,
                )
        else:
            return (
                CommandResult(
                    success=False,
                    message=("Interactive mode value must be a string or boolean"),
                ),
                state,
            )

        new_backend_config = state.backend_config.with_interactive_mode(enabled)
        updated_state = state.with_backend_config(new_backend_config)
        updated_state = updated_state.with_interactive_just_enabled(enabled)

        return (
            CommandResult(
                success=True,
                message=f"Interactive mode {'enabled' if enabled else 'disabled'}",
                data={"interactive-mode": enabled},
            ),
            updated_state,
        )

    async def _handle_redact_api_keys_in_prompts(
        self, value: Any, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        """Handle setting API key redaction."""
        if not isinstance(value, str):
            return (
                CommandResult(
                    success=False, message="Redaction value must be a string"
                ),
                state,
            )

        value_lower = value.lower()
        if value_lower in ("true", "yes", "1", "on", "enabled", "enable"):
            enabled = True
        elif value_lower in ("false", "no", "0", "off", "disabled", "disable"):
            enabled = False
        else:
            return (
                CommandResult(
                    success=False,
                    message=f"Invalid redaction value: {value}. Use TRUE/FALSE, YES/NO, etc.",
                ),
                state,
            )

        updated_state = state.with_api_key_redaction_enabled(bool(enabled))

        return (
            CommandResult(
                success=True,
                message=f"API key redaction in prompts {'enabled' if enabled else 'disabled'}",
                data={"redact-api-keys-in-prompts": enabled},
            ),
            updated_state,
        )

    def _is_static_route_locked(self) -> bool:
        policy = getattr(self, "_policy_service", None)
        if policy is None:
            policy = self.policy_service

        if policy is not None:
            try:
                return policy.is_static_route_enforced()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Policy service failed to determine static routing: %s",
                    exc,
                    exc_info=True,
                )

        import os

        static_route = os.environ.get("STATIC_ROUTE")
        return bool(static_route and static_route.strip())
