"""Unit tests for BackendApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
import os
from unittest import mock

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestBackendApplicator:
    """Unit tests for BackendApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a BackendApplicator instance."""
        from src.core.cli_support.applicators.backend_applicator import (
            BackendApplicator,
        )

        return BackendApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            default_backend=None,
            static_route=None,
            disable_gemini_oauth_fallback=False,
            disable_hybrid_backend=False,
            hybrid_backend_repeat_messages=False,
            reasoning_injection_probability=None,
            hybrid_reasoning_model_timeout=None,
            hybrid_reasoning_force_initial_turns=None,
            interleaved_thinking_instructions_file=None,
            openrouter_api_key=None,
            openrouter_api_base_url=None,
            gemini_api_key=None,
            gemini_api_base_url=None,
            zai_api_key=None,
            zai_coding_plan_api_key=None,
            zenmux_api_base_url=None,
            model_aliases=None,
            enable_antigravity_backend_debugging_override=False,
            enable_cline_backend_debugging_override=False,
            enable_gemini_oauth_free_backend_debugging_override=False,
            enable_gemini_oauth_plan_backend_debugging_override=False,
            enable_qwen_oauth_backend_debugging_override=False,
            enable_openai_codex_backend_debugging_override=False,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_default_backend(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that default_backend argument is applied correctly."""
        empty_args.default_backend = "openai"
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert overrides["backends"].get("default_backend") == "openai"
            assert os.environ.get("LLM_BACKEND") == "openai"
            assert resolution.is_set("backends.default_backend")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "backends.default_backend" in cli_params

    def test_apply_static_route(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that static_route argument is applied correctly."""
        empty_args.static_route = "gemini:gemini-2.5-pro"
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert overrides["backends"].get("static_route") == "gemini:gemini-2.5-pro"
            assert os.environ.get("STATIC_ROUTE") == "gemini:gemini-2.5-pro"

    def test_apply_disable_gemini_oauth_fallback(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_gemini_oauth_fallback is applied correctly."""
        empty_args.disable_gemini_oauth_fallback = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert overrides["backends"].get("disable_gemini_oauth_fallback") is True
            assert os.environ.get("DISABLE_GEMINI_OAUTH_FALLBACK") == "1"

    def test_apply_disable_hybrid_backend(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_hybrid_backend is applied correctly."""
        empty_args.disable_hybrid_backend = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert overrides["backends"].get("disable_hybrid_backend") is True
            assert os.environ.get("DISABLE_HYBRID_BACKEND") == "1"

    def test_apply_reasoning_injection_probability(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that reasoning_injection_probability is applied correctly."""
        empty_args.reasoning_injection_probability = 0.75
        applicator.apply(empty_args, overrides, resolution)

        assert "backends" in overrides
        assert overrides["backends"].get("reasoning_injection_probability") == 0.75

    def test_apply_interleaved_thinking_instructions_file(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        empty_args.interleaved_thinking_instructions_file = "config/prompts/thinker.md"
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert (
                overrides["backends"].get("interleaved_thinking_instructions_file")
                == "config/prompts/thinker.md"
            )
            assert (
                os.environ.get("INTERLEAVED_THINKING_INSTRUCTIONS_FILE")
                == "config/prompts/thinker.md"
            )
            assert resolution.is_set("backends.interleaved_thinking_instructions_file")

    def test_apply_openrouter_api_key(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that openrouter_api_key is applied correctly."""
        empty_args.openrouter_api_key = "sk-test-key"
        applicator.apply(empty_args, overrides, resolution)

        assert "backends" in overrides
        assert "openrouter" in overrides["backends"]
        assert overrides["backends"]["openrouter"].get("api_key") == ["sk-test-key"]
        assert resolution.is_set("backends.openrouter.api_key")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "backends.openrouter.api_key" in cli_params

    def test_apply_gemini_api_key(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that gemini_api_key is applied correctly."""
        empty_args.gemini_api_key = "gemini-key-123"
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert "backends" in overrides
            assert "gemini" in overrides["backends"]
            assert overrides["backends"]["gemini"].get("api_key") == ["gemini-key-123"]
            assert os.environ.get("GEMINI_API_KEY") == "gemini-key-123"

    def test_apply_backend_debugging_overrides(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that backend debugging overrides are applied correctly."""
        empty_args.enable_antigravity_backend_debugging_override = True
        empty_args.enable_cline_backend_debugging_override = True
        applicator.apply(empty_args, overrides, resolution)

        assert "backends" in overrides
        # Flags should be nested in backend-specific extra config
        assert "antigravity" in overrides["backends"]
        assert "extra" in overrides["backends"]["antigravity"]
        assert (
            overrides["backends"]["antigravity"]["extra"].get(
                "enable_antigravity_backend_debugging_override"
            )
            is True
        )
        assert "cline" in overrides["backends"]
        assert "extra" in overrides["backends"]["cline"]
        assert (
            overrides["backends"]["cline"]["extra"].get(
                "enable_cline_backend_debugging_override"
            )
            is True
        )

    def test_no_modifications_when_all_none_or_false(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None or False."""
        applicator.apply(empty_args, overrides, resolution)

        # No backends overrides should be added
        assert "backends" not in overrides

    def test_only_modifies_backends_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies backend-related keys (Property 3: Domain Applicator Isolation)."""
        empty_args.default_backend = "openai"
        empty_args.openrouter_api_key = "test-key"

        applicator.apply(empty_args, overrides, resolution)

        # Only model_aliases and backends should be modified at top level
        allowed_keys = {"backends", "model_aliases"}
        for key in overrides:
            assert (
                key in allowed_keys
            ), f"BackendApplicator modified unexpected key: {key}"
