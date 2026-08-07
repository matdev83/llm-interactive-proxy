"""Property tests for Domain Applicator Isolation.

**Feature: cli-god-object-refactoring, Property 3: Domain Applicator Isolation**

Requirements:
- 6.2: Each domain applicator only modifies its relevant configuration section
- 9.3: Property-based tests for correctness properties
"""

from __future__ import annotations

import argparse

import pytest
from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution

# Domain boundaries - each applicator should only modify keys within its domain
DOMAIN_BOUNDARIES: dict[str, set[str]] = {
    "ServerApplicator": {
        "host",
        "port",
        "anthropic_port",
        "proxy_timeout",
        "command_prefix",
        "context_window_override",
        "enable_activity_tracking",
        "request_dedup_window",
        "session",
    },  # session contains nested thinking_budget
    "LoggingApplicator": {"logging"},
    "BackendApplicator": {"backends", "model_aliases"},
    "SessionApplicator": {"session", "strict_command_detection"},
    "AuthApplicator": {"auth", "sso"},
    "AssessmentApplicator": {"assessment"},
    "MemoryApplicator": {"memory"},
    "FailureHandlingApplicator": {"failure_handling"},
    "EditPrecisionApplicator": {"edit_precision"},
    "IdentityApplicator": {"identity"},
    "RoutingApplicator": {"routing"},
    "CompactionApplicator": {"compaction"},
    "SandboxingApplicator": {"sandboxing"},
    "EndOfSessionApplicator": {"end_of_session"},
}


