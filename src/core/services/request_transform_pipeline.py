"""
Request transformation pipeline implementation.

This module provides the implementation of request transformations including:
- API key redaction
- Optional once-per-session suffix on the first user message
- Edit precision tuning
- Tool access control filtering

All transformations follow fail-open semantics and fixed ordering.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    MessageContentPartText,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.session import SessionState
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.request_processor_internal import IRequestTransformPipeline
from src.core.services.quality_verifier_steering_store import (
    consume_pending_quality_verifier_steering,
)

logger = logging.getLogger(__name__)


class RequestTransformPipeline(IRequestTransformPipeline):
    """
    Implements request transformations with fixed ordering and fail-open behavior.

    Transformation order (Requirement 9.8):
    1. API key redaction
    2. First user-message suffix append (once per session, when configured)
    3. Edit precision tuning
    4. Tool access control filtering

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
        2. First user-message suffix append (once per session, when configured)
        3. Edit precision tuning
        4. Tool filtering

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

        # Append configured suffix to first user message once per session (fail-open)
        try:
            request = await self._apply_auto_append_first_user_suffix(
                context, session, session_id, request
            )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Auto-append first user message failed; proceeding without append: %s",
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

        # Tag exact trailing continue/proceed as never-forward (fail-open)
        try:
            request = await self._apply_auto_continue_removal(
                context, session, session_id, request
            )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Auto-continue removal tagging failed; proceeding without tagging: %s",
                    e,
                    exc_info=True,
                )

        # Inject pending Quality Verifier steering (fail-open)
        try:
            request = await self._apply_quality_verifier_steering_injection(
                context, session, session_id, request
            )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Quality Verifier steering injection failed; proceeding without injection: %s",
                    e,
                    exc_info=True,
                )

        return request

    async def _apply_auto_continue_removal(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        del context, session

        if self._app_state is None:
            return request

        enabled = True
        app_config = self._get_app_config()
        try:
            session_cfg = (
                getattr(app_config, "session", None) if app_config is not None else None
            )
            enabled = bool(getattr(session_cfg, "auto_continue_removal_enabled", True))
        except Exception:
            enabled = True
        if not enabled:
            return request

        messages = list(request.messages or [])
        if not messages:
            return request

        last_message = messages[-1]
        if getattr(last_message, "role", None) != "user":
            return request

        content = getattr(last_message, "content", None)
        if not isinstance(content, str):
            return request

        if content.strip().lower() not in {"continue", "proceed"}:
            return request

        try:
            from typing import cast

            from src.core.domain.non_forwardable import NonForwardableTagScope
            from src.core.interfaces.non_forwardable_interface import (
                INonForwardableMessageIdentityService,
                INonForwardableMessageRegistry,
            )

            registry = self._app_state.get_service(
                cast(Any, INonForwardableMessageRegistry)
            )
            identity_service = self._app_state.get_service(
                cast(Any, INonForwardableMessageIdentityService)
            )
            if registry is None or identity_service is None:
                return request

            identity = identity_service.compute_identity(last_message)
            await registry.tag_identities(
                session_id=session_id,
                identities=[identity],
                scope=NonForwardableTagScope.NEVER_FORWARD,
                reason="auto_continue_removal",
            )
        except Exception:
            return request

        return request

    @staticmethod
    def _join_text_with_suffix(base: str, suffix: str) -> str:
        if not base:
            return suffix
        if base.endswith("\n") or suffix.startswith("\n"):
            return f"{base}{suffix}"
        return f"{base}\n{suffix}"

    def _append_suffix_to_message_content(self, content: Any, suffix: str) -> Any:
        if isinstance(content, str):
            return self._join_text_with_suffix(content, suffix)
        if isinstance(content, list):
            out: list[Any] = list(content)
            if not out:
                return [MessageContentPartText(text=suffix)]
            last = out[-1]
            if isinstance(last, MessageContentPartText):
                joined = self._join_text_with_suffix(last.text or "", suffix)
                out[-1] = last.model_copy(update={"text": joined})
                return out
            if isinstance(last, dict) and last.get("type") == "text":
                d = dict(last)
                d["text"] = self._join_text_with_suffix(
                    str(d.get("text") or ""), suffix
                )
                out[-1] = d
                return out
            out.append(MessageContentPartText(text=suffix))
            return out
        if content is None:
            return suffix
        return self._join_text_with_suffix(str(content), suffix)

    def _session_state_as_session_state(self, state_obj: object) -> SessionState | None:
        if isinstance(state_obj, SessionState):
            return state_obj
        inner = getattr(state_obj, "_state", None)
        if isinstance(inner, SessionState):
            return inner
        return None

    async def _apply_auto_append_first_user_suffix(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        if self._app_state is None:
            return request

        if isinstance(
            getattr(context, "extensions", None), dict
        ) and context.extensions.get("auxiliary_request"):
            return request

        resolved_app_config = self._get_resolved_app_config()
        suffix_raw = (
            getattr(resolved_app_config, "auto_append_first_prompt_text", None)
            if resolved_app_config is not None
            else None
        )
        suffix = str(suffix_raw).strip() if suffix_raw is not None else ""
        if not suffix:
            return request

        state_obj = getattr(session, "state", None)
        if state_obj is None:
            return request
        if bool(getattr(state_obj, "auto_append_first_prompt_applied", False)):
            return request

        messages = list(request.messages or [])
        first_user_idx: int | None = None
        for i, msg in enumerate(messages):
            role = getattr(msg, "role", None)
            if role == "user":
                first_user_idx = i
                break
        if first_user_idx is None:
            return request

        msg = messages[first_user_idx]
        new_content = self._append_suffix_to_message_content(
            getattr(msg, "content", None), suffix
        )
        updated_msg = msg.model_copy(update={"content": new_content})
        new_messages = [
            *messages[:first_user_idx],
            updated_msg,
            *messages[first_user_idx + 1 :],
        ]
        request = request.model_copy(update={"messages": new_messages})

        persist_ok = False
        try:
            base_state = self._session_state_as_session_state(state_obj)
            update_fn = getattr(session, "update_state", None)
            if base_state is not None and callable(update_fn):
                update_fn(base_state.with_auto_append_first_prompt_applied(True))
                persist_ok = True
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Auto-append first prompt: merged suffix into outbound request but "
                    "failed to persist session flag (may append again on next request); "
                    "session_id=%s",
                    session_id,
                    exc_info=True,
                )

        if logger.isEnabledFor(logging.INFO):
            note = "" if persist_ok else " [session flag not persisted]"
            logger.info(
                "Auto-append first prompt: merged suffix into first user message "
                "(session_id=%s, user_message_index=%d, suffix_chars=%d)%s",
                session_id,
                first_user_idx,
                len(suffix),
                note,
            )

        return request

    async def _apply_quality_verifier_steering_injection(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        if self._app_state is None:
            return request

        # Use Quality Verifier effective session id when present (stable across B2BUA rotations).
        qv_session_key_raw = None
        try:
            qv_session_key_raw = context.extensions.get(
                "quality_verifier_effective_session_id"
            )
        except Exception:
            qv_session_key_raw = None

        qv_session_key = str(qv_session_key_raw or session_id or "").strip()
        if not qv_session_key:
            return request

        steering_msg = consume_pending_quality_verifier_steering(
            app_state=self._app_state,
            session_key=qv_session_key,
        )
        if not steering_msg:
            return request

        from src.core.services.quality_verifier_steering_messages import (
            render_quality_verifier_steering_system_content,
        )

        rendered = render_quality_verifier_steering_system_content(steering_msg)
        if not rendered.strip():
            return request

        injection_start_index = len(request.messages or [])
        steering_message = ChatMessage(role="system", content=rendered)
        new_messages = [*list(request.messages or []), steering_message]
        request = request.model_copy(update={"messages": new_messages})

        # Set injection boundary in RequestContext for non-forwardable enforcement.
        try:
            from src.core.services.non_forwardable_message_enforcer import (
                PROXY_INJECTED_MESSAGES_START_INDEX_KEY,
            )

            existing = context.extensions.get(PROXY_INJECTED_MESSAGES_START_INDEX_KEY)
            if isinstance(existing, int):
                context.extensions[PROXY_INJECTED_MESSAGES_START_INDEX_KEY] = min(
                    existing, injection_start_index
                )
            else:
                context.extensions[PROXY_INJECTED_MESSAGES_START_INDEX_KEY] = (
                    injection_start_index
                )
        except Exception:
            # Soft fail: steering is best-effort.
            pass

        # Tag as client-history-only (best effort; failure should not break requests).
        try:
            from typing import cast

            from src.core.domain.non_forwardable import NonForwardableTagScope
            from src.core.interfaces.non_forwardable_interface import (
                INonForwardableMessageIdentityService,
                INonForwardableMessageRegistry,
            )

            registry = self._app_state.get_service(
                cast(Any, INonForwardableMessageRegistry)
            )
            identity_service = self._app_state.get_service(
                cast(Any, INonForwardableMessageIdentityService)
            )
            if registry is not None and identity_service is not None:
                identity = identity_service.compute_identity(steering_message)
                await registry.tag_identities(
                    session_id=session_id,
                    identities=[identity],
                    scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
                    reason="quality_verifier_steering",
                )
        except Exception:
            pass

        return request

    def _get_app_config(self) -> Any | None:
        if self._app_state is None:
            return None
        try:
            return self._app_state.get_setting("app_config")
        except (AttributeError, KeyError, TypeError):
            return None

    def _get_resolved_app_config(self) -> Any | None:
        if self._app_state is None:
            return None

        try:
            resolved = self._app_state.get_setting("resolved_app_config")
        except (AttributeError, KeyError, TypeError):
            resolved = None

        if resolved is not None:
            return resolved

        app_config = self._get_app_config()
        if app_config is None:
            return None

        try:
            from src.core.config.auto_append_first_prompt_hydration import (
                resolve_app_config,
            )

            return resolve_app_config(app_config)
        except Exception:
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
        session_override: object | None = None

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

    def _get_command_prefix(self, session: object) -> str | None:
        """Get command prefix from session override or app_state.

        Args:
            session: Session object

        Returns:
            Command prefix string or None
        """
        # Check session override first
        try:
            session_state = self._get_session_state(session)
            if session_state is not None:
                session_prefix = getattr(session_state, "command_prefix_override", None)
                if isinstance(session_prefix, str):
                    return session_prefix
        except (AttributeError, TypeError) as e:
            # Expected exceptions when session state is unavailable or has wrong type
            # Continue to app_state fallback
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Could not get command prefix from session state: %s",
                    e,
                    exc_info=True,
                )
        except Exception as e:
            # Unexpected errors - log with full context for visibility
            # Still continue to app_state fallback to preserve fail-open behavior
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error getting command prefix from session state: %s",
                    e,
                    exc_info=True,
                )

        # Fall back to app_state
        if self._app_state is not None:
            try:
                return self._app_state.get_command_prefix()
            except (AttributeError, TypeError) as e:
                # Expected exceptions when get_command_prefix is unavailable or returns wrong type
                # Fall back to None
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Could not get command prefix from app_state: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected errors - log with full context for visibility
                # Still fall back to None to preserve fail-open behavior
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error getting command prefix from app_state: %s",
                        e,
                        exc_info=True,
                    )

        return None

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

        # Create and apply redaction middleware
        redaction = RedactionMiddleware(api_keys=api_keys)
        redaction_context: dict[str, JsonValue] = {
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
                    exc_info=True,
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
                target_top_k=cfg_target_top_k,
                force_apply=force_apply,
                temperatures_config=temperatures_config,
            )

            request = await edit_precision.process(
                request,
                {
                    "session_id": session_id,
                    "agent": getattr(session, "agent", None),
                },
            )

            if hybrid_reasoning_disabled:
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
                # Intentionally silent control flow: AttributeError/TypeError indicates config attribute not available
                with contextlib.suppress(AttributeError, TypeError):
                    hrp = getattr(app_config, "hybrid_reasoning_probability", 0.5)
                    extra_body["_temp_hybrid_reasoning_probability"] = 0.0
                    # Also set metadata for observability
                    meta = extra_body.get("_edit_precision_meta")
                    if meta is None:
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
