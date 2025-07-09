from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Union, Tuple

import httpx
from fastapi import HTTPException  # Required for raising HTTP exceptions
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend

# Assuming ChatCompletionRequest is in src.models
from src.models import ChatCompletionRequest
from src.security import APIKeyRedactor, ProxyCommandFilter

# proxy_state and process_commands_in_messages are currently in src.proxy_logic
# These are used in main.py *before* calling the backend.
# The backend connector should ideally receive the final, processed payload.
# For now, this means the OpenRouterBackend will expect 'processed_messages' and 'effective_model'
# to be part of the request_data or handled before calling it.
# Let's assume the call in main.py will be adjusted to pass the correct data.

logger = logging.getLogger(__name__)


class OpenRouterBackend(LLMBackend):
    """LLMBackend implementation for OpenRouter.ai."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []

    async def initialize(
        self,
        *,
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[[str, str], Dict[str, str]],
        key_name: str,
        api_key: str,
    ) -> None:
        """Fetch available models and cache them for later use."""
        data = await self.list_models(
            openrouter_api_base_url=openrouter_api_base_url,
            openrouter_headers_provider=openrouter_headers_provider,
            key_name=key_name,
            api_key=api_key,
        )
        self.available_models = [
            m.get("id") for m in data.get("data", []) if m.get("id")
        ]

    def get_available_models(self) -> list[str]:
        """Return the list of cached model identifiers."""
        return list(self.available_models)

    def _redact_message_content(self, content: Any, prompt_redactor: APIKeyRedactor) -> Any:
        """Redacts text content within a message string or list of parts."""
        if isinstance(content, str):
            return prompt_redactor.redact(content)
        elif isinstance(content, list):
            # Process parts. Assuming parts are dictionaries as they come from model_dump().
            for part_dict in content:
                if isinstance(part_dict, dict) and part_dict.get("type") == "text" and "text" in part_dict:
                    part_dict["text"] = prompt_redactor.redact(part_dict["text"])
            return content # Return the modified list of dicts
        return content # No change for other types, or if content is None

    def _filter_message_content(self, content: Any, command_filter: ProxyCommandFilter) -> Any:
        """Emergency filter to remove proxy commands from message content."""
        if isinstance(content, str):
            return command_filter.filter_commands(content)
        elif isinstance(content, list):
            # Process parts. Assuming parts are dictionaries as they come from model_dump().
            for part_dict in content:
                if isinstance(part_dict, dict) and part_dict.get("type") == "text" and "text" in part_dict:
                    part_dict["text"] = command_filter.filter_commands(part_dict["text"])
            return content # Return the modified list of dicts
        return content # No change for other types, or if content is None

    def _prepare_openrouter_payload(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        project: str | None,
        prompt_redactor: APIKeyRedactor | None,
        command_filter: ProxyCommandFilter | None,
    ) -> Dict[str, Any]:
        """Constructs the payload for the OpenRouter API request."""
        payload = request_data.model_dump(exclude_unset=True)
        payload["model"] = effective_model
        # Ensure messages are in dict format, not Pydantic models
        payload["messages"] = [
            msg.model_dump(exclude_unset=True) for msg in processed_messages
        ]
        if project is not None:
            payload["project"] = project

        # Always request usage information for billing tracking
        payload["usage"] = {"include": True}

        # Apply emergency command filter first (before API key redaction)
        if command_filter:
            for msg_payload in payload["messages"]:
                original_content = msg_payload.get("content")
                msg_payload["content"] = self._filter_message_content(original_content, command_filter)

        # Apply API key redaction second
        if prompt_redactor:
            for msg_payload in payload["messages"]:
                original_content = msg_payload.get("content")
                msg_payload["content"] = self._redact_message_content(original_content, prompt_redactor)
        return payload

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,  # This is the original request
        processed_messages: list,  # Messages after command processing
        effective_model: str,  # Model after considering override
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[[str, str], Dict[str, str]],
        key_name: str,
        api_key: str,
        project: str | None = None,
        prompt_redactor: APIKeyRedactor | None = None,
        command_filter: ProxyCommandFilter | None = None,
    ) -> Union[StreamingResponse, Tuple[Dict[str, Any], Dict[str, str]]]:

        openrouter_payload = self._prepare_openrouter_payload(
            request_data,
            processed_messages,
            effective_model,
            project,
            prompt_redactor,
            command_filter,
        )

        logger.info(
            f"Forwarding to OpenRouter. Effective model: {effective_model}. Stream: {request_data.stream}"
        )
        logger.debug(
            f"Payload for OpenRouter: {json.dumps(openrouter_payload, indent=2)}"
        )

        headers = openrouter_headers_provider(key_name, api_key)
        api_url = f"{openrouter_api_base_url}/chat/completions"

        try:
            if request_data.stream:
                return await self._handle_openrouter_streaming_response(
                    api_url, openrouter_payload, headers
                )
            else:  # Non-streaming request
                response_json, response_headers = await self._handle_openrouter_non_streaming_response(
                    api_url, openrouter_payload, headers
                )
                return response_json, response_headers
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error from OpenRouter: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(
                status_code=e.response.status_code,
                detail=error_detail)
        except httpx.RequestError as e:
            logger.error(
                f"Request error connecting to OpenRouter: {type(e).__name__} - {str(e)}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to OpenRouter ({str(e)})",
            )
        # HTTPException and other unexpected errors will now propagate up.

    async def _handle_openrouter_non_streaming_response(
        self, url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        logger.debug("Initiating non-streaming request to OpenRouter.")
        response = await self.client.post(url, json=payload, headers=headers)
        logger.debug(f"OpenRouter non-stream response status: {response.status_code}")

        if response.status_code >= 400: # Check for HTTP errors
            try:
                error_detail = response.json()
            except json.JSONDecodeError: # If response is not JSON
                error_detail = response.text
            raise HTTPException(
                status_code=response.status_code, detail=error_detail
            )

        response_json = response.json()
        response_headers = dict(response.headers)
        logger.debug(f"OpenRouter response JSON: {json.dumps(response_json, indent=2)}")
        logger.debug(f"OpenRouter response headers: {response_headers}")
        return response_json, response_headers

    async def _handle_openrouter_streaming_response(
        self, url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> StreamingResponse:
        logger.debug("Initiating stream request to OpenRouter.")

        async def stream_generator():
            try:
                async with self.client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    logger.debug(f"OpenRouter stream response status: {response.status_code}")
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
                    logger.debug("OpenRouter stream finished.")
            except httpx.HTTPStatusError as e_stream:
                logger.info("Caught httpx.HTTPStatusError in stream_generator")
                body_text = ""
                try:
                    body_text = (await e_stream.response.aread()).decode("utf-8")
                except Exception: # pragma: no cover
                    pass # Keep body_text empty if decoding fails
                logger.error(
                    "HTTP error during OpenRouter stream: %s - %s",
                    e_stream.response.status_code,
                    body_text,
                )
                raise HTTPException(
                    status_code=e_stream.response.status_code,
                    detail={
                        "message": f"OpenRouter stream error: {e_stream.response.status_code} - {body_text}",
                        "type": "openrouter_error",
                        "code": e_stream.response.status_code,
                    },
                )
            except Exception as e_gen: # pragma: no cover - for truly unexpected errors
                logger.error(f"Error in stream generator: {e_gen}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": f"Proxy stream generator error: {str(e_gen)}",
                        "type": "proxy_error",
                        "code": "proxy_stream_error",
                    },
                )

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def list_models(
        self,
        *,
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[[str, str], Dict[str, str]],
        key_name: str,
        api_key: str,
    ) -> Dict[str, Any]:
        """Fetch available models from OpenRouter."""
        headers = openrouter_headers_provider(key_name, api_key)
        try:
            response = await self.client.get(
                f"{openrouter_api_base_url}/models", headers=headers
            )

            if not response.is_success:
                try:
                    error_detail = response.json()
                except json.JSONDecodeError:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code, detail=error_detail
                )

            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error from OpenRouter: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(
                status_code=e.response.status_code,
                detail=error_detail)
        except httpx.RequestError as e:
            logger.error(
                f"Request error connecting to OpenRouter: {type(e).__name__} - {str(e)}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to OpenRouter ({str(e)})",
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred in OpenRouterBackend.list_models: {type(e).__name__} - {str(e)}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error in backend connector: {str(e)}",
            )
