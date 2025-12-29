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

from pydantic.types import JsonValue

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
                    "Tool definition filtering failed: %s",
                    e,
                    exc_info=True,
                )

        return request

    def _get_app_config(self) -> Any | None:
        if self._app_state is None:
            return None
        try:
            return self._app_state.get_setting("app_config")
        except (AttributeError, KeyError, TypeError):
            return None

    def _get_session_state(self, session: object) -> Any | None:
        try:
            return getattr(session, "state", None)
        except AttributeError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to get session.state",
                    exc_info=True,
                )
            return None

    def _should_redact_api_keys(self, session: object, app_config: Any | None) -> bool:
        should_redact = True
        session_override: bool | None = None

        try:
            session_state = self._get_session_state(session)
            if session_state is not None:
                session_override = getattr(
                    session_state, "api_key_redaction_enabled", None
                )
                if not isinstance(session_override, bool | type(None)):
                    session_override = None
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get session state for API key redaction check: %s",
                    e,
                    exc_info=True,
                )
            session_override = None

        if session_override is not None:
            return bool(session_override)

        try:
            if app_config is not None and hasattr(app_config, "auth"):
                should_redact = bool(app_config.auth.redact_api_keys_in_prompts)
        except (AttributeError, TypeError, ValueError):
            should_redact = True

        return should_redact

    def _resolve_command_prefix(
        self, session: object, app_config: Any | None
    ) -> str | None:
        # 1) Session-level override
        try:
            session_state = self._get_session_state(session)
            if session_state is not None:
                session_prefix = getattr(session_state, "command_prefix_override", None)
                if isinstance(session_prefix, str):
                    session_prefix = session_prefix.strip()
                    if session_prefix:
                        return session_prefix
        except (AttributeError, TypeError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve session-level command prefix",
                    exc_info=True,
                )

        # 2) App state
        if self._app_state is not None:
            try:
                candidate_prefix = self._app_state.get_command_prefix()
            except AttributeError:
                candidate_prefix = None
            if isinstance(candidate_prefix, str):
                candidate_prefix = candidate_prefix.strip()
                if candidate_prefix:
                    return candidate_prefix

        # 3) Config
        try:
            config_prefix = (
                app_config.command_prefix if app_config is not None else None
            )
            if isinstance(config_prefix, str):
                config_prefix = config_prefix.strip()
                if config_prefix:
                    return config_prefix
        except (AttributeError, TypeError):
            pass

        return None

    def _get_commands_disabled(self) -> bool:
        if self._app_state is None:
            return False
        try:
            return bool(self._app_state.get_disable_commands())
        except AttributeError:
            return False

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
        app_config = self._get_app_config()
        if not self._should_redact_api_keys(session, app_config):
            return request

        # Import redaction middleware
        from src.core.common.logging_utils import (
            discover_api_keys_from_config_and_env,
        )
        from src.core.services.redaction_middleware import RedactionMiddleware

        # Discover API keys
        api_keys = discover_api_keys_from_config_and_env(app_config)

        # Resolve command prefix with precedence
        command_prefix = self._resolve_command_prefix(session, app_config)
        commands_disabled = self._get_commands_disabled()

        # Create and apply redaction middleware
        redaction = RedactionMiddleware(
            api_keys=api_keys,
            command_prefix=command_prefix or "!/",
        )
        redaction_context: dict[str, JsonValue] = {
            "commands_disabled": commands_disabled,
            "session_id": session_id,
        }

        # Debug logging before redaction (minimal for performance)
        if logger.isEnabledFor(logging.DEBUG) and request and request.messages:
            logger.debug("Processing redaction for %d messages", len(request.messages))

        try:
            request = await redaction.process(request, redaction_context)

            # Debug logging after redaction (minimal for performance)
            if logger.isEnabledFor(logging.DEBUG) and request and request.messages:
                logger.debug(
                    "Redaction completed for %d messages", len(request.messages)
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

    def _get_edit_precision_config(
        self, app_config: Any | None
    ) -> tuple[bool, float, float | None, int | None, str | None]:
        cfg_enabled = True
        cfg_temp = 0.1
        cfg_min_top_p: float | None = 0.3
        exclude_agents_regex: str | None = None
        cfg_target_top_k: int | None = None

        if app_config is None or not hasattr(app_config, "edit_precision"):
            return (
                cfg_enabled,
                cfg_temp,
                cfg_min_top_p,
                cfg_target_top_k,
                exclude_agents_regex,
            )

        try:
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
            cfg_enabled = True
            cfg_temp = 0.1
            cfg_min_top_p = None
            cfg_target_top_k = None
            exclude_agents_regex = None

        return (
            cfg_enabled,
            cfg_temp,
            cfg_min_top_p,
            cfg_target_top_k,
            exclude_agents_regex,
        )

    def _is_agent_excluded(
        self, exclude_agents_regex: str | None, agent: object
    ) -> bool:
        if not exclude_agents_regex or not agent:
            return False
        try:
            import re

            return bool(re.search(exclude_agents_regex, str(agent), re.IGNORECASE))
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Invalid regex in edit_precision.exclude_agents_regex: %s",
                    e,
                )
            return False

    def _consume_one_shot_counter(self, key: str, session_id: str) -> bool:
        if self._app_state is None:
            return False
        try:
            counter_map = self._app_state.get_setting(key)
            if not isinstance(counter_map, dict):
                return False
            counter_map = dict(counter_map)
            count = int(counter_map.get(session_id, 0))
            if count <= 0:
                return False
            new_count = count - 1
            if new_count > 0:
                counter_map[session_id] = new_count
            else:
                counter_map.pop(session_id, None)
            self._app_state.set_setting(key, counter_map)
            return True
        except (AttributeError, TypeError, ValueError):
            return False

    def _consume_flag(self, key: str, session_id: str) -> bool:
        if self._app_state is None:
            return False
        try:
            flag_map = self._app_state.get_setting(key)
            if not isinstance(flag_map, dict) or session_id not in flag_map:
                return False
            flag_map = dict(flag_map)
            del flag_map[session_id]
            self._app_state.set_setting(key, flag_map)
            return True
        except (AttributeError, TypeError, ValueError):
            return False

    def _clear_flag(self, key: str, session_id: str) -> None:
        if self._app_state is None:
            return
        try:
            active_map = self._app_state.get_setting(key)
            if not isinstance(active_map, dict) or session_id not in active_map:
                return
            active_map = dict(active_map)
            active_map.pop(session_id, None)
            self._app_state.set_setting(key, active_map)
        except (AttributeError, TypeError, ValueError):
            return

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
        # Import edit precision middleware
        from src.core.config.edit_precision_temperatures import (
            load_edit_precision_temperatures_config,
        )
        from src.core.services.edit_precision_middleware import (
            EditPrecisionTuningMiddleware,
        )

        # Load model-specific temperatures config (cached at module level)
        temperatures_config = load_edit_precision_temperatures_config()

        app_config = self._get_app_config()
        (
            cfg_enabled,
            cfg_temp,
            cfg_min_top_p,
            cfg_target_top_k,
            exclude_agents_regex,
        ) = self._get_edit_precision_config(app_config)

        # Respect agent exclusion regex if configured
        if cfg_enabled and self._is_agent_excluded(
            exclude_agents_regex, getattr(session, "agent", None)
        ):
            cfg_enabled = False

        force_apply = self._consume_one_shot_counter(
            "edit_precision_pending", session_id
        )

        hybrid_reasoning_disabled = self._consume_flag(
            "edit_precision_hybrid_reasoning_disabled", session_id
        )
        if hybrid_reasoning_disabled:
            self._clear_flag("edit_precision_hybrid_reasoning_active", session_id)

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
                            "Suppressing hybrid reasoning for session %s (was %s)",
                            session_id,
                            hrp,
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

    def _get_tool_access_policy_service(self) -> Any | None:
        if self._app_state is None:
            return None
        try:
            from src.core.services.tool_access_policy_service import (
                ToolAccessPolicyService,
            )

            return self._app_state.get_service(ToolAccessPolicyService)
        except (AttributeError, KeyError, TypeError):
            return None

    def _inject_extra_body_metadata(
        self, request: ChatRequest, key: str, value: Any
    ) -> ChatRequest:
        extra_body_attr = getattr(request, "extra_body", None)
        extra_body: dict[str, Any] = extra_body_attr.copy() if extra_body_attr else {}
        extra_body[key] = value
        return request.model_copy(update={"extra_body": extra_body})

    def _maybe_reset_tool_choice(
        self, request: ChatRequest, policy_service: Any, filtered_tools: list[Any]
    ) -> ChatRequest:
        tool_choice = getattr(request, "tool_choice", None)
        if not (
            tool_choice and isinstance(tool_choice, dict) and "function" in tool_choice
        ):
            return request

        choice_name = tool_choice.get("function", {}).get("name")
        if not choice_name:
            return request

        tool_names = [policy_service._extract_tool_name(t) for t in filtered_tools]
        if choice_name in tool_names:
            return request

        request = request.model_copy(update={"tool_choice": "auto"})
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Reset tool_choice to 'auto' because referenced tool '%s' was filtered",
                choice_name,
            )
        return request

    def _increment_tool_filtering_telemetry(self, removed_count: int) -> None:
        try:
            from src.core.services.tool_call_reactor_service import (
                ToolCallReactorService,
            )

            reactor_service = (
                self._app_state.get_service(ToolCallReactorService)
                if self._app_state
                else None
            )
            if reactor_service and hasattr(
                reactor_service, "increment_tool_definitions_filtered"
            ):
                reactor_service.increment_tool_definitions_filtered(removed_count)
        except (AttributeError, KeyError, TypeError):
            return

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
        if not getattr(request, "tools", None):
            return request

        try:
            policy_service = self._get_tool_access_policy_service()
            if not policy_service:
                return request

            model_name = getattr(request, "model", "")
            agent = getattr(session, "agent", None)

            result = policy_service.filter_tool_definitions(
                request.tools or [], model_name, agent
            )
            filtered_tools = result.filtered_tools
            metadata = result.metadata

            # Create modified request with filtered tools if any were removed
            original_tools = request.tools or []
            if len(filtered_tools) < len(original_tools):
                request = request.model_copy(update={"tools": filtered_tools})

                # Handle tool_choice if it references a filtered tool
                request = self._maybe_reset_tool_choice(
                    request, policy_service, filtered_tools
                )

                # Log filtering action
                removed_count = len(original_tools) - len(filtered_tools)
                policy_name = metadata.policy_applied or "unknown"
                filtered_names = metadata.filtered_tool_names

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Filtered %d tool definition(s) for model %s by policy '%s': %s",
                        removed_count,
                        model_name,
                        policy_name,
                        filtered_names,
                    )

                # Increment telemetry counter in reactor service (fail-open)
                self._increment_tool_filtering_telemetry(removed_count)

                # Store metadata in extra_body for observability
                request = self._inject_extra_body_metadata(
                    request, "tool_access", metadata.model_dump()
                )

            # Create modified request with filtered tools if any were removed
            original_tools = request.tools or []
            if len(filtered_tools) < len(original_tools):
                request = request.model_copy(update={"tools": filtered_tools})

                # Handle tool_choice if it references a filtered tool
                request = self._maybe_reset_tool_choice(
                    request, policy_service, filtered_tools
                )

                # Log the filtering action
                removed_count = len(original_tools) - len(filtered_tools)
                policy_name = metadata.get("policy_applied", "unknown")
                filtered_names = metadata.get("filtered_tool_names", [])

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Filtered %d tool definition(s) for model %s by policy '%s': %s",
                        removed_count,
                        model_name,
                        policy_name,
                        filtered_names,
                    )

                # Increment telemetry counter in reactor service (fail-open)
                self._increment_tool_filtering_telemetry(removed_count)

                # Store metadata in extra_body for observability
                request = self._inject_extra_body_metadata(
                    request, "tool_access", metadata
                )

        except Exception as e:
            # Tool definition filtering is fail-open: log warning and proceed
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Tool definition filtering failed: %s", e, exc_info=True)

        return request
