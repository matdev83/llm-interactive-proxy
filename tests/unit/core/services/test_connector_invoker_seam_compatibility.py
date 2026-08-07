"""Unit tests for ConnectorInvoker seam compatibility and typed contracts."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.connector_invoker import ConnectorInvoker

from tests.unit.core.services.connector_invoker_test_support import (
    MockCanonicalBackend,
    MockLegacyBackend,
)

pytest_plugins = ("tests.unit.core.services.connector_invoker_test_support",)


class TestConnectorSeamCompatibility:
    """Tests for connector seam compatibility and typed contracts (Task 2.6)."""

    @pytest.mark.asyncio
    async def test_canonical_connector_receives_typed_contracts(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
        sample_identity: IAppIdentityConfig,
        sample_session_key: SessionKey,
        sample_cancellation_coordinator: ISessionCancellationCoordinator,
    ) -> None:
        """Test that canonical connectors receive ConnectorChatCompletionsRequest with typed contracts."""
        backend = MockCanonicalBackend()

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=sample_request_context,
            options={"option1": "value1", "option2": 42},
        )

        # Verify canonical connector received typed contract
        assert backend.received_request is not None
        assert isinstance(backend.received_request, ConnectorChatCompletionsRequest)

        # Verify all required fields are present and typed correctly
        assert isinstance(backend.received_request.request, CanonicalChatRequest)
        assert isinstance(backend.received_request.processed_messages, list)
        assert all(
            isinstance(msg, ChatMessage)
            for msg in backend.received_request.processed_messages
        )
        assert isinstance(backend.received_request.effective_model, str)
        assert backend.received_request.identity == sample_identity
        assert backend.received_request.cancellation_token == sample_session_key
        assert (
            backend.received_request.cancellation_coordinator
            == sample_cancellation_coordinator
        )
        assert isinstance(backend.received_request.context, ConnectorRequestContext)
        assert isinstance(backend.received_request.options, dict)

        # Verify context fields are properly projected
        assert backend.received_request.context.request_id == "req-123"
        assert backend.received_request.context.session_id == "session-456"
        assert backend.received_request.context.client_host == "192.168.1.1"
        assert backend.received_request.context.extensions == {
            "key1": "value1",
            "key2": 42,
        }

    @pytest.mark.asyncio
    async def test_connector_context_extensions_json_safe(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
    ) -> None:
        """Test that ConnectorRequestContext extensions are JSON-safe (JsonValue)."""
        import json

        backend = MockCanonicalBackend()

        # Create context with JSON-safe extensions
        context_with_extensions = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            request_id="req-123",
            session_id="session-456",
            client_host="192.168.1.1",
            extensions={
                "string": "value",
                "int": 42,
                "float": 3.14,
                "bool": True,
                "null": None,
                "list": [1, 2, 3],
                "dict": {"nested": "value"},
            },
        )

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=context_with_extensions,
            options={},
        )

        # Verify context extensions are JSON-safe
        assert backend.received_request is not None
        received_context = backend.received_request.context
        assert isinstance(received_context, ConnectorRequestContext)
        assert isinstance(received_context.extensions, dict)

        # Verify extensions can be serialized to JSON
        try:
            json.dumps(received_context.extensions)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Context extensions are not JSON-serializable: {e}")

        # Verify all extension values are JSON-safe types
        for key, value in received_context.extensions.items():
            assert isinstance(
                value, str | int | float | bool | type(None) | list | dict
            ), f"Extension '{key}' contains non-JSON-safe type: {type(value)}"

    @pytest.mark.asyncio
    async def test_legacy_connector_receives_typed_domain_models(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that legacy connectors receive typed domain models, never dicts."""
        backend = MockLegacyBackend()

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={"option1": "value1"},
        )

        # Verify legacy connector received typed domain model, not dict
        assert backend.received_kwargs["request_data"] is not None
        assert isinstance(backend.received_kwargs["request_data"], CanonicalChatRequest)
        assert not isinstance(backend.received_kwargs["request_data"], dict)
        # Verify processed_messages are typed
        assert isinstance(backend.received_kwargs["processed_messages"], list)
        assert all(
            isinstance(msg, ChatMessage)
            for msg in backend.received_kwargs["processed_messages"]
        )

    @pytest.mark.asyncio
    async def test_options_remain_json_safe_no_callables(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that options remain JSON-safe and contain no callables."""
        import json

        from pydantic.types import JsonValue

        backend = MockCanonicalBackend()

        # Options with JSON-safe values only
        json_safe_options: dict[str, JsonValue] = {
            "string_option": "value",
            "int_option": 42,
            "float_option": 3.14,
            "bool_option": True,
            "list_option": [1, 2, 3],
            "dict_option": {"key": "value"},
            "null_option": None,
        }

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=json_safe_options,
        )

        # Verify options are JSON-serializable
        assert backend.received_request is not None
        received_options = backend.received_request.options
        assert isinstance(received_options, dict)

        # Verify no callables in options
        for key, value in received_options.items():
            assert not callable(
                value
            ), f"Option '{key}' contains callable: {type(value)}"

        # Verify options can be serialized to JSON
        try:
            json.dumps(received_options)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Options are not JSON-serializable: {e}")

    @pytest.mark.asyncio
    async def test_error_mapping_preserves_hierarchy(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that error mapping preserves error hierarchy."""
        from src.core.common.exceptions import BackendError, LLMProxyError

        # Create backend that raises BackendError
        class ErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise BackendError(
                    message="Test error",
                    backend_name="test-backend",
                    details={"key": "value"},
                )

        backend = ErrorBackend()

        # Verify error is propagated with correct type
        with pytest.raises(BackendError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        # Verify error hierarchy is preserved
        assert isinstance(exc_info.value, BackendError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Test error"
        assert exc_info.value.backend_name == "test-backend"

    @pytest.mark.asyncio
    async def test_canonical_backend_authentication_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that AuthenticationError is propagated through canonical path."""
        from src.core.common.exceptions import AuthenticationError, LLMProxyError

        class AuthErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise AuthenticationError(
                    message="Authentication failed",
                    details={"reason": "invalid_api_key"},
                )

        backend = AuthErrorBackend()

        with pytest.raises(AuthenticationError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, AuthenticationError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Authentication failed"
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_canonical_backend_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that BackendError is propagated through canonical path."""
        from src.core.common.exceptions import BackendError, LLMProxyError

        class BackendErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise BackendError(
                    message="Backend operation failed",
                    backend_name="test-backend",
                    details={"status_code": 502},
                    status_code=502,
                )

        backend = BackendErrorBackend()

        with pytest.raises(BackendError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, BackendError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Backend operation failed"
        assert exc_info.value.backend_name == "test-backend"
        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_canonical_backend_invalid_request_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that InvalidRequestError is propagated through canonical path."""
        from src.core.common.exceptions import InvalidRequestError, LLMProxyError

        class InvalidRequestErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise InvalidRequestError(
                    message="Invalid request",
                    details={"field": "model", "reason": "model_not_found"},
                )

        backend = InvalidRequestErrorBackend()

        with pytest.raises(InvalidRequestError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, InvalidRequestError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Invalid request"
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_canonical_backend_rate_limit_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that RateLimitExceededError is propagated through canonical path."""
        from src.core.common.exceptions import LLMProxyError, RateLimitExceededError

        class RateLimitErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise RateLimitExceededError(
                    message="Rate limit exceeded",
                    details={"reset_at": 1234567890},
                    reset_at=1234567890,
                )

        backend = RateLimitErrorBackend()

        with pytest.raises(RateLimitExceededError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, RateLimitExceededError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Rate limit exceeded"
        assert exc_info.value.status_code == 429
        assert exc_info.value.reset_at == 1234567890

    @pytest.mark.asyncio
    async def test_canonical_backend_service_unavailable_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that ServiceUnavailableError is propagated through canonical path."""
        from src.core.common.exceptions import LLMProxyError, ServiceUnavailableError

        class ServiceUnavailableErrorBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise ServiceUnavailableError(
                    message="Service temporarily unavailable",
                    details={"retry_after": 60},
                )

        backend = ServiceUnavailableErrorBackend()

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, ServiceUnavailableError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Service temporarily unavailable"
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_legacy_backend_authentication_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that AuthenticationError is propagated through legacy path."""
        from src.core.common.exceptions import AuthenticationError, LLMProxyError

        class AuthErrorLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise AuthenticationError(
                    message="Authentication failed",
                    details={"reason": "invalid_api_key"},
                )

        backend = AuthErrorLegacyBackend()

        with pytest.raises(AuthenticationError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, AuthenticationError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Authentication failed"
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_legacy_backend_backend_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that BackendError is propagated through legacy path."""
        from src.core.common.exceptions import BackendError, LLMProxyError

        class BackendErrorLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise BackendError(
                    message="Backend operation failed",
                    backend_name="test-backend",
                    details={"status_code": 502},
                    status_code=502,
                )

        backend = BackendErrorLegacyBackend()

        with pytest.raises(BackendError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, BackendError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Backend operation failed"
        assert exc_info.value.backend_name == "test-backend"
        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_legacy_backend_invalid_request_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that InvalidRequestError is propagated through legacy path."""
        from src.core.common.exceptions import InvalidRequestError, LLMProxyError

        class InvalidRequestErrorLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise InvalidRequestError(
                    message="Invalid request",
                    details={"field": "model", "reason": "model_not_found"},
                )

        backend = InvalidRequestErrorLegacyBackend()

        with pytest.raises(InvalidRequestError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, InvalidRequestError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Invalid request"
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_legacy_backend_rate_limit_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that RateLimitExceededError is propagated through legacy path."""
        from src.core.common.exceptions import LLMProxyError, RateLimitExceededError

        class RateLimitErrorLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise RateLimitExceededError(
                    message="Rate limit exceeded",
                    details={"reset_at": 1234567890},
                    reset_at=1234567890,
                )

        backend = RateLimitErrorLegacyBackend()

        with pytest.raises(RateLimitExceededError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, RateLimitExceededError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Rate limit exceeded"
        assert exc_info.value.status_code == 429
        assert exc_info.value.reset_at == 1234567890

    @pytest.mark.asyncio
    async def test_legacy_backend_service_unavailable_error_propagation(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that ServiceUnavailableError is propagated through legacy path."""
        from src.core.common.exceptions import LLMProxyError, ServiceUnavailableError

        class ServiceUnavailableErrorLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise ServiceUnavailableError(
                    message="Service temporarily unavailable",
                    details={"retry_after": 60},
                )

        backend = ServiceUnavailableErrorLegacyBackend()

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert isinstance(exc_info.value, ServiceUnavailableError)
        assert isinstance(exc_info.value, LLMProxyError)
        assert exc_info.value.message == "Service temporarily unavailable"
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_error_status_code_preservation_canonical(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that error status codes are preserved through canonical path."""
        from src.core.common.exceptions import BackendError

        # Test various status codes
        status_codes = [400, 401, 403, 404, 429, 500, 502, 503]

        def create_status_code_backend(status_code: int) -> type[MockCanonicalBackend]:
            """Create a backend class for a specific status code."""

            class StatusCodeBackend(MockCanonicalBackend):
                async def chat_completions(
                    self,
                    request: ConnectorChatCompletionsRequest,
                ) -> ResponseEnvelope | StreamingResponseEnvelope:
                    raise BackendError(
                        message=f"Error with status {status_code}",
                        backend_name="test-backend",
                        status_code=status_code,
                    )

            return StatusCodeBackend

        for status_code in status_codes:
            backend_class = create_status_code_backend(status_code)
            backend = backend_class()

            with pytest.raises(BackendError) as exc_info:
                await connector_invoker.invoke(
                    backend=backend,  # type: ignore[arg-type]
                    domain_request=sample_canonical_request,
                    canonical_request=sample_canonical_request,
                    effective_model="gpt-4",
                    identity=None,
                    cancellation_token=None,
                    cancellation_coordinator=None,
                    context=None,
                    options={},
                )

            assert exc_info.value.status_code == status_code

    @pytest.mark.asyncio
    async def test_error_status_code_preservation_legacy(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that error status codes are preserved through legacy path."""
        from src.core.common.exceptions import BackendError

        # Test various status codes
        status_codes = [400, 401, 403, 404, 429, 500, 502, 503]

        def create_status_code_legacy_backend(
            status_code: int,
        ) -> type[MockLegacyBackend]:
            """Create a legacy backend class for a specific status code."""

            class StatusCodeLegacyBackend(MockLegacyBackend):
                async def chat_completions(  # type: ignore[override]
                    self,
                    request_data: Any,
                    processed_messages: list[Any],
                    effective_model: str,
                    identity: IAppIdentityConfig | None = None,
                    cancellation_token: SessionKey | None = None,
                    cancellation_coordinator: Any | None = None,
                    **kwargs: Any,
                ) -> ResponseEnvelope | StreamingResponseEnvelope:
                    raise BackendError(
                        message=f"Error with status {status_code}",
                        backend_name="test-backend",
                        status_code=status_code,
                    )

            return StatusCodeLegacyBackend

        for status_code in status_codes:
            backend_class = create_status_code_legacy_backend(status_code)
            backend = backend_class()

            with pytest.raises(BackendError) as exc_info:
                await connector_invoker.invoke(
                    backend=backend,
                    domain_request=sample_canonical_request,
                    canonical_request=sample_canonical_request,
                    effective_model="gpt-4",
                    identity=None,
                    cancellation_token=None,
                    cancellation_coordinator=None,
                    context=None,
                    options={},
                )

            assert exc_info.value.status_code == status_code

    @pytest.mark.asyncio
    async def test_error_details_preservation_canonical(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that error details are preserved through canonical path."""
        from src.core.common.exceptions import BackendError

        error_details = {
            "error_code": "RATE_LIMIT_EXCEEDED",
            "retry_after": 60,
            "request_id": "req-123",
            "backend_response": {"status": "error", "code": 429},
        }

        class DetailsBackend(MockCanonicalBackend):
            async def chat_completions(
                self,
                request: ConnectorChatCompletionsRequest,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise BackendError(
                    message="Error with details",
                    backend_name="test-backend",
                    details=error_details,
                )

        backend = DetailsBackend()

        with pytest.raises(BackendError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert exc_info.value.details == error_details
        assert exc_info.value.details["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert exc_info.value.details["retry_after"] == 60

    @pytest.mark.asyncio
    async def test_error_details_preservation_legacy(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that error details are preserved through legacy path."""
        from src.core.common.exceptions import BackendError

        error_details = {
            "error_code": "RATE_LIMIT_EXCEEDED",
            "retry_after": 60,
            "request_id": "req-123",
            "backend_response": {"status": "error", "code": 429},
        }

        class DetailsLegacyBackend(MockLegacyBackend):
            async def chat_completions(  # type: ignore[override]
                self,
                request_data: Any,
                processed_messages: list[Any],
                effective_model: str,
                identity: IAppIdentityConfig | None = None,
                cancellation_token: SessionKey | None = None,
                cancellation_coordinator: Any | None = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                raise BackendError(
                    message="Error with details",
                    backend_name="test-backend",
                    details=error_details,
                )

        backend = DetailsLegacyBackend()

        with pytest.raises(BackendError) as exc_info:
            await connector_invoker.invoke(
                backend=backend,  # type: ignore[arg-type]
                domain_request=sample_canonical_request,
                canonical_request=sample_canonical_request,
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

        assert exc_info.value.details == error_details
        assert exc_info.value.details["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert exc_info.value.details["retry_after"] == 60

    @pytest.mark.asyncio
    async def test_options_reject_callables(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that callables in options are detected as non-JSON-serializable."""
        import json

        # Note: The invoker accepts options as dict[str, JsonValue] and passes them through.
        # Type checking at call site should prevent callables, but we test runtime detection.
        # The invoker doesn't filter options - it's the caller's responsibility to ensure JSON-safety.

        backend = MockCanonicalBackend()

        # Create options with a callable (this should not happen in practice due to type checking)
        def some_function() -> None:
            pass

        options_with_callable: dict[str, Any] = {
            "valid_option": "value",
            "callable_option": some_function,  # Not JSON-serializable
        }

        # The invoker passes options through as-is
        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=options_with_callable,  # type: ignore[arg-type]
        )

        # Verify options are passed through
        assert backend.received_request is not None
        received_options = backend.received_request.options
        assert isinstance(received_options, dict)
        assert "valid_option" in received_options
        assert "callable_option" in received_options

        # Verify that non-JSON-serializable values are detected when attempting serialization
        # This documents that callables cannot be serialized, reinforcing JSON-safety requirement
        with pytest.raises(TypeError, match="not JSON serializable"):
            json.dumps(received_options)

    @pytest.mark.asyncio
    async def test_options_reject_complex_objects(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that non-JSON-serializable complex objects are detected."""
        import json

        backend = MockCanonicalBackend()

        # Create options with a complex object that's not JSON-serializable
        class ComplexObject:
            def __init__(self) -> None:
                self.data = "test"

        complex_obj = ComplexObject()

        options_with_complex: dict[str, Any] = {
            "valid_option": "value",
            "complex_option": complex_obj,  # Not JSON-serializable
        }

        # The invoker passes options through as-is
        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=options_with_complex,  # type: ignore[arg-type]
        )

        # Verify options are passed through
        assert backend.received_request is not None
        received_options = backend.received_request.options
        assert isinstance(received_options, dict)
        assert "valid_option" in received_options
        assert "complex_option" in received_options

        # Verify that non-JSON-serializable values are detected when attempting serialization
        # This documents that complex objects cannot be serialized, reinforcing JSON-safety requirement
        with pytest.raises(TypeError, match="not JSON serializable"):
            json.dumps(received_options)

    @pytest.mark.asyncio
    async def test_options_json_serialization_roundtrip(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that options can be serialized and deserialized as JSON."""
        import json

        from pydantic.types import JsonValue

        backend = MockCanonicalBackend()

        # Options with various JSON-safe types
        json_safe_options: dict[str, JsonValue] = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool_true": True,
            "bool_false": False,
            "null": None,
            "list": [1, 2, 3],
            "nested_list": [[1, 2], [3, 4]],
            "dict": {"key": "value"},
            "nested_dict": {"level1": {"level2": "value"}},
            "mixed": {
                "string": "test",
                "number": 42,
                "list": [1, "two", 3.0],
                "dict": {"nested": "value"},
            },
        }

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=json_safe_options,
        )

        # Verify options are JSON-serializable
        assert backend.received_request is not None
        received_options = backend.received_request.options
        assert isinstance(received_options, dict)

        # Serialize to JSON
        json_str = json.dumps(received_options)
        assert isinstance(json_str, str)

        # Deserialize back
        deserialized = json.loads(json_str)
        assert deserialized == received_options

        # Verify roundtrip preserves all values
        assert deserialized["string"] == "value"
        assert deserialized["int"] == 42
        assert deserialized["float"] == 3.14
        assert deserialized["bool_true"] is True
        assert deserialized["bool_false"] is False
        assert deserialized["null"] is None
        assert deserialized["list"] == [1, 2, 3]
        assert deserialized["nested_dict"]["level1"]["level2"] == "value"

    @pytest.mark.asyncio
    async def test_legacy_connector_no_dict_leakage(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
    ) -> None:
        """Test that legacy connectors receive typed domain models, never dicts."""
        backend = MockLegacyBackend()

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=sample_request_context,
            options={"option1": "value1", "option2": 42},
        )

        # Verify request_data is a CanonicalChatRequest, not a dict
        assert backend.received_kwargs["request_data"] is not None
        assert isinstance(backend.received_kwargs["request_data"], CanonicalChatRequest)
        assert not isinstance(backend.received_kwargs["request_data"], dict)

        # Verify processed_messages are typed ChatMessage objects, not dicts
        assert isinstance(backend.received_kwargs["processed_messages"], list)
        assert all(
            isinstance(msg, ChatMessage)
            for msg in backend.received_kwargs["processed_messages"]
        )
        assert not any(
            isinstance(msg, dict)
            for msg in backend.received_kwargs["processed_messages"]
        )

        # Verify effective_model is a string, not a dict
        assert isinstance(backend.received_kwargs["effective_model"], str)
        assert not isinstance(backend.received_kwargs["effective_model"], dict)

    @pytest.mark.asyncio
    async def test_legacy_connector_options_expansion(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test that options are correctly expanded into kwargs for legacy connectors."""
        backend = MockLegacyBackend()

        from pydantic.types import JsonValue

        options: dict[str, JsonValue] = {
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2,
        }

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=options,
        )

        # Verify options are expanded into kwargs
        assert backend.received_kwargs["temperature"] == 0.7
        assert backend.received_kwargs["max_tokens"] == 100
        assert backend.received_kwargs["top_p"] == 0.9
        assert backend.received_kwargs["presence_penalty"] == 0.1
        assert backend.received_kwargs["frequency_penalty"] == 0.2

        # Verify options are not passed as a nested dict
        assert "options" not in backend.received_kwargs or not isinstance(
            backend.received_kwargs.get("options"), dict
        )

    @pytest.mark.asyncio
    async def test_legacy_connector_context_not_guaranteed(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
    ) -> None:
        """Test that context is not passed to legacy connectors (per design)."""
        backend = MockLegacyBackend()

        await connector_invoker.invoke(
            backend=backend,  # type: ignore[arg-type]
            domain_request=sample_canonical_request,
            canonical_request=sample_canonical_request,
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=sample_request_context,
            options={},
        )

        # Verify context is not in kwargs (legacy connectors don't receive context)
        # Per design: connector context is guaranteed only on canonical connector API
        assert "context" not in backend.received_kwargs

        # Verify other required parameters are present
        assert "request_data" in backend.received_kwargs
        assert "processed_messages" in backend.received_kwargs
        assert "effective_model" in backend.received_kwargs
