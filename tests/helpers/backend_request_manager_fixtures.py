"""Test fixtures for BackendRequestManager with refactored components."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from src.core.config.app_config import AppConfig
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedChunkContent,
    ProcessedResponse,
)
from src.core.services.backend_request_manager.streaming_response_handler import (
    BackendStreamingResponseHandler,
)
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.backend_request_preparation_service import (
    BackendRequestPreparationService,
)
from src.core.services.post_backend_response_coordinator import (
    PostBackendResponseCoordinator,
)
from src.core.services.tool_call_retry_coordinator import ToolCallRetryCoordinator
from tests.helpers.quality_verifier_factory_stub import QualityVerifierFactoryStub


def create_backend_request_manager(
    backend_processor: IBackendProcessor | None = None,
    response_processor: IResponseProcessor | None = None,
    config: AppConfig | None = None,
    mock_provider: Any | None = None,
    **kwargs: Any,
) -> BackendRequestManager:
    """Create a BackendRequestManager with all required components.

    Args:
        backend_processor: Optional backend processor (defaults to MagicMock)
        response_processor: Optional response processor (defaults to MagicMock)
        config: Optional app config (defaults to minimal config)

    Returns:
        BackendRequestManager instance with all components initialized
    """
    if backend_processor is None:
        backend_processor = MagicMock(spec=IBackendProcessor)

    if response_processor is None:
        response_processor = MagicMock(spec=IResponseProcessor)
        # Default behavior: pass through streaming responses
        response_processor.process_streaming_response = (
            lambda stream, _session_id, context=None, **kwargs: stream
        )

        async def _pass_process_response(
            content: object, _session_id: str, _context: Any = None, **_kwargs: Any
        ) -> ProcessedResponse:
            """Mirrors synthetic single-chunk non-streaming semantics (handler parity)."""

            return ProcessedResponse(content=cast(ProcessedChunkContent, content))

        response_processor.process_response = AsyncMock(
            side_effect=_pass_process_response
        )

    if config is None:
        config = AppConfig.model_validate(
            {
                "session": {
                    "tool_call_reactor": {"enabled": True},
                },
                "empty_response": {"enabled": True, "max_retries": 1},
            }
        )

    # Create request preparation
    history_compaction_service = kwargs.get("history_compaction_service")
    request_preparation = BackendRequestPreparationService(
        history_compaction_service=history_compaction_service, config=config
    )

    # Create tool call retry coordinator
    retry_coordinator = ToolCallRetryCoordinator(backend_processor=backend_processor)

    if mock_provider is None:
        mock_provider = MagicMock(spec=IServiceProvider)
        mock_provider.get_service = MagicMock(return_value=None)
        mock_provider.get_required_service = MagicMock(return_value=None)

    # Ensure get_required_service is available even if mock_provider was passed but doesn't have it
    if not hasattr(mock_provider, "get_required_service"):
        mock_provider.get_required_service = MagicMock(return_value=None)

    # Ensure get_service is available even if mock_provider was passed but doesn't have it
    if not hasattr(mock_provider, "get_service"):
        mock_provider.get_service = MagicMock(return_value=None)

    # Create streaming handler
    from src.core.services.backend_request_manager.loop_detector_factory import (
        LoopDetectorFactory,
    )
    from src.core.services.backend_request_manager.quality_verifier_stream_verifier import (
        QualityVerifierStreamVerifier,
    )
    from src.core.services.structured_output_enforcer import StructuredOutputEnforcer

    loop_detector_factory = LoopDetectorFactory(provider=mock_provider)
    angel_verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=QualityVerifierFactoryStub(),
        provider=mock_provider,
        turn_ledger=MagicMock(),
    )

    structured_output_enforcer = StructuredOutputEnforcer(provider=mock_provider)

    streaming_handler = BackendStreamingResponseHandler(
        response_processor=response_processor,
        loop_detector_factory=loop_detector_factory,
        quality_verifier_stream_verifier=angel_verifier,
        tool_call_retry_coordinator=retry_coordinator,
        backend_processor=backend_processor,
        structured_output_enforcer=structured_output_enforcer,
    )

    # Create BackendRequestManager
    # Merge config into kwargs if provided, but kwargs takes precedence
    manager_kwargs = {
        "history_compaction_service": None,
        "config": config,
        "dedup_service": None,
        **kwargs,  # Allow passing additional keyword arguments like history_compaction_service, etc.
    }
    # If config was passed in kwargs, use that instead
    if "config" in kwargs:
        manager_kwargs["config"] = kwargs["config"]

    post_backend_response_coordinator = manager_kwargs.pop(
        "post_backend_response_coordinator", None
    ) or PostBackendResponseCoordinator(streaming_handler=streaming_handler)

    return BackendRequestManager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        quality_verifier_service_factory=QualityVerifierFactoryStub(),
        request_preparation=request_preparation,
        post_backend_response_coordinator=post_backend_response_coordinator,
        **manager_kwargs,
    )
