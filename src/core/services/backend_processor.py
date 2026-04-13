from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

from src.core.common.exceptions import LLMProxyError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import has_explicit_backend_selector
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import SessionInteraction
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.services.composite_routing_state import is_composite_selector

if TYPE_CHECKING:
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.domain_entities_interface import ISession
    from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


def _coerce_call_completion_to_envelope(
    raw: Any,
    *,
    stream_requested: bool,
) -> ResponseEnvelope | StreamingResponseEnvelope:
    """Normalize legacy/raw backend payloads to domain envelopes before the manager.

    ``IBackendService.call_completion`` is typed to return envelopes, but tests and
    older shims may still return plain dicts, Pydantic chat payloads, or Starlette
    ``StreamingResponse`` objects.
    """
    if isinstance(raw, ResponseEnvelope | StreamingResponseEnvelope):
        return raw

    body_iterator = getattr(raw, "body_iterator", None)
    if body_iterator is not None and stream_requested:
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        async def _wrap_starlette_stream() -> AsyncIterator[ProcessedResponse]:
            async for chunk in body_iterator:
                if isinstance(chunk, bytes):
                    yield ProcessedResponse(content=chunk)
                elif isinstance(chunk, str):
                    yield ProcessedResponse(content=chunk.encode("utf-8"))
                else:
                    yield ProcessedResponse(content=chunk)

        media_type = getattr(raw, "media_type", None) or "text/event-stream"
        status = getattr(raw, "status_code", None)
        hdr_obj = getattr(raw, "headers", None)
        headers: dict[str, str] | None
        if hdr_obj is not None:
            try:
                headers = dict(hdr_obj)
            except (TypeError, ValueError):
                headers = None
        else:
            headers = None
        return StreamingResponseEnvelope(
            content=_wrap_starlette_stream(),
            media_type=str(media_type),
            headers=headers,
            status_code=int(status) if isinstance(status, int) else 200,
        )

    if isinstance(raw, dict):
        if stream_requested:
            msg = (
                "call_completion returned dict while streaming was requested; "
                "expected StreamingResponseEnvelope or a Starlette-compatible "
                "streaming response with body_iterator"
            )
            raise LLMProxyError(msg, status_code=500)
        return ResponseEnvelope(content=raw)

    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump) and not isinstance(raw, type):
        if stream_requested:
            msg = (
                "call_completion returned a Pydantic model while streaming was "
                "requested; expected StreamingResponseEnvelope"
            )
            raise LLMProxyError(msg, status_code=500)
        try:
            dumped = raw.model_dump(mode="json")
        except (TypeError, ValueError):
            dumped = raw.model_dump()
        if isinstance(dumped, dict):
            return ResponseEnvelope(content=dumped)
        return ResponseEnvelope(content={"data": dumped})

    msg = (
        "call_completion returned unsupported type "
        f"{type(raw).__name__}; expected ResponseEnvelope or StreamingResponseEnvelope"
    )
    raise LLMProxyError(msg, status_code=500)


