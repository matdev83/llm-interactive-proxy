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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


# Matches commands invoking pytest (pytest, python -m pytest, py.test, etc.)
_PYTEST_ROOT_PATTERN = re.compile(r"\b(pytest|py\.test)(?:\b|\.py\b)", re.IGNORECASE)

_FILTERING_FLAGS = {
    "-k",
    "-m",
    "--deselect",
    "--lf",
    "--lfnf",
    "--ff",
    "--ffnf",
    "--stepwise-skip",
}


_FLAGS_REQUIRING_VALUE = {
    "-k",
    "-m",
    "-c",
    "-p",
    "-o",
    "-n",
    "--maxfail",
    "--deselect",
    "--lfnf",
    "--ffnf",
    "--max-worker-restart",
    "--max-workers",
    "--dist",
    "--tx",
    "--cov",
    "--cov-report",
    "--rootdir",
    "--basetemp",
    "--junitxml",
    "--resultlog",
    "--log-cli-level",
    "--log-cli-format",
    "--log-cli-date-format",
    "--log-file",
    "--log-file-level",
    "--log-file-format",
    "--log-file-date-format",
    "--durations",
    "--max-slave-restart",
    "--pdbcls",
    "--pastebin",
    "--reruns",
    "--reruns-delay",
    "--stepwise-skip",
}


_PYTEST_TOKEN_PATTERN = re.compile(
    r"^(?:pytest|py\.test)(?:\.(?:py|exe|bat))?$", re.IGNORECASE
)
_COMMAND_SEPARATORS = {"&&", "||", ";", "|", "&"}
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_NON_INVOCATION_PRECEDERS = {
    "add",
    "apt",
    "apk",
    "brew",
    "cat",
    "conda",
    "dnf",
    "echo",
    "find",
    "freeze",
    "grep",
    "head",
    "install",
    "list",
    "more",
    "npm",
    "pacman",
    "pip",
    "pip3",
    "pip-compile",
    "pip-sync",
    "pipenv",
    "pnpm",
    "poetry",
    "printf",
    "remove",
    "rg",
    "ripgrep",
    "search",
    "sed",
    "show",
    "sort",
    "tail",
    "tee",
    "touch",
    "uninstall",
    "update",
    "uv",
    "uvx",
    "yarn",
    "yum",
}
_WRAPPER_COMMANDS = {
    "bash",
    "cmd",
    "command",
    "env",
    "nice",
    "nohup",
    "powershell",
    "pwsh",
    "sh",
    "sudo",
    "time",
    "zsh",
}
_WRAPPER_PAIRS = {
    ("pipenv", "run"),
    ("poetry", "run"),
    ("hatch", "run"),
    ("rye", "run"),
    ("pdm", "run"),
    ("uv", "run"),
    ("uvx", "run"),
    ("pipx", "run"),
    ("npm", "run"),
    ("yarn", "run"),
    ("pnpm", "run"),
}


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
        if isinstance(command, str) and command.strip():
            return command
        if isinstance(command, list | tuple) and command:
            return " ".join(str(item) for item in command)

        for key in ("input", "body", "data"):
            inner = arguments.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner
            if isinstance(inner, dict):
                sub = inner.get("command") or inner.get("cmd")
                if isinstance(sub, str) and sub.strip():
                    return sub
                if isinstance(sub, list | tuple) and sub:
                    return " ".join(str(item) for item in sub)

        args_list = arguments.get("args")
        if isinstance(args_list, str):
            return args_list
        if isinstance(args_list, list) and args_list:
            return " ".join(str(item) for item in args_list)

        return None

    if (
        isinstance(arguments, Sequence)
        and not isinstance(arguments, str | bytes)
        and arguments
    ):
        return " ".join(str(item) for item in arguments)

    return None


def _normalize_whitespace(command: str) -> str:
    return " ".join(command.strip().split())


