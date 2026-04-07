"""Backend Applicator - Extracts and applies backend-related CLI arguments.

This applicator handles:
- default_backend, static_route
- disable_gemini_oauth_fallback, disable_hybrid_backend
- disable_gemini_oauth_reasoning_prompt_injection
- hybrid_backend_repeat_messages, reasoning_injection_probability
- hybrid_reasoning_model_timeout, hybrid_reasoning_force_initial_turns
- API keys (openrouter, gemini, zai, zenmux)
- model_aliases
- Backend debugging overrides

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


def _normalize_api_key_value(value: str | Sequence[str]) -> list[str]:
    """Normalize CLI-supplied API key values into the expected list format."""
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return [item for item in value if item and item.strip()]


class BackendApplicator:
    """Applies backend-related CLI arguments to configuration.

    Handles:
    - default_backend: Default backend selection
    - static_route: Force specific backend:model routing
    - hybrid settings: Hybrid backend configuration
    - API keys: Various backend API keys
    - model_aliases: Model name rewrite rules
    - Debugging overrides: Backend-specific debugging toggles
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply backend-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        backend_overrides: dict[str, Any] = {}

        self._apply_default_backend(args, backend_overrides, resolution)
        self._apply_static_route(args, backend_overrides, resolution)
        self._apply_hybrid_settings(args, backend_overrides, resolution)
        self._apply_api_keys(args, backend_overrides, resolution, overrides)
        self._apply_model_aliases(args, overrides, resolution)
        self._apply_debugging_overrides(args, backend_overrides, resolution)

        # Add backend overrides to main overrides if any
        if backend_overrides:
            overrides["backends"] = backend_overrides

    def _apply_default_backend(
        self,
        args: CliArgs,
        backend_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply default_backend argument."""
        if getattr(args, "default_backend", None) is not None:
            backend_overrides["default_backend"] = args.default_backend
            os.environ["LLM_BACKEND"] = args.default_backend
            resolution.record(
                "backends.default_backend",
                args.default_backend,
                ParameterSource.CLI,
                origin="--default-backend",
            )

    def _apply_static_route(
        self,
        args: CliArgs,
        backend_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply static_route argument."""
        if getattr(args, "static_route", None) is not None:
            backend_overrides["static_route"] = args.static_route
            os.environ["STATIC_ROUTE"] = args.static_route
            resolution.record(
                "backends.static_route",
                args.static_route,
                ParameterSource.CLI,
                origin="--static-route",
            )

    def _apply_hybrid_settings(
        self,
        args: CliArgs,
        backend_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply hybrid backend settings."""
        if getattr(args, "disable_gemini_oauth_fallback", False):
            backend_overrides["disable_gemini_oauth_fallback"] = True
            os.environ["DISABLE_GEMINI_OAUTH_FALLBACK"] = "1"
            resolution.record(
                "backends.disable_gemini_oauth_fallback",
                True,
                ParameterSource.CLI,
                origin="--disable-gemini-oauth-fallback",
            )

        if getattr(args, "disable_gemini_oauth_reasoning_prompt_injection", False):
            backend_overrides["disable_gemini_oauth_reasoning_prompt_injection"] = True
            os.environ["DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION"] = "1"
            resolution.record(
                "backends.disable_gemini_oauth_reasoning_prompt_injection",
                True,
                ParameterSource.CLI,
                origin="--disable-gemini-oauth-reasoning-prompt-injection",
            )

        if getattr(args, "disable_hybrid_backend", False):
            backend_overrides["disable_hybrid_backend"] = True
            os.environ["DISABLE_HYBRID_BACKEND"] = "1"
            resolution.record(
                "backends.disable_hybrid_backend",
                True,
                ParameterSource.CLI,
                origin="--disable-hybrid-backend",
            )

        if getattr(args, "hybrid_backend_repeat_messages", False):
            backend_overrides["hybrid_backend_repeat_messages"] = True
            os.environ["HYBRID_BACKEND_REPEAT_MESSAGES"] = "1"
            resolution.record(
                "backends.hybrid_backend_repeat_messages",
                True,
                ParameterSource.CLI,
                origin="--hybrid-backend-repeat-messages",
            )

        if getattr(args, "reasoning_injection_probability", None) is not None:
            backend_overrides["reasoning_injection_probability"] = (
                args.reasoning_injection_probability
            )
            resolution.record(
                "backends.reasoning_injection_probability",
                args.reasoning_injection_probability,
                ParameterSource.CLI,
                origin="--reasoning-injection-probability",
            )

        if getattr(args, "hybrid_reasoning_model_timeout", None) is not None:
            backend_overrides["hybrid_reasoning_model_timeout"] = (
                args.hybrid_reasoning_model_timeout
            )
            os.environ["HYBRID_REASONING_MODEL_TIMEOUT"] = str(
                args.hybrid_reasoning_model_timeout
            )
            resolution.record(
                "backends.hybrid_reasoning_model_timeout",
                args.hybrid_reasoning_model_timeout,
                ParameterSource.CLI,
                origin="--hybrid-reasoning-model-timeout",
            )

        if getattr(args, "hybrid_reasoning_force_initial_turns", None) is not None:
            backend_overrides["hybrid_reasoning_force_initial_turns"] = (
                args.hybrid_reasoning_force_initial_turns
            )
            os.environ["HYBRID_REASONING_FORCE_INITIAL_TURNS"] = str(
                args.hybrid_reasoning_force_initial_turns
            )
            resolution.record(
                "backends.hybrid_reasoning_force_initial_turns",
                args.hybrid_reasoning_force_initial_turns,
                ParameterSource.CLI,
                origin="--hybrid-reasoning-force-initial-turns",
            )

    def _apply_api_keys(
        self,
        args: CliArgs,
        backend_overrides: dict[str, Any],
        resolution: ParameterResolution,
        overrides: CliOverrides,
    ) -> None:
        """Apply API key arguments."""
        # OpenRouter
        if getattr(args, "openrouter_api_key", None) is not None:
            normalized_key = _normalize_api_key_value(args.openrouter_api_key)
            openrouter_overrides = backend_overrides.setdefault("openrouter", {})
            openrouter_overrides["api_key"] = normalized_key
            resolution.record(
                "backends.openrouter.api_key",
                normalized_key,
                ParameterSource.CLI,
                origin="--openrouter-api-key",
            )

        if getattr(args, "openrouter_api_base_url", None) is not None:
            openrouter_overrides = backend_overrides.setdefault("openrouter", {})
            openrouter_overrides["api_url"] = args.openrouter_api_base_url
            resolution.record(
                "backends.openrouter.api_url",
                args.openrouter_api_base_url,
                ParameterSource.CLI,
                origin="--openrouter-api-base-url",
            )

        # Gemini
        if getattr(args, "gemini_api_key", None) is not None:
            normalized_key = _normalize_api_key_value(args.gemini_api_key)
            gemini_overrides = backend_overrides.setdefault("gemini", {})
            gemini_overrides["api_key"] = normalized_key
            if normalized_key:
                os.environ["GEMINI_API_KEY"] = normalized_key[0]
            else:
                os.environ.pop("GEMINI_API_KEY", None)
            resolution.record(
                "backends.gemini.api_key",
                normalized_key,
                ParameterSource.CLI,
                origin="--gemini-api-key",
            )

        if getattr(args, "gemini_api_base_url", None) is not None:
            gemini_overrides = backend_overrides.setdefault("gemini", {})
            gemini_overrides["api_url"] = args.gemini_api_base_url
            resolution.record(
                "backends.gemini.api_url",
                args.gemini_api_base_url,
                ParameterSource.CLI,
                origin="--gemini-api-base-url",
            )

        # ZAI
        if getattr(args, "zai_api_key", None) is not None:
            normalized_key = _normalize_api_key_value(args.zai_api_key)
            zai_overrides = backend_overrides.setdefault("zai", {})
            zai_overrides["api_key"] = normalized_key
            resolution.record(
                "backends.zai.api_key",
                normalized_key,
                ParameterSource.CLI,
                origin="--zai-api-key",
            )

        # ZAI Coding Plan
        if getattr(args, "zai_coding_plan_api_key", None) is not None:
            normalized_key = _normalize_api_key_value(args.zai_coding_plan_api_key)
            coding_plan_overrides = backend_overrides.setdefault("zai-coding-plan", {})
            coding_plan_overrides["api_key"] = normalized_key
            resolution.record(
                "backends.zai-coding-plan.api_key",
                normalized_key,
                ParameterSource.CLI,
                origin="--zai-coding-plan-api-key",
            )

        # ZenMux
        if getattr(args, "zenmux_api_base_url", None) is not None:
            zenmux_overrides = backend_overrides.setdefault("zenmux", {})
            zenmux_overrides["api_url"] = args.zenmux_api_base_url
            resolution.record(
                "backends.zenmux.api_url",
                args.zenmux_api_base_url,
                ParameterSource.CLI,
                origin="--zenmux-api-base-url",
            )

    def _apply_model_aliases(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply model aliases configuration."""
        if getattr(args, "model_aliases", None) is not None:
            import json

            from src.core.config.app_config import ModelAliasRule

            cli_aliases = [
                ModelAliasRule(pattern=pattern, replacement=replacement)
                for pattern, replacement in args.model_aliases
            ]
            overrides["model_aliases"] = cli_aliases
            resolution.record(
                "model_aliases",
                [alias.model_dump() for alias in cli_aliases],
                ParameterSource.CLI,
                origin="--model-alias",
            )

            # Store in environment for other processes
            alias_data = [
                {"pattern": rule.pattern, "replacement": rule.replacement}
                for rule in cli_aliases
            ]
            os.environ["MODEL_ALIASES"] = json.dumps(alias_data)

    def _apply_debugging_overrides(
        self,
        args: CliArgs,
        backend_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply backend debugging overrides."""
        debug_flags = [
            ("enable_antigravity_backend_debugging_override", "antigravity"),
            ("enable_cline_backend_debugging_override", "cline"),
            (
                "enable_gemini_oauth_free_backend_debugging_override",
                "gemini_oauth_free",
            ),
            (
                "enable_gemini_oauth_plan_backend_debugging_override",
                "gemini_oauth_plan",
            ),
            ("enable_qwen_oauth_backend_debugging_override", "qwen_oauth"),
            ("enable_anthropic_oauth_backend_debugging_override", "anthropic_oauth"),
            (
                "enable_gemini_oauth_auto_backend_debugging_override",
                "gemini_oauth_auto",
            ),
            (
                "enable_opencode_zen_backend_debugging_override",
                "opencode_zen",
            ),
            (
                "enable_kiro_oauth_auto_backend_debugging_override",
                "kiro_oauth_auto",
            ),
            (
                "enable_openai_codex_backend_debugging_override",
                "openai_codex",
            ),
        ]

        for flag_name, backend_name in debug_flags:
            if getattr(args, flag_name, False):
                # Put the flag in the backend-specific extra config
                # e.g., backends.cline.extra.enable_cline_backend_debugging_override
                backend_key = backend_name.replace("-", "_")
                if backend_key not in backend_overrides:
                    backend_overrides[backend_key] = {}
                if "extra" not in backend_overrides[backend_key]:
                    backend_overrides[backend_key]["extra"] = {}
                backend_overrides[backend_key]["extra"][flag_name] = True

                resolution.record(
                    f"backends.{backend_key}.extra.{flag_name}",
                    True,
                    ParameterSource.CLI,
                    origin=f"--{flag_name.replace('_', '-')}",
                )
