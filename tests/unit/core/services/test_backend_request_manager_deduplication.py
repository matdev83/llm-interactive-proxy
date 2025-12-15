"""Tests for BackendRequestManager deduplication integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import DuplicateRequestError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.request_deduplication_interface import (
    IRequestDeduplicationService,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager


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
        return BackendRequestManager(
            backend_processor=mock_backend_processor,
            response_processor=mock_response_processor,
            angel_service_factory=mock_angel_service_factory,
            config=mock_config,
            dedup_service=mock_dedup_service,
        )

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
