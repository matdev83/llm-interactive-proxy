"""
Non-forwardable message identity service implementation.

Computes deterministic SHA-256-based identities for ChatMessage instances.
Identities are stable across message content rewrites and do not depend
on client-provided metadata.

Requirements: 1.2, 1.9, 1.10, 1.12, 1.13, 5.2, 9.1
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from src.core.domain.chat import ChatMessage, MessageContentPart
from src.core.domain.non_forwardable import MessageIdentity
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
)

# Context variable for request-local identity cache
# Cache key: JSON-serialized normalized identity input dict
# Cache value: Computed MessageIdentity (SHA-256 hex string)
_identity_cache: contextvars.ContextVar[dict[str, MessageIdentity]] = (
    contextvars.ContextVar("identity_cache", default={})
)


class NonForwardableMessageIdentityService(INonForwardableMessageIdentityService):
    """Service for computing deterministic message identities.

    Computes stable, deterministic identities for messages that can be used
    to recognize the same message when it appears in client-submitted history.
    Identity computation does not rely on client-provided metadata or
    transport-specific fields.
    """

    def compute_identity(self, message: ChatMessage) -> MessageIdentity:
        """Compute deterministic identity for a message.

        The identity is stable for equivalent messages within the session
        and does not depend on client metadata or transport-specific fields.

        Uses request-local caching to avoid redundant hash computations for
        the same message within a single async request/workflow context.

        Args:
            message: The message to compute identity for (must be validated domain ChatMessage).

        Returns:
            Deterministic identity string (SHA-256 hex digest, lowercase).

        Preconditions:
            - message is a validated domain ChatMessage
        Postconditions:
            - returned identity is stable for equivalent messages within the session
            - identity does not include client metadata or transport-specific fields
        """
        identity_input = self._build_identity_input(message)

        # Check request-local cache first
        cache = _identity_cache.get({})
        cache_key = self._get_cache_key(identity_input)

        if cache_key in cache:
            return cache[cache_key]

        # Compute hash and store in cache
        identity = self._compute_hash(identity_input)
        cache[cache_key] = identity
        _identity_cache.set(cache)

        return identity

    def _build_identity_input(self, message: ChatMessage) -> dict[str, Any]:
        """Build the identity input dictionary from message attributes.

        For tool result messages (role="tool" and tool_call_id set), excludes
        content to ensure stability across content rewrites.
        For all other messages, includes all canonical attributes except metadata.

        Args:
            message: The message to build identity input for.

        Returns:
            Dictionary containing only the attributes that contribute to identity.
        """
        # Check if this is a tool result message
        is_tool_result = message.role == "tool" and message.tool_call_id is not None

        identity_input: dict[str, Any] = {
            "role": message.role,
        }

        if is_tool_result:
            # Tool result: exclude content, include tool_call_id and name
            identity_input["tool_call_id"] = message.tool_call_id
            if message.name is not None:
                identity_input["name"] = self._normalize_text(message.name)
        else:
            # Regular message: include all canonical attributes except metadata
            if message.content is not None:
                identity_input["content"] = self._normalize_content(message.content)
            if message.reasoning_content is not None:
                identity_input["reasoning_content"] = self._normalize_text(
                    message.reasoning_content
                )
            if message.name is not None:
                identity_input["name"] = self._normalize_text(message.name)
            if message.tool_calls is not None:
                identity_input["tool_calls"] = self._normalize_tool_calls(
                    message.tool_calls
                )
            if message.tool_call_id is not None:
                identity_input["tool_call_id"] = message.tool_call_id

        return identity_input

    def _normalize_content(
        self, content: str | Sequence[MessageContentPart] | None
    ) -> str | list[dict[str, Any]] | None:
        """Normalize message content for identity computation.

        For string content, normalizes line endings.
        For sequence content, preserves part order and normalizes each part.

        Args:
            content: The content to normalize.

        Returns:
            Normalized content representation.
        """
        if content is None:
            return None

        if isinstance(content, str):
            return self._normalize_text(content)

        # Sequence content: preserve part order, normalize each part
        normalized_parts: list[dict[str, Any]] = []
        for part in content:
            # Serialize part to dict (preserving all fields)
            if hasattr(part, "model_dump"):
                part_dict = part.model_dump()
            elif isinstance(part, dict):
                part_dict = part.copy()
            else:
                # Fallback: convert to dict
                if hasattr(part, "__dict__"):
                    part_dict = vars(part)
                else:
                    part_dict = {"value": str(part)}

            # Exclude transport-specific fields (per design.md line 272)
            # cache_control is a transport/protocol wrapper field
            part_dict.pop("cache_control", None)

            # Normalize text fields in the part
            normalized_part = self._normalize_dict_text_fields(part_dict)
            normalized_parts.append(normalized_part)

        return normalized_parts

    def _normalize_dict_text_fields(self, d: dict[str, Any]) -> dict[str, Any]:
        """Recursively normalize text fields in a dictionary.

        Args:
            d: Dictionary to normalize.

        Returns:
            Dictionary with normalized text fields.
        """
        normalized: dict[str, Any] = {}
        for key, value in d.items():
            if isinstance(value, str):
                normalized[key] = self._normalize_text(value)
            elif isinstance(value, dict):
                normalized[key] = self._normalize_dict_text_fields(value)
            elif isinstance(value, list):
                normalized[key] = [
                    (
                        self._normalize_dict_text_fields(item)
                        if isinstance(item, dict)
                        else (
                            self._normalize_text(item)
                            if isinstance(item, str)
                            else item
                        )
                    )
                    for item in value
                ]
            else:
                normalized[key] = value
        return normalized

    def _normalize_text(self, text: str) -> str:
        """Normalize text for hashing (line endings only).

        Converts CRLF and CR to LF. Does not trim whitespace.

        Args:
            text: Text to normalize.

        Returns:
            Normalized text.
        """
        # Normalize line endings: CRLF and CR -> LF
        # Do not trim whitespace
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _normalize_tool_calls(self, tool_calls: list[Any]) -> list[dict[str, Any]]:
        """Normalize tool calls for identity computation.

        Includes all fields: id, type, function.name, function.arguments,
        and any provider-specific extra fields.

        Args:
            tool_calls: List of tool calls to normalize.

        Returns:
            List of normalized tool call dictionaries.
        """
        normalized: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            if hasattr(tool_call, "model_dump"):
                tool_call_dict = tool_call.model_dump()
            elif isinstance(tool_call, dict):
                tool_call_dict = tool_call.copy()
            else:
                # Fallback: convert to dict
                if hasattr(tool_call, "__dict__"):
                    tool_call_dict = vars(tool_call)
                else:
                    tool_call_dict = {"value": str(tool_call)}

            # Normalize text fields (especially function.arguments)
            normalized_tool_call = self._normalize_dict_text_fields(tool_call_dict)
            normalized.append(normalized_tool_call)

        return normalized

    def _get_cache_key(self, identity_input: dict[str, Any]) -> str:
        """Get cache key from identity input.

        Serializes the identity input to JSON string for use as cache key.
        This is deterministic and unique per message.

        Args:
            identity_input: Dictionary containing identity attributes.

        Returns:
            JSON-serialized string representation of identity input.
        """
        return json.dumps(
            identity_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def _compute_hash(self, identity_input: dict[str, Any]) -> MessageIdentity:
        """Compute SHA-256 hash of identity input.

        Serializes to JSON with deterministic key ordering and no insignificant
        whitespace, then computes SHA-256 hash.

        Args:
            identity_input: Dictionary containing identity attributes.

        Returns:
            Lowercase hexadecimal SHA-256 hash string (64 characters).
        """
        # Serialize to JSON with deterministic key ordering and no insignificant whitespace
        json_bytes = self._get_cache_key(identity_input).encode("utf-8")

        # Compute SHA-256 hash
        hash_obj = hashlib.sha256(json_bytes)

        # Return lowercase hex string
        return hash_obj.hexdigest()
