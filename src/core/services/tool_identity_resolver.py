"""Resolve deterministic tool identity and output metadata."""

from __future__ import annotations

import io
import json
import re
import shlex
import xml.etree.ElementTree
from collections.abc import Mapping, Sequence
from typing import Any

from src.core.domain.chat import ChatMessage
from src.core.domain.compaction import categorize_tool
from src.core.domain.dynamic_compression import (
    ToolIdentity,
    ToolOutputContentType,
    ToolOutputContext,
)

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_LINE_NUMBER_RE = re.compile(r"^\s*\d+[:|]")
_DIFF_MARKER_RE = re.compile(r"^(diff --git|@@ |\+\+\+ |--- )")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SAFE_PREFIX_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PYTEST_COMMAND_RE = re.compile(r"\bpy\.?test\b", re.IGNORECASE)
_NDJSON_MAX_SCAN_LINES = 200
_NDJSON_MAX_SCAN_BYTES = 256 * 1024


class ToolIdentityResolver:
    """Stateless resolver for tool identity and observable metadata."""

    _default_explicit_flags: tuple[str, ...] = (
        "--json",
        "--format",
        "--stat",
        "--numstat",
        "--shortstat",
        "--output-format",
    )
    _two_segment_subcommand_signatures = frozenset({"uv"})
    _cmd_safe_switches = frozenset({"/c", "/k", "/s"})
    _option_tokens_with_value = frozenset(
        {
            "-C",
            "-c",
            "-f",
            "-m",
            "-p",
            "--config",
            "--cwd",
            "--file",
            "--git-dir",
            "--prefix",
            "--project",
            "--work-tree",
        }
    )
    _legacy_shell_tool_names = frozenset(
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
    _pytest_wrapper_executables = frozenset(
        {"uv", "uv.exe", "poetry", "poetry.exe", "pipenv", "pipenv.exe"}
    )
    _uv_run_options_with_value = frozenset(
        {
            "-m",
            "--module",
            "--python",
            "--with",
            "--with-editable",
            "--extra",
            "--group",
            "--no-group",
            "--index",
            "--default-index",
        }
    )

    def build_tool_call_lookup(
        self,
        messages: Sequence[ChatMessage],
    ) -> dict[str, tuple[str, str | dict[str, Any] | None]]:
        lookup: dict[str, tuple[str, str | dict[str, Any] | None]] = {}
        for message in messages:
            if message.role != "assistant" or not message.tool_calls:
                continue
            for tool_call in message.tool_calls:
                if not tool_call.id:
                    continue
                tool_name = tool_call.function.name or "unknown"
                lookup[tool_call.id] = (tool_name, tool_call.function.arguments)
        return lookup

    def resolve_tool_output(
        self,
        *,
        messages: Sequence[ChatMessage],
        tool_message: ChatMessage,
        explicit_format_flags: Sequence[str] | None = None,
        tool_lookup: (
            Mapping[str, tuple[str, str | dict[str, Any] | None]] | None
        ) = None,
    ) -> ToolOutputContext | None:
        if tool_message.role != "tool":
            return None

        if not isinstance(tool_message.content, str):
            return None
        content = tool_message.content

        lookup = (
            tool_lookup
            if tool_lookup is not None
            else self.build_tool_call_lookup(messages)
        )
        tool_name, tool_args = self._resolve_tool_name_and_args(tool_message, lookup)
        command = self._extract_command_string(tool_args)
        signature, prefix = self._extract_command_identity(command)
        if self.scan_for_pytest(tool_name=tool_name, arguments=tool_args) is not None:
            signature = "pytest"
            prefix = "pytest"

        explicit_flags = tuple(
            flag.strip().lower()
            for flag in (explicit_format_flags or self._default_explicit_flags)
            if flag.strip()
        )
        matched_flags = self._extract_explicit_format_flags(command, explicit_flags)
        category = str(categorize_tool(tool_name).value)

        content_type = self._detect_content_type(content)
        is_structured = content_type in {
            ToolOutputContentType.JSON,
            ToolOutputContentType.NDJSON,
            ToolOutputContentType.XML,
        }

        line_count = content.count("\n") + 1 if content else 0
        has_line_numbers = False
        has_diff_markers = False
        for line_index, line in enumerate(io.StringIO(content), start=1):
            if line_index <= 100 and not has_line_numbers:
                has_line_numbers = bool(_LINE_NUMBER_RE.match(line))
            if line_index <= 200 and not has_diff_markers:
                has_diff_markers = bool(_DIFF_MARKER_RE.match(line))
            if line_index >= 200 and has_line_numbers and has_diff_markers:
                break

        return ToolOutputContext(
            identity=ToolIdentity(
                tool_name=tool_name,
                tool_category=category,
                command_signature=signature,
                command_prefix=prefix,
                explicit_format_flags=matched_flags,
            ),
            content=content,
            content_type=content_type,
            byte_size=len(content.encode("utf-8")),
            line_count=line_count,
            has_line_numbers=has_line_numbers,
            has_ansi=bool(_ANSI_RE.search(content)),
            has_diff_markers=has_diff_markers,
            has_explicit_format=bool(matched_flags),
            structured_format=(content_type.value if is_structured else None),
            is_machine_parseable=is_structured,
        )

    def scan_for_pytest(
        self,
        *,
        tool_name: str,
        arguments: str | dict[str, Any] | None,
    ) -> str | None:
        """Legacy-compatible pytest detection (tool allowlist + command regex)."""
        if tool_name.lower() not in self._legacy_shell_tool_names:
            return None
        command = self._extract_command_string(arguments)
        if not command:
            return None
        if self._is_pytest_invocation_tokens(self._safe_split(command)):
            return command
        return None

    def _is_pytest_invocation_tokens(
        self,
        tokens: list[str],
        *,
        max_wrapper_depth: int = 3,
    ) -> bool:
        normalized_tokens = self._strip_env_prefix(tokens)
        if not normalized_tokens:
            return False

        executable = self._normalize_executable(normalized_tokens[0]).lower()
        remainder = normalized_tokens[1:]
        if executable in {"pytest", "py.test", "pytest.exe", "py.test.exe"}:
            return True
        if executable in {
            "python",
            "python.exe",
            "python3",
            "python3.exe",
            "py",
            "py.exe",
        }:
            lowered_tokens = [token.lower() for token in remainder]
            for idx, token in enumerate(lowered_tokens):
                if token != "-m":
                    continue
                if idx + 1 < len(lowered_tokens) and _PYTEST_COMMAND_RE.fullmatch(
                    lowered_tokens[idx + 1]
                ):
                    return True
            return False
        if executable in self._pytest_wrapper_executables and max_wrapper_depth > 0:
            wrapped = self._unwrap_pytest_wrapper_tokens(
                executable=executable,
                tokens=remainder,
            )
            if not wrapped:
                return False
            return self._is_pytest_invocation_tokens(
                wrapped,
                max_wrapper_depth=max_wrapper_depth - 1,
            )
        return bool(_PYTEST_COMMAND_RE.fullmatch(executable))

    def _unwrap_pytest_wrapper_tokens(
        self,
        *,
        executable: str,
        tokens: list[str],
    ) -> list[str]:
        if not tokens:
            return []

        idx = 0
        while idx < len(tokens):
            token = tokens[idx].strip()
            lowered = token.lower()
            if not token:
                idx += 1
                continue
            if lowered == "run":
                idx += 1
                break
            if token.startswith("-"):
                if "=" in token:
                    idx += 1
                    continue
                if lowered in self._option_tokens_with_value and idx + 1 < len(tokens):
                    idx += 2
                    continue
                idx += 1
                continue
            return []
        else:
            return []

        wrapped = tokens[idx:]
        if wrapped and wrapped[0] == "--":
            wrapped = wrapped[1:]
        if executable in {"uv", "uv.exe"}:
            wrapped = self._strip_uv_run_options(wrapped)
        return wrapped

    def _strip_uv_run_options(self, tokens: list[str]) -> list[str]:
        if not tokens:
            return []

        idx = 0
        module_target: str | None = None
        while idx < len(tokens):
            token = tokens[idx].strip()
            lowered = token.lower()
            if not token:
                idx += 1
                continue
            if lowered == "--":
                idx += 1
                break
            if lowered in {"-m", "--module"}:
                if idx + 1 >= len(tokens):
                    return []
                module_target = tokens[idx + 1]
                idx += 2
                continue
            if token.startswith("-"):
                if "=" in token:
                    idx += 1
                    continue
                if lowered in self._uv_run_options_with_value and idx + 1 < len(tokens):
                    idx += 2
                    continue
                idx += 1
                continue
            break

        remaining = [entry for entry in tokens[idx:] if entry.strip()]
        if module_target is not None:
            return ["python", "-m", module_target, *remaining]
        return remaining

    def _resolve_tool_name_and_args(
        self,
        message: ChatMessage,
        tool_lookup: Mapping[str, tuple[str, str | dict[str, Any] | None]],
    ) -> tuple[str, str | dict[str, Any] | None]:
        if message.tool_call_id and message.tool_call_id in tool_lookup:
            return tool_lookup[message.tool_call_id]

        metadata = message.metadata or {}
        if isinstance(metadata, dict):
            tool_name = metadata.get("tool_name")
            if isinstance(tool_name, str) and tool_name.strip():
                tool_args = metadata.get("tool_args")
                if isinstance(tool_args, str | dict):
                    return tool_name, tool_args
                return tool_name, None

        return "unknown", None

    def _extract_command_string(
        self, arguments: str | dict[str, Any] | None
    ) -> str | None:
        if arguments is None:
            return None

        parsed: Any = arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except (TypeError, ValueError):
                return arguments

        if isinstance(parsed, dict):
            direct = parsed.get("command") or parsed.get("cmd")
            if isinstance(direct, str) and direct.strip():
                return direct
            args_list = parsed.get("args")
            if isinstance(args_list, list):
                return " ".join(str(item) for item in args_list)
            for nested_key in ("input", "body", "data"):
                nested = parsed.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested
                if isinstance(nested, dict):
                    nested_cmd = nested.get("command") or nested.get("cmd")
                    if isinstance(nested_cmd, str) and nested_cmd.strip():
                        return nested_cmd

        if isinstance(parsed, list):
            return " ".join(str(item) for item in parsed)

        return None

    def _extract_command_identity(
        self, command: str | None
    ) -> tuple[str | None, str | None]:
        if not command:
            return None, None

        tokens = self._safe_split(command)
        if not tokens:
            return None, None

        normalized_tokens = self._strip_env_prefix(tokens)
        if not normalized_tokens:
            return None, None

        executable = self._normalize_executable(normalized_tokens[0])
        signature = executable.lower()
        rest = normalized_tokens[1:]

        if signature == "git":
            rest = self._strip_git_global_options(rest)

        prefix_tokens = self._extract_prefix_tokens(signature=signature, tokens=rest)
        prefix = " ".join([signature, *prefix_tokens]) if prefix_tokens else signature
        return signature, prefix

    def _extract_prefix_tokens(self, *, signature: str, tokens: list[str]) -> list[str]:
        if not tokens:
            return []

        first = tokens[0].strip().lower()
        if signature == "cmd" and first in self._cmd_safe_switches:
            return [first]

        max_tokens = 2 if signature in self._two_segment_subcommand_signatures else 1
        collected: list[str] = []
        idx = 0
        while idx < len(tokens) and len(collected) < max_tokens:
            token = tokens[idx].strip()
            if not token:
                idx += 1
                continue
            if token.startswith("-"):
                if "=" in token:
                    idx += 1
                    continue
                if token in self._option_tokens_with_value and idx + 1 < len(tokens):
                    idx += 2
                    continue
                idx += 1
                continue
            if not self._is_safe_prefix_token(token):
                break
            collected.append(token.lower())
            idx += 1
        return collected

    @staticmethod
    def _is_safe_prefix_token(token: str) -> bool:
        lowered = token.lower()
        if lowered.startswith(("http://", "https://", "file://", "ssh://", "git@")):
            return False
        if any(
            marker in token for marker in ("/", "\\", ":", "=", "@", "?", "&", "%", "#")
        ):
            return False
        return bool(_SAFE_PREFIX_TOKEN_RE.fullmatch(token))

    def _extract_explicit_format_flags(
        self,
        command: str | None,
        explicit_flags: Sequence[str],
    ) -> list[str]:
        if not command:
            return []
        command_tokens = [token.lower() for token in self._safe_split(command)]
        found: list[str] = []
        for flag in explicit_flags:
            for token in command_tokens:
                if token == flag or token.startswith(f"{flag}="):
                    found.append(flag)
                    break
        return found

    def _safe_split(self, command: str) -> list[str]:
        if not command.strip():
            return []
        for posix_mode in (True, False):
            try:
                return shlex.split(command, posix=posix_mode)
            except ValueError:
                continue
        return command.split()

    def _strip_env_prefix(self, tokens: list[str]) -> list[str]:
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            if token == "sudo":
                idx += 1
                continue
            if token == "env":
                idx += 1
                continue
            if _ENV_ASSIGNMENT_RE.match(token):
                idx += 1
                continue
            break
        return tokens[idx:]

    @staticmethod
    def _normalize_executable(token: str) -> str:
        normalized = token.replace("\\", "/")
        if "/" in normalized:
            normalized = normalized.rsplit("/", maxsplit=1)[-1]
        return normalized

    @staticmethod
    def _strip_git_global_options(tokens: list[str]) -> list[str]:
        result = list(tokens)
        idx = 0
        while idx < len(result):
            token = result[idx]
            if token in {"--no-pager", "--no-optional-locks", "--bare"}:
                idx += 1
                continue
            if token in {"-C", "-c", "--git-dir", "--work-tree"}:
                idx += 2
                continue
            if token.startswith(("--git-dir=", "--work-tree=")):
                idx += 1
                continue
            break
        return result[idx:]

    def _detect_content_type(self, content: str) -> ToolOutputContentType:
        stripped = content.strip()
        if not stripped:
            return ToolOutputContentType.TEXT

        if stripped.startswith(("{", "[")):
            try:
                json.loads(stripped)
                return ToolOutputContentType.JSON
            except (TypeError, ValueError):
                pass

        if self._is_bounded_ndjson(stripped):
            return ToolOutputContentType.NDJSON

        if stripped.startswith("<"):
            try:
                xml.etree.ElementTree.fromstring(stripped)
                return ToolOutputContentType.XML
            except xml.etree.ElementTree.ParseError:
                pass

        return ToolOutputContentType.TEXT

    def _is_bounded_ndjson(self, content: str) -> bool:
        if len(content) > _NDJSON_MAX_SCAN_BYTES:
            return False

        non_empty_lines = 0
        for raw_line in io.StringIO(content):
            stripped_line = raw_line.strip()
            if not stripped_line:
                continue
            non_empty_lines += 1
            if non_empty_lines > _NDJSON_MAX_SCAN_LINES:
                return False
            try:
                json.loads(stripped_line)
            except (TypeError, ValueError):
                return False
        return non_empty_lines > 1
