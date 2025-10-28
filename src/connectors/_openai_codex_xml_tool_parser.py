"""XML tool parser for KiloCode compatibility layer in OpenAI Codex connector."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.connectors._openai_codex_compatibility_errors import (
    CompatibilityErrorCode,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolInvocation:
    """Parsed KiloCode XML tool invocation."""

    canonical_name: str  # Normalized tool name
    original_tag: str  # Original XML tag
    arguments: dict[str, Any]
    raw_xml: str
    command_text: str | None  # For execute_command


class XMLParseError(Exception):
    """Raised when XML parsing fails.

    This is a legacy exception that wraps TranslationError for backward compatibility.
    """

    def __init__(self, message: str, xml_text: str | None = None):
        super().__init__(message)
        self.xml_text = xml_text
        self.error_code = CompatibilityErrorCode.INVALID_XML_SYNTAX.value


class XMLToolParser:
    """Parses KiloCode XML tool invocations."""

    SUPPORTED_TAGS = {
        "read_file",
        "list_files",
        "execute_command",
        "codebase_search",
        "search_files",
        "use_mcp_tool",
        "access_mcp_resource",
        "attempt_completion",
        "ask_followup_question",
        "search_and_replace",
        "write_to_file",
        "insert_content",
        "edit_file",
    }

    def parse(self, xml_text: str) -> ParsedToolInvocation | None:
        """Extract tool name and parameters from XML.

        Args:
            xml_text: XML text containing tool invocation

        Returns:
            ParsedToolInvocation if a supported tag is found, None otherwise

        Raises:
            XMLParseError: If XML is malformed or parsing fails
        """
        if not xml_text or not isinstance(xml_text, str):
            return None

        xml_text = xml_text.strip()
        if not xml_text:
            return None

        # Try to find any supported tag
        for tag in self.SUPPORTED_TAGS:
            content = self.extract_tag_content(xml_text, tag)
            if content is not None:
                # Parse based on tag type
                try:
                    if tag == "read_file":
                        return self._parse_read_file(tag, content, xml_text)
                    elif tag == "list_files":
                        return self._parse_list_files(tag, content, xml_text)
                    elif tag == "execute_command":
                        return self._parse_execute_command(tag, content, xml_text)
                    elif tag in ("codebase_search", "search_files"):
                        return self._parse_search(tag, content, xml_text)
                    elif tag == "use_mcp_tool":
                        return self._parse_use_mcp_tool(tag, content, xml_text)
                    elif tag == "access_mcp_resource":
                        return self._parse_access_mcp_resource(tag, content, xml_text)
                    elif tag == "attempt_completion":
                        return self._parse_attempt_completion(tag, content, xml_text)
                    elif tag == "ask_followup_question":
                        return self._parse_ask_followup_question(tag, content, xml_text)
                    elif tag in (
                        "search_and_replace",
                        "write_to_file",
                        "insert_content",
                        "edit_file",
                    ):
                        return self._parse_editing_tool(tag, content, xml_text)
                except XMLParseError:
                    raise
                except Exception as e:
                    logger.error(
                        "Unexpected error parsing <%s> tag: %s",
                        tag,
                        str(e),
                        exc_info=True,
                    )
                    raise XMLParseError(
                        f"Failed to parse <{tag}> tag: {e!s}", xml_text
                    ) from e

        return None

    def extract_tag_content(self, xml_text: str, tag: str) -> str | None:
        """Extract content between XML tags.

        Args:
            xml_text: XML text to search
            tag: Tag name (without angle brackets)

        Returns:
            Content between tags, or None if tag not found
        """
        if not xml_text or not tag:
            return None

        # Try to match opening and closing tags (case-insensitive)
        # Handle both self-closing and regular tags
        # Use .* instead of .+ to allow empty content
        pattern = rf"<{tag}(?:\s[^>]*)?>(.+?)</{tag}>"
        match = re.search(pattern, xml_text, re.IGNORECASE | re.DOTALL)

        if match:
            return match.group(1).strip()

        # Try empty tags like <tag></tag>
        pattern = rf"<{tag}(?:\s[^>]*)?>(\s*)</{tag}>"
        match = re.search(pattern, xml_text, re.IGNORECASE | re.DOTALL)
        if match:
            return ""

        # Try self-closing tag with attributes
        pattern = rf"<{tag}(?:\s[^>]*)?/>"
        match = re.search(pattern, xml_text, re.IGNORECASE)
        if match:
            return ""

        return None

    def _parse_read_file(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <read_file> tag.

        Expected format:
        <read_file>path/to/file.py</read_file>
        or
        <read_file path="path/to/file.py" />
        """
        arguments: dict[str, Any] = {}

        # Check if content is a simple path (non-empty and not starting with <)
        if content and content.strip() and not content.startswith("<"):
            arguments["path"] = content.strip()
        else:
            # Try to extract path from attributes
            path_match = re.search(
                r'path\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
            )
            if path_match:
                arguments["path"] = path_match.group(1)
            else:
                # Try to extract nested <path> tag
                path_content = self._extract_nested_tag(content, "path")
                if path_content:
                    arguments["path"] = path_content
                else:
                    raise XMLParseError(
                        f"Missing required 'path' parameter in <{tag}> tag", raw_xml
                    )

        # Extract optional parameters
        start_line = self._extract_nested_tag(content, "start_line")
        if start_line:
            try:
                arguments["start_line"] = int(start_line)
            except ValueError:
                raise XMLParseError(
                    f"Invalid start_line value: {start_line}", raw_xml
                ) from None

        end_line = self._extract_nested_tag(content, "end_line")
        if end_line:
            try:
                arguments["end_line"] = int(end_line)
            except ValueError:
                raise XMLParseError(
                    f"Invalid end_line value: {end_line}", raw_xml
                ) from None

        return ParsedToolInvocation(
            canonical_name="read_file",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_list_files(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <list_files> tag.

        Expected format:
        <list_files>path/to/dir</list_files>
        or
        <list_files path="path/to/dir" recursive="true" />
        """
        arguments: dict[str, Any] = {}

        # Check if content is a simple path
        if content and not content.startswith("<"):
            arguments["path"] = content.strip()
        else:
            # Try to extract path from attributes
            path_match = re.search(
                r'path\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
            )
            if path_match:
                arguments["path"] = path_match.group(1)
            else:
                # Try to extract nested <path> tag
                path_content = self._extract_nested_tag(content, "path")
                if path_content:
                    arguments["path"] = path_content
                else:
                    # Default to current directory
                    arguments["path"] = "."

        # Extract optional recursive flag
        recursive_match = re.search(
            r'recursive\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if recursive_match:
            recursive_val = recursive_match.group(1).lower()
            arguments["recursive"] = recursive_val in ("true", "1", "yes")
        else:
            recursive_content = self._extract_nested_tag(content, "recursive")
            if recursive_content:
                arguments["recursive"] = recursive_content.lower() in (
                    "true",
                    "1",
                    "yes",
                )

        # Extract optional depth
        depth_content = self._extract_nested_tag(content, "depth")
        if depth_content:
            try:
                arguments["depth"] = int(depth_content)
            except ValueError:
                raise XMLParseError(
                    f"Invalid depth value: {depth_content}", raw_xml
                ) from None

        return ParsedToolInvocation(
            canonical_name="list_files",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_execute_command(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <execute_command> tag.

        Expected format:
        <execute_command>ls -la</execute_command>
        or
        <execute_command command="ls -la" working_dir="/tmp" />
        """
        arguments: dict[str, Any] = {}
        command_text = None

        # Check if content is a simple command (non-empty and not starting with <)
        if content and content.strip() and not content.startswith("<"):
            command_text = content.strip()
            arguments["command"] = command_text
        else:
            # Try to extract command from attributes
            cmd_match = re.search(
                r'command\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
            )
            if cmd_match:
                command_text = cmd_match.group(1)
                arguments["command"] = command_text
            else:
                # Try to extract nested <command> tag
                cmd_content = self._extract_nested_tag(content, "command")
                if cmd_content:
                    command_text = cmd_content
                    arguments["command"] = command_text
                else:
                    raise XMLParseError(
                        f"Missing required 'command' parameter in <{tag}> tag", raw_xml
                    )

        # Extract optional working directory
        wd_match = re.search(
            r'working_dir\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if wd_match:
            arguments["working_dir"] = wd_match.group(1)
        else:
            wd_content = self._extract_nested_tag(content, "working_dir")
            if wd_content:
                arguments["working_dir"] = wd_content

        # Extract optional timeout
        timeout_match = re.search(
            r'timeout\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if timeout_match:
            try:
                arguments["timeout"] = int(timeout_match.group(1))
            except ValueError:
                raise XMLParseError(
                    f"Invalid timeout value: {timeout_match.group(1)}", raw_xml
                ) from None
        else:
            timeout_content = self._extract_nested_tag(content, "timeout")
            if timeout_content:
                try:
                    arguments["timeout"] = int(timeout_content)
                except ValueError:
                    raise XMLParseError(
                        f"Invalid timeout value: {timeout_content}", raw_xml
                    ) from None

        return ParsedToolInvocation(
            canonical_name="execute_command",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=command_text,
        )

    def _parse_search(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <codebase_search> or <search_files> tag.

        Expected format:
        <codebase_search>search pattern</codebase_search>
        or
        <search_files pattern="*.py" query="def main" />
        """
        arguments: dict[str, Any] = {}

        # Check if content is a simple query (non-empty and not starting with <)
        if content and content.strip() and not content.startswith("<"):
            arguments["query"] = content.strip()
        else:
            # Try to extract query from attributes
            query_match = re.search(
                r'query\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
            )
            if query_match:
                arguments["query"] = query_match.group(1)
            else:
                # Try to extract nested <query> tag
                query_content = self._extract_nested_tag(content, "query")
                if query_content:
                    arguments["query"] = query_content
                else:
                    raise XMLParseError(
                        f"Missing required 'query' parameter in <{tag}> tag", raw_xml
                    )

        # Extract optional pattern/include
        pattern_match = re.search(
            r'pattern\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if pattern_match:
            arguments["pattern"] = pattern_match.group(1)
        else:
            pattern_content = self._extract_nested_tag(content, "pattern")
            if pattern_content:
                arguments["pattern"] = pattern_content

        # Extract optional include
        include_match = re.search(
            r'include\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if include_match:
            arguments["include"] = include_match.group(1)
        else:
            include_content = self._extract_nested_tag(content, "include")
            if include_content:
                arguments["include"] = include_content

        # Extract optional path
        path_match = re.search(
            r'path\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if path_match:
            arguments["path"] = path_match.group(1)
        else:
            path_content = self._extract_nested_tag(content, "path")
            if path_content:
                arguments["path"] = path_content

        # Extract optional exclude
        exclude_match = re.search(
            r'exclude\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if exclude_match:
            arguments["exclude"] = exclude_match.group(1)
        else:
            exclude_content = self._extract_nested_tag(content, "exclude")
            if exclude_content:
                arguments["exclude"] = exclude_content

        # Extract optional recursive flag
        recursive_match = re.search(
            r'recursive\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if recursive_match:
            recursive_val = recursive_match.group(1).lower()
            arguments["recursive"] = recursive_val in ("true", "1", "yes")
        else:
            recursive_content = self._extract_nested_tag(content, "recursive")
            if recursive_content:
                arguments["recursive"] = recursive_content.lower() in (
                    "true",
                    "1",
                    "yes",
                )

        return ParsedToolInvocation(
            canonical_name=tag,
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_use_mcp_tool(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <use_mcp_tool> tag.

        Expected format:
        <use_mcp_tool name="patch_file">
          <arguments>
            <diff>...</diff>
          </arguments>
        </use_mcp_tool>
        """
        arguments: dict[str, Any] = {}

        # Extract tool name from attribute
        name_match = re.search(
            r'name\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE
        )
        if name_match:
            arguments["tool_name"] = name_match.group(1)
        else:
            # Try to extract nested <name> tag
            name_content = self._extract_nested_tag(content, "name")
            if name_content and name_content.strip():
                arguments["tool_name"] = name_content
            else:
                raise XMLParseError(
                    f"Missing required 'name' parameter in <{tag}> tag", raw_xml
                )

        # Extract arguments - try to find <arguments> block
        args_content = self._extract_nested_tag(content, "arguments")
        if args_content:
            # Parse nested arguments
            tool_args = self._parse_nested_arguments(args_content)
            arguments["tool_arguments"] = tool_args
        else:
            # No nested arguments
            arguments["tool_arguments"] = {}

        return ParsedToolInvocation(
            canonical_name="use_mcp_tool",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_access_mcp_resource(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <access_mcp_resource> tag.

        Expected format:
        <access_mcp_resource uri="file://path/to/resource" />
        """
        arguments: dict[str, Any] = {}

        # Extract URI from attribute
        uri_match = re.search(r'uri\s*=\s*["\']([^"\']+)["\']', raw_xml, re.IGNORECASE)
        if uri_match:
            arguments["uri"] = uri_match.group(1)
        else:
            # Try to extract nested <uri> tag
            uri_content = self._extract_nested_tag(content, "uri")
            if uri_content and uri_content.strip():
                arguments["uri"] = uri_content
            elif content and content.strip() and not content.startswith("<"):
                arguments["uri"] = content.strip()
            else:
                raise XMLParseError(
                    f"Missing required 'uri' parameter in <{tag}> tag", raw_xml
                )

        return ParsedToolInvocation(
            canonical_name="access_mcp_resource",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_attempt_completion(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <attempt_completion> tag.

        Expected format:
        <attempt_completion>
          <result>Task completed successfully</result>
        </attempt_completion>
        """
        arguments: dict[str, Any] = {}

        # Extract result message
        result_content = self._extract_nested_tag(content, "result")
        if result_content:
            arguments["result"] = result_content
        elif content and content.strip() and not content.startswith("<"):
            arguments["result"] = content.strip()
        else:
            # Empty content is allowed for attempt_completion
            arguments["result"] = ""

        return ParsedToolInvocation(
            canonical_name="attempt_completion",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_ask_followup_question(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse <ask_followup_question> tag.

        Expected format:
        <ask_followup_question>What should I do next?</ask_followup_question>
        """
        arguments: dict[str, Any] = {}

        # Extract question
        question_content = self._extract_nested_tag(content, "question")
        if question_content and question_content.strip():
            arguments["question"] = question_content
        elif content and content.strip() and not content.startswith("<"):
            arguments["question"] = content.strip()
        else:
            raise XMLParseError(
                f"Missing required 'question' parameter in <{tag}> tag", raw_xml
            )

        return ParsedToolInvocation(
            canonical_name="ask_followup_question",
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _parse_editing_tool(
        self, tag: str, content: str, raw_xml: str
    ) -> ParsedToolInvocation:
        """Parse editing tool tags (search_and_replace, write_to_file, etc.).

        Expected format varies by tool type.
        """
        arguments: dict[str, Any] = {}

        if tag == "search_and_replace":
            # Extract path
            path_content = self._extract_nested_tag(content, "path")
            if path_content:
                arguments["path"] = path_content
            else:
                raise XMLParseError(
                    f"Missing required 'path' parameter in <{tag}> tag", raw_xml
                )

            # Extract search pattern
            search_content = self._extract_nested_tag(content, "search")
            if search_content:
                arguments["search"] = search_content
            else:
                raise XMLParseError(
                    f"Missing required 'search' parameter in <{tag}> tag", raw_xml
                )

            # Extract replace text
            replace_content = self._extract_nested_tag(content, "replace")
            if replace_content:
                arguments["replace"] = replace_content
            else:
                raise XMLParseError(
                    f"Missing required 'replace' parameter in <{tag}> tag", raw_xml
                )

        elif tag == "write_to_file":
            # Extract path
            path_content = self._extract_nested_tag(content, "path")
            if path_content:
                arguments["path"] = path_content
            else:
                raise XMLParseError(
                    f"Missing required 'path' parameter in <{tag}> tag", raw_xml
                )

            # Extract content (can be empty string)
            file_content = self._extract_nested_tag(content, "content")
            if file_content is not None:
                arguments["content"] = file_content
            else:
                raise XMLParseError(
                    f"Missing required 'content' parameter in <{tag}> tag", raw_xml
                )

        elif tag in ("insert_content", "edit_file"):
            # Extract path
            path_content = self._extract_nested_tag(content, "path")
            if path_content:
                arguments["path"] = path_content
            else:
                raise XMLParseError(
                    f"Missing required 'path' parameter in <{tag}> tag", raw_xml
                )

            # Extract content or other parameters based on tag
            content_text = self._extract_nested_tag(content, "content")
            if content_text:
                arguments["content"] = content_text

            # For insert_content, extract position
            if tag == "insert_content":
                position = self._extract_nested_tag(content, "position")
                if position:
                    try:
                        arguments["position"] = int(position)
                    except ValueError:
                        raise XMLParseError(
                            f"Invalid position value: {position}", raw_xml
                        ) from None

        return ParsedToolInvocation(
            canonical_name=tag,
            original_tag=tag,
            arguments=arguments,
            raw_xml=raw_xml,
            command_text=None,
        )

    def _extract_nested_tag(self, content: str, tag: str) -> str | None:
        """Extract content from a nested tag within content.

        Args:
            content: Content to search within
            tag: Tag name to extract

        Returns:
            Tag content or None if not found
        """
        if not content or not tag:
            return None

        # Try to match tags with content (including empty content)
        pattern = rf"<{tag}(?:\s[^>]*)?>(.+?)</{tag}>"
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

        if match:
            return match.group(1).strip()

        # Try to match empty tags like <tag></tag>
        pattern = rf"<{tag}(?:\s[^>]*)?>(\s*)</{tag}>"
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return ""

        return None

    def _parse_nested_arguments(self, args_content: str) -> dict[str, Any]:
        """Parse nested argument tags into a dictionary.

        Args:
            args_content: Content of <arguments> block

        Returns:
            Dictionary of argument name to value
        """
        arguments: dict[str, Any] = {}

        # Find all tags in the arguments block
        tag_pattern = r"<(\w+)(?:\s[^>]*)?>(.+?)</\1>"
        matches = re.finditer(tag_pattern, args_content, re.IGNORECASE | re.DOTALL)

        for match in matches:
            arg_name = match.group(1)
            arg_value = match.group(2).strip()
            arguments[arg_name] = arg_value

        return arguments
