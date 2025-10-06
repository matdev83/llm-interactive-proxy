"""Pytest Full-Suite Steering Handler.

This handler warns agents when they attempt to execute a full pytest suite run
without specifying any target files, directories, or node expressions. The first
matching command within a session is swallowed and replaced with a steering
message encouraging selective test execution. If the agent re-issues the same
command immediately, the handler allows it to pass through.

The feature is opt-in and controlled by configuration flags.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


# Matches commands invoking pytest (pytest, python -m pytest, py.test, etc.)
_PYTEST_ROOT_PATTERN = re.compile(r"\b(pytest|py\.test)(?:\b|\.py\b)", re.IGNORECASE)


DEFAULT_STEERING_MESSAGE = (
    "You requested to run the whole test suite. This may be a lengthy process. "
    "Please consider running only selected tests for optimal speed. If you still "
    "believe you need to run the whole test suite, please re-send your tool call "
    "and it will be executed."
)


def _extract_command(arguments: Any) -> str | None:
    """Extract shell command string from tool arguments.

    Supports various shapes including strings, dicts with "command"/"cmd", nested
    inputs, and arg lists. Mirrors logic used by pytest compression service.
    """

    if arguments is None:
        return None

    if isinstance(arguments, str):
        try:
            import json

            parsed = json.loads(arguments)
        except (TypeError, ValueError):
            return arguments
        arguments = parsed

    if isinstance(arguments, dict):
        command = arguments.get("command") or arguments.get("cmd")
        command_str = _stringify_command_value(command)
        if command_str:
            return command_str

        for key in ("input", "body", "data"):
            inner = arguments.get(key)
            if isinstance(inner, dict):
                sub = inner.get("command") or inner.get("cmd")
                sub_str = _stringify_command_value(sub)
                if sub_str:
                    return sub_str

        args_list = arguments.get("args")
        if isinstance(args_list, list) and args_list:
            return " ".join(str(item) for item in args_list)

        return None

    if isinstance(arguments, list):
        return " ".join(str(item) for item in arguments)

    return None


def _normalize_whitespace(command: str) -> str:
    return " ".join(command.strip().split())


def _stringify_command_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list | tuple):
        parts: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                parts.append(text)
        if parts:
            return " ".join(parts)
    return None


def _looks_like_full_suite(command: str) -> bool:
    """Determine if the pytest command targets the entire suite.

    The heuristic identifies absence of file/dir/node selectors by checking for
    positional arguments that refer to files (contains path separators or ends
    with .py/.py[i]), directories, or node expressions (::). It also treats
    markers like -k, -m, -q, etc., as not selecting specific files.
    """

    normalized = _normalize_whitespace(command)
    if not _PYTEST_ROOT_PATTERN.search(normalized):
        return False

    tokens = normalized.split()

    # Skip the invocation part (e.g., python -m pytest, pytest, py.test)
    # Identify index where pytest command appears and inspect subsequent tokens.
    try:
        pytest_index = next(
            i for i, tok in enumerate(tokens) if _PYTEST_ROOT_PATTERN.search(tok)
        )
    except StopIteration:
        return False

    tail = tokens[pytest_index + 1 :]
    if not tail:
        return True  # plain "pytest"

    allowed_flag_prefixes = {"-", "--"}
    file_like_extensions = (".py", ".pyi")

    for token in tail:
        if not token:
            continue

        if any(token.startswith(prefix) for prefix in allowed_flag_prefixes):
            # Flags do not imply file selection; continue scanning
            continue

        # Strip trailing commas to handle cases like "pytest ,"
        stripped = token.strip(",")

        if "::" in stripped:
            return False

        if any(sep in stripped for sep in ("/", "\\")) or stripped.endswith(
            file_like_extensions
        ):
            return False

        if stripped == ".":
            # pytest . explicitly targets current directory
            return False

    return True


@dataclass
class _SessionState:
    last_command: str | None = None


class PytestFullSuiteHandler(IToolCallHandler):
    """Steering handler for full-suite pytest commands."""

    def __init__(self, message: str | None = None, enabled: bool = True) -> None:
        self._message = message or DEFAULT_STEERING_MESSAGE
        self._enabled = enabled
        self._session_state: dict[str, _SessionState] = {}

    @property
    def name(self) -> str:
        return "pytest_full_suite_handler"

    @property
    def priority(self) -> int:
        # Higher than generic config steering but below dangerous command handler
        return 95

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        command = self._extract_pytest_command(context)
        if not command:
            return False

        normalized = _normalize_whitespace(command)
        if not _looks_like_full_suite(normalized):
            return False

        state = self._session_state.get(context.session_id)
        return not (state and state.last_command == normalized)

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        command = self._extract_pytest_command(context)
        if not command:
            return ToolCallReactionResult(should_swallow=False)

        normalized = _normalize_whitespace(command)
        if not _looks_like_full_suite(normalized):
            return ToolCallReactionResult(should_swallow=False)

        state = self._session_state.setdefault(context.session_id, _SessionState())
        if state.last_command == normalized:
            return ToolCallReactionResult(should_swallow=False)

        state.last_command = normalized

        logger.info(
            "Steering full-suite pytest command in session %s: %s",
            context.session_id,
            normalized,
        )

        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=self._message,
            metadata={
                "handler": self.name,
                "tool_name": context.tool_name,
                "command": normalized,
                "source": "pytest_full_suite_steering",
            },
        )

    def _extract_pytest_command(self, context: ToolCallContext) -> str | None:
        tool_name = context.tool_name or ""
        arguments = context.tool_arguments

        shell_tools = {
            "bash",
            "exec_command",
            "execute_command",
            "run_shell_command",
            "shell",
            "local_shell",
            "container.exec",
        }

        if tool_name not in shell_tools:
            # Some providers map pytest directly as function name
            if _PYTEST_ROOT_PATTERN.search(tool_name):
                arg_str = _extract_command(arguments)
                return arg_str or tool_name
            return None

        return _extract_command(arguments)
