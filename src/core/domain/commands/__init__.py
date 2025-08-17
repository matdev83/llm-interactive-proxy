"""
Commands domain module.

This module contains command implementations for the new architecture.
"""

from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
    RouteAppendCommand,
    RouteClearCommand,
    RouteListCommand,
    RoutePrependCommand,
)
from src.core.domain.commands.hello_command import HelloCommand
from src.core.domain.commands.help_command import HelpCommand
from src.core.domain.commands.oneoff_command import OneoffCommand
from src.core.domain.commands.pwd_command import PwdCommand
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.commands.unset_command import UnsetCommand

# CommandResult is in the parent command_results.py module
from ..command_results import CommandResult

__all__ = [
    "BaseCommand",
    "CommandResult",
    "CreateFailoverRouteCommand",
    "DeleteFailoverRouteCommand",
    "HelloCommand",
    "HelpCommand",
    "ListFailoverRoutesCommand",
    "OneoffCommand",
    "PwdCommand",
    "RouteAppendCommand",
    "RouteClearCommand",
    "RouteListCommand",
    "RoutePrependCommand",
    "SetCommand",
    "UnsetCommand",
]
