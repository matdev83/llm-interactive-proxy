"""Pytest full-suite execution steering policy."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.interfaces.tool_call_reactor_interface import ToolCallContext

from ..interfaces import ISteeringPolicy
from ..models import SteeringResult
from ..session_state_store import SessionStateStore

logger = logging.getLogger(__name__)


DEFAULT_STEERING_MESSAGE = (
    "You requested to run the whole test suite. This may be a lengthy process. "
    "Please consider running only selected tests for optimal speed. If you still "
    "believe you need to run the whole test suite, please re-send your tool call "
    "and it will be executed."
)

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

_SHELL_TOOLS = {
    "bash",
    "cmd",
    "exec",
    "exec_command",
    "execute",
    "execute_command",
    "executepwsh",
    "execute_pwsh",
    "local_shell",
    "powershell",
    "pwsh",
    "python",
    "run_command",
    "run_shell_command",
    "run_terminal_cmd",
    "shell",
    "terminal",
    "container.exec",
}


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
    """Determine if the pytest command targets the entire suite."""
    if not _PYTEST_ROOT_PATTERN.search(command):
        return False

    tokens = _split_command_tokens(command)
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

            if flag_name in _FILTERING_FLAGS:
                return False

            if flag_name in _FLAGS_REQUIRING_VALUE and not token.endswith("="):
                skip_next_value = True
            continue

        stripped = token.strip(",")

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

        candidate_path = Path(candidate)
        if candidate_path.is_dir():
            return False

        if "." in candidate and not candidate.endswith(file_like_extensions):
            return False

        if re.fullmatch(r"[A-Za-z0-9_]+", candidate):
            return False

    return True


class PytestFullSuitePolicy(ISteeringPolicy):
    """Policy that warns about full pytest suite execution.

    Uses SessionStateStore to track if the same command was already warned about,
    allowing re-execution on second attempt.
    """

    def __init__(
        self,
        session_store: SessionStateStore,
        message: str | None = None,
        enabled: bool = True,
        prompt_override_path: Path | None = None,
    ) -> None:
        """Initialize the policy.

        Args:
            session_store: Shared session state store for TTL/reminder tracking
            message: Custom steering message
            enabled: Whether the policy is enabled
            prompt_override_path: Path to a file to override the default message
        """
        self._session_store = session_store
        self._enabled = enabled

        final_message = message or DEFAULT_STEERING_MESSAGE
        if prompt_override_path and prompt_override_path.is_file():
            try:
                final_message = prompt_override_path.read_text(encoding="utf-8")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Loaded pytest full suite steering prompt from %s",
                        prompt_override_path,
                    )
            except Exception:
                logger.warning(
                    "Failed to read pytest full suite steering prompt from %s, using default.",
                    prompt_override_path,
                    exc_info=True,
                )
        self._message = final_message

    @property
    def name(self) -> str:
        return "pytest_full_suite"

    @property
    def priority(self) -> int:
        # High priority to catch before general execution
        return 95

    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate if command is a full pytest suite run."""
        if not self._enabled:
            return None

        tool_name = (context.tool_name or "").strip().lower()

        # Only trigger for shell execution tools or pytest tools
        if tool_name not in _SHELL_TOOLS and not _PYTEST_ROOT_PATTERN.search(tool_name):
            return None

        if not command:
            return None

        # Check if command looks like full suite
        if not _looks_like_full_suite(command):
            return None

        # Check session state: allow if already warned about this exact command
        last_command = await self._session_store.get(
            context.session_id, "pytest_last_command"
        )

        if last_command == command:
            # Already warned - allow pass through
            return None

        if not dry_run:
            # Record this command for next time
            await self._session_store.set(
                context.session_id, "pytest_last_command", command
            )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Steering full-suite pytest command in session %s: %s",
                context.session_id,
                command,
            )

        return SteeringResult(
            message=self._message,
            should_block=True,
            policy_name=self.name,
            severity="warning",
            metadata={
                "tool_name": context.tool_name,
                "command": command,
                "source": "pytest_full_suite_steering",
            },
        )


__all__ = ["PytestFullSuitePolicy"]
