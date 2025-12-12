"""CLI Support Package.

This package contains extracted services and domain applicators for the CLI module.
It provides a modular architecture for CLI argument parsing, configuration application,
error handling, logging configuration, privilege checking, and server lifecycle management.

This is an internal package - the public CLI API remains in `src/core/cli.py`.
All classes here follow constructor injection for testability (Requirement 8.1, 8.2, 8.3).

Requirements satisfied:
- 10.1: New extracted helpers reside in `src/core/cli_support/`
- 10.2: `import src.core.cli` continues to import the `src/core/cli.py` module
- 10.3: Module structure clearly indicates each service's purpose
"""

from src.core.cli_support.argument_parser_builder import ArgumentParserBuilder
from src.core.cli_support.cli_args_validator import CliArgsValidator
from src.core.cli_support.configuration_applicator import ConfigurationApplicator

__all__ = [
    "ArgumentParserBuilder",
    "CliArgsValidator",
    "ConfigurationApplicator",
]
