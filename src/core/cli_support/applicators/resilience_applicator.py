"""Resilience Applicator - Applies resilience scoping CLI arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


def _flatten_cli_list(values: list[list[str]] | list[str] | None) -> list[str]:
    result: list[str] = []
    if not values:
        return result
    for entry in values:
        if isinstance(entry, list):
            for item in entry:
                stripped = str(item).strip()
                if stripped:
                    result.append(stripped)
        else:
            stripped = str(entry).strip()
            if stripped:
                result.append(stripped)
    return result


class ResilienceApplicator:
    """Applies resilience scoping CLI arguments to configuration overrides."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        resilience_overrides: dict[str, Any] = {}

        raw_personal = getattr(args, "resilience_personal_backends", None)
        if raw_personal is not None:
            personal_values = _flatten_cli_list(raw_personal)
            resilience_overrides["personal_backend_types"] = personal_values
            resolution.record(
                "resilience.personal_backend_types",
                personal_values,
                ParameterSource.CLI,
                origin="--resilience-personal-backends",
            )

        raw_shared = getattr(args, "resilience_shared_backends", None)
        if raw_shared is not None:
            shared_values = _flatten_cli_list(raw_shared)
            resilience_overrides["shared_backend_types"] = shared_values
            resolution.record(
                "resilience.shared_backend_types",
                shared_values,
                ParameterSource.CLI,
                origin="--resilience-shared-backends",
            )

        if resilience_overrides:
            overrides["resilience"] = resilience_overrides
