"""
Hybrid backend connector - orchestrates two-phase LLM interactions.

This connector implements a hybrid approach where:
1. A reasoning model generates chain-of-thought reasoning
2. The reasoning is captured and injected into the execution model's context
3. The execution model generates the final response with enhanced context
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.base import LLMBackend
from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
    get_reasoning_tags,
    supports_system_messages,
)
from src.connectors.utils.reasoning_stream_processor import (
    ReasoningStreamProcessor,
)
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Timeout constants
REASONING_PHASE_TIMEOUT = 60.0  # seconds
EXECUTION_PHASE_TIMEOUT = 120.0  # seconds


class HybridConnector(LLMBackend):
    """LLMBackend implementation for hybrid two-phase reasoning approach."""

    backend_type: str = "hybrid"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        backend_registry: BackendRegistry | None = None,
    ) -> None:
        """Initialize the hybrid connector.

        Args:
            client: HTTP client for API calls
            config: Application configuration
            translation_service: Service for translating between formats
            backend_registry: Registry to resolve backend connectors
        """
        super().__init__(config=config)
        self.client = client
        self.config = config
        self.translation_service = translation_service
        self._backend_registry = backend_registry

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the hybrid backend.

        Note:
            Reasoning and execution models are specified per-request in the model field,
            not during initialization.

        Args:
            **kwargs: Additional configuration (unused for hybrid backend)

        Raises:
            ConfigurationError: If hybrid backend is disabled in configuration
        """
        # Import backend_registry if not provided in constructor
        if self._backend_registry is None:
            from src.core.services.backend_registry import backend_registry

            self._backend_registry = backend_registry

        # Check if hybrid backend is disabled
        if (
            hasattr(self.config, "backends")
            and hasattr(self.config.backends, "disable_hybrid_backend")
            and self.config.backends.disable_hybrid_backend
        ):
            logger.warning("Hybrid backend is disabled in configuration")

        logger.info("Hybrid backend initialized successfully")

    def _parse_hybrid_model_spec(self, model_spec: str) -> tuple[str, str, str, str]:
        """Parse hybrid model specification.

        Args:
            model_spec: Format "hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]"
                       Example: "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"

        Returns:
            Tuple of (reasoning_backend, reasoning_model, execution_backend, execution_model)

        Raises:
            ValueError: If format is invalid or incomplete with descriptive messages and examples
        """
        # Remove "hybrid:" prefix if present
        if model_spec.startswith("hybrid:"):
            model_spec = model_spec[7:]

        # Check for brackets
        if not model_spec.startswith("[") or not model_spec.endswith("]"):
            raise ValueError(
                "Invalid hybrid model format. Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]. "
                "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            )

        # Remove brackets
        model_spec = model_spec[1:-1]

        # Split by comma
        parts = model_spec.split(",")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid hybrid model format. Expected exactly 2 models separated by comma, got {len(parts)}. "
                "Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]. "
                "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            )

        reasoning_spec = parts[0].strip()
        execution_spec = parts[1].strip()

        # Parse reasoning model spec
        reasoning_parts = reasoning_spec.split(":")
        if len(reasoning_parts) != 2:
            raise ValueError(
                f"Invalid reasoning model specification: '{reasoning_spec}'. "
                "Expected format: backend:model. "
                "Example: minimax:MiniMax-M2"
            )

        reasoning_backend = reasoning_parts[0].strip()
        reasoning_model = reasoning_parts[1].strip()

        if not reasoning_backend or not reasoning_model:
            raise ValueError(
                f"Incomplete reasoning model specification: '{reasoning_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: minimax:MiniMax-M2"
            )

        # Parse execution model spec
        execution_parts = execution_spec.split(":")
        if len(execution_parts) != 2:
            raise ValueError(
                f"Invalid execution model specification: '{execution_spec}'. "
                "Expected format: backend:model. "
                "Example: qwen-oauth:qwen3-coder-plus"
            )

        execution_backend = execution_parts[0].strip()
        execution_model = execution_parts[1].strip()

        if not execution_backend or not execution_model:
            raise ValueError(
                f"Incomplete execution model specification: '{execution_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: qwen-oauth:qwen3-coder-plus"
            )

        logger.debug(
            f"Parsed hybrid model spec: reasoning={reasoning_backend}:{reasoning_model}, "
            f"execution={execution_backend}:{execution_model}"
        )

        return reasoning_backend, reasoning_model, execution_backend, execution_model

    def _apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend: str,
        enable_reasoning: bool,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply reasoning parameters based on backend and phase.

        Args:
            request_data: Original request data (domain model, DTO, or dict)
            backend: Backend name
            enable_reasoning: True for reasoning phase, False for execution phase

        Returns:
            Request data with overridden reasoning parameters (same type as input)
        """
        # Get appropriate parameters based on phase
        if enable_reasoning:
            params = get_reasoning_params(backend)
            phase_name = "reasoning"
        else:
            params = get_execution_params(backend)
            phase_name = "execution"

        # If no parameters to override, return original
        if not params:
            return request_data

        # Handle domain models with model_copy
        if hasattr(request_data, "model_copy"):
            # Pydantic model - use model_copy to create a new instance with updates
            for key, value in params.items():
                old_value = getattr(request_data, key, None)
                if old_value != value:
                    logger.debug(
                        f"Overriding {key}: {old_value} -> {value} for {backend} ({phase_name} phase)"
                    )
            return request_data.model_copy(update=params)

        # Handle dicts
        elif isinstance(request_data, dict):
            request_copy = dict(request_data)
            for key, value in params.items():
                old_value = request_copy.get(key)
                request_copy[key] = value
                if old_value != value:
                    logger.debug(
                        f"Overriding {key}: {old_value} -> {value} for {backend} ({phase_name} phase)"
                    )
            return request_copy

        # Handle dataclasses
        elif is_dataclass(request_data) and not isinstance(request_data, type):
            request_dict = asdict(request_data)
            for key, value in params.items():
                old_value = request_dict.get(key)
                request_dict[key] = value
                if old_value != value:
                    logger.debug(
                        f"Overriding {key}: {old_value} -> {value} for {backend} ({phase_name} phase)"
                    )
            # Return as dict since we can't easily reconstruct the dataclass
            return request_dict

        # Fallback: return original
        return request_data

    def _supports_system_messages(self, backend: str) -> bool:
        """Check if backend supports system messages.

        Args:
            backend: Backend name

        Returns:
            True if backend supports system role messages
        """
        return supports_system_messages(backend)

    def _format_reasoning_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning with model-specific tags.

        Args:
            reasoning_output: Raw reasoning text
            backend: Backend name for format selection

        Returns:
            Formatted reasoning with appropriate tags
        """
        opening_tag, closing_tag = get_reasoning_tags(backend)
        return f"{opening_tag}\n{reasoning_output}\n{closing_tag}"

    def _inject_as_system_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as system message.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name for tag formatting

        Returns:
            Messages with reasoning in system message
        """
        import copy

        messages_copy = copy.deepcopy(messages)

        # Format reasoning with appropriate tags
        formatted_reasoning = self._format_reasoning_for_model(
            reasoning_output, execution_backend
        )

        # Create system message content
        system_content = (
            "Consider this reasoning when formulating your response:\n\n"
            f"{formatted_reasoning}"
        )

        # Check if there's already a system message
        has_system_message = False
        for i, msg in enumerate(messages_copy):
            if isinstance(msg, dict) and msg.get("role") == "system":
                # Augment existing system message
                messages_copy[i]["content"] = f"{msg['content']}\n\n{system_content}"
                has_system_message = True
                break

        # If no system message exists, create one at the beginning
        if not has_system_message:
            system_message = {"role": "system", "content": system_content}
            messages_copy.insert(0, system_message)

        return messages_copy

    def _inject_to_user_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as prefix to first user message.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name for tag formatting

        Returns:
            Messages with reasoning prepended to first user message
        """
        import copy

        messages_copy = copy.deepcopy(messages)

        # Format reasoning with appropriate tags
        formatted_reasoning = self._format_reasoning_for_model(
            reasoning_output, execution_backend
        )

        # Find first user message
        for i, msg in enumerate(messages_copy):
            if isinstance(msg, dict) and msg.get("role") == "user":
                # Prepend reasoning to user message
                original_content = msg.get("content", "")
                messages_copy[i][
                    "content"
                ] = f"{formatted_reasoning}\n\n{original_content}"
                break

        return messages_copy

    def _augment_messages(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Augment messages with reasoning using adaptive placement strategy.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name to determine capability

        Returns:
            New message list with reasoning injected appropriately
        """
        # Handle edge case: empty messages
        if not messages:
            logger.warning("Empty message list provided for augmentation")
            return messages

        # Check if execution backend supports system messages
        if self._supports_system_messages(execution_backend):
            # Primary strategy: inject as system message
            logger.debug(f"Using system message injection for {execution_backend}")
            return self._inject_as_system_message(
                messages, reasoning_output, execution_backend
            )
        else:
            # Fallback strategy: inject to user message
            logger.debug(f"Using user message prefix injection for {execution_backend}")
            return self._inject_to_user_message(
                messages, reasoning_output, execution_backend
            )

    def _strip_reasoning_tags(self, content: str) -> str:
        """Strip reasoning tags from content.

        Args:
            content: Content that may contain reasoning tags

        Returns:
            Content with reasoning tags and their content removed
        """
        import re

        # Define all possible reasoning tag patterns
        reasoning_patterns = [
            r"<thinking>.*?</thinking>",
            r"<think>.*?</think>",
            r"<reasoning>.*?</reasoning>",
            r"<reason>.*?</reason>",
        ]

        # Remove all reasoning tag patterns (case-insensitive, dotall for multiline)
        cleaned_content = content
        for pattern in reasoning_patterns:
            cleaned_content = re.sub(
                pattern, "", cleaned_content, flags=re.DOTALL | re.IGNORECASE
            )

        # Also remove the instruction prefix if present
        instruction_pattern = (
            r"Consider this reasoning when formulating your response:\s*"
        )
        cleaned_content = re.sub(
            instruction_pattern, "", cleaned_content, flags=re.IGNORECASE
        )

        return cleaned_content

    def _filter_response_content(self, content: Any) -> Any:
        """Filter reasoning tags from response content.

        This method handles various content types and ensures reasoning
        tags are removed from all parts of the response, including tool calls.

        Args:
            content: Response content (can be string, dict, or bytes)

        Returns:
            Filtered content with reasoning tags removed
        """

        # Handle bytes content (SSE chunks)
        if isinstance(content, bytes):
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:
                # If we can't decode, return as-is
                return content
        elif isinstance(content, str):
            content_str = content
        elif isinstance(content, dict):
            return self._filter_json_content(content)
        elif isinstance(content, list):
            return [self._filter_response_content(item) for item in content]
        else:
            # For other types, return as-is
            return content

        # Check if this is an SSE data line
        if content_str.startswith("data: "):
            data_part = content_str[6:].strip()

            # Skip [DONE] markers
            if data_part == "[DONE]":
                return content

            try:
                # Parse the JSON data
                data = json.loads(data_part)

                # Filter the JSON payload recursively
                cleaned = self._filter_json_content(data)

                # Reconstruct the SSE line
                filtered_data = json.dumps(cleaned, ensure_ascii=False)
                return (
                    f"data: {filtered_data}\n\n".encode()
                    if isinstance(content, bytes)
                    else f"data: {filtered_data}\n\n"
                )

            except json.JSONDecodeError:
                # If we can't parse JSON, just strip tags from the string
                filtered_str = self._strip_reasoning_tags(content_str)
                return (
                    filtered_str.encode("utf-8")
                    if isinstance(content, bytes)
                    else filtered_str
                )

        # For non-SSE content, just strip tags
        filtered_str = self._strip_reasoning_tags(content_str)
        return (
            filtered_str.encode("utf-8") if isinstance(content, bytes) else filtered_str
        )

    def _filter_json_content(self, data: Any) -> Any:
        """Recursively remove reasoning content from JSON-like structures."""

        if isinstance(data, dict):
            filtered: dict[str, Any] = {}
            for key, value in data.items():
                if key == "reasoning_content":
                    continue
                filtered[key] = self._filter_json_content(value)
            return filtered

        if isinstance(data, list):
            return [self._filter_json_content(item) for item in data]

        if isinstance(data, str):
            return self._strip_reasoning_tags(data)

        return data

    async def _filter_response_stream(
        self, response: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Filter reasoning tags from streaming response.

        Args:
            response: Original streaming response from execution model

        Returns:
            Filtered streaming response with reasoning tags removed
        """

        async def filtered_stream():
            """Generator that filters each chunk of the response stream."""
            if response.content is None:
                return

            async for chunk in response.content:
                # Filter the content
                filtered_content = self._filter_response_content(chunk.content)

                # Create new ProcessedResponse with filtered content
                filtered_chunk = ProcessedResponse(
                    content=filtered_content,
                    usage=chunk.usage,
                    metadata=chunk.metadata,
                )

                yield filtered_chunk

        # Return new StreamingResponseEnvelope with filtered stream
        return StreamingResponseEnvelope(
            content=filtered_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )

    @staticmethod
    def _truncate_after_reasoning_close(reasoning_output: str) -> str:
        """Trim reasoning output so that only the thinking segment remains."""

        closing_tags = ["</think>", "</thinking>", "</reason>", "</reasoning>"]
        for tag in closing_tags:
            index = reasoning_output.find(tag)
            if index != -1:
                return reasoning_output[: index + len(tag)]
        return reasoning_output

    def _format_reasoning_for_client(
        self,
        reasoning_output: str,
        reasoning_backend: str,
    ) -> str:
        """Prepare reasoning text for client consumption with native tags."""

        if not reasoning_output:
            return ""

        truncated = self._truncate_after_reasoning_close(reasoning_output)
        trimmed = truncated.rstrip()

        if not trimmed:
            return ""

        opening_tag, closing_tag = get_reasoning_tags(reasoning_backend)
        if opening_tag in trimmed and closing_tag in trimmed:
            return trimmed

        return f"{opening_tag}\n{trimmed}\n{closing_tag}"

    def _build_reasoning_stream_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> ProcessedResponse | None:
        """Create a processed response chunk that surfaces reasoning to clients."""

        formatted_reasoning = self._format_reasoning_for_client(
            reasoning_output, reasoning_backend
        )
        if not formatted_reasoning:
            return None

        payload = {
            "id": f"hybrid-reasoning-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"{reasoning_backend}:{reasoning_model}",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": formatted_reasoning,
                    },
                    "finish_reason": None,
                }
            ],
        }

        sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return ProcessedResponse(
            content=sse_payload,
            usage=None,
            metadata={
                "hybrid_phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
            },
        )

    def _prepend_reasoning_chunk_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> StreamingResponseEnvelope:
        """Inject the reasoning chunk ahead of the execution stream."""

        reasoning_chunk = self._build_reasoning_stream_chunk(
            reasoning_output, reasoning_backend, reasoning_model
        )
        if reasoning_chunk is None:
            return response

        original_stream = response.content

        async def combined_stream():
            yield reasoning_chunk
            if original_stream is None:
                return
            async for chunk in original_stream:
                yield chunk

        return StreamingResponseEnvelope(
            content=combined_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )

    @staticmethod
    def _join_reasoning_with_text(reasoning: str, existing: str | None) -> str:
        """Combine reasoning text with existing assistant message content."""

        if not existing:
            return reasoning
        if reasoning.endswith("\n") or existing.startswith("\n"):
            return f"{reasoning}{existing}"
        return f"{reasoning}\n{existing}"

    def _prepend_reasoning_to_non_streaming_content(
        self,
        content: Any,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> Any:
        """Attach reasoning output to non-streaming responses."""

        formatted_reasoning = self._format_reasoning_for_client(
            reasoning_output, reasoning_backend
        )
        if not formatted_reasoning:
            return content

        if isinstance(content, bytes):
            try:
                existing_text = content.decode("utf-8")
            except UnicodeDecodeError:
                return content
            combined = self._join_reasoning_with_text(
                formatted_reasoning, existing_text
            )
            return combined.encode("utf-8")

        if isinstance(content, str):
            return self._join_reasoning_with_text(formatted_reasoning, content)

        if isinstance(content, dict):
            updated = deepcopy(content)
            choices = updated.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue

                    message = choice.get("message")
                    if isinstance(message, dict):
                        existing = message.get("content")
                        if existing is None:
                            message["content"] = formatted_reasoning
                        elif isinstance(existing, str):
                            message["content"] = self._join_reasoning_with_text(
                                formatted_reasoning, existing
                            )
                        continue

                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        existing_delta_content = delta.get("content")
                        if existing_delta_content is None:
                            delta["content"] = formatted_reasoning
                        elif isinstance(existing_delta_content, str):
                            delta["content"] = self._join_reasoning_with_text(
                                formatted_reasoning, existing_delta_content
                            )
            return updated

        return content

    async def _execute_reasoning_phase(
        self,
        messages: list,
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
    ) -> str:
        """Execute reasoning phase and capture output.

        Args:
            messages: Original message history
            reasoning_backend: Backend name for reasoning model
            reasoning_model: Model name for reasoning
            request_data: Original request data
            identity: Optional identity configuration

        Returns:
            Extracted reasoning output as string

        Raises:
            BackendError: If reasoning model call fails (HTTP 502)
        """
        import asyncio

        logger.info(
            f"Starting reasoning phase with {reasoning_backend}:{reasoning_model}"
        )

        # Resolve reasoning backend connector from registry
        if self._backend_registry is None:
            logger.error("Backend registry not initialized for reasoning phase")
            raise BackendError(
                message="Backend registry not initialized",
                code="backend_registry_not_initialized",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            )

        try:
            # Use backend factory to properly create and initialize the backend
            from src.core.di.services import get_required_service
            from src.core.services.backend_factory import BackendFactory

            backend_factory_instance = get_required_service(BackendFactory)

            # Get backend config for reasoning backend
            reasoning_backend_config = None
            if hasattr(self.config, "backends"):
                with contextlib.suppress(AttributeError):
                    reasoning_backend_config = getattr(
                        self.config.backends, reasoning_backend
                    )

            # Use ensure_backend which properly handles API key initialization
            reasoning_connector = await backend_factory_instance.ensure_backend(
                reasoning_backend, self.config, reasoning_backend_config
            )

        except ValueError as e:
            logger.error(
                f"Reasoning backend '{reasoning_backend}' not found in registry",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error": str(e),
                },
            )
            raise BackendError(
                message=f"Reasoning backend '{reasoning_backend}' not found: {e}",
                code="reasoning_backend_not_found",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            ) from e
        except Exception as e:
            logger.error(
                f"Failed to initialize reasoning backend '{reasoning_backend}'",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to initialize reasoning backend: {e}",
                code="reasoning_backend_init_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            ) from e

        # Create request payload for reasoning model
        reasoning_request = self._apply_reasoning_params(
            request_data, reasoning_backend, enable_reasoning=True
        )

        # Ensure streaming is enabled for reasoning capture
        if hasattr(reasoning_request, "model_copy"):
            reasoning_request = reasoning_request.model_copy(update={"stream": True})
        elif isinstance(reasoning_request, dict):
            reasoning_request["stream"] = True
        else:
            # For other types, try to set attribute using setattr to avoid type errors
            with contextlib.suppress(AttributeError):
                reasoning_request.stream = True  # type: ignore[attr-defined]

        try:
            # Call reasoning model with timeout
            response = await asyncio.wait_for(
                reasoning_connector.chat_completions(
                    request_data=reasoning_request,
                    processed_messages=messages,
                    effective_model=reasoning_model,
                    identity=identity,
                ),
                timeout=REASONING_PHASE_TIMEOUT,
            )

            # Extract stream from response
            if isinstance(response, StreamingResponseEnvelope) and response.content:
                stream = response.content
            else:
                logger.error(
                    "Reasoning model did not return streaming response",
                    extra={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "response_type": type(response).__name__,
                    },
                )
                raise BackendError(
                    message="Reasoning model did not return streaming response",
                    code="reasoning_no_stream",
                    details={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "response_type": type(response).__name__,
                    },
                )

            # Use ReasoningStreamProcessor to capture reasoning output
            processor = ReasoningStreamProcessor()
            reasoning_text, reasoning_complete, metadata = (
                await processor.capture_reasoning_stream(stream)
            )

            # Cancel the stream if it has a cancel callback
            if hasattr(response, "cancel_callback") and response.cancel_callback:
                try:
                    await response.cancel_callback()
                    logger.debug(
                        "Reasoning stream cancelled successfully",
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                        },
                    )
                except Exception as e:
                    logger.debug(
                        f"Stream cancellation failed (non-fatal): {e}",
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                            "error": str(e),
                        },
                    )

            logger.info(
                f"Reasoning phase complete: {len(reasoning_text)} chars captured, "
                f"method={metadata.get('method')}, "
                f"chunks={metadata.get('chunks_processed')}"
            )

            return reasoning_text

        except asyncio.TimeoutError as e:
            # Handle timeout with partial reasoning fallback
            logger.warning(
                f"Reasoning phase timeout after {REASONING_PHASE_TIMEOUT}s, "
                f"attempting to use partial reasoning output",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "timeout_seconds": REASONING_PHASE_TIMEOUT,
                },
            )

            # If we have partial reasoning output from the processor, use it
            # Otherwise, raise the error
            raise BackendError(
                message=f"Reasoning phase timeout after {REASONING_PHASE_TIMEOUT}s",
                code="reasoning_timeout",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "timeout_seconds": REASONING_PHASE_TIMEOUT,
                },
            ) from e
        except BackendError:
            # Re-raise BackendError as-is (already has proper context)
            raise
        except Exception as e:
            logger.error(
                f"Reasoning phase failed with unexpected error: {type(e).__name__}",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Reasoning phase failed: {e}",
                code="reasoning_phase_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(e).__name__,
                },
            ) from e

    async def _execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list,
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        reasoning_output_length: int = 0,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute execution phase with augmented messages.

        Args:
            request_data: Original request data
            augmented_messages: Messages with reasoning appended
            execution_backend: Backend name for execution
            execution_model: Model name for execution
            identity: Optional identity configuration
            reasoning_output_length: Length of reasoning output for logging
            **kwargs: Additional arguments

        Returns:
            Response from execution model

        Raises:
            BackendError: If execution model call fails (HTTP 502)
        """
        logger.info(
            f"Starting execution phase with {execution_backend}:{execution_model}",
            extra={
                "phase": "execution",
                "execution_backend": execution_backend,
                "execution_model": execution_model,
                "reasoning_output_length": reasoning_output_length,
            },
        )

        # Resolve execution backend connector from registry
        if self._backend_registry is None:
            logger.error("Backend registry not initialized for execution phase")
            raise BackendError(
                message="Backend registry not initialized",
                code="backend_registry_not_initialized",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            )

        try:
            # Use backend factory to properly create and initialize the backend
            from src.core.di.services import get_required_service
            from src.core.services.backend_factory import BackendFactory

            backend_factory_instance = get_required_service(BackendFactory)

            # Get backend config for execution backend
            execution_backend_config = None
            if hasattr(self.config, "backends"):
                with contextlib.suppress(AttributeError):
                    execution_backend_config = getattr(
                        self.config.backends, execution_backend
                    )

            # Use ensure_backend which properly handles API key initialization
            execution_connector = await backend_factory_instance.ensure_backend(
                execution_backend, self.config, execution_backend_config
            )

        except ValueError as e:
            logger.error(
                f"Execution backend '{execution_backend}' not found in registry",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error": str(e),
                },
            )
            raise BackendError(
                message=f"Execution backend '{execution_backend}' not found: {e}",
                code="execution_backend_not_found",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            ) from e
        except Exception as e:
            logger.error(
                f"Failed to initialize execution backend '{execution_backend}'",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to initialize execution backend: {e}",
                code="execution_backend_init_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            ) from e

        # Create request payload with augmented messages
        execution_request = self._apply_reasoning_params(
            request_data, execution_backend, enable_reasoning=False
        )

        try:
            # Call execution model with augmented messages and timeout
            response = await asyncio.wait_for(
                execution_connector.chat_completions(
                    request_data=execution_request,
                    processed_messages=augmented_messages,
                    effective_model=execution_model,
                    identity=identity,
                    **kwargs,
                ),
                timeout=EXECUTION_PHASE_TIMEOUT,
            )

            logger.info(
                "Execution phase complete",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                },
            )

            return response

        except asyncio.TimeoutError as e:
            # Handle execution timeout
            logger.error(
                f"Execution phase timeout after {EXECUTION_PHASE_TIMEOUT}s",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "timeout_seconds": EXECUTION_PHASE_TIMEOUT,
                },
            )
            raise BackendError(
                message=f"Execution phase timeout after {EXECUTION_PHASE_TIMEOUT}s",
                code="execution_timeout",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "timeout_seconds": EXECUTION_PHASE_TIMEOUT,
                },
            ) from e

        except BackendError:
            # Re-raise BackendError as-is (already has proper context)
            raise
        except Exception as e:
            logger.error(
                f"Execution phase failed with unexpected error: {type(e).__name__}",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Execution phase failed: {e}",
                code="execution_phase_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error_type": type(e).__name__,
                },
            ) from e

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the two-phase hybrid completion.

        Args:
            request_data: Original request
            processed_messages: Messages after command processing
            effective_model: Format "hybrid:[backend:model,backend:model]"
            identity: Optional identity configuration
            **kwargs: Additional arguments

        Returns:
            StreamingResponseEnvelope with execution model's response

        Raises:
            ValueError: If model specification is invalid
            ConfigurationError: If hybrid backend is disabled
            BackendError: If either phase fails (HTTP 502)
        """
        start_time = time.time()

        # Extract session ID for logging if available
        session_id = None
        if identity and hasattr(identity, "session_id"):
            session_id = identity.session_id

        # Check if hybrid backend is disabled
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

        # Convert request_data to dict if needed
        if hasattr(request_data, "model_dump"):
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
            # Parse hybrid model specification
            (
                reasoning_backend,
                reasoning_model,
                execution_backend,
                execution_model,
            ) = self._parse_hybrid_model_spec(effective_model)

            # Log hybrid request initiation with session and model details
            logger.info(
                f"Hybrid request initiated: reasoning={reasoning_backend}:{reasoning_model}, "
                f"execution={execution_backend}:{execution_model}",
                extra={
                    "session_id": session_id,
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "message_count": len(processed_messages),
                    "stream": request_dict.get("stream", False),
                },
            )

        except ValueError as e:
            logger.error(
                f"Invalid hybrid model specification: {e}",
                extra={
                    "session_id": session_id,
                    "effective_model": effective_model,
                    "error": str(e),
                },
            )
            raise

        try:
            # Phase 1: Execute reasoning phase and capture output
            reasoning_output = await self._execute_reasoning_phase(
                messages=processed_messages,
                reasoning_backend=reasoning_backend,
                reasoning_model=reasoning_model,
                request_data=request_data,  # Pass original request_data, not dict
                identity=identity,
            )

            reasoning_time = time.time() - start_time

            # Log reasoning phase completion with output length and duration
            logger.info(
                f"Reasoning phase completed: {len(reasoning_output)} chars captured in {reasoning_time:.2f}s",
                extra={
                    "session_id": session_id,
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "output_length": len(reasoning_output),
                    "duration_seconds": reasoning_time,
                },
            )

        except BackendError as e:
            logger.error(
                f"Reasoning phase failed: {e.message}",
                extra={
                    "session_id": session_id,
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_code": e.code,
                    "error": e.message,
                },
            )
            raise BackendError(
                message=f"Hybrid backend error (reasoning phase): {e.message}",
                code="hybrid_reasoning_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "original_error": e.code,
                },
            ) from e

        try:
            # Phase 2: Augment messages with reasoning output
            augmented_messages = self._augment_messages(
                messages=processed_messages,
                reasoning_output=reasoning_output,
                execution_backend=execution_backend,
            )

            logger.debug(
                f"Messages augmented: {len(processed_messages)} -> {len(augmented_messages)} messages",
                extra={
                    "session_id": session_id,
                    "original_message_count": len(processed_messages),
                    "augmented_message_count": len(augmented_messages),
                    "reasoning_output_length": len(reasoning_output),
                },
            )

        except Exception as e:
            logger.error(
                f"Message augmentation failed: {e}",
                extra={
                    "session_id": session_id,
                    "execution_backend": execution_backend,
                    "reasoning_output_length": len(reasoning_output),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to augment messages with reasoning: {e}",
                code="hybrid_augmentation_failed",
                details={
                    "execution_backend": execution_backend,
                    "reasoning_output_length": len(reasoning_output),
                },
            ) from e

        try:
            # Phase 3: Execute execution phase with augmented messages
            response = await self._execute_execution_phase(
                request_data=request_data,  # Pass original request_data, not dict
                augmented_messages=augmented_messages,
                execution_backend=execution_backend,
                execution_model=execution_model,
                identity=identity,
                reasoning_output_length=len(reasoning_output),
                **kwargs,
            )

            # Phase 4: Filter reasoning tags from response
            if isinstance(response, StreamingResponseEnvelope):
                logger.debug(
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
                )

            total_time = time.time() - start_time
            execution_time = total_time - reasoning_time

            # Log execution phase completion with total duration
            logger.info(
                f"Hybrid request completed: total={total_time:.2f}s "
                f"(reasoning={reasoning_time:.2f}s, execution={execution_time:.2f}s)",
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

        except BackendError as e:
            logger.error(
                f"Execution phase failed: {e.message}",
                extra={
                    "session_id": session_id,
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "error_code": e.code,
                    "error": e.message,
                },
            )
            raise BackendError(
                message=f"Hybrid backend error (execution phase): {e.message}",
                code="hybrid_execution_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "original_error": e.code,
                },
            ) from e


# Register the hybrid backend
backend_registry.register_backend("hybrid", HybridConnector)
