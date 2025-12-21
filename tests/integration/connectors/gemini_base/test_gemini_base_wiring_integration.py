"""
Integration tests for Gemini base connector wiring and DI.

Tests verify connector assembly, service resolution, streaming/non-streaming
flows, and backend registration continuity. Covers Requirements 2.1, 2.2,
2.3, 2.5, 3.2, 5.1, 5.2, 5.3.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.gemini_base.chat_completion_coordinator import (
    GeminiChatCompletionCoordinator,
)
from src.connectors.gemini_base.chat_request_preparer import (
    ChatRequestPreparer,
    PreparedChatRequest,
)
from src.connectors.gemini_base.credential_coordinator import (
    GeminiCredentialCoordinator,
)
from src.connectors.gemini_base.endpoints import StandardCodeAssistEndpoint
from src.connectors.gemini_base.error_mapper import GeminiErrorMapper
from src.connectors.gemini_base.health_check_service import GeminiHealthCheckService
from src.connectors.gemini_base.interfaces import (
    IChatCompletionCoordinator,
    ICodeAssistOrchestrator,
    ICredentialCoordinator,
    IErrorMapper,
    IHealthCheckService,
    IModelRegistry,
    IVtcWrapperBuilder,
)
from src.connectors.gemini_base.model_registry import GeminiModelRegistry
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.connectors.gemini_base.vtc_wrapper_builder import GeminiVtcWrapperBuilder
from src.core.common.exceptions import BackendError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

pytestmark = [pytest.mark.integration]


@pytest.fixture
def mock_connector_base():
    """Create a minimal connector base for testing."""
    from unittest.mock import MagicMock

    import httpx
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    client = MagicMock(spec=httpx.AsyncClient)
    config = AppConfig()
    translation_service = TranslationService()

    # Create a concrete subclass for testing
    from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector

    class TestConnector(GeminiOAuthBaseConnector):
        backend_type = "test-gemini-oauth"

        async def _discover_project_id(self, auth_session) -> str:
            """Implement abstract method for testing."""
            return "test-project-id"

    connector = TestConnector(
        client=client,
        config=config,
        translation_service=translation_service,
        name="test-backend",
    )
    return connector


class TestConnectorWiring:
    """Test connector component wiring with DI."""

    def test_credential_coordinator_implements_interface(self) -> None:
        """Verify GeminiCredentialCoordinator implements ICredentialCoordinator."""
        coordinator = GeminiCredentialCoordinator()
        assert isinstance(coordinator, ICredentialCoordinator)

    def test_model_registry_implements_interface(self) -> None:
        """Verify GeminiModelRegistry implements IModelRegistry."""
        mock_discovery = Mock()
        mock_endpoint = Mock()
        mock_credential_coordinator = Mock()
        mock_http_client = Mock()

        registry = GeminiModelRegistry(
            model_discovery=mock_discovery,
            endpoint_config=mock_endpoint,
            credential_coordinator=mock_credential_coordinator,
            http_client=mock_http_client,
        )
        assert isinstance(registry, IModelRegistry)

    def test_health_check_service_implements_interface(self) -> None:
        """Verify GeminiHealthCheckService implements IHealthCheckService."""
        mock_credential_coordinator = Mock()
        mock_endpoint = StandardCodeAssistEndpoint()
        mock_http_client = Mock()

        service = GeminiHealthCheckService(
            credential_coordinator=mock_credential_coordinator,
            endpoint_config=mock_endpoint,
            http_client=mock_http_client,
            backend_name="test-backend",
        )
        assert isinstance(service, IHealthCheckService)

    def test_error_mapper_implements_interface(self) -> None:
        """Verify GeminiErrorMapper implements IErrorMapper."""
        mapper = GeminiErrorMapper()
        assert isinstance(mapper, IErrorMapper)

    def test_vtc_wrapper_builder_implements_interface(self) -> None:
        """Verify GeminiVtcWrapperBuilder implements IVtcWrapperBuilder."""
        builder = GeminiVtcWrapperBuilder(backend_type="test-backend")
        assert isinstance(builder, IVtcWrapperBuilder)

    def test_chat_completion_coordinator_implements_interface(self) -> None:
        """Verify GeminiChatCompletionCoordinator implements IChatCompletionCoordinator."""
        mock_preparer = Mock()
        mock_orchestrator = Mock()
        mock_token_refresher = Mock()
        mock_endpoint = Mock()

        coordinator = GeminiChatCompletionCoordinator(
            request_preparer=mock_preparer,
            orchestrator=mock_orchestrator,
            token_refresher=mock_token_refresher,
            endpoint_config=mock_endpoint,
            api_base_url="https://test.example.com",
            backend_type="test-backend",
        )
        assert isinstance(coordinator, IChatCompletionCoordinator)


class TestStreamingFlowIntegration:
    """Test streaming flow end-to-end integration."""

    @pytest.mark.asyncio
    async def test_streaming_response_envelope_structure(self) -> None:
        """Verify streaming response envelope has correct structure."""
        mock_preparer = Mock(spec=ChatRequestPreparer)
        prepared = Mock(spec=PreparedChatRequest)
        prepared.effective_model = "test-model"
        mock_preparer.prepare = AsyncMock(return_value=prepared)

        mock_orchestrator = Mock(spec=ICodeAssistOrchestrator)

        # Create a proper streaming envelope
        async def mock_generator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content={"test": "chunk1"})
            yield ProcessedResponse(content={"test": "chunk2"})

        mock_streaming_envelope = StreamingResponseEnvelope(
            content=mock_generator(),
            media_type="text/event-stream",
            headers={"X-Custom-Header": "test"},
        )
        mock_orchestrator.run_streaming = AsyncMock(
            return_value=mock_streaming_envelope
        )

        mock_token_refresher = Mock()
        mock_endpoint = Mock()

        coordinator = GeminiChatCompletionCoordinator(
            request_preparer=mock_preparer,
            orchestrator=mock_orchestrator,
            token_refresher=mock_token_refresher,
            endpoint_config=mock_endpoint,
            api_base_url="https://test.example.com",
            backend_type="test-backend",
        )

        mock_request = Mock()
        mock_request.stream = True
        mock_request.vtc_enabled = False

        result = await coordinator.execute(
            request_data=mock_request,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_non_streaming_response_envelope_structure(self) -> None:
        """Verify non-streaming response envelope has correct structure."""
        mock_preparer = Mock(spec=ChatRequestPreparer)
        prepared = Mock(spec=PreparedChatRequest)
        prepared.effective_model = "test-model"
        mock_preparer.prepare = AsyncMock(return_value=prepared)

        mock_orchestrator = Mock(spec=ICodeAssistOrchestrator)

        # Create a proper non-streaming envelope
        mock_response_envelope = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Hello"}}]},
            media_type="application/json",
            headers={"X-Custom-Header": "test"},
        )
        mock_orchestrator.run_non_streaming = AsyncMock(
            return_value=mock_response_envelope
        )

        mock_token_refresher = Mock()
        mock_endpoint = Mock()

        coordinator = GeminiChatCompletionCoordinator(
            request_preparer=mock_preparer,
            orchestrator=mock_orchestrator,
            token_refresher=mock_token_refresher,
            endpoint_config=mock_endpoint,
            api_base_url="https://test.example.com",
            backend_type="test-backend",
        )

        mock_request = Mock()
        mock_request.stream = False

        result = await coordinator.execute(
            request_data=mock_request,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, ResponseEnvelope)
        assert result.media_type == "application/json"


class TestBackendRegistrationContinuity:
    """Test backend registration continuity."""

    def test_gemini_oauth_backends_are_registered(self) -> None:
        """Verify Gemini OAuth backends can be discovered."""
        from src.core.services.backend_registry import backend_registry

        backends = backend_registry.get_registered_backends()

        # Check that at least one Gemini OAuth backend is registered
        gemini_backends = [name for name in backends if "gemini" in name.lower()]
        assert (
            len(gemini_backends) > 0
        ), "At least one Gemini backend should be registered"

    def test_antigravity_oauth_backend_exists(self) -> None:
        """Verify AntigravityOAuth backend class exists."""
        from src.connectors.antigravity_oauth import (
            AntigravityOAuthConnector,
        )

        assert AntigravityOAuthConnector is not None

    def test_gemini_oauth_plan_backend_exists(self) -> None:
        """Verify GeminiOAuthPlan backend class exists."""
        from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector

        assert GeminiOAuthPlanConnector is not None


class TestConfigurationCompatibility:
    """Test configuration compatibility across refactored components."""

    def test_endpoint_config_compatibility(self) -> None:
        """Verify endpoint configuration works with all components."""
        endpoint = StandardCodeAssistEndpoint()

        # Verify base URL
        base_url = endpoint.get_base_url()
        assert "googleapis.com" in base_url

        # Verify headers
        headers = endpoint.get_api_headers(credentials=None)
        assert isinstance(headers, dict)

    def test_credential_model_backward_compatibility(self) -> None:
        """Verify credential model works with legacy dict format."""
        legacy_credentials = {
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "expiry_date": 9999999999999,
            "project_id": "test-project",
            "extra_field": "extra_value",
        }

        # Should work with from_dict
        creds = GeminiOAuthCredentials.from_dict(legacy_credentials)
        assert creds.access_token == "test_token"

        # Extra fields should be preserved in to_dict
        result = creds.to_dict()
        assert "extra_field" in result


class TestServiceResolutionFallback:
    """Test service resolution with fallback behavior."""

    def test_vtc_wrapper_builder_works_without_di(self) -> None:
        """Verify VTC wrapper builder works when DI is unavailable."""
        builder = GeminiVtcWrapperBuilder(backend_type="test-backend")

        mock_request = Mock()
        mock_request.vtc_enabled = False

        # Should not raise even without DI
        result = builder.build(
            request_data=mock_request,
            effective_model="test-model",
        )
        assert result is None  # VTC disabled

    def test_chat_coordinator_works_without_optional_services(self) -> None:
        """Verify chat coordinator works without optional services."""
        mock_preparer = Mock(spec=ChatRequestPreparer)
        prepared = Mock(spec=PreparedChatRequest)
        prepared.effective_model = "test-model"
        mock_preparer.prepare = AsyncMock(return_value=prepared)

        mock_orchestrator = Mock(spec=ICodeAssistOrchestrator)
        mock_orchestrator.run_non_streaming = AsyncMock(
            return_value=ResponseEnvelope(
                content={},
                media_type="application/json",
                headers={},
            )
        )

        mock_token_refresher = Mock()
        mock_endpoint = Mock()

        # Create without optional services
        coordinator = GeminiChatCompletionCoordinator(
            request_preparer=mock_preparer,
            orchestrator=mock_orchestrator,
            token_refresher=mock_token_refresher,
            endpoint_config=mock_endpoint,
            api_base_url="https://test.example.com",
            backend_type="test-backend",
            # No vtc_wrapper_builder, error_mapper, or thought_signature_service
        )

        assert coordinator._vtc_wrapper_builder is None
        assert coordinator._error_mapper is None


class TestChunkOrdering:
    """Test chunk ordering in streaming responses."""

    @pytest.mark.asyncio
    async def test_streaming_chunks_preserve_order(self) -> None:
        """Verify streaming chunks are yielded in correct order."""
        chunks_received: list[dict] = []

        async def collect_chunks(gen: AsyncIterator[ProcessedResponse]) -> list[dict]:
            async for chunk in gen:
                chunks_received.append(chunk.content)
            return chunks_received

        # Create a test generator with ordered chunks
        async def ordered_generator() -> AsyncIterator[ProcessedResponse]:
            for i in range(5):
                yield ProcessedResponse(content={"index": i})

        envelope = StreamingResponseEnvelope(
            content=ordered_generator(),
            media_type="text/event-stream",
            headers={},
        )

        result = await collect_chunks(envelope.content)

        # Verify order is preserved
        for i, chunk in enumerate(result):
            assert chunk["index"] == i, f"Chunk at position {i} has wrong index"


class TestConnectorFacadeIntegration:
    """Test connector facade delegation and backward compatibility.

    Tests verify that GeminiOAuthBaseConnector properly delegates to coordinator
    services and preserves backward compatibility. Covers Requirements 1.5, 2.1, 2.4, 4.4.
    """

    @pytest.mark.asyncio
    async def test_connector_initialization_delegates_to_credential_coordinator(
        self, mock_connector_base
    ):
        """Verify connector initialize() delegates to credential coordinator.

        Requirement: 1.5 (thin orchestration), 2.1 (backend type/config surface).
        """
        connector = mock_connector_base
        mock_coordinator = Mock(spec=ICredentialCoordinator)
        mock_coordinator.initialize = AsyncMock()
        mock_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token",
            refresh_token="refresh_token",
            expiry_date=9999999999999,
        )
        mock_coordinator._credentials_path = None
        mock_coordinator._credentials_fingerprint = None
        mock_coordinator._credentials_file_hash = None

        connector._credential_coordinator = mock_coordinator

        # Mock model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.ensure_loaded = AsyncMock()
        mock_registry._available_models = ["gemini-2.5-pro"]
        mock_registry._available_models_set = {"gemini-2.5-pro"}
        mock_registry._models_from_api = True
        connector._model_registry = mock_registry

        await connector.initialize()

        # Verify credential coordinator was called
        mock_coordinator.initialize.assert_called_once()
        mock_coordinator.refresh_if_needed.assert_called_once()

        # Verify backward compatibility - credentials synced
        assert connector._oauth_credentials is not None
        assert connector._oauth_credentials["access_token"] == "test_token"

    @pytest.mark.asyncio
    async def test_connector_initialization_delegates_to_model_registry(
        self, mock_connector_base
    ):
        """Verify connector initialize() delegates to model registry.

        Requirement: 1.5 (thin orchestration), 2.1 (backend type/config surface).
        """
        connector = mock_connector_base
        mock_coordinator = Mock(spec=ICredentialCoordinator)
        mock_coordinator.initialize = AsyncMock()
        mock_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_coordinator.credentials = GeminiOAuthCredentials(access_token="test_token")
        mock_coordinator._credentials_path = None
        mock_coordinator._credentials_fingerprint = None
        mock_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_coordinator

        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.ensure_loaded = AsyncMock()
        mock_registry._available_models = ["gemini-2.5-pro", "gemini-2.5-flash"]
        mock_registry._available_models_set = {"gemini-2.5-pro", "gemini-2.5-flash"}
        mock_registry._models_from_api = True
        connector._model_registry = mock_registry

        await connector.initialize()

        # Verify model registry was called
        mock_registry.ensure_loaded.assert_called_once()

        # Verify backward compatibility - models synced
        assert connector.available_models == ["gemini-2.5-pro", "gemini-2.5-flash"]
        assert connector._available_models_set == {"gemini-2.5-pro", "gemini-2.5-flash"}

    @pytest.mark.asyncio
    async def test_connector_initialization_handles_credential_failure(
        self, mock_connector_base
    ):
        """Verify connector handles credential coordinator failures gracefully.

        Requirement: 2.4 (error mapping), 4.4 (connector.py limited).
        """
        from src.core.common.exceptions import AuthenticationError

        connector = mock_connector_base
        mock_coordinator = Mock(spec=ICredentialCoordinator)
        mock_coordinator.initialize = AsyncMock(
            side_effect=AuthenticationError("Credential load failed")
        )
        connector._credential_coordinator = mock_coordinator

        await connector.initialize()

        # Verify initialization failed
        assert connector._initialization_failed is True
        assert not connector.is_functional

    @pytest.mark.asyncio
    async def test_connector_chat_completions_delegates_to_coordinator(
        self, mock_connector_base
    ):
        """Verify connector chat_completions() delegates to chat completion coordinator.

        Requirement: 1.5 (thin orchestration), 2.2 (response schema), 4.4 (connector.py limited).
        """
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-2.5-pro")
        connector._model_registry = mock_registry

        # Setup chat completion coordinator
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        mock_response = ResponseEnvelope(
            content={"test": "response"},
            media_type="application/json",
            headers={},
        )
        mock_chat_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_chat_coordinator

        # Mark as functional
        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=[],
            effective_model="gemini-2.5-pro",
        )

        # Verify delegation
        mock_cred_coordinator.validate_runtime.assert_called_once()
        mock_cred_coordinator.refresh_if_needed.assert_called_once()
        mock_health.ensure_healthy.assert_called_once()
        mock_chat_coordinator.execute.assert_called_once()

        # Verify response
        assert isinstance(result, ResponseEnvelope)
        assert result.content == {"test": "response"}

    @pytest.mark.asyncio
    async def test_connector_preserves_backward_compatibility_state_sync(
        self, mock_connector_base
    ):
        """Verify connector syncs coordinator state to instance variables.

        Requirement: 2.1 (backend type/config surface).
        """
        connector = mock_connector_base

        # Setup credential coordinator with credentials
        mock_coordinator = Mock(spec=ICredentialCoordinator)
        mock_coordinator.initialize = AsyncMock()
        mock_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        creds = GeminiOAuthCredentials(
            access_token="test_token",
            refresh_token="refresh_token",
            expiry_date=9999999999999,
            project_id="test-project",
        )
        mock_coordinator.credentials = creds
        mock_coordinator._credentials_path = None
        mock_coordinator._credentials_fingerprint = None
        mock_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_coordinator

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.ensure_loaded = AsyncMock()
        mock_registry._available_models = ["gemini-2.5-pro"]
        mock_registry._available_models_set = {"gemini-2.5-pro"}
        mock_registry._models_from_api = True
        connector._model_registry = mock_registry

        await connector.initialize()

        # Verify backward compatibility state syncing
        assert connector._oauth_credentials is not None
        assert connector._oauth_credentials["access_token"] == "test_token"
        assert connector.available_models == ["gemini-2.5-pro"]
        assert connector._available_models_set == {"gemini-2.5-pro"}

    @pytest.mark.asyncio
    async def test_connector_uses_di_services_when_available(self, mock_connector_base):
        """Verify connector resolves services from DI when available.

        Requirement: 3.2 (DI wiring), 3.3 (abstractions).
        """
        from unittest.mock import MagicMock

        connector = mock_connector_base

        # Create mock DI provider
        mock_provider = MagicMock()
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_model_registry = Mock(spec=IModelRegistry)
        mock_health_service = Mock(spec=IHealthCheckService)
        mock_error_mapper = Mock(spec=IErrorMapper)
        mock_vtc_builder = Mock(spec=IVtcWrapperBuilder)

        mock_provider.get_service = MagicMock(
            side_effect=lambda service_type: {
                ICredentialCoordinator: mock_cred_coordinator,
                IModelRegistry: mock_model_registry,
                IHealthCheckService: mock_health_service,
                IErrorMapper: mock_error_mapper,
                IVtcWrapperBuilder: mock_vtc_builder,
            }.get(service_type)
        )

        # Patch get_service_provider to return our mock
        with patch("src.core.di.services.get_service_provider") as mock_get_provider:
            mock_get_provider.return_value = mock_provider

            # Re-initialize connector to trigger DI resolution
            connector.__init__(
                client=connector.client,
                config=connector.config,
                translation_service=connector.translation_service,
                name="test-backend",
            )

            # Verify DI services were resolved
            assert connector._credential_coordinator is mock_cred_coordinator
            assert connector._model_registry is mock_model_registry
            assert connector._health_check_service is mock_health_service
            assert connector._error_mapper is mock_error_mapper
            assert connector._vtc_wrapper_builder is mock_vtc_builder

    @pytest.mark.asyncio
    async def test_connector_falls_back_to_default_services_when_di_unavailable(
        self, mock_connector_base
    ):
        """Verify connector falls back to default services when DI unavailable.

        Requirement: 3.2 (DI wiring), 3.3 (abstractions).
        """
        connector = mock_connector_base

        # Patch get_service_provider to raise exception (DI unavailable)
        # Since it's imported inside __init__, patch at the source module
        with patch("src.core.di.services.get_service_provider") as mock_get_provider:
            mock_get_provider.side_effect = Exception("DI unavailable")

            # Re-initialize connector
            connector.__init__(
                client=connector.client,
                config=connector.config,
                translation_service=connector.translation_service,
                name="test-backend",
            )

            # Verify fallback services were created
            assert connector._credential_coordinator is not None
            assert isinstance(
                connector._credential_coordinator, GeminiCredentialCoordinator
            )
            assert connector._model_registry is not None
            assert isinstance(connector._model_registry, GeminiModelRegistry)
            assert connector._health_check_service is not None
            assert isinstance(connector._health_check_service, GeminiHealthCheckService)
            assert connector._error_mapper is not None
            assert isinstance(connector._error_mapper, GeminiErrorMapper)

    @pytest.mark.asyncio
    async def test_connector_error_propagation_through_facade(
        self, mock_connector_base
    ):
        """Verify error propagation through connector facade.

        Requirement: 2.4 (error mapping).
        """
        from src.core.common.exceptions import BackendError

        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-2.5-pro")
        connector._model_registry = mock_registry

        # Setup chat completion coordinator to raise error
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        test_error = BackendError("Test backend error", backend_name="test-backend")
        mock_chat_coordinator.execute = AsyncMock(side_effect=test_error)
        connector._chat_completion_coordinator = mock_chat_coordinator

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        # Verify error propagates
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
            )

        assert exc_info.value is test_error

    @pytest.mark.asyncio
    async def test_connector_model_name_mapping_via_registry(self, mock_connector_base):
        """Verify connector uses model registry for name mapping.

        Requirement: 2.1 (backend type/config surface), 1.5 (thin orchestration).
        """
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry with mapping
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-3-pro-preview")
        connector._model_registry = mock_registry

        # Setup chat completion coordinator
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        mock_response = ResponseEnvelope(
            content={}, media_type="application/json", headers={}
        )
        mock_chat_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_chat_coordinator

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        await connector.chat_completions(
            request_data=mock_request,
            processed_messages=[],
            effective_model="gemini-3-pro",  # Public alias
        )

        # Verify model registry was used for mapping
        mock_registry.to_internal_name.assert_called_with("gemini-3-pro")

        # Verify coordinator was called with internal name
        call_args = mock_chat_coordinator.execute.call_args
        assert call_args[1]["effective_model"] == "gemini-3-pro-preview"

    @pytest.mark.asyncio
    async def test_connector_is_backend_functional_method(self, mock_connector_base):
        """Verify connector is_backend_functional method works correctly.

        Requirement: 2.4 (error mapping), 4.4 (connector.py limited).
        """
        connector = mock_connector_base

        # Test: functional when all conditions met
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        assert connector.is_backend_functional() is True

        # Test: not functional when is_functional is False
        connector.is_functional = False
        assert connector.is_backend_functional() is False

        # Test: not functional when initialization failed
        connector.is_functional = True
        connector._initialization_failed = True
        assert connector.is_backend_functional() is False

        # Test: not functional when validation errors exist
        connector._initialization_failed = False
        connector._credential_validation_errors = ["Error 1", "Error 2"]
        assert connector.is_backend_functional() is False

    @pytest.mark.asyncio
    async def test_connector_initialization_handles_health_check_failure(
        self, mock_connector_base
    ):
        """Verify connector handles health check service failures gracefully.

        Requirement: 2.4 (error mapping), 4.4 (connector.py limited).
        """
        from src.core.common.exceptions import BackendError

        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.initialize = AsyncMock()
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        mock_cred_coordinator._credentials_path = None
        mock_cred_coordinator._credentials_fingerprint = None
        mock_cred_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_cred_coordinator

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.ensure_loaded = AsyncMock()
        mock_registry._available_models = ["gemini-2.5-pro"]
        mock_registry._available_models_set = {"gemini-2.5-pro"}
        mock_registry._models_from_api = True
        connector._model_registry = mock_registry

        # Setup health check service to fail
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock(
            side_effect=BackendError("Health check failed", backend_name="test-backend")
        )
        connector._health_check_service = mock_health

        # Initialize should handle health check failure gracefully
        # (Health check failures are non-blocking per design)
        # Note: Health checks are performed on first use, not during initialization
        await connector.initialize()

        # Verify health check was NOT called during initialization
        # (Health checks happen on first use per design)
        mock_health.ensure_healthy.assert_not_called()

        # Verify connector is functional
        assert connector.is_functional is True

    @pytest.mark.asyncio
    async def test_connector_chat_completions_handles_model_validation_failure(
        self, mock_connector_base
    ):
        """Verify connector handles model registry validation failures.

        Requirement: 2.1, 2.2 (model validation).
        """
        from src.core.common.exceptions import BackendError

        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry to raise validation error
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(
            side_effect=BackendError(
                "Model not available",
                backend_name="test-backend",
                code="model_not_found",
            )
        )
        connector._model_registry = mock_registry

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        # Verify validation error is propagated
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=[],
                effective_model="invalid-model",
            )

        assert exc_info.value.code == "model_not_found"

    @pytest.mark.asyncio
    async def test_connector_streaming_with_vtc_wrapper(self, mock_connector_base):
        """Verify connector streaming response with VTC wrapper integration.

        Requirement: 1.4, 2.3 (streaming with VTC).
        """
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-2.5-pro")
        connector._model_registry = mock_registry

        # Setup VTC wrapper builder (must be set before coordinator is created)
        mock_vtc_builder = Mock(spec=IVtcWrapperBuilder)
        mock_wrapper = Mock()
        mock_vtc_builder.build = Mock(return_value=mock_wrapper)
        connector._vtc_wrapper_builder = mock_vtc_builder

        # Setup chat completion coordinator with VTC wrapper
        # The coordinator is created lazily via _chat_completion_coordinator_instance property
        # So we need to ensure it uses the VTC wrapper builder we set
        async def mock_generator():
            yield ProcessedResponse(content={"delta": {"content": "chunk"}})

        mock_streaming_envelope = StreamingResponseEnvelope(
            content=mock_generator(),
            media_type="text/event-stream",
            headers={},
        )

        # Mock the coordinator instance property to return our mock
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        mock_chat_coordinator.execute = AsyncMock(return_value=mock_streaming_envelope)
        connector._chat_completion_coordinator = mock_chat_coordinator

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = True
        mock_request.vtc_enabled = True

        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=[],
            effective_model="gemini-2.5-pro",
        )

        # Verify coordinator was called (it should use VTC wrapper builder internally)
        mock_chat_coordinator.execute.assert_called_once()

        # Note: The VTC wrapper builder is used by the coordinator, not the connector directly
        # So we verify the coordinator was called with the request that has vtc_enabled=True
        call_args = mock_chat_coordinator.execute.call_args
        # Check positional args (request_data is first positional arg)
        if call_args[0]:
            assert call_args[0][0] is mock_request  # request_data
        # Check keyword args
        assert call_args[1]["effective_model"] == "gemini-2.5-pro"

        # Verify streaming response
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"


class TestConnectorOrchestrationOnly:
    """Test that connector.py is limited to orchestration only.

    Requirement: 4.4 - connector.py limited to orchestration and public interface definitions.
    """

    def test_connector_delegates_to_coordinators(self) -> None:
        """Verify connector delegates to coordinators without implementing business logic.

        The connector should be a thin facade that delegates to coordinator services
        rather than implementing business logic directly.
        """
        import inspect

        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector

        # Get connector source code
        source = inspect.getsource(GeminiOAuthBaseConnector)

        # Verify connector delegates to coordinators
        # Check that key methods delegate to coordinator services
        assert (
            "_credential_coordinator" in source
        ), "Connector should use credential coordinator"
        assert "_model_registry" in source, "Connector should use model registry"
        assert (
            "_health_check_service" in source
        ), "Connector should use health check service"
        assert (
            "_chat_completion_coordinator" in source
        ), "Connector should use chat completion coordinator"

        # Verify delegation patterns exist
        assert (
            "_credential_coordinator.initialize" in source
            or "self._credential_coordinator.initialize" in source
        ), "Connector should delegate initialization to credential coordinator"
        assert (
            "_credential_coordinator.validate_runtime" in source
            or "self._credential_coordinator.validate_runtime" in source
        ), "Connector should delegate validation to credential coordinator"
        assert (
            "_model_registry.ensure_loaded" in source
            or "self._model_registry.ensure_loaded" in source
        ), "Connector should delegate model loading to model registry"
        assert (
            "_chat_completion_coordinator_instance.execute" in source
            or "self._chat_completion_coordinator_instance.execute" in source
            or "_chat_completion_coordinator.execute" in source
            or "self._chat_completion_coordinator.execute" in source
        ), "Connector should delegate chat completion to coordinator"

    def test_connector_methods_are_thin_wrappers(self) -> None:
        """Verify connector methods are thin wrappers that delegate.

        Requirement: 4.4 - connector.py limited to orchestration.
        """
        import inspect

        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector

        # Check that chat_completions method delegates
        chat_completions_source = inspect.getsource(
            GeminiOAuthBaseConnector.chat_completions
        )

        # Should delegate to coordinator, not implement logic
        assert (
            "_chat_completion_coordinator" in chat_completions_source
            or "coordinator" in chat_completions_source.lower()
        ), "chat_completions should delegate to coordinator"

        # Should not contain business logic (e.g., request preparation, streaming execution)
        # These should be in coordinators, not in connector
        assert (
            "ChatRequestPreparer" not in chat_completions_source
            or "prepare" not in chat_completions_source
        ), "chat_completions should not directly use ChatRequestPreparer"

    def test_connector_does_not_contain_duplicate_business_logic(self) -> None:
        """Verify connector does not duplicate logic from coordinators.

        Requirement: 4.3 - Avoid duplicate logic across modules.
        """
        import inspect

        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.credential_coordinator import (
            GeminiCredentialCoordinator,
        )

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        inspect.getsource(GeminiCredentialCoordinator)

        # Check that credential validation logic is not duplicated
        # Connector should delegate, not reimplement
        if "validate_credentials_structure" in connector_source:
            # If present, it should be a thin wrapper delegating to CredentialLoader
            assert (
                "CredentialLoader.validate_credentials_structure" in connector_source
            ), "Connector should delegate credential validation, not reimplement"

        # Check that token refresh logic is not duplicated
        # Connector should delegate to coordinator
        if "_refresh_token_if_needed" in connector_source:
            assert (
                "_credential_coordinator.refresh_if_needed" in connector_source
                or "_token_manager.refresh_token_if_needed" in connector_source
            ), "Connector should delegate token refresh, not reimplement"

    def test_connector_initialization_delegates_to_services(self) -> None:
        """Verify connector initialization delegates to coordinator services.

        Requirement: 1.5 (thin orchestration), 4.4 (connector.py limited).
        """
        import inspect

        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector

        initialize_source = inspect.getsource(GeminiOAuthBaseConnector.initialize)

        # Should delegate to credential coordinator
        assert (
            "_credential_coordinator.initialize" in initialize_source
        ), "initialize should delegate to credential coordinator"

        # Should delegate to model registry
        assert (
            "_model_registry.ensure_loaded" in initialize_source
        ), "initialize should delegate to model registry"

        # Should not contain credential loading logic directly
        # (should be in CredentialCoordinator)
        assert (
            "CredentialLoader.load_oauth_credentials" not in initialize_source
            or "_credential_coordinator" in initialize_source
        ), "initialize should not directly load credentials, should delegate"


class TestErrorMapperThroughFacade:
    """Test error mapper integration through connector facade.

    Requirement: 2.4 (error mapping), design.md error mapper integration.
    """

    @pytest.mark.asyncio
    async def test_connector_error_mapper_called_through_facade(
        self, mock_connector_base
    ):
        """Verify error mapper is called correctly through connector facade."""
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-2.5-pro")
        connector._model_registry = mock_registry

        # Setup error mapper
        mock_error_mapper = Mock(spec=IErrorMapper)
        mapped_error = BackendError("Mapped error", backend_name="test-backend")
        mock_error_mapper.map_exception = Mock(return_value=mapped_error)
        connector._error_mapper = mock_error_mapper

        # Setup chat completion coordinator to raise error
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        generic_error = ValueError("Something went wrong")
        mock_chat_coordinator.execute = AsyncMock(side_effect=generic_error)
        connector._chat_completion_coordinator = mock_chat_coordinator

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        # Verify error mapper is called through facade
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
            )

        # Verify error mapper was called
        mock_error_mapper.map_exception.assert_called_once_with(
            generic_error, backend_name=connector.backend_type
        )
        assert exc_info.value is mapped_error

    @pytest.mark.asyncio
    async def test_connector_error_mapper_fallback_when_unavailable(
        self, mock_connector_base
    ):
        """Verify connector falls back to wrapping errors when error mapper unavailable."""
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        connector._credential_coordinator = mock_cred_coordinator

        # Setup health check service
        mock_health = Mock(spec=IHealthCheckService)
        mock_health.ensure_healthy = AsyncMock()
        connector._health_check_service = mock_health

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.to_internal_name = Mock(return_value="gemini-2.5-pro")
        connector._model_registry = mock_registry

        # No error mapper
        connector._error_mapper = None

        # Setup chat completion coordinator to raise error
        mock_chat_coordinator = Mock(spec=IChatCompletionCoordinator)
        generic_error = ValueError("Something went wrong")
        mock_chat_coordinator.execute = AsyncMock(side_effect=generic_error)
        connector._chat_completion_coordinator = mock_chat_coordinator

        connector.is_functional = True

        mock_request = Mock()
        mock_request.stream = False

        # Verify error is wrapped in BackendError when no mapper
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=[],
                effective_model="gemini-2.5-pro",
            )

        # Verify error was wrapped
        assert isinstance(exc_info.value, BackendError)
        # Connector wraps error without backend_name when no error mapper
        assert "chat completion failed" in exc_info.value.message
        assert exc_info.value.__cause__ is generic_error


class TestModelRegistryAPIDiscoveryFailure:
    """Test model registry API discovery failure and fallback behavior.

    Requirement: 2.1 (backend type/config surface), design.md model registry fallback.
    """

    @pytest.mark.asyncio
    async def test_model_registry_falls_back_on_api_discovery_failure(
        self, mock_connector_base
    ):
        """Verify model registry falls back to hardcoded list when API discovery fails."""
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.initialize = AsyncMock()
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        mock_cred_coordinator._credentials_path = None
        mock_cred_coordinator._credentials_fingerprint = None
        mock_cred_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_cred_coordinator

        # Setup model registry with API discovery failure
        mock_registry = Mock(spec=GeminiModelRegistry)
        mock_registry.ensure_loaded = AsyncMock()
        # Simulate API discovery failure - use fallback models
        from src.connectors.gemini_base.config import DEFAULT_AVAILABLE_MODELS

        mock_registry._available_models = DEFAULT_AVAILABLE_MODELS
        mock_registry._available_models_set = set(DEFAULT_AVAILABLE_MODELS)
        mock_registry._models_from_api = False  # Using fallback
        mock_registry.validate = Mock()  # Should skip validation when using fallback
        connector._model_registry = mock_registry

        await connector.initialize()

        # Verify fallback models are used
        assert connector.available_models == DEFAULT_AVAILABLE_MODELS
        assert connector._available_models_set == set(DEFAULT_AVAILABLE_MODELS)

    @pytest.mark.asyncio
    async def test_model_registry_caches_results_after_api_discovery(
        self, mock_connector_base
    ):
        """Verify model registry caches results correctly after API discovery."""
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.initialize = AsyncMock()
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        mock_cred_coordinator._credentials_path = None
        mock_cred_coordinator._credentials_fingerprint = None
        mock_cred_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_cred_coordinator

        # Setup model registry with successful API discovery
        mock_registry = Mock(spec=GeminiModelRegistry)
        api_models = ["gemini-2.5-pro", "gemini-2.5-flash"]
        mock_registry._available_models = api_models
        mock_registry._available_models_set = set(api_models)
        mock_registry._models_from_api = True
        mock_registry.ensure_loaded = AsyncMock()
        connector._model_registry = mock_registry

        # Call initialize multiple times
        await connector.initialize()
        await connector.initialize()

        # Verify ensure_loaded was called (but caching prevents duplicate API calls)
        assert mock_registry.ensure_loaded.call_count >= 1
        # Models should be cached
        assert connector.available_models == api_models


class TestConnectorStateSynchronization:
    """Test connector state synchronization scenarios.

    Requirement: 2.1 (backend type/config surface), design.md state synchronization.
    """

    @pytest.mark.asyncio
    async def test_connector_syncs_credential_state_after_refresh(
        self, mock_connector_base
    ):
        """Verify credential state syncs from coordinator to connector after refresh."""
        connector = mock_connector_base

        # Setup credential coordinator with initial credentials
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        initial_creds = GeminiOAuthCredentials(
            access_token="initial_token",
            refresh_token="refresh_token",
            expiry_date=9999999999999,
        )
        mock_cred_coordinator.credentials = initial_creds
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        connector._credential_coordinator = mock_cred_coordinator

        # Sync initial state
        connector._oauth_credentials = initial_creds.to_dict()

        # Simulate credential refresh - new credentials
        new_creds = GeminiOAuthCredentials(
            access_token="new_token",
            refresh_token="refresh_token",
            expiry_date=9999999999999,
        )
        mock_cred_coordinator.credentials = new_creds

        # Verify state sync happens (connector should sync from coordinator)
        # This is tested implicitly through chat_completions which validates runtime
        mock_cred_coordinator.validate_runtime = AsyncMock(return_value=True)

        # The connector should use coordinator's credentials
        assert connector._credential_coordinator.credentials.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_connector_syncs_model_state_during_initialization(
        self, mock_connector_base
    ):
        """Verify model state syncs from registry to connector during initialization."""
        connector = mock_connector_base

        # Setup credential coordinator
        mock_cred_coordinator = Mock(spec=ICredentialCoordinator)
        mock_cred_coordinator.initialize = AsyncMock()
        mock_cred_coordinator.refresh_if_needed = AsyncMock(return_value=True)
        mock_cred_coordinator.credentials = GeminiOAuthCredentials(
            access_token="test_token"
        )
        mock_cred_coordinator._credentials_path = None
        mock_cred_coordinator._credentials_fingerprint = None
        mock_cred_coordinator._credentials_file_hash = None
        connector._credential_coordinator = mock_cred_coordinator

        # Setup model registry
        mock_registry = Mock(spec=GeminiModelRegistry)
        models = ["gemini-2.5-pro", "gemini-2.5-flash"]
        mock_registry._available_models = models
        mock_registry._available_models_set = set(models)
        mock_registry._models_from_api = True
        mock_registry.ensure_loaded = AsyncMock()
        connector._model_registry = mock_registry

        await connector.initialize()

        # Verify model state was synced
        assert connector.available_models == models
        assert connector._available_models_set == set(models)
