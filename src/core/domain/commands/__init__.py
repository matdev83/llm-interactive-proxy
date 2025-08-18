"""
Commands domain module.

This module contains command implementations for the new architecture.
"""

# Import only the base command to avoid circular imports
from src.core.domain.commands.base_command import BaseCommand

# CommandResult is in the parent command_results.py module
from ..command_results import CommandResult

__all__ = [
    "BaseCommand",
    "CommandResult",
]
