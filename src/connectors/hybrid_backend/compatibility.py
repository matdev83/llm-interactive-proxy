"""Backward-compatibility wrapper methods for HybridConnector.

This module provides compatibility wrappers that delegate to the underlying
services/orchestrator. These methods are kept for backward compatibility with tests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.orchestration import HybridOrchestrator
    from src.core.config.app_config import AppConfig
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
    from src.core.interfaces.configuration_interface import IAppIdentityConfig
    from src.core.interfaces.model_bases import DomainModel, InternalDTO
    from src.core.services.translation_service import TranslationService

from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec
from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult

logger = logging.getLogger(__name__)


class HybridConnectorCompatibilityMixin:
    """Mixin providing backward-compatibility wrapper methods for HybridConnector.

    These methods delegate to the underlying services/orchestrator to maintain
    backward compatibility with existing tests.
    """

    # Type hints for mixin attributes (provided by HybridConnector)
    if TYPE_CHECKING:
        _orchestrator: HybridOrchestrator
        config: AppConfig
        translation_service: TranslationService

    def _parse_hybrid_model_spec(self, model_spec: str) -> HybridModelSpec:
        """Parse hybrid model specification (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ModelSpecParser.
        """
        return self._orchestrator.model_spec_parser.parse(model_spec)

    async def _execute_reasoning_phase(
        self,
        messages: list,
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> ReasoningPhaseResult:
        """Execute reasoning phase (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to PhaseExecutor.
        """
        return cast(
            ReasoningPhaseResult,
            await self._orchestrator.phase_executor.execute_reasoning_phase(
                messages=messages,
                reasoning_backend=reasoning_backend,
                reasoning_model=reasoning_model,
                request_data=request_data,
                identity=identity,
                uri_params=uri_params,
                session_id=session_id,  # Pass session_id for tag scoping (requirement 8.2)
            ),
        )

    async def _execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list,
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute execution phase (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to PhaseExecutor.
        """
        return cast(
            "ResponseEnvelope | StreamingResponseEnvelope",
            await self._orchestrator.phase_executor.execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend=execution_backend,
                execution_model=execution_model,
                identity=identity,
                uri_params=uri_params,
                **kwargs,
            ),
        )

    @staticmethod
    def _truncate_after_reasoning_close(reasoning_output: str) -> str:
        """Truncate after reasoning close (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ReasoningMarkupProcessor.
        """
        from src.connectors.hybrid_backend.services.reasoning_markup_processor import (
            ReasoningMarkupProcessor,
        )

        return ReasoningMarkupProcessor._truncate_after_reasoning_close(
            reasoning_output
        )

    def _format_reasoning_for_client(
        self,
        reasoning_output: str,
        reasoning_backend: str,
    ) -> str:
        """Format reasoning for client (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ReasoningMarkupProcessor.
        """
        from src.connectors.hybrid_backend.services.reasoning_markup_processor import (
            ReasoningMarkupProcessor,
        )

        processor = ReasoningMarkupProcessor()
        reasoning_text = processor.normalize(reasoning_output, reasoning_backend)
        return reasoning_text.plain

    def _augment_messages(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list[Any]:
        """Augment messages (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to MessageAugmentor.
        """
        return cast(
            list[Any],
            self._orchestrator.message_augmentor.augment(
                messages=messages,
                reasoning_output=reasoning_output,
                execution_backend=execution_backend,
            ),
        )

    def _strip_reasoning_tags(self, content: str) -> str:
        """Strip reasoning tags (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseFilter.
        """
        from src.connectors.hybrid_backend.services.response_filter import (
            ResponseFilter,
        )

        filter_service = ResponseFilter()
        return filter_service._strip_reasoning_tags(content)

    def _filter_response_content(self, content: Any) -> Any:
        """Filter response content (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseFilter.
        """
        return self._orchestrator.response_filter.filter_content(content)

    async def _filter_response_stream(
        self, response: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Filter response stream (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseFilter.
        """
        return cast(
            "StreamingResponseEnvelope",
            await self._orchestrator.response_filter.filter_stream(response),
        )

    def _build_tool_call_only_response(
        self,
        tool_calls: list[dict[str, Any]],
        request_dict: dict[str, Any],
        reasoning_backend: str,
        reasoning_model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Build tool call only response (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseBuilder.
        """
        return cast(
            "ResponseEnvelope | StreamingResponseEnvelope",
            self._orchestrator.response_builder.build_tool_call_response(
                tool_calls=tool_calls,
                request_dict=request_dict,
                backend=reasoning_backend,
                model=reasoning_model,
            ),
        )

    def _prepend_reasoning_chunk_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> StreamingResponseEnvelope:
        """Prepend reasoning chunk to stream (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseBuilder.
        """
        return cast(
            "StreamingResponseEnvelope",
            self._orchestrator.response_builder.prepend_reasoning_to_stream(
                response=response,
                reasoning_output=reasoning_output,
                reasoning_backend=reasoning_backend,
                reasoning_model=reasoning_model,
            ),
        )

    def _prepend_reasoning_to_non_streaming_content(
        self,
        content: Any,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> Any:
        """Prepend reasoning to non-streaming content (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It adds reasoning fields to dict content.
        """
        from copy import deepcopy

        if isinstance(content, bytes | str):
            return content

        if not isinstance(content, dict):
            return content

        updated = deepcopy(content)

        # Prepare reasoning texts
        from src.connectors.hybrid_backend.services.reasoning_markup_processor import (
            ReasoningMarkupProcessor,
        )

        processor = ReasoningMarkupProcessor()
        if formatted_reasoning:
            tagged = formatted_reasoning
            plain = processor.extract_plain_text(tagged)
        else:
            reasoning_text = processor.normalize(reasoning_output, reasoning_backend)
            tagged = reasoning_text.tagged
            plain = reasoning_text.plain

        if not plain or not tagged:
            return content

        # Add reasoning to choices if present
        choices = updated.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue

                message = choice.get("message")
                if isinstance(message, dict):
                    if "role" not in message:
                        message["role"] = "assistant"
                    message["reasoning"] = tagged
                    message["reasoning_content"] = plain
                    continue

                delta = choice.get("delta")
                if isinstance(delta, dict):
                    if "role" not in delta:
                        delta["role"] = "assistant"
                    delta["reasoning"] = tagged
                    delta["reasoning_content"] = plain
        else:
            # Add to metadata if no choices
            metadata = updated.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["reasoning"] = tagged
                metadata["reasoning_content"] = plain
                metadata.setdefault("reasoning_format", "hybrid_injected")

        return updated

    def _supports_system_messages(self, backend: str) -> bool:
        """Check if backend supports system messages (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        """
        from src.connectors.utils.model_capabilities import supports_system_messages

        return supports_system_messages(backend)

    def _format_reasoning_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning for model (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ReasoningMarkupProcessor.
        """
        from src.connectors.hybrid_backend.services.reasoning_markup_processor import (
            ReasoningMarkupProcessor,
        )

        processor = ReasoningMarkupProcessor()
        reasoning_text = processor.normalize(reasoning_output, backend)
        return reasoning_text.tagged if reasoning_text.plain else ""

    def _build_reasoning_stream_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> Any:
        """Build reasoning stream chunk (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ResponseBuilder.
        """
        return self._orchestrator.response_builder.build_reasoning_chunk(
            reasoning_output=reasoning_output,
            reasoning_backend=reasoning_backend,
            reasoning_model=reasoning_model,
        )

    def _resolve_backend_identity(
        self,
        backend: str,
        request_identity: IAppIdentityConfig | None,
        backend_config: Any = None,
    ) -> IAppIdentityConfig | None:
        """Resolve backend identity (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to IdentityResolver.
        """
        from src.connectors.hybrid_backend.infrastructure.identity_resolver import (
            IdentityResolver,
        )

        resolver = IdentityResolver(self.config)
        return resolver.resolve(
            backend=backend,
            request_identity=request_identity,
            backend_config=backend_config,
        )

    def _apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend_or_params: str | dict[str, Any],
        enable_reasoning: bool | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply reasoning params (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to ParameterApplicator.
        """
        from src.connectors.hybrid_backend.services.parameter_applicator import (
            ParameterApplicator,
        )
        from src.connectors.utils.model_capabilities import (
            get_execution_params,
            get_reasoning_params,
        )

        applicator = ParameterApplicator()

        if isinstance(backend_or_params, str):
            if enable_reasoning is None:
                raise TypeError(
                    "enable_reasoning flag is required when backend name is provided"
                )
            params = (
                get_reasoning_params(backend_or_params)
                if enable_reasoning
                else get_execution_params(backend_or_params)
            )
            params_dict = dict(params)
            # Log parameter overrides for backward compatibility with tests
            for key, value in params_dict.items():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Applying override {key}={value} to request")
            return applicator._apply_parameter_overrides(
                request_data=request_data,
                params=params_dict,
            )
        elif isinstance(backend_or_params, dict):
            # When params dict is provided directly, just apply it without backend lookup
            # Log parameter overrides for backward compatibility with tests
            for key, value in backend_or_params.items():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Applying override {key}={value} to request")
            return applicator._apply_parameter_overrides(
                request_data=request_data,
                params=backend_or_params,
            )
        else:
            raise TypeError(
                "backend_or_params must be a backend string or parameter dictionary"
            )

    def _prepare_backend_request(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        target_model: str,
        stream: bool,
        messages: list | None = None,
    ) -> Any:
        """Prepare backend request (backward-compatibility wrapper).

        This method is kept for backward compatibility with tests.
        It delegates to PhaseExecutor's internal preparation logic.
        """
        from dataclasses import asdict, is_dataclass

        from src.core.domain.chat import CanonicalChatRequest

        request_obj: Any = request_data

        if hasattr(request_obj, "model_copy"):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        elif isinstance(request_obj, dict):
            request_dict = dict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        elif is_dataclass(request_obj) and not isinstance(request_obj, type):
            request_dict = asdict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        else:
            raise TypeError(
                f"Unable to prepare backend request from type {type(request_obj).__name__}"
            )

        if not isinstance(request_obj, CanonicalChatRequest):
            request_obj = self.translation_service.to_domain_request(
                request_obj, "openai"
            )

        if messages is not None:
            request_obj = request_obj.model_copy(update={"messages": messages})

        # Remove session_id from extra_body to prevent session backend inheritance
        if request_obj.extra_body and isinstance(request_obj.extra_body, dict):
            keys_to_strip = {"session_id", "backend_type", "model"}
            cleaned_extra_body = {
                k: v
                for k, v in request_obj.extra_body.items()
                if k not in keys_to_strip
            }
            if len(cleaned_extra_body) != len(request_obj.extra_body):
                request_obj = request_obj.model_copy(
                    update={
                        "extra_body": cleaned_extra_body if cleaned_extra_body else None
                    }
                )

        return request_obj
