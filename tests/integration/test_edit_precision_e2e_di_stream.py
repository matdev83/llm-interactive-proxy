from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.config.app_config import AppConfig, EditPrecisionConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer

from tests.unit.core.test_doubles import MockCommandProcessor, TestDataBuilder


@pytest.mark.asyncio
async def test_e2e_di_streaming_pipeline_sets_pending_and_next_call_tuned() -> None:
    # Create config with edit precision enabled BEFORE building DI container
    from src.core.config.app_config import SessionConfig

    session_cfg = SessionConfig(
        json_repair_enabled=False, tool_call_repair_enabled=False
    )
    prov_cfg = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.12, override_top_p=True, min_top_p=0.34
        ),
        session=session_cfg,
    )

    # Build DI container with the configured AppConfig
    services = ServiceCollection()
    services.add_instance(AppConfig, prov_cfg)

    # Register infrastructure services (includes ILoopDetector)
    from src.core.app.stages.infrastructure import InfrastructureStage

    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, prov_cfg)

    # Register core services (includes EventBus which is required by streaming services)
    from src.core.app.stages.core_services import CoreServicesStage

    core_services_stage = CoreServicesStage()
    await core_services_stage.execute(services, prov_cfg)

    register_core_services(services, prov_cfg)

    # Register processor services (includes StreamNormalizer with LoopDetectionProcessor)
    from src.core.app.stages.processor import ProcessorStage

    processor_stage = ProcessorStage()
    await processor_stage.execute(services, prov_cfg)

    provider = services.build_service_provider()

    # Resolve the DI-wired normalizer (which will use the config with edit precision enabled)
    normalizer: StreamNormalizer = provider.get_required_service(StreamNormalizer)  # type: ignore[assignment]

    # Also publish to default app_state for request processor path
    app_state: ApplicationStateService = provider.get_required_service(ApplicationStateService)  # type: ignore[assignment]
    app_state.set_setting("app_config", prov_cfg)

    session_id = "di-e2e-sess"

    # Create a stream that includes a failure marker; include id as fallback session key
    async def stream() -> AsyncGenerator[dict, None]:
        yield {
            "id": session_id,
            "choices": [{"delta": {"content": "partial..."}}],
        }
        yield {
            "id": session_id,
            "choices": [{"delta": {"content": "... diff_error ..."}}],
        }

    # Drive the DI-wired streaming pipeline (which includes MiddlewareApplicationProcessor)
    async for _ in normalizer.process_stream(stream(), output_format="objects"):
        pass

    pending = app_state.get_setting("edit_precision_pending", {})
    assert isinstance(pending, dict)
    assert pending.get(session_id, 0) >= 1

    # Now send the next request and assert tuning is applied
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = session_id
    session_manager.get_session.return_value = AsyncMock(id=session_id, agent=None)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Proceed")],
        stream=False,
    )
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    response_manager.process_command_result.return_value = ResponseEnvelope(
        content={"ok": True}
    )

    # Create required mocks
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = AsyncMock(id=session_id, agent=None)
    session_enricher.enrich.return_value = (mock_session, request)
    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = request
    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=request.messages,
        command_executed=False,
        command_results=[],
    )
    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = request
    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    # Mock transform to return a request with tuned parameters
    tuned_request = request.model_copy(update={"temperature": 0.2, "top_p": 0.34})
    transform_pipeline.transform.return_value = tuned_request
    backend_executor = AsyncMock(spec=IBackendExecutor)
    backend_executor.execute.return_value = response

    rp = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=app_state,
    )
    await rp.process_request(
        __import__(
            "tests.unit.core.test_request_processor", fromlist=["MockRequestContext"]
        ).MockRequestContext(),
        request,
    )

    assert transform_pipeline.transform.called
    # Check the output of transform_pipeline.transform (the return value)
    tuned = transform_pipeline.transform.return_value
    # Model-specific config now overrides configured temperature for GPT models (0.2)
    assert tuned.temperature == pytest.approx(0.2)
    assert tuned.top_p == pytest.approx(0.34)
