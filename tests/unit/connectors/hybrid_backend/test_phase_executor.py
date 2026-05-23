"""Unit tests for PhaseExecutor service.

Tests cover reasoning and execution phase execution, backend resolution,
timeout handling, and error propagation.

Requirements satisfied:
- Req 9: Phase Executor Extraction
- Req 11: Test-preserving migration
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.hybrid_backend.protocols import IParameterApplicator, IPhaseExecutor
from src.core.common.exceptions import BackendError, ServiceResolutionError
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestPhaseExecutor:
    """Test PhaseExecutor service implementation."""

    @pytest.fixture
    def config(self):
        """Create a mock AppConfig for testing."""
        config = MagicMock()
        config.backends.hybrid_reasoning_model_timeout = 30.0
        config.backends.hybrid_execution_model_timeout = 60.0
        return config

    @pytest.fixture
    def client(self):
        """Create a mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def backend_registry(self):
        """Create a mock BackendRegistry."""
        return MagicMock()

    @pytest.fixture
    def parameter_applicator(self):
        """Create a mock IParameterApplicator."""
        applicator = MagicMock(spec=IParameterApplicator)
        applicator.apply_reasoning_params = MagicMock(side_effect=lambda x, *args: x)
        applicator.apply_execution_params = MagicMock(side_effect=lambda x, *args: x)
        return applicator

    @pytest.fixture
    def identity_resolver(self):
        """Create a mock IdentityResolver."""
        resolver = MagicMock()
        resolver.resolve = MagicMock(return_value=None)
        return resolver

    @pytest.fixture
    def translation_service(self):
        """Create a mock TranslationService."""
        service = MagicMock()
        service.to_domain_request = MagicMock(
            side_effect=lambda x, *args: CanonicalChatRequest(
                model="test-model",
                messages=[{"role": "user", "content": "test"}],
                stream=False,
            )
        )
        return service

    @pytest.fixture
    def phase_executor(
        self,
        client,
        config,
        backend_registry,
        parameter_applicator,
        identity_resolver,
        translation_service,
    ):
        """Create a PhaseExecutor instance for testing."""
        from src.connectors.hybrid_backend.infrastructure.phase_executor import (
            PhaseExecutor,
        )

        return PhaseExecutor(
            client=client,
            config=config,
            backend_registry=backend_registry,
            parameter_applicator=parameter_applicator,
            identity_resolver=identity_resolver,
            translation_service=translation_service,
        )

    @pytest.fixture
    def mock_backend_service(self):
        """Create a mock BackendService."""
        service = MagicMock()
        return service

    @pytest.fixture
    def mock_backend_factory(self):
        """Create a mock BackendFactory."""
        factory = MagicMock()
        return factory

    @pytest.fixture
    def mock_backend_connector(self):
        """Create a mock backend connector."""
        connector = MagicMock()
        connector.chat_completions = AsyncMock()
        return connector

    @pytest.fixture
    def mock_reasoning_stream(self):
        """Create a mock reasoning stream."""

        async def stream():
            chunk1 = ProcessedResponse(content="<thinking>")
            chunk2 = ProcessedResponse(content="reasoning")
            chunk3 = ProcessedResponse(content="</thinking>")
            yield chunk1
            yield chunk2
            yield chunk3

        return stream()

    @pytest.mark.asyncio
    async def test_executor_implements_protocol(self, phase_executor):
        """Verify executor implements IPhaseExecutor protocol."""
        assert isinstance(phase_executor, IPhaseExecutor)

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_success(
        self,
        phase_executor,
        mock_backend_service,
        mock_reasoning_stream,
    ):
        """Test successful reasoning phase execution."""
        # Setup mocks
        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            response = StreamingResponseEnvelope(
                content=mock_reasoning_stream,
                media_type="text/event-stream",
            )
            mock_backend_service.call_completion = AsyncMock(return_value=response)

            request_data = {"model": "test-model", "messages": []}
            identity = AppIdentityConfig(project="test-project")

            result = await phase_executor.execute_reasoning_phase(
                messages=[],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data=request_data,
                identity=identity,
            )

            assert result.__class__.__name__ == "ReasoningPhaseResult"
            assert result.complete is True
            assert "reasoning" in result.text.lower()

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_timeout(
        self,
        phase_executor,
        mock_backend_service,
    ):
        """Test reasoning phase timeout handling."""
        # Setup timeout
        phase_executor.config.backends.hybrid_reasoning_model_timeout = 0.1

        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            # Mock slow response that will timeout
            async def slow_stream():
                await asyncio.sleep(1.0)
                yield ProcessedResponse(content="test")

            # Make call_completion itself slow to trigger timeout
            async def slow_call_completion(*args, **kwargs):
                await asyncio.sleep(1.0)
                return StreamingResponseEnvelope(
                    content=slow_stream(),
                    media_type="text/event-stream",
                )

            mock_backend_service.call_completion = slow_call_completion

            request_data = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "test"}],
            }
            identity = AppIdentityConfig(project="test-project")

            result = await phase_executor.execute_reasoning_phase(
                messages=[{"role": "user", "content": "test"}],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data=request_data,
                identity=identity,
            )

            # Should return empty result on timeout
            assert result.__class__.__name__ == "ReasoningPhaseResult"
            assert result.complete is False
            assert result.text == ""

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_backend_not_found(
        self,
        phase_executor,
    ):
        """Test reasoning phase when backend registry is None."""
        phase_executor.backend_registry = None

        request_data = {"model": "test-model", "messages": []}
        identity = AppIdentityConfig(project="test-project")

        with pytest.raises(BackendError) as exc_info:
            await phase_executor.execute_reasoning_phase(
                messages=[],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data=request_data,
                identity=identity,
            )

        assert "Backend registry not initialized" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_service_resolution_error(
        self,
        phase_executor,
    ):
        """Test reasoning phase when BackendService cannot be resolved."""
        with patch(
            "src.core.di.services.get_required_service",
            side_effect=ServiceResolutionError("BackendService not found"),
        ):
            request_data = {"model": "test-model", "messages": []}
            identity = AppIdentityConfig(project="test-project")

            with pytest.raises(BackendError) as exc_info:
                await phase_executor.execute_reasoning_phase(
                    messages=[],
                    reasoning_backend="openai",
                    reasoning_model="gpt-4",
                    request_data=request_data,
                    identity=identity,
                )

            assert "Failed to initialize reasoning backend" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_uri_params(
        self,
        phase_executor,
        mock_backend_service,
        mock_reasoning_stream,
    ):
        """Test reasoning phase with URI parameters."""
        with (
            patch(
                "src.core.di.services.get_required_service",
                return_value=mock_backend_service,
            ),
            patch(
                "src.core.services.uri_parameter_validator.URIParameterValidator"
            ) as mock_validator_class,
        ):
            mock_validator = MagicMock()
            mock_validator.validate_and_normalize = MagicMock(
                return_value=({"temperature": 0.7}, [])
            )
            mock_validator_class.return_value = mock_validator

            response = StreamingResponseEnvelope(
                content=mock_reasoning_stream,
                media_type="text/event-stream",
            )
            mock_backend_service.call_completion = AsyncMock(return_value=response)

            request_data = {"model": "test-model", "messages": []}
            identity = AppIdentityConfig(project="test-project")
            uri_params = {"temperature": 0.7}

            result = await phase_executor.execute_reasoning_phase(
                messages=[],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data=request_data,
                identity=identity,
                uri_params=uri_params,
            )

            assert result.__class__.__name__ == "ReasoningPhaseResult"
            mock_validator.validate_and_normalize.assert_called_once_with(uri_params)

    @pytest.mark.asyncio
    async def test_execute_reasoning_phase_stream_cancellation(
        self,
        phase_executor,
        mock_backend_service,
        mock_reasoning_stream,
    ):
        """Test reasoning phase stream cancellation callback."""
        cancel_callback = AsyncMock()

        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            response = StreamingResponseEnvelope(
                content=mock_reasoning_stream,
                media_type="text/event-stream",
                cancel_callback=cancel_callback,
            )
            mock_backend_service.call_completion = AsyncMock(return_value=response)

            request_data = {"model": "test-model", "messages": []}
            identity = AppIdentityConfig(project="test-project")

            await phase_executor.execute_reasoning_phase(
                messages=[],
                reasoning_backend="openai",
                reasoning_model="gpt-4",
                request_data=request_data,
                identity=identity,
            )

            # Cancel callback should be called
            cancel_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_execution_phase_success(
        self,
        phase_executor,
        mock_backend_service,
    ):
        """Test successful execution phase."""
        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            response = ResponseEnvelope(
                content={"choices": [{"message": {"content": "response"}}]}
            )
            mock_backend_service.call_completion = AsyncMock(return_value=response)

            request_data = {"model": "test-model", "messages": []}
            augmented_messages = [{"role": "user", "content": "test"}]
            identity = AppIdentityConfig(project="test-project")

            result = await phase_executor.execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend="openai",
                execution_model="gpt-3.5-turbo",
                identity=identity,
            )

            assert isinstance(result, ResponseEnvelope)
            mock_backend_service.call_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_execution_phase_timeout(
        self,
        phase_executor,
        mock_backend_service,
    ):
        """Test execution phase timeout handling."""
        phase_executor.config.backends.hybrid_execution_model_timeout = 0.1

        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            # Mock slow response that will timeout
            async def slow_response():
                await asyncio.sleep(1.0)
                return ResponseEnvelope(content={})

            mock_backend_service.call_completion = slow_response

            request_data = {"model": "test-model", "messages": []}
            augmented_messages = [{"role": "user", "content": "test"}]
            identity = AppIdentityConfig(project="test-project")

            with pytest.raises(BackendError) as exc_info:
                await phase_executor.execute_execution_phase(
                    request_data=request_data,
                    augmented_messages=augmented_messages,
                    execution_backend="openai",
                    execution_model="gpt-3.5-turbo",
                    identity=identity,
                )

            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_execution_phase_backend_not_found(
        self,
        phase_executor,
        mock_backend_service,
    ):
        """Test execution phase when backend is not found."""
        with patch(
            "src.core.di.services.get_required_service",
            return_value=mock_backend_service,
        ):
            mock_backend_service.call_completion = AsyncMock(
                side_effect=ValueError("Backend not found")
            )

            request_data = {"model": "test-model", "messages": []}
            augmented_messages = [{"role": "user", "content": "test"}]
            identity = AppIdentityConfig(project="test-project")

            with pytest.raises(BackendError) as exc_info:
                await phase_executor.execute_execution_phase(
                    request_data=request_data,
                    augmented_messages=augmented_messages,
                    execution_backend="invalid-backend",
                    execution_model="gpt-3.5-turbo",
                    identity=identity,
                )

            assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_execution_phase_uri_params(
        self,
        phase_executor,
        mock_backend_service,
    ):
        """Test execution phase with URI parameters."""
        with (
            patch(
                "src.core.di.services.get_required_service",
                return_value=mock_backend_service,
            ),
            patch(
                "src.core.services.uri_parameter_validator.URIParameterValidator"
            ) as mock_validator_class,
        ):
            mock_validator = MagicMock()
            mock_validator.validate_and_normalize = MagicMock(
                return_value=({"temperature": 0.8}, [])
            )
            mock_validator_class.return_value = mock_validator

            response = ResponseEnvelope(content={})
            mock_backend_service.call_completion = AsyncMock(return_value=response)

            request_data = {"model": "test-model", "messages": []}
            augmented_messages = [{"role": "user", "content": "test"}]
            identity = AppIdentityConfig(project="test-project")
            uri_params = {"temperature": 0.8}

            await phase_executor.execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend="openai",
                execution_model="gpt-3.5-turbo",
                identity=identity,
                uri_params=uri_params,
            )

            mock_validator.validate_and_normalize.assert_called_once_with(uri_params)

    @pytest.mark.asyncio
    async def test_execute_execution_phase_backend_registry_none(
        self,
        phase_executor,
    ):
        """Test execution phase when backend registry is None."""
        phase_executor.backend_registry = None

        request_data = {"model": "test-model", "messages": []}
        augmented_messages = [{"role": "user", "content": "test"}]
        identity = AppIdentityConfig(project="test-project")

        with pytest.raises(BackendError) as exc_info:
            await phase_executor.execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend="openai",
                execution_model="gpt-3.5-turbo",
                identity=identity,
            )

        assert "Backend registry not initialized" in str(exc_info.value)
