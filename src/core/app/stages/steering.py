"""
Steering services initialization stage.

This stage registers unified steering framework services:
- Session state store
- Steering policies
- Unified steering handler
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

# Import at module level to avoid undefined name issues
from src.services.steering.models import (
    SteeringRule,
    SteeringRuleRateLimit,
    SteeringRuleTriggers,
)
from src.services.steering.policies import ConfiguredRulesPolicy

from .base import InitializationStage

logger = logging.getLogger(__name__)


class SteeringStage(InitializationStage):
    """Stage for registering unified steering framework services."""

    @property
    def name(self) -> str:
        return "steering"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Register unified steering framework (session store, policies, handler)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register steering services."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing steering services...")

        # Register session state store
        self._register_session_state_store(services, config)

        # Register policies
        self._register_steering_policies(services, config)

        # Register unified steering handler
        self._register_unified_steering_handler(services, config)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Steering services initialized successfully")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that steering services can be registered."""
        try:
            # Check that reactor config exists
            if not hasattr(config.session, "tool_call_reactor"):
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Config missing tool_call_reactor section")
                return False

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Steering services validation failed: {e}")
            return False

    def _register_session_state_store(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register session state store as singleton."""
        try:
            from src.services.steering import SessionStateStore

            reactor_config = config.session.tool_call_reactor

            # Use configured settings or legacy-compatible defaults
            ttl_seconds = getattr(reactor_config, "steering_session_ttl_seconds", 1800)
            max_sessions = getattr(reactor_config, "steering_max_sessions", 1024)

            services.add_singleton(
                SessionStateStore,
                implementation_factory=lambda provider: SessionStateStore(
                    ttl_seconds=ttl_seconds, max_sessions=max_sessions
                ),
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Registered SessionStateStore (ttl=%ds, max=%d)",
                    ttl_seconds,
                    max_sessions,
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register SessionStateStore: {e}")

    def _register_steering_policies(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register steering policies as singletons."""
        try:
            from src.services.steering.policies import (
                BinaryFileEditPolicy,
                InlinePythonPolicy,
                PytestFullSuitePolicy,
            )

            reactor_config = config.session.tool_call_reactor

            # Register InlinePythonPolicy
            services.add_singleton(
                InlinePythonPolicy,
                implementation_factory=lambda provider: InlinePythonPolicy(
                    message=getattr(
                        reactor_config, "inline_python_steering_message", None
                    ),
                    enabled=getattr(
                        reactor_config, "inline_python_steering_enabled", True
                    ),
                    prompt_override_path=Path(
                        "config/prompts/steering_inline_python.md"
                    ),
                ),
            )

            # Register BinaryFileEditPolicy
            services.add_singleton(
                BinaryFileEditPolicy,
                implementation_factory=lambda provider: BinaryFileEditPolicy(
                    message=getattr(
                        reactor_config, "binary_file_edit_steering_message", None
                    ),
                    enabled=getattr(
                        reactor_config, "binary_file_edit_steering_enabled", True
                    ),
                    prompt_override_path=Path(
                        "config/prompts/steering_binary_file_edit.md"
                    ),
                ),
            )

            # Register PytestFullSuitePolicy
            from src.services.steering import SessionStateStore

            services.add_singleton(
                PytestFullSuitePolicy,
                implementation_factory=lambda provider: PytestFullSuitePolicy(
                    session_store=provider.get_required_service(SessionStateStore),
                    message=reactor_config.pytest_full_suite_steering_message,
                    enabled=reactor_config.pytest_full_suite_steering_enabled,
                    prompt_override_path=Path(
                        "config/prompts/steering_pytest_full_suite.md"
                    ),
                ),
            )

            # Register ConfiguredRulesPolicy
            services.add_singleton(
                ConfiguredRulesPolicy,
                implementation_factory=lambda provider: self._create_configured_rules_policy(
                    provider, reactor_config
                ),
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered steering policies")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register steering policies: {e}")

    def _create_configured_rules_policy(
        self, provider: IServiceProvider, reactor_config: Any
    ) -> ConfiguredRulesPolicy:
        """Create ConfiguredRulesPolicy with synthesized legacy rules."""
        from src.services.steering import SessionStateStore

        # Build effective rules from config
        effective_rules = (
            (reactor_config.steering_rules or []).copy()
            if reactor_config.steering_rules
            else []
        )

        # Synthesize legacy apply_diff rule if enabled and missing
        if getattr(reactor_config, "apply_diff_steering_enabled", False):
            has_apply_rule = False
            for r in effective_rules:
                triggers = r.triggers
                tnames = triggers.tool_names
                phrases = triggers.phrases
                if "apply_diff" in tnames or any(
                    isinstance(p, str) and "apply_diff" in p for p in phrases
                ):
                    has_apply_rule = True
                    break

            if not has_apply_rule:
                # Check for override file
                apply_diff_msg = reactor_config.apply_diff_steering_message
                override_path = Path("config/prompts/steering_apply_diff.md")

                if not apply_diff_msg and override_path.is_file():
                    try:
                        apply_diff_msg = override_path.read_text(encoding="utf-8")
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Loaded apply_diff steering prompt from %s",
                                override_path,
                            )
                    except Exception:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to read apply_diff steering prompt from %s, using default.",
                                override_path,
                                exc_info=True,
                            )

                effective_rules.append(
                    SteeringRule(
                        name="apply_diff_to_patch_file",
                        enabled=True,
                        priority=100,
                        triggers=SteeringRuleTriggers(
                            tool_names=["apply_diff"],
                            phrases=[],
                        ),
                        message=(
                            apply_diff_msg
                            or (
                                "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, "
                                "as it is superior to apply_diff and provides automated Python QA checks."
                            )
                        ),
                        rate_limit=SteeringRuleRateLimit(
                            calls_per_window=1,
                            window_seconds=reactor_config.apply_diff_steering_rate_limit_seconds,
                        ),
                    )
                )

        return ConfiguredRulesPolicy(
            session_store=provider.get_required_service(SessionStateStore),
            rules=effective_rules,
            enabled=True,
        )

    def _register_unified_steering_handler(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register unified steering handler with policies."""
        try:
            from src.services.steering import UnifiedSteeringHandler
            from src.services.steering.policies import (
                BinaryFileEditPolicy,
                InlinePythonPolicy,
                PytestFullSuitePolicy,
            )

            def handler_factory(provider: IServiceProvider) -> UnifiedSteeringHandler:
                """Factory for creating unified steering handler with policies."""
                policies = [
                    provider.get_required_service(InlinePythonPolicy),
                    provider.get_required_service(BinaryFileEditPolicy),
                    provider.get_required_service(PytestFullSuitePolicy),
                    provider.get_required_service(ConfiguredRulesPolicy),
                ]

                reactor_config = config.session.tool_call_reactor
                priority_overrides = getattr(
                    reactor_config, "steering_policy_priorities", None
                )
                emit_legacy_log_enabled = getattr(
                    reactor_config, "emit_legacy_steering_log", False
                )

                return UnifiedSteeringHandler(
                    policies=policies,
                    enabled=True,
                    priority_overrides=priority_overrides,
                    emit_legacy_log_enabled=emit_legacy_log_enabled,
                )

            services.add_singleton(
                UnifiedSteeringHandler, implementation_factory=handler_factory
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered UnifiedSteeringHandler")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register UnifiedSteeringHandler: {e}")
