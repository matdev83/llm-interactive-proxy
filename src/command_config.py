import re
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.core.domain.commands.base_command import BaseCommand
from src.core.interfaces.domain_entities import ISessionState

if TYPE_CHECKING:
    from src.core.interfaces.domain_entities import ISessionState


class CommandParserConfig:
    """Configuration for the CommandParser."""

    def __init__(
        self,
        proxy_state: ISessionState,
        app: FastAPI,
        preserve_unknown: bool,
        functional_backends: set[str] | None = None,
    ):
        self.proxy_state = proxy_state
        self.app = app
        self.preserve_unknown = preserve_unknown
        self.functional_backends = functional_backends or set()


class CommandProcessorConfig:
    """Configuration for the CommandProcessor."""

    def __init__(
        self,
        proxy_state: ISessionState,
        app: FastAPI,
        command_pattern: re.Pattern,
        handlers: dict[str, BaseCommand],
        preserve_unknown: bool,
        command_results: list,
    ):
        self.proxy_state = proxy_state
        self.app = app
        self.command_pattern = command_pattern
        self.handlers = handlers
        self.preserve_unknown = preserve_unknown
        self.command_results = command_results
