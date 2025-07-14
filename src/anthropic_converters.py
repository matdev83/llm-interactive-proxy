"""
Converters for translating between Anthropic and OpenAI API formats.
This module isolates the mapping logic to handle potential spec drift.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Union, Literal

import anthropic
from pydantic import BaseModel


from typing import Literal

class AnthropicMessage(BaseModel):
    """Anthropic message format."""
    role: Literal["user", "assistant", "system"]
    content: str


class AnthropicMessagesRequest(BaseModel):
    """Anthropic /v1/messages request format."""
    model: str
    messages: List[AnthropicMessage]
    max_tokens: int
    system: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False


def anthropic_to_openai_request(anthropic_req: AnthropicMessagesRequest) -> Dict[str, Any]:
    """
    Convert Anthropic /v1/messages request to OpenAI /v1/chat/completions format.
    
    Args:
        anthropic_req: Anthropic request object
        
    Returns:
        OpenAI-compatible request dictionary
    """
    # Convert messages, adding system message if present
    openai_messages = []
    
    # Add system message first if present
    if anthropic_req.system:
        openai_messages.append({
            "role": "system",
            "content": anthropic_req.system
        })
    
    # Add conversation messages
    for msg in anthropic_req.messages:
        openai_messages.append({
            "role": msg.role,
            "content": msg.content
        })
    
    # Build OpenAI request
    openai_request = {
        "model": anthropic_req.model,
        "messages": openai_messages,
        "max_tokens": anthropic_req.max_tokens,
        "stream": anthropic_req.stream or False,
    }
    
    # Add optional parameters
    if anthropic_req.temperature is not None:
        openai_request["temperature"] = anthropic_req.temperature
        
    if anthropic_req.top_p is not None:
        openai_request["top_p"] = anthropic_req.top_p
        
    # Note: top_k is dropped as OpenAI doesn't support it
    
    if anthropic_req.stop_sequences:
        openai_request["stop"] = anthropic_req.stop_sequences
    
    return openai_request


def openai_to_anthropic_response(openai_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert OpenAI chat completion response to Anthropic /v1/messages format.
    
    Args:
        openai_response: OpenAI response dictionary
        
    Returns:
        Anthropic-compatible response dictionary
    """
    # Handle streaming vs non-streaming
    if "choices" not in openai_response:
        # This might be an error response, return a basic structure
        return {
            "id": openai_response.get("id", "msg-error"),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": ""}],
            "model": openai_response.get("model", "claude-3"),
            "stop_reason": "end_turn",
            "stop_sequence": None,
        }
    
    choice = openai_response["choices"][0]
    message = choice.get("message", {})
    content = message.get("content", "")
    
    # Build Anthropic response format
    anthropic_response = {
        "id": openai_response.get("id", "msg-anthropic"),
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": content
            }
        ],
        "model": openai_response.get("model", "claude-3"),
        "stop_reason": _map_finish_reason(choice.get("finish_reason")),
        "stop_sequence": None,
    }
    
    # Add usage information if present
    if "usage" in openai_response:
        usage = openai_response["usage"]
        anthropic_response["usage"] = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0)
        }
    
    return anthropic_response


def openai_stream_to_anthropic_stream(openai_chunk: str) -> str:
    """
    Convert OpenAI streaming chunk to Anthropic streaming format.
    
    Args:
        openai_chunk: OpenAI SSE chunk (data: {...})
        
    Returns:
        Anthropic-compatible SSE chunk
    """
    if not openai_chunk.startswith("data: "):
        return openai_chunk
    
    try:
        # Parse OpenAI chunk
        chunk_data = json.loads(openai_chunk[6:])  # Remove "data: " prefix
        
        if "choices" not in chunk_data:
            return openai_chunk  # Pass through non-choice chunks
        
        choice = chunk_data["choices"][0]
        delta = choice.get("delta", {})
        
        # Handle different types of chunks
        if "role" in delta:
            # Start of message
            anthropic_event = {
                "type": "message_start",
                "message": {
                    "id": chunk_data.get("id", "msg-anthropic"),
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": chunk_data.get("model", "claude-3"),
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0}
                }
            }
        elif "content" in delta and delta["content"]:
            # Content delta
            anthropic_event = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": delta["content"]
                }
            }
        elif choice.get("finish_reason"):
            # End of message
            anthropic_event = {
                "type": "message_delta",
                "delta": {
                    "stop_reason": _map_finish_reason(choice["finish_reason"]),
                    "stop_sequence": None
                },
                "usage": {
                    "output_tokens": 1  # Approximate
                }
            }
        else:
            # Unknown chunk type, pass through
            return openai_chunk
        
        return f"data: {json.dumps(anthropic_event)}\n\n"
        
    except (json.JSONDecodeError, KeyError) as e:
        # If parsing fails, pass through original
        return openai_chunk


def _map_finish_reason(openai_reason: Optional[str]) -> Optional[str]:
    """
    Map OpenAI finish_reason to Anthropic stop_reason.
    
    Args:
        openai_reason: OpenAI finish reason
        
    Returns:
        Anthropic stop reason
    """
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "content_filter": "stop_sequence",
        "function_call": "tool_use",  # If we support tools later
        None: None
    }
    
    return mapping.get(openai_reason, "end_turn")


def get_anthropic_models() -> Dict[str, Any]:
    """
    Return list of available Anthropic models in OpenAI /v1/models format.
    
    Returns:
        OpenAI-compatible models response
    """
    # Common Anthropic models
    anthropic_models = [
        {
            "id": "claude-3-5-sonnet-20241022",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "anthropic",
        },
        {
            "id": "claude-3-5-haiku-20241022", 
            "object": "model",
            "created": int(time.time()),
            "owned_by": "anthropic",
        },
        {
            "id": "claude-3-opus-20240229",
            "object": "model", 
            "created": int(time.time()),
            "owned_by": "anthropic",
        },
        {
            "id": "claude-3-sonnet-20240229",
            "object": "model",
            "created": int(time.time()), 
            "owned_by": "anthropic",
        },
        {
            "id": "claude-3-haiku-20240307",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "anthropic",
        },
    ]
    
    return {
        "object": "list",
        "data": anthropic_models
    }


def extract_anthropic_usage(anthropic_response: Union[Dict[str, Any], Any]) -> Dict[str, int]:
    """
    Extract token usage information from Anthropic response.
    
    Args:
        anthropic_response: Anthropic API response
        
    Returns:
        Usage dictionary with token counts
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    try:
        if isinstance(anthropic_response, dict):
            # Dictionary response
            if "usage" in anthropic_response:
                usage_data = anthropic_response["usage"]
                usage["input_tokens"] = usage_data.get("input_tokens", 0)
                usage["output_tokens"] = usage_data.get("output_tokens", 0)
        else:
            # Anthropic response object (including Mock objects for testing)
            if hasattr(anthropic_response, "usage"):
                usage_obj = anthropic_response.usage
                # Handle both real objects and Mock objects
                if hasattr(usage_obj, "input_tokens"):
                    usage["input_tokens"] = int(getattr(usage_obj, "input_tokens", 0))
                if hasattr(usage_obj, "output_tokens"):
                    usage["output_tokens"] = int(getattr(usage_obj, "output_tokens", 0))
        
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        
    except Exception as e:
        # If extraction fails, return zeros but log for debugging
        import logging
        logging.getLogger(__name__).debug("extract_anthropic_usage error: %s", e)
    
    return usage