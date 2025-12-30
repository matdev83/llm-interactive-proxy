"""
Response processing service registrations.

Registers:
- StreamFormattingService / IStreamFormattingService
- ResponseParser / IResponseParser
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_response_processing_services(services: ServiceCollection) -> None:
    """Register response processing services.

    Args:
        services: The service collection to register into
    """
    _register_stream_formatting_service(services)
    _register_response_parser(services)


def _register_stream_formatting_service(services: ServiceCollection) -> None:
    """Register StreamFormattingService with IStreamFormattingService interface binding."""
    from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
    from src.core.services.stream_formatting_service import StreamFormattingService

    def _stream_formatting_service_factory(
        provider: IServiceProvider,
    ) -> StreamFormattingService:
        return StreamFormattingService()

    # Register concrete type with factory
    register_singleton_if_absent(
        services,
        StreamFormattingService,
        implementation_factory=_stream_formatting_service_factory,
    )

    # Bind interface to concrete type by resolving it from provider
    def _istream_formatting_service_factory(
        provider: IServiceProvider,
    ) -> StreamFormattingService:
        return provider.get_required_service(StreamFormattingService)

    register_singleton_if_absent(
        services,
        cast(type, IStreamFormattingService),  # type: ignore[type-abstract]
        implementation_factory=_istream_formatting_service_factory,  # type: ignore[type-abstract]
    )


def _register_response_parser(services: ServiceCollection) -> None:
    """Register ResponseParser with IResponseParser interface binding."""
    from src.core.interfaces.response_parser_interface import IResponseParser
    from src.core.services.response_parser_service import ResponseParser

    # Register concrete type
    register_singleton_if_absent(services, ResponseParser)

    # Bind interface to concrete type
    def _iresponse_parser_factory(provider: IServiceProvider) -> ResponseParser:
        return provider.get_required_service(ResponseParser)

    register_singleton_if_absent(
        services,
        cast(type, IResponseParser),  # type: ignore[type-abstract]
        implementation_factory=_iresponse_parser_factory,  # type: ignore[type-abstract]
    )
