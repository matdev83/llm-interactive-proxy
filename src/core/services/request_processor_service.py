"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor using decomposed services."""

    def __init__(
        self,
        command_processor: ICommandProcessor,
        session_manager: ISessionManager,
        backend_request_manager: IBackendRequestManager,
        response_manager: IResponseManager,
        app_state: IApplicationState | None = None,
    ) -> None:
        """Initialize the request processor with decomposed services."""
        self._command_processor = command_processor
        self._session_manager = session_manager
        self._backend_request_manager = backend_request_manager
        self._response_manager = response_manager
        self._app_state = app_state

    async def process_request(
        self, context: RequestContext, request_data: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request using decomposed services."""
        logger.debug(
            f"RequestProcessor.process_request called with session_id: {getattr(context, 'session_id', 'unknown')}"
        )
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        # Resolve session and update agent if needed
        session_id = await self._session_manager.resolve_session_id(context)
        session = await self._session_manager.get_session(session_id)
        session = await self._session_manager.update_session_agent(
            session, request_data.agent
        )

        logger.debug(f"Resolved session_id: {session_id}")
        logger.debug(
            f"Request data type: {type(request_data)}, model: {getattr(request_data, 'model', 'unknown')}"
        )

        # Process commands in the request
        command_result = await self._handle_command_processing(
            request_data, session_id, context
        )

        # Debug logging to understand command processing behavior
        logger.debug(
            f"Command processing result: command_executed={command_result.command_executed}, modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}, command_results={len(command_result.command_results) if hasattr(command_result.command_results, '__len__') else 0}"
        )
        logger.info(
            f"Command processing result: command_executed={command_result.command_executed}, "
            f"modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}, "
            f"command_results={len(command_result.command_results) if hasattr(command_result.command_results, '__len__') else 0}"
        )

        # Special handling: Cline agent expects tool_calls for proxy commands
        try:
            if (
                getattr(session, "agent", None) == "cline"
                and command_result.command_executed
            ):
                await self._session_manager.record_command_in_session(
                    request_data, session_id
                )
                return await self._response_manager.process_command_result(
                    command_result, session
                )
        except Exception:
            # Fall back to default path on any issue
            logger.debug("Cline agent fast-path failed; continuing", exc_info=True)

        # Check if we should take the command-only path
        if self._should_process_command_only(command_result):
            logger.debug(f"Taking command result path for session {session_id}")
            logger.info(
                "Command executed with no modified messages - returning command result without backend call"
            )
            await self._session_manager.record_command_in_session(
                request_data, session_id
            )
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Prepare backend request
        backend_request = await self._backend_request_manager.prepare_backend_request(
            request_data, command_result
        )

        # Apply request redaction middleware (API keys and proxy commands)
        # just before calling the backend, so both original and command-modified
        # messages are covered.
        if backend_request is not None:
            try:
                from src.core.common.logging_utils import (
                    discover_api_keys_from_config_and_env,
                )
                from src.core.services.redaction_middleware import RedactionMiddleware

                # Resolve AppConfig via injected app_state when available
                app_config = None
                if self._app_state is not None:
                    try:
                        app_config = self._app_state.get_setting("app_config")
                    except Exception:
                        app_config = None

                # Only apply if feature flag is enabled (default True)
                should_redact = True
                try:
                    if app_config is not None and hasattr(app_config, "auth"):
                        should_redact = bool(app_config.auth.redact_api_keys_in_prompts)
                except Exception:
                    # Be conservative: keep redaction enabled on errors
                    should_redact = True

                if should_redact:
                    api_keys = discover_api_keys_from_config_and_env(app_config)
                    # Command prefix can be None; RedactionMiddleware has a default
                    command_prefix = None
                    try:
                        command_prefix = (
                            app_config.command_prefix
                            if app_config is not None
                            else None
                        )
                    except Exception:
                        command_prefix = None

                    # Check if commands are disabled
                    commands_disabled = False
                    if self._app_state is not None:
                        try:
                            commands_disabled = bool(
                                self._app_state.get_disable_commands()
                            )
                        except AttributeError:
                            commands_disabled = False

                    redaction = RedactionMiddleware(
                        api_keys=api_keys,
                        command_prefix=command_prefix or "!/",
                    )
                    redaction_context = {"commands_disabled": commands_disabled}
                    backend_request = await redaction.process(
                        backend_request, redaction_context
                    )
            except Exception:
                # Redaction is best-effort; never block requests on failure
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Request redaction middleware failed; proceeding without redaction",
                        exc_info=True,
                    )

        # Apply edit-precision tuning middleware if enabled and we still have a backend request
        if backend_request is not None:
            try:
                from src.core.services.edit_precision_middleware import (
                    EditPrecisionTuningMiddleware,
                )

                # Resolve AppConfig via injected app_state when available
                cfg_enabled = True
                cfg_temp = 0.1
                cfg_min_top_p: float | None = 0.3
                exclude_agents_regex: str | None = None
                cfg_override_top_p = False
                if self._app_state is not None:
                    try:
                        app_config = self._app_state.get_setting("app_config")
                        if app_config is not None and hasattr(
                            app_config, "edit_precision"
                        ):
                            # Pydantic models expose attributes directly
                            ep = app_config.edit_precision
                            cfg_enabled = bool(getattr(ep, "enabled", True))
                            cfg_temp = float(getattr(ep, "temperature", 0.1))
                            cfg_override_top_p = bool(
                                getattr(ep, "override_top_p", False)
                            )
                            cfg_min_top_p = (
                                getattr(ep, "min_top_p", 0.3)
                                if cfg_override_top_p
                                else None
                            )
                            cfg_target_top_k = (
                                int(getattr(ep, "target_top_k", 0)) or None
                                if bool(getattr(ep, "override_top_k", False))
                                else None
                            )
                            exclude_agents_regex = getattr(
                                ep, "exclude_agents_regex", None
                            )
                    except Exception:
                        # Keep defaults on error
                        cfg_enabled = True

                # Respect agent exclusion regex if configured
                if (
                    cfg_enabled
                    and exclude_agents_regex
                    and getattr(session, "agent", None)
                ):
                    try:
                        if re.search(
                            exclude_agents_regex,
                            str(session.agent),
                            re.IGNORECASE,
                        ):
                            cfg_enabled = False
                    except re.error:
                        # Invalid pattern; ignore exclusion
                        pass

                # If previous response flagged a pending precision tune, apply once
                force_apply = False
                try:
                    pending_map = (
                        self._app_state.get_setting("edit_precision_pending")
                        if self._app_state is not None
                        else None
                    )
                    if isinstance(pending_map, dict):
                        pending_count = int(pending_map.get(session_id, 0))
                        if pending_count > 0:
                            force_apply = True
                            # decrement one-shot counter
                            pending_map[session_id] = pending_count - 1
                            if self._app_state is not None:
                                self._app_state.set_setting(
                                    "edit_precision_pending", pending_map
                                )
                            # Best-effort info log
                            import contextlib

                            with contextlib.suppress(Exception):
                                logger.info(
                                    "Edit-precision pending consumed; session_id=%s prior_count=%s now=%s",
                                    session_id,
                                    pending_count,
                                    pending_map.get(session_id, 0),
                                )
                except Exception:
                    pass

                if cfg_enabled:
                    edit_precision = EditPrecisionTuningMiddleware(
                        target_temperature=cfg_temp,
                        min_top_p=cfg_min_top_p,
                        force_apply=force_apply,
                    )
                    # Inject target top_k dynamically if configured
                    try:
                        if cfg_target_top_k is not None:
                            edit_precision._target_top_k = int(cfg_target_top_k)
                    except Exception:
                        pass
                    backend_request = await edit_precision.process(
                        backend_request,
                        {
                            "session_id": session_id,
                            "agent": getattr(session, "agent", None),
                        },
                    )
            except Exception:
                # Never block on precision tuning; proceed with original request
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Edit-precision middleware failed; proceeding without overrides",
                        exc_info=True,
                    )

        if backend_request is None:
            # Skip backend call and return command result directly
            logger.debug(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            logger.info(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            await self._session_manager.record_command_in_session(
                request_data, session_id
            )
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Add session_id to extra_body if not present
        async def _resolve_extra_body(value: Any) -> dict[str, Any] | None:
            v = value
            try:
                # If already awaitable (e.g., AsyncMock), await directly
                if hasattr(v, "__await__"):
                    v = await v  # type: ignore[func-returns-value]
                # If callable, call it; then await if needed
                elif callable(v):
                    rv = v()
                    if hasattr(rv, "__await__"):
                        v = await rv  # type: ignore[func-returns-value]
                    else:
                        v = rv
                # Expect dict-like or None
                if v is None:
                    return None
                if isinstance(v, dict):
                    return v
                # Some domain objects may have model_dump method
                if hasattr(v, "model_dump"):
                    dumped = v.model_dump()
                    return dumped if isinstance(dumped, dict) else None
            except (TypeError, AttributeError) as e:
                logger.warning(f"Error resolving extra_body: {e}", exc_info=True)
                return None
            return None

        resolved_extra = await _resolve_extra_body(
            getattr(backend_request, "extra_body", None)
        )
        extra_body: dict[str, Any] = resolved_extra.copy() if resolved_extra else {}
        if "session_id" not in extra_body:
            extra_body["session_id"] = session_id
        backend_request = backend_request.model_copy(update={"extra_body": extra_body})

        # Process backend request with retry handling
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Calling backend for session {session_id} with request: {backend_request}"
            )
        backend_response = await self._backend_request_manager.process_backend_request(
            backend_request, session_id, context
        )
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Backend response for session {session_id}: {backend_response}"
            )

        # Update session history with the backend interaction
        await self._session_manager.update_session_history(
            request_data, backend_request, backend_response, session_id
        )

        return backend_response

    async def _process_command_result(
        self, command_result: ProcessedResult, session: Any
    ) -> ResponseEnvelope:
        """Compatibility wrapper used by legacy tests to process command-only results.

        Delegates to the injected response manager.
        """
        return await self._response_manager.process_command_result(
            command_result, session
        )

    def _should_process_command_only(self, command_result: ProcessedResult) -> bool:
        """Determine if we should process command result without backend call."""
        return command_result.command_executed and not command_result.modified_messages

    async def _handle_command_processing(
        self, request_data: ChatRequest, session_id: str, context: RequestContext
    ) -> ProcessedResult:
        """Handle command processing with global disable check and fallback."""
        # Respect global disable for interactive commands via injected application state
        should_disable_commands = False
        if self._app_state is not None:
            try:
                should_disable_commands = bool(self._app_state.get_disable_commands())
            except AttributeError as e:
                logger.warning(
                    f"Error getting disable_commands state: {e}", exc_info=True
                )
                should_disable_commands = False

        if should_disable_commands:
            # When commands are disabled, return early without processing
            # This prevents command execution and forces backend call path
            return ProcessedResult(
                command_executed=False,
                modified_messages=[],
                command_results=[],
            )

        # Work on a deep copy to avoid mutating the original request messages
        messages_copy = copy.deepcopy(request_data.messages)
        return await self._command_processor.process_messages(
            messages_copy, session_id, context
        )
