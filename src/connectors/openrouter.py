import httpx
import json
import logging
from typing import Union, Dict, Any, Callable

from starlette.responses import StreamingResponse
from fastapi import HTTPException # Required for raising HTTP exceptions

# Assuming ChatCompletionRequest is in src.models
from src.models import ChatCompletionRequest
from src.connectors.base import LLMBackend
# proxy_state and process_commands_in_messages are currently in src.proxy_logic
# These are used in main.py *before* calling the backend.
# The backend connector should ideally receive the final, processed payload.
# For now, this means the OpenRouterBackend will expect 'processed_messages' and 'effective_model'
# to be part of the request_data or handled before calling it.
# Let's assume the call in main.py will be adjusted to pass the correct data.

logger = logging.getLogger(__name__)

class OpenRouterBackend(LLMBackend):
    """
    LLMBackend implementation for OpenRouter.ai.
    """

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,  # This is the original request
        processed_messages: list,  # Messages after command processing
        effective_model: str,  # Model after considering override
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[[], Dict[str, str]],
        project: str | None = None,
    ) -> Union[StreamingResponse, Dict[str, Any]]:
        """
        Forwards a chat completion request to the OpenRouter API.

        Args:
            request_data: The original ChatCompletionRequest model instance.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            openrouter_api_base_url: The base URL for the OpenRouter API.
            openrouter_headers_provider: A callable that returns OpenRouter API headers.

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
        openrouter_payload["messages"] = [msg.model_dump(exclude_unset=True) for msg in processed_messages]
        if project is not None:
            openrouter_payload["project"] = project

        logger.info(f"Forwarding to OpenRouter. Effective model: {effective_model}. Stream: {request_data.stream}")
        logger.debug(f"Payload for OpenRouter: {json.dumps(openrouter_payload, indent=2)}")

        headers = openrouter_headers_provider()

        try:
            if request_data.stream:
                logger.debug("Initiating stream request to OpenRouter.")

                async def stream_generator():
                    try:
                        async with self.client.stream("POST", f"{openrouter_api_base_url}/chat/completions",
                                                       json=openrouter_payload, headers=headers) as response:
                            logger.debug(f"OpenRouter stream response status: {response.status_code}")
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                yield chunk
                            logger.debug("OpenRouter stream finished.")
                    except httpx.HTTPStatusError as e_stream:
                        logger.info("Caught httpx.HTTPStatusError in stream_generator")
                        logger.error(f"HTTP error during OpenRouter stream: {e_stream.response.status_code} - {e_stream.response.content.decode('utf-8')}")
                        # Yield an error message in SSE format for the client
                        error_payload = {
                            "error": {
                                "message": f"OpenRouter stream error: {e_stream.response.status_code} - {e_stream.response.content.decode('utf-8')}",
                                "type": "openrouter_error",
                                "code": e_stream.response.status_code
                            }
                        }
                        # For streaming errors, raise HTTPException directly
                        # This will be caught by the outer try-except block in chat_completions
                        # and re-raised as an HTTPException by FastAPI
                        raise HTTPException(
                            status_code=e_stream.response.status_code,
                            detail={"message": f"OpenRouter stream error: {e_stream.response.status_code} - {e_stream.response.content.decode('utf-8')}",
                                    "type": "openrouter_error",
                                    "code": e_stream.response.status_code}
                        )
                    except Exception as e_gen:
                        logger.error(f"Error in stream generator: {e_gen}", exc_info=True)
                        # For unexpected errors in generator, raise HTTPException
                        raise HTTPException(
                            status_code=500,
                            detail={"message": f"Proxy stream generator error: {str(e_gen)}",
                                    "type": "proxy_error",
                                    "code": "proxy_stream_error"}
                        )

                return StreamingResponse(stream_generator(), media_type="text/event-stream")

            else: # Non-streaming request
                logger.debug("Initiating non-streaming request to OpenRouter.")
                response = await self.client.post(f"{openrouter_api_base_url}/chat/completions",
                                             json=openrouter_payload, headers=headers)
                logger.debug(f"OpenRouter non-stream response status: {response.status_code}")
                response.raise_for_status()

                response_json = response.json()
                logger.debug(f"OpenRouter response JSON: {json.dumps(response_json, indent=2)}")
                return response_json

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from OpenRouter: {e.response.status_code} - {e.response.text}", exc_info=True)
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to OpenRouter: {type(e).__name__} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to OpenRouter ({str(e)})")
        except Exception as e:
            # This catches errors during the setup of the request or unexpected issues
            logger.error(f"An unexpected error occurred in OpenRouterBackend.chat_completions: {type(e).__name__} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal server error in backend connector: {str(e)}")

    async def list_models(
        self,
        *,
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[[], Dict[str, str]],
    ) -> Dict[str, Any]:
        """Fetch available models from OpenRouter."""
        headers = openrouter_headers_provider()
        try:
            response = await self.client.get(f"{openrouter_api_base_url}/models", headers=headers)
            response.raise_for_status()
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
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
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
            raise HTTPException(status_code=500, detail=f"Internal server error in backend connector: {str(e)}")
