from __future__ import annotations

from src.core.services.legacy_compression_compatibility_resolver import (
    LegacyCompressionCompatibilityResolver,
)


def test_connector_truncation_precedence_prefers_compaction() -> None:
    resolver = LegacyCompressionCompatibilityResolver()

    decision, diagnostics = resolver.resolve_connector_truncation_with_diagnostics(
        connector_max_chars=200,
        connector_max_lines=20,
        compaction_enabled=True,
        dynamic_compression_enabled=False,
    )

    assert decision.enabled is False
    assert decision.effective_max_chars is None
    assert decision.effective_max_lines is None
    assert decision.source == "history_compaction"
    assert decision.overridden is True
    assert diagnostics.applied == ["compaction.enabled"]
    assert diagnostics.ignored == [
        "connector.tool_output_truncate_chars",
        "connector.tool_output_truncate_lines",
    ]
    assert diagnostics.overridden == [
        "connector.tool_output_truncate_chars",
        "connector.tool_output_truncate_lines",
    ]
    assert diagnostics.warnings == [
        "Connector-level tool output truncation ignored because history compaction or dynamic compression is enabled."
    ]


def test_connector_truncation_precedence_uses_connector_when_not_overridden() -> None:
    resolver = LegacyCompressionCompatibilityResolver()

    decision, diagnostics = resolver.resolve_connector_truncation_with_diagnostics(
        connector_max_chars=120,
        connector_max_lines=None,
        compaction_enabled=False,
        dynamic_compression_enabled=False,
    )

    assert decision.enabled is True
    assert decision.effective_max_chars == 120
    assert decision.effective_max_lines is None
    assert decision.source == "connector"
    assert diagnostics.applied == ["connector.tool_output_truncate_chars"]
    assert diagnostics.inactive == ["connector.tool_output_truncate_lines"]
    assert diagnostics.warnings == []


def test_connector_truncation_precedence_tracks_unset_controls() -> None:
    resolver = LegacyCompressionCompatibilityResolver()

    decision, diagnostics = resolver.resolve_connector_truncation_with_diagnostics(
        connector_max_chars=None,
        connector_max_lines=None,
        compaction_enabled=False,
        dynamic_compression_enabled=False,
    )

    assert decision.enabled is False
    assert decision.source == "connector_unset"
    assert diagnostics.applied == []
    assert diagnostics.ignored == []
    assert diagnostics.inactive == [
        "connector.tool_output_truncate_chars",
        "connector.tool_output_truncate_lines",
    ]
    assert diagnostics.warnings == []


def test_connector_truncation_precedence_is_deterministic() -> None:
    resolver = LegacyCompressionCompatibilityResolver()

    first = resolver.resolve_connector_truncation_with_diagnostics(
        connector_max_chars=90,
        connector_max_lines=None,
        compaction_enabled=True,
        dynamic_compression_enabled=True,
    )
    second = resolver.resolve_connector_truncation_with_diagnostics(
        connector_max_chars=90,
        connector_max_lines=None,
        compaction_enabled=True,
        dynamic_compression_enabled=True,
    )

    assert first == second
    decision, diagnostics = first
    assert decision.source == "history_compaction+dynamic_compression"
    assert diagnostics.applied == ["compaction.enabled", "dynamic_compression.enabled"]
