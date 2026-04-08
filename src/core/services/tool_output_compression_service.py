"""Deterministic orchestration service for dynamic tool-output compression."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionRule,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import (
    CompressionMethodRecord,
    ToolOutputCompressionBatchResult,
    ToolOutputCompressionRecord,
)
from src.core.interfaces.compression_strategy_registry_interface import (
    CompressionStrategy,
)
from src.core.services.compression_strategies import (
    DiffCompactStrategy,
    DirectoryTreeSummaryStrategy,
    FileDetailLevelsStrategy,
    OutputPatternMatchRule,
    OutputPatternMatchStrategy,
    SearchResultsGroupingStrategy,
)
from src.core.services.compression_strategy_registry import (
    CompressionStrategyRegistry,
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
    ) -> None:
        self._strategy_registry = strategy_registry or CompressionStrategyRegistry()
        self._identity_resolver = identity_resolver or ToolIdentityResolver()
        self._selector = selector or RuleBasedStrategySelector()
        self._marker_renderer = marker_renderer or MarkerRenderer()
        self._config_resolver = config_resolver or DynamicCompressionConfigResolver()

    async def compress_messages(
        self,
        *,
        messages: Sequence[ChatMessage],
        config: DynamicCompressionConfig,
        target_token_budget: int | None = None,
    ) -> ToolOutputCompressionBatchResult:
        snapshot = self._config_resolver.create_runtime_snapshot(config)
        resolved = self._config_resolver.resolve(
            snapshot,
            available_methods=self._strategy_registry.available_method_names(),
        )
        effective_config = resolved.config
        runtime_strategy_overrides = self._build_runtime_strategy_overrides(
            effective_config
        )

        updated_messages: list[ChatMessage] = []
        records: list[ToolOutputCompressionRecord] = []
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
                warnings=list(resolved.warnings),
            )
            records.append(record)
            output_started_at = time.perf_counter()
            selected_rule_name: str | None = None
            declared_pipeline: list[str] = []
            enabled_pipeline: list[str] = []

            if not effective_config.enabled:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="compression_disabled",
                    output_started_at=output_started_at,
                )
                continue
            if context.byte_size < effective_config.min_bytes:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="below_min_bytes",
                    output_started_at=output_started_at,
                )
                continue
            if not effective_config.is_category_enabled(context.identity.tool_category):
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="category_disabled",
                    output_started_at=output_started_at,
                )
                continue
            if context.identity.tool_name in effective_config.disable_tools:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="tool_disabled",
                    output_started_at=output_started_at,
                )
                continue
            if context.identity.command_prefix and any(
                context.identity.command_prefix.startswith(prefix)
                for prefix in effective_config.disable_command_prefixes
            ):
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="command_prefix_disabled",
                    output_started_at=output_started_at,
                )
                continue

            selected_rule = self._selector.select_rule(context, effective_config)
            if selected_rule is None:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="no_matching_rule",
                    output_started_at=output_started_at,
                )
                continue
            selected_rule_name = selected_rule.name
            declared_pipeline = list(selected_rule.pipeline)

            pipeline = [
                method_name
                for method_name in selected_rule.pipeline
                if effective_config.is_method_enabled(method_name)
            ]
            enabled_pipeline = list(pipeline)
            if not pipeline:
                updated_messages.append(message)
                self._log_output_evaluation(
                    record=record,
                    selected_rule_name=selected_rule_name,
                    declared_pipeline=declared_pipeline,
                    enabled_pipeline=enabled_pipeline,
                    decision_reason="no_enabled_pipeline_methods",
                    output_started_at=output_started_at,
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
                rule=selected_rule,
                pipeline=pipeline,
                level=effective_config.level,
                max_level=effective_config.max_level,
                target_token_budget=target_token_budget,
                time_budget_ms=effective_config.time_budget_ms_per_output,
                runtime_strategy_overrides=runtime_strategy_overrides,
            )
            if budget_reason is not None:
                record.warnings.append(budget_reason)

            final_content = compressed_content
            marker_inserted = False
            if final_content != message.content:
                final_content, marker_inserted = self._marker_renderer.apply_marker(
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

            final_bytes = len(final_content.encode("utf-8"))
            record.methods = method_records
            record.failed_open = failed_open
            record.final_level = final_level
            record.marker_inserted = marker_inserted
            record.compressed_bytes = final_bytes
            record.applied = final_content != message.content

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

        return ToolOutputCompressionBatchResult(
            messages=updated_messages,
            records=records,
            warnings=list(resolved.warnings),
        )

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Approximate token count using the RTK 4-chars heuristic."""
        if not text:
            return 0
        return (len(text) + 3) // 4

    async def _run_pipeline_with_escalation(
        self,
        *,
        original_content: str,
        context,
        rule: CompressionRule,
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
        final_content = original_content
        final_records: list[CompressionMethodRecord] = []
        final_failed_open = False
        final_level = level
        budget_reason: str | None = None
        started_at = time.perf_counter()

        for candidate_level in levels:
            if self._is_time_budget_exceeded(
                started_at=started_at,
                time_budget_ms=time_budget_ms,
            ):
                final_failed_open = True
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
            if not records and budget_exhausted:
                final_failed_open = failed_open
                break

            final_content = content
            final_records = records
            final_failed_open = failed_open
            final_level = candidate_level
            if budget_exhausted:
                break

            if target_token_budget is None:
                break
            if self.estimate_tokens(content) <= target_token_budget:
                break

        return (
            final_content,
            final_records,
            final_failed_open,
            final_level,
            budget_reason,
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
        elapsed_total_ms = round(
            (time.perf_counter() - output_started_at) * 1000.0,
            3,
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
            bytes_in=record.original_bytes,
            bytes_out=record.compressed_bytes,
            selected_rule=selected_rule_name,
            declared_pipeline=list(declared_pipeline),
            enabled_pipeline=list(enabled_pipeline),
            methods_attempted=methods_attempted,
            methods_applied=methods_applied,
            elapsed_methods_ms=elapsed_methods_ms,
            elapsed_total_ms=elapsed_total_ms,
            failed_open=record.failed_open,
            warnings=list(record.warnings),
            compression_level=record.final_level.value,
            marker_inserted=record.marker_inserted,
            applied=record.applied,
        )
