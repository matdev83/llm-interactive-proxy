from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.b2bua_identity import B2buaIdentity
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

    @pytest.mark.asyncio
    async def test_resolve_session_prefers_a_leg_identity_in_b2bua_mode(
        self, resolver, session_service
    ):
        session_mock = Mock()
        session_service.get_session = AsyncMock(return_value=session_mock)

        context = Mock(spec=RequestContext)
        context.session_id = "legacy-session-id"
        context.b2bua_identity = B2buaIdentity(
            a_session_id="llm-b2bua-a-1234",
            b_session_id="llm-b2bua-b-1234-1",
            b_seq=1,
        )
        request = Mock(spec=ChatRequest)
        request.extra_body = {"session_id": "client-provided-id"}

        session, sid = await resolver.resolve_session(context, request)

        assert session == session_mock
        assert sid == "llm-b2bua-a-1234"
        session_service.get_session.assert_called_once_with("llm-b2bua-a-1234")

    @pytest.mark.asyncio
    async def test_resolve_session_does_not_use_request_session_fallback_in_b2bua_mode(
        self, resolver, session_service
    ):
        session_service.get_session = AsyncMock(return_value=None)

        context = Mock(spec=RequestContext)
        context.session_id = None
        context.b2bua_identity = B2buaIdentity(a_session_id="llm-b2bua-a-7777")
        request = Mock(spec=ChatRequest)
        request.extra_body = {"session_id": "client-provided-id"}

        session, sid = await resolver.resolve_session(context, request)

        assert session is None
        assert sid == "llm-b2bua-a-7777"
        session_service.get_session.assert_called_once_with("llm-b2bua-a-7777")

    @pytest.mark.asyncio
    async def test_resolve_session_prefers_auxiliary_effective_id_in_b2bua_mode(
        self, resolver, session_service
    ):
        session_mock = Mock()
        session_service.get_session = AsyncMock(return_value=session_mock)

        context = Mock(spec=RequestContext)
        context.session_id = "legacy-session-id"
        context.extensions = {
            "auxiliary_request": True,
            "auxiliary_effective_session_id": "aux::llm-b2bua-a-2222",
        }
        context.b2bua_identity = B2buaIdentity(a_session_id="llm-b2bua-a-2222")
        request = Mock(spec=ChatRequest)
        request.extra_body = {"session_id": "client-provided-id"}

        session, sid = await resolver.resolve_session(context, request)

        assert session == session_mock
        assert sid == "aux::llm-b2bua-a-2222"
        session_service.get_session.assert_called_once_with("aux::llm-b2bua-a-2222")
