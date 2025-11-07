"""Hybrid backend connector implementation."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.base import LLMBackend
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

from .message_augmentation import HybridMessageAugmentationMixin
from .model_spec import HybridModelSpecMixin
from .parameters import HybridParameterMixin
from .phases import HybridPhaseMixin
from .reasoning_markup import HybridReasoningMarkupMixin
from .request_preparation import HybridRequestPreparationMixin
from .response_filtering import HybridResponseFilteringMixin
from .utils import HybridConnectorUtilsMixin

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class HybridConnector(
    HybridModelSpecMixin,
    HybridParameterMixin,
    HybridReasoningMarkupMixin,
    HybridMessageAugmentationMixin,
    HybridResponseFilteringMixin,
    HybridRequestPreparationMixin,
    HybridPhaseMixin,
    HybridConnectorUtilsMixin,
    LLMBackend,
):
    """LLMBackend implementation for hybrid two-phase reasoning approach."""

    backend_type: str = "hybrid"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        backend_registry: BackendRegistry | None = None,
    ) -> None:
        super().__init__(config=config)
        self.client = client
        self.config = config
        self.translation_service = translation_service
        self._backend_registry = backend_registry

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the hybrid backend."""

        if self._backend_registry is None:
            from src.core.services.backend_registry import (
                backend_registry as default_registry,
            )

            self._backend_registry = default_registry

        if (
            hasattr(self.config, "backends")
            and hasattr(self.config.backends, "disable_hybrid_backend")
            and self.config.backends.disable_hybrid_backend
        ):
            logger.warning("Hybrid backend is disabled in configuration")

        logger.info("Hybrid backend initialized successfully")

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the two-phase hybrid completion."""

        start_time = time.time()
        session_id = getattr(identity, "session_id", None) if identity else None

        if (
            hasattr(self.config, "backends")
            and hasattr(self.config.backends, "disable_hybrid_backend")
            and self.config.backends.disable_hybrid_backend
        ):
            logger.warning(
                "Hybrid backend request rejected - backend is disabled",
                extra={"session_id": session_id},
            )
            raise ConfigurationError(
                message="Hybrid backend is disabled",
                code="hybrid_backend_disabled",
            )

        if isinstance(request_data, DomainModel):
            request_dict = request_data.model_dump()
        elif isinstance(request_data, dict):
            request_dict = request_data
        elif is_dataclass(request_data) and not isinstance(request_data, type):
            request_dict = asdict(request_data)
        else:
            raise TypeError(
                "request_data must be a Pydantic model, a dict, or a dataclass, "
                f"but got {type(request_data)}"
            )

        try:
            (
                reasoning_backend,
                reasoning_model,
                reasoning_params,
                execution_backend,
                execution_model,
                execution_params,
            ) = self._parse_hybrid_model_spec(effective_model)

            has_reasoning_effort_in_reasoning = "reasoning_effort" in reasoning_params
            has_reasoning_effort_in_execution = "reasoning_effort" in execution_params

            if has_reasoning_effort_in_reasoning or has_reasoning_effort_in_execution:
                logger.warning(
                    "reasoning_effort parameter in hybrid model string is not effective. "
                    "Hybrid backend enforces reasoning effort by design.",
                    extra={
                        "session_id": session_id,
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "execution_backend": execution_backend,
                        "execution_model": execution_model,
                        "reasoning_effort_in_reasoning": has_reasoning_effort_in_reasoning,
                        "reasoning_effort_in_execution": has_reasoning_effort_in_execution,
                    },
                )

                if has_reasoning_effort_in_reasoning:
                    reasoning_params = {
                        key: value
                        for key, value in reasoning_params.items()
                        if key != "reasoning_effort"
                    }
                if has_reasoning_effort_in_execution:
                    execution_params = {
                        key: value
                        for key, value in execution_params.items()
                        if key != "reasoning_effort"
                    }

            logger.info(
                "Hybrid request initiated: reasoning=%s:%s (params=%s), execution=%s:%s (params=%s)",
                reasoning_backend,
                reasoning_model,
                reasoning_params,
                execution_backend,
                execution_model,
                execution_params,
                extra={
                    "session_id": session_id,
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "reasoning_params": reasoning_params,
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "execution_params": execution_params,
                    "message_count": len(processed_messages),
                    "stream": request_dict.get("stream", False),
                },
            )

        except ValueError as exc:
            logger.error(
                "Invalid hybrid model specification: %s",
                exc,
                extra={
                    "session_id": session_id,
                    "effective_model": effective_model,
                    "error": str(exc),
                },
            )
            raise

        reasoning_output = ""
        client_reasoning = ""
        has_reasoning_content = False
        reasoning_time = 0.0

        if isinstance(request_data, dict):
            extra_body = request_data.get("extra_body", {})
        else:
            extra_body = getattr(request_data, "extra_body", {}) or {}

        temp_prob_override = extra_body.get("_temp_hybrid_reasoning_probability")
        if temp_prob_override is not None:
            temp_reasoning_probability = float(temp_prob_override)
            logger.info(
                "Using temporary reasoning injection probability override: %s for session",
                temp_reasoning_probability,
                extra={"session_id": session_id},
            )
        else:
            temp_reasoning_probability = (
                self.config.backends.reasoning_injection_probability
            )

        raw_request_messages = request_dict.get("messages")
        request_messages: list[Any] | None = None
        if isinstance(raw_request_messages, list):
            request_messages = raw_request_messages

        is_first_turn = self._is_first_user_turn(
            processed_messages=processed_messages, request_messages=request_messages
        )

        if is_first_turn:
            use_reasoning = True
            logger.info(
                "Reasoning model injection decision: FORCE (first user turn), probability=%s",
                temp_reasoning_probability,
            )
        else:
            random_draw = random.random()
            use_reasoning = random_draw < temp_reasoning_probability
            logger.info(
                "Reasoning model injection decision: %s, probability=%s, draw=%.4f",
                "USE" if use_reasoning else "SKIP",
                temp_reasoning_probability,
                random_draw,
            )

        if use_reasoning:
            try:
                reasoning_result = await self._execute_reasoning_phase(
                    messages=processed_messages,
                    reasoning_backend=reasoning_backend,
                    reasoning_model=reasoning_model,
                    request_data=request_data,
                    identity=identity,
                    uri_params=reasoning_params,
                )
                reasoning_output = reasoning_result.text

                reasoning_time = time.time() - start_time
                client_reasoning = self._format_reasoning_for_client(
                    reasoning_output, reasoning_backend
                )
                has_reasoning_content = self._has_reasoning_content(client_reasoning)
                if not has_reasoning_content:
                    client_reasoning = ""

                logger.info(
                    "Reasoning phase completed: %s chars captured in %.2fs",
                    len(reasoning_output),
                    reasoning_time,
                    extra={
                        "session_id": session_id,
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "output_length": len(reasoning_output),
                        "duration_seconds": reasoning_time,
                        "tool_call_count": len(reasoning_result.tool_calls),
                    },
                )

                skip_execution_due_to_tool_call = (
                    not has_reasoning_content and reasoning_result.has_tool_calls()
                )
                if skip_execution_due_to_tool_call:
                    logger.info(
                        "[hybrid-backend] Skipping call to the execution model as reasoning model produced no reasoning output but a tool call",
                        extra={
                            "session_id": session_id,
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                            "tool_call_count": len(reasoning_result.tool_calls),
                        },
                    )
                    return self._build_tool_call_only_response(
                        tool_calls=reasoning_result.tool_calls,
                        request_dict=request_dict,
                        reasoning_backend=reasoning_backend,
                        reasoning_model=reasoning_model,
                    )

            except BackendError as exc:
                logger.error(
                    "Reasoning phase failed: %s",
                    exc.message,
                    extra={
                        "session_id": session_id,
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "error_code": exc.code,
                        "error": exc.message,
                    },
                )
                raise BackendError(
                    message=f"Hybrid backend error (reasoning phase): {exc.message}",
                    code="hybrid_reasoning_failed",
                    details={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "original_error": exc.code,
                    },
                ) from exc

        try:
            augmented_messages = self._augment_messages(
                messages=processed_messages,
                reasoning_output=reasoning_output,
                execution_backend=execution_backend,
            )

            logger.debug(
                "Messages augmented: %s -> %s messages",
                len(processed_messages),
                len(augmented_messages),
                extra={
                    "session_id": session_id,
                    "original_message_count": len(processed_messages),
                    "augmented_message_count": len(augmented_messages),
                    "reasoning_output_length": len(reasoning_output),
                },
            )

        except Exception as exc:
            logger.error(
                "Message augmentation failed: %s",
                exc,
                extra={
                    "session_id": session_id,
                    "execution_backend": execution_backend,
                    "reasoning_output_length": len(reasoning_output),
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to augment messages with reasoning: {exc}",
                code="hybrid_augmentation_failed",
                details={
                    "execution_backend": execution_backend,
                    "reasoning_output_length": len(reasoning_output),
                },
            ) from exc

        try:
            response = await self._execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend=execution_backend,
                execution_model=execution_model,
                identity=identity,
                reasoning_output_length=len(reasoning_output),
                uri_params=execution_params,
                **kwargs,
            )

            if isinstance(response, StreamingResponseEnvelope):
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Filtering reasoning tags from streaming response",
                        extra={
                            "session_id": session_id,
                            "execution_backend": execution_backend,
                            "execution_model": execution_model,
                        },
                    )
                response = await self._filter_response_stream(response)
                response = self._prepend_reasoning_chunk_to_stream(
                    response,
                    reasoning_output,
                    reasoning_backend,
                    reasoning_model,
                    formatted_reasoning=client_reasoning,
                )
            elif isinstance(response, ResponseEnvelope):
                logger.debug(
                    "Filtering reasoning tags from non-streaming response",
                    extra={
                        "session_id": session_id,
                        "execution_backend": execution_backend,
                        "execution_model": execution_model,
                    },
                )
                filtered_content = self._filter_response_content(response.content)
                response.content = self._prepend_reasoning_to_non_streaming_content(
                    filtered_content,
                    reasoning_output,
                    reasoning_backend,
                    reasoning_model,
                    formatted_reasoning=client_reasoning,
                )
                if client_reasoning:
                    if response.metadata is None:
                        response.metadata = {}
                    response.metadata.setdefault("reasoning", client_reasoning)
                    response.metadata.setdefault("reasoning_format", "hybrid_injected")
                    response.metadata.setdefault("reasoning_backend", reasoning_backend)
                    response.metadata.setdefault("reasoning_model", reasoning_model)

            total_time = time.time() - start_time
            execution_time = total_time - reasoning_time

            logger.info(
                "Hybrid request completed: total=%.2fs (reasoning=%.2fs, execution=%.2fs)",
                total_time,
                reasoning_time,
                execution_time,
                extra={
                    "session_id": session_id,
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "total_duration_seconds": total_time,
                    "reasoning_duration_seconds": reasoning_time,
                    "execution_duration_seconds": execution_time,
                    "reasoning_output_length": len(reasoning_output),
                },
            )

            return response

        except BackendError as exc:
            logger.error(
                "Execution phase failed: %s",
                exc.message,
                extra={
                    "session_id": session_id,
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "error_code": exc.code,
                    "error": exc.message,
                },
            )
            raise BackendError(
                message=f"Hybrid backend error (execution phase): {exc.message}",
                code="hybrid_execution_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "original_error": exc.code,
                },
            ) from exc

        except AuthenticationError:
            raise

        except Exception as exc:
            logger.error(
                "Hybrid backend failed with unexpected error: %s",
                type(exc).__name__,
                extra={
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Hybrid backend execution failed: {exc}",
                code="hybrid_execution_unexpected_error",
                details={
                    "error_type": type(exc).__name__,
                    "session_id": session_id,
                },
            ) from exc
