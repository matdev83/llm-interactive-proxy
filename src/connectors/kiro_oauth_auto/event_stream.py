"""AWS Event Stream decoder for Kiro streaming responses."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AwsEventStreamMessage:
    event_type: str
    payload: bytes

    def json(self) -> dict:
        text = self.payload.decode("utf-8", errors="replace")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"_": parsed}


class AwsEventStreamDecoder:
    """Incremental decoder for AWS Event Stream frames.

    We do not validate CRCs (the upstream https connection already provides integrity).
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[AwsEventStreamMessage]:
        if data:
            self._buffer.extend(data)
        messages: list[AwsEventStreamMessage] = []

        while len(self._buffer) >= 16:
            total_length = int.from_bytes(self._buffer[0:4], "big", signed=False)
            if total_length < 16:
                # Corrupt stream; drop buffer to avoid infinite loop
                self._buffer.clear()
                break
            if len(self._buffer) < total_length:
                break

            headers_length = int.from_bytes(self._buffer[4:8], "big", signed=False)
            headers_start = 12
            headers_end = headers_start + headers_length
            payload_start = headers_end
            payload_end = total_length - 4  # strip message CRC

            headers = bytes(self._buffer[headers_start:headers_end])
            payload = (
                bytes(self._buffer[payload_start:payload_end])
                if payload_start < payload_end
                else b""
            )

            event_type = _extract_event_type(headers)
            if event_type:
                messages.append(
                    AwsEventStreamMessage(event_type=event_type, payload=payload)
                )

            del self._buffer[:total_length]

        return messages


def _extract_event_type(headers: bytes) -> str:
    """Extract ':event-type' string header."""
    offset = 0
    while offset < len(headers):
        name_len = headers[offset]
        offset += 1
        if offset + name_len > len(headers):
            break
        name = headers[offset : offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        if offset >= len(headers):
            break
        value_type = headers[offset]
        offset += 1

        # 7 = string; 6 = byte array; other types are fixed-size per AWS spec
        if value_type == 7:
            if offset + 2 > len(headers):
                break
            value_len = (headers[offset] << 8) | headers[offset + 1]
            offset += 2
            if offset + value_len > len(headers):
                break
            value = headers[offset : offset + value_len].decode(
                "utf-8", errors="replace"
            )
            offset += value_len
            if name == ":event-type":
                return value
            continue

        if value_type == 6:
            if offset + 2 > len(headers):
                break
            length = (headers[offset] << 8) | headers[offset + 1]
            offset += 2 + length
            continue

        skip_sizes = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4, 5: 8, 8: 8, 9: 16}
        size = skip_sizes.get(value_type)
        if size is None:
            break
        offset += size
    return ""
