"""Unit tests for DI compliance in responses controller factory."""

from __future__ import annotations

from typing import Any, cast

import pytest
from src.core.app.controllers.responses_controller import (
    ResponsesController,
    get_responses_controller,
)
from src.core.app.stages.controller import ControllerStage
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

    with pytest.raises(InitializationError) as exc_info:
        get_responses_controller(service_provider)
    assert "Failed to create ResponsesController" not in str(exc_info.value)
    assert "RequestProcessor" in str(exc_info.value)


def test_get_responses_controller_uses_di_instances(
    service_provider: IServiceProvider,
) -> None:
    """The factory should return the same instances registered in DI."""

    from src.core.interfaces.backend_model_resolver_interface import (
        IBackendModelResolver,
    )
    from src.core.interfaces.responses_session_store_interface import (
        IResponsesSessionStore,
    )
    from src.core.interfaces.translation_service_interface import (
        ITranslationService,
    )
    from src.core.services.anthropic_responses_projector import (
        AnthropicResponsesProjector,
    )
    from src.core.services.gemini_responses_projector import GeminiResponsesProjector
    from src.core.services.in_memory_responses_session_store import (
        InMemoryResponsesSessionStore,
    )
    from src.core.services.openai_responses_projector import OpenAIResponsesProjector
    from src.core.services.translation_service import TranslationService

    from tests.utils.responses_controller_test_deps import (
        build_responses_controller_backend_kwargs,
    )

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

    deps = build_responses_controller_backend_kwargs()
    store = deps["responses_session_store"]
    services.add_instance(InMemoryResponsesSessionStore, store)
    services.add_instance(cast(type, IResponsesSessionStore), store)  # type: ignore[type-abstract]

    resolver = deps["backend_model_resolver"]
    services.add_instance(cast(type, IBackendModelResolver), resolver)  # type: ignore[type-abstract]

    openai_proj = deps["openai_responses_projector"]
    anthropic_proj = deps["anthropic_responses_projector"]
    gemini_proj = deps["gemini_responses_projector"]
    services.add_instance(OpenAIResponsesProjector, openai_proj)
    services.add_instance(AnthropicResponsesProjector, anthropic_proj)
    services.add_instance(GeminiResponsesProjector, gemini_proj)

    provider_with_processor = services.build_service_provider()

    controller = get_responses_controller(provider_with_processor)

    assert isinstance(controller, ResponsesController)
    assert controller._processor is processor
    assert (
        controller._translation_service
        is provider_with_processor.get_required_service(TranslationService)
    )
    assert controller._responses_session_store is store
    assert controller._backend_model_resolver is resolver
    assert controller._openai_responses_projector is openai_proj
    assert controller._anthropic_responses_projector is anthropic_proj
    assert controller._gemini_responses_projector is gemini_proj


def test_controller_stage_uses_shared_responses_factory(
    service_provider: IServiceProvider,
) -> None:
    """ControllerStage should register the same DI-backed responses controller factory."""

    from src.core.interfaces.backend_model_resolver_interface import (
        IBackendModelResolver,
    )
    from src.core.interfaces.responses_session_store_interface import (
        IResponsesSessionStore,
    )
    from src.core.interfaces.translation_service_interface import (
        ITranslationService,
    )
    from src.core.services.anthropic_responses_projector import (
        AnthropicResponsesProjector,
    )
    from src.core.services.gemini_responses_projector import GeminiResponsesProjector
    from src.core.services.in_memory_responses_session_store import (
        InMemoryResponsesSessionStore,
    )
    from src.core.services.openai_responses_projector import OpenAIResponsesProjector
    from src.core.services.translation_service import TranslationService

    from tests.utils.responses_controller_test_deps import (
        build_responses_controller_backend_kwargs,
    )

    services = ServiceCollection()

    translation_service = service_provider.get_required_service(TranslationService)
    services.add_instance(TranslationService, translation_service)
    services.add_instance(cast(type, ITranslationService), translation_service)

    processor = StubRequestProcessor()
    services.add_instance(StubRequestProcessor, processor)
    services.add_instance(cast(type, IRequestProcessor), processor)

    deps = build_responses_controller_backend_kwargs()
    store = deps["responses_session_store"]
    services.add_instance(InMemoryResponsesSessionStore, store)
    services.add_instance(cast(type, IResponsesSessionStore), store)

    resolver = deps["backend_model_resolver"]
    services.add_instance(cast(type, IBackendModelResolver), resolver)

    openai_proj = deps["openai_responses_projector"]
    anthropic_proj = deps["anthropic_responses_projector"]
    gemini_proj = deps["gemini_responses_projector"]
    services.add_instance(OpenAIResponsesProjector, openai_proj)
    services.add_instance(AnthropicResponsesProjector, anthropic_proj)
    services.add_instance(GeminiResponsesProjector, gemini_proj)

    ControllerStage()._register_responses_controller(services)
    provider_with_controller = services.build_service_provider()

    controller = provider_with_controller.get_required_service(ResponsesController)

    assert isinstance(controller, ResponsesController)
    assert controller._processor is processor
    assert controller._translation_service is translation_service
    assert controller._responses_session_store is store
    assert controller._backend_model_resolver is resolver
    assert controller._openai_responses_projector is openai_proj
    assert controller._anthropic_responses_projector is anthropic_proj
    assert controller._gemini_responses_projector is gemini_proj
