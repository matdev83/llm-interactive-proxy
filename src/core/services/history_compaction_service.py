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

import hashlib
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
from src.core.domain.compaction_telemetry import (
    CompactionAggregateMetrics,
    CompactionAlertRecord,
    CompactionEventRecord,
    EffectiveCompactionConfigDiagnostics,
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
from src.core.services.compaction_metrics_recorder import CompactionMetricsRecorder

logger = logging.getLogger(__name__)


def build_effective_compaction_config_diagnostics(
    config: CompactionConfig,
) -> EffectiveCompactionConfigDiagnostics:
    """Build redaction-safe effective compaction controls for request diagnostics."""
    active: list[str] = []
    inactive: list[str] = []
    reasons: dict[str, str] = {}

    if config.enabled:
        active.append("compaction.enabled")
    else:
        inactive.append("compaction.enabled")
        reasons["compaction.enabled"] = "Compaction disabled in configuration."

    active.append(f"compaction.token_threshold={config.token_threshold}")
    active.append(f"compaction.max_tokens={config.max_tokens}")
    active.append(
        "compaction.min_tool_output_tokens_to_compact="
        f"{config.min_tool_output_tokens_to_compact}"
    )

    if config.redact_resource_identifiers:
        active.append("compaction.redact_resource_identifiers")
    else:
        inactive.append("compaction.redact_resource_identifiers")
        reasons["compaction.redact_resource_identifiers"] = (
            "Redaction disabled; resource identifiers may appear in stub text."
        )

    if config.allowed_tool_categories:
        active.append(
            "compaction.allowed_tool_categories="
            + ",".join(sorted(config.allowed_tool_categories))
        )
    else:
        inactive.append("compaction.allowed_tool_categories_empty")
        reasons["compaction.allowed_tool_categories"] = (
            "Allowlist empty; all non-denied tool categories are eligible."
        )

    if config.denied_tool_categories:
        active.append(
            "compaction.denied_tool_categories="
            + ",".join(sorted(config.denied_tool_categories))
        )

    fingerprint_source = "|".join(sorted(active + inactive))
    fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()[:16]

    return EffectiveCompactionConfigDiagnostics(
        active_controls=sorted(active),
        inactive_controls=sorted(inactive),
        ignored_controls=[],
        reasons=reasons,
        fingerprint=fingerprint,
        warnings=[],
    )


def _evaluation_only_result(
    *,
    messages: list[ChatMessage],
    config: CompactionConfig,
    original_count: int,
    reason: str,
) -> CompactionResult:
    recorder = CompactionMetricsRecorder()
    rec = CompactionEventRecord(decision_reason=reason, applied=False)
    alerts = list(recorder.record(rec, alerts_config=config.alerts))
    return CompactionResult(
        messages=messages,
        original_message_count=original_count,
        event_records=[rec],
        aggregate_metrics=recorder.snapshot(),
        alerts=alerts,
        effective_config_diagnostics=build_effective_compaction_config_diagnostics(
            config
        ),
    )


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
            return _evaluation_only_result(
                messages=messages,
                config=config,
                original_count=len(messages),
                reason="disabled",
            )

        if not messages:
            return CompactionResult(
                messages=[],
                original_message_count=0,
                event_records=[],
                aggregate_metrics=CompactionAggregateMetrics(),
                alerts=[],
                effective_config_diagnostics=build_effective_compaction_config_diagnostics(
                    config
                ),
            )

        # Check token budget threshold
        if current_token_estimate is not None:
            budget = TokenBudgetConfig.from_config(config, current_token_estimate)
            if not budget.needs_compaction:
                logger.debug(
                    "Token estimate %d below threshold %d - skipping compaction",
                    current_token_estimate,
                    config.token_threshold,
                )
                return _evaluation_only_result(
                    messages=messages,
                    config=config,
                    original_count=len(messages),
                    reason="below_token_threshold",
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
            return _evaluation_only_result(
                messages=messages,
                config=policies.config,
                original_count=len(messages),
                reason="policies_disabled",
            )

        try:
            return await self._perform_compaction(messages, policies)
        except Exception as exc:
            # Fail-open: log error and return original messages (Req 4.4)
            logger.error(
                "Compaction failed - returning original messages (fail-open)",
                exc_info=True,
            )
            recorder = CompactionMetricsRecorder()
            rec = CompactionEventRecord(
                decision_reason="fail_open",
                failed_open=True,
                failure_reason=str(exc),
                applied=False,
            )
            alerts = list(recorder.record(rec, alerts_config=policies.config.alerts))
            return CompactionResult(
                messages=messages,
                original_message_count=len(messages),
                error=str(exc),
                event_records=[rec],
                aggregate_metrics=recorder.snapshot(),
                alerts=alerts,
                effective_config_diagnostics=build_effective_compaction_config_diagnostics(
                    policies.config
                ),
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
        recorder = CompactionMetricsRecorder()
        alerts_accum: list[CompactionAlertRecord] = []
        event_records: list[CompactionEventRecord] = []

        def _sha256_hex(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        def emit(rec: CompactionEventRecord) -> None:
            event_records.append(rec)
            alerts_accum.extend(
                recorder.record(rec, alerts_config=policies.config.alerts)
            )

        effective_diag = build_effective_compaction_config_diagnostics(policies.config)

        for identity, occurrences in resource_map.items():
            if len(occurrences) <= 1:
                continue

            for msg_idx, tool_name, content in occurrences[:-1]:
                category = categorize_tool(tool_name)
                msg = messages[msg_idx]
                tool_call_id = msg.tool_call_id
                correlation_id = f"hc:{msg_idx}:{tool_call_id or 'none'}"
                identity_hash = _sha256_hex(str(identity))
                preview = str(identity)[:200]
                preview_redacted = bool(policies.config.redact_resource_identifiers)
                original_bytes = len(content.encode("utf-8"))
                original_tokens_estimate = original_bytes // 4

                if not policies.should_compact_tool(tool_name, category):
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "Skipping compaction for %s - denied by policy",
                            tool_name,
                        )
                    emit(
                        CompactionEventRecord(
                            correlation_id=correlation_id,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_category=category.value,
                            resource_identity_hash=identity_hash,
                            resource_identity_preview=preview,
                            resource_preview_redacted=preview_redacted,
                            original_bytes=original_bytes,
                            compacted_bytes=original_bytes,
                            saved_bytes=0,
                            original_tokens_estimate=original_tokens_estimate,
                            saved_tokens_estimate=0,
                            applied=False,
                            decision_reason="denied_by_policy",
                            message_index=msg_idx,
                        )
                    )
                    continue

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
                    emit(
                        CompactionEventRecord(
                            correlation_id=correlation_id,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_category=category.value,
                            resource_identity_hash=identity_hash,
                            resource_identity_preview=preview,
                            resource_preview_redacted=preview_redacted,
                            original_bytes=original_bytes,
                            compacted_bytes=original_bytes,
                            saved_bytes=0,
                            original_tokens_estimate=original_tokens_estimate,
                            saved_tokens_estimate=0,
                            applied=False,
                            decision_reason="skipped_below_min_tokens",
                            message_index=msg_idx,
                        )
                    )
                    continue

                stub = CompactionStub.create(
                    identity,
                    content,
                    msg_idx,
                    redact=policies.config.redact_resource_identifiers,
                )
                compacted_bytes = len(stub.stub_text.encode("utf-8"))
                saved_bytes = max(0, stub.original_byte_size - compacted_bytes)
                stale_indices[msg_idx] = stub
                stale_resources.add(str(identity))
                bytes_saved += saved_bytes
                emit(
                    CompactionEventRecord(
                        correlation_id=correlation_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tool_category=category.value,
                        resource_identity_hash=identity_hash,
                        resource_identity_preview=preview,
                        resource_preview_redacted=preview_redacted,
                        original_bytes=stub.original_byte_size,
                        compacted_bytes=compacted_bytes,
                        saved_bytes=saved_bytes,
                        original_tokens_estimate=stub.original_byte_size // 4,
                        saved_tokens_estimate=max(saved_bytes // 4, 0),
                        applied=True,
                        decision_reason="applied",
                        message_index=msg_idx,
                        original_sha256=_sha256_hex(content),
                        compacted_sha256=_sha256_hex(stub.stub_text),
                    )
                )

        if not event_records and not stale_indices:
            emit(
                CompactionEventRecord(
                    decision_reason="no_stale_results",
                    applied=False,
                )
            )

        if not stale_indices:
            return CompactionResult(
                messages=messages,
                original_message_count=original_count,
                event_records=event_records,
                aggregate_metrics=recorder.snapshot(),
                alerts=alerts_accum,
                effective_config_diagnostics=effective_diag,
            )

        # Phase 3: Build compacted message list
        compacted_messages: list[ChatMessage] = []

        for idx, msg in enumerate(messages):
            if idx in stale_indices:
                stub = stale_indices[idx]
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

        logger.info(
            "Compacted %d messages, saved ~%d bytes, stale resources: %s",
            len(stale_indices),
            bytes_saved,
            list(stale_resources)[:5],
        )

        tokens_saved = bytes_saved // 4

        return CompactionResult(
            messages=compacted_messages,
            compacted_count=len(stale_indices),
            bytes_saved=bytes_saved,
            tokens_saved_estimate=tokens_saved,
            original_message_count=original_count,
            stale_resources=stale_resources,
            event_records=event_records,
            aggregate_metrics=recorder.snapshot(),
            alerts=alerts_accum,
            effective_config_diagnostics=effective_diag,
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
