from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.chat import ChatRequest
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

