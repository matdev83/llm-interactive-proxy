from __future__ import annotations

import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers._compression_registration import (
    register_tool_output_compression_services,
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
from src.core.interfaces.tool_identity_resolver_interface import IToolIdentityResolver
from src.core.interfaces.tool_output_compression_interface import (
    IToolOutputCompressionService,
)
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.dynamic_compression_config_resolver import (
    DynamicCompressionConfigResolver,
)
from src.core.services.legacy_compression_compatibility_resolver import (
    LegacyCompressionCompatibilityResolver,
)
from src.core.services.marker_renderer import MarkerRenderer
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def test_compression_contracts_resolve_to_singleton_implementations() -> None:
    services = ServiceCollection()
    register_tool_output_compression_services(
        services=services, logger=logging.getLogger(__name__)
    )
    provider = services.build_service_provider(run_post_build_hooks=False)

    registry = provider.get_required_service(CompressionStrategyRegistry)
    registry_interface: ICompressionStrategyRegistry = provider.get_required_service(
        cast(type, ICompressionStrategyRegistry)
    )
    assert registry_interface is registry

    identity_resolver = provider.get_required_service(ToolIdentityResolver)
    identity_resolver_interface: IToolIdentityResolver = provider.get_required_service(
        cast(type, IToolIdentityResolver)
    )
    assert identity_resolver_interface is identity_resolver

    rule_selector = provider.get_required_service(RuleBasedStrategySelector)
    rule_selector_interface: ICompressionRuleEvaluator = provider.get_required_service(
        cast(type, ICompressionRuleEvaluator)
    )
    assert rule_selector_interface is rule_selector

    marker_renderer = provider.get_required_service(MarkerRenderer)
    marker_renderer_interface: ICompressionMarkerRenderer = (
        provider.get_required_service(cast(type, ICompressionMarkerRenderer))
    )
    assert marker_renderer_interface is marker_renderer

    config_resolver = provider.get_required_service(DynamicCompressionConfigResolver)
    config_resolver_interface: ICompressionConfigProvider = (
        provider.get_required_service(cast(type, ICompressionConfigProvider))
    )
    assert config_resolver_interface is config_resolver

    legacy_resolver = provider.get_required_service(
        LegacyCompressionCompatibilityResolver
    )
    legacy_resolver_interface: ILegacyCompressionCompatibilityResolver = (
        provider.get_required_service(
            cast(type, ILegacyCompressionCompatibilityResolver)
        )
    )
    assert legacy_resolver_interface is legacy_resolver

    compression_service = provider.get_required_service(ToolOutputCompressionService)
    compression_service_interface: IToolOutputCompressionService = (
        provider.get_required_service(cast(type, IToolOutputCompressionService))
    )
    assert compression_service_interface is compression_service


def test_compression_registry_factory_populates_default_method_set() -> None:
    services = ServiceCollection()
    register_tool_output_compression_services(
        services=services, logger=logging.getLogger(__name__)
    )
    provider = services.build_service_provider(run_post_build_hooks=False)

    registry = provider.get_required_service(CompressionStrategyRegistry)
    assert registry.available_method_names() == [
        "ansi_normalize",
        "diagnostics_grouping",
        "diff_compact",
        "directory_tree_summary",
        "failure_focus_generic",
        "file_detail_levels",
        "group_paths",
        "json_ndjson_structural",
        "line_dedupe",
        "log_line_dedupe",
        "output_pattern_match",
        "pytest_failure_focus",
        "search_results_grouping",
        "sensitive_field_projection",
        "truncate_failure_preserving",
        "xml_machine_safeguard",
    ]
