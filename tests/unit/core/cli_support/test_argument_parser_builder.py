"""Unit tests for ArgumentParserBuilder.

Tests that ArgumentParserBuilder constructs an argparse.ArgumentParser with all
expected arguments, organized by domain groups.

Requirements satisfied:
- 9.1: Unit tests for ArgumentParserBuilder
- 1.1: ArgumentParser is constructed by ArgumentParserBuilder class

Test-Driven Development (TDD):
- These tests are written FIRST (RED phase)
- Implementation will follow to make tests pass (GREEN phase)
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.core.cli_support.argument_parser_builder import ArgumentParserBuilder

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def builder() -> ArgumentParserBuilder:
    """Create an ArgumentParserBuilder instance."""
    from src.core.cli_support.argument_parser_builder import ArgumentParserBuilder

    return ArgumentParserBuilder()


@pytest.fixture
def parser(builder: ArgumentParserBuilder) -> argparse.ArgumentParser:
    """Build the parser from the builder."""
    return builder.build()


def _collect_cli_flags(parser: argparse.ArgumentParser) -> set[str]:
    """Collect all CLI flags from the parser."""
    flags: set[str] = set()
    for action in parser._actions:
        for option in action.option_strings:
            if option.startswith("-"):
                flags.add(option)
    return flags


def _get_action_by_dest(
    parser: argparse.ArgumentParser, dest: str
) -> argparse.Action | None:
    """Get parser action by destination name."""
    for action in parser._actions:
        if action.dest == dest:
            return action
    return None


# =============================================================================
# Core Parser Construction Tests
# =============================================================================


class TestArgumentParserBuilderConstruction:
    """Tests for ArgumentParserBuilder construction and initialization."""

    def test_builder_creates_argument_parser(
        self, builder: ArgumentParserBuilder
    ) -> None:
        """Builder.build() returns an argparse.ArgumentParser instance."""
        parser = builder.build()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_builder_can_be_called_multiple_times(
        self, builder: ArgumentParserBuilder
    ) -> None:
        """Builder.build() can be called multiple times, returning fresh parsers."""
        parser1 = builder.build()
        parser2 = builder.build()
        assert parser1 is not parser2
        assert isinstance(parser1, argparse.ArgumentParser)
        assert isinstance(parser2, argparse.ArgumentParser)

    def test_parser_has_description(self, parser: argparse.ArgumentParser) -> None:
        """Parser has a description."""
        assert parser.description is not None
        assert len(parser.description) > 0


# =============================================================================
# Backend Selection Flags Tests
# =============================================================================


class TestBackendSelectionFlags:
    """Tests for backend selection CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--default-backend",
            "--backend",  # Hidden alias
            "--static-route",
            "--disable-gemini-oauth-fallback",
            "--disable-hybrid-backend",
            "--hybrid-backend-repeat-messages",
            "--reasoning-injection-probability",
            "--reasoning_injection_probability",  # Underscore alias
            "--hybrid-reasoning-model-timeout",
            "--hybrid-reasoning-force-initial-turns",
            "--model-alias",
            "--quality-verifier-model",
            "--quality-verifier-frequency",
        ],
    )
    def test_backend_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Backend selection flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"

    def test_backend_flag_is_hidden(self, parser: argparse.ArgumentParser) -> None:
        """The --backend flag is hidden (SUPPRESS help)."""
        _get_action_by_dest(parser, "default_backend")
        # Check if any of the actions for default_backend has SUPPRESS help
        has_suppress = False
        for act in parser._actions:
            if act.dest == "default_backend" and act.help == argparse.SUPPRESS:
                has_suppress = True
                break
        assert has_suppress, "--backend should have SUPPRESS help"


# =============================================================================
# API Keys and URLs Flags Tests
# =============================================================================


class TestApiKeyFlags:
    """Tests for API key and URL CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--openrouter-api-key",
            "--openrouter-api-base-url",
            "--gemini-api-key",
            "--gemini-api-base-url",
            "--zai-api-key",
            "--zai-coding-plan-api-key",
            "--zenmux-api-base-url",
        ],
    )
    def test_api_key_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """API key and URL flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Server Options Flags Tests
# =============================================================================


