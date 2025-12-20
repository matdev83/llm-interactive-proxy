"""Service interfaces for OpenAI Codex connector.

This module defines abstract interfaces for connector components following
the dependency inversion principle. All interfaces extend ABC and document
preconditions and postconditions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexConnectorSettings,
    CodexInputItem,
    CodexPayload,
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityResult,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolArguments,
    ToolCall,
    ToolExecutionResult,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class ISettingsLoader(ABC):
    """Interface for loading and normalizing connector settings.

    Preconditions:
    - app_config is validated by core config loader

    Postconditions:
    - Settings include defaults and environment overrides
    - Normalized types are applied
    """

    @abstractmethod
    def load(self, app_config: AppConfig) -> CodexConnectorSettings:
        """Return normalized settings for the connector.

        Args:
            app_config: Application configuration

        Returns:
            Normalized connector settings with defaults and overrides applied
        """
        ...


class ICredentialManager(ABC):
    """Interface for managing credential lifecycle and concurrency.

    Preconditions:
    - initialize called once per connector lifecycle

    Postconditions:
    - Refresh never leaves credentials in a partially written state
    - Shutdown ensures watcher is stopped and is_watcher_running() returns False
    """

    @abstractmethod
    async def initialize(self, auth_path: Path | None) -> None:
        """Load initial credentials and start watcher.

        Args:
            auth_path: Optional path to auth.json file
        """
        ...

    @abstractmethod
    async def refresh_access_token(self) -> bool:
        """Refresh the access token in a concurrency-safe manner.

        Returns:
            True if refresh succeeded, False otherwise
        """
        ...

    @abstractmethod
    def get_access_token(self) -> str | None:
        """Return current access token if available.

        Returns:
            Access token string or None if not available
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Stop the file watcher and release resources.

        This method ensures clean shutdown by:
        - Stopping the credential file watcher
        - Cancelling any pending reload tasks
        - Releasing concurrency locks

        Safe to call multiple times; subsequent calls are no-ops.
        """
        ...

    @abstractmethod
    def is_watcher_running(self) -> bool:
        """Return True if the credential file watcher is active.

        Returns:
            True if watcher is running, False otherwise
        """
        ...


class IPayloadBuilder(ABC):
    """Interface for building Codex payloads.

    Preconditions:
    - CodexRequestContext contains resolved model and messages

    Postconditions:
    - Payload is compatible with Codex Responses API
    - Passthrough rules are preserved
    """

    @abstractmethod
    def build_payload(self, context: CodexRequestContext) -> CodexPayload:
        """Build a Codex payload preserving passthrough rules.

        Args:
            context: Request context with processed messages and capabilities

        Returns:
            Codex API payload ready for submission
        """
        ...


class IRequestTranslator(ABC):
    """Interface for translating canonical requests to Codex format.

    Preconditions:
    - Messages are pre-processed and validated

    Postconditions:
    - Output items match current Codex input schema
    - Parameter transformation semantics are preserved
    """

    @abstractmethod
    def translate_messages(
        self,
        messages: list[ProcessedMessage],
        context: CodexRequestContext | None = None,
    ) -> list[CodexInputItem]:
        """Convert processed messages to Codex input items.

        Args:
            messages: List of processed messages
            context: Optional request context for environment context and capabilities

        Returns:
            List of Codex input items
        """
        ...

    @abstractmethod
    def translate_tool_calls(self, tool_calls: list[ToolCall]) -> list[CodexInputItem]:
        """Convert tool calls to Codex function_call input items.

        Args:
            tool_calls: List of tool calls

        Returns:
            List of Codex input items representing function calls
        """
        ...


class IPromptResolver(ABC):
    """Interface for resolving and sanitizing system prompts.

    Preconditions:
    - Settings and capabilities are validated

    Postconditions:
    - Prompt content is sanitized and ready for API submission
    """

    @abstractmethod
    def resolve_system_prompt(
        self,
        settings: CodexConnectorSettings,
        capabilities: CodexClientCapabilities,
    ) -> str:
        """Return the resolved system prompt for the request.

        Args:
            settings: Connector settings
            capabilities: Client capabilities

        Returns:
            Resolved and sanitized system prompt
        """
        ...

    @abstractmethod
    def resolve_instructions(
        self,
        settings: CodexConnectorSettings,
        user_instructions: str | None,
    ) -> str | None:
        """Return merged instructions or None if not applicable.

        Args:
            settings: Connector settings
            user_instructions: Optional user-provided instructions

        Returns:
            Merged instructions or None
        """
        ...


class IToolSchemaResolver(ABC):
    """Interface for resolving tool schemas and handling collisions.

    Preconditions:
    - Request context contains tool definitions

    Postconditions:
    - Tool schemas are merged with collision handling
    - Output matches current tool schema merge behavior
    """

    @abstractmethod
    def resolve_tool_schema(
        self, context: CodexRequestContext
    ) -> list[CodexToolSchema]:
        """Resolve tool schemas and handle collisions.

        Args:
            context: Request context

        Returns:
            List of resolved tool schemas
        """
        ...


class IResponseExecutor(ABC):
    """Interface for executing Codex API requests with retry.

    Preconditions:
    - Payload and headers are already validated

    Postconditions:
    - Error shapes and statuses match current behavior
    - Streaming retry behavior is preserved
    """

    @abstractmethod
    async def execute(
        self, payload: CodexPayload, context: CodexRequestContext
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute Codex request with retry and compatibility handling.

        Args:
            payload: Codex API payload
            context: Request context

        Returns:
            Response envelope (streaming or non-streaming)
        """
        ...


