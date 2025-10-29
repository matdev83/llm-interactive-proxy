"""KiloCode tool translator for OpenAI Codex compatibility layer."""

from __future__ import annotations

import logging
import time
import traceback
from typing import TYPE_CHECKING, Any

from src.connectors._openai_codex_compatibility_errors import (
    CompatibilityErrorCode,
    TranslationError,
    create_parameter_validation_error,
    create_xml_parse_error,
    log_translation_error,
)
from src.connectors._openai_codex_xml_tool_parser import (
    ParsedToolInvocation,
    XMLParseError,
    XMLToolParser,
)

if TYPE_CHECKING:
    from src.connectors.openai_codex import OpenAICodexConnector

logger = logging.getLogger(__name__)

# Import telemetry
try:
    from src.connectors._openai_codex_telemetry import get_telemetry
except ImportError:
    # Fallback if telemetry module is not available
    def get_telemetry():  # type: ignore
        """Fallback telemetry getter."""
        return None


class KiloToolTranslator:
    """Translates KiloCode XML tool invocations to Codex format."""

    def __init__(
        self, connector: OpenAICodexConnector, session_service: Any | None = None
    ):
        """Initialize the translator.

        Args:
            connector: The OpenAI Codex connector instance
            session_service: Optional session service for state management.
                If None, session state updates will be skipped with a warning.
        """
        self._connector = connector
        self._session_service = session_service
        self._xml_parser: XMLToolParser | None = (
            None  # Lazy initialization for performance
        )

        # Log warning if session service not provided
        if session_service is None:
            logger.warning(
                "KiloToolTranslator initialized without session_service. "
                "Session state updates will be skipped."
            )

    async def translate_tool_invocation(
        self, xml_text: str, session_id: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        """Parse XML and return (tool_name, arguments) or None.

        Args:
            xml_text: XML text containing tool invocation
            session_id: Optional session ID for telemetry

        Returns:
            Tuple of (tool_name, arguments) if translation successful, None otherwise

        Raises:
            TranslationError: If translation fails
        """
        if not xml_text or not isinstance(xml_text, str):
            return None

        start_time = time.time()
        telemetry = get_telemetry()

        try:
            # Lazy initialize XML parser on first use
            if self._xml_parser is None:
                self._xml_parser = XMLToolParser()

            # Parse the XML
            parsed = self._xml_parser.parse(xml_text)
            if not parsed:
                return None

            # Translate based on tool type
            result = None
            execution_mode = "codex"  # Default execution mode

            if parsed.canonical_name == "read_file":
                result = self._translate_read_file(parsed)
            elif parsed.canonical_name == "list_files":
                result = self._translate_list_files(parsed)
            elif parsed.canonical_name == "execute_command":
                result = self._translate_execute_command(parsed)
            elif parsed.canonical_name in ("codebase_search", "search_files"):
                result = self._translate_search(parsed)
            elif parsed.canonical_name == "attempt_completion":
                result = self._translate_attempt_completion(parsed)
                execution_mode = "proxy"
            elif parsed.canonical_name == "ask_followup_question":
                result = self._translate_ask_followup_question(parsed)
                execution_mode = "proxy"
            elif parsed.canonical_name == "use_mcp_tool":
                result = self._translate_use_mcp_tool(parsed)
                execution_mode = "mcp"
            elif parsed.canonical_name == "access_mcp_resource":
                result = self._translate_access_mcp_resource(parsed)
                execution_mode = "mcp"
            elif parsed.canonical_name in (
                "search_and_replace",
                "write_to_file",
                "insert_content",
                "edit_file",
            ):
                result = self._translate_editing_tool(parsed)
                execution_mode = "proxy"
            else:
                # Unsupported tool - raise error as per Requirement 11.1
                from src.connectors._openai_codex_compatibility_errors import (
                    create_unsupported_tool_error,
                )

                raise create_unsupported_tool_error(
                    tool_name=parsed.canonical_name,
                    original_xml=xml_text,
                    session_id=session_id,
                    supported_tools=(
                        list(self._xml_parser.SUPPORTED_TAGS)
                        if self._xml_parser
                        else []
                    ),
                )

            # Log successful translation telemetry
            if result and telemetry:
                duration_ms = (time.time() - start_time) * 1000
                telemetry.log_translation_event(
                    session_id=session_id or "unknown",
                    tool_name=parsed.canonical_name,
                    original_xml=xml_text,
                    translated_tool=result[0] if result else None,
                    execution_mode=execution_mode,
                    duration_ms=duration_ms,
                    success=True,
                )

            return result

        except XMLParseError as e:
            error = create_xml_parse_error(
                message=f"Failed to parse XML: {e!s}",
                original_xml=xml_text,
            )
            log_translation_error(error, logger)

            # Log error telemetry
            if telemetry:
                duration_ms = (time.time() - start_time) * 1000
                telemetry.log_error_event(
                    session_id=session_id or "unknown",
                    error_code=str(error.error_code),
                    tool_name=error.tool_name,
                    error_message=str(error),
                    original_xml=xml_text,
                    stack_trace=traceback.format_exc(),
                )

            raise error from e
        except TranslationError as e:
            # Log error telemetry
            if telemetry:
                duration_ms = (time.time() - start_time) * 1000
                telemetry.log_error_event(
                    session_id=session_id or "unknown",
                    error_code=str(e.error_code),
                    tool_name=e.tool_name,
                    error_message=str(e),
                    original_xml=xml_text,
                    stack_trace=traceback.format_exc(),
                )

            # Re-raise translation errors without wrapping
            raise
        except Exception as e:
            error = TranslationError(
                message=f"Translation failed: {e!s}",
                tool_name="unknown",
                error_code=CompatibilityErrorCode.TRANSLATION_TIMEOUT,
                original_xml=xml_text,
            )
            log_translation_error(error, logger)

            # Log error telemetry
            if telemetry:
                duration_ms = (time.time() - start_time) * 1000
                telemetry.log_error_event(
                    session_id=session_id or "unknown",
                    error_code=str(error.error_code),
                    tool_name=error.tool_name,
                    error_message=str(error),
                    original_xml=xml_text,
                    stack_trace=traceback.format_exc(),
                )

            raise error from e

    def _translate_read_file(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <read_file> to Codex read_file tool.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        # Map to Codex read_file tool
        arguments: dict[str, Any] = {}

        # Required: path
        if "path" not in parsed.arguments:
            raise create_parameter_validation_error(
                tool_name="read_file",
                message="Missing required 'path' parameter",
                original_xml=parsed.raw_xml,
                missing_parameters=["path"],
            )

        arguments["path"] = parsed.arguments["path"]

        # Optional: start_line and end_line
        if "start_line" in parsed.arguments:
            arguments["start_line"] = parsed.arguments["start_line"]

        if "end_line" in parsed.arguments:
            arguments["end_line"] = parsed.arguments["end_line"]

        logger.debug("Translated <read_file> to Codex read_file tool: %s", arguments)

        return ("read_file", arguments)

    def _translate_list_files(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <list_files> to Codex list_dir tool.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        # Map to Codex list_dir tool
        arguments: dict[str, Any] = {}

        # Required: path (defaults to "." if not provided)
        arguments["path"] = parsed.arguments.get("path", ".")

        # Optional: recursive flag (map to depth parameter)
        if "recursive" in parsed.arguments:
            # If recursive is True, use a reasonable depth
            if parsed.arguments["recursive"]:
                arguments["depth"] = parsed.arguments.get("depth", 3)
        elif "depth" in parsed.arguments:
            arguments["depth"] = parsed.arguments["depth"]

        logger.debug("Translated <list_files> to Codex list_dir tool: %s", arguments)

        return ("list_dir", arguments)

    def _translate_execute_command(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <execute_command> to Codex shell tool.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        # Map to Codex shell tool
        arguments: dict[str, Any] = {}

        # Required: command
        if "command" not in parsed.arguments:
            raise create_parameter_validation_error(
                tool_name="execute_command",
                message="Missing required 'command' parameter",
                original_xml=parsed.raw_xml,
                missing_parameters=["command"],
            )

        command = parsed.arguments["command"]

        # Convert command string to argument array
        # For now, we'll pass the command as a single string
        # The shell tool should handle this appropriately
        arguments["command"] = command

        # Optional: working_dir
        if "working_dir" in parsed.arguments:
            arguments["working_dir"] = parsed.arguments["working_dir"]

        # Optional: timeout
        if "timeout" in parsed.arguments:
            arguments["timeout"] = parsed.arguments["timeout"]

        logger.debug("Translated <execute_command> to Codex shell tool: %s", arguments)

        return ("shell", arguments)

    def _translate_search(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <codebase_search> or <search_files> to Codex grep_files tool.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        # Map to Codex grep_files tool (or proxy-side search)
        arguments: dict[str, Any] = {}

        # Required: query/pattern
        if "query" not in parsed.arguments:
            raise create_parameter_validation_error(
                tool_name=parsed.canonical_name,
                message="Missing required 'query' parameter",
                original_xml=parsed.raw_xml,
                missing_parameters=["query"],
            )

        # Map query to pattern for grep_files
        arguments["pattern"] = parsed.arguments["query"]

        # Optional: path (defaults to current directory)
        arguments["path"] = parsed.arguments.get("path", ".")

        # Optional: include pattern (glob pattern for file filtering)
        if "include" in parsed.arguments:
            arguments["include"] = parsed.arguments["include"]
        elif "pattern" in parsed.arguments:
            # If pattern is provided separately from query, use it as include
            arguments["include"] = parsed.arguments["pattern"]

        # Optional: exclude pattern (glob pattern for file filtering)
        if "exclude" in parsed.arguments:
            arguments["exclude"] = parsed.arguments["exclude"]

        # Optional: recursive flag (defaults to True for search)
        arguments["recursive"] = parsed.arguments.get("recursive", True)

        # Optional: case_sensitive flag (defaults to True)
        arguments["case_sensitive"] = parsed.arguments.get("case_sensitive", True)

        logger.debug(
            "Translated <%s> to Codex grep_files tool: %s",
            parsed.canonical_name,
            arguments,
        )

        return ("grep_files", arguments)

    def _translate_attempt_completion(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <attempt_completion> for proxy-side handling.

        This tag is handled proxy-side and should not be forwarded to Codex.
        Returns a special marker that indicates proxy-side handling.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments) with special marker
        """
        arguments: dict[str, Any] = {}

        # Extract result message (can be empty)
        arguments["result"] = parsed.arguments.get("result", "")

        logger.debug(
            "Translated <attempt_completion> for proxy-side handling: %s", arguments
        )

        # Return a special marker to indicate this should be handled proxy-side
        return ("__proxy_attempt_completion", arguments)

    def _translate_ask_followup_question(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <ask_followup_question> for proxy-side handling.

        This tag is handled proxy-side and should not be forwarded to Codex.
        Returns a special marker that indicates proxy-side handling.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments) with special marker
        """
        arguments: dict[str, Any] = {}

        # Extract question (required)
        if "question" not in parsed.arguments:
            raise create_parameter_validation_error(
                tool_name="ask_followup_question",
                message="Missing required 'question' parameter",
                original_xml=parsed.raw_xml,
                missing_parameters=["question"],
            )

        arguments["question"] = parsed.arguments["question"]

        logger.debug(
            "Translated <ask_followup_question> for proxy-side handling: %s", arguments
        )

        # Return a special marker to indicate this should be handled proxy-side
        return ("__proxy_ask_followup_question", arguments)

    async def handle_conversation_control(
        self, tool_name: str, arguments: dict[str, Any], session_id: str | None = None
    ) -> str:
        """Handle conversation control operations proxy-side.

        These operations are not forwarded to Codex but handled locally.

        Args:
            tool_name: The conversation control tool name (with __proxy_ prefix)
            arguments: Tool arguments
            session_id: Optional session ID for state tracking

        Returns:
            Acknowledgment response in KiloCode format
        """
        if tool_name == "__proxy_attempt_completion":
            result_msg = arguments.get("result", "")
            logger.info(
                "Handling attempt_completion proxy-side",
                extra={
                    "session_id": session_id,
                    "result_length": len(result_msg),
                },
            )

            # Update session state
            await self._update_session_completion(session_id, arguments)

            # Return acknowledgment
            return f"[attempt_completion] Task completion acknowledged: {result_msg}"

        elif tool_name == "__proxy_ask_followup_question":
            question = arguments.get("question", "")
            logger.info(
                "Handling ask_followup_question proxy-side",
                extra={
                    "session_id": session_id,
                    "question": question,
                },
            )

            # Update session state
            await self._update_session_followup(session_id, arguments)

            # Return acknowledgment
            return f"[ask_followup_question] Question received: {question}"

        else:
            from src.connectors._openai_codex_compatibility_errors import (
                create_unsupported_tool_error,
            )

            raise create_unsupported_tool_error(
                tool_name=tool_name,
                session_id=session_id,
            )

    def _translate_use_mcp_tool(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <use_mcp_tool> to appropriate format.

        For patch_file tool, attempts to convert to Codex apply_patch grammar.
        For other MCP tools, forwards to MCP server.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        arguments: dict[str, Any] = {}

        # Extract tool name
        tool_name = parsed.arguments.get("tool_name")
        if not tool_name:
            raise create_parameter_validation_error(
                tool_name="use_mcp_tool",
                message="Missing required 'tool_name' parameter in use_mcp_tool",
                original_xml=parsed.raw_xml,
                missing_parameters=["tool_name"],
            )

        # Extract tool arguments
        tool_arguments = parsed.arguments.get("tool_arguments", {})

        # Special handling for patch_file tool
        if tool_name == "patch_file":
            # Check if we can convert to Codex apply_patch grammar
            if "diff" in tool_arguments or "patch" in tool_arguments:
                # Try to use Codex apply_patch tool
                # For now, forward to MCP server as fallback
                # In a full implementation, we would parse the diff and convert to Codex format
                logger.debug(
                    "Forwarding patch_file to MCP server (Codex apply_patch conversion not yet implemented)"
                )

                # Return marker for MCP tool execution
                arguments["tool_name"] = tool_name
                arguments["tool_arguments"] = tool_arguments

                return ("__proxy_use_mcp_tool", arguments)
            else:
                raise create_parameter_validation_error(
                    tool_name="patch_file",
                    message="Missing required 'diff' or 'patch' parameter for patch_file",
                    original_xml=parsed.raw_xml,
                    missing_parameters=["diff", "patch"],
                )

        # For other MCP tools, forward to MCP server
        arguments["tool_name"] = tool_name
        arguments["tool_arguments"] = tool_arguments

        logger.debug(
            "Translated <use_mcp_tool> for MCP server forwarding: tool=%s", tool_name
        )

        return ("__proxy_use_mcp_tool", arguments)

    def _translate_access_mcp_resource(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate <access_mcp_resource> to Codex read_mcp_resource tool.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments)
        """
        arguments: dict[str, Any] = {}

        # Extract URI
        uri = parsed.arguments.get("uri")
        if not uri:
            raise create_parameter_validation_error(
                tool_name="access_mcp_resource",
                message="Missing required 'uri' parameter in access_mcp_resource",
                original_xml=parsed.raw_xml,
                missing_parameters=["uri"],
            )

        # Map to Codex read_mcp_resource tool with parameter renaming
        # KiloCode uses 'uri', Codex might use 'resource_uri' or similar
        arguments["uri"] = uri

        logger.debug(
            "Translated <access_mcp_resource> to Codex read_mcp_resource tool: uri=%s",
            uri,
        )

        # Return marker for MCP resource access
        return ("__proxy_access_mcp_resource", arguments)

    def _translate_editing_tool(
        self, parsed: ParsedToolInvocation
    ) -> tuple[str, dict[str, Any]]:
        """Translate editing tools (search_and_replace, write_to_file, etc.).

        These tools are executed proxy-side using file system helpers.

        Args:
            parsed: Parsed tool invocation

        Returns:
            Tuple of (tool_name, arguments) with proxy marker
        """
        tool_name = parsed.canonical_name
        arguments: dict[str, Any] = {}

        if tool_name == "search_and_replace":
            # Validate required parameters
            missing = []
            if "path" not in parsed.arguments:
                missing.append("path")
            if "search" not in parsed.arguments:
                missing.append("search")
            if "replace" not in parsed.arguments:
                missing.append("replace")

            if missing:
                raise create_parameter_validation_error(
                    tool_name=tool_name,
                    message=f"Missing required parameters: {', '.join(missing)}",
                    original_xml=parsed.raw_xml,
                    missing_parameters=missing,
                )

            arguments["path"] = parsed.arguments["path"]
            arguments["search"] = parsed.arguments["search"]
            arguments["replace"] = parsed.arguments["replace"]

        elif tool_name == "write_to_file":
            # Validate required parameters
            missing = []
            if "path" not in parsed.arguments:
                missing.append("path")
            if "content" not in parsed.arguments:
                missing.append("content")

            if missing:
                raise create_parameter_validation_error(
                    tool_name=tool_name,
                    message=f"Missing required parameters: {', '.join(missing)}",
                    original_xml=parsed.raw_xml,
                    missing_parameters=missing,
                )

            arguments["path"] = parsed.arguments["path"]
            arguments["content"] = parsed.arguments["content"]

        elif tool_name == "insert_content":
            # Validate required parameters
            missing = []
            if "path" not in parsed.arguments:
                missing.append("path")
            if "content" not in parsed.arguments:
                missing.append("content")

            if missing:
                raise create_parameter_validation_error(
                    tool_name=tool_name,
                    message=f"Missing required parameters: {', '.join(missing)}",
                    original_xml=parsed.raw_xml,
                    missing_parameters=missing,
                )

            arguments["path"] = parsed.arguments["path"]
            arguments["content"] = parsed.arguments["content"]

            # Optional position parameter
            if "position" in parsed.arguments:
                arguments["position"] = parsed.arguments["position"]

        elif tool_name == "edit_file":
            # Validate required parameters
            if "path" not in parsed.arguments:
                raise create_parameter_validation_error(
                    tool_name=tool_name,
                    message="Missing required 'path' parameter",
                    original_xml=parsed.raw_xml,
                    missing_parameters=["path"],
                )

            arguments["path"] = parsed.arguments["path"]

            # Optional content parameter
            if "content" in parsed.arguments:
                arguments["content"] = parsed.arguments["content"]

        logger.debug(
            "Translated <%s> for proxy-side execution: %s", tool_name, arguments
        )

        # Return marker for proxy-side execution
        return (f"__proxy_{tool_name}", arguments)

    def _translate_mcp_parameters(
        self, kilo_params: dict[str, Any], mcp_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate KiloCode parameters to MCP parameter format.

        Args:
            kilo_params: Parameters from KiloCode tool invocation
            mcp_schema: MCP tool schema with parameter definitions

        Returns:
            Translated parameters for MCP tool

        Raises:
            TranslationError: If parameter validation fails
        """
        translated = {}

        # Get parameter definitions from schema
        schema_params = mcp_schema.get("parameters", {})
        if isinstance(schema_params, dict):
            properties = schema_params.get("properties", {})
            required = schema_params.get("required", [])
        else:
            properties = {}
            required = []

        # Validate required parameters are present
        missing_params = []
        for param_name in required:
            if param_name not in kilo_params:
                missing_params.append(param_name)

        if missing_params:
            raise create_parameter_validation_error(
                tool_name="mcp_tool",
                message=f"Missing required parameters: {', '.join(missing_params)}",
                missing_parameters=missing_params,
            )

        # Translate each parameter
        for param_name, param_value in kilo_params.items():
            # Get parameter schema
            param_schema = properties.get(param_name, {})
            param_type = param_schema.get("type")

            # Convert parameter types based on schema
            if param_type == "integer":
                # Convert string to int
                if isinstance(param_value, str):
                    try:
                        translated[param_name] = int(param_value)
                    except ValueError:
                        raise create_parameter_validation_error(
                            tool_name="mcp_tool",
                            message=f"Invalid {param_type} value for parameter '{param_name}': {param_value}",
                            invalid_parameters={
                                param_name: f"Expected {param_type}, got string"
                            },
                        )
                else:
                    translated[param_name] = param_value
            elif param_type == "number":
                # Convert string to float
                if isinstance(param_value, str):
                    try:
                        translated[param_name] = float(param_value)  # type: ignore[assignment]
                    except ValueError:
                        raise create_parameter_validation_error(
                            tool_name="mcp_tool",
                            message=f"Invalid {param_type} value for parameter '{param_name}': {param_value}",
                            invalid_parameters={
                                param_name: f"Expected {param_type}, got string"
                            },
                        )
                else:
                    translated[param_name] = param_value

            elif param_type == "boolean":
                # Convert string to bool
                if isinstance(param_value, str):
                    if param_value.lower() in ("true", "1", "yes"):
                        translated[param_name] = True
                    elif param_value.lower() in ("false", "0", "no"):
                        translated[param_name] = False
                    else:
                        raise create_parameter_validation_error(
                            tool_name="mcp_tool",
                            message=f"Invalid boolean value for parameter '{param_name}': {param_value}",
                            invalid_parameters={
                                param_name: "Expected boolean, got invalid string"
                            },
                        )
                else:
                    translated[param_name] = bool(param_value)

            else:
                # Keep as-is for string, array, object types
                translated[param_name] = param_value

        # Handle optional parameters with default values
        for param_name, param_schema in properties.items():
            if param_name not in translated and "default" in param_schema:
                translated[param_name] = param_schema["default"]

        logger.debug(
            "Translated MCP parameters: %d input params -> %d output params",
            len(kilo_params),
            len(translated),
        )

        return translated

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> str:
        """Format execution result in KiloCode's expected format.

        Args:
            tool_name: Name of the tool that was executed
            result: Result dictionary from tool execution

        Returns:
            Formatted result string in KiloCode format
        """
        # Handle MCP results specially (check for MCP-specific fields first)
        if isinstance(result, dict):
            # Check for MCP response structure with content field
            if "content" in result and "output" not in result:
                # MCP result with content field
                content = result["content"]
                if isinstance(content, list):
                    # Multiple content items
                    content_str = "\n".join(str(item) for item in content)
                else:
                    content_str = str(content)

                # Check for errors
                if result.get("isError"):
                    error_msg = result.get("error", content_str)
                    return f"[{tool_name}] Error: {error_msg}"

                return f"[{tool_name}] Result:\n{content_str}"

            # Check for MCP response structure with result field (but not output)
            elif (
                "result" in result
                and "output" not in result
                and "exit_code" not in result
            ):
                # MCP result with result field
                result_content = result["result"]
                if result.get("isError"):
                    error_msg = result.get("error", str(result_content))
                    return f"[{tool_name}] Error: {error_msg}"

                return f"[{tool_name}] Result:\n{result_content!s}"

        # Standard KiloCode format: [tool_name] Result: <content>
        output = result.get("output", "") if isinstance(result, dict) else str(result)
        exit_code = result.get("exit_code") if isinstance(result, dict) else None

        # Build the formatted result
        formatted_parts = [f"[{tool_name}] Result:"]

        if output:
            formatted_parts.append(output)

        # Add exit code for command execution
        if exit_code is not None and tool_name in ("shell", "execute_command"):
            formatted_parts.append(f"\nExit code: {exit_code}")

        # Add match count for search results
        if tool_name in ("grep_files", "codebase_search", "search_files"):
            matches_count = (
                result.get("matches_count") if isinstance(result, dict) else None
            )
            if matches_count is not None:
                formatted_parts.append(f"\nMatches found: {matches_count}")

        # Add error information if present
        if isinstance(result, dict) and result.get("error"):
            formatted_parts.append(f"\nError: {result['error']}")

        formatted_result = "\n".join(formatted_parts)

        logger.debug(
            "Formatted result for tool '%s' (length: %d bytes)",
            tool_name,
            len(formatted_result),
        )

        return formatted_result

    async def _update_session_completion(
        self, session_id: str | None, arguments: dict[str, Any]
    ) -> None:
        """Update session state for attempt_completion.

        Args:
            session_id: Session identifier
            arguments: Tool arguments containing completion result
        """
        if not session_id:
            logger.debug("No session_id provided, skipping session state update")
            return

        if not self._session_service:
            logger.debug(
                "Session service not available, skipping session state update for session %s",
                session_id,
            )
            return

        try:
            # Extract completion result
            completion_result = arguments.get("result", "")

            # Update session with completion status
            await self._session_service.update_session(
                session_id,
                status="completed",
                completion_result=completion_result,
                completed_at=time.time(),
            )

            logger.info(
                "Session %s marked as completed (result length: %d)",
                session_id,
                len(completion_result),
            )

        except Exception as e:
            # Log error but don't fail the request
            logger.error(
                "Failed to update session state for completion (session: %s): %s",
                session_id,
                str(e),
                exc_info=True,
            )

            # Record telemetry event for session update failure
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_error_event(
                    session_id=session_id,
                    error_code="SessionUpdateFailed",
                    tool_name="attempt_completion",
                    error_message=str(e),
                    original_xml="",
                    stack_trace=traceback.format_exc(),
                )

    async def _update_session_followup(
        self, session_id: str | None, arguments: dict[str, Any]
    ) -> None:
        """Update session state for ask_followup_question.

        Args:
            session_id: Session identifier
            arguments: Tool arguments containing follow-up question
        """
        if not session_id:
            logger.debug("No session_id provided, skipping session state update")
            return

        if not self._session_service:
            logger.debug(
                "Session service not available, skipping session state update for session %s",
                session_id,
            )
            return

        try:
            # Extract question
            question = arguments.get("question", "")

            # Get current session to preserve existing followup_questions list
            session = await self._session_service.get_session(session_id)
            existing_questions = (
                session.get("followup_questions", []) if session else []
            )

            # Append new question to list
            updated_questions = [
                *existing_questions,
                {"question": question, "timestamp": time.time()},
            ]

            # Update session with new followup question
            await self._session_service.update_session(
                session_id,
                followup_questions=updated_questions,
                last_followup_at=time.time(),
            )

            logger.info(
                "Session %s updated with follow-up question (total questions: %d)",
                session_id,
                len(updated_questions),
            )

        except Exception as e:
            # Log error but don't fail the request
            logger.error(
                "Failed to update session state for follow-up question (session: %s): %s",
                session_id,
                str(e),
                exc_info=True,
            )

            # Record telemetry event for session update failure
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_error_event(
                    session_id=session_id,
                    error_code="SessionUpdateFailed",
                    tool_name="ask_followup_question",
                    error_message=str(e),
                    original_xml="",
                    stack_trace=traceback.format_exc(),
                )
