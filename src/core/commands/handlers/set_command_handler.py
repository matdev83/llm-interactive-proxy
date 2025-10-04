from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.handlers.base_handler import BaseCommandHandler
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
    ToolLoopDetectionHandler,
    ToolLoopMaxRepeatsHandler,
    ToolLoopModeHandler,
    ToolLoopTTLHandler,
)
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.core.interfaces.command_service_interface import ICommandService


@command("set")
class SetCommandHandler(ICommandHandler):
    """Handler for the 'set' command."""

    def __init__(self, command_service: ICommandService | None = None) -> None:
        super().__init__(command_service)
        self._parameter_handlers = self._build_parameter_handlers()
        self.command_service = command_service

    @property
    def command_name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set a session value."

    @property
    def format(self) -> str:
        return "!/set(key=value)"

    @property
    def examples(self) -> list[str]:
        return ["!/set(model=anthropic/claude-3-opus-20240229)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle set command by updating session state for supported keys."""
        if not command.args:
            return CommandResult(
                success=False,
                message="No arguments provided.",
                name=self.command_name,
            )

        handled_any = False
        processed_params: set[str] = set()

        backend_result = self._apply_backend_argument(command.args, session)
        if backend_result is not None:
            return backend_result
        if self._has_parameter(command.args, "backend"):
            handled_any = True
            processed_params.add("backend")

        model_result = self._apply_model_argument(command.args, session)
        if model_result is not None:
            return model_result
        if self._has_parameter(command.args, "model"):
            handled_any = True
            processed_params.add("model")

        for raw_key, value in command.args.items():
            normalized = self._normalize_param(raw_key)
            if normalized in processed_params:
                continue

            if normalized == "temperature":
                temperature_result = self._apply_temperature(value, session)
                if temperature_result is not None:
                    return temperature_result
                handled_any = True
                processed_params.add(normalized)
                continue

            if normalized == "project":
                project_result = self._apply_project(value, session)
                if project_result is not None:
                    return project_result
                handled_any = True
                processed_params.add(normalized)
                continue

            handler = self._parameter_handlers.get(normalized)
            if handler is not None:
                handler_result = handler.handle(value, session.state)
                if not handler_result.success:
                    return CommandResult(
                        success=False,
                        message=handler_result.message,
                        name=self.command_name,
                    )
                if handler_result.new_state is not None:
                    session.state = handler_result.new_state
                handled_any = True
                processed_params.add(normalized)
                continue

            return CommandResult(
                success=False,
                message=f"Unknown parameter: {raw_key}",
                name=self.command_name,
            )

        if not handled_any:
            return CommandResult(
                success=False,
                message="No valid parameters provided.",
                name=self.command_name,
            )

        return CommandResult(
            success=True,
            message="Settings updated",
            name=self.command_name,
            new_state=session.state,
        )

    def _apply_backend_argument(
        self, args: Mapping[str, Any], session: Session
    ) -> CommandResult | None:
        for key, value in args.items():
            if self._normalize_param(key) != "backend":
                continue
            if not isinstance(value, str):
                return CommandResult(
                    success=False,
                    message="Backend name must be a string",
                    name=self.command_name,
                )
            new_backend_config = session.state.backend_config.with_backend(value)
            session.state = session.state.with_backend_config(new_backend_config)
            return None
        return None

    def _apply_model_argument(
        self, args: Mapping[str, Any], session: Session
    ) -> CommandResult | None:
        for key, value in args.items():
            if self._normalize_param(key) != "model":
                continue
            if value is None:
                new_backend_config = session.state.backend_config.with_model(None)
                session.state = session.state.with_backend_config(new_backend_config)
                return None
            if not isinstance(value, str):
                return CommandResult(
                    success=False,
                    message="Model name must be a string",
                    name=self.command_name,
                )
            model_value = value
            if ":" in model_value:
                backend_part, model_part = model_value.split(":", 1)
                backend_error = self._apply_backend_argument(
                    {"backend": backend_part}, session
                )
                if backend_error is not None:
                    return backend_error
                model_value = model_part
            new_backend_config = session.state.backend_config.with_model(model_value)
            session.state = session.state.with_backend_config(new_backend_config)
            return None
        return None

    def _apply_temperature(self, value: Any, session: Session) -> CommandResult | None:
        if value is None:
            return CommandResult(
                success=False,
                message="Temperature value must be specified",
                name=self.command_name,
            )
        try:
            temperature = float(value)
        except (TypeError, ValueError):
            return CommandResult(
                success=False,
                message="Temperature must be a valid number",
                name=self.command_name,
            )
        if not 0.0 <= temperature <= 1.0:
            return CommandResult(
                success=False,
                message="Temperature must be between 0.0 and 1.0",
                name=self.command_name,
            )
        reasoning_config = session.state.reasoning_config.with_temperature(temperature)
        session.state = session.state.with_reasoning_config(reasoning_config)
        return None

    def _apply_project(self, value: Any, session: Session) -> CommandResult | None:
        if not isinstance(value, str) or not value:
            return CommandResult(
                success=False,
                message="Project name must be a non-empty string",
                name=self.command_name,
            )
        session.state = session.state.with_project(value)
        return None

    def _build_parameter_handlers(self) -> dict[str, BaseCommandHandler]:
        handlers: list[BaseCommandHandler] = [
            ProjectDirCommandHandler(),
            LoopDetectionHandler(),
            ToolLoopDetectionHandler(),
            ToolLoopMaxRepeatsHandler(),
            ToolLoopModeHandler(),
            ToolLoopTTLHandler(),
            ReasoningEffortHandler(),
            ThinkingBudgetHandler(),
            GeminiGenerationConfigHandler(),
        ]
        handler_map: dict[str, BaseCommandHandler] = {}
        for handler in handlers:
            names = [handler.name, *handler.aliases]
            for name in names:
                handler_map[self._normalize_param(name)] = handler
        return handler_map

    def _normalize_param(self, param_name: str) -> str:
        return param_name.lower().replace("_", "-").replace(" ", "-")

    def _has_parameter(self, args: Mapping[str, Any], name: str) -> bool:
        normalized_name = self._normalize_param(name)
        return any(
            self._normalize_param(arg_name) == normalized_name for arg_name in args
        )
