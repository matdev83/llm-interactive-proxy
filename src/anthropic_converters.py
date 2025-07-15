
"""Converter functions between Anthropic API format and OpenAI format."""
import json
import logging

from typing import List, Dict, Any
from src.anthropic_models import (
    AnthropicMessagesRequest, AnthropicMessagesResponse, AnthropicMessage, ContentBlock, Usage
)
from src.models import (
    ChatCompletionRequest, ChatMessage, ChatCompletionResponse, ChatCompletionChoice,
    ChatCompletionChoiceMessage, CompletionUsage
)


def anthropic_to_openai_request(anthropic_request: AnthropicMessagesRequest) -> ChatCompletionRequest:
    """Convert Anthropic MessagesRequest to OpenAI ChatCompletionRequest."""
    messages = []
    if anthropic_request.system:
        messages.append(ChatMessage(role="system", content=anthropic_request.system))
    
    for msg in anthropic_request.messages:
        messages.append(ChatMessage(role=msg.role, content=msg.content))

    return ChatCompletionRequest(
        model=anthropic_request.model,
        messages=messages,
        max_tokens=anthropic_request.max_tokens,
        temperature=anthropic_request.temperature,
        top_p=anthropic_request.top_p,
        stop=anthropic_request.stop_sequences,
        stream=anthropic_request.stream,
    )


def openai_to_anthropic_response(openai_response: ChatCompletionResponse) -> AnthropicMessagesResponse:
    """Convert OpenAI ChatCompletionResponse to Anthropic MessagesResponse."""
    choice = openai_response.choices[0]
    content_blocks = [ContentBlock(type="text", text=choice.message.content)]

    return AnthropicMessagesResponse(
        id=openai_response.id,
        type="message",
        role="assistant",
        content=content_blocks,
        model=openai_response.model,
        stop_reason=choice.finish_reason,
        usage=Usage(
            input_tokens=openai_response.usage.prompt_tokens,
            output_tokens=openai_response.usage.completion_tokens,
        ),
    )


def openai_to_anthropic_stream_chunk(chunk_data: str, id: str, model: str) -> str:
    """Convert OpenAI streaming chunk to Anthropic streaming format."""
    try:
        # Strip SSE prefix if present
        if chunk_data.startswith("data: "):
            chunk_data = chunk_data[6:]

        # Terminal marker
        if chunk_data.strip() == "[DONE]":
            return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"

        openai_chunk: Dict[str, Any] = json.loads(chunk_data)
        choice: Dict[str, Any] = openai_chunk.get("choices", [{}])[0]
        delta: Dict[str, Any] = choice.get("delta", {})

        # Content delta
        if delta.get("content"):
            content = delta["content"]
            payload = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": content},
            }
            return f"event: content_block_delta\ndata: {json.dumps(payload)}\n\n"

        # Finish reason delta
        if choice.get("finish_reason"):
            payload = {
                "type": "message_delta",
                "delta": {"stop_reason": choice["finish_reason"]},
            }
            return f"event: message_delta\ndata: {json.dumps(payload)}\n\n"
    except json.JSONDecodeError:
        # Ignore bad JSON chunk
        return ""
    except Exception as e:
        # Log for debugging but return empty to keep stream alive
        logging.getLogger(__name__).debug("Failed to convert stream chunk: %s", e)
        return ""
