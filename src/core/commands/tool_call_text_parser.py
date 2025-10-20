from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "TextToolInvocation",
    "TextToolResult",
    "parse_textual_tool_invocation",
    "parse_textual_tool_result",
]

_TOOL_NAME_ALIASES: dict[str, str] = {
    "execute_command": "shell",
    "run_command": "shell",
    "apply_diff": "apply_patch",
    "apply_patch": "apply_patch",
    "view_image": "view_image",
}


@dataclass(frozen=True)
class TextToolInvocation:
    """Structured representation of a tool invocation embedded in plain text."""

    canonical_name: str
    arguments: Mapping[str, Any]
    raw_text: str
    command_text: str | None = None


@dataclass(frozen=True)
class TextToolResult:
    """Structured representation of a tool result embedded in plain text."""

    canonical_name: str
    output_text: str
    raw_text: str
    command_text: str | None = None
    exit_code: int | None = None
    working_directory: str | None = None


def parse_textual_tool_invocation(text: str) -> TextToolInvocation | None:
    """Parse a textual tool invocation (e.g., Cline XML envelope)."""
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("<execute_command"):
        return _parse_execute_command_invocation(stripped)
    if stripped.startswith("<apply_diff"):
        return _parse_apply_diff_invocation(stripped)
    if stripped.startswith("<view_image"):
        return _parse_view_image_invocation(stripped)
    return None


def parse_textual_tool_result(text: str) -> TextToolResult | None:
    """Parse a textual tool result of the form `[tool] Result: ...`."""
    stripped = text.strip()
    if not stripped or not stripped.startswith("[") or " Result" not in stripped:
        return None

    match = re.match(
        r"\[(?P<label>[^\]]+)\]\s*Result:\s*(?P<body>.*)",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None

    label = match.group("label").strip()
    body = match.group("body")
    tool_token = label.split()[0].strip().lower()
    canonical_name = _TOOL_NAME_ALIASES.get(tool_token)
    if not canonical_name:
        return None

    command_text = None
    if " for " in label:
        command_text = label.split(" for ", 1)[1].strip().strip("'\" ")

    exit_code: int | None = None
    exit_match = re.search(r"Exit code:\s*(-?\d+)", body)
    if exit_match:
        try:
            exit_code = int(exit_match.group(1))
        except ValueError:
            exit_code = None

    cwd: str | None = None
    cwd_match = re.search(
        r"working directory ['\"]([^'\"]+)['\"]", body, flags=re.IGNORECASE
    )
    if cwd_match:
        cwd = cwd_match.group(1)

    output_section = body
    output_label_match = re.search(r"\n(?:Output|Error|Stdout|Stderr):", body)
    if output_label_match:
        output_section = body[output_label_match.end() :]
    output_text = output_section.strip()

    return TextToolResult(
        canonical_name=canonical_name,
        output_text=output_text,
        raw_text=stripped,
        command_text=command_text,
        exit_code=exit_code,
        working_directory=cwd,
    )


def _parse_execute_command_invocation(text: str) -> TextToolInvocation | None:
    command_match = re.search(r"<command>(.*?)</command>", text, flags=re.DOTALL)
    if not command_match:
        return None

    command_text = command_match.group(1).strip()
    cwd_match = re.search(r"<cwd>(.*?)</cwd>", text, flags=re.DOTALL)
    cwd = cwd_match.group(1).strip() if cwd_match else None

    try:
        command_parts = shlex.split(command_text)
    except Exception:
        command_parts = [command_text]

    arguments: dict[str, Any] = {"command": command_parts}
    if cwd:
        arguments["workdir"] = cwd

    return TextToolInvocation(
        canonical_name="shell",
        arguments=arguments,
        raw_text=text,
        command_text=command_text,
    )


def _parse_apply_diff_invocation(text: str) -> TextToolInvocation | None:
    diff_match = re.search(r"<diff>(.*?)</diff>", text, flags=re.DOTALL)
    if not diff_match:
        return None

    patch_text = diff_match.group(1).strip()
    path_match = re.search(r"<path>(.*?)</path>", text, flags=re.DOTALL)
    path_value = path_match.group(1).strip() if path_match else None

    arguments: dict[str, Any] = {"patch": patch_text}
    if path_value:
        arguments["path"] = path_value

    return TextToolInvocation(
        canonical_name="apply_patch",
        arguments=arguments,
        raw_text=text,
        command_text=None,
    )


def _parse_view_image_invocation(text: str) -> TextToolInvocation | None:
    path_match = re.search(r"<path>(.*?)</path>", text, flags=re.DOTALL)
    if not path_match:
        return None

    path_value = path_match.group(1).strip()
    return TextToolInvocation(
        canonical_name="view_image",
        arguments={"path": path_value},
        raw_text=text,
        command_text=None,
    )
