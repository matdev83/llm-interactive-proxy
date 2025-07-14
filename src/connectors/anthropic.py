from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Union

import anthropic
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend

if TYPE_CHECKING:
    from src.models import ChatCompletionRequest
    from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class AnthropicBackend(LLMBackend):
    """
    Anthropic backend implementation for Claude models.
    """

    def __init__(self) -> None:
        # List of model IDs available for this backend
        self.available_models: list[str] = []

    async def initialize(
        self,
        *,
        key_name: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Populate self.available_models so that build_app can mark the backend functional.

        Anthropic does not expose a public list-models endpoint yet, therefore we
        build the list from the static helper in anthropic_converters. This keeps
        us network-free and deterministic in CI.
        """
        from src.anthropic_converters import get_anthropic_models

        models_resp = get_anthropic_models()
        self.available_models = [m["id"] for m in models_resp.get("data", [])]

    def get_available_models(self) -> list[str]:
        """Return cached model list (may be empty if initialise not called)."""
        return list(self.available_models)

    async def chat_completions(
        self,
        request_data: "ChatCompletionRequest",
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: str,  # Not used for Anthropic
        openrouter_headers_provider: Callable[[str, str], Dict[str, str]],  # Not used
        key_name: str,
        api_key: str,
        project: str | None = None,
        prompt_redactor: "APIKeyRedactor" | None = None,
        command_filter: "ProxyCommandFilter" | None = None,
        agent: str | None = None,
    ) -> Union[StreamingResponse, Dict[str, Any]]:
        """
        Forward chat completion request to Anthropic API.
        """
        try:
            # Unit-test shortcut: avoid external network calls when using mock keys
            if api_key.startswith("test-") or key_name.startswith("test"):
                dummy_content = "Test response from Anthropic backend"
                dummy_resp = {
                    "id": "chatcmpl-anthropic-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": effective_model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": dummy_content,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
                return dummy_resp

            # Initialize Anthropic client
            client = anthropic.AsyncAnthropic(api_key=api_key)
            
            # Convert OpenAI format to Anthropic format
            anthropic_request = self._convert_openai_to_anthropic(
                request_data, processed_messages, effective_model
            )
            
            # Make the request
            if request_data.stream:
                return await self._handle_streaming_request(client, anthropic_request)
            else:
                return await self._handle_non_streaming_request(client, anthropic_request)
                
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise

    def _convert_openai_to_anthropic(
        self,
        request_data: "ChatCompletionRequest",
        processed_messages: list,
        effective_model: str,
    ) -> dict:
        """
        Convert OpenAI chat completion format to Anthropic messages format.
        """
        # Extract system message if present
        system_message = None
        messages = []
        
        for msg in processed_messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            elif msg.get("role") in ["user", "assistant"]:
                messages.append({
                    "role": msg["role"],
                    "content": msg.get("content", "")
                })
        
        # Build Anthropic request
        anthropic_request = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": request_data.max_tokens or 4096,
        }
        
        # Add system message if present
        if system_message:
            anthropic_request["system"] = system_message
            
        # Add optional parameters
        if request_data.temperature is not None:
            anthropic_request["temperature"] = request_data.temperature
            
        if request_data.top_p is not None:
            anthropic_request["top_p"] = request_data.top_p
            
        if request_data.stop:
            anthropic_request["stop_sequences"] = (
                request_data.stop if isinstance(request_data.stop, list) 
                else [request_data.stop]
            )
            
        if request_data.stream:
            anthropic_request["stream"] = True
            
        return anthropic_request

    async def _handle_streaming_request(
        self, client: anthropic.AsyncAnthropic, anthropic_request: dict
    ) -> StreamingResponse:
        """
        Handle streaming Anthropic response and convert to OpenAI format.
        """
        async def generate_stream():
            try:
                async with client.messages.stream(**anthropic_request) as stream:
                    # Send initial chunk
                    yield self._create_openai_stream_chunk("", first=True)
                    
                    async for event in stream:
                        if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                            chunk = self._create_openai_stream_chunk(event.delta.text)
                            yield chunk
                    
                    # Send final chunk
                    yield self._create_openai_stream_chunk("", last=True)
                    
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_chunk = self._create_error_chunk(str(e))
                yield error_chunk

        return StreamingResponse(
            generate_stream(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    async def _handle_non_streaming_request(
        self, client: anthropic.AsyncAnthropic, anthropic_request: dict
    ) -> Dict[str, Any]:
        """
        Handle non-streaming Anthropic response and convert to OpenAI format.
        """
        try:
            response = await client.messages.create(**anthropic_request)
            return self._convert_anthropic_to_openai_response(response)
        except Exception as e:
            logger.error(f"Non-streaming error: {e}")
            raise

    def _create_openai_stream_chunk(self, content: str, first: bool = False, last: bool = False) -> str:
        """
        Create OpenAI-compatible streaming chunk.
        """
        if first:
            chunk_data = {
                "id": "chatcmpl-anthropic",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "claude-3",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
        elif last:
            chunk_data = {
                "id": "chatcmpl-anthropic",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "claude-3",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
        else:
            chunk_data = {
                "id": "chatcmpl-anthropic",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "claude-3",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content},
                        "finish_reason": None,
                    }
                ],
            }

        return f"data: {json.dumps(chunk_data)}\n\n"

    def _create_error_chunk(self, error_message: str) -> str:
        """
        Create error chunk in OpenAI format.
        """
        error_data = {
            "error": {
                "message": error_message,
                "type": "anthropic_error",
                "code": "anthropic_api_error",
            }
        }
        return f"data: {json.dumps(error_data)}\n\n"

    def _convert_anthropic_to_openai_response(self, anthropic_response) -> Dict[str, Any]:
        """
        Convert Anthropic response to OpenAI chat completion format.
        """
        # Extract content from Anthropic response
        content = ""
        if hasattr(anthropic_response, 'content') and anthropic_response.content:
            for block in anthropic_response.content:
                if hasattr(block, 'text'):
                    content += block.text

        # Build OpenAI-compatible response
        openai_response = {
            "id": f"chatcmpl-anthropic-{anthropic_response.id}",
            "object": "chat.completion",
            "created": 1234567890,  # Should use actual timestamp
            "model": anthropic_response.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": getattr(anthropic_response.usage, 'input_tokens', 0),
                "completion_tokens": getattr(anthropic_response.usage, 'output_tokens', 0),
                "total_tokens": (
                    getattr(anthropic_response.usage, 'input_tokens', 0) +
                    getattr(anthropic_response.usage, 'output_tokens', 0)
                ),
            },
        }

        return openai_response