class ICompatibilityLayer(ABC):
    """Interface for handling KiloCode and Droid compatibility flows.

    Preconditions:
    - Request context has processed messages

    Postconditions:
    - Tool translations and results match current behavior
    - Cleanup ensures state resources are released
    """

    @abstractmethod
    async def apply(self, context: CodexRequestContext) -> CompatibilityResult:
        """Detect and translate compatibility tool calls.

        Args:
            context: Request context

        Returns:
            Compatibility result with tool lists and state
        """
        ...

    @abstractmethod
    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        """Apply streaming tool-call translations with owned state.

        Args:
            chunk: Provider stream chunk
            state: Per-request compatibility state

        Returns:
            Translated stream chunk
        """
        ...

    @abstractmethod
    async def cleanup_state(self, state: CompatibilityState) -> None:
        """Release per-request state after streaming completes or on error.

        This method MUST be called after streaming ends (success or failure) to:
        - Clear tool-call caches and translation buffers
        - Release any pending tool-call references
        - Reset detection flags

        The state object should not be reused after cleanup.

        Args:
            state: Compatibility state to clean up
        """
        ...

    @abstractmethod
    def create_state(self) -> CompatibilityState:
        """Create a new per-request compatibility state instance.

        Returns a fresh state object for tracking compatibility flows
        during a single request lifecycle.

        Returns:
            New compatibility state instance
        """
        ...


class IToolExecutionService(ABC):
    """Interface for executing proxy and MCP tools.

    Preconditions:
    - Tool name and arguments are validated

    Postconditions:
    - Tool results are formatted consistently
    - Error reporting matches current behavior
    """

    @abstractmethod
    async def execute_proxy_tool(
        self, tool_name: str, arguments: ToolArguments, session_id: str | None = None
    ) -> ToolExecutionResult:
        """Execute a proxy tool and return formatted result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            session_id: Optional session ID for telemetry and conversation control

        Returns:
            Tool execution result with success/error status
        """
        ...

    @abstractmethod
    async def execute_mcp_tool(
        self, tool_name: str, arguments: ToolArguments, session_id: str | None = None
    ) -> ToolExecutionResult:
        """Execute an MCP tool and return formatted result.

        Args:
            tool_name: Name of the MCP tool to execute
            arguments: Tool arguments
            session_id: Optional session ID for telemetry

        Returns:
            Tool execution result with success/error status
        """
        ...

    @abstractmethod
    def get_available_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all available tools (proxy + MCP).

        Returns:
            List of tool schema dictionaries
        """
        ...

    @abstractmethod
    async def connect_mcp_server(
        self, server_name: str, server_config: dict[str, Any]
    ) -> bool:
        """Connect to an MCP server to make its tools available.

        Args:
            server_name: Unique name for the server
            server_config: Server configuration

        Returns:
            True if connection successful, False otherwise
        """
        ...
