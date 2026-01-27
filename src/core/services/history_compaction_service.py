"""
History compaction service implementation.

This module provides the implementation of the history compaction interface
that detects and replaces stale tool outputs in message histories.

Requirements covered:
- 1.1-1.5: Staleness detection by resource identity
- 2.1-2.5: Stub replacement with transparency
- 3.1-3.5: Token budget governance
- 4.1-4.5: Observability, fail-open, redaction
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.chat import ChatMessage
from src.core.domain.compaction import (
    CompactionStub,
    ResourceIdentity,
    ResourceIdentityExtractor,
    categorize_tool,
    is_tool_result_message,
)
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    CompactionPolicies,
    TokenBudgetConfig,
)
from src.core.interfaces.history_compaction_interface import (
    CompactionResult,
    IHistoryCompactionService,
)

logger = logging.getLogger(__name__)


class HistoryCompactionService(IHistoryCompactionService):
    """Implementation of the history compaction service.

    Performs single-pass compaction of stale tool outputs by correlating
    messages by resource identity and replacing older results with stubs.

    Design:
    - Single-pass correlation using hashmap for O(n) complexity
    - Immutable message handling - creates new messages for stubs
    - Fail-open behavior with comprehensive error logging
    """

    def __init__(self) -> None:
        """Initialize the compaction service."""
        self._extractor = ResourceIdentityExtractor()

    async def compact_history(
        self,
        messages: list[ChatMessage],
        config: CompactionConfig,
        current_token_estimate: int | None = None,
    ) -> CompactionResult:
        """Compact stale tool outputs in message history.

        See IHistoryCompactionService.compact_history for full documentation.
        """
        # Quick exit checks
        if not config.enabled:
            logger.debug("Compaction disabled - returning original messages")
            return CompactionResult(
                messages=messages,
                original_message_count=len(messages),
            )

        if not messages:
            return CompactionResult(messages=[], original_message_count=0)

        # Check token budget threshold
        if current_token_estimate is not None:
            budget = TokenBudgetConfig.from_config(config, current_token_estimate)
            if not budget.needs_compaction:
                logger.debug(
                    "Token estimate %d below threshold %d - skipping compaction",
                    current_token_estimate,
                    config.token_threshold,
                )
                return CompactionResult(
                    messages=messages,
                    original_message_count=len(messages),
                )

        # Build policies and perform compaction
        policies = CompactionPolicies.from_config(config)
        return await self.compact_with_policies(
            messages, policies, current_token_estimate
        )

    async def compact_with_policies(
        self,
        messages: list[ChatMessage],
        policies: CompactionPolicies,
        current_token_estimate: int | None = None,
    ) -> CompactionResult:
        """Compact history with explicit policies.

        See IHistoryCompactionService.compact_with_policies for full documentation.
        """
        if not policies.config.enabled:
            return CompactionResult(
                messages=messages,
                original_message_count=len(messages),
            )

        try:
            return await self._perform_compaction(messages, policies)
        except Exception as exc:
            # Fail-open: log error and return original messages (Req 4.4)
            logger.error(
                "Compaction failed - returning original messages (fail-open)",
                exc_info=True,
            )
            return CompactionResult(
                messages=messages,
                original_message_count=len(messages),
                error=str(exc),
            )

    def should_compact(
        self,
        messages: list[ChatMessage],
        config: CompactionConfig,
        current_token_estimate: int | None = None,
    ) -> bool:
        """Check if compaction should be triggered."""
        if not config.enabled:
            return False

        if not messages:
            return False

        # Token budget check
        if current_token_estimate is not None:
            budget = TokenBudgetConfig.from_config(config, current_token_estimate)
            if not budget.needs_compaction:
                return False

        # Quick scan for tool messages - potential compaction candidates
        tool_message_count = sum(
            1 for msg in messages if is_tool_result_message(msg.role, msg.tool_call_id)
        )

        # Need at least 2 tool messages to potentially have staleness
        return tool_message_count >= 2

    async def _perform_compaction(
        self,
        messages: list[ChatMessage],
        policies: CompactionPolicies,
    ) -> CompactionResult:
        """Execute the compaction algorithm.

        Algorithm (optimized single-pass):
        0. Build tool call index for O(1) argument lookup
        1. Forward pass: collect resource identities (skip already compacted)
        2. Identify stale messages (older messages for same resource)
        3. Create stubs for stale messages that pass policy checks
        4. Build result with compacted messages
        """
        original_count = len(messages)

        # Phase 0: Build tool call index for O(1) lookups
        # This avoids O(n) backward scans for each tool result message
        tool_call_index: dict[str, tuple[str, str | dict[str, Any]]] = {}
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.id and tc.function.name:
                        tool_call_index[tc.id] = (
                            tc.function.name,
                            tc.function.arguments or "{}",
                        )

        # Phase 1: Build resource correlation map
        # Maps resource identity -> list of (message_index, tool_name, content)
        resource_map: dict[ResourceIdentity, list[tuple[int, str, str]]] = {}

        for idx, msg in enumerate(messages):
            if not is_tool_result_message(msg.role, msg.tool_call_id):
                continue

            # Skip messages already marked as compacted from a previous run
            # This avoids redundant processing when the same history is analyzed repeatedly
            if msg.metadata and msg.metadata.get("_compacted"):
                continue

            # Extract tool name - first try the indexed lookup, then fallback methods
            tool_name: str | None = None
            if msg.tool_call_id and msg.tool_call_id in tool_call_index:
                tool_name = tool_call_index[msg.tool_call_id][0]
            else:
                tool_name = self._extract_tool_name_from_message(msg, idx, messages)
            if not tool_name:
                continue

            # Get message content as string
            content = self._get_content_as_string(msg.content)
            if not content:
                continue

            # Try to extract resource identity using indexed lookup first
            arguments: str | dict[str, Any] | None = None
            if msg.tool_call_id and msg.tool_call_id in tool_call_index:
                arguments = tool_call_index[msg.tool_call_id][1]
            elif msg.metadata and "tool_args" in msg.metadata:
                arguments = msg.metadata["tool_args"]
            identity = self._extractor.extract(tool_name, arguments, msg.tool_call_id)

            if identity is None:
                # Cannot identify resource - skip compaction per Req 1.3
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Skipping message %d - cannot extract resource identity",
                        idx,
                    )
                continue

            if identity not in resource_map:
                resource_map[identity] = []
            resource_map[identity].append((idx, tool_name, content))

        # Phase 2: Identify stale messages
        # For each resource, all messages except the last are stale
        stale_indices: dict[int, CompactionStub] = {}
        stale_resources: set[str] = set()
        bytes_saved = 0

        for identity, occurrences in resource_map.items():
            if len(occurrences) <= 1:
                # Only one occurrence - not stale
                continue

            # Check policy for this tool
            tool_name = occurrences[0][1]
            category = categorize_tool(tool_name)

            if not policies.should_compact_tool(tool_name, category):
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Skipping compaction for %s - denied by policy",
                        tool_name,
                    )
                continue

            # Mark all but the last occurrence as stale
            for msg_idx, _, content in occurrences[:-1]:
                # Avoid compacting very small tool outputs: savings are usually not worth
                # the potential downstream downsides (e.g., remote cache invalidation).
                min_tokens = policies.config.min_tool_output_tokens_to_compact
                content_token_estimate = len(content) // 4
                if min_tokens > 0 and content_token_estimate < min_tokens:
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "Skipping compaction for message %d - tool output %d tokens below per-message minimum %d",
                            msg_idx,
                            content_token_estimate,
                            min_tokens,
                        )
                    continue

                # Pass redaction flag from config (Req 4.5)
                stub = CompactionStub.create(
                    identity,
                    content,
                    msg_idx,
                    redact=policies.config.redact_resource_identifiers,
                )
                stale_indices[msg_idx] = stub
                stale_resources.add(str(identity))
                bytes_saved += stub.original_byte_size - len(
                    stub.stub_text.encode("utf-8")
                )

        if not stale_indices:
            # No stale messages found
            return CompactionResult(
                messages=messages,
                original_message_count=original_count,
            )

        # Phase 3: Build compacted message list
        compacted_messages: list[ChatMessage] = []

        for idx, msg in enumerate(messages):
            if idx in stale_indices:
                stub = stale_indices[idx]
                # Create a new message with stub content
                compacted_msg = ChatMessage(
                    role=msg.role,
                    content=stub.stub_text,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    metadata={
                        **(msg.metadata or {}),
                        "_compacted": True,
                        "_original_bytes": stub.original_byte_size,
                    },
                )
                compacted_messages.append(compacted_msg)
            else:
                compacted_messages.append(msg)

        # Log compaction summary (Req 4.1)
        logger.info(
            "Compacted %d messages, saved ~%d bytes, stale resources: %s",
            len(stale_indices),
            bytes_saved,
            list(stale_resources)[:5],  # Limit logged resources
        )

        # Estimate tokens saved (rough approximation: 4 chars per token)
        tokens_saved = bytes_saved // 4

        return CompactionResult(
            messages=compacted_messages,
            compacted_count=len(stale_indices),
            bytes_saved=bytes_saved,
            tokens_saved_estimate=tokens_saved,
            original_message_count=original_count,
            stale_resources=stale_resources,
        )

    def _extract_tool_name_from_message(
        self,
        msg: ChatMessage,
        msg_idx: int,
        all_messages: list[ChatMessage],
    ) -> str | None:
        """Extract tool name from a tool result message.

        Tries:
        1. Message name field (common convention)
        2. Metadata tool_name field
        3. Look up from corresponding tool_call in preceding assistant message
        """
        # Try name field
        if msg.name:
            return msg.name

        # Try metadata
        if msg.metadata and "tool_name" in msg.metadata:
            return str(msg.metadata["tool_name"])

        # Look up from preceding assistant message's tool_calls
        if msg.tool_call_id:
            for i in range(msg_idx - 1, -1, -1):
                prev_msg = all_messages[i]
                if prev_msg.role == "assistant" and prev_msg.tool_calls:
                    for tc in prev_msg.tool_calls:
                        if tc.id == msg.tool_call_id:
                            return tc.function.name

        return None

    def _get_content_as_string(
        self,
        content: Any,
    ) -> str:
        """Convert message content to string for size calculation."""
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        # Multimodal content - concatenate text parts
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif hasattr(part, "type") and getattr(part, "type", None) == "text":  # type: ignore[attr-defined]
                    text_parts.append(getattr(part, "text", ""))  # type: ignore[attr-defined]
            return "\n".join(text_parts)

        return str(content)

    def _find_tool_call_arguments(
        self,
        tool_call_id: str | None,
        msg_idx: int,
        all_messages: list[ChatMessage],
    ) -> str | dict[str, Any] | None:
        """Find the arguments for a tool call by ID.

        Searches:
        1. Metadata "tool_args" in the message itself
        2. Preceding assistant messages for the tool_call
        """
        if msg_idx < len(all_messages):
            msg = all_messages[msg_idx]
            if msg.metadata and "tool_args" in msg.metadata:
                from typing import cast

                return cast(dict[str, Any], msg.metadata["tool_args"])

        if not tool_call_id:
            return None

        for i in range(msg_idx - 1, -1, -1):
            msg = all_messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.id == tool_call_id:
                        return tc.function.arguments

        return None
