"""Interface for dynamic tool-output compression service."""

from __future__ import annotations

from typing import Protocol

from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.dynamic_compression_config import (
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputCompressionBatchResult


class IToolOutputCompressionService(Protocol):
    """Compression orchestrator contract."""

    async def compress_messages(
        self,
        *,
        messages: list[ChatMessage],
        config: DynamicCompressionConfig,
        target_token_budget: int | None = None,
    ) -> ToolOutputCompressionBatchResult:
        """Compress eligible tool messages and return batch diagnostics."""
        ...
