"""Pytest Context Saving Handler.

This handler modifies pytest commands to include flags that provide a more
concise and useful output for LLM consumption. It adds `-r fE` and `-q`
to pytest commands that do not already have them.

The feature is opt-in and controlled by a configuration flag.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

# Import from unified steering policy (replaces legacy pytest_full_suite_handler)
from src.services.steering.policies.pytest_full_suite_policy import (
    _PYTEST_ROOT_PATTERN,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.propagate = False
PASS_THROUGH_RESULT = ToolCallReactionResult(should_swallow=False)
_DEFAULT_SHELL_TOOL_NAMES = frozenset(
    {
        "bash",
        "exec_command",
        "execute_command",
        "run_shell_command",
        "shell",
        "local_shell",
        "container.exec",
    }
)


def _has_short_flag(token: str, flag_char: str) -> bool:
    return token.startswith(f"-{flag_char}") and not token.startswith("--")


def _has_verbose_flag(token: str) -> bool:
    return token == "--verbose" or _has_short_flag(token, "v")


def _has_quiet_flag(token: str) -> bool:
    return token == "--quiet" or _has_short_flag(token, "q")


def _extract_command(arguments: Any) -> str | None:
    """Extract shell command string from tool arguments.

    Supports various shapes including strings, dicts with "command"/"cmd", nested
    inputs, and arg lists. This is a standalone utility for command extraction.
    """
    if arguments is None:
        return None

    # If it's already a string, see if it's JSON first
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            arguments = parsed
        except (ValueError, TypeError):
            # Plain string - type narrowing tells us it's still str
            return str(arguments)

    # If dict, try common fields
    if isinstance(arguments, dict):
        cmd = arguments.get("command") or arguments.get("cmd")
        if isinstance(cmd, str) and cmd.strip():
            return cmd
        # Sometimes a sub-dict holds the command
        for key in ("input", "body", "data"):
            inner = arguments.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner
            if isinstance(inner, dict):
                sub = inner.get("command") or inner.get("cmd")
                if isinstance(sub, str) and sub.strip():
                    return sub
        # If args provided (list or string), handle it
        args = arguments.get("args")
        if isinstance(args, list) and args:
            try:
                return " ".join(str(a) for a in args)
            except (TypeError, ValueError, MemoryError):
                # Log unexpected errors during string conversion
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert args list to command string",
                        exc_info=True,
                    )
                return None
        if isinstance(args, str) and args.strip():
            return args
        return None

    # If list/tuple, join
    if isinstance(arguments, list | tuple):
        try:
            return " ".join(str(a) for a in arguments)
        except (TypeError, ValueError, MemoryError):
            # Log unexpected errors during string conversion
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to convert arguments list/tuple to command string",
                    exc_info=True,
                )
            return None
    return None


class PytestContextSavingHandler(IToolCallHandler):
    """Handler to modify pytest commands for context saving."""

    def __init__(
        self,
        enabled: bool = True,
        shell_tool_names: Iterable[str] | None = None,
    ):
        self._enabled = enabled
        self._command_cache: OrderedDict[str, str] = OrderedDict()
        self._cache_limit = 256
        if shell_tool_names is None:
            self._shell_tool_names = {
                name.lower() for name in _DEFAULT_SHELL_TOOL_NAMES
            }
        else:
            self._shell_tool_names = {name.lower() for name in shell_tool_names}

    @property
    def name(self) -> str:
        return "pytest_context_saving_handler"

    @property
    def priority(self) -> int:
        # Lower priority than PytestFullSuiteHandler to run after it.
        return 90

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        command = self._fast_extract_command(context.tool_arguments)
        if not command:
            return False

        tool_name = context.tool_name or ""
        tool_name_lower = tool_name.lower()
        if (
            tool_name_lower not in self._shell_tool_names
            and not _PYTEST_ROOT_PATTERN.fullmatch(tool_name_lower)
        ):
            return False

        return bool(_PYTEST_ROOT_PATTERN.search(command))

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        if not self._enabled:
            return PASS_THROUGH_RESULT

        command = self._fast_extract_command(context.tool_arguments)
        if not command:
            return PASS_THROUGH_RESULT

        cached_command = self._command_cache.get(command)
        log_modification = False
        if cached_command is not None:
            self._command_cache.move_to_end(command)
            modified_command = cached_command
        else:
            modified_command = self._add_pytest_flags(command)
            self._command_cache[command] = modified_command
            if len(self._command_cache) > self._cache_limit:
                self._command_cache.popitem(last=False)
            log_modification = True

        if modified_command != command:
            if log_modification:
                logger.info(
                    "Modifying pytest command in session %s: '%s' -> '%s'",
                    context.session_id,
                    command,
                    modified_command,
                )
            self._update_tool_arguments(context, modified_command)

        return PASS_THROUGH_RESULT

    @staticmethod
    def _fast_extract_command(arguments: Any) -> str | None:
        """Fast-path command extraction for common dictionary inputs."""
        if isinstance(arguments, dict):
            candidate = arguments.get("command") or arguments.get("cmd")
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        command = _extract_command(arguments)
        if command and command.strip():
            return command
        return None

    def _add_pytest_flags(self, command: str) -> str:
        """Add context-saving flags to a pytest command."""
        tokens = command.split()
        if not tokens:
            return command

        pytest_index = -1
        has_r_flag = False
        has_q_flag = False
        has_verbose_flag = False
        for index, token in enumerate(tokens):
            if pytest_index == -1 and "pytest" in token:
                pytest_index = index

            lowered = token.lower()
            if not has_r_flag and (lowered == "-r" or lowered.startswith("-r")):
                has_r_flag = True
            if not has_q_flag and _has_quiet_flag(token):
                has_q_flag = True
            if not has_verbose_flag and _has_verbose_flag(token):
                has_verbose_flag = True

            if pytest_index != -1 and has_r_flag and (has_q_flag or has_verbose_flag):
                break

        if pytest_index == -1:
            return command

        to_insert: list[str] = []
        if not has_r_flag:
            to_insert.append("-r fE")
        if not has_q_flag and not has_verbose_flag:
            to_insert.append("-q")

        if not to_insert:
            return command

        insertion_point = pytest_index + 1
        tokens[insertion_point:insertion_point] = to_insert
        return " ".join(tokens)

    def _update_tool_arguments(
        self, context: ToolCallContext, new_command: str
    ) -> None:
        """Update the tool arguments with the modified command."""
        arguments = context.tool_arguments

        if isinstance(arguments, dict):
            self._update_mapping(arguments, new_command)
            return

        if isinstance(arguments, str):
            updated = self._update_string_arguments(arguments, new_command)
            context.tool_arguments = updated  # type: ignore[assignment]
            return

        if isinstance(arguments, list):
            context.tool_arguments = new_command.split()  # type: ignore[assignment]
            return

        # Attempt to decode JSON-like payloads stored in unexpected structures
        try:
            serialized = json.dumps(arguments)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            logger.debug(
                "Unsupported tool_arguments type %s for pytest context saving update",
                type(arguments),
            )
            return

        try:
            parsed = json.loads(serialized)
        except (json.JSONDecodeError, TypeError):
            return

        if isinstance(parsed, dict):
            self._update_mapping(parsed, new_command)
            context.tool_arguments = parsed

    @staticmethod
    def _update_mapping(mapping: dict[str, Any], new_command: str) -> None:
        if "command" in mapping:
            mapping["command"] = new_command
            return
        if "cmd" in mapping:
            mapping["cmd"] = new_command
            return
        if "input" in mapping and isinstance(mapping["input"], str):
            mapping["input"] = new_command
            return
        if "args" in mapping:
            args_value = mapping["args"]
            if isinstance(args_value, list):
                mapping["args"] = [new_command]
                return
            if isinstance(args_value, str):
                mapping["args"] = new_command
                return

        # Fallback: set a new command field to preserve output
        mapping["command"] = new_command

    @staticmethod
    def _update_string_arguments(arguments: str, new_command: str) -> str:
        stripped = arguments.strip()
        if not stripped:
            return new_command

        # Try JSON payloads first
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return new_command

        if isinstance(parsed, dict):
            PytestContextSavingHandler._update_mapping(parsed, new_command)
            return json.dumps(parsed)

        return new_command
