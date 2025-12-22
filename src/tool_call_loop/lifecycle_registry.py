from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Any

from cachetools import TTLCache


@dataclass
class ToolCallStreamState:
    """Lifecycle tracking state for a single streaming session."""

    inflight_signatures: set[str] = field(default_factory=set)
    processed_signatures: set[str] = field(default_factory=set)


def build_tool_call_signature(tool_call: dict[str, Any]) -> str:
    """Build a stable signature for a tool call dictionary."""

    identifier = tool_call.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier

    function_block = tool_call.get("function")
    if not isinstance(function_block, dict):
        function_block = {}

    name = function_block.get("name", "unknown")
    arguments = function_block.get("arguments", "")

    if isinstance(arguments, dict | list):
        try:
            arguments_repr = json.dumps(arguments, sort_keys=True)
        except (TypeError, ValueError):
            arguments_repr = str(arguments)
    else:
        arguments_repr = str(arguments)

    digest = hashlib.sha256(
        f"{name}:{arguments_repr}".encode("utf-8", "ignore")
    ).hexdigest()
    return f"{name}:{digest}"


class ToolCallLifecycleRegistry:
    """Registry that prevents duplicate tool call processing across the pipeline."""

    def __init__(self, max_streams: int = 1024) -> None:
        self._lock = threading.Lock()
        self._max_streams = max_streams
        self._states: dict[str, ToolCallStreamState] = TTLCache(
            maxsize=max_streams, ttl=3600
        )

    def register_detection(self, stream_key: str, signature: str) -> bool:
        """
        Record that a tool call with the given signature was observed.

        Returns True only for the first concurrent observation. Duplicate detections
        while a signature is in-flight return False so callers can skip duplicates.
        """

        if not stream_key:
            stream_key = "anonymous-stream"

        with self._lock:
            state = self._get_state(stream_key)
            if signature in state.inflight_signatures:
                return False
            state.inflight_signatures.add(signature)
            return True

    def mark_processed(self, stream_key: str, signature: str) -> None:
        """Mark a tool call signature as fully processed by the reactor."""

        if not stream_key:
            stream_key = "anonymous-stream"

        with self._lock:
            state = self._states.get(stream_key)
            if state is None:
                return
            state.inflight_signatures.discard(signature)
            state.processed_signatures.add(signature)

    def is_processed(self, stream_key: str, signature: str) -> bool:
        """Return True if the signature has already completed processing."""

        if not stream_key:
            stream_key = "anonymous-stream"

        with self._lock:
            state = self._states.get(stream_key)
            if state is None:
                return False
            return signature in state.processed_signatures

    def clear_stream(self, stream_key: str) -> None:
        """Forget lifecycle state for a completed stream."""

        if not stream_key:
            stream_key = "anonymous-stream"

        with self._lock:
            self._states.pop(stream_key, None)

    def _get_state(self, stream_key: str) -> ToolCallStreamState:
        state = self._states.get(stream_key)
        if state is None:
            state = ToolCallStreamState()
            self._states[stream_key] = state
        return state
