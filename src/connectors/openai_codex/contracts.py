"""Contract models for OpenAI Codex connector.

This module defines internal contract models used for type-safe communication
between connector components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.core.domain.chat import CanonicalChatRequest, ToolCall

# Re-export CanonicalChatRequest for convenience
__all__ = [
    "CanonicalChatRequest",
    "CodexClientCapabilities",
    "CodexConnectorDependencies",
    "CodexConnectorSettings",
    "CodexInitOptions",
    "CodexInputItem",
    "CodexPayload",
    "CodexRequestContext",
    "CodexToolSchema",
    "CompatibilityResult",
    "CompatibilityState",
    "MessagePart",
    "PendingToolCall",
    "ProcessedMessage",
    "ProviderStreamChunk",
    "ReasoningSpec",
    "ToolArguments",
    "ToolCall",
    "ToolExecutionResult",
]

# Supporting Structures


class ProcessedMessage(BaseModel):
    """Processed message with role, content, tool calls, and metadata.

    This represents a message that has been processed and is ready for
    translation to Codex format.
    """

    role: str
    content: str | list[MessagePart]
    tool_calls: list[ToolCall] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, object] | None = None


class MessagePart(BaseModel):
    """Content part in a multimodal message."""

    type: str
    text: str | None = None
    data: object | None = None


ProcessedMessage.model_rebuild()


class CodexInputItem(BaseModel):
    """Codex API input item.

    Discriminated union for Codex Responses API input items.
    """

    model_config = ConfigDict(extra="allow")
    type: str
    content: object | None = None


class CodexToolSchema(BaseModel):
    """Tool schema structure for Codex API."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    # Matches Codex CLI ToolSpec JSON: `type=function` tools have `parameters`,
    # but `type=custom` (freeform grammar tools) do not.
    parameters: dict[str, object] | None = None
    type: str = "function"
    format: dict[str, Any] | None = None


class ToolArguments(BaseModel):
    """Tool arguments payload."""

    payload: dict[str, object]


class ToolExecutionResult(BaseModel):
    """Tool execution result with success/error status."""

    success: bool
    result: str
    error: str | None = None
    metadata: dict[str, object] | None = None


class ProviderStreamChunk(BaseModel):
    """Wrapper for provider-specific streaming chunks."""

    raw: object


class PendingToolCall(BaseModel):
    """Pending tool call tracking."""

    id: str
    name: str
    command_text: str


class ReasoningSpec(BaseModel):
    """Reasoning specification for Codex API."""

    effort: str = "medium"
    summary: str = "auto"


# Core Contract Models


class CodexConnectorSettings(BaseModel):
    """Normalized connector settings with defaults and env overrides."""

    default_capabilities: CodexClientCapabilities
    agent_overrides: dict[str, dict[str, Any]]
    prompt: dict[str, Any]
    tool_schema: dict[str, Any]
    streaming: dict[str, Any]
    compatibility_layer: dict[str, Any]
    renderer: dict[str, Any]
    websocket: dict[str, Any] = {"enabled": False, "beta_mode": "v1"}
    managed_oauth: dict[str, Any] = Field(default_factory=dict)
    gpt55_unsupported_free_plan_downgrade: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "proactive_enabled": True,
            "reactive_enabled": True,
            "source_model": "gpt-5.5",
            "target_model": "gpt-5.4",
            "free_plan_types": ["free"],
        }
    )


class CodexInitOptions(BaseModel):
    """Normalized initialization options from legacy kwargs."""

    openai_codex_path: str | None = None
    openai_api_base_url: str | None = None
    backend_extras: dict[str, object] | None = None


class CodexRequestContext(BaseModel):
    """Request context with processed messages and capabilities.

    Invariants:
    - session_id must be present and non-empty
    - effective_model must be stripped of vendor prefix
    """

    request: CanonicalChatRequest
    processed_messages: list[ProcessedMessage]
    effective_model: str
    capabilities: CodexClientCapabilities
    session_id: str
    metadata: dict[str, object] | None = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        """Ensure session_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("session_id must be present and non-empty")
        return v.strip()

    @field_validator("effective_model")
    @classmethod
    def validate_effective_model(cls, v: str) -> str:
        """Ensure effective_model is stripped of vendor prefix."""
        # Remove vendor prefix if present (e.g., "openai-codex:gpt-5.1-codex" -> "gpt-5.1-codex")
        if ":" in v:
            v = v.split(":", 1)[1]
        return v


class CodexPayload(BaseModel):
    """Codex API payload structure.

    Serialized payload matches current behavior and passthrough rules.
    """

    model: str
    input: list[CodexInputItem]
    tools: list[CodexToolSchema]
    tool_choice: str
    parallel_tool_calls: bool
    reasoning: ReasoningSpec | None = None
    store: bool
    stream: bool
    include: list[str]
    prompt_cache_key: str
    previous_response_id: str | None = None
    instructions: str | None = None
    extras: dict[str, object] | None = None


class CompatibilityState(BaseModel):
    """Per-request compatibility state.

    State is per-request and must be cleared after stream ends.
    """

    droid_tool_name_cache: dict[str, str] = Field(default_factory=dict)
    droid_tool_args_buffer: dict[str, str] = Field(default_factory=dict)
    pending_tool_calls: list[PendingToolCall] = Field(default_factory=list)
    is_kilocode: bool = False
    is_droid: bool = False


class CompatibilityResult(BaseModel):
    """Tool lists and results for compatibility flows.

    Tool lists and results aligned with current compatibility behavior.
    """

    codex_tools: list[CodexToolSchema]
    proxy_tools: list[CodexToolSchema]
    mcp_tools: list[CodexToolSchema]
    tool_results: list[ToolExecutionResult]
    state: CompatibilityState


@dataclass
class CodexConnectorDependencies:
    """Optional component overrides bundle for dependency injection.

    All fields optional; defaults resolved by factory.
    """

    settings_loader: Any | None = None
    credential_manager: Any | None = None
    payload_builder: Any | None = None
    response_executor: Any | None = None
    compatibility_layer: Any | None = None
    tool_execution_service: Any | None = None
