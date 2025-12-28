"""
Tooling registrar.

Registers tool call reactor, pytest compression, and dangerous command handling services.
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_interface_and_implementation,
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.tool_call_reactor_interface import IToolCallReactor

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register tooling services.

    This registrar handles:
    - Tool call reactor service and history tracker
    - Tool call reactor orchestrator and related interfaces
    - Dangerous command handling
    - Pytest compression
    - Tool access policy service

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register core tool call reactor services
    _register_tool_call_reactor_core(services, app_config)

    # Register supporting services (optional)
    _register_dangerous_command_service(services, app_config)
    _register_pytest_compression_service(services, app_config)
    _register_tool_access_policy_service(services, app_config)


def _register_tool_call_reactor_core(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register core tool call reactor services."""
    try:
        from src.core.services.tool_call_reactor.extractor import ToolCallExtractor
        from src.core.services.tool_call_reactor_service import (
            InMemoryToolCallHistoryTracker,
            ToolCallReactorService,
        )

        # Register ToolCallExtractor as singleton
        register_singleton_if_absent(services, ToolCallExtractor)

        # Register IToolCallExtractor interface binding
        try:
            from src.core.interfaces.tool_call_extractor_interface import (
                IToolCallExtractor,
            )

            def itool_call_extractor_factory(
                provider: IServiceProvider,
            ) -> ToolCallExtractor:
                return provider.get_required_service(ToolCallExtractor)

            register_singleton_if_absent(
                services,
                cast(type, IToolCallExtractor),
                implementation_factory=itool_call_extractor_factory,
            )
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register IToolCallExtractor interface: {e}")

        # Register InMemoryToolCallHistoryTracker as singleton
        def history_tracker_factory(
            provider: IServiceProvider,
        ) -> InMemoryToolCallHistoryTracker:
            """Factory for creating history tracker with config."""
            from src.core.interfaces.time_source_interface import ITimeSource

            config = provider.get_service(AppConfig)
            session_ttl = 3600
            max_sessions = 10000
            max_entries_per_session = 100

            if config is not None and hasattr(config.session, "tool_call_reactor"):
                reactor_config = config.session.tool_call_reactor
                session_ttl = getattr(
                    reactor_config, "session_ttl_seconds", session_ttl
                )
                max_sessions = getattr(reactor_config, "max_sessions", max_sessions)
                max_entries_per_session = getattr(
                    reactor_config, "max_entries_per_session", max_entries_per_session
                )

            # Get time source from DI if available
            time_source = provider.get_service(cast(type, ITimeSource))

            return InMemoryToolCallHistoryTracker(
                session_ttl_seconds=session_ttl,
                max_sessions=max_sessions,
                max_entries_per_session=max_entries_per_session,
                time_source=time_source,
            )

        register_singleton_if_absent(
            services,
            InMemoryToolCallHistoryTracker,
            implementation_factory=history_tracker_factory,
        )

        # Register ToolCallReactorService with factory
        def tool_call_reactor_factory(
            provider: IServiceProvider,
        ) -> ToolCallReactorService:
            """Factory for creating ToolCallReactorService."""
            history_tracker = provider.get_required_service(
                InMemoryToolCallHistoryTracker
            )
            return ToolCallReactorService(history_tracker)

        register_singleton_if_absent(
            services,
            ToolCallReactorService,
            implementation_factory=tool_call_reactor_factory,
        )

        # Register IToolCallReactor interface bound to ToolCallReactorService
        register_interface_and_implementation(
            services,
            cast(type, IToolCallReactor),
            ToolCallReactorService,
        )

        # Register tool call reactor subsystem services (normalizer, deduplicator, etc.)
        _register_tool_call_reactor_subsystem(services)

        # Register orchestrator and related interfaces if tool call reactor is enabled
        _register_tool_call_reactor_orchestrator(services, app_config)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Registered ToolCallReactorService, InMemoryToolCallHistoryTracker, and IToolCallReactor"
            )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Could not register tool call reactor services: {e}")


