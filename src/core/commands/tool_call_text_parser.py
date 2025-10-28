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
    # Legacy Cline/Codex mappings
    "execute_command": "shell",
    "run_command": "shell",
    "apply_diff": "apply_patch",
    "apply_patch": "apply_patch",
    "view_image": "view_image",
    # Dynamic tool mappings - these preserve the original tool name
    # allowing the universal executor to handle them appropriately
    "read_file": "read_file",
    "list_files": "list_files",
    "list_dir": "list_dir",
    "codebase_search": "codebase_search",
    "search_files": "search_files",
    "grep_files": "grep_files",
    "use_mcp_tool": "use_mcp_tool",
    "attempt_completion": "attempt_completion",
    "ask_followup_question": "ask_followup_question",
    "completion_marker": "completion_marker",
    "followup_marker": "followup_marker",
}

# Pre-compiled regex patterns for performance optimization
_TOOL_RESULT_PATTERN = re.compile(
    r"\[(?P<label>[^\]]+)\]\s*Result:\s*(?P<body>.*)", re.DOTALL | re.IGNORECASE
)
_EXIT_CODE_PATTERN = re.compile(r"Exit code:\s*(-?\d+)")
_CWD_PATTERN = re.compile(r"working directory ['\"]([^'\"]+)['\"]", re.IGNORECASE)
_OUTPUT_LABEL_PATTERN = re.compile(r"\n(?:Output|Error|Stdout|Stderr):")
_COMMAND_PATTERN = re.compile(r"<command>(.*?)</command>", re.DOTALL)
_CWD_PATTERN_XML = re.compile(r"<cwd>(.*?)</cwd>", re.DOTALL)
_DIFF_PATTERN = re.compile(r"<diff>(.*?)</diff>", re.DOTALL)
_PATH_PATTERN = re.compile(r"<path>(.*?)</path>", re.DOTALL)

# KiloCode XML patterns
_READ_FILE_PATTERN = re.compile(r"<read_file[^>]*>(.*?)</read_file>", re.DOTALL)
_LIST_FILES_PATTERN = re.compile(r"<list_files[^>]*>(.*?)</list_files>", re.DOTALL)
_SEARCH_FILES_PATTERN = re.compile(
    r"<(?:codebase_search|search_files)[^>]*>(.*?)</(?:codebase_search|search_files)>",
    re.DOTALL,
)
_USE_MCP_TOOL_PATTERN = re.compile(
    r"<use_mcp_tool[^>]*>(.*?)</use_mcp_tool>", re.DOTALL
)
_ATTEMPT_COMPLETION_PATTERN = re.compile(
    r"<attempt_completion[^>]*>(.*?)</attempt_completion>", re.DOTALL
)
_ASK_FOLLOWUP_PATTERN = re.compile(
    r"<ask_followup_question[^>]*>(.*?)</ask_followup_question>", re.DOTALL
)

# Generic XML attribute patterns
_FILE_PATH_ATTR_PATTERN = re.compile(r'(?:file_path|path)="([^"]*)"')
_RECURSIVE_ATTR_PATTERN = re.compile(r'recursive="([^"]*)"')
_PATTERN_ATTR_PATTERN = re.compile(r'pattern="([^"]*)"')
_TOOL_NAME_ATTR_PATTERN = re.compile(r'tool_name="([^"]*)"')

# Comprehensive pattern for single-pass extraction
_COMPREHENSIVE_EXTRACTION_PATTERN = re.compile(
    r"(?P<exit_code>Exit code:\s*(-?\d+))|"
    r"(?P<cwd>working directory ['\"]([^'\"]+)['\"])|"
    r"(?P<output_label>\n(?:Output|Error|Stdout|Stderr):)",
    re.IGNORECASE,
)


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

    # Legacy Cline/Codex tools
    if stripped.startswith("<execute_command"):
        return _parse_execute_command_invocation(stripped)
    if stripped.startswith("<apply_diff"):
        return _parse_apply_diff_invocation(stripped)
    if stripped.startswith("<view_image"):
        return _parse_view_image_invocation(stripped)

    # KiloCode tools
    if stripped.startswith("<read_file"):
        return _parse_read_file_invocation(stripped)
    if stripped.startswith("<list_files"):
        return _parse_list_files_invocation(stripped)
    if stripped.startswith(("<codebase_search", "<search_files")):
        return _parse_search_files_invocation(stripped)
    if stripped.startswith("<use_mcp_tool"):
        return _parse_use_mcp_tool_invocation(stripped)
    if stripped.startswith("<attempt_completion"):
        return _parse_attempt_completion_invocation(stripped)
    if stripped.startswith("<ask_followup_question"):
        return _parse_ask_followup_invocation(stripped)

    return None


