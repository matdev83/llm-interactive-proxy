"""
Tool output compression service DI registrations.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider


def register_tool_output_compression_services(
    services: ServiceCollection, logger: logging.Logger
) -> None:
    """Register ToolOutputCompressionService and supporting dependencies."""
    from src.core.domain.configuration.dynamic_compression_config import (
        DynamicCompressionConfig,
    )
    from src.core.interfaces.compression_config_provider_interface import (
        ICompressionConfigProvider,
    )
    from src.core.interfaces.compression_marker_renderer_interface import (
        ICompressionMarkerRenderer,
    )
    from src.core.interfaces.compression_rule_evaluator_interface import (
        ICompressionRuleEvaluator,
    )
    from src.core.interfaces.compression_strategy_registry_interface import (
        ICompressionStrategyRegistry,
    )
    from src.core.interfaces.legacy_compression_compatibility_resolver_interface import (
        ILegacyCompressionCompatibilityResolver,
    )
    from src.core.interfaces.tool_identity_resolver_interface import (
        IToolIdentityResolver,
    )
    from src.core.interfaces.tool_output_compression_interface import (
        IToolOutputCompressionService,
    )
    from src.core.services.compression_metrics_recorder import (
        CompressionMetricsRecorder,
    )
    from src.core.services.compression_recovery_store import CompressionRecoveryStore
    from src.core.services.compression_strategies import (
        AnsiNormalizeStrategy,
        DiagnosticsGroupingStrategy,
        DiffCompactStrategy,
        DirectoryTreeSummaryStrategy,
        FailureFocusGenericStrategy,
        FailurePreservingTruncateStrategy,
        FileDetailLevelsStrategy,
        LineDedupeStrategy,
        MutatingSuccessAckStrategy,
        OutputPatternMatchRule,
        OutputPatternMatchStrategy,
        PytestFailureFocusStrategy,
        SearchResultsGroupingStrategy,
        SimilarityGroupingStrategy,
        StatsExtractionSummaryStrategy,
    )
    from src.core.services.compression_strategy_registry import (
        CompressionStrategyRegistry,
    )
    from src.core.services.declarative_compression_rules import (
        DeclarativeRuleRegistry,
    )
    from src.core.services.dynamic_compression_config_resolver import (
        DynamicCompressionConfigResolver,
    )
    from src.core.services.legacy_compression_compatibility_resolver import (
        LegacyCompressionCompatibilityResolver,
    )
    from src.core.services.marker_renderer import MarkerRenderer
    from src.core.services.rule_based_strategy_selector import (
        RuleBasedStrategySelector,
    )
    from src.core.services.structural_compression_strategies import (
        JsonNdjsonStructuralStrategy,
        LogLineDedupeStrategy,
        SensitiveFieldProjectionStrategy,
        XmlMachineSafeguardStrategy,
    )
    from src.core.services.tool_identity_resolver import ToolIdentityResolver
    from src.core.services.tool_output_compression_service import (
        ToolOutputCompressionService,
    )

    def _compression_registry_factory(
        _provider: IServiceProvider,
    ) -> CompressionStrategyRegistry:
        tunable_attr = "__dynamic_config_runtime_tunable__"

        def _mark_runtime_tunable(strategy: Any) -> Any:
            setattr(strategy, tunable_attr, True)
            return strategy

        registry = CompressionStrategyRegistry()
        defaults = DynamicCompressionConfig()
        registry.register("ansi_normalize", AnsiNormalizeStrategy())
        registry.register("line_dedupe", LineDedupeStrategy())
        registry.register("group_paths", SimilarityGroupingStrategy())
        registry.register(
            "directory_tree_summary",
            _mark_runtime_tunable(
                DirectoryTreeSummaryStrategy(
                    noise_directories=defaults.noise_directories,
                )
            ),
        )
        registry.register(
            "search_results_grouping",
            _mark_runtime_tunable(
                SearchResultsGroupingStrategy(
                    max_matches_per_file=defaults.search_max_matches_per_file,
                    max_total_groups=defaults.search_max_total_groups,
                    context_lines=defaults.search_context_lines,
                    max_line_length=defaults.search_max_line_length,
                )
            ),
        )
        registry.register(
            "file_detail_levels",
            _mark_runtime_tunable(
                FileDetailLevelsStrategy(
                    detail_mode=defaults.file_detail_mode,
                    fallback_mode=defaults.file_detail_fallback_mode,
                    auto_full_max_lines=defaults.file_detail_auto_full_max_lines,
                    auto_structure_max_lines=defaults.file_detail_auto_structure_max_lines,
                    include_line_numbers=defaults.file_detail_include_line_numbers,
                    max_lines=defaults.file_detail_max_lines,
                    last_n_lines=defaults.file_detail_last_n_lines,
                )
            ),
        )
        registry.register(
            "truncate_failure_preserving", FailurePreservingTruncateStrategy()
        )
        registry.register(
            "output_pattern_match",
            _mark_runtime_tunable(
                OutputPatternMatchStrategy(
                    rules=[
                        OutputPatternMatchRule(
                            pattern=rule.pattern,
                            message=rule.message,
                            unless=rule.unless,
                            fallback_message=rule.fallback_message,
                        )
                        for rule in defaults.output_pattern_rules
                    ],
                    regex_timeout_ms=defaults.output_pattern_regex_timeout_ms,
                )
            ),
        )
        registry.register(
            "diff_compact",
            _mark_runtime_tunable(
                DiffCompactStrategy(
                    max_hunk_lines=defaults.diff_max_lines_per_hunk,
                    max_total_lines=defaults.diff_max_total_lines,
                )
            ),
        )
        registry.register("pytest_failure_focus", PytestFailureFocusStrategy())
        registry.register("failure_focus_generic", FailureFocusGenericStrategy())
        registry.register("diagnostics_grouping", DiagnosticsGroupingStrategy())
        registry.register(
            "json_ndjson_structural",
            _mark_runtime_tunable(
                JsonNdjsonStructuralStrategy(
                    max_depth=defaults.json_structural_max_depth,
                    max_keys_per_object=defaults.json_structural_max_keys_per_object,
                    max_array_elements=defaults.json_structural_max_array_elements,
                    string_max_len=defaults.json_structural_string_max_len,
                    min_bytes=defaults.json_structural_min_bytes,
                )
            ),
        )
        registry.register(
            "xml_machine_safeguard",
            _mark_runtime_tunable(
                XmlMachineSafeguardStrategy(
                    text_max_len=defaults.xml_safeguard_text_max_len,
                    min_bytes=defaults.xml_safeguard_min_bytes,
                )
            ),
        )
        registry.register(
            "log_line_dedupe",
            _mark_runtime_tunable(
                LogLineDedupeStrategy(
                    min_repeat=defaults.log_dedupe_min_repeat,
                    min_bytes=defaults.log_dedupe_min_bytes,
                )
            ),
        )
        registry.register(
            "sensitive_field_projection",
            _mark_runtime_tunable(
                SensitiveFieldProjectionStrategy(
                    skip_command_prefixes=tuple(
                        defaults.sensitive_projection_skip_prefixes
                    ),
                )
            ),
        )
        registry.register("mutating_success_ack", MutatingSuccessAckStrategy())
        registry.register("stats_extraction_summary", StatsExtractionSummaryStrategy())
        return registry

    register_singleton_if_absent(
        services,
        CompressionStrategyRegistry,
        implementation_factory=_compression_registry_factory,
    )
    register_singleton_if_absent(services, ToolIdentityResolver)
    register_singleton_if_absent(services, RuleBasedStrategySelector)
    register_singleton_if_absent(services, MarkerRenderer)
    register_singleton_if_absent(services, DynamicCompressionConfigResolver)
    register_singleton_if_absent(services, DeclarativeRuleRegistry)
    register_singleton_if_absent(services, LegacyCompressionCompatibilityResolver)
    register_singleton_if_absent(services, CompressionMetricsRecorder)
    register_singleton_if_absent(services, CompressionRecoveryStore)

    def _register_interface_alias(
        interface_type: type,
        implementation_type: type,
        interface_name: str,
    ) -> None:
        def _interface_factory(
            provider: IServiceProvider,
            implementation: type = implementation_type,
        ) -> Any:
            return provider.get_required_service(implementation)

        try:
            register_singleton_if_absent(
                services,
                interface_type,
                implementation_factory=_interface_factory,  # type: ignore[type-abstract]
            )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register %s interface: %s",
                    interface_name,
                    e,
                    exc_info=True,
                )

    _register_interface_alias(
        cast(type, ICompressionStrategyRegistry),
        CompressionStrategyRegistry,
        "ICompressionStrategyRegistry",
    )
    _register_interface_alias(
        cast(type, IToolIdentityResolver),
        ToolIdentityResolver,
        "IToolIdentityResolver",
    )
    _register_interface_alias(
        cast(type, ICompressionRuleEvaluator),
        RuleBasedStrategySelector,
        "ICompressionRuleEvaluator",
    )
    _register_interface_alias(
        cast(type, ICompressionMarkerRenderer),
        MarkerRenderer,
        "ICompressionMarkerRenderer",
    )
    _register_interface_alias(
        cast(type, ICompressionConfigProvider),
        DynamicCompressionConfigResolver,
        "ICompressionConfigProvider",
    )
    _register_interface_alias(
        cast(type, ILegacyCompressionCompatibilityResolver),
        LegacyCompressionCompatibilityResolver,
        "ILegacyCompressionCompatibilityResolver",
    )

    def _tool_output_compression_factory(
        provider: IServiceProvider,
    ) -> ToolOutputCompressionService:
        return ToolOutputCompressionService(
            strategy_registry=provider.get_required_service(
                CompressionStrategyRegistry
            ),
            identity_resolver=provider.get_required_service(ToolIdentityResolver),
            selector=provider.get_required_service(RuleBasedStrategySelector),
            marker_renderer=provider.get_required_service(MarkerRenderer),
            config_resolver=provider.get_required_service(
                DynamicCompressionConfigResolver
            ),
            metrics_recorder=provider.get_required_service(CompressionMetricsRecorder),
            recovery_store=provider.get_required_service(CompressionRecoveryStore),
            declarative_rule_registry=provider.get_required_service(
                DeclarativeRuleRegistry
            ),
        )

    register_singleton_if_absent(
        services,
        ToolOutputCompressionService,
        implementation_factory=_tool_output_compression_factory,
    )
    _register_interface_alias(
        cast(type, IToolOutputCompressionService),
        ToolOutputCompressionService,
        "IToolOutputCompressionService",
    )
