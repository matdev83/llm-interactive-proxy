"""SSE decoder implementation.

This module contains the SSEDecoder class for decoding Server-Sent Events (SSE)
formatted payloads into structured content.
"""

from __future__ import annotations

import json
from typing import Any


class SSEDecoder:
    """Decode SSE-formatted payloads."""

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

        stripped = text_payload.strip()
        if "data:" not in stripped:
            return payload, {}, False

        data_lines: list[str] = []
        for line in stripped.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

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

        metadata_hint: dict[str, Any] = {}
        try:
            decoded = json.loads(data_body)
        except json.JSONDecodeError:
            if forced_done:
                metadata_hint["finish_reason"] = "stop"
            return data_body, metadata_hint, forced_done

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
