from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
    ResolvedTarget,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.services.backend_completion_flow.backend_request_preparer import (
    BackendRequestPreparer,
)


class TestBackendRequestPreparer:
    @pytest.fixture
    def backend_model_resolver(self):
        return Mock(spec=IBackendModelResolver)

    @pytest.fixture
    def backend_config_service(self):
        return Mock(spec=IBackendConfigProvider)

    @pytest.fixture
    def reasoning_config_applicator(self):
        return Mock(spec=IReasoningConfigApplicator)

    @pytest.fixture
    def uri_parameter_applicator(self):
        return Mock(spec=IURIParameterApplicator)

    @pytest.fixture
    def config(self):
        return Mock(spec=IConfig)

    @pytest.fixture
    def preparer(
        self,
        backend_model_resolver,
        backend_config_service,
        reasoning_config_applicator,
        uri_parameter_applicator,
        config,
    ):
        return BackendRequestPreparer(
            backend_model_resolver=backend_model_resolver,
            backend_config_service=backend_config_service,
            reasoning_config_applicator=reasoning_config_applicator,
            uri_parameter_applicator=uri_parameter_applicator,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_prepare_request(self, preparer, backend_model_resolver):
        request = Mock(spec=ChatRequest)
        context = Mock(spec=RequestContext)

        resolved = ResolvedTarget(
            backend="openai", model="gpt-4", uri_params={"foo": "bar"}
        )
        backend_model_resolver.resolve_target = AsyncMock(return_value=resolved)

        backend, model, params = await preparer.prepare_request(request, context)

        assert backend == "openai"
        assert model == "gpt-4"
        assert params == {"foo": "bar"}
        backend_model_resolver.resolve_target.assert_called_with(request, context)

    @pytest.mark.asyncio
    async def test_prepare_backend_request(
        self,
        preparer,
        reasoning_config_applicator,
        backend_config_service,
        uri_parameter_applicator,
        config,
    ):
        request = Mock(spec=ChatRequest)
        session = Mock()

        reasoning_config_applicator.apply.return_value = request
        backend_config_service.apply_backend_config.return_value = request
        uri_parameter_applicator.apply.return_value = request

        result = await preparer.prepare_backend_request(
            request=request,
            backend_type="openai",
            session=session,
            uri_params={"foo": "bar"},
        )

        assert result == request
        reasoning_config_applicator.apply.assert_called_with(request, session)
        backend_config_service.apply_backend_config.assert_called_with(
            request, "openai", config
        )
        uri_parameter_applicator.apply.assert_called_with(
            request, {"foo": "bar"}, "openai", session
        )

    @pytest.mark.asyncio
    async def test_prepare_backend_request_resolves_empty_uri_params(
        self,
        preparer,
        reasoning_config_applicator,
        backend_config_service,
        uri_parameter_applicator,
        config,
    ):
        request = Mock(spec=ChatRequest)
        session = Mock()

        reasoning_config_applicator.apply.return_value = request
        backend_config_service.apply_backend_config.return_value = request
        uri_parameter_applicator.apply.return_value = request

        result = await preparer.prepare_backend_request(
            request=request,
            backend_type="openai-responses",
            session=session,
            uri_params={},
        )

        assert result == request
        uri_parameter_applicator.apply.assert_called_once_with(
            request, {}, "openai-responses", session
        )

    def test_prepare_backend_kwargs(self, preparer):
        session = Mock()
        session.state.project = "proj_1"
        session.state.project_dir = "/tmp"

        kwargs = preparer.prepare_backend_kwargs(
            session_id_for_backend="sess_1",
            session=session,
            context=None,
            backend_type="openai",
        )

        assert kwargs["session_id"] == "sess_1"
        assert kwargs["project"] == "proj_1"
        assert kwargs["project_dir"] == "/tmp"

    def test_prepare_backend_kwargs_uses_b_leg_session_id_in_b2bua_mode(self, preparer):
        session = Mock()
        session.state.project = "proj_1"
        session.state.project_dir = "/tmp"
        context = Mock(spec=RequestContext)
        context.b2bua_identity = B2buaIdentity(
            a_session_id="llm-b2bua-a-1234",
            b_session_id="llm-b2bua-b-1234-2",
            b_seq=2,
        )

        kwargs = preparer.prepare_backend_kwargs(
            session_id_for_backend="llm-b2bua-a-1234",
            session=session,
            context=context,
            backend_type="openai",
        )

        assert kwargs["session_id"] == "llm-b2bua-b-1234-2"
        assert kwargs["project"] == "proj_1"
        assert kwargs["project_dir"] == "/tmp"

    def test_prepare_backend_kwargs_omits_session_id_without_b_leg_in_b2bua_mode(
        self, preparer
    ):
        context = Mock(spec=RequestContext)
        context.b2bua_identity = B2buaIdentity(a_session_id="llm-b2bua-a-1234")

        kwargs = preparer.prepare_backend_kwargs(
            session_id_for_backend="llm-b2bua-a-1234",
            session=None,
            context=context,
            backend_type="openai",
        )

        assert "session_id" not in kwargs

    def test_prepare_backend_kwargs_prefers_auxiliary_effective_session_id(
        self, preparer
    ):
        context = Mock(spec=RequestContext)
        context.extensions = {
            "auxiliary_request": True,
            "auxiliary_effective_session_id": "aux::llm-b2bua-a-1234",
        }
        context.b2bua_identity = B2buaIdentity(
            a_session_id="llm-b2bua-a-1234",
            b_session_id="llm-b2bua-b-1234-9",
            b_seq=9,
        )

        kwargs = preparer.prepare_backend_kwargs(
            session_id_for_backend="llm-b2bua-b-1234-9",
            session=None,
            context=context,
            backend_type="openai",
        )

        assert kwargs["session_id"] == "aux::llm-b2bua-a-1234"

    def test_prepare_backend_kwargs_uses_opaque_surrogate_when_required_connector_has_no_b_leg(
        self, preparer
    ):
        context = Mock(spec=RequestContext)
        context.request_id = "req-opaque-1"
        context.extensions = {
            "retry_attempt": 0,
            "auxiliary_attempt_ordinal": 1,
        }
        context.b2bua_identity = B2buaIdentity(a_session_id="llm-b2bua-a-1234")

        kwargs = preparer.prepare_backend_kwargs(
            session_id_for_backend=None,
            session=None,
            context=context,
            backend_type="openai-codex.1",
        )

        surrogate = kwargs.get("session_id")
        assert isinstance(surrogate, str)
        assert surrogate.startswith("sur-openai-codex-")
        assert "llm-b2bua-a-1234" not in surrogate

    @pytest.mark.asyncio
    async def test_prepare_request_routes_auxiliary_via_shared_resolver(
        self,
        backend_model_resolver,
        backend_config_service,
        reasoning_config_applicator,
        uri_parameter_applicator,
        config,
    ) -> None:
        auxiliary_router = Mock()
        auxiliary_router.enabled = True
        auxiliary_router.should_route_to_auxiliary.return_value = True
        auxiliary_router.get_auxiliary_backend.return_value = "openrouter"
        auxiliary_router.get_auxiliary_model.return_value = "openai/gpt-4o-mini"

        preparer = BackendRequestPreparer(
            backend_model_resolver=backend_model_resolver,
            backend_config_service=backend_config_service,
            reasoning_config_applicator=reasoning_config_applicator,
            uri_parameter_applicator=uri_parameter_applicator,
            config=config,
            auxiliary_router=auxiliary_router,
        )

        observed_skip_flags: list[object] = []

        async def _resolve_target_side_effect(request_obj, context_obj):
            assert context_obj is context
            observed_skip_flags.append(
                context_obj.extensions.get("skip_static_route", False)
            )
            if len(observed_skip_flags) == 1:
                return ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
            return ResolvedTarget(
                backend="openrouter.1",
                model="openai/gpt-4o-mini",
                uri_params={"temperature": "0.2"},
            )

        backend_model_resolver.resolve_target = AsyncMock(
            side_effect=_resolve_target_side_effect
        )

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="summarize this chat")],
            extra_body={"backend_type": "openai", "x": "y"},
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-aux",
            session_id="session-1",
        )

        target = await preparer.prepare_request(request, context)

        assert target.backend == "openrouter.1"
        assert target.model == "openai/gpt-4o-mini"
        assert target.uri_params == {"temperature": "0.2"}
        assert backend_model_resolver.resolve_target.call_count == 2

        second_call_request = backend_model_resolver.resolve_target.call_args_list[
            1
        ].args[0]
        assert second_call_request.model == "openrouter:openai/gpt-4o-mini"
        assert second_call_request.extra_body is not None
        assert "backend_type" not in second_call_request.extra_body
        assert second_call_request.extra_body["x"] == "y"
        assert observed_skip_flags == [True, True]
        assert "skip_static_route" not in context.extensions
        assert context.extensions["auxiliary_request"] is True
        assert context.extensions["auxiliary_original_backend"] == "openai"
        assert context.extensions["auxiliary_original_model"] == "gpt-4"
        assert context.extensions["auxiliary_backend"] == "openrouter.1"
        assert context.extensions["auxiliary_model"] == "openai/gpt-4o-mini"
