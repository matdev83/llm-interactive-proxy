"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

import contextlib
import logging

from src.core.domain.chat import ChatRequest
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.request_processor_internal import (
    IBackendExecutor,
    IBackendPreparer,
    ICommandHandler,
    IRequestSideEffects,
    IRequestTransformPipeline,
    ISessionEnricher,
)
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.auxiliary_request_router import (
    AuxiliaryRequestRouter,
)
from src.core.services.auxiliary_request_router import (
    AuxiliaryRoutingConfig as AuxRoutingConfigDomain,
)

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor using decomposed services."""

    def __init__(
        self,
        command_processor: ICommandProcessor,
        session_manager: ISessionManager,
        backend_request_manager: IBackendRequestManager,
        response_manager: IResponseManager,
        session_enricher: ISessionEnricher,
        request_side_effects: IRequestSideEffects,
        command_handler: ICommandHandler,
        backend_preparer: IBackendPreparer,
        transform_pipeline: IRequestTransformPipeline,
        backend_executor: IBackendExecutor,
        app_state: IApplicationState | None = None,
        replacement_service: IModelReplacementService | None = None,
    ) -> None:
        """Initialize the request processor with decomposed services.

        Args:
            command_processor: Legacy command processor interface (required)
            session_manager: Session management service (required)
            backend_request_manager: Backend request management service (required)
            response_manager: Response processing service (required)
            session_enricher: Session enrichment component (required)
            request_side_effects: Side effects component (streaming registry, memory) (required)
            command_handler: Command processing and early-return handler (required)
            backend_preparer: Backend request preparation and validation (required)
            transform_pipeline: Request transformation pipeline (redaction, precision, filtering) (required)
            backend_executor: Backend execution and persistence side effects (required)
            app_state: Application state for configuration and service access (optional)
            replacement_service: Model replacement service for fallback models (optional)
        """
        self._command_processor = command_processor
        self._session_manager = session_manager
        self._backend_request_manager = backend_request_manager
        self._response_manager = response_manager
        self._session_enricher = session_enricher
        self._request_side_effects = request_side_effects
        self._command_handler = command_handler
        self._backend_preparer = backend_preparer
        self._transform_pipeline = transform_pipeline
        self._backend_executor = backend_executor
        self._app_state = app_state
        self._replacement_service = replacement_service

    @staticmethod
    def _is_tool_result_followup_request(request: ChatRequest) -> bool:
        """Return True when this request is a tool-result continuation.

        Tool-result continuation requests include one or more `tool` role messages
        after the most recent `user` message.
        """
        try:
            last_user_idx = -1
            last_tool_idx = -1
            for idx, msg in enumerate(getattr(request, "messages", []) or []):
                role = getattr(msg, "role", None)
                if role is None and isinstance(msg, dict):
                    role = msg.get("role")
                if role == "user":
                    last_user_idx = idx
                elif role == "tool":
                    last_tool_idx = idx
            return last_tool_idx > last_user_idx and last_user_idx >= 0
        except Exception:
            return False

    async def process_request(
        self,
        context: RequestContext,
        request_data: ChatRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request using decomposed services."""
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RequestProcessor.process_request called with session_id: {getattr(context, 'session_id', 'unknown')}"
            )

        # Enrich session and client context
        from typing import cast

        from src.core.domain.session import Session

        enriched_session, request_data = await self._session_enricher.enrich(
            context, request_data
        )
        # Enrichment step returns a concrete ChatRequest instance
        session = cast(Session, enriched_session)
        session_id = await self._session_manager.resolve_session_id(context)

        # Ensure session_id is propagated consistently for downstream components.
        # Many backends/connectors (e.g., Gemini thought signature injection) rely on
        # request_data.session_id being present even when the client does not send it.
        with contextlib.suppress(Exception):
            context.session_id = session_id
        with contextlib.suppress(Exception):
            request_data = request_data.model_copy(update={"session_id": session_id})

        # Optional auxiliary request routing (title/summary generation).
        #
        # Clients like OpenCode may issue parallel lightweight requests (e.g. title
        # generation). When configured, route those to an alternative backend/model
        # and isolate their session lifecycle from the primary conversation.
        try:
            if self._app_state is not None:
                app_config = self._app_state.get_setting("app_config")
                aux_cfg = getattr(app_config, "auxiliary_routing", None)
                if aux_cfg and getattr(aux_cfg, "enabled", False):
                    domain_cfg = AuxRoutingConfigDomain(
                        enabled=True,
                        backend=getattr(aux_cfg, "backend", None),
                        model=getattr(aux_cfg, "model", None),
                        detection_patterns=list(
                            getattr(aux_cfg, "detection_patterns", [])
                        ),
                        max_message_count=getattr(aux_cfg, "max_message_count", 3),
                    )
                    router = AuxiliaryRequestRouter(domain_cfg)

                    if router.should_route_to_auxiliary(request_data):
                        aux_backend = router.get_auxiliary_backend()
                        aux_model = router.get_auxiliary_model()

                        parsed_original = parse_model_backend(
                            str(getattr(request_data, "model", "") or ""),
                            "",
                        )
                        original_backend = parsed_original.backend_type
                        original_model = parsed_original.model_name

                        routed_model = aux_model or original_model
                        request_data = request_data.model_copy(
                            update={"model": f"{aux_backend}:{routed_model}"}
                        )

                        context.extensions["auxiliary_request"] = True
                        context.extensions["auxiliary_effective_session_id"] = (
                            f"aux::{session_id}"
                        )
                        context.extensions["auxiliary_original_backend"] = (
                            original_backend
                        )
                        context.extensions["auxiliary_original_model"] = original_model
                        context.extensions["auxiliary_backend"] = aux_backend
                        context.extensions["auxiliary_model"] = routed_model
        except Exception:
            # Fail-open: never break request processing due to auxiliary routing.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Auxiliary routing failed; continuing", exc_info=True)

        # Apply request side effects (streaming registry, memory injection/capture)
        request_data = await self._request_side_effects.apply(
            context, session_id, request_data
        )

        # Transfer injection boundary from ChatRequest.extra_body to RequestContext.extensions
        # This allows middleware (like AssessmentMiddleware) to set boundaries that the enforcer can use
        if request_data.extra_body:
            boundary_key = "_proxy_injected_messages_start_index"
            if boundary_key in request_data.extra_body:
                boundary_value = request_data.extra_body[boundary_key]
                if isinstance(boundary_value, int):
                    from src.core.services.non_forwardable_message_enforcer import (
                        PROXY_INJECTED_MESSAGES_START_INDEX_KEY,
                    )

                    context.extensions[PROXY_INJECTED_MESSAGES_START_INDEX_KEY] = (
                        boundary_value
                    )

        # Process commands and handle command-only flows
        result = await self._command_handler.handle(
            context, session, session_id, request_data
        )
        # If CommandHandler returns a response envelope, it took the command-only path
        if isinstance(result, ResponseEnvelope | StreamingResponseEnvelope):
            return result
        # Otherwise, it's a ProcessedResult and we continue with backend flow
        command_result = result

        # --- Angel gating state (per request) ---
        # Angel verification runs only on remote backend completions, but its scheduling and
        # skip conditions are derived from the client-submitted request.
        is_tool_followup = self._is_tool_result_followup_request(request_data)

        angel_model_spec: str | None = None
        angel_frequency: int = 10
        angel_max_history: int | None = None
        angel_max_consecutive_failures: int = 5
        angel_cooldown_seconds: int = 300

        try:
            if self._app_state is not None:
                cfg = self._app_state.get_setting("app_config")
                session_cfg = getattr(cfg, "session", None)
                raw_model = getattr(session_cfg, "angel_model", None)
                angel_model_spec = raw_model if isinstance(raw_model, str) else None

                raw_freq = getattr(session_cfg, "angel_frequency", 10)
                try:
                    angel_frequency = int(raw_freq) if raw_freq is not None else 10
                except (TypeError, ValueError):
                    angel_frequency = 10

                raw_max_history = getattr(session_cfg, "angel_max_history", None)
                angel_max_history = (
                    int(raw_max_history) if isinstance(raw_max_history, int) else None
                )

                angel_max_consecutive_failures = getattr(
                    session_cfg, "angel_max_consecutive_failures", 5
                )
                angel_cooldown_seconds = getattr(
                    session_cfg, "angel_cooldown_seconds", 300
                )
        except Exception:
            angel_model_spec = None
            angel_frequency = 10
            angel_max_history = None
            angel_max_consecutive_failures = 5
            angel_cooldown_seconds = 300

        angel_enabled = bool(angel_model_spec)
        if angel_enabled:
            # Provide Angel config to downstream layers via RequestContext.extensions.
            context.extensions["angel_model"] = str(angel_model_spec)
            context.extensions["angel_frequency"] = max(1, angel_frequency)
            if angel_max_history is not None:
                # Ignore invalid values; the verifier will treat it as disabled.
                with contextlib.suppress(TypeError, ValueError):
                    context.extensions["angel_max_history"] = int(angel_max_history)

            context.extensions["angel_max_consecutive_failures"] = (
                angel_max_consecutive_failures
            )
            context.extensions["angel_cooldown_seconds"] = angel_cooldown_seconds

        # Tool-result continuations should never trigger Angel.
        if is_tool_followup:
            context.extensions["angel_skip_verification"] = True

        angel_turn_incremented = False
        current_eligible_turn_count = 0
        try:
            state_dict = session.state.to_dict() if hasattr(session, "state") else {}
            raw_count = state_dict.get("angel_eligible_turn_count", 0)
            if isinstance(raw_count, int):
                current_eligible_turn_count = raw_count
            elif isinstance(raw_count, float | str):
                current_eligible_turn_count = int(raw_count)
        except Exception:
            current_eligible_turn_count = 0

        # Apply model replacement if enabled
        # Note: Model replacement logic remains in RequestProcessor orchestrator rather than
        # being extracted to a dedicated component. This is intentional per research.md:
        # "In staged initialization wiring, the replacement service is currently not injected
        # into RequestProcessor, so this code path is typically inactive." If this feature
        # becomes more active or complex, consider extracting to a ModelReplacementHandler component.
        # Resolve original backend and model for replacement service
        # context.backend is often None at this point, so we fall back to app_state defaults
        # or parse from model name if it contains a prefix (e.g., "openai:gpt-4o")
        backend_type = None
        if self._app_state is not None:
            try:
                # Use IApplicationState.get_backend_type() to get the configured default backend
                backend_type = self._app_state.get_backend_type()
            except (AttributeError, RuntimeError, TypeError) as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failed to get backend type from app state: {exc}")
                backend_type = None

        if not isinstance(backend_type, str) or not backend_type.strip():
            backend_type = None

        model_spec = getattr(request_data, "model", "") or ""
        has_explicit_backend = isinstance(model_spec, str) and ":" in model_spec
        parsed = parse_model_backend(str(model_spec), (backend_type or ""))
        original_backend = (
            parsed.backend_type
            if has_explicit_backend
            else (context.backend or parsed.backend_type)
        )
        original_model = parsed.model_name

        # Ensure requested_model is populated for metrics and tracking
        if not context.requested_model:
            context.requested_model = original_model

        # Ensure context attributes are populated for downstream services and fallback logic
        # If the client provided an explicit backend prefix ("backend:model"), it must win.
        if (not context.backend) or has_explicit_backend:
            context.backend = original_backend
        if not context.effective_model:
            context.effective_model = original_model

        if logger.isEnabledFor(logging.DEBUG):

            logger.debug(
                f"Model replacement resolution: original_backend='{original_backend}', "
                f"original_model='{original_model}', "
                f"backend_type_from_state='{backend_type}', "
                f"replacement_service_present={self._replacement_service is not None}"
            )

        replacement_active_for_request = False

        if (
            self._replacement_service is not None
            and original_backend
            and original_model
        ):
            # Avoid initiating a replacement on turns that are scheduled for Angel
            # verification. This prevents the replacement model from being implicated
            # in Angel verification/correction flow.
            suppress_replacement_for_angel = False
            state = self._replacement_service.get_state(session_id)
            if angel_enabled and not is_tool_followup and not state.active:
                try:
                    freq = max(1, int(angel_frequency))
                except (TypeError, ValueError):
                    freq = 10
                next_eligible = max(0, int(current_eligible_turn_count)) + 1
                if freq > 0 and (next_eligible % freq) == 0:
                    suppress_replacement_for_angel = True
                    context.extensions["replacement_suppressed_for_angel"] = True

            should_replace = False
            if not suppress_replacement_for_angel:
                should_replace = self._replacement_service.should_replace(
                    session_id, context, original_backend, original_model
                )

            if should_replace:
                # Activate replacement if not already active
                if not state.active:
                    await self._replacement_service.activate_replacement(
                        session_id, original_backend, original_model
                    )

                # Get effective backend:model
                effective_backend, effective_model = (
                    self._replacement_service.get_effective_backend_model(
                        session_id, original_backend, original_model
                    )
                )

                # Update backend and model in context and request
                # Downstream components (preparer, handlers) rely on these updated values
                context.backend = effective_backend
                context.effective_model = effective_model
                request_data = request_data.model_copy(
                    update={"model": f"{effective_backend}:{effective_model}"}
                )
                replacement_active_for_request = True

        # Prepare and validate backend request

        backend_request = await self._backend_preparer.prepare(
            context, session_id, request_data, command_result
        )
        if backend_request is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Backend call skipped for session {session_id}; recording command interaction if applicable"
                )
            # Backend should be skipped; command result is already the final result
            # Record command execution in session history if one was executed
            if command_result.command_executed:
                await self._session_manager.record_command_in_session(
                    request_data, session_id
                )
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Apply request transformations using pipeline
        # Note: transform() always returns ChatRequest (never None) per IRequestTransformPipeline contract
        backend_request = await self._transform_pipeline.transform(
            context, session, session_id, backend_request
        )

        def _prepare_angel_extensions_for_backend_call(
            *, replacement_active: bool
        ) -> None:
            """Populate RequestContext.extensions for downstream Angel verification.

            This function is called immediately before each backend execution attempt
            (including fallback retries).
            """

            nonlocal angel_turn_incremented
            nonlocal current_eligible_turn_count

            # Make replacement status explicit for the verifier.
            context.extensions["model_replacement_active"] = bool(replacement_active)

            # Skip verification for tool-result followups and replacement-model turns.
            skip = bool(is_tool_followup or replacement_active)
            context.extensions["angel_skip_verification"] = skip

            if skip:
                context.extensions.pop("angel_eligible_turn_count", None)
                return

            if not angel_enabled:
                context.extensions.pop("angel_eligible_turn_count", None)
                return

            # Increment eligible counter exactly once per client request.
            if not angel_turn_incremented:
                new_count = max(0, int(current_eligible_turn_count)) + 1
                try:
                    new_state = session.state.with_multiple_updates(
                        angel_eligible_turn_count=new_count
                    )
                    session.update_state(new_state)
                except Exception:
                    # Fail-open: still track the count in the request context for scheduling.
                    pass
                current_eligible_turn_count = new_count
                angel_turn_incremented = True

            context.extensions["angel_eligible_turn_count"] = int(
                current_eligible_turn_count
            )

        # Execute backend and perform persistence side effects
        try:
            _prepare_angel_extensions_for_backend_call(
                replacement_active=replacement_active_for_request
            )
            return await self._backend_executor.execute(
                context, session, session_id, backend_request, request_data
            )
        except Exception as e:
            # Check if this failure happened while using a replacement model
            if (
                self._replacement_service is not None
                and context.backend
                and context.effective_model
            ):
                state = self._replacement_service.get_state(session_id)
                # If failure occurred on replacement model
                if (
                    state.active
                    and context.backend == state.replacement_backend
                    and context.effective_model == state.replacement_model
                ):
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Replacement model {context.backend}:{context.effective_model} failed: {e}. "
                            f"Falling back to original model for session {session_id}."
                        )

                    # Deactivate replacement immediately due to failure
                    state.deactivate()

                    # Revert context to original backend
                    context.backend = state.original_backend
                    context.effective_model = state.original_model

                    # Revert request model
                    request_data_fallback = request_data.model_copy(
                        update={
                            "model": f"{state.original_backend}:{state.original_model}"
                        }
                    )

                    # Prepare new backend request for fallback
                    # We need to re-prepare because backend-specific logic might differ
                    fallback_backend_request = await self._backend_preparer.prepare(
                        context, session_id, request_data_fallback, command_result
                    )

                    if fallback_backend_request:
                        # Re-transform if needed
                        fallback_backend_request = (
                            await self._transform_pipeline.transform(
                                context, session, session_id, fallback_backend_request
                            )
                        )

                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                f"Retrying with original model {state.original_backend}:{state.original_model} "
                                f"for session {session_id}"
                            )

                        # Retry execution with original model
                        _prepare_angel_extensions_for_backend_call(
                            replacement_active=False
                        )
                        return await self._backend_executor.execute(
                            context,
                            session,
                            session_id,
                            fallback_backend_request,
                            request_data_fallback,
                        )

            # If we can't handle it or it wasn't a replacement failure, re-raise
            raise
