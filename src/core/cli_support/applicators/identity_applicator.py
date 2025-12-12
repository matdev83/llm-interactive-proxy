"""Identity Applicator - Extracts and applies client identity CLI arguments.

This applicator handles:
- identity_user_agent, identity_url, identity_title

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class IdentityApplicator:
    """Applies client identity CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply identity CLI arguments to configuration overrides."""
        identity_overrides: dict[str, Any] = {}

        if getattr(args, "identity_user_agent", None) is not None:
            user_agent_override = identity_overrides.setdefault("user_agent", {})
            user_agent_override["mode"] = "override"
            user_agent_override["override_value"] = args.identity_user_agent
            resolution.record(
                "identity.user_agent.override_value",
                args.identity_user_agent,
                ParameterSource.CLI,
                origin="--identity-user-agent",
            )
            resolution.record(
                "identity.user_agent.mode",
                "override",
                ParameterSource.CLI,
                origin="--identity-user-agent",
            )

        if getattr(args, "identity_url", None) is not None:
            url_override = identity_overrides.setdefault("url", {})
            url_override["mode"] = "override"
            url_override["override_value"] = args.identity_url
            resolution.record(
                "identity.url.override_value",
                args.identity_url,
                ParameterSource.CLI,
                origin="--identity-url",
            )
            resolution.record(
                "identity.url.mode",
                "override",
                ParameterSource.CLI,
                origin="--identity-url",
            )

        if getattr(args, "identity_title", None) is not None:
            title_override = identity_overrides.setdefault("title", {})
            title_override["mode"] = "override"
            title_override["override_value"] = args.identity_title
            resolution.record(
                "identity.title.override_value",
                args.identity_title,
                ParameterSource.CLI,
                origin="--identity-title",
            )
            resolution.record(
                "identity.title.mode",
                "override",
                ParameterSource.CLI,
                origin="--identity-title",
            )

        if identity_overrides:
            overrides["identity"] = identity_overrides
