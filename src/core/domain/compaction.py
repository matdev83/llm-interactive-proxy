"""
Domain models for context compaction feature.

This module defines the core domain concepts for intelligent context compaction
of stale tool outputs in message histories before dispatch to LLM backends.

Requirements covered:
- 1.1-1.3: Resource identity and staleness detection
- 2.1-2.3: Stub replacement for stale outputs
- 3.3-3.4: Per-tool allow/deny policies
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolCategory(str, Enum):
    """Categories of tools for compaction policy evaluation.

    Used to determine which tool types are eligible for compaction
    per the allow/deny configuration (Req 3.4).
    """

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    COMMAND_EXECUTION = "command_execution"
    SEARCH = "search"
    LIST_DIRECTORY = "list_dir"
    VIEW_FILE = "view_file"
    TEST_EXECUTION = "test_execution"
    OTHER = "other"


# Tool name patterns that map to categories
# Note: Order matters - more specific categories should be checked first
_TOOL_CATEGORY_PATTERNS: list[tuple[ToolCategory, list[str]]] = [
    # VIEW_FILE is more specific than FILE_READ, check first
    (ToolCategory.VIEW_FILE, ["view_file", "view_file_outline"]),
    (
        ToolCategory.FILE_READ,
        [
            "read_file",
            "cat",
            "read",
            "get_file_contents",
            "file_read",
            "view_code_item",
            "search_in_file",
        ],
    ),
    (
        ToolCategory.FILE_WRITE,
        [
            "write_file",
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
            "apply_diff",
            "apply_patch",
            "edit_file",
            "create_file",
        ],
    ),
    (
        ToolCategory.COMMAND_EXECUTION,
        [
            "run_command",
            "execute_command",
            "bash",
            "shell",
            "terminal",
            "command_status",
            "send_command_input",
        ],
    ),
    (
        ToolCategory.SEARCH,
        [
            "grep_search",
            "codebase_search",
            "find_by_name",
            "search",
            "ripgrep",
            "find",
        ],
    ),
    (ToolCategory.LIST_DIRECTORY, ["list_dir", "ls", "directory", "list_directory"]),
    (
        ToolCategory.TEST_EXECUTION,
        [
            "run_pytest",
            "run_tests",
            "test",
            "pytest",
            "unittest",
            "jest",
            "mocha",
            "npm_test",
        ],
    ),
]


@dataclass(frozen=True)
class ResourceIdentity:
    """Unique identifier for a resource accessed by a tool.

    Used to correlate tool results for the same resource across conversation
    history to detect staleness (Req 1.1).

    The identity is constructed from:
    - Tool name (normalized)
    - Primary resource key (e.g., file path, command signature)
    - Optional secondary keys for disambiguation

    Invariants:
    - Two ResourceIdentity instances are equal iff they refer to the same resource
    - Identity is immutable once created
    """

    tool_name: str
    primary_key: str
    secondary_keys: tuple[str, ...] = field(default_factory=tuple)

    def __hash__(self) -> int:
        return hash((self.tool_name.lower(), self.primary_key, self.secondary_keys))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResourceIdentity):
            return NotImplemented
        return (
            self.tool_name.lower() == other.tool_name.lower()
            and self.primary_key == other.primary_key
            and self.secondary_keys == other.secondary_keys
        )

    def __str__(self) -> str:
        if self.secondary_keys:
            return (
                f"{self.tool_name}:{self.primary_key}:{':'.join(self.secondary_keys)}"
            )
        return f"{self.tool_name}:{self.primary_key}"


@dataclass(frozen=True)
class CompactionStub:
    """Replacement content for a stale tool result.

    Contains the stub message that replaces the original tool output
    when it has been superseded by newer results (Req 2.1).

    Attributes:
        resource_identity: The resource this stub represents
        original_byte_size: Size of the original content that was replaced
        stub_text: The replacement text content
        message_index: Position of the original message in history
    """

    resource_identity: ResourceIdentity
    original_byte_size: int
    stub_text: str
    message_index: int

    @classmethod
    def create(
        cls,
        resource_identity: ResourceIdentity,
        original_content: str,
        message_index: int,
    ) -> "CompactionStub":
        """Create a compaction stub for stale content.

        Args:
            resource_identity: Identity of the compacted resource
            original_content: The original content being replaced
            message_index: Index of the message in history

        Returns:
            A new CompactionStub instance with generated stub text
        """
        original_size = len(original_content.encode("utf-8"))
        stub_text = (
            f"[COMPACTED] Previous output for {resource_identity.primary_key} "
            f"({original_size} bytes) was removed because a newer result "
            f"for this resource exists later in the conversation."
        )
        return cls(
            resource_identity=resource_identity,
            original_byte_size=original_size,
            stub_text=stub_text,
            message_index=message_index,
        )


class ResourceIdentityExtractor:
    """Extracts resource identity from tool call arguments.

    Implements the correlation key extraction logic for tool outputs
    (Req 1.1, 1.3). Handles various tool argument formats and extracts
    the primary resource identifier.

    Supported key types:
    - File paths: file_path, path, AbsolutePath, filepath, File
    - Command signatures: command, CommandLine, cmd
    - Search queries: Query, query, pattern
    - Directory paths: DirectoryPath, SearchDirectory
    """

    # Parameter names for different resource types
    PATH_PARAMS: tuple[str, ...] = (
        "file_path",
        "path",
        "AbsolutePath",
        "filepath",
        "File",
        "TargetFile",
        "target_file",
        "filename",
    )

    DIRECTORY_PARAMS: tuple[str, ...] = (
        "DirectoryPath",
        "SearchDirectory",
        "directory",
        "dir",
        "Cwd",
    )

    COMMAND_PARAMS: tuple[str, ...] = ("command", "CommandLine", "cmd", "Input")

    QUERY_PARAMS: tuple[str, ...] = ("Query", "query", "pattern", "SearchPath")

    def extract(
        self,
        tool_name: str,
        arguments: str | dict[str, Any] | None,
        tool_call_id: str | None = None,
    ) -> ResourceIdentity | None:
        """Extract resource identity from tool arguments.

        Args:
            tool_name: Name of the tool that was called
            arguments: Tool call arguments (JSON string or dict)
            tool_call_id: Optional tool call ID for fallback

        Returns:
            ResourceIdentity if extraction succeeds, None if identity
            cannot be determined (Req 1.3)
        """
        if arguments is None:
            return None

        # Parse JSON string arguments
        args_dict: dict[str, Any]
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                if isinstance(parsed, dict):
                    args_dict = parsed
                else:
                    # Arguments is a simple string value
                    return ResourceIdentity(
                        tool_name=tool_name,
                        primary_key=arguments.strip(),
                    )
            except json.JSONDecodeError:
                # Treat as raw string argument
                if arguments.strip():
                    return ResourceIdentity(
                        tool_name=tool_name,
                        primary_key=arguments.strip(),
                    )
                return None
        else:
            args_dict = arguments

        # Try path parameters first
        primary_key = self._extract_param(args_dict, self.PATH_PARAMS)
        if primary_key:
            return ResourceIdentity(
                tool_name=tool_name,
                primary_key=self._normalize_path(primary_key),
            )

        # Try directory parameters
        primary_key = self._extract_param(args_dict, self.DIRECTORY_PARAMS)
        if primary_key:
            # For directory operations, include pattern if present
            pattern = self._extract_param(args_dict, ("Pattern", "pattern"))
            secondary = (pattern,) if pattern else ()
            return ResourceIdentity(
                tool_name=tool_name,
                primary_key=self._normalize_path(primary_key),
                secondary_keys=secondary,
            )

        # Try command parameters
        primary_key = self._extract_param(args_dict, self.COMMAND_PARAMS)
        if primary_key:
            # Create a signature from the command
            signature = self._create_command_signature(primary_key)
            return ResourceIdentity(
                tool_name=tool_name,
                primary_key=signature,
            )

        # Try query parameters
        primary_key = self._extract_param(args_dict, self.QUERY_PARAMS)
        if primary_key:
            search_path = self._extract_param(
                args_dict, ("SearchPath", "path", "directory")
            )
            secondary = (search_path,) if search_path else ()
            return ResourceIdentity(
                tool_name=tool_name,
                primary_key=primary_key,
                secondary_keys=secondary,
            )

        # Fallback: use tool_call_id if provided (Req 1.3 - skip compaction)
        # We return None here as per requirement 1.3:
        # "the proxy shall skip compaction for that message and preserve its content"
        return None

    def _extract_param(
        self,
        args: dict[str, Any],
        param_names: tuple[str, ...],
    ) -> str | None:
        """Extract a parameter value from arguments by trying multiple names."""
        for name in param_names:
            value = args.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_path(self, path: str) -> str:
        """Normalize path for consistent comparison.

        - Convert backslashes to forward slashes
        - Remove trailing slashes
        - Lowercase drive letters on Windows
        """
        normalized = path.replace("\\", "/").rstrip("/")
        # Lowercase Windows drive letter if present
        if len(normalized) >= 2 and normalized[1] == ":":
            normalized = normalized[0].lower() + normalized[1:]
        return normalized

    def _create_command_signature(self, command: str) -> str:
        """Create a normalized signature from a command string.

        Extracts the base command/executable to correlate similar commands
        while ignoring argument variations.
        """
        # Extract first word/executable from command
        parts = command.strip().split()
        if not parts:
            return command

        # Get base command, stripping common prefixes
        base = parts[0]

        # Remove path prefixes
        if "/" in base or "\\" in base:
            base = base.split("/")[-1].split("\\")[-1]

        # Remove common extensions
        base = re.sub(r"\.(exe|sh|bat|cmd|ps1)$", "", base, flags=re.IGNORECASE)

        return base.lower()


def categorize_tool(tool_name: str) -> ToolCategory:
    """Determine the category of a tool by name.

    Used for allow/deny policy evaluation (Req 3.4).

    Args:
        tool_name: The tool name to categorize

    Returns:
        The ToolCategory for this tool
    """
    normalized = tool_name.lower().replace("_", "").replace("-", "")

    for category, patterns in _TOOL_CATEGORY_PATTERNS:
        for pattern in patterns:
            normalized_pattern = pattern.lower().replace("_", "").replace("-", "")
            if normalized == normalized_pattern:
                return category

    return ToolCategory.OTHER


def is_tool_result_message(role: str, tool_call_id: str | None) -> bool:
    """Check if a message is a tool result message.

    Tool result messages have role='tool' and a tool_call_id linking
    them to the original tool call.

    Args:
        role: The message role
        tool_call_id: The tool call ID if present

    Returns:
        True if this is a tool result message eligible for compaction
    """
    return role == "tool" and tool_call_id is not None
