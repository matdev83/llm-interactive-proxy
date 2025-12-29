"""
Response post-processor strategies for Gemini OAuth connectors.

This module provides different response processing implementations:
- NoOpResponsePostProcessor: Pass-through, no modifications
- XmlToolCallPostProcessor: Parse XML tool calls (Antigravity/Claude)
"""

import json
import logging
import re
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    FunctionCall,
    ToolCall,
)

if TYPE_CHECKING:
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class NoOpResponsePostProcessor:
    """Response post-processor that does nothing (pass-through).

    Used by gemini-oauth-plan and gemini-oauth-free backends.
    """

    def process(
        self,
        response: "ResponseEnvelope",
        effective_model: str,
    ) -> "ResponseEnvelope":
        """Pass through the response without modification.

        Args:
            response: The response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The unmodified response envelope.
        """
        return response

    async def process_streaming(
        self,
        response: "StreamingResponseEnvelope",
        effective_model: str,
    ) -> "StreamingResponseEnvelope":
        """Pass through the streaming response without modification.

        Args:
            response: The streaming response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The unmodified streaming response envelope.
        """
        return response


class XmlToolCallPostProcessor:
    """Response post-processor that parses XML tool calls.

    Used by antigravity-oauth backend.
    Claude models through Antigravity may return tool calls as XML text
    in the response content, which needs to be parsed and converted
    to proper tool_calls format.
    """

    # Regex pattern to extract <Tool> blocks
    TOOL_PATTERN = re.compile(r"<Tool>(.*?)</Tool>", re.DOTALL)

    def process(
        self,
        response: "ResponseEnvelope",
        effective_model: str,
    ) -> "ResponseEnvelope":
        """Post-process response to handle XML tool calls for Sonnet 4.5.

        This is a workaround for the model returning tool calls as XML text.

        Args:
            response: The response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed response envelope with tool calls parsed.
        """
        # Check if response content is a string with XML tool calls
        if not isinstance(response.content, str):
            return response

        if "<Tool>" not in response.content:
            return response

        content = response.content
        tool_calls = self._extract_tool_calls_from_xml(content)

        if not tool_calls:
            return response

        # Remove the <Tool> block from content
        match = self.TOOL_PATTERN.search(content)
        if match:
            content = content.replace(match.group(0), "").strip()

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
        return response

    async def process_streaming(
        self,
        response: "StreamingResponseEnvelope",
        effective_model: str,
    ) -> "StreamingResponseEnvelope":
        """Post-process streaming response to handle XML tool calls.

        This method intercepts the stream, buffers it, and checks for XML tool calls.
        This adds latency but is necessary for correctness with Claude models
        through the Antigravity backend.

        Args:
            response: The streaming response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed streaming response envelope.
        """
        from src.core.domain.responses import StreamingResponseEnvelope
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        # Check if content is an async iterable
        if response.content is None or not hasattr(response.content, "__aiter__"):
            return response

        original_iterator = response.content

        async def _intercept_stream() -> AsyncGenerator["ProcessedResponse", None]:
            import uuid

            buffer: list[ProcessedResponse] = []
            buffer_size = 0
            MAX_BUFFER_SIZE = 5 * 1024 * 1024  # 5MB limit for tool detection

            async for chunk in original_iterator:
                buffer.append(chunk)

                # Estimate size to prevent OOM/DoS
                if hasattr(chunk, "content"):
                    chunk_content = chunk.content
                    if isinstance(chunk_content, str):
                        buffer_size += len(chunk_content)
                    elif isinstance(chunk_content, dict):
                        # Rough estimate for dict content
                        choices = chunk_content.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content_part = delta.get("content", "")
                            if content_part:
                                buffer_size += len(content_part)

                if buffer_size > MAX_BUFFER_SIZE:
                    # Buffer exceeded limit, stop buffering and yield everything
                    logger.warning(
                        "Response exceeded %s bytes during XML tool detection; skipping tool parsing to prevent OOM/DoS.",
                        MAX_BUFFER_SIZE,
                    )
                    for buffered_chunk in buffer:
                        yield buffered_chunk
                    buffer = []
                    # Stream remaining chunks directly
                    async for remaining_chunk in original_iterator:
                        yield remaining_chunk
                    return

            # Reconstruct full content
            full_content = ""
            for chunk in buffer:
                if hasattr(chunk, "content"):
                    chunk_content = chunk.content
                    if isinstance(chunk_content, dict):
                        choices = chunk_content.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content_part = delta.get("content", "")
                            if content_part:
                                full_content += content_part
                    elif isinstance(chunk_content, str):
                        full_content += chunk_content

            # Check for XML tool calls
            tool_calls: list[dict[str, Any]] = []
            if "<Tool>" in full_content:
                tool_calls = self._extract_tool_calls_dict_from_xml(full_content)
                if tool_calls:
                    match = self.TOOL_PATTERN.search(full_content)
                    if match:
                        full_content = full_content.replace(match.group(0), "").strip()

            if tool_calls and buffer:
                # Yield content first if any
                if full_content:
                    yield ProcessedResponse(
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
                                        "content": full_content,
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )

                # Yield tool calls
                yield ProcessedResponse(
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
                # Re-yield original chunks
                for chunk in buffer:
                    yield chunk

        return StreamingResponseEnvelope(
            content=_intercept_stream(),
            media_type=response.media_type,
            headers=response.headers,
        )

    def _extract_tool_calls_from_xml(self, content: str) -> list[ToolCall]:
        """Extract ToolCall objects from XML content.

        Args:
            content: The content string potentially containing XML tool calls.

        Returns:
            List of ToolCall objects.
        """
        tool_calls: list[ToolCall] = []
        match = self.TOOL_PATTERN.search(content)

        if not match:
            return tool_calls

        tool_json = match.group(1)
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
                                    arguments=json.dumps(tool_data.get("input", {})),
                                ),
                            )
                        )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to parse XML tool call: %s", e)

        return tool_calls

    def _extract_tool_calls_dict_from_xml(self, content: str) -> list[dict[str, Any]]:
        """Extract tool calls as dictionaries from XML content.

        Args:
            content: The content string potentially containing XML tool calls.

        Returns:
            List of tool call dictionaries.
        """
        tool_calls: list[dict[str, Any]] = []
        match = self.TOOL_PATTERN.search(content)

        if not match:
            return tool_calls

        tool_json = match.group(1)
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
                                    "name": tool_data.get("name", ""),
                                    "arguments": json.dumps(tool_data.get("input", {})),
                                },
                            }
                        )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to parse XML tool call in stream: %s", e)

        return tool_calls


__all__ = [
    "NoOpResponsePostProcessor",
    "XmlToolCallPostProcessor",
]
