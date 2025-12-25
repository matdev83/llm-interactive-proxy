"""
Gemini CLI ACP (Agent Client Protocol) connector

This connector delegates/forwards user prompts to gemini-cli using the Agent Client Protocol (ACP).
Unlike other gemini-cli backends that use OAuth credentials, this backend spawns gemini-cli as a
subprocess and communicates with it via JSON-RPC over standard input/output streams.

The Agent Client Protocol (ACP) is a standardized protocol for communication between code editors
and AI coding agents. It uses JSON-RPC for structured data exchange and supports features like:
- Real-time streaming updates
- Tool call lifecycle management
- User confirmations
- Multi-buffer file editing
- Command execution

This implementation allows the proxy to act as an ACP client, delegating all AI processing to
the gemini-cli agent while providing a standardized OpenAI-compatible API to clients.

=== CRITICAL IMPLEMENTATION NOTES ===

1. SUBPROCESS MANAGEMENT:
   - gemini-cli is spawned as a subprocess for each session
   - Communication is via stdin/stdout using JSON-RPC
   - Process lifecycle must be properly managed (spawn, monitor, cleanup)

2. ACP PROTOCOL:
   - First message must include AgentSettings with project directory
   - Messages follow JSON-RPC 2.0 specification
   - Responses come as streaming TaskStatusUpdateEvents
   - Tool calls require confirmation handling

3. MESSAGE FORMAT:
   - Request: JSON-RPC with method and params
   - Response: Streaming events with agent thoughts, tool calls, and text
   - Must handle both structured (DataPart) and text (TextPart) responses

4. STREAMING:
   - ACP streams responses as TaskStatusUpdateEvents
   - Each event contains agent thoughts, tool calls, or text responses
   - Must aggregate streaming events into final response

5. ERROR HANDLING:
   - Subprocess failures must be caught and reported
   - Communication timeouts must be handled gracefully
   - Malformed JSON responses must be handled

This implementation provides full integration with gemini-cli as an agent,
enabling advanced features like multi-file editing, tool usage, and streaming.
"""

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import tiktoken

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.domain.session_key import SessionKey
from src.core.domain.usage_summary import UsageSummary
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .base import add_vendor_prefix
from .gemini import GeminiBackend
from .gemini_cli_acp_types import ACPResponse, DataPart, TaskStatusUpdateEvent, TextPart

logger = logging.getLogger(__name__)


# Default timeout for gemini-cli responses (in seconds)
DEFAULT_PROCESS_TIMEOUT = 300.0  # 5 minutes for complex operations
DEFAULT_CONNECTION_TIMEOUT = 60.0
DEFAULT_IDLE_TIMEOUT = 30.0  # Kill process if idle for this long
MAX_RESPONSE_LINE_SIZE = 10 * 1024 * 1024  # 10MB limit for JSON-RPC lines


