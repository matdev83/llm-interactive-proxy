"""Connector invoker service with canonical-first dispatch and legacy fallback.

This service handles connector invocation through a typed boundary, preferring
the canonical connector API when available and falling back to the legacy API
with typed domain models (never dicts).
"""

from __future__ import annotations

import contextlib
import copy
import inspect
import logging
from collections.abc import Sequence
from typing import Any

from pydantic.types import JsonValue

from src.connectors.base import LLMBackend
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
from src.core.services.boundary_validation import extract_correlation_ids

logger = logging.getLogger(__name__)


class ConnectorInvoker:
    """Service for invoking connectors with canonical-first dispatch.

    This invoker builds canonical connector request contracts, projects
    RequestContext to ConnectorRequestContext, and dispatches to the canonical
    API when available, falling back to the legacy API with typed domain models.

    The invoker ensures that:
    - Canonical backends receive ConnectorChatCompletionsRequest contracts
    - Legacy backends receive canonical domain models (never dicts)
    - Options are expanded into kwargs only for legacy path
    - Legacy path usage is logged for observability
    """

    def _project_context(
        self, context: RequestContext | None
    ) -> ConnectorRequestContext | None:
        """Project RequestContext to ConnectorRequestContext.

        Performs a shallow, JSON-safe mapping of stable, transport-agnostic
        data needed for logging/diagnostics/correlation.

        Args:
            context: Request context to project, or None

        Returns:
            ConnectorRequestContext with projected fields, or None if context is None
        """
        if context is None:
            return None

        # Deep copy extensions dict to avoid shared mutable state
        extensions = copy.deepcopy(context.extensions) if context.extensions else {}

        return ConnectorRequestContext(
            request_id=context.request_id,
            session_id=context.session_id,
            client_host=context.client_host,
            extensions=extensions,
        )

    def _build_canonical_request(
        self,
        domain_request: CanonicalChatRequest,
        processed_messages: Sequence[ChatMessage],
        effective_model: str,
        identity: IAppIdentityConfig | None,
        cancellation_token: SessionKey | None,
        cancellation_coordinator: ISessionCancellationCoordinator | None,
        context: ConnectorRequestContext | None,
        options: dict[str, JsonValue],
    ) -> ConnectorChatCompletionsRequest:
        """Build ConnectorChatCompletionsRequest from canonical inputs.

        Args:
            domain_request: Canonical chat request payload
            processed_messages: Typed sequence of processed messages
            effective_model: Model identifier after considering any overrides
            identity: Application identity configuration for authentication
            cancellation_token: Session key for cancellation scoping
            cancellation_coordinator: Cancellation coordinator for structural enforcement
            context: Connector-facing request context (from projection)
            options: JSON-safe container for provider-specific connector options

        Returns:
            ConnectorChatCompletionsRequest with all inputs bundled

        Raises:
            ValueError: If options dict contains reserved keys that conflict with contract fields
        """
        # Validate that options dict doesn't contain reserved keys
        reserved_keys = {
            "context",
            "request",
            "processed_messages",
            "effective_model",
            "identity",
            "cancellation_token",
            "cancellation_coordinator",
        }
        conflicting_keys = reserved_keys.intersection(options.keys())
        if conflicting_keys:
            raise ValueError(
                f"Options dict contains reserved keys that conflict with ConnectorChatCompletionsRequest fields: {conflicting_keys}. "
                "These keys are reserved and cannot be used in the options dict."
            )

        return ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            cancellation_token=cancellation_token,
            cancellation_coordinator=cancellation_coordinator,
            context=context,
            options=options,
        )

    def _is_canonical_backend(self, backend: LLMBackend) -> bool:
        """Check if backend implements ICanonicalChatCompletionsBackend.

        Uses structural typing check: verifies that the backend has a
        chat_completions method with the canonical signature (first parameter
        named "request" with ConnectorChatCompletionsRequest type).

        Handles backward-compatible signatures like:
        - chat_completions(request: ConnectorChatCompletionsRequest)
        - chat_completions(request: ConnectorChatCompletionsRequest, *args, **kwargs)

        Args:
            backend: Backend instance to check

        Returns:
            True if backend implements canonical API, False otherwise
        """
        # Check if backend has chat_completions method
        if not hasattr(backend, "chat_completions"):
            return False

        method = backend.chat_completions
        if not callable(method):
            return False

        # Get method signature
        # Note: inspect.signature on a bound method doesn't include 'self'
        try:
            sig = inspect.signature(method)
        except (ValueError, TypeError):
            # If signature inspection fails, assume legacy
            return False

        params = list(sig.parameters.values())

        # Filter out varargs (*args) and varkwargs (**kwargs) for counting
        # Canonical API may have: chat_completions(request, *args, **kwargs)
        # We only care about required positional/keyword parameters
        required_params = [
            p
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        ]

        # Canonical API should have exactly 1 required parameter (request)
        # Legacy API has many required parameters (request_data, processed_messages, etc.)
        if len(required_params) != 1:
            return False

        # Check the first required parameter
        request_param = required_params[0]

        # Parameter name should be "request" for canonical API
        # Legacy API uses "request_data" as first parameter
        if request_param.name != "request":
            return False

        # Check type annotation
        param_annotation = request_param.annotation

        # Check if annotation matches ConnectorChatCompletionsRequest
        if param_annotation == ConnectorChatCompletionsRequest:
            return True

        # Handle string annotations (forward references)
        if (
            isinstance(param_annotation, str)
            and "ConnectorChatCompletionsRequest" in param_annotation
        ):
            return True

        # Check if annotation is a type that matches (handle Union, etc.)
        with contextlib.suppress(AttributeError, TypeError):
            from typing import get_args, get_origin

            origin = get_origin(param_annotation)
            if origin is not None:
                args = get_args(param_annotation)
                if ConnectorChatCompletionsRequest in args:
                    return True

        # Require explicit type annotation - do not fall back to True without verification
        # This prevents misclassifying legacy connectors that happen to have a parameter named "request"
        return False

    async def invoke(
        self,
        backend: LLMBackend,
        domain_request: CanonicalChatRequest,
        canonical_request: CanonicalChatRequest,
        effective_model: str,
        identity: IAppIdentityConfig | None,
        cancellation_token: SessionKey | None,
        cancellation_coordinator: ISessionCancellationCoordinator | None,
        context: RequestContext | None,
        options: dict[str, JsonValue],
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Invoke connector with canonical-first dispatch and legacy fallback.

        Builds canonical connector request contract, projects RequestContext to
        ConnectorRequestContext, and dispatches to canonical API when available.
        Falls back to legacy API with typed domain models (never dicts).

        Args:
            backend: Backend instance to invoke
            domain_request: Canonical chat request for backend (after preparation)
            canonical_request: Canonical chat request (original, for processed_messages)
            effective_model: Model identifier after considering any overrides
            identity: Application identity configuration for authentication
            cancellation_token: Session key for cancellation scoping
            cancellation_coordinator: Cancellation coordinator for structural enforcement
            context: Request context for correlation/debugging
            options: JSON-safe container for provider-specific connector options

        Returns:
            Either ResponseEnvelope for non-streaming requests or
            StreamingResponseEnvelope for streaming requests

        Raises:
            Any exception raised by the backend connector
        """
        # Project context to connector-facing context
        connector_context = self._project_context(context)

        # Check if backend implements canonical API
        is_canonical = self._is_canonical_backend(backend)

        if is_canonical:
            # Build canonical request contract
            connector_request = self._build_canonical_request(
                domain_request=domain_request,
                processed_messages=list(canonical_request.messages),
                effective_model=effective_model,
                identity=identity,
                cancellation_token=cancellation_token,
                cancellation_coordinator=cancellation_coordinator,
                context=connector_context,
                options=options,
            )

            # Invoke canonical API
            return await backend.chat_completions(connector_request)  # type: ignore[call-arg]
        else:
            # Legacy path: invoke with typed domain models (never dicts)
            # Log legacy path usage for observability with correlation identifiers
            correlation_ids = extract_correlation_ids(context)
            backend_type = getattr(backend, "backend_type", "unknown")
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Using legacy connector API",
                    extra={
                        "backend_type": backend_type,
                        "session_id": correlation_ids["session_id"],
                        "request_id": correlation_ids["request_id"],
                    },
                )

            # BOUNDARY EXCEPTION (Requirement 2.7, Design.md line 289):
            # This is the ONLY permitted location where `options` (dict[str, JsonValue])
            # are re-expanded into `**kwargs` for backward compatibility with legacy
            # connectors that expect keyword arguments.
            #
            # Rationale:
            # - Backward compatibility: Legacy connectors use LLMBackend.chat_completions()
            #   with permissive **kwargs signatures
            # - Constrained surface: Options expansion is confined to this single location
            #   in ConnectorInvoker, preventing legacy shapes from leaking into core services
            # - JSON-safe: Options are constrained to JsonValue types, ensuring deterministic
            #   logging/capture (Requirement 4.3)
            #
            # Promotion path (Design.md Phase 2/3):
            # - Migrate connectors to implement ICanonicalChatCompletionsBackend
            # - Use canonical API which receives options as typed dict[str, JsonValue]
            # - Deprecate legacy kwargs expansion (Phase 2: warn in logs)
            # - Remove legacy kwargs expansion entirely (Phase 3: optional, requires approval)
            #
            # This exception is time-bounded and documented per Requirement 2.7/3.5.
            kwargs: dict[str, Any] = dict(options)

            # Invoke legacy API with canonical domain models
            return await backend.chat_completions(
                request_data=domain_request,  # Canonical domain model, never dict
                processed_messages=list(canonical_request.messages),  # Typed values
                effective_model=effective_model,
                identity=identity,
                cancellation_token=cancellation_token,
                cancellation_coordinator=cancellation_coordinator,
                **kwargs,  # Options expanded here only
            )