def _register_tool_call_reactor_subsystem(services: ServiceCollection) -> None:
    """Register tool call reactor subsystem services (normalizer, deduplicator, parser, etc.)."""
    try:
        # Register ToolCallLifecycleRegistry first (required by deduplicator)
        from src.tool_call_loop.lifecycle_registry import ToolCallLifecycleRegistry

        register_singleton_if_absent(services, ToolCallLifecycleRegistry)
        from src.core.interfaces.replacement_response_factory_interface import (
            IReplacementResponseFactory,
        )
        from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
            IToolArgumentsFixupPipeline,
        )
        from src.core.interfaces.tool_arguments_parser_interface import (
            IToolArgumentsParser,
        )
        from src.core.interfaces.tool_call_deduplicator_interface import (
            IToolCallDeduplicator,
        )
        from src.core.interfaces.tool_call_normalizer_interface import (
            IToolCallNormalizer,
        )
        from src.core.interfaces.tool_call_stream_context_resolver_interface import (
            IToolCallStreamContextResolver,
        )
        from src.core.services.tool_call_reactor.arguments_fixup_pipeline import (
            ToolArgumentsFixupPipeline,
        )
        from src.core.services.tool_call_reactor.arguments_parser import (
            ToolArgumentsParser,
        )
        from src.core.services.tool_call_reactor.deduplicator import (
            ToolCallDeduplicator,
        )
        from src.core.services.tool_call_reactor.normalizer import ToolCallNormalizer
        from src.core.services.tool_call_reactor.replacement_response_factory import (
            ReplacementResponseFactory,
        )
        from src.core.services.tool_call_reactor.stream_context_resolver import (
            ToolCallStreamContextResolver,
        )

        # Register ToolCallNormalizer (no dependencies)
        register_singleton_if_absent(services, ToolCallNormalizer)
        register_singleton_if_absent(
            services,
            cast(type, IToolCallNormalizer),
            implementation_factory=lambda provider: provider.get_required_service(
                ToolCallNormalizer
            ),
        )

        # Register ToolCallDeduplicator (requires ToolCallLifecycleRegistry)
        def tool_call_deduplicator_factory(
            provider: IServiceProvider,
        ) -> ToolCallDeduplicator:
            lifecycle_registry = provider.get_required_service(
                ToolCallLifecycleRegistry
            )
            return ToolCallDeduplicator(lifecycle_registry=lifecycle_registry)

        register_singleton_if_absent(
            services,
            ToolCallDeduplicator,
            implementation_factory=tool_call_deduplicator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IToolCallDeduplicator),
            implementation_factory=tool_call_deduplicator_factory,
        )

        # Register ToolArgumentsParser (no dependencies)
        register_singleton_if_absent(services, ToolArgumentsParser)
        register_singleton_if_absent(
            services,
            cast(type, IToolArgumentsParser),
            implementation_factory=lambda provider: provider.get_required_service(
                ToolArgumentsParser
            ),
        )

        # Register ToolArgumentsFixupPipeline (optional WindowsDoubleAmpersandFixer)
        def tool_arguments_fixup_pipeline_factory(
            provider: IServiceProvider,
        ) -> ToolArgumentsFixupPipeline:
            """Factory for creating ToolArgumentsFixupPipeline with configured WindowsDoubleAmpersandFixer."""
            from src.core.services.windows_double_ampersand_fixer import (
                WindowsDoubleAmpersandFixer,
            )

            config = provider.get_required_service(AppConfig)

            # Get double_ampersand_fixes_for_windows_enabled from session config
            enabled = True
            if hasattr(config, "session") and config.session is not None:
                enabled = getattr(
                    config.session,
                    "double_ampersand_fixes_for_windows_enabled",
                    True,
                )

            windows_fixer = WindowsDoubleAmpersandFixer(enabled=enabled)
            return ToolArgumentsFixupPipeline(windows_ampersand_fixer=windows_fixer)

        register_singleton_if_absent(
            services,
            ToolArgumentsFixupPipeline,
            implementation_factory=tool_arguments_fixup_pipeline_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IToolArgumentsFixupPipeline),
            implementation_factory=tool_arguments_fixup_pipeline_factory,
        )

        # Register ReplacementResponseFactory (no dependencies)
        register_singleton_if_absent(services, ReplacementResponseFactory)
        register_singleton_if_absent(
            services,
            cast(type, IReplacementResponseFactory),
            implementation_factory=lambda provider: provider.get_required_service(
                ReplacementResponseFactory
            ),
        )

        # Register ToolCallStreamContextResolver (requires StreamingContextRegistry)
        def tool_call_stream_context_resolver_factory(
            provider: IServiceProvider,
        ) -> ToolCallStreamContextResolver:
            from src.core.services.streaming.stream_context_registry import (
                StreamingContextRegistry,
            )

            registry = provider.get_required_service(StreamingContextRegistry)
            return ToolCallStreamContextResolver(registry=registry)

        register_singleton_if_absent(
            services,
            ToolCallStreamContextResolver,
            implementation_factory=tool_call_stream_context_resolver_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IToolCallStreamContextResolver),
            implementation_factory=tool_call_stream_context_resolver_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered tool call reactor subsystem services")
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Could not register tool call reactor subsystem: {e}")