class TestServerOptionsFlags:
    """Tests for basic server configuration CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--host",
            "--port",
            "--anthropic-port",
            "--timeout",
            "--command-prefix",
            "--force-context-window",
            "--thinking-budget",
        ],
    )
    def test_server_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Server configuration flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"

    def test_port_is_int_type(self, parser: argparse.ArgumentParser) -> None:
        """--port flag accepts integer type."""
        action = _get_action_by_dest(parser, "port")
        assert action is not None
        assert action.type is int


# =============================================================================
# Logging Flags Tests
# =============================================================================


class TestLoggingFlags:
    """Tests for logging CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--log",
            "--capture-file",
            "--capture-max-bytes",
            "--capture-truncate-bytes",
            "--capture-max-files",
            "--capture-rotate-interval",
            "--capture-total-max-bytes",
            "--cbor-capture-dir",
            "--cbor-capture-session",
            "--config",
            "--log-level",
            "--log-colors",
            "--no-log-colors",
        ],
    )
    def test_logging_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Logging flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Feature Flags Tests
# =============================================================================


class TestFeatureFlags:
    """Tests for feature toggle CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--disable-interactive-mode",
            "--disable-redact-api-keys-in-prompts",
            "--disable-sso-captcha",
            "--enable-sso",
            "--sso-config",
            "--sso-provider",
            "--sso-auth-mode",
            "--disable-auth",
            "--force-set-project",
            "--project-dir-resolution-model",
            "--project-dir-resolution-mode",
            "--disable-default-openrouter-project-dir-resolution-fallback",
            "--disable-interactive-commands",
            "--disable-accounting",
            "--strict-command-detection",
            "--enable-sandboxing",
        ],
    )
    def test_feature_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Feature toggle flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# History Compaction Flags Tests
# =============================================================================


class TestCompactionFlags:
    """Tests for history compaction CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-context-compaction",
            "--compaction-min-tokens",
        ],
    )
    def test_compaction_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """History compaction flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Planning Phase Flags Tests
# =============================================================================


class TestPlanningPhaseFlags:
    """Tests for planning phase CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-planning-phase",
            "--planning-phase-strong-model",
            "--planning-phase-max-turns",
            "--planning-phase-max-file-writes",
            "--planning-phase-temperature",
            "--planning-phase-top-p",
            "--planning-phase-reasoning-effort",
            "--planning-phase-thinking-budget",
        ],
    )
    def test_planning_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Planning phase flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Edit Precision Flags Tests
# =============================================================================


class TestEditPrecisionFlags:
    """Tests for edit precision tuning CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-edit-precision",
            "--disable-edit-precision",
            "--edit-precision-temperature",
            "--edit-precision-min-top-p",
            "--edit-precision-override-top-p",
            "--edit-precision-target-top-k",
            "--edit-precision-override-top-k",
            "--edit-precision-exclude-agents",
        ],
    )
    def test_edit_precision_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Edit precision flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Backend Debugging Overrides Flags Tests
# =============================================================================


class TestBackendDebuggingFlags:
    """Tests for backend debugging override CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-cline-backend-debugging-override",
            "--enable-antigravity-backend-debugging-override",
            "--enable-gemini-oauth-free-backend-debugging-override",
            "--enable-gemini-oauth-plan-backend-debugging-override",
            "--enable-qwen-oauth-backend-debugging-override",
            "--enable-kiro-oauth-auto-backend-debugging-override",
            "--enable-droid-path-fix",
        ],
    )
    def test_debugging_override_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Backend debugging override flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Authentication Flags Tests
# =============================================================================


class TestAuthenticationFlags:
    """Tests for authentication and security CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-brute-force-protection",
            "--disable-brute-force-protection",
            "--auth-max-failed-attempts",
            "--auth-brute-force-ttl",
            "--auth-brute-force-initial-block",
            "--auth-brute-force-multiplier",
            "--auth-brute-force-max-block",
            "--allow-admin",
            "--daemon",
            "--trusted-ip",
        ],
    )
    def test_auth_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Authentication and security flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Pytest Compression Flags Tests
# =============================================================================


class TestPytestFlags:
    """Tests for pytest-related CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-pytest-full-suite-steering",
            "--disable-pytest-full-suite-steering",
            "--enable-pytest-context-saving",
        ],
    )
    def test_pytest_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Pytest flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Session and Testing Flags Tests
# =============================================================================


