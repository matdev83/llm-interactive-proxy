"""Legacy/dynamic compression precedence resolver."""

from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class PytestCompatibilityDecision(DomainModel):
    """Deterministic precedence decision for pytest compression migration."""

    effective_enabled: bool
    source: str
    overridden: bool = False
    warning: str | None = None


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

    _LEGACY_PYTEST_CONTROL = "session.pytest_compression_enabled"
    _DYNAMIC_PYTEST_CONTROL = "dynamic_compression.methods.pytest_failure_focus"
    _CONNECTOR_TRUNCATION_CHARS_CONTROL = "connector.tool_output_truncate_chars"
    _CONNECTOR_TRUNCATION_LINES_CONTROL = "connector.tool_output_truncate_lines"
    _COMPACTION_CONTROL = "compaction.enabled"
    _DYNAMIC_COMPRESSION_CONTROL = "dynamic_compression.enabled"

    def resolve_pytest_mode(
        self,
        *,
        legacy_pytest_enabled: bool,
        dynamic_pytest_mode: bool | str | None,
    ) -> PytestCompatibilityDecision:
        if dynamic_pytest_mode in (None, "inherit_legacy"):
            return PytestCompatibilityDecision(
                effective_enabled=legacy_pytest_enabled,
                source="legacy",
                overridden=False,
            )

        if isinstance(dynamic_pytest_mode, bool):
            overridden = dynamic_pytest_mode != legacy_pytest_enabled
            return PytestCompatibilityDecision(
                effective_enabled=dynamic_pytest_mode,
                source="dynamic_override",
                overridden=overridden,
            )

        return PytestCompatibilityDecision(
            effective_enabled=legacy_pytest_enabled,
            source="legacy",
            warning=(
                "Invalid dynamic pytest mode detected; "
                "falling back to legacy pytest compression setting."
            ),
        )

    def resolve_pytest_mode_with_diagnostics(
        self,
        *,
        legacy_pytest_enabled: bool,
        dynamic_pytest_mode: bool | str | None,
    ) -> tuple[
        PytestCompatibilityDecision,
        DynamicCompressionCompatibilityDiagnostics,
    ]:
        """Resolve pytest mode and emit migration-safe diagnostics."""
        decision = self.resolve_pytest_mode(
            legacy_pytest_enabled=legacy_pytest_enabled,
            dynamic_pytest_mode=dynamic_pytest_mode,
        )
        diagnostics = DynamicCompressionCompatibilityDiagnostics()

        if decision.source == "dynamic_override":
            diagnostics.applied.append(self._DYNAMIC_PYTEST_CONTROL)
        else:
            diagnostics.applied.append(self._LEGACY_PYTEST_CONTROL)
            if dynamic_pytest_mode not in (None, "inherit_legacy"):
                diagnostics.ignored.append(self._DYNAMIC_PYTEST_CONTROL)

        if decision.overridden:
            diagnostics.overridden.append(self._LEGACY_PYTEST_CONTROL)
        if not decision.effective_enabled:
            diagnostics.inactive.append(self._DYNAMIC_PYTEST_CONTROL)
        if decision.warning:
            diagnostics.warnings.append(decision.warning)
        if decision.overridden and decision.source == "dynamic_override":
            diagnostics.warnings.append(
                "dynamic_compression.methods.pytest_failure_focus overrides "
                "session.pytest_compression_enabled for the dynamic request-path "
                "pipeline; legacy response-time pytest filtering may still differ."
            )

        return decision, diagnostics

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

        if compaction_enabled or dynamic_compression_enabled:
            applied_controls: list[str] = []
            if compaction_enabled:
                applied_controls.append(self._COMPACTION_CONTROL)
            if dynamic_compression_enabled:
                applied_controls.append(self._DYNAMIC_COMPRESSION_CONTROL)
            diagnostics.applied.extend(applied_controls)

            warning: str | None = None
            if configured_controls:
                diagnostics.ignored.extend(configured_controls)
                diagnostics.overridden.extend(configured_controls)
                diagnostics.inactive.extend(configured_controls)
                warning = (
                    "Connector-level tool output truncation ignored because "
                    "history compaction or dynamic compression is enabled."
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
