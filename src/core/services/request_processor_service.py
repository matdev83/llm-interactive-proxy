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
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
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

        # Attach domain_request to context for intelligent session resolution
        context.domain_request = request_data  # type: ignore

        # Resolve session and update agent if needed
        session_id = await self._session_manager.resolve_session_id(context)
        session = await self._session_manager.get_session(session_id)

        incoming_agent = getattr(request_data, "agent", None) or getattr(
            context, "agent", None
        )
        session = await self._session_manager.update_session_agent(
            session, incoming_agent
        )
        session_agent = getattr(session, "agent", None)
        if session_agent:
            request_data = request_data.model_copy(update={"agent": session_agent})

        logger.debug(f"Resolved session_id: {session_id}")
        logger.debug(
            f"Request data type: {type(request_data)}, model: {getattr(request_data, 'model', 'unknown')}"
        )

        # Auto-detect project directory if needed
        if (
            self._app_state is not None
            and hasattr(session, "state")
            and not getattr(session.state, "project_dir_resolution_attempted", False)
        ):
            try:
                project_dir_service = self._app_state.get_service(
                    ProjectDirectoryResolutionService
                )
                if project_dir_service:
                    await project_dir_service.maybe_resolve_project_directory(
                        session, request_data
                    )
                    logger.debug("Project directory auto-detection completed")
            except Exception as e:
                # Don't fail the request if project directory detection fails
                logger.debug(
                    f"Project directory auto-detection failed: {e}", exc_info=True
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
                        logger.debug(
                            "Failed to enforce input token limit; continuing",
                            exc_info=True,
                        )
            except InvalidRequestError:
                # Bubble up to FastAPI exception handlers
                raise
            except Exception:
                # If anything in enforcement fails, continue without blocking
                logger.debug(
                    "Model limits enforcement encountered an error; proceeding",
                    exc_info=True,
                )

        # Apply request redaction middleware (API keys and proxy commands)
        # just before calling the backend, so both original and command-modified
        # messages are covered.
        logger.debug(
            f"Redaction check: backend_request is not None = {backend_request is not None}"
        )
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

                # Only apply if feature flag or session override enable it
                should_redact = True
                session_override: bool | None = None
                try:
                    session_state = getattr(session, "state", None)
                    if session_state is not None:
                        session_override = getattr(
                            session_state, "api_key_redaction_enabled", None
                        )
                        if not isinstance(session_override, bool | type(None)):
                            session_override = None
                except Exception:
                    session_override = None

                if session_override is None:
                    try:
                        if app_config is not None and hasattr(app_config, "auth"):
                            should_redact = bool(
                                app_config.auth.redact_api_keys_in_prompts
                            )
                    except (AttributeError, TypeError, ValueError):
                        # Be conservative: keep redaction enabled on errors
                        should_redact = True
                else:
                    should_redact = bool(session_override)

                if should_redact:
                    api_keys = discover_api_keys_from_config_and_env(app_config)
                    # Command prefix can be None; RedactionMiddleware has a default
                    command_prefix: str | None = None

                    # Check for session-level command prefix override first
                    try:
                        session_state = getattr(session, "state", None)
                        if session_state is not None:
                            session_prefix = getattr(
                                session_state, "command_prefix_override", None
                            )
                            if (
                                isinstance(session_prefix, str)
                                and session_prefix.strip()
                            ):
                                command_prefix = session_prefix.strip()
                    except Exception:
                        pass

                    # Fall back to app state command prefix if no session override
                    if not command_prefix and self._app_state is not None:
                        try:
                            candidate_prefix = self._app_state.get_command_prefix()
                        except AttributeError:
                            candidate_prefix = None
                        if isinstance(candidate_prefix, str):
                            stripped_prefix = candidate_prefix.strip()
                            command_prefix = stripped_prefix or None
                        else:
                            command_prefix = None

                    # Fall back to config command prefix if still not found
                    if not command_prefix:
                        try:
                            config_prefix = (
                                app_config.command_prefix
                                if app_config is not None
                                else None
                            )
                            if isinstance(config_prefix, str):
                                stripped_prefix = config_prefix.strip()
                                command_prefix = stripped_prefix or None
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

                    # Debug logging before redaction (minimal for performance)
                    if (
                        logger.isEnabledFor(logging.DEBUG)
                        and backend_request
                        and backend_request.messages
                    ):
                        logger.debug(
                            f"Processing redaction for {len(backend_request.messages)} messages"
                        )

                    backend_request = await redaction.process(
                        backend_request, redaction_context
                    )

                    # Debug logging after redaction (minimal for performance)
                    if (
                        logger.isEnabledFor(logging.DEBUG)
                        and backend_request
                        and backend_request.messages
                    ):
                        logger.debug(
                            f"Redaction completed for {len(backend_request.messages)} messages"
                        )
            except Exception as e:
                # Redaction is best-effort; never block requests on failure
                logger.warning(
                    "Request redaction middleware failed; proceeding without redaction: %s",
                    e,
                    exc_info=True,
                )

        # Apply edit-precision tuning middleware if enabled and we still have a backend request
        if backend_request is not None:
            try:
                from src.core.config.edit_precision_temperatures import (
                    load_edit_precision_temperatures_config,
                )
                from src.core.services.edit_precision_middleware import (
                    EditPrecisionTuningMiddleware,
                )

                # Load model-specific temperatures config (cached at module level)
                temperatures_config = load_edit_precision_temperatures_config()

                # Resolve AppConfig via injected app_state when available
                cfg_enabled = True
                cfg_temp = 0.1
                cfg_min_top_p: float | None = 0.3
                exclude_agents_regex: str | None = None
                cfg_override_top_p = False
                cfg_target_top_k: int | None = None
                app_config = None
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
                        app_config = None

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
                        pending_map = dict(pending_map)
                        pending_count = int(pending_map.get(session_id, 0))
                        if pending_count > 0:
                            force_apply = True
                            # decrement one-shot counter
                            new_count = pending_count - 1
                            if new_count > 0:
                                pending_map[session_id] = new_count
                            else:
                                pending_map.pop(session_id, None)
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

                # NEW: Check if hybrid reasoning should be disabled for this session
                hybrid_reasoning_disabled = False
                try:
                    hybrid_disabled_map = (
                        self._app_state.get_setting(
                            "edit_precision_hybrid_reasoning_disabled"
                        )
                        if self._app_state is not None
                        else None
                    )
                    if isinstance(hybrid_disabled_map, dict):
                        hybrid_disabled_map = dict(hybrid_disabled_map)
                        if session_id in hybrid_disabled_map:
                            hybrid_reasoning_disabled = True
                            # Remove the flag so it's only used for this request
                            del hybrid_disabled_map[session_id]
                            if self._app_state is not None:
                                self._app_state.set_setting(
                                    "edit_precision_hybrid_reasoning_disabled",
                                    hybrid_disabled_map,
                                )
                                self._clear_active_hybrid_disable_flag(session_id)
                            logger.info(
                                f"Hybrid reasoning disabled for session {session_id} due to edit failure",
                                extra={"session_id": session_id},
                            )
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(
                        "Could not resolve hybrid reasoning disabled flag: %s",
                        e,
                        exc_info=True,
                    )

                if cfg_enabled:
                    edit_precision = EditPrecisionTuningMiddleware(
                        target_temperature=cfg_temp,
                        min_top_p=cfg_min_top_p,
                        force_apply=force_apply,
                        temperatures_config=temperatures_config,
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

                if hybrid_reasoning_disabled and backend_request is not None:
                    backend_request = self._apply_hybrid_reasoning_override(
                        backend_request,
                        session_id,
                        app_config,
                    )
            except (AttributeError, TypeError, ValueError):
                # Never block on precision tuning; proceed with original request
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

        # Apply tool access control filtering if enabled and tools are present
        if backend_request is not None and getattr(backend_request, "tools", None):
            try:
                from src.core.services.tool_access_policy_service import (
                    ToolAccessPolicyService,
                )

                policy_service = None
                if self._app_state is not None:
                    try:
                        policy_service = self._app_state.get_service(
                            ToolAccessPolicyService
                        )
                    except (AttributeError, KeyError, TypeError):
                        policy_service = None

                if policy_service:
                    model_name = getattr(backend_request, "model", "")
                    agent = getattr(session, "agent", None)

                    filtered_tools, metadata = policy_service.filter_tool_definitions(
                        backend_request.tools or [], model_name, agent
                    )

                    # Create modified request with filtered tools if any were removed
                    original_tools = backend_request.tools or []
                    if len(filtered_tools) < len(original_tools):
                        backend_request = backend_request.model_copy(
                            update={"tools": filtered_tools}
                        )

                        # Handle tool_choice if it references a filtered tool
                        tool_choice = getattr(backend_request, "tool_choice", None)
                        if (
                            tool_choice
                            and isinstance(tool_choice, dict)
                            and "function" in tool_choice
                        ):
                            choice_name = tool_choice.get("function", {}).get("name")
                            if choice_name:
                                # Check if the referenced tool is still in filtered_tools
                                tool_names = [
                                    policy_service._extract_tool_name(t)
                                    for t in filtered_tools
                                ]
                                if choice_name not in tool_names:
                                    # Remove tool_choice or set to "auto"
                                    backend_request = backend_request.model_copy(
                                        update={"tool_choice": "auto"}
                                    )
                                    logger.info(
                                        f"Reset tool_choice to 'auto' because referenced tool '{choice_name}' was filtered"
                                    )

                        # Log the filtering action
                        removed_count = len(original_tools) - len(filtered_tools)
                        policy_name = metadata.get("policy_applied", "unknown")
                        filtered_names = metadata.get("filtered_tool_names", [])

                        logger.info(
                            f"Filtered {removed_count} tool definition(s) for model "
                            f"{model_name} by policy '{policy_name}': {filtered_names}"
                        )

                        # Increment telemetry counter in reactor service
                        try:
                            from src.core.services.tool_call_reactor_service import (
                                ToolCallReactorService,
                            )

                            if self._app_state:
                                reactor_service = self._app_state.get_service(
                                    ToolCallReactorService
                                )
                            else:
                                reactor_service = None
                            if reactor_service and hasattr(
                                reactor_service, "increment_tool_definitions_filtered"
                            ):
                                reactor_service.increment_tool_definitions_filtered(
                                    removed_count
                                )
                        except (AttributeError, KeyError, TypeError):
                            pass

                        # Store metadata in extra_body for observability
                        extra_body_attr = getattr(backend_request, "extra_body", None)
                        extra_body: dict[str, Any] = (
                            extra_body_attr.copy() if extra_body_attr else {}
                        )
                        extra_body["tool_access"] = metadata
                        backend_request = backend_request.model_copy(
                            update={"extra_body": extra_body}
                        )

            except Exception as e:
                # Tool definition filtering is fail-open: log warning and proceed
                logger.warning(f"Tool definition filtering failed: {e}", exc_info=True)

        # Add session_id to extra_body if not present
        final_extra_body_attr = getattr(backend_request, "extra_body", None)
        final_extra_body: dict[str, Any] = (
            final_extra_body_attr.copy() if final_extra_body_attr else {}
        )
        if "session_id" not in final_extra_body:
            final_extra_body["session_id"] = session_id
        backend_request = backend_request.model_copy(
            update={"extra_body": final_extra_body}
        )

        # Process backend request with retry handling
        logger.info(
            f"Calling backend for session {session_id} with model: {getattr(backend_request, 'model', 'unknown')}"
        )
        backend_response = await self._backend_request_manager.process_backend_request(
            backend_request, session_id, context
        )
        logger.info(
            f"Backend response for session {session_id}: {type(backend_response).__name__}"
        )

        # Update session history with the backend interaction
        await self._session_manager.update_session_history(
            request_data, backend_request, backend_response, session_id
        )

        # Update session fingerprint for continuity detection
        if hasattr(self._session_manager, "update_session_fingerprint"):
            try:
                await self._session_manager.update_session_fingerprint(
                    session_id, list(backend_request.messages)
                )
            except Exception as e:
                logger.debug(
                    f"Failed to update session fingerprint: {e}", exc_info=True
                )

        return backend_response

    def _clear_active_hybrid_disable_flag(self, session_id: str) -> None:
        """Remove the active hybrid disable marker for the given session if present."""
        if self._app_state is None:
            return

        try:
            active_map = self._app_state.get_setting(
                "edit_precision_hybrid_reasoning_active", {}
            )
            if not isinstance(active_map, dict) or session_id not in active_map:
                return

            updated_map = dict(active_map)
            updated_map.pop(session_id, None)
            self._app_state.set_setting(
                "edit_precision_hybrid_reasoning_active", updated_map
            )
        except Exception as exc:
            logger.debug(
                "Failed to clear active hybrid disable marker for session %s: %s",
                session_id,
                exc,
                exc_info=True,
            )

    def _apply_hybrid_reasoning_override(
        self,
        backend_request: ChatRequest,
        session_id: str,
        app_config: Any | None,
    ) -> ChatRequest:
        """Temporarily disable hybrid reasoning for the given request if applicable."""

        try:
            model_name = str(getattr(backend_request, "model", "") or "")
        except Exception:
            model_name = ""

        if not model_name.lower().startswith("hybrid:"):
            return backend_request

        extra_body_attr = getattr(backend_request, "extra_body", None)
        extra_body: dict[str, Any] = (
            extra_body_attr.copy() if isinstance(extra_body_attr, dict) else {}
        )

        # Respect existing override if one is already forcing a low probability
        existing_override = extra_body.get("_temp_hybrid_reasoning_probability")
        if existing_override is not None:
            try:
                if float(existing_override) <= 0.0:
                    return backend_request
            except (TypeError, ValueError):
                pass

        base_probability = self._resolve_hybrid_reasoning_probability(
            extra_body_attr if isinstance(extra_body_attr, dict) else None,
            app_config,
        )

        if base_probability is not None and base_probability <= 0.0:
            return backend_request

        meta = extra_body.get("_edit_precision_meta")
        if not isinstance(meta, dict):
            meta = {}
            extra_body["_edit_precision_meta"] = meta

        if base_probability is not None:
            meta.setdefault(
                "original_hybrid_reasoning_probability", float(base_probability)
            )
        meta["applied_hybrid_reasoning_probability"] = 0.0
        meta["hybrid_reasoning_override_source"] = "response_pending"

        extra_body["_temp_hybrid_reasoning_probability"] = 0.0

        base_display = base_probability if base_probability is not None else "unknown"
        logger.info(
            "Hybrid reasoning probability override applied; session_id=%s base=%s -> 0.0",
            session_id,
            base_display,
        )

        return backend_request.model_copy(update={"extra_body": extra_body})

    def _resolve_hybrid_reasoning_probability(
        self,
        extra_body: dict[str, Any] | None,
        app_config: Any | None,
    ) -> float | None:
        """Resolve the baseline hybrid reasoning probability for logging/telemetry."""

        if isinstance(extra_body, dict):
            for key in (
                "hybrid_reasoning_probability",
                "hybrid_reasoning_probability_override",
            ):
                value = extra_body.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue

        if app_config is not None:
            try:
                backends_cfg = getattr(app_config, "backends", None)
                value = getattr(backends_cfg, "reasoning_injection_probability", None)
                if value is not None:
                    return float(value)
            except (AttributeError, TypeError, ValueError):
                return None

        return None

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
