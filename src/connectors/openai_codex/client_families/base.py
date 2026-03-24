"""Base contracts for Codex client-family compatibility adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityState,
    ProviderStreamChunk,
    ToolExecutionResult,
)


@dataclass(slots=True)
class FamilyApplyResult:
    """Result emitted by a client-family adapter during apply phase."""

    codex_tools: list[CodexToolSchema] = field(default_factory=list)
    proxy_tools: list[CodexToolSchema] = field(default_factory=list)
    mcp_tools: list[CodexToolSchema] = field(default_factory=list)
    tool_results: list[ToolExecutionResult] = field(default_factory=list)


class IClientFamilyAdapter(Protocol):
    """Adapter contract for client-family specific compatibility behavior."""

    family: str

    async def detect(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> None:
        """Populate family-specific flags on compatibility state."""
        ...

    async def apply(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> FamilyApplyResult:
        """Apply family-specific request translation and tool execution."""
        ...

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        """Translate streaming chunks for this family when needed."""
        ...

    async def cleanup_state(self, state: CompatibilityState) -> None:
        """Cleanup family-specific state."""
        ...

    def adapt_payload_dict(
        self,
        payload_dict: dict[str, object],
        context: CodexRequestContext,
        *,
        resolved_instructions: str | None = None,
    ) -> dict[str, object]:
        """Adapt a Codex payload dictionary for this family."""
        ...

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        """Return incompatible tool names that should be rejected server-side."""
        ...

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        """Append steering for incompatible tool calls to a retry payload."""
        ...
