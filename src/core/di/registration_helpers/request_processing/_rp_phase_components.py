"""
Request processor phase component registrations.

Registers internal RequestProcessor collaborators:
- ArtifactService
- CommandHandler / ICommandHandler
- BackendPreparer / IBackendPreparer
- SessionEnricher / ISessionEnricher
- RequestSideEffects / IRequestSideEffects
- RequestTransformPipeline / IRequestTransformPipeline
- BackendExecutor / IBackendExecutor
"""

from __future__ import annotations

import contextlib
import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_request_phase_components(services: ServiceCollection) -> None:
    """Register request processor phase components."""
    _register_artifact_service(services)
    _register_command_handler(services)
    _register_backend_preparer(services)
    _register_session_enricher(services)
    _register_request_side_effects(services)
    _register_request_transform_pipeline(services)
    _register_backend_executor(services)


def _register_artifact_service(services: ServiceCollection) -> None:
    """Register ArtifactService."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.services.artifact_service import ArtifactService

    register_singleton_if_absent(
        services,
        ArtifactService,
        implementation_factory=lambda provider: ArtifactService(),
    )


def _register_command_handler(services: ServiceCollection) -> None:
    """Register CommandHandler and ICommandHandler."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.command_processor_interface import (
        ICommandProcessor,
    )
    from src.core.interfaces.request_processor_internal import ICommandHandler
    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.artifact_service import ArtifactService
    from src.core.services.command_handler import CommandHandler

    def _command_handler_factory(provider: IServiceProvider) -> CommandHandler:
        command_processor: ICommandProcessor = provider.get_required_service(
            cast(type, ICommandProcessor)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        response_manager: IResponseManager = provider.get_required_service(
            cast(type, IResponseManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        artifact_service = provider.get_service(ArtifactService)
        return CommandHandler(
            command_processor=command_processor,
            session_manager=session_manager,
            response_manager=response_manager,
            app_state=app_state,
            artifact_service=artifact_service,
        )

    register_singleton_if_absent(
        services, CommandHandler, implementation_factory=_command_handler_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, ICommandHandler),
        implementation_factory=lambda provider: provider.get_required_service(
            CommandHandler
        ),  # type: ignore[type-abstract]
    )


def _register_backend_preparer(services: ServiceCollection) -> None:
    """Register BackendPreparer and IBackendPreparer."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.request_processor_internal import IBackendPreparer
    from src.core.services.backend_preparer import BackendPreparer

    def _backend_preparer_factory(provider: IServiceProvider) -> BackendPreparer:
        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        return BackendPreparer(
            backend_request_manager=backend_request_manager, app_state=app_state
        )

    register_singleton_if_absent(
        services, BackendPreparer, implementation_factory=_backend_preparer_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, IBackendPreparer),
        implementation_factory=lambda provider: provider.get_required_service(
            BackendPreparer
        ),  # type: ignore[type-abstract]
    )


def _register_session_enricher(services: ServiceCollection) -> None:
    """Register SessionEnricher and ISessionEnricher."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.request_processor_internal import ISessionEnricher
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.session_enricher import SessionEnricher

    def _session_enricher_factory(provider: IServiceProvider) -> SessionEnricher:
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        return SessionEnricher(session_manager=session_manager, app_state=app_state)

    register_singleton_if_absent(
        services, SessionEnricher, implementation_factory=_session_enricher_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, ISessionEnricher),
        implementation_factory=lambda provider: provider.get_required_service(
            SessionEnricher
        ),  # type: ignore[type-abstract]
    )


def _register_request_side_effects(services: ServiceCollection) -> None:
    """Register RequestSideEffects and IRequestSideEffects."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.request_processor_internal import IRequestSideEffects
    from src.core.memory.capture_middleware import MemoryCaptureMiddleware
    from src.core.memory.injection_middleware import (
        ContextInjectionMiddleware,
    )
    from src.core.services.request_side_effects import RequestSideEffects

    def _request_side_effects_factory(
        provider: IServiceProvider,
    ) -> RequestSideEffects:
        import contextlib

        context_injector = None
        with contextlib.suppress(RuntimeError):
            # Optional service not registered
            context_injector = provider.get_service(ContextInjectionMiddleware)
        memory_capture = None
        with contextlib.suppress(RuntimeError):
            # Optional service not registered
            memory_capture = provider.get_service(MemoryCaptureMiddleware)
        return RequestSideEffects(
            context_injector=context_injector, memory_capture=memory_capture
        )

    register_singleton_if_absent(
        services,
        RequestSideEffects,
        implementation_factory=_request_side_effects_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IRequestSideEffects),
        implementation_factory=lambda provider: provider.get_required_service(
            RequestSideEffects
        ),  # type: ignore[type-abstract]
    )


def _register_request_transform_pipeline(services: ServiceCollection) -> None:
    """Register RequestTransformPipeline and IRequestTransformPipeline."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.request_processor_internal import (
        IRequestTransformPipeline,
    )
    from src.core.services.request_transform_pipeline import (
        RequestTransformPipeline,
    )

    def _transform_pipeline_factory(
        provider: IServiceProvider,
    ) -> RequestTransformPipeline:
        app_state = None
        with contextlib.suppress(Exception):
            app_state = provider.get_service(cast(type, IApplicationState))
        return RequestTransformPipeline(app_state=app_state)

    register_singleton_if_absent(
        services,
        cast(type, IRequestTransformPipeline),
        implementation_factory=_transform_pipeline_factory,  # type: ignore[type-abstract]
    )


def _register_backend_executor(services: ServiceCollection) -> None:
    """Register BackendExecutor and IBackendExecutor."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.model_replacement_service_interface import (
        IModelReplacementService,
    )
    from src.core.interfaces.request_processor_internal import IBackendExecutor
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.backend_executor import BackendExecutor

    def _backend_executor_factory(provider: IServiceProvider) -> IBackendExecutor:
        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        replacement_service = provider.get_service(cast(type, IModelReplacementService))
        return BackendExecutor(
            backend_request_manager=backend_request_manager,
            session_manager=session_manager,
            replacement_service=replacement_service,
        )

    register_singleton_if_absent(
        services,
        cast(type, IBackendExecutor),
        implementation_factory=_backend_executor_factory,  # type: ignore[type-abstract]
    )