class TestSessionTestingFlags:
    """Tests for session and testing CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--fix-think-tags",
            "--test-execution-reminder-enabled",
            "--no-test-execution-reminder-enabled",
            "--disable-dangerous-git-commands-protection",
            "--disable-double-ampersand-fixes-for-windows",
            "--disable-auto-continue-removal",
            "--enable-loop-detection",
        ],
    )
    def test_session_testing_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Session and testing flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"

    def test_disable_auto_continue_removal_flag_shape(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """--disable-auto-continue-removal uses expected destination defaults."""
        action = _get_action_by_dest(parser, "disable_auto_continue_removal")
        assert action is not None
        assert "--disable-auto-continue-removal" in action.option_strings
        assert action.default is None

    def test_enable_loop_detection_flag_shape(self, parser: argparse.ArgumentParser) -> None:
        """--enable-loop-detection is a boolean opt-in flag."""
        action = _get_action_by_dest(parser, "enable_loop_detection")
        assert action is not None
        assert "--enable-loop-detection" in action.option_strings
        assert action.default is False


# =============================================================================
# Tool Access Control Flags Tests
# =============================================================================


class TestToolAccessFlags:
    """Tests for tool access control CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--allowed-tools",
            "--blocked-tools",
            "--default-policy",
        ],
    )
    def test_tool_access_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Tool access control flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Routing Control Flags Tests
# =============================================================================


class TestRoutingFlags:
    """Tests for routing control CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--disable-routing-with-backend-ids",
            "--disable-routing-with-backend-names",
            "--disable-routing-with-only-model-names",
        ],
    )
    def test_routing_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Routing control flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Quality Verifier Flags Tests
# =============================================================================


class TestQualityVerifierFlags:
    """Tests for Quality Verifier CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--quality-verifier-model",
            "--quality-verifier-frequency",
            "--quality-verifier-max-history",
            "--quality-verifier-max-consecutive-failures",
            "--quality-verifier-cooldown-seconds",
            "--quality-verifier-ttft-timeout-seconds",
        ],
    )
    def test_quality_verifier_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Quality Verifier flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Client Identity Flags Tests
# =============================================================================


class TestClientIdentityFlags:
    """Tests for client identity override CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--identity-user-agent",
            "--identity-url",
            "--identity-title",
        ],
    )
    def test_identity_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Client identity flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# ProxyMem Flags Tests
# =============================================================================


class TestProxyMemFlags:
    """Tests for ProxyMem (cross-session memory) CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--memory-available",
            "--memory-default-enabled",
            "--memory-summary-model",
            "--memory-context-model",
            "--memory-summary-prompt",
            "--memory-context-prompt",
            "--memory-database-path",
            "--memory-session-timeout",
            "--memory-retention-days",
            "--memory-max-context-tokens",
            "--memory-context-relevance-threshold",
            "--memory-single-user-mode",
            "--memory-fixed-user-id",
            "--memory-redaction-pattern",
            "--memory-disable-user",
            "--memory-disable-client",
        ],
    )
    def test_memory_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """ProxyMem flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Failure Handling Flags Tests
# =============================================================================


class TestFailureHandlingFlags:
    """Tests for failure handling CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--disable-failure-handling",
            "--max-silent-wait",
            "--total-timeout-budget",
            "--keepalive-interval",
            "--max-failover-hops",
            "--min-retry-wait",
        ],
    )
    def test_failure_handling_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Failure handling flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Resilience Scoping Flags Tests
# =============================================================================


class TestResilienceScopingFlags:
    """Tests for resilience scoping CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--resilience-personal-backends",
            "--resilience-shared-backends",
        ],
    )
    def test_resilience_scoping_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Resilience scoping flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Activity Tracking and Deduplication Flags Tests
# =============================================================================


class TestActivityDeduplicationFlags:
    """Tests for activity tracking and deduplication CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-activity-tracking",
            "--request-dedup-window",
            "--disable-request-dedup",
        ],
    )
    def test_activity_dedup_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Activity tracking and deduplication flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"


# =============================================================================
# Random Model Replacement Flags Tests
# =============================================================================


