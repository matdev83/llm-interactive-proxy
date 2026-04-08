"""Deterministic dynamic compression config resolver with fail-open semantics."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionRule,
    DynamicCompressionConfig,
)
from src.core.interfaces.model_bases import DomainModel


class ResolvedDynamicCompressionConfig(DomainModel):
    """Resolved config snapshot plus operator diagnostics."""

    config: DynamicCompressionConfig
    warnings: list[str] = Field(default_factory=list)


class DynamicCompressionConfigResolver:
    """Resolve config deterministically and fail-open on invalid scopes."""

    _level_rank: dict[CompressionLevel, int] = {
        CompressionLevel.CONSERVATIVE: 0,
        CompressionLevel.BALANCED: 1,
        CompressionLevel.AGGRESSIVE: 2,
    }

    def create_runtime_snapshot(
        self,
        config: DynamicCompressionConfig,
    ) -> DynamicCompressionConfig:
        """Return an immutable per-request snapshot."""
        return config.model_copy(deep=True)

    def resolve(
        self,
        config: DynamicCompressionConfig,
        *,
        available_methods: Iterable[str],
    ) -> ResolvedDynamicCompressionConfig:
        warnings: list[str] = []
        normalized_available_methods = {
            name.strip() for name in available_methods if name
        }

        level = config.level
        max_level = config.max_level
        if self._level_rank[max_level] < self._level_rank[level]:
            max_level = level
            warnings.append(
                "dynamic_compression.max_level was below dynamic_compression.level; "
                "using level as max_level to keep deterministic escalation bounds."
            )

        known_categories = {key.lower() for key in config.categories}
        disable_categories: list[str] = []
        for category in config.disable_categories:
            normalized = category.lower()
            if normalized not in known_categories:
                warnings.append(
                    "Unknown dynamic compression category override ignored: "
                    f"{category!r}"
                )
                continue
            disable_categories.append(category)

        known_methods = set(config.methods)
        known_or_available_methods = known_methods | normalized_available_methods
        disable_methods: list[str] = []
        for method in config.disable_methods:
            if method not in known_methods:
                warnings.append(
                    "Unknown dynamic compression method override ignored: "
                    f"{method!r}"
                )
                continue
            disable_methods.append(method)

        normalized_rules: list[CompressionRule] = []
        for rule in config.rules:
            filtered_pipeline: list[str] = []
            for method_name in rule.pipeline:
                if method_name not in known_or_available_methods:
                    warnings.append(
                        f"Rule '{rule.name}' references unknown method "
                        f"{method_name!r}; method ignored (fail-open)."
                    )
                    continue
                if method_name not in normalized_available_methods:
                    warnings.append(
                        f"Rule '{rule.name}' references unavailable method "
                        f"{method_name!r}; method ignored (fail-open)."
                    )
                    continue
                filtered_pipeline.append(method_name)
            normalized_rules.append(
                rule.model_copy(update={"pipeline": filtered_pipeline})
            )

        if config.model_extra:
            for extra_key in sorted(config.model_extra.keys()):
                warnings.append(
                    "Unknown dynamic_compression option ignored: " f"{extra_key!r}"
                )

        resolved_config = config.model_copy(
            update={
                "level": level,
                "max_level": max_level,
                "disable_categories": disable_categories,
                "disable_methods": disable_methods,
                "rules": normalized_rules,
            }
        )
        return ResolvedDynamicCompressionConfig(
            config=resolved_config, warnings=warnings
        )
