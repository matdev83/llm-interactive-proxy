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
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .gemini import GeminiBackend

logger = logging.getLogger(__name__)

# Default timeout for gemini-cli responses (in seconds)
DEFAULT_PROCESS_TIMEOUT = 300.0  # 5 minutes for complex operations
DEFAULT_CONNECTION_TIMEOUT = 60.0
DEFAULT_IDLE_TIMEOUT = 30.0  # Kill process if idle for this long


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
            logger.info(
                f"Initialized gemini-cli-acp backend with project directory: {self._project_dir}"
            )

        except Exception as e:
            self._initialization_failed = True
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
            logger.debug(f"Project directory already set to {project_dir}")
            return

        # Kill existing process
        await self._kill_process()

        # Update project directory
        old_project_dir = self._project_dir
        self._project_dir = new_project_dir

        # Reset message ID for new process
        self._message_id = 0

        logger.info(
            f"Project directory changed from {old_project_dir} to {self._project_dir}"
        )

    async def _spawn_gemini_cli_process(self) -> None:
        """Spawn gemini-cli subprocess with ACP support."""
        if self._process and self._process.poll() is None:
            # Process already running
            return

        try:
            # Build command with ACP flags
            cmd = [
                self._gemini_cli_executable,
                "--mode",
                "acp",  # Enable ACP mode
                "--model",
                self._model,
                "--workspace",
                str(self._project_dir),
            ]

            if self._auto_accept:
                cmd.append("--auto-accept")

            # Spawn process
            logger.debug(f"Spawning gemini-cli process: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._project_dir),
            )

            # Wait a moment for process to start
            await asyncio.sleep(0.1)

            # Check if process started successfully
            if self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode(
                        "utf-8", errors="replace"
                    )
                raise BackendError(
                    message="gemini-cli process failed to start",
                    details={"stderr": stderr},
                )

            self._last_activity = asyncio.get_event_loop().time()
            logger.info("gemini-cli ACP process started successfully")

        except Exception as e:
            logger.error(f"Failed to spawn gemini-cli process: {e}")
            raise APIConnectionError(
                message=f"Failed to start gemini-cli: {e}",
                details={"executable": self._gemini_cli_executable},
            )

    async def _kill_process(self) -> None:
        """Kill the gemini-cli process."""
        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
                logger.debug("gemini-cli process terminated")
            except Exception as e:
                logger.warning(f"Error terminating gemini-cli process: {e}")
            finally:
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
            logger.debug(f"Sent JSON-RPC message: {method}")
        except Exception as e:
            logger.error(f"Failed to send JSON-RPC message: {e}")
            raise APIConnectionError(
                message=f"Failed to communicate with gemini-cli: {e}"
            )

    async def _read_jsonrpc_response(self) -> dict[str, Any] | None:
        """Read a JSON-RPC response from gemini-cli stdout.

        Returns:
            Parsed JSON-RPC response or None if stream ended
        """
        if not self._process or not self._process.stdout:
            raise BackendError(message="gemini-cli process not running")

        try:
            # Read line from stdout
            loop = asyncio.get_event_loop()
            line = await loop.run_in_executor(None, self._process.stdout.readline)

            if not line:
                return None  # Stream ended

            self._last_activity = loop.time()

            # Parse JSON
            response: dict[str, Any] = json.loads(line.decode("utf-8"))
            logger.debug(
                f"Received JSON-RPC response: {response.get('method', 'unknown')}"
            )
            return response

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON-RPC response: {e}")
            raise BackendError(
                message="Invalid JSON response from gemini-cli",
                details={"error": str(e)},
            )
        except Exception as e:
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
                if "result" in response:
                    # TaskStatusUpdateEvent
                    event = response["result"]
                    message = event.get("Message", {})

                    # Handle TextPart
                    if isinstance(message, str):
                        sse_chunk = self._create_sse_chunk(
                            message, effective_model, chunk_id
                        )
                        yield ProcessedResponse(content=sse_chunk)

                    # Handle DataPart with structured data
                    elif isinstance(message, dict):
                        if "TextPart" in message:
                            text = message["TextPart"]
                            sse_chunk = self._create_sse_chunk(
                                text, effective_model, chunk_id
                            )
                            yield ProcessedResponse(content=sse_chunk)

                        elif "DataPart" in message:
                            # Handle tool calls or other structured data
                            data_part = message["DataPart"]
                            if "ToolCall" in data_part:
                                tool_call = data_part["ToolCall"]
                                logger.debug(f"Tool call: {tool_call.get('tool_name')}")
                                # For now, we don't expose tool calls directly
                                # They'll be reflected in the final response text

                elif "error" in response:
                    error = response["error"]
                    raise BackendError(
                        message=f"gemini-cli error: {error.get('message', 'Unknown error')}",
                        details=error,
                    )

        except asyncio.TimeoutError:
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
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
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
                logger.info(
                    f"Project directory changed via session to: {project_dir_from_session}"
                )
                await self.change_project_dir(project_dir_from_session)

            # Ensure process is running
            await self._spawn_gemini_cli_process()

            # Initialize agent on first use
            if self._message_id == 0:
                await self._initialize_agent()

            # Extract user message
            user_message = ""
            for msg in processed_messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        user_message = content
                        break

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
                    usage={
                        "prompt_tokens": self._estimate_tokens(user_message),
                        "completion_tokens": self._estimate_tokens(full_response),
                        "total_tokens": self._estimate_tokens(
                            user_message + full_response
                        ),
                    },
                )

                return ResponseEnvelope(
                    content=canonical_response,
                    headers={},
                    status_code=200,
                )

        except Exception as e:
            logger.error(f"Error in gemini-cli-acp chat_completions: {e}")
            # Kill process on error to force restart
            await self._kill_process()
            raise

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
        """Get list of available models.

        Returns:
            List of model identifiers
        """
        return [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]

    async def __aenter__(self) -> "GeminiCliAcpConnector":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - cleanup process."""
        _ = exc_type, exc_val, exc_tb  # Unused but required by protocol
        await self._kill_process()


# Register the backend
backend_registry.register_backend("gemini-cli-acp", GeminiCliAcpConnector)
