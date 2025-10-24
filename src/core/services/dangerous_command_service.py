import json
import re
from typing import Any

from src.core.domain.chat import ToolCall
from src.core.domain.configuration.dangerous_command_config import (
    DangerousCommandConfig,
    DangerousCommandRule,
)


class DangerousCommandService:
    def __init__(self, config: DangerousCommandConfig):
        self.config = config

    def scan_tool_call(
        self, tool_call: ToolCall
    ) -> tuple[DangerousCommandRule, str] | None:
        """
        Scans a tool call for dangerous commands.

        Args:
            tool_call: The tool call to scan.

        Returns:
            A tuple containing the matched rule and the command string if a dangerous
            command is found, otherwise None.
        """
        return self.scan(tool_call.function.name, tool_call.function.arguments)

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
                except Exception:
                    return None
            return None

        # If list, join
        if isinstance(arguments, list):
            try:
                return " ".join(str(a) for a in arguments)
            except Exception:
                return None
        return None

    def _generate_command_candidates(self, command: str) -> list[str]:
        """Produce normalized variants to improve pattern detection."""
        candidates: set[str] = set()
        collapsed = re.sub(r"\s+", " ", command).strip()
        candidates.add(command)
        candidates.add(collapsed)

        substitution_normalized = re.sub(
            r"\$\((?:which|command\s+-v)\s+git\)",
            "git",
            collapsed,
            flags=re.IGNORECASE,
        )
        candidates.add(substitution_normalized.strip())

        env_stripped = re.sub(
            r"\b[A-Z_][A-Z0-9_]*=.*?(?=\s+git\b)",
            "",
            substitution_normalized,
            flags=re.IGNORECASE,
        )
        env_stripped = re.sub(r"\s+", " ", env_stripped).strip()
        candidates.add(env_stripped)

        tokens = env_stripped.split()
        if tokens:
            normalized_tokens: list[str] = []
            for token in tokens:
                cleaned = token
                if "git" in token.lower():
                    cleaned = re.split(r"[\\/]", token)[-1]
                normalized_tokens.append(cleaned)
            candidates.add(" ".join(normalized_tokens).strip())

        return [candidate for candidate in candidates if candidate]

    def scan(
        self, tool_name: str, arguments: Any
    ) -> tuple[DangerousCommandRule, str] | None:
        """Scan tool_name and arguments for dangerous command.

        Returns matched rule and reconstructed command string, or None.
        """
        if tool_name not in self.config.tool_names:
            return None

        command_to_check = self._extract_command_string(arguments)
        if not command_to_check:
            return None

        candidates = self._generate_command_candidates(command_to_check)

        for rule in self.config.rules:
            for candidate in candidates:
                if rule.pattern.search(candidate):
                    return rule, command_to_check
        return None
