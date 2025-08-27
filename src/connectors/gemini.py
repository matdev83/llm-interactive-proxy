from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.adapters.api_adapters import dict_to_domain_chat_request
from src.core.common.exceptions import BackendError, ServiceUnavailableError
from src.core.config.app_config import AppConfig  # Added
from src.core.domain.chat import (
    ChatRequest,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry
from src.core.services.json_repair_service import JsonRepairService  # Added
from src.core.services.streaming_json_repair_processor import (
    StreamingJsonRepairProcessor,  # Added
)

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class GeminiBackend(LLMBackend):
    """LLMBackend implementation for Google's Gemini API."""

    backend_type: str = "gemini"

    def __init__(
        self, client: httpx.AsyncClient, config: AppConfig
    ) -> None:  # Modified
        self.client = client
        self.config = config  # Stored config
        self.available_models: list[str] = []
        self.api_keys: list[str] = []

    async def initialize(self, **kwargs: Any) -> None:
        """Store configuration for lazy initialization."""
        self.gemini_api_base_url = kwargs.get("gemini_api_base_url")
        self.key_name = kwargs.get("key_name")
        self.api_key = kwargs.get("api_key")

        if not self.gemini_api_base_url or not self.key_name or not self.api_key:
            raise ValueError(
                "gemini_api_base_url, key_name, and api_key are required for GeminiBackend"
            )

        # Don't make HTTP calls during initialization
        # Models will be fetched on first use

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached."""
        if (
            not self.available_models
            and hasattr(self, "api_key")
            and self.gemini_api_base_url
            and self.key_name
            and self.api_key
        ):
            try:
                data = await self.list_models(
                    gemini_api_base_url=self.gemini_api_base_url,
                    key_name=self.key_name,
                    api_key=self.api_key,
                )
                self.available_models = [
                    m.get("name") for m in data.get("models", []) if m.get("name")
                ]
            except Exception as e:
                logger.warning(f"Failed to fetch Gemini models: {e}")
                # Return empty list on failure, don't crash
                self.available_models = []

    def get_available_models(self) -> list[str]:
        """Return cached Gemini model names. For immediate use, prefer async version."""
        return list(self.available_models)

    async def get_available_models_async(self) -> list[str]:
        """Return Gemini model names, fetching them if not cached."""
        await self._ensure_models_loaded()
        return list(self.available_models)

    def _convert_stream_chunk(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        """Convert a Gemini streaming JSON chunk to OpenAI format."""
        candidate: dict[str, Any] = {}
        text = ""
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text += part["text"]
        finish = candidate.get("finishReason")
        return {
            "id": data.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "delta": {"content": text},
                    "finish_reason": (
                        finish.lower() if isinstance(finish, str) else None
                    ),
                }
            ],
        }

    def _convert_full_response(
        self, data: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert a Gemini JSON response to OpenAI format, including function calls."""
        candidate: dict[str, Any] = {}
        text = ""
        tool_call_obj: dict[str, Any] | None = None
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict):
                    if part.get("functionCall"):
                        fc = part["functionCall"]
                        try:
                            args_str = json.dumps(fc.get("args", {}))
                        except Exception:
                            args_str = "{}"
                        tool_call_obj = {
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": fc.get("name", "function"),
                                "arguments": args_str,
                            },
                        }
                    elif "text" in part:
                        text += part["text"]
        finish = candidate.get("finishReason")
        usage = data.get("usageMetadata", {})

        message: dict[str, Any] = {"role": "assistant", "content": text}
        finish_reason = finish.lower() if isinstance(finish, str) else None
        if tool_call_obj is not None:
            message["content"] = None
            message["tool_calls"] = [tool_call_obj]
            finish_reason = "tool_calls"

        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            },
        }

    def _convert_part_for_gemini(
        self, part: MessageContentPartText | MessageContentPartImage
    ) -> dict[str, Any]:
        """Convert a MessageContentPart into Gemini API format."""
        if isinstance(part, MessageContentPartText):
            # Text content is already processed by middleware
            return {"text": part.text}
        if isinstance(part, MessageContentPartImage):
            url = part.image_url.url
            # Data URL -> inlineData
            if url.startswith("data:"):
                try:
                    header, b64_data = url.split(",", 1)
                    mime = header.split(";")[0][5:]
                except Exception:
                    mime = "application/octet-stream"
                    b64_data = ""
                return {"inlineData": {"mimeType": mime, "data": b64_data}}
            # Otherwise treat as remote file URI
            return {
                "fileData": {"mimeType": "application/octet-stream", "fileUri": url}
            }
        data = part.model_dump(exclude_unset=True)
        if data.get("type") == "text" and "text" in data:
            # Text content is already processed by middleware
            data.pop("type", None)
        return data

    def _prepare_gemini_contents(
        self, processed_messages: list[Any]
    ) -> list[dict[str, Any]]:
        payload_contents = []
        for msg in processed_messages:
            if msg.role == "system":
                # Gemini API does not support system role
                continue

            if isinstance(msg.content, str):
                # If this is a tool or function role, represent it as functionResponse for Gemini
                if msg.role in ["tool", "function"]:
                    # Try to parse JSON payload; otherwise wrap string
                    try:
                        input_obj = json.loads(msg.content)
                    except Exception:
                        input_obj = {"output": msg.content}
                    parts: list[dict[str, Any]] = [
                        {
                            "functionResponse": {
                                "name": getattr(msg, "name", "tool") or "tool",
                                "response": input_obj,
                            }
                        }
                    ]
                else:
                    # Content is already processed by middleware
                    parts = [{"text": msg.content}]
            else:
                parts = [self._convert_part_for_gemini(part) for part in msg.content]

            # Map roles to 'user' or 'model' as required by Gemini API
            if msg.role == "user":
                gemini_role = "user"
            elif msg.role in ["tool", "function"]:
                # Tool/function results are treated as coming from the user side in Gemini
                gemini_role = "user"
            else:  # e.g., assistant
                gemini_role = "model"

            payload_contents.append({"role": gemini_role, "parts": parts})
        return payload_contents

    async def _handle_gemini_streaming_response(
        self, base_url: str, payload: dict, headers: dict, effective_model: str
    ) -> StreamingResponseEnvelope:
        url = f"{base_url}:streamGenerateContent"
        try:
            request = self.client.build_request(
                "POST", url, json=payload, headers=headers
            )
            response = await self.client.send(request, stream=True)
            if response.status_code >= 400:
                try:
                    body_text = (await response.aread()).decode("utf-8")
                except Exception:
                    body_text = ""
                finally:
                    await response.aclose()
                logger.error(
                    "HTTP error during Gemini stream: %s - %s",
                    response.status_code,
                    body_text,
                )
                raise BackendError(
                    message=f"Gemini stream error: {response.status_code} - {body_text}",
                    code="gemini_error",
                    status_code=response.status_code,
                )

            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                # Initialize JSON repair processor if enabled
                if self.config.session.json_repair_enabled:
                    json_repair_service = JsonRepairService()
                    processor = StreamingJsonRepairProcessor(
                        repair_service=json_repair_service,
                        buffer_cap_bytes=self.config.session.json_repair_buffer_cap_bytes,
                        strict_mode=self.config.session.json_repair_strict_mode,
                        schema=self.config.session.json_repair_schema,  # Added schema
                    )
                    # Wrap the raw stream with the JSON repair processor
                    processed_stream = processor.process_stream(response.aiter_text())
                else:
                    # If JSON repair is disabled, just use the raw stream
                    processed_stream = response.aiter_text()

                try:
                    async for chunk in processed_stream:
                        # If JSON repair is enabled, the processor yields repaired JSON strings
                        # or raw text. If disabled, it yields raw text.
                        # Convert Gemini format to OpenAI format for consistency
                        from src.gemini_converters import gemini_to_openai_stream_chunk

                        if chunk.startswith(("data: ", "id: ", ":")):
                            # Convert Gemini SSE chunk to OpenAI format
                            openai_chunk = gemini_to_openai_stream_chunk(chunk)
                            yield openai_chunk.encode()
                        else:
                            # Convert raw Gemini JSON to OpenAI format
                            openai_chunk = gemini_to_openai_stream_chunk(
                                f"data: {chunk}"
                            )
                            yield openai_chunk.encode()

                    yield b"data: [DONE]\n\n"
                finally:
                    await response.aclose()

            return StreamingResponseEnvelope(
                content=stream_generator(),
                media_type="text/event-stream",
                headers=dict(response.headers),
            )
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(message=f"Could not connect to Gemini ({e})")

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[str, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Resolve base configuration
        base_api_url, headers = await self._resolve_gemini_api_config(
            gemini_api_base_url, openrouter_api_base_url, api_key, **kwargs
        )
        if identity:
            if identity.url:
                headers["HTTP-Referer"] = identity.url
            if identity.title:
                headers["X-Title"] = identity.title

        # Normalize incoming request to ChatRequest
        if isinstance(request_data, dict):
            request_data = dict_to_domain_chat_request(request_data)
        elif not isinstance(request_data, ChatRequest):
            # Convert to dict first
            if hasattr(request_data, "model_dump"):
                request_dict = request_data.model_dump()  # type: ignore
            elif hasattr(request_data, "dict"):
                request_dict = request_data.dict()  # type: ignore
            else:
                request_dict = dict(request_data)  # type: ignore
            request_data = dict_to_domain_chat_request(request_dict)
        request_data = cast(ChatRequest, request_data)

        # Build payload
        payload: dict[str, Any] = {
            "contents": self._prepare_gemini_contents(processed_messages)
        }
        self._apply_generation_config(payload, request_data)
        if request_data.extra_body:
            # Merge extra_body with payload, but be careful with generationConfig.
            # We support both legacy placement under 'generation_config' and
            # the external 'generationConfig' key that Gemini expects.
            # Normalize: prefer explicit generation_config on ChatRequest, then
            # merge any 'generationConfig' present in extra_body on top.
            extra_body_copy = dict(request_data.extra_body)

            # If caller placed generation_config on ChatRequest it was already
            # merged by _apply_generation_config into payload['generationConfig'].
            # Now merge any generationConfig from extra_body on top of what we
            # already have (extra body should be able to override specific keys).
            # Accept either CamelCase 'generationConfig' (as used in tests and
            # by external callers) or legacy snake_case 'generation_config'
            extra_gen_cfg = extra_body_copy.pop("generationConfig", None)
            if extra_gen_cfg is None:
                extra_gen_cfg = extra_body_copy.pop("generation_config", None)
            if extra_gen_cfg:
                # merge by creating a new dict so we don't retain old references
                existing = payload.get("generationConfig", {})
                merged = dict(existing)
                merged.update(extra_gen_cfg)
                # Ensure extra_body overrides win for temperature specifically
                if "temperature" in extra_gen_cfg:
                    merged["temperature"] = extra_gen_cfg["temperature"]
                payload["generationConfig"] = merged

            # Finally update payload with remaining extra body fields
            if extra_body_copy:
                payload.update(extra_body_copy)
        # Remove generation_config (legacy key) if present; we've migrated it
        # into 'generationConfig' in _apply_generation_config.
        payload.pop("generation_config", None)
        # Debug output
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Final payload: %s", payload)

        # Normalize model id and construct URL
        model_name = self._normalize_model_name(effective_model)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Constructing Gemini API URL with model_name: %s", model_name)
        model_url = f"{base_api_url}/v1beta/models/{model_name}"

        # Streaming vs non-streaming
        if request_data.stream:
            return await self._handle_gemini_streaming_response(
                model_url, payload, headers, effective_model
            )

        return await self._handle_gemini_non_streaming_response(
            model_url, payload, headers, effective_model
        )

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, str]]:
        # Prefer explicit params, then kwargs, then instance attributes set during initialize
        base = (
            gemini_api_base_url
            or openrouter_api_base_url
            or kwargs.get("gemini_api_base_url")
            or getattr(self, "gemini_api_base_url", None)
        )
        key = api_key or kwargs.get("api_key") or getattr(self, "api_key", None)
        if not base or not key:
            raise HTTPException(
                status_code=500,
                detail="Gemini API base URL and API key must be provided.",
            )
        return base.rstrip("/"), {"x-goog-api-key": key}

    def _apply_generation_config(
        self, payload: dict[str, Any], request_data: ChatRequest
    ) -> None:
        # Initialize generationConfig
        generation_config = payload.setdefault("generationConfig", {})

        # thinking budget
        if getattr(request_data, "thinking_budget", None):
            generation_config.setdefault("thinkingConfig", {})[
                "thinkingBudget"
            ] = request_data.thinking_budget  # type: ignore[index]

        # generation config blob - merge with existing config
        if getattr(request_data, "generation_config", None):
            # Deep merge the generation_config into generationConfig
            for key, value in request_data.generation_config.items():  # type: ignore[union-attr]
                generation_config[key] = value

        # temperature clamped to [0,1]
        temperature = getattr(request_data, "temperature", None)
        if temperature is not None:
            if temperature > 1.0:
                logger.warning(
                    f"Temperature {temperature} > 1.0 for Gemini, clamping to 1.0"
                )
                temperature = 1.0
            generation_config["temperature"] = temperature

    def _normalize_model_name(self, effective_model: str) -> str:
        model_name = effective_model
        if model_name.startswith("gemini:"):
            model_name = model_name.split(":", 1)[1]
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        if model_name.startswith("gemini/"):
            model_name = model_name.split("/", 1)[1]
        if "/" in model_name:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Detected provider prefix in model name '%s'. Using last path segment as Gemini model id.",
                    model_name,
                )
            model_name = model_name.rsplit("/", 1)[-1]
        return model_name

    async def _handle_gemini_non_streaming_response(
        self, base_url: str, payload: dict, headers: dict, effective_model: str
    ) -> ResponseEnvelope:
        url = f"{base_url}:generateContent"
        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_error",
                    status_code=response.status_code,
                )
            data = response.json()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Gemini response headers: %s", dict(response.headers))
            return ResponseEnvelope(
                content=self._convert_full_response(data, effective_model),
                headers=dict(response.headers),
                status_code=response.status_code,
            )
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(message=f"Could not connect to Gemini ({e})")

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> dict[str, Any]:
        headers = {"x-goog-api-key": api_key}
        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models"
        try:
            response = await self.client.get(url, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_error",
                    status_code=response.status_code,
                )
            return cast(dict[str, Any], response.json())
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(message=f"Could not connect to Gemini ({e})")


backend_registry.register_backend("gemini", GeminiBackend)
