from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_completion_flow.completion_session_resolver import (
    CompletionSessionResolver,
)


class TestCompletionSessionResolver:
    @pytest.fixture
    def session_service(self):
        return Mock(spec=ISessionService)

    @pytest.fixture
    def resolver(self, session_service):
        return CompletionSessionResolver(session_service=session_service)

    @pytest.mark.asyncio
    async def test_resolve_session_from_context(self, resolver, session_service):
        session_mock = Mock()
        session_service.get_session = AsyncMock(return_value=session_mock)

        context = Mock(spec=RequestContext)
        context.session_id = "sess_ctx"
        request = Mock(spec=ChatRequest)
        request.extra_body = {}

        session, sid = await resolver.resolve_session(context, request)

        assert session == session_mock
        assert sid == "sess_ctx"
        session_service.get_session.assert_called_with("sess_ctx")

    @pytest.mark.asyncio
    async def test_resolve_session_from_request_extra_body(
        self, resolver, session_service
    ):
        session_mock = Mock()
        session_service.get_session = AsyncMock(return_value=session_mock)

        context = Mock(spec=RequestContext)
        context.session_id = None
        request = Mock(spec=ChatRequest)
        request.extra_body = {"session_id": "sess_req"}

        session, sid = await resolver.resolve_session(context, request)

        assert session == session_mock
        assert sid == "sess_req"
        session_service.get_session.assert_called_with("sess_req")

    @pytest.mark.asyncio
    async def test_resolve_session_none(self, resolver, session_service):
        session_service.get_session = AsyncMock(return_value=None)

        context = Mock(spec=RequestContext)
        context.session_id = None
        request = Mock(spec=ChatRequest)
        request.extra_body = {}

        session, sid = await resolver.resolve_session(context, request)

        assert session is None
        assert sid is None
        session_service.get_session.assert_not_called()

