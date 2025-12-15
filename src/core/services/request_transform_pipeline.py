"""
Request transformation pipeline implementation.

This module provides the implementation of request transformations including:
- API key redaction
- Edit precision tuning
- Tool access control filtering

All transformations follow fail-open semantics and fixed ordering.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.request_processor_internal import IRequestTransformPipeline

logger = logging.getLogger(__name__)


class RequestTransformPipeline(IRequestTransformPipeline):
    """
    Implements request transformations with fixed ordering and fail-open behavior.

    Transformation order (Requirement 9.8):
    1. API key redaction
    2. Edit precision tuning
    3. Tool access control filtering

    All transformations are fail-open (Requirement 9.7): unexpected errors
    are logged and processing continues.
    """

    def __init__(self, app_state: IApplicationState | None = None) -> None:
        """
        Initialize the transformation pipeline.

        Args:
            app_state: Application state for accessing configuration and services
        """
        self._app_state = app_state

    async def transform(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        """
        Apply request transformations in fixed order.

        Transformation order (must be preserved):
        1. API key redaction
        2. Edit precision tuning
        3. Tool filtering

        All transformations are fail-open (log and continue on unexpected errors).
        Structured validation failures (from preparation phase) are not handled here.

        Args:
            context: Request context
            session: Session object
            session_id: Session ID
            request: Chat request to transform

        Returns:
            Transformed chat request
        """
        # Apply redaction (fail-open)
        try:
            request = await self._apply_redaction(context, session, session_id, request)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Request redaction middleware failed; proceeding without redaction: %s",
                    e,
                    exc_info=True,
                )

        # Apply edit precision (fail-open)
        try:
            request = await self._apply_edit_precision(
                context, session, session_id, request
            )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Edit precision tuning failed; proceeding with original request: %s",
                    e,
                    exc_info=True,
                )

        # Apply tool filtering (fail-open)
        try:
            request = await self._apply_tool_filtering(
                context, session, session_id, request
            )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Tool definition filtering failed: {e}",
                    exc_info=True,
                )

        return request

    async def _apply_redaction(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        """
        Apply API key redaction to request.

        Configuration precedence for enabling redaction:
        1. Session-level override (session.state.api_key_redaction_enabled)
        2. App config setting (app_config.auth.redact_api_keys_in_prompts)

        Command prefix precedence:
        1. Session-level override (session.state.command_prefix_override)
        2. App state command prefix (app_state.get_command_prefix())
        3. Config command prefix (app_config.command_prefix)

        Returns:
            Request with API keys redacted (or unchanged if redaction disabled)
        """
        # Get app config
        app_config = None
        if self._app_state is not None:
            try:
                app_config = self._app_state.get_setting("app_config")
            except (AttributeError, KeyError, TypeError):
                app_config = None

        # Determine if redaction should be applied
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
                    should_redact = bool(app_config.auth.redact_api_keys_in_prompts)
            except (AttributeError, TypeError, ValueError):
                # Be conservative: keep redaction enabled on errors
                should_redact = True
        else:
            should_redact = bool(session_override)

        if not should_redact:
            return request

        # Import redaction middleware
        from src.core.common.logging_utils import (
            discover_api_keys_from_config_and_env,
        )
        from src.core.services.redaction_middleware import RedactionMiddleware

        # Discover API keys
        api_keys = discover_api_keys_from_config_and_env(app_config)

        # Resolve command prefix with precedence
        command_prefix: str | None = None

        # Check for session-level command prefix override first
        try:
            session_state = getattr(session, "state", None)
            if session_state is not None:
                session_prefix = getattr(session_state, "command_prefix_override", None)
                if isinstance(session_prefix, str) and session_prefix.strip():
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
                    app_config.command_prefix if app_config is not None else None
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
                commands_disabled = bool(self._app_state.get_disable_commands())
            except AttributeError:
                commands_disabled = False

        # Create and apply redaction middleware
        redaction = RedactionMiddleware(
            api_keys=api_keys,
            command_prefix=command_prefix or "!/",
        )
        redaction_context = {
            "commands_disabled": commands_disabled,
            "session_id": session_id,
        }

        # Debug logging before redaction (minimal for performance)
        if logger.isEnabledFor(logging.DEBUG) and request and request.messages:
            logger.debug(f"Processing redaction for {len(request.messages)} messages")

        try:
            request = await redaction.process(request, redaction_context)

            # Debug logging after redaction (minimal for performance)
            if logger.isEnabledFor(logging.DEBUG) and request and request.messages:
                logger.debug(
                    f"Redaction completed for {len(request.messages)} messages"
                )
        except Exception as e:
            # Redaction is best-effort; log and continue with original request
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Redaction middleware process failed; continuing with original request: %s",
                    e,
                    exc_info=True,
                )

        return request

    async def _apply_edit_precision(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        """
        Apply edit precision tuning to request.

        Adjusts sampling parameters (temperature, top_p, top_k) based on
        configuration and agent exclusions. May apply hybrid reasoning
        suppression if active in session state.

        Returns:
            Request with edit precision adjustments (or unchanged if disabled)
        """
        if request is None:
            return request

        # Import edit precision middleware
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
                if app_config is not None and hasattr(app_config, "edit_precision"):
                    # Pydantic models expose attributes directly
                    ep = app_config.edit_precision
                    cfg_enabled = bool(getattr(ep, "enabled", True))
                    cfg_temp = float(getattr(ep, "temperature", 0.1))
                    cfg_override_top_p = bool(getattr(ep, "override_top_p", False))
                    cfg_min_top_p = (
                        getattr(ep, "min_top_p", 0.3) if cfg_override_top_p else None
                    )
                    cfg_target_top_k = (
                        int(getattr(ep, "target_top_k", 0)) or None
                        if bool(getattr(ep, "override_top_k", False))
                        else None
                    )
                    exclude_agents_regex = getattr(ep, "exclude_agents_regex", None)
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
        if cfg_enabled and exclude_agents_regex:
            agent = getattr(session, "agent", None)
            if agent:
                try:
                    import re

                    if re.search(exclude_agents_regex, str(agent), re.IGNORECASE):
                        cfg_enabled = False
                except Exception as e:
                    # Invalid pattern; ignore exclusion
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Invalid regex in edit_precision.exclude_agents_regex: %s", e
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
        except (AttributeError, TypeError, ValueError):
            pass

        # Check if hybrid reasoning should be disabled for this session
        hybrid_reasoning_disabled = False
        try:
            hybrid_disabled_map = (
                self._app_state.get_setting("edit_precision_hybrid_reasoning_disabled")
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
            # Also clear the active flag when consuming the disabled flag
            active_map = (
                self._app_state.get_setting("edit_precision_hybrid_reasoning_active")
                if self._app_state is not None
                else None
            )
            if isinstance(active_map, dict) and session_id in active_map:
                active_map = dict(active_map)
                active_map.pop(session_id, None)
                if self._app_state is not None:
                    self._app_state.set_setting(
                        "edit_precision_hybrid_reasoning_active",
                        active_map,
                    )
        except (AttributeError, TypeError, ValueError):
            pass

        if not cfg_enabled:
            return request

        # Create and apply middleware
        try:
            edit_precision = EditPrecisionTuningMiddleware(
                target_temperature=cfg_temp,
                min_top_p=cfg_min_top_p,
                force_apply=force_apply,
                temperatures_config=temperatures_config,
            )
            # Inject target top_k dynamically if configured
            if cfg_target_top_k is not None:
                with contextlib.suppress(AttributeError, TypeError, ValueError):
                    edit_precision._target_top_k = int(cfg_target_top_k)

            request = await edit_precision.process(
                request,
                {
                    "session_id": session_id,
                    "agent": getattr(session, "agent", None),
                },
            )

            if hybrid_reasoning_disabled and request is not None:
                request = self._apply_hybrid_reasoning_override(
                    request, session_id, app_config
                )
        except Exception as e:
            # Fail-open: log and continue with original request
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Edit precision tuning failed; proceeding with original request: %s",
                    e,
                    exc_info=True,
                )

        return request

    def _apply_hybrid_reasoning_override(
        self, request: ChatRequest, session_id: str, app_config: Any
    ) -> ChatRequest:
        """Apply hybrid reasoning suppression override."""
        try:
            extra_body_attr = getattr(request, "extra_body", None)
            extra_body: dict[str, Any] = (
                extra_body_attr.copy() if extra_body_attr else {}
            )

            # Suppress hybrid reasoning
            if app_config is not None:
                try:
                    hrp = getattr(app_config, "hybrid_reasoning_probability", 0.5)
                    extra_body["_temp_hybrid_reasoning_probability"] = 0.0
                    # Also set metadata for observability
                    meta = extra_body.get("_edit_precision_meta")
                    if not isinstance(meta, dict):
                        meta = {}
                        extra_body["_edit_precision_meta"] = meta
                    meta["applied_hybrid_reasoning_probability"] = 0.0
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            f"Suppressing hybrid reasoning for session {session_id} (was {hrp})",
                            extra={"session_id": session_id},
                        )
                except (AttributeError, TypeError):
                    pass

            request = request.model_copy(update={"extra_body": extra_body})
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to apply hybrid reasoning override: %s", e, exc_info=True
                )

        return request

    async def _apply_tool_filtering(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        """
        Apply tool access control filtering to request.

        Filters tool definitions based on policy service rules.
        Adjusts tool_choice if it references a filtered tool.
        Adds metadata to extra_body for observability.

        Returns:
            Request with filtered tools (or unchanged if no filtering needed)
        """
        if request is None or not getattr(request, "tools", None):
            return request

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

            if not policy_service:
                return request

            model_name = getattr(request, "model", "")
            agent = getattr(session, "agent", None)

            filtered_tools, metadata = policy_service.filter_tool_definitions(
                request.tools or [], model_name, agent
            )

            # Create modified request with filtered tools if any were removed
            original_tools = request.tools or []
            if len(filtered_tools) < len(original_tools):
                request = request.model_copy(update={"tools": filtered_tools})

                # Handle tool_choice if it references a filtered tool
                tool_choice = getattr(request, "tool_choice", None)
                if (
                    tool_choice
                    and isinstance(tool_choice, dict)
                    and "function" in tool_choice
                ):
                    choice_name = tool_choice.get("function", {}).get("name")
                    if choice_name:
                        # Check if the referenced tool is still in filtered_tools
                        tool_names = [
                            policy_service._extract_tool_name(t) for t in filtered_tools
                        ]
                        if choice_name not in tool_names:
                            # Remove tool_choice or set to "auto"
                            request = request.model_copy(update={"tool_choice": "auto"})
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    f"Reset tool_choice to 'auto' because referenced tool '{choice_name}' was filtered"
                                )

                # Log the filtering action
                removed_count = len(original_tools) - len(filtered_tools)
                policy_name = metadata.get("policy_applied", "unknown")
                filtered_names = metadata.get("filtered_tool_names", [])

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Filtered {removed_count} tool definition(s) for model "
                        f"{model_name} by policy '{policy_name}': {filtered_names}"
                    )

                # Increment telemetry counter in reactor service (fail-open)
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
                extra_body_attr = getattr(request, "extra_body", None)
                extra_body: dict[str, Any] = (
                    extra_body_attr.copy() if extra_body_attr else {}
                )
                extra_body["tool_access"] = metadata
                request = request.model_copy(update={"extra_body": extra_body})

        except Exception as e:
            # Tool definition filtering is fail-open: log warning and proceed
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Tool definition filtering failed: {e}", exc_info=True)

        return request
