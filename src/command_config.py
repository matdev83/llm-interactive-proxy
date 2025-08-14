import re

from fastapi import FastAPI

from src.commands.base import BaseCommand, CommandResult
from src.proxy_logic import ProxyState


class CommandParserConfig:
    """Configuration for the CommandParser."""

    def __init__(
        self,
        proxy_state: ProxyState,
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
        proxy_state: ProxyState,
        app: FastAPI,
        command_pattern: re.Pattern,
        handlers: dict[str, BaseCommand],
        preserve_unknown: bool,
        command_results: list[CommandResult],
    ):
        self.proxy_state = proxy_state
        self.app = app
        self.command_pattern = command_pattern
        self.handlers = handlers
        self.preserve_unknown = preserve_unknown
        self.command_results = command_results
