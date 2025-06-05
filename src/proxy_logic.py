import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyState:
    """Manages the state of the proxy, particularly model overrides."""

    def __init__(self) -> None:
        self.override_model: Optional[str] = None
        self.project: Optional[str] = None

    def set_override_model(self, model_name: str) -> None:
        logger.info(f"Setting override model to: {model_name}")
        self.override_model = model_name

    def unset_override_model(self) -> None:
        logger.info("Unsetting override model.")
        self.override_model = None

    def set_project(self, project_name: str) -> None:
        logger.info(f"Setting project to: {project_name}")
        self.project = project_name

    def unset_project(self) -> None:
        logger.info("Unsetting project.")
        self.project = None

    def reset(self) -> None:
        logger.info("Resetting ProxyState instance.")
        self.override_model = None
        self.project = None

    def get_effective_model(self, requested_model: str) -> str:
        if self.override_model:
            logger.info(
                f"Overriding requested model '{requested_model}' with '{self.override_model}'"
            )
            return self.override_model
        return requested_model


# Re-export command parsing helpers from the dedicated module for backward compatibility
from .command_parser import (
    parse_arguments,
    get_command_pattern,
    _process_text_for_commands,
    process_commands_in_messages,
    CommandParser,
)

__all__ = [
    "ProxyState",
    "parse_arguments",
    "get_command_pattern",
    "_process_text_for_commands",
    "process_commands_in_messages",
    "CommandParser",
]
