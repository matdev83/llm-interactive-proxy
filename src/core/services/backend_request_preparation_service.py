"""
Backend request preparation service implementation.

This module provides the implementation of the backend request preparation interface,
extracting request preparation logic from BackendRequestManager for modularity.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.4, 8.1, 9.1
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    TokenBudgetConfig,
)
from src.core.domain.configuration.dynamic_compression_config import (
    DynamicCompressionConfig,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.history_compaction_interface import (
    IHistoryCompactionService,
)
from src.core.interfaces.tool_output_compression_interface import (
    IToolOutputCompressionService,
)
from src.core.services.legacy_compression_compatibility_resolver import (
    DynamicCompressionCompatibilityDiagnostics,
    LegacyCompressionCompatibilityResolver,
)

logger = logging.getLogger(__name__)


class BackendRequestPreparationService(IBackendRequestPreparation):
    """Service for preparing backend requests from command results and compaction."""

    def __init__(
        self,
        history_compaction_service: IHistoryCompactionService | None = None,
        config: IConfig | None = None,
        tool_output_compression_service: IToolOutputCompressionService | None = None,
        legacy_compression_compatibility_resolver: (
            LegacyCompressionCompatibilityResolver | None
        ) = None,
    ) -> None:
        """Initialize the request preparation service.

        Args:
            history_compaction_service: Optional service for compacting history
            config: Optional application configuration
        """
        self._history_compaction_service = history_compaction_service
        self._config = config
        self._tool_output_compression_service = tool_output_compression_service
        self._legacy_compression_compatibility_resolver = (
            legacy_compression_compatibility_resolver
            or LegacyCompressionCompatibilityResolver()
        )

    async def prepare(
        self,
        request: ChatRequest,
        command_result: ProcessedResult,
    ) -> ChatRequest | None:
        """Return a new request with normalized messages or None to skip backend.

        Args:
            request: The original backend request
            command_result: Result of command processing

        Returns:
            A new request with normalized messages, or None to skip backend execution

        Preconditions:
            - request.messages and command_result are non-null

        Postconditions:
            - Returned request uses new message list when modified
            - Original request instance is not mutated
        """
        final_request = request

        # Process modified_messages if they exist (either from command execution or filtering)
        # This handles both command execution and command filtering when commands are disabled
        final_messages: list[ChatMessage] = list(request.messages)
        messages_were_modified = False

        if command_result.modified_messages:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Processing modified_messages; command_executed=%s, modified_messages_count=%s",
                    command_result.command_executed,
                    len(command_result.modified_messages or []),
                )

            # Process modified_messages: if they exist and have content, they replace original messages
            if any(
                self._message_has_content(m) for m in command_result.modified_messages
            ):
                normalized_messages: list[ChatMessage] = []
                for m in command_result.modified_messages:
                    if isinstance(m, ChatMessage):
                        normalized_messages.append(m)
                    elif isinstance(m, dict):
                        normalized_messages.append(ChatMessage(**m))
                    else:
                        normalized_messages.append(
                            ChatMessage(
                                role=getattr(m, "role", "user"),
                                content=getattr(m, "content", ""),
                            )
                        )
                final_messages = normalized_messages
                messages_were_modified = True
            else:
                # All modified messages are empty, skip backend call
                return None

        # Process command_results: append tool outputs to the message list
        # Only process command_results when commands were actually executed
        if command_result.command_executed and command_result.command_results:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Command executed; command_results_count=%s",
                    len(command_result.command_results or []),
                )
            extra_messages = []
            for result in command_result.command_results:
                extracted = self._extract_messages_from_command_result(result)
                if extracted:
                    extra_messages.extend(extracted)

            if extra_messages:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Appending %s command result messages to backend request",
                        len(extra_messages),
                    )
                final_messages.extend(extra_messages)
                messages_were_modified = True

        # If messages were changed, create a new request object
        if messages_were_modified:
            final_request = request.model_copy(update={"messages": final_messages})

        # Apply history compaction to reduce stale tool outputs
        # This is done after command processing but before connector translation
        # Use history compaction if available and we have a token count
        compaction_feature_enabled = False
        compaction_mutated_messages = False
        if self._history_compaction_service is not None:
            # Fast approximate token estimate using character count / 4
            # This is O(n) and avoids expensive tokenization for threshold checking
            # Actual tokenization happens later in the pipeline if needed
            total_chars = sum(
                len(str(msg.content or "")) for msg in final_request.messages
            )
            token_estimate = total_chars // 4  # ~4 chars per token average

            # Initialize config for exception handler
            config: CompactionConfig | None = None
            try:
                # Use injected config or default
                compaction_config: CompactionConfig
                if self._config and hasattr(self._config, "compaction"):
                    compaction_config = getattr(self._config, "compaction", None) or CompactionConfig.default()  # type: ignore[attr-defined]
                else:
                    compaction_config = CompactionConfig.default()

                # Store for exception handler
                config = compaction_config
                compaction_feature_enabled = bool(compaction_config.enabled)

                # Check if we should even check compaction (token threshold)
                # First check: is feature enabled?
                # Second check: is token count above threshold?
                if (
                    compaction_config.enabled
                    and token_estimate >= compaction_config.token_threshold
                ):
                    compaction_result = (
                        await self._history_compaction_service.compact_history(
                            final_request.messages,
                            compaction_config,
                            current_token_estimate=token_estimate,
                        )
                    )
                    compaction_mutated_messages = bool(compaction_result.was_compacted)
                    if compaction_result.was_compacted and logger.isEnabledFor(
                        logging.INFO
                    ):
                        # Use structured logging with observability context (Req 4.1)
                        logger.info(
                            "Compacted conversation history",
                            extra={
                                "original_messages": compaction_result.original_message_count,
                                "compacted_messages": compaction_result.compacted_count,
                                "bytes_saved": compaction_result.bytes_saved,
                                "tokens_saved_estimate": compaction_result.tokens_saved_estimate,
                                "original_tokens_estimate": token_estimate,
                                # Export metrics for observability (Req 4.1)
                                "metrics": compaction_result.to_metrics().model_dump(),
                            },
                        )
                    if compaction_result.was_compacted:
                        final_request = final_request.model_copy(
                            update={"messages": compaction_result.messages}
                        )

                        # Check for overflow after compaction (Req 3.2)
                        # If compaction could not reduce tokens below max_tokens,
                        # emit a warning to alert operators of potential overflow risk.
                        # Request is still forwarded (fail-open behavior).
                        post_compaction_chars = sum(
                            len(str(msg.content or ""))
                            for msg in final_request.messages
                        )
                        post_compaction_estimate = post_compaction_chars // 4

                        budget = TokenBudgetConfig.from_config(
                            compaction_config, post_compaction_estimate
                        )
                        if budget.exceeds_max:
                            overflow = budget.current_estimate - budget.max_tokens
                            logger.warning(
                                "Context compaction could not reduce tokens below maximum - overflow risk",
                                extra={
                                    "current_estimate": budget.current_estimate,
                                    "max_tokens": budget.max_tokens,
                                    "overflow_tokens": overflow,
                                    "recommendation": "Consider adjusting compaction policies or token limits",
                                },
                            )
            except Exception as exc:
                # Fail-open: log error and continue with original messages
                if logger.isEnabledFor(logging.WARNING):
                    # Safely get config.enabled for logging, defaulting to False if config not available
                    config_enabled = False
                    if config is not None:
                        config_enabled = getattr(config, "enabled", False)
                    logger.warning(
                        "History compaction failed - continuing with original messages: %s",
                        exc,
                        exc_info=True,
                        extra={
                            "compaction": {
                                "failed_open": True,
                                "enabled": config_enabled,
                                "error": str(exc),
                            }
                        },
                    )

        # Apply dynamic tool-output compression after compaction.
        if self._tool_output_compression_service is not None:
            dynamic_config = DynamicCompressionConfig()
            compatibility_diagnostics = DynamicCompressionCompatibilityDiagnostics()
            try:
                if self._config is not None:
                    dynamic_from_config = getattr(
                        self._config, "dynamic_compression", None
                    )
                    if isinstance(dynamic_from_config, DynamicCompressionConfig):
                        dynamic_config = dynamic_from_config
                    elif isinstance(dynamic_from_config, dict):
                        dynamic_config = DynamicCompressionConfig.model_validate(
                            dynamic_from_config
                        )

                (
                    dynamic_config,
                    compatibility_diagnostics,
                ) = self._resolve_pytest_compatibility(dynamic_config)

                path_overlap_warnings = self._build_request_path_overlap_warnings(
                    compaction_enabled=compaction_feature_enabled,
                    compaction_mutated_messages=compaction_mutated_messages,
                    dynamic_enabled=bool(dynamic_config.enabled),
                )
                compatibility_diagnostics = self._merge_compatibility_warnings(
                    diagnostics=compatibility_diagnostics,
                    warnings=path_overlap_warnings,
                )

                token_budget: int | None = None
                if self._config is not None and hasattr(
                    self._config, "context_window_override"
                ):
                    maybe_budget = getattr(
                        self._config, "context_window_override", None
                    )
                    if isinstance(maybe_budget, int) and maybe_budget > 0:
                        token_budget = maybe_budget

                compression_result = (
                    await self._tool_output_compression_service.compress_messages(
                        messages=list(final_request.messages),
                        config=dynamic_config,
                        target_token_budget=token_budget,
                    )
                )

                compatibility_diagnostics = self._merge_compatibility_warnings(
                    diagnostics=compatibility_diagnostics,
                    warnings=compression_result.warnings,
                )
                applied_count = sum(
                    1 for record in compression_result.records if record.applied
                )
                self._log_dynamic_compression_diagnostics(
                    compatibility_diagnostics=compatibility_diagnostics,
                    records_evaluated=len(compression_result.records),
                    records_applied=applied_count,
                    aggregate_metrics=compression_result.aggregate_metrics.model_dump(
                        mode="json"
                    ),
                    alert_count=len(compression_result.alerts),
                )

                if compression_result.records:
                    if applied_count > 0:
                        final_request = final_request.model_copy(
                            update={"messages": compression_result.messages}
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Dynamic compression evaluated %d tool outputs (applied=%d)",
                            len(compression_result.records),
                            applied_count,
                        )
                final_request = self._attach_dynamic_compression_diagnostics(
                    request=final_request,
                    dynamic_config=dynamic_config,
                    compatibility_diagnostics=compatibility_diagnostics,
                    compression_result=compression_result,
                )
            except Exception as exc:
                # Fail-open: continue request flow unchanged.
                compatibility_diagnostics = self._merge_compatibility_warnings(
                    diagnostics=compatibility_diagnostics,
                    warnings=[
                        "Dynamic tool-output compression failed open for this request path."
                    ],
                )
                self._log_dynamic_compression_diagnostics(
                    compatibility_diagnostics=compatibility_diagnostics,
                    records_evaluated=0,
                    records_applied=0,
                    aggregate_metrics=None,
                    alert_count=0,
                    failure=exc,
                )
                final_request = self._attach_dynamic_compression_diagnostics(
                    request=final_request,
                    dynamic_config=dynamic_config,
                    compatibility_diagnostics=compatibility_diagnostics,
                    compression_result=None,
                )

        # Return the (possibly modified) request
        return final_request

    @staticmethod
    def _build_request_path_overlap_warnings(
        *,
        compaction_enabled: bool,
        compaction_mutated_messages: bool,
        dynamic_enabled: bool,
    ) -> list[str]:
        """Emit deterministic notes when multiple request-path reductions may stack."""
        notes: list[str] = []
        if compaction_enabled and dynamic_enabled:
            notes.append(
                "Both history compaction and dynamic tool-output compression are enabled; "
                "eligible tool outputs are shaped first by compaction (when triggered) and "
                "then by the dynamic compression pass."
            )
        if compaction_mutated_messages and dynamic_enabled:
            notes.append(
                "History compaction modified messages before the dynamic tool-output "
                "compression pass for this request."
            )
        return notes

    def _resolve_pytest_compatibility(
        self,
        dynamic_config: DynamicCompressionConfig,
    ) -> tuple[DynamicCompressionConfig, DynamicCompressionCompatibilityDiagnostics]:
        legacy_pytest_enabled = True
        legacy_pytest_min_lines = 30
        legacy_pytest_configured = False
        legacy_pytest_min_lines_configured = False
        if self._config is not None:
            session_config = getattr(self._config, "session", None)
            if session_config is not None:
                maybe_legacy_pytest = getattr(
                    session_config,
                    "pytest_compression_enabled",
                    True,
                )
                if isinstance(maybe_legacy_pytest, bool):
                    legacy_pytest_enabled = maybe_legacy_pytest
                    legacy_pytest_configured = maybe_legacy_pytest is not True
                maybe_legacy_min_lines = getattr(
                    session_config,
                    "pytest_compression_min_lines",
                    legacy_pytest_min_lines,
                )
                if isinstance(maybe_legacy_min_lines, int):
                    legacy_pytest_min_lines = max(0, maybe_legacy_min_lines)
                    legacy_pytest_min_lines_configured = legacy_pytest_min_lines != 30

        dynamic_pytest_mode = dynamic_config.methods.get("pytest_failure_focus")
        decision, compatibility_diagnostics = (
            self._legacy_compression_compatibility_resolver.resolve_pytest_mode_with_diagnostics(
                legacy_pytest_enabled=legacy_pytest_enabled,
                dynamic_pytest_mode=dynamic_pytest_mode,
            )
        )
        if dynamic_pytest_mode in (None, "inherit_legacy") and legacy_pytest_configured:
            warning = (
                "session.pytest_compression_enabled is deprecated; "
                "set dynamic_compression.methods.pytest_failure_focus instead."
            )
            if warning not in compatibility_diagnostics.warnings:
                compatibility_diagnostics.warnings.append(warning)
        min_lines_override = self._resolve_pytest_min_lines_override(
            dynamic_config=dynamic_config,
            legacy_min_lines=legacy_pytest_min_lines,
            legacy_control_configured=legacy_pytest_min_lines_configured,
            compatibility_diagnostics=compatibility_diagnostics,
        )
        resolved_methods = dict(dynamic_config.methods)
        resolved_methods["pytest_failure_focus"] = decision.effective_enabled
        return (
            dynamic_config.model_copy(
                update={
                    "methods": resolved_methods,
                    "pytest_failure_focus_min_lines": min_lines_override,
                }
            ),
            compatibility_diagnostics,
        )

    @staticmethod
    def _resolve_pytest_min_lines_override(
        *,
        dynamic_config: DynamicCompressionConfig,
        legacy_min_lines: int,
        legacy_control_configured: bool,
        compatibility_diagnostics: DynamicCompressionCompatibilityDiagnostics,
    ) -> int:
        legacy_control = "session.pytest_compression_min_lines"
        dynamic_control = "dynamic_compression.pytest_failure_focus_min_lines"
        dynamic_value = None
        if dynamic_config.model_extra is not None:
            dynamic_value = dynamic_config.model_extra.get(
                "pytest_failure_focus_min_lines"
            )

        if dynamic_value is not None:
            try:
                effective_min_lines = max(0, int(dynamic_value))
            except (TypeError, ValueError):
                effective_min_lines = legacy_min_lines
                compatibility_diagnostics.warnings.append(
                    "Invalid dynamic pytest min-lines override detected; "
                    "falling back to session.pytest_compression_min_lines."
                )
            compatibility_diagnostics.applied.append(dynamic_control)
            if effective_min_lines != legacy_min_lines:
                compatibility_diagnostics.overridden.append(legacy_control)
            return effective_min_lines

        compatibility_diagnostics.applied.append(legacy_control)
        if legacy_control_configured:
            compatibility_diagnostics.warnings.append(
                "session.pytest_compression_min_lines is deprecated; "
                "set dynamic_compression.pytest_failure_focus_min_lines instead."
            )
        return legacy_min_lines

    @staticmethod
    def _merge_compatibility_warnings(
        *,
        diagnostics: DynamicCompressionCompatibilityDiagnostics,
        warnings: Iterable[str],
    ) -> DynamicCompressionCompatibilityDiagnostics:
        if not warnings:
            return diagnostics

        merged_warnings: list[str] = list(diagnostics.warnings)
        seen = set(merged_warnings)
        for warning in warnings:
            normalized = warning.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged_warnings.append(normalized)
        return diagnostics.model_copy(update={"warnings": merged_warnings})

    def _log_dynamic_compression_diagnostics(
        self,
        *,
        compatibility_diagnostics: DynamicCompressionCompatibilityDiagnostics,
        records_evaluated: int,
        records_applied: int,
        aggregate_metrics: dict[str, Any] | None,
        alert_count: int,
        failure: Exception | None = None,
    ) -> None:
        diagnostics_payload = {
            "compatibility": compatibility_diagnostics.model_dump(mode="json"),
            "records_evaluated": records_evaluated,
            "records_applied": records_applied,
            "aggregate_metrics": aggregate_metrics,
            "alert_count": alert_count,
        }
        if failure is not None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Dynamic tool-output compression failed - continuing with original messages: %s",
                    failure,
                    exc_info=True,
                    extra={"dynamic_compression": diagnostics_payload},
                )
            return

        if compatibility_diagnostics.warnings:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Dynamic compression compatibility diagnostics",
                    extra={"dynamic_compression": diagnostics_payload},
                )
            return

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Dynamic compression compatibility diagnostics",
                extra={"dynamic_compression": diagnostics_payload},
            )

    def _attach_dynamic_compression_diagnostics(
        self,
        *,
        request: ChatRequest,
        dynamic_config: DynamicCompressionConfig,
        compatibility_diagnostics: DynamicCompressionCompatibilityDiagnostics,
        compression_result: Any | None,
    ) -> ChatRequest:
        merged_diagnostics = dict(request.compression_diagnostics or {})
        merged_diagnostics["dynamic_compression_compatibility"] = (
            compatibility_diagnostics.model_dump(mode="json")
        )
        if compression_result is not None:
            merged_diagnostics["dynamic_compression_effective_config"] = (
                self._build_effective_config_diagnostics_payload(
                    dynamic_config=dynamic_config,
                    compatibility_diagnostics=compatibility_diagnostics,
                    compression_result=compression_result,
                )
            )
            merged_diagnostics["dynamic_compression_records"] = [
                self._safe_record_payload(record)
                for record in compression_result.records
            ]
            merged_diagnostics["dynamic_compression_stats"] = (
                compression_result.aggregate_metrics.model_dump(mode="json")
            )
            merged_diagnostics["dynamic_compression_alerts"] = [
                alert.model_dump(mode="json") for alert in compression_result.alerts
            ]
            merged_diagnostics["dynamic_compression_correlation"] = (
                self._build_correlation_payload(compression_result.records)
            )
            recovery_handles = sorted(
                {
                    record.recovery_handle
                    for record in compression_result.records
                    if getattr(record, "recovery_handle", None)
                }
            )
            merged_diagnostics["dynamic_compression_recovery"] = {
                "mode": dynamic_config.recovery.mode,
                "enabled": dynamic_config.recovery.mode != "never",
                "handles": recovery_handles,
                "hint_in_text": bool(dynamic_config.recovery.hint_in_text),
                "thresholds": {
                    "min_original_bytes": dynamic_config.recovery.min_original_bytes,
                    "min_saved_bytes": dynamic_config.recovery.min_saved_bytes,
                    "max_artifact_bytes": dynamic_config.recovery.max_artifact_bytes,
                    "max_artifacts": dynamic_config.recovery.max_artifacts,
                    "retention_seconds": dynamic_config.recovery.retention_seconds,
                },
            }
        return request.model_copy(
            update={"compression_diagnostics": merged_diagnostics}
        )

    @staticmethod
    def _safe_record_payload(record: Any) -> dict[str, Any]:
        return {
            "tool_call_id": record.tool_call_id,
            "tool_name": record.identity.tool_name,
            "tool_category": record.identity.tool_category,
            "command_signature": record.identity.command_signature,
            "command_prefix": record.identity.command_prefix,
            "original_bytes": record.original_bytes,
            "compressed_bytes": record.compressed_bytes,
            "saved_bytes": record.saved_bytes,
            "elapsed_total_ms": record.elapsed_total_ms,
            "methods_applied": list(record.methods_applied),
            "methods": [method.model_dump(mode="json") for method in record.methods],
            "final_level": record.final_level.value,
            "applied": record.applied,
            "failed_open": record.failed_open,
            "fallback_applied": record.fallback_applied,
            "failure_reason": record.failure_reason,
            "marker_inserted": record.marker_inserted,
            "warnings": list(record.warnings),
            "original_sha256": record.original_sha256,
            "compressed_sha256": record.compressed_sha256,
            "correlation_id": record.correlation_id,
            "recovery_handle": record.recovery_handle,
            "recovery_persisted": record.recovery_persisted,
            "recovery_hint_inserted": record.recovery_hint_inserted,
            "explicit_format_note": record.explicit_format_note,
        }

    @staticmethod
    def _build_correlation_payload(records: list[Any]) -> dict[str, Any]:
        return {
            "record_count": len(records),
            "records": [
                {
                    "tool_call_id": record.tool_call_id,
                    "correlation_id": record.correlation_id,
                    "original_sha256": record.original_sha256,
                    "compressed_sha256": record.compressed_sha256,
                    "saved_bytes": record.saved_bytes,
                    "methods_applied": list(record.methods_applied),
                    "recovery_handle": record.recovery_handle,
                }
                for record in records
            ],
        }

    @staticmethod
    def _build_effective_config_diagnostics_payload(
        *,
        dynamic_config: DynamicCompressionConfig,
        compatibility_diagnostics: DynamicCompressionCompatibilityDiagnostics,
        compression_result: Any,
    ) -> dict[str, Any]:
        effective_config = (
            compression_result.effective_config.model_dump(mode="json")
            if compression_result.effective_config is not None
            else {
                "active_controls": [],
                "inactive_controls": [],
                "ignored_controls": [],
                "reasons": {},
                "fingerprint": None,
                "warnings": [],
            }
        )
        active_controls = set(effective_config.get("active_controls", []))
        inactive_controls = set(effective_config.get("inactive_controls", []))
        ignored_controls = set(effective_config.get("ignored_controls", []))
        reasons = dict(effective_config.get("reasons", {}))
        warnings = set(effective_config.get("warnings", []))

        active_controls.update(compatibility_diagnostics.applied)
        inactive_controls.update(compatibility_diagnostics.inactive)
        ignored_controls.update(compatibility_diagnostics.ignored)
        ignored_controls.update(compatibility_diagnostics.overridden)
        warnings.update(compatibility_diagnostics.warnings)

        for control in compatibility_diagnostics.ignored:
            reasons.setdefault(
                control,
                "Accepted but ignored due to compatibility precedence.",
            )
        for control in compatibility_diagnostics.inactive:
            reasons.setdefault(
                control,
                "Accepted but inactive in current runtime context.",
            )
        for control in compatibility_diagnostics.overridden:
            reasons.setdefault(
                control,
                "Accepted but overridden by deterministic precedence rules.",
            )
        for warning in compatibility_diagnostics.warnings:
            key = f"compatibility.warning.{len(reasons)}"
            reasons.setdefault(key, warning)

        return {
            "enabled": bool(dynamic_config.enabled),
            "level": dynamic_config.level.value,
            "max_level": dynamic_config.max_level.value,
            "active_controls": sorted(active_controls),
            "inactive_controls": sorted(inactive_controls),
            "ignored_controls": sorted(ignored_controls),
            "reasons": reasons,
            "warnings": sorted(warnings),
            "fingerprint": effective_config.get("fingerprint"),
        }

    @staticmethod
    def _message_has_content(message: Any) -> bool:
        """Check if a message has user content.

        Args:
            message: The message to check (can be dict, ChatMessage, or other)

        Returns:
            True if message has user role and non-empty content
        """
        role = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        if role != "user":
            return False
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        if content is None:
            return False
        if isinstance(content, str):
            return bool(content.strip())  # Check for non-empty string
        if isinstance(content, list):
            return len(content) > 0
        return bool(content)

    @staticmethod
    def _extract_messages_from_command_result(result: Any) -> list[ChatMessage]:
        """Extract chat messages embedded in command results for backend replay.

        Args:
            result: Command result that may contain messages

        Returns:
            List of extracted ChatMessage instances
        """

        def _coerce_message(candidate: Any) -> ChatMessage | None:
            """Convert a candidate object into a ChatMessage when possible."""
            if isinstance(candidate, ChatMessage):
                return candidate

            if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
                try:
                    dumped = candidate.model_dump()
                    if isinstance(dumped, dict):
                        return ChatMessage(**dumped)
                except (ValidationError, TypeError, ValueError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to coerce object with model_dump to ChatMessage: %s",
                            e,
                            exc_info=True,
                        )
                    return None

            if isinstance(candidate, dict):
                try:
                    return ChatMessage(**candidate)
                except (ValidationError, TypeError, ValueError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to coerce dict to ChatMessage: %s",
                            e,
                            exc_info=True,
                        )
                    return None
            return None

        def _iter_candidates(value: Any) -> Iterable[Any]:
            """Yield potential message representations from arbitrary structures."""
            if value is None:
                return ()

            # Prefer explicit tool message containers if present
            if isinstance(value, dict):
                # Check for tool_messages key in dict
                if "tool_messages" in value:
                    tool_value = value["tool_messages"]
                    if isinstance(tool_value, list | tuple):
                        return tuple(tool_value)
                    if tool_value is not None:
                        return (tool_value,)
            elif hasattr(value, "tool_messages"):
                tool_value = value.tool_messages
                if isinstance(tool_value, list | tuple):
                    return tuple(tool_value)
                if tool_value is not None:
                    return (tool_value,)

            if isinstance(value, list | tuple):
                return tuple(value)

            return (value,)

        messages: list[ChatMessage] = []
        for candidate in _iter_candidates(result):
            coerced = _coerce_message(candidate)
            if coerced is not None:
                messages.append(coerced)
        return messages
