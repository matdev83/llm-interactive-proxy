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
import random
import re
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Any, cast

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
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    ServiceResolutionError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.domain.chat import CanonicalChatRequest
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Timeout constants
REASONING_PHASE_TIMEOUT = 60.0  # seconds
EXECUTION_PHASE_TIMEOUT = 120.0  # seconds


@dataclass
class ReasoningPhaseResult:
    """Container for reasoning phase outcome."""

    text: str
    complete: bool
    tool_calls: list[dict[str, Any]]
    raw_chunks: list[ProcessedResponse]
    media_type: str | None
    headers: dict[str, str] | None

    def has_tool_calls(self) -> bool:
        """Check whether reasoning produced any tool calls."""

        return bool(self.tool_calls)


class HybridConnector(LLMBackend):
    """LLMBackend implementation for hybrid two-phase reasoning approach."""

    backend_type: str = "hybrid"
    _LEADING_REASONING_TAG = re.compile(
        r"^\s*<\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*", re.IGNORECASE
    )
    _TRAILING_REASONING_TAG = re.compile(
        r"\s*<\s*/\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*$",
        re.IGNORECASE,
    )

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

    def _parse_hybrid_model_spec(
        self, model_spec: str
    ) -> tuple[str, str, dict[str, Any], str, str, dict[str, Any]]:
        """Parse hybrid model specification with optional URI parameters.

        Args:
            model_spec: Format "hybrid:[reasoning-backend:reasoning-model?params,execution-backend:execution-model?params]"
                       Example: "hybrid:[minimax:MiniMax-M2?temperature=0.8,qwen-oauth:qwen3-coder-plus?temperature=0.3]"

        Returns:
            Tuple of (reasoning_backend, reasoning_model, reasoning_params,
                     execution_backend, execution_model, execution_params)

        Raises:
            ValueError: If format is invalid or incomplete with descriptive messages and examples
        """
        from src.core.domain.model_utils import parse_model_with_params

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

        # Split by comma - need to be careful with commas in query strings
        # Strategy: Split by comma, but track if we're inside a query string
        # A comma inside a query string (after ?) should not split the models
        # We need to find the comma that separates the two model specs
        parts = []
        current_part: list[str] = []

        i = 0
        while i < len(model_spec):
            char = model_spec[i]

            # Check if this is a comma that separates models
            # It should be a comma that's not part of a query string
            if char == ",":
                # Look back to see if we're in a query string
                # A comma is a separator if there's no '?' before it in the current part
                # or if there's a complete backend:model before it
                current_str = "".join(current_part)

                # Check if we have a complete model spec (backend:model with optional ?params)
                # by checking if there's a colon before any question mark
                has_colon = ":" in current_str
                current_str.find("?")

                if has_colon:
                    # This looks like a complete model spec, so this comma is a separator
                    parts.append(current_str)
                    current_part = []
                    i += 1
                    continue

            current_part.append(char)
            i += 1

        # Add the last part
        if current_part:
            parts.append("".join(current_part))

        if len(parts) != 2:
            raise ValueError(
                f"Invalid hybrid model format. Expected exactly 2 models separated by comma, got {len(parts)}. "
                "Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]. "
                "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            )

        reasoning_spec = parts[0].strip()
        execution_spec = parts[1].strip()

        # Parse reasoning model spec with URI parameters
        try:
            reasoning_backend, reasoning_model, reasoning_params = (
                parse_model_with_params(reasoning_spec)
            )
        except Exception as e:
            # Log warning about parsing failure but provide helpful error message
            logger.warning(
                f"Failed to parse reasoning model specification '{reasoning_spec}': {e}. "
                f"Attempting to continue with fallback parsing."
            )
            raise ValueError(
                f"Invalid reasoning model specification: '{reasoning_spec}'. "
                f"Error: {e}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: minimax:MiniMax-M2?temperature=0.8"
            ) from e

        reasoning_backend = reasoning_backend.strip()
        reasoning_model = reasoning_model.strip()

        if not reasoning_backend or not reasoning_model:
            raise ValueError(
                f"Incomplete reasoning model specification: '{reasoning_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: minimax:MiniMax-M2"
            )

        # Parse execution model spec with URI parameters
        try:
            execution_backend, execution_model, execution_params = (
                parse_model_with_params(execution_spec)
            )
        except Exception as e:
            # Log warning about parsing failure but provide helpful error message
            logger.warning(
                f"Failed to parse execution model specification '{execution_spec}': {e}. "
                f"Attempting to continue with fallback parsing."
            )
            raise ValueError(
                f"Invalid execution model specification: '{execution_spec}'. "
                f"Error: {e}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: qwen-oauth:qwen3-coder-plus?temperature=0.3"
            ) from e

        execution_backend = execution_backend.strip()
        execution_model = execution_model.strip()

        if not execution_backend or not execution_model:
            raise ValueError(
                f"Incomplete execution model specification: '{execution_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: qwen-oauth:qwen3-coder-plus"
            )

        logger.debug(
            f"Parsed hybrid model spec: reasoning={reasoning_backend}:{reasoning_model} (params={reasoning_params}), "
            f"execution={execution_backend}:{execution_model} (params={execution_params})"
        )

        return (
            reasoning_backend,
            reasoning_model,
            reasoning_params,
            execution_backend,
            execution_model,
            execution_params,
        )

    def _apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend_or_params: str | dict[str, Any],
        enable_reasoning: bool | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply backend-specific reasoning parameters to the request.

        This method supports both legacy usage where a backend name is provided
        alongside the ``enable_reasoning`` flag, as well as direct parameter
        dictionaries (used in certain integration tests).
        """

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
        elif isinstance(backend_or_params, dict):
            params = backend_or_params
        else:
            raise TypeError(
                "backend_or_params must be a backend string or parameter dictionary"
            )

        return self._apply_parameter_overrides(request_data, params)

    def _apply_parameter_overrides(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        params: dict[str, Any],
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply a parameter dictionary to the request data."""

        # If no parameters to override, return original
        if not params:
            return request_data

        # Log the overrides
        for key, value in params.items():
            logger.debug(f"Applying override {key}={value} to request")

        # Handle Pydantic models (includes CanonicalChatRequest)
        if isinstance(request_data, DomainModel):
            # Ensure extra_body is a mutable dict
            current_extra_body = getattr(request_data, "extra_body", None)
            new_extra_body = dict(current_extra_body) if current_extra_body else {}

            # Apply overrides
            new_extra_body.update(params)

            # Strip hybrid routing hints that would confuse downstream connectors
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)

            return request_data.model_copy(
                update={
                    "extra_body": new_extra_body if new_extra_body else None,
                    **params,
                }
            )

        # Handle dicts
        elif isinstance(request_data, dict):
            request_copy = dict(request_data)
            # Ensure extra_body exists and is a mutable dict
            current_extra_body = request_copy.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )

            # Apply overrides
            new_extra_body.update(params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_copy["extra_body"] = new_extra_body if new_extra_body else None

            # Expose overrides at the top level for compatibility
            request_copy.update(params)

            return request_copy

        # Handle dataclasses
        elif is_dataclass(request_data) and not isinstance(request_data, type):
            request_dict = asdict(request_data)
            # Ensure extra_body exists and is a mutable dict
            current_extra_body = request_dict.get("extra_body")
            new_extra_body = (
                dict(current_extra_body) if isinstance(current_extra_body, dict) else {}
            )

            # Apply overrides
            new_extra_body.update(params)
            for drop_key in ("backend_type", "model"):
                new_extra_body.pop(drop_key, None)
            request_dict["extra_body"] = new_extra_body if new_extra_body else None

            # Merge overrides into the dataclass representation
            request_dict.update(params)

            # Return as dict since we can't easily reconstruct the dataclass
            return request_dict
        # Fallback: return original if type is not supported
        logger.warning(
            f"Unsupported request_data type in _apply_reasoning_params: {type(request_data).__name__}"
        )
        return request_data

    def _resolve_backend_identity(
        self,
        backend: str,
        request_identity: IAppIdentityConfig | None,
        backend_config: Any = None,
    ) -> IAppIdentityConfig | None:
        """Resolve identity configuration for backend calls.

        Preference order:
        1. Backend-specific identity provided via backend_config or AppConfig.backends
        2. Identity attached to the current request
        3. Global application identity
        """

        if backend_config is not None and getattr(backend_config, "identity", None):
            return cast(IAppIdentityConfig, backend_config.identity)

        backend_identity = None
        if hasattr(self.config, "backends"):
            with contextlib.suppress(AttributeError):
                backend_settings = getattr(self.config.backends, backend)
                backend_identity = getattr(backend_settings, "identity", None)
        if backend_identity is not None:
            return cast(IAppIdentityConfig, backend_identity)

        if request_identity is not None:
            return request_identity

        return getattr(self.config, "identity", None)

    def get_reasoning_params(self, backend: str = "openai") -> dict[str, Any]:
        """Expose reasoning parameter presets for tests and diagnostics."""

        return get_reasoning_params(backend)

    def get_execution_params(self, backend: str = "openai") -> dict[str, Any]:
        """Expose execution parameter presets for tests and diagnostics."""

        return get_execution_params(backend)

    def _supports_system_messages(self, backend: str) -> bool:
        """Check if backend supports system messages.

        Args:
            backend: Backend name

        Returns:
            True if backend supports system role messages
        """
        return supports_system_messages(backend)

    @staticmethod
    def _assemble_reasoning_markup(
        opening_tag: str, closing_tag: str, body: str
    ) -> str:
        """Rebuild reasoning text with canonical tags."""

        if not body:
            return f"{opening_tag}{closing_tag}"

        if "\n" in body or body.startswith("<"):
            return f"{opening_tag}\n{body}\n{closing_tag}"

        return f"{opening_tag}{body}{closing_tag}"

    def _normalize_reasoning_markup(
        self, reasoning_output: str, opening_tag: str, closing_tag: str
    ) -> str:
        """Normalize reasoning markup to use canonical tags and ensure closure."""

        truncated = self._truncate_after_reasoning_close(reasoning_output)
        stripped = truncated.strip()
        if not stripped:
            return stripped

        leading_match = self._LEADING_REASONING_TAG.match(stripped)
        body_start = leading_match.end() if leading_match else 0
        body_section = stripped[body_start:]

        trailing_match = self._TRAILING_REASONING_TAG.search(body_section)
        if trailing_match:
            body_end = trailing_match.start()
            body_section = body_section[:body_end]

        body = body_section.strip()
        return self._assemble_reasoning_markup(opening_tag, closing_tag, body)

    def _apply_reasoning_tag_wrapping(
        self, reasoning_output: str, opening_tag: str, closing_tag: str
    ) -> str:
        """Wrap or normalize reasoning output using backend-specific tags."""

        return self._normalize_reasoning_markup(
            reasoning_output, opening_tag, closing_tag
        )

    @staticmethod
    def _extract_reasoning_inner_text(text: str) -> str:
        """Strip XML-like tags and return inner text for reasoning payloads."""

        if not text:
            return ""

        return re.sub(r"<[^>]+>", "", text).strip()

    def _has_reasoning_content(self, formatted_reasoning: str) -> bool:
        """Determine whether the formatted reasoning contains substantive text."""

        return bool(self._extract_reasoning_inner_text(formatted_reasoning))

    def _prepare_reasoning_texts(
        self, reasoning_output: str, backend: str
    ) -> tuple[str, str]:
        """Return backend-tagged reasoning and plain text representations."""

        if not reasoning_output:
            return "", ""

        opening_tag, closing_tag = get_reasoning_tags(backend)
        tagged = self._apply_reasoning_tag_wrapping(
            reasoning_output, opening_tag, closing_tag
        ).strip()

        plain = self._extract_reasoning_inner_text(tagged)
        if not plain:
            return "", ""

        return tagged, plain

    def _format_reasoning_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning with model-specific tags.

        Args:
            reasoning_output: Raw reasoning text
            backend: Backend name for format selection

        Returns:
            Formatted reasoning with appropriate tags
        """
        tagged, plain = self._prepare_reasoning_texts(reasoning_output, backend)
        return tagged if plain else ""

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
        if not formatted_reasoning:
            return messages_copy

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
        if not formatted_reasoning:
            return messages_copy

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
            augmented_messages = self._inject_as_system_message(
                messages, reasoning_output, execution_backend
            )
        else:
            # Fallback strategy: inject to user message
            logger.debug(f"Using user message prefix injection for {execution_backend}")
            augmented_messages = self._inject_to_user_message(
                messages, reasoning_output, execution_backend
            )

        if self.config.backends.hybrid_backend_repeat_messages:
            formatted_reasoning = self._format_reasoning_for_model(
                reasoning_output, execution_backend
            )
            if formatted_reasoning:
                augmented_messages.append(
                    {"role": "assistant", "content": formatted_reasoning}
                )
        return augmented_messages

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

        _, plain_text = self._prepare_reasoning_texts(
            reasoning_output, reasoning_backend
        )
        return plain_text

    def _build_reasoning_stream_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> ProcessedResponse | None:
        """Create a processed response chunk that surfaces reasoning to clients."""

        formatted = (
            formatted_reasoning.strip()
            if formatted_reasoning
            and "<" in formatted_reasoning
            and ">" in formatted_reasoning
            else ""
        )
        if not formatted:
            formatted, plain_reasoning = self._prepare_reasoning_texts(
                reasoning_output, reasoning_backend
            )
        else:
            plain_reasoning = self._extract_reasoning_inner_text(formatted)

        if formatted_reasoning and formatted_reasoning.strip() and not formatted:
            # formatted_reasoning provided but lacked tags; reuse for plain text
            plain_reasoning = formatted_reasoning.strip()
            formatted, _ = self._prepare_reasoning_texts(
                reasoning_output, reasoning_backend
            )
            if not formatted:
                formatted = formatted_reasoning.strip()

        if not plain_reasoning:
            return None

        delta_payload: dict[str, Any] = {
            "role": "assistant",
            "reasoning": formatted,
            "reasoning_content": plain_reasoning,
            "content": "",
        }

        payload = {
            "id": f"hybrid-reasoning-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"{reasoning_backend}:{reasoning_model}",
            "choices": [
                {
                    "index": 0,
                    "delta": delta_payload,
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

    def _build_tool_call_only_response(
        self,
        tool_calls: list[dict[str, Any]],
        request_dict: dict[str, Any],
        reasoning_backend: str,
        reasoning_model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Construct a response that forwards tool calls without execution."""

        stream_requested = bool(request_dict.get("stream", False))
        created_ts = int(time.time())
        model_name = f"{reasoning_backend}:{reasoning_model}"

        if stream_requested:
            payload = {
                "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            done_payload = "data: [DONE]\n\n"

            async def tool_call_stream():
                yield ProcessedResponse(
                    content=sse_payload,
                    metadata={
                        "hybrid_phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "skipped_execution": True,
                    },
                )
                yield ProcessedResponse(
                    content=done_payload,
                    metadata={"is_done": True},
                )

            return StreamingResponseEnvelope(
                content=tool_call_stream(),
                media_type="text/event-stream",
            )

        response_content = {
            "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        return ResponseEnvelope(
            content=response_content,
            metadata={
                "hybrid_phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
                "skipped_execution": True,
            },
        )

    def _prepend_reasoning_chunk_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> StreamingResponseEnvelope:
        """Inject the reasoning chunk ahead of the execution stream."""

        reasoning_chunk = self._build_reasoning_stream_chunk(
            reasoning_output,
            reasoning_backend,
            reasoning_model,
            formatted_reasoning=formatted_reasoning,
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

    def _prepend_reasoning_to_non_streaming_content(
        self,
        content: Any,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> Any:
        """Attach reasoning output to non-streaming responses."""

        tagged, plain = self._prepare_reasoning_texts(
            reasoning_output, reasoning_backend
        )
        if formatted_reasoning:
            candidate = formatted_reasoning.strip()
            if "<" in candidate and ">" in candidate:
                tagged = candidate
                plain = self._extract_reasoning_inner_text(candidate) or plain
            elif candidate:
                plain = candidate
        if not plain or not tagged:
            return content

        if isinstance(content, bytes):
            return content

        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            updated = deepcopy(content)
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
                metadata = updated.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["reasoning"] = tagged
                    metadata["reasoning_content"] = plain
                    metadata.setdefault("reasoning_format", "hybrid_injected")
            return updated

        return content

    async def _execute_reasoning_phase(
        self,
        messages: list,
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
    ) -> ReasoningPhaseResult:
        """Execute reasoning phase and capture output and metadata.

        Args:
            messages: Original message history
            reasoning_backend: Backend name for reasoning model
            reasoning_model: Model name for reasoning
            request_data: Original request data
            identity: Optional identity configuration

        Returns:
            Structured result containing reasoning text, tool calls, and stream metadata

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

        # Create request payload for reasoning model
        reasoning_preset_params = get_reasoning_params(reasoning_backend)
        reasoning_request = self._apply_reasoning_params(
            request_data, reasoning_preset_params
        )

        # Apply URI parameters if provided
        if uri_params:
            try:
                # Validate URI parameters before applying
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        f"URI parameter validation errors for reasoning phase ({reasoning_backend}:{reasoning_model}): "
                        f"{', '.join(validation_errors)}. Invalid parameters will be excluded."
                    )

                # Apply normalized parameters
                if normalized_params:
                    reasoning_request = self._apply_parameter_overrides(
                        reasoning_request, normalized_params
                    )
            except Exception as param_error:
                # Log error but continue without URI parameters
                logger.warning(
                    f"Failed to apply URI parameters for reasoning phase ({reasoning_backend}:{reasoning_model}): "
                    f"{param_error}. Continuing without URI parameters."
                )

        # Prepare canonical request for backend service
        # Use full backend:model format so backend_service can properly resolve it
        canonical_reasoning_request = self._prepare_backend_request(
            reasoning_request,
            target_model=f"{reasoning_backend}:{reasoning_model}",
            stream=True,
            messages=messages,
        )

        # DEBUG: Log what we're sending
        extra_body = getattr(canonical_reasoning_request, "extra_body", None)
        if isinstance(extra_body, dict):
            extra_body_keys = ", ".join(sorted(map(str, extra_body.keys())))
        elif extra_body is None:
            extra_body_keys = "None"
        else:
            extra_body_keys = f"<non-dict:{type(extra_body).__name__}>"

        logger.error(
            "[HYBRID DEBUG] Prepared reasoning request: model=%s, extra_body_keys=%s",
            canonical_reasoning_request.model,
            extra_body_keys,
        )

        try:
            from src.core.di.services import get_required_service
            from src.core.domain.request_context import (
                RequestContext,
                RequestCookies,
                RequestHeaders,
            )
            from src.core.services.backend_service import BackendService

            backend_service = get_required_service(BackendService)

            # Create a clean context without session to prevent session backend inheritance
            # This ensures the reasoning backend is resolved from the model name, not session state
            clean_context = RequestContext(
                headers=RequestHeaders(),
                cookies=RequestCookies(),
                state=None,
                app_state=None,
                session_id=None,  # No session to prevent backend inheritance
            )

            # Call reasoning model with timeout via backend service
            try:
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                        context=clean_context,  # Prefer context-enabled call
                    ),
                    timeout=REASONING_PHASE_TIMEOUT,
                )
            except TypeError as exc:
                # Integration stubs may not accept context; retry without it.
                if "context" not in str(exc):
                    raise
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                    ),
                    timeout=REASONING_PHASE_TIMEOUT,
                )

            # Extract stream from response
            response_media_type = getattr(response, "media_type", None)
            response_headers = getattr(response, "headers", None)

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
            tool_calls = metadata.get("tool_calls") or []
            raw_chunks = metadata.get("raw_chunks") or []

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

            return ReasoningPhaseResult(
                text=reasoning_text,
                complete=reasoning_complete,
                tool_calls=tool_calls,
                raw_chunks=raw_chunks,
                media_type=response_media_type,
                headers=response_headers,
            )

        except ServiceResolutionError as e:
            logger.error(
                "Failed to resolve BackendService for reasoning phase",
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

    def _prepare_backend_request(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        target_model: str,
        stream: bool,
        messages: list | None = None,
    ) -> CanonicalChatRequest:
        """Normalize request for backend service calls."""

        from src.core.domain.chat import CanonicalChatRequest, ChatRequest

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
        elif isinstance(request_obj, ChatRequest):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        else:
            raise TypeError(
                "Unable to prepare backend request from type "
                f"{type(request_obj).__name__}"
            )

        if not isinstance(request_obj, CanonicalChatRequest):
            request_obj = self.translation_service.to_domain_request(
                request_obj, "openai"
            )

        if messages is not None:
            request_obj = request_obj.model_copy(update={"messages": messages})

        # Remove session_id from extra_body to prevent session backend inheritance
        # This ensures the backend is resolved from the model name, not session state
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

        return cast("CanonicalChatRequest", request_obj)

    async def _execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list,
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        reasoning_output_length: int = 0,
        uri_params: dict[str, Any] | None = None,
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

            execution_identity = self._resolve_backend_identity(
                execution_backend, identity, execution_backend_config
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
        execution_preset_params = get_execution_params(execution_backend)
        execution_request = self._apply_reasoning_params(
            request_data, execution_preset_params
        )

        # Apply URI parameters if provided
        if uri_params:
            try:
                # Validate URI parameters before applying
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        f"URI parameter validation errors for execution phase ({execution_backend}:{execution_model}): "
                        f"{', '.join(validation_errors)}. Invalid parameters will be excluded."
                    )

                # Apply normalized parameters
                if normalized_params:
                    execution_request = self._apply_parameter_overrides(
                        execution_request, normalized_params
                    )
            except Exception as param_error:
                # Log error but continue without URI parameters
                logger.warning(
                    f"Failed to apply URI parameters for execution phase ({execution_backend}:{execution_model}): "
                    f"{param_error}. Continuing without URI parameters."
                )

        try:
            # Call execution model with augmented messages and timeout
            response = await asyncio.wait_for(
                execution_connector.chat_completions(
                    request_data=execution_request,
                    processed_messages=augmented_messages,
                    effective_model=execution_model,
                    identity=execution_identity,
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
        except AuthenticationError:
            # Re-raise AuthenticationError as-is (already has proper context)
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

    @staticmethod
    def _extract_message_role(message: Any) -> str | None:
        """Best-effort extraction of a message role."""

        role = getattr(message, "role", None)
        if isinstance(role, str) and role:
            return role

        if isinstance(message, dict):
            role_value = message.get("role")
            return role_value if isinstance(role_value, str) else None

        if hasattr(message, "model_dump") and callable(message.model_dump):
            try:
                dumped = message.model_dump()
                role_value = dumped.get("role")
                if isinstance(role_value, str):
                    return role_value
            except Exception:
                return None

        if hasattr(message, "get") and callable(message.get):
            try:
                role_value = message.get("role")
                if isinstance(role_value, str):
                    return role_value
            except Exception:
                return None

        return None

    def _is_first_user_turn(
        self,
        processed_messages: list[Any] | None,
        request_messages: list[Any] | None,
    ) -> bool:
        """Determine whether the current request represents the first user turn."""

        messages_to_check: list[Any] = []
        if processed_messages:
            messages_to_check = list(processed_messages)
        elif request_messages:
            messages_to_check = list(request_messages)

        if not messages_to_check:
            # No prior context available; treat as first turn to err on the side of reasoning.
            return True

        for message in messages_to_check:
            role = self._extract_message_role(message)
            if not role:
                continue
            normalized_role = role.strip().lower()
            if normalized_role in {"assistant", "tool", "function"}:
                return False

        return True

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
            # Parse hybrid model specification with URI parameters
            (
                reasoning_backend,
                reasoning_model,
                reasoning_params,
                execution_backend,
                execution_model,
                execution_params,
            ) = self._parse_hybrid_model_spec(effective_model)

            # Check for reasoning_effort parameter and log warning
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

                # Remove reasoning_effort from parameters to prevent it from being applied
                if has_reasoning_effort_in_reasoning:
                    reasoning_params = {
                        k: v
                        for k, v in reasoning_params.items()
                        if k != "reasoning_effort"
                    }
                if has_reasoning_effort_in_execution:
                    execution_params = {
                        k: v
                        for k, v in execution_params.items()
                        if k != "reasoning_effort"
                    }

            # Log hybrid request initiation with session and model details
            logger.info(
                f"Hybrid request initiated: reasoning={reasoning_backend}:{reasoning_model} (params={reasoning_params}), "
                f"execution={execution_backend}:{execution_model} (params={execution_params})",
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

        reasoning_output = ""
        client_reasoning = ""
        has_reasoning_content = False
        reasoning_time = 0.0

        # Check for temporary reasoning injection probability override from edit precision middleware
        temp_reasoning_probability = None
        if isinstance(request_data, dict):
            extra_body = request_data.get("extra_body", {})
        else:
            extra_body = getattr(request_data, "extra_body", {})
            if extra_body is None:
                extra_body = {}

        # Check if edit precision middleware has set a temporary override
        temp_prob_override = extra_body.get("_temp_hybrid_reasoning_probability")
        if temp_prob_override is not None:
            temp_reasoning_probability = float(temp_prob_override)
            # Log that we're using a temporary override
            logger.info(
                f"Using temporary reasoning injection probability override: {temp_reasoning_probability} for session",
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
                # Phase 1: Execute reasoning phase and capture output
                reasoning_result = await self._execute_reasoning_phase(
                    messages=processed_messages,
                    reasoning_backend=reasoning_backend,
                    reasoning_model=reasoning_model,
                    request_data=request_data,  # Pass original request_data, not dict
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
                uri_params=execution_params,
                **kwargs,
            )

            # Phase 4: Filter reasoning tags from response
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
