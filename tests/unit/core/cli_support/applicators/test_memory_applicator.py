"""Unit tests for MemoryApplicator.

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


class TestMemoryApplicator:
    """Unit tests for MemoryApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a MemoryApplicator instance."""
        from src.core.cli_support.applicators.memory_applicator import MemoryApplicator

        return MemoryApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            memory_available=None,
            memory_default_enabled=None,
            memory_summary_model=None,
            memory_context_model=None,
            memory_summary_prompt=None,
            memory_context_prompt=None,
            memory_database_path=None,
            memory_session_timeout=None,
            memory_summarization_delay=None,
            memory_max_sessions_to_consider=None,
            memory_retention_days=None,
            memory_max_context_tokens=None,
            memory_max_summary_tokens=None,
            memory_max_transcript_chars=None,
            memory_summary_completion_tokens=None,
            memory_context_relevance_threshold=None,
            memory_max_buffer_size_bytes=None,
            memory_analysis_queue_maxsize=None,
            memory_analysis_timeout_seconds=None,
            memory_max_concurrent_analyses=None,
            memory_context_template=None,
            memory_single_user_mode=None,
            memory_fixed_user_id=None,
            memory_persist_transcript=None,
            memory_redaction_patterns=None,
            memory_disabled_users=None,
            memory_disabled_clients=None,
            memory_summary_prompt_version=None,
            memory_summary_schema_version=None,
            memory_require_project_discovery=None,
            memory_project_discovery_mode=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_memory_available(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_available argument is applied correctly."""
        empty_args.memory_available = True
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("available") is True
        assert resolution.is_set("memory.available")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.available" in cli_params

    def test_apply_memory_default_enabled(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_default_enabled argument is applied correctly."""
        empty_args.memory_default_enabled = False
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("default_enabled") is False
        assert resolution.is_set("memory.default_enabled")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.default_enabled" in cli_params

    def test_apply_memory_summary_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_summary_model argument is applied correctly."""
        empty_args.memory_summary_model = "openai:gpt-4"
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("summary_model") == "openai:gpt-4"
        assert resolution.is_set("memory.summary_model")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.summary_model" in cli_params

    def test_apply_memory_context_model(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_context_model argument is applied correctly."""
        empty_args.memory_context_model = "gemini:gemini-pro"
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("context_model") == "gemini:gemini-pro"
        assert resolution.is_set("memory.context_model")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.context_model" in cli_params

    def test_apply_memory_database_path(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_database_path argument is applied correctly."""
        empty_args.memory_database_path = "/tmp/memory.db"
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("database_path") == "/tmp/memory.db"
        assert resolution.is_set("memory.database_path")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.database_path" in cli_params

    def test_apply_memory_session_timeout(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_session_timeout argument is applied correctly."""
        empty_args.memory_session_timeout = 60
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("session_timeout_minutes") == 60
        assert resolution.is_set("memory.session_timeout_minutes")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.session_timeout_minutes" in cli_params

    def test_apply_memory_retention_days(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_retention_days argument is applied correctly."""
        empty_args.memory_retention_days = 30
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("retention_days") == 30
        assert resolution.is_set("memory.retention_days")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.retention_days" in cli_params

    def test_apply_memory_max_context_tokens(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_max_context_tokens argument is applied correctly."""
        empty_args.memory_max_context_tokens = 8192
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("max_context_tokens") == 8192
        assert resolution.is_set("memory.max_context_tokens")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.max_context_tokens" in cli_params

    def test_apply_memory_disabled_users(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_disabled_users argument is applied correctly as a set."""
        empty_args.memory_disabled_users = ["user1", "user2"]
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("disabled_users") == {"user1", "user2"}
        assert resolution.is_set("memory.disabled_users")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.disabled_users" in cli_params

    def test_apply_memory_disabled_clients(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_disabled_clients argument is applied correctly as a set."""
        empty_args.memory_disabled_clients = ["client1", "client2"]
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("disabled_clients") == {"client1", "client2"}
        assert resolution.is_set("memory.disabled_clients")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.disabled_clients" in cli_params

    def test_apply_memory_redaction_patterns(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that memory_redaction_patterns argument is applied correctly."""
        empty_args.memory_redaction_patterns = ["password", "api_key"]
        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert overrides["memory"].get("redaction_patterns") == [
            "password",
            "api_key",
        ]
        assert resolution.is_set("memory.redaction_patterns")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "memory.redaction_patterns" in cli_params

    def test_env_settings_applied_before_cli(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that environment settings are applied but CLI takes precedence."""
        with mock.patch.dict(os.environ, {"MEMORY_AVAILABLE": "false"}, clear=False):
            empty_args.memory_available = True
            applicator.apply(empty_args, overrides, resolution)

            assert "memory" in overrides
            assert overrides["memory"].get("available") is True

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert len(overrides) == 0
            assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0

    def test_only_modifies_memory_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies memory keys (Property 3: Domain Applicator Isolation)."""
        empty_args.memory_available = True
        empty_args.memory_default_enabled = True
        empty_args.memory_summary_model = "openai:gpt-4"
        empty_args.memory_database_path = "/tmp/memory.db"

        applicator.apply(empty_args, overrides, resolution)

        assert "memory" in overrides
        assert len(overrides) == 1
        for key in overrides:
            assert key == "memory", f"MemoryApplicator modified unexpected key: {key}"
