from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any

from cachetools import TTLCache
from pydantic import BaseModel


@dataclass
class ToolCallStreamState:
    """Lifecycle tracking state for a single streaming session."""

    inflight_signatures: set[str] = field(default_factory=set)
    processed_signatures: set[str] = field(default_factory=set)


class ToolCallFunctionBlock(BaseModel):
    """Function block within a tool call (OpenAI format)."""

    name: str = "unknown"
    arguments: str | dict[Any, Any] | list[Any] = ""


class ToolCallDict(BaseModel):
    """Tool call dictionary structure (OpenAI format)."""

    id: str | None = None
    function: ToolCallFunctionBlock


def build_tool_call_signature(tool_call: ToolCallDict | dict[str, Any]) -> str:
    """Build a stable signature for a tool call dictionary."""

    if isinstance(tool_call, ToolCallDict):
        model_obj = tool_call
        if model_obj.id:
            return model_obj.id

        name = model_obj.function.name
        arguments = model_obj.function.arguments
        # Check for index in extra fields (not explicitly in ToolCallDict but might be in model_dump)
        index = getattr(model_obj, "index", None)
    else:
        identifier = tool_call.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier

        function_block = tool_call.get("function")
        if not isinstance(function_block, dict):
            function_block = {}

        name = function_block.get("name", "unknown")
        arguments = function_block.get("arguments", "")
        index = tool_call.get("index")

    # If we have an index but no ID, we can use a stable signature based on the index.
    # This prevents the signature from changing during streaming as arguments grow.
    # We include the name to ensure that we don't collision if the model changes
    # its mind about the tool name at the same index (rare but possible).
    if index is not None and name:
        return f"idx:{index}:{name}"

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


def build_reactor_processing_signature(
    tool_call: ToolCallDict | dict[str, Any], *, is_streaming: bool
) -> str:
    """Stable signature for tool-call reactor dedupe and lifecycle marking.

    In streaming mode, OpenAI-style deltas often include ``index`` and ``function.name``
    before ``id`` appears. Using ``id`` as soon as it arrives would change the
    signature mid-stream (e.g. ``idx:0:bash`` vs ``call_abc``), causing the reactor
    to run more than once for the same logical tool call.

    When streaming and both ``index`` and ``function.name`` are present, prefer
    ``idx:{index}:{name}`` so signatures stay stable across argument deltas and
    late-arriving ``id`` fields. Otherwise fall back to ``id`` (when set) or
    :func:`build_tool_call_signature`.
    """

    if isinstance(tool_call, ToolCallDict):
        data = tool_call.model_dump()
    else:
        data = dict(tool_call)

    function_block = data.get("function")
    if not isinstance(function_block, dict):
        function_block = {}
    name = function_block.get("name")

    if is_streaming and isinstance(name, str) and name:
        idx_val = data.get("index")
        if idx_val is not None:
            try:
                idx_int = int(idx_val)
            except (TypeError, ValueError):
                idx_int = idx_val
            return f"idx:{idx_int}:{name}"

    identifier = data.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier

    return build_tool_call_signature(data)


class ToolCallLifecycleRegistry:
    """Registry that prevents duplicate tool call processing across the pipeline."""

    def __init__(self, max_streams: int = 1024) -> None:
        self._lock = asyncio.Lock()
        self._max_streams = max_streams
        self._states: MutableMapping[str, ToolCallStreamState] = TTLCache(
            maxsize=max_streams, ttl=3600
        )

    async def register_detection(self, stream_key: str, signature: str) -> bool:
        """
        Record that a tool call with the given signature was observed.

        Returns True only for the first concurrent observation. Duplicate detections
        while a signature is in-flight return False so callers can skip duplicates.
        """

        if not stream_key:
            stream_key = "anonymous-stream"

        async with self._lock:
            state = await self._get_state(stream_key)
            if (
                signature in state.inflight_signatures
                or signature in state.processed_signatures
            ):
                return False
            state.inflight_signatures.add(signature)
            return True

    async def mark_processed(self, stream_key: str, signature: str) -> None:
        """Mark a tool call signature as fully processed by the reactor."""

        if not stream_key:
            stream_key = "anonymous-stream"

        async with self._lock:
            state = self._states.get(stream_key)
            if state is None:
                return
            state.inflight_signatures.discard(signature)
            state.processed_signatures.add(signature)

    async def is_processed(self, stream_key: str, signature: str) -> bool:
        """Return True if the signature has already completed processing."""

        if not stream_key:
            stream_key = "anonymous-stream"

        async with self._lock:
            state = self._states.get(stream_key)
            if state is None:
                return False
            return signature in state.processed_signatures

    async def clear_stream(self, stream_key: str) -> None:
        """Forget lifecycle state for a completed stream."""

        if not stream_key:
            stream_key = "anonymous-stream"

        async with self._lock:
            self._states.pop(stream_key, None)

    async def _get_state(self, stream_key: str) -> ToolCallStreamState:
        state = self._states.get(stream_key)
        if state is None:
            state = ToolCallStreamState()
            self._states[stream_key] = state
        return state