def parse_textual_tool_result(text: str) -> TextToolResult | None:
    """Parse a textual tool result of the form `[tool] Result: ...`."""
    stripped = text.strip()
    if not stripped or not stripped.startswith("[") or " Result" not in stripped:
        return None

    match = _TOOL_RESULT_PATTERN.match(stripped)
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

    # Use comprehensive pattern for single-pass extraction
    exit_code: int | None = None
    cwd: str | None = None
    output_section = body

    for match in _COMPREHENSIVE_EXTRACTION_PATTERN.finditer(body):
        if match.group("exit_code"):
            try:
                exit_code = int(match.group(2))  # Group 2 is the captured number
            except ValueError:
                exit_code = None
        elif match.group("cwd"):
            cwd_match = _CWD_PATTERN.search(match.group("cwd"))
            if cwd_match:
                cwd = cwd_match.group(1)
            else:
                cwd = match.group("cwd")
        elif match.group("output_label"):
            output_section = body[match.end() :]
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
    command_match = _COMMAND_PATTERN.search(text)
    if not command_match:
        return None

    command_text = command_match.group(1).strip()
    cwd_match = _CWD_PATTERN_XML.search(text)
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
    diff_match = _DIFF_PATTERN.search(text)
    if not diff_match:
        return None

    patch_text = diff_match.group(1).strip()
    path_match = _PATH_PATTERN.search(text)
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
    path_match = _PATH_PATTERN.search(text)
    if not path_match:
        return None

    path_value = path_match.group(1).strip()
    return TextToolInvocation(
        canonical_name="view_image",
        arguments={"path": path_value},
        raw_text=text,
        command_text=None,
    )


def _parse_read_file_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <read_file> XML invocation."""
    # Extract file path from attributes or content
    path_attr_match = _FILE_PATH_ATTR_PATTERN.search(text)
    if path_attr_match:
        file_path = path_attr_match.group(1).strip()
    else:
        # Try to extract from content
        content_match = _READ_FILE_PATTERN.search(text)
        if not content_match:
            return None
        file_path = content_match.group(1).strip()

    if not file_path:
        return None

    arguments = {"file_path": file_path}
    return TextToolInvocation(
        canonical_name="read_file",
        arguments=arguments,
        raw_text=text,
        command_text=None,
    )


def _parse_list_files_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <list_files> XML invocation."""
    # Extract path from attributes or content
    path_attr_match = _FILE_PATH_ATTR_PATTERN.search(text)
    if path_attr_match:
        dir_path = path_attr_match.group(1).strip()
    else:
        # Try to extract from content
        content_match = _LIST_FILES_PATTERN.search(text)
        if content_match:
            dir_path = content_match.group(1).strip()
        else:
            dir_path = "."  # Default to current directory

    # Check for recursive attribute
    recursive_match = _RECURSIVE_ATTR_PATTERN.search(text)
    recursive = recursive_match.group(1).lower() == "true" if recursive_match else False

    arguments = {"dir_path": dir_path or "."}
    if recursive:
        arguments["recursive"] = recursive

    return TextToolInvocation(
        canonical_name="list_dir",
        arguments=arguments,
        raw_text=text,
        command_text=None,
    )


def _parse_search_files_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <codebase_search> or <search_files> XML invocation."""
    # Extract pattern from attributes or content
    pattern_attr_match = _PATTERN_ATTR_PATTERN.search(text)
    if pattern_attr_match:
        pattern = pattern_attr_match.group(1).strip()
    else:
        # Try to extract from content
        content_match = _SEARCH_FILES_PATTERN.search(text)
        if not content_match:
            return None
        pattern = content_match.group(1).strip()

    if not pattern:
        return None

    arguments = {"pattern": pattern}

    # Extract optional path
    path_attr_match = _FILE_PATH_ATTR_PATTERN.search(text)
    if path_attr_match:
        arguments["path"] = path_attr_match.group(1).strip()

    return TextToolInvocation(
        canonical_name="grep_files",
        arguments=arguments,
        raw_text=text,
        command_text=None,
    )


def _parse_use_mcp_tool_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <use_mcp_tool> XML invocation."""
    # Extract tool name from attributes
    tool_name_match = _TOOL_NAME_ATTR_PATTERN.search(text)
    if not tool_name_match:
        return None

    tool_name = tool_name_match.group(1).strip()

    # Extract content and other attributes
    content_match = _USE_MCP_TOOL_PATTERN.search(text)
    arguments = {"tool_name": tool_name}

    # Add content if present
    if content_match:
        content = content_match.group(1).strip()
        if content:
            arguments["arguments"] = content

    # Extract any other attributes (path, etc.)
    path_match = _FILE_PATH_ATTR_PATTERN.search(text)
    if path_match:
        arguments["path"] = path_match.group(1).strip()

    # For patch_file operations, include special handling but let universal executor decide
    if tool_name == "patch_file" and "arguments" in arguments:
        arguments["patch_content"] = arguments["arguments"]

    return TextToolInvocation(
        canonical_name="use_mcp_tool",
        arguments=arguments,
        raw_text=text,
        command_text=None,
    )


def _parse_attempt_completion_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <attempt_completion> XML invocation."""
    content_match = _ATTEMPT_COMPLETION_PATTERN.search(text)
    result_text = content_match.group(1).strip() if content_match else ""

    return TextToolInvocation(
        canonical_name="completion_marker",
        arguments={"result": result_text},
        raw_text=text,
        command_text=None,
    )


def _parse_ask_followup_invocation(text: str) -> TextToolInvocation | None:
    """Parse KiloCode <ask_followup_question> XML invocation."""
    content_match = _ASK_FOLLOWUP_PATTERN.search(text)
    question_text = content_match.group(1).strip() if content_match else ""

    return TextToolInvocation(
        canonical_name="followup_marker",
        arguments={"question": question_text},
        raw_text=text,
        command_text=None,
    )
