"""Unit tests for DI compliance in responses controller factory."""

from __future__ import annotations

from typing import Any, cast

import pytest
from src.core.app.controllers.responses_controller import (
    ResponsesController,
    get_responses_controller,
)
from src.core.common.exceptions import InitializationError
from src.core.di.container import ServiceCollection
from src.core.domain.request_context import RequestContext
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor


class StubRequestProcessor(IRequestProcessor):
    """Minimal IRequestProcessor implementation for testing."""

    async def process_request(
        self,
        context: RequestContext,
        request_data: Any,
    ) -> Any:
        raise NotImplementedError


@pytest.fixture()
def service_provider() -> IServiceProvider:
    """Create a service provider with basic translation registration."""

    from src.core.interfaces.translation_service_interface import (
        ITranslationService,
    )
    from src.core.services.translation_service import TranslationService

    services = ServiceCollection()
    translation_service = TranslationService()
    services.add_instance(TranslationService, translation_service)
    services.add_instance(cast(type, ITranslationService), translation_service)  # type: ignore[type-abstract]
    return services.build_service_provider()


def test_get_responses_controller_requires_request_processor(
    service_provider: IServiceProvider,
) -> None:
    """The factory should fail fast when IRequestProcessor is missing."""

    with pytest.raises(InitializationError):
        get_responses_controller(service_provider)


def test_get_responses_controller_uses_di_instances(
    service_provider: IServiceProvider,
) -> None:
    """The factory should return the same instances registered in DI."""

    from src.core.interfaces.translation_service_interface import (
        ITranslationService,
    )
    from src.core.services.translation_service import TranslationService

    services = ServiceCollection()

    translation_service = service_provider.get_required_service(TranslationService)
    services.add_instance(TranslationService, translation_service)
    services.add_instance(
        cast(type, ITranslationService),
        translation_service,
    )  # type: ignore[type-abstract]

    processor = StubRequestProcessor()
    services.add_instance(StubRequestProcessor, processor)
    services.add_instance(
        cast(type, IRequestProcessor),
        processor,
    )  # type: ignore[type-abstract]

    provider_with_processor = services.build_service_provider()

    controller = get_responses_controller(provider_with_processor)

    assert isinstance(controller, ResponsesController)
    assert controller._processor is processor
    assert (
        controller._translation_service
        is provider_with_processor.get_required_service(TranslationService)
    )

