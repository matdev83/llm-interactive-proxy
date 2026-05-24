"""Reasoning metadata injection for response adapters."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

logger = logging.getLogger(__name__)


class ReasoningInjector:
    """Inject reasoning metadata into OpenAI-style payloads.

    Handles injection of reasoning_content and reasoning fields into
    both streaming (delta) and non-streaming (message) payload formats.
    """

    def inject_reasoning(
        self,
        content: Any,
        metadata: dict[str, Any],
        *,
        streaming: bool | None = None,
    ) -> Any:
        """Inject reasoning fields into content.

        Args:
            content: Content to inject into
            metadata: Metadata containing reasoning fields
            streaming: Optional streaming flag. If None, inferred from content.

        Returns:
            Content with reasoning injected
        """
        normalized_content = self._normalize_content(content)

        if not metadata:
            return normalized_content

        # Some strict OpenAI clients crash/disconnect when non-standard delta fields
        # (reasoning_content/thinking/etc.) are present. When the streaming pipeline
        # marks a response as strict, skip injecting reasoning entirely.
        if metadata.get("_suppress_reasoning_fields"):
            return normalized_content

        # Infer streaming mode if not provided
        if streaming is None:
            streaming = self._infer_streaming_mode(normalized_content)

        reasoning_text = metadata.get("reasoning_content") or metadata.get("reasoning")

        if isinstance(normalized_content, dict):
            if self._assign_reasoning(
                normalized_content, metadata, streaming=streaming
            ):
                return normalized_content

            # If we couldn't place reasoning inside choices, surface it via metadata.
            # IMPORTANT: for OpenAI-style streaming responses, adding a top-level
            # `metadata` field breaks strict OpenAI client schemas.
            if reasoning_text and not streaming:
                metadata_block = normalized_content.get("metadata")
                reasoning_payload = {
                    "reasoning_content": reasoning_text,
                    "reasoning": metadata.get("reasoning", reasoning_text),
                }
                if isinstance(metadata_block, dict):
                    metadata_block.setdefault(
                        "reasoning_content", reasoning_payload["reasoning_content"]
                    )
                    metadata_block.setdefault(
                        "reasoning", reasoning_payload["reasoning"]
                    )
                else:
                    normalized_content["metadata"] = reasoning_payload
            return normalized_content

        if reasoning_text:
            return self._build_streaming_payload(
                normalized_content, metadata, reasoning_text, streaming=streaming
            )

        if streaming and isinstance(normalized_content, str):
            return self._build_streaming_payload(
                normalized_content, metadata, None, streaming=streaming
            )

        # For non-streaming responses with tool_calls in metadata but simple content,
        # we need to build an OpenAI-style payload to include the tool_calls
        tool_calls = metadata.get("tool_calls")
        if not streaming and isinstance(tool_calls, list) and tool_calls:
            return self._build_streaming_payload(
                normalized_content, metadata, None, streaming=False
            )

        return normalized_content

    def build_streaming_payload(
        self,
        content: Any,
        metadata: dict[str, Any],
        *,
        streaming: bool = True,
    ) -> dict[str, Any]:
        """Build OpenAI-style payload when content is not dict.

        Args:
            content: Non-dict content
            metadata: Metadata to include in payload
            streaming: Whether this is a streaming payload

        Returns:
            OpenAI-style dict payload
        """
        reasoning_text = metadata.get("reasoning_content") or metadata.get("reasoning")
        return self._build_streaming_payload(
            content, metadata, reasoning_text, streaming=streaming
        )

    def _normalize_content(self, content: Any) -> Any:
        """Normalize content into JSON-serializable structures when possible."""
        # Preserve StopChunkWithUsage - it's a dict subclass that must not be converted
        # to a plain dict, otherwise its stringification protection is lost
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        if isinstance(content, StopChunkWithUsage):
            return content
        if hasattr(content, "model_dump"):
            try:
                return content.model_dump()
            except (TypeError, ValueError, AttributeError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to model_dump content; falling back to dict",
                        exc_info=True,
                    )
                return dict(content)
        if is_dataclass(content) and not isinstance(content, type):
            return asdict(content)
        return content

    def _infer_streaming_mode(self, content: Any) -> bool:
        """Infer streaming mode from content structure.

        Args:
            content: Content to inspect

        Returns:
            True if content appears to be streaming format
        """
        if isinstance(content, dict):
            choices = content.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    # Check if delta exists (streaming) or message exists (non-streaming)
                    if "delta" in first_choice:
                        return True
                    if "message" in first_choice:
                        return False
        return False

    def _assign_reasoning(
        self,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        *,
        streaming: bool,
    ) -> bool:
        """Insert reasoning metadata into an OpenAI-style payload.

        Args:
            payload: Payload dictionary
            metadata: Metadata containing reasoning fields
            streaming: Whether this is a streaming payload

        Returns:
            True when reasoning was injected into at least one choice
        """
        reasoning_text = metadata.get("reasoning_content") or metadata.get("reasoning")
        if not reasoning_text:
            return False

        choices = payload.get("choices")
        if not isinstance(choices, list):
            return False

        assigned = False
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            target_key = "delta" if (streaming or "delta" in choice) else "message"
            target = choice.get(target_key)
            if not isinstance(target, dict):
                target = {}
                choice[target_key] = target

            if target.get("reasoning_content"):
                # Reasoning already present: treat as successfully assigned so we
                # don't fall back to non-standard top-level `metadata` injection.
                assigned = True
                continue

            if streaming:
                target.setdefault("role", metadata.get("role", "assistant"))
            elif metadata.get("role") and "role" not in target:
                target["role"] = metadata["role"]

            target["reasoning_content"] = reasoning_text
            target.setdefault("reasoning", metadata.get("reasoning", reasoning_text))
            assigned = True

        return assigned

    def _build_streaming_payload(
        self,
        content: Any,
        metadata: dict[str, Any],
        reasoning_text: str | None,
        *,
        streaming: bool,
    ) -> dict[str, Any]:
        """Create an OpenAI-style payload when we can't inject into existing content.

        Args:
            content: Content to wrap
            metadata: Metadata to include
            reasoning_text: Optional reasoning text
            streaming: Whether this is a streaming payload

        Returns:
            OpenAI-style payload dictionary
        """
        chunk_id = metadata.get("id")
        if not isinstance(chunk_id, str) or not chunk_id:
            chunk_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"

        created_raw = metadata.get("created")
        if isinstance(created_raw, int):
            created = created_raw
        elif isinstance(created_raw, float) and created_raw.is_integer():
            created = int(created_raw)
        elif isinstance(created_raw, str) and created_raw.strip():
            try:
                created = int(created_raw)
            except (TypeError, ValueError):
                created = int(time.time())
        else:
            created = int(time.time())

        model_name = metadata.get("model") or "unknown"
        object_type = metadata.get("object")
        if not isinstance(object_type, str):
            object_type = "chat.completion.chunk" if streaming else "chat.completion"

        choice_payload: dict[str, Any] = {
            "index": metadata.get("index", 0),
            "finish_reason": metadata.get("finish_reason"),
        }

        target_key = "delta" if streaming else "message"
        target_payload: dict[str, Any] = {
            "role": metadata.get("role", "assistant"),
        }

        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            target_payload["tool_calls"] = tool_calls

        if reasoning_text:
            target_payload["reasoning_content"] = reasoning_text
            target_payload["reasoning"] = metadata.get("reasoning", reasoning_text)

        if isinstance(content, dict):
            target_payload.update(content)
        elif isinstance(content, str) and content:
            # Preserve whitespace-only content (spaces, newlines) - don't use .strip()
            if streaming:
                target_payload["content"] = content
            else:
                target_payload.setdefault("content", content)
        elif content not in (None, ""):
            # For non-string content, convert and preserve as-is
            rendered = str(content)
            if rendered:
                target_payload.setdefault("content", rendered)

        choice_payload[target_key] = target_payload

        return {
            "id": chunk_id,
            "object": object_type,
            "created": created,
            "model": model_name,
            "choices": [choice_payload],
        }
