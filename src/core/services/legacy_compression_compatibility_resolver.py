"""Legacy/dynamic compression precedence resolver."""

from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class ConnectorTruncationCompatibilityDecision(DomainModel):
    """Deterministic precedence decision for connector-level truncation."""

    effective_max_chars: int | None = None
    effective_max_lines: int | None = None
    source: str
    overridden: bool = False
    warning: str | None = None

    @property
    def enabled(self) -> bool:
        """Whether connector-level truncation remains active."""
        return (
            self.effective_max_chars is not None or self.effective_max_lines is not None
        )


class LegacyCompressionCompatibilityResolver:
    """Resolve deterministic precedence between legacy and dynamic controls."""

    _CONNECTOR_TRUNCATION_CHARS_CONTROL = "connector.tool_output_truncate_chars"
    _CONNECTOR_TRUNCATION_LINES_CONTROL = "connector.tool_output_truncate_lines"
    _COMPACTION_CONTROL = "compaction.enabled"
    _DYNAMIC_COMPRESSION_CONTROL = "dynamic_compression.enabled"

    def resolve_connector_truncation(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> ConnectorTruncationCompatibilityDecision:
        decision, _ = self.resolve_connector_truncation_with_diagnostics(
            connector_max_chars=connector_max_chars,
            connector_max_lines=connector_max_lines,
            compaction_enabled=compaction_enabled,
            dynamic_compression_enabled=dynamic_compression_enabled,
        )
        return decision

    def resolve_connector_truncation_with_diagnostics(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> tuple[
        ConnectorTruncationCompatibilityDecision,
        ConnectorTruncationCompatibilityDiagnostics,
    ]:
        """Resolve connector truncation precedence with migration diagnostics."""
        diagnostics = ConnectorTruncationCompatibilityDiagnostics()

        configured_controls: list[str] = []
        if connector_max_chars is not None:
            configured_controls.append(self._CONNECTOR_TRUNCATION_CHARS_CONTROL)
        if connector_max_lines is not None:
            configured_controls.append(self._CONNECTOR_TRUNCATION_LINES_CONTROL)

        diagnostics.connector_truncation_configured = bool(configured_controls)

        if compaction_enabled or dynamic_compression_enabled:
            applied_controls: list[str] = []
            active_stages: list[str] = []
            if compaction_enabled:
                applied_controls.append(self._COMPACTION_CONTROL)
                active_stages.append("history_compaction")
            if dynamic_compression_enabled:
                applied_controls.append(self._DYNAMIC_COMPRESSION_CONTROL)
                active_stages.append("dynamic_compression")
            diagnostics.applied.extend(applied_controls)
            diagnostics.active_request_path_stages = list(active_stages)

            warning: str | None = None
            if configured_controls:
                diagnostics.ignored.extend(configured_controls)
                diagnostics.overridden.extend(configured_controls)
                diagnostics.inactive.extend(configured_controls)
                stage_summary = ", ".join(active_stages)
                warning = (
                    "Connector-level tool output truncation is disabled because "
                    f"request-path reduction is already active ({stage_summary}). "
                    "Rely on history compaction and/or dynamic tool-output compression "
                    "for tool payloads instead of connector truncation."
                )
                diagnostics.warnings.append(warning)
            else:
                diagnostics.inactive.extend(
                    [
                        self._CONNECTOR_TRUNCATION_CHARS_CONTROL,
                        self._CONNECTOR_TRUNCATION_LINES_CONTROL,
                    ]
                )

            if compaction_enabled and dynamic_compression_enabled:
                overlap = (
                    "Both history compaction and dynamic tool-output compression are enabled; "
                    "tool-bearing history may be reduced in multiple sequential stages "
                    "before connector translation."
                )
                diagnostics.overlap_notes.append(overlap)
                if configured_controls:
                    diagnostics.overlap_notes.append(
                        "Ambiguous overlap: connector truncation limits are configured but "
                        "would stack with request-path compaction/dynamic compression; "
                        "connector truncation stays disabled to avoid cutting the same tool "
                        "payload twice at different layers."
                    )
            elif configured_controls:
                single = active_stages[0] if active_stages else "request-path reduction"
                diagnostics.overlap_notes.append(
                    f"Connector truncation limits are ignored while {single} handles "
                    "tool-output shaping on the request path."
                )

            if compaction_enabled and dynamic_compression_enabled:
                source = "history_compaction+dynamic_compression"
            elif compaction_enabled:
                source = "history_compaction"
            else:
                source = "dynamic_compression"

            return (
                ConnectorTruncationCompatibilityDecision(
                    effective_max_chars=None,
                    effective_max_lines=None,
                    source=source,
                    overridden=bool(configured_controls),
                    warning=warning,
                ),
                diagnostics,
            )

        if configured_controls:
            diagnostics.applied.extend(configured_controls)
            if connector_max_chars is None:
                diagnostics.inactive.append(self._CONNECTOR_TRUNCATION_CHARS_CONTROL)
            if connector_max_lines is None:
                diagnostics.inactive.append(self._CONNECTOR_TRUNCATION_LINES_CONTROL)
            return (
                ConnectorTruncationCompatibilityDecision(
                    effective_max_chars=connector_max_chars,
                    effective_max_lines=connector_max_lines,
                    source="connector",
                    overridden=False,
                ),
                diagnostics,
            )

        diagnostics.inactive.extend(
            [
                self._CONNECTOR_TRUNCATION_CHARS_CONTROL,
                self._CONNECTOR_TRUNCATION_LINES_CONTROL,
            ]
        )
        return (
            ConnectorTruncationCompatibilityDecision(
                effective_max_chars=None,
                effective_max_lines=None,
                source="connector_unset",
                overridden=False,
            ),
            diagnostics,
        )


class DynamicCompressionCompatibilityDiagnostics(DomainModel):
    """Migration/compatibility diagnostics for operators."""

    applied: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    inactive: list[str] = Field(default_factory=list)
    overridden: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConnectorTruncationCompatibilityDiagnostics(DomainModel):
    """Compatibility diagnostics for connector-level truncation precedence."""

    applied: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    inactive: list[str] = Field(default_factory=list)
    overridden: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    overlap_notes: list[str] = Field(default_factory=list)
    active_request_path_stages: list[str] = Field(default_factory=list)
    connector_truncation_configured: bool = False
