"""
Backend extracted helper services registration helpers.

Handles registration of misc helper services required by BackendService:
- ModelAliasResolver
- URIParameterApplicator
- PlanningPhaseManager
- StreamSessionIdResolver
- ExceptionNormalizer
- UsageTrackingWrapper
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_extracted_backend_services(services: ServiceCollection) -> None:
    """Register extracted backend-related services required by BackendService."""
    try:
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.model_alias_resolver_interface import (
            IModelAliasResolver,
        )
        from src.core.interfaces.planning_phase_manager_interface import (
            IPlanningPhaseManager,
        )
        from src.core.interfaces.reasoning_config_applicator_interface import (
            IReasoningConfigApplicator,
        )
        from src.core.interfaces.stream_session_id_resolver_interface import (
            IStreamSessionIdResolver,
        )
        from src.core.interfaces.uri_parameter_applicator_interface import (
            IURIParameterApplicator,
        )
        from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
        from src.core.interfaces.usage_tracking_wrapper_interface import (
            IUsageTrackingWrapper,
        )
        from src.core.services.exception_normalizer import ExceptionNormalizer
        from src.core.services.model_alias_resolver import ModelAliasResolver
        from src.core.services.planning_phase_manager import PlanningPhaseManager
        from src.core.services.reasoning_config_applicator import (
            ReasoningConfigApplicator,
        )
        from src.core.services.stream_session_id_resolver import StreamSessionIdResolver
        from src.core.services.uri_parameter_applicator import URIParameterApplicator
        from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper

        def _model_alias_resolver_factory(
            provider: IServiceProvider,
        ) -> ModelAliasResolver:
            from src.core.interfaces.configuration_interface import IConfig

            config = provider.get_service(cast(type, IConfig))
            return ModelAliasResolver(config=config)

        register_singleton_if_absent(
            services,
            ModelAliasResolver,
            implementation_factory=_model_alias_resolver_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IModelAliasResolver),
            implementation_factory=lambda p: p.get_required_service(ModelAliasResolver),
        )

        def _uri_parameter_applicator_factory(
            provider: IServiceProvider,
        ) -> URIParameterApplicator:
            from src.core.interfaces.configuration_interface import IConfig

            config = provider.get_service(cast(type, IConfig))
            return URIParameterApplicator(config=config)

        register_singleton_if_absent(
            services,
            URIParameterApplicator,
            implementation_factory=_uri_parameter_applicator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IURIParameterApplicator),
            implementation_factory=lambda p: p.get_required_service(
                URIParameterApplicator
            ),
        )

        register_singleton_if_absent(services, ReasoningConfigApplicator)
        register_singleton_if_absent(
            services,
            cast(type, IReasoningConfigApplicator),
            implementation_factory=lambda p: p.get_required_service(
                ReasoningConfigApplicator
            ),
        )

        def _planning_phase_manager_factory(
            provider: IServiceProvider,
        ) -> PlanningPhaseManager:
            from src.core.interfaces.session_service_interface import ISessionService

            session_service = provider.get_service(cast(type, ISessionService))
            return PlanningPhaseManager(session_service=session_service)

        register_singleton_if_absent(
            services,
            PlanningPhaseManager,
            implementation_factory=_planning_phase_manager_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IPlanningPhaseManager),
            implementation_factory=lambda p: p.get_required_service(
                PlanningPhaseManager
            ),
        )

        register_singleton_if_absent(services, StreamSessionIdResolver)
        register_singleton_if_absent(
            services,
            cast(type, IStreamSessionIdResolver),
            implementation_factory=lambda p: p.get_required_service(
                StreamSessionIdResolver
            ),
        )

        register_singleton_if_absent(services, ExceptionNormalizer)
        register_singleton_if_absent(
            services,
            cast(type, IExceptionNormalizer),
            implementation_factory=lambda p: p.get_required_service(
                ExceptionNormalizer
            ),
        )

        def _usage_tracking_wrapper_factory(
            provider: IServiceProvider,
        ) -> UsageTrackingWrapper:
            import contextlib

            from src.core.interfaces.stream_formatting_interface import (
                IStreamFormattingService,
            )

            # Optional service - handle RuntimeError when not registered
            usage_service = None
            with contextlib.suppress(RuntimeError):
                # Service not registered - this is expected for optional services
                usage_service = provider.get_service(cast(type, IUsageTrackingService))
            # Optional service - handle RuntimeError when not registered
            stream_formatting = None
            with contextlib.suppress(RuntimeError):
                # Service not registered - this is expected for optional services
                stream_formatting = provider.get_service(
                    cast(type, IStreamFormattingService)
                )
            return UsageTrackingWrapper(
                usage_tracking_service=usage_service,
                stream_formatting_service=stream_formatting,
            )

        register_singleton_if_absent(
            services,
            UsageTrackingWrapper,
            implementation_factory=_usage_tracking_wrapper_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IUsageTrackingWrapper),
            implementation_factory=lambda p: p.get_required_service(
                UsageTrackingWrapper
            ),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register extracted backend services: %s", e)