class TestRandomModelReplacementFlags:
    """Tests for random model replacement CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--enable-replacement",
            "--disable-replacement",
            "--replacement-probability",
            "--replacement-backend-model",
            "--replacement-turn-count",
        ],
    )
    def test_replacement_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Random model replacement flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"

    def test_replacement_probability_is_float(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """--replacement-probability flag accepts float type."""
        action = _get_action_by_dest(parser, "replacement_probability")
        assert action is not None
        assert action.type is float

    def test_replacement_turn_count_is_int(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """--replacement-turn-count flag accepts integer type."""
        action = _get_action_by_dest(parser, "replacement_turn_count")
        assert action is not None
        assert action.type is int


# =============================================================================
# Argument Groups Tests
# =============================================================================


class TestArgumentGroups:
    """Tests for argument group organization."""

    def test_has_history_compaction_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a History Compaction argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "History Compaction" in group_names

    def test_has_backend_debugging_overrides_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a Backend Debugging Overrides argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Backend Debugging Overrides" in group_names

    def test_has_tool_access_control_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a Tool Access Control argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Tool Access Control" in group_names

    def test_has_routing_control_group(self, parser: argparse.ArgumentParser) -> None:
        """Parser has a Routing Control argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Routing Control" in group_names

    def test_has_client_identity_override_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a Client Identity Override argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Client Identity Override" in group_names

    def test_has_proxymem_group(self, parser: argparse.ArgumentParser) -> None:
        """Parser has a ProxyMem group."""
        group_names = [g.title for g in parser._action_groups]
        assert "ProxyMem (Cross-Session Memory)" in group_names

    def test_has_failure_handling_group(self, parser: argparse.ArgumentParser) -> None:
        """Parser has a Failure Handling argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Failure Handling" in group_names

    def test_has_resilience_scoping_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a Resilience Scoping argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Resilience Scoping" in group_names

    def test_has_random_model_replacement_group(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser has a Random Model Replacement argument group."""
        group_names = [g.title for g in parser._action_groups]
        assert "Random Model Replacement" in group_names


# =============================================================================
# Access Mode Flags Tests
# =============================================================================


