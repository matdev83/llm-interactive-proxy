"""Contracts for resolving tool identity metadata for compression."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from src.core.domain.chat import ChatMessage
from src.core.domain.dynamic_compression import ToolOutputContext


class IToolIdentityResolver(Protocol):
    """Resolver contract for tool output identity extraction."""

    def build_tool_call_lookup(
        self,
        messages: Sequence[ChatMessage],
    ) -> dict[str, tuple[str, str | dict[str, Any] | None]]:
        """Build lookup map from tool call ID to tool metadata."""
        ...

    def resolve_tool_output(
        self,
        *,
        messages: Sequence[ChatMessage],
        tool_message: ChatMessage,
        explicit_format_flags: Sequence[str] | None = None,
    ) -> ToolOutputContext | None:
        """Resolve rich output context for a tool message."""
        ...
