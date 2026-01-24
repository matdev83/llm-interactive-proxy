import json
import logging
import re
from typing import Any

from pydantic import BaseModel

from src.core.domain.chat import ToolCall
from src.core.domain.configuration.dangerous_command_config import (
    _COMBINED_DANGEROUS_PATTERN,
    DangerousCommandConfig,
    DangerousCommandRule,
)

_SUBSHELL_GIT_PATTERN = re.compile(r"\$\((?:which|command\s+-v)\s+git\)", re.IGNORECASE)
_ENV_PREFIX_PATTERN = re.compile(r"\b[A-Z_][A-Z0-9_]*=.*?(?=\s+git\b)", re.IGNORECASE)

logger = logging.getLogger(__name__)


class DangerousCommandMatch(BaseModel):
    """Represents a matched dangerous command rule."""

    rule: DangerousCommandRule
    command: str


class DangerousCommandService:

    def __init__(self, config: DangerousCommandConfig, command_service=None):
        self.config = config
        # Normalize tool names once so lookups remain case-insensitive while
        # preserving the original configuration for external access.
        self._normalized_tool_names: set[str] = {
            tool_name.lower() for tool_name in self.config.tool_names
        }
        # Optional command extraction service for safe dev tool checks
        self._command_service = command_service

    def scan_tool_call(self, tool_call: ToolCall) -> DangerousCommandMatch | None:
        """
        Scans a tool call for dangerous commands.

        Args:
            tool_call: The tool call to scan.

        Returns:
            A DangerousCommandMatch object if a dangerous command is found, otherwise None.
        """
        tool_name = tool_call.function.name
        if not tool_name:
            return None
        return self.scan(tool_name, tool_call.function.arguments)

    def _extract_command_string(self, arguments: Any) -> str | None:
        """Extract a shell command string from tool arguments.

        Supports:
        - Raw string
        - JSON string -> dict extraction
        - Dict with common keys: 'command', 'cmd'
        - Dict 'args' list joined to string
        """
        if arguments is None:
            return None
        # If it's already a string, see if it's JSON first
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                arguments = parsed
            except json.JSONDecodeError:
                # Plain string
                s: str = arguments
                return s

        # If dict, try common fields
        if isinstance(arguments, dict):
            cmd = arguments.get("command") or arguments.get("cmd")
            if isinstance(cmd, str) and cmd.strip():
                return cmd
            # Sometimes a sub-dict holds the command
            for key in ("input", "body", "data"):
                inner = arguments.get(key)
                if isinstance(inner, dict):
                    sub = inner.get("command") or inner.get("cmd")
                    if isinstance(sub, str) and sub.strip():
                        return sub
            # If args array provided, join into a single string
            args = arguments.get("args")
            if isinstance(args, list) and args:
                try:
                    return " ".join(str(a) for a in args)
                except (TypeError, ValueError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to convert args array to command string: %s",
                            e,
                            exc_info=True,
                        )
                    return None
            return None

        # If list, join
        if isinstance(arguments, list):
            try:
                return " ".join(str(a) for a in arguments)
            except (TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert arguments list to command string: %s",
                        e,
                        exc_info=True,
                    )
                return None
        return None

    def _normalize_for_detection(self, command: str) -> str:
        collapsed = re.sub(r"\s+", " ", command).strip()
        # Treat escaped newlines/backslash spacers as regular whitespace so
        # commands like "git \ checkout -- ." normalize correctly.
        collapsed = re.sub(r"\\\s*", " ", collapsed)
        without_subshell = _SUBSHELL_GIT_PATTERN.sub("git", collapsed)
        without_env = _ENV_PREFIX_PATTERN.sub("", without_subshell)
        return re.sub(r"\s+", " ", without_env).strip()

    def _generate_command_candidates(self, command: str) -> list[str]:
        """Produce normalized variants to improve pattern detection."""
        # For large commands, skip expensive normalization. A fast pre-check should
        # have already been performed. This step is for finding the specific rule.
        if len(command) > 10000:
            return [command, command[:2000]]

        candidates: set[str] = set()
        collapsed = re.sub(r"\s+", " ", command).strip()
        candidates.add(command)
        candidates.add(collapsed)

        substitution_normalized = _SUBSHELL_GIT_PATTERN.sub("git", collapsed)
        candidates.add(substitution_normalized.strip())

        env_stripped = _ENV_PREFIX_PATTERN.sub("", substitution_normalized)
        env_stripped = re.sub(r"\s+", " ", env_stripped).strip()
        candidates.add(env_stripped)

        # Optimize token processing for large strings
        if (
            len(env_stripped) < 10000
        ):  # Only do detailed tokenization for smaller strings
            tokens = env_stripped.split()
            if tokens:
                normalized_tokens: list[str] = []
                for token in tokens:
                    cleaned = token
                    if "git" in token.lower():
                        cleaned = re.split(r"[\\/]", token)[-1]
                    normalized_tokens.append(cleaned)
                candidates.add(" ".join(normalized_tokens).strip())

                # Handle git invocations with leading options before the subcommand
                # (e.g., "git --work-tree=. checkout -- .") by stripping those
                # options to surface the risky subcommand.
                stripped = self._strip_git_leading_options(env_stripped)
                if stripped != env_stripped:
                    candidates.add(stripped)

        return [candidate for candidate in candidates if candidate]

    @staticmethod
    def _strip_git_leading_options(command: str) -> str:
        """Remove leading git options to expose the subcommand for detection."""
        tokens = command.split()
        if not tokens or tokens[0].lower() != "git":
            return command

        idx = 1
        while idx < len(tokens) and tokens[idx].startswith("-"):
            idx += 1

        if idx == 1 or idx >= len(tokens):
            return command

        return " ".join(["git"] + tokens[idx:]).strip()

    def scan(self, tool_name: str, arguments: Any) -> DangerousCommandMatch | None:
        """Scan tool_name and arguments for dangerous command.

        Returns DangerousCommandMatch object, or None.
        """
        normalized_tool_name = tool_name.lower() if isinstance(tool_name, str) else ""
        if normalized_tool_name not in self._normalized_tool_names:
            return None

        command_to_check = self._extract_command_string(arguments)
        if not command_to_check:
            return None

        # Exempt safe developer tools (linters, formatters, type checkers)
        if (
            self._command_service
            and hasattr(self._command_service, "is_safe_dev_tool_command")
            and self._command_service.is_safe_dev_tool_command(command_to_check)
        ):
            # Safe dev tool - no need to log at warning level
            return None

        original_command = command_to_check
        # Truncate for performance before any processing
        if len(command_to_check) > self.config.max_command_length:
            command_to_check = command_to_check[: self.config.max_command_length]

        # Fast pre-check on the (potentially truncated) command
        normalized_for_detection = self._normalize_for_detection(command_to_check)

        combined_match = _COMBINED_DANGEROUS_PATTERN.search(normalized_for_detection)
        if not combined_match:
            # Try again after stripping leading git options to catch forms like
            # "git --work-tree=. checkout -- ."
            stripped = self._strip_git_leading_options(normalized_for_detection)
            if stripped == normalized_for_detection:
                return None
            if not _COMBINED_DANGEROUS_PATTERN.search(stripped):
                return None

        # If there's a potential match, generate candidates to find the specific rule
        candidates = self._generate_command_candidates(normalized_for_detection)
        if command_to_check not in candidates:
            candidates.append(command_to_check)

        for rule in self.config.rules:
            for candidate in candidates:
                if rule.pattern.search(candidate):
                    return DangerousCommandMatch(rule=rule, command=original_command)
        return None

    def might_be_dangerous(self, tool_name: str, arguments: Any) -> bool:
        """Fast pre-check for whether arguments contain a dangerous command.

        This method is optimized for low overhead (used by can_handle) and avoids
        iterating all rules. It relies on the combined pattern to indicate that
        at least one rule *could* match.
        """
        normalized_tool_name = tool_name.lower() if isinstance(tool_name, str) else ""
        if normalized_tool_name not in self._normalized_tool_names:
            return False

        command_to_check = self._extract_command_string(arguments)
        if not command_to_check:
            return False

        if (
            self._command_service
            and hasattr(self._command_service, "is_safe_dev_tool_command")
            and self._command_service.is_safe_dev_tool_command(command_to_check)
        ):
            return False

        if len(command_to_check) > self.config.max_command_length:
            command_to_check = command_to_check[: self.config.max_command_length]

        normalized_for_detection = self._normalize_for_detection(command_to_check)
        if _COMBINED_DANGEROUS_PATTERN.search(normalized_for_detection):
            return True

        stripped = self._strip_git_leading_options(normalized_for_detection)
        return stripped != normalized_for_detection and bool(
            _COMBINED_DANGEROUS_PATTERN.search(stripped)
        )
