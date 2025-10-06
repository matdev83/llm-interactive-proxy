"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

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
        except (AttributeError, TypeError):
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

        # Enforce per-model context window limits (front-end enforcement)
        if backend_request is not None and self._app_state is not None:
            try:
                from src.core.common.exceptions import InvalidRequestError
                from src.core.domain.model_utils import (
                    ModelDefaults,
                    parse_model_backend,
                )
                from src.core.utils.token_count import count_tokens, extract_prompt_text

                model_defaults_map: dict[str, Any] = (
                    self._app_state.get_model_defaults() or {}
                )
                # Resolve backend and model name
                backend_type: str | None = None
                try:
                    backend_type = self._app_state.get_backend_type()
                except Exception:
                    backend_type = None

                _rm = getattr(backend_request, "model", None) or getattr(
                    request_data, "model", ""
                )
                requested_model: str = str(_rm)
                backend_key, model_name = parse_model_backend(
                    requested_model, (backend_type or "")
                )

                # Candidate keys to look up defaults
                candidate_keys: list[str] = []
                if requested_model:
                    candidate_keys.append(requested_model)
                if backend_key and model_name:
                    candidate_keys.append(f"{backend_key}:{model_name}")
                    candidate_keys.append(f"{backend_key}/{model_name}")
                if model_name:
                    candidate_keys.append(model_name)

                model_defaults: ModelDefaults | dict[str, Any] | None = None
                for k in candidate_keys:
                    md = model_defaults_map.get(k)
                    if md is None:
                        continue
                    # Accept either a ModelDefaults instance or a plain dict-like
                    if isinstance(md, ModelDefaults | dict):
                        model_defaults = md
                        break

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Model limits lookup: requested_model=%s backend=%s model=%s candidates=%s found=%s",
                        requested_model,
                        backend_key,
                        model_name,
                        candidate_keys,
                        bool(model_defaults),
                    )

                # Check for CLI context window override first
                cli_context_window = None
                if self._app_state is not None:
                    try:
                        app_config = self._app_state.get_setting("app_config")
                        if app_config is not None and hasattr(
                            app_config, "context_window_override"
                        ):
                            cli_context_window = getattr(
                                app_config, "context_window_override", None
                            )
                    except (AttributeError, KeyError, TypeError):
                        cli_context_window = None

                limits = (
                    getattr(model_defaults, "limits", None)
                    if model_defaults is not None
                    and not isinstance(model_defaults, dict)
                    else (
                        model_defaults.get("limits")
                        if isinstance(model_defaults, dict)
                        else None
                    )
                )

                # Apply CLI override if set
                if cli_context_window is not None and cli_context_window > 0:
                    # Create a new limits object or modify existing to use CLI override
                    if limits is None:
                        limits = {"context_window": cli_context_window}
                    elif isinstance(limits, dict):
                        limits = limits.copy()
                        limits["context_window"] = cli_context_window
                        # Also update max_input_tokens to match for consistency
                        limits["max_input_tokens"] = cli_context_window
                    else:
                        # Create a dict representation for object-based limits
                        limits = {
                            "context_window": cli_context_window,
                            "max_input_tokens": cli_context_window,
                            "max_output_tokens": getattr(
                                limits, "max_output_tokens", None
                            ),
                            "requests_per_minute": getattr(
                                limits, "requests_per_minute", None
                            ),
                            "tokens_per_minute": getattr(
                                limits, "tokens_per_minute", None
                            ),
                        }

                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Applied CLI context window override: %s tokens for model %s",
                            cli_context_window,
                            requested_model or model_name,
                        )
                if limits is not None:
                    # Note: max_output_tokens enforcement removed as it's redundant with backend limits
                    # and provides limited practical value. Backend providers already enforce
                    # their own output limits, and models naturally stop when complete.

                    # Enforce input token limit as a hard error
                    try:
                        # Determine effective input token limit. Prefer explicit max_input_tokens,
                        # but fall back to context_window when only that is configured.
                        max_in = None
                        context_window = None
                        if isinstance(limits, dict):
                            max_in = limits.get("max_input_tokens") or limits.get(
                                "context_window"
                            )
                            context_window = limits.get("context_window")
                        else:
                            max_in = getattr(
                                limits, "max_input_tokens", None
                            ) or getattr(limits, "context_window", None)
                            context_window = getattr(limits, "context_window", None)

                        if max_in is not None and max_in > 0:
                            text = extract_prompt_text(
                                getattr(backend_request, "messages", []) or []
                            )
                            measured = int(count_tokens(text, model=model_name))

                            # Check input token limit
                            if measured > int(max_in):
                                logger.info(
                                    "Input token limit exceeded: measured=%s limit=%s model=%s",
                                    measured,
                                    int(max_in),
                                    requested_model,
                                )
                                raise InvalidRequestError(
                                    message="Input token limit exceeded",
                                    code="input_limit_exceeded",
                                    param="messages",
                                    details={
                                        "model": requested_model or model_name,
                                        "limit": int(max_in),
                                        "measured": measured,
                                    },
                                )

                            # Check total token limit (input + max_tokens) against context window
                            max_tokens = getattr(backend_request, "max_tokens", None)
                            if (
                                context_window is not None
                                and context_window > 0
                                and max_tokens is not None
                                and max_tokens > 0
                            ):
                                total_requested = measured + max_tokens
                                if total_requested > context_window:
                                    logger.info(
                                        "Total token limit exceeded: input=%s + max_tokens=%s = %s > context_window=%s model=%s",
                                        measured,
                                        max_tokens,
                                        total_requested,
                                        context_window,
                                        requested_model,
                                    )
                                    raise InvalidRequestError(
                                        message="Total token limit exceeded (input + max_tokens exceeds context window)",
                                        code="total_limit_exceeded",
                                        param="max_tokens",
                                        details={
                                            "model": requested_model or model_name,
                                            "context_window": int(context_window),
                                            "input_tokens": measured,
                                            "max_tokens": max_tokens,
                                            "total_requested": total_requested,
                                            "suggestion": f"Reduce max_tokens to {context_window - measured} or less",
                                        },
                                    )
                    except InvalidRequestError:
                        # Re-raise structured invalid request
                        raise
                    except Exception:
                        # Best-effort enforcement; don't fail on unexpected issues
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to enforce input token limit; continuing",
                                exc_info=True,
                            )
            except InvalidRequestError:
                # Bubble up to FastAPI exception handlers
                raise
            except Exception:
                # If anything in enforcement fails, continue without blocking
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Model limits enforcement encountered an error; proceeding",
                        exc_info=True,
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
                    except (AttributeError, KeyError, TypeError):
                        app_config = None

                # Only apply if feature flag is enabled (default True)
                should_redact = True
                try:
                    if app_config is not None and hasattr(app_config, "auth"):
                        should_redact = bool(app_config.auth.redact_api_keys_in_prompts)
                except (AttributeError, TypeError, ValueError):
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
                    except (AttributeError, TypeError):
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
            except (AttributeError, TypeError, ValueError):
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
                cfg_target_top_k: int | None = None
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
                    except (AttributeError, TypeError, ValueError):
                        # Keep defaults on error
                        cfg_enabled = True
                        cfg_temp = 0.1
                        cfg_override_top_p = False
                        cfg_min_top_p = None
                        cfg_target_top_k = None
                        exclude_agents_regex = None

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
                    except re.error as e:
                        # Invalid pattern; ignore exclusion
                        logger.warning(
                            "Invalid regex in edit_precision.exclude_agents_regex: %s",
                            e,
                        )

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
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(
                        "Could not resolve edit_precision_pending: %s", e, exc_info=True
                    )

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
                    except (AttributeError, TypeError, ValueError) as e:
                        logger.debug(
                            "Could not set target_top_k on edit_precision middleware: %s",
                            e,
                            exc_info=True,
                        )
                    backend_request = await edit_precision.process(
                        backend_request,
                        {
                            "session_id": session_id,
                            "agent": getattr(session, "agent", None),
                        },
                    )
            except (AttributeError, TypeError, ValueError):
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
        extra_body_attr = getattr(backend_request, "extra_body", None)
        extra_body: dict[str, Any] = extra_body_attr.copy() if extra_body_attr else {}
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

        # The command processor is now responsible for creating copies of any messages it modifies.
        return await self._command_processor.process_messages(
            request_data.messages, session_id, context
        )
