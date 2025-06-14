from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Union

import httpx
from fastapi import HTTPException  # Required for raising HTTP exceptions
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend

# Assuming ChatCompletionRequest is in src.models
from src.models import ChatCompletionRequest
from src.security import APIKeyRedactor

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
    ) -> Union[StreamingResponse, Dict[str, Any]]:
        """
        Forwards a chat completion request to the OpenRouter API.

        Args:
            request_data: The original ChatCompletionRequest model instance.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            openrouter_api_base_url: The base URL for the OpenRouter API.
            openrouter_headers_provider: A callable that returns OpenRouter API headers.
            prompt_redactor: Optional APIKeyRedactor used to sanitize messages.

        Returns:
            A StreamingResponse for streaming requests, or a dict for non-streaming.

        Raises:
            HTTPException: If OpenRouter returns an HTTP error (e.g., 4xx, 5xx)
                           or if there's a request error (e.g., connection issue).
                           Also for unexpected errors during processing.
        """

        openrouter_payload = request_data.model_dump(exclude_unset=True)
        openrouter_payload["model"] = effective_model
        # Ensure messages are in dict format, not Pydantic models
        openrouter_payload["messages"] = [
            msg.model_dump(exclude_unset=True) for msg in processed_messages
        ]
        if project is not None:
            openrouter_payload["project"] = project

        if prompt_redactor:
            for msg in openrouter_payload["messages"]:
                if isinstance(msg.get("content"), str):
                    msg["content"] = prompt_redactor.redact(msg["content"])
                elif isinstance(msg.get("content"), list):
                    for part in msg["content"]:
                        if part.get("type") == "text" and "text" in part:
                            part["text"] = prompt_redactor.redact(part["text"])

        logger.info(
            f"Forwarding to OpenRouter. Effective model: {effective_model}. Stream: {request_data.stream}"
        )
        logger.debug(
            f"Payload for OpenRouter: {json.dumps(openrouter_payload, indent=2)}"
        )

        headers = openrouter_headers_provider(key_name, api_key)

        try:
            if request_data.stream:
                logger.debug("Initiating stream request to OpenRouter.")

                async def stream_generator():
                    try:
                        async with self.client.stream(
                            "POST",
                            f"{openrouter_api_base_url}/chat/completions",
                            json=openrouter_payload,
                            headers=headers,
                        ) as response:
                            logger.debug(
                                f"OpenRouter stream response status: {response.status_code}"
                            )
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                yield chunk
                            logger.debug("OpenRouter stream finished.")
                    except httpx.HTTPStatusError as e_stream:
                        logger.info(
                            "Caught httpx.HTTPStatusError in stream_generator")
                        try:
                            body_text = (await e_stream.response.aread()).decode(
                                "utf-8"
                            )
                        except Exception:
                            body_text = ""
                        logger.error(
                            "HTTP error during OpenRouter stream: %s - %s",
                            e_stream.response.status_code,
                            body_text,
                        )
                        # For streaming errors, raise HTTPException directly
                        raise HTTPException(
                            status_code=e_stream.response.status_code,
                            detail={
                                "message": f"OpenRouter stream error: {e_stream.response.status_code} - {body_text}",
                                "type": "openrouter_error",
                                "code": e_stream.response.status_code,
                            },
                        )
                    except Exception as e_gen:
                        logger.error(
                            f"Error in stream generator: {e_gen}",
                            exc_info=True)
                        # For unexpected errors in generator, raise
                        # HTTPException
                        raise HTTPException(
                            status_code=500,
                            detail={
                                "message": f"Proxy stream generator error: {str(e_gen)}",
                                "type": "proxy_error",
                                "code": "proxy_stream_error",
                            },
                        )

                return StreamingResponse(
                    stream_generator(), media_type="text/event-stream"
                )

            else:  # Non-streaming request
                logger.debug("Initiating non-streaming request to OpenRouter.")
                response = await self.client.post(
                    f"{openrouter_api_base_url}/chat/completions",
                    json=openrouter_payload,
                    headers=headers,
                )
                logger.debug(
                    f"OpenRouter non-stream response status: {response.status_code}"
                )

                # Manual status code check for compatibility with pytest_httpx
                # mocks
                if response.status_code >= 400:
                    try:
                        error_detail = response.json()
                    except Exception:
                        error_detail = response.text
                    raise HTTPException(
                        status_code=response.status_code, detail=error_detail
                    )

                response_json = response.json()
                logger.debug(
                    f"OpenRouter response JSON: {json.dumps(response_json, indent=2)}"
                )
                return response_json

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