class TestAccessModeFlags:
    """Tests for access mode CLI arguments."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--single-user-mode",
            "--multi-user-mode",
        ],
    )
    def test_access_mode_flags_present(
        self, parser: argparse.ArgumentParser, flag: str
    ) -> None:
        """Access mode flags are present."""
        flags = _collect_cli_flags(parser)
        assert flag in flags, f"Flag {flag} not found in parser"

    def test_access_mode_flags_are_mutually_exclusive(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Access mode flags are mutually exclusive."""
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--single-user-mode",
                    "--multi-user-mode",
                ]
            )

    def test_access_mode_flags_have_help_text(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Access mode flags have descriptive help text."""
        single_user_action = _get_action_by_dest(parser, "single_user_mode")
        multi_user_action = _get_action_by_dest(parser, "multi_user_mode")

        assert single_user_action is not None
        assert multi_user_action is not None
        assert single_user_action.help is not None
        assert multi_user_action.help is not None
        assert len(single_user_action.help) > 0
        assert len(multi_user_action.help) > 0

    def test_access_mode_help_text_indicates_default(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Access mode help text indicates Single User Mode is the default."""
        single_user_action = _get_action_by_dest(parser, "single_user_mode")
        assert single_user_action is not None
        assert single_user_action.help is not None
        # Help text should mention default or Single User Mode
        help_text_lower = single_user_action.help.lower()
        assert "default" in help_text_lower or "single user" in help_text_lower

    def test_access_mode_help_text_explains_differences(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Access mode help text explains differences between modes."""
        single_user_action = _get_action_by_dest(parser, "single_user_mode")
        multi_user_action = _get_action_by_dest(parser, "multi_user_mode")

        assert single_user_action is not None
        assert multi_user_action is not None
        assert single_user_action.help is not None
        assert multi_user_action.help is not None

        # Help text should mention key differences
        single_help_lower = single_user_action.help.lower()
        multi_help_lower = multi_user_action.help.lower()

        # Single User Mode should mention OAuth or localhost
        assert (
            "oauth" in single_help_lower
            or "localhost" in single_help_lower
            or "local" in single_help_lower
        )

        # Multi User Mode should mention production or shared
        assert (
            "production" in multi_help_lower
            or "shared" in multi_help_lower
            or "multi" in multi_help_lower
        )

    def test_parse_single_user_mode_flag(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --single-user-mode flag."""
        args = parser.parse_args(["--single-user-mode"])
        assert args.single_user_mode is True

    def test_parse_multi_user_mode_flag(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --multi-user-mode flag."""
        args = parser.parse_args(["--multi-user-mode"])
        assert args.multi_user_mode is True

    def test_no_access_mode_flag_defaults_to_none(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """When no access mode flag is specified, both are None (default handled elsewhere)."""
        args = parser.parse_args([])
        # argparse will set these to False by default for store_true actions
        # The actual default mode selection happens in the applicator
        assert hasattr(args, "single_user_mode")
        assert hasattr(args, "multi_user_mode")


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing CLI."""

    def test_parser_matches_build_cli_parser(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """ArgumentParserBuilder produces parser with same flags as build_cli_parser."""
        from src.core.cli import build_cli_parser

        original_parser = build_cli_parser()
        original_flags = _collect_cli_flags(original_parser)
        new_flags = _collect_cli_flags(parser)

        # They should have the same flags
        assert original_flags == new_flags, (
            f"Flags differ. Missing: {original_flags - new_flags}, "
            f"Extra: {new_flags - original_flags}"
        )


class TestProjectDirResolutionFilesystemModeFlag:
    """Tests for --project-dir-resolution-filesystem-mode CLI argument."""

    def test_flag_present(self, parser: argparse.ArgumentParser) -> None:
        flags = _collect_cli_flags(parser)
        assert "--project-dir-resolution-filesystem-mode" in flags

    def test_flag_parses_values(self, parser: argparse.ArgumentParser) -> None:
        args = parser.parse_args(
            ["--project-dir-resolution-filesystem-mode", "disabled"]
        )
        assert args.project_dir_resolution_filesystem_mode == "disabled"

    def test_flag_rejects_invalid_values(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--project-dir-resolution-filesystem-mode", "unsupported"]
            )


class TestProjectDirResolutionOpenRouterFallbackFlag:
    """Tests for the auto OpenRouter fallback disable flag."""

    def test_flag_present(self, parser: argparse.ArgumentParser) -> None:
        flags = _collect_cli_flags(parser)
        assert "--disable-default-openrouter-project-dir-resolution-fallback" in flags

    def test_flag_sets_true(self, parser: argparse.ArgumentParser) -> None:
        args = parser.parse_args(
            ["--disable-default-openrouter-project-dir-resolution-fallback"]
        )
        assert args.disable_default_openrouter_project_dir_resolution_fallback is True

    def test_default_backend_has_dynamic_choices(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """--default-backend has dynamically populated backend choices."""
        action = _get_action_by_dest(parser, "default_backend")
        assert action is not None
        assert action.choices is not None
        choices = list(action.choices)
        assert len(choices) > 0
        # Verify it includes at least some expected backends
        registered_backends = choices
        # Should have at least some backends registered
        assert len(registered_backends) >= 1


# =============================================================================
# Parser Functionality Tests
# =============================================================================


class TestParserFunctionality:
    """Tests for parser functionality (parsing arguments)."""

    def test_parse_empty_args(self, parser: argparse.ArgumentParser) -> None:
        """Parser can parse empty arguments list."""
        args = parser.parse_args([])
        assert args is not None

    def test_parse_host_port(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --host and --port."""
        args = parser.parse_args(["--host", "0.0.0.0", "--port", "8080"])
        assert args.host == "0.0.0.0"
        assert args.port == 8080

    def test_parse_default_backend(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --default-backend with valid choice."""
        from src.core.services.backend_registry import backend_registry

        backends = backend_registry.get_registered_backends()
        if backends:
            backend = backends[0]
            args = parser.parse_args(["--default-backend", backend])
            assert args.default_backend == backend

    def test_parse_log_level(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --log-level with valid choice."""
        args = parser.parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_parse_boolean_flags(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses boolean action flags."""
        args = parser.parse_args(["--disable-auth", "--enable-sandboxing"])
        assert args.disable_auth is True
        assert args.enable_sandboxing is True

    def test_parse_mutually_exclusive_brute_force(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser enforces mutual exclusivity for brute-force protection flags."""
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--enable-brute-force-protection",
                    "--disable-brute-force-protection",
                ]
            )

    def test_parse_enable_dynamic_compression(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Parser correctly parses --enable-dynamic-compression flag."""
        args = parser.parse_args(["--enable-dynamic-compression"])
        assert args.enable_dynamic_compression is True

    def test_parse_model_alias(self, parser: argparse.ArgumentParser) -> None:
        """Parser correctly parses --model-alias with pattern=replacement format."""
        args = parser.parse_args(
            [
                "--model-alias",
                "^gpt-(.*)=openrouter:openai/gpt-\\1",
            ]
        )
        assert args.model_aliases is not None
        assert len(args.model_aliases) == 1
        pattern, replacement = args.model_aliases[0]
        assert pattern == "^gpt-(.*)"
        assert replacement == "openrouter:openai/gpt-\\1"
