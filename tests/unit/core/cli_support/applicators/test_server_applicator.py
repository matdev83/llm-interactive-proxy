"""Unit tests for ServerApplicator.

Test-Driven Development: Write tests first (RED), then implement (GREEN).

Requirements:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
- 6.5: Each applicator is testable in isolation with mock AppConfig
- 9.1: Unit tests for each domain applicator
"""

from __future__ import annotations

import argparse
import os
from unittest import mock

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class TestServerApplicator:
    """Unit tests for ServerApplicator class."""

    @pytest.fixture
    def applicator(self):
        """Create a ServerApplicator instance."""
        from src.core.cli_support.applicators.server_applicator import ServerApplicator

        return ServerApplicator()

    @pytest.fixture
    def empty_args(self) -> CliArgs:
        """Create empty CLI arguments namespace."""
        return argparse.Namespace(
            host=None,
            port=None,
            anthropic_port=None,
            timeout=None,
            command_prefix=None,
            force_context_window=None,
            enable_activity_tracking=None,
            request_dedup_window=None,
            disable_request_dedup=None,
            thinking_budget=None,
            disable_stale_acp_agent_kills=None,
            stale_acp_agent_kill_idle_seconds=None,
        )

    @pytest.fixture
    def overrides(self) -> CliOverrides:
        """Create empty overrides dictionary."""
        return {}

    @pytest.fixture
    def resolution(self) -> ParameterResolution:
        """Create parameter resolution tracker."""
        return ParameterResolution()

    def test_apply_host(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that host argument is applied correctly."""
        empty_args.host = "192.168.1.100"
        applicator.apply(empty_args, overrides, resolution)

        assert overrides.get("host") == "192.168.1.100"
        assert resolution.is_set("host")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "host" in cli_params

    def test_apply_port(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that port argument is applied correctly and sets environment variable."""
        empty_args.port = 9090
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("port") == 9090
            assert os.environ.get("PROXY_PORT") == "9090"
            assert resolution.is_set("port")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "port" in cli_params

    def test_apply_anthropic_port(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that anthropic_port argument is applied correctly."""
        empty_args.anthropic_port = 8181
        applicator.apply(empty_args, overrides, resolution)

        assert overrides.get("anthropic_port") == 8181
        assert resolution.is_set("anthropic_port")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "anthropic_port" in cli_params

    def test_apply_timeout(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that timeout argument is applied correctly."""
        empty_args.timeout = 120
        applicator.apply(empty_args, overrides, resolution)

        assert overrides.get("proxy_timeout") == 120
        assert resolution.is_set("proxy_timeout")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "proxy_timeout" in cli_params

    def test_apply_command_prefix(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that command_prefix argument is applied correctly and sets environment variable."""
        empty_args.command_prefix = "/custom"
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("command_prefix") == "/custom"
            assert os.environ.get("COMMAND_PREFIX") == "/custom"
            assert resolution.is_set("command_prefix")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "command_prefix" in cli_params

    def test_apply_force_context_window(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that force_context_window argument is applied correctly and sets environment variable."""
        empty_args.force_context_window = 128000
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("context_window_override") == 128000
            assert os.environ.get("FORCE_CONTEXT_WINDOW") == "128000"
            assert resolution.is_set("context_window_override")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "context_window_override" in cli_params

    def test_apply_enable_activity_tracking(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that enable_activity_tracking argument is applied correctly."""
        empty_args.enable_activity_tracking = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("enable_activity_tracking") is True
            assert os.environ.get("ENABLE_ACTIVITY_TRACKING") == "1"
            assert resolution.is_set("enable_activity_tracking")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "enable_activity_tracking" in cli_params

    def test_apply_request_dedup_window(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that request_dedup_window argument is applied correctly."""
        empty_args.request_dedup_window = 5.0
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("request_dedup_window") == 5.0
            assert os.environ.get("LLM_REQUEST_DEDUP_WINDOW") == "5.0"
            assert resolution.is_set("request_dedup_window")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "request_dedup_window" in cli_params

    def test_apply_disable_request_dedup(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that disable_request_dedup disables deduplication."""
        empty_args.disable_request_dedup = True
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("request_dedup_window") == 0.0
            assert os.environ.get("LLM_REQUEST_DEDUP_WINDOW") == "0"
            assert resolution.is_set("request_dedup_window")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "request_dedup_window" in cli_params

    def test_apply_thinking_budget(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that thinking_budget argument is applied correctly."""
        empty_args.thinking_budget = 1024
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            # Should be in session.planning_phase.overrides.thinking_budget
            assert (
                overrides.get("session", {})
                .get("planning_phase", {})
                .get("overrides", {})
                .get("thinking_budget")
                == 1024
            )
            assert os.environ.get("THINKING_BUDGET") == "1024"
            assert resolution.is_set("session.planning_phase.overrides.thinking_budget")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "session.planning_phase.overrides.thinking_budget" in cli_params

    def test_apply_disable_stale_acp_agent_kills(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --disable-stale-acp-agent-kills is applied."""
        empty_args.disable_stale_acp_agent_kills = True
        applicator.apply(empty_args, overrides, resolution)

        assert overrides.get("disable_stale_acp_agent_kills") is True
        assert resolution.is_set("disable_stale_acp_agent_kills")
        cli_params = resolution.latest_by_source(ParameterSource.CLI)
        assert "disable_stale_acp_agent_kills" in cli_params

    def test_apply_stale_acp_agent_kill_idle_seconds(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that --stale-acp-agent-kill-idle-seconds is applied."""
        empty_args.stale_acp_agent_kill_idle_seconds = 1800.0
        with mock.patch.dict(os.environ, {}, clear=True):
            applicator.apply(empty_args, overrides, resolution)

            assert overrides.get("stale_acp_agent_kill_idle_seconds") == 1800.0
            assert os.environ.get("STALE_ACP_AGENT_KILL_IDLE_SECONDS") == "1800.0"
            assert resolution.is_set("stale_acp_agent_kill_idle_seconds")
            cli_params = resolution.latest_by_source(ParameterSource.CLI)
            assert "stale_acp_agent_kill_idle_seconds" in cli_params

    def test_no_modifications_when_all_none(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that no modifications are made when all arguments are None."""
        applicator.apply(empty_args, overrides, resolution)

        # No overrides should be added
        assert len(overrides) == 0
        # No resolution entries should be recorded
        assert len(resolution.latest_by_source(ParameterSource.CLI)) == 0

    def test_only_modifies_server_domain(
        self,
        applicator,
        empty_args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Test that applicator only modifies server-related keys (Property 3: Domain Applicator Isolation)."""
        empty_args.host = "0.0.0.0"
        empty_args.port = 3000
        empty_args.timeout = 60
        empty_args.command_prefix = "/cmd"
        empty_args.force_context_window = 64000
        empty_args.thinking_budget = 512

        applicator.apply(empty_args, overrides, resolution)

        # All keys should be server-related or nested
        allowed_keys = {
            "host",
            "port",
            "anthropic_port",
            "proxy_timeout",
            "command_prefix",
            "context_window_override",
            "enable_activity_tracking",
            "request_dedup_window",
            "disable_stale_acp_agent_kills",
            "stale_acp_agent_kill_idle_seconds",
            "session",  # Contains nested thinking_budget
        }
        for key in overrides:
            assert (
                key in allowed_keys
            ), f"ServerApplicator modified unexpected key: {key}"
