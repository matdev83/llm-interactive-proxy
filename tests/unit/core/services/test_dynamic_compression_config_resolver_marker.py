from __future__ import annotations

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionMarkerConfig,
    CompressionRule,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.dynamic_compression_config_resolver import (
    DynamicCompressionConfigResolver,
)
from src.core.services.marker_renderer import MarkerRenderer


def test_resolver_keeps_registry_methods_absent_from_config_methods() -> None:
    resolver = DynamicCompressionConfigResolver()
    config = DynamicCompressionConfig(
        enabled=True,
        methods={"configured": True},
        rules=[
            CompressionRule(
                name="registry-backed",
                pipeline=["registry_only", "configured"],
            )
        ],
    )

    resolved = resolver.resolve(
        config,
        available_methods=["configured", "registry_only"],
    )

    assert resolved.config.rules[0].pipeline == ["registry_only", "configured"]
    assert all("registry_only" not in warning for warning in resolved.warnings)


def test_resolver_warns_for_unknown_and_unavailable_rule_methods() -> None:
    resolver = DynamicCompressionConfigResolver()
    config = DynamicCompressionConfig(
        enabled=True,
        methods={"configured_unavailable": True},
        rules=[
            CompressionRule(
                name="mixed",
                pipeline=["configured_unavailable", "unknown_everywhere"],
            )
        ],
    )

    resolved = resolver.resolve(config, available_methods=["other_available"])

    assert resolved.config.rules[0].pipeline == []
    assert any(
        "references unavailable method 'configured_unavailable'" in warning
        for warning in resolved.warnings
    )
    assert any(
        "references unknown method 'unknown_everywhere'" in warning
        for warning in resolved.warnings
    )


def test_render_marker_stable_format_without_trailing_spaces() -> None:
    renderer = MarkerRenderer()
    marker = renderer.render_marker(
        marker_config=CompressionMarkerConfig(
            enabled=True,
            include_sizes=True,
            include_methods=True,
        ),
        level=CompressionLevel.BALANCED,
        methods=["line_dedupe", "ansi_normalize"],
        original_bytes=200,
        compressed_bytes=120,
    )

    assert (
        marker
        == "[COMPRESSED level=balanced methods=line_dedupe,ansi_normalize saved=80B]"
    )
    assert not marker.endswith(" ]")


def test_render_marker_methods_only_format_is_stable() -> None:
    renderer = MarkerRenderer()
    marker = renderer.render_marker(
        marker_config=CompressionMarkerConfig(
            enabled=True,
            include_sizes=False,
            include_methods=True,
        ),
        level=CompressionLevel.AGGRESSIVE,
        methods=["line_dedupe"],
        original_bytes=200,
        compressed_bytes=20,
    )

    assert marker == "[COMPRESSED methods=line_dedupe]"


def test_apply_marker_replaces_existing_prefix_without_spacing_artifacts() -> None:
    renderer = MarkerRenderer()
    context = ToolOutputContext.for_text(
        tool_name="shell",
        tool_category="command_execution",
        content="payload",
    )

    rendered, inserted = renderer.apply_marker(
        context=context,
        content="[COMPRESSED methods=old ]  \n\npayload",
        marker_config=CompressionMarkerConfig(enabled=True),
        level=CompressionLevel.CONSERVATIVE,
        methods=["line_dedupe"],
        original_bytes=10,
        compressed_bytes=8,
    )

    assert inserted is True
    assert (
        rendered
        == "[COMPRESSED level=conservative methods=line_dedupe saved=2B]\npayload"
    )


def test_resolver_warns_for_unknown_options_and_invalid_overrides() -> None:
    resolver = DynamicCompressionConfigResolver()
    config = DynamicCompressionConfig.model_validate(
        {
            "enabled": True,
            "disable_categories": ["unknown_category"],
            "disable_methods": ["unknown_method"],
            "unknown_option": "value",
        }
    )

    resolved = resolver.resolve(
        config,
        available_methods=["line_dedupe", "declarative_rule_filter"],
    )

    assert resolved.config.disable_categories == []
    assert resolved.config.disable_methods == []
    assert any(
        "Unknown dynamic compression category override ignored" in warning
        for warning in resolved.warnings
    )
    assert any(
        "Unknown dynamic compression method override ignored" in warning
        for warning in resolved.warnings
    )
    assert any(
        "Unknown dynamic_compression option ignored: 'unknown_option'" in warning
        for warning in resolved.warnings
    )