def _split_command_tokens(command: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote_char: str | None = None

    for char in command:
        if quote_char is not None:
            if char == quote_char:
                quote_char = None
            else:
                current.append(char)
            continue

        if char in {"'", '"'}:
            quote_char = char
            continue

        if char.isspace():
            if current:
                tokens.append("".join(current))
                current.clear()
            continue

        current.append(char)

    if current:
        tokens.append("".join(current))

    return tokens


def _normalize_token_for_matching(token: str) -> str:
    trimmed = token.strip().strip(",")
    if not trimmed:
        return ""

    trimmed = trimmed.rstrip(";|&")
    if "/" in trimmed or "\\" in trimmed:
        trimmed = trimmed.replace("\\", "/").rsplit("/", 1)[-1]

    return trimmed


def _previous_meaningful_index(
    tokens: list[str], normalized_tokens: list[str], start: int
) -> int | None:
    idx = start - 1
    while idx >= 0:
        normalized = normalized_tokens[idx]
        if not normalized:
            idx -= 1
            continue

        if _ASSIGNMENT_RE.match(normalized):
            idx -= 1
            continue

        raw = tokens[idx].strip()
        if normalized in {"-m", "--module"}:
            return idx

        if raw.startswith(("-", "/")):
            idx -= 1
            continue

        if idx > 0 and tokens[idx - 1].strip().startswith(("-", "/")):
            idx -= 2
            continue

        return idx

    return None


def _is_pytest_invocation(
    tokens: list[str], normalized_tokens: list[str], index: int
) -> bool:
    start = index
    while True:
        idx = _previous_meaningful_index(tokens, normalized_tokens, start)
        if idx is None:
            return True

        normalized = normalized_tokens[idx]
        lower = normalized.lower()

        if lower in _COMMAND_SEPARATORS:
            return True

        if lower in _NON_INVOCATION_PRECEDERS:
            return False

        if lower in {"-m", "--module"}:
            return True

        if lower == "run":
            prefix_idx = _previous_meaningful_index(tokens, normalized_tokens, idx)
            if prefix_idx is not None:
                prefix_lower = normalized_tokens[prefix_idx].lower()
                if (prefix_lower, lower) in _WRAPPER_PAIRS:
                    return True
                start = prefix_idx + 1
                continue

        if lower in _WRAPPER_COMMANDS:
            return True

        start = idx

        # Continue scanning further left to allow chained wrappers before returning
        if start == 0:
            return False


def _find_pytest_invocation_index(
    tokens: list[str], normalized_tokens: list[str]
) -> int | None:
    for index, normalized in enumerate(normalized_tokens):
        if not normalized:
            continue

        candidate = normalized
        if _PYTEST_TOKEN_PATTERN.fullmatch(candidate) and _is_pytest_invocation(
            tokens, normalized_tokens, index
        ):
            return index

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

    tokens = _split_command_tokens(normalized)
    if not tokens:
        return False

    normalized_tokens = [_normalize_token_for_matching(token) for token in tokens]
    pytest_index = _find_pytest_invocation_index(tokens, normalized_tokens)
    if pytest_index is None:
        return False

    tail = tokens[pytest_index + 1 :]
    if not tail:
        return True  # plain "pytest"

    allowed_flag_prefixes = {"-", "--"}
    file_like_extensions = (".py", ".pyi")

    skip_next_value = False

    for token in tail:
        if skip_next_value:
            skip_next_value = False
            continue

        if not token:
            continue

        if any(token.startswith(prefix) for prefix in allowed_flag_prefixes):
            flag_name, _, _ = token.partition("=")

            # Flags that explicitly select a subset of tests
            if flag_name in _FILTERING_FLAGS:
                return False

            if flag_name in _FLAGS_REQUIRING_VALUE and not token.endswith("="):
                skip_next_value = True
            continue

        # Strip trailing commas to handle cases like "pytest ,"
        stripped = token.strip(",")

        # Treat plain current-directory invocations (".") as full-suite runs
        if stripped in {".", "./", ".\\"}:
            return True

        if "::" in stripped:
            return False

        if any(sep in stripped for sep in ("/", "\\")) or stripped.endswith(
            file_like_extensions
        ):
            return False

        candidate = stripped.rstrip("/\\")
        if not candidate:
            continue

        # Detect directories passed as positional arguments (e.g. "pytest tests")
        # which indicate a targeted run rather than the entire suite.
        candidate_path = Path(candidate)
        if candidate_path.is_dir():
            return False

        # Support module-style selectors such as "pytest tests.unit.test_example"
        # by considering any dotted path that is not a Python file extension as
        # a targeted run.
        if "." in candidate and not candidate.endswith(file_like_extensions):
            return False

        if re.fullmatch(r"[A-Za-z0-9_]+", candidate):
            return False

    return True


@dataclass
class _SessionState:
    last_command: str | None = None
    last_seen: float = 0.0


class PytestFullSuiteHandler(IToolCallHandler):
    """Steering handler for full-suite pytest commands."""

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        *,
        state_ttl_seconds: int = 1800,
        max_sessions: int = 1024,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._message = message or DEFAULT_STEERING_MESSAGE
        self._enabled = enabled
        self._session_state: dict[str, _SessionState] = {}
        self._state_ttl_seconds = max(state_ttl_seconds, 1)
        self._max_sessions = max(max_sessions, 1)
        self._monotonic = monotonic or time.monotonic

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

        now = self._monotonic()
        self._prune_session_state(now)

        state = self._session_state.get(context.session_id)
        if state:
            state.last_seen = now
            if state.last_command == normalized:
                return False

        return True

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        command = self._extract_pytest_command(context)
        if not command:
            return ToolCallReactionResult(should_swallow=False)

        normalized = _normalize_whitespace(command)
        if not _looks_like_full_suite(normalized):
            return ToolCallReactionResult(should_swallow=False)

        now = self._monotonic()
        self._prune_session_state(now)

        state = self._session_state.setdefault(
            context.session_id, _SessionState(last_seen=now)
        )
        state.last_seen = now
        if state.last_command == normalized:
            return ToolCallReactionResult(should_swallow=False)

        state.last_command = normalized
        # Ensure memory guardrails are enforced after recording the new command
        self._prune_session_state(now)

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

    def _prune_session_state(self, now: float) -> None:
        expired: list[str] = []
        for session_id, state in self._session_state.items():
            if now - state.last_seen > self._state_ttl_seconds:
                expired.append(session_id)

        for session_id in expired:
            del self._session_state[session_id]

        if len(self._session_state) <= self._max_sessions:
            return

        # Remove oldest sessions to cap memory usage
        sorted_sessions = sorted(
            self._session_state.items(), key=lambda item: item[1].last_seen
        )
        remove_count = len(self._session_state) - self._max_sessions
        for session_id, _ in sorted_sessions[:remove_count]:
            del self._session_state[session_id]

    def _extract_pytest_command(self, context: ToolCallContext) -> str | None:
        tool_name_raw = context.tool_name or ""
        tool_name = tool_name_raw.strip()
        normalized_tool_name = tool_name.lower()
        arguments = context.tool_arguments

        # Tools that are recognized as shell/command execution tools
        # These should only trigger if they execute commands on the user's host
        shell_tools = {
            "bash",
            "cmd",
            "exec",
            "exec_command",
            "execute",
            "execute_command",
            "local_shell",
            "python",
            "run_command",
            "run_shell_command",
            "run_terminal_cmd",
            "shell",
            "terminal",
            "container.exec",
        }

        command = _extract_command(arguments)

        # Only trigger for recognized shell execution tools
        if normalized_tool_name in shell_tools:
            return command

        # Some providers map pytest directly as function name (e.g., "pytest" tool)
        if _PYTEST_ROOT_PATTERN.search(tool_name):
            if command:
                return f"{tool_name} {command}"
            return tool_name

        # Do NOT trigger for arbitrary tools even if command contains pytest
        # This was causing false positives for non-shell tools
        return None
