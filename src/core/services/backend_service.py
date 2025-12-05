from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import re
import time
from collections import OrderedDict
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    BackendError,
    InvalidRequestError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.config.config_loader import _collect_api_keys
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.failover_service import FailoverService
from src.rate_limit import parse_retry_delay

logger = logging.getLogger(__name__)


class BackendService(IBackendService):
    """Service for interacting with LLM backends.

    This service manages backend selection, rate limiting, and failover.
    """

    def __init__(
        self,
        factory: BackendFactory,
        rate_limiter: IRateLimiter,
        config: IConfig,
        session_service: ISessionService,  # Add session_service
        app_state: IApplicationState,
        backend_config_provider: IBackendConfigProvider | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
        failover_strategy: IFailoverStrategy | None = None,
        failover_coordinator: IFailoverCoordinator | None = None,
        wire_capture: IWireCapture | None = None,
        routing_service: BackendRoutingService | None = None,
    ):
        """Initialize the backend service.

        Args:
        Args:
            factory: The factory for creating backends
            rate_limiter: The rate limiter for API calls
            config: Application configuration
            session_service: The session service
            app_state: Application state service
            backend_configs: Configurations for backends
            failover_routes: Routes for backend failover
            routing_service: Service for instance routing and discovery
        """
        self._factory = factory
        self._rate_limiter = rate_limiter
        self._config = config
        self._session_service = session_service  # Store session_service
        self._app_state = app_state
        self._backend_config_provider: IBackendConfigProvider | None = (
            backend_config_provider
        )
        self._backend_configs: dict[str, Any] = {}
        self._failover_routes: dict[str, dict[str, Any]] = failover_routes or {}
        self._failover_strategy: IFailoverStrategy | None = failover_strategy
        self._routing_service = routing_service
        self._backends: dict[str, LLMBackend] = {}
        self._per_session_backends: OrderedDict[str, LLMBackend] = OrderedDict()
        self._per_session_backend_limit = self._resolve_per_session_backend_limit(
            config
        )
        from src.core.config.app_config import AppConfig
        from src.core.services.failover_coordinator import FailoverCoordinator

        # Ensure config is properly typed for type checking
        _typed_config = cast(AppConfig, config)

        self._failover_service: FailoverService = FailoverService(
            failover_routes=self._failover_routes
        )
        if failover_coordinator is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "BackendService: No IFailoverCoordinator provided; using default FailoverCoordinator. "
                    "Prefer injecting an IFailoverCoordinator via DI to adhere to DIP."
                )
            self._failover_coordinator: IFailoverCoordinator = FailoverCoordinator(
                self._failover_service
            )
        else:
            self._failover_coordinator = failover_coordinator
        # Use injected backend config provider or create default
        if backend_config_provider is not None:
            self._backend_config_service = backend_config_provider
        else:
            # Fallback for backward compatibility - create with app_config
            from src.core.config.app_config import AppConfig
            from src.core.services.backend_config_provider import BackendConfigProvider

            if isinstance(config, AppConfig):
                self._backend_config_service = BackendConfigProvider(config)
            else:
                # Create a minimal AppConfig for backward compatibility
                self._backend_config_service = BackendConfigProvider(AppConfig())
        # Assign wire_capture if provided
        self._wire_capture: IWireCapture | None = wire_capture

    def _resolve_per_session_backend_limit(self, config: IConfig) -> int:
        """Determine the cache size for per-session backends."""
        default_limit = 32
        try:
            session_config = getattr(config, "session", None)
            candidate = getattr(
                session_config, "max_per_session_backends", default_limit
            )
            if isinstance(candidate, int) and candidate > 0:
                return candidate
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Falling back to default per-session backend limit: %s",
                    exc,
                    exc_info=True,
                )
        return default_limit

    @staticmethod
    def _is_per_session_cache_key(cache_key: str, backend_type: str) -> bool:
        """Return True when the cache key maps to a session-scoped backend."""
        return cache_key != backend_type

    async def _enforce_per_session_backend_limit(self) -> None:
        """Ensure the per-session backend cache does not grow without bound."""
        limit = max(self._per_session_backend_limit, 1)
        while len(self._per_session_backends) > limit:
            evicted_key, evicted_backend = self._per_session_backends.popitem(
                last=False
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicting per-session backend %s due to cache limit %d",
                    evicted_key,
                    limit,
                )
            await self._shutdown_backend(evicted_backend)

    async def _shutdown_backend(self, backend: LLMBackend) -> None:
        """Shutdown the backend if it has a shutdown method."""
        shutdown = getattr(backend, "shutdown", None)
        if shutdown is None:
            return

        try:
            if inspect.iscoroutinefunction(shutdown):  # type: ignore[arg-type]
                await shutdown()
            else:
                shutdown()
        except Exception:
            logger.exception("Error shutting down backend %s", backend.backend_type)

    def _apply_model_aliases(self, model: str) -> str:
        """Applies the first matching model alias rule to the model name.

        Args:
            model: The original model name

        Returns:
            The rewritten model name, or the original if no rules match
        """
        from src.core.config.app_config import AppConfig

        app_config = cast(AppConfig, self._config)

        # Handle case where config might be a Mock object (in tests)
        try:
            model_aliases = getattr(app_config, "model_aliases", [])
            if not model_aliases:
                return model

            # Check if model_aliases is iterable (not a Mock)
            iter(model_aliases)
        except (AttributeError, TypeError):
            # If model_aliases is not iterable (e.g., Mock object), return original model
            return model

        for alias in model_aliases:
            try:
                # Handle case where alias might be a Mock object
                pattern = getattr(alias, "pattern", None)
                replacement = getattr(alias, "replacement", None)

                if not pattern or not replacement:
                    continue

                # Anchor patterns to the start of the string by default to
                # preserve the historical behaviour of ``re.match`` while
                # still honoring any explicit anchors provided in the
                # configuration.
                match = re.match(pattern, model)
                if match:
                    # Use match.expand to honor capture groups regardless of match span
                    new_model = match.expand(replacement)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Applied model alias: '{model}' -> '{new_model}'")
                    return new_model
            except (re.error, AttributeError, TypeError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Invalid regex pattern in model alias or mock object: {e}"
                    )
                continue

        return model

    @staticmethod
    def _stream_as_sse_bytes(
        it: Any,
    ) -> Any:
        """Adapt a stream of domain chunks into SSE-encoded bytes.

        Accepts an async iterator that may yield ProcessedResponse, dict, str, or bytes
        and produces an async iterator of bytes suitable for wire capture and direct
        transport to clients.
        """
        import json

        from src.core.interfaces.response_processor_interface import ProcessedResponse

        def _chunk_signals_done(content: Any, metadata: dict[str, Any] | None) -> bool:
            if isinstance(content, bytes | bytearray):
                text = content.decode("utf-8", errors="ignore").strip()
                if text == "[DONE]" or text.startswith("data: [DONE]"):
                    return True
                if text == '["DONE"]' or text.startswith('data: ["DONE"]'):
                    return True
            elif isinstance(content, str):
                stripped = content.strip()
                if stripped == "[DONE]" or stripped.startswith("data: [DONE]"):
                    return True
                if stripped == '["DONE"]' or stripped.startswith('data: ["DONE"]'):
                    return True

            if metadata and metadata.get("finish_reason"):
                if content is None or content == "":
                    return True
                if isinstance(content, dict):
                    choices = content.get("choices") or []
                    if choices:
                        delta = (
                            choices[0].get("delta")
                            if isinstance(choices[0], dict)
                            else {}
                        )
                        if not delta or all(
                            not delta.get(key)
                            for key in (
                                "content",
                                "tool_calls",
                                "reasoning_content",
                                "reasoning",
                            )
                        ):
                            return True

            if isinstance(content, dict):
                content_metadata = content.get("metadata")
                if isinstance(content_metadata, dict) and content_metadata.get(
                    "finish_reason"
                ):
                    return True
                choices = content.get("choices")
                if isinstance(choices, list):
                    for choice in choices:
                        if isinstance(choice, dict) and choice.get("finish_reason"):
                            return True

            return False

        def _format_as_sse(content: Any) -> bytes:
            """Normalize arbitrary content to SSE-framed bytes."""
            if isinstance(content, bytes | bytearray):
                stripped_bytes = bytes(content).strip()
                if stripped_bytes.startswith(b"data:"):
                    return bytes(content)
                if stripped_bytes in (b"[DONE]", b'["DONE"]'):
                    return b"data: [DONE]\n\n"
                text_val = content.decode("utf-8", errors="replace")
                return f"data: {text_val}\n\n".encode()

            if isinstance(content, str):
                stripped_text = content.strip()
                if stripped_text.startswith("data:"):
                    return content.encode("utf-8")
                if stripped_text in ("[DONE]", '["DONE"]'):
                    return b"data: [DONE]\n\n"
                return f"data: {content}\n\n".encode()

            if isinstance(content, dict):
                return f"data: {json.dumps(content)}\n\n".encode()

            return f"data: {content}\n\n".encode()

        async def _adapter() -> Any:
            done_sent = False
            async for chunk in it:  # type: ignore
                content = (
                    chunk.content if isinstance(chunk, ProcessedResponse) else chunk
                )
                metadata = (
                    chunk.metadata if isinstance(chunk, ProcessedResponse) else {}
                )

                # CRITICAL: Check for StopChunkWithUsage and convert to SSE properly
                # Use StreamingContent.to_bytes() which knows how to handle it correctly
                from src.core.ports.streaming_contracts import (
                    StopChunkWithUsage,
                    StreamingContent,
                )

                if isinstance(content, StopChunkWithUsage):
                    # Create StreamingContent and use its to_bytes() method
                    # which properly serializes StopChunkWithUsage with usage at top level
                    streaming_content = StreamingContent(
                        content=content,
                        is_done=True,
                        metadata=metadata,
                        usage=content.get("usage"),
                    )
                    yield streaming_content.to_bytes()
                    done_sent = True
                else:
                    yield _format_as_sse(content)

                if _chunk_signals_done(content, metadata):
                    done_sent = True
                    if isinstance(content, bytes | bytearray | str):
                        text_str = (
                            content.decode("utf-8", errors="ignore")
                            if isinstance(content, bytes | bytearray)
                            else content
                        )
                        stripped = text_str.strip()
                        if stripped in ("[DONE]", '["DONE"]'):
                            break
                        if stripped.startswith(("data: [DONE]", 'data: ["DONE"]')):
                            break
                    yield b"data: [DONE]\n\n"
                    break

            if not done_sent:
                yield b"data: [DONE]\n\n"

        return _adapter()

    def _normalize_provider_exception(
        self, exc: Exception, backend_type: str
    ) -> Exception:
        """Translate provider exceptions into domain-specific errors when possible."""
        if isinstance(exc, BackendError | RateLimitExceededError):
            return exc

        if isinstance(exc, HTTPException) and getattr(exc, "status_code", None) == 429:
            detail_payload = getattr(exc, "detail", None)
            message: str | None = None

            if isinstance(detail_payload, dict):
                message = detail_payload.get("message")
                if not message:
                    error_block = detail_payload.get("error")
                    if isinstance(error_block, dict):
                        message = error_block.get("message")
            if not message and detail_payload is not None:
                message = str(detail_payload)
            if not message:
                message = "Rate limit exceeded"

            headers = getattr(exc, "headers", None)
            retry_after_seconds: float | None = None
            if isinstance(headers, dict):
                retry_after_raw = headers.get("Retry-After") or headers.get(
                    "retry-after"
                )
                if retry_after_raw is not None:
                    try:
                        retry_after_seconds = float(retry_after_raw)
                    except (TypeError, ValueError):
                        retry_after_seconds = None

            reset_at = (
                time.time() + retry_after_seconds
                if isinstance(retry_after_seconds, int | float)
                else None
            )

            if isinstance(
                detail_payload,
                dict | list | tuple | str | int | float | bool | type(None),
            ):
                serialized_detail = detail_payload
            else:
                serialized_detail = str(detail_payload)

            details: dict[str, Any] = {
                "backend": backend_type,
                "status_code": 429,
                "detail": serialized_detail,
            }
            if isinstance(headers, dict) and headers:
                details["headers"] = dict(headers)

            return RateLimitExceededError(
                message=message,
                details=details,
                reset_at=reset_at,
            )

        if isinstance(exc, HTTPException):
            status_code = getattr(exc, "status_code", None)
            detail_payload = getattr(exc, "detail", None)

            http_message: str | None = None
            if isinstance(detail_payload, dict):
                http_message = detail_payload.get("message") or detail_payload.get(
                    "error", {}
                ).get(
                    "message"
                )  # type: ignore[index]
            elif detail_payload is not None:
                http_message = str(detail_payload)

            http_message = http_message or "Backend request failed"
            http_details: dict[str, Any] = {
                "backend": backend_type,
                "detail": detail_payload,
            }
            if isinstance(status_code, int):
                http_details["status_code"] = status_code

            if isinstance(status_code, int) and 400 <= status_code < 500:
                return InvalidRequestError(
                    message=http_message,
                    details=http_details,
                )

            return BackendError(
                message=http_message,
                backend_name=backend_type,
                status_code=status_code if isinstance(status_code, int) else 502,
                details=http_details,
            )

        return exc

    def _resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest,
    ) -> str:
        """Resolve a stable identifier for streaming capture and buffering."""
        if session_id:
            return str(session_id)

        request_session = getattr(request, "session_id", None)
        if request_session:
            return str(request_session)

        try:
            extra_body = getattr(request, "extra_body", None)
            if isinstance(extra_body, dict):
                extra_session = extra_body.get("session_id")
                if extra_session:
                    return str(extra_session)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to read session_id from request.extra_body", exc_info=True
                )

        context_request_id = getattr(context, "request_id", None) if context else None
        if context_request_id:
            return str(context_request_id)

        return uuid4().hex

    def _apply_reasoning_config(
        self, request: ChatRequest, session: Any
    ) -> ChatRequest:
        """Apply reasoning configuration from session to the request.

        Args:
            request: The chat completion request
            session: The session containing reasoning configuration



        Returns:
            The updated request with reasoning configuration applied
        """
        try:
            # Get reasoning configuration from session
            reasoning_config = getattr(session, "get_reasoning_mode", lambda: None)()
            if reasoning_config is None:
                return request

            # Collect field updates to avoid mutating frozen Pydantic models
            updates: dict[str, Any] = {}

            extra_body_attr = getattr(request, "extra_body", None)
            edit_precision_active = False
            if isinstance(extra_body_attr, dict):
                try:
                    edit_precision_active = bool(
                        extra_body_attr.get("_edit_precision_mode")
                    )
                except Exception:
                    edit_precision_active = False
            else:
                edit_precision_active = False

            def _apply_numeric_update(field: str, value: Any) -> None:
                # Helper to apply numeric overrides while respecting edit precision when active.
                if value is None:
                    return
                numeric_value: Any = value
                try:
                    if field in {"temperature", "top_p"}:
                        numeric_value = float(value)
                    elif field == "top_k":
                        numeric_value = int(value)
                except (TypeError, ValueError):
                    numeric_value = value

                if edit_precision_active and field in {"temperature", "top_p", "top_k"}:
                    current_value = getattr(request, field, None)
                    try:
                        if current_value is not None:
                            if field in {"temperature", "top_p"}:
                                numeric_value = min(
                                    float(current_value), float(numeric_value)
                                )
                            else:
                                numeric_value = min(
                                    int(current_value), int(numeric_value)
                                )
                    except (TypeError, ValueError):
                        pass

                updates[field] = numeric_value

            # Apply temperature if set
            if (
                hasattr(reasoning_config, "temperature")
                and reasoning_config.temperature is not None
            ):
                _apply_numeric_update("temperature", reasoning_config.temperature)

            # Apply top_p if set (for OpenAI-compatible backends)
            if (
                hasattr(reasoning_config, "top_p")
                and reasoning_config.top_p is not None
            ):
                _apply_numeric_update("top_p", reasoning_config.top_p)

            if (
                hasattr(reasoning_config, "top_k")
                and reasoning_config.top_k is not None
            ):
                _apply_numeric_update("top_k", reasoning_config.top_k)

            # Apply reasoning_effort if set (for OpenAI reasoning models)
            if (
                hasattr(reasoning_config, "reasoning_effort")
                and reasoning_config.reasoning_effort is not None
            ):
                updates["reasoning_effort"] = reasoning_config.reasoning_effort

            # Apply thinking_budget if set (for Gemini models)
            if (
                hasattr(reasoning_config, "thinking_budget")
                and reasoning_config.thinking_budget is not None
            ):
                updates["thinking_budget"] = reasoning_config.thinking_budget

            # Apply reasoning_config if set
            if (
                hasattr(reasoning_config, "reasoning_config")
                and reasoning_config.reasoning_config is not None
            ):
                updates["reasoning"] = reasoning_config.reasoning_config

            # Apply gemini_generation_config if set
            if (
                hasattr(reasoning_config, "gemini_generation_config")
                and reasoning_config.gemini_generation_config is not None
            ):
                updates["generation_config"] = reasoning_config.gemini_generation_config

            # Apply planning-phase overrides if active
            try:
                planning_cfg = getattr(session.state, "planning_phase_config", None)
                if planning_cfg and bool(getattr(planning_cfg, "enabled", False)):
                    overrides = getattr(planning_cfg, "overrides", None)
                    # overrides may be dict (from AppConfig) or a VO instance (not expected here)
                    if isinstance(overrides, dict):
                        if overrides.get("temperature") is not None:
                            _apply_numeric_update(
                                "temperature", overrides.get("temperature")
                            )
                        if overrides.get("top_p") is not None:
                            _apply_numeric_update("top_p", overrides.get("top_p"))
                        if overrides.get("top_k") is not None:
                            _apply_numeric_update("top_k", overrides.get("top_k"))
                        if overrides.get("reasoning_effort") is not None:
                            updates["reasoning_effort"] = overrides.get(
                                "reasoning_effort"
                            )
                        if overrides.get("thinking_budget") is not None:
                            updates["thinking_budget"] = overrides.get(
                                "thinking_budget"
                            )
                        if overrides.get("reasoning") is not None:
                            updates["reasoning"] = overrides.get("reasoning")
                        if overrides.get("generation_config") is not None:
                            updates["generation_config"] = overrides.get(
                                "generation_config"
                            )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Planning-phase overrides application failed", exc_info=True
                    )

            if updates:
                request = request.model_copy(update=updates)

            # Apply prompt prefix and suffix if available in reasoning config
            # Check if reasoning_config has user_prompt_prefix or user_prompt_suffix attributes
            prefix = getattr(reasoning_config, "user_prompt_prefix", None)
            suffix = getattr(reasoning_config, "user_prompt_suffix", None)

            if (
                (
                    (prefix is not None and prefix != "")
                    or (suffix is not None and suffix != "")
                )
                and hasattr(request, "messages")
                and request.messages
            ):
                modified_messages = []
                for message in request.messages:
                    # Only modify user messages
                    if getattr(message, "role", "") == "user":
                        # Handle both string and list content
                        content = getattr(message, "content", None)
                        if isinstance(content, str):
                            new_content = ""
                            if prefix is not None:
                                new_content += prefix
                            new_content += content
                            if suffix is not None:
                                new_content += suffix
                            # Create a new message with modified content
                            modified_message = message.model_copy(
                                update={"content": new_content}
                            )
                            modified_messages.append(modified_message)
                        elif isinstance(content, list):
                            # For multimodal content, modify the first text part
                            modified_content = []
                            for part in content:
                                if (
                                    hasattr(part, "type")
                                    and part.type == "text"
                                    and hasattr(part, "text")
                                ):
                                    # Modify the text content
                                    new_text = ""
                                    if prefix is not None:
                                        new_text += prefix
                                    new_text += part.text
                                    if suffix is not None:
                                        new_text += suffix
                                    modified_part = part.model_copy(
                                        update={"text": new_text}
                                    )
                                    modified_content.append(modified_part)
                                else:
                                    modified_content.append(part)
                            # If no text part was found, add prefix/suffix as a new text part
                            if not any(
                                hasattr(part, "type") and part.type == "text"
                                for part in content
                            ):
                                if prefix is not None:
                                    modified_content.insert(
                                        0, {"type": "text", "text": prefix}
                                    )
                                if suffix is not None:
                                    modified_content.append(
                                        {"type": "text", "text": suffix}
                                    )
                            modified_message = message.model_copy(
                                update={"content": modified_content}
                            )
                            modified_messages.append(modified_message)
                        else:
                            modified_messages.append(message)
                    else:
                        modified_messages.append(message)
                # Update the request with modified messages
                request = request.model_copy(update={"messages": modified_messages})

        except Exception:
            # Log but continue if reasoning config application fails
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to apply reasoning config", exc_info=True)

        return request

    def _apply_uri_parameters(
        self,
        request: ChatRequest,
        uri_params: dict[str, Any],
        backend_type: str,
        session: Any | None = None,
    ) -> ChatRequest:
        """Apply URI parameters to request using parameter resolution service.

        This method resolves parameters from multiple sources with precedence:
        1. Session commands (highest priority)
        2. URI parameters
        3. Request headers
        4. Configuration file (lowest priority)

        Args:
            request: The chat completion request
            uri_params: Parameters extracted from model string URI
            backend_type: Backend type for logging context
            session: Session object (for session command overrides)

        Returns:
            The updated request with resolved parameters applied
        """
        # Early return if no URI parameters to apply
        if not uri_params:
            return request

        try:

            def _coerce_parameter(name: str, value: Any) -> Any | None:
                """Coerce parameter values into canonical types."""

                if value is None:
                    return None

                try:
                    if name in {"temperature", "top_p"}:
                        return float(value)
                    if name == "top_k":
                        if isinstance(value, float):
                            if not value.is_integer():
                                raise ValueError(f"{value!r} is not an integer value")
                            return int(value)
                        if isinstance(value, int):
                            return value

                        string_value = str(value).strip()
                        float_value = float(string_value)
                        if not float_value.is_integer():
                            raise ValueError(f"{value!r} is not an integer value")
                        return int(float_value)
                    if name == "reasoning_effort":
                        return str(value)
                except (TypeError, ValueError) as exc:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Failed to coerce raw value {value!r} to type for {name}: {exc}"
                        )
                    return None

                return value

            def _assign_param(target: dict[str, Any], name: str, value: Any) -> None:
                coerced = _coerce_parameter(name, value)
                if coerced is not None:
                    target[name] = coerced

            def _assign_from_obj(target: dict[str, Any], obj: Any, name: str) -> None:
                if obj is None:
                    return
                value = getattr(obj, name, None)
                if value is not None:
                    _assign_param(target, name, value)

            # Import validation and resolution services
            from src.core.services.parameter_resolution_service import (
                ParameterResolutionService,
            )
            from src.core.services.uri_parameter_validator import (
                URIParameterValidator,
            )

            # Validate and normalize URI parameters
            try:
                validator = URIParameterValidator()
                normalized_uri_params, validation_errors = (
                    validator.validate_and_normalize(uri_params)
                )

                # Log validation errors if any
                if validation_errors and logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"URI parameter validation errors for {backend_type}: {', '.join(validation_errors)}. "
                        f"Invalid parameters will be excluded from the request."
                    )
            except Exception as validation_error:
                # If validation itself fails, log error and continue without URI params
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to validate URI parameters for {backend_type}: {validation_error}. "
                        f"Continuing without URI parameters."
                    )
                return request

            # Extract parameters from other sources
            # 1. Config parameters (from backend config or app config)
            config_params: dict[str, Any] = {}
            try:
                from src.core.config.app_config import AppConfig

                app_config = cast(AppConfig, self._config)
                backend_config = app_config.backends.get(backend_type)
                if backend_config:
                    for param_name in (
                        "temperature",
                        "top_p",
                        "top_k",
                        "reasoning_effort",
                    ):
                        _assign_from_obj(config_params, backend_config, param_name)

                    extra_cfg = getattr(backend_config, "extra", None)
                    if isinstance(extra_cfg, dict):
                        for param_name in (
                            "temperature",
                            "top_p",
                            "top_k",
                            "reasoning_effort",
                        ):
                            if param_name in extra_cfg:
                                _assign_param(
                                    config_params, param_name, extra_cfg[param_name]
                                )
            except Exception as config_error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Failed to extract config parameters for {backend_type}: {config_error}",
                        exc_info=True,
                    )

            # 2. Header parameters (from request extra_body or headers)
            header_params: dict[str, Any] = {}
            try:
                if request.extra_body:
                    # Check for parameters in extra_body that might come from headers
                    for param_name in (
                        "temperature",
                        "top_p",
                        "top_k",
                        "reasoning_effort",
                    ):
                        if param_name in request.extra_body:
                            _assign_param(
                                header_params,
                                param_name,
                                request.extra_body[param_name],
                            )

                # Also check top-level request fields
                for param_name in (
                    "temperature",
                    "top_p",
                    "top_k",
                    "reasoning_effort",
                ):
                    value = getattr(request, param_name, None)
                    if value is not None:
                        _assign_param(header_params, param_name, value)
            except Exception as header_error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Failed to extract header parameters for {backend_type}: {header_error}",
                        exc_info=True,
                    )

            # 3. Session parameters (from session reasoning config)
            session_params: dict[str, Any] = {}
            if session is not None:
                try:
                    reasoning_config = getattr(
                        session, "get_reasoning_mode", lambda: None
                    )()
                    if reasoning_config is not None:
                        for param_name in (
                            "temperature",
                            "top_p",
                            "top_k",
                            "reasoning_effort",
                        ):
                            _assign_from_obj(
                                session_params, reasoning_config, param_name
                            )
                except Exception as session_error:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Failed to extract session parameters for {backend_type}: {session_error}",
                            exc_info=True,
                        )

            # Apply one-shot overrides from edit-precision middleware as session-level overrides
            try:
                extra_body = getattr(request, "extra_body", None)
                if isinstance(extra_body, dict) and extra_body.get(
                    "_edit_precision_mode"
                ):
                    if getattr(request, "temperature", None) is not None:
                        session_params["temperature"] = request.temperature
                    if getattr(request, "top_p", None) is not None:
                        session_params["top_p"] = request.top_p
                    if getattr(request, "top_k", None) is not None:
                        session_params["top_k"] = request.top_k
            except Exception as edit_precision_error:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to apply edit-precision overrides to session parameters: %s",
                        edit_precision_error,
                        exc_info=True,
                    )

            # Resolve parameters using ParameterResolutionService
            try:
                resolution_service = ParameterResolutionService()
                resolved = resolution_service.resolve_parameters(
                    uri_params=normalized_uri_params,
                    header_params=header_params,
                    config_params=config_params,
                    session_params=session_params,
                    backend=backend_type,
                )
            except Exception as resolution_error:
                # If parameter resolution fails, log error and continue without URI params
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to resolve parameters for {backend_type}: {resolution_error}. "
                        f"Continuing without URI parameters."
                    )
                return request

            # Apply resolved parameters to request
            try:
                resolved_params = resolved.to_dict()
                if resolved_params:
                    # Update request with resolved parameters
                    updates: dict[str, Any] = {}

                    # Apply temperature
                    if "temperature" in resolved_params:
                        updates["temperature"] = resolved_params["temperature"]

                    if "top_p" in resolved_params:
                        updates["top_p"] = resolved_params["top_p"]

                    if "top_k" in resolved_params:
                        updates["top_k"] = resolved_params["top_k"]

                    # Apply reasoning_effort
                    if "reasoning_effort" in resolved_params:
                        updates["reasoning_effort"] = resolved_params[
                            "reasoning_effort"
                        ]

                    # Also update extra_body to ensure parameters are passed through
                    if request.extra_body:
                        extra_body = dict(request.extra_body)
                    else:
                        extra_body = {}

                    extra_body.update(resolved_params)
                    updates["extra_body"] = extra_body

                    # Apply updates to request
                    request = request.model_copy(update=updates)

                    # Emit debug logs showing effective parameter values and sources
                    debug_info = resolved.get_debug_info()
                    if debug_info and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Applied URI parameters to request for {backend_type}: {debug_info}"
                        )
            except Exception as apply_error:
                # If applying parameters fails, log error and return original request
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failed to apply resolved parameters to request for {backend_type}: {apply_error}. "
                        f"Continuing with original request."
                    )
                return request

        except Exception as outer_error:
            # Catch-all for any unexpected errors in URI parameter application
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error applying URI parameters to request for {backend_type}: {outer_error}. "
                    f"Continuing with original request.",
                    exc_info=True,
                )

        return request

    def _get_failover_plan(
        self, model: str, backend_type: str
    ) -> list[tuple[str, str]]:
        """Return an ordered plan of (backend, model) attempts.

        Uses the extracted strategy when enabled and available, otherwise falls
        back to coordinator-provided attempts.

        When circuit breaker is enabled, filters out backends whose API endpoints
        are unhealthy.
        """
        use_strategy: bool = False
        try:
            use_strategy = self._app_state.get_use_failover_strategy()
        except (AttributeError, KeyError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not get failover strategy from app state: {e}",
                    exc_info=True,
                )
            use_strategy = False

        if use_strategy and self._failover_strategy is not None:
            try:
                plan = self._failover_strategy.get_failover_plan(model, backend_type)
                return self._filter_unhealthy_backends(plan)
            except (BackendError, RateLimitExceededError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failover strategy failed: {e}", exc_info=True)
                # Fall back to coordinator attempts on error

        attempts = self._failover_coordinator.get_failover_attempts(model, backend_type)
        plan = [(a.backend, a.model) for a in attempts]
        return self._filter_unhealthy_backends(plan)

    def _filter_unhealthy_backends(
        self, plan: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Filter out backends with unhealthy API endpoints.

        Args:
            plan: List of (backend, model) tuples.

        Returns:
            Filtered list excluding unhealthy backends (if circuit breaker enabled).
        """
        # Check if circuit breaker is enabled
        # Use getattr for defensive programming - test configs may not have health_check
        health_check = getattr(self._config, "health_check", None)
        if health_check is None or not getattr(health_check, "circuit_breaker_enabled", True):
            return plan

        filtered: list[tuple[str, str]] = []
        for backend_name, model_name in plan:
            backend = self._backends.get(backend_name)
            if backend is None:
                # Backend not yet created, include it (health unknown)
                filtered.append((backend_name, model_name))
                continue

            if backend.is_backend_functional():
                filtered.append((backend_name, model_name))
            else:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Skipping backend %s (unhealthy endpoint) in failover plan",
                        backend_name,
                    )

        if not filtered and plan:
            # If all backends were filtered out, return original plan
            # to avoid complete failure when health checks are too strict
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "All backends filtered as unhealthy, falling back to original plan"
                )
            return plan

        return filtered

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion"""
        # Resolve backend type, effective model, and URI parameters
        backend_type, effective_model, uri_params = (
            await self._resolve_backend_and_model(request)
        )

        # Ensure the request payload reflects the resolved backend and model.
        request = self._synchronize_request_with_target(
            request, backend_type, effective_model
        )

        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )

        # Handle complex failover if configured for this model
        if allow_failover and effective_model in effective_failover_routes:
            return await self._execute_complex_failover(
                request,
                effective_model,
                backend_type,
                effective_failover_routes,
                stream,
                context,
            )

        rate_key = f"backend:{backend_type}"
        limit_info = await self._rate_limiter.check_limit(rate_key)
        if limit_info.is_limited:
            raise RateLimitExceededError(
                message=f"Rate limit exceeded for {backend_type}",
                reset_at=limit_info.reset_at,
                limit=limit_info.limit,
                remaining=limit_info.remaining,
            )

        try:
            await self._rate_limiter.record_usage(rate_key)

            session: Any | None = None
            session_id_for_backend: str | None = None

            # Resolve session from context when available so session-scoped
            # backends (e.g., gemini-cli-acp) keep their state isolated.
            if context and context.session_id:
                session_id_for_backend = context.session_id
                try:
                    session = await self._session_service.get_session(
                        context.session_id
                    )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to load session '%s' for backend call",
                            context.session_id,
                            exc_info=True,
                        )
                    session = None

            request_session_id = (
                request.extra_body.get("session_id") if request.extra_body else None
            )
            if (
                session is None
                and isinstance(request_session_id, str)
                and request_session_id
            ):
                if session_id_for_backend is None:
                    session_id_for_backend = request_session_id
                try:
                    session = await self._session_service.get_session(
                        request_session_id
                    )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Could not load session {request_session_id} for backend from backend-only service"
                        )
                    # If session cannot be loaded, proceed without it
                    session = None

            # Initialize backend only after passing rate limiting checks
            try:
                backend = await self._get_or_create_backend(
                    backend_type, session_id=session_id_for_backend
                )
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                raise BackendError(
                    message=f"Failed to initialize backend {backend_type}",
                    backend_name=backend_type,
                    details={"error": str(e)},
                ) from e

            # Check if backend is rate limited by retry-after
            if hasattr(backend, "get_retry_after_remaining"):
                retry_after_remaining = backend.get_retry_after_remaining()
                if retry_after_remaining is not None:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Backend %s is rate limited, retry after %.1f seconds",
                            backend_type,
                            retry_after_remaining,
                        )
                    raise RateLimitExceededError(
                        message=f"Backend {backend_type} is rate limited",
                        details={
                            "backend": backend_type,
                            "retry_after_seconds": retry_after_remaining,
                        },
                        reset_at=time.time() + retry_after_remaining,
                    )

            # Check if backend is functional, with recovery attempt
            if (
                hasattr(backend, "is_backend_functional")
                and not backend.is_backend_functional()
            ):
                # Try to recover the backend before giving up
                # This handles cases where quota was exhausted but time has passed
                recovered = False
                if hasattr(backend, "_validate_runtime_credentials"):
                    try:
                        recovered = await backend._validate_runtime_credentials()
                        if recovered and logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Backend %s recovered after validation check",
                                backend_type,
                            )
                    except Exception as e:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Backend %s recovery attempt failed: %s",
                                backend_type,
                                e,
                            )

                # Re-check functional status after recovery attempt
                if not recovered and not backend.is_backend_functional():
                    # Get detailed validation errors if available
                    validation_errors: list[str] = []
                    if hasattr(backend, "get_validation_errors"):
                        validation_errors = backend.get_validation_errors()

                    error_details: dict[str, Any] = {
                        "reason": "Backend reported as non-functional",
                    }

                    if validation_errors:
                        error_details["validation_errors"] = validation_errors
                        error_message = f"Backend {backend_type} is not functional: {'; '.join(validation_errors)}"
                    else:
                        error_message = f"Backend {backend_type} is not functional"

                    # Log the error for visibility
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Backend %s is not functional: %s",
                            backend_type,
                            error_message,
                        )

                    # If streaming is enabled, return SSE error stream instead of raising
                    if stream or getattr(request, "stream", False):
                        from collections.abc import AsyncGenerator

                        from src.core.domain.responses import StreamingResponseEnvelope
                        from src.core.interfaces.response_processor_interface import (
                            ProcessedResponse,
                        )
                        from src.core.ports.streaming_contracts import (
                            handle_streaming_error,
                        )

                        backend_error = BackendError(
                            message=error_message,
                            backend_name=backend_type,
                            details=error_details,
                        )

                        async def error_stream() -> (
                            AsyncGenerator[ProcessedResponse, None]
                        ):
                            chunk = await handle_streaming_error(
                                backend_error,
                                getattr(request, "session_id", None),
                                backend_type,
                            )
                            # Yield as string so response_adapters legacy SSE check passes
                            yield ProcessedResponse(
                                content=chunk.to_bytes().decode("utf-8")
                            )

                        return StreamingResponseEnvelope(
                            content=error_stream(),
                            media_type="text/event-stream",
                            headers={},
                            status_code=500,
                        )

                    # Non-streaming: raise as usual
                    raise BackendError(
                        message=error_message,
                        backend_name=backend_type,
                        details=error_details,
                    )

            domain_request: ChatRequest = request

            # Apply session reasoning configuration if available
            if session is not None:
                try:
                    domain_request = self._apply_reasoning_config(
                        domain_request, session
                    )
                except Exception:
                    # Log but continue if session access fails
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to apply reasoning config from session",
                            exc_info=True,
                        )

            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

            # Apply URI parameters with precedence resolution
            if uri_params:
                try:
                    domain_request = self._apply_uri_parameters(
                        domain_request, uri_params, backend_type, session
                    )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to apply URI parameters",
                            exc_info=True,
                        )

            try:
                app_config_typed: AppConfig = cast(AppConfig, self._config)
                provider_backend_config = self._backend_configs.get(backend_type)
                if provider_backend_config and getattr(
                    provider_backend_config, "identity", None
                ):
                    identity = provider_backend_config.identity
                else:
                    backend_config_from_app = app_config_typed.backends.get(
                        backend_type
                    )
                    identity = (
                        backend_config_from_app.identity
                        if backend_config_from_app and backend_config_from_app.identity
                        else app_config_typed.identity
                    )

                # Populate session turn count if session is available
                if session and hasattr(session, "history"):
                    identity = identity.model_copy(
                        update={"session_turn_count": len(session.history)}
                    )
                # Wire-capture: capture outbound payload pre-call (best-effort)
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)
                        # Get session_id from context, not from request.extra_body
                        session_id = getattr(context, "session_id", None)
                        await self._wire_capture.capture_outbound_request(
                            context=context,
                            session_id=session_id,
                            backend=backend_type,
                            model=effective_model,
                            key_name=key_name,
                            request_payload=domain_request,
                        )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (request) failed for backend %s with model %s",
                            backend_type,
                            effective_model,
                            exc_info=True,
                        )
                backend_call_kwargs: dict[str, Any] = {}
                if session_id_for_backend:
                    backend_call_kwargs["session_id"] = session_id_for_backend
                if session is not None and hasattr(session, "state"):
                    try:
                        project_value = getattr(session.state, "project", None)
                        if isinstance(project_value, str) and project_value:
                            backend_call_kwargs["project"] = project_value
                    except Exception:
                        pass
                    try:
                        project_dir_value = getattr(session.state, "project_dir", None)
                        if isinstance(project_dir_value, str) and project_dir_value:
                            backend_call_kwargs["project_dir"] = project_dir_value
                    except Exception:
                        pass

                # Calculate outbound tokens AFTER all transformations
                # This tracks what we're actually sending to the backend
                try:
                    from src.core.utils.usage_recalculation import (
                        calculate_outbound_tokens,
                    )

                    outbound_tokens = calculate_outbound_tokens(
                        domain_request, model=effective_model
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Outbound tokens to {backend_type}/{effective_model}: {outbound_tokens}"
                        )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to calculate outbound tokens", exc_info=True
                        )
                    outbound_tokens = 0

                try:
                    result: ResponseEnvelope | StreamingResponseEnvelope = (
                        await backend.chat_completions(
                            request_data=domain_request,
                            processed_messages=request.messages,
                            effective_model=effective_model,
                            identity=identity,
                            **backend_call_kwargs,
                        )
                    )

                    # Store outbound tokens in result metadata for tracking
                    if hasattr(result, "metadata") and result.metadata is None:
                        result.metadata = {}
                    if hasattr(result, "metadata") and isinstance(
                        result.metadata, dict
                    ):
                        result.metadata["outbound_tokens"] = outbound_tokens
                except AttributeError:
                    # Result doesn't support metadata, skip
                    pass
                except BackendError as be:
                    # Lightweight retry once on HTTP 429 from backend
                    if getattr(be, "status_code", None) == 429:
                        delay_seconds = parse_retry_delay(getattr(be, "details", None))
                        cooldown_seconds = (
                            math.ceil(delay_seconds) if delay_seconds else 15
                        )

                        # Store retry-after in backend instance to prevent future spam
                        if (
                            delay_seconds
                            and delay_seconds > 0
                            and hasattr(backend, "set_retry_after")
                        ):
                            backend.set_retry_after(delay_seconds)
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Backend %s rate limited, set retry-after for %.1f seconds",
                                    backend_type,
                                    delay_seconds,
                                )

                        try:
                            await self._rate_limiter.apply_cooldown(
                                rate_key, cooldown_seconds
                            )
                        except Exception:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Rate limiter is not available", exc_info=True
                                )
                        if delay_seconds:
                            try:
                                await asyncio.sleep(delay_seconds)
                            except Exception:
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Retry delay sleep failed for backend %s",
                                        backend_type,
                                        exc_info=True,
                                    )
                        result = await backend.chat_completions(
                            request_data=domain_request,
                            processed_messages=request.messages,
                            effective_model=effective_model,
                            identity=identity,
                            **backend_call_kwargs,
                        )
                    else:
                        raise
                # Get session_id from context for stream correlation
                session_id = getattr(context, "session_id", None)
                session_id = self._resolve_stream_session_id(
                    session_id, context, domain_request
                )
                if context is not None and not getattr(context, "session_id", None):
                    with contextlib.suppress(Exception):
                        context.session_id = session_id
                from src.core.domain.responses import StreamingResponseEnvelope

                # Wire-capture: capture inbound
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)

                        if isinstance(result, StreamingResponseEnvelope):
                            # Adapt domain stream to bytes for capture and transport
                            byte_stream = self._stream_as_sse_bytes(result.content)
                            wrapped_stream = self._wire_capture.wrap_inbound_stream(
                                context=context,
                                session_id=session_id,
                                backend=backend_type,
                                model=effective_model,
                                key_name=key_name,
                                stream=byte_stream,  # type: ignore
                            )

                            # Convert back to ProcessedResponse stream for adapters
                            # IMPORTANT: Include session_id in metadata for stream correlation
                            # This ensures tool call buffering works correctly across chunks
                            async def _to_processed_with_capture() -> Any:
                                from src.core.interfaces.response_processor_interface import (
                                    ProcessedResponse,
                                )

                                async for b in wrapped_stream:  # type: ignore
                                    yield ProcessedResponse(
                                        content=b,
                                        metadata=(
                                            {
                                                "session_id": session_id,
                                                "stream_id": session_id,
                                            }
                                            if session_id
                                            else {}
                                        ),
                                    )

                            return StreamingResponseEnvelope(
                                content=_to_processed_with_capture(),
                                media_type=result.media_type,
                                headers=result.headers,
                                metadata=result.metadata,
                            )
                        else:
                            await self._wire_capture.capture_inbound_response(
                                context=context,
                                session_id=session_id,
                                backend=backend_type,
                                model=effective_model,
                                key_name=key_name,
                                response_content=result.content,
                            )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (response) failed for backend %s with model %s",
                            backend_type,
                            effective_model,
                            exc_info=True,
                        )

                # IMPORTANT: Always wrap streaming responses with session_id for proper
                # tool call buffering, even when wire capture is disabled
                if isinstance(result, StreamingResponseEnvelope):
                    original_content = result.content

                    async def _inject_session_id() -> Any:
                        from src.core.interfaces.response_processor_interface import (
                            ProcessedResponse,
                        )

                        async for chunk in original_content:  # type: ignore
                            if isinstance(chunk, ProcessedResponse):
                                # Merge session_id into existing metadata
                                metadata = dict(chunk.metadata or {})
                                if session_id and "session_id" not in metadata:
                                    metadata["session_id"] = session_id
                                if session_id and "stream_id" not in metadata:
                                    metadata["stream_id"] = session_id
                                yield ProcessedResponse(
                                    content=chunk.content,
                                    metadata=metadata,
                                    usage=chunk.usage,
                                )
                            else:
                                # Wrap raw chunk with session_id
                                yield ProcessedResponse(
                                    content=chunk,
                                    metadata=(
                                        {
                                            "session_id": session_id,
                                            "stream_id": session_id,
                                        }
                                        if session_id
                                        else {}
                                    ),
                                )

                    return StreamingResponseEnvelope(
                        content=_inject_session_id(),
                        media_type=result.media_type,
                        headers=result.headers,
                        metadata=result.metadata,
                    )

                return result
            except (
                Exception
            ) as call_exc:  # Catch all exceptions for comprehensive logging
                call_exc = self._normalize_provider_exception(call_exc, backend_type)

                # Store retry-after in backend instance if this is a rate limit error
                if isinstance(call_exc, RateLimitExceededError) and hasattr(
                    backend, "set_retry_after"
                ):
                    reset_at = getattr(call_exc, "reset_at", None)
                    if reset_at is not None:
                        retry_after_seconds = reset_at - time.time()
                        if retry_after_seconds > 0:
                            backend.set_retry_after(retry_after_seconds)
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Backend %s rate limited, cached retry-after for %.1f seconds",
                                    backend_type,
                                    retry_after_seconds,
                                )

                # If the exception is already a BackendError or RateLimitExceededError,
                # treat it specially; otherwise wrap or re-raise depending on allow_failover.
                if isinstance(call_exc, BackendError | RateLimitExceededError):
                    if not allow_failover:
                        # Re-raise the original domain-specific exception
                        raise call_exc
                    last_error = call_exc
                else:
                    if not allow_failover:
                        # Immediate wrapping when failover is disabled
                        raise BackendError(
                            message=f"Backend call failed: {call_exc!s}",
                            backend_name=backend_type,
                        ) from call_exc  # Chain the exception
                    last_error = call_exc  # type: ignore[assignment]

                # Handle failover on backend call failure
                if allow_failover:
                    return await self._handle_backend_call_failover(
                        request, backend_type, stream, last_error
                    )

                # If we get here, wrap the last error into BackendError
                raise BackendError(
                    message=f"Backend call failed: {last_error!s}",
                    backend_name=backend_type,
                )

        except (BackendError, RateLimitExceededError, LLMProxyError):
            # Propagate expected exceptions as-is
            raise
        except Exception as e:
            # Catch any other unexpected exceptions and wrap them
            raise BackendError(
                message=f"An unexpected error occurred during backend call to {backend_type}: {e!s}",
                backend_name=backend_type,
            ) from e

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        """Validate that a backend and model combination is valid"""
        try:
            backend_instance: LLMBackend = await self._get_or_create_backend(backend)

            available_models: list[str] = backend_instance.get_available_models()
            if model in available_models:
                return True, None

            return False, f"Model {model} not available on backend {backend}"
        except (BackendError, TypeError, ValueError, AttributeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Backend validation failed for {backend}: {e!s}", exc_info=True
                )
            return False, f"Backend validation failed: {e!s}"

    async def _get_or_create_backend(
        self, backend_type: str, session_id: str | None = None
    ) -> LLMBackend:
        """Get an existing backend or create a new one."""

        # Always use session-specific cache key if session_id is provided
        # This ensures all backends are isolated per session
        if session_id:
            cache_key = f"{backend_type}:{session_id}"
        elif backend_type == "gemini-cli-acp":
            # Special case for gemini-cli-acp which requires isolation even without explicit session_id
            # (though session_id should ideally be provided)
            cache_key = f"{backend_type}:default"
        else:
            cache_key = backend_type

        if self._is_per_session_cache_key(cache_key, backend_type):
            backend = self._per_session_backends.get(cache_key)
            if backend is not None:
                self._per_session_backends.move_to_end(cache_key)
                return backend
        else:
            backend = self._backends.get(cache_key)
            if backend is not None:
                return backend

        try:
            provider_backend_config: BackendConfig | None = None
            app_config: AppConfig = cast(AppConfig, self._config)

            if self._backend_config_provider:
                provider_cfg = self._backend_config_provider.get_backend_config(
                    backend_type
                )

                if isinstance(provider_cfg, BackendConfig):
                    provider_backend_config = provider_cfg
                elif isinstance(provider_cfg, AppConfig):
                    app_config = provider_cfg

            if provider_backend_config is not None:
                try:
                    self._backend_configs[backend_type] = (
                        provider_backend_config.model_copy(deep=True)
                    )
                except AttributeError:
                    self._backend_configs[backend_type] = provider_backend_config
            else:
                self._backend_configs.pop(backend_type, None)

            created_backend: LLMBackend = await self._factory.ensure_backend(
                backend_type, app_config, provider_backend_config
            )
            if self._is_per_session_cache_key(cache_key, backend_type):
                self._per_session_backends[cache_key] = created_backend
                self._per_session_backends.move_to_end(cache_key)
                await self._enforce_per_session_backend_limit()
            else:
                self._backends[cache_key] = created_backend
            return created_backend
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise BackendError(
                message=f"Failed to create backend {backend_type}: {e!s}",
                backend_name=backend_type,
            ) from e
        except Exception as e:
            raise BackendError(
                f"Failed to create backend '{backend_type}': {e}",
                backend_name=backend_type,
            ) from e

    def get_backend(self, backend_type: str) -> LLMBackend:
        """Get a backend instance synchronously (for testing purposes)."""
        if backend_type in self._backends:
            return self._backends[backend_type]

        # For testing, create a simple backend instance
        from src.core.config.app_config import AppConfig

        app_config = cast(AppConfig, self._config)

        # Create backend using factory
        backend = self._factory.create_backend(backend_type, app_config)
        self._backends[backend_type] = backend
        return backend

    async def chat_completions(
        self,
        request: ChatRequest,
        *,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:  # type: ignore[override]
        """Handle chat completions with the LLM."""

        return await self.call_completion(
            request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

    async def _apply_planning_phase_if_needed(
        self, session: Any, default_backend: str
    ) -> None:
        """Apply planning phase model override if conditions are met.

        Args:
            session: The current session
            default_backend: Default backend for model parsing
        """
        if not session or not session.state:
            return

        planning_config = getattr(session.state, "planning_phase_config", None)
        if (
            not planning_config
            or not bool(getattr(planning_config, "enabled", False))
            or not getattr(planning_config, "strong_model", None)
        ):
            return

        # Safely extract counters with defaults
        try:
            turn_count = int(
                getattr(session.state, "planning_phase_turn_count", 0) or 0
            )
        except Exception:
            turn_count = 0
        try:
            file_write_count = int(
                getattr(session.state, "planning_phase_file_write_count", 0) or 0
            )
        except Exception:
            file_write_count = 0

        try:
            _max_turns = int(getattr(planning_config, "max_turns", 0) or 0)
        except Exception:
            _max_turns = 0
        try:
            _max_writes = int(getattr(planning_config, "max_file_writes", 0) or 0)
        except Exception:
            _max_writes = 0

        if (turn_count >= _max_turns) or (file_write_count >= _max_writes):
            await self._restore_planning_phase_route(session)
            return

        from src.core.domain.configuration.backend_config import BackendConfiguration
        from src.core.domain.model_utils import parse_model_backend
        from src.core.interfaces.configuration_interface import IBackendConfig

        requested_backend, requested_model = parse_model_backend(
            session.state.backend_config.model or "", default_backend
        )
        strong_backend, strong_model = parse_model_backend(
            planning_config.strong_model, default_backend
        )

        current_full_model = f"{requested_backend}:{requested_model}"
        strong_full_model = f"{strong_backend}:{strong_model}"

        if current_full_model == strong_full_model:
            return

        # Persist the original route so we can restore it when planning phase ends
        try:
            has_original_backend = bool(
                getattr(session.state, "planning_phase_original_backend", None)
            )
            has_original_model = bool(
                getattr(session.state, "planning_phase_original_model", None)
            )
        except Exception:
            has_original_backend = False
            has_original_model = False

        if not (has_original_backend or has_original_model):
            new_state = session.state.with_planning_phase_original_route(
                requested_backend,
                requested_model,
            )
            session.update_state(new_state)
            await self._session_service.update_session(session)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Planning phase active (turn {turn_count + 1}/{planning_config.max_turns}): "
                f"routing from {current_full_model} to {strong_full_model}"
            )

        new_backend_config = BackendConfiguration(
            backend_type=strong_backend,
            model=strong_model,
            interactive_mode=session.state.backend_config.interactive_mode,
        )

        new_state = session.state.with_backend_config(
            cast(IBackendConfig, new_backend_config)
        )
        session.update_state(new_state)
        await self._session_service.update_session(session)

    async def _update_planning_phase_counters(
        self, session_id: str, response: Any
    ) -> None:
        """Update planning phase counters after a successful completion.

        Args:
            session_id: The session ID
            response: The response envelope containing metadata
        """
        try:
            session = await self._session_service.get_session(session_id)
            if not session or not session.state:
                return

            planning_config = session.state.planning_phase_config
            if not planning_config.enabled:
                return

            turn_count = session.state.planning_phase_turn_count
            file_write_count = session.state.planning_phase_file_write_count

            if (
                turn_count >= planning_config.max_turns
                or file_write_count >= planning_config.max_file_writes
            ):
                await self._restore_planning_phase_route(session)
                return

            new_turn_count = turn_count + 1
            new_file_write_count = (
                file_write_count + self._count_file_writes_in_response(response)
            )

            if new_turn_count != turn_count or new_file_write_count != file_write_count:
                # Performance optimization: use single model_copy instead of chaining
                new_state = session.state.with_multiple_updates(
                    planning_phase_turn_count=new_turn_count,
                    planning_phase_file_write_count=new_file_write_count,
                )

                session.update_state(new_state)
                await self._session_service.update_session(session)

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Updated session %s with planning_phase_turn_count=%d, planning_phase_file_write_count=%d",
                        session_id,
                        new_turn_count,
                        new_file_write_count,
                    )

                if (
                    new_turn_count >= planning_config.max_turns
                    or new_file_write_count >= planning_config.max_file_writes
                ):
                    await self._restore_planning_phase_route(session)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to update planning phase counters: {e}", exc_info=True
                )

    async def _restore_planning_phase_route(self, session: Any) -> None:
        """Restore the original backend/model after planning phase concludes."""

        if not session or not session.state:
            return

        try:
            original_backend = getattr(
                session.state, "planning_phase_original_backend", None
            )
            original_model = getattr(
                session.state, "planning_phase_original_model", None
            )
        except Exception:
            return

        if original_backend is None and original_model is None:
            return

        from src.core.domain.configuration.backend_config import BackendConfiguration
        from src.core.interfaces.configuration_interface import IBackendConfig

        current_config = session.state.backend_config
        target_backend = original_backend or current_config.backend_type
        target_model = (
            original_model if original_model is not None else current_config.model
        )

        # Ensure that we are not passing mock objects to the BackendConfiguration
        if hasattr(target_backend, "_extract_mock_name"):
            target_backend = str(target_backend)
        if hasattr(target_model, "_extract_mock_name"):
            target_model = str(target_model)

        restored_config = BackendConfiguration(
            backend_type=target_backend,
            model=target_model,
            interactive_mode=current_config.interactive_mode,
        )

        # Performance optimization: use single model_copy instead of chaining
        new_state = session.state.with_multiple_updates(
            backend_config=cast(IBackendConfig, restored_config),
            planning_phase_original_backend=None,
            planning_phase_original_model=None,
        )

        session.update_state(new_state)
        await self._session_service.update_session(session)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Planning phase complete; restored session %s to backend=%s model=%s",
                getattr(session, "id", None),
                target_backend,
                target_model,
            )

    def _count_file_writes_in_response(self, response: Any) -> int:
        """Count file write tool calls in a response.

        Args:
            response: The response envelope

        Returns:
            Number of file write operations detected
        """
        file_write_tools = {
            "write_file",
            "edit_file",
            "patch_file",
            "apply_diff",
            "search_replace",
            "str_replace_editor",
            "write_to_file",
            "create_file",
            "modify_file",
            "apply_patch",
            "edit_notebook",
        }

        count = 0
        tool_calls = []

        if hasattr(response, "metadata") and isinstance(response.metadata, dict):
            tool_calls = response.metadata.get("tool_calls", [])
        elif hasattr(response, "content") and isinstance(response.content, dict):
            choices = response.content.get("choices", [])
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message", {})
                if message and isinstance(message, dict):
                    tool_calls = message.get("tool_calls", [])

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("function", {}).get("name") or tool_call.get(
                    "name"
                )
                if tool_name and tool_name.lower() in file_write_tools:
                    count += 1

        return count

    async def _resolve_backend_and_model(
        self, request: ChatRequest
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve backend type, effective model, and URI parameters from request and session"""
        session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        session = (
            await self._session_service.get_session(session_id) if session_id else None
        )

        from src.core.config.app_config import AppConfig

        app_config: AppConfig = cast(AppConfig, self._config)
        default_backend: str = (
            app_config.backends.default_backend
            if hasattr(app_config, "backends")
            else "openai"
        )

        await self._apply_planning_phase_if_needed(session, default_backend)

        backend_type: str | None = None
        if session and session.state and session.state.backend_config:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            backend_type = cast(
                BackendConfiguration, session.state.backend_config
            ).backend_type

        if not backend_type:
            backend_type = (
                request.extra_body.get("backend_type") if request.extra_body else None
            )

        effective_model: str = request.model

        # Apply model aliases BEFORE parsing backend from model name
        effective_model = self._apply_model_aliases(effective_model)

        # Parse model string with URI parameters
        uri_params: dict[str, Any] = {}
        if not backend_type:
            from src.core.domain.model_utils import parse_model_with_params

            # Pass empty string as default to detect if backend was specified
            parsed_backend, parsed_model, uri_params = parse_model_with_params(
                effective_model, ""
            )

            if not parsed_backend:
                # No backend specified in model string (Variant 3)
                if self._routing_service:
                    # Try discovery
                    discovered = self._routing_service.resolve_backend_instance(
                        None, parsed_model
                    )
                    if discovered:
                        parsed_backend = discovered

            # Fallback to default backend if discovery failed or not used
            backend_type = parsed_backend or default_backend
            effective_model = parsed_model

            # If we have a backend type (either parsed or default), try to route it (Variant 2)
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        else:
            # Backend type is already set (from session or extra_body)
            # Still need to parse URI parameters from the model string
            from src.core.domain.model_utils import parse_model_with_params

            # Parse with empty default backend since we already have backend_type
            _, parsed_model, uri_params = parse_model_with_params(effective_model, "")
            effective_model = parsed_model

            # Try to route the explicitly set backend (Variant 2)
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        # Apply static_route override if configured
        app_config = cast(AppConfig, self._config)
        if (
            hasattr(app_config, "backends")
            and hasattr(app_config.backends, "static_route")
            and app_config.backends.static_route
        ):
            static_route = app_config.backends.static_route
            # Parse backend:model format (check it's a string first)
            if isinstance(static_route, str) and ":" in static_route:
                forced_backend, forced_model = static_route.split(":", 1)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route override: {backend_type}:{effective_model} -> {forced_backend}:{forced_model}"
                    )
                backend_type = forced_backend
                effective_model = forced_model
            else:
                # If no colon, treat as model only
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route model override: {effective_model} -> {static_route}"
                    )
                effective_model = static_route

        return backend_type, effective_model, uri_params

    def _synchronize_request_with_target(
        self, request: ChatRequest, backend_type: str, effective_model: str
    ) -> ChatRequest:
        """
        Ensure the request (and nested extra_body) reflect the backend/model chosen.

        Args:
            request: Original chat request from the client.
            backend_type: Resolved backend name.
            effective_model: Resolved model name.

        Returns:
            A request object updated with the resolved backend/model information.
        """
        updates: dict[str, Any] = {}

        # Preserve the original model format if it contains a backend prefix that matches
        # the resolved backend. This allows connectors to see the original client request.
        # However, if the backend was overridden (e.g., via static_route), update the model.
        should_update_model = False
        if request.model != effective_model:
            if ":" in request.model:
                # Model has backend prefix - check if it matches the resolved backend
                request_backend, _ = request.model.split(":", 1)
                if request_backend != backend_type:
                    # Backend was overridden, update the model
                    should_update_model = True
                # else: Backend matches, preserve original format
            else:
                # No backend prefix, update to effective model
                should_update_model = True

        if should_update_model:
            updates["model"] = effective_model

        extra_body = getattr(request, "extra_body", None)
        if isinstance(extra_body, dict):
            updated_extra_body = dict(extra_body)
            extra_changed = False

            if updated_extra_body.get("model") != effective_model:
                updated_extra_body["model"] = effective_model
                extra_changed = True

            if backend_type:
                if updated_extra_body.get("backend_type") != backend_type:
                    updated_extra_body["backend_type"] = backend_type
                    extra_changed = True
            elif "backend_type" in updated_extra_body:
                # Remove stale backend_type when backend resolution is empty.
                updated_extra_body.pop("backend_type")
                extra_changed = True

            if extra_changed:
                updates["extra_body"] = updated_extra_body

        if not updates:
            return request

        return request.model_copy(update=updates)

    def _detect_key_name(self, backend_type: str) -> str | None:
        """Derive API key name (env var) for the backend when possible.

        Falls back to the backend type when a specific name is not found.
        """
        try:
            app_config: AppConfig = cast(AppConfig, self._config)
            backend_cfg = app_config.backends.get(backend_type)
            api_key_value: str | None = None
            if backend_cfg and getattr(backend_cfg, "api_key", None):
                keys = backend_cfg.api_key
                api_key_value = keys[0] if keys else None
            if not api_key_value:
                return backend_type

            env_base = {
                "openrouter": "OPENROUTER_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "zai": "ZAI_API_KEY",
                "zenmux": "ZENMUX_API_KEY",
                "minimax": "MINIMAX_API_KEY",
            }.get(backend_type)
            if not env_base:
                return backend_type
            mapping = _collect_api_keys(env_base)
            for name, value in mapping.items():
                if value == api_key_value:
                    return name
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("_detect_key_name failed", exc_info=True)
        return backend_type

    async def _execute_complex_failover(
        self,
        request: ChatRequest,
        effective_model: str,
        backend_type: str,
        effective_failover_routes: dict[str, Any],
        stream: bool,
        context: RequestContext | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy for models with configured routes"""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Using complex failover policy for model {effective_model}")
        try:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            _backend_config: BackendConfiguration = BackendConfiguration(
                backend_type=backend_type,
                model=effective_model,
                failover_routes_data=effective_failover_routes,
            )

            plan: list[tuple[str, str]] = self._get_failover_plan(
                effective_model, backend_type
            )

            return await self._attempt_failover_plan(
                request, plan, stream, backend_type, context
            )
        except BackendError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError) as failover_error:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failover processing failed: {failover_error!s}", exc_info=True
                )
            raise BackendError(
                message="all backends failed", backend_name=backend_type
            ) from failover_error

    async def _attempt_failover_plan(
        self,
        request: ChatRequest,
        plan: list[tuple[str, str]],
        stream: bool,
        backend_type: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Attempt failover using the provided plan.



        Args:
            request: The original request
            plan: List of (backend, model) tuples to attempt
            stream: Whether the request is a streaming request
            backend_type: The original backend type

        Returns:
            Response from the first successful attempt



        Raises:
            BackendError: If all attempts fail
        """
        last_error: Exception | None = None
        if not plan:
            raise BackendError(message="all backends failed", backend_name=backend_type)

        for backend_attempt, model_attempt in plan:
            try:
                attempt_extra_body: dict[str, Any] = (
                    request.extra_body.copy() if request.extra_body else {}
                )
                attempt_extra_body["backend_type"] = backend_attempt

                attempt_request: ChatRequest = request.model_copy(
                    update={
                        "extra_body": attempt_extra_body,
                        "model": model_attempt,
                    }
                )

                return await self.call_completion(
                    attempt_request,
                    stream=stream,
                    allow_failover=False,
                    context=context,
                )
            except (BackendError, RateLimitExceededError) as attempt_error:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failover attempt failed for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue
            except Exception as attempt_error:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Unexpected error during failover attempt for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue

        if last_error:
            raise BackendError(
                message=f"All failover attempts failed. Last error: {last_error!s}",
                backend_name=backend_type,
            )
        else:
            raise BackendError(
                message="All failover attempts failed. No error details available.",
                backend_name=backend_type,
            )

    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances.

        Returns:
             A dictionary mapping backend instance names to LLMBackend objects.
        """
        return self._backends.copy()

    async def _handle_backend_call_failover(
        self,
        request: ChatRequest,
        backend_type: str,
        stream: bool,
        last_error: Exception,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle failover logic when a backend call fails.

        This method inspects request-scoped and service-level failover routes
        and attempts alternative backends/models when the primary call fails.
        """
        # Proceed with failover logic using last_error as the last seen exception
        request_failover_routes_nested: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes_nested: dict[str, Any] = (
            request_failover_routes_nested
            if request_failover_routes_nested
            else self._failover_routes
        )

        if request.model in effective_failover_routes_nested:
            try:
                # Get the failover plan using the consolidated approach
                plan_nested: list[tuple[str, str]] = self._get_failover_plan(
                    request.model, backend_type
                )

                return await self._attempt_failover_plan(
                    request, plan_nested, stream, backend_type, context
                )
            except (TypeError, ValueError, AttributeError, KeyError) as failover_error:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Failover processing failed: {failover_error!s}", exc_info=True
                    )
                raise BackendError(
                    message=f"Failover processing failed: {failover_error!s}",
                    backend_name=backend_type,
                ) from failover_error

        elif backend_type in self._failover_routes:
            fallback_info: dict[str, Any] = self._failover_routes.get(backend_type, {})
            fallback_backend: str | None = fallback_info.get("backend")
            fallback_model: str | None = fallback_info.get("model")

            if fallback_backend:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Primary backend {backend_type} failed with error: {last_error!s}. "
                        f"Attempting fallback to {fallback_backend}"
                    )

                fallback_extra_body: dict[str, Any] = (
                    request.extra_body.copy() if request.extra_body else {}
                )
                fallback_extra_body["backend_type"] = fallback_backend

                fallback_updates: dict[str, Any] = {"extra_body": fallback_extra_body}
                if fallback_model:
                    fallback_updates["model"] = fallback_model

                fallback_request: ChatRequest = request.model_copy(
                    update=fallback_updates
                )

                return await self.call_completion(
                    fallback_request,
                    stream=stream,
                    allow_failover=False,
                    context=context,
                )

        normalized_last_error = self._normalize_provider_exception(
            last_error, backend_type
        )
        if isinstance(
            normalized_last_error, RateLimitExceededError | BackendError | LLMProxyError
        ):
            raise normalized_last_error

        # If no failover options available, raise the original error
        raise BackendError(
            message=f"Backend call failed: {last_error!s}",
            backend_name=backend_type,
        )
