"""Deterministic rule matching for dynamic compression."""

from __future__ import annotations

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionRule,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext


class RuleBasedStrategySelector:
    """Select exactly one rule using deterministic ordering."""

    def select_rule(
        self,
        context: ToolOutputContext,
        config: DynamicCompressionConfig,
    ) -> CompressionRule | None:
        ordered = sorted(
            enumerate(config.rules),
            key=lambda indexed_rule: (indexed_rule[1].priority, indexed_rule[0]),
        )
        for _, rule in ordered:
            if self._matches(rule, context):
                return rule
        return None

    def _matches(self, rule: CompressionRule, context: ToolOutputContext) -> bool:
        predicate = rule.when
        identity = context.identity

        if predicate.tool_name and predicate.tool_name != identity.tool_name:
            return False
        if (
            predicate.tool_category
            and predicate.tool_category != identity.tool_category
        ):
            return False
        if (
            predicate.command_signature
            and predicate.command_signature != identity.command_signature
        ):
            return False
        if (
            predicate.command_prefix
            and predicate.command_prefix != identity.command_prefix
        ):
            return False
        if (
            predicate.has_explicit_format is not None
            and predicate.has_explicit_format != context.has_explicit_format
        ):
            return False
        if predicate.min_bytes is not None and context.byte_size < predicate.min_bytes:
            return False
        if predicate.max_bytes is not None and context.byte_size > predicate.max_bytes:
            return False
        if predicate.content_types:
            allowed = {x.strip().lower() for x in predicate.content_types if x.strip()}
            if context.content_type.value.lower() not in allowed:
                return False
        return True
