"""Canonical connector-facing contracts and protocol.

This module defines the typed contracts used for connector invocation,
replacing permissive dict[str, Any] and Any types at the connector seam boundary.

Contracts defined here:
- ConnectorRequestContext: Minimal connector-facing context contract
- ConnectorChatCompletionsRequest: Canonical connector request payload
- ICanonicalChatCompletionsBackend: Protocol for canonical connector API
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic.types import JsonValue

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import InternalDTO
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)


@dataclass
class ConnectorRequestContext(InternalDTO):
    """Minimal connector-facing context contract.

    Carries only stable, transport-agnostic data needed for logging/diagnostics/correlation,
    without exposing raw transport details (headers/cookies) or core-internal objects.

    This contract is a shallow projection of RequestContext, containing only
    the minimal data needed by connectors for correlation and debugging.

    Attributes:
        request_id: Request correlation identifier (optional)
        session_id: Session correlation identifier (optional)
        client_host: Client host/IP address (optional)
        extensions: JSON-safe extension container for cross-layer metadata
    """

    request_id: str | None
    session_id: str | None
    client_host: str | None
    extensions: dict[str, JsonValue] = field(default_factory=dict)


@dataclass
class ConnectorChatCompletionsRequest(InternalDTO):
    """Canonical connector-facing request contract.

    Bundles all inputs needed for connector invocation in a single typed contract
    at the connector entry boundary.

    Attributes:
        request: Canonical chat request payload
        processed_messages: Typed sequence of processed messages (after command processing)
        effective_model: Model identifier after considering any overrides
        identity: Application identity configuration for authentication (optional)
        cancellation_token: Session key for cancellation scoping (optional)
        cancellation_coordinator: Cancellation coordinator for structural enforcement (optional)
        context: Connector-facing request context (optional)
        options: JSON-safe container for provider-specific connector options
    """

    request: CanonicalChatRequest
    processed_messages: Sequence[ChatMessage]
    effective_model: str
    identity: IAppIdentityConfig | None
    cancellation_token: SessionKey | None
    cancellation_coordinator: ISessionCancellationCoordinator | None
    context: ConnectorRequestContext | None
    options: dict[str, JsonValue] = field(default_factory=dict)


@dataclass
class ConnectorResponsesRequest(InternalDTO):
    request: CanonicalChatRequest
    processed_messages: Sequence[ChatMessage]
    effective_model: str
    identity: IAppIdentityConfig | None
    cancellation_token: SessionKey | None
    cancellation_coordinator: ISessionCancellationCoordinator | None
    context: ConnectorRequestContext | None
    options: dict[str, JsonValue] = field(default_factory=dict)

    @staticmethod
    def from_chat_completions(
        req: ConnectorChatCompletionsRequest,
    ) -> ConnectorResponsesRequest:
        return ConnectorResponsesRequest(
            request=req.request,
            processed_messages=req.processed_messages,
            effective_model=req.effective_model,
            identity=req.identity,
            cancellation_token=req.cancellation_token,
            cancellation_coordinator=req.cancellation_coordinator,
            context=req.context,
            options=dict(req.options),
        )


class ICanonicalChatCompletionsBackend(Protocol):
    """Canonical connector protocol for typed connector invocation.

    Connectors implementing this protocol receive typed contracts and
    return typed response envelopes, eliminating dict/Any leakage at the boundary.

    Core orchestration invokes backends through this contract.

    The protocol is transport-agnostic and does not depend on FastAPI/Starlette types.
    """

    async def chat_completions(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Invoke chat completions using canonical typed contracts.

        Args:
            request: Canonical connector request payload containing:
                - Canonical chat request
                - Typed processed messages
                - Effective model identifier
                - Optional identity, cancellation, and context
                - JSON-safe provider-specific options

        Returns:
            Either ResponseEnvelope for non-streaming requests or
            StreamingResponseEnvelope for streaming requests.

        Raises:
            :class:`LLMProxyError` subclasses only (for example :class:`BackendError`,
            :class:`InvalidRequestError`, :class:`RateLimitExceededError`,
            :class:`AuthenticationError`). Implementations must not raise framework
            HTTP types (for example Starlette/FastAPI ``HTTPException``); transport
            adapters map domain errors to HTTP responses.
        """
        ...


__all__ = [
    "ConnectorRequestContext",
    "ConnectorChatCompletionsRequest",
    "ConnectorResponsesRequest",
    "ICanonicalChatCompletionsBackend",
]
