"""
Antigravity OAuth connector that reuses Antigravity app credentials.

This backend uses the Antigravity sandbox endpoint and reads credentials from
the Antigravity VS Code style state database.

This connector uses the Strategy Pattern with the following strategies:
- AntigravitySQLiteCredentialProvider: Loads from Antigravity state.vscdb
- AntigravitySandboxEndpoint: Uses daily-cloudcode-pa.sandbox.googleapis.com
- AntigravityRequestBodyBuilder: requestId/userAgent/requestType format
- AntigravityProjectDiscovery: Paid tier discovery for Antigravity
- FallbackModelDiscovery: Skips fetchAvailableModels (sandbox doesn't expose it)
- XmlToolCallPostProcessor: Parses XML tool calls for Claude models
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.connectors.base import strip_vendor_prefix
from src.connectors.gemini_base.credential_providers import (
    AntigravitySQLiteCredentialProvider,
)
from src.connectors.gemini_base.endpoints import AntigravitySandboxEndpoint
from src.connectors.gemini_base.model_discovery import FallbackModelDiscovery
from src.connectors.gemini_base.models import TierScore
from src.connectors.gemini_base.project_discovery import AntigravityProjectDiscovery
from src.connectors.gemini_base.request_builders import AntigravityRequestBodyBuilder
from src.connectors.gemini_base.response_processors import XmlToolCallPostProcessor
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    FunctionCall,
    ToolCall,
)
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Vendor prefixes that need to be stripped for Antigravity backend
ANTHROPIC_VENDOR_PREFIX = "anthropic"

from .gemini_oauth_base import GeminiOAuthBaseConnector

logger = logging.getLogger(__name__)

ANTIGRAVITY_AUTH_KEY = "antigravityAuthStatus"
ANTIGRAVITY_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"

ANTIGRAVITY_STATE_DB_ENV = "ANTIGRAVITY_STATE_DB"
ANTIGRAVITY_USER_AGENT = "antigravity/1.11.5 windows/amd64"
GLOBAL_STORAGE_SUBPATH = Path("Antigravity") / "User" / "globalStorage"

# Maximum JSON parse size to prevent DoS attacks (10MB)
MAX_JSON_PARSE_SIZE = 10 * 1024 * 1024  # 10MB in bytes

# Enable internal/debug-only backends automatically when running under tests.
_DEBUG_OVERRIDE_DEFAULT = os.environ.get(
    "ENABLE_INTERNAL_BACKENDS_FOR_TESTS", "1"
).lower() not in {"0", "false", "no"}


class AntigravityAuthStatus(BaseModel):
    """Antigravity-specific auth status loaded from state database.

    This model represents the credentials stored by Antigravity's VS Code extension.
    The primary field is 'apiKey' which gets normalized to 'access_token' for
    OAuth compatibility.
    """

    model_config = ConfigDict(extra="allow")

    api_key: str = Field(
        ..., alias="apiKey", description="Antigravity API key/credential"
    )
    project_id: str | None = Field(None, description="Cached project ID")
    refresh_token: str | None = Field(None, description="Refresh token if available")
    expiry_date: int | None = Field(
        None, description="Token expiry timestamp in epoch milliseconds"
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v:
            raise ValueError("apiKey must be a non-empty string")
        return v

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AntigravityAuthStatus":
        """Create auth status from dictionary.

        Args:
            data: Dictionary containing auth status fields.

        Returns:
            AntigravityAuthStatus instance.
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility.

        Returns:
            Dictionary representation including extra fields.
        """
        return self.model_dump(mode="python", exclude_none=False, by_alias=True)


class AntigravityOAuthConnector(GeminiOAuthBaseConnector):
    """
    Connector for Antigravity OAuth credentials.

    This connector uses the Antigravity sandbox endpoint instead of the standard
    Code Assist API endpoint. The sandbox does not expose fetchAvailableModels,
    so model discovery and health checks rely on cached/fallback lists instead.

    Inherits directly from GeminiOAuthBaseConnector (not from Free) to allow
    independent evolution of Antigravity-specific behavior.
    """

    backend_type: str = "antigravity-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str | None = None,
    ) -> None:
        # Initialize with Antigravity-specific strategies
        super().__init__(
            client,
            config,
            translation_service,
            name=name or self.backend_type,
            # Strategy injection for Antigravity behavior
            credential_provider=AntigravitySQLiteCredentialProvider(),
            endpoint_config=AntigravitySandboxEndpoint(),
            request_body_builder=AntigravityRequestBodyBuilder(),
            project_discovery=AntigravityProjectDiscovery(),
            model_discovery=FallbackModelDiscovery(),
            response_post_processor=XmlToolCallPostProcessor(),
        )
        self.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT
        self._enable_antigravity_backend_debugging_override = _DEBUG_OVERRIDE_DEFAULT
        self._owns_custom_client = False  # Track if we created a custom client

    # NOTE: _get_api_headers and _get_session_headers are now handled by
    # AntigravitySandboxEndpoint strategy injected in __init__

    # NOTE: _build_code_assist_request_body is now handled by
    # AntigravityRequestBodyBuilder strategy injected in __init__

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize using Antigravity's sandbox endpoint and custom User-Agent."""
        backends_config = getattr(self.config, "backends", None)
        backend_config = getattr(backends_config, "antigravity_oauth", None)
        extras = backend_config.extra if backend_config else {}

        current = self._enable_antigravity_backend_debugging_override
        self._enable_antigravity_backend_debugging_override = (
            kwargs.get("enable_antigravity_backend_debugging_override")
            if "enable_antigravity_backend_debugging_override" in kwargs
            else extras.get("enable_antigravity_backend_debugging_override", current)
        )

        kwargs.setdefault("gemini_api_base_url", ANTIGRAVITY_SANDBOX_ENDPOINT)

        # Store reference to original client before replacing
        original_client = getattr(self, "client", None)

        # Create a custom client with Antigravity-specific User-Agent
        # This ensures all requests use the correct User-Agent regardless of settings
        custom_client = httpx.AsyncClient(
            headers={"User-Agent": ANTIGRAVITY_USER_AGENT},
            timeout=httpx.Timeout(60.0, connect=30.0),
        )
        self.client = custom_client
        self._owns_custom_client = True

        try:
            await super().initialize(**kwargs)
        except Exception as exc:
            # Never propagate init errors so other backends remain usable.
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to initialize antigravity-oauth backend: %s",
                    exc,
                    exc_info=True,
                )
            # Close custom client if initialization fails
            if self._owns_custom_client:
                try:
                    if not custom_client.is_closed:
                        await custom_client.aclose()
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to close custom client during initialization cleanup",
                            exc_info=True,
                        )
                self._owns_custom_client = False
            self._fail_init([f"Initialization failed: {exc}"])
        finally:
            # Close original client if we replaced it and it's different
            if original_client is not None and original_client is not custom_client:
                try:
                    if not original_client.is_closed:
                        await original_client.aclose()
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to close original client during initialization cleanup",
                            exc_info=True,
                        )

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Any = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> Any:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        """Handle chat completions with model validation.

        This method validates the requested model against the available models list
        before delegating to the parent implementation.

        Raises:
            BackendError: If the requested model is not available
            HTTPException: If the debugging override flag is not enabled
        """
        if not self._enable_antigravity_backend_debugging_override:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Rejected request: Antigravity backend requires debugging override flag. "
                    "To enable, use by --enable-antigravity-backend-debugging-override flag."
                )
            raise HTTPException(
                status_code=403,
                detail=(
                    "Forbidden: This backend is reserved for internal development and debugging purposes only. "
                    "Use --enable-antigravity-backend-debugging-override to bypass this check."
                ),
            )

        # Ensure models are loaded (cached after first call)
        await self._ensure_models_loaded()

        # Strip any prefix from the model name for validation
        model_name = effective_model
        prefix = "gemini-oauth-plan:"
        if model_name.startswith(prefix):
            model_name = model_name[len(prefix) :]

        # Strip vendor prefixes for Antigravity backend
        # The remote backend requires model names without vendor prefixes
        model_name = strip_vendor_prefix(model_name, ANTHROPIC_VENDOR_PREFIX)
        model_name = strip_vendor_prefix(model_name, "google")
        model_name = strip_vendor_prefix(model_name, "openai")

        # Map public model names to internal variants based on reasoning_effort
        # - gemini-3-pro -> gemini-3-pro-high/low (based on reasoning_effort)
        # - claude-opus-4.5 -> claude-opus-4-5-thinking (always, ignoring reasoning_effort)
        # - claude-sonnet-4.5 -> claude-sonnet-4-5 or claude-sonnet-4-5-thinking
        # - gpt-oss-120b -> gpt-oss-120b-medium (always, ignoring reasoning_effort)
        model_name = self._map_model_with_reasoning_effort(model_name, request_data)

        # Skip strict model validation - Antigravity sandbox supports both Gemini and Claude
        # NOTE: Claude models have limited multi-turn tool calling support when using this backend.
        # The proxy converts domain format -> Gemini format (functionCall without IDs),
        # but Antigravity needs IDs when converting to Anthropic format for Claude models.
        # This can cause "tool_use.id: Field required" errors in follow-up requests with history.
        # self.validate_model(model_name)

        # Delegate to parent implementation with the stripped model name
        response = await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=model_name,
            identity=identity,
            openrouter_api_base_url=openrouter_api_base_url,
            openrouter_headers_provider=openrouter_headers_provider,
            key_name=key_name,
            api_key=api_key,
            project=project,
            agent=agent,
            gemini_api_base_url=gemini_api_base_url,
            **kwargs,
        )

        # Post-process response to handle XML tool calls for Sonnet 4.5
        # This is a workaround for the model returning tool calls as XML text
        if (
            isinstance(response, ResponseEnvelope)
            and isinstance(response.content, str)
            and "<Tool>" in response.content
        ):
            content = response.content
            tool_calls = []

            # Regex to extract <Tool> block
            # Assuming single <Tool> block containing a JSON array
            tool_pattern = r"<Tool>(.*?)</Tool>"
            match = re.search(tool_pattern, content, re.DOTALL)

            if match:
                tool_json = match.group(1)
                # DoS protection: Check size before parsing
                if len(tool_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Tool JSON payload too large: %d bytes (limit: %d bytes), skipping parsing",
                            len(tool_json.encode("utf-8")),
                            MAX_JSON_PARSE_SIZE,
                        )
                else:
                    try:
                        tools_data = json.loads(tool_json)
                        if isinstance(tools_data, list):
                            for tool_data in tools_data:
                                if tool_data.get("type") == "tool_use":
                                    tool_calls.append(
                                        ToolCall(
                                            id=tool_data.get("id", ""),
                                            type="function",
                                            function=FunctionCall(
                                                name=tool_data.get("name", ""),
                                                arguments=json.dumps(
                                                    tool_data.get("input", {})
                                                ),
                                            ),
                                        )
                                    )

                        # Remove the <Tool> block from content
                        content = content.replace(match.group(0), "").strip()

                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning("Failed to parse XML tool call: %s", e)

            if tool_calls:
                # Construct CanonicalChatResponse
                canonical_response = CanonicalChatResponse(
                    id=f"chatcmpl-antigravity-{int(time.time())}",
                    object="chat.completion",
                    created=int(time.time()),
                    model=effective_model,
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant",
                                content=content or None,
                                tool_calls=tool_calls,
                            ),
                            finish_reason="tool_calls",
                        )
                    ],
                    usage=response.usage,
                )

                # Update envelope content - convert CanonicalChatResponse to dict
                content_dict = canonical_response.model_dump()
                response.content = content_dict if isinstance(content_dict, dict) else str(canonical_response)  # type: ignore[assignment]

        # Handle streaming responses
        elif isinstance(response, ResponseEnvelope) and response.content is not None:
            # Check if content is an async iterator (streaming)
            from collections.abc import AsyncIterator

            if isinstance(response.content, AsyncIterator):
                # We need to intercept the stream, buffer it, and check for XML tool calls
                # This adds latency but is necessary for correctness with this model/backend combo
                original_iterator: AsyncIterator[Any] = response.content  # type: ignore[assignment]

                async def _intercept_stream():
                    # Stream processing with bounded memory usage
                    # We only need to buffer content for XML tool call detection
                    # and keep track of the first chunk type for reconstruction
                    content_parts: list[str] = []
                    first_chunk_type: type[Any] | None = None
                    original_chunks: list[Any] = []

                    # Process stream in a single pass with bounded memory
                    async for chunk in original_iterator:  # type: ignore[union-attr]
                        if first_chunk_type is None:
                            first_chunk_type = type(chunk)

                        # Store original chunk for potential re-yielding
                        original_chunks.append(chunk)

                        # Extract and accumulate content for XML detection
                        if hasattr(chunk, "content"):
                            chunk_content = chunk.content
                            if isinstance(chunk_content, dict):
                                # It might be a CanonicalStreamChunk dict
                                choices = chunk_content.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content_part = delta.get("content", "")
                                    if content_part:
                                        content_parts.append(content_part)
                            elif isinstance(chunk_content, str):
                                content_parts.append(chunk_content)

                        # Early exit if we detect tool calls and have enough content
                        # Build content_buffer efficiently using list accumulation
                        content_buffer = "".join(content_parts)
                        if "<Tool>" in content_buffer and "</Tool>" in content_buffer:
                            # We have a complete tool call, break to process it
                            break

                    # Build final content buffer after loop (may have been built in loop)
                    content_buffer = "".join(content_parts)

                    # Check for XML tool calls in the accumulated content
                    tool_calls = []
                    if "<Tool>" in content_buffer:
                        tool_pattern = r"<Tool>(.*?)</Tool>"
                        match = re.search(tool_pattern, content_buffer, re.DOTALL)
                        if match:
                            tool_json = match.group(1)
                            # DoS protection: Check size before parsing
                            if len(tool_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
                                if logger.isEnabledFor(logging.WARNING):
                                    logger.warning(
                                        "Tool JSON payload too large in stream: %d bytes (limit: %d bytes), skipping parsing",
                                        len(tool_json.encode("utf-8")),
                                        MAX_JSON_PARSE_SIZE,
                                    )
                            else:
                                try:
                                    tools_data = json.loads(tool_json)
                                    if isinstance(tools_data, list):
                                        for tool_data in tools_data:
                                            if tool_data.get("type") == "tool_use":
                                                tool_calls.append(
                                                    {
                                                        "id": tool_data.get("id", ""),
                                                        "type": "function",
                                                        "function": {
                                                            "name": tool_data.get(
                                                                "name", ""
                                                            ),
                                                            "arguments": json.dumps(
                                                                tool_data.get(
                                                                    "input", {}
                                                                )
                                                            ),
                                                        },
                                                    }
                                                )
                                    # Remove XML from content
                                    content_buffer = content_buffer.replace(
                                        match.group(0), ""
                                    ).strip()
                                except Exception as e:
                                    if logger.isEnabledFor(logging.WARNING):
                                        logger.warning(
                                            "Failed to parse XML tool call in stream: %s",
                                            e,
                                        )

                    if tool_calls and first_chunk_type is not None:
                        # Yield tool call chunks
                        import uuid

                        (
                            tool_calls[0]["id"]
                            if tool_calls
                            else f"call_{uuid.uuid4().hex[:8]}"
                        )

                        # Yield content first if any
                        if content_buffer:
                            yield first_chunk_type(  # type: ignore[misc]
                                content={
                                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": effective_model,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {
                                                "role": "assistant",
                                                "content": content_buffer,
                                            },
                                            "finish_reason": None,
                                        }
                                    ],
                                }
                            )

                        # Yield tool calls
                        yield first_chunk_type(  # type: ignore[misc]
                            content={
                                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": effective_model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"tool_calls": tool_calls},
                                        "finish_reason": "tool_calls",
                                    }
                                ],
                            }
                        )
                    else:
                        # Re-yield original chunks (streaming without buffering)
                        for chunk in original_chunks:
                            yield chunk

                        # Continue yielding remaining chunks from original iterator
                        async for chunk in original_iterator:  # type: ignore[union-attr]
                            yield chunk

                response.content = _intercept_stream()  # type: ignore[assignment]

        return response

    def _extract_reasoning_effort(self, request_data: Any) -> str | None:
        """Extract reasoning_effort from request data.

        Reasoning effort can be specified via:
        - Top-level `reasoning_effort` field (Chat Completions API style)
        - Nested `reasoning.effort` field (Responses API style)
        - URI query parameter (highest precedence, already resolved by BackendService)

        Args:
            request_data: The request data containing reasoning_effort parameter.

        Returns:
            The reasoning effort value, or None if not specified.
        """
        reasoning_effort: str | None = None

        # 1. Check top-level reasoning_effort (Chat Completions style)
        if hasattr(request_data, "reasoning_effort"):
            reasoning_effort = request_data.reasoning_effort
        elif isinstance(request_data, dict):
            reasoning_effort = request_data.get("reasoning_effort")

        # 2. If not found, check nested reasoning.effort (Responses API style)
        if not reasoning_effort:
            reasoning_obj = None
            if hasattr(request_data, "reasoning"):
                reasoning_obj = getattr(request_data, "reasoning", None)  # type: ignore[attr-defined]
            elif isinstance(request_data, dict):
                reasoning_obj = request_data.get("reasoning")

            if isinstance(reasoning_obj, dict):
                reasoning_effort = reasoning_obj.get("effort")

        # 3. Check extra_body for both formats (URI params get stored there)
        if not reasoning_effort:
            extra_body = None
            if hasattr(request_data, "extra_body"):
                extra_body = getattr(request_data, "extra_body", None)  # type: ignore[attr-defined]
            elif isinstance(request_data, dict):
                extra_body = request_data.get("extra_body")

            if isinstance(extra_body, dict):
                # Check flat format first
                reasoning_effort = extra_body.get("reasoning_effort")
                # Then check nested format
                if not reasoning_effort:
                    reasoning_obj = extra_body.get("reasoning")
                    if isinstance(reasoning_obj, dict):
                        reasoning_effort = reasoning_obj.get("effort")

        return reasoning_effort

    def _map_model_with_reasoning_effort(
        self, model_name: str, request_data: Any
    ) -> str:
        """Map public model names to internal variants based on reasoning_effort.

        The Antigravity sandbox uses distinct internal model names for different
        reasoning effort levels. This method handles:

        1. gemini-3-pro:
           - high/medium (default) -> gemini-3-pro-high
           - low -> gemini-3-pro-low

        2. claude-opus-4.5:
           - Always maps to claude-opus-4-5-thinking (ignores reasoning_effort)

        3. claude-sonnet-4.5:
           - high/medium -> claude-sonnet-4-5-thinking
           - low (default) -> claude-sonnet-4-5

        4. gpt-oss-120b:
           - Always maps to gpt-oss-120b-medium (ignores reasoning_effort)

        Args:
            model_name: The model name after vendor prefix stripping.
            request_data: The request data containing reasoning_effort parameter.

        Returns:
            The mapped internal model name.
        """
        # Check if this model requires mapping
        if model_name == "gemini-3-pro":
            return self._map_gemini_3_pro_model(model_name, request_data)
        elif model_name == "claude-opus-4.5":
            return self._map_claude_opus_model(model_name, request_data)
        elif model_name == "claude-sonnet-4.5":
            return self._map_claude_sonnet_model(model_name, request_data)
        elif model_name == "gpt-oss-120b":
            return self._map_gpt_oss_model(model_name, request_data)

        return model_name

    def _map_gemini_3_pro_model(self, model_name: str, request_data: Any) -> str:
        """Map gemini-3-pro to internal model names based on reasoning_effort.

        Mapping:
        - high, medium, or default -> gemini-3-pro-high
        - low -> gemini-3-pro-low
        """
        if model_name != "gemini-3-pro":
            return model_name

        reasoning_effort = self._extract_reasoning_effort(request_data)

        # Default to "high" if not specified
        if not reasoning_effort:
            reasoning_effort = "high"

        # Normalize to lowercase for comparison
        effort_lower = reasoning_effort.lower().strip()

        # Map to internal model names
        if effort_lower == "low":
            internal_model = "gemini-3-pro-low"
        else:
            # high, medium, or any other value defaults to high
            internal_model = "gemini-3-pro-high"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Mapped model '%s' with reasoning_effort='%s' to internal model '%s'",
                model_name,
                reasoning_effort,
                internal_model,
            )

        return internal_model

    def _map_claude_opus_model(self, model_name: str, request_data: Any) -> str:
        """Map claude-opus-4.5 to internal model name.

        Always maps to claude-opus-4-5-thinking regardless of reasoning_effort.

        Note: The public name uses dot (claude-opus-4.5) while internal names
        use hyphen (claude-opus-4-5).
        """
        if model_name != "claude-opus-4.5":
            return model_name

        # Always map to thinking variant, ignoring reasoning_effort
        internal_model = "claude-opus-4-5-thinking"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Mapped model '%s' to internal model '%s' (always thinking variant)",
                model_name,
                internal_model,
            )

        return internal_model

    def _map_claude_sonnet_model(self, model_name: str, request_data: Any) -> str:
        """Map claude-sonnet-4.5 to internal model names based on reasoning_effort.

        Mapping:
        - high, medium -> claude-sonnet-4-5-thinking
        - low or default -> claude-sonnet-4-5

        Note: The public name uses dot (claude-sonnet-4.5) while internal names
        use hyphen (claude-sonnet-4-5).
        """
        if model_name != "claude-sonnet-4.5":
            return model_name

        reasoning_effort = self._extract_reasoning_effort(request_data)

        # Normalize to lowercase for comparison
        effort_lower = (reasoning_effort or "").lower().strip()

        # Map to internal model names
        # For Claude Sonnet: high/medium -> thinking, low/default -> base model
        if effort_lower in ("high", "medium"):
            internal_model = "claude-sonnet-4-5-thinking"
        else:
            # low, or default -> base model
            internal_model = "claude-sonnet-4-5"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Mapped model '%s' with reasoning_effort='%s' to internal model '%s'",
                model_name,
                reasoning_effort or "(default)",
                internal_model,
            )

        return internal_model

    def _map_gpt_oss_model(self, model_name: str, request_data: Any) -> str:
        """Map gpt-oss-120b to internal model name.

        Always maps to gpt-oss-120b-medium regardless of reasoning_effort.
        """
        if model_name != "gpt-oss-120b":
            return model_name

        # Always map to medium variant, ignoring reasoning_effort
        internal_model = "gpt-oss-120b-medium"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Mapped model '%s' to internal model '%s' (always medium variant)",
                model_name,
                internal_model,
            )

        return internal_model

    async def _load_models_from_api(self) -> None:
        """
        Skip model enumeration on the sandbox endpoint to avoid 404 noise.

        The Antigravity sandbox does not expose fetchAvailableModels; use the
        hardcoded fallback list unless a different base URL is explicitly set.
        """
        base_url = (self.gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not base_url:
            base_url = sandbox_url

        if base_url == sandbox_url:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Skipping fetchAvailableModels for Antigravity sandbox; using fallback model list."
                )
            # Load models from FallbackModelDiscovery strategy
            self.available_models = self._model_discovery.get_fallback_models()
            self._available_models_set = set(self.available_models)
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Loaded %d Antigravity models (fallback list)",
                    len(self.available_models),
                )
            # Load models from the FallbackModelDiscovery strategy
            self.available_models = self._model_discovery.get_fallback_models()
            self._available_models_set = set(self.available_models)
            logger.info(
                f"Loaded {len(self.available_models)} Antigravity models (fallback list)"
            )
            return

        await super()._load_models_from_api()

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> ModelsListingResponse:
        """
        List models without hitting unavailable sandbox endpoints.

        When targeting the Antigravity sandbox, rely on the locally cached model
        list instead of calling fetchAvailableModels (which returns 404).
        """
        target_base = (gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not target_base:
            target_base = sandbox_url

        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401, detail="No OAuth access token available"
            )

        if target_base == sandbox_url:
            await self._ensure_models_loaded()
            model_infos = [
                ModelInfo(
                    id=f"models/{model}", name=model, object="model", owned_by="google"
                )
                for model in self.available_models
            ]
            return ModelsListingResponse(object="list", data=model_infos)

        return await super().list_models(
            gemini_api_base_url=gemini_api_base_url,
            key_name=key_name,
            api_key=api_key,
        )

    async def _perform_health_check(self) -> bool:
        """
        Perform a lightweight health check without hitting unavailable endpoints.

        The sandbox endpoint does not expose fetchAvailableModels; we only verify
        that credentials are usable when targeting that host.
        """
        base_url = (self.gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not base_url or base_url == sandbox_url:
            healthy = await self._refresh_token_if_needed()
            if healthy:
                self._health_checked = True
            return healthy

        return await super()._perform_health_check()

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """
        Discover the project id using the paid-tier onboarding flow.

        The Antigravity token maps to a real account; prefer the highest tier
        reported by loadCodeAssist instead of the free-tier defaults to avoid
        artificial quota limits.
        """
        if self._project_id:
            return str(self._project_id)

        if not auth_session:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "auth_session required for Antigravity project discovery but missing"
                )
            initial = (
                self._oauth_credentials.get("project_id")
                if self._oauth_credentials
                else None
            )
            return str(initial or "default")

        initial_project_id = (
            self._oauth_credentials.get("project_id")
            if self._oauth_credentials
            else None
        )
        fallback_project_id = initial_project_id or "default"

        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            load_request = {
                "cloudaicompanionProject": initial_project_id,
                "metadata": client_metadata,
            }

            load_url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=load_url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code != 200:
                raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

            load_data = load_response.json()
            project_candidate = load_data.get("cloudaicompanionProject")
            if project_candidate:
                self._project_id = project_candidate
                return str(self._project_id)

            allowed_tiers_raw = load_data.get("allowedTiers", [])
            allowed_tiers = [
                tier for tier in allowed_tiers_raw if isinstance(tier, dict)
            ]
            current_tier = load_data.get("currentTier")
            if isinstance(current_tier, dict):
                allowed_tiers.append(current_tier)

            def _tier_id(tier: dict[str, Any]) -> str:
                raw_id = tier.get("id") or tier.get("tierId")
                return str(raw_id or "").lower()

            def _context_tokens(tier: dict[str, Any]) -> int:
                for key in (
                    "maxContextTokens",
                    "contextTokenLimit",
                    "contextWindowTokens",
                    "tokenLimit",
                    "maxContextWindow",
                ):
                    value = tier.get(key)
                    if isinstance(value, int | float):
                        return int(value)
                return 0

            def _tier_score(tier: dict[str, Any]) -> TierScore:
                tier_id = _tier_id(tier)
                is_paid = int(
                    tier_id
                    in {
                        "paid-tier",
                        "google-one-tier",
                        "googleone-tier",
                        "googleone",
                        "duet-ai-pro",
                    }
                )
                context_tokens = _context_tokens(tier)
                if is_paid and context_tokens == 0:
                    context_tokens = 1_000_000
                is_default = int(bool(tier.get("isDefault")))
                return TierScore(
                    is_paid=is_paid,
                    context_tokens=context_tokens,
                    is_default=is_default,
                )

            tier_to_use = max(allowed_tiers, key=_tier_score) if allowed_tiers else None
            selected_tier_id = (
                tier_to_use.get("id") or tier_to_use.get("tierId")
                if tier_to_use
                else None
            )
            if not selected_tier_id:
                selected_tier_id = "paid-tier"

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Selected Code Assist tier '%s' for Antigravity", selected_tier_id
                )

            onboard_request = {
                "tierId": selected_tier_id,
                "cloudaicompanionProject": initial_project_id,
                "metadata": {
                    **client_metadata,
                    "duetProject": initial_project_id,
                },
            }

            onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
            max_retries = 30
            retry_count = 0

            while retry_count < max_retries:
                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )

                if lro_response.status_code != 200:
                    raise BackendError(f"OnboardUser failed: {lro_response.text}")

                lro_data = lro_response.json()
                if lro_data.get("done"):
                    response_data = lro_data.get("response", {})
                    cloudai_project = response_data.get("cloudaicompanionProject", {})
                    discovered_project_id = cloudai_project.get(
                        "id", initial_project_id or "default"
                    )
                    self._project_id = discovered_project_id
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Discovered Antigravity project ID: %s", self._project_id
                        )
                    return str(self._project_id)

                retry_count += 1
                await asyncio.sleep(2)

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Onboarding timed out for Antigravity; falling back to project '%s'",
                    fallback_project_id,
                )
        except Exception as exc:  # pragma: no cover - defensive fallback
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Antigravity project discovery failed, using fallback project '%s': %s",
                    fallback_project_id,
                    exc,
                    exc_info=True,
                )

        self._project_id = fallback_project_id
        return str(self._project_id)

    # -------------------------------------------------------------------------
    # Antigravity-specific credential loading methods
    # -------------------------------------------------------------------------

    def _candidate_state_db_paths(self) -> list[Path]:
        """
        Build a prioritized list of potential Antigravity state database paths.

        Uses an explicit override when provided, otherwise resolves platform
        specific roaming/config locations with a fallback to macOS paths.
        """
        override = os.getenv(ANTIGRAVITY_STATE_DB_ENV)
        if override:
            override_path = Path(override)
            if str(override_path).strip():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Using explicit ANTIGRAVITY_STATE_DB override: %s",
                        override_path,
                    )
                return [override_path]

        candidates: list[Path] = []
        # Windows roaming profile (e.g., %APPDATA%)
        appdata = os.getenv("APPDATA")
        if appdata:
            base = Path(appdata)
            candidates.append(base / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
            candidates.append(base / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup")
        elif os.name == "nt":
            roaming_home = Path.home() / "AppData" / "Roaming"
            candidates.append(roaming_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
            candidates.append(
                roaming_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup"
            )

        # XDG config locations (Linux) or ~/.config fallback
        home_dir = Path.home()
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        config_home = Path(xdg_config_home) if xdg_config_home else home_dir / ".config"
        candidates.append(config_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
        candidates.append(config_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup")

        # macOS Application Support location
        mac_config_base = home_dir / "Library" / "Application Support"
        candidates.append(mac_config_base / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
        candidates.append(
            mac_config_base / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup"
        )

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_candidates: list[Path] = []
        for path in candidates:
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            unique_candidates.append(path)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                f"Candidate Antigravity DB paths: {[str(p) for p in unique_candidates]}",
            )
        return unique_candidates

    def _load_auth_status_from_db(self, db_path: Path) -> AntigravityAuthStatus | None:
        """
        Read the Antigravity auth status payload from the state database.

        Returns:
            AntigravityAuthStatus if successfully parsed, None otherwise.
        """
        parsed = self._parse_auth_status_value_from_db(db_path)
        return parsed

    def _extract_credentials_from_db(
        self, db_path: Path
    ) -> AntigravityAuthStatus | None:
        """
        Load and parse the Antigravity auth status from the database.

        Returns:
            AntigravityAuthStatus if successfully parsed, None otherwise.
        """
        return self._load_auth_status_from_db(db_path)

    def _parse_auth_status_value_from_db(
        self, db_path: Path
    ) -> AntigravityAuthStatus | None:
        """
        Parse Antigravity auth status from database.

        Args:
            db_path: Path to the Antigravity state database.

        Returns:
            AntigravityAuthStatus if successfully parsed, None otherwise.
        """
        try:
            # Use URI mode for read-only access to avoid locking issues
            uri_path = (
                db_path.as_uri().replace("file:///", "file:/")
                if os.name == "nt"
                else db_path.as_uri()
            )
            # Ensure proper URI format for sqlite3
            if not uri_path.startswith("file:"):
                uri_path = f"file:{db_path.as_posix()}"

            connection_string = f"{uri_path}?mode=ro"

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    f"Attempting to read Antigravity DB at: {connection_string}",
                )

            with sqlite3.connect(connection_string, uri=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT value FROM ItemTable WHERE key=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (ANTIGRAVITY_AUTH_KEY,),
                )
                row = cursor.fetchone()
                if not row:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Key '{ANTIGRAVITY_AUTH_KEY}' not found in {db_path}"
                        )
                    return None
                raw_value = row[0]
                return self._parse_auth_status_value(raw_value)
        except sqlite3.Error as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to read Antigravity state database at %s: %s", db_path, exc
                )
            return None
        except Exception as exc:  # pragma: no cover - defensive guardrail
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error reading Antigravity state db %s: %s", db_path, exc
                )
            return None

    def _parse_auth_status_value(
        self, raw_value: str | bytes
    ) -> AntigravityAuthStatus | None:
        """
        Parse JSON string from the database into a strongly-typed model.

        Args:
            raw_value: Raw value from database (string or bytes).

        Returns:
            AntigravityAuthStatus if successfully parsed, None otherwise.
        """
        try:
            if isinstance(raw_value, bytes):
                # Decode bytes to string if necessary
                raw_value = raw_value.decode("utf-8")

            # Ensure raw_value is a string before calling strip()
            raw_value_str = str(raw_value)
            if not raw_value_str.strip():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Auth status value is empty.")
                return None

            # DoS protection: Check size before parsing
            if len(raw_value_str.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Auth status JSON payload too large: %d bytes (limit: %d bytes)",
                        len(raw_value_str.encode("utf-8")),
                        MAX_JSON_PARSE_SIZE,
                    )
                return None

            auth_data = json.loads(raw_value_str)

            if auth_data is None:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Auth status value is null/None.")
                return None

            if isinstance(auth_data, dict):
                try:
                    return AntigravityAuthStatus.from_dict(auth_data)
                except (ValueError, TypeError) as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Failed to create AntigravityAuthStatus from dict: {e}"
                        )
                    return None

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Parsed auth status is not a dictionary: {type(auth_data)}"
                )
            return None
        except json.JSONDecodeError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to parse Antigravity auth status JSON: %s", exc)
            return None
        except Exception as exc:  # pragma: no cover
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error parsing auth status: {exc}", exc_info=True
                )
            return None

    def _normalize_antigravity_credentials(
        self, credentials: AntigravityAuthStatus | dict[str, Any]
    ) -> dict[str, Any]:
        """
        Normalize Antigravity-specific credentials to standard OAuth format.

        Antigravity stores credentials with 'apiKey' field, but the OAuth system
        expects 'access_token'. This method maps fields appropriately.

        Args:
            credentials: AntigravityAuthStatus or dict containing credentials.

        Returns:
            Dictionary in standard OAuth format with 'access_token' field.
        """
        # Convert model to dict if needed
        if isinstance(credentials, AntigravityAuthStatus):
            base_dict = credentials.to_dict()
        else:
            # credentials is dict[str, Any] at this point due to type narrowing
            base_dict = credentials

        # Create a copy to avoid modifying the original
        normalized = base_dict.copy()

        # Map Antigravity 'apiKey' to standard OAuth 'access_token'
        if "apiKey" in normalized and "access_token" not in normalized:
            normalized["access_token"] = normalized.pop("apiKey")
        elif "apiKey" in normalized and "access_token" in normalized:
            # Both present - prefer access_token but keep apiKey for compatibility
            normalized.pop("apiKey")

        # The Antigravity token behaves like a static bearer; if no refresh_token is
        # present, ignore expiry metadata so the base class does not mark it stale.
        if not normalized.get("refresh_token"):
            normalized.pop("expiry_date", None)
            normalized.pop("refresh_token", None)

        return normalized

    async def _load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """
        Load OAuth credentials from the Antigravity state database or its backup.

        Args:
            force_reload: If True, bypass cache and force reload from file
            silent: If True, suppress INFO level logging (used when checking for changes)
        """
        # Prefer the currently used path first to keep file watching stable
        candidate_paths = self._candidate_state_db_paths()
        if self._credentials_path:
            preferred = [self._credentials_path]
            preferred.extend(
                path for path in candidate_paths if path != self._credentials_path
            )
            candidate_paths = preferred

        errors: list[str] = []
        for path in candidate_paths:
            try:
                if not path.exists():
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Path does not exist: %s", path)
                    continue

                current_modified = None
                try:
                    current_modified = path.stat().st_mtime
                except OSError:
                    current_modified = None

                if (
                    not force_reload
                    and self._oauth_credentials
                    and self._credentials_path
                    and path == self._credentials_path
                    and current_modified is not None
                    and current_modified == self._last_modified
                ):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Antigravity credentials unchanged; using cached copy."
                        )
                    return True

                credentials = self._extract_credentials_from_db(path)
                if not credentials:
                    errors.append(
                        f"Failed to load Antigravity credentials from {path}; missing {ANTIGRAVITY_AUTH_KEY}."
                    )
                    continue

                # Map Antigravity-specific fields to standard OAuth format
                normalized_credentials = self._normalize_antigravity_credentials(
                    credentials
                )

                is_valid, validation_errors = self._validate_credentials_structure(
                    normalized_credentials, silent=silent
                )
                errors.extend(validation_errors)
                if not is_valid:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Invalid credentials in %s: %s", path, validation_errors
                        )
                    continue

                self._oauth_credentials = normalized_credentials
                self._credentials_path = path
                self._last_modified = current_modified or time.time()
                self._credentials_fingerprint = self._compute_credentials_fingerprint(
                    normalized_credentials
                )
                try:

                    def _hash_file(target_path: Path) -> str:
                        return hashlib.sha256(target_path.read_bytes()).hexdigest()

                    credentials_file_hash: str | None = await asyncio.to_thread(
                        _hash_file, path
                    )
                except OSError:
                    credentials_file_hash = None
                self._credentials_file_hash = credentials_file_hash
                self._last_credentials_event_hash = credentials_file_hash
                if not silent and logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Loaded Antigravity OAuth credentials from %s%s",
                        path,
                        " (force reload)" if force_reload else "",
                    )
                return True
            except Exception as exc:
                errors.append(f"Unexpected error reading {path}: {exc}")
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Error loading Antigravity credentials from %s: %s", path, exc
                    )

        if errors:
            self._credential_validation_errors = errors
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to load Antigravity credentials. Errors: {errors}"
                )
        return False

    async def _cleanup_custom_client(self) -> None:
        """Explicitly cleanup custom HTTP client."""
        if (
            hasattr(self, "_owns_custom_client")
            and self._owns_custom_client
            and hasattr(self, "client")
            and not self.client.is_closed
        ):
            try:
                await self.client.aclose()
                self._owns_custom_client = False
            except Exception:
                # Log cleanup errors for debugging, but don't propagate
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to close custom client during cleanup",
                        exc_info=True,
                    )

    async def shutdown(self) -> None:
        """Shutdown the connector and clean up resources.

        This method is called by BackendLifecycleManager during backend shutdown
        to ensure proper cleanup of custom HTTP clients.
        """
        await self._cleanup_custom_client()

    def __del__(self):
        """Cleanup HTTP client on destruction."""
        # Close custom HTTP client if we own it
        # Note: We can't await in __del__, so we try best-effort cleanup
        if (
            hasattr(self, "_owns_custom_client")
            and self._owns_custom_client
            and hasattr(self, "client")
            and not self.client.is_closed
        ):
            try:
                import asyncio
                import contextlib

                # Try to close the client if event loop is available
                try:
                    loop = asyncio.get_running_loop()
                    # Event loop exists - schedule cleanup (fire and forget)
                    with contextlib.suppress(RuntimeError):
                        # Loop might be closing - ignore
                        task = loop.create_task(self.client.aclose())
                        # Store reference to prevent garbage collection
                        _ = task
                except RuntimeError:
                    # No running event loop - try to get existing one
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_closed():
                            if loop.is_running():
                                # Loop is running - schedule cleanup
                                with contextlib.suppress(RuntimeError):
                                    task = loop.create_task(self.client.aclose())
                                    # Store reference to prevent garbage collection
                                    _ = task
                            else:
                                # Loop exists but not running - run cleanup synchronously
                                with contextlib.suppress(Exception):
                                    loop.run_until_complete(self.client.aclose())
                    except (RuntimeError, AttributeError):
                        # No event loop available - can't close async client
                        # This is acceptable during interpreter shutdown
                        pass
            except Exception:
                # Suppress all exceptions during cleanup
                # The logging system may already be torn down
                pass

        # Call parent cleanup
        super().__del__()


backend_registry.register_backend("antigravity-oauth", AntigravityOAuthConnector)
