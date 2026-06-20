from __future__ import annotations

from src.core.commands.handlers.base_handler import BaseCommandHandler
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
)
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)


def build_set_parameter_handlers() -> dict[str, BaseCommandHandler]:
    """Return normalized parameter handlers for the set command."""
    handlers: list[BaseCommandHandler] = [
        ProjectDirCommandHandler(),
        LoopDetectionHandler(),
        ReasoningEffortHandler(),
        ThinkingBudgetHandler(),
        GeminiGenerationConfigHandler(),
    ]
    handler_map: dict[str, BaseCommandHandler] = {}
    for handler in handlers:
        names = [handler.name, *handler.aliases]
        for name in names:
            normalized = _normalize_param(name)
            handler_map[normalized] = handler
    return handler_map


def _normalize_param(param_name: str) -> str:
    return param_name.lower().replace("_", "-").replace(" ", "-")
