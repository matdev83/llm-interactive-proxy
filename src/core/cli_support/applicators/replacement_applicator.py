"""Replacement Applicator - Extracts and applies random model replacement CLI arguments.

This applicator handles:
- replacement_enabled
- replacement_probability
- replacement_rules (new conditional replacement rules)
- replacement_turn_count

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource
from src.core.domain.configuration.replacement_rule import ReplacementRule


class ReplacementApplicator:
    """Applies random model replacement CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply random model replacement CLI arguments to configuration overrides."""
        replacement_overrides: dict[str, Any] = {}

        if getattr(args, "replacement_enabled", None) is not None:
            replacement_overrides["enabled"] = args.replacement_enabled
            os.environ["REPLACEMENT_ENABLED"] = (
                "true" if args.replacement_enabled else "false"
            )
            resolution.record(
                "replacement.enabled",
                args.replacement_enabled,
                ParameterSource.CLI,
                origin="--enable-replacement",
            )

        if getattr(args, "replacement_probability", None) is not None:
            replacement_overrides["probability"] = args.replacement_probability
            os.environ["REPLACEMENT_PROBABILITY"] = str(args.replacement_probability)
            resolution.record(
                "replacement.probability",
                args.replacement_probability,
                ParameterSource.CLI,
                origin="--replacement-probability",
            )

        # Handle new replacement_rules format
        replacement_rules = getattr(args, "replacement_rules", None)
        if replacement_rules is not None:
            # Parse rule strings into ReplacementRule objects
            parsed_rules = []
            for rule_str in replacement_rules:
                rule = self._parse_replacement_rule(rule_str)
                parsed_rules.append(rule)

            replacement_overrides["replacement_rules"] = parsed_rules
            # Store as JSON array in environment variable
            rules_json = json.dumps(
                [
                    {
                        "from_pattern": rule.from_pattern,
                        "to_backend": rule.to_backend,
                        "to_model": rule.to_model,
                    }
                    for rule in parsed_rules
                ]
            )
            os.environ["REPLACEMENT_RULES"] = rules_json
            resolution.record(
                "replacement.replacement_rules",
                parsed_rules,
                ParameterSource.CLI,
                origin="--random-model-replacement-from-to",
            )

        # Backward compatibility: handle old replacement_backend_model
        if getattr(args, "replacement_backend_model", None) is not None:
            # Convert to replacement_rules format if not already set
            if "replacement_rules" not in replacement_overrides:
                rule_str = f"*={args.replacement_backend_model}"
                rule = self._parse_replacement_rule(rule_str)
                replacement_overrides["replacement_rules"] = [rule]
            # Also set backend_model for backward compatibility
            replacement_overrides["backend_model"] = args.replacement_backend_model
            os.environ["REPLACEMENT_BACKEND_MODEL"] = args.replacement_backend_model
            resolution.record(
                "replacement.backend_model",
                args.replacement_backend_model,
                ParameterSource.CLI,
                origin="--replacement-backend-model (deprecated)",
            )

        if getattr(args, "replacement_turn_count", None) is not None:
            replacement_overrides["turn_count"] = args.replacement_turn_count
            os.environ["REPLACEMENT_TURN_COUNT"] = str(args.replacement_turn_count)
            resolution.record(
                "replacement.turn_count",
                args.replacement_turn_count,
                ParameterSource.CLI,
                origin="--replacement-turn-count",
            )

        if replacement_overrides:
            overrides["replacement"] = replacement_overrides

    def _parse_replacement_rule(self, rule_str: str) -> ReplacementRule:
        """Parse a replacement rule string into a ReplacementRule object.

        Args:
            rule_str: Rule string in format '<from>=<to>'

        Returns:
            ReplacementRule object

        Raises:
            ValueError: If the rule format is invalid
        """
        if "=" not in rule_str:
            raise ValueError(
                f"Invalid replacement rule format '{rule_str}'. "
                f"Expected '<from-model-name>=<to-model-name>'"
            )

        parts = rule_str.split("=", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid replacement rule format '{rule_str}'. "
                f"Expected exactly one '=' separator"
            )

        from_pattern = parts[0].strip()
        to_part = parts[1].strip()

        if not from_pattern:
            raise ValueError(
                f"Invalid replacement rule format '{rule_str}'. "
                f"<from-model-name> cannot be empty"
            )

        if ":" not in to_part:
            raise ValueError(
                f"Invalid replacement rule format '{rule_str}'. "
                f"<to-model-name> must be in format 'backend:model'"
            )

        to_backend, to_model = to_part.split(":", 1)
        if not to_backend or not to_model:
            raise ValueError(
                f"Invalid replacement rule format '{rule_str}'. "
                f"Both backend and model must be specified in <to-model-name>"
            )

        return ReplacementRule(
            from_pattern=from_pattern,
            to_backend=to_backend,
            to_model=to_model,
        )
