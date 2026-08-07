"""
Unit tests for Gemini base connector interface contracts.

These tests verify that interface definitions are correct and can be implemented
by mock classes for dependency injection and testing.
"""

from collections.abc import AsyncIterator, Callable
from typing import Any

from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.interfaces import (
    IChatCompletionCoordinator,
    ICodeAssistOrchestrator,
    ICredentialCoordinator,
    IErrorMapper,
    IHealthCheckService,
    IModelRegistry,
    IVtcWrapperBuilder,
)
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.connectors.gemini_base.orchestrator import StreamWrapper
from src.connectors.gemini_base.streaming_executor import ITokenRefresher
from src.core.common.exceptions import LLMProxyError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestICredentialCoordinator:
    """Test ICredentialCoordinator interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that ICredentialCoordinator can be implemented by a mock class."""

        class MockCredentialCoordinator:
            async def initialize(
                self, *, gemini_cli_oauth_path: str | None = None
            ) -> None:
                """Mock initialize method."""

            async def validate_runtime(self) -> bool:
                """Mock validate_runtime method."""
                return True

            async def refresh_if_needed(self, *, force_reload: bool = False) -> bool:
                """Mock refresh_if_needed method."""
                return True

            async def handle_credentials_file_change(self) -> None:
                """Mock file change handler."""

            @property
            def credentials(self) -> GeminiOAuthCredentials | None:
                """Mock credentials property."""
                return None

        coordinator = MockCredentialCoordinator()
        assert isinstance(coordinator, ICredentialCoordinator)

    def test_interface_methods_are_required(self) -> None:
        """Verify that all required methods must be present."""

        class IncompleteCoordinator:
            async def initialize(
                self, *, gemini_cli_oauth_path: str | None = None
            ) -> None:
                pass

            # Missing validate_runtime, refresh_if_needed, credentials

        coordinator = IncompleteCoordinator()
        assert not isinstance(coordinator, ICredentialCoordinator)


class TestIModelRegistry:
    """Test IModelRegistry interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that IModelRegistry can be implemented by a mock class."""

        class MockModelRegistry:
            async def ensure_loaded(self) -> None:
                """Mock ensure_loaded method."""

            def validate(self, model_name: str) -> None:
                """Mock validate method."""

            def to_public_name(self, model_name: str) -> str:
                """Mock to_public_name method."""
                return model_name

            def to_internal_name(self, model_name: str) -> str:
                """Mock to_internal_name method."""
                return model_name

            def list_public_models(self) -> list[str]:
                """Mock list_public_models method."""
                return []

        registry = MockModelRegistry()
        assert isinstance(registry, IModelRegistry)


class TestIHealthCheckService:
    """Test IHealthCheckService interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that IHealthCheckService can be implemented by a mock class."""

        class MockHealthCheckService:
            async def ensure_healthy(self) -> None:
                """Mock ensure_healthy method."""

        service = MockHealthCheckService()
        assert isinstance(service, IHealthCheckService)


class TestIChatCompletionCoordinator:
    """Test IChatCompletionCoordinator interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that IChatCompletionCoordinator can be implemented by a mock class."""

        class MockChatCompletionCoordinator:
            async def execute(
                self,
                request_data: CanonicalChatRequest,
                processed_messages: list[ChatMessage],
                *,
                effective_model: str,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                """Mock execute method."""
                # Return a minimal ResponseEnvelope for testing
                from src.core.domain.responses import ResponseEnvelope

                return ResponseEnvelope(
                    content="test",
                    media_type="text/plain",
                    headers={},
                )

        coordinator = MockChatCompletionCoordinator()
        assert isinstance(coordinator, IChatCompletionCoordinator)


class TestIErrorMapper:
    """Test IErrorMapper interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that IErrorMapper can be implemented by a mock class."""

        class MockErrorMapper:
            def map_exception(
                self, error: Exception, *, backend_name: str
            ) -> LLMProxyError:
                """Mock map_exception method."""
                from src.core.common.exceptions import BackendError

                return BackendError("mapped error", backend_name=backend_name)

        mapper = MockErrorMapper()
        assert isinstance(mapper, IErrorMapper)


class TestIVtcWrapperBuilder:
    """Test IVtcWrapperBuilder interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that IVtcWrapperBuilder can be implemented by a mock class."""

        class MockVtcWrapperBuilder:
            def build(
                self,
                request_data: CanonicalChatRequest,
                *,
                effective_model: str,
            ) -> StreamWrapper | None:
                """Mock build method."""
                return None

        builder = MockVtcWrapperBuilder()
        assert isinstance(builder, IVtcWrapperBuilder)


class TestICodeAssistOrchestrator:
    """Test ICodeAssistOrchestrator interface contract."""

    def test_interface_can_be_implemented(self) -> None:
        """Verify that ICodeAssistOrchestrator can be implemented by a mock class."""

        class MockCodeAssistOrchestrator:
            async def run_streaming(
                self,
                *,
                prepared: PreparedChatRequest,
                url: str,
                token_refresher: ITokenRefresher,
                thought_signature_callback: (
                    Callable[[list[dict[str, Any]], str | None], None] | None
                ) = None,
                key_name: str | None = None,
                stream_wrapper: StreamWrapper | None = None,
            ) -> StreamingResponseEnvelope:
                """Mock run_streaming method."""
                from src.core.domain.responses import StreamingResponseEnvelope

                async def empty_gen() -> AsyncIterator[ProcessedResponse]:
                    return
                    yield  # type: ignore[unreachable]

                return StreamingResponseEnvelope(
                    content=empty_gen(),
                    media_type="text/event-stream",
                    headers={},
                )

            async def run_non_streaming(
                self,
                *,
                prepared: PreparedChatRequest,
                url: str,
                token_refresher: ITokenRefresher,
                thought_signature_callback: (
                    Callable[[list[dict[str, Any]], str | None], None] | None
                ) = None,
                key_name: str | None = None,
            ) -> ResponseEnvelope:
                """Mock run_non_streaming method."""
                from src.core.domain.responses import ResponseEnvelope

                return ResponseEnvelope(
                    content="test",
                    media_type="text/plain",
                    headers={},
                )

        orchestrator = MockCodeAssistOrchestrator()
        assert isinstance(orchestrator, ICodeAssistOrchestrator)
