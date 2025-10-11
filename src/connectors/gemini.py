from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend
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
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_API_KEY_HEADER = "x-goog-api-key"


class GeminiBackend(LLMBackend):
    """LLMBackend implementation for Google's Gemini API."""

    backend_type: str = "gemini"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        self.client = client
        self.config = config  # Stored config
        self.translation_service = translation_service
        self.available_models: list[str] = []
        self.api_keys: list[str] = []

    async def initialize(self, **kwargs: Any) -> None:
        """Store configuration for lazy initialization."""
        base_url = kwargs.get("gemini_api_base_url")
        api_key = kwargs.get("api_key")
        provided_key_name = kwargs.get("key_name")

        if not base_url or not api_key:
            raise ValueError(
                "gemini_api_base_url and api_key are required for GeminiBackend"
            )

        self.gemini_api_base_url = base_url
        self.api_key = api_key
        self.key_name = self._normalize_api_key_header(provided_key_name)

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
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to fetch Gemini models: %s", e, exc_info=True
                    )
                # Return empty list on failure, don't crash
                self.available_models = []

    def get_available_models(self) -> list[str]:
        """Return cached Gemini model names. For immediate use, prefer async version."""
        return list(self.available_models)

    async def get_available_models_async(self) -> list[str]:
        """Return Gemini model names, fetching them if not cached."""
        await self._ensure_models_loaded()
        return list(self.available_models)

    # Translation is now handled by TranslationService

    def _convert_part_for_gemini(
        self,
        part: (
            MessageContentPartText
            | MessageContentPartImage
            | Mapping[str, Any]
            | str
            | Any
        ),
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
        if isinstance(part, str):
            return {"text": part}

        data: dict[str, Any]
        if isinstance(part, Mapping):
            data = dict(part)
        elif hasattr(part, "model_dump") and callable(part.model_dump):
            data = part.model_dump(exclude_unset=True)
        else:
            return {"text": str(part)}

        if data.get("type") == "text" and "text" in data:
            # Text content is already processed by middleware
            data = {key: value for key, value in data.items() if key != "type"}
        return data

    def _prepare_gemini_contents(
        self, processed_messages: list[Any]
    ) -> list[dict[str, Any]]:
        payload_contents = []
        for msg in processed_messages:
            role = None
            if isinstance(msg, Mapping):
                role = msg.get("role")
            else:
                role = getattr(msg, "role", None)

            if role == "system":
                # Gemini API does not support system role
                continue

            if role is None:
                role = "user"

            def _get_value(obj: Any, key: str) -> Any:
                if isinstance(obj, Mapping):
                    return obj.get(key)
                return getattr(obj, key, None)

            content = _get_value(msg, "content")
            parts_key_value = _get_value(msg, "parts")

            if isinstance(content, str):
                # If this is a tool or function role, represent it as functionResponse for Gemini
                if role in ["tool", "function"]:
                    # Try to parse JSON payload; otherwise wrap string
                    try:
                        input_obj = json.loads(content)
                    except Exception:
                        input_obj = {"output": content}
                    parts: list[dict[str, Any]] = [
                        {
                            "functionResponse": {
                                "name": _get_value(msg, "name") or "tool",
                                "response": input_obj,
                            }
                        }
                    ]
                else:
                    # Content is already processed by middleware
                    parts = [{"text": content}]
            else:
                raw_parts: Sequence[Any] | None = None

                if isinstance(content, Sequence) and not isinstance(
                    content, str | bytes | bytearray
                ):
                    raw_parts = content
                elif isinstance(content, Mapping):
                    inferred_parts = content.get("parts")
                    if isinstance(inferred_parts, Sequence) and not isinstance(
                        inferred_parts, str | bytes | bytearray
                    ):
                        raw_parts = inferred_parts
                    else:
                        raw_parts = [content]
                elif content is None:
                    if isinstance(parts_key_value, Sequence) and not isinstance(
                        parts_key_value, str | bytes | bytearray
                    ):
                        raw_parts = parts_key_value
                    elif parts_key_value is not None:
                        raw_parts = [parts_key_value]

                if raw_parts is None:
                    raw_parts = []

                parts = [self._convert_part_for_gemini(part) for part in raw_parts]

                if not parts and parts_key_value is not None:
                    # Fallback for singular dict/str stored under parts
                    parts = [self._convert_part_for_gemini(parts_key_value)]

            # Map roles to 'user' or 'model' as required by Gemini API
            if role == "user":
                gemini_role = "user"
            elif role in ["tool", "function"]:
                # Tool/function results are treated as coming from the user side in Gemini
                gemini_role = "user"
            else:  # e.g., assistant
                gemini_role = "model"

            payload_contents.append({"role": gemini_role, "parts": parts})
        return payload_contents

    @staticmethod
    def _coerce_stream_chunk(raw_chunk: Any) -> dict[str, Any] | None:
        if isinstance(raw_chunk, dict):
            return raw_chunk

        if isinstance(raw_chunk, bytes | bytearray):
            raw_chunk = raw_chunk.decode("utf-8", errors="ignore")

        if not isinstance(raw_chunk, str):
            return None

        stripped_chunk = raw_chunk.strip()
        if not stripped_chunk:
            return None

        data_segments: list[str] = []
        for line in stripped_chunk.splitlines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_value = line[5:].strip()
                if not data_value:
                    continue
                if data_value == "[DONE]":
                    return None
                data_segments.append(data_value)
            else:
                data_segments.append(line)

        for segment in data_segments or [stripped_chunk]:
            try:
                parsed = json.loads(segment)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, dict):
                return parsed

            if isinstance(parsed, str):
                stripped_parsed = parsed.strip()
                if stripped_parsed:
                    return {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": stripped_parsed}]},
                            }
                        ]
                    }

            # If parsed value is not usable, continue searching remaining segments
            continue

        # Fallback to treating the content as plain text
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": stripped_chunk}]},
                }
            ]
        }

    async def _handle_gemini_streaming_response(
        self, base_url: str, payload: dict, headers: dict, effective_model: str
    ) -> StreamingResponseEnvelope:
        headers = ensure_loop_guard_header(headers)
        url = f"{base_url}:streamGenerateContent"
        request = self.client.build_request("POST", url, json=payload, headers=headers)
        try:
            response = await self.client.send(request, stream=True)
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(message=f"Could not connect to Gemini ({e})")

        if response.status_code >= 400:
            try:
                # Attempt to read body text for logging if available
                if hasattr(response, "aread"):
                    body_bytes = await response.aread()  # type: ignore[no-untyped-call]
                else:
                    body_bytes = b""
                body_text = body_bytes.decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
            finally:
                # Close response if supported
                if hasattr(response, "aclose"):
                    await response.aclose()
            if logger.isEnabledFor(logging.ERROR):
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
            processed_stream = response.aiter_text()

            try:
                async for raw_chunk in processed_stream:
                    parsed_chunk = self._coerce_stream_chunk(raw_chunk)
                    if parsed_chunk is None:
                        continue

                    yield ProcessedResponse(
                        content=self.translation_service.to_domain_stream_chunk(
                            parsed_chunk, source_format="gemini"
                        )
                    )

                done_chunk = {
                    "candidates": [
                        {
                            "content": {"parts": []},
                            "finishReason": "STOP",
                        }
                    ]
                }
                yield ProcessedResponse(
                    content=self.translation_service.to_domain_stream_chunk(
                        done_chunk, source_format="gemini"
                    )
                )
            finally:
                if hasattr(response, "aclose"):
                    await response.aclose()

        return StreamingResponseEnvelope(
            content=stream_generator(),
            media_type="text/event-stream",
            headers=dict(response.headers),
        )

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
            gemini_api_base_url,
            openrouter_api_base_url,
            api_key,
            key_name=key_name,
            **kwargs,
        )
        if identity:
            headers.update(identity.get_resolved_headers(None))

        # request_data is expected to be a domain ChatRequest (or subclass like CanonicalChatRequest)
        # (the frontend controller converts from frontend-specific format to domain format)
        # Backends should ONLY convert FROM domain TO backend-specific format
        # Type assertion: we know from architectural design that request_data is ChatRequest-like
        from typing import cast

        from src.core.domain.chat import CanonicalChatRequest, ChatRequest

        if not isinstance(request_data, ChatRequest):
            raise TypeError(
                f"Expected ChatRequest or CanonicalChatRequest, got {type(request_data).__name__}. "
                "Backend connectors should only receive domain-format requests."
            )
        # Cast to CanonicalChatRequest for mypy compatibility with translation service signature
        domain_request: CanonicalChatRequest = cast(CanonicalChatRequest, request_data)

        # Translate CanonicalChatRequest to Gemini request using the translation service
        payload = self.translation_service.from_domain_request(
            domain_request, target_format="gemini"
        )

        # Apply generation config including temperature clamping
        self._apply_generation_config(payload, domain_request)

        # Apply contents and extra_body
        payload["contents"] = self._prepare_gemini_contents(processed_messages)
        if domain_request.extra_body:
            # Merge extra_body with payload, but be careful with generationConfig.
            # We support both legacy placement under 'generation_config' and
            # the external 'generationConfig' key that Gemini expects.
            # Normalize: prefer explicit generation_config on ChatRequest, then
            # merge any 'generationConfig' present in extra_body on top.
            extra_body_copy = dict(domain_request.extra_body)

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

                extra_reasoning_effort: Any | None = None
                extra_thinking_cfg: dict[str, Any] | None = None

                for key, value in extra_gen_cfg.items():
                    if key == "thinkingConfig" and isinstance(value, dict):
                        extra_thinking_cfg = dict(value)
                        extra_reasoning_effort = extra_thinking_cfg.pop(
                            "reasoning_effort", extra_reasoning_effort
                        )
                        continue
                    if key == "reasoning_effort":
                        extra_reasoning_effort = value
                        continue
                    if key == "maxOutputTokens" and "maxOutputTokens" not in merged:
                        merged["maxOutputTokens"] = value
                        continue
                    merged[key] = value

                if extra_thinking_cfg is not None:
                    existing_thinking = merged.get("thinkingConfig")
                    if isinstance(existing_thinking, dict):
                        existing_thinking.update(extra_thinking_cfg)
                    else:
                        merged["thinkingConfig"] = extra_thinking_cfg

                if "temperature" in extra_gen_cfg:
                    merged["temperature"] = extra_gen_cfg["temperature"]

                if extra_reasoning_effort is not None:
                    self._apply_reasoning_effort_to_generation_config(
                        merged, extra_reasoning_effort
                    )

                merged.pop("reasoning_effort", None)
                payload["generationConfig"] = merged
                generation_config = payload["generationConfig"]

            # Finally update payload with remaining extra body fields
            if extra_body_copy:
                payload.update(extra_body_copy)
        # Remove generation_config (legacy key) if present; we've migrated it
        # into 'generationConfig' in _apply_generation_config.
        payload.pop("generation_config", None)

        if "generationConfig" in payload:
            generation_config = payload["generationConfig"]
            if isinstance(generation_config, dict):
                thinking_config = generation_config.get("thinkingConfig")
                reasoning_effort = None

                if isinstance(thinking_config, dict):
                    reasoning_effort = thinking_config.get("reasoning_effort")

                top_level_reasoning_effort = generation_config.get("reasoning_effort")
                if top_level_reasoning_effort is not None:
                    reasoning_effort = top_level_reasoning_effort

                if reasoning_effort is not None:
                    self._apply_reasoning_effort_to_generation_config(
                        generation_config, reasoning_effort
                    )

                if isinstance(thinking_config, dict):
                    thinking_config.pop("reasoning_effort", None)

                generation_config.pop("reasoning_effort", None)
        # Debug output
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Final payload: %s", payload)

        # Normalize model id and construct URL
        model_name = self._normalize_model_name(effective_model)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Constructing Gemini API URL with model_name: %s", model_name)
        model_url = f"{base_api_url}/v1beta/models/{model_name}"

        # Streaming vs non-streaming
        if domain_request.stream:
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
        *,
        key_name: str | None = None,
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
        header_candidate = (
            key_name or kwargs.get("key_name") or getattr(self, "key_name", None)
        )
        if not base or not key:
            raise HTTPException(
                status_code=500,
                detail="Gemini API base URL and API key must be provided.",
            )
        normalized_header = self._normalize_api_key_header(header_candidate)
        headers = ensure_loop_guard_header({normalized_header: key})
        return base.rstrip("/"), headers

    def _normalize_api_key_header(self, header_name: str | None) -> str:
        """Resolve the HTTP header name used for Gemini API keys."""

        if header_name is None:
            return DEFAULT_GEMINI_API_KEY_HEADER

        normalized = str(header_name).strip()
        if not normalized:
            return DEFAULT_GEMINI_API_KEY_HEADER

        if normalized.lower() == self.backend_type:
            return DEFAULT_GEMINI_API_KEY_HEADER

        return normalized

    @staticmethod
    def _map_reasoning_effort_to_budget(reasoning_effort: Any) -> int:
        """Map OpenAI-style reasoning_effort strings to Gemini thinking budgets."""

        if not isinstance(reasoning_effort, str):
            return -1

        effort_map = {
            "low": 512,
            "medium": 2048,
            "high": -1,
        }
        return effort_map.get(reasoning_effort.lower(), -1)

    def _apply_reasoning_effort_to_generation_config(
        self, generation_config: dict[str, Any], reasoning_effort: Any
    ) -> None:
        """Ensure reasoning_effort values become valid Gemini thinkingConfig."""

        if not reasoning_effort:
            return

        existing_thinking_config = generation_config.get("thinkingConfig")

        if existing_thinking_config is None:
            thinking_config: dict[str, Any] = {}
            generation_config["thinkingConfig"] = thinking_config
        elif isinstance(existing_thinking_config, dict):
            thinking_config = existing_thinking_config
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping reasoning_effort translation because thinkingConfig is %s",
                    type(existing_thinking_config).__name__,
                )
            return

        thinking_config.pop("reasoning_effort", None)

        if "thinkingBudget" not in thinking_config:
            thinking_config["thinkingBudget"] = self._map_reasoning_effort_to_budget(
                reasoning_effort
            )

        thinking_config.setdefault("includeThoughts", True)

    def _apply_generation_config(
        self, payload: dict[str, Any], request_data: ChatRequest
    ) -> None:
        # Initialize generationConfig
        generation_config = payload.setdefault("generationConfig", {})

        # thinking budget
        if getattr(request_data, "thinking_budget", None):
            thinking_config = generation_config.setdefault("thinkingConfig", {})
            thinking_config["thinkingBudget"] = request_data.thinking_budget  # type: ignore[index]

        # top_k
        if getattr(request_data, "top_k", None) is not None:
            generation_config["topK"] = request_data.top_k

        # reasoning_effort -> thinkingBudget translation
        if getattr(request_data, "reasoning_effort", None) is not None:
            self._apply_reasoning_effort_to_generation_config(
                generation_config, request_data.reasoning_effort
            )

        # generation config blob - merge with existing config
        if getattr(request_data, "generation_config", None):
            # Deep merge the generation_config into generationConfig
            for key, value in request_data.generation_config.items():  # type: ignore[union-attr]
                generation_config[key] = value

        # temperature clamped to [0,1]
        temperature = getattr(request_data, "temperature", None)
        if temperature is not None:
            # Clamp temperature to [0,1] range for Gemini
            if float(temperature) > 1.0:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Temperature {temperature} > 1.0 for Gemini, clamping to 1.0"
                    )
                temperature = 1.0
            generation_config["temperature"] = float(temperature)

        # top_p
        if request_data.top_p is not None:
            generation_config["topP"] = request_data.top_p

        # stop sequences
        if request_data.stop:
            generation_config["stopSequences"] = request_data.stop

        # Unsupported parameters
        if request_data.seed is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'seed' parameter.")
        if request_data.presence_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "GeminiBackend does not support the 'presence_penalty' parameter."
            )
        if request_data.frequency_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "GeminiBackend does not support the 'frequency_penalty' parameter."
            )
        if request_data.logit_bias is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'logit_bias' parameter.")
        if request_data.user is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'user' parameter.")

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
        headers = ensure_loop_guard_header(headers)
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

            domain_response = self.translation_service.to_domain_response(
                data, source_format="gemini"
            )

            return ResponseEnvelope(
                content=domain_response,
                headers=dict(response.headers),
                status_code=response.status_code,
                usage=domain_response.usage,
            )
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(message=f"Could not connect to Gemini ({e})")

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> dict[str, Any]:
        if not key_name:
            raise ValueError("key_name must be provided when listing Gemini models")
        normalized_header = str(key_name)
        headers = ensure_loop_guard_header({normalized_header: api_key})
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