def _register_tool_call_reactor_orchestrator(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register tool call reactor orchestrator and related interfaces.

    Note: This is a complex registration with many dependencies. The orchestrator
    coordinates tool-call processing and requires multiple collaborators.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Always register orchestrator if dependencies are available
    # Config check is done at runtime, not registration time
    # This allows tests to work without requiring config

    try:
        from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
            IToolCallReactorOrchestrator,
        )
        from src.core.services.tool_call_reactor.orchestrator import (
            ToolCallReactorOrchestrator,
        )

        def orchestrator_factory(
            provider: IServiceProvider,
        ) -> ToolCallReactorOrchestrator:
            """Factory for creating ToolCallReactorOrchestrator with all dependencies."""
            from src.core.interfaces.replacement_response_factory_interface import (
                IReplacementResponseFactory,
            )
            from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
                IToolArgumentsFixupPipeline,
            )
            from src.core.interfaces.tool_arguments_parser_interface import (
                IToolArgumentsParser,
            )
            from src.core.interfaces.tool_call_deduplicator_interface import (
                IToolCallDeduplicator,
            )
            from src.core.interfaces.tool_call_extractor_interface import (
                IToolCallExtractor,
            )
            from src.core.interfaces.tool_call_normalizer_interface import (
                IToolCallNormalizer,
            )
            from src.core.interfaces.tool_call_stream_context_resolver_interface import (
                IToolCallStreamContextResolver,
            )
            from src.tool_call_loop.lifecycle_registry import (
                ToolCallLifecycleRegistry,
            )

            # Resolve all dependencies
            extractor: IToolCallExtractor = provider.get_required_service(
                cast(type, IToolCallExtractor)
            )
            normalizer: IToolCallNormalizer = provider.get_required_service(
                cast(type, IToolCallNormalizer)
            )
            stream_context_resolver: IToolCallStreamContextResolver = (
                provider.get_required_service(
                    cast(type, IToolCallStreamContextResolver)
                )
            )
            deduplicator: IToolCallDeduplicator = provider.get_required_service(
                cast(type, IToolCallDeduplicator)
            )
            arguments_parser: IToolArgumentsParser = provider.get_required_service(
                cast(type, IToolArgumentsParser)
            )
            arguments_fixup_pipeline: IToolArgumentsFixupPipeline = (
                provider.get_required_service(cast(type, IToolArgumentsFixupPipeline))
            )
            reactor: IToolCallReactor = provider.get_required_service(
                cast(type, IToolCallReactor)
            )
            replacement_factory: IReplacementResponseFactory = (
                provider.get_required_service(cast(type, IReplacementResponseFactory))
            )
            lifecycle_registry: ToolCallLifecycleRegistry = (
                provider.get_required_service(ToolCallLifecycleRegistry)
            )

            return ToolCallReactorOrchestrator(
                extractor=extractor,
                normalizer=normalizer,
                stream_context_resolver=stream_context_resolver,
                deduplicator=deduplicator,
                arguments_parser=arguments_parser,
                arguments_fixup_pipeline=arguments_fixup_pipeline,
                reactor=reactor,
                replacement_factory=replacement_factory,
                lifecycle_registry=lifecycle_registry,
            )

        register_singleton_if_absent(
            services,
            ToolCallReactorOrchestrator,
            implementation_factory=orchestrator_factory,
        )

        # Register interface bound to orchestrator
        register_singleton_if_absent(
            services,
            cast(type, IToolCallReactorOrchestrator),
            implementation_factory=orchestrator_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Registered ToolCallReactorOrchestrator and IToolCallReactorOrchestrator"
            )
    except ImportError as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Could not register tool call reactor orchestrator: {e}", exc_info=True
            )
    except Exception as e:
        # Don't fail startup if orchestrator registration fails
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register ToolCallReactorOrchestrator: {e}", exc_info=True
            )


