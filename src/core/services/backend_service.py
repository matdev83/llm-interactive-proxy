from __future__ import annotations

import logging
import re
from typing import Any, cast

from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
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
        self._backends: dict[str, LLMBackend] = {}
        from src.core.config.app_config import AppConfig
        from src.core.services.failover_coordinator import FailoverCoordinator

        # Ensure config is properly typed for type checking
        _typed_config = cast(AppConfig, config)

        self._failover_service: FailoverService = FailoverService(
            failover_routes=self._failover_routes
        )
        if failover_coordinator is None:
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
                    logger.info(f"Applied model alias: '{model}' -> '{new_model}'")
                    return new_model
            except (re.error, AttributeError, TypeError) as e:
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

        async def _adapter() -> Any:
            async for chunk in it:  # type: ignore
                content = (
                    chunk.content if isinstance(chunk, ProcessedResponse) else chunk
                )
                if isinstance(content, dict):
                    line = f"data: {json.dumps(content)}\n\n".encode()
                    yield line
                elif isinstance(content, str):
                    yield content.encode("utf-8")
                elif isinstance(content, bytes):
                    yield content
                else:
                    yield str(content).encode("utf-8")

        return _adapter()

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

    def _get_failover_plan(
        self, model: str, backend_type: str
    ) -> list[tuple[str, str]]:
        """Return an ordered plan of (backend, model) attempts.

        Uses the extracted strategy when enabled and available, otherwise falls
        back to coordinator-provided attempts.
        """
        use_strategy: bool = False
        try:
            use_strategy = self._app_state.get_use_failover_strategy()
        except (AttributeError, KeyError) as e:
            logger.debug(
                f"Could not get failover strategy from app state: {e}", exc_info=True
            )
            use_strategy = False

        if use_strategy and self._failover_strategy is not None:
            try:
                return self._failover_strategy.get_failover_plan(model, backend_type)
            except (BackendError, RateLimitExceededError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failover strategy failed: {e}", exc_info=True)
                # Fall back to coordinator attempts on error

        attempts = self._failover_coordinator.get_failover_attempts(model, backend_type)
        return [(a.backend, a.model) for a in attempts]

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion"""
        # Resolve backend type and effective model
        backend_type, effective_model = await self._resolve_backend_and_model(request)

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

            # Initialize backend only after passing rate limiting checks
            try:
                backend = await self._get_or_create_backend(backend_type)
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                raise BackendError(
                    message=f"Failed to initialize backend {backend_type}",
                    backend_name=backend_type,
                    details={"error": str(e)},
                ) from e

            # Check if backend is functional
            if (
                hasattr(backend, "is_backend_functional")
                and not backend.is_backend_functional()
            ):
                raise BackendError(
                    message=f"Backend {backend_type} is not functional",
                    backend_name=backend_type,
                    details={"reason": "Backend reported as non-functional"},
                )

            domain_request: ChatRequest = request

            # Apply session reasoning configuration if available
            if context and context.session_id:
                try:
                    session = await self._session_service.get_session(
                        context.session_id
                    )
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

            try:
                app_config_typed: AppConfig = cast(AppConfig, self._config)
                provider_backend_config = self._backend_configs.get(backend_type)
                if (
                    provider_backend_config
                    and getattr(provider_backend_config, "identity", None)
                ):
                    identity = provider_backend_config.identity
                else:
                    backend_config_from_app = app_config_typed.backends.get(
                        backend_type
                    )
                    identity = (
                        backend_config_from_app.identity
                        if backend_config_from_app
                        and backend_config_from_app.identity
                        else app_config_typed.identity
                    )
                # Wire-capture: capture outbound payload pre-call (best-effort)
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)
                        session_id = (
                            request.extra_body.get("session_id")
                            if request.extra_body
                            else None
                        )
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
                try:
                    result: ResponseEnvelope | StreamingResponseEnvelope = (
                        await backend.chat_completions(
                            request_data=domain_request,
                            processed_messages=request.messages,
                            effective_model=effective_model,
                            identity=identity,
                        )
                    )
                except BackendError as be:
                    # Lightweight retry once on HTTP 429 from backend
                    if getattr(be, "status_code", None) == 429:
                        # Optional: Parse retry delay if available; avoid sleeping in tests
                        _ = parse_retry_delay(getattr(be, "details", None))
                        result = await backend.chat_completions(
                            request_data=domain_request,
                            processed_messages=request.messages,
                            effective_model=effective_model,
                            identity=identity,
                        )
                    else:
                        raise
                # Wire-capture: capture inbound
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)
                        session_id = (
                            request.extra_body.get("session_id")
                            if request.extra_body
                            else None
                        )
                        from src.core.domain.responses import StreamingResponseEnvelope

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
                            async def _to_processed() -> Any:
                                from src.core.interfaces.response_processor_interface import (
                                    ProcessedResponse,
                                )

                                async for b in wrapped_stream:  # type: ignore
                                    yield ProcessedResponse(content=b)

                            return StreamingResponseEnvelope(
                                content=_to_processed(),
                                media_type=result.media_type,
                                headers=result.headers,
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

                return result
            except (
                Exception
            ) as call_exc:  # Catch all exceptions for comprehensive logging
                # If the exception is already a BackendError or RateLimitExceededError,
                # treat it specially; otherwise wrap or re-raise depending on allow_failover.
                if isinstance(call_exc, BackendError | RateLimitExceededError):
                    if not allow_failover:
                        # Re-raise the original domain-specific exception
                        raise  # Re-raise the original exception
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

        except (BackendError, RateLimitExceededError):
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
            logger.warning(
                f"Backend validation failed for {backend}: {e!s}", exc_info=True
            )
            return False, f"Backend validation failed: {e!s}"

    async def _get_or_create_backend(self, backend_type: str) -> LLMBackend:
        """Get an existing backend or create a new one"""
        if backend_type in self._backends:
            return self._backends[backend_type]

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

            backend: LLMBackend = await self._factory.ensure_backend(
                backend_type, app_config, provider_backend_config
            )
            self._backends[backend_type] = backend
            return backend
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
                return

            new_turn_count = turn_count + 1
            new_file_write_count = (
                file_write_count + self._count_file_writes_in_response(response)
            )

            if new_turn_count != turn_count or new_file_write_count != file_write_count:
                new_state = session.state.with_planning_phase_turn_count(
                    new_turn_count
                ).with_planning_phase_file_write_count(new_file_write_count)

                session.update_state(new_state)
                await self._session_service.update_session(session)

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Updated planning phase counters: turns={new_turn_count}/{planning_config.max_turns}, "
                        f"file_writes={new_file_write_count}/{planning_config.max_file_writes}"
                    )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to update planning phase counters: {e}", exc_info=True
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

    async def _resolve_backend_and_model(self, request: ChatRequest) -> tuple[str, str]:
        """Resolve backend type and effective model from request and session"""
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

        if not backend_type:
            from src.core.domain.model_utils import parse_model_backend

            parsed_backend, parsed_model = parse_model_backend(
                effective_model, default_backend
            )
            backend_type = parsed_backend
            effective_model = parsed_model

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

        return backend_type, effective_model

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
                logger.warning(
                    f"Failover attempt failed for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                    exc_info=True,
                )
                last_error = attempt_error
                continue
            except Exception as attempt_error:
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

        # If no failover options available, raise the original error
        raise BackendError(
            message=f"Backend call failed: {last_error!s}",
            backend_name=backend_type,
        )