class BackendProcessor(IBackendProcessor):
    """Processor that handles request forwarding to the backend service."""

    def __init__(
        self,
        backend_service: IBackendService,
        session_service: ISessionService,
        app_state: IApplicationState | None = None,
    ):
        self._backend_service = backend_service
        self._session_service = session_service
        self._app_state = app_state

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process a request through the backend service."""
        # Note: In the original implementation, process_messages was called.
        # But IBackendProcessor defines process_backend_request.
        # We'll use the latter as the primary entry point.

        # Try to resolve session
        session = None
        try:
            session = await self._session_service.get_session(session_id)
        except asyncio.CancelledError:
            # Propagate cancellation - session resolution should not block cancellation
            raise
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
            # Catch specific exceptions from repository/service layer
            logger.debug(
                "Failed to resolve session %s in BackendProcessor: %s",
                session_id,
                e,
                exc_info=True,
            )
        except Exception as e:
            # Fallback for unexpected errors - log and continue (fail-open)
            logger.warning(
                "Unexpected error resolving session %s in BackendProcessor: %s",
                session_id,
                e,
                exc_info=True,
            )

        processed_messages = request.messages

        # Forward to internal implementation
        return await self._process_forward(
            request, processed_messages, session_id, session, context
        )

    async def _process_forward(
        self,
        request: ChatRequest,
        processed_messages: list[Any],
        session_id: str,
        session: ISession | None = None,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Forward the request to the backend service and record interaction."""
        logger.debug("BackendProcessor forwarding for session %s", session_id)

        # Build raw prompt for interaction logging
        raw_prompt = ""
        if processed_messages:
            last_msg = processed_messages[-1]
            if isinstance(last_msg, dict):
                raw_prompt = str(last_msg.get("content", ""))
            elif isinstance(last_msg, ChatMessage):
                raw_prompt = str(last_msg.content)
            else:
                raw_prompt = str(last_msg)

        # Prepare extra_body for backend-specific features (failover, etc.)
        extra_body_dict = {}
        if request.extra_body:
            extra_body_dict.update(request.extra_body)
        else:
            # Fallback to dict copy if extra_body is missing
            extra_body_dict = {
                k: v
                for k, v in request.__dict__.items()
                if not k.startswith("_") and not callable(v)
            }

        model_spec = str(getattr(request, "model", "") or "")
        explicit_backend = has_explicit_backend_selector(model_spec)
        explicit_non_composite_backend = explicit_backend and not is_composite_selector(
            model_spec
        )

        # Get failover routes from session and add them to extra_body.
        # IMPORTANT: explicit backend routing ("backend:model") must never be subject
        # to automatic failover routing.
        failover_routes: list[Any] | None = None

        # Prefer session-scoped failover routes
        try:
            if session and session.state.backend_config.failover_routes:
                session_routes = session.state.backend_config.failover_routes
                failover_routes = []
                for name, data in session_routes.items():
                    if hasattr(data, "model_dump"):
                        failover_routes.append(data)
                    elif isinstance(data, dict):
                        failover_routes.append({"name": name, **data})
                    else:
                        failover_routes.append({"name": name, "value": str(data)})
        except (AttributeError, KeyError, TypeError, ValueError):
            logger.debug(
                "Failed to extract failover routes from session", exc_info=True
            )
            failover_routes = None

        if not failover_routes and self._app_state is not None:
            try:
                failover_routes = cast(
                    list[Any] | None, self._app_state.get_failover_routes()
                )
            except (AttributeError, TypeError, KeyError):
                logger.debug(
                    "Failed to get failover routes from app_state", exc_info=True
                )
                failover_routes = None

        if failover_routes and not explicit_non_composite_backend:
            serializable_routes = [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in failover_routes
            ]
            extra_body_dict["failover_routes"] = serializable_routes
        else:
            # Defensive: ensure we don't forward any caller-provided failover routes
            # when the request explicitly targets a backend.
            extra_body_dict.pop("failover_routes", None)

        # Call the backend
        call_request = request.model_copy(update={"extra_body": extra_body_dict})
        raw_backend_response = await self._backend_service.call_completion(
            request=call_request,
            stream=call_request.stream if call_request.stream is not None else False,
            allow_failover=not explicit_non_composite_backend,
            context=context,
        )
        stream_requested = bool(
            call_request.stream if call_request.stream is not None else False
        )
        backend_response = _coerce_call_completion_to_envelope(
            raw_backend_response,
            stream_requested=stream_requested,
        )

        # Add session interaction
        if session:
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=getattr(session.state.backend_config, "backend_type", None),
                    model=getattr(session.state.backend_config, "model", None),
                    project=getattr(session.state, "project", None),
                    parameters={
                        "temperature": call_request.temperature,
                        "top_p": call_request.top_p,
                        "stream": call_request.stream,
                    },
                )
            )

        return backend_response
