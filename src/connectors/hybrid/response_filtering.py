"""Response filtering and augmentation utilities for the hybrid connector."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from copy import deepcopy
from typing import Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class HybridResponseFilteringMixin:
    """Helpers for filtering reasoning output in responses."""

    def _strip_reasoning_tags(self, content: str) -> str:
        """Strip reasoning tags from content."""

        reasoning_patterns = [
            r"<thinking>.*?</thinking>",
            r"<think>.*?</think>",
            r"<reasoning>.*?</reasoning>",
            r"<reason>.*?</reason>",
        ]

        cleaned_content = content
        for pattern in reasoning_patterns:
            cleaned_content = re.sub(
                pattern, "", cleaned_content, flags=re.DOTALL | re.IGNORECASE
            )

        instruction_pattern = (
            r"Consider this reasoning when formulating your response:\s*"
        )
        cleaned_content = re.sub(
            instruction_pattern, "", cleaned_content, flags=re.IGNORECASE
        )

        return cleaned_content

    def _filter_response_content(self, content: Any) -> Any:
        """Filter reasoning tags from response content."""

        if isinstance(content, bytes):
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:  # pragma: no cover - defensive
                return content
        elif isinstance(content, str):
            content_str = content
        elif isinstance(content, dict):
            return self._filter_json_content(content)
        elif isinstance(content, list):
            return [self._filter_response_content(item) for item in content]
        else:
            return content

        if content_str.startswith("data: "):
            data_part = content_str[6:].strip()
            if data_part == "[DONE]":
                return content

            try:
                data = json.loads(data_part)
                cleaned = self._filter_json_content(data)
                filtered_data = json.dumps(cleaned, ensure_ascii=False)
                if isinstance(content, bytes):
                    return f"data: {filtered_data}\n\n".encode()
                return f"data: {filtered_data}\n\n"
            except json.JSONDecodeError:
                filtered_str = self._strip_reasoning_tags(content_str)
                if isinstance(content, bytes):
                    return filtered_str.encode("utf-8")
                return filtered_str

        filtered_str = self._strip_reasoning_tags(content_str)
        if isinstance(content, bytes):
            return filtered_str.encode("utf-8")
        return filtered_str

    def _filter_json_content(self, data: Any) -> Any:
        """Recursively remove reasoning content from JSON-like structures."""

        if isinstance(data, dict):
            filtered: dict[str, Any] = {}
            for key, value in data.items():
                if key == "reasoning_content":
                    continue
                filtered[key] = self._filter_json_content(value)
            return filtered

        if isinstance(data, list):
            return [self._filter_json_content(item) for item in data]

        if isinstance(data, str):
            return self._strip_reasoning_tags(data)

        return data

    async def _filter_response_stream(
        self, response: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Filter reasoning tags from streaming response."""

        async def filtered_stream():
            if response.content is None:
                return

            async for chunk in response.content:
                filtered_content = self._filter_response_content(chunk.content)
                filtered_chunk = ProcessedResponse(
                    content=filtered_content,
                    usage=chunk.usage,
                    metadata=chunk.metadata,
                )
                yield filtered_chunk

        return StreamingResponseEnvelope(
            content=filtered_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )

    def _format_reasoning_for_client(
        self, reasoning_output: str, reasoning_backend: str
    ) -> str:
        """Prepare reasoning text for client consumption with native tags."""

        if not reasoning_output:
            return ""

        _, plain_text = self._prepare_reasoning_texts(
            reasoning_output, reasoning_backend
        )
        return plain_text

    def _build_reasoning_stream_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> ProcessedResponse | None:
        """Create a processed response chunk that surfaces reasoning to clients."""

        formatted = (
            formatted_reasoning.strip()
            if formatted_reasoning
            and "<" in formatted_reasoning
            and ">" in formatted_reasoning
            else ""
        )
        if not formatted:
            formatted, plain_reasoning = self._prepare_reasoning_texts(
                reasoning_output, reasoning_backend
            )
        else:
            plain_reasoning = self._extract_reasoning_inner_text(formatted)

        if formatted_reasoning and formatted_reasoning.strip() and not formatted:
            plain_reasoning = formatted_reasoning.strip()
            formatted, _ = self._prepare_reasoning_texts(
                reasoning_output, reasoning_backend
            )
            if not formatted:
                formatted = formatted_reasoning.strip()

        if not plain_reasoning:
            return None

        delta_payload: dict[str, Any] = {
            "role": "assistant",
            "reasoning": formatted,
            "reasoning_content": plain_reasoning,
            "content": "",
        }

        payload = {
            "id": f"hybrid-reasoning-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"{reasoning_backend}:{reasoning_model}",
            "choices": [
                {
                    "index": 0,
                    "delta": delta_payload,
                    "finish_reason": None,
                }
            ],
        }

        sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return ProcessedResponse(
            content=sse_payload,
            usage=None,
            metadata={
                "hybrid_phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
            },
        )

    def _build_tool_call_only_response(
        self,
        tool_calls: list[dict[str, Any]],
        request_dict: dict[str, Any],
        reasoning_backend: str,
        reasoning_model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Construct a response that forwards tool calls without execution."""

        stream_requested = bool(request_dict.get("stream", False))
        created_ts = int(time.time())
        model_name = f"{reasoning_backend}:{reasoning_model}"

        if stream_requested:
            payload = {
                "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            done_payload = "data: [DONE]\n\n"

            async def tool_call_stream():
                yield ProcessedResponse(
                    content=sse_payload,
                    metadata={
                        "hybrid_phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "skipped_execution": True,
                    },
                )
                yield ProcessedResponse(
                    content=done_payload,
                    metadata={"is_done": True},
                )

            return StreamingResponseEnvelope(
                content=tool_call_stream(),
                media_type="text/event-stream",
            )

        response_content = {
            "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        return ResponseEnvelope(
            content=response_content,
            metadata={
                "hybrid_phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
                "skipped_execution": True,
            },
        )

    def _prepend_reasoning_chunk_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> StreamingResponseEnvelope:
        """Inject the reasoning chunk ahead of the execution stream."""

        reasoning_chunk = self._build_reasoning_stream_chunk(
            reasoning_output,
            reasoning_backend,
            reasoning_model,
            formatted_reasoning=formatted_reasoning,
        )
        if reasoning_chunk is None:
            return response

        original_stream = response.content

        async def combined_stream():
            yield reasoning_chunk
            if original_stream is None:
                return
            async for chunk in original_stream:
                yield chunk

        return StreamingResponseEnvelope(
            content=combined_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )

    def _prepend_reasoning_to_non_streaming_content(
        self,
        content: Any,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
        formatted_reasoning: str | None = None,
    ) -> Any:
        """Attach reasoning output to non-streaming responses."""

        tagged, plain = self._prepare_reasoning_texts(
            reasoning_output, reasoning_backend
        )
        if formatted_reasoning:
            candidate = formatted_reasoning.strip()
            if "<" in candidate and ">" in candidate:
                tagged = candidate
                plain = self._extract_reasoning_inner_text(candidate) or plain
            elif candidate:
                plain = candidate
        if not plain or not tagged:
            return content

        if isinstance(content, bytes):
            return content

        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            updated = deepcopy(content)
            choices = updated.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue

                    message = choice.get("message")
                    if isinstance(message, dict):
                        if "role" not in message:
                            message["role"] = "assistant"
                        message["reasoning"] = tagged
                        message["reasoning_content"] = plain
                        continue

                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        if "role" not in delta:
                            delta["role"] = "assistant"
                        delta["reasoning"] = tagged
                        delta["reasoning_content"] = plain
            else:
                metadata = updated.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["reasoning"] = tagged
                    metadata["reasoning_content"] = plain
                    metadata.setdefault("reasoning_format", "hybrid_injected")
            return updated

        return content
