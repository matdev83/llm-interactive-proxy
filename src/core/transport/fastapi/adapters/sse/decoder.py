"""SSE decoder implementation.

This module contains the SSEDecoder class for decoding Server-Sent Events (SSE)
formatted payloads into structured content.
"""

from __future__ import annotations

import json
from typing import Any


class SSEDecoder:
    """Decode SSE-formatted payloads."""

    # Security limits to prevent DoS attacks
    MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_JSON_DEPTH = 100  # Maximum nesting depth for JSON parsing
    MAX_DATA_LINES = 1000  # Maximum number of data lines to process

    def decode_payload(self, payload: bytes | str) -> tuple[Any, dict[str, Any], bool]:
        """Decode SSE payload.

        Args:
            payload: SSE-formatted payload (bytes or str)

        Returns:
            Tuple of (decoded_content, metadata_hints, is_done)
        """
        text_payload: str | None = None
        if isinstance(payload, bytes | bytearray):
            try:
                text_payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload, {}, False
        elif isinstance(payload, str):
            text_payload = payload
        else:
            return payload, {}, False

        # Security: Check payload size limit
        if len(text_payload) > self.MAX_PAYLOAD_SIZE:
            return payload, {"error": "payload_too_large"}, False

        stripped = text_payload.strip()
        if "data:" not in stripped:
            return payload, {}, False

        data_lines: list[str] = []
        for line in stripped.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

                # Security: Limit number of data lines to prevent memory exhaustion
                if len(data_lines) >= self.MAX_DATA_LINES:
                    break

        if not data_lines:
            return payload, {}, False

        forced_done = False
        if data_lines and data_lines[-1] in ("[DONE]", '["DONE"]'):
            forced_done = True
            data_lines = data_lines[:-1]

        # Nothing but a done marker
        if not data_lines:
            return "", {"finish_reason": "stop"}, True

        data_body = "\n".join(data_lines).strip()
        if data_body in ("[DONE]", '["DONE"]'):
            return "", {"finish_reason": "stop"}, True

        # Security: Check data body size
        if len(data_body) > self.MAX_PAYLOAD_SIZE:
            return data_body, {"error": "data_too_large"}, forced_done

        metadata_hint: dict[str, Any] = {}
        try:
            # Security: Use safe JSON parsing with depth limit
            decoded = self._safe_json_loads(data_body)
        except json.JSONDecodeError:
            if forced_done:
                metadata_hint["finish_reason"] = "stop"
            return data_body, metadata_hint, forced_done
        except (ValueError, RecursionError):
            # Security: Handle potential DoS attempts
            return data_body, {"error": "invalid_json_structure"}, forced_done

        # Only extract metadata from dict objects
        if isinstance(decoded, dict):
            finish_reason = decoded.get("finish_reason")
            if finish_reason:
                metadata_hint["finish_reason"] = finish_reason
            elif forced_done:
                metadata_hint["finish_reason"] = "stop"

            event_type = decoded.get("type")
            if isinstance(event_type, str):
                metadata_hint["event_type"] = event_type.strip().lower()
        elif forced_done:
            metadata_hint["finish_reason"] = "stop"

        return decoded, metadata_hint, forced_done

    def _safe_json_loads(self, data: str) -> Any:
        """Safely parse JSON with depth and size limits to prevent DoS attacks.

        Args:
            data: JSON string to parse

        Returns:
            Parsed JSON data

        Raises:
            json.JSONDecodeError: If JSON is malformed
            ValueError: If JSON exceeds depth limits
            RecursionError: If JSON has excessive nesting
        """
        # Use a simpler approach: manually check JSON depth before parsing
        if self._check_json_depth(data) > self.MAX_JSON_DEPTH:
            raise ValueError("JSON nesting depth exceeded limit")

        # Use standard JSON parser with recursion limit check
        try:
            # Temporarily reduce Python's recursion limit to prevent stack overflow
            import sys

            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(min(self.MAX_JSON_DEPTH * 2, original_limit))

            try:
                return json.loads(data)
            finally:
                # Restore original recursion limit
                sys.setrecursionlimit(original_limit)

        except RecursionError:
            raise ValueError("JSON nesting depth exceeded limit")

    def _check_json_depth(self, json_str: str) -> int:
        """Check the maximum depth of nesting in a JSON string.

        This is a simple heuristic that counts brace and bracket nesting.
        It's not perfectly accurate but provides reasonable protection.

        Args:
            json_str: JSON string to analyze

        Returns:
            Estimated maximum nesting depth
        """
        max_depth = 0
        current_depth = 0
        in_string = False
        escape_next = False

        for char in json_str:
            if escape_next:
                escape_next = False
                continue

            if char == "\\" and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if not in_string:
                if char in "{[":
                    current_depth += 1
                    max_depth = max(max_depth, current_depth)
                elif char in "}]":
                    current_depth = max(0, current_depth - 1)

        return max_depth
