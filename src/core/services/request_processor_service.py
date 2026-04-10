"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from collections import OrderedDict
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)
from src.core.domain.quality_verifier_turns import (
    MIN_LOGICAL_TURN_FLOOR_FOR_QUALITY_VERIFIER,
    logical_floor_from_scaled,
    migrate_legacy_eligible_turn_counter,
    qv_tool_followup_increment_scaled,
    qv_user_turn_increment_scaled,
)
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

logger = logging.getLogger(__name__)

MAX_QUALITY_VERIFIER_TURN_STATES = 10_000
_ROUTING_CODES_BY_STATUS: dict[int, tuple[str, str, bool]] = {
    400: ("unsupported_on_instance", "availability", False),
    403: ("policy_rejected", "policy", False),
    404: ("unknown_model", "validation", False),
    503: ("temporarily_unavailable", "availability", True),
}


def _canonicalize_routing_error_details(
    status_code: int,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize routing metadata so status and canonical code do not disagree."""
    normalized = dict(details) if isinstance(details, dict) else {}
    canonical = _ROUTING_CODES_BY_STATUS.get(status_code)
    if canonical is None:
        return normalized

    code, category, retryable = canonical
    normalized["code"] = code
    normalized["category"] = category
    normalized["retryable"] = retryable
    return normalized


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
        self._quality_verifier_turn_counts: OrderedDict[str, int] = OrderedDict()

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

    @staticmethod
    def _extract_first_user_message_text(request: ChatRequest) -> str | None:
        """Return the first user message text when available."""
        try:
            for msg in getattr(request, "messages", []) or []:
                role = getattr(msg, "role", None)
                if role is None and isinstance(msg, dict):
                    role = msg.get("role")
                if role != "user":
                    continue

                content = getattr(msg, "content", None)
                if content is None and isinstance(msg, dict):
                    content = msg.get("content")

                if isinstance(content, str):
                    normalized = content.strip()
                    return normalized or None

                if content is not None:
                    normalized = str(content).strip()
                    return normalized or None
        except Exception:
            return None

        return None

    def _resolve_replacement_session_id(
        self,
        *,
        session_id: str,
        context: RequestContext,
        request_data: ChatRequest,
    ) -> str:
        """Resolve a stable identifier for model replacement state.

        In B2BUA mode, canonical A-leg session IDs may rotate between requests when
        the client does not supply a stable session identifier. This method derives
        a continuity key so random replacement can still trigger across turns.
        """
        identity = getattr(context, "b2bua_identity", None)
        if identity is None:
            return session_id

        client_session_id = getattr(identity, "client_session_id", None)
        auth_scope_id = getattr(identity, "auth_scope_id", None)

        if isinstance(client_session_id, str) and client_session_id.strip():
            scope = auth_scope_id.strip() if isinstance(auth_scope_id, str) else "anon"
            return f"b2bua-client:{scope}:{client_session_id.strip()}"

        if isinstance(auth_scope_id, str) and auth_scope_id.strip():
            first_user_message = self._extract_first_user_message_text(request_data)
            if first_user_message:
                digest = hashlib.sha256(first_user_message.encode("utf-8")).hexdigest()[
                    :16
                ]
                return f"b2bua-scope:{auth_scope_id.strip()}:{digest}"
            return f"b2bua-scope:{auth_scope_id.strip()}"

        return session_id

    def _resolve_quality_verifier_session_id(
        self,
        *,
        session_id: str,
        context: RequestContext,
    ) -> str:
        """Resolve a stable identifier for Quality Verifier scheduling.

        Quality Verifier scheduling should remain stable across B2BUA A-leg session
        rotations. Unlike random replacement continuity, verifier scheduling avoids
        first-user-message hashing because message churn can cause
        key churn that prevents frequency counters from progressing.
        """
        identity = getattr(context, "b2bua_identity", None)
        if identity is None:
            return session_id

        client_session_id = getattr(identity, "client_session_id", None)
        auth_scope_id = getattr(identity, "auth_scope_id", None)

        if isinstance(client_session_id, str) and client_session_id.strip():
            scope = auth_scope_id.strip() if isinstance(auth_scope_id, str) else "anon"
            return f"b2bua-client:{scope}:{client_session_id.strip()}"

        if isinstance(auth_scope_id, str) and auth_scope_id.strip():
            return f"b2bua-scope:{auth_scope_id.strip()}"

        # Fallback for unauthenticated + sessionless clients.
        #
        # Some clients do not provide a stable session identifier and may also run
        # with authentication disabled (local dev / single-user). In these cases the
        # A-leg session id can rotate per request and Quality Verifier frequency
        # counters would never progress beyond 1.
        #
        # Derive a stable, non-sensitive continuity key from connection identity.
        try:
            agent = getattr(context, "agent", None)
            client_host = getattr(context, "client_host", None)
            agent_text = str(agent).strip() if agent is not None else ""
            host_text = str(client_host).strip() if client_host is not None else ""
            if agent_text or host_text:
                digest = hashlib.sha256(
                    f"{agent_text}|{host_text}".encode("utf-8", errors="ignore")
                ).hexdigest()[:16]
                return f"b2bua-fallback:{digest}"
        except Exception:
            # Fail-open: keep behavior identical to previous versions.
            pass

        return session_id

    def _get_quality_verifier_turn_count(self, session_key: str) -> int:
        """Return in-memory Quality Verifier **scaled** turn counter for a continuity key."""
        raw = self._quality_verifier_turn_counts.get(session_key, 0)
        if isinstance(raw, float):
            migrated = migrate_legacy_eligible_turn_counter(raw)
            self._quality_verifier_turn_counts[session_key] = migrated
            raw = migrated
        count = (
            int(raw)
            if isinstance(raw, int)
            else migrate_legacy_eligible_turn_counter(raw)
        )
        if session_key in self._quality_verifier_turn_counts:
            self._quality_verifier_turn_counts.move_to_end(session_key, last=True)
        return max(0, int(count))

    def _set_quality_verifier_turn_count(self, session_key: str, count: int) -> None:
        """Persist in-memory Quality Verifier **scaled** turn count with bounded LRU size."""
        self._quality_verifier_turn_counts[session_key] = max(0, int(count))
        self._quality_verifier_turn_counts.move_to_end(session_key, last=True)
        while (
            len(self._quality_verifier_turn_counts) > MAX_QUALITY_VERIFIER_TURN_STATES
        ):
            self._quality_verifier_turn_counts.popitem(last=False)

    def reset_quality_verifier_eligible_turn_count(
        self, session_key: str, session: Any | None
    ) -> None:
        """Reset scaled QV counter in LRU and session state (see IQualityVerifierTurnLedger)."""
        key = (session_key or "").strip()
        if not key:
            return
        self._set_quality_verifier_turn_count(key, 0)
        if session is None:
            return
        try:
            st = getattr(session, "state", None)
            if st is not None and hasattr(st, "with_multiple_updates"):
                new_st = st.with_multiple_updates(
                    quality_verifier_eligible_turn_count=0
                )
                upd = getattr(session, "update_state", None)
                if callable(upd):
                    upd(new_st)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Quality Verifier: failed to persist eligible turn reset",
                    exc_info=True,
                )

    async def process_request(  # noqa: C901
        self,
        context: RequestContext,
        request_data: ChatRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request using decomposed services."""
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

        replacement_session_id = self._resolve_replacement_session_id(
            session_id=session_id,
            context=context,
            request_data=request_data,
        )
        context.extensions["replacement_effective_session_id"] = replacement_session_id
        quality_verifier_session_id = self._resolve_quality_verifier_session_id(
            session_id=session_id,
            context=context,
        )
        context.extensions["quality_verifier_effective_session_id"] = (
            quality_verifier_session_id
        )

        # Apply request side effects (streaming registry, memory injection/capture)
        request_data = await self._request_side_effects.apply(
            context, session_id, request_data
        )

        # Transfer injection boundary from ChatRequest.extra_body to RequestContext.extensions.
        # This allows request middleware to set boundaries that the enforcer can use.
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

        # --- Quality Verifier gating state (per request) ---
        # Quality Verifier runs only on remote backend completions, but its scheduling and
        # skip conditions are derived from the client-submitted request.
        is_tool_followup = self._is_tool_result_followup_request(request_data)

        quality_verifier_model_spec: str | None = None
        quality_verifier_frequency: int = 10
        quality_verifier_max_history: int | None = None
        quality_verifier_max_consecutive_failures: int = 5
        quality_verifier_cooldown_seconds: int = 300
        quality_verifier_ttft_timeout_seconds: float = 30.0
        quality_verifier_tool_followup_weight: float = 0.2

        try:
            if self._app_state is not None:
                cfg = self._app_state.get_setting("app_config")
                session_cfg = getattr(cfg, "session", None)
                raw_model = getattr(session_cfg, "quality_verifier_model", None)
                quality_verifier_model_spec = (
                    raw_model if isinstance(raw_model, str) else None
                )

                raw_freq = getattr(session_cfg, "quality_verifier_frequency", 10)
                try:
                    quality_verifier_frequency = (
                        int(raw_freq) if raw_freq is not None else 10
                    )
                except (TypeError, ValueError):
                    quality_verifier_frequency = 10

                raw_max_history = getattr(
                    session_cfg, "quality_verifier_max_history", None
                )
                quality_verifier_max_history = (
                    int(raw_max_history) if isinstance(raw_max_history, int) else None
                )

                quality_verifier_max_consecutive_failures = getattr(
                    session_cfg, "quality_verifier_max_consecutive_failures", 5
                )
                quality_verifier_cooldown_seconds = getattr(
                    session_cfg, "quality_verifier_cooldown_seconds", 300
                )
                raw_ttft_timeout_seconds = getattr(
                    session_cfg, "quality_verifier_ttft_timeout_seconds", 30.0
                )
                try:
                    quality_verifier_ttft_timeout_seconds = float(
                        raw_ttft_timeout_seconds
                    )
                except (TypeError, ValueError):
                    quality_verifier_ttft_timeout_seconds = 30.0
                if quality_verifier_ttft_timeout_seconds <= 0:
                    quality_verifier_ttft_timeout_seconds = 30.0

                raw_tool_followup_weight = getattr(
                    session_cfg, "quality_verifier_tool_followup_weight", 0.2
                )
                try:
                    quality_verifier_tool_followup_weight = float(
                        raw_tool_followup_weight
                    )
                except (TypeError, ValueError):
                    quality_verifier_tool_followup_weight = 0.2
                # Clamp between 0.0 and 1.0
                quality_verifier_tool_followup_weight = max(
                    0.0, min(1.0, quality_verifier_tool_followup_weight)
                )
        except Exception:
            quality_verifier_model_spec = None
            quality_verifier_frequency = 10
            quality_verifier_max_history = None
            quality_verifier_max_consecutive_failures = 5
            quality_verifier_cooldown_seconds = 300
            quality_verifier_ttft_timeout_seconds = 30.0
            quality_verifier_tool_followup_weight = 0.2

        quality_verifier_enabled = bool(quality_verifier_model_spec)
        if quality_verifier_enabled:
            # Provide Quality Verifier config to downstream layers via RequestContext.extensions.
            context.extensions["quality_verifier_model"] = str(
                quality_verifier_model_spec
            )
            context.extensions["quality_verifier_frequency"] = max(
                1, quality_verifier_frequency
            )
            if quality_verifier_max_history is not None:
                # Ignore invalid values; the verifier will treat it as disabled.
                with contextlib.suppress(TypeError, ValueError):
                    context.extensions["quality_verifier_max_history"] = int(
                        quality_verifier_max_history
                    )

            context.extensions["quality_verifier_max_consecutive_failures"] = (
                quality_verifier_max_consecutive_failures
            )
            context.extensions["quality_verifier_cooldown_seconds"] = (
                quality_verifier_cooldown_seconds
            )
            context.extensions["quality_verifier_ttft_timeout_seconds"] = (
                quality_verifier_ttft_timeout_seconds
            )

        # Tool-result continuations should never trigger Quality Verifier.
        if is_tool_followup:
            context.extensions["quality_verifier_skip_verification"] = True

        quality_verifier_turn_incremented = False
        current_eligible_turn_scaled = 0
        in_memory_eligible_turn_scaled = self._get_quality_verifier_turn_count(
            quality_verifier_session_id
        )
        try:
            state_dict = session.state.to_dict() if hasattr(session, "state") else {}
            raw_count = state_dict.get("quality_verifier_eligible_turn_count", 0)
            session_eligible_turn_scaled = migrate_legacy_eligible_turn_counter(
                raw_count
            )
        except Exception:
            session_eligible_turn_scaled = 0
        # Use the maximum of session state and in-memory count (both scaled integers)
        current_eligible_turn_scaled = max(
            0,
            max(session_eligible_turn_scaled, in_memory_eligible_turn_scaled),
        )

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
        has_explicit_backend = isinstance(model_spec, str) and (
            has_explicit_backend_selector(model_spec)
        )
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
        context.extensions.pop("replacement_source_selector", None)
        context.extensions.pop("replacement_effective_selector", None)

        if (
            self._replacement_service is not None
            and original_backend
            and original_model
            and not context.extensions.get("auxiliary_request")
        ):
            # Avoid initiating a replacement on turns that are scheduled for Quality Verifier
            # verification. This prevents the replacement model from being implicated
            # in Quality Verifier/correction flow.
            suppress_replacement_for_quality_verifier = False
            state = self._replacement_service.get_state(replacement_session_id)
            # Suppress replacement (no dice roll, no sticky replacement model) on turns
            # where the main completion is scheduled for Quality Verifier — including when
            # replacement is already active from a prior turn.
            if quality_verifier_enabled and not is_tool_followup:
                try:
                    freq = max(1, int(quality_verifier_frequency))
                except (TypeError, ValueError):
                    freq = 10
                # After this request, counter will increase by at least one full user turn
                # (worst case) when replacement is not active — use scaled storage.
                next_scaled = (
                    max(0, int(current_eligible_turn_scaled))
                    + qv_user_turn_increment_scaled()
                )
                next_eligible_floor = logical_floor_from_scaled(next_scaled)
                if (
                    freq > 0
                    and next_eligible_floor
                    >= MIN_LOGICAL_TURN_FLOOR_FOR_QUALITY_VERIFIER
                    and (next_eligible_floor % freq) == 0
                ):
                    suppress_replacement_for_quality_verifier = True
                    context.extensions[
                        "replacement_suppressed_for_quality_verifier"
                    ] = True
                    if state.active:
                        # BackendExecutor must not consume a replacement turn when we
                        # intentionally routed this request to the original model for QV.
                        context.extensions["replacement_skip_complete_turn"] = True
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Replacement suppressed for quality verifier on logical_floor=%s "
                            "(scaled_after_next_user_turn=%s frequency=%s session=%s "
                            "had_active_replacement=%s)",
                            next_eligible_floor,
                            next_scaled,
                            freq,
                            replacement_session_id,
                            state.active,
                        )

            should_replace = False
            if not suppress_replacement_for_quality_verifier:
                should_replace = self._replacement_service.should_replace(
                    replacement_session_id, context, original_backend, original_model
                )

            if not suppress_replacement_for_quality_verifier and (
                should_replace or state.active
            ):
                # Activate replacement if not already active
                if should_replace and not state.active:
                    await self._replacement_service.activate_replacement(
                        replacement_session_id, original_backend, original_model
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Replacement activated: {original_backend}:{original_model} -> "
                            f"{state.replacement_backend}:{state.replacement_model} "
                            f"for session {replacement_session_id}"
                        )

                # Get effective backend:model
                effective_backend, effective_model = (
                    self._replacement_service.get_effective_backend_model(
                        replacement_session_id, original_backend, original_model
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
                context.extensions["call_purpose"] = "replacement"
                context.extensions["replacement_source_selector"] = (
                    f"{original_backend}:{original_model}"
                )
                context.extensions["replacement_effective_selector"] = (
                    f"{effective_backend}:{effective_model}"
                )

                if logger.isEnabledFor(logging.DEBUG) and quality_verifier_enabled:
                    logger.debug(
                        "Quality verifier will be SKIPPED this turn due to active replacement "
                        "(session=%s, scaled=%s logical_floor=%s)",
                        replacement_session_id,
                        current_eligible_turn_scaled,
                        logical_floor_from_scaled(current_eligible_turn_scaled),
                    )

        # Prepare and validate backend request
        # Define helper function before try block for use in fallback logic
        def _prepare_quality_verifier_extensions_for_backend_call(
            *, replacement_active: bool
        ) -> None:
            """Populate RequestContext.extensions for downstream Quality Verifier.

            This function is called immediately before each backend execution attempt
            (including fallback retries).
            """

            nonlocal quality_verifier_turn_incremented
            nonlocal current_eligible_turn_scaled
            nonlocal quality_verifier_tool_followup_weight

            # Make replacement status explicit for the verifier.
            context.extensions["model_replacement_active"] = bool(replacement_active)

            # Skip verification for tool-result followups and replacement-model turns.
            skip = bool(is_tool_followup or replacement_active)
            context.extensions["quality_verifier_skip_verification"] = skip

            # When replacement is active, don't increment turn counter at all
            if replacement_active:
                context.extensions.pop("quality_verifier_eligible_turn_count", None)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Quality verifier SKIPPED: reason=replacement_active, "
                        f"session={quality_verifier_session_id}, "
                        f"replacement={replacement_active}"
                    )
                return

            if not quality_verifier_enabled:
                context.extensions.pop("quality_verifier_eligible_turn_count", None)
                return

            # Increment eligible counter exactly once per client request (scaled integer).
            # Tool followups add a fractional slice of one logical turn.
            if not quality_verifier_turn_incremented:
                if is_tool_followup:
                    increment_scaled = qv_tool_followup_increment_scaled(
                        quality_verifier_tool_followup_weight
                    )
                else:
                    increment_scaled = qv_user_turn_increment_scaled()

                new_scaled = max(0, int(current_eligible_turn_scaled)) + int(
                    increment_scaled
                )
                try:
                    new_state = session.state.with_multiple_updates(
                        quality_verifier_eligible_turn_count=new_scaled
                    )
                    session.update_state(new_state)
                except Exception:
                    # Fail-open: still track the count in the request context for scheduling.
                    pass
                self._set_quality_verifier_turn_count(
                    quality_verifier_session_id,
                    new_scaled,
                )
                current_eligible_turn_scaled = new_scaled
                quality_verifier_turn_incremented = True

                if logger.isEnabledFor(logging.DEBUG) and is_tool_followup:
                    lf = logical_floor_from_scaled(new_scaled)
                    logger.debug(
                        "Quality Verifier: counter incremented for tool follow-up "
                        "(scaled=%s logical_floor=%s tool_increment_scaled=%s); "
                        "stream verification skipped on this request (tool-result continuation — "
                        "verifier runs on completions that are not tool-follow-ups).",
                        new_scaled,
                        lf,
                        increment_scaled,
                    )

            context.extensions["quality_verifier_eligible_turn_count"] = int(
                current_eligible_turn_scaled
            )

            if logger.isEnabledFor(logging.DEBUG):
                try:
                    freq_int = max(1, int(quality_verifier_frequency))
                except (TypeError, ValueError):
                    freq_int = 10
                current_turn_floor = logical_floor_from_scaled(
                    int(current_eligible_turn_scaled)
                )
                should_run_next = (
                    current_turn_floor >= MIN_LOGICAL_TURN_FLOOR_FOR_QUALITY_VERIFIER
                    and (current_turn_floor % freq_int) == 0
                )
                logger.debug(
                    "Quality Verifier scheduling: effective_session=%s "
                    "scaled=%s logical_floor=%s frequency=%s run_now=%s",
                    quality_verifier_session_id,
                    current_eligible_turn_scaled,
                    current_turn_floor,
                    freq_int,
                    should_run_next,
                )

        # Execute backend with fallback support for replacement model failures
        # This try-catch covers both preparation and execution phases to ensure
        # replacement model errors (including OAuth token refresh failures) trigger
        # automatic fallback to the original model (B2BUA-aware fallback pattern).
        fallback_attempted = False
        try:
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

            _prepare_quality_verifier_extensions_for_backend_call(
                replacement_active=replacement_active_for_request
            )
            result = await self._backend_executor.execute(
                context, session, session_id, backend_request, request_data
            )

            # Check if result is an error response (for streaming requests)
            # Streaming requests return error envelopes instead of raising exceptions
            is_error_response = False
            status_code = getattr(result, "status_code", None)
            if status_code is not None:
                with contextlib.suppress(TypeError, ValueError):
                    is_error_response = int(status_code) >= 400

            if is_error_response:
                # Extract original error details from metadata if available
                orig_message: str | None = None
                orig_type: str | None = None
                orig_code: str | None = None

                orig_details: dict[str, Any] | None = None

                metadata = getattr(result, "metadata", None)
                if isinstance(metadata, dict):
                    orig_message = str(metadata.get("error_message") or "")
                    orig_type = str(metadata.get("error_type") or "")
                    orig_code = str(metadata.get("error_code") or "")
                    orig_details = metadata.get("error_details")  # type: ignore[assignment]

                # ALWAYS raise for error status codes to satisfy Requirements 10.4 (errors propagate)
                # and legacy regression tests. Fallback logic handles re-try if appropriate.
                from src.core.common.exceptions import (
                    AuthenticationError,
                    BackendError,
                    RoutingError,
                )

                # Determine which exception to raise, preserving original info if possible
                error_message = (
                    orig_message or f"Backend returned {result.status_code} error"
                )
                error_details = orig_details or {}
                if orig_code and "code" not in error_details:
                    error_details["code"] = orig_code

                if result.status_code == 401:
                    raise AuthenticationError(
                        error_message or "Backend returned 401 error"
                    )
                elif result.status_code == 404 or orig_type == "RoutingError":
                    error_details = _canonicalize_routing_error_details(
                        int(result.status_code),
                        error_details,
                    )
                    raise RoutingError(
                        message=error_message,
                        details=error_details,
                        code=error_details.get("code") or orig_code or "unknown_model",
                    )
                else:
                    raise BackendError(
                        message=error_message,
                        status_code=result.status_code,
                        details=error_details,
                        code=orig_code,
                    )

            return result
        except Exception as e:
            # Check if this failure happened while using a replacement model
            # Fallback to original model if replacement fails during preparation or execution
            if (
                not fallback_attempted
                and self._replacement_service is not None
                and context.backend
                and context.effective_model
            ):
                state = self._replacement_service.get_state(replacement_session_id)
                # If failure occurred on replacement model
                if (
                    state.active
                    and context.backend == state.replacement_backend
                    and context.effective_model == state.replacement_model
                ):
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Replacement model {context.backend}:{context.effective_model} failed: {e}. "
                            f"Falling back to original model for replacement-session {replacement_session_id} "
                            f"(request session {session_id})."
                        )

                    # Deactivate replacement immediately due to failure
                    fallback_attempted = True
                    state.deactivate()

                    # Revert context to original backend
                    context.backend = state.original_backend
                    context.effective_model = state.original_model
                    context.extensions.pop("call_purpose", None)

                    # Revert request model
                    request_data_fallback = request_data.model_copy(
                        update={
                            "model": f"{state.original_backend}:{state.original_model}"
                        }
                    )

                    # Prepare new backend request for fallback
                    # This triggers a NEW B2BUA identity allocation for the fallback attempt,
                    # ensuring proper session isolation per the B2BUA pattern
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
                        # IMPORTANT: This execute() call flows through BackendCompletionFlowService
                        # which allocates a NEW B2BUA attempt identity (different b_session_id and b_seq)
                        # This ensures proper session isolation between the failed replacement
                        # attempt and the successful fallback attempt
                        _prepare_quality_verifier_extensions_for_backend_call(
                            replacement_active=False
                        )
                        fallback_result = await self._backend_executor.execute(
                            context,
                            session,
                            session_id,
                            fallback_backend_request,
                            request_data_fallback,
                        )

                        # CRITICAL: Also check fallback result for error status
                        # If fallback also fails, we need to raise the error (no infinite retries)
                        fallback_status = getattr(fallback_result, "status_code", None)
                        fallback_failed = False
                        if fallback_status is not None:
                            with contextlib.suppress(TypeError, ValueError):
                                fallback_failed = int(fallback_status) >= 400

                        if fallback_failed:

                            from src.core.common.exceptions import (
                                AuthenticationError,
                                BackendError,
                                RoutingError,
                            )

                            fallback_message: str | None = None
                            fallback_type: str | None = None
                            fallback_code: str | None = None
                            fallback_details: dict[str, Any] | None = None

                            metadata = getattr(fallback_result, "metadata", None)
                            if isinstance(metadata, dict):
                                fallback_message = str(
                                    metadata.get("error_message") or ""
                                )
                                fallback_type = str(metadata.get("error_type") or "")
                                fallback_code = str(metadata.get("error_code") or "")
                                fallback_details = metadata.get("error_details")

                            error_message = (
                                fallback_message
                                or f"Both models failed, fallback returned status: {fallback_result.status_code}"
                            )
                            error_details = fallback_details or {}
                            if fallback_code and "code" not in error_details:
                                error_details["code"] = fallback_code

                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    f"Fallback attempt failed: replacement and original models both returned errors "
                                    f"(status: {fallback_result.status_code}, session: {session_id})"
                                )

                            if fallback_result.status_code == 401:
                                raise AuthenticationError(
                                    error_message
                                    or "Both replacement and original models failed with 401 error"
                                )
                            elif (
                                fallback_result.status_code == 404
                                or fallback_type == "RoutingError"
                            ):
                                error_details = _canonicalize_routing_error_details(
                                    int(fallback_result.status_code),
                                    error_details,
                                )
                                raise RoutingError(
                                    message=error_message,
                                    details=error_details,
                                    code=error_details.get("code")
                                    or fallback_code
                                    or "unknown_model",
                                )
                            else:
                                raise BackendError(
                                    message=error_message,
                                    status_code=fallback_result.status_code,
                                    details=error_details,
                                    code=fallback_code,
                                )

                        return fallback_result

            # If we can't handle it or it wasn't a replacement failure, re-raise
            raise
