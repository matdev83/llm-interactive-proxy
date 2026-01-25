"""Tests for BackendRequestManager deduplication integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import DuplicateRequestError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.request_deduplication_interface import (
    IRequestDeduplicationService,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.backend_request_manager_service import BackendRequestManager

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


class TestBackendRequestManagerDeduplication:
    @pytest.fixture
    def mock_backend_processor(self) -> MagicMock:
        return MagicMock(spec=IBackendProcessor)

    @pytest.fixture
    def mock_response_processor(self) -> MagicMock:
        return MagicMock(spec=IResponseProcessor)

    @pytest.fixture
    def mock_angel_service_factory(self) -> MagicMock:
        return MagicMock(spec=IAngelServiceFactory)

    @pytest.fixture
    def mock_dedup_service(self) -> AsyncMock:
        return AsyncMock(spec=IRequestDeduplicationService)

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        return MagicMock(spec=IConfig)

    @pytest.fixture
    def backend_request_manager(
        self,
        mock_backend_processor: MagicMock,
        mock_response_processor: MagicMock,
        mock_angel_service_factory: MagicMock,
        mock_dedup_service: AsyncMock,
        mock_config: MagicMock,
    ) -> BackendRequestManager:
        # Use helper to create manager with all required components
        manager = create_backend_request_manager(
            backend_processor=mock_backend_processor,
            response_processor=mock_response_processor,
        )
        # Set the dedup service
        manager._dedup_service = mock_dedup_service
        return manager

    @pytest.mark.asyncio
    async def test_process_backend_request_calls_dedup_service(
        self,
        backend_request_manager: BackendRequestManager,
        mock_dedup_service: AsyncMock,
        mock_backend_processor: MagicMock,
    ) -> None:
        """Verify that the dedup service is called before processing."""
        # Setup
        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        session_id = "test-session"
        context = RequestContext(
            headers={}, cookies={}, state=MagicMock(), app_state=MagicMock()
        )

        # Mock dedup service to return "not a duplicate"
        mock_dedup_service.check_and_register.return_value = (False, "hash123")

        # Mock backend processing
        mock_backend_processor.process_backend_request = AsyncMock(
            return_value=MagicMock()
        )

        # Execute
        await backend_request_manager.process_backend_request(
            request, session_id, context
        )

        # Verify
        mock_dedup_service.check_and_register.assert_awaited_once_with(
            request, session_id
        )
        mock_backend_processor.process_backend_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_backend_request_raises_on_duplicate(
        self,
        backend_request_manager: BackendRequestManager,
        mock_dedup_service: AsyncMock,
        mock_backend_processor: MagicMock,
    ) -> None:
        """Verify that duplicate requests raise DuplicateRequestError and do not reach backend."""
        # Setup
        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        session_id = "test-session"
        context = RequestContext(
            headers={}, cookies={}, state=MagicMock(), app_state=MagicMock()
        )

        # Mock dedup service to return "IS a duplicate"
        mock_dedup_service.check_and_register.return_value = (True, "hash123")

        # Mock backend processing
        mock_backend_processor.process_backend_request = AsyncMock()

        # Execute & verify
        with pytest.raises(DuplicateRequestError):
            await backend_request_manager.process_backend_request(
                request, session_id, context
            )

        # Backend should not be called on duplicate
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_dedup_enabled_for_streaming_requests(
        self,
        backend_request_manager: BackendRequestManager,
        mock_dedup_service: AsyncMock,
        mock_backend_processor: MagicMock,
    ) -> None:
        """Verify streaming dedup is enabled for streaming requests.
        
        This was changed from bypass to enabled to prevent zombie request
        patterns where clients continue retrying after being stopped.
        
        Status-aware tracking ensures legitimate retries after 429/503
        are still allowed.
        """
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )
        session_id = "test-session"
        context = RequestContext(
            headers={"user-agent": "generic-client/1.0"},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            agent="generic-client/1.0",
        )

        # Mock dedup service to return duplicate
        mock_dedup_service.check_and_register.return_value = (True, "hash123")

        # Execute & verify - should raise DuplicateRequestError
        with pytest.raises(DuplicateRequestError):
            await backend_request_manager.process_backend_request(
                request, session_id, context
            )

        # Dedup service should have been called
        mock_dedup_service.check_and_register.assert_awaited_once_with(
            request, session_id
        )
        # Backend should not be called on duplicate
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_dedup_bypass_via_header(
        self,
        backend_request_manager: BackendRequestManager,
        mock_dedup_service: AsyncMock,
        mock_backend_processor: MagicMock,
    ) -> None:
        """Verify dedup can still be bypassed via x-llmproxy-no-dedup header."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )
        session_id = "test-session"
        context = RequestContext(
            headers={
                "user-agent": "generic-client/1.0",
                "x-llmproxy-no-dedup": "true",
            },
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            agent="generic-client/1.0",
        )

        async def _empty_stream():
            if False:  # pragma: no cover - type hint placeholder
                yield ProcessedResponse()
            return

        mock_backend_processor.process_backend_request = AsyncMock(
            return_value=StreamingResponseEnvelope(content=_empty_stream())
        )
        mock_dedup_service.check_and_register.return_value = (True, "hash123")

        await backend_request_manager.process_backend_request(
            request, session_id, context
        )

        # Dedup should be bypassed via header
        mock_dedup_service.check_and_register.assert_not_called()
        mock_backend_processor.process_backend_request.assert_awaited_once()