class GeminiCliAcpConnector(GeminiBackend):
    """Connector that uses gemini-cli via Agent Client Protocol (ACP).

    This connector spawns gemini-cli as a subprocess and communicates with it
    using JSON-RPC over stdin/stdout according to the ACP specification.
    """

    backend_type: str = "gemini-cli-acp"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        **kwargs: Any,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.name = "gemini-cli-acp"
        self.is_functional = False
        self._process: subprocess.Popen[bytes] | None = None
        self._project_dir: Path | None = None
        self._gemini_cli_executable: str = "gemini"
        self._model: str = "gemini-2.5-flash"
        self._auto_accept: bool = True
        self._process_timeout: float = DEFAULT_PROCESS_TIMEOUT
        self._idle_timeout: float = DEFAULT_IDLE_TIMEOUT
        self._last_activity: float = 0
        self._initialization_failed = False
        self._message_id = 0
        self._pending_responses: dict[int, asyncio.Future[Any]] = {}

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the gemini-cli ACP backend.

        Args:
            project_dir: Path to project directory (optional, can be set later)
            gemini_cli_executable: Path to gemini-cli executable (default: "gemini")
            model: Model to use (default: "gemini-2.5-flash")
            auto_accept: Auto-accept safe operations (default: True)
            process_timeout: Timeout for process operations in seconds
            **kwargs: Additional configuration parameters

        Note:
            project_dir can be provided via:
            1. Initialize parameter (project_dir=...)
            2. Environment variable (GEMINI_CLI_WORKSPACE)
            3. CLI parameter (via config)
            4. Slash command (!/project-dir(/path))
            5. Current working directory (fallback)
        """
        try:
            # Get project directory with multiple fallbacks
            project_dir = (
                kwargs.get("project_dir")  # 1. Explicit parameter
                or os.getenv("GEMINI_CLI_WORKSPACE")  # 2. Environment variable
                or os.getcwd()  # 3. Current working directory as fallback
            )

            self._project_dir = Path(project_dir).resolve()
            if not self._project_dir.exists():
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Project directory does not exist: {project_dir}, "
                        f"using current directory instead"
                    )
                self._project_dir = Path(os.getcwd()).resolve()

            # Get optional configuration
            self._gemini_cli_executable = kwargs.get("gemini_cli_executable", "gemini")
            self._model = kwargs.get("model", "gemini-2.5-flash")
            self._auto_accept = kwargs.get("auto_accept", True)
            self._process_timeout = kwargs.get(
                "process_timeout", DEFAULT_PROCESS_TIMEOUT
            )

            # Verify gemini-cli is available
            if not self._check_gemini_cli_available():
                raise ConfigurationError(
                    message=f"gemini-cli executable not found: {self._gemini_cli_executable}",
                    details={
                        "executable": self._gemini_cli_executable,
                        "hint": "Install with: npm install -g @google/gemini-cli",
                    },
                )

            self.is_functional = True
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Initialized gemini-cli-acp backend with project directory: {self._project_dir}"
                )

        except Exception as e:
            self._initialization_failed = True
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to initialize gemini-cli-acp backend: {e}")
            raise

    def _check_gemini_cli_available(self) -> bool:
        """Check if gemini-cli executable is available."""
        try:
            result = subprocess.run(
                [self._gemini_cli_executable, "--version"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _get_next_message_id(self) -> int:
        """Get next message ID for JSON-RPC."""
        self._message_id += 1
        return self._message_id

    async def change_project_dir(self, project_dir: str) -> None:
        """Change the project directory and restart the gemini-cli process.

        Args:
            project_dir: New project directory path

        Raises:
            ConfigurationError: If project directory doesn't exist
        """
        new_project_dir = Path(project_dir).resolve()

        if not new_project_dir.exists():
            raise ConfigurationError(
                message=f"Project directory does not exist: {project_dir}",
                details={"project_dir": str(project_dir)},
            )

        # Check if project directory actually changed
        if new_project_dir == self._project_dir:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Project directory already set to {project_dir}")
            return

        # Kill existing process
        await self._kill_process()

        # Update project directory
        old_project_dir = self._project_dir
        self._project_dir = new_project_dir

        # Reset message ID for new process
        self._message_id = 0

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Project directory changed from {old_project_dir} to {self._project_dir}"
            )

    async def _spawn_gemini_cli_process(self) -> None:
        """Spawn gemini-cli subprocess with ACP support."""
        if self._process and self._process.poll() is None:
            # Process already running
            return

        process: subprocess.Popen[bytes] | None = None
        try:
            # Build command with ACP flags
            cmd = [
                self._gemini_cli_executable,
                "--experimental-acp",  # Enable ACP mode
                "--model",
                self._model,
            ]

            if self._auto_accept:
                cmd.append("-y")  # YOLO mode (auto-accept)

            # Spawn process
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Spawning gemini-cli process: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._project_dir),
            )
            # Assign to instance variable only after successful creation
            self._process = process

            # Wait a moment for process to start
            await asyncio.sleep(0.1)

            # Check if process started successfully
            if self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode(
                        "utf-8", errors="replace"
                    )
                # Don't call _cleanup_process here - let exception handler
                # call _kill_process() which will clean up properly
                # This avoids double cleanup which causes test failures
                raise BackendError(
                    message="gemini-cli process failed to start",
                    details={"stderr": stderr},
                )

            self._last_activity = asyncio.get_event_loop().time()
            if logger.isEnabledFor(logging.INFO):
                logger.info("gemini-cli ACP process started successfully")

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to spawn gemini-cli process: {e}")
            # Ensure process is cleaned up even if exception occurs before assignment
            if process is not None and process is not self._process:
                self._cleanup_process(process)
            await self._kill_process()
            raise APIConnectionError(
                message=f"Failed to start gemini-cli: {e}",
                details={"executable": self._gemini_cli_executable},
            )

    async def _kill_process(self) -> None:
        """Kill the gemini-cli process."""
        if self._process:
            process = self._process
            try:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("gemini-cli process terminated")
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error terminating gemini-cli process: {e}")
            finally:
                self._cleanup_process(process)

    def _cleanup_process(self, process: subprocess.Popen[bytes] | None = None) -> None:
        """Close process pipes and clear reference."""
        proc = process or self._process
        if not proc:
            return

        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, stream_name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception as stream_error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error closing gemini-cli %s stream: %s",
                        stream_name,
                        stream_error,
                    )

        if proc is self._process:
            self._process = None

    async def _send_jsonrpc_message(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC message to gemini-cli via stdin.

        Args:
            method: JSON-RPC method name
            params: Method parameters
        """
        if not self._process or not self._process.stdin:
            raise BackendError(message="gemini-cli process not running")

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._get_next_message_id(),
        }

        try:
            message_str = json.dumps(message) + "\n"
            self._process.stdin.write(message_str.encode("utf-8"))
            self._process.stdin.flush()
            self._last_activity = asyncio.get_event_loop().time()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Sent JSON-RPC message: {method}")
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to send JSON-RPC message: {e}")
            raise APIConnectionError(
                message=f"Failed to communicate with gemini-cli: {e}"
            )

    async def _read_jsonrpc_response(self) -> ACPResponse | None:
        """Read a JSON-RPC response from gemini-cli stdout.

        Returns:
            Parsed JSON-RPC response or None if stream ended
        """
        if not self._process or not self._process.stdout:
            raise BackendError(message="gemini-cli process not running")

        try:
            # Read line from stdout with size limit
            # Note: loop.run_in_executor with a simple file read doesn't support a limit argument directly
            # on the readline call in all executor contexts, but file.readline(limit) does.
            # However, run_in_executor runs a function.
            # We need to wrap the readline call to pass the limit.

            def _read_limited() -> bytes:
                if self._process and self._process.stdout:
                    # Use the module-level MAX_RESPONSE_LINE_SIZE
                    # Reading a single line larger than this will return a truncated line
                    # which will likely fail JSON parsing, safely rejecting the oversized payload.
                    return self._process.stdout.readline(MAX_RESPONSE_LINE_SIZE + 1)
                return b""

            loop = asyncio.get_event_loop()
            line = await loop.run_in_executor(None, _read_limited)

            if not line:
                return None  # Stream ended

            if len(line) > MAX_RESPONSE_LINE_SIZE:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Received oversize response line from gemini-cli ({len(line)} bytes). "
                        f"Limit is {MAX_RESPONSE_LINE_SIZE} bytes."
                    )
                # Consume the rest of the line to resync?
                # Actually, for security, better to terminate connection/process than consume unbounded data.
                # But here we just reject this message.
                raise BackendError(message="Response too large from gemini-cli")

            self._last_activity = loop.time()

            # Parse JSON
            data = json.loads(line.decode("utf-8"))
            response = ACPResponse(**data)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Received JSON-RPC response: {response.method or 'unknown'}"
                )
            return response

        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to parse JSON-RPC response: {e}")
            raise BackendError(
                message="Invalid JSON response from gemini-cli",
                details={"error": str(e)},
            )
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to read JSON-RPC response: {e}")
            raise APIConnectionError(message=f"Failed to read from gemini-cli: {e}")

    async def _initialize_agent(self) -> None:
        """Initialize the ACP agent with project directory settings."""
        # Send initialization message with AgentSettings
        await self._send_jsonrpc_message(
            "initialize",
            {
                "AgentSettings": {
                    "workspace_path": str(self._project_dir),
                }
            },
        )

    async def _process_streaming_response(
        self, effective_model: str
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Process streaming responses from gemini-cli.

        Args:
            effective_model: The model name being used

        Yields:
            ProcessedResponse objects with SSE chunks
        """
        chunk_id = str(uuid.uuid4())

        try:
            while True:
                response = await asyncio.wait_for(
                    self._read_jsonrpc_response(),
                    timeout=self._process_timeout,
                )

                if not response:
                    break  # Stream ended

                # Handle different response types
                if response.is_result:
                    # TaskStatusUpdateEvent
                    if isinstance(response.result, dict):
                        event = TaskStatusUpdateEvent(**response.result)
                    else:
                        # Fallback for simple results (e.g. in some tests)
                        event = TaskStatusUpdateEvent(Message=str(response.result))

                    message = event.Message

                    # Handle TextPart
                    if isinstance(message, str):
                        sse_chunk = self._create_sse_chunk(
                            message, effective_model, chunk_id
                        )
                        yield ProcessedResponse(content=sse_chunk)

                    # Handle DataPart or TextPart model
                    elif isinstance(message, TextPart | DataPart):

                        if isinstance(message, TextPart):
                            text = message.TextPart
                            sse_chunk = self._create_sse_chunk(
                                text, effective_model, chunk_id
                            )
                            yield ProcessedResponse(content=sse_chunk)

                        elif isinstance(message, DataPart):
                            # Handle tool calls or other structured data
                            if message.ToolCall:
                                tool_call = message.ToolCall
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(f"Tool call: {tool_call.tool_name}")
                                # For now, we don't expose tool calls directly
                                # They'll be reflected in the final response text

                    # Handle raw dict as fallback
                    elif isinstance(message, dict):
                        if "TextPart" in message:
                            text = message["TextPart"]
                            sse_chunk = self._create_sse_chunk(
                                text, effective_model, chunk_id
                            )
                            yield ProcessedResponse(content=sse_chunk)

                        elif "DataPart" in message:
                            data_part = message["DataPart"]
                            if "ToolCall" in data_part:
                                tc = data_part["ToolCall"]
                                tool_name = (
                                    tc.get("tool_name")
                                    if isinstance(tc, dict)
                                    else getattr(tc, "tool_name", "unknown")
                                )
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(f"Tool call: {tool_name}")

                elif response.error is not None:
                    err = response.error
                    raise BackendError(
                        message=f"gemini-cli error: {err.message}",
                        details=err.model_dump(),
                    )


        except asyncio.TimeoutError:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Timeout reading from gemini-cli")
            raise APITimeoutError(
                message="Timeout waiting for gemini-cli response",
                details={"timeout": self._process_timeout},
            )
        finally:
            # Send final chunk
            yield ProcessedResponse(content=self._create_sse_done_chunk())

    def _create_sse_chunk(self, text: str, model: str, chunk_id: str) -> str:
        """Create an SSE chunk in OpenAI format."""
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(asyncio.get_event_loop().time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": None,
                }
            ],
        }
        return f"data: {json.dumps(chunk)}\n\n"

    def _create_sse_done_chunk(self) -> str:
        """Create the final SSE chunk."""
        return "data: [DONE]\n\n"

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        """Process chat completion request via gemini-cli ACP.

        Args:
            request_data: The chat request
            processed_messages: List of messages
            effective_model: Model to use
            identity: Optional identity config
            **kwargs: Additional parameters

        Returns:
            Response envelope (streaming or non-streaming)
        """
        if not self.is_functional:
            raise ServiceUnavailableError(
                message="gemini-cli-acp backend not initialized",
                details={"initialization_failed": self._initialization_failed},
            )

        try:
            # Check if project directory was changed via session state
            project_dir_from_session = kwargs.get("project_dir") or kwargs.get(
                "project"
            )
            if project_dir_from_session and str(project_dir_from_session) != str(
                self._project_dir
            ):
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Project directory changed via session to: {project_dir_from_session}"
                    )
                await self.change_project_dir(project_dir_from_session)

            # Ensure process is running
            await self._spawn_gemini_cli_process()

            # Initialize agent on first use
            if self._message_id == 0:
                await self._initialize_agent()

            # Extract and convert user message to string for ACP protocol
            user_message = self._extract_user_message_as_string(processed_messages)

            if not user_message:
                raise BackendError(message="No user message found in request")

            # Send message to gemini-cli
            await self._send_jsonrpc_message(
                "sendMessage",
                {
                    "message": user_message,
                    "model": effective_model,
                },
            )

            # Check if streaming is requested
            stream = False
            if hasattr(request_data, "stream"):
                stream = request_data.stream
            elif isinstance(request_data, dict):
                stream = request_data.get("stream", False)

            if stream:
                # Return streaming response
                return StreamingResponseEnvelope(
                    content=self._process_streaming_response(effective_model),
                    media_type="text/event-stream",
                    headers={},
                )
            else:
                # Collect all chunks for non-streaming response
                full_response = ""
                async for processed_chunk in self._process_streaming_response(
                    effective_model
                ):
                    chunk = processed_chunk.content
                    if (
                        isinstance(chunk, str)
                        and chunk.startswith("data: ")
                        and not chunk.startswith("data: [DONE]")
                    ):
                        chunk_data = json.loads(chunk[6:])
                        content = chunk_data["choices"][0]["delta"].get("content", "")
                        full_response += content

                # Create response
                canonical_response = CanonicalChatResponse(
                    id=str(uuid.uuid4()),
                    object="chat.completion",
                    created=int(asyncio.get_event_loop().time()),
                    model=effective_model,
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant",
                                content=full_response,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=UsageSummary.from_dict(
                        {
                            "prompt_tokens": self._estimate_tokens(user_message),
                            "completion_tokens": self._estimate_tokens(full_response),
                            "total_tokens": self._estimate_tokens(
                                user_message + full_response
                            ),
                        }
                    ),
                )

                response_envelope = ResponseEnvelope(
                    content=canonical_response,
                    headers={},
                    status_code=200,
                )

                # Ensure usage is calculated (CLI doesn't provide usage)
                return self.ensure_usage_in_response(
                    response_envelope, processed_messages, effective_model
                )

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error in gemini-cli-acp chat_completions: {e}")
            # Kill process on error to force restart
            await self._kill_process()
            raise

    def _extract_user_message_as_string(self, processed_messages: list[Any]) -> str:
        """Extract and convert user messages to string for ACP protocol.

        ACP protocol requires simple string prompts, not structured message objects.
        This method handles various message formats and converts them to strings.
        Only the last user message is used as the remote agent handles context.

        Args:
            processed_messages: List of messages in various formats

        Returns:
            String representation of the last user message
        """
        last_user_message = ""

        for msg in processed_messages:
            # Handle different message formats
            content = ""
            role = ""

            if isinstance(msg, dict):
                # Standard message format
                role = msg.get("role", "")
                content = msg.get("content", "")

                # Handle nested content structures
                if not content and "parts" in msg:
                    # Handle multi-part messages (like from translation service)
                    parts = msg["parts"]
                    if isinstance(parts, list):
                        content_parts = []
                        for part in parts:
                            if isinstance(part, dict):
                                if "text" in part:
                                    content_parts.append(part["text"])
                                elif "content" in part:
                                    content_parts.append(part["content"])
                            elif isinstance(part, str):
                                content_parts.append(part)
                        content = " ".join(content_parts)

                # Handle content as list
                if isinstance(content, list):
                    content_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if "text" in item:
                                content_parts.append(item["text"])
                            elif "content" in item:
                                content_parts.append(item["content"])
                        elif isinstance(item, str):
                            content_parts.append(item)
                    content = " ".join(content_parts)

                # Convert content to string if it's not already
                if not isinstance(content, str):
                    try:
                        content = str(content)
                    except Exception:
                        content = ""

            elif isinstance(msg, str):
                # Simple string message
                content = msg
                role = "user"

            elif hasattr(msg, "content"):
                # Message object with content attribute
                content = getattr(msg, "content", "")
                if hasattr(msg, "role"):
                    role = getattr(msg, "role", "")
                if not isinstance(content, str):
                    try:
                        content = str(content)
                    except Exception:
                        content = ""

            # Only process user messages
            if role == "user" and content:
                last_user_message = content

        return last_user_message

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            # Fallback: rough estimate
            return len(text.split()) * 2

    def get_available_models(self) -> list[str]:
        """Get list of available models with vendor prefix.

        Returns:
            List of model identifiers with 'google/' vendor prefix.
            For example: ['google/gemini-2.5-flash', 'google/gemini-2.5-pro']
        """
        raw_models = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]
        return [add_vendor_prefix(m, self.VENDOR_PREFIX) for m in raw_models]

    async def shutdown(self) -> None:
        """Release resources owned by the connector."""
        for future in list(self._pending_responses.values()):
            if not future.done():
                future.cancel()
        self._pending_responses.clear()
        await self._kill_process()

    def __del__(self) -> None:
        """Cleanup subprocess on destruction.

        This ensures that if GeminiCliAcpConnector is destroyed without
        shutdown() being called (e.g., during application crash or abrupt exit),
        the subprocess is still terminated to prevent resource leaks.

        Note: This is a best-effort cleanup since __del__ cannot be async.
        The proper cleanup path is via shutdown() which should be called
        by BackendLifecycleManager during application shutdown.
        """
        # Guard against partial initialization
        if hasattr(self, "_process"):
            process = self._process
            if process is not None:
                try:
                    # Check if process is still running
                    if process.poll() is None:
                        # Process is still running, terminate it synchronously
                        # We can't await in __del__, so we do best-effort cleanup
                        try:
                            process.terminate()
                            # Wait with timeout (synchronous)
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                # Process didn't terminate, force kill
                                process.kill()
                                with contextlib.suppress(
                                    subprocess.TimeoutExpired, Exception
                                ):
                                    process.wait(timeout=5)
                        except Exception:
                            # Suppress all exceptions during interpreter shutdown
                            # The logging system may already be torn down
                            pass

                    # Clean up process pipes
                    self._cleanup_process(process)
                except Exception:
                    # Suppress all exceptions during interpreter shutdown
                    pass
                finally:
                    # Clear reference to prevent leaks
                    self._process = None

    async def __aenter__(self) -> "GeminiCliAcpConnector":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - cleanup process."""
        _ = exc_type, exc_val, exc_tb  # Unused but required by protocol
        await self._kill_process()


# Register the backend
backend_registry.register_backend("gemini-cli-acp", GeminiCliAcpConnector)
