"""Deterministic orchestration service for dynamic tool-output compression."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Sequence

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionMarkerConfig,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import (
    CompressionAlertRecord,
    CompressionMethodRecord,
    EffectiveCompressionConfigDiagnostics,
    ToolOutputCompressionBatchResult,
    ToolOutputCompressionRecord,
)
from src.core.interfaces.compression_strategy_registry_interface import (
    CompressionStrategy,
)
from src.core.services.compression_metrics_recorder import (
    CompressionMetricsRecorder,
)
from src.core.services.compression_recovery_store import CompressionRecoveryStore
from src.core.services.compression_strategies import (
    DiffCompactStrategy,
    DirectoryTreeSummaryStrategy,
    FileDetailLevelsStrategy,
    OutputPatternMatchRule,
    OutputPatternMatchStrategy,
    PytestFailureFocusStrategy,
    SearchResultsGroupingStrategy,
)
from src.core.services.compression_strategy_registry import (
    CompressionStrategyRegistry,
)
from src.core.services.declarative_compression_rules import (
    DeclarativeRuleRegistry,
    ResolvedDeclarativeRules,
)
from src.core.services.dynamic_compression_config_resolver import (
    DynamicCompressionConfigResolver,
)
from src.core.services.marker_renderer import MarkerRenderer
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.structural_compression_strategies import (
    JsonNdjsonStructuralStrategy,
    LogLineDedupeStrategy,
    SensitiveFieldProjectionStrategy,
    XmlMachineSafeguardStrategy,
)
from src.core.services.tool_identity_resolver import ToolIdentityResolver

_MESSAGE_YIELD_INTERVAL = 8
_METHOD_YIELD_INTERVAL = 8
_TIME_BUDGET_EXCEEDED_REASON = "time_budget_exceeded"
_DYNAMIC_CONFIG_RUNTIME_TUNABLE_ATTR = "__dynamic_config_runtime_tunable__"
_COMPACTED_STUB_MARKER = "[COMPACTED]"
_SYSTEM_REMINDER_MARKER = "<system-reminder>"
_NOISY_NOOP_DECISION_REASONS = frozenset(
    {
        "compression_disabled",
        "below_min_bytes",
        "category_disabled",
        "tool_disabled",
        "command_prefix_disabled",
        "no_matching_rule",
        "no_enabled_pipeline_methods",
    }
)
logger = get_logger(__name__)


class ToolOutputCompressionService:
    """Select and apply compression methods with fail-open guarantees."""

    def __init__(
        self,
        *,
        strategy_registry: CompressionStrategyRegistry | None = None,
        identity_resolver: ToolIdentityResolver | None = None,
        selector: RuleBasedStrategySelector | None = None,
        marker_renderer: MarkerRenderer | None = None,
        config_resolver: DynamicCompressionConfigResolver | None = None,
        metrics_recorder: CompressionMetricsRecorder | None = None,
        recovery_store: CompressionRecoveryStore | None = None,
        declarative_rule_registry: DeclarativeRuleRegistry | None = None,
    ) -> None:
        self._strategy_registry = strategy_registry or CompressionStrategyRegistry()
        self._identity_resolver = identity_resolver or ToolIdentityResolver()
        self._selector = selector or RuleBasedStrategySelector()
        self._marker_renderer = marker_renderer or MarkerRenderer()
        self._config_resolver = config_resolver or DynamicCompressionConfigResolver()
        self._metrics_recorder = metrics_recorder or CompressionMetricsRecorder()
        self._recovery_store = recovery_store or CompressionRecoveryStore()
        self._declarative_rule_registry = (
            declarative_rule_registry or DeclarativeRuleRegistry()
        )

    def prevalidate_config(self, config: DynamicCompressionConfig) -> list[str]:
        """Validate dynamic/declarative config eagerly and return warnings."""
        _, warnings, _ = self._resolve_effective_config_and_rules(config)
        return warnings

    async def compress_messages(
        self,
        *,
        messages: Sequence[ChatMessage],
        config: DynamicCompressionConfig,
        target_token_budget: int | None = None,
    ) -> ToolOutputCompressionBatchResult:
        (
            effective_config,
            resolver_warnings,
            resolved_declarative_rules,
        ) = self._resolve_effective_config_and_rules(config)
        runtime_strategy_overrides = self._build_runtime_strategy_overrides(
            effective_config
        )
        effective_config_diagnostics = self._build_effective_config_diagnostics(
            effective_config=effective_config,
            resolver_warnings=resolver_warnings,
        )

        updated_messages: list[ChatMessage] = []
        records: list[ToolOutputCompressionRecord] = []
        batch_alerts: list[CompressionAlertRecord] = []
        tool_lookup = self._identity_resolver.build_tool_call_lookup(messages)

        for message_index, message in enumerate(messages):
            if message_index and message_index % _MESSAGE_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)
            if message.role != "tool" or not isinstance(message.content, str):
                updated_messages.append(message)
                continue

            context = self._identity_resolver.resolve_tool_output(
                messages=messages,
                tool_message=message,
                explicit_format_flags=effective_config.explicit_format_flags,
                tool_lookup=tool_lookup,
            )
            if context is None:
                updated_messages.append(message)
                continue

            record = ToolOutputCompressionRecord(
                tool_call_id=message.tool_call_id,
                identity=context.identity,
                original_bytes=context.byte_size,
                compressed_bytes=context.byte_size,
                methods=[],
                marker_inserted=False,
                failed_open=False,
                applied=False,
                final_level=effective_config.level,
                warnings=list(resolver_warnings),
            )
            records.append(record)
            output_started_at = time.perf_counter()
            selected_rule_name: str | None = None
            declared_pipeline: list[str] = []
            enabled_pipeline: list[str] = []
            already_processed_warning = self._already_processed_skip_warning(message)
            if already_processed_warning is not None:
                updated_messages.append(message)
                self._append_warning_once(
                    record=record,
                    warning=already_processed_warning,
                )
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="already_processed_output",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue

            if not effective_config.enabled:
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="compression_disabled",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue
            if context.byte_size < effective_config.min_bytes:
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="below_min_bytes",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue
            if not effective_config.is_category_enabled(context.identity.tool_category):
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="category_disabled",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue
            if context.identity.tool_name in effective_config.disable_tools:
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="tool_disabled",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue
            if context.identity.command_prefix and any(
                context.identity.command_prefix.startswith(prefix)
                for prefix in effective_config.disable_command_prefixes
            ):
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="command_prefix_disabled",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue

            selected_rule = self._selector.select_rule(context, effective_config)
            selected_declarative_rule = self._declarative_rule_registry.match_rule(
                context=context,
                rules=resolved_declarative_rules.rules,
            )

            use_declarative_rule = False
            if selected_declarative_rule is not None:
                if selected_rule is None:
                    use_declarative_rule = True
                elif selected_declarative_rule.override:
                    use_declarative_rule = True
                    self._append_warning_once(
                        record=record,
                        warning=(
                            "declarative_rule_override:"
                            f"{selected_declarative_rule.name}"
                        ),
                    )
                else:
                    self._append_warning_once(
                        record=record,
                        warning=(
                            "declarative_rule_ignored_code_precedence:"
                            f"{selected_declarative_rule.name}"
                        ),
                    )

            if selected_rule is None and not use_declarative_rule:
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="no_matching_rule",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue
            per_output_runtime_overrides = dict(runtime_strategy_overrides)
            if use_declarative_rule:
                assert selected_declarative_rule is not None
                selected_rule_name = f"declarative:{selected_declarative_rule.name}"
                declared_pipeline = ["declarative_rule_filter"]
                per_output_runtime_overrides["declarative_rule_filter"] = (
                    self._declarative_rule_registry.make_strategy(
                        rule=selected_declarative_rule,
                        regex_timeout_ms=effective_config.declarative_regex_timeout_ms,
                    )
                )
            else:
                assert selected_rule is not None
                selected_rule_name = selected_rule.name
                declared_pipeline = list(selected_rule.pipeline)

            pipeline = [
                method_name
                for method_name in declared_pipeline
                if effective_config.is_method_enabled(method_name)
            ]
            enabled_pipeline = list(pipeline)
            if not pipeline:
                updated_messages.append(message)
                self._finalize_record_fields(
                    record=record,
                    final_content=message.content,
                    output_started_at=output_started_at,
                )
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="no_enabled_pipeline_methods",
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue

            (
                compressed_content,
                method_records,
                failed_open,
                final_level,
                budget_reason,
            ) = await self._run_pipeline_with_escalation(
                original_content=message.content,
                context=context,
                pipeline=pipeline,
                level=effective_config.level,
                max_level=effective_config.max_level,
                target_token_budget=target_token_budget,
                time_budget_ms=effective_config.time_budget_ms_per_output,
                runtime_strategy_overrides=per_output_runtime_overrides,
            )
            if budget_reason is not None:
                record.warnings.append(budget_reason)

            final_content = compressed_content
            final_bytes = len(final_content.encode("utf-8"))
            marker_inserted = False
            if final_content != message.content:
                marked_content, marker_inserted = self._marker_renderer.apply_marker(
                    context=context,
                    content=final_content,
                    marker_config=effective_config.marker,
                    level=final_level,
                    methods=[
                        method.name for method in method_records if method.applied
                    ],
                    original_bytes=context.byte_size,
                    compressed_bytes=len(final_content.encode("utf-8")),
                )
                marked_bytes = len(marked_content.encode("utf-8"))
                if marked_bytes <= record.original_bytes:
                    final_content = marked_content
                    final_bytes = marked_bytes
                else:
                    marker_inserted = False
                    self._append_warning_once(
                        record=record,
                        warning="marker_rolled_back_size_increase",
                    )

            record.methods = method_records
            record.failed_open = failed_open
            record.final_level = final_level
            record.marker_inserted = marker_inserted
            record.compressed_bytes = final_bytes
            record.applied = final_content != message.content
            record.saved_bytes = max(0, record.original_bytes - final_bytes)
            record.methods_applied = [
                method.name for method in method_records if method.applied
            ]
            if effective_config.telemetry_include_content_hashes:
                record.original_sha256 = self._hash_payload(message.content)
                record.compressed_sha256 = self._hash_payload(final_content)

            if effective_config.recovery.mode != "never":
                recovery_handle, recovery_warning = (
                    await self._recovery_store.persist_if_eligible(
                        original_content=message.content,
                        record=record,
                        config=effective_config.recovery,
                    )
                )
                if recovery_warning:
                    record.warnings.append(recovery_warning)
                if recovery_handle:
                    record.recovery_handle = recovery_handle
                    record.recovery_persisted = True
                    if self._should_insert_recovery_hint(
                        record=record,
                        marker_config=effective_config.marker,
                        content_type=context.content_type.value,
                        hint_in_text=effective_config.recovery.hint_in_text,
                    ):
                        hinted_content = self._append_recovery_hint(
                            content=final_content,
                            handle=recovery_handle,
                        )
                        hinted_bytes = len(hinted_content.encode("utf-8"))
                        if hinted_bytes <= record.original_bytes:
                            final_content = hinted_content
                            final_bytes = hinted_bytes
                            record.compressed_bytes = hinted_bytes
                            record.recovery_hint_inserted = True
                            record.applied = final_content != message.content
                        else:
                            self._append_warning_once(
                                record=record,
                                warning="recovery_hint_skipped_size_increase",
                            )

            if final_bytes > record.original_bytes:
                final_content = compressed_content
                final_bytes = len(final_content.encode("utf-8"))
                record.marker_inserted = False
                record.recovery_hint_inserted = False
                self._append_warning_once(
                    record=record,
                    warning="final_output_rolled_back_size_increase",
                )

            self._finalize_record_fields(
                record=record,
                final_content=final_content,
                output_started_at=output_started_at,
            )
            if effective_config.telemetry_include_content_hashes:
                record.original_sha256 = self._hash_payload(message.content)
                record.compressed_sha256 = self._hash_payload(final_content)
            record.correlation_id = self._build_correlation_id(record)
            if final_content == message.content:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason=(
                        "failed_open" if record.failed_open else "not_applied"
                    ),
                    output_started_at=output_started_at,
                )
                batch_alerts.extend(
                    self._record_metrics_and_alerts(
                        record=record,
                        effective_config=effective_config,
                    )
                )
                continue

            updated_messages.append(
                message.model_copy(update={"content": final_content})
            )
            self._log_output_evaluation(
                record=record,
                selected_rule_name=selected_rule_name,
                declared_pipeline=declared_pipeline,
                enabled_pipeline=enabled_pipeline,
                decision_reason=(
                    "applied_failed_open" if record.failed_open else "applied"
                ),
                output_started_at=output_started_at,
            )
            batch_alerts.extend(
                self._record_metrics_and_alerts(
                    record=record,
                    effective_config=effective_config,
                )
            )

        return ToolOutputCompressionBatchResult(
            messages=updated_messages,
            records=records,
            warnings=list(resolver_warnings),
            aggregate_metrics=self._metrics_recorder.snapshot(),
            alerts=batch_alerts,
            effective_config=effective_config_diagnostics,
        )

    def _resolve_effective_config_and_rules(
        self,
        config: DynamicCompressionConfig,
    ) -> tuple[
        DynamicCompressionConfig,
        list[str],
        ResolvedDeclarativeRules,
    ]:
        snapshot = self._config_resolver.create_runtime_snapshot(config)
        resolved = self._config_resolver.resolve(
            snapshot,
            available_methods=(
                *self._strategy_registry.available_method_names(),
                "declarative_rule_filter",
            ),
        )
        effective_config = resolved.config
        resolver_warnings = list(resolved.warnings)
        resolved_declarative_rules = self._declarative_rule_registry.resolve(
            effective_config
        )
        for warning in resolved_declarative_rules.warnings:
            if warning not in resolver_warnings:
                resolver_warnings.append(warning)
        return effective_config, resolver_warnings, resolved_declarative_rules

    def _build_effective_config_diagnostics(
        self,
        *,
        effective_config: DynamicCompressionConfig,
        resolver_warnings: list[str],
    ) -> EffectiveCompressionConfigDiagnostics:
        active_controls: set[str] = set()
        inactive_controls: set[str] = set()
        ignored_controls: set[str] = set()
        reasons: dict[str, str] = {}

        if effective_config.enabled:
            active_controls.add("dynamic_compression.enabled")
        else:
            inactive_controls.add("dynamic_compression.enabled")
            reasons["dynamic_compression.enabled"] = (
                "Dynamic compression disabled by configuration."
            )

        active_controls.add(f"dynamic_compression.level.{effective_config.level.value}")
        active_controls.add(
            f"dynamic_compression.max_level.{effective_config.max_level.value}"
        )

        disabled_categories = {
            category.strip().lower() for category in effective_config.disable_categories
        }
        for category, category_enabled in sorted(effective_config.categories.items()):
            control = f"dynamic_compression.categories.{category}"
            if not category_enabled:
                inactive_controls.add(control)
                reasons[control] = "Category disabled in categories map."
                continue
            if category.lower() in disabled_categories:
                inactive_controls.add(control)
                reasons[control] = (
                    "Category disabled by dynamic_compression.disable_categories."
                )
                continue
            active_controls.add(control)

        for category in sorted(disabled_categories):
            control = f"dynamic_compression.disable_categories.{category}"
            active_controls.add(control)
            reasons[control] = "Operator category opt-out control active."

        for method_name, method_state in sorted(effective_config.methods.items()):
            control = f"dynamic_compression.methods.{method_name}"
            if method_state is False:
                inactive_controls.add(control)
                reasons[control] = "Method disabled in methods map."
                continue
            if method_name in effective_config.disable_methods:
                inactive_controls.add(control)
                reasons[control] = (
                    "Method disabled by dynamic_compression.disable_methods."
                )
                continue
            active_controls.add(control)

        for method_name in sorted(effective_config.disable_methods):
            control = f"dynamic_compression.disable_methods.{method_name}"
            active_controls.add(control)
            reasons[control] = "Operator method opt-out control active."

        for tool_name in sorted(effective_config.disable_tools):
            control = f"dynamic_compression.disable_tools.{tool_name}"
            active_controls.add(control)
            reasons[control] = "Operator tool opt-out control active."

        for command_prefix in sorted(effective_config.disable_command_prefixes):
            control = (
                "dynamic_compression.disable_command_prefixes."
                f"{command_prefix.lower()}"
            )
            active_controls.add(control)
            reasons[control] = "Operator command-prefix opt-out control active."

        unique_warnings = sorted(
            {warning.strip() for warning in resolver_warnings if warning.strip()}
        )
        for idx, warning in enumerate(unique_warnings):
            control = self._warning_to_control(warning=warning, index=idx)
            ignored_controls.add(control)
            reasons[control] = warning

        fingerprint = hashlib.sha256(
            json.dumps(
                effective_config.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]

        return EffectiveCompressionConfigDiagnostics(
            active_controls=sorted(active_controls),
            inactive_controls=sorted(inactive_controls),
            ignored_controls=sorted(ignored_controls),
            reasons=reasons,
            fingerprint=fingerprint,
            warnings=unique_warnings,
        )

    @staticmethod
    def _warning_to_control(*, warning: str, index: int) -> str:
        lowered = warning.lower()
        if "unknown dynamic compression category override ignored" in lowered:
            category = ToolOutputCompressionService._extract_quoted_token(warning)
            if category:
                return f"dynamic_compression.disable_categories.{category.lower()}"
        if "unknown dynamic compression method override ignored" in lowered:
            method = ToolOutputCompressionService._extract_quoted_token(warning)
            if method:
                return f"dynamic_compression.disable_methods.{method}"
        if "unknown dynamic_compression option ignored" in lowered:
            option = ToolOutputCompressionService._extract_quoted_token(warning)
            if option:
                return f"dynamic_compression.{option}"
        if (
            "references unknown method" in lowered
            or "references unavailable method" in lowered
        ):
            method = ToolOutputCompressionService._extract_quoted_token(warning)
            if method:
                return f"dynamic_compression.rules.pipeline.{method}"
        return f"dynamic_compression.ignored_warning.{index}"

    @staticmethod
    def _extract_quoted_token(value: str) -> str | None:
        first_quote = value.find("'")
        if first_quote < 0:
            return None
        second_quote = value.find("'", first_quote + 1)
        if second_quote <= first_quote:
            return None
        token = value[first_quote + 1 : second_quote].strip()
        return token or None

    def _record_metrics_and_alerts(
        self,
        *,
        record: ToolOutputCompressionRecord,
        effective_config: DynamicCompressionConfig,
    ) -> list[CompressionAlertRecord]:
        alerts = self._metrics_recorder.record(
            record,
            alerts_config=effective_config.alerts,
        )
        for alert in alerts:
            if not is_log_level_enabled(logger, logging.WARNING):
                continue
            logger.warning(
                "Dynamic compression alert emitted",
                alert_type=alert.alert_type,
                method=alert.method,
                threshold=alert.threshold,
                observed_count=alert.observed_count,
                window_seconds=alert.window_seconds,
                category=alert.category,
                compression_level=(
                    alert.level.value if alert.level is not None else None
                ),
                warning=alert.warning,
            )
        return alerts

    @staticmethod
    def _hash_payload(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _append_warning_once(
        *,
        record: ToolOutputCompressionRecord,
        warning: str,
    ) -> None:
        if warning not in record.warnings:
            record.warnings.append(warning)

    @staticmethod
    def _already_processed_skip_warning(message: ChatMessage) -> str | None:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        if metadata.get("_compacted"):
            return "skipped_already_processed_compaction"
        if not isinstance(message.content, str):
            return None
        if _COMPACTED_STUB_MARKER in message.content:
            return "skipped_already_processed_compaction"
        if (
            _SYSTEM_REMINDER_MARKER in message.content
            and "artifact" in message.content.lower()
        ):
            return "skipped_already_processed_artifact_preview"
        return None

    @staticmethod
    def _build_correlation_id(record: ToolOutputCompressionRecord) -> str:
        source = "|".join(
            [
                record.tool_call_id or "-",
                record.identity.tool_name,
                record.identity.command_signature or "-",
                record.original_sha256 or "-",
                record.compressed_sha256 or "-",
                str(record.saved_bytes),
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _should_insert_recovery_hint(
        *,
        record: ToolOutputCompressionRecord,
        marker_config: CompressionMarkerConfig,
        content_type: str,
        hint_in_text: bool,
    ) -> bool:
        if not hint_in_text:
            return False
        if not record.recovery_persisted or not record.recovery_handle:
            return False
        if content_type != "text":
            return False
        if not marker_config.enabled:
            return False
        return getattr(marker_config.style, "value", "") != "none"

    @staticmethod
    def _append_recovery_hint(*, content: str, handle: str) -> str:
        suffix = f"[RECOVERY_HANDLE:{handle}]"
        if not content:
            return suffix
        if content.endswith("\n"):
            return f"{content}{suffix}"
        return f"{content}\n{suffix}"

    @staticmethod
    def _finalize_record_fields(
        *,
        record: ToolOutputCompressionRecord,
        final_content: str,
        output_started_at: float,
    ) -> None:
        record.compressed_bytes = len(final_content.encode("utf-8"))
        record.saved_bytes = max(0, record.original_bytes - record.compressed_bytes)
        record.methods_applied = [
            method.name for method in record.methods if method.applied
        ]
        record.elapsed_total_ms = round(
            (time.perf_counter() - output_started_at) * 1000.0,
            3,
        )
        record.fallback_applied = record.failed_open or any(
            method.skipped_reason for method in record.methods
        )
        if record.failure_reason is None:
            for method in record.methods:
                if method.error:
                    record.failure_reason = method.error
                    break
            if record.failure_reason is None and record.failed_open:
                record.failure_reason = "pipeline_fail_open"

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Approximate token count using the 4-characters heuristic."""
        if not text:
            return 0
        return (len(text) + 3) // 4

    async def _run_pipeline_with_escalation(
        self,
        *,
        original_content: str,
        context,
        pipeline: list[str],
        level: CompressionLevel,
        max_level: CompressionLevel,
        target_token_budget: int | None,
        time_budget_ms: int,
        runtime_strategy_overrides: dict[str, CompressionStrategy],
    ) -> tuple[
        str,
        list[CompressionMethodRecord],
        bool,
        CompressionLevel,
        str | None,
    ]:
        levels = self._levels_between(level, max_level)
        best_content: str | None = None
        best_records: list[CompressionMethodRecord] = []
        best_level = level
        best_failed_open = False
        best_meets_budget = False
        observed_failed_open = False
        budget_reason: str | None = None
        started_at = time.perf_counter()

        for candidate_level in levels:
            if self._is_time_budget_exceeded(
                started_at=started_at,
                time_budget_ms=time_budget_ms,
            ):
                observed_failed_open = True
                budget_reason = _TIME_BUDGET_EXCEEDED_REASON
                break

            content, records, failed_open, budget_exhausted = (
                await self._run_single_level_pipeline(
                    content=original_content,
                    context=context,
                    pipeline=pipeline,
                    level=candidate_level,
                    started_at=started_at,
                    time_budget_ms=time_budget_ms,
                    runtime_strategy_overrides=runtime_strategy_overrides,
                )
            )
            if budget_exhausted:
                failed_open = True
                budget_reason = _TIME_BUDGET_EXCEEDED_REASON
            observed_failed_open = observed_failed_open or failed_open
            meets_budget = (
                target_token_budget is not None
                and self.estimate_tokens(content) <= target_token_budget
            )
            if self._is_better_escalation_candidate(
                candidate_content=content,
                candidate_failed_open=failed_open,
                candidate_meets_budget=meets_budget,
                best_content=best_content,
                best_failed_open=best_failed_open,
                best_meets_budget=best_meets_budget,
            ):
                best_content = content
                best_records = records
                best_level = candidate_level
                best_failed_open = failed_open
                best_meets_budget = meets_budget
            if budget_exhausted:
                break

            if target_token_budget is None:
                break
            if meets_budget and not failed_open:
                break

        if best_content is None:
            return (
                original_content,
                [],
                observed_failed_open,
                level,
                budget_reason,
            )

        return (
            best_content,
            best_records,
            observed_failed_open or best_failed_open,
            best_level,
            budget_reason,
        )

    @staticmethod
    def _is_better_escalation_candidate(
        *,
        candidate_content: str,
        candidate_failed_open: bool,
        candidate_meets_budget: bool,
        best_content: str | None,
        best_failed_open: bool,
        best_meets_budget: bool,
    ) -> bool:
        if best_content is None:
            return True
        candidate_key = ToolOutputCompressionService._escalation_candidate_key(
            content=candidate_content,
            failed_open=candidate_failed_open,
            meets_budget=candidate_meets_budget,
        )
        best_key = ToolOutputCompressionService._escalation_candidate_key(
            content=best_content,
            failed_open=best_failed_open,
            meets_budget=best_meets_budget,
        )
        return candidate_key < best_key

    @staticmethod
    def _escalation_candidate_key(
        *,
        content: str,
        failed_open: bool,
        meets_budget: bool,
    ) -> tuple[int, int, int, int]:
        return (
            1 if failed_open else 0,
            0 if meets_budget else 1,
            len(content.encode("utf-8")),
            ToolOutputCompressionService.estimate_tokens(content),
        )

    async def _run_single_level_pipeline(
        self,
        *,
        content: str,
        context,
        pipeline: list[str],
        level: CompressionLevel,
        started_at: float,
        time_budget_ms: int,
        runtime_strategy_overrides: dict[str, CompressionStrategy],
    ) -> tuple[str, list[CompressionMethodRecord], bool, bool]:
        current_content = content
        method_records: list[CompressionMethodRecord] = []
        failed_open = False

        for method_index, method_name in enumerate(pipeline):
            if method_index and method_index % _METHOD_YIELD_INTERVAL == 0:
                await asyncio.sleep(0)

            in_bytes = len(current_content.encode("utf-8"))
            if self._is_time_budget_exceeded(
                started_at=started_at,
                time_budget_ms=time_budget_ms,
            ):
                failed_open = True
                method_records.append(
                    self._build_budget_skipped_record(
                        method_name=method_name,
                        payload_bytes=in_bytes,
                    )
                )
                return current_content, method_records, failed_open, True

            strategy = runtime_strategy_overrides.get(method_name)
            if strategy is None:
                strategy = self._strategy_registry.get(method_name)
            start = time.perf_counter()
            if strategy is None:
                method_records.append(
                    CompressionMethodRecord(
                        name=method_name,
                        applied=False,
                        elapsed_ms=0.0,
                        original_bytes=in_bytes,
                        result_bytes=in_bytes,
                        skipped_reason="unavailable_method",
                    )
                )
                continue

            try:
                result_content = strategy.compress(
                    current_content,
                    context=context,
                    level=level,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0
            except Exception as exc:  # - fail-open boundary
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                failed_open = True
                method_records.append(
                    CompressionMethodRecord(
                        name=method_name,
                        applied=False,
                        elapsed_ms=elapsed_ms,
                        original_bytes=in_bytes,
                        result_bytes=in_bytes,
                        error=str(exc),
                    )
                )
                break

            out_bytes = len(result_content.encode("utf-8"))
            if out_bytes > in_bytes:
                method_records.append(
                    CompressionMethodRecord(
                        name=method_name,
                        applied=False,
                        elapsed_ms=elapsed_ms,
                        original_bytes=in_bytes,
                        result_bytes=in_bytes,
                        skipped_reason="size_increase",
                    )
                )
                continue

            applied = result_content != current_content
            method_records.append(
                CompressionMethodRecord(
                    name=method_name,
                    applied=applied,
                    elapsed_ms=elapsed_ms,
                    original_bytes=in_bytes,
                    result_bytes=out_bytes,
                )
            )
            current_content = result_content

            if self._is_time_budget_exceeded(
                started_at=started_at,
                time_budget_ms=time_budget_ms,
            ):
                failed_open = True
                next_method_idx = method_index + 1
                if next_method_idx < len(pipeline):
                    method_records.append(
                        self._build_budget_skipped_record(
                            method_name=pipeline[next_method_idx],
                            payload_bytes=out_bytes,
                        )
                    )
                return current_content, method_records, failed_open, True

        return current_content, method_records, failed_open, False

    def _build_runtime_strategy_overrides(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        overrides: dict[str, CompressionStrategy] = {}
        overrides.update(self._build_directory_tree_summary_override(effective_config))
        overrides.update(self._build_search_results_grouping_override(effective_config))
        overrides.update(self._build_file_detail_levels_override(effective_config))
        overrides.update(self._build_output_pattern_match_override(effective_config))
        overrides.update(self._build_diff_compact_override(effective_config))
        overrides.update(self._build_pytest_failure_focus_override(effective_config))
        overrides.update(self._build_json_ndjson_structural_override(effective_config))
        overrides.update(self._build_xml_machine_safeguard_override(effective_config))
        overrides.update(self._build_log_line_dedupe_override(effective_config))
        overrides.update(
            self._build_sensitive_field_projection_override(effective_config)
        )
        return overrides

    def _build_directory_tree_summary_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("directory_tree_summary")
        if type(
            strategy
        ) is not DirectoryTreeSummaryStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "directory_tree_summary": DirectoryTreeSummaryStrategy(
                    noise_directories=effective_config.noise_directories,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build directory_tree_summary runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_search_results_grouping_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("search_results_grouping")
        if type(
            strategy
        ) is not SearchResultsGroupingStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "search_results_grouping": SearchResultsGroupingStrategy(
                    max_matches_per_file=effective_config.search_max_matches_per_file,
                    max_total_groups=effective_config.search_max_total_groups,
                    context_lines=effective_config.search_context_lines,
                    max_line_length=effective_config.search_max_line_length,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build search_results_grouping runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_file_detail_levels_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("file_detail_levels")
        if type(
            strategy
        ) is not FileDetailLevelsStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "file_detail_levels": FileDetailLevelsStrategy(
                    detail_mode=effective_config.file_detail_mode,
                    fallback_mode=effective_config.file_detail_fallback_mode,
                    auto_full_max_lines=effective_config.file_detail_auto_full_max_lines,
                    auto_structure_max_lines=effective_config.file_detail_auto_structure_max_lines,
                    include_line_numbers=effective_config.file_detail_include_line_numbers,
                    max_lines=effective_config.file_detail_max_lines,
                    last_n_lines=effective_config.file_detail_last_n_lines,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build file_detail_levels runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_output_pattern_match_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("output_pattern_match")
        if type(
            strategy
        ) is not OutputPatternMatchStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "output_pattern_match": OutputPatternMatchStrategy(
                    rules=[
                        OutputPatternMatchRule(
                            pattern=rule.pattern,
                            message=rule.message,
                            unless=rule.unless,
                            fallback_message=rule.fallback_message,
                        )
                        for rule in effective_config.output_pattern_rules
                    ],
                    regex_timeout_ms=effective_config.output_pattern_regex_timeout_ms,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build output_pattern_match runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_diff_compact_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("diff_compact")
        if type(
            strategy
        ) is not DiffCompactStrategy or not self._is_runtime_tunable_strategy(strategy):
            return {}
        try:
            return {
                "diff_compact": DiffCompactStrategy(
                    max_hunk_lines=effective_config.diff_max_lines_per_hunk,
                    max_total_lines=effective_config.diff_max_total_lines,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build diff_compact runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_pytest_failure_focus_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("pytest_failure_focus")
        if type(strategy) is not PytestFailureFocusStrategy:
            return {}
        min_lines_value: object | None = effective_config.pytest_failure_focus_min_lines
        if min_lines_value is None:
            return {}
        if isinstance(min_lines_value, bool):
            return {}
        if isinstance(min_lines_value, int):
            min_lines = max(0, min_lines_value)
        elif isinstance(min_lines_value, str):
            try:
                min_lines = max(0, int(min_lines_value))
            except (TypeError, ValueError):
                logger.debug(
                    "Invalid pytest_failure_focus_min_lines runtime override %r; "
                    "using registered strategy.",
                    min_lines_value,
                )
                return {}
        else:
            logger.debug(
                "Invalid pytest_failure_focus_min_lines runtime override %r; "
                "using registered strategy.",
                min_lines_value,
            )
            return {}
        return {
            "pytest_failure_focus": PytestFailureFocusStrategy(min_lines=min_lines),
        }

    def _build_json_ndjson_structural_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("json_ndjson_structural")
        if type(
            strategy
        ) is not JsonNdjsonStructuralStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "json_ndjson_structural": JsonNdjsonStructuralStrategy(
                    max_depth=effective_config.json_structural_max_depth,
                    max_keys_per_object=effective_config.json_structural_max_keys_per_object,
                    max_array_elements=effective_config.json_structural_max_array_elements,
                    string_max_len=effective_config.json_structural_string_max_len,
                    min_bytes=effective_config.json_structural_min_bytes,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build json_ndjson_structural runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_xml_machine_safeguard_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("xml_machine_safeguard")
        if type(
            strategy
        ) is not XmlMachineSafeguardStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "xml_machine_safeguard": XmlMachineSafeguardStrategy(
                    text_max_len=effective_config.xml_safeguard_text_max_len,
                    min_bytes=effective_config.xml_safeguard_min_bytes,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build xml_machine_safeguard runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_log_line_dedupe_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("log_line_dedupe")
        if type(
            strategy
        ) is not LogLineDedupeStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "log_line_dedupe": LogLineDedupeStrategy(
                    min_repeat=effective_config.log_dedupe_min_repeat,
                    min_bytes=effective_config.log_dedupe_min_bytes,
                )
            }
        except Exception:
            logger.debug(
                "Failed to build log_line_dedupe runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    def _build_sensitive_field_projection_override(
        self,
        effective_config: DynamicCompressionConfig,
    ) -> dict[str, CompressionStrategy]:
        strategy = self._strategy_registry.get("sensitive_field_projection")
        if type(
            strategy
        ) is not SensitiveFieldProjectionStrategy or not self._is_runtime_tunable_strategy(
            strategy
        ):
            return {}
        try:
            return {
                "sensitive_field_projection": SensitiveFieldProjectionStrategy(
                    skip_command_prefixes=tuple(
                        effective_config.sensitive_projection_skip_prefixes
                    ),
                )
            }
        except Exception:
            logger.debug(
                "Failed to build sensitive_field_projection runtime strategy override; "
                "using registered strategy.",
                exc_info=True,
            )
            return {}

    @staticmethod
    def _is_runtime_tunable_strategy(strategy: object | None) -> bool:
        if strategy is None:
            return False
        return bool(
            getattr(strategy, _DYNAMIC_CONFIG_RUNTIME_TUNABLE_ATTR, False) is True
        )

    @staticmethod
    def _is_time_budget_exceeded(*, started_at: float, time_budget_ms: int) -> bool:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return elapsed_ms >= float(time_budget_ms)

    @staticmethod
    def _build_budget_skipped_record(
        *,
        method_name: str,
        payload_bytes: int,
    ) -> CompressionMethodRecord:
        return CompressionMethodRecord(
            name=method_name,
            applied=False,
            elapsed_ms=0.0,
            original_bytes=payload_bytes,
            result_bytes=payload_bytes,
            skipped_reason=_TIME_BUDGET_EXCEEDED_REASON,
        )

    @staticmethod
    def _levels_between(
        start: CompressionLevel,
        end: CompressionLevel,
    ) -> list[CompressionLevel]:
        order = [
            CompressionLevel.CONSERVATIVE,
            CompressionLevel.BALANCED,
            CompressionLevel.AGGRESSIVE,
        ]
        start_idx = order.index(start)
        end_idx = order.index(end)
        if end_idx < start_idx:
            end_idx = start_idx
        return order[start_idx : end_idx + 1]

    @staticmethod
    def _explicit_format_diagnostic_note(
        *,
        record: ToolOutputCompressionRecord,
        selected_rule_name: str | None,
        decision_reason: str,
    ) -> str | None:
        if not record.identity.explicit_format_flags:
            return None
        flags = ",".join(record.identity.explicit_format_flags)
        parts = [f"flags=[{flags}]", f"path_decision={decision_reason}"]
        if selected_rule_name:
            parts.append(f"selected_rule={selected_rule_name}")
        return "; ".join(parts)

    def _log_output_evaluation(
        self,
        *,
        record: ToolOutputCompressionRecord,
        selected_rule_name: str | None,
        declared_pipeline: list[str],
        enabled_pipeline: list[str],
        decision_reason: str,
        output_started_at: float,
    ) -> None:
        record.explicit_format_note = self._explicit_format_diagnostic_note(
            record=record,
            selected_rule_name=selected_rule_name,
            decision_reason=decision_reason,
        )
        # Avoid high-volume debug noise for routine pass-through paths.
        if (
            not record.applied
            and not record.failed_open
            and decision_reason in _NOISY_NOOP_DECISION_REASONS
        ):
            return
        should_emit_info = record.applied or record.failed_open
        if should_emit_info:
            if not is_log_level_enabled(logger, logging.INFO):
                return
            log_level = "info"
            log_fn = logger.info
        else:
            if not is_log_level_enabled(logger, logging.DEBUG):
                return
            log_level = "debug"
            log_fn = logger.debug

        methods_attempted = [method.name for method in record.methods]
        if not methods_attempted:
            methods_attempted = list(enabled_pipeline)
        methods_applied = [method.name for method in record.methods if method.applied]
        elapsed_methods_ms = round(
            sum(method.elapsed_ms for method in record.methods),
            3,
        )
        elapsed_total_ms = (
            record.elapsed_total_ms
            if record.elapsed_total_ms > 0
            else round((time.perf_counter() - output_started_at) * 1000.0, 3)
        )

        log_fn(
            "Tool output compression evaluated",
            log_level=log_level,
            decision_reason=decision_reason,
            tool_call_id=record.tool_call_id,
            tool_name=record.identity.tool_name,
            tool_category=record.identity.tool_category,
            command_signature=record.identity.command_signature,
            command_prefix=record.identity.command_prefix,
            explicit_format_flags=list(record.identity.explicit_format_flags),
            explicit_format_note=record.explicit_format_note,
            bytes_in=record.original_bytes,
            bytes_out=record.compressed_bytes,
            bytes_saved=record.saved_bytes,
            selected_rule=selected_rule_name,
            declared_pipeline=list(declared_pipeline),
            enabled_pipeline=list(enabled_pipeline),
            methods_attempted=methods_attempted,
            methods_applied=methods_applied,
            elapsed_methods_ms=elapsed_methods_ms,
            elapsed_total_ms=elapsed_total_ms,
            failed_open=record.failed_open,
            fallback_applied=record.fallback_applied,
            failure_reason=record.failure_reason,
            warnings=list(record.warnings),
            compression_level=record.final_level.value,
            marker_inserted=record.marker_inserted,
            applied=record.applied,
            correlation_id=record.correlation_id,
            original_sha256=record.original_sha256,
            compressed_sha256=record.compressed_sha256,
            recovery_handle=record.recovery_handle,
            recovery_persisted=record.recovery_persisted,
            recovery_hint_inserted=record.recovery_hint_inserted,
        )