def _register_dangerous_command_service(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register dangerous command service if enabled."""
    if app_config is None:
        return

    try:
        # Check if dangerous commands feature is enabled
        dangerous_commands_enabled = False
        if hasattr(app_config, "dangerous_commands"):
            dangerous_config = getattr(app_config, "dangerous_commands", None)  # type: ignore[attr-defined]
            dangerous_commands_enabled = getattr(dangerous_config, "enabled", False)
        elif hasattr(app_config, "unified_security"):
            unified_config = app_config.unified_security
            if unified_config is not None:
                dangerous_config = getattr(unified_config, "dangerous_commands", None)
                if dangerous_config is not None:
                    dangerous_commands_enabled = getattr(
                        dangerous_config, "enabled", False
                    )

        if not dangerous_commands_enabled:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("DangerousCommandService not registered: feature disabled")
            return

        from src.core.services.dangerous_command_service import DangerousCommandService

        def dangerous_command_service_factory(
            provider: IServiceProvider,
        ) -> DangerousCommandService:
            """Factory for creating DangerousCommandService."""
            config = provider.get_required_service(AppConfig)

            # Get dangerous command config
            dangerous_config = None
            if hasattr(config, "dangerous_commands"):
                dangerous_config = config.dangerous_commands
            elif hasattr(config, "unified_security"):
                unified_config = config.unified_security
                if unified_config is not None:
                    dangerous_config = getattr(
                        unified_config, "dangerous_commands", None
                    )

            if dangerous_config is None:
                # Fallback to default config
                from src.core.domain.configuration.dangerous_command_config import (
                    DangerousCommandConfig,
                )

                # Create default config with empty rules and tool names
                dangerous_config = DangerousCommandConfig(tool_names=[], rules=[])

            return DangerousCommandService(config=dangerous_config)

        register_singleton_if_absent(
            services,
            DangerousCommandService,
            implementation_factory=dangerous_command_service_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered DangerousCommandService")
    except ImportError as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Could not register DangerousCommandService: {e}", exc_info=True
            )
    except Exception as e:
        # Don't fail startup if dangerous command service registration fails
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register DangerousCommandService: {e}", exc_info=True
            )


def _register_pytest_compression_service(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register pytest compression service."""
    try:
        from src.core.services.pytest_compression_service import (
            PytestCompressionService,
        )

        # PytestCompressionService is always available (no config needed)
        register_singleton_if_absent(services, PytestCompressionService)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered PytestCompressionService")
    except ImportError as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Could not register PytestCompressionService: {e}", exc_info=True
            )
    except Exception as e:
        # Don't fail startup if pytest compression service registration fails
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register PytestCompressionService: {e}", exc_info=True
            )


def _register_tool_access_policy_service(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register tool access policy service if policies are configured."""
    if app_config is None:
        return

    try:
        # Check if tool call reactor is enabled and has access policies
        reactor_config = getattr(app_config.session, "tool_call_reactor", None)
        if reactor_config is None:
            return

        # Check if reactor is enabled
        if not getattr(reactor_config, "enabled", False):
            return

        # Check if access policies are configured
        access_policies = getattr(reactor_config, "access_policies", None)
        if not access_policies or len(access_policies) == 0:
            return

        from src.core.services.tool_access_policy_service import (
            ToolAccessPolicyService,
        )

        def tool_access_policy_service_factory(
            provider: IServiceProvider,
        ) -> ToolAccessPolicyService:
            """Factory for creating ToolAccessPolicyService."""
            config = provider.get_required_service(AppConfig)
            reactor_config = config.session.tool_call_reactor
            return ToolAccessPolicyService(reactor_config)

        register_singleton_if_absent(
            services,
            ToolAccessPolicyService,
            implementation_factory=tool_access_policy_service_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered ToolAccessPolicyService")
    except ImportError as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Could not register ToolAccessPolicyService: {e}", exc_info=True
            )
    except Exception as e:
        # Don't fail startup if tool access policy service registration fails
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register ToolAccessPolicyService: {e}", exc_info=True
            )
