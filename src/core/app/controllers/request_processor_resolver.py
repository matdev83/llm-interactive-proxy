"""Utilities for resolving DI-managed request processors."""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.common.exceptions import InitializationError, ServiceResolutionError
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor

logger = logging.getLogger(__name__)


def resolve_request_processor(
    service_provider: IServiceProvider,
    *,
    fallback_provider: IServiceProvider | None = None,
) -> IRequestProcessor:
    """Resolve an ``IRequestProcessor`` without manual instantiation."""

    request_processor = service_provider.get_service(cast(type, IRequestProcessor))
    if request_processor is not None:
        return request_processor

    if fallback_provider is not None:
        request_processor = fallback_provider.get_service(cast(type, IRequestProcessor))
        if request_processor is not None:
            return request_processor

    return _build_from_service_collection(service_provider)


def _get_from_provider(
    provider: IServiceProvider,
) -> IRequestProcessor | None:
    return provider.get_service(cast(type, IRequestProcessor))


def _get_from_global_provider(
    local_provider: IServiceProvider,
) -> IRequestProcessor | None:
    try:
        from src.core.di.services import get_service_provider
    except ImportError:  # pragma: no cover - defensive guard
        logger.debug("Failed to import get_service_provider", exc_info=True)
        return None

    try:
        global_provider = get_service_provider()
    except (
        ImportError,
        AttributeError,
        RuntimeError,
    ) as e:  # pragma: no cover - defensive guard
        logger.debug("Failed to get global service provider: %s", e, exc_info=True)
        return None

    if global_provider is None or global_provider is local_provider:
        return None

    return global_provider.get_service(cast(type, IRequestProcessor))


def _build_from_service_collection(
    local_provider: IServiceProvider,
) -> IRequestProcessor:
    try:
        from src.core.di.services import (
            get_service_collection,
            set_service_provider,
        )
    except ImportError as import_error:  # pragma: no cover - defensive guard
        raise InitializationError("DI services module unavailable") from import_error

    # First, try to get the request processor directly from the local provider
    # This respects test mocks and custom registrations
    request_processor = local_provider.get_service(cast(type, IRequestProcessor))
    if request_processor is not None:
        return request_processor

    services = get_service_collection()
    fallback_provider = services.build_service_provider()

    # Make the rebuilt provider available for subsequent resolutions
    try:
        set_service_provider(fallback_provider)
    except (
        ImportError,
        AttributeError,
        RuntimeError,
    ) as e:  # pragma: no cover - best-effort update
        logger.debug("Failed to update global service provider: %s", e, exc_info=True)

    request_processor = fallback_provider.get_service(cast(type, IRequestProcessor))

    if request_processor is None:
        try:
            request_processor = fallback_provider.get_required_service(
                cast(type, IRequestProcessor)
            )
        except ServiceResolutionError as resolver_error:
            raise InitializationError(
                "Could not resolve IRequestProcessor from DI container"
            ) from resolver_error

    if request_processor is None:
        raise InitializationError("Request processor resolution failed")

    _register_singleton_instance(services, request_processor)
    _cache_on_provider(local_provider, request_processor)

    return request_processor


def _register_singleton_instance(
    services: Any, request_processor: IRequestProcessor
) -> None:
    try:
        from src.core.services.request_processor_service import RequestProcessor
    except ImportError:  # pragma: no cover - defensive guard
        RequestProcessor = None  # type: ignore

    try:
        services.add_instance(cast(type, IRequestProcessor), request_processor)
        if RequestProcessor is not None:
            services.add_instance(RequestProcessor, request_processor)
    except (
        ImportError,
        AttributeError,
        RuntimeError,
        ValueError,
    ) as e:  # pragma: no cover - defensive guard
        logger.debug("Failed to cache IRequestProcessor instance: %s", e, exc_info=True)


def _cache_on_provider(
    provider: IServiceProvider, request_processor: IRequestProcessor
) -> None:
    try:
        from src.core.di.container import ServiceProvider
        from src.core.services.request_processor_service import RequestProcessor
    except ImportError:  # pragma: no cover - defensive guard
        return

    if not isinstance(provider, ServiceProvider):
        return

    try:
        singleton_instances = getattr(provider, "_singleton_instances", None)
    except AttributeError:  # pragma: no cover - defensive guard
        return

    if not isinstance(singleton_instances, dict):
        return

    singleton_instances[IRequestProcessor] = request_processor
    if RequestProcessor is not None:
        singleton_instances[RequestProcessor] = request_processor