class TestDomainApplicatorIsolation:
    """Property tests for domain applicator isolation.

    **Validates: Requirements 6.2**

    Property 3: Domain Applicator Isolation
    *For any* domain applicator, applying arguments SHALL only modify configuration
    keys within its designated domain.
    """

    @staticmethod
    def _get_sample_args_for_applicator(applicator_name: str) -> CliArgs:
        """Create sample CLI arguments that would trigger the applicator."""
        if applicator_name == "ServerApplicator":
            return argparse.Namespace(
                host="127.0.0.1",
                port=8080,
                anthropic_port=8081,
                timeout=60,
                command_prefix="/cmd",
                force_context_window=128000,
                enable_activity_tracking=True,
                request_dedup_window=3.0,
                disable_request_dedup=False,
                thinking_budget=None,
            )
        elif applicator_name == "LoggingApplicator":
            return argparse.Namespace(
                log_file="./logs/test.log",
                log_level="DEBUG",
                log_use_colors=True,
                capture_file="./captures/wire.log",
                capture_max_bytes=10485760,
                capture_truncate_bytes=4096,
                capture_max_files=5,
                capture_rotate_interval_seconds=3600,
                capture_total_max_bytes=104857600,
                cbor_capture_dir="./var/cbor",
                cbor_capture_session_id="test-session",
            )
        elif applicator_name == "BackendApplicator":
            return argparse.Namespace(
                default_backend="openai",
                static_route=None,
                disable_gemini_oauth_fallback=True,
                disable_hybrid_backend=False,
                hybrid_backend_repeat_messages=False,
                reasoning_injection_probability=0.5,
                hybrid_reasoning_model_timeout=60,
                hybrid_reasoning_force_initial_turns=4,
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
                enable_kiro_oauth_auto_backend_debugging_override=False,
            )
        elif applicator_name == "SessionApplicator":
            return argparse.Namespace(
                disable_interactive_mode=True,
                force_set_project=True,
                project_dir_resolution_model=None,
                project_dir_resolution_mode=None,
                disable_interactive_commands=False,
                quality_verifier_model=None,
                quality_verifier_frequency=None,
                enable_planning_phase=True,
                planning_phase_strong_model=None,
                planning_phase_max_turns=None,
                planning_phase_max_file_writes=None,
                planning_phase_temperature=None,
                planning_phase_top_p=None,
                planning_phase_reasoning_effort=None,
                planning_phase_thinking_budget=None,
                pytest_full_suite_steering_enabled=None,
                cat_file_edits_steering_enabled=None,
                pytest_context_saving_enabled=None,
                test_execution_reminder_enabled=None,
                fix_think_tags_enabled=None,
                disable_dangerous_git_commands_protection=None,
                disable_double_ampersand_fixes_for_windows=None,
                droid_path_fix_enabled=None,
                tool_access_allowed_tools=None,
                tool_access_blocked_tools=None,
                tool_access_default_policy=None,
                strict_command_detection=None,
                disable_accounting=None,
            )
        elif applicator_name == "AuthApplicator":
            return argparse.Namespace(
                disable_auth=True,
                disable_sso_captcha=True,
                enable_sso=True,
                sso_config_path=None,
                sso_provider=None,
                sso_auth_mode=None,
                trusted_ips=None,
                disable_redact_api_keys_in_prompts=None,
                brute_force_protection_enabled=True,
                auth_max_failed_attempts=5,
                auth_brute_force_ttl=300,
                auth_initial_block_seconds=60,
                auth_block_multiplier=2.0,
                auth_max_block_seconds=3600,
            )
        elif applicator_name == "AssessmentApplicator":
            return argparse.Namespace(
                llm_assessment_enabled=True,
                llm_assessment_turn_threshold=5,
                llm_assessment_confidence_threshold=0.8,
                llm_assessment_model=None,
                llm_assessment_history_window=10,
            )
        elif applicator_name == "MemoryApplicator":
            return argparse.Namespace(
                memory_available=True,
                memory_default_enabled=True,
                memory_summary_model=None,
                memory_context_model=None,
                memory_summary_prompt=None,
                memory_context_prompt=None,
                memory_database_path=None,
                memory_session_timeout=30,
                memory_retention_days=30,
                memory_max_context_tokens=4096,
                memory_context_relevance_threshold=0.7,
                memory_single_user_mode=None,
                memory_fixed_user_id=None,
                memory_redaction_patterns=None,
                memory_disabled_users=None,
                memory_disabled_clients=None,
            )
        elif applicator_name == "FailureHandlingApplicator":
            return argparse.Namespace(
                disable_failure_handling=False,
                max_silent_wait=30,
                total_timeout_budget=120,
                keepalive_interval=5,
                max_failover_hops=3,
                min_retry_wait=1,
            )
        elif applicator_name == "EditPrecisionApplicator":
            return argparse.Namespace(
                edit_precision_enabled=True,
                edit_precision_temperature=0.1,
                edit_precision_min_top_p=0.3,
                edit_precision_override_top_p=True,
                edit_precision_override_top_k=False,
                edit_precision_target_top_k=None,
                edit_precision_exclude_agents_regex=None,
            )
        elif applicator_name == "IdentityApplicator":
            return argparse.Namespace(
                identity_user_agent="TestAgent/1.0",
                identity_url="https://example.com",
                identity_title="Test Identity",
            )
        elif applicator_name == "RoutingApplicator":
            return argparse.Namespace(
                disable_routing_with_backend_ids=True,
                disable_routing_with_backend_names=True,
                disable_routing_with_only_model_names=False,
            )
        elif applicator_name == "CompactionApplicator":
            return argparse.Namespace(
                enable_context_compaction=True,
                compaction_min_tokens=100000,
            )
        elif applicator_name == "SandboxingApplicator":
            return argparse.Namespace(
                enable_sandboxing=True,
            )
        else:
            return argparse.Namespace()

    @pytest.mark.parametrize(
        "applicator_name",
        [
            "ServerApplicator",
            "LoggingApplicator",
            "BackendApplicator",
            "SessionApplicator",
            "AuthApplicator",
            "MemoryApplicator",
            "FailureHandlingApplicator",
            "EditPrecisionApplicator",
            "IdentityApplicator",
            "RoutingApplicator",
            "CompactionApplicator",
            "SandboxingApplicator",
            "EndOfSessionApplicator",
        ],
    )
    def test_domain_applicator_isolation(self, applicator_name: str) -> None:
        """Test that each domain applicator only modifies keys within its designated domain.

        **Feature: cli-god-object-refactoring, Property 3: Domain Applicator Isolation**

        This property test verifies that applying arguments through a domain applicator
        only affects configuration keys within that applicator's designated domain.
        """
        # Import the applicator dynamically
        module_name = applicator_name.replace("Applicator", "").lower()
        try:
            module = __import__(
                f"src.core.cli_support.applicators.{module_name}_applicator",
                fromlist=[applicator_name],
            )
            applicator_class = getattr(module, applicator_name)
        except (ImportError, AttributeError):
            pytest.skip(f"{applicator_name} not yet implemented")
            return

        # Create applicator and test data
        applicator = applicator_class()
        args = self._get_sample_args_for_applicator(applicator_name)
        overrides: CliOverrides = {}
        resolution = ParameterResolution()

        # Apply the applicator
        applicator.apply(args, overrides, resolution)

        # Verify domain isolation
        allowed_keys = DOMAIN_BOUNDARIES.get(applicator_name, set())
        for key in overrides:
            assert (
                key in allowed_keys
            ), f"{applicator_name} modified key '{key}' outside its domain. Allowed keys: {allowed_keys}"
