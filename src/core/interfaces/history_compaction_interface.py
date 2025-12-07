"""
Interface for history compaction service.

This module defines the contract for the context compaction feature that
trims stale tool outputs from message histories before LLM backend dispatch.

Requirements covered:
- 1.1-1.5: Staleness detection
- 2.1-2.5: Stub replacement
- 3.1-3.5: Token budget governance
- 4.1-4.5: Observability and fail-open
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    CompactionPolicies,
)


@dataclass
class CompactionResult:
    """Result of a compaction operation.

    Contains the compacted messages and metadata about what was done.

    Attributes:
        messages: The resulting message list (may be same as input if no compaction)
        compacted_count: Number of messages that were compacted
        bytes_saved: Approximate bytes reduced by compaction
        tokens_saved_estimate: Estimated tokens reduced (approximate)
        original_message_count: Number of messages before compaction
        stale_resources: Set of resource identities that were detected as stale
        error: If fail-open was triggered, contains the error information
    """

    messages: list[ChatMessage]
    compacted_count: int = 0
    bytes_saved: int = 0
    tokens_saved_estimate: int = 0
    original_message_count: int = 0
    stale_resources: set[str] = field(default_factory=set)
    error: str | None = None

    @property
    def was_compacted(self) -> bool:
        """Returns True if any compaction occurred."""
        return self.compacted_count > 0

    @property
    def failed_open(self) -> bool:
        """Returns True if compaction failed and returned original messages."""
        return self.error is not None

    def to_metrics(self) -> dict[str, int | float]:
        """Convert result to metrics dictionary for observability (Req 4.1).

        Returns metrics suitable for Prometheus/CloudWatch/etc.
        Does not include any message content.
        """
        return {
            "compaction_messages_compacted": self.compacted_count,
            "compaction_bytes_saved": self.bytes_saved,
            "compaction_tokens_saved_estimate": self.tokens_saved_estimate,
            "compaction_original_count": self.original_message_count,
            "compaction_stale_resources_count": len(self.stale_resources),
            "compaction_failed_open": 1 if self.failed_open else 0,
        }

    def to_log_context(self) -> dict[str, str | int | bool]:
        """Convert result to structured log context (Req 4.2, 4.3).

        Returns a dictionary suitable for structured logging.
        Resource identities are included but not removed content (Req 4.5).
        """
        context: dict[str, str | int | bool] = {
            "compacted_count": self.compacted_count,
            "bytes_saved": self.bytes_saved,
            "tokens_saved_estimate": self.tokens_saved_estimate,
            "original_message_count": self.original_message_count,
            "was_compacted": self.was_compacted,
            "failed_open": self.failed_open,
        }
        if self.stale_resources:
            # Limit to first 10 resources to avoid log bloat
            resources_list = list(self.stale_resources)[:10]
            context["stale_resources"] = ",".join(resources_list)
            if len(self.stale_resources) > 10:
                context["stale_resources_truncated"] = True
        if self.error:
            context["error"] = self.error
        return context


class IHistoryCompactionService(ABC):
    """Interface for context compaction service.

    Processes chat message histories to detect and replace stale tool outputs
    with explicit stubs, reducing prompt size while preserving conversational
    integrity and transparency about removed content.

    Design principles:
    - Single responsibility: Only handles history compaction logic
    - Fail-open: On errors, returns original messages with logging
    - Observability: Provides compaction metrics for monitoring
    """

    @abstractmethod
    async def compact_history(
        self,
        messages: list[ChatMessage],
        config: CompactionConfig,
        current_token_estimate: int | None = None,
    ) -> CompactionResult:
        """Compact stale tool outputs in message history.

        Traverses the message history to detect stale tool results
        (older outputs for the same resource when newer outputs exist),
        and replaces them with explicit stubs.

        Args:
            messages: The chat message history to compact
            config: Compaction configuration (thresholds, policies)
            current_token_estimate: Optional current token estimate to
                trigger threshold-based compaction

        Returns:
            CompactionResult containing the (possibly compacted) messages
            and metrics about the operation.

        Invariants:
            - Message order is preserved
            - Latest tool result per resource is never compacted
            - Messages without identifiable resources are preserved
            - On any error, original messages are returned (fail-open)
        """

    @abstractmethod
    async def compact_with_policies(
        self,
        messages: list[ChatMessage],
        policies: CompactionPolicies,
        current_token_estimate: int | None = None,
    ) -> CompactionResult:
        """Compact history with explicit policies.

        Same as compact_history but accepts pre-evaluated policies
        for more granular control over tool-level allow/deny.

        Args:
            messages: The chat message history to compact
            policies: Pre-evaluated compaction policies
            current_token_estimate: Optional current token estimate

        Returns:
            CompactionResult with compaction details
        """

    @abstractmethod
    def should_compact(
        self,
        messages: list[ChatMessage],
        config: CompactionConfig,
        current_token_estimate: int | None = None,
    ) -> bool:
        """Check if compaction should be triggered.

        Quick check without performing actual compaction.
        Used for conditional compaction in request pipeline.

        Args:
            messages: The message history
            config: Compaction configuration
            current_token_estimate: Current token estimate

        Returns:
            True if compaction should be performed
        """
